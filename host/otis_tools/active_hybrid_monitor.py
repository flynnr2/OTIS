"""Read-only authoritative progress snapshot for a CX320 live attempt.

The monitor never opens the serial device and never submits a command.  It
combines the capture-owner heartbeat, supervisor state, retained evidence
freshness, and exact serial-owner set so unattended monitoring can distinguish
process liveness from scientific progress.
"""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import time
from typing import Any

from .active_hybrid_activation import validate_frozen_run_manifest
from .capture_runtime_checks import _serial_owner_pids


TOOL_ID = "cx320_active_hybrid_monitor_v1"
CAPTURE_STATE = Path("reports/capture_device_state.json")
SUPERVISOR_STATE = Path("reports/cx317_active_supervisor_state.json")
RAW_SERIAL = Path("raw/serial.log")
ESTIMATES = Path("csv/estimates_v2.csv")
ACTIVE = Path("csv/active_transactions_v1.csv")
HYBRID = Path("csv/active_hybrid_decisions_v1.csv")
CAPTURE_MAX_AGE_S = 15.0
EVIDENCE_MAX_AGE_S = 15.0


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _read_object(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _age_s(path: Path, *, now: float) -> float | None:
    if not path.is_file():
        return None
    return max(0.0, now - path.stat().st_mtime)


def _row_summary(path: Path, fields: tuple[str, ...]) -> dict[str, Any]:
    if not path.is_file():
        return {"rows": 0, "latest": None}
    rows = 0
    latest: dict[str, str] | None = None
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            rows += 1
            latest = {field: row.get(field, "") for field in fields}
    return {"rows": rows, "latest": latest}


def _pid_alive(value: object) -> bool:
    try:
        pid = int(value)
        os.kill(pid, 0)
    except (OSError, TypeError, ValueError):
        return False
    return True


def snapshot(run_dir: Path, *, now: float | None = None) -> dict[str, Any]:
    """Return one non-mutating snapshot of the decision-bearing live state."""

    run_dir = run_dir.resolve()
    manifest = validate_frozen_run_manifest(run_dir / "run_manifest.json")
    now = time.time() if now is None else now
    capture = _read_object(run_dir / CAPTURE_STATE)
    supervisor = _read_object(run_dir / SUPERVISOR_STATE)
    terminal = None if supervisor is None else supervisor.get("terminal")
    terminal_reached = isinstance(terminal, dict)
    device = str(manifest["host"]["serial_device"])
    owners = sorted(_serial_owner_pids(device))
    capture_pid = None if capture is None else capture.get("pid")
    capture_age = _age_s(run_dir / CAPTURE_STATE, now=now)
    raw_age = _age_s(run_dir / RAW_SERIAL, now=now)
    integrity_faults: list[str] = []
    if capture is None:
        integrity_faults.append("capture_state_missing")
    else:
        if not terminal_reached and capture_age is not None and capture_age > CAPTURE_MAX_AGE_S:
            integrity_faults.append("capture_state_stale")
        if not terminal_reached and capture.get("capture_active") is not True:
            integrity_faults.append("capture_inactive_before_terminal")
        if not terminal_reached and capture.get("serial_open") is not True:
            integrity_faults.append("serial_closed_before_terminal")
        for field in (
            "malformed_utf8",
            "parser_errors",
            "reconnect_count",
            "commands_rejected",
        ):
            if int(capture.get(field, 0)) != 0:
                integrity_faults.append(f"capture_{field}_nonzero")
    if not terminal_reached:
        if capture_pid is None or owners != [int(capture_pid)]:
            integrity_faults.append("sole_serial_owner_mismatch")
        if raw_age is None:
            integrity_faults.append("raw_evidence_missing")
        elif raw_age > EVIDENCE_MAX_AGE_S:
            integrity_faults.append("raw_evidence_stale")

    estimates = _row_summary(
        run_dir / ESTIMATES,
        (
            "estimate_id",
            "estimator_timestamp_ticks",
            "source_dac_ref",
            "frequency_error_hz",
        ),
    )
    transactions = _row_summary(
        run_dir / ACTIVE,
        (
            "transaction_record_sequence",
            "event",
            "request_sequence",
            "active_state",
            "response_class",
        ),
    )
    hybrid = _row_summary(
        run_dir / HYBRID,
        (
            "hybrid_record_sequence",
            "decision_sequence",
            "dac_epoch",
            "state_after",
            "phase_materially_influenced",
            "requested_delta_codes",
        ),
    )
    status = (
        "terminal"
        if terminal_reached
        else "fault"
        if integrity_faults
        else "running"
    )
    return {
        "schema_version": 1,
        "tool": TOOL_ID,
        "observed_utc": _utc_now(),
        "status": status,
        "run_dir": str(run_dir),
        "run_id": manifest["run_id"],
        "bundle_sha256": manifest["bundle"]["bundle_sha256"],
        "activation_sha256": manifest["activation"]["activation_sha256"],
        "terminal": terminal,
        "integrity_faults": integrity_faults,
        "capture": {
            "pid": capture_pid,
            "pid_alive": _pid_alive(capture_pid),
            "state_age_s": capture_age,
            "raw_evidence_age_s": raw_age,
            "serial_owner_pids": owners,
            "bytes_written": None if capture is None else capture.get("bytes_written"),
            "lines_parsed": None if capture is None else capture.get("lines_parsed"),
            "commands_sent": None if capture is None else capture.get("commands_sent"),
            "emergency_aborts_sent": (
                None if capture is None else capture.get("emergency_aborts_sent")
            ),
        },
        "progress": {
            "qualification_started_utc": (
                None if supervisor is None else supervisor.get("qualification_started_utc")
            ),
            "qualified_origin_estimate_id": (
                None if supervisor is None else supervisor.get("qualified_origin_estimate_id")
            ),
            "latest_hybrid_state": (
                None if supervisor is None else supervisor.get("latest_hybrid_state")
            ),
            "first_phase_checkpoint_passed": (
                False if supervisor is None else supervisor.get("first_phase_checkpoint_passed", False)
            ),
            "later_authority_released": (
                False if supervisor is None else supervisor.get("later_authority_released", False)
            ),
            "phase_material_application_count": (
                0 if supervisor is None else supervisor.get("phase_material_application_count", 0)
            ),
            "estimates": estimates,
            "active_transactions": transactions,
            "active_hybrid_decisions": hybrid,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args(argv)
    try:
        result = snapshot(args.run_dir)
    except (FileNotFoundError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 2 if result["status"] == "fault" else 0


if __name__ == "__main__":
    raise SystemExit(main())
