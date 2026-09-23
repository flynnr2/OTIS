from __future__ import annotations

import json
import os
import pty
import select
import threading
import time
from pathlib import Path

import pytest

from host.otis_tools.instrument_recorder import (
    InstrumentRecorder, RecorderConfig, passive_serial_open, request, socket_path,
    verify_recording,
)
from host.otis_tools.firmware_host_contract import ACTIVE_STATUS_KEYS


def _sts(key: str, value: str, sequence: int) -> bytes:
    return f"STS,1,{sequence},1000000,rp2040_monotonic_us32,adaptive_hybrid,{key},{value},INFO,0\n".encode()


def _snapshot(session: int = 42, generation: int = 1, command_sequence: int = 0) -> bytes:
    values = {key: "0" for key in ACTIVE_STATUS_KEYS}
    values.update(session_id=str(session), capture_session="1",
                  mode="AUTO_DISCIPLINE", requested_mode="AUTO_DISCIPLINE",
                  state="ACQUIRING_OR_TRACKING", reason="acquiring", fault="none",
                  applied_code="43085", confirmed_applied_code_known="true",
                  dac_epoch="1", command_sequence=str(command_sequence),
                  command_completed=str(command_sequence), instrument_ticks_domain="rp2040_timer_us64")
    pairs = [("snapshot_generation_begin", str(generation)),
             ("snapshot_contract", "OTIS_INSTRUMENT_STATUS_V2")]
    pairs.extend((key, values[key]) for key in ACTIVE_STATUS_KEYS)
    pairs.append(("snapshot_generation_complete", str(generation)))
    return b"".join(_sts(key, value, i + 1) for i, (key, value) in enumerate(pairs))


class _PtyPort:
    def __init__(self, device: str, baud: int) -> None:
        del baud
        self.fd = os.open(device, os.O_RDWR | os.O_NOCTTY | os.O_NONBLOCK)
        import termios
        attrs = termios.tcgetattr(self.fd)
        attrs[0] = attrs[1] = attrs[3] = 0
        attrs[2] |= termios.CLOCAL | termios.CREAD
        termios.tcsetattr(self.fd, termios.TCSANOW, attrs)

    def read(self, size: int) -> bytes:
        if not select.select([self.fd], [], [], 0.03)[0]:
            return b""
        try:
            return os.read(self.fd, size)
        except BlockingIOError:
            return b""

    def write(self, data: bytes) -> int:
        return os.write(self.fd, data)

    def close(self) -> None:
        os.close(self.fd)


def _start_recorder(tmp_path: Path, *, duration: float = 0.8, rotate_bytes: int = 4096):
    master, slave = pty.openpty()
    device = os.ttyname(slave)
    os.close(slave)
    recorder = InstrumentRecorder(
        RecorderConfig(device=device, run_dir=tmp_path, duration_s=duration,
                       rotate_bytes=rotate_bytes, status_interval_s=0.05),
        serial_factory=_PtyPort,
    )
    outcome: dict = {}

    def run() -> None:
        try:
            outcome["result"] = recorder.run()
        except BaseException as exc:
            outcome["error"] = exc

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    until = time.monotonic() + 2
    while not socket_path(tmp_path).exists() or not recorder.running:
        assert time.monotonic() < until, outcome
        time.sleep(0.005)
    return master, recorder, thread, outcome


def test_attach_record_mode_and_duration_leave_instrument_alone(tmp_path: Path) -> None:
    master, recorder, thread, outcome = _start_recorder(tmp_path, rotate_bytes=256)
    try:
        evidence = b"REF,unfamiliar,new,record\n" + _snapshot()
        os.write(master, evidence)
        until = time.monotonic() + 2
        while recorder.instrument is None:
            assert time.monotonic() < until
            time.sleep(0.005)
        stale = request(tmp_path, {"operation": "mode", "expected_session": 41,
                                   "mode": 1, "code": 0, "dwell_s": 0})
        assert "error" in stale
        result = request(tmp_path, {"operation": "mode", "expected_session": 42,
                                    "mode": 1, "code": 0, "dwell_s": 0})
        assert result["submission"] == "written_unconfirmed"
        assert result["sequence"] == 1
        assert select.select([master], [], [], 1)[0]
        assert os.read(master, 512) == b"ACTIVE MODE 42 1 1 0 0\n"
        receipt = b"ICM,2,1,42,1,1,0,0,ACCEPTED,1,1000000,rp2040_timer_us64\n"
        followup = _snapshot(generation=2, command_sequence=1)
        os.write(master, receipt + followup)
        evidence += receipt + followup
        until = time.monotonic() + 1
        while recorder.pending_command is not None or recorder.completed_generation != 2:
            assert time.monotonic() < until
            time.sleep(0.005)
        assert recorder.last_receipt["result"] == "ACCEPTED"
        timed = request(tmp_path, {"operation": "mode", "expected_session": 42,
                                   "mode": 0, "code": 0, "dwell_s": 3600})
        assert timed["sequence"] == 2
        assert select.select([master], [], [], 1)[0]
        assert os.read(master, 512) == b"ACTIVE MODE 42 2 0 0 3600\n"
        thread.join(2)
        assert not thread.is_alive() and "error" not in outcome
        manifest = json.loads((tmp_path / "recording_manifest.json").read_text())
        retained = b"".join((tmp_path / item["path"]).read_bytes() for item in manifest["segments"])
        assert retained == evidence
        assert manifest["bytes_recorded"] == len(evidence)
        assert len(manifest["segments"]) > 1
        assert not socket_path(tmp_path).exists()
        assert verify_recording(tmp_path)["status"] == "verified"
        first = tmp_path / manifest["segments"][0]["path"]
        first.write_bytes(first.read_bytes() + b"tampered")
        with pytest.raises(ValueError, match="identity mismatch"):
            verify_recording(tmp_path)
    finally:
        os.close(master)


def test_status_requires_complete_generation_and_fresh_identity(tmp_path: Path) -> None:
    master, recorder, thread, outcome = _start_recorder(tmp_path, duration=0.6)
    try:
        complete_line = _snapshot().splitlines(keepends=True)[-1]
        os.write(master, _snapshot()[:-len(complete_line)])
        time.sleep(0.1)
        assert recorder.instrument is None
        assert "error" in request(tmp_path, {"operation": "mode", "expected_session": 42,
                                             "mode": 1, "code": 0, "dwell_s": 0})
        os.write(master, complete_line)
        until = time.monotonic() + 1
        while recorder.instrument is None:
            assert time.monotonic() < until
            time.sleep(0.005)
        recorder.instrument_at = recorder.monotonic() - 20
        assert "error" in request(tmp_path, {"operation": "mode", "expected_session": 42,
                                             "mode": 1, "code": 0, "dwell_s": 0})
        thread.join(2)
        assert "error" not in outcome
    finally:
        os.close(master)


def test_disk_failure_is_retained_as_recording_failure(tmp_path: Path, monkeypatch) -> None:
    master, recorder, thread, outcome = _start_recorder(tmp_path, duration=2)
    monkeypatch.setattr(recorder, "_write_raw", lambda _data: (_ for _ in ()).throw(OSError("disk full")))
    try:
        os.write(master, b"some evidence\n")
        thread.join(2)
        assert isinstance(outcome.get("error"), OSError)
        state = json.loads((tmp_path / "recorder_state.json").read_text())
        assert state["recording"] is False
        assert "disk full" in state["recording_error"]
    finally:
        os.close(master)


def test_passive_serial_open_sets_cdc_carrier_without_reset_before_open() -> None:
    events: list[tuple[str, object]] = []

    class Port:
        def __init__(self, **kwargs):
            assert kwargs["port"] is None
            self._dtr = True
            self._rts = True

        @property
        def dtr(self):
            return self._dtr

        @dtr.setter
        def dtr(self, value):
            events.append(("dtr", value))
            self._dtr = value

        @property
        def rts(self):
            return self._rts

        @rts.setter
        def rts(self, value):
            events.append(("rts", value))
            self._rts = value

        def open(self):
            assert self._dtr is True and self._rts is False
            events.append(("open", self.port))

        def close(self):
            events.append(("close", None))

    class Module:
        Serial = Port

    port = passive_serial_open("/dev/example", 115200, serial_module=Module)
    assert events[:3] == [("dtr", True), ("rts", False), ("open", "/dev/example")]
    port.close()
    with pytest.raises(ValueError, match="1200"):
        passive_serial_open("/dev/example", 1200, serial_module=Module)


def test_pinned_rp2040_cdc_contract_requires_dtr_and_resets_only_at_1200() -> None:
    core = (Path.home() / "Library/Arduino15/packages/rp2040/hardware/rp2040/6.1.0")
    serial_source = core / "cores/rp2040/SerialUSB.cpp"
    tinyusb_source = core / "pico-sdk/lib/tinyusb/src/class/cdc/cdc_device.c"
    if not serial_source.is_file() or not tinyusb_source.is_file():
        pytest.skip("pinned RP2040 core 6.1.0 source is unavailable")
    serial_text = serial_source.read_text(encoding="utf-8")
    cdc_text = tinyusb_source.read_text(encoding="utf-8")
    assert "return tud_cdc_connected();" in serial_text
    assert "(_ss.bps == 1200) && (!_ss.dtr)" in serial_text
    assert "DTR (bit 0) active  is considered as connected" in cdc_text
    assert "tu_bit_test(_cdcd_itf[itf].line_state, 0)" in cdc_text
