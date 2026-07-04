from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import csv
import json

from .run_loader import RunManifest


SEQUENCE_FIELDS_BY_NAME = {
    "raw_events.csv": "event_seq",
    "ref.csv": "event_seq",
    "evt.csv": "event_seq",
    "count_observations.csv": "count_seq",
    "cnt.csv": "count_seq",
    "health.csv": "status_seq",
    "environment.csv": "env_seq",
    "dac_steps.csv": "seq",
}


@dataclass(frozen=True)
class SessionInfo:
    session_id: str
    start_reason: str
    close_reason: str | None
    source: str
    start_row: int | None = None
    end_row: int | None = None
    marker_utc: str | None = None


@dataclass(frozen=True)
class RunSessionSummary:
    run_id: str
    session_count: int
    reconnect_event_count: int
    reboot_marker_count: int
    split_reasons: tuple[str, ...]
    sessions: tuple[SessionInfo, ...]


def _int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value), 0)
    except (TypeError, ValueError):
        return None


def _read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _raw_log_markers(path: Path) -> tuple[int, int, list[SessionInfo]]:
    if not path.exists():
        return 0, 0, ()
    reconnects = 0
    boots = 0
    sessions: list[SessionInfo] = []
    seen_data = False
    session_index = 1
    with path.open("rb") as handle:
        for line_number, raw_line in enumerate(handle, start=1):
            text = raw_line.decode("utf-8", errors="replace").strip()
            if not text:
                continue
            if text.startswith("# OTIS_HOST "):
                try:
                    payload = json.loads(text.removeprefix("# OTIS_HOST "))
                except json.JSONDecodeError:
                    payload = {}
                event = str(payload.get("event", ""))
                if event == "serial_disconnected":
                    reconnects += 1
                if event == "serial_opened" and seen_data:
                    session_index += 1
                    sessions.append(
                        SessionInfo(
                            session_id=f"session_{session_index:04d}",
                            start_reason="host_serial_reopened_after_capture_started",
                            close_reason=None,
                            source="raw/serial.log",
                            start_row=line_number,
                            marker_utc=str(payload.get("utc", "")) or None,
                        )
                    )
                continue
            if "BOOT" in text or text.startswith("BOOT,") or text.startswith("HDR,"):
                boots += 1
                if seen_data:
                    session_index += 1
                    sessions.append(
                        SessionInfo(
                            session_id=f"session_{session_index:04d}",
                            start_reason="firmware_boot_or_header_marker_after_capture_started",
                            close_reason=None,
                            source="raw/serial.log",
                            start_row=line_number,
                        )
                    )
            seen_data = True
    return reconnects, boots, tuple(sessions)


def _sequence_split_sessions(manifest: RunManifest) -> list[SessionInfo]:
    sessions: list[SessionInfo] = []
    session_index = 1
    for entry in manifest.files:
        rel_path = entry.get("path")
        if not rel_path:
            continue
        path = manifest.root / str(rel_path)
        field = SEQUENCE_FIELDS_BY_NAME.get(path.name)
        if not field:
            continue
        previous: int | None = None
        for row_number, row in enumerate(_read_csv_rows(path), start=2):
            current = _int(row.get(field))
            if current is None:
                continue
            if previous is not None and current <= previous:
                session_index += 1
                sessions.append(
                    SessionInfo(
                        session_id=f"session_{session_index:04d}",
                        start_reason=f"{path.name}:{field}_restart_or_rollback",
                        close_reason="sequence_restart_or_rollback",
                        source=str(path.relative_to(manifest.root)),
                        start_row=row_number,
                    )
                )
            previous = current
    return sessions


def detect_run_sessions(manifest: RunManifest) -> RunSessionSummary:
    reconnects, boots, raw_sessions = _raw_log_markers(manifest.root / "raw" / "serial.log")
    sequence_sessions = _sequence_split_sessions(manifest)
    split_sources = list(raw_sessions) if raw_sessions else sequence_sessions
    if raw_sessions and sequence_sessions:
        first_raw = min(raw_sessions, key=lambda item: item.start_row or 0)
        split_sources = [
            SessionInfo(
                session_id=first_raw.session_id,
                start_reason="host_or_firmware_session_boundary",
                close_reason="reconnect_boot_or_sequence_restart",
                source=first_raw.source,
                start_row=first_raw.start_row,
                marker_utc=first_raw.marker_utc,
            )
        ]
    elif len(raw_sessions) > 1:
        first_raw = min(raw_sessions, key=lambda item: item.start_row or 0)
        split_sources = [
            SessionInfo(
                session_id=first_raw.session_id,
                start_reason="host_or_firmware_session_boundary",
                close_reason="reconnect_or_boot",
                source=first_raw.source,
                start_row=first_raw.start_row,
                marker_utc=first_raw.marker_utc,
            )
        ]
    elif len(sequence_sessions) > 1:
        first_sequence = min(sequence_sessions, key=lambda item: (item.source, item.start_row or 0))
        split_sources = [
            SessionInfo(
                session_id=first_sequence.session_id,
                start_reason="csv_sequence_restart_or_rollback",
                close_reason="sequence_restart_or_rollback",
                source=first_sequence.source,
                start_row=first_sequence.start_row,
            )
        ]
    split_ordered = tuple(
        SessionInfo(
            session_id=f"session_{index + 2:04d}",
            start_reason=session.start_reason,
            close_reason=session.close_reason,
            source=session.source,
            start_row=session.start_row,
            end_row=session.end_row,
            marker_utc=session.marker_utc,
        )
        for index, session in enumerate(split_sources)
    )
    ordered = (SessionInfo("session_0001", "capture_start", None, "run_manifest"),) + split_ordered
    reasons = tuple(sorted({session.start_reason for session in ordered if session.start_reason != "capture_start"}))
    return RunSessionSummary(
        run_id=manifest.run_id,
        session_count=len(ordered),
        reconnect_event_count=reconnects,
        reboot_marker_count=boots,
        split_reasons=reasons,
        sessions=ordered,
    )
