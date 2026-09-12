from __future__ import annotations

import argparse
import csv
import glob
import json
import logging
import os
import signal
import subprocess
import tempfile
import threading
import time
from collections.abc import Callable
from contextlib import ExitStack
from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path

from .acquisition_frontier import FRONTIER_POLICY, AcquisitionFrontierTracker
from .active_status_live_state import (
    LIVE_STATE_PATH,
    ActiveStatusLiveReducer,
)
from .contracts import CONTRACT_FIELDS
from .record_splitter import CsvRecordSplitter, split_targets
from .run_loader import CAPTURE_IN_PROGRESS_FLAG, find_manifest_path, load_manifest
from .run_paths import ensure_run_layout
from .serial_commands import (
    CommandFifo,
    parse_serial_command,
    parse_timestamped_command_line,
)

LOGGER = logging.getLogger("otis.capture_device")
HOST_MARKER_PREFIX = b"# OTIS_HOST"
CAPTURE_STATE = Path("reports/capture_device_state.json")
CAPTURE_STATE_HEARTBEAT_S = 5.0
SEGMENT_PROTOCOL_ID = "otis_capture_closure_v1"
SEGMENT_CLOSURE = Path("reports/capture_segment_closure_v1.json")


def _serial_owner_pids(device: str) -> set[int]:
    result = subprocess.run(
        ["lsof", "-t", device], text=True, capture_output=True, check=False
    )
    if result.returncode not in {0, 1}:
        raise ValueError(f"cannot inspect serial owners: {result.stderr.strip()}")
    return {
        int(line) for line in result.stdout.splitlines() if line.strip().isdigit()
    }


def _capture_state_ready(run_dir: Path, pid: int) -> bool:
    path = run_dir / CAPTURE_STATE
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        state.get("pid") == pid
        and state.get("capture_active") is True
        and state.get("serial_open") is True
    )


@dataclass(frozen=True)
class CaptureDeviceConfig:
    device: str
    baud: int
    run_dir: Path
    command_fifo: Path | None = None
    emergency_command_fifo: Path | None = None
    read_size: int = 4096
    read_timeout_s: float = 1.0
    write_timeout_s: float = 1.0
    normal_command_max_age_s: float | None = None
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


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def _atomic_new_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite immutable capture artifact: {path}")
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class ActiveStatusLivePublisher:
    """Publish explicit active-snapshot states from flushed health records."""

    def __init__(self, run_dir: Path) -> None:
        self.path = run_dir / LIVE_STATE_PATH
        self.reducer = ActiveStatusLiveReducer()

    @property
    def active_snapshot_in_progress(self) -> bool:
        """Whether capture has begun but not completed an atomic ACTIVE burst."""

        return self.reducer.current_generation is not None

    def process_line(
        self, line: str, *, transport_generation: int
    ) -> None:
        try:
            values = next(csv.reader([line.strip()]))
        except csv.Error as exc:
            raise ValueError(
                f"cannot publish parsed live-health record: {exc}"
            ) from exc
        fields = CONTRACT_FIELDS["health_v1"]
        if len(values) != len(fields):
            raise ValueError("parsed live-health record width changed")
        update = self.reducer.observe(dict(zip(fields, values)))
        if update is None:
            return
        _atomic_json(
            self.path,
            {
                **update,
                "observed_utc": datetime.now(timezone.utc).isoformat().replace(
                    "+00:00", "Z"
                ),
                "observed_monotonic_ns": time.monotonic_ns(),
                "capture_pid": os.getpid(),
                "transport_generation": transport_generation,
            },
        )


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


def _resolve_requested_device(
    *,
    explicit_device: str | None,
    auto_detect: bool,
    expected_auto_detect_device: str | None,
) -> str:
    if expected_auto_detect_device is not None and not auto_detect:
        raise ValueError("--expected-auto-detect-device requires --auto-detect")
    device = _detect_single_device() if auto_detect else explicit_device
    if not isinstance(device, str) or not device:
        raise ValueError("serial device selection is unavailable")
    if (
        expected_auto_detect_device is not None
        and device != expected_auto_detect_device
    ):
        raise ValueError(
            "fresh capture auto-detect differs from the path frozen into "
            "the run manifest"
        )
    return device


def _require_exact_manifest(run_dir: Path) -> None:
    manifest_path = find_manifest_path(run_dir)
    if manifest_path is not None:
        return
    raise ValueError("capture requires an existing exact run manifest")


def _split_targets(run_dir: Path) -> tuple[dict[str, Path], dict[str, tuple[str, Path]]]:
    manifest_path = find_manifest_path(run_dir)
    if manifest_path is None:
        raise ValueError("capture requires an existing exact run manifest")
    manifest = load_manifest(run_dir).data
    return split_targets(manifest, run_dir)


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


class CaptureSink:
    """One logical evidence sink carried by an already-open serial owner."""

    def __init__(
        self,
        runner: CaptureDeviceRunner,
        *,
        run_dir: Path,
        command_fifo_path: Path | None,
        emergency_fifo_path: Path | None,
    ) -> None:
        self.runner = runner
        self.run_dir = run_dir.resolve()
        self.command_fifo_path = command_fifo_path
        self.emergency_fifo_path = emergency_fifo_path
        paths = ensure_run_layout(self.run_dir)
        _require_exact_manifest(self.run_dir)
        if (self.run_dir / SEGMENT_CLOSURE).exists():
            raise FileExistsError(
                "refusing to reopen a logically or physically closed capture segment: "
                f"{self.run_dir}"
            )
        self._stack = ExitStack()
        try:
            file_by_contract, file_by_record_type = _split_targets(self.run_dir)
            self.raw_handle = self._stack.enter_context(
                paths.raw_serial_log.open("a+b")
            )
            self.splitter = self._stack.enter_context(
                CsvRecordSplitter(
                    file_by_contract,
                    file_by_record_type,
                    append=True,
                    on_parser_error=runner._parser_error,
                )
            )
            self.command_fifo = (
                self._stack.enter_context(CommandFifo(command_fifo_path))
                if command_fifo_path is not None
                else None
            )
            self.emergency_fifo = (
                self._stack.enter_context(CommandFifo(emergency_fifo_path))
                if emergency_fifo_path is not None
                else None
            )
            self.in_progress = self.run_dir / CAPTURE_IN_PROGRESS_FLAG
            self.in_progress.touch(exist_ok=True)
            self.raw_writer = RawEvidenceWriter(self.raw_handle)
            self.active_status_live_publisher = ActiveStatusLivePublisher(
                self.run_dir
            )
            manifest_path = find_manifest_path(self.run_dir)
            if manifest_path is None:
                raise FileNotFoundError("capture segment has no manifest")
            manifest_value = load_manifest(self.run_dir).data
            self.acquisition_frontier_tracker = (
                AcquisitionFrontierTracker(self.run_dir, manifest_value)
                if manifest_value.get("acquisition_frontier") == FRONTIER_POLICY
                else None
            )
            self.closed = False
        except BaseException:
            self._stack.close()
            raise

    def start(self, *, generation: int, previous_run: str | None = None) -> None:
        _write_marker(
            self.raw_writer,
            "capture_started",
            device=self.runner.config.device,
            baud=self.runner.config.baud,
            owner_pid=os.getpid(),
            transport_generation=generation,
            previous_run=previous_run,
        )
        if self.command_fifo_path is not None:
            _write_marker(
                self.raw_writer,
                "command_ingress_opened",
                path=str(self.command_fifo_path),
                batch_limit=1,
                normal_command_max_age_s=self.runner.config.normal_command_max_age_s,
            )
        if self.emergency_fifo_path is not None:
            _write_marker(
                self.raw_writer,
                "emergency_command_ingress_opened",
                path=str(self.emergency_fifo_path),
            )

    def close(
        self,
        *,
        generation: int,
        physical_serial_open: bool,
    ) -> None:
        if self.closed:
            return
        _write_marker(
            self.raw_writer,
            "capture_stopped",
            bytes_written=self.runner.bytes_written,
            lines_seen=self.runner.lines_seen,
            lines_parsed=self.runner.lines_parsed,
            malformed_utf8=self.runner.malformed_utf8,
            parser_errors=self.runner.parser_errors,
            reconnect_count=self.runner.reconnect_count,
            commands_sent=self.runner.commands_sent,
            commands_rejected=self.runner.commands_rejected,
            normal_command_buffered_bytes_discarded=(
                self.runner.normal_command_buffered_bytes_discarded
            ),
            emergency_aborts_sent=self.runner.emergency_aborts_sent,
            emergency_abort_latched=self.runner.emergency_abort_latched,
            owner_pid=os.getpid(),
            transport_generation=generation,
        )
        manifest_path = find_manifest_path(self.run_dir)
        if manifest_path is None:
            raise FileNotFoundError("capture segment has no manifest to bind")
        _atomic_new_json(
            self.run_dir / SEGMENT_CLOSURE,
            {
                "schema_version": 1,
                "protocol": SEGMENT_PROTOCOL_ID,
                "closed_utc": _utc_now(),
                "run": str(self.run_dir),
                "run_manifest_sha256": sha256(manifest_path.read_bytes()).hexdigest(),
                "device": self.runner.config.device,
                "baud": self.runner.config.baud,
                "owner_pid": os.getpid(),
                "transport_generation": generation,
                "closure_mode": "physical_serial_close",
                "logical_segment_closed": True,
                "physical_serial_open": physical_serial_open,
                "serial_reopened": False,
                "counters": {
                    "bytes_written": self.runner.bytes_written,
                    "lines_seen": self.runner.lines_seen,
                    "lines_parsed": self.runner.lines_parsed,
                    "malformed_utf8": self.runner.malformed_utf8,
                    "parser_errors": self.runner.parser_errors,
                    "reconnect_count": self.runner.reconnect_count,
                    "commands_sent": self.runner.commands_sent,
                    "commands_rejected": self.runner.commands_rejected,
                    "emergency_aborts_sent": self.runner.emergency_aborts_sent,
                },
            },
        )
        self.in_progress.unlink(missing_ok=True)
        self.runner._write_state(
            run_dir=self.run_dir,
            capture_active=False,
            serial_open=physical_serial_open,
            logical_segment_closed=True,
            physical_serial_open=physical_serial_open,
            transport_generation=generation,
        )
        self._stack.close()
        self.closed = True

    def abandon_incomplete(self) -> None:
        """Close host resources while retaining the in-progress flag as evidence."""
        if self.closed:
            return
        self._stack.close()
        self.closed = True


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
        self.normal_command_buffered_bytes_discarded = 0
        self.emergency_aborts_sent = 0
        self.emergency_abort_latched = False
        self.emergency_abort_raw_frontier: dict[str, object] | None = None
        self.acquisition_frontier_observer_error: str | None = None
        self.capture_active = False
        self.serial_open = False
        self.framer = LineFramer(config.max_line_bytes)
        self.graceful_stop_requested = False
        self.current_run_dir = config.run_dir.resolve()
        self.transport_generation = 1
        self.current_command_fifo_configured = config.command_fifo is not None
        self.current_emergency_fifo_configured = (
            config.emergency_command_fifo is not None
        )

    def request_stop(self, signum: int | None = None) -> None:
        if signum == signal.SIGINT and not self.graceful_stop_requested:
            self.graceful_stop_requested = True
            _log_event(logging.INFO, "graceful_shutdown_requested", signal=signum)
            return
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

    def _process_line(
        self,
        line: bytes,
        splitter: CsvRecordSplitter,
        raw_writer: RawEvidenceWriter,
        active_status_live_publisher: ActiveStatusLivePublisher | None = None,
        acquisition_frontier_tracker: AcquisitionFrontierTracker | None = None,
    ) -> None:
        self.lines_seen += 1
        try:
            text = line.decode("utf-8")
        except UnicodeDecodeError as exc:
            self.malformed_utf8 += 1
            _log_event(logging.WARNING, "malformed_utf8", line_number=self.lines_seen, error=str(exc))
            _write_marker(raw_writer, "malformed_utf8", line_number=self.lines_seen, error=str(exc))
            if (
                acquisition_frontier_tracker is not None
                and self.acquisition_frontier_observer_error is None
            ):
                try:
                    acquisition_frontier_tracker.note_discrepancy(
                        f"malformed UTF-8 device record: {exc}",
                        line_number=self.lines_seen,
                    )
                except Exception as observer_error:
                    self._acquisition_frontier_observer_failed(observer_error)
            return
        parser_errors_before = self.parser_errors
        contract = splitter.process_line(text)
        if self.parser_errors != parser_errors_before:
            try:
                parsed_fields = next(csv.reader([text.strip()]))
            except csv.Error:
                parsed_fields = []
            _write_marker(
                raw_writer,
                "firmware_host_contract_discrepancy",
                line_number=self.lines_seen,
                raw_line=text.rstrip("\r\n"),
                parsed_fields=parsed_fields,
                parser_errors=self.parser_errors,
            )
            if (
                acquisition_frontier_tracker is not None
                and self.acquisition_frontier_observer_error is None
            ):
                try:
                    acquisition_frontier_tracker.note_discrepancy(
                        "firmware host contract parser rejected a device record",
                        line_number=self.lines_seen,
                    )
                except Exception as observer_error:
                    self._acquisition_frontier_observer_failed(observer_error)
        elif splitter.last_disposition in {
            "late_attach_boot_fragment",
            "raw_only_diagnostic",
        }:
            _write_marker(
                raw_writer,
                "firmware_raw_only_diagnostic",
                line_number=self.lines_seen,
                record_type=splitter.last_record_type,
                disposition=splitter.last_disposition,
            )
        if contract is not None:
            self.lines_parsed += 1
            if (
                acquisition_frontier_tracker is not None
                and self.acquisition_frontier_observer_error is None
                and splitter.last_record_type in {"REF", "SNP", "CNT", "APS", "EST"}
            ):
                fields = CONTRACT_FIELDS[contract]
                record = dict(zip(
                    fields,
                    next(csv.reader([text.strip()])),
                    strict=True,
                ))
                try:
                    target_handle = splitter.handle_by_record_type.get(
                        splitter.last_record_type
                    )
                    if target_handle is None:
                        target_handle = splitter.handle_by_contract[contract]
                    encoded_row = (text.strip() + "\n").encode("utf-8")
                    csv_byte_offset = target_handle.tell() - len(encoded_row)
                    prior_frontier_sha256 = (
                        acquisition_frontier_tracker.frontier.get("frontier_sha256")
                        if acquisition_frontier_tracker.frontier is not None
                        else None
                    )
                    acquisition_frontier_tracker.observe(
                        record,
                        line_number=self.lines_seen,
                        csv_byte_offset=csv_byte_offset,
                    )
                    established = acquisition_frontier_tracker.frontier
                    if prior_frontier_sha256 is None and established is not None:
                        acquisition_frontier_tracker.note_marker_search_offset(
                            raw_writer.handle.tell()
                        )
                        _write_marker(
                            raw_writer,
                            "acquisition_frontier_established",
                            frontier_sha256=established["frontier_sha256"],
                            capture_line_ordinal=self.lines_seen,
                        )
                except Exception as observer_error:
                    self._acquisition_frontier_observer_failed(observer_error)
            if (
                contract == "health_v1"
                and active_status_live_publisher is not None
            ):
                active_status_live_publisher.process_line(
                    text,
                    transport_generation=self.transport_generation,
                )

    def _parser_error(self, message: str) -> None:
        self.parser_errors += 1
        _log_event(logging.WARNING, "parser_error", message=message, parser_errors=self.parser_errors)
        self._emit_status()

    def _acquisition_frontier_observer_failed(self, error: Exception) -> None:
        """Latch a diagnostic authority hold without stopping serial capture."""

        if self.acquisition_frontier_observer_error is not None:
            return
        self.acquisition_frontier_observer_error = (
            f"{type(error).__name__}: {error}"
        )
        self._parser_error(
            "acquisition frontier observer failed: "
            + self.acquisition_frontier_observer_error
        )

    def _process_bytes(
        self,
        data: bytes,
        splitter: CsvRecordSplitter,
        raw_writer: RawEvidenceWriter,
        active_status_live_publisher: ActiveStatusLivePublisher | None = None,
        acquisition_frontier_tracker: AcquisitionFrontierTracker | None = None,
        before_line_processing: Callable[[], None] | None = None,
    ) -> None:
        raw_writer.write_device(data)
        self.bytes_written += len(data)
        lines, events = self.framer.feed(data)
        for event in events:
            _log_event(logging.WARNING, event)
            _write_marker(raw_writer, event)
            if (
                acquisition_frontier_tracker is not None
                and self.acquisition_frontier_observer_error is None
            ):
                try:
                    acquisition_frontier_tracker.note_discrepancy(event)
                except Exception as observer_error:
                    self._acquisition_frontier_observer_failed(observer_error)
        # A full serial read can contain many telemetry rows.  Service command
        # ingress after the bytes are durably ordered in raw evidence but
        # before CSV/status consumers process the batch, so consumer latency
        # cannot exhaust the command freshness and acknowledgement bounds.
        if before_line_processing is not None:
            before_line_processing()
        for line in lines:
            self._process_line(
                line,
                splitter,
                raw_writer,
                active_status_live_publisher,
                acquisition_frontier_tracker,
            )

    def _send_command(
        self,
        raw_command: str,
        serial_handle,
        raw_writer: RawEvidenceWriter,
        *,
        priority: bool = False,
    ) -> None:
        try:
            command, created_monotonic_ns = parse_timestamped_command_line(
                raw_command
            )
            if not priority and self.config.normal_command_max_age_s is not None:
                if created_monotonic_ns is None:
                    raise ValueError(
                        "normal command lacks required OTISQ1 timestamp envelope"
                    )
                age_s = (
                    time.monotonic_ns() - created_monotonic_ns
                ) / 1_000_000_000
                if age_s < 0 or age_s > self.config.normal_command_max_age_s:
                    raise ValueError(
                        "normal command timestamp is stale or from the future: "
                        f"age_s={age_s:.6f} limit_s="
                        f"{self.config.normal_command_max_age_s:.6f}"
                    )
        except ValueError as exc:
            self.commands_rejected += 1
            _log_event(logging.WARNING, "host_command_rejected", command=raw_command, reason=str(exc))
            _write_marker(raw_writer, "host_command_rejected", command=raw_command, reason=str(exc))
            self._emit_status()
            return

        payload = (command.normalized + "\n").encode("ascii")
        _log_event(logging.INFO, "host_command_accepted", command=command.normalized)
        _write_marker(raw_writer, "host_command_accepted", command=command.normalized)
        bytes_written = serial_handle.write(payload)
        if bytes_written != len(payload):
            raise OSError(
                "short serial command write: "
                f"expected {len(payload)} bytes, wrote {bytes_written}"
            )
        self.commands_sent += 1
        _log_event(logging.INFO, "host_command_sent", command=command.normalized, bytes_written=bytes_written)
        _write_marker(raw_writer, "host_command_sent", command=command.normalized, bytes_written=bytes_written)
        self._emit_status()

    def _poll_commands(self, command_fifo: CommandFifo | None, serial_handle, raw_writer: RawEvidenceWriter) -> None:
        if command_fifo is None:
            return
        for raw_command in command_fifo.poll(max_lines=1):
            self._send_command(raw_command, serial_handle, raw_writer)

    def _poll_command_ingress(
        self,
        emergency_fifo: CommandFifo | None,
        command_fifo: CommandFifo | None,
        serial_handle,
        raw_writer: RawEvidenceWriter,
    ) -> None:
        if self.graceful_stop_requested:
            return
        self._poll_emergency_command(
            emergency_fifo,
            command_fifo,
            serial_handle,
            raw_writer,
        )
        if not self.emergency_abort_latched:
            self._poll_commands(command_fifo, serial_handle, raw_writer)

    def _poll_emergency_command(
        self,
        emergency_fifo: CommandFifo | None,
        command_fifo: CommandFifo | None,
        serial_handle,
        raw_writer: RawEvidenceWriter,
    ) -> None:
        if emergency_fifo is None:
            return
        emergency_commands = emergency_fifo.poll(max_lines=1)
        if not emergency_commands:
            return
        raw_command = emergency_commands[0]
        try:
            command = parse_serial_command(raw_command)
        except ValueError as exc:
            _write_marker(
                raw_writer,
                "emergency_command_ingress_fault",
                command=raw_command,
                reason=str(exc),
            )
            command = parse_serial_command("ACTIVE ABORT")
        if command.normalized != "ACTIVE ABORT":
            _write_marker(
                raw_writer,
                "emergency_command_ingress_fault",
                command=command.normalized,
                reason="emergency FIFO accepts ACTIVE ABORT only",
            )
            command = parse_serial_command("ACTIVE ABORT")
        if self.emergency_abort_latched:
            _write_marker(raw_writer, "emergency_abort_duplicate_ignored")
            return

        self.emergency_abort_latched = True
        _write_marker(raw_writer, "emergency_abort_latched")
        if command_fifo is not None:
            buffered = len(command_fifo.buffer)
            command_fifo.close()
            command_fifo.buffer.clear()
            self.normal_command_buffered_bytes_discarded += buffered
            _write_marker(
                raw_writer,
                "normal_command_ingress_revoked",
                buffered_bytes_discarded=buffered,
            )
        self._send_command(
            "ACTIVE ABORT", serial_handle, raw_writer, priority=True
        )
        self.emergency_aborts_sent += 1
        # This is a search frontier, not proof of marker persistence: a partial
        # device line may defer the marker until its newline arrives.
        raw_identity = os.fstat(raw_writer.handle.fileno())
        self.emergency_abort_raw_frontier = {
            "run_directory": str(self.current_run_dir),
            "search_offset_bytes": raw_writer.handle.tell(),
            "device": raw_identity.st_dev,
            "inode": raw_identity.st_ino,
        }
        _write_marker(raw_writer, "emergency_abort_sent")
        self._emit_status()

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
            normal_command_buffered_bytes_discarded=(
                self.normal_command_buffered_bytes_discarded
            ),
            emergency_aborts_sent=self.emergency_aborts_sent,
            emergency_abort_latched=self.emergency_abort_latched,
        )
        self._write_state()

    def _write_state(
        self,
        *,
        run_dir: Path | None = None,
        capture_active: bool | None = None,
        serial_open: bool | None = None,
        logical_segment_closed: bool = False,
        physical_serial_open: bool | None = None,
        transport_generation: int | None = None,
    ) -> None:
        target = self.current_run_dir if run_dir is None else run_dir
        effective_capture_active = (
            self.capture_active if capture_active is None else capture_active
        )
        effective_serial_open = self.serial_open if serial_open is None else serial_open
        _atomic_json(
            target / CAPTURE_STATE,
            {
                "schema_version": 1,
                "updated_utc": _utc_now(),
                "updated_monotonic_ns": time.monotonic_ns(),
                "pid": os.getpid(),
                "capture_active": effective_capture_active,
                "serial_open": effective_serial_open,
                "logical_segment_closed": logical_segment_closed,
                "physical_serial_open": (
                    effective_serial_open
                    if physical_serial_open is None
                    else physical_serial_open
                ),
                "transport_generation": (
                    self.transport_generation
                    if transport_generation is None
                    else transport_generation
                ),
                "bytes_written": self.bytes_written,
                "lines_seen": self.lines_seen,
                "lines_parsed": self.lines_parsed,
                "malformed_utf8": self.malformed_utf8,
                "parser_errors": self.parser_errors,
                "acquisition_frontier_observer_error": (
                    self.acquisition_frontier_observer_error
                ),
                "reconnect_count": self.reconnect_count,
                "serial_exclusive_requested": self.serial_factory is None,
                "commands_sent": self.commands_sent,
                "commands_rejected": self.commands_rejected,
                "normal_command_buffered_bytes_discarded": (
                    self.normal_command_buffered_bytes_discarded
                ),
                "emergency_aborts_sent": self.emergency_aborts_sent,
                "emergency_abort_latched": self.emergency_abort_latched,
                "emergency_abort_raw_frontier": self.emergency_abort_raw_frontier,
                "command_fifo_configured": (
                    self.current_command_fifo_configured
                ),
                "emergency_command_fifo_configured": (
                    self.current_emergency_fifo_configured
                ),
                "state_heartbeat_interval_s": CAPTURE_STATE_HEARTBEAT_S,
                "normal_command_batch_limit": 1,
                "normal_command_max_age_s": (
                    self.config.normal_command_max_age_s
                ),
                "write_timeout_s": self.config.write_timeout_s,
            },
        )

    def run(self) -> int:
        sink = CaptureSink(
            self,
            run_dir=self.current_run_dir,
            command_fifo_path=self.config.command_fifo,
            emergency_fifo_path=self.config.emergency_command_fifo,
        )
        self.capture_active = True
        self._emit_status()
        backoff = self.config.reconnect_initial_s
        next_status = time.monotonic() + self.config.status_interval_s
        next_state = time.monotonic() + CAPTURE_STATE_HEARTBEAT_S
        capture_deadline = (
            time.monotonic() + self.config.duration_s
            if self.config.duration_s is not None
            else None
        )
        duration_reached = False
        try:
            sink.start(generation=self.transport_generation)
            raw_writer = sink.raw_writer
            splitter = sink.splitter
            command_fifo = sink.command_fifo
            emergency_fifo = sink.emergency_fifo
            self._emit_status()
            factory = self._serial_factory()
            serial_exceptions = self._serial_exceptions()
            try:
                while not self.stop_event.is_set():
                    serial_handle = None
                    try:
                        _log_event(logging.INFO, "serial_opening", device=self.config.device, baud=self.config.baud)
                        serial_kwargs = {
                            "baudrate": self.config.baud,
                            "timeout": self.config.read_timeout_s,
                            "write_timeout": self.config.write_timeout_s,
                        }
                        if self.serial_factory is None:
                            serial_kwargs["exclusive"] = True
                        serial_handle = factory(
                            self.config.device,
                            **serial_kwargs,
                        )
                        _log_event(logging.INFO, "serial_opened", device=self.config.device, baud=self.config.baud)
                        self.serial_open = True
                        self._emit_status()
                        _write_marker(raw_writer, "serial_opened", device=self.config.device, baud=self.config.baud)
                        backoff = self.config.reconnect_initial_s

                        while not self.stop_event.is_set():
                            if not self.graceful_stop_requested:
                                self._poll_emergency_command(
                                    emergency_fifo,
                                    command_fifo,
                                    serial_handle,
                                    raw_writer,
                                )
                            # A planned or requested stop drains the current
                            # device record before closing.
                            # Reading one byte at a time prevents a following
                            # record from being consumed before the capture
                            # can stop on the newline boundary.
                            drain_to_boundary = duration_reached or self.graceful_stop_requested
                            read_size = 1 if drain_to_boundary else self.config.read_size
                            data = serial_handle.read(read_size)
                            if data:
                                self._process_bytes(
                                    data,
                                    splitter,
                                    raw_writer,
                                    sink.active_status_live_publisher,
                                    sink.acquisition_frontier_tracker,
                                    before_line_processing=lambda: self._poll_command_ingress(
                                        emergency_fifo,
                                        command_fifo,
                                        serial_handle,
                                        raw_writer,
                                    ),
                                )
                            # Abort may arrive while the serial read or a
                            # downstream consumer is blocked.  Recheck the
                            # priority path at the final boundary before any
                            # normal command.
                            self._poll_command_ingress(
                                emergency_fifo,
                                command_fifo,
                                serial_handle,
                                raw_writer,
                            )
                            now = time.monotonic()
                            if capture_deadline is not None and now >= capture_deadline:
                                duration_reached = True
                            if (
                                (duration_reached or self.graceful_stop_requested)
                                and not raw_writer.partial
                                and not self.framer.buffer
                                and not self.framer.discarding_oversize
                                # A complete serial line is not necessarily a
                                # complete control-plane record: ACTIVE status
                                # is an atomic multi-line generation.  Drain a
                                # generation already begun before closing so a
                                # terminal query cannot replace the last
                                # complete snapshot with an in-progress one.
                                and not sink.active_status_live_publisher.active_snapshot_in_progress
                            ):
                                if duration_reached:
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
                                else:
                                    _log_event(
                                        logging.INFO,
                                        "graceful_shutdown_complete",
                                    )
                                    _write_marker(
                                        raw_writer,
                                        "graceful_shutdown_complete",
                                    )
                                self.stop_event.set()
                                break
                            if now >= next_status:
                                self._emit_status()
                                next_status = now + self.config.status_interval_s
                                next_state = now + CAPTURE_STATE_HEARTBEAT_S
                            elif now >= next_state:
                                self._write_state()
                                next_state = now + CAPTURE_STATE_HEARTBEAT_S
                    except serial_exceptions as exc:
                        self.serial_open = False
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
                        self._emit_status()
                        if (
                            self.current_emergency_fifo_configured
                        ):
                            self.emergency_abort_latched = True
                            if command_fifo is not None:
                                command_fifo.close()
                                command_fifo.buffer.clear()
                            _write_marker(
                                raw_writer,
                                "active_command_transport_fail_static_stop",
                                error=str(exc),
                            )
                            self.stop_event.set()
                            break
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
                                self.serial_open = False
                            except Exception as exc:  # noqa: BLE001 - close failures are diagnostic only.
                                _log_event(logging.WARNING, "serial_close_error", error=str(exc))
            finally:
                dropped = self.framer.drop_partial()
                raw_writer.drop_partial()
                if dropped:
                    _log_event(logging.WARNING, "partial_line_dropped", bytes=dropped, reason="shutdown")
                    _write_marker(raw_writer, "partial_line_dropped", bytes=dropped, reason="shutdown")
                self.capture_active = False
                self.serial_open = False
                sink.close(
                    generation=self.transport_generation,
                    physical_serial_open=False,
                )
        finally:
            if not sink.closed:
                self.capture_active = False
                self.serial_open = False
                sink.close(
                    generation=self.transport_generation,
                    physical_serial_open=False,
                )
        return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Own an OTIS USB serial device and append captured records to a run directory.")
    device_group = parser.add_mutually_exclusive_group(required=True)
    device_group.add_argument("--device", help="Serial device path, for example /dev/cu.usbmodem101.")
    device_group.add_argument("--auto-detect", action="store_true", help="Use the only /dev/cu.usbmodem* device if exactly one exists.")
    parser.add_argument(
        "--expected-auto-detect-device",
        help=(
            "With --auto-detect, require the capture process's exactly-one "
            "resolution to equal this freshly resolved manifest path."
        ),
    )
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
        "--emergency-command-fifo",
        type=Path,
        help=(
            "Optional independent priority FIFO accepting ACTIVE ABORT only; "
            "its presence makes serial transport faults fail-static."
        ),
    )
    parser.add_argument(
        "--write-timeout-s",
        type=float,
        default=1.0,
        help="Positive serial-command write timeout; no tcdrain flush is used.",
    )
    parser.add_argument(
        "--normal-command-max-age-s",
        type=float,
        help=(
            "Require OTISQ1 monotonic timestamp envelopes on normal commands "
            "and reject commands older than this positive bound."
        ),
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.duration_s is not None and args.duration_s <= 0:
        parser.error("--duration-s must be positive")
    if args.write_timeout_s <= 0:
        parser.error("--write-timeout-s must be positive")
    if (
        args.normal_command_max_age_s is not None
        and args.normal_command_max_age_s <= 0
    ):
        parser.error("--normal-command-max-age-s must be positive")
    if args.emergency_command_fifo is not None and args.command_fifo is None:
        parser.error("--emergency-command-fifo requires --command-fifo")
    if (
        args.emergency_command_fifo is not None
        and args.normal_command_max_age_s is None
    ):
        parser.error(
            "--emergency-command-fifo requires "
            "--normal-command-max-age-s"
        )
    if (
        args.emergency_command_fifo is not None
        and args.command_fifo is not None
        and args.emergency_command_fifo.absolute()
        == args.command_fifo.absolute()
    ):
        parser.error("normal and emergency command FIFOs must be distinct")
    log_path = args.run_dir / "reports/capture_device.log"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
        filename=log_path,
        filemode="a",
        force=True,
    )
    try:
        device = _resolve_requested_device(
            explicit_device=args.device,
            auto_detect=args.auto_detect,
            expected_auto_detect_device=args.expected_auto_detect_device,
        )
    except ValueError as exc:
        parser.error(str(exc))
    config = CaptureDeviceConfig(
        device=device,
        baud=args.baud,
        run_dir=args.run_dir,
        command_fifo=args.command_fifo,
        emergency_command_fifo=args.emergency_command_fifo,
        read_size=args.read_size,
        write_timeout_s=args.write_timeout_s,
        normal_command_max_age_s=args.normal_command_max_age_s,
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
