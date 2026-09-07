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
import io
import json
import os
from pathlib import Path
import time
from typing import Any

from .active_hybrid_activation import validate_frozen_run_manifest
from .active_hybrid_programme_contract import (
    CX320_PROGRAMME,
    ActiveHybridProgramme,
    programme_from_mapping,
)
from .capture_runtime_checks import _serial_owner_pids
from .contracts import (
    ACTIVE_HYBRID_DECISION_V1_FIELDS,
    ACTIVE_HYBRID_DECISION_V2_FIELDS,
    ACTIVE_HYBRID_MAINTENANCE_V1_FIELDS,
    ACTIVE_TRANSACTION_V1_FIELDS,
    ACTIVE_TRANSACTION_V2_FIELDS,
)


TOOL_ID = "cx320_active_hybrid_monitor_v1"
CAPTURE_STATE = Path("reports/capture_device_state.json")
SUPERVISOR_STATE = Path("reports/cx317_active_supervisor_state.json")
RAW_SERIAL = Path("raw/serial.log")
ESTIMATES = Path("csv/estimates_v2.csv")
ACTIVE = Path("csv/active_transactions_v1.csv")
HYBRID = Path("csv/active_hybrid_decisions_v1.csv")
PLANT_SIGN = Path("csv/plant_sign_qualification_v1.csv")
ACTIVE_EXACT = Path("csv/active_transactions_v2.csv")
HYBRID_EXACT = Path("csv/active_hybrid_decisions_v2.csv")
CAPTURE_MAX_AGE_S = 15.0
EVIDENCE_MAX_AGE_S = 15.0
EXACT_LIFECYCLE_TIME_DOMAIN = "rp2040_timer0_extended"
PREWRITE_QUALIFICATION_DEADLINE_S = 660.0
QUALIFIED_D14_ENDPOINT_CONTRACT = "qualified_D14_D8_aperture_count_v2"
QUALIFIED_D14_MILESTONE_APERTURES = 21_600
UINT32_MODULUS = 1 << 32
UINT32_MAXIMUM_FORWARD_DELTA = (1 << 31) - 1

_AT2_NON_JOIN_FIELDS = frozenset(
    {
        "record_type",
        "schema_version",
        "timing_record_sequence",
        "event_timestamp_ticks",
        "time_domain",
    }
)
_AH2_NON_JOIN_FIELDS = frozenset(
    {
        "record_type",
        "schema_version",
        "timing_record_sequence",
        "decision_timestamp_ticks",
        "time_domain",
    }
)


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


def _utc_epoch(value: object) -> float | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


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


def _stable_contract_rows(path: Path, fields: list[str]) -> list[dict[str, str]]:
    """Read only newline-complete rows while capture may still be appending."""

    if not path.is_file():
        raise ValueError(f"required retained CSV is missing: {path}")
    payload = path.read_bytes()
    newline = payload.rfind(b"\n")
    if newline < 0:
        raise ValueError(f"required retained CSV header is unavailable: {path}")
    try:
        text = payload[: newline + 1].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"retained CSV is not UTF-8: {path}") from exc
    reader = csv.DictReader(io.StringIO(text, newline=""))
    if reader.fieldnames != fields:
        raise ValueError(f"retained CSV header differs: {path}")
    rows = list(reader)
    if any(None in row or any(value is None for value in row.values()) for row in rows):
        raise ValueError(f"retained CSV row width differs: {path}")
    return rows


def _exact_sidecar_progress(
    *,
    source_rows: list[dict[str, str]],
    timing_rows: list[dict[str, str]],
    source_sequence_field: str,
    timestamp_field: str,
    record_type: str,
    join_fields: tuple[str, ...],
    source_age_s: float | None,
    sidecar_age_s: float | None,
) -> dict[str, Any]:
    mismatches: list[str] = []
    source_by_sequence: dict[str, dict[str, str]] = {}
    for row in source_rows:
        sequence = row[source_sequence_field]
        if sequence in source_by_sequence:
            mismatches.append(
                f"{record_type} source duplicate {source_sequence_field}={sequence}"
            )
        source_by_sequence[sequence] = row

    joined_sequences: set[str] = set()
    timing_source_sequences: set[str] = set()
    previous_timing_sequence = 0
    previous_ticks: int | None = None
    latest: dict[str, str] | None = None
    for row_number, timing in enumerate(timing_rows, start=1):
        source_sequence = timing[source_sequence_field]
        try:
            timing_sequence = int(timing["timing_record_sequence"])
            ticks = int(timing[timestamp_field])
        except (TypeError, ValueError) as exc:
            mismatches.append(f"{record_type} row {row_number} counter is malformed")
            continue
        if (
            timing["record_type"] != record_type
            or timing["schema_version"] != "2"
            or timing["time_domain"] != EXACT_LIFECYCLE_TIME_DOMAIN
            or timing_sequence <= previous_timing_sequence
            or (previous_ticks is not None and ticks < previous_ticks)
        ):
            mismatches.append(f"{record_type} row {row_number} identity differs")
        previous_timing_sequence = timing_sequence
        previous_ticks = ticks
        if source_sequence in timing_source_sequences:
            mismatches.append(
                f"{record_type} duplicate {source_sequence_field}={source_sequence}"
            )
        timing_source_sequences.add(source_sequence)
        source = source_by_sequence.get(source_sequence)
        if source is None:
            mismatches.append(
                f"{record_type} orphan {source_sequence_field}={source_sequence}"
            )
        else:
            differing = [
                field for field in join_fields if timing[field] != source[field]
            ]
            if differing:
                mismatches.append(
                    f"{record_type} join mismatch {source_sequence_field}="
                    f"{source_sequence}:" + ",".join(differing)
                )
            else:
                joined_sequences.add(source_sequence)
        latest = {
            "timing_record_sequence": timing["timing_record_sequence"],
            source_sequence_field: source_sequence,
            timestamp_field: timing[timestamp_field],
            "time_domain": timing["time_domain"],
        }

    pending = sorted(
        set(source_by_sequence) - timing_source_sequences,
        key=lambda value: int(value),
    )
    join_lag = len(source_rows) - len(timing_rows)
    lag_stale = bool(
        join_lag > 0
        and source_age_s is not None
        and source_age_s > EVIDENCE_MAX_AGE_S
    )
    return {
        "source_rows": len(source_rows),
        "sidecar_rows": len(timing_rows),
        "joined_rows": len(joined_sequences),
        "join_lag_rows": join_lag,
        "pending_source_sequences": pending,
        "source_age_s": source_age_s,
        "sidecar_age_s": sidecar_age_s,
        "lag_stale": lag_stale,
        "mismatches": mismatches,
        "latest": latest,
    }


def _exact_lifecycle_timing_progress(run_dir: Path, *, now: float) -> dict[str, Any]:
    transaction_rows = _stable_contract_rows(
        run_dir / ACTIVE, ACTIVE_TRANSACTION_V1_FIELDS
    )
    transaction_timings = _stable_contract_rows(
        run_dir / ACTIVE_EXACT, ACTIVE_TRANSACTION_V2_FIELDS
    )
    decision_rows = _stable_contract_rows(
        run_dir / HYBRID, ACTIVE_HYBRID_DECISION_V1_FIELDS
    )
    decision_timings = _stable_contract_rows(
        run_dir / HYBRID_EXACT, ACTIVE_HYBRID_DECISION_V2_FIELDS
    )
    transactions = _exact_sidecar_progress(
        source_rows=transaction_rows,
        timing_rows=transaction_timings,
        source_sequence_field="transaction_record_sequence",
        timestamp_field="event_timestamp_ticks",
        record_type="AT2",
        join_fields=tuple(
            field
            for field in ACTIVE_TRANSACTION_V2_FIELDS
            if field not in _AT2_NON_JOIN_FIELDS
        ),
        source_age_s=_age_s(run_dir / ACTIVE, now=now),
        sidecar_age_s=_age_s(run_dir / ACTIVE_EXACT, now=now),
    )
    decisions = _exact_sidecar_progress(
        source_rows=decision_rows,
        timing_rows=decision_timings,
        source_sequence_field="hybrid_record_sequence",
        timestamp_field="decision_timestamp_ticks",
        record_type="AH2",
        join_fields=tuple(
            field
            for field in ACTIVE_HYBRID_DECISION_V2_FIELDS
            if field not in _AH2_NON_JOIN_FIELDS
        ),
        source_age_s=_age_s(run_dir / HYBRID, now=now),
        sidecar_age_s=_age_s(run_dir / HYBRID_EXACT, now=now),
    )
    mismatches = [*transactions["mismatches"], *decisions["mismatches"]]
    return {
        "required": True,
        "time_domain": EXACT_LIFECYCLE_TIME_DOMAIN,
        "AT2": transactions,
        "AH2": decisions,
        "join_exact_at_observed_frontier": bool(
            not mismatches
            and transactions["join_lag_rows"] == 0
            and decisions["join_lag_rows"] == 0
        ),
        "mismatches": mismatches,
    }


def _maintenance_evidence_progress(
    run_dir: Path,
    *,
    programme: ActiveHybridProgramme,
    expected_build_identity: str,
    now: float,
) -> dict[str, Any]:
    """Read the descriptor-declared CX323 maintenance evidence without I/O."""

    contract = programme.maintenance_record_contract
    record_type = programme.maintenance_record_type
    if contract != "active_hybrid_maintenance_v1" or record_type != "AHM":
        raise ValueError("unsupported long-run maintenance evidence descriptor")
    path = run_dir / "csv" / f"{contract}.csv"
    rows = _stable_contract_rows(path, ACTIVE_HYBRID_MAINTENANCE_V1_FIELDS)
    mismatches: list[str] = []
    previous_sequence = 0
    latest: dict[str, str] | None = None
    expected = {
        "record_type": record_type,
        "run_identity": programme.runtime_run_identity,
        "build_identity": expected_build_identity,
        "profile_identity": programme.profile_id,
        "policy_id": programme.policy_id,
        "time_domain": EXACT_LIFECYCLE_TIME_DOMAIN,
    }
    for row_number, row in enumerate(rows, start=1):
        try:
            sequence = int(row["maintenance_record_sequence"])
        except (TypeError, ValueError):
            mismatches.append(f"AHM row {row_number} sequence is malformed")
            continue
        if sequence <= previous_sequence:
            mismatches.append(f"AHM row {row_number} sequence is not increasing")
        previous_sequence = sequence
        for field, value in expected.items():
            if row.get(field) != value:
                mismatches.append(
                    f"AHM row {row_number} {field} differs: "
                    f"{row.get(field)!r} != {value!r}"
                )
        latest = {
            field: row.get(field, "")
            for field in (
                "maintenance_record_sequence",
                "event",
                "maintenance_state_after",
                "request_pending_after",
                "response_pending_after",
                "metadata_hold_after",
                "reason",
            )
        }
    return {
        "required": True,
        "contract": contract,
        "record_type": record_type,
        "rows": len(rows),
        "age_s": _age_s(path, now=now),
        "latest": latest,
        "mismatches": mismatches,
    }


def _qualified_d14_aperture_progress(
    supervisor: dict[str, Any] | None,
    *,
    programme: ActiveHybridProgramme,
) -> dict[str, Any]:
    """Project the retained CX323 qualification frontier without wall time."""

    target = programme.qualified_d14_aperture_count
    if target is None:
        return {"required": False}
    reserve = programme.correction_response_reserve_d14_apertures
    if (
        type(target) is not int
        or target <= 0
        or type(reserve) is not int
        or not 0 < reserve < target
    ):
        raise ValueError("qualified D14 endpoint descriptor is malformed")
    admission_close = target - reserve
    result: dict[str, Any] = {
        "required": True,
        "endpoint_contract": QUALIFIED_D14_ENDPOINT_CONTRACT,
        "progress_domain": "accepted_D14_D8_apertures",
        "accepted_apertures": None,
        "target_apertures": target,
        "remaining_apertures": target,
        "milestones": {
            "interval_apertures": QUALIFIED_D14_MILESTONE_APERTURES,
            "nominal_interval_s": QUALIFIED_D14_MILESTONE_APERTURES,
            "nominal_interval_h": 6,
            "completed_apertures": [],
            "next_apertures": QUALIFIED_D14_MILESTONE_APERTURES,
        },
        "correction_admission": {
            "close_apertures": admission_close,
            "response_reserve_apertures": reserve,
            "close_reached": False,
            "closed_utc": (
                None
                if supervisor is None
                else supervisor.get("response_horizon_closed_utc")
            ),
        },
        "target_reached": False,
        "reference_identity": {
            "counter_domain": "uint32_modulo",
            "origin": None,
            "current": None,
            "endpoint": None,
        },
        "state": "awaiting_qualified_origin",
    }
    if supervisor is None:
        return result

    accepted_origin = supervisor.get("qualified_d14_accepted_window_origin")
    reference_origin = supervisor.get("qualified_d14_reference_sequence_origin")
    accepted_apertures = supervisor.get("qualified_d14_accepted_apertures")
    reference_current = supervisor.get(
        "qualified_d14_reference_sequence_endpoint"
    )
    retained = (
        accepted_origin,
        reference_origin,
        accepted_apertures,
        reference_current,
    )
    if all(value is None for value in retained):
        return result
    for name, value in (
        ("qualified accepted-window origin", accepted_origin),
        ("qualified D14 reference origin", reference_origin),
    ):
        if type(value) is not int or not 0 <= value < UINT32_MODULUS:
            raise ValueError(f"{name} is malformed")

    result["reference_identity"]["origin"] = {
        "accepted_window_count": accepted_origin,
        "boundary_reference_sequence": reference_origin,
    }
    result["reference_identity"]["endpoint"] = {
        "accepted_window_count": (accepted_origin + target) % UINT32_MODULUS,
        "boundary_reference_sequence": (
            reference_origin + target
        ) % UINT32_MODULUS,
    }
    if accepted_apertures is None and reference_current is None:
        result["state"] = "qualified_origin_established_awaiting_progress"
        return result
    if (
        type(accepted_apertures) is not int
        or not 0 <= accepted_apertures <= UINT32_MAXIMUM_FORWARD_DELTA
    ):
        raise ValueError("qualified accepted-aperture progress is malformed")
    if (
        type(reference_current) is not int
        or not 0 <= reference_current < UINT32_MODULUS
    ):
        raise ValueError("qualified current D14 reference is malformed")

    expected_reference_current = (
        reference_origin + accepted_apertures
    ) % UINT32_MODULUS
    if reference_current != expected_reference_current:
        raise ValueError(
            "qualified current D14 reference differs from accepted-aperture progress"
        )
    accepted_current = (
        accepted_origin + accepted_apertures
    ) % UINT32_MODULUS
    completed_count = min(accepted_apertures, target) // (
        QUALIFIED_D14_MILESTONE_APERTURES
    )
    completed = [
        QUALIFIED_D14_MILESTONE_APERTURES * index
        for index in range(1, completed_count + 1)
    ]
    next_milestone = (
        None
        if completed and completed[-1] >= target
        else QUALIFIED_D14_MILESTONE_APERTURES * (completed_count + 1)
    )
    if next_milestone is not None and next_milestone > target:
        next_milestone = target
    admission_reached = accepted_apertures >= admission_close
    closed_utc = supervisor.get("response_horizon_closed_utc")
    if closed_utc is not None and not admission_reached:
        raise ValueError(
            "correction admission is recorded closed before its exact aperture boundary"
        )

    result.update(
        {
            "accepted_apertures": accepted_apertures,
            "remaining_apertures": max(0, target - accepted_apertures),
            "milestones": {
                "interval_apertures": QUALIFIED_D14_MILESTONE_APERTURES,
                "nominal_interval_s": QUALIFIED_D14_MILESTONE_APERTURES,
                "nominal_interval_h": 6,
                "completed_apertures": completed,
                "next_apertures": next_milestone,
            },
            "correction_admission": {
                "close_apertures": admission_close,
                "response_reserve_apertures": reserve,
                "close_reached": admission_reached,
                "closed_utc": closed_utc,
            },
            "target_reached": accepted_apertures >= target,
            "state": (
                "qualified_target_reached"
                if accepted_apertures >= target
                else "correction_admission_closed"
                if admission_reached
                else "qualification_in_progress"
            ),
        }
    )
    result["reference_identity"]["current"] = {
        "accepted_window_count": accepted_current,
        "boundary_reference_sequence": reference_current,
    }
    return result


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
    try:
        programme = programme_from_mapping(manifest)
    except ValueError:
        # Retain compatibility with the narrow monitor fixtures and historical
        # CX320 snapshots that predate an explicit programme field.
        programme = CX320_PROGRAMME
    now = time.time() if now is None else now
    capture = _read_object(run_dir / CAPTURE_STATE)
    supervisor = _read_object(run_dir / SUPERVISOR_STATE)
    terminal = None if supervisor is None else supervisor.get("terminal")
    terminal_reached = isinstance(terminal, dict)
    prewrite_readiness = (
        None
        if supervisor is None
        else supervisor.get("latest_prewrite_readiness")
    )
    supervisor_started_epoch = _utc_epoch(
        None if supervisor is None else supervisor.get("supervisor_started_utc")
    )
    prewrite_elapsed_s = (
        None
        if supervisor_started_epoch is None
        else max(0.0, now - supervisor_started_epoch)
    )
    device = str(manifest["host"]["serial_device"])
    owners = sorted(_serial_owner_pids(device))
    capture_pid = None if capture is None else capture.get("pid")
    capture_age = _age_s(run_dir / CAPTURE_STATE, now=now)
    raw_age = _age_s(run_dir / RAW_SERIAL, now=now)
    integrity_faults: list[str] = []
    exact_timing: dict[str, Any] | None = None
    maintenance: dict[str, Any] | None = None
    try:
        qualified_apertures = _qualified_d14_aperture_progress(
            supervisor,
            programme=programme,
        )
    except (TypeError, ValueError) as exc:
        qualified_apertures = {
            "required": True,
            "endpoint_contract": QUALIFIED_D14_ENDPOINT_CONTRACT,
            "unavailable": True,
            "mismatches": [str(exc)],
        }
        integrity_faults.append("qualified_d14_aperture_progress_invalid")
    if programme.integrated_long_run:
        try:
            exact_timing = _exact_lifecycle_timing_progress(run_dir, now=now)
        except (OSError, TypeError, ValueError) as exc:
            exact_timing = {
                "required": True,
                "time_domain": EXACT_LIFECYCLE_TIME_DOMAIN,
                "join_exact_at_observed_frontier": False,
                "unavailable": True,
                "mismatches": [str(exc)],
            }
        if exact_timing.get("unavailable") is True:
            integrity_faults.append("exact_timing_sidecar_unavailable")
        elif exact_timing["mismatches"]:
            integrity_faults.append("exact_timing_sidecar_identity_mismatch")
        for record_type in ("AT2", "AH2"):
            progress = exact_timing.get(record_type)
            if not isinstance(progress, dict):
                continue
            if int(progress["join_lag_rows"]) < 0:
                integrity_faults.append(
                    f"{record_type}_sidecar_ahead_of_canonical_source"
                )
            elif int(progress["join_lag_rows"]) > 1 or progress["lag_stale"]:
                integrity_faults.append(f"{record_type}_sidecar_join_lag_stale")
    if programme.persistent_maintenance_policy:
        expected_pre_setup_header_only = bool(
            isinstance(supervisor, dict)
            and supervisor.get("manual_start_sent") is False
            and supervisor.get("setup_confirmed_utc") is None
            and supervisor.get("latest_hybrid_state") in {None, "SETUP_PENDING"}
        )
        try:
            maintenance = _maintenance_evidence_progress(
                run_dir,
                programme=programme,
                expected_build_identity=str(manifest["firmware"]["build_identity"]),
                now=now,
            )
        except (OSError, TypeError, ValueError) as exc:
            maintenance = {
                "required": True,
                "unavailable": True,
                "mismatches": [str(exc)],
            }
        maintenance["expected_pre_setup_header_only"] = (
            expected_pre_setup_header_only
        )
        if maintenance.get("unavailable") is True or (
            not maintenance.get("rows")
            and not expected_pre_setup_header_only
        ):
            integrity_faults.append("maintenance_evidence_unavailable")
        elif maintenance["mismatches"]:
            integrity_faults.append("maintenance_evidence_identity_mismatch")
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
        if (
            programme.integrated_long_run
            and isinstance(prewrite_readiness, dict)
            and prewrite_readiness.get("ready") is False
            and prewrite_elapsed_s is not None
            and prewrite_elapsed_s
            > PREWRITE_QUALIFICATION_DEADLINE_S
        ):
            integrity_faults.append("prewrite_qualification_deadline_expired")

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
    plant_sign = (
        _row_summary(
            run_dir / PLANT_SIGN,
            (
                "qualification_record_sequence",
                "event",
                "state_after",
                "accepted_intervals",
                "request_sequence",
                "passed",
                "reason",
            ),
        )
        if programme.identification_required
        else {"rows": 0, "latest": None}
    )
    if programme.identification_required and not terminal_reached:
        plant_state = (
            None if supervisor is None else supervisor.get("latest_plant_sign_state")
        )
        if plant_state == "PLANT_SIGN_RESPONSE_ACK_PENDING":
            psq_age = _age_s(run_dir / PLANT_SIGN, now=now)
            latest_psq = plant_sign.get("latest")
            if psq_age is None or psq_age > EVIDENCE_MAX_AGE_S:
                integrity_faults.append("plant_sign_response_evidence_stale")
            if not isinstance(latest_psq, dict) or latest_psq.get("event") != "response":
                integrity_faults.append("plant_sign_response_evidence_not_visible")
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
        "monitoring": {
            "maximum_poll_interval_s": 10,
            "plant_sign_ack_deadline_s": 30,
            "evidence_stale_after_s": EVIDENCE_MAX_AGE_S,
            "prewrite_qualification_deadline_s": PREWRITE_QUALIFICATION_DEADLINE_S,
        },
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
            "supervisor_started_utc": (
                None if supervisor is None else supervisor.get("supervisor_started_utc")
            ),
            "prewrite_elapsed_s": prewrite_elapsed_s,
            "prewrite_contract_ready_utc": (
                None
                if supervisor is None
                else supervisor.get("prewrite_contract_ready_utc")
            ),
            "prewrite_readiness": prewrite_readiness,
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
            "host_verification_hold": (
                None if supervisor is None else supervisor.get("host_verification_hold")
            ),
            "estimates": estimates,
            "active_transactions": transactions,
            "active_hybrid_decisions": hybrid,
            "qualified_d14_apertures": qualified_apertures,
            "exact_timing_sidecars": exact_timing,
            "maintenance_evidence": maintenance,
            "plant_sign_qualification": plant_sign,
            "plant_sign_state": (
                None if supervisor is None else supervisor.get("latest_plant_sign_state")
            ),
            "plant_sign_prearm_sent": (
                False if supervisor is None else supervisor.get("plant_sign_prearm_sent", False)
            ),
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
