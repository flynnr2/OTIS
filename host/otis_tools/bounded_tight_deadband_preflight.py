"""No-I/O structural preflight for a bounded-control proposal bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .no_write_qualification_supervisor import load_no_write_qualification_spec
from .bounded_tight_deadband_bundle import validate_proposal
from .bounded_tight_deadband_outcome_contract import normal_command_allowed
from .bounded_tight_deadband_prewrite_contract import (
    FRESH_HOST_ATTACH_MAXIMUM_UPTIME_S,
    RAW_PPS_QUALIFICATION_DEADLINE_S,
    RUNTIME_CONTRACT_ID,
    TELEMETRY_BASELINE_STABLE_OBSERVATIONS,
    canonical_prewrite_fixture,
    evaluate_prewrite_readiness,
)
from .programme_status import OFFLINE_PREPARATION, load_programme_status


TOOL_ID = "cx319_g2_offline_preflight_v1"


def evaluate(proposal_path: Path) -> dict[str, Any]:
    proposal = validate_proposal(proposal_path)
    status = load_programme_status()["programmes"][proposal["programme_id"]]
    spec, identities, leg = load_no_write_qualification_spec("A")
    build_identity = (
        proposal["firmware"]["source_sha256"]
        + ":"
        + proposal["firmware"]["configuration_sha256"]
    )
    expected_identity = {
        "run_identity": spec.run_identity,
        "build_identity": build_identity,
        "profile_identity": spec.profile,
        **identities,
    }
    health = canonical_prewrite_fixture(
        expected_identity=expected_identity,
        planned_live_stimulus_code=spec.start_code,
    )
    readiness = evaluate_prewrite_readiness(
        health,
        expected_identity=expected_identity,
        planned_live_stimulus_code=spec.start_code,
        active_row_count=0,
        dac_row_count=0,
    )
    accepted = [
        "CONFIG?",
        "DAC?",
        "FC0?",
        "ACTIVE?",
        "ACTIVE LEASE 1",
        "ACTIVE SNAPSHOT 99",
        "ACTIVE SETUP 1 7 99 650 4 0xA808 1 " + "b" * 64,
        "ACTIVE ARM 1 2 3000",
        "ACTIVE EVIDENCE 1 1",
        "ACTIVE EVIDENCE 1 4",
    ]
    rejected = [
        "DAC SET 0xA809",
        "DAC SET 0xA808",
        "DAC MID",
        "DAC ZERO",
        "ACTIVE ABORT",
        "ACTIVE ARM 0 2 3000",
        "ACTIVE EVIDENCE 1 5",
        "SWEEP START",
        "PPSGEN START",
    ]
    envelope = proposal["intended_live_envelope"]
    checks = {
        "proposal_is_explicitly_non_authorizing": (
            proposal["status"] == "proposed_not_authorized"
            and proposal["authority"]["effective"] is False
            and OFFLINE_PREPARATION in status["allowed_operations"]
            and "g2_live_leg" not in status["allowed_operations"]
        ),
        "passed_q1_q3_sequence_same_firmware_and_policy_bound": (
            proposal["g1_pass"]["qualification_sequence_gate"] == "Q3"
            and set(proposal["g1_pass"]["sequence_prerequisites"]) == {"q1", "q2"}
            and proposal["g1_pass"]["firmware"] == proposal["firmware"]
            and proposal["g1_pass"]["policy"] == proposal["policy"]
        ),
        "evidence_epoch_build_and_no_flash_entry_exact": (
            proposal["compatibility_floor"] == "CX319_EVIDENCE_EPOCH_1"
            and proposal["firmware_entry"]
            == {
                "mode": "verify_installed_exact_q3_image_no_flash",
                "required_uf2_sha256": proposal["firmware"]["uf2"]["sha256"],
                "firmware_flash_allowed": False,
                "unknown_or_mismatched_installed_image": (
                    "stop_and_require_shortest_affected_physical_no_write_requalification"
                ),
            }
            and proposal["firmware_build_provenance"]["configuration"]["sha256"]
            == proposal["firmware"]["configuration_sha256"]
            and proposal["firmware_build_provenance"]["target"]["fqbn"]
            == proposal["firmware"]["fqbn"]
            and proposal["expected_device"]["expected_board_serial"]
            == "503533748A919118"
            and proposal["expected_device"]["single_continuously_draining_owner"]
            is True
        ),
        "expected_entry_transcript_is_fail_closed": (
            proposal["expected_entry_transcript"]["build"]
            == {
                "profile_id": proposal["firmware"]["profile_id"],
                "source_sha256": proposal["firmware"]["source_sha256"],
                "configuration_sha256": proposal["firmware"][
                    "configuration_sha256"
                ],
                "uf2_sha256": proposal["firmware"]["uf2"]["sha256"],
            }
            and proposal["expected_entry_transcript"]["dac"]
            == {
                "physical_applied_code_before_setup": "unknown",
                "planned_setup_code": 0xA808,
                "setup_opens_new_dac_epoch": True,
            }
            and proposal["expected_entry_transcript"]["gnss_pps"]
            == {
                "identity_epoch": 1,
                "identity_stable": True,
                "metadata_control_eligible": True,
                "raw_pps_control_eligible": True,
                "qualification_deadline_s": RAW_PPS_QUALIFICATION_DEADLINE_S,
            }
            and proposal["expected_entry_transcript"]["active_snapshot"]
            == {
                "complete_single_generation": True,
                "post_attach_nonce_exact": True,
                "session_nonzero": True,
                "state_before_setup": "DISARMED",
                "fail_static": False,
                "setup_partition_healthy": True,
            }
        ),
        "leg_a_identity_setup_and_direction_exact": (
            spec.profile == "cx319_tight_lower"
            and spec.run_identity == "cx319_tight_lower:3195001"
            and spec.start_code == 0xA808
            and leg.required_direction == 1
        ),
        "live_command_allowlist_exact": (
            all(normal_command_allowed(command) for command in accepted)
            and not any(normal_command_allowed(command) for command in rejected)
        ),
        "prewrite_runtime_contract_exact": (
            readiness.ready
            and readiness.contract_id == RUNTIME_CONTRACT_ID
            and proposal["readiness_gates"][
                "fresh_host_attach_maximum_uptime_s"
            ]
            == FRESH_HOST_ATTACH_MAXIMUM_UPTIME_S
            and proposal["readiness_gates"][
                "gnss_pps_qualification_deadline_s"
            ]
            == RAW_PPS_QUALIFICATION_DEADLINE_S
            and proposal["readiness_gates"][
                "continuous_drain_from_host_attachment_through_physical_close"
            ]
            is True
            and proposal["readiness_gates"][
                "ordinary_telemetry_attach_baseline_stable_observations"
            ]
            == TELEMETRY_BASELINE_STABLE_OBSERVATIONS
            and proposal["readiness_gates"][
                "post_attach_ordinary_telemetry_increment_forbidden"
            ]
            is True
            and proposal["readiness_gates"][
                "evidence_capture_preview_partition_and_control_gates_absolute"
            ]
            is True
            and proposal["readiness_gates"][
                "gnss_service_precedes_serial_transport_early_return"
            ]
            is True
            and proposal["readiness_gates"][
                "gnss_prewrite_identity_epoch"
            ]
            == 1
            and proposal["readiness_gates"][
                "gnss_identity_and_control_eligibility_required_before_setup"
            ]
            is True
            and readiness.physical_dac_confirmation
            == "unknown_before_live_stimulus"
        ),
        "controller_bounds_and_clocks_exact": envelope
        == {
            "setup_writes": 1,
            "automatic_corrections": 4,
            "maximum_step_codes": 21,
            "maximum_cumulative_codes": 84,
            "minimum_code": 0xA800,
            "maximum_code": 0xAB00,
            "minimum_applied_cadence_s": 1800,
            "settling_exclusion_s": 900,
            "fresh_support_s": 600,
            "qualification_deadline_s": 5400,
            "maximum_qualified_duration_s": 14400,
            "one_request_outstanding": True,
            "automatic_retry": False,
            "automatic_restore": False,
        },
        "phase_and_hybrid_authority_zero": (
            proposal["authority"]["phase_or_hybrid_actionable"] is False
        ),
        "complete_operational_rehearsal_still_required": proposal[
            "readiness_gates"
        ]["accelerated_operational_path_rehearsal_required"],
    }
    return {
        "schema_version": 1,
        "tool": TOOL_ID,
        "mode": "offline_no_io",
        "status": "passed" if all(checks.values()) else "failed",
        "proposal_bundle_sha256": proposal["bundle_sha256"],
        "checks": checks,
        "runtime_contract": readiness.as_dict(),
        "hardware_operations": {
            "serial_opens": 0,
            "firmware_flashes": 0,
            "commands": 0,
            "dac_writes": 0,
            "control_arms": 0,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("proposal", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = evaluate(args.proposal)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
