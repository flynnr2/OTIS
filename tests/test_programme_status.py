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


def test_tracked_status_records_g2_v7_nonpass_and_blocks_g3() -> None:
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
        "g1_recovery_host_timing_repair_in_offline_preparation"
    )
    assert successor["allowed_operations"] == [OFFLINE_PREPARATION]
    assert successor["authority"] == (
        "explicit_operator_g1_recovery_no_write_authority"
    )
    assert successor["next_gate"] == (
        "host_timing_repair_complete_operational_rehearsal_then_fresh_no_flash_g1_authority"
    )
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
    assert successor["g2_v6_operator_authority"] == {
        "record": (
            "docs/60_EXPERIMENTS/"
            "CX319_STABILIZED_TIGHT_DEADBAND_PROGRAMME/"
            "08_G2_V6_LIVE_AUTHORITY.md"
        ),
        "physical_presence_confirmed": True,
        "one_board_restart": True,
        "firmware_flash": False,
        "fresh_restart_maximum_prewrite_uptime_s": 120,
        "effective": False,
        "activation_retired_after_prewrite_entry": True,
    }
    assert successor["g2_v6_prewrite_stop"] == {
        "run_id": "live_leg_a_v6_20260811T162957Z",
        "activation_sha256": (
            "664310ab48fbf118fd8b90d370be50941"
            "307cd7895131eaa926cd337c3134027"
        ),
        "evidence_content_sha256": (
            "e30e7f32edff77e05e7ebc867d75edc"
            "a27f819698b9af194a485ee83ebf2d05c"
        ),
        "terminal_reason": (
            "cx319_g2_supervisor_fault:live telemetry_dropped is 3"
        ),
        "fresh_restart_uptime_s": 14,
        "telemetry_queue_high_water": 192,
        "telemetry_dropped": 3,
        "partition_fault": "none",
        "evidence_queue_high_water": 0,
        "setup_stimuli": 0,
        "dac_writes": 0,
        "control_arms": 0,
        "automatic_corrections": 0,
    }
    assert successor["completed_g2_v7_offline_evidence"] == {
        "source_revision": "5582ea1aee3084d01f2a69184982e574b0f7f783",
        "proposal_bundle_sha256": (
            "f92f41854306bba103afd8ef0fe1aa56"
            "0360aa0da81c94547624165028b68dd4"
        ),
        "proposal_file_sha256": (
            "5a58381efbdb4636df7f0ac59ae40a728"
            "0490b67bab65c90f363c487ffe9b416"
        ),
        "preflight_file_sha256": (
            "7a82247d504f3c30bda3fa77b21e2fa8"
            "426b9746881e4ca186e06394521bffb4"
        ),
        "operational_rehearsal_file_sha256": (
            "825c7677e88ada1f86644ab95503341ae"
            "7ab90d57d50f114087380014e00a612"
        ),
        "operational_rehearsal_content_sha256": (
            "549d93a5227482515a5824a044ff6b2e"
            "7a7530473074c42a0e33f6c52c179b43"
        ),
        "operational_rehearsal_seal_sha256": (
            "be8973fb35b33c2015887d8af81e2329"
            "bd8e3400c5266afbf3a148c92836ec0c"
        ),
        "registration_path_exercised": True,
        "ordinary_telemetry_attach_baseline_stable_observations": 2,
        "post_attach_ordinary_telemetry_increment_forbidden": True,
        "absolute_non_telemetry_health_gates": True,
    }
    assert successor["g2_v7_operator_authority"] == {
        "record": (
            "docs/60_EXPERIMENTS/"
            "CX319_STABILIZED_TIGHT_DEADBAND_PROGRAMME/"
            "11_G2_V7_LIVE_AUTHORITY.md"
        ),
        "physical_presence_confirmed": True,
        "one_board_restart": True,
        "firmware_flash": False,
        "fresh_restart_maximum_prewrite_uptime_s": 120,
        "ordinary_telemetry_attach_baseline_stable_observations": 2,
        "post_attach_ordinary_telemetry_increment_forbidden": True,
        "effective": False,
        "activation_retired_after_terminal": True,
    }
    assert successor["g3_conditional_upper_flash_authority"] == {
        "record": (
            "docs/60_EXPERIMENTS/"
            "CX319_STABILIZED_TIGHT_DEADBAND_PROGRAMME/"
            "12_CONDITIONAL_G3_UPPER_FLASH_AND_LIVE_AUTHORITY.md"
        ),
        "currently_executable": False,
        "requires_passing_g2_analysis_and_seal": True,
        "requires_fresh_exact_upper_bundle_preflight_and_operational_rehearsal": True,
        "firmware_profile": "cx319_tight_upper",
        "exact_firmware_flash_limit": 1,
        "g3_live_execution": True,
        "existing_bounded_envelope": True,
        "manual_reset_expected_after_successful_upload": False,
        "operator_assistance_required_if_upload_or_reenumeration_fails": True,
    }
    assert successor["g2_v7_qualification_deadline_nonpass"] == {
        "run_id": "live_leg_a_v7_20260811T170842Z",
        "activation_sha256": (
            "b7ce4ba75fd2ff2f5c67b1a90b6a25ff"
            "f1cd1bf16d18ff6e201f703415947787"
        ),
        "started_utc": "2026-08-11T17:08:42Z",
        "terminal_utc": "2026-08-11T18:38:58Z",
        "terminal_reason": "stage5_qualification_deadline_expired",
        "run_state": "complete",
        "analysis_status": "failed",
        "evidence_content_sha256": (
            "530def1cdbc3353de48bfdd7f0fd4380e"
            "a55020bdca0fad0ea73252ccfe29980"
        ),
        "evidence_snapshot_digest": (
            "8e5ec0aeb28fd8a6dafcaf50849dd46c"
            "88409c2b901d1dbf6bd5e0542ff8f099"
        ),
        "seal_sha256": (
            "7d4a10f0d70d866d53bb9f95270e536"
            "9b235814fbefe3c5a4e9624943399670e"
        ),
        "seal_file_sha256": (
            "a90216aadf1d8e18f294112755c708df"
            "3d10697b9fb7431c48b49d979f3a394f"
        ),
        "external_registration_classification": "interrupted_campaign",
        "qualification_started": False,
        "gnss_receiver_identity_epoch": 2,
        "gnss_receiver_control_eligible": False,
        "runtime_health_integrity_clean": True,
        "ordinary_telemetry_attach_baseline": 3,
        "post_attach_ordinary_telemetry_increment": 0,
        "serial_reconnects": 0,
        "serial_parser_errors": 0,
        "setup_stimuli": 1,
        "dac_writes": 1,
        "control_arms": 0,
        "automatic_corrections": 0,
    }
    assert successor["g2_cross_surface_recovery"] == {
        "cause": (
            "dual_core_busy_serial_transport_early_return_starved_gnss_rx_"
            "and_manufactured_identity_epoch_2"
        ),
        "firmware_recovery": (
            "bounded_gnss_rx_service_precedes_serial_transport_early_return"
        ),
        "host_recovery": (
            "prewrite_requires_exact_epoch_1_gnss_and_pps_control_authority"
        ),
        "g1_runtime_contract_id": "cx319_g1_prewrite_runtime_contract_v3",
        "runtime_contract_id": "cx319_g2_prewrite_runtime_contract_v5",
        "outcome_contract_id": "cx319_g2_leg_a_outcome_contract_v2",
        "host_attach_contract": (
            "two_stable_observations_then_frozen_no_increment"
        ),
        "full_host_test_count": 1085,
        "full_host_tests_passed": True,
        "fresh_g1_physical_requalification_required": True,
        "g2_retry_authorized": False,
        "g3_currently_authorized": False,
    }
    assert successor["g1_recovery_no_write_authority"] == {
        "record": (
            "docs/60_EXPERIMENTS/"
            "CX319_STABILIZED_TIGHT_DEADBAND_PROGRAMME/"
            "14_G1_RECOVERY_NO_WRITE_AUTHORITY.md"
        ),
        "effective": False,
        "consumed": True,
        "device": "/dev/cu.usbmodem14601",
        "firmware_profile": "cx319_tight_lower",
        "exact_firmware_flash_limit": 1,
        "physical_no_write_runs": 1,
        "dac_value_writes": 0,
        "setup_stimuli": 0,
        "control_arms": 0,
        "automatic_corrections": 0,
        "manual_reset_expected_after_successful_upload": False,
        "operator_assistance_required_if_upload_or_reenumeration_fails": True,
        "consumed_by_run_id": "no_write_recovery_leg_a_20260811T200913Z",
    }
    assert successor["g1_recovery_timing_stop"]["flash_status"] == "pass"
    assert successor["g1_recovery_timing_stop"]["flash_attempts"] == 1
    assert successor["g1_recovery_timing_stop"]["gnss_identity_epoch"] == 1
    assert successor["g1_recovery_timing_stop"]["host_prewrite_deadline_s"] == 30
    assert successor["g1_recovery_timing_stop"][
        "observed_historical_raw_pps_eligibility_s"
    ] == 612
    assert successor["g1_recovery_timing_stop"]["dac_value_writes"] == 0
    assert successor["forbidden_until_next_gate"] == [
        "g2_v5_activation_reuse",
        "g2_v6_activation_reuse",
        "g2_v7_activation_reuse",
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
