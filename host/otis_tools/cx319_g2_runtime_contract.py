"""CX319 G2 identity for the shared pre-write runtime predicate.

The semantics are unchanged from the proven tight-deadband predicate.  The
new identity prevents a completed G1 qualification contract from being
silently treated as live-leg authority.
"""

from __future__ import annotations

from typing import Mapping

from .cx318_stage5_runtime_contract import (
    ACTIVE_STATUS_KEYS,
    HEALTH_INTEGRITY_EXACT,
    Health,
    Stage5HealthIntegrity,
    Stage5Readiness,
    canonical_prewrite_fixture,
    environment_streams_ready,
    evaluate_health_integrity,
    evaluate_prewrite_readiness as _evaluate_prewrite_readiness,
)
from .cx319_runtime_contract import INHERITED_PREVIEW_BASELINE_PROVENANCE


RUNTIME_CONTRACT_ID = "cx319_g2_prewrite_runtime_contract_v2"
FRESH_RESTART_MAXIMUM_UPTIME_S = 120


def evaluate_prewrite_readiness(
    health: Health,
    *,
    expected_identity: Mapping[str, str],
    planned_live_stimulus_code: int,
    active_row_count: int,
    dac_row_count: int,
) -> Stage5Readiness:
    base = _evaluate_prewrite_readiness(
        health,
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
        missing=tuple(missing),
        mismatches=tuple(mismatches),
        inherited_preview_baseline_code=base.inherited_preview_baseline_code,
        inherited_preview_baseline_provenance=(
            base.inherited_preview_baseline_provenance
        ),
        planned_live_stimulus_code=base.planned_live_stimulus_code,
        physical_dac_confirmation=base.physical_dac_confirmation,
    )


__all__ = [
    "ACTIVE_STATUS_KEYS",
    "HEALTH_INTEGRITY_EXACT",
    "FRESH_RESTART_MAXIMUM_UPTIME_S",
    "INHERITED_PREVIEW_BASELINE_PROVENANCE",
    "RUNTIME_CONTRACT_ID",
    "Stage5HealthIntegrity",
    "Stage5Readiness",
    "canonical_prewrite_fixture",
    "environment_streams_ready",
    "evaluate_health_integrity",
    "evaluate_prewrite_readiness",
]
