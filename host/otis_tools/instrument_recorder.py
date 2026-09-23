"""Passive, single-owner serial recorder for the firmware-owned instrument.

The recorder has no steering timer or scientific decision path. A local Unix
socket lets an explicit client submit a mode request through its serial owner.
"""
from __future__ import annotations

import csv
import hashlib
import json
import os
import socket
import tempfile
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .firmware_host_contract import ACTIVE_STATUS_KEYS


STATE = "recorder_state.json"
RESERVATION = "recorder.in_progress"
MAX_REQUEST_BYTES = 1024
UINT32_MAX = 0xFFFFFFFF
UINT64_MAX = 0xFFFFFFFFFFFFFFFF
INSTRUMENT_MODES = frozenset({"AUTO_DISCIPLINE", "OBSERVE_HOLD", "FIXED_CODE", "CHARACTERIZE"})
INSTRUMENT_STATES = frozenset({
    "STARTUP", "APPLICATION_PENDING", "REFERENCE_HOLD", "METADATA_HOLD",
    "RESPONSE_PENDING", "ACQUIRING_OR_TRACKING", "CONTROLLER_HOLD",
    "INTEGRITY_FAULT", *INSTRUMENT_MODES,
})
STATUS_KEYS = frozenset(ACTIVE_STATUS_KEYS) | {"snapshot_contract"}


def socket_path(run_dir: Path) -> Path:
    identity = hashlib.sha256(str(run_dir.resolve()).encode("utf-8")).hexdigest()[:20]
    return Path(tempfile.gettempdir()) / f"otis-recorder-{identity}.sock"


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _atomic_json(path: Path, value: dict) -> None:
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent,
                                     prefix=f".{path.name}.", delete=False) as handle:
        json.dump(value, handle, sort_keys=True, indent=2, allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def passive_serial_open(device: str, baud: int, *, serial_module=None):
    """Attach with CDC carrier enabled without the RP2040 1200-baud reset."""
    if baud <= 0 or baud == 1200:
        raise ValueError("baud must be positive and must not be the RP2040 reset rate 1200")
    if serial_module is None:
        import serial as serial_module  # type: ignore[no-redef]
    port = serial_module.Serial(port=None, baudrate=baud, timeout=0.1,
                                write_timeout=0.5, exclusive=True)
    try:
        # TinyUSB reports CDC connected only while DTR is high. The pinned
        # RP2040 core resets only for 1200 baud with DTR low.
        port.dtr = True
        port.rts = False
        port.port = device
        port.open()
        # Some drivers reassert controls on open; restore and verify the
        # requested low level before treating attachment as established.
        port.dtr = True
        port.rts = False
        if not port.dtr or port.rts:
            raise OSError("serial modem-control outputs did not remain at CDC carrier state")
        return port
    except BaseException:
        port.close()
        raise


def parse_status_row(line: bytes) -> tuple[str, str, str] | None:
    """Return component, key, value from a well-formed health STS record."""
    try:
        row = next(csv.reader([line.decode("ascii")]))
    except (UnicodeError, csv.Error):
        return None
    if len(row) != 10 or row[:2] != ["STS", "1"]:
        return None
    if (not row[2].isdigit() or not row[3].isdigit()
            or row[4] not in {"rp2040_monotonic_us32", "rp2040_timer_us64"}):
        return None
    return row[5], row[6], row[7]


def parse_instrument_status(fields: dict[str, str]) -> dict | None:
    """Validate one complete instrument generation, not a mixed STS prefix."""
    if set(fields) != STATUS_KEYS:
        return None
    if fields["snapshot_contract"] != "OTIS_INSTRUMENT_STATUS_V2":
        return None
    if (fields["mode"] not in INSTRUMENT_MODES or
            fields["requested_mode"] not in INSTRUMENT_MODES or
            fields["state"] not in INSTRUMENT_STATES or
            fields["instrument_ticks_domain"] != "rp2040_timer_us64"):
        return None
    try:
        session, sequence, completed, code, dac_epoch = map(
            int, (fields["session_id"], fields["command_sequence"],
                  fields["command_completed"], fields["applied_code"], fields["dac_epoch"])
        )
    except ValueError:
        return None
    if not (0 < session <= UINT64_MAX and 0 <= completed <= sequence <= UINT32_MAX
            and 0 <= code <= 0xFFFF and 0 <= dac_epoch <= UINT32_MAX):
        return None
    if fields["confirmed_applied_code_known"] not in {"true", "false"}:
        return None
    return {
        "session": session, "last_command_sequence": sequence,
        "completed_command_sequence": completed, "mode": fields["mode"],
        "requested_mode": fields["requested_mode"], "state": fields["state"],
        "applied_code": code, "applied_code_known": fields["confirmed_applied_code_known"] == "true",
        "dac_epoch": dac_epoch, "reason": fields["reason"],
        "build_identity": fields.get("build_identity"),
        "policy_identity": fields.get("active_policy_sha256"),
        "fields": dict(fields),
    }


@dataclass(frozen=True)
class RecorderConfig:
    device: str
    run_dir: Path
    baud: int = 115200
    duration_s: float | None = None
    rotate_bytes: int = 128 * 1024 * 1024
    status_interval_s: float = 1.0
    status_fresh_s: float = 10.0


class InstrumentRecorder:
    def __init__(self, config: RecorderConfig, *, serial_factory=passive_serial_open,
                 monotonic=time.monotonic) -> None:
        if not config.device or config.baud <= 0 or config.baud == 1200 or config.rotate_bytes <= 0:
            raise ValueError("device and rotate_bytes must be positive; baud must not be 1200")
        if config.duration_s is not None and config.duration_s <= 0:
            raise ValueError("duration_s must be positive")
        self.config = config
        self.serial_factory = serial_factory
        self.monotonic = monotonic
        self.run_dir = config.run_dir.resolve()
        self.port = None
        self.server = None
        self.raw = None
        self.raw_size = 0
        self.segment = 0
        self.segments: list[dict] = []
        self.bytes_recorded = 0
        self.lines_seen = 0
        self.invalid_status = 0
        self.instrument: dict | None = None
        self.instrument_at: float | None = None
        self.last_record_at: float | None = None
        self.record_counts = {key: 0 for key in ("REF", "SNP", "CNT", "APS", "EST", "IAP", "IRS", "ICM")}
        self.last_receipt: dict | None = None
        self.pending_command: dict | None = None
        self.partial = bytearray()
        self.partial_overflow = False
        self.status_fields: dict[str, str] | None = None
        self.status_generation = 0
        self.completed_generation = 0
        self.last_sequence = 0
        self.started = self.monotonic()
        self.last_state_write = 0.0
        self.error: str | None = None
        self.running = False

    def _state(self) -> dict:
        age = None if self.instrument_at is None else max(0.0, self.monotonic() - self.instrument_at)
        record_age = None if self.last_record_at is None else max(0.0, self.monotonic() - self.last_record_at)
        return {
            "schema_version": 1, "pid": os.getpid(), "device": self.config.device,
            "started_utc": self.started_utc, "observed_utc": _utc(),
            "observed_monotonic_ns": time.monotonic_ns(),
            "status_interval_s": self.config.status_interval_s,
            "instrument_fresh_limit_s": self.config.status_fresh_s,
            "recording": self.running, "serial_open": self.port is not None,
            "bytes_recorded": self.bytes_recorded, "lines_seen": self.lines_seen,
            "invalid_status_records": self.invalid_status,
            "segment": self.segment, "instrument": self.instrument,
            "instrument_age_s": age,
            "instrument_fresh": age is not None and age <= self.config.status_fresh_s,
            "last_record_age_s": record_age, "observed_record_counts": dict(self.record_counts),
            "last_command_receipt": self.last_receipt,
            "pending_command": self.pending_command,
            "recording_error": self.error,
        }

    def _publish(self) -> None:
        _atomic_json(self.run_dir / STATE, self._state())
        self.last_state_write = self.monotonic()

    def _open_segment(self) -> None:
        self.segment += 1
        path = self.run_dir / f"serial-{self.segment:04d}.raw"
        self.raw = path.open("xb", buffering=0)
        self.raw_size = 0
        self.segments.append({"path": path.name, "bytes": 0})

    def _close_segment(self) -> None:
        if self.raw is None:
            return
        self.raw.flush()
        os.fsync(self.raw.fileno())
        self.raw.close()
        self.raw = None
        entry = self.segments[-1]
        path = self.run_dir / entry["path"]
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
        entry["sha256"] = digest.hexdigest()

    def _write_raw(self, data: bytes) -> None:
        if self.raw is None:
            raise RuntimeError("raw segment unavailable")
        view = memoryview(data)
        while view:
            count = self.raw.write(view)
            if count is None or count <= 0:
                raise OSError("raw evidence write made no progress")
            view = view[count:]
        self.raw_size += len(data)
        self.bytes_recorded += len(data)
        self.segments[-1]["bytes"] = self.raw_size
        if self.raw_size >= self.config.rotate_bytes:
            self._close_segment()
            self._open_segment()

    def _observe(self, data: bytes) -> None:
        # Parsing is advisory. Raw bytes have already been written. A corrupt
        # or unbounded line cannot consume unbounded memory or erase evidence.
        self.partial.extend(data)
        while True:
            end = self.partial.find(b"\n")
            if end < 0:
                if len(self.partial) > 8192:
                    self.partial.clear()
                    self.partial_overflow = True
                return
            line = bytes(self.partial[:end]).rstrip(b"\r")
            del self.partial[:end + 1]
            self.lines_seen += 1
            self.last_record_at = self.monotonic()
            if self.partial_overflow:
                self.partial_overflow = False
                continue
            tag = line.split(b",", 1)[0].decode("ascii", errors="ignore")
            if tag in self.record_counts:
                self.record_counts[tag] += 1
            if tag == "ICM":
                self._observe_receipt(line)
            if not line.startswith(b"STS,"):
                continue
            parsed = parse_status_row(line)
            if parsed is None:
                self.invalid_status += 1
                self.status_fields = None
                continue
            component, key, value = parsed
            if component != "adaptive_hybrid":
                continue
            if key == "snapshot_generation_begin":
                try:
                    generation = int(value)
                except ValueError:
                    generation = 0
                if generation <= 0 or self.status_fields is not None:
                    self.invalid_status += 1
                    self.status_fields = None
                else:
                    self.status_generation = generation
                    self.status_fields = {}
                continue
            if self.status_fields is None:
                continue
            if key == "snapshot_generation_complete":
                if value != str(self.status_generation):
                    self.invalid_status += 1
                    self.status_fields = None
                    continue
                status = parse_instrument_status(self.status_fields)
                self.status_fields = None
                if status is None:
                    self.invalid_status += 1
                    continue
                if self.instrument and status["session"] != self.instrument["session"]:
                    self.last_sequence = 0
                    self.completed_generation = 0
                elif self.instrument and self.status_generation <= self.completed_generation:
                    self.invalid_status += 1
                    continue
                elif self.instrument and status["last_command_sequence"] < self.instrument["last_command_sequence"]:
                    self.invalid_status += 1
                    continue
                self.instrument = status
                self.completed_generation = self.status_generation
                self.instrument_at = self.monotonic()
                self.last_sequence = max(self.last_sequence, status["last_command_sequence"])
                if (self.pending_command is not None
                        and status["session"] == self.pending_command["session"]
                        and status["completed_command_sequence"] >= self.pending_command["sequence"]):
                    self.pending_command = None
                self._publish()
                continue
            if key in self.status_fields:
                self.invalid_status += 1
                self.status_fields = None
                continue
            if key not in STATUS_KEYS or len(self.status_fields) >= len(STATUS_KEYS):
                self.invalid_status += 1
                self.status_fields = None
                continue
            self.status_fields[key] = value

    def _observe_receipt(self, line: bytes) -> None:
        try:
            row = next(csv.reader([line.decode("ascii")]))
            if len(row) != 12 or row[:2] != ["ICM", "2"] or row[11] != "rp2040_timer_us64":
                return
            record_sequence, session, sequence, mode, code, dwell, completed, ticks = map(
                int, (row[2], row[3], row[4], row[5], row[6], row[7], row[9], row[10]))
            if row[8] not in {"ACCEPTED", "REJECTED", "DUPLICATE"}:
                return
            self.last_receipt = {
                "record_sequence": record_sequence, "session": session,
                "sequence": sequence, "mode": mode,
                "code": code, "dwell_s": dwell, "result": row[8],
                "command_completed": completed, "ticks": ticks,
                "ticks_domain": row[11],
            }
            if (self.pending_command is not None
                    and (session, sequence) == (self.pending_command["session"], self.pending_command["sequence"])):
                if row[8] == "REJECTED" or completed >= sequence:
                    self.pending_command = None
                else:
                    self.pending_command["receipt"] = row[8]
            self._publish()
        except (UnicodeError, ValueError, csv.Error):
            return

    def _reply(self, client: socket.socket, value: dict) -> None:
        client.sendall((json.dumps(value, sort_keys=True) + "\n").encode("utf-8"))

    def _serve_one(self) -> None:
        if self.server is None:
            return
        try:
            client, _ = self.server.accept()
        except BlockingIOError:
            return
        with client:
            client.settimeout(0.2)
            try:
                request = client.recv(MAX_REQUEST_BYTES + 1)
                if len(request) > MAX_REQUEST_BYTES or not request.endswith(b"\n"):
                    raise ValueError("request must be one bounded JSON line")
                value = json.loads(request)
                if not isinstance(value, dict):
                    raise ValueError("request must be an object")
                if value.get("operation") == "status":
                    result = self._state()
                elif value.get("operation") == "mode":
                    result = self._mode_request(value)
                else:
                    raise ValueError("unsupported operation")
                self._reply(client, result)
            except (ValueError, OSError, json.JSONDecodeError) as exc:
                try:
                    self._reply(client, {"error": str(exc)})
                except OSError:
                    pass

    def _mode_request(self, request: dict) -> dict:
        status = self.instrument
        if (status is None or self.instrument_at is None or self.status_fields is not None
                or self.monotonic() - self.instrument_at > self.config.status_fresh_s):
            raise ValueError("fresh instrument status required before a mode request")
        expected = request.get("expected_session")
        if type(expected) is not int or expected != status["session"]:
            raise ValueError("instrument session differs from requested session")
        mode = request.get("mode")
        code = request.get("code", 0)
        dwell = request.get("dwell_s", 0)
        if type(mode) is not int or mode not in range(4):
            raise ValueError("mode must be 0..3")
        if type(code) is not int or not 0 <= code <= 0xFFFF:
            raise ValueError("code must be a decimal uint16")
        if type(dwell) is not int or not 0 <= dwell <= UINT32_MAX:
            raise ValueError("dwell_s must be a decimal uint32")
        if mode in (0, 1) and code != 0 or mode in (1, 2) and dwell != 0:
            raise ValueError("mode arguments are inconsistent")
        if mode == 0 and dwell > 604800 or mode == 3 and not 1 <= dwell <= 86400:
            raise ValueError("mode duration is outside the firmware contract")
        if self.pending_command is not None and mode != 1:
            raise ValueError("previous mode request is still unconfirmed")
        if self.last_sequence >= UINT32_MAX:
            raise ValueError("command sequence exhausted for this session")
        sequence = self.last_sequence + 1
        command = f"ACTIVE MODE {expected} {sequence} {mode} {code} {dwell}\n".encode("ascii")
        # A transport write proves submission only. The next status and
        # firmware receipt must establish acceptance or application.
        if self.port is None or self.port.write(command) != len(command):
            self.error = "mode command transport write was incomplete; identity is unconfirmed"
            raise OSError("mode command was not fully submitted")
        self.last_sequence = sequence
        self.pending_command = {"session": expected, "sequence": sequence,
                                "mode": mode, "submitted_utc": _utc()}
        self._publish()
        return {"submission": "written_unconfirmed", "session": expected,
                "sequence": sequence, "command": command.decode("ascii").strip()}

    def run(self) -> dict:
        self.started = self.monotonic()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        reservation = self.run_dir / RESERVATION
        self.started_utc = _utc()
        with reservation.open("x", encoding="utf-8") as handle:
            json.dump({"pid": os.getpid(), "started_utc": _utc()}, handle)
        sock_path = socket_path(self.run_dir)
        deadline = None if self.config.duration_s is None else self.started + self.config.duration_s
        try:
            if sock_path.exists():
                raise FileExistsError(sock_path)
            self.server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            self.server.bind(str(sock_path))
            os.chmod(sock_path, 0o600)
            self.server.listen(4)
            self.server.setblocking(False)
            self._open_segment()
            self.port = self.serial_factory(self.config.device, self.config.baud)
            self.running = True
            self._publish()
            while deadline is None or self.monotonic() < deadline:
                self._serve_one()
                if self.error is not None:
                    raise OSError(self.error)
                data = self.port.read(4096)
                if data:
                    self._write_raw(data)
                    self._observe(data)
                if self.monotonic() - self.last_state_write >= self.config.status_interval_s:
                    self._publish()
            self.running = False
        except BaseException as exc:
            self.error = f"{type(exc).__name__}: {exc}"
            self.running = False
            raise
        finally:
            if self.port is not None:
                self.port.close()
                self.port = None
            if self.server is not None:
                self.server.close()
                self.server = None
            sock_path.unlink(missing_ok=True)
            if self.raw is not None:
                self._close_segment()
            _atomic_json(self.run_dir / "recording_manifest.json", {
                "schema_version": 1, "device": self.config.device,
                "started_utc": self.started_utc, "closed_utc": _utc(),
                "segments": self.segments, "bytes_recorded": self.bytes_recorded,
                "observed_record_counts": self.record_counts,
                "invalid_status_records": self.invalid_status,
                "recording_error": self.error,
                "instrument_session_at_close": self.instrument["session"] if self.instrument else None,
            })
            self._publish()
            reservation.unlink(missing_ok=True)
        return self._state()


def request(run_dir: Path, value: dict, *, timeout_s: float = 2.0) -> dict:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(timeout_s)
        client.connect(str(socket_path(run_dir)))
        client.sendall((json.dumps(value, sort_keys=True) + "\n").encode("utf-8"))
        response = bytearray()
        while b"\n" not in response and len(response) <= 65536:
            block = client.recv(4096)
            if not block:
                break
            response.extend(block)
        if b"\n" not in response:
            raise OSError("recorder response incomplete")
        return json.loads(response.split(b"\n", 1)[0])


def verify_recording(run_dir: Path) -> dict:
    """Check closed raw segment identity without claiming scientific coverage."""
    root = run_dir.resolve()
    if (root / RESERVATION).exists():
        raise ValueError("recording is still active or was interrupted")
    manifest = json.loads((root / "recording_manifest.json").read_text(encoding="utf-8"))
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("segments"), list):
        raise ValueError("unsupported recording manifest")
    total = 0
    for index, entry in enumerate(manifest["segments"], 1):
        name = f"serial-{index:04d}.raw"
        if not isinstance(entry, dict) or entry.get("path") != name:
            raise ValueError("raw segments are missing or out of order")
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError(f"raw segment unavailable: {name}")
        digest = hashlib.sha256()
        size = 0
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(block)
                size += len(block)
        if type(entry.get("bytes")) is not int or size != entry["bytes"] or digest.hexdigest() != entry.get("sha256"):
            raise ValueError(f"raw segment identity mismatch: {name}")
        total += size
    if total != manifest.get("bytes_recorded"):
        raise ValueError("recording byte count mismatch")
    return {"status": "verified", "segments": len(manifest["segments"]),
            "bytes_recorded": total, "recording_error": manifest.get("recording_error"),
            "scientific_coverage": "not_established_by_raw_hashes"}


def read_recorder_status(run_dir: Path, *, now_monotonic_ns: int | None = None) -> dict:
    """Recompute freshness independently of the recorder's last publication."""
    state = json.loads((run_dir / STATE).read_text(encoding="utf-8"))
    now = time.monotonic_ns() if now_monotonic_ns is None else now_monotonic_ns
    observed = state.get("observed_monotonic_ns")
    elapsed = (now - observed) / 1_000_000_000 if type(observed) is int and 0 <= observed <= now else None
    state["publication_age_s"] = elapsed
    interval = state.get("status_interval_s", 1.0)
    limit = state.get("instrument_fresh_limit_s", 10.0)
    if not isinstance(interval, (int, float)) or interval <= 0:
        interval = 1.0
    if not isinstance(limit, (int, float)) or limit <= 0:
        limit = 10.0
    state["writer_fresh"] = bool(state.get("recording") and elapsed is not None
                                 and elapsed <= max(5.0, 3 * interval))
    for key in ("instrument_age_s", "last_record_age_s"):
        old = state.get(key)
        state[key] = old + elapsed if isinstance(old, (int, float)) and elapsed is not None else None
    state["instrument_fresh"] = bool(state["writer_fresh"] and
                                      state["instrument_age_s"] is not None and
                                      state["instrument_age_s"] <= limit)
    return state
