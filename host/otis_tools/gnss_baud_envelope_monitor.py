"""Read-only milestone monitor for the GNSS baud-envelope programme."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import time
from typing import Any, Mapping

from .gnss_baud_envelope_supervisor import (
    EVENTS_PATH,
    PROGRAMME_ID,
    STATE_PATH,
    canonical_sha256,
    load_contract,
    read_events,
)


TOOL_ID = "otis_gnss_baud_envelope_monitor_v1"


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _age_s(path: Path, now: float) -> float | None:
    if not path.is_file():
        return None
    return max(0.0, now - path.stat().st_mtime)


def snapshot(
    run_dir: Path,
    *,
    contract_path: Path,
    now: float | None = None,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    contract = load_contract(contract_path)
    expected_hash = canonical_sha256(contract)
    state_path = run_dir / STATE_PATH
    events_path = run_dir / EVENTS_PATH
    retained_health_path = run_dir / "csv/health.csv"
    raw_serial_path = run_dir / "raw/serial.log"
    state = _read_object(state_path)
    events = read_events(events_path)
    if state.get("programme_id") != PROGRAMME_ID:
        raise ValueError("supervisor state has wrong programme identity")
    if state.get("contract_sha256") != expected_hash:
        raise ValueError("supervisor state has wrong contract identity")
    if any(event.get("contract_sha256") != expected_hash for event in events):
        raise ValueError("monitor ledger mixes contract identities")
    now = time.time() if now is None else now
    monitoring = contract.get("monitoring", {})
    maximum_age_s = int(monitoring.get("evidence_stale_after_ms", 5000)) / 1000
    terminal = state.get("terminal")
    state_age = _age_s(state_path, now)
    evidence_ages = {
        "supervisor_events": _age_s(events_path, now),
        "retained_health": _age_s(retained_health_path, now),
        "raw_serial": _age_s(raw_serial_path, now),
    }
    integrity_faults: list[str] = []
    if terminal is None:
        if state_age is None or state_age > maximum_age_s:
            integrity_faults.append("supervisor_state_stale")
        physical_sources_present = (
            evidence_ages["retained_health"] is not None
            or evidence_ages["raw_serial"] is not None
        )
        required_sources = (
            ("retained_health", "raw_serial")
            if physical_sources_present
            else ("supervisor_events",)
        )
        for source in required_sources:
            age = evidence_ages[source]
            if age is None:
                integrity_faults.append(f"{source}_missing")
            elif age > maximum_age_s:
                integrity_faults.append(f"{source}_stale")

    transitions = [
        {
            "event_sequence": event["event_sequence"],
            "event": event["event"],
            "segment_id": event.get("segment_id"),
            "source_baud": event.get("source_baud"),
            "target_baud": event.get("target_baud"),
            "confirmed_baud": event.get("confirmed_baud", event.get("recovered_baud")),
            "baud_epoch": event.get("baud_epoch"),
        }
        for event in events
        if event.get("event") in {
            "transition_confirmed",
            "transition_target_failed_recovered",
            "transition_unrecoverable",
        }
    ]
    first_faults: dict[str, dict[str, Any]] = {}
    for event in events:
        if event.get("event") != "rate_local_fault":
            continue
        fault_class = str(event.get("fault_class"))
        first_faults.setdefault(
            fault_class,
            {
                "event_sequence": event["event_sequence"],
                "segment_id": event.get("segment_id"),
                "baud": event.get("baud"),
            },
        )
    phase_events = [
        event for event in events
        if event.get("event") in {"phase_started", "phase_completed", "segment_completed"}
    ]
    status = "terminal" if terminal is not None else "fault" if integrity_faults else "running"
    result = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "programme_id": PROGRAMME_ID,
        "contract_sha256": expected_hash,
        "run_dir": str(run_dir),
        "status": status,
        "integrity_faults": integrity_faults,
        "terminal": terminal,
        "freshness": {
            "maximum_age_s": maximum_age_s,
            "supervisor_state_age_s": state_age,
            "evidence_source_ages_s": evidence_ages,
        },
        "progress": {
            "current_segment_id": state.get("current_segment_id"),
            "current_phase_id": state.get("current_phase_id"),
            "confirmed_baud": state.get("confirmed_baud"),
            "baud_epoch": state.get("baud_epoch"),
            "completed_segment_count": len(state.get("completed_segments", [])),
            "latest_phase_or_segment_milestone": phase_events[-1] if phase_events else None,
        },
        "transition_history": transitions,
        "first_fault_by_class": first_faults,
        "reporting_policy": {
            "repeated_local_faults_suppressed": True,
            "authoritative_poll_period_ms": int(
                monitoring.get("authoritative_poll_period_ms", 1000)
            ),
        },
    }
    result["snapshot_sha256"] = canonical_sha256(result)
    return result


def notable_changes(
    previous: Mapping[str, Any] | None, current: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Return only state transitions and first fault classes, never repeats."""

    if previous is None:
        previous = {}
    result: list[dict[str, Any]] = []
    before_progress = previous.get("progress", {})
    progress = current.get("progress", {})
    for field in ("current_segment_id", "current_phase_id", "confirmed_baud", "baud_epoch"):
        if progress.get(field) != before_progress.get(field):
            result.append({"kind": "progress", "field": field, "value": progress.get(field)})
    old_transitions = previous.get("transition_history", [])
    for transition in current.get("transition_history", [])[len(old_transitions):]:
        result.append({"kind": "transition_result", **transition})
    old_faults = previous.get("first_fault_by_class", {})
    for fault_class, detail in current.get("first_fault_by_class", {}).items():
        if fault_class not in old_faults:
            result.append({"kind": "first_fault_class", "fault_class": fault_class, **detail})
    old_integrity = set(previous.get("integrity_faults", []))
    for fault in current.get("integrity_faults", []):
        if fault not in old_integrity:
            result.append({"kind": "monitor_fault", "fault": fault})
    if current.get("terminal") is not None and current.get("terminal") != previous.get("terminal"):
        result.append({"kind": "programme_terminal", "terminal": current["terminal"]})
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--follow", action="store_true")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--poll-s", type=float, default=1.0)
    args = parser.parse_args(argv)
    if args.poll_s <= 0:
        parser.error("--poll-s must be positive")
    if args.follow:
        if args.output is None:
            parser.error("--follow requires --output")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        previous: dict[str, Any] | None = None
        while True:
            try:
                value = snapshot(args.run_dir, contract_path=args.contract)
            except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
                value = {
                    "schema_version": 1,
                    "status": "fault",
                    "integrity_faults": [f"monitor_snapshot_error:{type(exc).__name__}:{exc}"],
                    "terminal": None,
                }
            records = notable_changes(previous, value)
            if previous is None:
                records.insert(0, {"kind": "monitor_started", "snapshot": value})
            with args.output.open("a", encoding="utf-8") as handle:
                for record in records:
                    handle.write(
                        json.dumps(
                            {
                                "observed_monotonic_ns": time.monotonic_ns(),
                                **record,
                            },
                            sort_keys=True,
                            allow_nan=False,
                        )
                        + "\n"
                    )
                if records:
                    handle.flush()
                    os.fsync(handle.fileno())
            if value.get("terminal") is not None:
                return 2 if value["status"] == "fault" else 0
            previous = value
            time.sleep(args.poll_s)
    try:
        value = snapshot(args.run_dir, contract_path=args.contract)
    except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(value, indent=2, sort_keys=True, allow_nan=False))
    return 2 if value["status"] == "fault" else 0


if __name__ == "__main__":
    raise SystemExit(main())
