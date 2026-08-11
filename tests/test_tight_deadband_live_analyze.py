from __future__ import annotations

import json
from pathlib import Path

from host.otis_tools.tight_deadband_live_analyze import (
    _capsules_exact,
    _commands_exact,
    _controller_replay,
    _response_replay,
)
from host.otis_tools.cx317_i_only_preview_replay import load_post_campaign_policy
from host.otis_tools.tight_deadband_supervisor import (
    healthy_required_direction_applications,
)


def _response_group(post_error_hz: str = "0.005") -> list[dict[str, str]]:
    common = {
        "request_sequence": "1",
        "pre_error_hz": "0.001",
        "post_error_hz": "0",
        "requested_delta_codes": "21",
        "applied_code": str(0xA81D),
        "observed_response_hz": "0",
        "cumulative_response_hz": "0",
        "consecutive_indeterminate": "0",
        "response_class": "unavailable",
        "reason": "request_pending",
    }
    rows = []
    for sequence, event in enumerate(
        ("request_created", "core0_accepted", "application", "response"),
        start=2,
    ):
        row = dict(common)
        row.update(
            {
                "transaction_record_sequence": str(sequence),
                "event": event,
            }
        )
        rows.append(row)
    rows[-1].update(
        {
            "post_error_hz": post_error_hz,
            "observed_response_hz": "0.004",
            "cumulative_response_hz": "0.004",
            "response_class": "healthy_detected",
            "reason": "response_detected_with_commanded_sign",
        }
    )
    return rows


def test_stage5_response_replay_matches_firmware_without_legacy_float_deadband() -> None:
    exact, results = _response_replay(_response_group(), 0xA800, 0xAB00)
    assert exact is True
    assert results == [
        {
            "request_sequence": 1,
            "observed_class": "healthy_detected",
            "replayed_class": "healthy_detected",
            "observed_reason": "response_detected_with_commanded_sign",
            "replayed_reason": "response_detected_with_commanded_sign",
            "exact": True,
        }
    ]


def test_required_direction_is_bound_to_its_own_healthy_response() -> None:
    rows = _response_group()
    assert healthy_required_direction_applications(rows, 1) == [rows[2]]
    assert healthy_required_direction_applications(rows, -1) == []

    rows[-1]["response_class"] = "wrong_sign"
    assert healthy_required_direction_applications(rows, 1) == []

    rows[-1]["response_class"] = "healthy_indeterminate_near_resolution"
    assert healthy_required_direction_applications(rows, 1) == [rows[2]]


def test_live_capsules_require_every_nonmanual_row_and_phase_ack(tmp_path: Path) -> None:
    rows = _response_group(post_error_hz="0.010")
    phases = {
        "request_created": 1,
        "core0_accepted": 2,
        "application": 3,
        "response": 4,
    }
    events = []
    for row in rows:
        sequence = int(row["transaction_record_sequence"])
        path = (
            tmp_path
            / "reports/step_001"
            / f"record_{sequence:06d}_{row['event']}.json"
        )
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(row), encoding="utf-8")
        events.append(
            {
                "event": "transaction_phase_acknowledged",
                "record_sequence": sequence,
                "phase": phases[row["event"]],
            }
        )
    state = {
        "acknowledged_record_sequences": [
            int(row["transaction_record_sequence"]) for row in rows
        ]
    }
    exact, hashes = _capsules_exact(tmp_path, rows, events, state)
    assert exact is True
    assert len(hashes) == 4

    events.pop()
    exact, _ = _capsules_exact(tmp_path, rows, events, state)
    assert exact is False


def test_live_command_stream_must_match_supervisor_submission_order() -> None:
    events = [
        {"event": "command_submitted", "command": "CONFIG?"},
        {"event": "command_acknowledged", "command": "CONFIG?"},
        {"event": "command_submitted", "command": "DAC?"},
        {"event": "command_acknowledged", "command": "DAC?"},
        {"event": "command_submitted", "command": "DAC SET 0xA808"},
        {"event": "command_acknowledged", "command": "DAC SET 0xA808"},
        {"event": "command_submitted", "command": "ACTIVE LEASE 1"},
        {"event": "command_acknowledged", "command": "ACTIVE LEASE 1"},
        {"event": "command_submitted", "command": "ACTIVE?"},
        {"event": "command_acknowledged", "command": "ACTIVE?"},
    ]
    markers = [
        {"event": "host_command_sent", "command": "CONFIG?"},
        {"event": "host_command_sent", "command": "DAC?"},
        {"event": "host_command_sent", "command": "DAC SET 0xA808"},
        {"event": "host_command_sent", "command": "ACTIVE LEASE 1"},
        {"event": "host_command_sent", "command": "ACTIVE?"},
    ]
    assert (
        _commands_exact(
            markers,
            events,
            {"commands_sent": 5},
            setup_code=0xA808,
            allowed_emergency_aborts=0,
        )
        is True
    )
    markers.reverse()
    assert (
        _commands_exact(
            markers,
            events,
            {"commands_sent": 5},
            setup_code=0xA808,
            allowed_emergency_aborts=0,
        )
        is False
    )


def test_live_command_stream_accepts_only_the_declared_emergency_abort() -> None:
    events = [
        {"event": "command_submitted", "command": "CONFIG?"},
        {"event": "command_acknowledged", "command": "CONFIG?"},
        {"event": "command_submitted", "command": "DAC?"},
        {"event": "command_acknowledged", "command": "DAC?"},
        {"event": "command_submitted", "command": "DAC SET 0xA808"},
        {"event": "command_acknowledged", "command": "DAC SET 0xA808"},
        {"event": "emergency_device_abort_submitted"},
    ]
    markers = [
        {"event": "host_command_sent", "command": "CONFIG?"},
        {"event": "host_command_sent", "command": "DAC?"},
        {"event": "host_command_sent", "command": "DAC SET 0xA808"},
        {"event": "host_command_sent", "command": "ACTIVE ABORT"},
    ]
    assert _commands_exact(
        markers,
        events,
        {"commands_sent": 4},
        setup_code=0xA808,
        allowed_emergency_aborts=1,
    )


def test_stage5_controller_replay_binds_integer_gate_and_application_delta() -> None:
    policy = load_post_campaign_policy()
    stage5_hash = "d" * 64
    estimates = {
        "est:cx317:selected600:000100": {"frequency_error_hz": "0.003333333333"},
        "est:cx317:selected600:000101": {"frequency_error_hz": "-0.010000000000"},
    }
    common = {
        "time_domain": "rp2040_timer0",
        "plant_model_hash": policy.plant_model_hash,
        "policy_version": "CX318_STAGE5_TIGHT_ACTIVE_FREQUENCY_ONLY_V1",
        "config_hash": stage5_hash,
        "model_applicability": "applicable",
        "preview_only": "true",
        "actuation_authorized": "false",
        "actionable": "false",
        "step_limited": "false",
        "range_clamped": "false",
    }
    controls = [
        {
            **common,
            "control_seq": "0",
            "decision_id": "ctl:cx317:000000",
            "decision_timestamp_ticks": str(4200 * 16_000_000),
            "est_input_ref": "est:cx317:selected600:000100",
            "current_dac_code": str(0xA808),
            "frequency_error_hz": "0.003333333333",
            "control_state": "LOCKED_PREVIEW",
            "previous_control_state": "SETTLE_PREVIEW",
            "state_transition": "true",
            "transition_reason_code": "tight_entry_pending",
            "decision_reason_code": "tight_entry_pending",
            "preview_eligibility": "true",
            "preview_available": "true",
            "raw_delta_codes": "0.000000000000",
            "limited_delta_codes": "0",
            "proposed_dac_code": str(0xA808),
        },
        {
            **common,
            "control_seq": "1",
            "decision_id": "ctl:cx317:000001",
            "decision_timestamp_ticks": str(6000 * 16_000_000),
            "est_input_ref": "est:cx317:selected600:000101",
            "current_dac_code": str(0xA808),
            "frequency_error_hz": "-0.010000000000",
            "control_state": "LOCKED_PREVIEW",
            "previous_control_state": "LOCKED_PREVIEW",
            "state_transition": "false",
            "transition_reason_code": "preview_available_observe_only",
            "decision_reason_code": "preview_available_observe_only",
            "preview_eligibility": "true",
            "preview_available": "true",
            "raw_delta_codes": "28.845027706465",
            "limited_delta_codes": "21",
            "proposed_dac_code": str(0xA81D),
            "step_limited": "true",
        },
    ]
    tdb = [
        {
            "estimate_id": "est:cx317:selected600:000100",
            "frequency_controller_eligible": "false",
            "reason_codes": "tight_entry_pending",
        },
        {
            "estimate_id": "est:cx317:selected600:000101",
            "frequency_controller_eligible": "true",
            "reason_codes": "outside_loose_evidence",
        },
    ]
    dac = [{"elapsed_ms": "2700000"}]
    applications = [
        {
            "decision_sequence": "1",
            "requested_delta_codes": "21",
            "requested_code": str(0xA81D),
        }
    ]

    exact, replay = _controller_replay(
        controls,
        estimates,
        tdb,
        dac,
        applications,
        stage5_policy_sha256=stage5_hash,
    )
    assert exact is True, replay
    assert replay["application_bindings"] == [
        {"decision_sequence": 1, "pass": True}
    ]

    for row in controls:
        row["policy_version"] = (
            "CX319_STABILIZED_TIGHT_DEADBAND_FREQUENCY_ONLY_V1"
        )
    assert _controller_replay(
        controls,
        estimates,
        tdb,
        dac,
        applications,
        stage5_policy_sha256=stage5_hash,
        policy_id="CX319_STABILIZED_TIGHT_DEADBAND_FREQUENCY_ONLY_V1",
    )[0] is True

    applications[0]["requested_delta_codes"] = "20"
    assert _controller_replay(
        controls,
        estimates,
        tdb,
        dac,
        applications,
        stage5_policy_sha256=stage5_hash,
    )[0] is False


def test_live_analyzer_and_gate_keep_hybrid_authority_false() -> None:
    analyzer = Path("host/otis_tools/tight_deadband_live_analyze.py").read_text(
        encoding="utf-8"
    )
    gate = Path("host/otis_tools/cx318_stage5_bidirectional_gate.py").read_text(
        encoding="utf-8"
    )
    assert "phase_hybrid_tdb_continuous_and_zero_authority" in analyzer
    assert '"hybrid_actuation_authorized": False' in gate
    assert '"stage6_frequency_only_authorized": status == "passed"' in gate
