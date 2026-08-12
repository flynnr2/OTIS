from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

import pytest

from host.otis_tools.contracts import (
    CONTRACT_FIELDS,
    TIGHT_DEADBAND_POLICY_SHA256,
)
from host.otis_tools.tight_deadband_supervisor import (
    ACTIVE_SNAPSHOT_COMPLETION_POLL_S,
    ACTIVE_SNAPSHOT_COMPLETION_TIMEOUT_S,
    MAXIMUM_QUALIFIED_DURATION_S,
    PREWRITE_CONTRACT_STARTUP_GRACE_S,
    REHEARSAL_DURATION_S,
    SETUP_RESULT_GRACE_S,
    TightDeadbandSupervisor,
    load_tight_deadband_spec,
)
from host.otis_tools.active_status_live_state import LiveHealthState
from host.otis_tools.setup_authority_contract import (
    SETUP_AUTHORITY_LIFETIME_S,
)
from host.otis_tools.prewrite_readiness_contract import ACTIVE_STATUS_KEYS


BUILD_IDENTITY = "a" * 64 + ":" + "b" * 64


def _supervisor(tmp_path: Path, *, mode: str, leg_name: str = "A") -> TightDeadbandSupervisor:
    run = tmp_path / f"{mode}_{leg_name}"
    (run / "csv").mkdir(parents=True)
    spec, identities, leg = load_tight_deadband_spec(leg_name)
    return TightDeadbandSupervisor(
        mode=mode,
        leg=leg,
        run_dir=run,
        command_fifo=tmp_path / f"{mode}_{leg_name}.command.fifo",
        emergency_command_fifo=tmp_path / f"{mode}_{leg_name}.emergency.fifo",
        abort_fifo=tmp_path / f"{mode}_{leg_name}.abort.fifo",
        spec=spec,
        identities=identities,
        expected_build_identity=BUILD_IDENTITY,
        allow_manual_start=mode == "live",
        allow_arm=mode == "live",
        duration_s=None,
    )


def _health(supervisor: TightDeadbandSupervisor, **values: str) -> dict[tuple[str, str], str]:
    result = {
        **{
            ("cx317_active", key): "present"
            for key in ACTIVE_STATUS_KEYS
        },
        ("cx317_active", "run_identity"): supervisor.spec.run_identity,
        ("cx317_active", "build_identity"): BUILD_IDENTITY,
        ("cx317_active", "profile_identity"): supervisor.spec.profile,
        ("cx317_active", "session_id"): "1",
        ("cx317_active", "query_nonce"): str(
            supervisor.state["host_attach_query_nonce"]
        ),
        ("cx317_active", "snapshot_generation_begin"): "7",
        ("cx317_active", "snapshot_generation_complete"): "7",
        ("cx317_active", "state"): "DISARMED",
        ("cx317_active", "reason"): "initialized_disarmed",
        ("cx317_active", "enabled"): "true",
        ("cx317_active", "evidence_pending"): "false",
        ("cx317_active", "manual_start_confirmed"): "false",
        ("cx317_active", "arm_eligible"): "false",
        ("cx317_active", "evidence_phase"): "evidence_clear",
        ("cx317_active", "capture_lease_live"): "true",
        ("cx317_active", "fail_static"): "false",
        ("cx317_active", "evidence_request_sequence"): "0",
        ("cx317_active", "expected_setup_code"): (
            f"0x{supervisor.spec.start_code:04X}"
        ),
        ("cx317_active", "confirmed_applied_code_known"): "false",
        ("cx317_active", "confirmed_applied_code"): "unavailable",
        ("cx317_active", "correction_count"): "0",
        ("cx317_active", "cumulative_movement_codes"): "0",
        ("cx317_active", "dac_epoch"): "0",
        ("cx317_active", "selected_interval_count"): "0",
        ("cx317_active", "uptime_s"): "3000",
        ("cx317_active", "automatic_retry"): "false",
        ("cx317_active", "automatic_restore"): "false",
        ("cx318_preview", "static_code"): "0xA828",
        ("cx318_preview", "applied_code"): "0xA828",
        ("cx318_preview", "dac_epoch"): "0",
        ("cx317_preview", "actionable"): "false",
        ("cx317_preview", "actuation_authorized"): "false",
        ("cx318_preview", "actionable"): "false",
        ("cx318_preview", "actuation_authorized"): "false",
        ("cx318_preview", "authorization_consumed"): "false",
        ("dac", "applied_code_known"): "false",
        ("dac", "last_write_ok"): "false",
        ("dac", "last_applied_code"): "unavailable",
        ("capture", "dropped_count"): "0",
        ("capture", "pps_count_boundary_dropped_count"): "0",
        ("dual_core", "telemetry_dropped"): "0",
        ("dual_core", "service_publish_failures"): "0",
        ("dual_core", "partition_fault"): "none",
        ("dual_core", "fail_static"): "false",
        ("cx317_preview", "telemetry_dropped_frames"): "0",
    }
    for key, value in supervisor.identities.items():
        result[("cx317_active", key)] = value
    for name, value in values.items():
        result[("cx317_active", name)] = value
    return result


def _write_tight_entry(supervisor: TightDeadbandSupervisor) -> None:
    path = supervisor.run_dir / "csv/tight_deadband_decisions_v1.csv"
    common = {
        "record_type": "TDB",
        "schema_version": "1",
        "decision_timestamp_ticks": "16000000000",
        "time_domain": "rp2040_timer0",
        "capture_session": "1",
        "dac_epoch": "1",
        "absolute_edge_error_counts": "2",
        "release_counter": "0",
        "frequency_controller_eligible": "false",
        "requalified": "false",
        "requalification_reason": "",
        "historical_v2_inside": "true",
        "symmetric_two_count_inside": "true",
        "policy_id": "CX318_STAGE5_TIGHT_HYSTERETIC_COUNTS_V1",
        "policy_sha256": TIGHT_DEADBAND_POLICY_SHA256,
        "actionable": "false",
        "actuation_authorized": "false",
        "authorization_consumed": "false",
    }
    rows = [
        {
            **common,
            "decision_sequence": "0",
            "estimate_id": "est:cx317:selected600:000001",
            "integer_edge_error_counts": "2",
            "state_before": "REQUALIFY_OUTSIDE",
            "state_after": "OUTSIDE",
            "entry_counter": "1",
            "transition": "true",
            "reason_codes": "tight_entry_pending",
        },
        {
            **common,
            "decision_sequence": "1",
            "estimate_id": "est:cx317:selected600:000002",
            "integer_edge_error_counts": "-2",
            "state_before": "OUTSIDE",
            "state_after": "TIGHT_INSIDE",
            "entry_counter": "0",
            "transition": "true",
            "reason_codes": "tight_entry_confirmed",
        },
    ]
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=CONTRACT_FIELDS["tight_deadband_decisions_v1"]
        )
        writer.writeheader()
        writer.writerows(rows)


def _write_outside_cadence_hold(supervisor: TightDeadbandSupervisor) -> None:
    tdb_path = supervisor.run_dir / "csv/tight_deadband_decisions_v1.csv"
    with tdb_path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=CONTRACT_FIELDS["tight_deadband_decisions_v1"]
        )
        writer.writeheader()
        writer.writerow(
            {
                "record_type": "TDB",
                "schema_version": "1",
                "decision_sequence": "0",
                "estimate_id": "est:cx317:selected600:000003",
                "decision_timestamp_ticks": "57627748416",
                "time_domain": "rp2040_timer0",
                "capture_session": "1",
                "dac_epoch": "1",
                "integer_edge_error_counts": "-4",
                "absolute_edge_error_counts": "4",
                "state_before": "REQUALIFY_OUTSIDE",
                "state_after": "OUTSIDE",
                "entry_counter": "0",
                "release_counter": "0",
                "transition": "true",
                "frequency_controller_eligible": "true",
                "requalified": "false",
                "requalification_reason": "",
                "historical_v2_inside": "false",
                "symmetric_two_count_inside": "false",
                "policy_id": "CX318_STAGE5_TIGHT_HYSTERETIC_COUNTS_V1",
                "policy_sha256": TIGHT_DEADBAND_POLICY_SHA256,
                "actionable": "false",
                "actuation_authorized": "false",
                "authorization_consumed": "false",
                "reason_codes": "outside_loose_evidence",
            }
        )
    controls = supervisor.run_dir / "csv/control_previews_v1.csv"
    controls.write_text(
        "decision_timestamp_ticks,preview_available,decision_reason_code,"
        "est_input_ref,decision_id,limited_delta_codes,control_state\n"
        "38427843600,true,preview_available_observe_only,"
        "est:cx317:selected600:000001,ctl:1,21,"
        "LOCKED_PREVIEW\n"
        "48027796864,false,decision_cadence_hold,"
        "est:cx317:selected600:000002,ctl:2,,"
        "LOCKED_PREVIEW\n"
        "57627748416,false,decision_cadence_hold,"
        "est:cx317:selected600:000003,ctl:3,,"
        "LOCKED_PREVIEW\n",
        encoding="utf-8",
    )


def _utc(epoch: float) -> str:
    return (
        datetime.fromtimestamp(epoch, timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def test_load_stage5_specs_bind_exact_opposite_legs() -> None:
    lower, lower_ids, leg_a = load_tight_deadband_spec("A")
    upper, upper_ids, leg_b = load_tight_deadband_spec("B")

    assert (lower.profile, lower.start_code, lower.correction_limit, lower.cumulative_limit) == (
        "cx318_stage5_tight_lower",
        0xA808,
        4,
        84,
    )
    assert (upper.profile, upper.start_code) == ("cx318_stage5_tight_upper", 0xA848)
    assert (leg_a.required_direction, leg_b.required_direction) == (1, -1)
    assert lower_ids == upper_ids


def test_rehearsal_constructor_rejects_any_write_authority(tmp_path: Path) -> None:
    spec, identities, leg = load_tight_deadband_spec("A")
    with pytest.raises(ValueError, match="cannot have setup or arm authority"):
        TightDeadbandSupervisor(
            mode="rehearsal",
            leg=leg,
            run_dir=tmp_path / "run",
            command_fifo=tmp_path / "command",
            emergency_command_fifo=tmp_path / "emergency",
            abort_fifo=tmp_path / "abort",
            spec=spec,
            identities=identities,
            expected_build_identity=BUILD_IDENTITY,
            allow_manual_start=True,
            allow_arm=False,
            duration_s=None,
        )


def test_live_submits_the_exact_setup_once(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path, mode="live")
    commands: list[str] = []
    supervisor._command = commands.append  # type: ignore[method-assign]
    health = _health(supervisor)

    supervisor._maybe_start_or_arm(health)
    supervisor._maybe_start_or_arm(health)

    assert len(commands) == 1
    assert commands[0].startswith("ACTIVE SETUP 1 7 ")
    assert " 1 0xA808 1 " in commands[0]
    assert supervisor.state["manual_start_sent"] is True


def test_live_setup_waits_for_exact_a828_epoch_zero_identity(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path, mode="live")
    commands: list[str] = []
    supervisor._command = commands.append  # type: ignore[method-assign]
    health = _health(supervisor)
    health[("cx318_preview", "dac_epoch")] = "1"

    supervisor._maybe_start_or_arm(health)

    assert commands == []
    assert supervisor.state["manual_start_sent"] is False


def test_lost_setup_transaction_aborts_after_authority_expiry(
    tmp_path: Path,
) -> None:
    supervisor = _supervisor(tmp_path, mode="live")
    commands: list[str] = []
    supervisor._command = commands.append  # type: ignore[method-assign]
    supervisor.emergency_command_fifo = None
    now = 1_800_000_000.0
    supervisor.state.update(
        manual_start_sent=True,
        setup_requested_utc=_utc(
            now - SETUP_AUTHORITY_LIFETIME_S - SETUP_RESULT_GRACE_S
        ),
    )
    health = _health(supervisor, manual_start_confirmed="false")

    supervisor._check_setup_transaction_timeout(health, now - 1.0)
    assert commands == []
    supervisor._check_setup_transaction_timeout(health, now)

    assert commands == ["ACTIVE ABORT"]
    assert supervisor.state["terminal"]["result"] == "aborted"
    assert supervisor.state["terminal"]["reason"] == (
        "setup_transaction_expired_without_observed_result"
    )


def test_missing_required_status_fails_after_cheap_startup_grace(
    tmp_path: Path,
) -> None:
    supervisor = _supervisor(tmp_path, mode="rehearsal")
    health = _health(supervisor)
    del health[("cx317_active", "dac_epoch")]

    supervisor._check_prewrite_contract(
        health, PREWRITE_CONTRACT_STARTUP_GRACE_S - 1
    )
    with pytest.raises(ValueError, match="missing cx317_active.dac_epoch"):
        supervisor._check_prewrite_contract(
            health, PREWRITE_CONTRACT_STARTUP_GRACE_S
        )


def test_health_field_loss_after_readiness_fails_immediately(
    tmp_path: Path,
) -> None:
    supervisor = _supervisor(tmp_path, mode="live")
    health = _health(supervisor)
    supervisor._check_prewrite_contract(health, 0)
    del health[("cx317_preview", "telemetry_dropped_frames")]

    with pytest.raises(ValueError, match="continuous runtime health contract"):
        supervisor._check_fail_static_health(health)


def test_current_health_waits_for_newest_wire_generation_without_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor = _supervisor(tmp_path, mode="rehearsal")
    completed_health = _health(supervisor)
    selections = iter(
        (
            LiveHealthState(
                "in_progress", {}, 8, 100_000_000_000, "started"
            ),
            LiveHealthState(
                "complete",
                completed_health,
                8,
                100_000_000_000,
                "complete",
            ),
        )
    )
    sleeps: list[float] = []
    monkeypatch.setattr(
        "host.otis_tools.tight_deadband_supervisor."
        "read_live_health_state",
        lambda *_args, **_kwargs: next(selections),
    )
    monkeypatch.setattr(
        "host.otis_tools.tight_deadband_supervisor.time.monotonic_ns",
        lambda: 100_000_000_000,
    )
    monkeypatch.setattr(
        "host.otis_tools.tight_deadband_supervisor.time.sleep",
        sleeps.append,
    )

    health = supervisor._current_health()

    assert health == completed_health
    assert sleeps == [ACTIVE_SNAPSHOT_COMPLETION_POLL_S]


def test_current_health_allows_completion_after_declared_q1_detach(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor = _supervisor(tmp_path, mode="rehearsal")
    completed_health = _health(supervisor)
    pending_observed_ns = 100_000_000_000
    selections = iter(
        (
            LiveHealthState(
                "in_progress", {}, 8, pending_observed_ns, "started"
            ),
            LiveHealthState(
                "complete",
                completed_health,
                8,
                pending_observed_ns + 1_600_000_000,
                "complete",
            ),
        )
    )
    monotonic_values = iter(
        (pending_observed_ns + 1_250_000_000, pending_observed_ns + 1_600_000_000)
    )
    monkeypatch.setattr(
        "host.otis_tools.tight_deadband_supervisor."
        "read_live_health_state",
        lambda *_args, **_kwargs: next(selections),
    )
    monkeypatch.setattr(
        "host.otis_tools.tight_deadband_supervisor.time.monotonic_ns",
        lambda: next(monotonic_values),
    )
    monkeypatch.setattr(
        "host.otis_tools.tight_deadband_supervisor.time.sleep",
        lambda _seconds: None,
    )

    assert supervisor._current_health() == completed_health


def test_current_health_returns_negative_evidence_after_bounded_wire_timeout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor = _supervisor(tmp_path, mode="rehearsal")
    selection = LiveHealthState(
        "in_progress", {}, 8, 100_000_000_000, "started"
    )
    monkeypatch.setattr(
        "host.otis_tools.tight_deadband_supervisor."
        "read_live_health_state",
        lambda *_args, **_kwargs: selection,
    )
    monkeypatch.setattr(
        "host.otis_tools.tight_deadband_supervisor.time.monotonic_ns",
        lambda: 100_000_000_000
        + int(ACTIVE_SNAPSHOT_COMPLETION_TIMEOUT_S * 1_000_000_000),
    )
    monkeypatch.setattr(
        "host.otis_tools.tight_deadband_supervisor.time.sleep",
        lambda _seconds: None,
    )

    with pytest.raises(ValueError, match="did not complete"):
        supervisor._current_health()


def test_rehearsal_has_a_finite_no_write_terminal(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path, mode="rehearsal")
    health = _health(supervisor)
    supervisor._rehearsal_evidence_ready = lambda value: True  # type: ignore[method-assign]

    supervisor._maybe_finish(health, 0.0, REHEARSAL_DURATION_S - 1)
    assert supervisor.state["terminal"] is None
    supervisor._maybe_finish(health, 0.0, REHEARSAL_DURATION_S)

    assert supervisor.state["terminal"]["result"] == "healthy_stop"
    assert "no_write_rehearsal" in supervisor.state["terminal"]["reason"]


def test_live_pass_requires_expected_direction_response_and_tight_entry(
    tmp_path: Path,
) -> None:
    supervisor = _supervisor(tmp_path, mode="live")
    _write_tight_entry(supervisor)
    now = 1_800_000_000.0
    supervisor.state.update(
        setup_confirmed_utc=_utc(now - 2000),
        qualification_started_utc=_utc(now - 1000),
        expected_direction_seen=True,
        response_count=1,
        arm_pending=False,
    )
    health = _health(
        supervisor,
        manual_start_confirmed="true",
        arm_eligible="true",
    )

    supervisor._maybe_finish(health, now, 3000.0)

    assert supervisor.state["tight_entry_seen"] is True
    assert supervisor.state["terminal"]["result"] == "healthy_stop"


def test_live_arms_before_next_cadence_after_two_hold_rows(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor = _supervisor(tmp_path, mode="live")
    _write_outside_cadence_hold(supervisor)
    supervisor.state.update(
        manual_start_sent=True,
        setup_confirmed_utc=_utc(1_800_000_000.0),
        qualification_started_utc=_utc(1_800_000_100.0),
    )
    commands: list[str] = []
    monkeypatch.setattr(supervisor, "_identity_ready", lambda health: True)
    monkeypatch.setattr(supervisor, "_command", commands.append)
    health = _health(
        supervisor,
        manual_start_confirmed="true",
        arm_eligible="true",
        selected_interval_count="0",
        uptime_s="3600",
    )

    supervisor._maybe_start_or_arm(health)
    health[("cx317_active", "selected_interval_count")] = "520"
    health[("cx317_active", "uptime_s")] = "4120"
    supervisor._maybe_start_or_arm(health)

    assert len(commands) == 1
    assert commands[0].startswith("ACTIVE ARM 1 ")
    assert supervisor.state["arm_pending"] is True


def test_opposite_only_leg_stops_nonpass_at_frozen_endpoint(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path, mode="live", leg_name="B")
    _write_tight_entry(supervisor)
    commands: list[str] = []
    supervisor._command = commands.append  # type: ignore[method-assign]
    supervisor.emergency_command_fifo = None
    qualified = 1_800_000_000.0
    supervisor.state.update(
        setup_confirmed_utc=_utc(qualified - 1000),
        qualification_started_utc=_utc(qualified),
        expected_direction_seen=False,
        response_count=2,
        arm_pending=False,
    )
    health = _health(supervisor, manual_start_confirmed="true")

    supervisor._maybe_finish(
        health,
        qualified + MAXIMUM_QUALIFIED_DURATION_S,
        MAXIMUM_QUALIFIED_DURATION_S + 1000,
    )

    assert commands == ["ACTIVE ABORT"]
    assert supervisor.state["terminal"]["result"] == "aborted"
    assert supervisor.state["terminal"]["reason"] == (
        "stage5_finite_qualified_endpoint_nonpass"
    )


def test_historical_tight_entry_cannot_pass_after_current_release(
    tmp_path: Path,
) -> None:
    supervisor = _supervisor(tmp_path, mode="live")
    _write_tight_entry(supervisor)
    rows = list(
        csv.DictReader(
            (supervisor.run_dir / "csv/tight_deadband_decisions_v1.csv").open()
        )
    )
    pending_release = dict(rows[-1])
    pending_release.update(
        decision_sequence="2",
        estimate_id="est:cx317:selected600:000003",
        integer_edge_error_counts="4",
        absolute_edge_error_counts="4",
        state_before="TIGHT_INSIDE",
        state_after="TIGHT_INSIDE",
        release_counter="1",
        transition="false",
        frequency_controller_eligible="false",
        reason_codes="loose_release_pending",
        historical_v2_inside="false",
        symmetric_two_count_inside="false",
    )
    released = dict(pending_release)
    released.update(
        decision_sequence="3",
        estimate_id="est:cx317:selected600:000004",
        release_counter="0",
        state_after="OUTSIDE",
        transition="true",
        frequency_controller_eligible="true",
        reason_codes="loose_release_confirmed",
    )
    rows.extend((pending_release, released))
    path = supervisor.run_dir / "csv/tight_deadband_decisions_v1.csv"
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=CONTRACT_FIELDS["tight_deadband_decisions_v1"]
        )
        writer.writeheader()
        writer.writerows(rows)
    now = 1_800_000_000.0
    supervisor.state.update(
        setup_confirmed_utc=_utc(now - 2000),
        qualification_started_utc=_utc(now - 1000),
        expected_direction_seen=True,
        response_count=1,
        arm_pending=False,
        tight_entry_seen=True,
    )

    supervisor._maybe_finish(
        _health(supervisor, manual_start_confirmed="true"), now, 3000.0
    )

    assert supervisor.state["terminal"] is None
