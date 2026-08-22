"""Frozen host programme descriptors for bounded active-hybrid campaigns.

This module contains identities and finite envelopes only.  It deliberately
does not implement estimator, controller, plant-sign, transaction, or verdict
semantics.  The shared host lifecycle uses the descriptor to select the
campaign-specific contracts while the scientific replay modules remain the
authority for their respective decisions.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[2]


@dataclass(frozen=True)
class ActiveHybridProgramme:
    key: str
    programme_id: str
    profile_id: str
    runtime_run_identity: str
    status_programme_id: str
    operation: str
    live_stage: str
    compatibility_floor: str
    manifest_section: str
    policy_id: str
    policy_path: Path
    natural_policy_id: str
    natural_policy_path: Path
    setup_code: int
    maximum_applications: int
    maximum_cumulative_movement_codes: int
    maximum_step_codes: int
    minimum_code: int
    maximum_code: int
    minimum_applied_cadence_s: int
    qualified_duration_s: int
    absolute_wall_limit_s: int
    minimum_natural_phase_material_applications: int
    bundle_id: str
    activation_id: str
    rehearsal_report_type: str
    run_bundle_path: Path
    run_proposal_path: Path
    run_activation_path: Path
    physical_seal_path: Path
    terminal_decisions: frozenset[str]
    healthy_preliminary_decisions: frozenset[str]
    hybrid_states: frozenset[str]
    armable_hybrid_states: frozenset[str]
    identification_required: bool = False
    response_checkpoint_observational: bool = False

    @property
    def campaign_name(self) -> str:
        return self.profile_id

    @property
    def capture_duration_s(self) -> int:
        return self.absolute_wall_limit_s + 180

    @property
    def supervisor_duration_s(self) -> int:
        return self.absolute_wall_limit_s + 120

_COMMON_TERMINALS = frozenset(
    {
        "bounded_active_hybrid_control_passed",
        "phase_influence_not_exercised",
        "first_phase_transaction_passed_sustained_result_incomplete",
        "phase_channel_degraded_frequency_control_retained",
        "hybrid_response_wrong_or_frequency_not_reacquired",
        "hybrid_policy_chatter_or_budget_nonpass",
        "frequency_performance_materially_degraded",
        "right_censored_incomplete",
        "measurement_authority_or_platform_fault",
        "operator_abort",
    }
)

_COMMON_HEALTHY_PRELIMINARY = frozenset(
    {
        "pending_offline_scientific_analysis",
        "phase_influence_not_exercised",
        "first_phase_transaction_passed_sustained_result_incomplete",
        "hybrid_response_wrong_or_frequency_not_reacquired",
    }
)

_COMMON_STATES = frozenset(
    {
        "SETUP_PENDING",
        "FREQUENCY_ACQUIRE",
        "PHASE_QUALIFY",
        "FIRST_PHASE_TRANSACTION",
        "HYBRID_TRACKING",
        "PHASE_DEGRADED_FREQUENCY_ONLY",
        "FAIL_STATIC",
    }
)


CX320_PROGRAMME = ActiveHybridProgramme(
    key="cx320",
    programme_id="CX320_BOUNDED_ACTIVE_HYBRID_PHASE_FREQUENCY_V1",
    profile_id="cx320_active_hybrid",
    runtime_run_identity="cx320_active_hybrid:3200001",
    status_programme_id="cx320_bounded_active_hybrid",
    operation="cx320_stage5_bounded_active_hybrid_live",
    live_stage="CX320_BOUNDED_ACTIVE_HYBRID_PHASE_FREQUENCY_LIVE",
    compatibility_floor="CX320_EVIDENCE_EPOCH_1",
    manifest_section="cx320",
    policy_id="CX320_BOUNDED_ACTIVE_HYBRID_TIGHT_V1",
    policy_path=REPO_ROOT
    / "profiles/discipline/cx320_bounded_active_hybrid_tight_v1.json",
    natural_policy_id="CX320_BOUNDED_ACTIVE_HYBRID_TIGHT_V1",
    natural_policy_path=REPO_ROOT
    / "profiles/discipline/cx320_bounded_active_hybrid_tight_v1.json",
    setup_code=0xA83C,
    maximum_applications=4,
    maximum_cumulative_movement_codes=84,
    maximum_step_codes=21,
    minimum_code=0xA800,
    maximum_code=0xAB00,
    minimum_applied_cadence_s=1800,
    qualified_duration_s=43_200,
    absolute_wall_limit_s=57_600,
    minimum_natural_phase_material_applications=2,
    bundle_id="cx320_active_hybrid_12h_qualified_16h_wall_bundle_v1",
    activation_id="cx320_active_hybrid_12h_live_activation_v1",
    rehearsal_report_type="cx320_active_hybrid_live_topology_rehearsal_v1",
    run_bundle_path=Path("cx320_active_hybrid_exact_bundle_v1.json"),
    run_proposal_path=Path("cx320_active_hybrid_authority_proposal_v1.json"),
    run_activation_path=Path("cx320_active_hybrid_live_activation_v1.json"),
    physical_seal_path=Path("reports/cx320_active_hybrid_physical_seal_v1.json"),
    terminal_decisions=_COMMON_TERMINALS,
    healthy_preliminary_decisions=_COMMON_HEALTHY_PRELIMINARY,
    hybrid_states=_COMMON_STATES,
    armable_hybrid_states=frozenset(
        {"FREQUENCY_ACQUIRE", "PHASE_QUALIFY", "HYBRID_TRACKING"}
    ),
)


CX321_PROGRAMME = ActiveHybridProgramme(
    key="cx321",
    programme_id="CX321_BOUNDED_ACTIVE_HYBRID_SUCCESSOR_V2",
    profile_id="cx321_active_hybrid",
    runtime_run_identity="cx321_active_hybrid:3210001",
    status_programme_id="cx321_bounded_active_hybrid_successor",
    operation="cx321_stage5_bounded_active_hybrid_live",
    live_stage="CX321_BOUNDED_ACTIVE_HYBRID_PLANT_SIGN_LIVE",
    compatibility_floor="CX321_EVIDENCE_EPOCH_1",
    manifest_section="cx321",
    policy_id="CX321_BOUNDED_ACTIVE_HYBRID_PLANT_SIGN_V2",
    policy_path=REPO_ROOT
    / "profiles/discipline/cx321_bounded_active_hybrid_plant_sign_v2.json",
    natural_policy_id="CX320_BOUNDED_ACTIVE_HYBRID_TIGHT_V1",
    natural_policy_path=REPO_ROOT
    / "profiles/discipline/cx320_bounded_active_hybrid_tight_v1.json",
    setup_code=0xA83C,
    maximum_applications=4,
    maximum_cumulative_movement_codes=84,
    maximum_step_codes=21,
    minimum_code=0xA800,
    maximum_code=0xAB00,
    minimum_applied_cadence_s=1800,
    qualified_duration_s=43_200,
    absolute_wall_limit_s=57_600,
    minimum_natural_phase_material_applications=2,
    bundle_id="cx321_active_hybrid_12h_qualified_16h_wall_bundle_v1",
    activation_id="cx321_active_hybrid_12h_live_activation_v1",
    rehearsal_report_type="cx321_active_hybrid_live_topology_rehearsal_v1",
    run_bundle_path=Path("cx321_active_hybrid_exact_bundle_v1.json"),
    run_proposal_path=Path("cx321_active_hybrid_authority_proposal_v1.json"),
    run_activation_path=Path("cx321_active_hybrid_live_activation_v1.json"),
    physical_seal_path=Path("reports/cx321_active_hybrid_physical_seal_v1.json"),
    terminal_decisions=_COMMON_TERMINALS
    | {"plant_sign_qualification_not_exercised", "plant_sign_qualification_failed"},
    healthy_preliminary_decisions=_COMMON_HEALTHY_PRELIMINARY
    | {"plant_sign_qualification_not_exercised"},
    hybrid_states=_COMMON_STATES | {"PLANT_SIGN_QUALIFY"},
    armable_hybrid_states=frozenset(
        {"PLANT_SIGN_QUALIFY", "PHASE_QUALIFY", "HYBRID_TRACKING"}
    ),
    identification_required=True,
)


CX322_PROGRAMME = ActiveHybridProgramme(
    key="cx322",
    programme_id="CX322_BOUNDED_HYBRID_FACT_GATHERING_V1",
    profile_id="cx322_direct_hybrid",
    runtime_run_identity="cx322_direct_hybrid:3220001",
    status_programme_id="cx322_bounded_hybrid_fact_gathering",
    operation="cx322_stage5_bounded_hybrid_fact_gathering_live",
    live_stage="CX322_BOUNDED_HYBRID_FACT_GATHERING_LIVE",
    compatibility_floor="CX322_EVIDENCE_EPOCH_1",
    manifest_section="cx322",
    policy_id="CX322_BOUNDED_HYBRID_FACT_GATHERING_V1",
    policy_path=REPO_ROOT
    / "profiles/discipline/cx322_bounded_hybrid_fact_gathering_v1.json",
    natural_policy_id="CX322_BOUNDED_HYBRID_FACT_GATHERING_V1",
    natural_policy_path=REPO_ROOT
    / "profiles/discipline/cx322_bounded_hybrid_fact_gathering_v1.json",
    setup_code=0xA83C,
    maximum_applications=4,
    maximum_cumulative_movement_codes=84,
    maximum_step_codes=21,
    minimum_code=0xA800,
    maximum_code=0xAB00,
    minimum_applied_cadence_s=1800,
    qualified_duration_s=43_200,
    absolute_wall_limit_s=57_600,
    minimum_natural_phase_material_applications=2,
    bundle_id="cx322_direct_hybrid_12h_qualified_16h_wall_bundle_v1",
    activation_id="cx322_direct_hybrid_12h_live_activation_v1",
    rehearsal_report_type="cx322_direct_hybrid_live_topology_rehearsal_v1",
    run_bundle_path=Path("cx322_direct_hybrid_exact_bundle_v1.json"),
    run_proposal_path=Path("cx322_direct_hybrid_authority_proposal_v1.json"),
    run_activation_path=Path("cx322_direct_hybrid_live_activation_v1.json"),
    physical_seal_path=Path("reports/cx322_direct_hybrid_physical_seal_v1.json"),
    terminal_decisions=frozenset(
        {
            "bounded_direct_hybrid_evidence_acquired",
            "bounded_direct_hybrid_early_safety_stop",
            "right_censored_incomplete",
            "measurement_authority_or_platform_fault",
            "operator_abort",
        }
    ),
    healthy_preliminary_decisions=frozenset(
        {"pending_offline_scientific_analysis"}
    ),
    hybrid_states=_COMMON_STATES,
    armable_hybrid_states=frozenset(
        {
            "FREQUENCY_ACQUIRE",
            "PHASE_QUALIFY",
            "HYBRID_TRACKING",
            "PHASE_DEGRADED_FREQUENCY_ONLY",
        }
    ),
    response_checkpoint_observational=True,
)


PROGRAMMES = {
    CX320_PROGRAMME.key: CX320_PROGRAMME,
    CX321_PROGRAMME.key: CX321_PROGRAMME,
    CX322_PROGRAMME.key: CX322_PROGRAMME,
}


def get_active_hybrid_programme(
    value: str | ActiveHybridProgramme | None = None,
) -> ActiveHybridProgramme:
    if value is None:
        return CX320_PROGRAMME
    if isinstance(value, ActiveHybridProgramme):
        return value
    normalized = value.strip().lower()
    for programme in PROGRAMMES.values():
        if normalized in {
            programme.key,
            programme.programme_id.lower(),
            programme.profile_id.lower(),
            programme.runtime_run_identity.lower(),
        }:
            return programme
    raise ValueError(f"unknown active-hybrid programme: {value!r}")


def programme_from_mapping(value: Mapping[str, Any]) -> ActiveHybridProgramme:
    for field in ("programme_id", "profile_identity", "run_identity"):
        candidate = value.get(field)
        if isinstance(candidate, str):
            try:
                return get_active_hybrid_programme(candidate)
            except ValueError:
                pass
    raise ValueError("active-hybrid artifact does not identify a supported programme")


def progressive_checkpoint_contract(
    programme: ActiveHybridProgramme,
) -> dict[str, Any]:
    common = {
        "first_phase_material_applications_before_checkpoint": 1,
        "first_response_acknowledgement_requires_durable_AHY_and_ACT": True,
        "first_response_acknowledgement_requires_exact_host_replay": True,
    }
    if programme.response_checkpoint_observational:
        return {
            **common,
            "descriptive_minimum_phase_material_applications": (
                programme.minimum_natural_phase_material_applications
            ),
            "phase_material_application_count_is_acquisition_pass_gate": False,
            "later_authority_requires_exact_response_observation_and_tight_reacquisition": True,
        }
    return {
        **common,
        "minimum_phase_material_applications_for_pass": (
            programme.minimum_natural_phase_material_applications
        ),
        "later_authority_requires_healthy_response_and_tight_reacquisition": True,
    }
