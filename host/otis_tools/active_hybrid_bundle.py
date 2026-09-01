"""Create and validate the exact non-authorizing CX320 programme bundle."""

from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .active_hybrid_policy import (
    CX323Observation,
    CX323PhasePriorityController,
    load_cx323_policy,
    load_policy,
)
from .active_hybrid_programme_contract import (
    ActiveHybridProgramme,
    CX320_PROGRAMME,
    PROGRAMMES,
    get_active_hybrid_programme,
    integrated_setup_provenance_contract,
    progressive_checkpoint_contract,
    programme_from_mapping,
)
from .gnss_operational_baud_policy import (
    GNSS_OPERATIONAL_BAUD_POLICY,
    GNSS_OPERATIONAL_REQUIRED_DEFINES,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_ID = "cx320_active_hybrid_exact_bundle_v1"
BUNDLE_ID = "cx320_active_hybrid_12h_qualified_16h_wall_bundle_v1"
PROFILE_ID = "cx320_active_hybrid"
PROGRAMME_ID = "CX320_BOUNDED_ACTIVE_HYBRID_PHASE_FREQUENCY_V1"
RUNTIME_RUN_IDENTITY = "cx320_active_hybrid:3200001"
EXPECTED_BOARD_SERIAL = "503533748A919118"
FRESH_SERIAL_AUTO_DETECT = (
    "capture_device_--auto-detect_exactly_one_/dev/cu.usbmodem*"
)
CX323_POLICY_ID = "CX323_PHASE_PRIORITY_PERSISTENT_MAINTENANCE_V1"
CX323_POLICY_RELATIVE_PATH = Path(
    "profiles/discipline/cx323_phase_priority_persistent_maintenance_v2.json"
)
CX323_POLICY_SHA256 = (
    "24ec5210b897b3ea9dd64aa5946c69e02e277c09922f5a5208f3476d6eaba926"
)
CX323_V2_CONTRACT_RELATIVE_PATH = Path(
    "docs/60_EXPERIMENTS/OTIS_CX323_SUSTAINED_HYBRID_SUCCESSOR_STUDY/"
    "study_contract_v2.json"
)
CX323_V2_CONTRACT_FILE_SHA256 = (
    "fc46b30e2bd323cdcbfdefa84fc7a35943584007120f3e1b9b96bbe98ba379af"
)
CX323_V2_CONTRACT_SEMANTIC_SHA256 = (
    "20b729dce477349704ce09e7cacf14047525450d50230c8f114f75959289d707"
)
CX323_V3_CONTRACT_RELATIVE_PATH = Path(
    "docs/60_EXPERIMENTS/OTIS_CX323_SUSTAINED_HYBRID_SUCCESSOR_STUDY/"
    "study_contract_v3.json"
)
CX323_V3_CONTRACT_FILE_SHA256 = (
    "a9915b61f295eaa743d8803ee609dd2a3f5b3136fff41d4dc6766929e6f06949"
)
CX323_V3_CONTRACT_SEMANTIC_SHA256 = (
    "32a7f47330404e1cf7ea724517643deff078e74d3e1aa50127c378bced5f4d53"
)
CX323_AHM_CONTRACT_RELATIVE_PATH = Path(
    "docs/50_SOFTWARE/CX323_ACTIVE_HYBRID_MAINTENANCE_EVIDENCE_CONTRACT.md"
)
CX323_AHM_CONTRACT_SHA256 = (
    "08826ada2caaca2dda624fcd2e67415978b9a21ccc3c947a9461918a5583389d"
)
CX323_ENGINEERING_CONTRACT_ID = (
    "OTIS_CX323_D9_D6_72H_ADAPTIVE_HYBRID_ENGINEERING_CONTRACT_V2"
)
CX323_REPLAY_ID = "cx323_progressive_tagged_debt_replay_v1"
CX323_REPLAY_CANDIDATE_ID = (
    "cx323_phase_priority_persistent_cap_tagged_debt_v1"
)
CX323_EXACT_IDENTITIES = {
    "programme_id": "OTIS_CX323_D9_D6_72H_ADAPTIVE_HYBRID_V1",
    "profile_id": "cx323_d9_d6_72h_adaptive_hybrid",
    "operation": "cx323_d9_d6_72h_adaptive_hybrid_live",
    "runtime_run_identity": "cx323_d9_d6_72h_adaptive_hybrid:1",
    "live_stage": "OTIS_CX323_D9_D6_72H_ADAPTIVE_HYBRID_LIVE",
    "compatibility_floor": "OTIS_CX323_D9_D6_72H_EVIDENCE_EPOCH_1",
    "bundle_id": "cx323_d9_d6_72h_adaptive_hybrid_bundle_v1",
    "activation_id": "cx323_d9_d6_72h_adaptive_hybrid_activation_v1",
}
CX323_EXACT_TERMINALS = {
    "qualified_complete": "cx323_d9_d6_72h_qualified_hybrid_complete",
    "authority_not_sustained": (
        "cx323_d9_d6_72h_hybrid_authority_not_sustained"
    ),
    "right_censored_incomplete": "cx323_d9_d6_72h_right_censored_incomplete",
    "authoritative_capture_fault": (
        "cx323_d9_d6_72h_D14_D8_authority_or_capture_fault"
    ),
    "d9_digital_fault": (
        "cx323_d9_d6_72h_D9_configuration_or_readback_fault"
    ),
    "controller_or_transaction_fault": (
        "cx323_d9_d6_72h_controller_or_transaction_fault"
    ),
    "maintenance_evidence_fault": (
        "cx323_d9_d6_72h_maintenance_evidence_fault"
    ),
    "identity_or_evidence_fault": (
        "cx323_d9_d6_72h_identity_or_evidence_fault"
    ),
    "operator_abort": "cx323_d9_d6_72h_operator_abort",
    "pre_setup_no_write_abort": "cx323_d9_d6_72h_pre_setup_no_write_abort",
}
REQUIRED_FALSE_AUTHORITY = (
    "effective",
    "firmware_flash",
    "reset",
    "serial_access",
    "command_fifo",
    "setup_stimulus",
    "dac_write",
    "control_arm",
    "physical_rehearsal",
    "live_acquisition",
)
TOOL_PATHS = {
    "bundle": Path(__file__),
    "programme_contract": Path(__file__).with_name(
        "active_hybrid_programme_contract.py"
    ),
    "controller_reference": Path(__file__).with_name("active_hybrid_policy.py"),
    "predecessor_audit": Path(__file__).with_name("active_hybrid_evidence_audit.py"),
    "frozen_evidence_replay": Path(__file__).with_name("active_hybrid_replay.py"),
    "sustained_continuation_synthesis": Path(__file__).with_name(
        "sustained_hybrid_synthesis.py"
    ),
    "host_supervisor_contract": Path(__file__).with_name("active_hybrid_supervisor.py"),
    "response_replay_guard": Path(__file__).with_name("active_hybrid_evidence_guard.py"),
    "plant_sign_replay_guard": Path(__file__).with_name(
        "cx321_plant_sign_evidence_guard.py"
    ),
    "authority_proposal_validator": Path(__file__).with_name("active_hybrid_proposal.py"),
    "structural_preflight": Path(__file__).with_name("active_hybrid_preflight.py"),
    "operational_rehearsal": Path(__file__).with_name("active_hybrid_rehearsal.py"),
    "analyzer": Path(__file__).with_name("active_hybrid_analyze.py"),
    "finalizer_and_sealer": Path(__file__).with_name("active_hybrid_finalize.py"),
    "capture": Path(__file__).with_name("capture_device.py"),
    "capture_splitter": Path(__file__).with_name("capture_serial.py"),
    "run_loader": Path(__file__).with_name("run_loader.py"),
    "run_paths": Path(__file__).with_name("run_paths.py"),
    "serial_commands": Path(__file__).with_name("serial_commands.py"),
    "active_transaction_supervisor": Path(__file__).with_name("active_transactions.py"),
    "active_transport_supervisor": Path(__file__).with_name("active_control_supervisor.py"),
    "active_status_snapshot_contract": Path(__file__).with_name("active_status_contract.py"),
    "active_status_live_state": Path(__file__).with_name(
        "active_status_live_state.py"
    ),
    "priority_abort": Path(__file__).with_name("abort_transport.py"),
    "logical_rotation": Path(__file__).with_name("capture_segment_rotation.py"),
    "contract_validator": Path(__file__).with_name("contracts.py"),
    "time_domain_contract": Path(__file__).with_name("time_domains.py"),
    "evidence_snapshot": Path(__file__).with_name("evidence.py"),
    "evidence_finalization_journal": Path(__file__).with_name(
        "evidence_finalization.py"
    ),
    "registration": Path(__file__).with_name("evidence_index.py"),
    "live_activation_and_manifest": Path(__file__).with_name("active_hybrid_activation.py"),
    "live_supervisor": Path(__file__).with_name("active_hybrid_live_supervisor.py"),
    "live_runner": Path(__file__).with_name("active_hybrid_run.py"),
    "live_analyzer_and_sealer": Path(__file__).with_name("active_hybrid_live_analyze.py"),
    "live_topology_rehearsal": Path(__file__).with_name("active_hybrid_live_rehearsal.py"),
    "live_monitor": Path(__file__).with_name("active_hybrid_monitor.py"),
}
SUSTAINED_REGULATION_ACCEPTANCE = {
    "characterization_is_not_an_entry_or_terminal_failure": True,
    "failure_requires_real_evidence_against_a_frozen_criterion": True,
    "maximum_absolute_raw_relative_phase_cycles": 36,
    "final_post_reversal_window_s": 21_600,
    "maximum_absolute_final_OLS_phase_slope_cycles_per_s": 1.0 / 3600.0,
    "persistent_wrong_direction_complete_same_epoch_windows": 2,
    "minimum_post_reversal_qualified_s": 21_600,
}
SUSTAINED_DECISION_IDENTITY_PROPAGATION = {
    "required_sequence": [
        "setup",
        "first_natural_application_and_response",
        "first_post_response_released_decision",
        "repeated_natural_application_and_response",
        "deliberate_challenge_application_and_response_if_required",
        "opposite_direction_recovery_application_and_response",
        "first_post_recovery_decision",
    ],
    "identity_fields": [
        "run_identity",
        "build_identity",
        "profile_identity",
        "policy_sha256",
        "session_id",
        "request_sequence",
        "decision_sequence",
        "application_sequence",
        "applied_code",
        "dac_epoch",
        "phase_epoch",
        "automatic_application_count",
        "correction_count",
        "deliberate_challenge_disposition",
    ],
    "producer_acknowledgement_alone_is_sufficient": False,
}


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: dict[str, Any]) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _binding(path: Path) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f"CX320 bound file is unavailable: {path}")
    return {
        "path": str(path),
        "sha256": _sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _cx323_successor_binding(
    programme: ActiveHybridProgramme,
) -> dict[str, Any]:
    """Bind the promoted policy and AHM contract without mutating either.

    The same value is required in the eventual engineering contract and exact
    bundle.  This makes a Campaign18 profile, policy hash, or evidence label a
    deterministic identity failure rather than a compatible predecessor.
    """

    if not programme.persistent_maintenance_policy:
        raise ValueError("persistent-maintenance successor capability is absent")
    observed_identities = {
        "programme_id": programme.programme_id,
        "profile_id": programme.profile_id,
        "operation": programme.operation,
        "runtime_run_identity": programme.runtime_run_identity,
        "live_stage": programme.live_stage,
        "compatibility_floor": programme.compatibility_floor,
        "bundle_id": programme.bundle_id,
        "activation_id": programme.activation_id,
    }
    if observed_identities != CX323_EXACT_IDENTITIES:
        raise ValueError("CX323 exact successor identities differ")
    policy_path = (REPO_ROOT / CX323_POLICY_RELATIVE_PATH).resolve()
    v2_path = (REPO_ROOT / CX323_V2_CONTRACT_RELATIVE_PATH).resolve()
    v3_path = (REPO_ROOT / CX323_V3_CONTRACT_RELATIVE_PATH).resolve()
    ahm_path = (REPO_ROOT / CX323_AHM_CONTRACT_RELATIVE_PATH).resolve()
    if (
        programme.policy_id != CX323_POLICY_ID
        or programme.natural_policy_id != CX323_POLICY_ID
        or programme.policy_path.resolve() != policy_path
        or programme.natural_policy_path.resolve() != policy_path
        or _sha256_file(policy_path) != CX323_POLICY_SHA256
    ):
        raise ValueError("CX323 selected policy identity differs")
    if (
        not v2_path.is_file()
        or _sha256_file(v2_path) != CX323_V2_CONTRACT_FILE_SHA256
        or _read_object(v2_path).get("contract_sha256")
        != CX323_V2_CONTRACT_SEMANTIC_SHA256
    ):
        raise ValueError("CX323 V2 selection contract identity differs")
    if (
        not v3_path.is_file()
        or _sha256_file(v3_path) != CX323_V3_CONTRACT_FILE_SHA256
        or _read_object(v3_path).get("contract_sha256")
        != CX323_V3_CONTRACT_SEMANTIC_SHA256
    ):
        raise ValueError("CX323 V3 native-boundary contract identity differs")
    if (
        programme.maintenance_record_type != "AHM"
        or programme.maintenance_record_contract
        != "active_hybrid_maintenance_v1"
        or not ahm_path.is_file()
        or _sha256_file(ahm_path) != CX323_AHM_CONTRACT_SHA256
    ):
        raise ValueError("CX323 normative AHM contract identity differs")
    return {
        "identities": dict(CX323_EXACT_IDENTITIES),
        "selected_policy": {
            "policy_id": CX323_POLICY_ID,
            "path": CX323_POLICY_RELATIVE_PATH.as_posix(),
            "sha256": CX323_POLICY_SHA256,
        },
        "selection_and_native_boundary": {
            "v2_selection": {
                "path": CX323_V2_CONTRACT_RELATIVE_PATH.as_posix(),
                "file_sha256": CX323_V2_CONTRACT_FILE_SHA256,
                "semantic_sha256": CX323_V2_CONTRACT_SEMANTIC_SHA256,
            },
            "v3_native_boundary_correction": {
                "path": CX323_V3_CONTRACT_RELATIVE_PATH.as_posix(),
                "file_sha256": CX323_V3_CONTRACT_FILE_SHA256,
                "semantic_sha256": CX323_V3_CONTRACT_SEMANTIC_SHA256,
            },
        },
        "maintenance_evidence": {
            "record_type": "AHM",
            "record_contract": "active_hybrid_maintenance_v1",
            "normative_contract_path": (
                CX323_AHM_CONTRACT_RELATIVE_PATH.as_posix()
            ),
            "normative_contract_sha256": CX323_AHM_CONTRACT_SHA256,
        },
    }


def _validate_cx323_bundle_binding(
    bundle: dict[str, Any], programme: ActiveHybridProgramme
) -> None:
    expected = _cx323_successor_binding(programme)
    policy = bundle.get("policy", {})
    if (
        bundle.get("profile_identity") != programme.profile_id
        or bundle.get("persistent_maintenance") != expected
        or policy.get("policy_id") != CX323_POLICY_ID
        or policy.get("sha256") != CX323_POLICY_SHA256
        or policy.get("policy_sha256") != CX323_POLICY_SHA256
    ):
        raise ValueError("CX323 exact bundle successor binding differs")


def _engineering_contract_binding(
    programme: ActiveHybridProgramme,
) -> dict[str, Any]:
    path = programme.engineering_contract_path
    if path is None:
        raise ValueError("integrated engineering contract is unavailable")
    if not path.is_file():
        if programme.persistent_maintenance_policy:
            raise ValueError(
                "CX323 exact engineering contract is pending at required path: "
                f"{path}"
            )
        raise ValueError("integrated engineering contract is unavailable")
    contract = _read_object(path)
    claimed = contract.get("contract_semantic_sha256")
    unsigned = {
        key: value
        for key, value in contract.items()
        if key != "contract_semantic_sha256"
    }
    if programme.persistent_maintenance_policy:
        firmware = contract.get("firmware", {})
        timing = contract.get("time", {})
        starting_dac = contract.get("starting_dac", {})
        envelope = contract.get("controller_envelope", {})
        serial = contract.get("serial", {})
        timing_truth = contract.get("timing_truth", {})
        d9 = contract.get("d9", {})
        d6 = contract.get("d6", {})
        gnss_hold = contract.get("gnss_metadata_hold", {})
        controller_inhibit = contract.get("controller_inhibit", {})
        claim_boundary = contract.get("claim_boundary", {})
        authority_lineage = contract.get("authority_lineage", {})
        physical_execution = contract.get("physical_execution", {})
        if (
            claimed != _canonical_sha256(unsigned)
            or contract.get("contract_id") != CX323_ENGINEERING_CONTRACT_ID
            or contract.get("persistent_maintenance")
            != _cx323_successor_binding(programme)
            or firmware.get("profile_id") != programme.profile_id
            or firmware.get("campaign_macro")
            != programme.firmware_campaign_macro
            or timing.get("qualified_duration_s")
            != programme.qualified_duration_s
            or timing.get("absolute_wall_limit_s")
            != programme.authorized_absolute_wall_limit_s
            or timing.get("source_counter_domain") != "rp2040_timer0"
            or timing.get("counter_domain") != "rp2040_timer0_extended"
            or timing.get("nominal_counter_hz") != 16_000_000
            or timing.get("coordinate_units_per_second") != 16_000_000
            or timing.get("source_counter_hz") != 1_000_000
            or timing.get("encoding_scale") != 16
            or timing.get("quantum_ticks") != 16
            or timing.get("quantum_ns") != 1_000
            or timing.get("projected_from") != "rp2040_timerawl_or_micros"
            or timing.get("qualified_endpoint_contract")
            != "qualified_D14_D8_aperture_count_v2"
            or timing.get("qualified_d14_aperture_count")
            != programme.qualified_d14_aperture_count
            or timing.get("qualification_deadline_s") != 5_400
            or starting_dac.get("pre_setup_physical_code")
            != "unknown_unreadable_after_power_cycle"
            or starting_dac.get("setup_code") != programme.setup_code
            or starting_dac.get("setup_code_hex")
            != f"0x{programme.setup_code:04X}"
            or starting_dac.get("setup_write_limit") != 1
            or starting_dac.get("required_first_known_boundary")
            != "setup_acceptance_application_DAC_epoch_and_first_dependent_consumer_exact"
            or starting_dac.get("retry_permitted") is not False
            or starting_dac.get("restoration_permitted") is not False
            or envelope.get("automatic_application_limit")
            != programme.authorized_maximum_applications
            or envelope.get("automatic_cumulative_movement_limit_codes")
            != programme.authorized_maximum_cumulative_movement_codes
            or envelope.get("automatic_step_limit_codes")
            != programme.maximum_step_codes
            or envelope.get("total_dac_write_limit_including_setup")
            != programme.authorized_maximum_physical_applications + 1
            or envelope.get("minimum_application_cadence_s")
            != programme.minimum_applied_cadence_s
            or envelope.get(
                "close_new_application_admission_before_endpoint_s"
            )
            != programme.correction_response_reserve_s
            or envelope.get(
                "close_new_application_admission_before_endpoint_d14_apertures"
            )
            != programme.correction_response_reserve_d14_apertures
            or envelope.get("authority_ceilings_are_nonbinding_not_targets")
            is not True
            or serial.get("baud") != 115200
            or serial.get("stored_device_path_permitted") is not False
            or serial.get("selection")
            != "capture_device_--auto-detect_fresh_for_every_capture_and_reenumeration"
            or timing_truth.get("reference_input") != "D14"
            or timing_truth.get("oscillator_and_control_input") != "D8"
            or timing_truth.get("D14_D8_continuity_required") is not True
            or d9.get("role")
            != "fixed_forwarded_output_with_digital_configuration_and_readback_gate_only"
            or d9.get("measurement_authority") is not False
            or d9.get("control_authority") is not False
            or d6.get("role")
            != "D9_through_1k_series_resistor_digital_diagnostic_sidecar"
            or d6.get("measurement_authority") is not False
            or d6.get("control_authority") is not False
            or gnss_hold.get("recoverable_anomaly_is_run_terminal") is not False
            or gnss_hold.get("force_or_inject_glitch") is not False
            or gnss_hold.get("new_corrections_during_hold")
            != "inhibited"
            or gnss_hold.get("last_confirmed_dac_code") != "preserved"
            or gnss_hold.get("D14_D8_capture_and_qualification")
            != "continues"
            or gnss_hold.get("resumption")
            != "fresh_same_receiver_metadata_then_two_complete_causally_later_maintenance_windows"
            or controller_inhibit.get("acquisition_continues") is not True
            or controller_inhibit.get("new_control_authority") != "inhibited"
            or controller_inhibit.get("host_abort") is not False
            or controller_inhibit.get("endpoint_terminal")
            != CX323_EXACT_TERMINALS["authority_not_sustained"]
            or contract.get("terminals") != CX323_EXACT_TERMINALS
            or set(CX323_EXACT_TERMINALS.values())
            != set(programme.terminal_decisions)
            or claim_boundary.get("waveform_evidence_status")
            != "unresolved_oscilloscope_deferred"
            or claim_boundary.get("waveform_claim_permitted") is not False
            or claim_boundary.get("prompt02_promotion_permitted") is not False
            or authority_lineage.get("standing_operator_authority_received")
            is not True
            or authority_lineage.get(
                "effective_only_after_all_promotion_gates_and_exact_activation_binding"
            )
            is not True
            or physical_execution.get("authorized_by_this_contract_alone")
            is not False
            or physical_execution.get("exact_bundle_activation_required")
            is not True
        ):
            raise ValueError("CX323 exact engineering contract semantics differ")
        return {
            **_binding(path),
            "contract_id": CX323_ENGINEERING_CONTRACT_ID,
            "contract_semantic_sha256": claimed,
            "persistent_maintenance": _cx323_successor_binding(programme),
        }
    if contract.get("contract_id") == (
        "OTIS_CX322_D9_D6_72H_INTEGRATED_ENGINEERING_CONTRACT_V1"
    ):
        from .cx322_d9_d6_72h_engineering import load_contract

        checked = load_contract(path)
        firmware = checked["firmware"]
        timing = checked["time"]
        envelope = checked["controller_envelope"]
        serial = checked["serial"]
        if (
            claimed != _canonical_sha256(unsigned)
            or firmware.get("profile_id") != programme.profile_id
            or timing.get("qualified_duration_s")
            != programme.qualified_duration_s
            or timing.get("absolute_wall_limit_s")
            != programme.authorized_absolute_wall_limit_s
            or timing.get("counter_domain") != "rp2040_timer0_extended"
            or envelope.get("automatic_application_limit")
            != programme.authorized_maximum_applications
            or envelope.get("automatic_cumulative_movement_limit_codes")
            != programme.authorized_maximum_cumulative_movement_codes
            or envelope.get("automatic_step_limit_codes")
            != programme.maximum_step_codes
            or envelope.get("total_dac_write_limit_including_setup")
            != programme.authorized_maximum_physical_applications + 1
            or envelope.get("minimum_application_cadence_s")
            != programme.minimum_applied_cadence_s
            or envelope.get(
                "close_new_application_admission_before_endpoint_s"
            )
            != programme.correction_response_reserve_s
            or envelope.get("authority_ceilings_are_nonbinding_not_targets")
            is not True
            or serial.get("baud") != 115200
            or serial.get("stored_device_path_permitted") is not False
        ):
            raise ValueError("72h integrated engineering contract semantics differ")
        return {
            **_binding(path),
            "contract_semantic_sha256": claimed,
        }
    envelope = contract.get("initial_bench_envelope", {})
    if (
        claimed != _canonical_sha256(unsigned)
        or contract.get("contract_id")
        != "OTIS_CX322_D9_D6_INTEGRATION_ENGINEERING_CONTRACT_V1"
        or contract.get("firmware_profile", {}).get("profile_id")
        != programme.profile_id
        or envelope.get("unarmed_concurrency_observation_seconds")
        != programme.engineering_unarmed_observation_s
        or envelope.get("maximum_automatic_applications")
        != programme.authorized_maximum_applications
        or envelope.get("maximum_cumulative_movement_codes")
        != programme.authorized_maximum_cumulative_movement_codes
        or envelope.get("maximum_step_codes") != programme.maximum_step_codes
        or envelope.get("absolute_wall_limit_seconds")
        != programme.authorized_absolute_wall_limit_s
        or envelope.get("starting_code_policy")
        != "query_if_observable_else_establish_first_known_state_by_exact_authorized_setup_never_infer_or_restore"
        or envelope.get("starting_state_provenance")
        != integrated_setup_provenance_contract(programme)
    ):
        raise ValueError("integrated engineering contract semantics differ")
    return {
        **_binding(path),
        "contract_semantic_sha256": claimed,
    }


def _validate_build(
    build_manifest_path: Path,
    programme: ActiveHybridProgramme = CX320_PROGRAMME,
) -> dict[str, Any]:
    manifest = _read_object(build_manifest_path)
    provenance = manifest.get("provenance", {})
    configuration = provenance.get("configuration", {})
    source = provenance.get("source", {})
    target = provenance.get("target", {})
    toolchain = provenance.get("toolchain", {})
    if configuration.get("profile_id") != programme.profile_id:
        raise ValueError(
            f"firmware build is not the exact {programme.key.upper()} profile"
        )
    defines = configuration.get("defines", {})
    expected_defines = {
        "OTIS_ENABLE_CX320_ACTIVE_HYBRID": "1",
        "OTIS_ENABLE_CX317_BOUNDED_ACTIVE": "1",
        "OTIS_CX317_ACTIVE_CAMPAIGN": (
            programme.firmware_campaign_macro
            or (
                "OTIS_CX317_ACTIVE_CAMPAIGN_CX321_ACTIVE_HYBRID"
                if programme.identification_required
                else "OTIS_CX317_ACTIVE_CAMPAIGN_SUSTAINED_HYBRID_REGULATION"
                if programme.sustained_regulation
                else "OTIS_CX317_ACTIVE_CAMPAIGN_CX322_DIRECT_HYBRID"
                if programme.response_checkpoint_observational
                else "OTIS_CX317_ACTIVE_CAMPAIGN_CX320_ACTIVE_HYBRID"
            )
        ),
        "OTIS_CX317_ACTIVE_START_CODE": f"0x{programme.setup_code:04X}u",
        "OTIS_CX317_ACTIVE_CORRECTION_LIMIT": (
            f"{programme.authorized_maximum_physical_applications}u"
        ),
        "OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES": (
            f"{programme.authorized_maximum_cumulative_movement_codes}u"
        ),
        "OTIS_CX317_MINIMUM_APPLIED_CADENCE_S": (
            f"{programme.minimum_applied_cadence_s}u"
        ),
        "OTIS_DAC_MIN_CODE": "0xA800u",
        "OTIS_DAC_MAX_CODE": "0xAB00u",
        "OTIS_SELECTED_HYBRID_EXTERNAL_DAC_EPOCH_RESEED": "1",
    }
    if programme.identification_required:
        expected_defines["OTIS_ENABLE_CX321_ACTIVE_HYBRID"] = "1"
    if programme.response_checkpoint_observational:
        expected_defines["OTIS_ENABLE_CX322_DIRECT_HYBRID"] = "1"
    if programme.forwarded_output_integration:
        expected_defines.update(
            {
                "OTIS_ENABLE_D9_D6_READINESS_PROFILE": "0",
                "OTIS_ENABLE_FORWARDED_D9_OUTPUT": "1",
                "OTIS_ENABLE_FORWARDED_D6_MONITOR": "1",
                **GNSS_OPERATIONAL_REQUIRED_DEFINES,
            }
        )
    if programme.sustained_regulation:
        expected_defines.update(
            {
                "OTIS_ENABLE_SUSTAINED_HYBRID_REGULATION": "1",
                "OTIS_ACTIVE_HYBRID_MAX_AUTOMATIC_APPLICATIONS": "12u",
                "OTIS_ACTIVE_HYBRID_ENABLE_REVERSAL_CHALLENGE": "1",
            }
        )
    if programme.firmware_hybrid_maximum_automatic_applications is not None:
        expected_defines["OTIS_ACTIVE_HYBRID_MAX_AUTOMATIC_APPLICATIONS"] = (
            f"{programme.firmware_hybrid_maximum_automatic_applications}u"
        )
    if programme.firmware_hybrid_maximum_cumulative_movement_codes is not None:
        expected_defines[
            "OTIS_ACTIVE_HYBRID_MAX_CUMULATIVE_MOVEMENT_CODES"
        ] = f"{programme.firmware_hybrid_maximum_cumulative_movement_codes}u"
    if any(defines.get(name) != value for name, value in expected_defines.items()):
        raise ValueError(
            f"firmware build {programme.key.upper()} compile-time envelope differs"
        )
    configuration_sha256 = configuration.get("sha256")
    source_sha256 = source.get("sha256")
    if not all(
        isinstance(value, str) and len(value) == 64
        for value in (configuration_sha256, source_sha256)
    ):
        raise ValueError("firmware build lacks exact source/configuration identity")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError("firmware build artifact list is unavailable")
    uf2 = [item for item in artifacts if item.get("name", "").endswith(".uf2")]
    if len(uf2) != 1:
        raise ValueError("firmware build must bind exactly one UF2")
    uf2_path = build_manifest_path.parent / uf2[0]["name"]
    if not uf2_path.is_file() or _sha256_file(uf2_path) != uf2[0].get("sha256"):
        raise ValueError("firmware UF2 identity differs from the build manifest")
    if target.get("fqbn") != "rp2040:rp2040:arduino_nano_connect:freq=133":
        raise ValueError("firmware target differs")
    if not toolchain.get("compiler_identity") or not toolchain.get("installed_sha256"):
        raise ValueError("firmware toolchain identity is incomplete")
    if source.get("state") != "clean":
        raise ValueError(
            f"exact {programme.key.upper()} live firmware build requires clean source state"
        )
    return {
        "profile_id": programme.profile_id,
        "build_manifest": _binding(build_manifest_path),
        "source_revision": source.get("git_commit"),
        "source_state": source.get("state"),
        "source_sha256": source_sha256,
        "configuration_sha256": configuration_sha256,
        "build_identity": f"{source_sha256}:{configuration_sha256}",
        "uf2": _binding(uf2_path),
        "fqbn": target["fqbn"],
        "toolchain": toolchain,
        "defines": defines,
    }


def _validate_replay(
    replay_path: Path,
    policy_sha256: str,
    programme: ActiveHybridProgramme = CX320_PROGRAMME,
) -> dict[str, Any]:
    if programme.persistent_maintenance_policy:
        return _validate_cx323_replay(replay_path, policy_sha256, programme)
    replay = _read_object(replay_path)
    claimed = replay.pop("report_sha256", None)
    observed = _canonical_sha256(replay)
    replay["report_sha256"] = claimed
    if claimed != observed:
        raise ValueError("CX320 replay semantic report identity differs")
    current_tool = Path(__file__).with_name(
        "sustained_hybrid_synthesis.py"
        if programme.sustained_regulation
        else "active_hybrid_replay.py"
    )
    if (
        replay.get("status") != "passed"
        or replay.get("selected_candidate_id") != "p21600_cap1_tight_active_v1"
        or replay.get("policy_sha256") != policy_sha256
        or replay.get("tool_sha256") != _sha256_file(current_tool)
        or not all(replay.get("selection_checks", {}).values())
        or (
            programme.sustained_regulation
            and replay.get("programme_id") != programme.programme_id
        )
    ):
        raise ValueError("CX320 replay selection or current tool binding differs")
    return {
        **_binding(replay_path),
        "report_sha256": claimed,
        "selected_candidate_id": replay["selected_candidate_id"],
        "selection_checks": replay["selection_checks"],
    }


def _cx323_progressive_replay_report(
    programme: ActiveHybridProgramme,
) -> dict[str, Any]:
    """Execute the frozen CX323 oracle through two complete transactions.

    This is intentionally independent of the historical CX320/CX322 replay.
    The second transaction is needed to prove that the residual produced by
    the first exact application remains tagged and participates in the next
    maintenance decision.
    """

    successor = _cx323_successor_binding(programme)
    engineering = _engineering_contract_binding(programme)
    policy = load_cx323_policy(programme.natural_policy_path)
    controller = CX323PhasePriorityController(policy)

    def observation(timestamp_s: int, opening: int, closing: int) -> CX323Observation:
        return CX323Observation(
            timestamp_s=timestamp_s,
            capture_session=1,
            source_first_sequence=opening,
            source_last_sequence=closing,
            dac_epoch=controller.dac_epoch,
            applied_code=controller.applied_code,
            accumulated_edge_error_counts=-1,
            tight_state="TIGHT_INSIDE",
            phase_epoch=1,
            relative_phase_cycles=-4,
        )

    first_hold = controller.decide(observation(0, 0, 600))
    first_request = controller.decide(observation(600, 600, 1200))
    controller.confirm_application(
        first_request,
        applied_code=first_request.requested_code,
        dac_epoch=2,
        first_consumer_exact=True,
    )
    first_debt = asdict(controller.debt)
    first_application_state = {
        "applied_code": controller.applied_code,
        "dac_epoch": controller.dac_epoch,
        "application_count": controller.application_count,
        "cumulative_movement_codes": controller.cumulative_movement_codes,
        "request_pending": controller.request_pending,
        "response_pending": controller.response_pending,
    }
    first_response_hold = controller.decide(observation(1200, 1200, 1800))
    controller.complete_response(fresh_exact=True)

    cadence_hold_one = controller.decide(observation(1200, 1200, 1800))
    cadence_hold_two = controller.decide(observation(1800, 1800, 2400))
    second_request = controller.decide(observation(2400, 2400, 3000))
    debt_entering_second_request = asdict(controller.debt)
    controller.confirm_application(
        second_request,
        applied_code=second_request.requested_code,
        dac_epoch=3,
        first_consumer_exact=True,
    )
    second_debt = asdict(controller.debt)
    controller.complete_response(fresh_exact=True)

    selection_checks = {
        "exact_successor_identity": successor["identities"]
        == CX323_EXACT_IDENTITIES,
        "exact_policy_identity": policy.policy_id == CX323_POLICY_ID
        and policy.policy_sha256 == CX323_POLICY_SHA256,
        "exact_engineering_contract": engineering.get("contract_id")
        == CX323_ENGINEERING_CONTRACT_ID,
        "first_persistent_window_holds": first_hold.reason
        == "persistence_first_interval_hold"
        and first_hold.requested_delta_codes == 0
        and first_hold.persistence_count == 1,
        "second_persistent_window_requests": first_request.reason
        == "maintenance_request_ready"
        and first_request.maintenance_request is True
        and first_request.requested_delta_codes == 5
        and first_request.persistence_count == 2,
        "first_application_reaches_exact_consumer": first_application_state
        == {
            "applied_code": 43090,
            "dac_epoch": 2,
            "application_count": 1,
            "cumulative_movement_codes": 5,
            "request_pending": False,
            "response_pending": True,
        },
        "response_blocks_before_completion": first_response_hold.reason
        == "response_pending_hold",
        "cadence_and_persistence_continue_after_response": (
            cadence_hold_one.reason == "cadence_hold"
            and cadence_hold_one.persistence_count == 1
            and cadence_hold_two.reason == "cadence_hold"
            and cadence_hold_two.persistence_count == 2
        ),
        "tagged_debt_enters_second_decision": (
            first_debt == debt_entering_second_request
            and sum(first_debt.values()) == 341_671_780_415
            and first_debt["fll_picocodes"] != 0
            and first_debt["pll_picocodes"] != 0
            and second_request.committed_debt_picocodes
            == sum(first_debt.values())
        ),
        "second_progressive_transaction_completes": (
            second_request.reason == "maintenance_request_ready"
            and second_request.maintenance_request is True
            and second_request.requested_delta_codes == 5
            and controller.applied_code == 43095
            and controller.dac_epoch == 3
            and controller.application_count == 2
            and controller.cumulative_movement_codes == 10
            and controller.request_pending is False
            and controller.response_pending is False
        ),
        "tagged_debt_remains_bounded_after_second_application": (
            sum(second_debt.values()) == 500_000_000_000
            and second_debt["fll_picocodes"] == 450_000_000_000
            and second_debt["pll_picocodes"] == 50_000_000_000
        ),
    }
    if not all(selection_checks.values()):
        failed = sorted(name for name, passed in selection_checks.items() if not passed)
        raise ValueError(
            "CX323 progressive replay oracle failed: " + ", ".join(failed)
        )

    oracle_path = Path(__file__).with_name("active_hybrid_policy.py")
    return {
        "schema_version": 1,
        "replay_id": CX323_REPLAY_ID,
        "status": "passed",
        "selected_candidate_id": CX323_REPLAY_CANDIDATE_ID,
        "programme_identity": dict(CX323_EXACT_IDENTITIES),
        "policy": successor["selected_policy"],
        "selection_and_native_boundary": successor[
            "selection_and_native_boundary"
        ],
        "maintenance_evidence": successor["maintenance_evidence"],
        "engineering_contract": {
            "contract_id": engineering["contract_id"],
            "contract_semantic_sha256": engineering[
                "contract_semantic_sha256"
            ],
            "file_sha256": engineering["sha256"],
        },
        "oracle": {
            "tool_id": "cx323_phase_priority_python_oracle_v1",
            "path": str(oracle_path.resolve()),
            "sha256": _sha256_file(oracle_path),
        },
        "lifecycle": {
            "first_persistence_hold": asdict(first_hold),
            "first_request": asdict(first_request),
            "first_application": {
                **first_application_state,
                "first_consumer_exact": True,
                "tagged_debt": first_debt,
            },
            "first_response_hold": asdict(first_response_hold),
            "post_response_cadence_holds": [
                asdict(cadence_hold_one),
                asdict(cadence_hold_two),
            ],
            "second_request": asdict(second_request),
            "second_application": {
                "applied_code": second_request.requested_code,
                "dac_epoch": 3,
                "first_consumer_exact": True,
                "tagged_debt": second_debt,
            },
            "second_response_complete": True,
        },
        "selection_checks": selection_checks,
    }


def create_cx323_progressive_replay(
    *,
    output_path: Path,
    programme: ActiveHybridProgramme,
) -> dict[str, Any]:
    """Write the deterministic CX323 progressive replay consumed by a bundle."""

    if not programme.persistent_maintenance_policy:
        raise ValueError(
            "CX323 progressive replay generation requires persistent maintenance"
        )
    unsigned = _cx323_progressive_replay_report(programme)
    report = {
        **unsigned,
        "report_sha256": _canonical_sha256(unsigned),
    }
    payload = (
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    ).encode("utf-8")
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output_path.open("xb") as stream:
            written = stream.write(payload)
            if written != len(payload):
                raise OSError(
                    f"short immutable CX323 replay write: {output_path}"
                )
    except FileExistsError as error:
        raise ValueError(
            f"refusing to overwrite CX323 progressive replay: {output_path}"
        ) from error
    return report


def _validate_cx323_replay(
    replay_path: Path,
    policy_sha256: str,
    programme: ActiveHybridProgramme,
) -> dict[str, Any]:
    if policy_sha256 != CX323_POLICY_SHA256:
        raise ValueError("CX323 replay policy identity differs")
    replay = _read_object(replay_path)
    claimed = replay.pop("report_sha256", None)
    observed = _canonical_sha256(replay)
    if claimed != observed:
        raise ValueError("CX323 replay semantic report identity differs")
    expected = _cx323_progressive_replay_report(programme)
    if replay != expected:
        raise ValueError(
            "CX323 replay lifecycle, identity, or contract binding differs"
        )
    return {
        **_binding(replay_path),
        "report_sha256": claimed,
        "replay_id": CX323_REPLAY_ID,
        "selected_candidate_id": CX323_REPLAY_CANDIDATE_ID,
        "selection_checks": replay["selection_checks"],
        "oracle": replay["oracle"],
        "engineering_contract": replay["engineering_contract"],
    }


def create_bundle(
    *,
    build_manifest_path: Path,
    replay_path: Path,
    programme: ActiveHybridProgramme = CX320_PROGRAMME,
) -> dict[str, Any]:
    engineering_contract = (
        _engineering_contract_binding(programme)
        if programme.forwarded_output_integration
        else None
    )
    policy = load_policy(programme.natural_policy_path)
    policy_document = _read_object(programme.natural_policy_path)
    firmware = _validate_build(build_manifest_path.resolve(), programme)
    replay = _validate_replay(
        replay_path.resolve(), policy.policy_sha256, programme
    )
    authority = {name: False for name in REQUIRED_FALSE_AUTHORITY}
    authority.update(
        {
            "offline_preparation": True,
            "separate_exact_bundle_operator_decision_required": True,
            "consumed_by_first_physical_terminal": True,
        }
    )
    bundle: dict[str, Any] = {
        "schema_version": 1,
        "bundle_id": programme.bundle_id,
        "programme_id": programme.programme_id,
        "tool": TOOL_ID,
        "created_utc": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "status": "frozen_non_effective_physical_proposal_input",
        "run_identity": programme.runtime_run_identity,
        **(
            {"profile_identity": programme.profile_id}
            if programme.persistent_maintenance_policy
            else {}
        ),
        "policy": {
            **_binding(programme.natural_policy_path),
            "policy_id": policy.policy_id,
            "policy_sha256": policy.policy_sha256,
        },
        "firmware": firmware,
        **(
            {"gnss_uart_policy": GNSS_OPERATIONAL_BAUD_POLICY}
            if programme.forwarded_output_integration
            else {}
        ),
        "offline_replay": replay,
        "host_tools": {name: _binding(path) for name, path in TOOL_PATHS.items()},
        "topology": {
            "sole_reference_input": "D14",
            "sole_oscillator_count_input": "D8",
            "independent_event_input_not_authority": "D10",
            "gnss_role": "same_receiver_D14_qualification_metadata_only",
            "D9_GPOUT0": (
                "D8_GPIO20_GPIN0_to_D9_GPIO21_GPOUT0_integer_divide_one"
                if programme.forwarded_output_integration
                else "deferred_unchanged"
            ),
            **(
                {
                    "D6_forwarded_monitor": (
                        "D9_through_1k_series_resistor_to_D6_GPIO18_"
                        "diagnostic_zero_authority"
                    )
                }
                if programme.forwarded_output_integration
                else {}
            ),
            "serial_owner_count": 1,
            "serial_owner": "capture_device",
            "normal_and_priority_abort_fifos_distinct": True,
            "expected_board_serial": (
                None
                if programme.fresh_serial_auto_detect
                else EXPECTED_BOARD_SERIAL
            ),
            **(
                {"serial_device_selection": FRESH_SERIAL_AUTO_DETECT}
                if programme.fresh_serial_auto_detect
                else {}
            ),
        },
        "setup": {
            "exact_code": programme.setup_code,
            "exact_code_hex": f"0x{programme.setup_code:04X}",
            "physical_applied_code_before_setup": (
                integrated_setup_provenance_contract(programme)[
                    "physical_applied_code_before_setup"
                ]
                if programme.forwarded_output_integration
                else "unknown"
            ),
            "one_setup_application": True,
            "same_code_reapplication_opens_new_epoch": True,
            "exact_acknowledgement_required": True,
            "consumer_epoch_propagation_required": [
                "frequency_estimator",
                "phase_estimator",
                "controller",
                "preview_replay",
                "recorder",
                "response_classifier",
            ],
        },
        "finite_limits": {
            "qualified_duration_s": programme.qualified_duration_s,
            **(
                {
                    "qualified_endpoint_contract": "qualified_D14_D8_aperture_count_v2",
                    "qualified_d14_aperture_count": programme.qualified_d14_aperture_count,
                    "correction_response_reserve_d14_apertures": programme.correction_response_reserve_d14_apertures,
                }
                if programme.qualified_d14_aperture_count is not None
                else {}
            ),
            "qualified_origin": "first_complete_fresh_authoritative_600s_estimate_after_exact_setup_support_and_common_health_qualification",
            "absolute_wall_clock_limit_s": (
                programme.authorized_absolute_wall_limit_s
            ),
            "wall_clock_origin": "sole_capture_owner_records_exact_run_identity_before_setup_submission",
            "maximum_total_automatic_applications": (
                programme.authorized_maximum_applications
            ),
            "maximum_total_physical_control_applications": (
                programme.authorized_maximum_physical_applications
            ),
            "maximum_deliberate_challenges": programme.maximum_deliberate_challenges,
            "maximum_combined_step_codes": programme.maximum_step_codes,
            "maximum_cumulative_absolute_movement_codes": (
                programme.authorized_maximum_cumulative_movement_codes
            ),
            "minimum_applied_cadence_s": programme.minimum_applied_cadence_s,
            "minimum_code": programme.minimum_code,
            "maximum_code": programme.maximum_code,
            "maximum_outstanding_requests": 1,
            "automatic_retry": False,
            "automatic_restoration": False,
            "live_extension": False,
        },
        **(
            {}
            if programme.persistent_maintenance_policy
            else {"prospective_metrics": policy_document["prospective_metrics"]}
        ),
        "progressive_authority": {
            "states": (
                [
                    "FREQUENCY_ACQUIRE",
                    "PHASE_QUALIFY",
                    "FIRST_PHASE_TRANSACTION",
                    "HYBRID_TRACKING",
                    "PHASE_DEGRADED_FREQUENCY_ONLY",
                    "FAIL_STATIC",
                ]
                if programme is CX320_PROGRAMME
                else sorted(programme.hybrid_states - {"SETUP_PENDING"})
            ),
            **progressive_checkpoint_contract(programme),
            "response_class_sign_and_magnitude_are_admission_gates": (
                not programme.response_checkpoint_observational
            ),
        },
        "command_envelope": {
            "identity_queries_before_setup": ["CONFIG?", "DUALCORE?", "DAC?", "ACTIVE?"],
            "setup": (
                "ACTIVE SETUP <authorization> <generation> <nonce> "
                "<expiry> <session> "
                f"0x{programme.setup_code:04X} 1 <configuration_sha256>"
            ),
            "arm": "ACTIVE ARM <authorization_sequence> <nonce> <absolute_expiry_s>",
            "evidence_acknowledgement": "ACTIVE EVIDENCE <request_sequence> <phase_1_to_4>",
            "priority_abort_only": "ACTIVE ABORT",
            "normal_command_max_age_s": 2.0,
            "normal_write_timeout_s": 1.0,
            "command_ack_timeout_s": 3.0,
            "priority_abort_delivery_required_before_capture_close": True,
        },
        "stop_conditions": [
            (
                "qualified_D14_D8_aperture_count_complete"
                if programme.qualified_d14_aperture_count is not None
                else "qualified_duration_complete"
            ),
            "absolute_wall_clock_limit",
            (
                "phase_degradation_recorded_frequency_only_continues"
                if programme.response_checkpoint_observational
                else "phase_only_degradation_active_hybrid_nonpass"
            ),
            "shared_D14_or_D8_qualification_loss",
            "ambiguous_DAC_epoch_or_identity",
            "capture_or_evidence_discontinuity",
            "transaction_or_acknowledgement_fault",
            (
                "missing_late_or_invalid_response_evidence"
                if programme.response_checkpoint_observational
                else "wrong_absent_late_or_right_censored_response"
            ),
            "range_cadence_count_or_cumulative_budget_breach",
            "serial_owner_loss_or_transport_obstruction",
            "priority_abort_delivery_failure",
            "operator_abort",
        ],
        "terminal_requirements": {
            "one_confirmed_static_code": True,
            "outstanding_request": False,
            "outstanding_response": False,
            "latent_authority": False,
            "every_terminal_analyzed_sealed_and_registered": True,
        },
        "authority": authority,
    }
    if programme.persistent_maintenance_policy:
        bundle["persistent_maintenance"] = _cx323_successor_binding(programme)
    if programme.forwarded_output_integration:
        if engineering_contract is None:
            raise ValueError("integrated engineering contract binding is unavailable")
        bundle["engineering_contract"] = engineering_contract
        bundle["setup"]["provenance"] = integrated_setup_provenance_contract(
            programme
        )
    if programme.sustained_regulation:
        bundle["reversal_challenge"] = policy_document["reversal_challenge"]
        bundle["sustained_regulation_acceptance"] = (
            SUSTAINED_REGULATION_ACCEPTANCE
        )
        bundle["decision_identity_propagation"] = (
            SUSTAINED_DECISION_IDENTITY_PROPAGATION
        )
        bundle["stop_conditions"].extend(
            [
                "persistent_wrong_direction_across_two_complete_same_phase_epoch_response_windows",
                "required_reversal_or_deliberate_challenge_recovery_not_demonstrated",
                "absolute_raw_relative_phase_escape",
                "final_phase_slope_or_frequency_preservation_criterion_not_sustained",
                "hybrid_policy_chatter_or_path_exhaustion",
            ]
        )
    if programme.identification_required:
        programme_policy = _read_object(programme.policy_path)
        policy_bindings = programme_policy.get("bindings")
        if not isinstance(policy_bindings, dict):
            raise ValueError("CX321 programme policy bindings are unavailable")
        exact_bindings: dict[str, dict[str, Any]] = {}
        for name, declared in policy_bindings.items():
            if not isinstance(declared, dict):
                raise ValueError(f"CX321 policy binding {name} is malformed")
            source = REPO_ROOT / str(declared.get("path", ""))
            if (
                not source.is_file()
                or _sha256_file(source) != declared.get("sha256")
            ):
                raise ValueError(f"CX321 policy binding differs: {name}")
            exact_bindings[name] = _binding(source)
        estimator_document = _read_object(
            REPO_ROOT
            / str(policy_bindings["identification_estimator"]["path"])
        )
        runtime_config = estimator_document.get("runtime_config")
        if not isinstance(runtime_config, dict):
            raise ValueError("CX321 strict estimator config binding is unavailable")
        runtime_config_path = REPO_ROOT / str(runtime_config.get("path", ""))
        if (
            not runtime_config_path.is_file()
            or _sha256_file(runtime_config_path)
            != runtime_config.get("file_sha256")
        ):
            raise ValueError("CX321 strict estimator config file differs")
        from .pps_cumulative_span_estimator import SpanEstimatorConfig

        strict_config = SpanEstimatorConfig.from_mapping(
            _read_object(runtime_config_path)
        )
        if strict_config.config_hash != runtime_config.get(
            "canonical_config_hash"
        ):
            raise ValueError("CX321 canonical estimator config identity differs")
        bundle["profile_identity"] = programme.profile_id
        bundle["programme_policy"] = {
            **_binding(programme.policy_path),
            "policy_id": programme.policy_id,
        }
        bundle["identification"] = {
            "bindings": exact_bindings,
            "estimator_runtime_config": {
                **_binding(runtime_config_path),
                "canonical_config_hash": strict_config.config_hash,
            },
            "step_codes": 21,
            "response_floor_counts": 3,
            "response_ceiling_counts": 14,
            "settling_exclusion_s": 900,
            "span_intervals": 1500,
            "host_replay_ack_deadline_s": 30,
        }
        bundle["command_envelope"]["evidence_acknowledgement"] = (
            "ACTIVE EVIDENCE <request_sequence> <phase_1_to_3>"
        )
        bundle["command_envelope"]["plant_sign_response_acknowledgement"] = (
            "ACTIVE EVIDENCE <request_sequence> 4 "
            "<response_psq_record_sequence> <response_counts> "
            "<application_sequence> <dac_epoch> "
            "<response_source_last_sequence> <attestation_sha256>"
        )
        bundle["progressive_authority"][
            "plant_sign_identification_required"
        ] = True
    bundle["bundle_sha256"] = _canonical_sha256(bundle)
    return bundle


def validate_bundle(
    path: Path,
    programme: ActiveHybridProgramme | None = None,
) -> dict[str, Any]:
    path = path.resolve()
    bundle = _read_object(path)
    claimed = bundle.pop("bundle_sha256", None)
    observed = _canonical_sha256(bundle)
    bundle["bundle_sha256"] = claimed
    programme = programme or programme_from_mapping(bundle)
    if claimed != observed:
        raise ValueError("CX320 bundle semantic identity differs")
    if (
        bundle.get("bundle_id") != programme.bundle_id
        or bundle.get("programme_id") != programme.programme_id
        or bundle.get("status") != "frozen_non_effective_physical_proposal_input"
        or bundle.get("run_identity") != programme.runtime_run_identity
        or (
            programme.persistent_maintenance_policy
            and bundle.get("profile_identity") != programme.profile_id
        )
        or (
            programme.identification_required
            and bundle.get("profile_identity") != programme.profile_id
        )
        or bundle.get("topology", {}).get("expected_board_serial")
        != (
            None
            if programme.fresh_serial_auto_detect
            else EXPECTED_BOARD_SERIAL
        )
        or (
            programme.fresh_serial_auto_detect
            and bundle.get("topology", {}).get("serial_device_selection")
            != FRESH_SERIAL_AUTO_DETECT
        )
        or bundle.get("command_envelope", {}).get("arm")
        != "ACTIVE ARM <authorization_sequence> <nonce> <absolute_expiry_s>"
    ):
        raise ValueError("unexpected CX320 bundle identity")
    if any(bundle.get("authority", {}).get(name) is not False for name in REQUIRED_FALSE_AUTHORITY):
        raise ValueError("CX320 bundle contains effective physical authority")
    if programme.persistent_maintenance_policy:
        _validate_cx323_bundle_binding(bundle, programme)
    if programme.forwarded_output_integration and (
        bundle.get("engineering_contract")
        != _engineering_contract_binding(programme)
        or bundle.get("gnss_uart_policy") != GNSS_OPERATIONAL_BAUD_POLICY
        or bundle.get("setup", {}).get("provenance")
        != integrated_setup_provenance_contract(programme)
        or bundle.get("setup", {}).get("physical_applied_code_before_setup")
        != integrated_setup_provenance_contract(programme)[
            "physical_applied_code_before_setup"
        ]
    ):
        raise ValueError("integrated setup provenance or contract binding differs")
    if set(bundle.get("host_tools", {})) != set(TOOL_PATHS):
        raise ValueError("CX320 bundle does not bind the complete current host path")
    for section, bindings in (("host_tools", bundle.get("host_tools", {})),):
        if not isinstance(bindings, dict):
            raise ValueError(f"CX320 {section} bindings are unavailable")
        for name, binding in bindings.items():
            bound = Path(str(binding.get("path", "")))
            if not bound.is_file() or _sha256_file(bound) != binding.get("sha256"):
                raise ValueError(f"CX320 {section} binding differs: {name}")
    if programme.identification_required:
        if bundle.get("command_envelope", {}).get(
            "evidence_acknowledgement"
        ) != "ACTIVE EVIDENCE <request_sequence> <phase_1_to_3>" or bundle.get(
            "command_envelope", {}
        ).get("plant_sign_response_acknowledgement") != (
            "ACTIVE EVIDENCE <request_sequence> 4 "
            "<response_psq_record_sequence> <response_counts> "
            "<application_sequence> <dac_epoch> "
            "<response_source_last_sequence> <attestation_sha256>"
        ):
            raise ValueError("CX321 command envelope differs")
        programme_policy_binding = bundle.get("programme_policy", {})
        programme_policy_path = Path(
            str(programme_policy_binding.get("path", ""))
        )
        if (
            not programme_policy_path.is_file()
            or _sha256_file(programme_policy_path)
            != programme_policy_binding.get("sha256")
            or programme_policy_binding.get("policy_id") != programme.policy_id
        ):
            raise ValueError("active-hybrid programme policy binding differs")
        programme_policy_document = _read_object(programme_policy_path)
        declared_bindings = programme_policy_document.get("bindings", {})
        identification = bundle.get("identification", {})
        exact_bindings = identification.get("bindings", {})
        if (
            not isinstance(declared_bindings, dict)
            or not isinstance(exact_bindings, dict)
            or set(exact_bindings) != set(declared_bindings)
        ):
            raise ValueError("CX321 exact identification bindings differ")
        for name, declared in declared_bindings.items():
            bound = exact_bindings[name]
            source = REPO_ROOT / str(declared.get("path", ""))
            if (
                not source.is_file()
                or declared.get("sha256") != _sha256_file(source)
                or bound != _binding(source)
            ):
                raise ValueError(f"CX321 identification binding differs: {name}")
        estimator = _read_object(
            REPO_ROOT
            / str(declared_bindings["identification_estimator"]["path"])
        )
        runtime = estimator.get("runtime_config", {})
        runtime_path = REPO_ROOT / str(runtime.get("path", ""))
        runtime_binding = identification.get("estimator_runtime_config", {})
        from .pps_cumulative_span_estimator import SpanEstimatorConfig

        runtime_config = SpanEstimatorConfig.from_mapping(
            _read_object(runtime_path)
        )
        if (
            runtime_binding
            != {
                **_binding(runtime_path),
                "canonical_config_hash": runtime_config.config_hash,
            }
            or runtime_config.config_hash
            != runtime.get("canonical_config_hash")
            or {
                "step_codes": identification.get("step_codes"),
                "response_floor_counts": identification.get(
                    "response_floor_counts"
                ),
                "response_ceiling_counts": identification.get(
                    "response_ceiling_counts"
                ),
                "settling_exclusion_s": identification.get(
                    "settling_exclusion_s"
                ),
                "span_intervals": identification.get("span_intervals"),
                "host_replay_ack_deadline_s": identification.get(
                    "host_replay_ack_deadline_s"
                ),
            }
            != {
                "step_codes": 21,
                "response_floor_counts": 3,
                "response_ceiling_counts": 14,
                "settling_exclusion_s": 900,
                "span_intervals": 1500,
                "host_replay_ack_deadline_s": 30,
            }
        ):
            raise ValueError("CX321 strict identification envelope differs")
    policy_binding = bundle["policy"]
    policy_path = Path(policy_binding["path"])
    if _sha256_file(policy_path) != policy_binding["sha256"]:
        raise ValueError("CX320 policy file binding differs")
    policy = load_policy(policy_path)
    if policy.policy_sha256 != policy_binding["policy_sha256"]:
        raise ValueError("CX320 semantic policy binding differs")
    policy_document = _read_object(policy_path)
    if (
        not programme.persistent_maintenance_policy
        and bundle.get("prospective_metrics")
        != policy_document["prospective_metrics"]
    ):
        raise ValueError("CX320 prospective scientific metrics differ from policy")
    if programme.sustained_regulation and (
        bundle.get("reversal_challenge")
        != policy_document.get("reversal_challenge")
        or bundle.get("sustained_regulation_acceptance")
        != SUSTAINED_REGULATION_ACCEPTANCE
        or bundle.get("decision_identity_propagation")
        != SUSTAINED_DECISION_IDENTITY_PROPAGATION
    ):
        raise ValueError("sustained-hybrid frozen decision contract differs")
    _validate_build(Path(bundle["firmware"]["build_manifest"]["path"]), programme)
    _validate_replay(
        Path(bundle["offline_replay"]["path"]),
        policy.policy_sha256,
        programme,
    )
    return bundle


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-manifest", type=Path)
    parser.add_argument("--replay", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--validate", type=Path)
    parser.add_argument("--generate-progressive-replay", action="store_true")
    parser.add_argument(
        "--programme", choices=tuple(PROGRAMMES), default="cx320"
    )
    args = parser.parse_args(argv)
    programme = get_active_hybrid_programme(args.programme)
    if args.generate_progressive_replay:
        if args.output is None:
            parser.error("--generate-progressive-replay requires --output")
        if any(
            value is not None
            for value in (args.validate, args.build_manifest, args.replay)
        ):
            parser.error(
                "--generate-progressive-replay cannot be combined with "
                "bundle creation or validation inputs"
            )
        try:
            result = create_cx323_progressive_replay(
                output_path=args.output,
                programme=programme,
            )
        except ValueError as error:
            parser.error(str(error))
    elif args.validate is not None:
        result = validate_bundle(args.validate, programme)
    else:
        if args.build_manifest is None or args.replay is None:
            parser.error("bundle creation requires --build-manifest and --replay")
        result = create_bundle(
            build_manifest_path=args.build_manifest,
            replay_path=args.replay,
            programme=programme,
        )
        if args.output is not None:
            if args.output.exists():
                parser.error(f"refusing to overwrite CX320 bundle: {args.output}")
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n",
                encoding="utf-8",
            )
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
