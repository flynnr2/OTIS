from __future__ import annotations

import csv
from pathlib import Path

import pytest

from host.otis_tools import bounded_tight_deadband_supervisor
from host.otis_tools.no_write_qualification_supervisor import load_no_write_qualification_spec
from host.otis_tools.bounded_tight_deadband_prewrite_contract import (
    RAW_PPS_QUALIFICATION_DEADLINE_S,
    RUNTIME_CONTRACT_ID,
    canonical_prewrite_fixture,
)
from host.otis_tools.bounded_tight_deadband_supervisor import create_supervisor, main
from host.otis_tools.programme_status import ProgrammeExecutionBlocked


BUILD_IDENTITY = "a" * 64 + ":" + "b" * 64


def _supervisor(tmp_path: Path):  # type: ignore[no-untyped-def]
    run = tmp_path / "g2"
    (run / "csv").mkdir(parents=True)
    return create_supervisor(
        run_dir=run,
        command_fifo=tmp_path / "normal.fifo",
        emergency_command_fifo=tmp_path / "emergency.fifo",
        abort_fifo=tmp_path / "abort.fifo",
        expected_build_identity=BUILD_IDENTITY,
    )


def _write_telemetry_observations(
    supervisor, values: list[int]
) -> None:  # type: ignore[no-untyped-def]
    path = supervisor.run_dir / "csv/health.csv"
    fields = (
        "record_type",
        "schema_version",
        "status_seq",
        "timestamp_ticks",
        "status_domain",
        "component",
        "status_key",
        "status_value",
        "severity",
        "flags",
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for index, value in enumerate(values, start=1):
            writer.writerow(
                {
                    "record_type": "STS",
                    "schema_version": "1",
                    "status_seq": str(index),
                    "timestamp_ticks": str(index * 160_000_000),
                    "status_domain": "rp2040_timer0",
                    "component": "dual_core",
                    "status_key": "telemetry_dropped",
                    "status_value": str(value),
                    "severity": "WARN" if value else "INFO",
                    "flags": "32" if value else "0",
                }
            )


def _freeze_baseline(supervisor, values: list[int] | None = None) -> None:  # type: ignore[no-untyped-def]
    _write_telemetry_observations(supervisor, values or [0, 0])
    supervisor._observe_telemetry_drop_baseline()
    supervisor.state["host_attach_uptime_s"] = 30
    supervisor.state["host_attach_uptime_status_seq"] = 1


def _bind_snapshot(supervisor, health) -> None:  # type: ignore[no-untyped-def]
    health[("cx317_active", "query_nonce")] = str(
        supervisor.state["host_attach_query_nonce"]
    )
    health[("cx317_active", "snapshot_generation_begin")] = "7"
    health[("cx317_active", "snapshot_generation_complete")] = "7"
    health[("cx317_active", "session_id")] = "4"


def test_g2_spec_is_exact_lower_positive_leg() -> None:
    spec, identities, leg = load_no_write_qualification_spec("A")

    assert spec.profile == "cx319_tight_lower"
    assert spec.run_identity == "cx319_tight_lower:3195001"
    assert spec.start_code == 0xA808
    assert spec.correction_limit == 4
    assert spec.cumulative_limit == 84
    assert spec.maximum_step == 21
    assert leg.required_direction == 1
    assert identities["active_policy_sha256"]


def test_g3_supervisor_is_exact_upper_negative_leg(tmp_path: Path) -> None:
    run = tmp_path / "g3"
    (run / "csv").mkdir(parents=True)
    supervisor = create_supervisor(
        run_dir=run,
        command_fifo=tmp_path / "normal.fifo",
        emergency_command_fifo=tmp_path / "emergency.fifo",
        abort_fifo=tmp_path / "abort.fifo",
        expected_build_identity=BUILD_IDENTITY,
        leg_name="B",
    )

    assert supervisor.spec.profile == "cx319_tight_upper"
    assert supervisor.spec.start_code == 0xA848
    assert supervisor.leg.required_direction == -1
    assert supervisor.state["cx319_gate"] == "G3"
    assert supervisor.state["cx319_leg"] == "B"


@pytest.mark.parametrize(
    ("leg_name", "profile", "start_code", "direction", "gate"),
    [
        ("L", "cx319_range_part_b_lower", 0xA800, 1, "PBL"),
        ("U", "cx319_range_part_b_upper", 0xA890, -1, "PBU"),
    ],
)
def test_conditional_part_b_supervisor_loads_exact_nine_correction_leg(
    tmp_path: Path,
    leg_name: str,
    profile: str,
    start_code: int,
    direction: int,
    gate: str,
) -> None:
    run = tmp_path / gate.lower()
    (run / "csv").mkdir(parents=True)
    supervisor = create_supervisor(
        run_dir=run,
        command_fifo=tmp_path / f"{gate}-normal.fifo",
        emergency_command_fifo=tmp_path / f"{gate}-emergency.fifo",
        abort_fifo=tmp_path / f"{gate}-abort.fifo",
        expected_build_identity=BUILD_IDENTITY,
        leg_name=leg_name,
    )

    assert supervisor.spec.profile == profile
    assert supervisor.spec.start_code == start_code
    assert supervisor.spec.correction_limit == 9
    assert supervisor.spec.cumulative_limit == 189
    assert supervisor.leg.required_direction == direction
    assert supervisor.state["cx319_gate"] == gate


def test_upper_completion_supervisor_loads_exact_bounded_continuation(
    tmp_path: Path,
) -> None:
    run = tmp_path / "pbuc"
    (run / "csv").mkdir(parents=True)
    supervisor = create_supervisor(
        run_dir=run,
        command_fifo=tmp_path / "pbuc-normal.fifo",
        emergency_command_fifo=tmp_path / "pbuc-emergency.fifo",
        abort_fifo=tmp_path / "pbuc-abort.fifo",
        expected_build_identity=BUILD_IDENTITY,
        leg_name="C",
    )

    assert supervisor.spec.profile == "cx319_range_part_b_upper_completion"
    assert supervisor.spec.start_code == 0xA83C
    assert supervisor.spec.correction_limit == 2
    assert supervisor.spec.cumulative_limit == 42
    assert supervisor.leg.required_direction == -1
    assert supervisor.state["cx319_gate"] == "PBUC"


def test_g2_prewrite_contract_has_live_leg_identity(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path)
    expected = {
        "run_identity": supervisor.spec.run_identity,
        "build_identity": BUILD_IDENTITY,
        "profile_identity": supervisor.spec.profile,
        **supervisor.identities,
    }
    health = canonical_prewrite_fixture(
        expected_identity=expected,
        planned_live_stimulus_code=supervisor.spec.start_code,
    )
    _freeze_baseline(supervisor)
    _bind_snapshot(supervisor, health)

    readiness = supervisor._prewrite_readiness(health)

    assert readiness.ready is True
    assert readiness.contract_id == RUNTIME_CONTRACT_ID
    assert readiness.planned_live_stimulus_code == "0xA808"


def test_g2_supervisor_requests_exact_setup_once(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path)
    expected = {
        "run_identity": supervisor.spec.run_identity,
        "build_identity": BUILD_IDENTITY,
        "profile_identity": supervisor.spec.profile,
        **supervisor.identities,
    }
    health = canonical_prewrite_fixture(
        expected_identity=expected,
        planned_live_stimulus_code=supervisor.spec.start_code,
    )
    _freeze_baseline(supervisor)
    _bind_snapshot(supervisor, health)
    commands: list[str] = []
    supervisor._command = commands.append  # type: ignore[method-assign]

    supervisor._maybe_start_or_arm(health)
    supervisor._maybe_start_or_arm(health)

    assert len(commands) == 1
    assert commands[0].startswith("ACTIVE SETUP 1 7 ")
    assert " 4 0xA808 1 " in commands[0]
    assert (supervisor.run_dir / "reports/setup_authority_input_v1.json").is_file()
    assert supervisor.state["manual_start_sent"] is True


def test_g2_supervisor_issues_no_setup_when_exact_firmware_authority_is_false(
    tmp_path: Path,
) -> None:
    supervisor = _supervisor(tmp_path)
    expected = {
        "run_identity": supervisor.spec.run_identity,
        "build_identity": BUILD_IDENTITY,
        "profile_identity": supervisor.spec.profile,
        **supervisor.identities,
    }
    health = canonical_prewrite_fixture(
        expected_identity=expected,
        planned_live_stimulus_code=supervisor.spec.start_code,
    )
    _freeze_baseline(supervisor)
    _bind_snapshot(supervisor, health)
    health[("cx317_active", "setup_reference_eligible")] = "false"
    commands: list[str] = []
    supervisor._command = commands.append  # type: ignore[method-assign]

    supervisor._maybe_start_or_arm(health)

    assert commands == []
    assert supervisor.state["manual_start_sent"] is False
    assert not (supervisor.run_dir / "reports/setup_authority_input_v1.json").exists()


def test_g2_prewrite_allows_pps_qualification_after_fresh_attach_window(
    tmp_path: Path,
) -> None:
    supervisor = _supervisor(tmp_path)
    expected = {
        "run_identity": supervisor.spec.run_identity,
        "build_identity": BUILD_IDENTITY,
        "profile_identity": supervisor.spec.profile,
        **supervisor.identities,
    }
    health = canonical_prewrite_fixture(
        expected_identity=expected,
        planned_live_stimulus_code=supervisor.spec.start_code,
    )
    _freeze_baseline(supervisor)
    _bind_snapshot(supervisor, health)
    health[("cx317_active", "uptime_s")] = "612"

    readiness = supervisor._prewrite_readiness(health)

    assert readiness.ready is True


def test_g2_rejects_pre_attachment_backlog_without_solicited_nonce(
    tmp_path: Path,
) -> None:
    supervisor = _supervisor(tmp_path)
    expected = {
        "run_identity": supervisor.spec.run_identity,
        "build_identity": BUILD_IDENTITY,
        "profile_identity": supervisor.spec.profile,
        **supervisor.identities,
    }
    health = canonical_prewrite_fixture(
        expected_identity=expected,
        planned_live_stimulus_code=supervisor.spec.start_code,
    )
    _freeze_baseline(supervisor)
    health[("cx317_active", "query_nonce")] = "123"
    health[("cx317_active", "snapshot_generation_complete")] = "6"

    readiness = supervisor._prewrite_readiness(health)

    assert readiness.ready is False
    assert any("post-attachment snapshot" in item for item in readiness.mismatches)


def test_g2_uses_the_separate_pps_qualification_deadline(tmp_path: Path) -> None:
    supervisor = _supervisor(tmp_path)

    assert supervisor.prewrite_contract_startup_grace_s == (
        RAW_PPS_QUALIFICATION_DEADLINE_S
    )


def test_g2_freezes_a_stable_nonzero_host_attach_baseline(
    tmp_path: Path,
) -> None:
    supervisor = _supervisor(tmp_path)
    _freeze_baseline(supervisor, [3, 3])

    assert supervisor.state["telemetry_drop_baseline"] == 3
    assert supervisor.state["telemetry_drop_baseline_status_seq"] == 2
    assert supervisor.state["telemetry_drop_candidate_observations"] == 2


def test_g2_waits_for_backlog_convergence_before_freezing_baseline(
    tmp_path: Path,
) -> None:
    supervisor = _supervisor(tmp_path)
    _freeze_baseline(supervisor, [0, 3, 3])

    assert supervisor.state["telemetry_drop_baseline"] == 3
    assert supervisor.state["telemetry_drop_baseline_status_seq"] == 3
    assert supervisor.state["telemetry_drop_candidate_observations"] == 2


def test_g2_rejects_any_telemetry_increment_after_attach_baseline(
    tmp_path: Path,
) -> None:
    supervisor = _supervisor(tmp_path)
    _freeze_baseline(supervisor, [3, 3])

    with pytest.raises(ValueError, match="live telemetry_dropped is 4"):
        supervisor._check_fail_static_health(
            {("dual_core", "telemetry_dropped"): "4"}
        )


def test_g2_cli_is_blocked_before_reading_a_run_spec(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def blocked(*args: object, **kwargs: object) -> None:
        raise ProgrammeExecutionBlocked("operation 'g2_live_leg' is blocked")

    monkeypatch.setattr(
        bounded_tight_deadband_supervisor, "require_programme_operation_allowed", blocked
    )
    with pytest.raises(SystemExit) as exc:
        main(["--run-spec", "/not-used/g2.json"])

    assert exc.value.code == 2
    assert "g2_live_leg" in capsys.readouterr().err
