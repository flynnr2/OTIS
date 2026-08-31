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

CX323_REHEARSAL_COVERAGE = (
    "cx323_exact_AT2_AH2_AHM_atomic_capture",
    "cx323_repeated_controller_transaction",
    "cx323_GNSS_hold_causal_requalification",
    "cx323_exact_72h_endpoint_clock",
    "cx323_authoritative_capture_fault_terminal",
)


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
    maximum_physical_applications: int
    maximum_deliberate_challenges: int
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
    sustained_regulation: bool = False
    sustained_status_contract: bool = False
    prospectively_changed_authority_envelope: bool = False
    forwarded_output_integration: bool = False
    fresh_serial_auto_detect: bool = False
    natural_policy_programme_id: str | None = None
    engineering_unarmed_observation_s: int = 0
    engineering_maximum_applications: int | None = None
    engineering_maximum_physical_applications: int | None = None
    engineering_maximum_cumulative_movement_codes: int | None = None
    engineering_absolute_wall_limit_s: int | None = None
    terminal_after_first_response: bool = False
    engineering_contract_path: Path | None = None
    firmware_campaign_macro: str | None = None
    firmware_hybrid_maximum_automatic_applications: int | None = None
    firmware_hybrid_maximum_cumulative_movement_codes: int | None = None
    correction_response_reserve_s: int = 1800
    accelerated_rehearsal_terminal_classifications: tuple[
        tuple[str, str], ...
    ] = ()
    integrated_long_run: bool = False
    persistent_maintenance_policy: bool = False
    maintenance_record_type: str | None = None
    maintenance_record_contract: str | None = None
    controller_inhibit_acquisition_continues: bool = False
    gnss_metadata_hold_nonterminal: bool = False
    qualified_endpoint_reason_override: str | None = None

    @property
    def campaign_name(self) -> str:
        return self.profile_id

    @property
    def capture_duration_s(self) -> int:
        return self.authorized_absolute_wall_limit_s + 180

    @property
    def supervisor_duration_s(self) -> int:
        return self.authorized_absolute_wall_limit_s + 120

    @property
    def qualified_endpoint_reason(self) -> str:
        if self.qualified_endpoint_reason_override is not None:
            return self.qualified_endpoint_reason_override
        duration = (
            f"{self.qualified_duration_s // 3600}h"
            if self.qualified_duration_s % 3600 == 0
            else f"{self.qualified_duration_s}s"
        )
        return f"{self.key}_{duration}_qualified_endpoint_complete"

    @property
    def authorized_maximum_applications(self) -> int:
        return self.engineering_maximum_applications or self.maximum_applications

    @property
    def authorized_maximum_physical_applications(self) -> int:
        return (
            self.engineering_maximum_physical_applications
            or self.maximum_physical_applications
        )

    @property
    def authorized_maximum_cumulative_movement_codes(self) -> int:
        return (
            self.engineering_maximum_cumulative_movement_codes
            or self.maximum_cumulative_movement_codes
        )

    @property
    def authorized_absolute_wall_limit_s(self) -> int:
        return self.engineering_absolute_wall_limit_s or self.absolute_wall_limit_s


def integrated_setup_provenance_contract(
    programme: ActiveHybridProgramme,
) -> dict[str, Any]:
    """Freeze setup semantics when the physical boot DAC code is unreadable."""

    if not programme.forwarded_output_integration:
        raise ValueError("setup-provenance contract is integration-specific")
    return {
        "physical_applied_code_before_setup": (
            "unknown_unreadable_after_power_cycle"
        ),
        "firmware_dac_epoch_before_setup": (
            "zero_is_new_firmware_session_not_physical_DAC_history"
        ),
        "pre_setup_query": "DAC?_required_expected_to_report_unavailable",
        "authorized_setup_code": programme.setup_code,
        "authorized_setup_code_hex": f"0x{programme.setup_code:04X}",
        "setup_operation": (
            "prospectively_frozen_authorized_stimulus_not_restoration"
        ),
        "first_confirmed_state_boundary": (
            "exact_setup_acceptance_application_DAC_epoch_and_first_dependent_consumer"
        ),
        "prior_or_nominal_state_inferred": False,
        "automatic_or_nominal_restoration": False,
    }

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
    maximum_physical_applications=4,
    maximum_deliberate_challenges=0,
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
    maximum_physical_applications=4,
    maximum_deliberate_challenges=0,
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
    maximum_physical_applications=4,
    maximum_deliberate_challenges=0,
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


CX322_D9_D6_INTEGRATION_PROGRAMME = ActiveHybridProgramme(
    key="cx322_d9_d6_integration",
    programme_id="OTIS_CX322_D9_D6_INTEGRATION_ENGINEERING_V1",
    profile_id="cx322_d9_d6_integration_engineering",
    runtime_run_identity="cx322_d9_d6_integration_engineering:1",
    status_programme_id="cx322_d9_d6_integration_engineering",
    operation="cx322_d9_d6_integration_engineering_live",
    live_stage="OTIS_CX322_D9_D6_INTEGRATION_ENGINEERING_LIVE",
    compatibility_floor="OTIS_CX322_D9_D6_INTEGRATION_EVIDENCE_EPOCH_1",
    manifest_section="cx322_d9_d6_integration",
    policy_id="CX322_BOUNDED_HYBRID_FACT_GATHERING_V1",
    policy_path=REPO_ROOT
    / "profiles/discipline/cx322_bounded_hybrid_fact_gathering_v1.json",
    natural_policy_id="CX322_BOUNDED_HYBRID_FACT_GATHERING_V1",
    natural_policy_path=REPO_ROOT
    / "profiles/discipline/cx322_bounded_hybrid_fact_gathering_v1.json",
    setup_code=0xA83C,
    maximum_applications=4,
    maximum_physical_applications=4,
    maximum_deliberate_challenges=0,
    maximum_cumulative_movement_codes=84,
    maximum_step_codes=21,
    minimum_code=0xA800,
    maximum_code=0xAB00,
    minimum_applied_cadence_s=1800,
    qualified_duration_s=43_200,
    absolute_wall_limit_s=57_600,
    minimum_natural_phase_material_applications=2,
    bundle_id="cx322_d9_d6_integration_engineering_bundle_v1",
    activation_id="cx322_d9_d6_integration_engineering_activation_v1",
    rehearsal_report_type="cx322_d9_d6_integration_live_topology_rehearsal_v1",
    run_bundle_path=Path("cx322_d9_d6_integration_exact_bundle_v1.json"),
    run_proposal_path=Path("cx322_d9_d6_integration_authority_proposal_v1.json"),
    run_activation_path=Path("cx322_d9_d6_integration_live_activation_v1.json"),
    physical_seal_path=Path(
        "reports/cx322_d9_d6_integration_physical_seal_v1.json"
    ),
    terminal_decisions=frozenset(
        {
            "bounded_integrated_engineering_evidence_acquired",
            "bounded_integrated_engineering_early_safety_stop",
            "pre_setup_provenance_unresolved",
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
    forwarded_output_integration=True,
    fresh_serial_auto_detect=True,
    natural_policy_programme_id="CX322_BOUNDED_HYBRID_FACT_GATHERING_V1",
    engineering_unarmed_observation_s=1_800,
    engineering_maximum_applications=1,
    engineering_maximum_physical_applications=1,
    engineering_maximum_cumulative_movement_codes=21,
    engineering_absolute_wall_limit_s=7_200,
    terminal_after_first_response=True,
    engineering_contract_path=REPO_ROOT
    / "docs/60_EXPERIMENTS/"
    "OTIS_D9_OUTPUT_AND_ADAPTIVE_STEERING_INTEGRATION_PROGRAMME/"
    "cx322_d9_d6_integration_engineering_contract_v1.json",
)


CX322_D9_D6_72H_PROGRAMME = ActiveHybridProgramme(
    key="cx322_d9_d6_72h",
    programme_id="OTIS_CX322_D9_D6_72H_INTEGRATED_ENGINEERING_V1",
    profile_id="cx322_d9_d6_72h_sustained_engineering",
    runtime_run_identity="cx322_d9_d6_72h_sustained_engineering:1",
    status_programme_id="cx322_d9_d6_72h_sustained_engineering",
    operation="cx322_d9_d6_72h_sustained_engineering_live",
    live_stage="OTIS_CX322_D9_D6_72H_SUSTAINED_ENGINEERING_LIVE",
    compatibility_floor="OTIS_CX322_D9_D6_72H_EVIDENCE_EPOCH_1",
    manifest_section="cx322_d9_d6_72h",
    policy_id="CX322_BOUNDED_HYBRID_FACT_GATHERING_V1",
    policy_path=REPO_ROOT
    / "profiles/discipline/cx322_bounded_hybrid_fact_gathering_v1.json",
    natural_policy_id="CX322_BOUNDED_HYBRID_FACT_GATHERING_V1",
    natural_policy_path=REPO_ROOT
    / "profiles/discipline/cx322_bounded_hybrid_fact_gathering_v1.json",
    setup_code=0xA83C,
    # These are the unchanged CX322 numerical-policy limits.  The distinct
    # engineering authority envelope below changes only how long that law may
    # remain available; it does not select a different controller.
    maximum_applications=4,
    maximum_physical_applications=4,
    maximum_deliberate_challenges=0,
    maximum_cumulative_movement_codes=84,
    maximum_step_codes=21,
    minimum_code=0xA800,
    maximum_code=0xAB00,
    minimum_applied_cadence_s=1800,
    qualified_duration_s=259_200,
    absolute_wall_limit_s=280_800,
    minimum_natural_phase_material_applications=0,
    bundle_id="cx322_d9_d6_72h_sustained_engineering_bundle_v1",
    activation_id="cx322_d9_d6_72h_sustained_engineering_activation_v1",
    rehearsal_report_type="cx322_d9_d6_72h_live_topology_rehearsal_v1",
    run_bundle_path=Path("cx322_d9_d6_72h_exact_bundle_v1.json"),
    run_proposal_path=Path("cx322_d9_d6_72h_authority_proposal_v1.json"),
    run_activation_path=Path("cx322_d9_d6_72h_live_activation_v1.json"),
    physical_seal_path=Path(
        "reports/cx322_d9_d6_72h_physical_seal_v1.json"
    ),
    terminal_decisions=frozenset(
        {
            "cx322_d9_d6_72h_qualified_engineering_complete",
            "cx322_d9_d6_72h_right_censored_incomplete",
            "cx322_d9_d6_72h_D14_D8_authority_or_capture_fault",
            "cx322_d9_d6_72h_D9_configuration_or_readback_fault",
            "cx322_d9_d6_72h_controller_or_transaction_fault",
            "cx322_d9_d6_72h_identity_or_evidence_fault",
            "cx322_d9_d6_72h_operator_abort",
            "cx322_d9_d6_72h_pre_setup_no_write_abort",
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
    sustained_status_contract=True,
    prospectively_changed_authority_envelope=True,
    forwarded_output_integration=True,
    fresh_serial_auto_detect=True,
    natural_policy_programme_id="CX322_BOUNDED_HYBRID_FACT_GATHERING_V1",
    engineering_maximum_applications=144,
    engineering_maximum_physical_applications=144,
    engineering_maximum_cumulative_movement_codes=3_024,
    engineering_absolute_wall_limit_s=280_800,
    engineering_contract_path=REPO_ROOT
    / "docs/60_EXPERIMENTS/"
    "OTIS_D9_OUTPUT_AND_ADAPTIVE_STEERING_INTEGRATION_PROGRAMME/"
    "cx322_d9_d6_72h_integrated_engineering_contract_v1.json",
    firmware_campaign_macro=(
        "OTIS_CX317_ACTIVE_CAMPAIGN_D9_D6_72H_SUSTAINED_HYBRID"
    ),
    firmware_hybrid_maximum_automatic_applications=144,
    firmware_hybrid_maximum_cumulative_movement_codes=3_024,
    correction_response_reserve_s=1_500,
    accelerated_rehearsal_terminal_classifications=(
        (
            "modeled_phase_transaction",
            "cx322_d9_d6_72h_right_censored_incomplete",
        ),
        (
            "clean_phase_degradation",
            "cx322_d9_d6_72h_right_censored_incomplete",
        ),
        (
            "shared_fail_static_transport_obstruction",
            "cx322_d9_d6_72h_identity_or_evidence_fault",
        ),
        (
            "abort_delivery_failure",
            "cx322_d9_d6_72h_identity_or_evidence_fault",
        ),
    ),
    integrated_long_run=True,
    controller_inhibit_acquisition_continues=True,
    gnss_metadata_hold_nonterminal=True,
)


CX323_D9_D6_72H_PROGRAMME = ActiveHybridProgramme(
    key="cx323_d9_d6_72h",
    programme_id="OTIS_CX323_D9_D6_72H_ADAPTIVE_HYBRID_V1",
    profile_id="cx323_d9_d6_72h_adaptive_hybrid",
    runtime_run_identity="cx323_d9_d6_72h_adaptive_hybrid:1",
    status_programme_id="cx323_d9_d6_72h_adaptive_hybrid",
    operation="cx323_d9_d6_72h_adaptive_hybrid_live",
    live_stage="OTIS_CX323_D9_D6_72H_ADAPTIVE_HYBRID_LIVE",
    compatibility_floor="OTIS_CX323_D9_D6_72H_EVIDENCE_EPOCH_1",
    manifest_section="cx323_d9_d6_72h",
    policy_id="CX323_PHASE_PRIORITY_PERSISTENT_MAINTENANCE_V1",
    policy_path=REPO_ROOT
    / "profiles/discipline/cx323_phase_priority_persistent_maintenance_v1.json",
    natural_policy_id="CX323_PHASE_PRIORITY_PERSISTENT_MAINTENANCE_V1",
    natural_policy_path=REPO_ROOT
    / "profiles/discipline/cx323_phase_priority_persistent_maintenance_v1.json",
    setup_code=0xA84D,
    maximum_applications=144,
    maximum_physical_applications=144,
    maximum_deliberate_challenges=0,
    maximum_cumulative_movement_codes=3_024,
    maximum_step_codes=21,
    minimum_code=0xA800,
    maximum_code=0xAB00,
    minimum_applied_cadence_s=1_800,
    qualified_duration_s=259_200,
    absolute_wall_limit_s=280_800,
    minimum_natural_phase_material_applications=0,
    bundle_id="cx323_d9_d6_72h_adaptive_hybrid_bundle_v1",
    activation_id="cx323_d9_d6_72h_adaptive_hybrid_activation_v1",
    rehearsal_report_type="cx323_d9_d6_72h_live_topology_rehearsal_v1",
    run_bundle_path=Path("cx323_d9_d6_72h_exact_bundle_v1.json"),
    run_proposal_path=Path("cx323_d9_d6_72h_authority_proposal_v1.json"),
    run_activation_path=Path("cx323_d9_d6_72h_live_activation_v1.json"),
    physical_seal_path=Path(
        "reports/cx323_d9_d6_72h_physical_seal_v1.json"
    ),
    terminal_decisions=frozenset(
        {
            "cx323_d9_d6_72h_qualified_hybrid_complete",
            "cx323_d9_d6_72h_hybrid_authority_not_sustained",
            "cx323_d9_d6_72h_right_censored_incomplete",
            "cx323_d9_d6_72h_D14_D8_authority_or_capture_fault",
            "cx323_d9_d6_72h_D9_configuration_or_readback_fault",
            "cx323_d9_d6_72h_controller_or_transaction_fault",
            "cx323_d9_d6_72h_maintenance_evidence_fault",
            "cx323_d9_d6_72h_identity_or_evidence_fault",
            "cx323_d9_d6_72h_operator_abort",
            "cx323_d9_d6_72h_pre_setup_no_write_abort",
        }
    ),
    healthy_preliminary_decisions=frozenset(
        {
            "pending_offline_scientific_analysis",
            "controller_authority_inhibited_acquisition_continues",
            "gnss_metadata_hold",
            "gnss_metadata_hold_requalified",
        }
    ),
    hybrid_states=_COMMON_STATES
    | {"GNSS_METADATA_HOLD", "CONTROLLER_AUTHORITY_INHIBITED"},
    armable_hybrid_states=frozenset(
        {
            "FREQUENCY_ACQUIRE",
            "PHASE_QUALIFY",
            "HYBRID_TRACKING",
            "PHASE_DEGRADED_FREQUENCY_ONLY",
        }
    ),
    response_checkpoint_observational=True,
    sustained_status_contract=True,
    prospectively_changed_authority_envelope=True,
    forwarded_output_integration=True,
    fresh_serial_auto_detect=True,
    natural_policy_programme_id=(
        "OTIS_CX323_D9_D6_72H_ADAPTIVE_HYBRID_V1"
    ),
    engineering_maximum_applications=144,
    engineering_maximum_physical_applications=144,
    engineering_maximum_cumulative_movement_codes=3_024,
    engineering_absolute_wall_limit_s=280_800,
    engineering_contract_path=REPO_ROOT
    / "docs/60_EXPERIMENTS/"
    "OTIS_CX323_SUSTAINED_HYBRID_SUCCESSOR_STUDY/"
    "cx323_d9_d6_72h_adaptive_hybrid_contract_v1.json",
    firmware_campaign_macro=(
        "OTIS_CX317_ACTIVE_CAMPAIGN_CX323_D9_D6_72H_ADAPTIVE_HYBRID"
    ),
    firmware_hybrid_maximum_automatic_applications=144,
    firmware_hybrid_maximum_cumulative_movement_codes=3_024,
    correction_response_reserve_s=1_500,
    accelerated_rehearsal_terminal_classifications=(
        (
            "modeled_phase_transaction",
            "cx323_d9_d6_72h_right_censored_incomplete",
        ),
        (
            "clean_phase_degradation",
            "cx323_d9_d6_72h_right_censored_incomplete",
        ),
        (
            "controller_inhibit_acquisition_continues",
            "cx323_d9_d6_72h_hybrid_authority_not_sustained",
        ),
        (
            "shared_fail_static_transport_obstruction",
            "cx323_d9_d6_72h_identity_or_evidence_fault",
        ),
        (
            "abort_delivery_failure",
            "cx323_d9_d6_72h_identity_or_evidence_fault",
        ),
    ),
    integrated_long_run=True,
    persistent_maintenance_policy=True,
    maintenance_record_type="AHM",
    maintenance_record_contract="active_hybrid_maintenance_v1",
    controller_inhibit_acquisition_continues=True,
    gnss_metadata_hold_nonterminal=True,
    qualified_endpoint_reason_override=(
        "cx323_d9_d6_72h_qualified_hybrid_complete"
    ),
)


SUSTAINED_HYBRID_PROGRAMME = ActiveHybridProgramme(
    key="sustained_hybrid",
    programme_id="OTIS_SUSTAINED_HYBRID_REGULATION_V1",
    profile_id="otis_sustained_hybrid_regulation_v1",
    runtime_run_identity="otis_sustained_hybrid_regulation_v1:1",
    status_programme_id="otis_sustained_hybrid_regulation_v1",
    operation="otis_sustained_hybrid_regulation_live",
    live_stage="OTIS_SUSTAINED_HYBRID_REGULATION_LIVE",
    compatibility_floor="OTIS_SUSTAINED_HYBRID_EVIDENCE_EPOCH_1",
    manifest_section="sustained_hybrid",
    policy_id="OTIS_SUSTAINED_HYBRID_REGULATION_V1",
    policy_path=REPO_ROOT
    / "profiles/discipline/otis_sustained_hybrid_regulation_v1.json",
    natural_policy_id="OTIS_SUSTAINED_HYBRID_REGULATION_V1",
    natural_policy_path=REPO_ROOT
    / "profiles/discipline/otis_sustained_hybrid_regulation_v1.json",
    setup_code=0xA83C,
    maximum_applications=12,
    maximum_physical_applications=13,
    maximum_deliberate_challenges=1,
    maximum_cumulative_movement_codes=84,
    maximum_step_codes=21,
    minimum_code=0xA800,
    maximum_code=0xAB00,
    minimum_applied_cadence_s=1800,
    qualified_duration_s=86_400,
    absolute_wall_limit_s=108_000,
    minimum_natural_phase_material_applications=2,
    bundle_id="otis_sustained_hybrid_24h_qualified_30h_wall_bundle_v1",
    activation_id="otis_sustained_hybrid_24h_live_activation_v1",
    rehearsal_report_type="otis_sustained_hybrid_live_topology_rehearsal_v1",
    run_bundle_path=Path("otis_sustained_hybrid_exact_bundle_v1.json"),
    run_proposal_path=Path("otis_sustained_hybrid_authority_proposal_v1.json"),
    run_activation_path=Path("otis_sustained_hybrid_live_activation_v1.json"),
    physical_seal_path=Path("reports/otis_sustained_hybrid_physical_seal_v1.json"),
    terminal_decisions=frozenset(
        {
            "sustained_hybrid_regulation_demonstrated_natural_reversal",
            "sustained_hybrid_regulation_demonstrated_challenge_reversal",
            "reversal_not_observed_within_authorized_window",
            "deliberate_reversal_recovery_not_demonstrated",
            "phase_or_frequency_regulation_not_sustained",
            "hybrid_policy_chatter_or_path_exhaustion",
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
    sustained_regulation=True,
    sustained_status_contract=True,
)


PROGRAMMES = {
    CX320_PROGRAMME.key: CX320_PROGRAMME,
    CX321_PROGRAMME.key: CX321_PROGRAMME,
    CX322_PROGRAMME.key: CX322_PROGRAMME,
    CX322_D9_D6_INTEGRATION_PROGRAMME.key: CX322_D9_D6_INTEGRATION_PROGRAMME,
    CX322_D9_D6_72H_PROGRAMME.key: CX322_D9_D6_72H_PROGRAMME,
    CX323_D9_D6_72H_PROGRAMME.key: CX323_D9_D6_72H_PROGRAMME,
    SUSTAINED_HYBRID_PROGRAMME.key: SUSTAINED_HYBRID_PROGRAMME,
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
