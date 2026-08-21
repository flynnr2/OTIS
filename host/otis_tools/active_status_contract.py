"""Complete-generation contract for command-bearing active status."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Mapping


ACTIVE_STATUS_SNAPSHOT_CONTRACT = "cx317_active_status_snapshot_v1"
CX321_ACTIVE_STATUS_SNAPSHOT_CONTRACT = "cx321_active_status_snapshot_v2"
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
    "setup_gnss_eligible",
    "setup_reference_eligible",
    "setup_partition_healthy",
    "hybrid_state",
    "hybrid_reason",
    "first_phase_checkpoint_passed",
    "phase_nonzero_application_count",
    "phase_material_application_count",
    "frequency_only_application_count",
    "session_id",
    "query_nonce",
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
CX321_ACTIVE_STATUS_KEYS = (
    *ACTIVE_STATUS_KEYS,
    "plant_sign_state",
    "plant_sign_pre_window_count",
    "plant_sign_accumulator_accepted_intervals",
    "plant_sign_arm_window_eligible",
    "plant_sign_gate_sha256",
    "identification_estimator_sha256",
    "identification_estimator_config_sha256",
    "natural_frequency_estimator_sha256",
)
ACTIVE_STATUS_CONTRACT_KEYS = {
    ACTIVE_STATUS_SNAPSHOT_CONTRACT: ACTIVE_STATUS_KEYS,
    CX321_ACTIVE_STATUS_SNAPSHOT_CONTRACT: CX321_ACTIVE_STATUS_KEYS,
}
ACTIVE_STATUS_WIRE_KEYS = (
    SNAPSHOT_BEGIN_KEY,
    SNAPSHOT_CONTRACT_KEY,
    *ACTIVE_STATUS_KEYS,
    SNAPSHOT_COMPLETE_KEY,
)
CX321_ACTIVE_STATUS_WIRE_KEYS = (
    SNAPSHOT_BEGIN_KEY,
    SNAPSHOT_CONTRACT_KEY,
    *CX321_ACTIVE_STATUS_KEYS,
    SNAPSHOT_COMPLETE_KEY,
)
ALL_ACTIVE_STATUS_WIRE_KEYS = frozenset(
    (*ACTIVE_STATUS_WIRE_KEYS, *CX321_ACTIVE_STATUS_WIRE_KEYS)
)


def active_status_wire_keys(contract: str) -> tuple[str, ...] | None:
    keys = ACTIVE_STATUS_CONTRACT_KEYS.get(contract)
    if keys is None:
        return None
    return (
        SNAPSHOT_BEGIN_KEY,
        SNAPSHOT_CONTRACT_KEY,
        *keys,
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

    snapshots, newest_started_generation = complete_active_status_snapshots(
        rows
    )
    if not snapshots:
        return {}
    newest = snapshots[-1]
    generation = int(newest[SNAPSHOT_COMPLETE_KEY])
    # A newer generation that began but did not complete exactly is current
    # negative evidence. Never fall back to an older eligible generation.
    return newest if generation == newest_started_generation else {}


def complete_active_status_snapshots(
    rows: Iterable[Mapping[str, str]],
) -> tuple[list[dict[str, str]], int]:
    """Return every exact snapshot plus the newest generation that began."""

    current_generation: int | None = None
    current: dict[str, str] = {}
    duplicate_or_invalid = False
    newest_started_generation = 0
    snapshots: list[dict[str, str]] = []

    for row in rows:
        if row.get("record_type") != "STS" or row.get("component") != (
            ACTIVE_STATUS_COMPONENT
        ):
            continue
        key = row.get("status_key", "")
        value = row.get("status_value", "")
        if key == SNAPSHOT_BEGIN_KEY:
            current_generation = _unsigned_generation(value)
            if current_generation is not None:
                newest_started_generation = max(
                    newest_started_generation, current_generation
                )
            current = {}
            duplicate_or_invalid = current_generation is None
            continue
        if current_generation is None:
            continue
        if key == SNAPSHOT_COMPLETE_KEY:
            completed_generation = _unsigned_generation(value)
            contract = current.get(SNAPSHOT_CONTRACT_KEY, "")
            required = ACTIVE_STATUS_CONTRACT_KEYS.get(contract)
            if (
                not duplicate_or_invalid
                and completed_generation == current_generation
                and required is not None
                and all(field in current for field in required)
            ):
                snapshots.append({
                    **current,
                    SNAPSHOT_BEGIN_KEY: str(completed_generation),
                    SNAPSHOT_COMPLETE_KEY: str(completed_generation),
                })
            current_generation = None
            current = {}
            duplicate_or_invalid = False
            continue
        if key in current:
            duplicate_or_invalid = True
        current[key] = value

    snapshots.sort(key=lambda item: int(item[SNAPSHOT_COMPLETE_KEY]))
    return snapshots, newest_started_generation


def evaluate_solicited_attach_snapshot_history(
    rows: Iterable[Mapping[str, str]],
    *,
    query_nonce: int,
    frozen_uptime_s: int,
    frozen_generation: int,
    maximum_uptime_s: int | None,
) -> dict[str, object]:
    """Prove the retained attach boundary came from its solicited generation."""

    snapshots, newest_started_generation = complete_active_status_snapshots(rows)
    matching = [
        snapshot
        for snapshot in snapshots
        if snapshot.get("query_nonce") == str(query_nonce)
    ]
    first = matching[0] if matching else None
    try:
        first_generation = (
            int(first[SNAPSHOT_COMPLETE_KEY]) if first is not None else None
        )
        first_uptime_s = int(first["uptime_s"]) if first is not None else None
    except (KeyError, ValueError):
        first_generation = None
        first_uptime_s = None
    exact = (
        query_nonce > 0
        and frozen_uptime_s >= 0
        and (
            maximum_uptime_s is None
            or frozen_uptime_s <= maximum_uptime_s
        )
        and frozen_generation > 0
        and first_generation == frozen_generation
        and first_uptime_s == frozen_uptime_s
        and all(
            int(snapshot.get(SNAPSHOT_COMPLETE_KEY, "0"))
            == int(snapshot.get(SNAPSHOT_BEGIN_KEY, "-1"))
            for snapshot in matching
        )
    )
    return {
        "exact": exact,
        "query_nonce": query_nonce,
        "frozen_uptime_s": frozen_uptime_s,
        "frozen_generation": frozen_generation,
        "maximum_uptime_s": maximum_uptime_s,
        "matching_snapshot_count": len(matching),
        "first_matching_generation": first_generation,
        "first_matching_uptime_s": first_uptime_s,
        "newest_started_generation": newest_started_generation,
    }


def latest_complete_health(
    path: Path, *, required_query_nonce: int | None = None
) -> dict[tuple[str, str], str]:
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
    if required_query_nonce is not None and active.get("query_nonce") != str(
        required_query_nonce
    ):
        active = {}
    latest.update(
        {(ACTIVE_STATUS_COMPONENT, key): value for key, value in active.items()}
    )
    return latest
