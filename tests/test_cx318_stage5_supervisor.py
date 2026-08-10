from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path

import pytest

from host.otis_tools.contracts import (
    CONTRACT_FIELDS,
    TIGHT_DEADBAND_POLICY_SHA256,
)
from host.otis_tools.cx318_stage5_supervisor import (
    MAXIMUM_QUALIFIED_DURATION_S,
    REHEARSAL_DURATION_S,
    Stage5Supervisor,
    load_stage5_spec,
)


BUILD_IDENTITY = "a" * 64 + ":" + "b" * 64


def _supervisor(tmp_path: Path, *, mode: str, leg_name: str = "A") -> Stage5Supervisor:
    run = tmp_path / f"{mode}_{leg_name}"
    (run / "csv").mkdir(parents=True)
    spec, identities, leg = load_stage5_spec(leg_name)
    return Stage5Supervisor(
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


def _health(supervisor: Stage5Supervisor, **values: str) -> dict[tuple[str, str], str]:
    result = {
        ("cx317_active", "run_identity"): supervisor.spec.run_identity,
        ("cx317_active", "build_identity"): BUILD_IDENTITY,
        ("cx317_active", "profile_identity"): supervisor.spec.profile,
        ("cx317_active", "session_id"): "1",
        ("cx317_active", "state"): "DISARMED",
        ("cx317_active", "reason"): "initialized_disarmed",
        ("cx317_active", "manual_start_confirmed"): "false",
        ("cx317_active", "arm_eligible"): "false",
        ("cx317_active", "evidence_phase"): "evidence_clear",
        ("cx317_active", "correction_count"): "0",
        ("cx317_active", "dac_epoch"): "0",
        ("cx317_active", "selected_interval_count"): "0",
        ("cx317_active", "uptime_s"): "3000",
        ("cx318_preview", "static_code"): "0xA828",
        ("cx318_preview", "applied_code"): "0xA828",
        ("cx318_preview", "dac_epoch"): "0",
    }
    for key, value in supervisor.identities.items():
        result[("cx317_active", key)] = value
    for name, value in values.items():
        result[("cx317_active", name)] = value
    return result


def _write_tight_entry(supervisor: Stage5Supervisor) -> None:
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


def _utc(epoch: float) -> str:
    return (
        datetime.fromtimestamp(epoch, timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def test_load_stage5_specs_bind_exact_opposite_legs() -> None:
    lower, lower_ids, leg_a = load_stage5_spec("A")
    upper, upper_ids, leg_b = load_stage5_spec("B")

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
    spec, identities, leg = load_stage5_spec("A")
    with pytest.raises(ValueError, match="cannot have setup or arm authority"):
        Stage5Supervisor(
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

    assert commands == ["DAC SET 0xA808"]
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
