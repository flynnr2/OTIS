from __future__ import annotations

import csv
from pathlib import Path

import pytest

from host.otis_tools import bounded_tight_deadband_supervisor
from host.otis_tools.no_write_qualification_supervisor import load_no_write_qualification_spec
from host.otis_tools.bounded_tight_deadband_prewrite_contract import (
    FRESH_HOST_ATTACH_MAXIMUM_UPTIME_S,
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
    commands: list[str] = []
    supervisor._command = commands.append  # type: ignore[method-assign]

    supervisor._maybe_start_or_arm(health)
    supervisor._maybe_start_or_arm(health)

    assert commands == ["DAC SET 0xA808"]
    assert supervisor.state["manual_start_sent"] is True


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
    health[("cx317_active", "uptime_s")] = "612"

    readiness = supervisor._prewrite_readiness(health)

    assert readiness.ready is True


def test_g2_prewrite_rejects_a_stale_host_attachment(tmp_path: Path) -> None:
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
    supervisor.state["host_attach_uptime_s"] = (
        FRESH_HOST_ATTACH_MAXIMUM_UPTIME_S + 1
    )

    readiness = supervisor._prewrite_readiness(health)

    assert readiness.ready is False
    assert any("fresh host-attach" in item for item in readiness.mismatches)


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
