"""Single operating descriptor for the OTIS adaptive hybrid regulator.

The descriptor contains the finite run envelope and exact identities shared by
bundle creation, capture, supervision, replay, analysis, and sealing.  It is
deliberately a single value: changing duration or authority requires a new run
manifest, not another product branch.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping


PROGRAMME_ID = "OTIS_ADAPTIVE_HYBRID_REGULATION_V1"
PROFILE_ID = "adaptive_hybrid_regulation"
RUNTIME_RUN_IDENTITY = "adaptive_hybrid_regulation:1"


@dataclass(frozen=True)
class AdaptiveHybridProgramme:
    programme_id: str = PROGRAMME_ID
    profile_id: str = PROFILE_ID
    runtime_run_identity: str = RUNTIME_RUN_IDENTITY
    operation: str = "adaptive_hybrid_regulation_live"
    live_stage: str = "OTIS_ADAPTIVE_HYBRID_REGULATION_LIVE"
    evidence_epoch: str = "OTIS_ADAPTIVE_HYBRID_EVIDENCE_EPOCH_1"
    manifest_section: str = "adaptive_hybrid"
    policy_id: str = PROGRAMME_ID
    setup_code: int = 0xA84D
    maximum_applications: int = 144
    maximum_physical_applications: int = 144
    maximum_cumulative_movement_codes: int = 3_024
    maximum_step_codes: int = 21
    minimum_code: int = 0xA800
    maximum_code: int = 0xAB00
    minimum_applied_cadence_s: int = 1_800
    qualified_duration_s: int = 259_200
    absolute_wall_limit_s: int = 280_800
    minimum_natural_phase_material_applications: int = 0
    bundle_id: str = "adaptive_hybrid_regulation_bundle_v1"
    activation_id: str = "adaptive_hybrid_regulation_activation_v1"
    run_bundle_path: Path = Path("adaptive_hybrid_exact_bundle_v1.json")
    run_proposal_path: Path = Path("adaptive_hybrid_authority_proposal_v1.json")
    run_activation_path: Path = Path("adaptive_hybrid_live_activation_v1.json")
    physical_seal_path: Path = Path(
        "reports/adaptive_hybrid_physical_seal_v1.json"
    )
    correction_response_reserve_s: int = 1_500
    qualified_d14_aperture_count: int = 259_200
    correction_response_reserve_d14_apertures: int = 1_511
    maintenance_record_type: str = "AHM"
    maintenance_record_contract: str = "active_hybrid_maintenance_v1"
    qualification_deadline_s: int = 5_400
    response_checkpoint_observational: bool = True
    sustained_regulation: bool = True
    forwarded_output_integration: bool = True
    integrated_long_run: bool = True
    persistent_maintenance_policy: bool = True
    controller_inhibit_acquisition_continues: bool = True

    @property
    def key(self) -> str:
        return self.profile_id

    @property
    def campaign_name(self) -> str:
        return self.profile_id

    @property
    def capture_duration_s(self) -> int:
        return self.absolute_wall_limit_s + 180

    @property
    def supervisor_duration_s(self) -> int:
        return self.absolute_wall_limit_s + 120

    @property
    def qualified_endpoint_reason(self) -> str:
        return "adaptive_hybrid_qualified_complete"

    @property
    def authorized_maximum_applications(self) -> int:
        return self.maximum_applications

    @property
    def authorized_maximum_physical_applications(self) -> int:
        return self.maximum_physical_applications

    @property
    def authorized_maximum_cumulative_movement_codes(self) -> int:
        return self.maximum_cumulative_movement_codes

    @property
    def authorized_absolute_wall_limit_s(self) -> int:
        return self.absolute_wall_limit_s

    @property
    def healthy_preliminary_decisions(self) -> frozenset[str]:
        return frozenset(
            {
                "pending_offline_scientific_analysis",
                "controller_authority_inhibited_acquisition_continues",
                "gnss_metadata_hold",
                "gnss_metadata_hold_requalified",
            }
        )

    @property
    def terminal_decisions(self) -> frozenset[str]:
        return frozenset(
            {
                "adaptive_hybrid_qualified_complete",
                "adaptive_hybrid_authority_not_sustained",
                "adaptive_hybrid_right_censored_incomplete",
                "adaptive_hybrid_D14_D8_authority_or_capture_fault",
                "adaptive_hybrid_D9_configuration_or_readback_fault",
                "adaptive_hybrid_controller_or_transaction_fault",
                "adaptive_hybrid_maintenance_evidence_fault",
                "adaptive_hybrid_identity_or_evidence_fault",
                "adaptive_hybrid_operator_abort",
                "adaptive_hybrid_pre_setup_no_write_abort",
            }
        )

    @property
    def hybrid_states(self) -> frozenset[str]:
        return frozenset(
            {
                "SETUP_PENDING",
                "FREQUENCY_ACQUIRE",
                "PHASE_QUALIFY",
                "FIRST_PHASE_TRANSACTION",
                "HYBRID_TRACKING",
                "PHASE_DEGRADED_FREQUENCY_ONLY",
                "GNSS_METADATA_HOLD",
                "CONTROLLER_AUTHORITY_INHIBITED",
                "FAIL_STATIC",
            }
        )

    @property
    def armable_hybrid_states(self) -> frozenset[str]:
        return frozenset(
            {
                "FREQUENCY_ACQUIRE",
                "PHASE_QUALIFY",
                "HYBRID_TRACKING",
                "PHASE_DEGRADED_FREQUENCY_ONLY",
            }
        )


ADAPTIVE_HYBRID_PROGRAMME = AdaptiveHybridProgramme()

ADAPTIVE_HYBRID_STRUCTURAL_PREFLIGHT_COVERAGE = (
    "deterministic_controller_transaction",
    "GNSS_hold_causal_requalification_model",
    "D10_optional_event_control_projection",
)


def programme_from_mapping(value: Mapping[str, Any]) -> AdaptiveHybridProgramme:
    expected = {
        "programme_id": PROGRAMME_ID,
        "image_identity": PROFILE_ID,
        "run_identity": RUNTIME_RUN_IDENTITY,
    }
    observed = {
        key: value[key]
        for key in expected
        if key in value and value[key] is not None
    }
    if not observed:
        raise ValueError("artifact does not identify the adaptive-hybrid programme")
    mismatches = {
        key: (actual, expected[key])
        for key, actual in observed.items()
        if actual != expected[key]
    }
    if mismatches:
        raise ValueError(
            "artifact identifies a non-current adaptive-hybrid programme: "
            + ", ".join(
                f"{key}={actual!r}, expected {wanted!r}"
                for key, (actual, wanted) in sorted(mismatches.items())
            )
        )
    return ADAPTIVE_HYBRID_PROGRAMME


def integrated_setup_provenance_contract(
    programme: AdaptiveHybridProgramme = ADAPTIVE_HYBRID_PROGRAMME,
) -> dict[str, Any]:
    return {
        "physical_applied_code_before_setup": "unknown_unreadable_after_power_cycle",
        "firmware_dac_epoch_before_setup": (
            "zero_is_new_firmware_session_not_physical_DAC_history"
        ),
        "pre_setup_query": "DAC?_required_expected_to_report_unavailable",
        "authorized_setup_code": programme.setup_code,
        "authorized_setup_code_hex": f"0x{programme.setup_code:04X}",
        "setup_operation": "prospectively_frozen_authorized_stimulus_not_restoration",
        "first_confirmed_state_boundary": (
            "exact_setup_acceptance_application_DAC_epoch_and_first_dependent_consumer"
        ),
        "prior_or_nominal_state_inferred": False,
        "automatic_or_nominal_restoration": False,
    }


def progressive_checkpoint_contract(
    programme: AdaptiveHybridProgramme = ADAPTIVE_HYBRID_PROGRAMME,
) -> dict[str, Any]:
    return {
        "first_phase_material_applications_before_checkpoint": 1,
        "first_response_acknowledgement_requires_durable_AHY_and_ACT": True,
        "first_response_acknowledgement_requires_exact_host_replay": True,
        "descriptive_minimum_phase_material_applications": (
            programme.minimum_natural_phase_material_applications
        ),
        "phase_material_application_count_is_acquisition_pass_gate": False,
        "later_authority_requires_exact_response_observation_and_tight_reacquisition": True,
    }
