from __future__ import annotations

from copy import deepcopy

import pytest

from host.otis_tools.cx319_g2_contract import evaluate, normal_command_allowed
from host.otis_tools.cx319_g2_supervisor import create_supervisor


def _transcript() -> dict[str, object]:
    return {
        "schema_version": 1,
        "contract_id": "cx319_g2_leg_a_outcome_contract_v1",
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
                "command": "DAC SET 0xA808",
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
        ("DAC SET 0xA808", True),
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
    assert result["checks"]["healthy_positive_automatic_transaction"] is False


def test_g2_outcome_contract_rejects_phase_authority() -> None:
    transcript = deepcopy(_transcript())
    transcript["phase_and_hybrid"]["actionable"] = True  # type: ignore[index]

    result = evaluate(transcript)

    assert result["status"] == "failed"
    assert result["checks"]["phase_and_hybrid_zero_authority"] is False


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
