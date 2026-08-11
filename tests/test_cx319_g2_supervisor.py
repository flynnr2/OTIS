from __future__ import annotations

from pathlib import Path

import pytest

from host.otis_tools import cx319_g2_supervisor
from host.otis_tools.cx319_g1_supervisor import load_cx319_spec
from host.otis_tools.cx319_g2_runtime_contract import (
    FRESH_RESTART_MAXIMUM_UPTIME_S,
    RUNTIME_CONTRACT_ID,
    canonical_prewrite_fixture,
)
from host.otis_tools.cx319_g2_supervisor import create_supervisor, main
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


def test_g2_spec_is_exact_lower_positive_leg() -> None:
    spec, identities, leg = load_cx319_spec("A")

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
    commands: list[str] = []
    supervisor._command = commands.append  # type: ignore[method-assign]

    supervisor._maybe_start_or_arm(health)
    supervisor._maybe_start_or_arm(health)

    assert commands == ["DAC SET 0xA808"]
    assert supervisor.state["manual_start_sent"] is True


def test_g2_prewrite_rejects_a_clean_but_stale_ownerless_session(
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
    health[("cx317_active", "uptime_s")] = str(
        FRESH_RESTART_MAXIMUM_UPTIME_S + 1
    )

    readiness = supervisor._prewrite_readiness(health)

    assert readiness.ready is False
    assert any("fresh restart" in item for item in readiness.mismatches)


def test_g2_cli_is_blocked_before_reading_a_run_spec(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    def blocked(*args: object, **kwargs: object) -> None:
        raise ProgrammeExecutionBlocked("operation 'g2_live_leg' is blocked")

    monkeypatch.setattr(
        cx319_g2_supervisor, "require_programme_operation_allowed", blocked
    )
    with pytest.raises(SystemExit) as exc:
        main(["--run-spec", "/not-used/g2.json"])

    assert exc.value.code == 2
    assert "g2_live_leg" in capsys.readouterr().err
