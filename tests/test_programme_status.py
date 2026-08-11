from __future__ import annotations

import json
from pathlib import Path

import pytest

from host.otis_tools.programme_status import (
    CX319_G1_NO_WRITE_BENCH_REHEARSAL,
    CX319_G2_LIVE_LEG,
    OFFLINE_PREPARATION,
    ProgrammeExecutionBlocked,
    load_programme_status,
    require_programme_execution_allowed,
    require_programme_operation_allowed,
)


def test_tracked_status_records_g1_pass_and_returns_to_offline_scope() -> None:
    status = load_programme_status()

    assert status["active_programme"] == "cx319_stabilized_tight_deadband"
    assert status["programmes"]["platform_stabilization"] == {
        "state": "completed",
        "allowed_operations": [],
        "effective_date": "2026-08-11",
        "authority": "passed_completion_gate",
    }
    assert status["programmes"]["cx318_stage5"]["state"] == (
        "suspended_incomplete_unsealed"
    )
    assert status["programmes"]["cx318_stage5"]["allowed_operations"] == []
    successor = status["programmes"]["cx319_stabilized_tight_deadband"]
    assert successor["state"] == "g1_passed_g2_offline_preparation"
    assert successor["allowed_operations"] == [OFFLINE_PREPARATION]
    assert successor["completed_g1_evidence"] == {
        "run_id": "no_write_leg_a_20260811T133632Z",
        "bundle_sha256": (
            "777e88c9978edb525f887c496b5badf2"
            "b5e2cdae09bdfaea0a4071932377db77"
        ),
        "seal_sha256": (
            "a690bdfd16754ea90f8f40bc1fcdf8e6"
            "b6b5143b29ef8ad6e96c110f2eaac87b"
        ),
        "evidence_content_sha256": (
            "cd17f90587a321ed0ddd6c40db76c0be"
            "ffc8981c68ef7afdd8e46bbc1549432d"
        ),
    }
    assert successor["forbidden_until_next_gate"] == [
        "g1_physical_repeat",
        "dac_write",
        "control_arm",
        "setup_stimulus",
        "automatic_correction",
        "rehearsal_to_live_promotion",
        "live_actuation",
    ]

    with pytest.raises(ProgrammeExecutionBlocked, match="operational_execution"):
        require_programme_execution_allowed("platform_stabilization")

    assert require_programme_operation_allowed(
        "cx319_stabilized_tight_deadband", OFFLINE_PREPARATION
    ) == successor
    with pytest.raises(ProgrammeExecutionBlocked, match="operation .* is blocked"):
        require_programme_operation_allowed(
            "cx319_stabilized_tight_deadband",
            CX319_G1_NO_WRITE_BENCH_REHEARSAL,
        )
    with pytest.raises(ProgrammeExecutionBlocked, match="operation .* is blocked"):
        require_programme_operation_allowed(
            "cx319_stabilized_tight_deadband", CX319_G2_LIVE_LEG
        )
    with pytest.raises(ProgrammeExecutionBlocked, match="operational_execution"):
        require_programme_execution_allowed("cx319_stabilized_tight_deadband")


def test_suspended_stage5_is_blocked_before_operational_side_effects() -> None:
    with pytest.raises(ProgrammeExecutionBlocked, match="operational_execution"):
        require_programme_execution_allowed("cx318_stage5")


def test_status_contract_rejects_an_inactive_active_programme(
    tmp_path: Path,
) -> None:
    path = tmp_path / "status.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "status_id": "otis_programme_status_v2",
                "active_programme": "blocked",
                "programmes": {
                    "blocked": {
                        "state": "suspended",
                        "allowed_operations": [],
                        "effective_date": "2026-08-11",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="active_programme must permit"):
        load_programme_status(path)


def test_stage5_manifest_create_cli_stops_on_programme_status(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from host.otis_tools import cx318_stage5_manifest

    with pytest.raises(SystemExit) as exc:
        cx318_stage5_manifest.main(
            [
                "create",
                "--mode",
                "rehearsal",
                "--leg",
                "A",
                "--run-dir",
                "/not-used",
                "--build-manifest",
                "/not-used/build.json",
                "--uf2",
                "/not-used/image.uf2",
                "--stage4-seal",
                "/not-used/seal.json",
                "--serial-device",
                "/not-used/device",
            ]
        )

    assert exc.value.code == 2
    assert "suspended_incomplete_unsealed" in capsys.readouterr().err
