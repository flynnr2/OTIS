from __future__ import annotations

import csv
from pathlib import Path

import pytest

from host.otis_tools.tight_deadband_supervisor import TightDeadbandSupervisor
from host.otis_tools.no_write_qualification_supervisor import (
    NoWriteQualificationSupervisor,
    POLICY_PATH,
    _sha256,
    load_no_write_qualification_spec,
)
from host.otis_tools.no_write_prewrite_readiness_contract import (
    RAW_PPS_QUALIFICATION_DEADLINE_S,
    canonical_prewrite_fixture,
)


BUILD_IDENTITY = "a" * 64 + ":" + "b" * 64


def _supervisor(tmp_path: Path) -> NoWriteQualificationSupervisor:
    run = tmp_path / "g1"
    (run / "csv").mkdir(parents=True)
    spec, identities, leg = load_no_write_qualification_spec("A")
    supervisor = NoWriteQualificationSupervisor(
        leg=leg,
        run_dir=run,
        command_fifo=tmp_path / "normal.fifo",
        emergency_command_fifo=tmp_path / "emergency.fifo",
        abort_fifo=tmp_path / "abort.fifo",
        spec=spec,
        identities=identities,
        expected_build_identity=BUILD_IDENTITY,
        duration_s=None,
    )
    supervisor.state.update(
        telemetry_drop_baseline=0,
        telemetry_drop_baseline_status_seq=2,
        host_attach_uptime_s=30,
        host_attach_uptime_status_seq=1,
    )
    return supervisor


@pytest.mark.parametrize(
    ("leg", "profile", "tag", "code", "direction"),
    [
        ("A", "cx319_tight_lower", 3195001, 0xA808, 1),
        ("B", "cx319_tight_upper", 3195002, 0xA848, -1),
    ],
)
def test_current_spec_is_exact(
    leg: str, profile: str, tag: int, code: int, direction: int
) -> None:
    spec, identities, selected = load_no_write_qualification_spec(leg)

    assert spec.profile == profile
    assert spec.run_identity == f"{profile}:{tag}"
    assert spec.start_code == code
    assert spec.maximum_step == 21
    assert selected.required_direction == direction
    assert set(identities) == {
        "estimator_sha256",
        "model_sha256",
        "active_policy_sha256",
        "response_policy_sha256",
        "numerical_policy_sha256",
    }


def test_supervisor_command_override_rejects_every_write_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    submitted: list[str] = []
    monkeypatch.setattr(
        TightDeadbandSupervisor,
        "_command",
        lambda _self, command: submitted.append(command),
    )
    supervisor = NoWriteQualificationSupervisor.__new__(NoWriteQualificationSupervisor)

    for command in (
        "CONFIG?",
        "DAC?",
        "FC0?",
        "ACTIVE?",
        "ACTIVE SNAPSHOT 99",
        "ACTIVE LEASE 7",
    ):
        supervisor._command(command)
    assert submitted == [
        "CONFIG?",
        "DAC?",
        "FC0?",
        "ACTIVE?",
        "ACTIVE SNAPSHOT 99",
        "ACTIVE LEASE 7",
    ]

    for command in (
        "ACTIVE ABORT",
        "DAC SET 0xA808",
        "DAC MID",
        "DAC ZERO",
        "ACTIVE ARM 1 2 3",
        "ACTIVE EVIDENCE 1 1",
        "SWEEP START",
        "PPSGEN START",
    ):
        with pytest.raises(ValueError, match="no-write allowlist"):
            supervisor._command(command)


def test_any_active_transaction_is_terminal_failure(tmp_path: Path) -> None:
    supervisor = NoWriteQualificationSupervisor.__new__(NoWriteQualificationSupervisor)
    supervisor.run_dir = tmp_path
    path = tmp_path / "csv/active_transactions_v1.csv"
    path.parent.mkdir()
    path.write_text("event\napplication\n", encoding="utf-8")

    with pytest.raises(ValueError, match="active transaction"):
        supervisor._process_transactions()


def test_supervisor_replay_identity_is_current_policy() -> None:
    supervisor = NoWriteQualificationSupervisor.__new__(NoWriteQualificationSupervisor)
    supervisor.tight_deadband_policy_sha256 = _sha256(POLICY_PATH)

    assert supervisor.tight_deadband_policy_sha256 == (
        "936d92a1421b7a8f3db620cd0add2c1ecd1a73dbd9aad4581beb8d8c0b8e1698"
    )


def test_g1_freezes_the_same_stable_host_attach_baseline_as_g2(
    tmp_path: Path,
) -> None:
    supervisor = NoWriteQualificationSupervisor.__new__(NoWriteQualificationSupervisor)
    supervisor.run_dir = tmp_path
    supervisor.state = {
        "telemetry_drop_candidate": None,
        "telemetry_drop_candidate_observations": 0,
        "telemetry_drop_last_status_seq": 0,
        "telemetry_drop_baseline": None,
        "telemetry_drop_baseline_status_seq": None,
    }
    supervisor._event = lambda *args, **kwargs: None  # type: ignore[method-assign]
    supervisor._save = lambda: None  # type: ignore[method-assign]
    path = tmp_path / "csv/health.csv"
    path.parent.mkdir()
    fields = (
        "record_type",
        "status_seq",
        "component",
        "status_key",
        "status_value",
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for sequence, value in enumerate((0, 3, 3), start=1):
            writer.writerow(
                {
                    "record_type": "STS",
                    "status_seq": str(sequence),
                    "component": "dual_core",
                    "status_key": "telemetry_dropped",
                    "status_value": str(value),
                }
            )

    supervisor._observe_telemetry_drop_baseline()

    assert supervisor.state["telemetry_drop_baseline"] == 3
    assert supervisor.state["telemetry_drop_baseline_status_seq"] == 3


def test_g1_waits_for_deliberate_pps_startup_qualification(
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
    health[("gnss_receiver", "raw_pps_control_eligible")] = "false"
    health[("gnss_receiver", "control_eligible")] = "false"

    supervisor._check_prewrite_contract(health, 30)
    supervisor._check_prewrite_contract(
        health, RAW_PPS_QUALIFICATION_DEADLINE_S - 1
    )
    with pytest.raises(ValueError, match="raw_pps_control_eligible"):
        supervisor._check_prewrite_contract(
            health, RAW_PPS_QUALIFICATION_DEADLINE_S
        )


def test_g1_accepts_pps_qualification_at_the_observed_612_seconds(
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
    health[("cx317_active", "uptime_s")] = "612"
    health[("cx317_active", "query_nonce")] = str(
        supervisor.state["host_attach_query_nonce"]
    )
    health[("cx317_active", "snapshot_generation_complete")] = "7"

    readiness = supervisor._check_prewrite_contract(health, 612)

    assert readiness is not None and readiness.ready is True
    assert supervisor.prewrite_contract_startup_grace_s == 660
