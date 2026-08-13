from __future__ import annotations

from copy import deepcopy

import pytest

from host.otis_tools.bounded_tight_deadband_outcome_contract import (
    CONTRACT_ID,
    UPPER_CONTRACT_ID,
    evaluate,
    normal_command_allowed,
)
from host.otis_tools.bounded_tight_deadband_supervisor import create_supervisor


SETUP_COMMAND = (
    "ACTIVE SETUP 1 7 99 650 4 0xA808 1 " + "b" * 64
)


def _transcript() -> dict[str, object]:
    return {
        "schema_version": 1,
        "contract_id": CONTRACT_ID,
        "programme_id": "cx319_stabilized_tight_deadband",
        "gate": "G2",
        "leg": "A",
        "mode": "accelerated_offline_no_io",
        "authority": {"effective": False},
        "hardware_operations": {
            "serial_opens": 0,
            "firmware_flashes": 0,
            "dac_writes": 0,
            "control_arms": 0,
        },
        "commands": [
            {"path": "normal", "command": "CONFIG?", "acknowledged": True},
            {"path": "normal", "command": "DAC?", "acknowledged": True},
            {
                "path": "normal",
                "command": SETUP_COMMAND,
                "acknowledged": True,
            },
            {
                "path": "normal",
                "command": "ACTIVE ARM 1 2 4120",
                "acknowledged": True,
            },
            *[
                {
                    "path": "normal",
                    "command": f"ACTIVE EVIDENCE 1 {phase}",
                    "acknowledged": True,
                }
                for phase in range(1, 5)
            ],
            {
                "path": "emergency",
                "command": "ACTIVE ABORT",
                "acknowledged": True,
            },
        ],
        "setup": {
            "requested_code": 0xA808,
            "applied_code": 0xA808,
            "dac_epoch": 1,
            "acknowledged": True,
        },
        "automatic_transactions": [
            {
                "result": "healthy_completed",
                "delta_codes": 21,
                "applied_code": 0xA81D,
                "application_timestamp_s": 4202,
            }
        ],
        "tight_entry": {
            "consecutive_estimates": 2,
            "integer_edge_error_counts": [2, -2],
            "terminal_state": "TIGHT_INSIDE",
            "current_dac_epoch": 2,
        },
        "limits": {
            "maximum_automatic_corrections": 4,
            "maximum_step_codes": 21,
            "maximum_cumulative_codes": 84,
            "minimum_applied_cadence_s": 1800,
            "settling_exclusion_s": 900,
            "fresh_support_s": 600,
            "qualification_deadline_s": 5400,
            "maximum_qualified_duration_s": 14400,
        },
        "phase_and_hybrid": {
            "actionable": False,
            "actuation_authorized": False,
            "authorization_consumed": False,
            "frequency_controller_input": False,
        },
        "host_attach_telemetry": {
            "ordinary_telemetry_is_diagnostic_and_lossy": True,
            "frozen_baseline": 3,
            "stable_observations": 2,
            "all_evidence_capture_preview_partition_and_control_gates_absolute": True,
            "post_attach_increment_rejected": True,
            "post_attachment_query_nonce": 99,
            "frozen_snapshot_generation": 7,
            "pre_attachment_backlog_rejected": True,
        },
        "gnss_prewrite": {
            "identity_epoch": 1,
            "identity_stable": True,
            "metadata_control_eligible": True,
            "raw_pps_control_eligible": True,
            "control_eligible": True,
            "epoch_2_rejected_before_setup": True,
            "raw_pps_false_before_deadline_no_setup": True,
            "raw_pps_ready_uptime_s": 612,
            "qualification_deadline_s": 660,
            "missing_raw_pps_at_deadline_rejected": True,
        },
        "transport_fault": {
            "normal_path_saturated": True,
            "priority_abort_observed": True,
            "sole_owner": True,
            "serial_reopened": False,
        },
        "closure": {
            "analyzer_ran": True,
            "seal_created": True,
            "registration_rehearsed": True,
            "same_owner_rotation": True,
        },
    }


@pytest.mark.parametrize(
    ("command", "allowed"),
    [
        ("CONFIG?", True),
        ("DAC?", True),
        ("FC0?", True),
        ("ACTIVE?", True),
        ("ACTIVE LEASE 1", True),
        (SETUP_COMMAND, True),
        ("DAC SET 0xA808", False),
        ("ACTIVE ARM 1 2 3", True),
        ("ACTIVE EVIDENCE 1 4", True),
        ("ACTIVE ABORT", False),
        ("DAC SET 0xA809", False),
        ("ACTIVE ARM 0 2 3", False),
        ("ACTIVE EVIDENCE 1 5", False),
        ("PPSGEN START", False),
    ],
)
def test_g2_normal_command_boundary(command: str, allowed: bool) -> None:
    assert normal_command_allowed(command) is allowed


def test_g2_outcome_contract_accepts_the_complete_accelerated_path() -> None:
    result = evaluate(_transcript())

    assert result["status"] == "passed"
    assert all(result["checks"].values())


def test_g2_outcome_contract_accepts_the_complete_physical_path() -> None:
    transcript = deepcopy(_transcript())
    transcript["mode"] = "physical_frequency_only_live"
    transcript["authority"] = {"effective": True}
    transcript["hardware_operations"] = {
        "serial_opens": 1,
        "firmware_flashes": 0,
        "dac_writes": 2,
        "control_arms": 1,
    }
    transcript["commands"] = [
        item
        for item in transcript["commands"]
        if item["path"] != "emergency"
    ]
    transcript["closure"] = {
        "analyzer_ran": True,
        "seal_created": True,
        "registration_completed": True,
        "clean_physical_close": True,
    }
    transcript["terminal"] = {"result": "passed"}

    result = evaluate(transcript)

    assert result["status"] == "passed"
    assert all(result["checks"].values())


def test_g2_outcome_contract_rejects_wrong_direction() -> None:
    transcript = deepcopy(_transcript())
    transcript["automatic_transactions"][0]["delta_codes"] = -21  # type: ignore[index]

    result = evaluate(transcript)

    assert result["status"] == "failed"
    assert (
        result["checks"]["healthy_required_direction_automatic_transaction"]
        is False
    )


def test_g3_outcome_contract_accepts_matched_upper_negative_path() -> None:
    transcript = deepcopy(_transcript())
    transcript.update(contract_id=UPPER_CONTRACT_ID, gate="G3", leg="B")
    transcript["commands"][2]["command"] = (  # type: ignore[index]
        "ACTIVE SETUP 1 7 99 650 4 0xA848 1 " + "b" * 64
    )
    transcript["setup"] = {  # type: ignore[assignment]
        "requested_code": 0xA848,
        "applied_code": 0xA848,
        "dac_epoch": 1,
        "acknowledged": True,
    }
    transcript["automatic_transactions"][0].update(  # type: ignore[index]
        delta_codes=-21,
        applied_code=0xA833,
    )

    result = evaluate(transcript)

    assert result["status"] == "passed"
    assert result["observed"]["required_direction"] == "negative"


def test_g2_outcome_contract_rejects_phase_authority() -> None:
    transcript = deepcopy(_transcript())
    transcript["phase_and_hybrid"]["actionable"] = True  # type: ignore[index]

    result = evaluate(transcript)

    assert result["status"] == "failed"
    assert result["checks"]["phase_and_hybrid_zero_authority"] is False


def test_g2_outcome_contract_rejects_unstable_gnss_prewrite_identity() -> None:
    transcript = deepcopy(_transcript())
    transcript["gnss_prewrite"]["identity_epoch"] = 2  # type: ignore[index]
    transcript["gnss_prewrite"]["identity_stable"] = False  # type: ignore[index]

    result = evaluate(transcript)

    assert result["status"] == "failed"
    assert (
        result["checks"][
            "gnss_identity_and_control_authority_exact_before_setup"
        ]
        is False
    )


def test_g2_supervisor_rejects_commands_outside_live_envelope(
    tmp_path,  # type: ignore[no-untyped-def]
) -> None:
    run = tmp_path / "run"
    (run / "csv").mkdir(parents=True)
    supervisor = create_supervisor(
        run_dir=run,
        command_fifo=tmp_path / "normal",
        emergency_command_fifo=tmp_path / "emergency",
        abort_fifo=tmp_path / "abort",
        expected_build_identity="a" * 64 + ":" + "b" * 64,
    )

    with pytest.raises(ValueError, match="outside the exact normal allowlist"):
        supervisor._command("DAC SET 0xA809")
