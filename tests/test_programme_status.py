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


def test_tracked_status_records_g2_offline_readiness_without_live_authority() -> None:
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
    assert successor["state"] == "g2_offline_ready_awaiting_live_authority"
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
    assert successor["completed_g2_offline_evidence"] == {
        "proposal_bundle_sha256": (
            "29ee02a7d1a577668617ff0655f432bf"
            "3526f293839399526900067f91617328"
        ),
        "preflight_file_sha256": (
            "6f9cef83043c2308016bd44ebf2a24d6"
            "7a621ba10a88c75314c4ab8e644e4be9"
        ),
        "operational_rehearsal_file_sha256": (
            "52133d3a8536e6f0a3ebc74ab2145bb"
            "1ae2e3654e02eb87eb9c66949b1b84e11"
        ),
        "operational_rehearsal_content_sha256": (
            "4ac768fce52ce119441545c8b39109ce"
            "1072e7dd14e7dbcf3a994c8591f2706e"
        ),
        "operational_rehearsal_seal_sha256": (
            "6ad255a95a8916db6f4ba4290a2d7cdf"
            "8de014ba8d0ef9e8a71fbfddf3aeb01f"
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
