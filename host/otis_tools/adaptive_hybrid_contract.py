"""Single operating descriptor for the OTIS adaptive hybrid regulator.

The descriptor contains the finite run envelope and exact identities shared by
bundle creation, capture, supervision, replay, analysis, and sealing.  It is
deliberately a single value: changing duration or authority requires a new run
manifest, not another product branch.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
from pathlib import Path
from types import MappingProxyType
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
    maintenance_record_contract: str = "active_hybrid_maintenance_v2"
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

OPERATIONAL_REHEARSAL_SEAL_TYPE = (
    "adaptive_hybrid_operational_rehearsal_seal_v1"
)
OPERATIONAL_REHEARSAL_REQUIRED_BOUNDARIES = (
    "continuous_capture_and_exact_frozen_identity_consumption",
    "actual_capture_and_supervisor_process_topology",
    "setup_arm_and_evidence_ack_through_first_dependent_decision",
    "timeout_periodic_and_repeated_transaction_boundaries",
    "normal_command_transport_obstruction",
    "independent_priority_abort_submission_and_delivery_before_capture_close",
    "atomic_serial_owner_handoff_without_ownerless_interval",
    "clean_stop_shared_current_analyzer_consumers_snapshot_rehearsal_seal_and_successful_registration",
)


# Closed current bench-attempt envelopes live beside the sole programme
# descriptor.  They constrain individual bench entries; they do not add an
# alternate programme or grant authority by themselves.
SCHEMA_VERSION = 2
CONTRACT_ID = "adaptive_hybrid_bench_attempt_envelope_v2"
CAUSAL_STATE_SCHEMA_VERSION = 2
CAUSAL_STATE_CONTRACT_ID = "adaptive_hybrid_bench_attempt_causal_state_v2"

INHIBITED_ZERO_WRITE = "inhibited_zero_write"
CONTINGENT_72_HOUR_HYBRID_CONTROL = "contingent_72_hour_hybrid_control"
PURPOSES = frozenset(
    {INHIBITED_ZERO_WRITE, CONTINGENT_72_HOUR_HYBRID_CONTROL}
)

EXPECTED_BOARD_SERIAL = "503533748A919118"
EXPECTED_HARDWARE_ID = "503533748A919118"
EXPECTED_USB_VID = "0x2341"
EXPECTED_USB_PID = "0x005E"
EXPECTED_USB_PRODUCT = "Nano RP2040 Connect"
EXPECTED_BOARD_NAME = "Arduino Nano RP2040 Connect"
EXPECTED_BASE_FQBN = "rp2040:rp2040:arduino_nano_connect"
EXPECTED_COMPILE_FQBN = "rp2040:rp2040:arduino_nano_connect:freq=133"

PROGRESS_DOMAIN = "accepted_D14_D8_apertures"
ENDPOINT_CONTRACT = "qualified_D14_D8_aperture_count_v2"
AUTOMATIC_APPLICATION_ADMISSION_DEADLINE_APERTURES = (
    ADAPTIVE_HYBRID_PROGRAMME.qualified_d14_aperture_count
    - ADAPTIVE_HYBRID_PROGRAMME.correction_response_reserve_d14_apertures
)
CORRECTION_RESPONSE_RESERVE_APERTURES = 1_511
FIRST_DEPENDENT_DECISION_RESERVE_APERTURES = 600
ABSOLUTE_WALL_LIMIT_S = ADAPTIVE_HYBRID_PROGRAMME.absolute_wall_limit_s
INHIBITED_ZERO_WRITE_ABSOLUTE_WALL_LIMIT_S = 7_200
ARM_OPPORTUNITY_INTERVAL_S = 600
ARM_SUBMISSION_LIMIT = ABSOLUTE_WALL_LIMIT_S // ARM_OPPORTUNITY_INTERVAL_S
QUALIFIED_APERTURE_MILESTONES = (21_600, 86_400, 172_800, 259_200)
SETUP_CODE = ADAPTIVE_HYBRID_PROGRAMME.setup_code


@dataclass(frozen=True)
class _PurposeLimits:
    setup_application_limit: int
    automatic_application_limit: int
    required_completed_automatic_applications: int
    arm_submission_limit: int
    total_dac_value_write_limit: int
    maximum_outstanding_requests: int
    setup_code: int | None
    automatic_application_admission_deadline_apertures: int
    absolute_wall_limit_s: int
    authority_initially_closed: bool
    authority_closure_trigger: str
    success_terminal: str
    zero_natural_correction_outcome: str


_LIMITS = MappingProxyType(
    {
        INHIBITED_ZERO_WRITE: _PurposeLimits(
            setup_application_limit=0,
            automatic_application_limit=0,
            required_completed_automatic_applications=0,
            arm_submission_limit=0,
            total_dac_value_write_limit=0,
            maximum_outstanding_requests=0,
            setup_code=None,
            automatic_application_admission_deadline_apertures=0,
            absolute_wall_limit_s=INHIBITED_ZERO_WRITE_ABSOLUTE_WALL_LIMIT_S,
            authority_initially_closed=True,
            authority_closure_trigger="initial_contract_state",
            success_terminal="inhibited_zero_write_complete",
            zero_natural_correction_outcome="inhibited_by_contract",
        ),
        CONTINGENT_72_HOUR_HYBRID_CONTROL: _PurposeLimits(
            setup_application_limit=1,
            automatic_application_limit=(
                ADAPTIVE_HYBRID_PROGRAMME.authorized_maximum_physical_applications
            ),
            required_completed_automatic_applications=0,
            arm_submission_limit=ARM_SUBMISSION_LIMIT,
            total_dac_value_write_limit=(
                1
                + ADAPTIVE_HYBRID_PROGRAMME.authorized_maximum_physical_applications
            ),
            maximum_outstanding_requests=1,
            setup_code=SETUP_CODE,
            automatic_application_admission_deadline_apertures=(
                AUTOMATIC_APPLICATION_ADMISSION_DEADLINE_APERTURES
            ),
            absolute_wall_limit_s=ABSOLUTE_WALL_LIMIT_S,
            authority_initially_closed=False,
            authority_closure_trigger="automatic_application_limit_reached",
            success_terminal=(
                ADAPTIVE_HYBRID_PROGRAMME.qualified_endpoint_reason
            ),
            zero_natural_correction_outcome=(
                "zero_natural_corrections_valid_at_qualified_endpoint"
            ),
        ),
    }
)


def _canonical_bench_attempt_json(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError) as exc:
        raise ValueError("bench-attempt envelope is not canonical JSON") from exc


def canonical_bench_attempt_sha256(unsigned_envelope: Mapping[str, Any]) -> str:
    """Return the identity of an unsigned canonical envelope document."""

    return sha256(_canonical_bench_attempt_json(unsigned_envelope)).hexdigest()


@dataclass(frozen=True, slots=True)
class BenchAttemptEnvelope:
    """One of the two exact, current bench-attempt contracts."""

    purpose: str

    def __post_init__(self) -> None:
        if self.purpose not in PURPOSES:
            raise ValueError(f"unsupported bench-attempt purpose {self.purpose!r}")

    @property
    def limits(self) -> _PurposeLimits:
        return _LIMITS[self.purpose]

    def unsigned_document(self) -> dict[str, Any]:
        limits = self.limits
        return {
            "schema_version": SCHEMA_VERSION,
            "contract": CONTRACT_ID,
            "purpose": self.purpose,
            "device_identity": {
                "expected_board_serial": EXPECTED_BOARD_SERIAL,
                "expected_hardware_id": EXPECTED_HARDWARE_ID,
                "expected_usb_vid": EXPECTED_USB_VID,
                "expected_usb_pid": EXPECTED_USB_PID,
                "expected_usb_product": EXPECTED_USB_PRODUCT,
                "expected_board_name": EXPECTED_BOARD_NAME,
                "expected_base_fqbn": EXPECTED_BASE_FQBN,
                "expected_compile_fqbn": EXPECTED_COMPILE_FQBN,
            },
            "authority": {
                "setup_application_limit": limits.setup_application_limit,
                "automatic_application_limit": limits.automatic_application_limit,
                "required_completed_automatic_applications": (
                    limits.required_completed_automatic_applications
                ),
                "arm_submission_limit": limits.arm_submission_limit,
                "total_dac_value_write_limit": limits.total_dac_value_write_limit,
                "maximum_outstanding_requests": limits.maximum_outstanding_requests,
                "setup_code": limits.setup_code,
                "automatic_retry_permitted": False,
                "arm_retry_permitted": False,
                "arm_submission_scope": "distinct_natural_correction_opportunities",
                "restore_write_permitted": False,
                "attempt_extension_permitted": False,
                "forced_correction_permitted": False,
            },
            "timing": {
                "progress_domain": PROGRESS_DOMAIN,
                "endpoint_contract": ENDPOINT_CONTRACT,
                "automatic_application_admission_deadline_delta": (
                    limits.automatic_application_admission_deadline_apertures
                ),
                "correction_response_reserve_delta": (
                    CORRECTION_RESPONSE_RESERVE_APERTURES
                ),
                "first_dependent_decision_reserve_delta": (
                    FIRST_DEPENDENT_DECISION_RESERVE_APERTURES
                ),
                "absolute_wall_limit_s": limits.absolute_wall_limit_s,
                "wall_limit_role": "separate_hard_bound_not_decision_counter",
            },
            "causal_state": {
                "schema_version": CAUSAL_STATE_SCHEMA_VERSION,
                "contract": CAUSAL_STATE_CONTRACT_ID,
                "durable_ACT_application_count": {
                    "initial": 0,
                    "maximum": limits.automatic_application_limit,
                    "source": "durable_validated_ACT_application_records",
                },
                "firmware_correction_count": {
                    "initial": 0,
                    "maximum": limits.automatic_application_limit,
                    "source": (
                        "causally_complete_firmware_snapshot_for_same_request_sequence"
                    ),
                },
                "authority_closed": {
                    "initial": limits.authority_initially_closed,
                    "closure_trigger": limits.authority_closure_trigger,
                    "source": "durable_bench_attempt_causal_state",
                    "persistence_required": True,
                    "persistence_order": (
                        "durable_before_phase_3_evidence_acknowledgement"
                    ),
                    "reopening_permitted": False,
                    "new_ARM_permitted_when_closed": False,
                },
                "count_comparison_precondition": (
                    "ACT_and_firmware_snapshot_causally_complete_for_same_request_sequence"
                ),
                "count_mismatch_transition": "operator_review_hold",
            },
            "terminal_semantics": {
                "natural_correction_only": True,
                "success_terminal": limits.success_terminal,
                "zero_natural_correction_outcome": (
                    limits.zero_natural_correction_outcome
                ),
                "no_retry": True,
                "no_restore": True,
                "no_extension": True,
            },
            "monitoring_semantics": {
                "authoritative_source": (
                    "retained_supervisor_state_and_capture_evidence"
                ),
                "accepted_D14_D8_aperture_milestones": (
                    list(QUALIFIED_APERTURE_MILESTONES)
                    if self.purpose == CONTINGENT_72_HOUR_HYBRID_CONTROL
                    else []
                ),
                "first_application_milestone_nonterminal": (
                    self.purpose == CONTINGENT_72_HOUR_HYBRID_CONTROL
                ),
                "host_monitor_may_decide_terminal": False,
            },
            "host_discrepancy_semantics": {
                "transition": "operator_review_hold",
                "new_setup_authority": False,
                "new_ARM_authority": False,
                "automatic_abort_authority": False,
                "automatic_teardown_authority": False,
                "failed_campaign_authority": False,
                "retain_capture_and_serial_owner": True,
                "preserve_last_confirmed_code": True,
                "preserve_exact_pending_phase_identity": True,
            },
        }

    def as_dict(self) -> dict[str, Any]:
        unsigned = self.unsigned_document()
        return {
            **unsigned,
            "envelope_sha256": canonical_bench_attempt_sha256(unsigned),
        }


def envelope_for_purpose(purpose: str) -> BenchAttemptEnvelope:
    """Return the immutable contract object for an exact supported purpose."""

    return BenchAttemptEnvelope(purpose=purpose)


def validate_bench_attempt_envelope(
    value: Mapping[str, Any],
) -> BenchAttemptEnvelope:
    """Fail closed unless *value* is exactly one generated envelope."""

    if not isinstance(value, Mapping):
        raise ValueError("bench-attempt envelope must be a mapping")
    expected_top_level_keys = {
        "schema_version",
        "contract",
        "purpose",
        "device_identity",
        "authority",
        "timing",
        "causal_state",
        "terminal_semantics",
        "monitoring_semantics",
        "host_discrepancy_semantics",
        "envelope_sha256",
    }
    if set(value) != expected_top_level_keys:
        raise ValueError("bench-attempt envelope has unknown or missing fields")
    purpose = value.get("purpose")
    if not isinstance(purpose, str) or purpose not in PURPOSES:
        raise ValueError(f"unsupported bench-attempt purpose {purpose!r}")
    expected = envelope_for_purpose(purpose)
    expected_document = expected.as_dict()
    claimed_sha256 = value.get("envelope_sha256")
    if not isinstance(claimed_sha256, str):
        raise ValueError("bench-attempt envelope identity is malformed")
    unsigned = {
        key: item for key, item in value.items() if key != "envelope_sha256"
    }
    if claimed_sha256 != canonical_bench_attempt_sha256(unsigned):
        raise ValueError("bench-attempt envelope identity is not exact")
    if _canonical_bench_attempt_json(value) != _canonical_bench_attempt_json(
        expected_document
    ):
        raise ValueError("bench-attempt envelope is not the exact current contract")
    return expected


def operational_rehearsal_authorization_contract(
    *,
    bundle: dict[str, Any],
    proposal: dict[str, Any],
    programme: AdaptiveHybridProgramme = ADAPTIVE_HYBRID_PROGRAMME,
) -> dict[str, Any]:
    """Return the exact host-rehearsal activation-input contract."""

    firmware = bundle.get("firmware")
    policy = bundle.get("policy")
    authoritative_inputs = bundle.get("authoritative_inputs")
    host_tools = bundle.get("host_tools")
    if not all(
        isinstance(value, dict)
        for value in (firmware, policy, authoritative_inputs, host_tools)
    ):
        raise ValueError("rehearsal authorization inputs are incomplete")
    required_tools = {
        "capture_device",
        "acquisition_frontier",
        "raw_measurement_replay",
        "adaptive_hybrid_operational_rehearsal",
        "adaptive_hybrid_supervisor",
        "adaptive_hybrid_run",
        "adaptive_hybrid_analyze",
        "evidence",
        "evidence_finalization",
        "evidence_index",
    }
    if not required_tools.issubset(host_tools):
        raise ValueError("rehearsal authorization host-tool closure is incomplete")
    return {
        "schema_version": 1,
        "seal_type": OPERATIONAL_REHEARSAL_SEAL_TYPE,
        "report_kind": "operational_path_rehearsal",
        "status": "passed",
        "identity": {
            "programme_id": programme.programme_id,
            "run_identity": programme.runtime_run_identity,
            "image_identity": programme.profile_id,
            "bundle_sha256": bundle.get("bundle_sha256"),
            "proposal_sha256": proposal.get("proposal_sha256"),
            "source_revision": firmware.get("source_revision"),
            "build_identity": firmware.get("build_identity"),
            "uf2_sha256": (
                firmware.get("uf2", {}).get("sha256")
                if isinstance(firmware.get("uf2"), dict)
                else None
            ),
            "policy_sha256": policy.get("policy_sha256"),
            "authoritative_input_set_sha256": authoritative_inputs.get(
                "set_sha256"
            ),
        },
        "required_boundaries": list(OPERATIONAL_REHEARSAL_REQUIRED_BOUNDARIES),
        "required_evidence": {
            "immutable_complete_acquisition_snapshot": True,
            "shared_current_analyzer_consumers_exact": True,
            "successful_rehearsal_registration": True,
            "exact_tool_bindings": {
                name: host_tools[name] for name in sorted(required_tools)
            },
            "raw_evidence_and_frozen_criteria_unchanged_during_analysis": True,
        },
        "host_discrepancy_semantics": {
            "review_required_hold": True,
            "new_setup_or_arm": False,
            "automatic_abort_or_teardown": False,
            "failed_campaign_authority": False,
        },
        "claim_boundary": {
            "authorizes_activation_input_only": True,
            "is_not_physical_plant_qualification": True,
            "grants_no_retry_extension_or_restoration": True,
            "physical_actions_performed": 0,
        },
        "producer_requirement": (
            "current_bundle_bound_real_io_rehearsal_producer_and_independent_seal"
        ),
    }


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
