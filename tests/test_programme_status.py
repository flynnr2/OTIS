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


def test_tracked_status_records_g2_recovery_readiness_and_blocks_reuse() -> None:
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
    assert successor["state"] == (
        "g2_recovery_offline_ready_awaiting_exact_v6_authority_and_restart"
    )
    assert successor["allowed_operations"] == [OFFLINE_PREPARATION]
    assert successor["operator_authority"] == {
        "record": (
            "docs/60_EXPERIMENTS/"
            "CX319_STABILIZED_TIGHT_DEADBAND_PROGRAMME/"
            "05_G2_AND_CONDITIONAL_G3_LIVE_AUTHORITY.md"
        ),
        "g2_v5_effective": False,
        "g2_v5_activation_retired_after_prewrite_entry": True,
        "g3_conditional_on_passing_g2_and_fresh_upper_rehearsal": True,
        "g4_authorized": False,
    }
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
            "4650eef8485c412212c29885fd5407f6"
            "adf7de6f71d07babf96f72f8b9a65f34"
        ),
        "preflight_file_sha256": (
            "b6440186e58ab30434cd721a0100cf2b"
            "d9d5ccda89a98cb7107803d53affacab"
        ),
        "operational_rehearsal_file_sha256": (
            "b61fc3e9098abcec574d1fad1548eadd"
            "915e7dd86aaea637718907fe3fd52cac"
        ),
        "operational_rehearsal_content_sha256": (
            "7fa6bd6987e29e16548df372ec915054"
            "0bffc0e2b55b3d32f3a5d34f71c4ee9a"
        ),
        "operational_rehearsal_seal_sha256": (
            "5b5e79a3a81a700961b2d7084f929ae"
            "0683260d444e2f1cf2b1163eb5effef71"
        ),
    }
    assert successor["g2_prewrite_stop"] == {
        "run_id": "live_leg_a_20260811T154208Z",
        "activation_sha256": (
            "510543e64f0cd4c3b71a60ddeeea52e0"
            "e3c32b6338baf28ceba254d39131c67d"
        ),
        "evidence_content_sha256": (
            "a22a32c7716db791ab7d348abeabe3445"
            "a4789667095d78aece2c653c6c6442d"
        ),
        "terminal_reason": (
            "cx319_g2_supervisor_fault:dual-core partition fault: "
            "evidence_queue_exhausted"
        ),
        "setup_stimuli": 0,
        "dac_writes": 0,
        "control_arms": 0,
        "automatic_corrections": 0,
    }
    assert successor["completed_g2_recovery_offline_evidence"] == {
        "source_revision": "ec95f268fc756bf69efa20bc4211883f9bcdb09a",
        "proposal_bundle_sha256": (
            "8726590f586a3c1ff97adbaa02aa3d21"
            "6e89cad61d155489e1988d07860e7df5"
        ),
        "proposal_file_sha256": (
            "0731671cabbc3ffc9ccc1800852ff823"
            "3caf242f53b171ac7b422b3c2f2d1c7a"
        ),
        "preflight_file_sha256": (
            "38f8b3d125ae256d2df359b020318f22"
            "4e4cd9172c755f672f48064699ef7f03"
        ),
        "operational_rehearsal_file_sha256": (
            "12fc3178a4a743868524ed3a6caf3013"
            "1faaba0b10b7063c34fb1436845c45bf"
        ),
        "operational_rehearsal_content_sha256": (
            "558314ac16ee9d12a97c7d557e71e5c4"
            "a8401cabafeb30206710f111adfa6c54"
        ),
        "operational_rehearsal_seal_sha256": (
            "e11e77d788407c873844ac236260921a"
            "335da11f4498839074f7f62b4efad25b"
        ),
        "registration_path_exercised": True,
        "fresh_restart_maximum_prewrite_uptime_s": 120,
    }
    assert successor["forbidden_until_next_gate"] == [
        "g1_physical_repeat",
        "firmware_flash",
        "g2_v5_activation_reuse",
        "dac_write",
        "control_arm",
        "setup_stimulus",
        "automatic_correction",
        "rehearsal_to_live_promotion",
        "g3_live_leg_before_passing_g2_and_fresh_upper_rehearsal",
        "phase_or_hybrid_actuation",
        "g4_progression",
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
