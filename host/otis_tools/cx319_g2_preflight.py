"""No-I/O structural preflight for a CX319 G2 proposal bundle."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .cx319_g1_supervisor import load_cx319_spec
from .cx319_g2_bundle import validate_proposal
from .cx319_g2_contract import normal_command_allowed
from .cx319_g2_runtime_contract import (
    FRESH_RESTART_MAXIMUM_UPTIME_S,
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
    spec, identities, leg = load_cx319_spec("A")
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
        "DAC SET 0xA808",
        "ACTIVE ARM 1 2 3000",
        "ACTIVE EVIDENCE 1 1",
        "ACTIVE EVIDENCE 1 4",
    ]
    rejected = [
        "DAC SET 0xA809",
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
        "passed_g1_same_firmware_and_policy_bound": (
            proposal["g1_pass"]["firmware"] == proposal["firmware"]
            and proposal["g1_pass"]["policy"] == proposal["policy"]
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
                "fresh_restart_maximum_prewrite_uptime_s"
            ]
            == FRESH_RESTART_MAXIMUM_UPTIME_S
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
