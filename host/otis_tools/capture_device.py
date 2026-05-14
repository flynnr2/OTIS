from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import argparse
import glob
import json
import logging
import signal
import time
import threading
from typing import Callable

from .capture_serial import CsvRecordSplitter, _split_targets_from_manifest
from .run_loader import CAPTURE_IN_PROGRESS_FLAG, find_manifest_path
from .run_paths import default_csv_files, ensure_run_layout


LOGGER = logging.getLogger("otis.capture_device")
HOST_MARKER_PREFIX = b"# OTIS_HOST"


@dataclass(frozen=True)
class CaptureDeviceConfig:
    device: str
    baud: int
    run_dir: Path
    read_size: int = 4096
    read_timeout_s: float = 1.0
    reconnect_initial_s: float = 1.0
    reconnect_max_s: float = 30.0
    status_interval_s: float = 60.0
    max_line_bytes: int = 65536


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _log_event(level: int, event: str, **fields: object) -> None:
    details = " ".join(f"{key}={value!r}" for key, value in sorted(fields.items()))
    LOGGER.log(level, "event=%s%s", event, f" {details}" if details else "")


def _write_marker(raw_handle, event: str, **fields: object) -> None:
    payload = {"event": event, "utc": _utc_now(), **fields}
    if raw_handle.tell() > 0:
        raw_handle.seek(-1, 1)
        last_byte = raw_handle.read(1)
        raw_handle.seek(0, 2)
        if last_byte != b"\n":
            raw_handle.write(b"\n")
    raw_handle.write(HOST_MARKER_PREFIX + b" " + json.dumps(payload, sort_keys=True).encode("utf-8") + b"\n")
    raw_handle.flush()


def _load_serial_module():
    try:
        import serial  # type: ignore
    except ImportError as exc:
        raise SystemExit("pyserial is required for capture_device; install it with `python3 -m pip install pyserial`") from exc
    return serial


def _detect_single_device() -> str:
    candidates = sorted(glob.glob("/dev/cu.usbmodem*"))
    if len(candidates) != 1:
        raise SystemExit(f"--auto-detect requires exactly one /dev/cu.usbmodem* device; found {len(candidates)}")
    return candidates[0]


def _create_manifest_if_missing(run_dir: Path, device: str, baud: int) -> None:
    manifest_path = find_manifest_path(run_dir)
    if manifest_path is not None:
        return
    manifest = {
        "schema_version": 1,
        "run_id": run_dir.name,
        "created_utc": _utc_now(),
        "started_at_utc": _utc_now(),
        "template": False,
        "host": {
            "tool": "host.otis_tools.capture_device",
            "version": "0",
            "serial_device": device,
            "baud": baud,
        },
        "profile": {
            "name": "h0_reference",
            "version": 1,
        },
        "domains": [
            {
                "name": "rp2040_timer0",
                "nominal_hz": 16000000,
            }
        ],
        "channels": [
            {"channel_id": 0, "role": "generic_pulse", "record_family": "raw_events_v1"},
            {"channel_id": 1, "role": "pps_reference", "record_family": "raw_events_v1"},
            {"channel_id": 2, "role": "xcxo_observation", "record_family": "count_observations_v1"},
        ],
        "contracts": {
            "raw_events_v1": 1,
            "count_observations_v1": 1,
            "health_v1": 1,
            "run_manifest_v1": 1,
        },
        "files": default_csv_files(),
        "expected_artifacts": [entry["path"] for entry in default_csv_files()],
        "known_limitations": [
            "Host serial ingest is archival only; RP2040-side hardware remains the timing authority.",
        ],
    }
    with (run_dir / "run_manifest.json").open("x", encoding="utf-8") as handle:
        json.dump(manifest, handle, indent=2)
        handle.write("\n")


def _split_targets(run_dir: Path) -> tuple[dict[str, Path], dict[str, tuple[str, Path]]]:
    manifest_path = find_manifest_path(run_dir)
    if manifest_path is None:
        return {entry["contract"]: run_dir / entry["path"] for entry in default_csv_files()}, {}
    with manifest_path.open("r", encoding="utf-8") as handle:
        manifest = json.load(handle)
    return _split_targets_from_manifest(manifest, run_dir)


class LineFramer:
    def __init__(self, max_line_bytes: int) -> None:
        self.max_line_bytes = max_line_bytes
        self.buffer = bytearray()

    def feed(self, data: bytes) -> tuple[list[bytes], list[str]]:
        lines: list[bytes] = []
        events: list[str] = []
        self.buffer.extend(data)
        while True:
            try:
                newline_index = self.buffer.index(0x0A)
            except ValueError:
                break
            line = bytes(self.buffer[:newline_index]).rstrip(b"\r")
            del self.buffer[: newline_index + 1]
            lines.append(line)
        if len(self.buffer) > self.max_line_bytes:
            dropped = len(self.buffer)
            self.buffer.clear()
            events.append(f"oversize_partial_line_dropped bytes={dropped}")
        return lines, events

    def drop_partial(self) -> int:
        dropped = len(self.buffer)
        self.buffer.clear()
        return dropped


class CaptureDeviceRunner:
    def __init__(
        self,
        config: CaptureDeviceConfig,
        serial_factory: Callable[..., object] | None = None,
        stop_event: threading.Event | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.config = config
        self.serial_factory = serial_factory
        self.stop_event = stop_event or threading.Event()
        self.sleep = sleep
        self.bytes_written = 0
        self.lines_seen = 0
        self.lines_parsed = 0
        self.malformed_utf8 = 0
        self.parser_errors = 0
        self.reconnect_count = 0
        self.framer = LineFramer(config.max_line_bytes)

    def request_stop(self, signum: int | None = None) -> None:
        _log_event(logging.INFO, "shutdown_requested", signal=signum)
        self.stop_event.set()

    def _serial_factory(self):
        if self.serial_factory is not None:
            return self.serial_factory
        serial_module = _load_serial_module()
        return serial_module.Serial

    def _serial_exceptions(self) -> tuple[type[BaseException], ...]:
        if self.serial_factory is not None:
            return (OSError, EOFError)
        serial_module = _load_serial_module()
        return (OSError, EOFError, serial_module.SerialException)

    def _process_line(self, line: bytes, splitter: CsvRecordSplitter, raw_handle) -> None:
        self.lines_seen += 1
        try:
            text = line.decode("utf-8")
        except UnicodeDecodeError as exc:
            self.malformed_utf8 += 1
            _log_event(logging.WARNING, "malformed_utf8", line_number=self.lines_seen, error=str(exc))
            _write_marker(raw_handle, "malformed_utf8", line_number=self.lines_seen, error=str(exc))
            text = line.decode("utf-8", errors="replace")
        contract = splitter.process_line(text)
        if contract is not None:
            self.lines_parsed += 1

    def _parser_error(self, message: str) -> None:
        self.parser_errors += 1
        _log_event(logging.WARNING, "parser_error", message=message, parser_errors=self.parser_errors)

    def _process_bytes(self, data: bytes, splitter: CsvRecordSplitter, raw_handle) -> None:
        raw_handle.write(data)
        raw_handle.flush()
        self.bytes_written += len(data)
        lines, events = self.framer.feed(data)
        for event in events:
            _log_event(logging.WARNING, event)
            _write_marker(raw_handle, event)
        for line in lines:
            self._process_line(line, splitter, raw_handle)

    def _emit_status(self) -> None:
        _log_event(
            logging.INFO,
            "status",
            bytes_written=self.bytes_written,
            lines_seen=self.lines_seen,
            lines_parsed=self.lines_parsed,
            malformed_utf8=self.malformed_utf8,
            parser_errors=self.parser_errors,
            reconnect_count=self.reconnect_count,
        )

    def run(self) -> int:
        paths = ensure_run_layout(self.config.run_dir)
        _create_manifest_if_missing(self.config.run_dir, self.config.device, self.config.baud)
        file_by_contract, file_by_record_type = _split_targets(self.config.run_dir)
        in_progress = self.config.run_dir / CAPTURE_IN_PROGRESS_FLAG
        in_progress.touch(exist_ok=True)
        backoff = self.config.reconnect_initial_s
        next_status = time.monotonic() + self.config.status_interval_s

        with paths.raw_serial_log.open("a+b") as raw_handle, CsvRecordSplitter(
            file_by_contract,
            file_by_record_type,
            append=True,
            on_parser_error=self._parser_error,
        ) as splitter:
            _write_marker(raw_handle, "capture_started", device=self.config.device, baud=self.config.baud)
            factory = self._serial_factory()
            serial_exceptions = self._serial_exceptions()
            try:
                while not self.stop_event.is_set():
                    serial_handle = None
                    try:
                        _log_event(logging.INFO, "serial_opening", device=self.config.device, baud=self.config.baud)
                        serial_handle = factory(self.config.device, baudrate=self.config.baud, timeout=self.config.read_timeout_s)
                        _log_event(logging.INFO, "serial_opened", device=self.config.device, baud=self.config.baud)
                        _write_marker(raw_handle, "serial_opened", device=self.config.device, baud=self.config.baud)
                        backoff = self.config.reconnect_initial_s

                        while not self.stop_event.is_set():
                            data = serial_handle.read(self.config.read_size)
                            if data:
                                self._process_bytes(data, splitter, raw_handle)
                            now = time.monotonic()
                            if now >= next_status:
                                self._emit_status()
                                next_status = now + self.config.status_interval_s
                    except serial_exceptions as exc:
                        self.reconnect_count += 1
                        dropped = self.framer.drop_partial()
                        _log_event(
                            logging.WARNING,
                            "serial_disconnected",
                            reconnect_count=self.reconnect_count,
                            partial_line_dropped_bytes=dropped,
                            error=str(exc),
                        )
                        _write_marker(
                            raw_handle,
                            "serial_disconnected",
                            reconnect_count=self.reconnect_count,
                            partial_line_dropped_bytes=dropped,
                            error=str(exc),
                        )
                        if self.stop_event.is_set():
                            break
                        _log_event(logging.INFO, "reconnecting", delay_s=backoff)
                        _write_marker(raw_handle, "reconnecting", delay_s=backoff)
                        self.sleep(backoff)
                        backoff = min(self.config.reconnect_max_s, backoff * 2)
                    finally:
                        if serial_handle is not None:
                            try:
                                serial_handle.close()
                            except Exception as exc:  # noqa: BLE001 - close failures are diagnostic only.
                                _log_event(logging.WARNING, "serial_close_error", error=str(exc))
            finally:
                dropped = self.framer.drop_partial()
                if dropped:
                    _log_event(logging.WARNING, "partial_line_dropped", bytes=dropped, reason="shutdown")
                    _write_marker(raw_handle, "partial_line_dropped", bytes=dropped, reason="shutdown")
                _write_marker(
                    raw_handle,
                    "capture_stopped",
                    bytes_written=self.bytes_written,
                    lines_seen=self.lines_seen,
                    lines_parsed=self.lines_parsed,
                    malformed_utf8=self.malformed_utf8,
                    parser_errors=self.parser_errors,
                    reconnect_count=self.reconnect_count,
                )
                in_progress.unlink(missing_ok=True)
                self._emit_status()
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Own an OTIS USB serial device and append captured records to a run directory.")
    device_group = parser.add_mutually_exclusive_group(required=True)
    device_group.add_argument("--device", help="Serial device path, for example /dev/cu.usbmodem101.")
    device_group.add_argument("--auto-detect", action="store_true", help="Use the only /dev/cu.usbmodem* device if exactly one exists.")
    parser.add_argument("--baud", type=int, default=115200, help="Serial baud rate.")
    parser.add_argument("--run-dir", required=True, type=Path, help="Run directory to create/use.")
    parser.add_argument("--status-interval", type=float, default=60.0, help="Seconds between health log lines.")
    parser.add_argument("--read-size", type=int, default=4096, help="Bytes per serial read.")
    parser.add_argument("--max-line-bytes", type=int, default=65536, help="Maximum buffered partial line size.")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    device = _detect_single_device() if args.auto_detect else args.device
    config = CaptureDeviceConfig(
        device=device,
        baud=args.baud,
        run_dir=args.run_dir,
        read_size=args.read_size,
        status_interval_s=args.status_interval,
        max_line_bytes=args.max_line_bytes,
    )
    runner = CaptureDeviceRunner(config)
    signal.signal(signal.SIGINT, lambda signum, _frame: runner.request_stop(signum))
    signal.signal(signal.SIGTERM, lambda signum, _frame: runner.request_stop(signum))
    raise SystemExit(runner.run())


if __name__ == "__main__":
    main()
