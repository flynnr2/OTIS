from __future__ import annotations

import json
from pathlib import Path

from host.otis_tools.control_evidence_replay import (
    _capsules_exact,
    _commands_exact,
    _controller_replay,
    _response_replay,
    _selected_frequency_estimator_sha256,
    _selected_windows_nonoverlap,
)
from host.otis_tools.frequency_control_replay import load_current_replay_policy
from host.otis_tools.frequency_control_supervisor import (
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


def test_response_replay_matches_firmware_without_float_deadband() -> None:
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


def test_selected_windows_allow_reset_gaps_but_reject_overlap() -> None:
    assert _selected_windows_nonoverlap([(0, 600), (600, 1200), (2700, 3300)])
    assert not _selected_windows_nonoverlap([(0, 600), (599, 1199)])


def test_measurement_replay_resolves_current_and_legacy_estimator_bindings() -> None:
    identity = "a" * 64
    assert _selected_frequency_estimator_sha256(
        {"policy": {"bindings": {"frequency_estimator": {"sha256": identity}}}}
    ) == identity
    assert _selected_frequency_estimator_sha256(
        {
            "policy": {
                "bindings": {
                    "selected_frequency_estimator": {"sha256": identity}
                }
            }
        }
    ) == identity


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
    (
        tmp_path
        / "reports/step_001"
        / "record_000005_response_replay_attestation.json"
    ).write_text("{}\n", encoding="utf-8")
    exact, hashes = _capsules_exact(tmp_path, rows, events, state)
    assert exact is True
    assert len(hashes) == 4

    events.pop()
    exact, _ = _capsules_exact(tmp_path, rows, events, state)
    assert exact is False


def test_live_capsules_allow_only_declared_terminal_checkpoint_rejection(
    tmp_path: Path,
) -> None:
    rows = _response_group(post_error_hz="0.001")
    phases = {
        "request_created": 1,
        "core0_accepted": 2,
        "application": 3,
        "response": 4,
    }
    response_sequence = int(rows[-1]["transaction_record_sequence"])
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
        if sequence != response_sequence:
            events.append(
                {
                    "event": "transaction_phase_acknowledged",
                    "record_sequence": sequence,
                    "phase": phases[row["event"]],
                }
            )
    state = {
        "acknowledged_record_sequences": [
            int(row["transaction_record_sequence"]) for row in rows[:-1]
        ]
    }

    exact, hashes = _capsules_exact(
        tmp_path,
        rows,
        events,
        state,
        permitted_unacknowledged_sequences=frozenset({response_sequence}),
    )

    assert exact is True
    assert len(hashes) == 4
    assert not _capsules_exact(tmp_path, rows, events, state)[0]


def test_live_command_stream_must_match_supervisor_submission_order() -> None:
    setup = "ACTIVE SETUP 1 7 99 650 4 0xA808 1 " + "b" * 64
    events = [
        {"event": "command_submitted", "command": "CONFIG?"},
        {"event": "host_written", "command": "CONFIG?"},
        {"event": "command_submitted", "command": "DAC?"},
        {"event": "host_written", "command": "DAC?"},
        {"event": "command_submitted", "command": setup},
        {"event": "host_written", "command": setup},
        {"event": "command_submitted", "command": "ACTIVE LEASE 1"},
        {"event": "host_written", "command": "ACTIVE LEASE 1"},
        {"event": "command_submitted", "command": "ACTIVE SNAPSHOT 99"},
        {"event": "host_written", "command": "ACTIVE SNAPSHOT 99"},
    ]
    markers = [
        {"event": "host_command_sent", "command": "CONFIG?"},
        {"event": "host_command_sent", "command": "DAC?"},
        {"event": "host_command_sent", "command": setup},
        {"event": "host_command_sent", "command": "ACTIVE LEASE 1"},
        {"event": "host_command_sent", "command": "ACTIVE SNAPSHOT 99"},
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
    setup = "ACTIVE SETUP 1 7 99 650 4 0xA808 1 " + "b" * 64
    events = [
        {"event": "command_submitted", "command": "CONFIG?"},
        {"event": "host_written", "command": "CONFIG?"},
        {"event": "command_submitted", "command": "DAC?"},
        {"event": "host_written", "command": "DAC?"},
        {"event": "command_submitted", "command": setup},
        {"event": "host_written", "command": setup},
        {"event": "emergency_device_abort_submitted"},
    ]
    markers = [
        {"event": "host_command_sent", "command": "CONFIG?"},
        {"event": "host_command_sent", "command": "DAC?"},
        {"event": "host_command_sent", "command": setup},
        {"event": "host_command_sent", "command": "ACTIVE ABORT"},
    ]
    assert _commands_exact(
        markers,
        events,
        {"commands_sent": 4},
        setup_code=0xA808,
        allowed_emergency_aborts=1,
    )


def test_controller_replay_binds_integer_gate_and_application_delta() -> None:
    policy = load_current_replay_policy()
    stage5_hash = "d" * 64
    estimates = {
        "est:cx317:selected600:000100": {"frequency_error_hz": "0.003333333333"},
        "est:cx317:selected600:000101": {"frequency_error_hz": "-0.010000000000"},
    }
    common = {
        "time_domain": "rp2040_timer0",
        "plant_model_hash": policy.plant_model_hash,
        "policy_version": "CX319_STABILIZED_TIGHT_DEADBAND_FREQUENCY_ONLY_V1",
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


def test_controller_replay_preserves_startup_support_before_first_estimate() -> None:
    policy = load_current_replay_policy()
    stage5_hash = "d" * 64
    control = {
        "control_seq": "0",
        "decision_id": "ctl:cx317:000000",
        "decision_timestamp_ticks": str(policy.warmup_s * 16_000_000),
        "time_domain": "rp2040_timer0",
        "est_input_ref": "est:cx317:selected600:000000",
        "plant_model_hash": policy.plant_model_hash,
        "policy_version": "CX319_STABILIZED_TIGHT_DEADBAND_FREQUENCY_ONLY_V1",
        "config_hash": stage5_hash,
        "control_state": "QUALIFYING",
        "previous_control_state": "WARMUP_INHIBIT",
        "state_transition": "true",
        "transition_reason_code": "fresh_estimator_support",
        "preview_eligibility": "false",
        "current_dac_code": str(0xA808),
        "frequency_error_hz": "",
        "model_applicability": "applicable",
        "raw_delta_codes": "",
        "limited_delta_codes": "",
        "proposed_dac_code": "",
        "step_limited": "false",
        "range_clamped": "false",
        "preview_available": "false",
        "preview_only": "true",
        "actuation_authorized": "false",
        "actionable": "false",
        "decision_reason_code": "fresh_estimator_support",
    }
    manual_setup = {
        "elapsed_ms": "600000",
        "event": "manual_apply",
    }

    exact, replay = _controller_replay(
        [control],
        {},
        [],
        [manual_setup],
        [],
        stage5_policy_sha256=stage5_hash,
    )

    assert exact is True, replay
    assert replay["comparisons"][0]["host_state"] == "QUALIFYING"
    assert replay["comparisons"][0]["host_reason"] == "fresh_estimator_support"


def test_current_analyzer_keeps_phase_hybrid_authority_zero() -> None:
    analyzer = Path(
        "host/otis_tools/bounded_tight_deadband_live_analyze.py"
    ).read_text(encoding="utf-8")
    assert "phase_hybrid_tdb_continuous_and_zero_authority" in analyzer
