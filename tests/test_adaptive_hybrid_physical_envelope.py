from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace

import pytest

from host.otis_tools import adaptive_hybrid_activation as activation_module
from host.otis_tools import adaptive_hybrid_proposal as proposal_module
from host.otis_tools import adaptive_hybrid_run as run_module
from host.otis_tools.adaptive_hybrid_contract import (
    ADAPTIVE_HYBRID_PROGRAMME,
    ARM_OPPORTUNITY_INTERVAL_S,
    ARM_SUBMISSION_LIMIT,
    CAUSAL_STATE_CONTRACT_ID,
    CAUSAL_STATE_SCHEMA_VERSION,
    CONTINGENT_72_HOUR_HYBRID_CONTROL,
    INHIBITED_ZERO_WRITE,
    envelope_for_purpose,
)


def test_proposal_requests_the_same_finite_arm_envelope_as_physical_entry() -> None:
    requested = proposal_module._requested_authority(ADAPTIVE_HYBRID_PROGRAMME)

    assert "control_arm_limit" not in requested
    assert requested["arm_submission_limit"] == ARM_SUBMISSION_LIMIT == 468
    assert requested["arm_opportunity_interval_s"] == ARM_OPPORTUNITY_INTERVAL_S == 600
    assert requested["maximum_outstanding_requests"] == 1


def _board_listing(*, product: str = "Nano RP2040 Connect") -> dict[str, object]:
    return {
        "detected_ports": [
            {
                "port": {
                    "address": "/dev/cu.usbmodem-test",
                    "hardware_id": "503533748A919118",
                    "properties": {
                        "serialNumber": "503533748A919118",
                        "vid": "0x2341",
                        "pid": "0x005e",
                        "product": product,
                    },
                },
                "matching_boards": [
                    {
                        "name": "Arduino Nano RP2040 Connect",
                        "fqbn": "rp2040:rp2040:arduino_nano_connect",
                    }
                ],
            }
        ]
    }


@pytest.mark.parametrize(
    ("purpose", "setup", "automatic", "arms", "writes"),
    (
        (INHIBITED_ZERO_WRITE, 0, 0, 0, 0),
        (CONTINGENT_72_HOUR_HYBRID_CONTROL, 1, 144, 468, 145),
    ),
)
def test_activation_and_run_fields_derive_from_exact_bench_envelope(
    purpose: str, setup: int, automatic: int, arms: int, writes: int
) -> None:
    bench = envelope_for_purpose(purpose)
    authority = activation_module._authority(ADAPTIVE_HYBRID_PROGRAMME, bench)
    section = activation_module._run_section(
        ADAPTIVE_HYBRID_PROGRAMME, authority, bench
    )

    assert authority["firmware_flash_limit"] == 1
    assert authority["setup_write_limit"] == setup
    assert authority["maximum_total_automatic_applications"] == automatic
    assert authority["arm_submission_limit"] == arms
    assert authority["total_dac_value_write_limit"] == writes
    expected_wall_s = 7200 if purpose == INHIBITED_ZERO_WRITE else 280800
    assert authority["absolute_wall_clock_limit_s"] == expected_wall_s
    assert section["purpose"] == purpose
    assert section["automatic_control"]["authorized"] is (automatic > 0)
    assert section["automatic_control"]["maximum_total_applications"] == automatic
    assert section["automatic_control"]["maximum_cumulative_movement_codes"] == (
        ADAPTIVE_HYBRID_PROGRAMME.authorized_maximum_cumulative_movement_codes
        if automatic
        else 0
    )
    assert authority["maximum_cumulative_absolute_movement_codes"] == (
        ADAPTIVE_HYBRID_PROGRAMME.authorized_maximum_cumulative_movement_codes
        if automatic
        else 0
    )
    assert section["qualification"]["progress_domain"] == (
        "accepted_D14_D8_apertures"
    )


def test_board_identity_checks_every_envelope_field(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    completed = SimpleNamespace(stdout=json.dumps(_board_listing()))
    monkeypatch.setattr(run_module.subprocess, "run", lambda *_args, **_kwargs: completed)
    bench = envelope_for_purpose(INHIBITED_ZERO_WRITE)

    identity = run_module.read_board_identity(
        "/dev/cu.usbmodem-test", bench_attempt=bench
    )
    assert identity["product"] == "Nano RP2040 Connect"

    completed.stdout = json.dumps(_board_listing(product="lookalike"))
    with pytest.raises(ValueError, match="accepted OTIS bench board"):
        run_module.read_board_identity(
            "/dev/cu.usbmodem-test", bench_attempt=bench
        )


@pytest.mark.parametrize(
    "purpose", (INHIBITED_ZERO_WRITE, CONTINGENT_72_HOUR_HYBRID_CONTROL)
)
def test_single_upload_record_binds_envelope_and_compile_identity(
    purpose: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bench = envelope_for_purpose(purpose)
    identity = bench.as_dict()["device_identity"]
    board = {
        "address": "/dev/cu.usbmodem-test",
        "serial_number": identity["expected_board_serial"],
        "hardware_id": identity["expected_hardware_id"],
        "vid": identity["expected_usb_vid"],
        "pid": identity["expected_usb_pid"],
        "product": identity["expected_usb_product"],
        "board_name": identity["expected_board_name"],
        "board_fqbn": identity["expected_base_fqbn"],
    }
    calls: list[list[str]] = []

    def run(command: list[str], **_kwargs: object) -> SimpleNamespace:
        calls.append(command)
        return SimpleNamespace(returncode=0, stdout="uploaded", stderr="")

    monkeypatch.setattr(run_module.subprocess, "run", run)
    monkeypatch.setattr(run_module, "_fresh_auto_detect_device", lambda: board["address"])
    monkeypatch.setattr(run_module, "read_board_identity", lambda *_args, **_kwargs: board)
    activation = {
        "bench_attempt": bench.as_dict(),
        "authority": {"firmware_flash_limit": 1},
        "firmware": {
            "fqbn": identity["expected_compile_fqbn"],
            "uf2": {"path": "/tmp/frozen.uf2", "sha256": "a" * 64},
            "build_identity": "source:config",
            "image_id": ADAPTIVE_HYBRID_PROGRAMME.profile_id,
        },
        "bundle": {"bundle_sha256": "b" * 64},
    }

    _, _, record = run_module._upload_exact_firmware(
        run_dir=tmp_path,
        activation=activation,
        device=str(board["address"]),
        board_before=board,
        arduino_cli="arduino-cli",
    )

    assert len(calls) == 1
    assert record["firmware_flash_count"] == 1
    assert record["bench_attempt"] == bench.as_dict()
    assert record["compile_fqbn"] == identity["expected_compile_fqbn"]
    assert record["dac_value_write_attempts"] == 0


def test_runner_durations_and_terminals_are_envelope_derived(tmp_path: Path) -> None:
    zero = envelope_for_purpose(INHIBITED_ZERO_WRITE)
    contingent = envelope_for_purpose(CONTINGENT_72_HOUR_HYBRID_CONTROL)
    capture = run_module._capture_command(
        device="/dev/cu.usbmodem-test", run_dir=tmp_path, bench_attempt=zero
    )
    supervisor = run_module._supervisor_command(
        run_dir=tmp_path,
        build_identity="source:config",
        bench_attempt=contingent,
    )
    assert capture[capture.index("--duration-s") + 1] == "7380"
    assert supervisor[supervisor.index("--duration-s") + 1] == "280920"
    assert run_module._terminal_expected(
        {
            "result": "healthy_stop",
            "reason": "inhibited_zero_write_complete",
            "preliminary_decision": "pending_offline_scientific_analysis",
            "last_confirmed_code": None,
        },
        zero,
    )
    assert not run_module._terminal_expected(
        {
            "result": "healthy_stop",
            "reason": "inhibited_zero_write_complete",
            "preliminary_decision": "pending_offline_scientific_analysis",
            "last_confirmed_code": 43000,
        },
        zero,
    )
    assert not run_module._terminal_expected(
        {
            "result": "healthy_stop",
            "reason": contingent.as_dict()["terminal_semantics"][
                "success_terminal"
            ],
            "preliminary_decision": "pending_offline_scientific_analysis",
            "last_confirmed_code": None,
        },
        contingent,
    )
    assert run_module._terminal_expected(
        {
            "result": "healthy_stop",
            "reason": "adaptive_hybrid_qualified_complete",
            "preliminary_decision": "pending_offline_scientific_analysis",
            "last_confirmed_code": ADAPTIVE_HYBRID_PROGRAMME.setup_code,
        },
        contingent,
    )


def _zero_write_review_inputs() -> dict[str, object]:
    bench = envelope_for_purpose(INHIBITED_ZERO_WRITE)
    identities = {
        "active_policy_sha256": "active",
        "estimator_sha256": "estimator",
        "model_sha256": "model",
        "numerical_policy_sha256": "numerical",
        "response_policy_sha256": "response",
    }
    supervisor = {
        "terminal": None,
        "host_verification_hold": {
            "source": "bench_attempt_wall_endpoint_observer",
            "error": "zero-write wall endpoint lacks a clear static terminal",
            "review_status": "operator_review_required",
            "new_authority": False,
        },
        "manual_start_sent": False,
        "setup_requested_utc": None,
        "setup_confirmed_utc": None,
        "setup_authorization_sequence": 0,
        "setup_authority_path": None,
        "setup_confirmation": None,
        "arm_pending": False,
        "arm_sent_at_utc": None,
        "authorization_sequence": 0,
        "bench_attempt_arm_admission_closed": True,
        "bench_attempt_arm_submission_count": 0,
        "bench_attempt_last_arm_opportunity": None,
        "bench_attempt_arm_admissions": [],
        "terminal_static_code": None,
        "bench_attempt_causal_state": {
            "schema_version": CAUSAL_STATE_SCHEMA_VERSION,
            "contract": CAUSAL_STATE_CONTRACT_ID,
            "durable_ACT_application_count": 0,
            "firmware_correction_count": 0,
            "authority_closed": True,
            "closure": {
                "trigger": "initial_contract_state",
                "bench_attempt_purpose": INHIBITED_ZERO_WRITE,
                "bench_attempt_envelope_sha256": bench.as_dict()[
                    "envelope_sha256"
                ],
            },
        },
        "wall_origin_utc": "2026-09-09T00:00:00Z",
        "qualified_authoritative_capture_baseline": {
            "rejected_window_count": 0
        },
        "qualified_d14_accepted_window_origin": 10,
        "qualified_d14_reference_sequence_origin": 10,
        "qualified_d14_accepted_apertures": 20,
        "initial_session_id": 1,
    }
    capture_counters = {
        "commands_rejected": 0,
        "emergency_aborts_sent": 0,
        "malformed_utf8": 0,
        "parser_errors": 0,
        "reconnect_count": 0,
    }
    capture = {
        **capture_counters,
        "capture_active": False,
        "serial_open": False,
        "physical_serial_open": False,
        "logical_segment_closed": True,
        "intentional_detach_count": 0,
    }
    closure = {
        "closed_utc": "2026-09-09T02:03:00Z",
        "closure_mode": "physical_serial_close",
        "physical_serial_open": False,
        "logical_segment_closed": True,
        "counters": capture_counters,
    }
    health = {
        ("adaptive_hybrid", key): value
        for key, value in {
            "state": "DISARMED",
            "reason": "initialized_disarmed",
            "hybrid_state": "SETUP_PENDING",
            "hybrid_reason": "setup_consumers_pending",
            "capture_lease_live": "true",
            "manual_start_confirmed": "false",
            "arm_eligible": "false",
            "fail_static": "false",
            "evidence_phase": "evidence_clear",
            "evidence_pending": "false",
            "evidence_request_sequence": "0",
            "confirmed_applied_code_known": "false",
            "confirmed_applied_code": "unavailable",
            "correction_count": "0",
            "cumulative_movement_codes": "0",
            "dac_epoch": "0",
            "phase_material_application_count": "0",
            "phase_nonzero_application_count": "0",
            "frequency_only_application_count": "0",
            "first_phase_checkpoint_passed": "false",
            "automatic_retry": "false",
            "automatic_restore": "false",
            "run_identity": "run",
            "build_identity": "build",
            "image_identity": "image",
            **identities,
        }.items()
    }
    health.update(
        {
            ("pps_gate", "snapshot_session"): "1",
            ("pps_gate", "accepted_window_count"): "30",
            ("pps_gate", "boundary_reference_sequence"): "30",
            ("pps_gate", "rejected_window_count"): "0",
            ("pps_gate", "state"): "open",
            ("pps_gate", "valid"): "true",
            ("pps_gate", "control_eligible"): "true",
        }
    )
    return {
        "bench_attempt": bench,
        "manifest": {
            "run_identity": "run",
            "image_identity": "image",
            "firmware": {"build_identity": "build"},
            "transaction_identities": identities,
        },
        "supervisor_state": supervisor,
        "capture_state": capture,
        "capture_closure": closure,
        "completion": {"terminal": None, "orchestration_error": None},
        "health": health,
        "active_rows": [],
        "dac_rows": [],
        "setup_authority_present": False,
    }


def test_zero_write_review_derives_null_code_terminal_from_exact_absence() -> None:
    terminal = run_module._zero_write_review_terminal(
        **_zero_write_review_inputs()
    )

    assert terminal == {
        "result": "healthy_stop",
        "reason": "inhibited_zero_write_complete",
        "preliminary_decision": "pending_offline_scientific_analysis",
        "last_confirmed_code": None,
        "utc": "2026-09-09T02:03:00Z",
    }


def test_zero_write_review_rejects_a_fabricated_static_code() -> None:
    inputs = deepcopy(_zero_write_review_inputs())
    inputs["health"][("adaptive_hybrid", "confirmed_applied_code_known")] = "true"
    inputs["health"][("adaptive_hybrid", "confirmed_applied_code")] = "0xA84D"

    with pytest.raises(ValueError, match="confirmed_applied_code_known"):
        run_module._zero_write_review_terminal(**inputs)


def test_zero_write_review_rejects_any_setup_authority_frontier() -> None:
    retained = deepcopy(_zero_write_review_inputs())
    retained["supervisor_state"]["setup_authorization_sequence"] = 1
    with pytest.raises(ValueError, match="setup_authorization_sequence"):
        run_module._zero_write_review_terminal(**retained)

    artifact = deepcopy(_zero_write_review_inputs())
    artifact["setup_authority_present"] = True
    with pytest.raises(ValueError, match="setup, ACT, or DAC"):
        run_module._zero_write_review_terminal(**artifact)


def test_finalization_recovery_cannot_redirect_its_retained_index(
    tmp_path: Path,
) -> None:
    retained = (tmp_path / "retained-index.json").resolve()
    journal = {"index_path": str(retained)}

    assert run_module._recovery_index_path(journal, None) == retained
    assert run_module._recovery_index_path(journal, retained) == retained
    with pytest.raises(ValueError, match="differs from the retained journal"):
        run_module._recovery_index_path(journal, tmp_path / "other-index.json")
