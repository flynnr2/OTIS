from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import argparse
from contextlib import nullcontext
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
from .serial_commands import CommandFifo, parse_serial_command


LOGGER = logging.getLogger("otis.capture_device")
HOST_MARKER_PREFIX = b"# OTIS_HOST"


@dataclass(frozen=True)
class CaptureDeviceConfig:
    device: str
    baud: int
    run_dir: Path
    command_fifo: Path | None = None
    manifest_template: Path | None = None
    read_size: int = 4096
    read_timeout_s: float = 1.0
    reconnect_initial_s: float = 1.0
    reconnect_max_s: float = 30.0
    status_interval_s: float = 60.0
    max_line_bytes: int = 65536
    duration_s: float | None = None


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _log_event(level: int, event: str, **fields: object) -> None:
    details = " ".join(f"{key}={value!r}" for key, value in sorted(fields.items()))
    LOGGER.log(level, "event=%s%s", event, f" {details}" if details else "")


def _marker_bytes(event: str, **fields: object) -> bytes:
    payload = {"event": event, "utc": _utc_now(), **fields}
    return HOST_MARKER_PREFIX + b" " + json.dumps(payload, sort_keys=True).encode("utf-8") + b"\n"


class RawEvidenceWriter:
    """Keep host annotations between complete device records.

    Serial reads may end in the middle of a CSV record.  Holding only that
    final partial record lets command/audit markers wait for its terminating
    newline instead of being inserted into the device bytes.
    """

    def __init__(self, handle) -> None:
        self.handle = handle
        self.partial = bytearray()
        self.pending_markers: list[bytes] = []

    def _ensure_line_boundary(self) -> None:
        if self.handle.tell() == 0:
            return
        self.handle.seek(-1, 1)
        last_byte = self.handle.read(1)
        self.handle.seek(0, 2)
        if last_byte != b"\n":
            self.handle.write(b"\n")

    def _write_pending_markers(self) -> None:
        if not self.pending_markers:
            return
        for marker in self.pending_markers:
            self.handle.write(marker)
        self.pending_markers.clear()

    def write_device(self, data: bytes) -> None:
        self.partial.extend(data)
        while True:
            try:
                newline_index = self.partial.index(0x0A)
            except ValueError:
                break
            end = newline_index + 1
            self.handle.write(self.partial[:end])
            del self.partial[:end]
            self._write_pending_markers()
        self.handle.flush()

    def write_marker(self, event: str, **fields: object) -> None:
        marker = _marker_bytes(event, **fields)
        if self.partial:
            self.pending_markers.append(marker)
        else:
            self._ensure_line_boundary()
            self.handle.write(marker)
            self.handle.flush()

    def drop_partial(self) -> int:
        dropped = len(self.partial)
        self.partial.clear()
        self._ensure_line_boundary()
        self._write_pending_markers()
        self.handle.flush()
        return dropped


def _write_marker(raw_writer: RawEvidenceWriter, event: str, **fields: object) -> None:
    raw_writer.write_marker(event, **fields)


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


def _create_manifest_if_missing(
    run_dir: Path,
    device: str,
    baud: int,
    manifest_template: Path | None = None,
) -> None:
    manifest_path = find_manifest_path(run_dir)
    if manifest_path is not None:
        return
    if manifest_template is not None:
        with manifest_template.open("r", encoding="utf-8") as handle:
            manifest = json.load(handle)
        if (
            not isinstance(manifest, dict)
            or manifest.get("schema_version") != 1
            or manifest.get("template") is not True
            or not isinstance(manifest.get("files"), list)
            or not manifest["files"]
        ):
            raise ValueError("capture manifest template is invalid")
        now = _utc_now()
        manifest["run_id"] = run_dir.name
        manifest["created_utc"] = now
        manifest["started_at_utc"] = now
        manifest["template"] = False
        host = manifest.setdefault("host", {})
        if not isinstance(host, dict):
            raise ValueError("capture manifest template host field is invalid")
        host["serial_device"] = device
        host["baud"] = baud
        with (run_dir / "run_manifest.json").open("x", encoding="utf-8") as handle:
            json.dump(manifest, handle, indent=2)
            handle.write("\n")
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
            "pps_snapshots_v1": 1,
            "health_v1": 1,
            "dac_steps_v1": 1,
            "environment_v1": 1,
            "reference_observations_v1": 1,
            "diagnostics_v1": 1,
            "estimates_v2": 2,
            "control_previews_v1": 1,
            "active_transactions_v1": 1,
            "pseudo_pps_truth_v1": 1,
            "run_manifest_v1": 1,
        },
        "files": default_csv_files(),
        "expected_artifacts": [entry["path"] for entry in default_csv_files() if not entry.get("optional")],
        "environment_sources": [
            {"source": "sht4x", "role": "vcocxo_near", "primary_temperature": True},
            {"source": "bmp280", "role": "pressure_reference", "primary_temperature": False},
        ],
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
        self.discarding_oversize = False
        self.discarded_oversize_bytes = 0

    def feed(self, data: bytes) -> tuple[list[bytes], list[str]]:
        lines: list[bytes] = []
        events: list[str] = []
        self.buffer.extend(data)
        while True:
            if self.discarding_oversize:
                try:
                    newline_index = self.buffer.index(0x0A)
                except ValueError:
                    self.discarded_oversize_bytes += len(self.buffer)
                    self.buffer.clear()
                    break
                self.discarded_oversize_bytes += newline_index
                del self.buffer[: newline_index + 1]
                self.discarding_oversize = False
                self.discarded_oversize_bytes = 0
                continue
            try:
                newline_index = self.buffer.index(0x0A)
            except ValueError:
                break
            framed = bytes(self.buffer[:newline_index])
            del self.buffer[: newline_index + 1]
            if len(framed) > self.max_line_bytes:
                events.append(f"oversize_line_dropped bytes={len(framed)}")
                continue
            lines.append(framed.rstrip(b"\r"))
        if len(self.buffer) > self.max_line_bytes:
            dropped = len(self.buffer)
            self.discarding_oversize = True
            self.discarded_oversize_bytes = dropped
            self.buffer.clear()
            events.append(f"oversize_partial_line_dropped bytes={dropped}")
        return lines, events

    def drop_partial(self) -> int:
        dropped = self.discarded_oversize_bytes + len(self.buffer)
        self.buffer.clear()
        self.discarding_oversize = False
        self.discarded_oversize_bytes = 0
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
        self.commands_sent = 0
        self.commands_rejected = 0
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

    def _process_line(self, line: bytes, splitter: CsvRecordSplitter, raw_writer: RawEvidenceWriter) -> None:
        self.lines_seen += 1
        try:
            text = line.decode("utf-8")
        except UnicodeDecodeError as exc:
            self.malformed_utf8 += 1
            _log_event(logging.WARNING, "malformed_utf8", line_number=self.lines_seen, error=str(exc))
            _write_marker(raw_writer, "malformed_utf8", line_number=self.lines_seen, error=str(exc))
            return
        contract = splitter.process_line(text)
        if contract is not None:
            self.lines_parsed += 1

    def _parser_error(self, message: str) -> None:
        self.parser_errors += 1
        _log_event(logging.WARNING, "parser_error", message=message, parser_errors=self.parser_errors)

    def _process_bytes(self, data: bytes, splitter: CsvRecordSplitter, raw_writer: RawEvidenceWriter) -> None:
        raw_writer.write_device(data)
        self.bytes_written += len(data)
        lines, events = self.framer.feed(data)
        for event in events:
            _log_event(logging.WARNING, event)
            _write_marker(raw_writer, event)
        for line in lines:
            self._process_line(line, splitter, raw_writer)

    def _send_command(self, raw_command: str, serial_handle, raw_writer: RawEvidenceWriter) -> None:
        try:
            command = parse_serial_command(raw_command)
        except ValueError as exc:
            self.commands_rejected += 1
            _log_event(logging.WARNING, "host_command_rejected", command=raw_command, reason=str(exc))
            _write_marker(raw_writer, "host_command_rejected", command=raw_command, reason=str(exc))
            return

        payload = (command.normalized + "\n").encode("ascii")
        _log_event(logging.INFO, "host_command_accepted", command=command.normalized)
        _write_marker(raw_writer, "host_command_accepted", command=command.normalized)
        bytes_written = serial_handle.write(payload)
        flush = getattr(serial_handle, "flush", None)
        if flush is not None:
            flush()
        self.commands_sent += 1
        _log_event(logging.INFO, "host_command_sent", command=command.normalized, bytes_written=bytes_written)
        _write_marker(raw_writer, "host_command_sent", command=command.normalized, bytes_written=bytes_written)

    def _poll_commands(self, command_fifo: CommandFifo | None, serial_handle, raw_writer: RawEvidenceWriter) -> None:
        if command_fifo is None:
            return
        for raw_command in command_fifo.poll():
            self._send_command(raw_command, serial_handle, raw_writer)

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
            commands_sent=self.commands_sent,
            commands_rejected=self.commands_rejected,
        )

    def run(self) -> int:
        paths = ensure_run_layout(self.config.run_dir)
        _create_manifest_if_missing(
            self.config.run_dir,
            self.config.device,
            self.config.baud,
            self.config.manifest_template,
        )
        file_by_contract, file_by_record_type = _split_targets(self.config.run_dir)
        in_progress = self.config.run_dir / CAPTURE_IN_PROGRESS_FLAG
        in_progress.touch(exist_ok=True)
        backoff = self.config.reconnect_initial_s
        next_status = time.monotonic() + self.config.status_interval_s
        capture_deadline = (
            time.monotonic() + self.config.duration_s
            if self.config.duration_s is not None
            else None
        )
        duration_reached = False

        command_fifo_context = (
            CommandFifo(self.config.command_fifo) if self.config.command_fifo is not None else nullcontext(None)
        )
        with paths.raw_serial_log.open("a+b") as raw_handle, CsvRecordSplitter(
            file_by_contract,
            file_by_record_type,
            append=True,
            on_parser_error=self._parser_error,
        ) as splitter, command_fifo_context as command_fifo:
            raw_writer = RawEvidenceWriter(raw_handle)
            _write_marker(raw_writer, "capture_started", device=self.config.device, baud=self.config.baud)
            if self.config.command_fifo is not None:
                _write_marker(raw_writer, "command_ingress_opened", path=str(self.config.command_fifo))
            factory = self._serial_factory()
            serial_exceptions = self._serial_exceptions()
            try:
                while not self.stop_event.is_set():
                    serial_handle = None
                    try:
                        _log_event(logging.INFO, "serial_opening", device=self.config.device, baud=self.config.baud)
                        serial_handle = factory(self.config.device, baudrate=self.config.baud, timeout=self.config.read_timeout_s)
                        _log_event(logging.INFO, "serial_opened", device=self.config.device, baud=self.config.baud)
                        _write_marker(raw_writer, "serial_opened", device=self.config.device, baud=self.config.baud)
                        backoff = self.config.reconnect_initial_s

                        while not self.stop_event.is_set():
                            # After the planned duration, drain only the
                            # current device record.  Reading one byte at a
                            # time prevents a following record from being
                            # consumed before the capture can stop on the
                            # newline boundary.
                            read_size = 1 if duration_reached else self.config.read_size
                            data = serial_handle.read(read_size)
                            if data:
                                self._process_bytes(data, splitter, raw_writer)
                            self._poll_commands(command_fifo, serial_handle, raw_writer)
                            now = time.monotonic()
                            if capture_deadline is not None and now >= capture_deadline:
                                duration_reached = True
                            if (
                                duration_reached
                                and not raw_writer.partial
                                and not self.framer.buffer
                                and not self.framer.discarding_oversize
                            ):
                                _log_event(
                                    logging.INFO,
                                    "planned_duration_complete",
                                    duration_s=self.config.duration_s,
                                )
                                _write_marker(
                                    raw_writer,
                                    "planned_duration_complete",
                                    duration_s=self.config.duration_s,
                                )
                                self.stop_event.set()
                                break
                            if now >= next_status:
                                self._emit_status()
                                next_status = now + self.config.status_interval_s
                    except serial_exceptions as exc:
                        self.reconnect_count += 1
                        dropped = self.framer.drop_partial()
                        raw_writer.drop_partial()
                        _log_event(
                            logging.WARNING,
                            "serial_disconnected",
                            reconnect_count=self.reconnect_count,
                            partial_line_dropped_bytes=dropped,
                            error=str(exc),
                        )
                        _write_marker(
                            raw_writer,
                            "serial_disconnected",
                            reconnect_count=self.reconnect_count,
                            partial_line_dropped_bytes=dropped,
                            error=str(exc),
                        )
                        if self.stop_event.is_set():
                            break
                        _log_event(logging.INFO, "reconnecting", delay_s=backoff)
                        _write_marker(raw_writer, "reconnecting", delay_s=backoff)
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
                raw_writer.drop_partial()
                if dropped:
                    _log_event(logging.WARNING, "partial_line_dropped", bytes=dropped, reason="shutdown")
                    _write_marker(raw_writer, "partial_line_dropped", bytes=dropped, reason="shutdown")
                _write_marker(
                    raw_writer,
                    "capture_stopped",
                    bytes_written=self.bytes_written,
                    lines_seen=self.lines_seen,
                    lines_parsed=self.lines_parsed,
                    malformed_utf8=self.malformed_utf8,
                    parser_errors=self.parser_errors,
                    reconnect_count=self.reconnect_count,
                    commands_sent=self.commands_sent,
                    commands_rejected=self.commands_rejected,
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
    parser.add_argument(
        "--duration-s",
        type=float,
        help="Optional positive planned capture duration; closes normally when elapsed.",
    )
    parser.add_argument("--command-fifo", type=Path, help="Optional run-local FIFO for validated atomic host commands.")
    parser.add_argument(
        "--manifest-template",
        type=Path,
        help="Optional immutable JSON template used only when the run has no manifest; run_id is the run-directory name.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.duration_s is not None and args.duration_s <= 0:
        parser.error("--duration-s must be positive")
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
    device = _detect_single_device() if args.auto_detect else args.device
    config = CaptureDeviceConfig(
        device=device,
        baud=args.baud,
        run_dir=args.run_dir,
        command_fifo=args.command_fifo,
        manifest_template=args.manifest_template,
        read_size=args.read_size,
        status_interval_s=args.status_interval,
        max_line_bytes=args.max_line_bytes,
        duration_s=args.duration_s,
    )
    runner = CaptureDeviceRunner(config)
    signal.signal(signal.SIGINT, lambda signum, _frame: runner.request_stop(signum))
    signal.signal(signal.SIGTERM, lambda signum, _frame: runner.request_stop(signum))
    raise SystemExit(runner.run())


if __name__ == "__main__":
    main()
