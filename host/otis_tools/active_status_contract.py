"""Complete-generation contract for command-bearing active status."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Mapping


ACTIVE_STATUS_SNAPSHOT_CONTRACT = "cx317_active_status_snapshot_v1"
ACTIVE_STATUS_COMPONENT = "cx317_active"
SNAPSHOT_BEGIN_KEY = "snapshot_generation_begin"
SNAPSHOT_CONTRACT_KEY = "snapshot_contract"
SNAPSHOT_COMPLETE_KEY = "snapshot_generation_complete"

ACTIVE_STATUS_KEYS = (
    "enabled",
    "run_identity",
    "build_identity",
    "profile_identity",
    "estimator_sha256",
    "model_sha256",
    "active_policy_sha256",
    "response_policy_sha256",
    "numerical_policy_sha256",
    "state",
    "reason",
    "evidence_pending",
    "evidence_phase",
    "capture_lease_live",
    "manual_start_confirmed",
    "arm_eligible",
    "fail_static",
    "session_id",
    "uptime_s",
    "evidence_request_sequence",
    "expected_setup_code",
    "confirmed_applied_code_known",
    "confirmed_applied_code",
    "correction_count",
    "cumulative_movement_codes",
    "dac_epoch",
    "selected_interval_count",
    "automatic_retry",
    "automatic_restore",
)
ACTIVE_STATUS_WIRE_KEYS = (
    SNAPSHOT_BEGIN_KEY,
    SNAPSHOT_CONTRACT_KEY,
    *ACTIVE_STATUS_KEYS,
    SNAPSHOT_COMPLETE_KEY,
)


def _unsigned_generation(value: str) -> int | None:
    try:
        generation = int(value)
    except ValueError:
        return None
    return generation if generation > 0 else None


def latest_complete_active_status(
    rows: Iterable[Mapping[str, str]],
) -> dict[str, str]:
    """Return only the newest complete, internally coherent active burst."""

    current_generation: int | None = None
    current: dict[str, str] = {}
    duplicate_or_invalid = False
    newest_generation = 0
    newest: dict[str, str] = {}

    for row in rows:
        if row.get("record_type") != "STS" or row.get("component") != (
            ACTIVE_STATUS_COMPONENT
        ):
            continue
        key = row.get("status_key", "")
        value = row.get("status_value", "")
        if key == SNAPSHOT_BEGIN_KEY:
            current_generation = _unsigned_generation(value)
            current = {}
            duplicate_or_invalid = current_generation is None
            continue
        if current_generation is None:
            continue
        if key == SNAPSHOT_COMPLETE_KEY:
            completed_generation = _unsigned_generation(value)
            if (
                not duplicate_or_invalid
                and completed_generation == current_generation
                and completed_generation > newest_generation
                and current.get(SNAPSHOT_CONTRACT_KEY)
                == ACTIVE_STATUS_SNAPSHOT_CONTRACT
                and all(field in current for field in ACTIVE_STATUS_KEYS)
            ):
                newest_generation = completed_generation
                newest = {
                    **current,
                    SNAPSHOT_BEGIN_KEY: str(completed_generation),
                    SNAPSHOT_COMPLETE_KEY: str(completed_generation),
                }
            current_generation = None
            current = {}
            duplicate_or_invalid = False
            continue
        if key in current:
            duplicate_or_invalid = True
        current[key] = value

    return newest


def latest_complete_health(path: Path) -> dict[tuple[str, str], str]:
    """Combine ordinary latest status with one completed active snapshot."""

    if not path.exists():
        return {}
    with path.open("r", newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))

    latest: dict[tuple[str, str], str] = {}
    for row in rows:
        if row.get("record_type") != "STS":
            continue
        component = row.get("component", "")
        if component == ACTIVE_STATUS_COMPONENT:
            continue
        latest[(component, row.get("status_key", ""))] = row.get(
            "status_value", ""
        )

    active = latest_complete_active_status(rows)
    latest.update(
        {(ACTIVE_STATUS_COMPONENT, key): value for key, value in active.items()}
    )
    return latest
