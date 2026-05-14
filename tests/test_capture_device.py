from __future__ import annotations

from pathlib import Path
import json
import shutil
import threading

from host.otis_tools.capture_device import CaptureDeviceConfig, CaptureDeviceRunner, LineFramer
from host.otis_tools.run_paths import RunPaths


class FakeSerial:
    def __init__(self, chunks, stop_event: threading.Event | None = None, fail_after: Exception | None = None) -> None:
        self.chunks = list(chunks)
        self.stop_event = stop_event
        self.fail_after = fail_after
        self.closed = False

    def read(self, _size: int) -> bytes:
        if self.chunks:
            return self.chunks.pop(0)
        if self.fail_after is not None:
            raise self.fail_after
        if self.stop_event is not None:
            self.stop_event.set()
        return b""

    def close(self) -> None:
        self.closed = True


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
    assert framer.drop_partial() == 0


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

    assert b"REF,1,1000" in raw
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
    assert "\ufffd" in paths.health_csv.read_text(encoding="utf-8")
    assert runner.malformed_utf8 == 1


def test_capture_device_logs_parser_errors_but_keeps_rows(tmp_path: Path) -> None:
    stop_event = threading.Event()
    config = _config(tmp_path)
    malformed_known_record = b"REF,1,1000,1,R,16000000,rp2040_timer0,16,extra\n"
    serial = FakeSerial([malformed_known_record], stop_event=stop_event)
    runner = CaptureDeviceRunner(config, serial_factory=lambda *_args, **_kwargs: serial, stop_event=stop_event)

    assert runner.run() == 0

    paths = RunPaths(config.run_dir)
    assert malformed_known_record in paths.raw_serial_log.read_bytes()
    assert "REF,1,1000,1,R,16000000,rp2040_timer0,16,extra" in paths.raw_events_csv.read_text(encoding="utf-8")
    assert runner.parser_errors == 1


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
    assert manifest["files"] == [
        {"path": "csv/raw_events.csv", "contract": "raw_events_v1"},
        {"path": "csv/count_observations.csv", "contract": "count_observations_v1"},
        {"path": "csv/health.csv", "contract": "health_v1"},
    ]
    assert not (config.run_dir / "capture_in_progress.flag").exists()


def test_capture_device_uses_h1_manifest_split_targets(tmp_path: Path) -> None:
    stop_event = threading.Event()
    run_dir = tmp_path / "h1_run"
    shutil.copytree("runs/h1_open_loop/dac_manual_sweep/_template", run_dir)
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
    assert b"STS,1,partial" in raw
    assert b"partial_line_dropped" in raw
    assert "partial" not in RunPaths(config.run_dir).health_csv.read_text(encoding="utf-8")
