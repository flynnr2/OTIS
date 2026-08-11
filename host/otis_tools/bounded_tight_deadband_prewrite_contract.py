"""Bounded tight-deadband identity for the shared pre-write predicate.

The semantics are unchanged from the proven tight-deadband predicate.  The
new identity prevents a completed G1 qualification contract from being
silently treated as live-leg authority.
"""

from __future__ import annotations

from typing import Mapping

from .prewrite_readiness_contract import (
    ACTIVE_STATUS_KEYS,
    HEALTH_INTEGRITY_EXACT,
    Health,
    PrewriteHealthIntegrity,
    PrewriteReadiness,
    canonical_prewrite_fixture as _canonical_prewrite_fixture,
    environment_streams_ready,
    evaluate_prewrite_readiness as _evaluate_prewrite_readiness,
)
from .host_attach_health_contract import (
    FRESH_HOST_ATTACH_MAXIMUM_UPTIME_S,
    TELEMETRY_BASELINE_STABLE_OBSERVATIONS,
    TELEMETRY_DROP_KEY,
    evaluate_health_integrity,
    evaluate_telemetry_drop_history,
    telemetry_drop_observations,
)
from .no_write_prewrite_readiness_contract import (
    GNSS_PREWRITE_EXACT,
    INHERITED_PREVIEW_BASELINE_PROVENANCE,
    RAW_PPS_QUALIFICATION_DEADLINE_S,
)


RUNTIME_CONTRACT_ID = "cx319_g2_prewrite_runtime_contract_v5"
def evaluate_prewrite_readiness(
    health: Health,
    *,
    expected_identity: Mapping[str, str],
    planned_live_stimulus_code: int,
    active_row_count: int,
    dac_row_count: int,
    telemetry_drop_baseline: int = 0,
) -> PrewriteReadiness:
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
    return PrewriteReadiness(
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
    "FRESH_HOST_ATTACH_MAXIMUM_UPTIME_S",
    "GNSS_PREWRITE_EXACT",
    "INHERITED_PREVIEW_BASELINE_PROVENANCE",
    "RUNTIME_CONTRACT_ID",
    "RAW_PPS_QUALIFICATION_DEADLINE_S",
    "TELEMETRY_BASELINE_STABLE_OBSERVATIONS",
    "TELEMETRY_DROP_KEY",
    "PrewriteHealthIntegrity",
    "PrewriteReadiness",
    "canonical_prewrite_fixture",
    "environment_streams_ready",
    "evaluate_health_integrity",
    "evaluate_prewrite_readiness",
    "evaluate_telemetry_drop_history",
    "telemetry_drop_observations",
]
