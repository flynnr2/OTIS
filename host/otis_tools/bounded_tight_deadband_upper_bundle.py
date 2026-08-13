"""Freeze and validate the matched CX319 G3 upper-side proposal bundle."""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any
import json

from .bounded_tight_deadband_bundle import (
    HOST_TOOL_PATHS,
    REPO_ROOT,
    _atomic_new,
    _binding,
    _firmware_build_provenance,
    _git_identity,
    _read,
    _sha256_file,
    _utc_now,
)
from .bounded_tight_deadband_leg import UPPER
from .bounded_tight_deadband_outcome_contract import (
    MAXIMUM_CODE,
    MAXIMUM_CORRECTIONS,
    MAXIMUM_CUMULATIVE_CODES,
    MAXIMUM_QUALIFIED_DURATION_S,
    MAXIMUM_STEP_CODES,
    MINIMUM_CADENCE_S,
    MINIMUM_CODE,
    QUALIFICATION_DEADLINE_S,
    canonical_sha256,
)
from .bounded_tight_deadband_prewrite_contract import (
    FRESH_HOST_ATTACH_MAXIMUM_UPTIME_S,
    RAW_PPS_QUALIFICATION_DEADLINE_S,
    TELEMETRY_BASELINE_STABLE_OBSERVATIONS,
)
from .no_write_qualification_bundle import POLICY_PATH, PROGRAMME_ID, _load_policy, validate_build
from .programme_status import OFFLINE_PREPARATION, load_programme_status, require_programme_operation_allowed


DEFAULT_G2_SEAL = REPO_ROOT / (
    "runs/cx319_stabilized_tight_deadband/q4/"
    "timer_rollover_offline_reanalysis_20260813T171500Z/"
    "cx319_g2_live_leg_superseding_seal_v1.json"
)


def validate_g2_pass(path: Path) -> dict[str, Any]:
    path = path.resolve()
    seal = _read(path, "passing G2 superseding seal")
    status = load_programme_status()["programmes"][PROGRAMME_ID]
    recorded = status.get("q4_g2_lower_physical_qualification_result", {})
    unsigned = {key: value for key, value in seal.items() if key != "seal_sha256"}
    if (
        recorded.get("status") != "passed"
        or seal.get("status") != "passed"
        or seal.get("gate") != "G2"
        or seal.get("leg") != "A"
        or seal.get("terminal", {}).get("result") != "healthy_stop"
        or seal.get("terminal", {}).get("reason")
        != "required_direction_and_two_estimate_tight_entry"
        or not isinstance(seal.get("checks"), dict)
        or not seal["checks"]
        or not all(seal["checks"].values())
        or seal.get("seal_sha256") != canonical_sha256(unsigned)
        or seal.get("seal_sha256") != recorded.get("superseding_seal_sha256")
    ):
        raise ValueError("G3 requires the exact recorded passing G2 superseding seal")
    return {
        "run_id": recorded["run_id"],
        "seal": _binding(path),
        "seal_sha256": seal["seal_sha256"],
        "acquisition_content_sha256": recorded["acquisition_content_sha256"],
        "registered_content_sha256": recorded[
            "superseding_registered_content_sha256"
        ],
        "terminal": seal["terminal"],
        "profile_id": recorded["profile_id"],
        "setup_code": recorded["setup_code"],
        "automatic_direction": recorded["automatic_direction"],
    }


def create_proposal(
    *,
    g2_seal_path: Path,
    build_manifest_path: Path,
    uf2_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    require_programme_operation_allowed(PROGRAMME_ID, OFFLINE_PREPARATION)
    commit, state = _git_identity()
    if state != "clean":
        raise ValueError("G3 proposal bundle requires a clean repository")
    g2_pass = validate_g2_pass(g2_seal_path)
    firmware = validate_build(
        leg=UPPER.leg,
        build_manifest_path=build_manifest_path,
        uf2_path=uf2_path,
        allow_clean_ancestor_source=True,
    )
    policy = _load_policy()
    policy_binding = {
        **policy,
        "path": str(POLICY_PATH.resolve()),
        "sha256": _sha256_file(POLICY_PATH),
    }
    host_tools = {name: _binding(path) for name, path in HOST_TOOL_PATHS.items()}
    unsigned: dict[str, Any] = {
        "schema_version": 1,
        "compatibility_floor": "CX319_EVIDENCE_EPOCH_1",
        "tool": UPPER.proposal_tool,
        "bundle_id": UPPER.proposal_bundle_id,
        "created_utc": _utc_now(),
        "source_revision": commit,
        "source_state": state,
        "programme_id": PROGRAMME_ID,
        "gate": UPPER.gate,
        "leg": UPPER.leg,
        "status": "proposed_not_authorized",
        "authority": {
            "effective": False,
            "physical_execution": False,
            "firmware_flash": False,
            "serial_open": False,
            "setup_stimulus": False,
            "control_arm": False,
            "automatic_correction": False,
            "dac_value_write": False,
            "phase_or_hybrid_actionable": False,
            "required_future_operation": UPPER.operation,
            "explicit_operator_transition_required": True,
        },
        "g2_pass": g2_pass,
        "firmware": firmware,
        "firmware_build_provenance": _firmware_build_provenance(firmware),
        "firmware_entry": {
            "mode": "flash_exact_upper_profile_once",
            "required_uf2_sha256": firmware["uf2"]["sha256"],
            "firmware_flash_allowed_in_effective_g3": True,
            "maximum_firmware_flashes": 1,
            "upload_failure": "stop_without_retry_and_request_operator_assistance",
        },
        "policy": policy_binding,
        "host_tools": host_tools,
        "expected_device": {
            "last_qualified_serial_path": "/dev/cu.usbmodem14601",
            "expected_board_serial": "503533748A919118",
            "baud": 115200,
            "single_continuously_draining_owner": True,
            "serial_path_may_reenumerate_but_board_identity_may_not": True,
        },
        "expected_entry_transcript": {
            "queries_before_setup": [
                "CONFIG?",
                "DAC?",
                "FC0?",
                "ACTIVE LEASE <nonzero_uint32>",
                "ACTIVE SNAPSHOT <post_attach_nonce>",
            ],
            "boot": {
                "fresh_host_attach_maximum_uptime_s": FRESH_HOST_ATTACH_MAXIMUM_UPTIME_S,
                "automatic_reboot_recovery": False,
                "caused_by_exact_upper_upload": True,
            },
            "build": {
                "profile_id": firmware["profile_id"],
                "source_sha256": firmware["source_sha256"],
                "configuration_sha256": firmware["configuration_sha256"],
                "uf2_sha256": firmware["uf2"]["sha256"],
            },
            "dac": {
                "physical_applied_code_before_setup": "unknown_after_flash",
                "planned_setup_code": UPPER.setup_code,
                "setup_opens_new_dac_epoch": True,
            },
            "timing": {
                "status_clock_domain": "rp2040_timer0",
                "measurement_reference": "gnss_raw_pps",
            },
            "gnss_pps": {
                "identity_epoch": 1,
                "identity_stable": True,
                "metadata_control_eligible": True,
                "raw_pps_control_eligible": True,
                "qualification_deadline_s": RAW_PPS_QUALIFICATION_DEADLINE_S,
            },
            "active_snapshot": {
                "complete_single_generation": True,
                "post_attach_nonce_exact": True,
                "session_nonzero": True,
                "state_before_setup": "DISARMED",
                "fail_static": False,
                "setup_partition_healthy": True,
            },
        },
        "leg_spec": {
            "profile_id": UPPER.profile_id,
            "run_binding_tag": UPPER.run_binding_tag,
            "run_identity": UPPER.run_identity,
            "setup_code": UPPER.setup_code,
            "setup_code_hex": UPPER.setup_code_hex,
            "required_automatic_direction": UPPER.required_direction,
        },
        "intended_live_envelope": {
            "setup_writes": 1,
            "automatic_corrections": MAXIMUM_CORRECTIONS,
            "maximum_step_codes": MAXIMUM_STEP_CODES,
            "maximum_cumulative_codes": MAXIMUM_CUMULATIVE_CODES,
            "minimum_code": MINIMUM_CODE,
            "maximum_code": MAXIMUM_CODE,
            "minimum_applied_cadence_s": MINIMUM_CADENCE_S,
            "settling_exclusion_s": 900,
            "fresh_support_s": 600,
            "qualification_deadline_s": QUALIFICATION_DEADLINE_S,
            "maximum_qualified_duration_s": MAXIMUM_QUALIFIED_DURATION_S,
            "one_request_outstanding": True,
            "automatic_retry": False,
            "automatic_restore": False,
        },
        "command_envelope": {
            "normal_exact": [
                "CONFIG?",
                "DAC?",
                "FC0?",
                "ACTIVE SNAPSHOT <post_attach_nonce>",
                "ACTIVE LEASE <nonzero_uint32>",
                f"ACTIVE SETUP <authorization> <generation> <nonce> <expiry> <session> {UPPER.setup_code_hex} 1 <configuration_sha256> exactly once",
                "ACTIVE ARM <sequence> <nonce> <expiry>",
                "ACTIVE EVIDENCE <request_sequence> <phase_1_to_4>",
            ],
            "emergency_exact": ["ACTIVE ABORT"],
            "normal_batch_limit": 1,
            "normal_command_max_age_s": 2.0,
            "write_timeout_s": 1.0,
        },
        "readiness_gates": {
            "structural_preflight_required": True,
            "accelerated_operational_path_rehearsal_required": True,
            "fresh_host_attach_maximum_uptime_s": FRESH_HOST_ATTACH_MAXIMUM_UPTIME_S,
            "gnss_pps_qualification_deadline_s": RAW_PPS_QUALIFICATION_DEADLINE_S,
            "continuous_drain_from_host_attachment_through_physical_close": True,
            "ordinary_telemetry_attach_baseline_stable_observations": TELEMETRY_BASELINE_STABLE_OBSERVATIONS,
            "post_attach_ordinary_telemetry_increment_forbidden": True,
            "evidence_capture_preview_partition_and_control_gates_absolute": True,
            "gnss_service_precedes_serial_transport_early_return": True,
            "gnss_prewrite_identity_epoch": 1,
            "gnss_identity_and_control_eligibility_required_before_setup": True,
            "passing_g2_seal_required": True,
            "physical_qualification_requires_effective_conditional_authority": True,
            "analyzer_seal_and_registration_required": True,
            "physical_runner_and_live_analyzer_bound": True,
        },
    }
    value = {**unsigned, "bundle_sha256": canonical_sha256(unsigned)}
    _atomic_new(output_path.resolve(), value)
    return value


def validate_frozen_proposal(path: Path) -> dict[str, Any]:
    value = _read(path.resolve(), "G3 proposal bundle")
    unsigned = {key: item for key, item in value.items() if key != "bundle_sha256"}
    if (
        value.get("schema_version") != 1
        or value.get("tool") != UPPER.proposal_tool
        or value.get("bundle_id") != UPPER.proposal_bundle_id
        or value.get("gate") != UPPER.gate
        or value.get("leg") != UPPER.leg
        or value.get("status") != "proposed_not_authorized"
        or value.get("authority", {}).get("effective") is not False
        or value.get("bundle_sha256") != canonical_sha256(unsigned)
    ):
        raise ValueError("G3 proposal identity, authority, or digest differs")
    return value


def validate_proposal(path: Path) -> dict[str, Any]:
    value = validate_frozen_proposal(path)
    _, state = _git_identity()
    if state != "clean":
        raise ValueError("G3 proposal validation requires a clean source state")
    if value.get("host_tools") != {
        name: _binding(tool_path) for name, tool_path in HOST_TOOL_PATHS.items()
    }:
        raise ValueError("G3 proposal host-tool binding is stale")
    if value.get("g2_pass") != validate_g2_pass(
        Path(value["g2_pass"]["seal"]["path"])
    ):
        raise ValueError("G3 proposal G2 prerequisite binding is stale")
    firmware = validate_build(
        leg=UPPER.leg,
        build_manifest_path=Path(value["firmware"]["build_manifest"]["path"]),
        uf2_path=Path(value["firmware"]["uf2"]["path"]),
        allow_clean_ancestor_source=True,
    )
    if value.get("firmware") != firmware:
        raise ValueError("G3 proposal upper firmware binding is stale")
    current_policy = _load_policy()
    if (
        value.get("policy", {}).get("policy_id") != current_policy.get("policy_id")
        or value.get("policy", {}).get("sha256") != _sha256_file(POLICY_PATH)
    ):
        raise ValueError("G3 proposal policy binding is stale")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--g2-seal", type=Path, default=DEFAULT_G2_SEAL)
    create.add_argument("--build-manifest", type=Path, required=True)
    create.add_argument("--uf2", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("proposal", type=Path)
    args = parser.parse_args(argv)
    result = (
        create_proposal(
            g2_seal_path=args.g2_seal,
            build_manifest_path=args.build_manifest,
            uf2_path=args.uf2,
            output_path=args.output,
        )
        if args.command == "create"
        else validate_proposal(args.proposal)
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
