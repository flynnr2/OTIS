"""CX319 G1 pre-write contract for no-write firmware qualification.

The selected relative-phase/hybrid implementation retains its historical
``cx318_preview`` telemetry component name. This wrapper gives the current
programme's no-write qualification a distinct contract identity and requires
the GNSS receiver state needed by G2. It performs no I/O and grants no
actuation authority.
"""

from __future__ import annotations

from typing import Mapping

from .cx318_stage5_runtime_contract import (
    ACTIVE_STATUS_KEYS,
    HEALTH_INTEGRITY_EXACT,
    Health,
    Stage5HealthIntegrity,
    Stage5Readiness,
    canonical_prewrite_fixture as _canonical_prewrite_fixture,
    environment_streams_ready,
    evaluate_prewrite_readiness as _evaluate_prewrite_readiness,
)
from .cx319_host_attach_contract import (
    TELEMETRY_BASELINE_STABLE_OBSERVATIONS,
    TELEMETRY_DROP_KEY,
    evaluate_health_integrity,
    evaluate_telemetry_drop_history,
    telemetry_drop_observations,
)


RUNTIME_CONTRACT_ID = "cx319_g1_prewrite_runtime_contract_v2"
INHERITED_PREVIEW_BASELINE_PROVENANCE = (
    "cx318_last_confirmed_a828_historical_context_not_current_physical_confirmation"
)
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
    if health.get(TELEMETRY_DROP_KEY) is not None:
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
                f"{name}={observed!r}, expected {required!r} during G1"
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
    health = _canonical_prewrite_fixture(
        expected_identity=expected_identity,
        planned_live_stimulus_code=planned_live_stimulus_code,
    )
    health.update(GNSS_PREWRITE_EXACT)
    return health


__all__ = [
    "ACTIVE_STATUS_KEYS",
    "GNSS_PREWRITE_EXACT",
    "HEALTH_INTEGRITY_EXACT",
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
