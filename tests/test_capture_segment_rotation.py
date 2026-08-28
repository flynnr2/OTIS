from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path
import threading
import time

import pytest

import host.otis_tools.capture_device as capture_device
import host.otis_tools.bounded_tight_deadband_activation as current_activation
from host.otis_tools.capture_device import CaptureDeviceConfig, CaptureDeviceRunner
from host.otis_tools.capture_segment_rotation import (
    PROTOCOL_ID,
    prepare_transition,
    request_rotation,
)
from host.otis_tools.run_paths import default_csv_files, ensure_run_layout
from host.otis_tools.serial_commands import send_command_to_fifo


def _wait_until(predicate, timeout_s: float = 3.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("timed out waiting for capture rehearsal condition")


def test_same_open_serial_rotates_rehearsal_transition_live_and_only_live_can_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = (tmp_path / "rehearsal").resolve()
    transition = (tmp_path / "transition").resolve()
    live = (tmp_path / "live").resolve()
    control = (tmp_path / "carrier").resolve()
    device = "/dev/cu.usbmodemFAKE"
    ensure_run_layout(source)
    capture_device._create_manifest_if_missing(source, device, 115200)
    prepare_transition(source / "run_manifest.json", transition)
    live.mkdir()
    (live / "run_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "stage": current_activation.LIVE_STAGE,
                "host": {"serial_device": device, "baud": 115200},
                "files": default_csv_files(),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        current_activation,
        "validate_frozen_run_manifest",
        lambda _: {"stage": current_activation.LIVE_STAGE},
    )

    class StreamingSerial:
        def __init__(self) -> None:
            self.sequence = 0
            self.writes: list[bytes] = []
            self.closed = False

        def read(self, _size: int) -> bytes:
            time.sleep(0.002)
            self.sequence += 1
            return (
                f"REF,1,{self.sequence},1,R,{self.sequence * 16000000},"
                "rp2040_timer0,16\n"
            ).encode("ascii")

        def write(self, data: bytes) -> int:
            self.writes.append(data)
            return len(data)

        def close(self) -> None:
            self.closed = True

    serial = StreamingSerial()
    factory_calls = 0

    def factory(*_args, **_kwargs):
        nonlocal factory_calls
        factory_calls += 1
        return serial

    config = CaptureDeviceConfig(
        device=device,
        baud=115200,
        run_dir=source,
        status_interval_s=999,
        segment_control_dir=control,
        segment_capability="test-capability",
    )
    runner = CaptureDeviceRunner(config, serial_factory=factory)
    results: list[int] = []
    worker = threading.Thread(target=lambda: results.append(runner.run()))
    worker.start()
    try:
        _wait_until(
            lambda: (control / "carrier_state.json").is_file()
            and json.loads((control / "carrier_state.json").read_text()).get(
                "status"
            )
            == "running"
        )
        _wait_until(lambda: serial.sequence >= 3)
        first = request_rotation(
            control_dir=control,
            capability="test-capability",
            to_run=transition,
            mode="transition",
        )
        assert first["serial_reopened"] is False
        assert serial.writes == []
        _wait_until(lambda: serial.sequence >= 6)

        normal_fifo = live / "control/commands.fifo"
        emergency_fifo = live / "control/emergency.fifo"
        second = request_rotation(
            control_dir=control,
            capability="test-capability",
            to_run=live,
            mode="live",
            command_fifo=normal_fifo,
            emergency_command_fifo=emergency_fifo,
        )
        assert second["serial_reopened"] is False
        assert second["pid"] == first["pid"]
        assert second["transport_generation"] == 3
        assert send_command_to_fifo(normal_fifo, "CONFIG?") == 0
        _wait_until(lambda: serial.writes == [b"CONFIG?\n"])
    finally:
        runner.request_stop()
        worker.join(timeout=3.0)

    assert not worker.is_alive()
    assert results == [0]
    assert factory_calls == 1
    assert serial.closed is True
    assert serial.writes == [b"CONFIG?\n"]
    for run in (source, transition, live):
        raw = run / "raw/serial.log"
        assert raw.is_file()
        assert "REF,1," in raw.read_text(encoding="utf-8")
    assert not (source / capture_device.CAPTURE_IN_PROGRESS_FLAG).exists()
    assert not (transition / capture_device.CAPTURE_IN_PROGRESS_FLAG).exists()
    assert not (live / capture_device.CAPTURE_IN_PROGRESS_FLAG).exists()
    assert json.loads(
        (source / capture_device.SEGMENT_CLOSURE).read_text()
    )["closure_mode"] == "same_owner_logical_rotation"
    assert json.loads(
        (transition / capture_device.SEGMENT_CLOSURE).read_text()
    )["closure_mode"] == "same_owner_logical_rotation"
    assert json.loads(
        (live / capture_device.SEGMENT_CLOSURE).read_text()
    )["closure_mode"] == "physical_serial_close"


def test_rotation_operation_id_reuses_completed_response_without_reissuing(
    tmp_path: Path,
) -> None:
    control = tmp_path / "control"
    target = (tmp_path / "target").resolve()
    target.mkdir()
    operation_id = "stage5-leg-a-rehearsal-to-transition"
    request_id = sha256(
        f"{PROTOCOL_ID}:{operation_id}".encode("utf-8")
    ).hexdigest()[:32]
    response = {
        "schema_version": 1,
        "request_id": request_id,
        "status": "completed",
        "from_run": str((tmp_path / "source").resolve()),
        "to_run": str(target),
        "pid": 123,
        "transport_generation": 2,
        "serial_reopened": False,
        "reconnect_count": 0,
    }
    response_path = control / capture_device.SEGMENT_RESPONSE_DIR / f"{request_id}.json"
    response_path.parent.mkdir(parents=True)
    response_path.write_text(json.dumps(response), encoding="utf-8")

    observed = request_rotation(
        control_dir=control,
        capability="unused-on-resume",
        to_run=target,
        mode="transition",
        operation_id=operation_id,
    )

    assert observed == response
    assert not (control / capture_device.SEGMENT_REQUEST).exists()


def test_pending_rotation_drains_partial_record_before_single_validation(
    tmp_path: Path,
) -> None:
    source = (tmp_path / "source").resolve()
    transition = (tmp_path / "transition").resolve()
    control = (tmp_path / "carrier").resolve()
    device = "/dev/cu.usbmodemFAKE"
    ensure_run_layout(source)
    capture_device._create_manifest_if_missing(source, device, 115200)
    prepare_transition(source / "run_manifest.json", transition)

    class PartialChunkSerial:
        """Full reads always contain a row but end partway into the next."""

        def __init__(self) -> None:
            self.record = b"#" + b"x" * 507 + b"\n"
            self.offset = 0
            self.read_calls = 0
            self.closed = False

        def read(self, size: int) -> bytes:
            self.read_calls += 1
            if size > 1:
                time.sleep(0.002)
            result = bytearray()
            while len(result) < size:
                available = min(size - len(result), len(self.record) - self.offset)
                result.extend(self.record[self.offset : self.offset + available])
                self.offset = (self.offset + available) % len(self.record)
            return bytes(result)

        def write(self, data: bytes) -> int:
            return len(data)

        def close(self) -> None:
            self.closed = True

    serial = PartialChunkSerial()
    factory_calls = 0

    def factory(*_args, **_kwargs):
        nonlocal factory_calls
        factory_calls += 1
        return serial

    runner = CaptureDeviceRunner(
        CaptureDeviceConfig(
            device=device,
            baud=115200,
            run_dir=source,
            read_size=512,
            status_interval_s=999,
            segment_control_dir=control,
            segment_capability="test-capability",
        ),
        serial_factory=factory,
    )
    validation_calls = 0
    validate = runner._validate_segment_request

    def count_validation(request):
        nonlocal validation_calls
        validation_calls += 1
        return validate(request)

    runner._validate_segment_request = count_validation  # type: ignore[method-assign]
    results: list[int] = []
    worker = threading.Thread(target=lambda: results.append(runner.run()))
    worker.start()
    try:
        _wait_until(
            lambda: (control / "carrier_state.json").is_file()
            and json.loads((control / "carrier_state.json").read_text()).get(
                "status"
            )
            == "running"
        )
        _wait_until(lambda: serial.read_calls >= 3)
        owner_pid = int(
            json.loads((control / "carrier_state.json").read_text())["pid"]
        )
        response = request_rotation(
            control_dir=control,
            capability="test-capability",
            to_run=transition,
            mode="transition",
            wait_timeout_s=0.5,
            operation_id="partial-record-boundary-drain",
        )
    finally:
        runner.request_stop()
        worker.join(timeout=3.0)

    assert not worker.is_alive()
    assert results == [0]
    assert response["pid"] == owner_pid
    assert response["transport_generation"] == 2
    assert response["serial_reopened"] is False
    assert validation_calls == 1
    assert factory_calls == 1
    assert serial.closed is True
    assert json.loads((source / capture_device.SEGMENT_CLOSURE).read_text())[
        "closure_mode"
    ] == "same_owner_logical_rotation"
