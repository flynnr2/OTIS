"""Independent local observation of a recording; no serial or command access."""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Event

from .instrument_recorder import read_recorder_status


def _utc() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def material_view(state: dict) -> dict:
    instrument = state.get("instrument") or {}
    fields = instrument.get("fields") or {}
    counts = state.get("observed_record_counts") or {}
    return {
        "recording": state.get("recording"),
        "serial_open": state.get("serial_open"),
        "writer_fresh": state.get("writer_fresh"),
        "instrument_fresh": state.get("instrument_fresh"),
        "capture_fresh": state.get("capture_fresh"),
        "recording_error": state.get("recording_error"),
        "session": instrument.get("session"),
        "mode": instrument.get("mode"),
        "state": instrument.get("state"),
        "fault": fields.get("fault"),
        "qualification": {
            key: fields.get(key) for key in (
                "reference_hold", "metadata_hold", "acceptance_epoch",
                "response_incomplete",
            )
        },
        "applied_code": instrument.get("applied_code"),
        "dac_epoch": instrument.get("dac_epoch"),
        "command_completed": instrument.get("completed_command_sequence"),
        "last_command_receipt": state.get("last_command_receipt"),
        "pending_command": state.get("pending_command"),
        "application_records": counts.get("IAP"),
        "response_records": counts.get("IRS"),
        "loss": {
            key: fields.get(key) for key in (
                "observation_dropped", "evidence_dropped", "phase_preview_dropped",
                "telemetry_dropped", "critical_dropped", "direct_rows_dropped",
                "delivery_coverage",
            )
        },
    }


class RecordingMonitor:
    def __init__(self, run_dir: Path, *, poll_interval_s: float = 5.0,
                 summary_interval_s: float = 3600.0, max_log_bytes: int = 8 * 1024 * 1024,
                 monotonic=time.monotonic, sleep=time.sleep, stop_event: Event | None = None) -> None:
        if poll_interval_s <= 0 or summary_interval_s <= 0 or max_log_bytes <= 0:
            raise ValueError("monitor intervals and log limit must be positive")
        self.run_dir = run_dir.resolve()
        self.poll_interval_s = poll_interval_s
        self.summary_interval_s = summary_interval_s
        self.max_log_bytes = max_log_bytes
        self.monotonic = monotonic
        self.sleep = sleep
        self.stop_event = stop_event or Event()
        self.last_material: dict | None = None
        self.next_summary = 0.0
        self.log_segment = 0
        self.log_size = 0
        self.log = None
        self.event_count = 0
        self.capture_last_counts: dict[str, int] = {}
        self.capture_last_advance: dict[str, float] = {}
        self.capture_identity: tuple[object, object] | None = None

    def _open_log(self) -> None:
        self.log_segment += 1
        path = self.run_dir / f"monitor-events-{self.log_segment:04d}.jsonl"
        self.log = path.open("xb", buffering=0)
        self.log_size = 0

    def _emit(self, event: str, **fields: object) -> None:
        payload = {"event": event, "observed_utc": _utc(), **fields,
                   "delivery": "local_durable_file"}
        encoded = (json.dumps(payload, sort_keys=True, allow_nan=False) + "\n").encode("utf-8")
        if self.log is None:
            self._open_log()
        if self.log_size and self.log_size + len(encoded) > self.max_log_bytes:
            self.log.close()
            self._open_log()
        written = self.log.write(encoded)
        if written != len(encoded):
            raise OSError("monitor event delivery was incomplete")
        self.log.flush()
        os.fsync(self.log.fileno())
        self.log_size += len(encoded)
        self.event_count += 1

    def poll_once(self) -> dict:
        try:
            state = read_recorder_status(self.run_dir)
            counts = state.get("observed_record_counts") or {}
            now = self.monotonic()
            instrument = state.get("instrument") or {}
            identity = (state.get("pid"), instrument.get("session"))
            if identity != self.capture_identity or not state.get("recording"):
                self.capture_last_counts.clear()
                self.capture_last_advance.clear()
                self.capture_identity = identity
            for record_type in ("REF", "SNP", "CNT"):
                count = counts.get(record_type)
                previous = self.capture_last_counts.get(record_type)
                if type(count) is int and previous is not None and count > previous:
                    self.capture_last_counts[record_type] = count
                    self.capture_last_advance[record_type] = now
                elif type(count) is int and previous is None:
                    self.capture_last_counts[record_type] = count
                elif type(count) is int and previous is not None and count < previous:
                    self.capture_last_counts[record_type] = count
                    self.capture_last_advance.pop(record_type, None)
            if len(self.capture_last_advance) < 3:
                state["capture_fresh"] = None
                state["capture_age_s"] = None
            else:
                age = max(now - self.capture_last_advance[tag] for tag in ("REF", "SNP", "CNT"))
                state["capture_age_s"] = age
                state["capture_fresh"] = bool(state.get("writer_fresh") and age <= max(5.0, 3 * self.poll_interval_s))
            material = material_view(state)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            state = {"availability": "unavailable", "error": f"{type(exc).__name__}: {exc}"}
            material = {"availability": "unavailable", "error": state["error"]}
        if material != self.last_material:
            changes = material if self.last_material is None else {
                key: {"before": self.last_material.get(key), "after": value}
                for key, value in material.items() if self.last_material.get(key) != value
            }
            self._emit("material_change", changes=changes)
            self.last_material = material
        now = self.monotonic()
        if now >= self.next_summary:
            self._emit("periodic_summary", status=state)
            self.next_summary = now + self.summary_interval_s
        return state

    def run(self) -> dict:
        self.run_dir.mkdir(parents=True, exist_ok=True)
        try:
            while not self.stop_event.is_set():
                state = self.poll_once()
                if state.get("recording") is False and (self.run_dir / "recording_manifest.json").is_file():
                    self._emit("recording_closed", status=state)
                    break
                self.sleep(self.poll_interval_s)
        except OSError as exc:
            failure = {"status": "delivery_failed", "error": f"{type(exc).__name__}: {exc}",
                       "observed_utc": _utc(), "events_written": self.event_count}
            print(json.dumps(failure, sort_keys=True), file=sys.stderr)
            try:
                (self.run_dir / "monitor_delivery_failure.json").write_text(
                    json.dumps(failure, sort_keys=True) + "\n", encoding="utf-8"
                )
            except OSError:
                pass
            return failure
        finally:
            if self.log is not None:
                self.log.close()
                self.log = None
        return {"status": "closed" if not self.stop_event.is_set() else "stopped",
                "events_written": self.event_count, "log_segments": self.log_segment,
                "notification_destination": "local_files_only"}
