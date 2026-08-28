"""Create and validate the exact non-authorizing CX320 programme bundle."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .active_hybrid_policy import load_policy
from .active_hybrid_programme_contract import (
    ActiveHybridProgramme,
    CX320_PROGRAMME,
    PROGRAMMES,
    get_active_hybrid_programme,
    progressive_checkpoint_contract,
    programme_from_mapping,
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
            "OTIS_CX317_ACTIVE_CAMPAIGN_CX321_ACTIVE_HYBRID"
            if programme.identification_required
            else "OTIS_CX317_ACTIVE_CAMPAIGN_SUSTAINED_HYBRID_REGULATION"
            if programme.sustained_regulation
            else "OTIS_CX317_ACTIVE_CAMPAIGN_CX322_DIRECT_HYBRID"
            if programme.response_checkpoint_observational
            else "OTIS_CX317_ACTIVE_CAMPAIGN_CX320_ACTIVE_HYBRID"
        ),
        "OTIS_CX317_ACTIVE_START_CODE": "0xA83Cu",
        "OTIS_CX317_ACTIVE_CORRECTION_LIMIT": f"{programme.maximum_physical_applications}u",
        "OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES": "84u",
        "OTIS_CX317_MINIMUM_APPLIED_CADENCE_S": "1800u",
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


def create_bundle(
    *,
    build_manifest_path: Path,
    replay_path: Path,
    programme: ActiveHybridProgramme = CX320_PROGRAMME,
) -> dict[str, Any]:
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
        "policy": {
            **_binding(programme.natural_policy_path),
            "policy_id": policy.policy_id,
            "policy_sha256": policy.policy_sha256,
        },
        "firmware": firmware,
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
            "physical_applied_code_before_setup": "unknown",
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
        "prospective_metrics": policy_document["prospective_metrics"],
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
            "setup": "ACTIVE SETUP <authorization> <generation> <nonce> <expiry> <session> 0xA83C 1 <configuration_sha256>",
            "arm": "ACTIVE ARM <authorization_sequence> <nonce> <absolute_expiry_s>",
            "evidence_acknowledgement": "ACTIVE EVIDENCE <request_sequence> <phase_1_to_4>",
            "priority_abort_only": "ACTIVE ABORT",
            "normal_command_max_age_s": 2.0,
            "normal_write_timeout_s": 1.0,
            "command_ack_timeout_s": 3.0,
            "priority_abort_delivery_required_before_capture_close": True,
        },
        "stop_conditions": [
            "qualified_duration_complete",
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
    if bundle.get("prospective_metrics") != policy_document.get(
        "prospective_metrics"
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
    parser.add_argument(
        "--programme", choices=tuple(PROGRAMMES), default="cx320"
    )
    args = parser.parse_args(argv)
    programme = get_active_hybrid_programme(args.programme)
    if args.validate is not None:
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
