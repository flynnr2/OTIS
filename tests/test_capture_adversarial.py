"""Damaged framing and duplicate startup cannot defeat evidence boundaries."""

import json
import signal
import tempfile
import tracemalloc

import pytest

from host.otis_tools.capture_device import (
    CaptureDeviceConfig,
    CaptureDeviceRunner,
    CaptureSink,
    RawEvidenceWriter,
)
from host.otis_tools.offline import finish_run
from tests.capture_fixtures import write_simulated_run


def test_unterminated_stream_and_pending_markers_are_bounded_and_retained():
    block = b"x" * 8192
    with tempfile.TemporaryFile("w+b") as stream:
        writer = RawEvidenceWriter(stream)
        tracemalloc.start()
        try:
            for _ in range(128):
                writer.write_device(block)
            assert stream.tell() == 1048576
            for ordinal in range(2000):
                writer.write_marker("pending", ordinal=ordinal, detail="x" * 256)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        assert peak < 512 * 1024
        assert writer.drop_partial() == 1048576
        writer.close()
        stream.seek(0)
        assert stream.read(1048576) == block * 128
        assert stream.read(1) == b"\n"
        records = [
            json.loads(line.removeprefix(b"# OTIS_HOST "))
            for line in stream.readlines()
        ]
        assert records[0]["event"] == "raw_partial_record_retained"
        assert records[0]["byte_count"] == 1048576
        assert records[0]["synthetic_terminating_lf"] is True
        assert [row["ordinal"] for row in records[1:]] == list(range(2000))


def test_duplicate_capture_cannot_append_or_replace_existing_evidence(tmp_path):
    write_simulated_run(tmp_path)
    runner = CaptureDeviceRunner(
        CaptureDeviceConfig("/dev/never-open", 115200, tmp_path)
    )
    owner = CaptureSink(
        runner, run_dir=tmp_path, command_fifo_path=None, emergency_fifo_path=None
    )
    try:
        owner.raw_writer.write_device(b"existing captured bytes\n")
        before = {
            p.relative_to(tmp_path): p.read_bytes()
            for p in tmp_path.rglob("*")
            if p.is_file()
        }
        with pytest.raises(FileExistsError):
            CaptureSink(
                runner,
                run_dir=tmp_path,
                command_fifo_path=None,
                emergency_fifo_path=None,
            )
        after = {
            p.relative_to(tmp_path): p.read_bytes()
            for p in tmp_path.rglob("*")
            if p.is_file()
        }
        assert after == before
    finally:
        owner.abandon_incomplete()


def test_capture_start_failure_retains_incomplete_reservation(tmp_path, monkeypatch):
    write_simulated_run(tmp_path)
    runner = CaptureDeviceRunner(
        CaptureDeviceConfig("/dev/never-open", 115200, tmp_path),
        serial_factory=lambda *_args, **_kwargs: None,
    )

    def fail_start(*_args, **_kwargs):
        raise RuntimeError("injected fatal sink failure")

    monkeypatch.setattr(CaptureSink, "start", fail_start)
    with pytest.raises(RuntimeError, match="injected fatal sink failure"):
        runner.run()

    assert (tmp_path / "capture_in_progress.flag").is_file()
    assert not (tmp_path / "reports/capture_segment_closure_v1.json").exists()
    with pytest.raises(ValueError, match="capture remains active"):
        finish_run(tmp_path)


def test_serial_disconnect_is_incomplete_when_priority_transport_is_required(
    tmp_path,
):
    write_simulated_run(tmp_path)

    class DisconnectedSerial:
        def read(self, _size):
            raise EOFError("injected transport disconnect")

        def close(self):
            return None

    runner = CaptureDeviceRunner(
        CaptureDeviceConfig(
            "/dev/never-open",
            115200,
            tmp_path,
            command_fifo=tmp_path / "control/normal_commands.fifo",
            emergency_command_fifo=tmp_path / "control/emergency_abort.fifo",
        ),
        serial_factory=lambda *_args, **_kwargs: DisconnectedSerial(),
    )

    with pytest.raises(
        RuntimeError, match="capture transport failed before orderly closure"
    ):
        runner.run()

    assert runner.reconnect_count == 1
    assert runner.emergency_abort_latched is True
    assert (tmp_path / "capture_in_progress.flag").is_file()
    assert not (tmp_path / "reports/capture_segment_closure_v1.json").exists()


def test_capture_write_failure_retains_original_cause_and_reservation(
    tmp_path, monkeypatch
):
    write_simulated_run(tmp_path)

    class OneRecordSerial:
        def read(self, _size):
            return b"REF,injected\n"

        def close(self):
            return None

    runner = CaptureDeviceRunner(
        CaptureDeviceConfig(
            "/dev/never-open",
            115200,
            tmp_path,
            command_fifo=tmp_path / "control/normal_commands.fifo",
            emergency_command_fifo=tmp_path / "control/emergency_abort.fifo",
        ),
        serial_factory=lambda *_args, **_kwargs: OneRecordSerial(),
    )

    def fail_write(*_args, **_kwargs):
        raise OSError("injected evidence write failure")

    monkeypatch.setattr(runner, "_process_bytes", fail_write)
    with pytest.raises(RuntimeError, match="capture transport failed") as raised:
        runner.run()

    assert isinstance(raised.value.__cause__, OSError)
    assert str(raised.value.__cause__) == "injected evidence write failure"
    assert (tmp_path / "capture_in_progress.flag").is_file()
    assert not (tmp_path / "reports/capture_segment_closure_v1.json").exists()


def test_serial_close_failure_cannot_publish_complete_capture(tmp_path):
    write_simulated_run(tmp_path)

    class CloseFailureSerial:
        def read(self, _size):
            return b""

        def close(self):
            raise OSError("injected serial close failure")

    runner = CaptureDeviceRunner(
        CaptureDeviceConfig("/dev/never-open", 115200, tmp_path),
        serial_factory=lambda *_args, **_kwargs: CloseFailureSerial(),
    )
    runner.request_stop(signal.SIGINT)

    with pytest.raises(RuntimeError, match="serial close failed") as raised:
        runner.run()

    assert isinstance(raised.value.__cause__, OSError)
    assert (tmp_path / "capture_in_progress.flag").is_file()
    assert not (tmp_path / "reports/capture_segment_closure_v1.json").exists()


def test_timestamped_official_abort_is_not_reported_as_ingress_fault(
    tmp_path, monkeypatch
):
    from types import SimpleNamespace

    from host.otis_tools import capture_device as capture_module
    from host.otis_tools.serial_commands import timestamped_command_line

    runner = CaptureDeviceRunner(CaptureDeviceConfig("/dev/unused", 115200, tmp_path))
    sent = []
    markers = []
    monkeypatch.setattr(
        runner,
        "_send_command",
        lambda command, *_args, **_kwargs: sent.append(command),
    )
    monkeypatch.setattr(runner, "_emit_status", lambda: None)
    monkeypatch.setattr(
        capture_module,
        "_write_marker",
        lambda _writer, event, **_fields: markers.append(event),
    )
    fifo = SimpleNamespace(
        poll=lambda **_kwargs: [timestamped_command_line("ACTIVE ABORT")]
    )
    with tempfile.TemporaryFile("w+b") as stream:
        writer = RawEvidenceWriter(stream)
        runner._poll_emergency_command(fifo, None, object(), writer)

    assert sent == ["ACTIVE ABORT"]
    assert "emergency_command_ingress_fault" not in markers


def test_serial_owner_probe_has_a_subprocess_deadline(monkeypatch):
    from host.otis_tools import capture_device as capture_module

    def time_out(*_args, **kwargs):
        assert kwargs["timeout"] == capture_module.SERIAL_OWNER_PROBE_TIMEOUT_S
        raise capture_module.subprocess.TimeoutExpired("lsof", kwargs["timeout"])

    monkeypatch.setattr(capture_module.subprocess, "run", time_out)
    with pytest.raises(ValueError, match="inspection timed out"):
        capture_module._serial_owner_pids("/dev/fake")
