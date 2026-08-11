"""CX319 G2 identity for the shared pre-write runtime predicate.

The semantics are unchanged from the proven tight-deadband predicate.  The
new identity prevents a completed G1 qualification contract from being
silently treated as live-leg authority.
"""

from __future__ import annotations

from typing import Iterable, Mapping

from .cx318_stage5_runtime_contract import (
    ACTIVE_STATUS_KEYS,
    HEALTH_INTEGRITY_EXACT,
    Health,
    Stage5HealthIntegrity,
    Stage5Readiness,
    canonical_prewrite_fixture as _canonical_prewrite_fixture,
    environment_streams_ready,
    evaluate_health_integrity as _evaluate_health_integrity,
    evaluate_prewrite_readiness as _evaluate_prewrite_readiness,
)
from .cx319_runtime_contract import INHERITED_PREVIEW_BASELINE_PROVENANCE


RUNTIME_CONTRACT_ID = "cx319_g2_prewrite_runtime_contract_v4"
FRESH_RESTART_MAXIMUM_UPTIME_S = 120
TELEMETRY_DROP_KEY = ("dual_core", "telemetry_dropped")
TELEMETRY_BASELINE_STABLE_OBSERVATIONS = 2
GNSS_PREWRITE_EXACT = {
    ("gnss_receiver", "initialized"): "true",
    ("gnss_receiver", "rx_only"): "true",
    ("gnss_receiver", "metadata_fresh"): "true",
    ("gnss_receiver", "checksum_requalified"): "true",
    ("gnss_receiver", "gsa_3d_fresh"): "true",
    ("gnss_receiver", "gsa_checksum_requalified"): "true",
    ("gnss_receiver", "identity_epoch"): "1",
    ("gnss_receiver", "identity_stable"): "true",
    ("gnss_receiver", "metadata_control_eligible"): "true",
    ("gnss_receiver", "raw_pps_control_eligible"): "true",
    ("gnss_receiver", "control_eligible"): "true",
}


def evaluate_health_integrity(
    health: Health,
    *,
    telemetry_drop_baseline: int = 0,
) -> Stage5HealthIntegrity:
    """Apply the shared health contract relative to an observed attach baseline.

    Ordinary cross-core telemetry is explicitly lossy firmware diagnostics. A
    cumulative value established before the host has drained its first backlog
    is retained, while every evidence, capture, preview, partition and control
    invariant remains absolute. Any later telemetry increment is a mismatch.
    """

    normalized = dict(health)
    observed = health.get(TELEMETRY_DROP_KEY)
    additional_missing: list[str] = []
    additional_mismatches: list[str] = []
    if observed is None:
        additional_missing.append("missing dual_core.telemetry_dropped")
    else:
        try:
            observed_value = int(observed)
        except ValueError:
            additional_mismatches.append(
                "dual_core.telemetry_dropped="
                f"{observed!r}, expected unsigned integer"
            )
        else:
            if observed_value < 0:
                additional_mismatches.append(
                    "dual_core.telemetry_dropped="
                    f"{observed!r}, expected unsigned integer"
                )
            elif observed_value != telemetry_drop_baseline:
                additional_mismatches.append(
                    "dual_core.telemetry_dropped="
                    f"{observed!r}, expected frozen host-attach baseline "
                    f"{telemetry_drop_baseline}"
                )
        normalized[TELEMETRY_DROP_KEY] = "0"
    base = _evaluate_health_integrity(normalized)
    missing = tuple(dict.fromkeys((*base.missing, *additional_missing)))
    mismatches = tuple(
        dict.fromkeys((*base.mismatches, *additional_mismatches))
    )
    return Stage5HealthIntegrity(
        clean=not missing and not mismatches,
        missing=missing,
        mismatches=mismatches,
    )


def telemetry_drop_observations(
    rows: Iterable[Mapping[str, str]],
) -> list[tuple[int, int]]:
    """Return ordered `(status_seq, cumulative_drop_count)` observations."""

    observations: list[tuple[int, int]] = []
    for row in rows:
        if (
            row.get("record_type") != "STS"
            or row.get("component") != TELEMETRY_DROP_KEY[0]
            or row.get("status_key") != TELEMETRY_DROP_KEY[1]
        ):
            continue
        try:
            status_seq = int(row.get("status_seq", ""))
            value = int(row.get("status_value", ""))
        except ValueError as exc:
            raise ValueError(
                "malformed dual_core.telemetry_dropped observation"
            ) from exc
        if status_seq <= 0 or value < 0:
            raise ValueError(
                "dual_core.telemetry_dropped observation must have positive "
                "status_seq and unsigned value"
            )
        observations.append((status_seq, value))
    return observations


def evaluate_telemetry_drop_history(
    rows: Iterable[Mapping[str, str]],
    *,
    frozen_baseline: int,
    frozen_status_seq: int,
) -> dict[str, object]:
    observations = telemetry_drop_observations(rows)
    status_sequences = [status_seq for status_seq, _ in observations]
    values = [value for _, value in observations]
    status_sequences_strictly_increasing = all(
        later > earlier
        for earlier, later in zip(status_sequences, status_sequences[1:])
    )
    nondecreasing = all(
        later >= earlier for earlier, later in zip(values, values[1:])
    )
    post_freeze = [
        value for status_seq, value in observations
        if status_seq >= frozen_status_seq
    ]
    freeze_index = next(
        (
            index
            for index, (status_seq, _value) in enumerate(observations)
            if status_seq == frozen_status_seq
        ),
        None,
    )
    stable_before_freeze = (
        freeze_index is not None
        and freeze_index >= TELEMETRY_BASELINE_STABLE_OBSERVATIONS - 1
        and all(
            observations[index][1] == frozen_baseline
            for index in range(
                freeze_index - TELEMETRY_BASELINE_STABLE_OBSERVATIONS + 1,
                freeze_index + 1,
            )
        )
    )
    exact = (
        frozen_baseline >= 0
        and frozen_status_seq > 0
        and status_sequences_strictly_increasing
        and nondecreasing
        and stable_before_freeze
        and bool(post_freeze)
        and all(value == frozen_baseline for value in post_freeze)
    )
    return {
        "exact": exact,
        "frozen_baseline": frozen_baseline,
        "frozen_status_seq": frozen_status_seq,
        "observation_count": len(observations),
        "observations": [
            {"status_seq": status_seq, "value": value}
            for status_seq, value in observations
        ],
        "status_sequences_strictly_increasing": (
            status_sequences_strictly_increasing
        ),
        "nondecreasing_before_freeze": nondecreasing,
        "stable_observations_required": (
            TELEMETRY_BASELINE_STABLE_OBSERVATIONS
        ),
        "stable_before_freeze": stable_before_freeze,
        "no_increment_after_freeze": (
            bool(post_freeze)
            and all(value == frozen_baseline for value in post_freeze)
        ),
    }


def evaluate_prewrite_readiness(
    health: Health,
    *,
    expected_identity: Mapping[str, str],
    planned_live_stimulus_code: int,
    active_row_count: int,
    dac_row_count: int,
    telemetry_drop_baseline: int = 0,
) -> Stage5Readiness:
    normalized = dict(health)
    observed_telemetry = health.get(TELEMETRY_DROP_KEY)
    if observed_telemetry is not None:
        normalized[TELEMETRY_DROP_KEY] = "0"
    base = _evaluate_prewrite_readiness(
        normalized,
        expected_identity=expected_identity,
        planned_live_stimulus_code=planned_live_stimulus_code,
        active_row_count=active_row_count,
        dac_row_count=dac_row_count,
        contract_id=RUNTIME_CONTRACT_ID,
        inherited_preview_baseline_provenance=(
            INHERITED_PREVIEW_BASELINE_PROVENANCE
        ),
    )
    missing = list(base.missing)
    mismatches = list(base.mismatches)
    telemetry_integrity = evaluate_health_integrity(
        health, telemetry_drop_baseline=telemetry_drop_baseline
    )
    missing.extend(telemetry_integrity.missing)
    mismatches.extend(telemetry_integrity.mismatches)
    for key, required in GNSS_PREWRITE_EXACT.items():
        observed = health.get(key)
        name = f"{key[0]}.{key[1]}"
        if observed is None:
            missing.append(f"missing {name}")
        elif observed != required:
            mismatches.append(
                f"{name}={observed!r}, expected {required!r} before setup"
            )
    raw_uptime = health.get(("cx317_active", "uptime_s"))
    if raw_uptime is not None:
        try:
            uptime_s = int(raw_uptime)
        except ValueError:
            # The inherited predicate already reports the malformed value.
            pass
        else:
            if uptime_s > FRESH_RESTART_MAXIMUM_UPTIME_S:
                mismatches.append(
                    "cx317_active.uptime_s="
                    f"{raw_uptime!r}, expected at most "
                    f"{FRESH_RESTART_MAXIMUM_UPTIME_S} after a fresh restart"
                )
    return Stage5Readiness(
        contract_id=base.contract_id,
        ready=not missing and not mismatches,
        missing=tuple(dict.fromkeys(missing)),
        mismatches=tuple(dict.fromkeys(mismatches)),
        inherited_preview_baseline_code=base.inherited_preview_baseline_code,
        inherited_preview_baseline_provenance=(
            base.inherited_preview_baseline_provenance
        ),
        planned_live_stimulus_code=base.planned_live_stimulus_code,
        physical_dac_confirmation=base.physical_dac_confirmation,
    )


def canonical_prewrite_fixture(
    *,
    expected_identity: Mapping[str, str],
    planned_live_stimulus_code: int,
) -> dict[tuple[str, str], str]:
    """Return the exact healthy G2 fixture, including GNSS authority."""

    health = _canonical_prewrite_fixture(
        expected_identity=expected_identity,
        planned_live_stimulus_code=planned_live_stimulus_code,
    )
    health.update(GNSS_PREWRITE_EXACT)
    return health


__all__ = [
    "ACTIVE_STATUS_KEYS",
    "HEALTH_INTEGRITY_EXACT",
    "FRESH_RESTART_MAXIMUM_UPTIME_S",
    "GNSS_PREWRITE_EXACT",
    "INHERITED_PREVIEW_BASELINE_PROVENANCE",
    "RUNTIME_CONTRACT_ID",
    "TELEMETRY_BASELINE_STABLE_OBSERVATIONS",
    "TELEMETRY_DROP_KEY",
    "Stage5HealthIntegrity",
    "Stage5Readiness",
    "canonical_prewrite_fixture",
    "environment_streams_ready",
    "evaluate_health_integrity",
    "evaluate_prewrite_readiness",
    "evaluate_telemetry_drop_history",
    "telemetry_drop_observations",
]
