"""CX319 identity wrapper for the shared tight-deadband pre-write contract.

The selected relative-phase/hybrid implementation retains its historical
``cx318_preview`` telemetry component name. This wrapper gives the current
programme's pre-write predicate a new contract identity without forking its
semantics. It performs no I/O and grants no actuation authority.
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


RUNTIME_CONTRACT_ID = "cx319_g1_prewrite_runtime_contract_v1"
INHERITED_PREVIEW_BASELINE_PROVENANCE = (
    "cx318_last_confirmed_a828_historical_context_not_current_physical_confirmation"
)


def evaluate_prewrite_readiness(
    health: Health,
    *,
    expected_identity: Mapping[str, str],
    planned_live_stimulus_code: int,
    active_row_count: int,
    dac_row_count: int,
) -> Stage5Readiness:
    return _evaluate_prewrite_readiness(
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


__all__ = [
    "ACTIVE_STATUS_KEYS",
    "HEALTH_INTEGRITY_EXACT",
    "INHERITED_PREVIEW_BASELINE_PROVENANCE",
    "RUNTIME_CONTRACT_ID",
    "Stage5HealthIntegrity",
    "Stage5Readiness",
    "canonical_prewrite_fixture",
    "environment_streams_ready",
    "evaluate_health_integrity",
    "evaluate_prewrite_readiness",
]
