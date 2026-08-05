from __future__ import annotations

from pathlib import Path
import json
import signal
import shutil
import threading

import host.otis_tools.capture_device as capture_device_module
from host.otis_tools.capture_device import (
    CaptureDeviceConfig,
    CaptureDeviceRunner,
    LineFramer,
    RawEvidenceWriter,
)
from host.otis_tools.run_paths import RunPaths, default_csv_files


class FakeSerial:
    def __init__(self, chunks, stop_event: threading.Event | None = None, fail_after: Exception | None = None) -> None:
        self.chunks = list(chunks)
        self.stop_event = stop_event
        self.fail_after = fail_after
        self.closed = False
        self.writes: list[bytes] = []

    def read(self, size: int) -> bytes:
        if self.chunks:
            chunk = self.chunks.pop(0)
            if len(chunk) > size:
                self.chunks.insert(0, chunk[size:])
                return chunk[:size]
            return chunk
        if self.fail_after is not None:
            raise self.fail_after
        if self.stop_event is not None:
            self.stop_event.set()
        return b""

    def close(self) -> None:
        self.closed = True

    def write(self, data: bytes) -> int:
        self.writes.append(data)
        return len(data)

    def flush(self) -> None:
        return None


def _config(tmp_path: Path) -> CaptureDeviceConfig:
    return CaptureDeviceConfig(
        device="/dev/cu.usbmodemTEST",
        baud=115200,
        run_dir=tmp_path / "run",
        reconnect_initial_s=0.001,
        reconnect_max_s=0.001,
        status_interval_s=999,
    )


def test_line_framer_holds_partial_lines() -> None:
    framer = LineFramer(max_line_bytes=64)

    lines, events = framer.feed(b"EVT,1")
    assert lines == []
    assert events == []

    lines, events = framer.feed(b",2\nSTS,1")
    assert lines == [b"EVT,1,2"]
    assert events == []
    assert framer.drop_partial() == len(b"STS,1")


def test_line_framer_drops_oversize_partial_line() -> None:
    framer = LineFramer(max_line_bytes=4)

    lines, events = framer.feed(b"abcdef")

    assert lines == []
    assert events == ["oversize_partial_line_dropped bytes=6"]
    assert framer.drop_partial() == 6


def test_line_framer_discards_oversize_continuation_to_record_boundary() -> None:
    framer = LineFramer(max_line_bytes=8)

    lines, events = framer.feed(b"REF,1,10")
    assert lines == []
    assert events == []

    lines, events = framer.feed(b"00,1,R")
    assert lines == []
    assert events == ["oversize_partial_line_dropped bytes=14"]

    lines, events = framer.feed(b",16000000,rp2040_timer0,16\nSTS,1,ok\n")
    assert lines == [b"STS,1,ok"]
    assert events == []
    assert framer.drop_partial() == 0


def test_line_framer_rejects_oversize_complete_line() -> None:
    framer = LineFramer(max_line_bytes=4)

    lines, events = framer.feed(b"abcdef\nok\n")

    assert lines == [b"ok"]
    assert events == ["oversize_line_dropped bytes=6"]


def test_capture_device_writes_append_only_raw_and_csv(tmp_path: Path) -> None:
    stop_event = threading.Event()
    config = _config(tmp_path)
    paths = RunPaths(config.run_dir)
    paths.raw_dir.mkdir(parents=True)
    paths.raw_serial_log.write_bytes(b"PREEXISTING\n")

    serial = FakeSerial(
        [
            b"REF,1,1000,1,R,16000000,rp2040_timer0,16\n",
            b"CNT,1,7,2,1,16000001,rp2040_timer0,16,R,h0_tcxo_16mhz,0\n",
            b"STS,1,1,1,rp2040_timer0,system,mode,SW1_GPS_PPS,INFO,32768\n",
            b"ENV,1,1,16000000,rp2040_timer0,sht4x,vcocxo_near,31.250,45.000,,0\n",
            b"PGT,1,1,1,CLEAN_NOMINAL,1,0,start,marker,0,0,0,0\n",
        ],
        stop_event=stop_event,
    )
    runner = CaptureDeviceRunner(config, serial_factory=lambda *_args, **_kwargs: serial, stop_event=stop_event)

    assert runner.run() == 0

    raw = paths.raw_serial_log.read_bytes()
    assert raw.startswith(b"PREEXISTING\n")
    assert b"REF,1,1000" in raw
    assert "REF,1,1000,1,R,16000000,rp2040_timer0,16" in paths.raw_events_csv.read_text(encoding="utf-8")
    assert "CNT,1,7,2,1,16000001,rp2040_timer0,16,R,h0_tcxo_16mhz,0" in paths.count_observations_csv.read_text(
        encoding="utf-8"
    )
    assert "STS,1,1,1,rp2040_timer0,system,mode,SW1_GPS_PPS,INFO,32768" in paths.health_csv.read_text(encoding="utf-8")
    assert "ENV,1,1,16000000,rp2040_timer0,sht4x,vcocxo_near,31.250,45.000,,0" in paths.environment_csv.read_text(
        encoding="utf-8"
    )
    assert "PGT,1,1,1,CLEAN_NOMINAL" in paths.pseudo_pps_truth_csv.read_text(
        encoding="utf-8"
    )


def test_capture_device_reconnect_drops_partial_without_truncating(tmp_path: Path) -> None:
    stop_event = threading.Event()
    config = _config(tmp_path)
    serials = [
        FakeSerial([b"REF,1,1000"], fail_after=EOFError("device disappeared")),
        FakeSerial([b"REF,1,1001,1,R,32000000,rp2040_timer0,16\n"], stop_event=stop_event),
    ]

    def factory(*_args, **_kwargs):
        return serials.pop(0)

    runner = CaptureDeviceRunner(config, serial_factory=factory, stop_event=stop_event, sleep=lambda _seconds: None)

    assert runner.run() == 0
    raw = RunPaths(config.run_dir).raw_serial_log.read_bytes()

    assert b"REF,1,1000" not in raw
    assert b"serial_disconnected" in raw
    assert b"partial_line_dropped_bytes" in raw
    assert runner.reconnect_count == 1
    assert "REF,1,1001,1,R,32000000,rp2040_timer0,16" in RunPaths(config.run_dir).raw_events_csv.read_text(
        encoding="utf-8"
    )


def test_capture_device_malformed_utf8_preserves_raw_bytes(tmp_path: Path) -> None:
    stop_event = threading.Event()
    config = _config(tmp_path)
    bad_line = b"STS,1,1,1,rp2040_timer0,system,bad,\xff,INFO,0\n"
    serial = FakeSerial([bad_line], stop_event=stop_event)
    runner = CaptureDeviceRunner(config, serial_factory=lambda *_args, **_kwargs: serial, stop_event=stop_event)

    assert runner.run() == 0

    paths = RunPaths(config.run_dir)
    assert bad_line in paths.raw_serial_log.read_bytes()
    assert b"malformed_utf8" in paths.raw_serial_log.read_bytes()
    assert "\ufffd" not in paths.health_csv.read_text(encoding="utf-8")
    assert runner.malformed_utf8 == 1
    assert runner.lines_parsed == 0


def test_capture_device_preserves_malformed_frame_only_in_raw_evidence(tmp_path: Path) -> None:
    stop_event = threading.Event()
    config = _config(tmp_path)
    malformed_known_record = b"REF,1,1000,1,R,16000000,rp2040_timer0,16,extra\n"
    serial = FakeSerial([malformed_known_record], stop_event=stop_event)
    runner = CaptureDeviceRunner(config, serial_factory=lambda *_args, **_kwargs: serial, stop_event=stop_event)

    assert runner.run() == 0

    paths = RunPaths(config.run_dir)
    assert malformed_known_record in paths.raw_serial_log.read_bytes()
    assert "REF,1,1000,1,R,16000000,rp2040_timer0,16,extra" not in paths.raw_events_csv.read_text(
        encoding="utf-8"
    )
    assert runner.parser_errors == 1
    assert runner.lines_parsed == 0


def test_capture_device_creates_manifest_and_layout(tmp_path: Path) -> None:
    stop_event = threading.Event()
    config = _config(tmp_path)
    serial = FakeSerial([], stop_event=stop_event)
    runner = CaptureDeviceRunner(config, serial_factory=lambda *_args, **_kwargs: serial, stop_event=stop_event)

    assert runner.run() == 0

    paths = RunPaths(config.run_dir)
    manifest = json.loads(paths.manifest.read_text(encoding="utf-8"))
    assert paths.raw_dir.exists()
    assert paths.csv_dir.exists()
    assert paths.reports_dir.exists()
    assert manifest["files"] == default_csv_files()
    assert not (config.run_dir / "capture_in_progress.flag").exists()


def test_capture_device_instantiates_exact_manifest_template(tmp_path: Path) -> None:
    stop_event = threading.Event()
    run_dir = tmp_path / "stage5_open_loop_20260802T120000Z"
    config = CaptureDeviceConfig(
        device="/dev/cu.usbmodemTEST",
        baud=115200,
        run_dir=run_dir,
        manifest_template=Path(
            "profiles/run_templates/cx317_pps_gated_open_loop_v1/manifest.json"
        ),
        reconnect_initial_s=0.001,
        reconnect_max_s=0.001,
        status_interval_s=999,
    )
    serial = FakeSerial([], stop_event=stop_event)
    runner = CaptureDeviceRunner(
        config,
        serial_factory=lambda *_args, **_kwargs: serial,
        stop_event=stop_event,
    )

    assert runner.run() == 0

    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["run_id"] == run_dir.name
    assert manifest["template"] is False
    assert manifest["host"]["serial_device"] == config.device
    assert manifest["firmware"]["config_id"] == "cx317_pps_gated_open_loop"
    assert (run_dir / "csv" / "dac_steps.csv").exists()


def test_capture_device_uses_h1_manifest_split_targets(tmp_path: Path) -> None:
    stop_event = threading.Event()
    run_dir = tmp_path / "h1_run"
    shutil.copytree(
        "profiles/run_templates/h1_open_loop/dac_manual_sweep",
        run_dir,
    )
    config = _config(tmp_path)
    config = CaptureDeviceConfig(
        device=config.device,
        baud=config.baud,
        run_dir=run_dir,
        reconnect_initial_s=config.reconnect_initial_s,
        reconnect_max_s=config.reconnect_max_s,
        status_interval_s=config.status_interval_s,
    )
    serial = FakeSerial(
        [
            b"EVT,1,1000,0,R,16000000,rp2040_timer0,0\n",
            b"REF,1,1001,1,R,32000000,rp2040_timer0,16\n",
            b"DAC,1,1,1000,-1,32768,32768,0,,,5000,start,0\n",
        ],
        stop_event=stop_event,
    )
    runner = CaptureDeviceRunner(config, serial_factory=lambda *_args, **_kwargs: serial, stop_event=stop_event)

    assert runner.run() == 0
    assert "EVT,1,1000" in (run_dir / "csv" / "evt.csv").read_text(encoding="utf-8")
    assert "REF,1,1001" in (run_dir / "csv" / "ref.csv").read_text(encoding="utf-8")
    assert "EVT,1,1000" not in (run_dir / "csv" / "ref.csv").read_text(encoding="utf-8")
    assert "DAC,1,1,1000" in (run_dir / "csv" / "dac_steps.csv").read_text(encoding="utf-8")


def test_capture_device_clean_shutdown_drops_partial_line(tmp_path: Path) -> None:
    stop_event = threading.Event()
    config = _config(tmp_path)
    serial = FakeSerial([b"STS,1,partial"], stop_event=stop_event)
    runner = CaptureDeviceRunner(config, serial_factory=lambda *_args, **_kwargs: serial, stop_event=stop_event)

    assert runner.run() == 0

    raw = RunPaths(config.run_dir).raw_serial_log.read_bytes()
    assert b"STS,1,partial" not in raw
    assert b"partial_line_dropped" in raw
    assert "partial" not in RunPaths(config.run_dir).health_csv.read_text(encoding="utf-8")


def test_sigint_shutdown_drains_exactly_one_partial_device_line(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    runner: CaptureDeviceRunner

    class SignalAfterFirstRead(FakeSerial):
        def __init__(self) -> None:
            super().__init__(
                [
                    b"STS,1,1,1,rp2040_timer0,system,mode",
                    b",SW1_GPS_PPS,INFO,32768\n"
                    b"REF,1,1001,1,R,32000000,rp2040_timer0,16\n",
                ]
            )
            self.first_read = True

        def read(self, size: int) -> bytes:
            data = super().read(size)
            if self.first_read:
                self.first_read = False
                runner.request_stop(signal.SIGINT)
            return data

    serial = SignalAfterFirstRead()
    runner = CaptureDeviceRunner(
        config,
        serial_factory=lambda *_args, **_kwargs: serial,
    )

    assert runner.run() == 0

    raw = RunPaths(config.run_dir).raw_serial_log.read_bytes()
    assert (
        b"STS,1,1,1,rp2040_timer0,system,mode,SW1_GPS_PPS,INFO,32768\n"
        in raw
    )
    assert b"REF,1,1001" not in raw
    assert b"graceful_shutdown_complete" in raw
    assert b"partial_line_dropped" not in raw


def test_planned_duration_stops_after_completing_partial_device_line(
    tmp_path: Path, monkeypatch
) -> None:
    clock_ticks = iter(range(1000))
    monkeypatch.setattr(
        capture_device_module.time,
        "monotonic",
        lambda: float(next(clock_ticks)),
    )
    base = _config(tmp_path)
    config = CaptureDeviceConfig(
        device=base.device,
        baud=base.baud,
        run_dir=base.run_dir,
        reconnect_initial_s=base.reconnect_initial_s,
        reconnect_max_s=base.reconnect_max_s,
        status_interval_s=base.status_interval_s,
        duration_s=1.0,
    )
    serial = FakeSerial(
        [
            b"STS,1,1,1,rp2040_timer0,system,mode",
            b",SW1_GPS_PPS,INFO,32768\n"
            b"REF,1,1001,1,R,32000000,rp2040_timer0,16\n",
        ]
    )
    runner = CaptureDeviceRunner(
        config,
        serial_factory=lambda *_args, **_kwargs: serial,
    )

    assert runner.run() == 0

    paths = RunPaths(config.run_dir)
    raw = paths.raw_serial_log.read_bytes()
    assert b"STS,1,1,1,rp2040_timer0,system,mode,SW1_GPS_PPS,INFO,32768\n" in raw
    assert b"REF,1,1001" not in raw
    assert b"planned_duration_complete" in raw
    assert b"partial_line_dropped" not in raw
    assert runner.parser_errors == 0


def test_capture_device_sends_audited_atomic_command_without_polluting_raw_stream(tmp_path: Path) -> None:
    stop_event = threading.Event()
    config = _config(tmp_path)
    serial = FakeSerial([], stop_event=stop_event)
    runner = CaptureDeviceRunner(config, serial_factory=lambda *_args, **_kwargs: serial, stop_event=stop_event)

    paths = RunPaths(config.run_dir)
    paths.raw_dir.mkdir(parents=True)
    with paths.raw_serial_log.open("a+b") as raw_handle:
        runner._send_command("dac mid", serial, RawEvidenceWriter(raw_handle))

    raw = paths.raw_serial_log.read_bytes()
    assert serial.writes == [b"DAC MID\n"]
    assert b"host_command_accepted" in raw
    assert b"host_command_sent" in raw
    assert b"\nDAC MID\n" not in raw
    assert runner.commands_sent == 1


def test_capture_device_rejects_open_ended_command(tmp_path: Path) -> None:
    stop_event = threading.Event()
    config = _config(tmp_path)
    serial = FakeSerial([], stop_event=stop_event)
    runner = CaptureDeviceRunner(config, serial_factory=lambda *_args, **_kwargs: serial, stop_event=stop_event)

    paths = RunPaths(config.run_dir)
    paths.raw_dir.mkdir(parents=True)
    with paths.raw_serial_log.open("a+b") as raw_handle:
        runner._send_command("SWEEP ADD 0x8000 5000", serial, RawEvidenceWriter(raw_handle))

    raw = paths.raw_serial_log.read_bytes()
    assert serial.writes == []
    assert b"host_command_rejected" in raw
    assert runner.commands_rejected == 1


def test_raw_evidence_writer_defers_host_marker_until_partial_device_line_completes(tmp_path: Path) -> None:
    path = tmp_path / "serial.log"
    with path.open("a+b") as raw_handle:
        writer = RawEvidenceWriter(raw_handle)
        writer.write_device(b"CNT,1,2700,2,43227335024,43243335024")
        writer.write_marker("host_command_sent", command="CONFIG?", bytes_written=8)
        writer.write_device(b",rp2040_timer0,15999997,R,h0_tcxo_16mhz,16\n")

    lines = path.read_bytes().splitlines()
    assert lines[0] == (
        b"CNT,1,2700,2,43227335024,43243335024,"
        b"rp2040_timer0,15999997,R,h0_tcxo_16mhz,16"
    )
    assert lines[1].startswith(b"# OTIS_HOST ")
    assert b"host_command_sent" in lines[1]


def test_raw_evidence_writer_drops_partial_device_line_before_pending_markers(tmp_path: Path) -> None:
    path = tmp_path / "serial.log"
    with path.open("a+b") as raw_handle:
        writer = RawEvidenceWriter(raw_handle)
        writer.write_device(b"REF,1,4131,1,R,50125319056,rp")
        writer.write_marker("partial_line_dropped", bytes=29, reason="shutdown")
        assert writer.drop_partial() == 29

    lines = path.read_bytes().splitlines()
    assert len(lines) == 1
    assert lines[0].startswith(b"# OTIS_HOST ")
    assert b"REF,1,4131" not in lines[0]
