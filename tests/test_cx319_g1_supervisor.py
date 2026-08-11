from __future__ import annotations

import csv
from pathlib import Path

import pytest

from host.otis_tools.cx318_stage5_supervisor import Stage5Supervisor
from host.otis_tools.cx319_g1_supervisor import (
    Cx319G1Supervisor,
    POLICY_PATH,
    _sha256,
    load_cx319_spec,
)


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
    spec, identities, selected = load_cx319_spec(leg)

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
        Stage5Supervisor,
        "_command",
        lambda _self, command: submitted.append(command),
    )
    supervisor = Cx319G1Supervisor.__new__(Cx319G1Supervisor)

    for command in ("CONFIG?", "DAC?", "FC0?", "ACTIVE?", "ACTIVE LEASE 7"):
        supervisor._command(command)
    assert submitted == [
        "CONFIG?",
        "DAC?",
        "FC0?",
        "ACTIVE?",
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
    supervisor = Cx319G1Supervisor.__new__(Cx319G1Supervisor)
    supervisor.run_dir = tmp_path
    path = tmp_path / "csv/active_transactions_v1.csv"
    path.parent.mkdir()
    path.write_text("event\napplication\n", encoding="utf-8")

    with pytest.raises(ValueError, match="active transaction"):
        supervisor._process_transactions()


def test_supervisor_replay_identity_is_current_policy() -> None:
    supervisor = Cx319G1Supervisor.__new__(Cx319G1Supervisor)
    supervisor.tight_deadband_policy_sha256 = _sha256(POLICY_PATH)

    assert supervisor.tight_deadband_policy_sha256 == (
        "e278e5d324d9029574102c6fb3a263373888fbd701a6a44a7c913a7d1707de70"
    )


def test_g1_freezes_the_same_stable_host_attach_baseline_as_g2(
    tmp_path: Path,
) -> None:
    supervisor = Cx319G1Supervisor.__new__(Cx319G1Supervisor)
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
