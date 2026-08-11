from __future__ import annotations

from pathlib import Path

import pytest

from host.otis_tools.cx318_stage5_supervisor import Stage5Supervisor
from host.otis_tools.cx319_g1_supervisor import (
    Cx319G1Supervisor,
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
