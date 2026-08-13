from __future__ import annotations
import json
from pathlib import Path

import pytest

from host.otis_tools.programme_status import (
    NO_WRITE_BENCH_REHEARSAL,
    BOUNDED_TIGHT_DEADBAND_LIVE_LEG,
    OFFLINE_PREPARATION,
    ProgrammeExecutionBlocked,
    load_programme_status,
    require_programme_execution_allowed,
    require_programme_operation_allowed,
)


def test_tracked_status_authorizes_observed_manual_restart_once() -> None:
    status = load_programme_status()

    assert status["active_programme"] == "cx319_stabilized_tight_deadband"
    assert status["programmes"]["platform_stabilization"] == {
        "state": "completed",
        "allowed_operations": [],
        "effective_date": "2026-08-11",
        "authority": "passed_completion_gate",
    }
    successor = status["programmes"]["cx319_stabilized_tight_deadband"]
    assert successor["state"] == (
        "q4_lower_manual_restart_authorized_awaiting_observer"
    )
    assert successor["allowed_operations"] == [
        OFFLINE_PREPARATION,
        BOUNDED_TIGHT_DEADBAND_LIVE_LEG,
    ]
    assert successor["authority"] == (
        "explicit_operator_q4_lower_manual_restart_live_authority"
    )
    assert successor["next_gate"] == (
        "arm_observer_then_one_manual_reset_and_exact_candidate_once"
    )
    assert successor["q4_lower_live_authority"] == {
        "record": (
            "docs/60_EXPERIMENTS/"
            "CX319_STABILIZED_TIGHT_DEADBAND_PROGRAMME/"
            "20_Q4_LOWER_SIDE_FINITE_LIVE_AUTHORITY.md"
        ),
        "operator_instruction": "move_on_to_the_physical_q4_live_run",
        "effective": False,
        "consumed": True,
        "consumed_by_activation_sha256": (
            "fc138d94f9c858b1c54e73364635fc34"
            "11fe2726ea16ff357cda5ef667b294fe"
        ),
        "consumed_by_run_id": "live_leg_a_20260813T074315Z",
        "programme_operation": BOUNDED_TIGHT_DEADBAND_LIVE_LEG,
        "live_run_limit": 1,
        "firmware_flash_limit": 0,
        "board_reset_limit": 0,
        "setup_write_limit": 1,
        "control_arm_limit": 1,
        "automatic_correction_limit": 4,
        "maximum_step_codes": 21,
        "maximum_cumulative_codes": 84,
        "minimum_code": 0xA800,
        "maximum_code": 0xAB00,
        "phase_or_hybrid_actionable": False,
        "expected_board_serial": "503533748A919118",
        "required_uf2_sha256": (
            "50f863a2150d1b1391504553a1d20e1c"
            "b951daae5b450a83c90628265a522083"
        ),
        "proposal_bundle_sha256": (
            "f08c9a581ec92271828f9c7c0ff87b5"
            "e0d1ce04e6015c92d4100c75f7882bbfe"
        ),
        "operational_rehearsal_seal_sha256": (
            "4e6d20094a80e9a3ffcabc6db93302b4"
            "9acfbf5d48a2da6faeaa70ebe1f65084"
        ),
    }
    assert successor["q4_lower_live_prewrite_stop"] == {
        "record": (
            "docs/60_EXPERIMENTS/"
            "CX319_STABILIZED_TIGHT_DEADBAND_PROGRAMME/"
            "21_Q4_LOWER_SIDE_PREWRITE_TRANSPORT_STOP.md"
        ),
        "run_id": "live_leg_a_20260813T074315Z",
        "activation_sha256": (
            "fc138d94f9c858b1c54e73364635fc34"
            "11fe2726ea16ff357cda5ef667b294fe"
        ),
        "activation_file_sha256": (
            "9f436238a598f4860d323126a6cb3b14"
            "abf663dffa4bb0844f152dc023e7e8c2"
        ),
        "run_manifest_sha256": (
            "aa301587e20fe935aed9e0303a53a8234"
            "f216ad9dbf20f2b59db1aa7ac5f4c0d"
        ),
        "terminal_reason": (
            "cx319_g2_supervisor_fault:capture transport state mismatch: "
            "capture_active=False, expected True"
        ),
        "evidence_content_sha256": (
            "ae3cbc42e62b05daa41de6502b2ed27a"
            "0a18eeb6bcfc2672f55f6c79c099ab93"
        ),
        "capture_commands_sent": 32,
        "firmware_lines_received": 0,
        "serial_write_timeout": True,
        "setup_stimuli": 0,
        "dac_value_writes": 0,
        "control_arms": 0,
        "automatic_corrections": 0,
        "failure_class": "platform_escape_into_campaign",
        "scientific_result": False,
    }
    assert successor["q4_lower_retry_offline_readiness"] == {
        "record": (
            "docs/60_EXPERIMENTS/"
            "CX319_STABILIZED_TIGHT_DEADBAND_PROGRAMME/"
            "22_Q4_LOWER_SIDE_RETRY_OFFLINE_READINESS.md"
        ),
        "authority_proposal": (
            "profiles/qualification/"
            "cx319_q4_lower_live_retry_authority_proposal_v1.json"
        ),
        "outcome": "q4_lower_retry_offline_ready_for_separate_authority",
        "source_revision": "421501dc49d29eb91f6160a0b7965475c12c706b",
        "proposal_bundle_sha256": (
            "9697652d963c0bcfe44800c1f3ff7c6c"
            "f032ca382c5479c8cec0edb1ddccbd56"
        ),
        "proposal_file_sha256": (
            "1c9e64cab6ca10d7d114927dcb378d75"
            "f350150633c188f73642f874c8b94a8d"
        ),
        "preflight_file_sha256": (
            "07df6e2d08f1fbfa38978091d0174d2b"
            "bd020a6f55ee743fd9a4cbfe3ecab7a1"
        ),
        "operational_rehearsal_file_sha256": (
            "413e64508bc1ae7dadffac816e157335f"
            "f4db899ec7bc01aadfb50018c232e6b"
        ),
        "operational_rehearsal_content_sha256": (
            "89f8df3952218cb729f22d62acc5969e"
            "c2b30d447f21fedb8a4d178f2b755877"
        ),
        "operational_rehearsal_seal_sha256": (
            "c56d402abd3ac208ca10b73f78863372"
            "ca4abb176c10c8d56c3c3d2845c84c6d"
        ),
        "live_runner_sha256": (
            "833bc0f3c07a2bb678cd7a863f8a1f44"
            "e947a5e5ae9772114cf54ac192d657c5"
        ),
        "reused_q1_q3_and_firmware_evidence": True,
        "live_authority_effective": False,
    }
    assert successor["q4_lower_retry_live_authority"] == {
        "record": (
            "docs/60_EXPERIMENTS/"
            "CX319_STABILIZED_TIGHT_DEADBAND_PROGRAMME/"
            "23_Q4_LOWER_SIDE_RETRY_LIVE_AUTHORITY.md"
        ),
        "operator_instruction": "authorized",
        "effective": False,
        "consumed": True,
        "consumed_by_activation_sha256": (
            "439c201d91d5e3e3a17dad28d3fcffcc"
            "e55959768c2d9b83c42f366f3ed12958"
        ),
        "consumed_by_restart_attempt_record_sha256": (
            "e06e59e266f2d96adceb9dd1bb67c2f8"
            "df7560a8a4ebfc3fbae1a5237a09c878"
        ),
        "programme_operation": BOUNDED_TIGHT_DEADBAND_LIVE_LEG,
        "board_restart_limit": 1,
        "firmware_flash_limit": 0,
        "physical_live_run_limit": 1,
        "setup_write_limit": 1,
        "control_arm_limit": 1,
        "automatic_correction_limit": 4,
        "maximum_step_codes": 21,
        "maximum_cumulative_codes": 84,
        "minimum_code": 0xA800,
        "maximum_code": 0xAB00,
        "phase_or_hybrid_actionable": False,
        "expected_board_serial": "503533748A919118",
        "required_uf2_sha256": (
            "50f863a2150d1b1391504553a1d20e1c"
            "b951daae5b450a83c90628265a522083"
        ),
        "proposal_bundle_sha256": (
            "9697652d963c0bcfe44800c1f3ff7c6c"
            "f032ca382c5479c8cec0edb1ddccbd56"
        ),
        "operational_rehearsal_seal_sha256": (
            "c56d402abd3ac208ca10b73f78863372"
            "ca4abb176c10c8d56c3c3d2845c84c6d"
        ),
    }
    assert successor["q4_lower_retry_restart_stop"] == {
        "record": (
            "docs/60_EXPERIMENTS/"
            "CX319_STABILIZED_TIGHT_DEADBAND_PROGRAMME/"
            "24_Q4_LOWER_SIDE_RESTART_PATH_STOP.md"
        ),
        "authority_proposal": (
            "profiles/qualification/"
            "cx319_q4_lower_live_manual_restart_authority_proposal_v1.json"
        ),
        "activation_sha256": (
            "439c201d91d5e3e3a17dad28d3fcffcc"
            "e55959768c2d9b83c42f366f3ed12958"
        ),
        "restart_attempt_record_sha256": (
            "e06e59e266f2d96adceb9dd1bb67c2f8"
            "df7560a8a4ebfc3fbae1a5237a09c878"
        ),
        "restart_observed": False,
        "firmware_flashes": 0,
        "physical_live_runs": 0,
        "serial_opens": 0,
        "setup_stimuli": 0,
        "dac_value_writes": 0,
        "control_arms": 0,
        "automatic_corrections": 0,
        "candidate_and_rehearsal_remain_current": True,
        "failure_class": "platform_defect_before_hardware_effect",
    }
    assert successor["q4_lower_manual_restart_live_authority"] == {
        "record": (
            "docs/60_EXPERIMENTS/"
            "CX319_STABILIZED_TIGHT_DEADBAND_PROGRAMME/"
            "25_Q4_LOWER_SIDE_MANUAL_RESTART_LIVE_AUTHORITY.md"
        ),
        "operator_instruction": (
            "I authorize the manual-reset proposal and I am at the bench."
        ),
        "physical_presence_confirmed": True,
        "effective": True,
        "consumed": False,
        "programme_operation": BOUNDED_TIGHT_DEADBAND_LIVE_LEG,
        "manual_reset_button_only": True,
        "restart_observer_required_before_press": True,
        "software_restart_commands": False,
        "board_restart_limit": 1,
        "firmware_flash_limit": 0,
        "physical_live_run_limit": 1,
        "setup_write_limit": 1,
        "control_arm_limit": 1,
        "automatic_correction_limit": 4,
        "maximum_step_codes": 21,
        "maximum_cumulative_codes": 84,
        "minimum_code": 0xA800,
        "maximum_code": 0xAB00,
        "phase_or_hybrid_actionable": False,
        "expected_board_serial": "503533748A919118",
        "required_uf2_sha256": (
            "50f863a2150d1b1391504553a1d20e1c"
            "b951daae5b450a83c90628265a522083"
        ),
        "proposal_bundle_sha256": (
            "9697652d963c0bcfe44800c1f3ff7c6c"
            "f032ca382c5479c8cec0edb1ddccbd56"
        ),
        "operational_rehearsal_seal_sha256": (
            "c56d402abd3ac208ca10b73f78863372"
            "ca4abb176c10c8d56c3c3d2845c84c6d"
        ),
    }
    assert successor["q4_offline_readiness"] == {
        "record": (
            "docs/60_EXPERIMENTS/"
            "CX319_STABILIZED_TIGHT_DEADBAND_PROGRAMME/"
            "18_Q4_LOWER_SIDE_OFFLINE_READINESS_REPORT.md"
        ),
        "authority_proposal": (
            "profiles/qualification/"
            "cx319_q4_lower_live_authority_proposal_v1.json"
        ),
        "outcome": "q4_offline_ready_for_separate_live_authority_decision",
        "source_revision": "2f46e1f01da75a17c69b259626d282df4ca1bcdc",
        "proposal_bundle_sha256": (
            "f08c9a581ec92271828f9c7c0ff87b5"
            "e0d1ce04e6015c92d4100c75f7882bbfe"
        ),
        "proposal_file_sha256": (
            "4c83e4736af8ab1a5ef07840c28a6b98"
            "841932fcbf3402a0ae329c554cbf9a40"
        ),
        "preflight_file_sha256": (
            "444dc38dcff124341b868a9ba48e510e5"
            "0b51dce3c1d99a286b8e4db12f4068b"
        ),
        "operational_rehearsal_file_sha256": (
            "95ec5a8916d1f63f73a62308823ec32d"
            "43acaf2b580cf28d418698094b49584b"
        ),
        "operational_rehearsal_content_sha256": (
            "2d45d94cdfd4477ca5f028e1007843ae"
            "385539c91add7d05abec593f43a0d7c7"
        ),
        "operational_rehearsal_seal_sha256": (
            "4e6d20094a80e9a3ffcabc6db93302b4"
            "9acfbf5d48a2da6faeaa70ebe1f65084"
        ),
        "release_tests_passed": 723,
        "supported_profiles_passed": 2,
        "expected_failure_guards_passed": 5,
        "live_authority_effective": False,
    }
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
        "full_host_test_count": 1088,
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
    assert successor["q1_q3_sequence_authority"] == {
        "record": (
            "docs/60_EXPERIMENTS/"
            "CX319_STABILIZED_TIGHT_DEADBAND_PROGRAMME/"
            "16_Q1_Q3_SEQUENCE_AUTHORITY.md"
        ),
        "effective": False,
        "consumed": True,
        "current_gate": "complete",
        "q1_exact_lower_flash_limit": 1,
        "q1_dac_value_writes": 0,
        "q2_requires_bound_stub_or_confirmed_electrical_inhibition": True,
        "q3_no_write": True,
        "q4_authorized": False,
    }
    assert successor["q1_sequence_result"]["seal_sha256"] == (
        "0d8c4863a48930f40057b6bc665f8fa8"
        "80a83548a4ff7a4b30525c3bff7639df"
    )
    assert successor["q2_sequence_result"]["seal_sha256"] == (
        "86eafb3c3c55cde62c555eec4658fe90"
        "fb77faa9a5d44a5db65b2f080567fb66"
    )
    assert successor["q2_sequence_result"][
        "physical_oscillator_movement_possible"
    ] is False
    assert successor["q3_sequence_result"] == {
        "run_id": "q3_physical_no_write_20260812T150928Z",
        "host_source_revision": "1a58f44584137d770a0c661de4f1e653f12cdfcf",
        "firmware_source_revision": "1c1d7382b85534e06d5b2a8d086d9e5621fa3b2f",
        "bundle_sha256": (
            "28a4d0f01e54aa9ea4068a6b7cdd360"
            "763e42781932b19a9ef9b39222552a7ab"
        ),
        "uf2_sha256": (
            "50f863a2150d1b1391504553a1d20e1c"
            "b951daae5b450a83c90628265a522083"
        ),
        "seal_sha256": (
            "4d0747017fa77810bf3967a4f3bbe64e"
            "8f0d7ce962cb3143a1d56540f3fa8c35"
        ),
        "evidence_content_sha256": (
            "989170aaad2cabfd7454a9e8c047ab35"
            "14f1e6da90ff423d34461e783dd641e7"
        ),
        "capture_duration_s": 2706.0,
        "selected_600s_estimates": 1,
        "dac_value_writes": 0,
        "setup_stimuli": 0,
        "control_arms": 0,
        "automatic_corrections": 0,
        "serial_reconnects": 0,
        "serial_parser_errors": 0,
        "priority_abort_passed": True,
        "same_owner_logical_rotation": True,
    }
    assert successor["forbidden_until_next_gate"] == [
        "g2_v5_activation_reuse",
        "g2_v6_activation_reuse",
        "g2_v7_activation_reuse",
        "rehearsal_to_live_promotion",
        "firmware_flash",
        "board_reset",
        "automatic_retry",
        "automatic_restore",
        "duration_extension",
        "second_q4_lower_live_run",
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
            NO_WRITE_BENCH_REHEARSAL,
        )
    assert require_programme_operation_allowed(
        "cx319_stabilized_tight_deadband",
        BOUNDED_TIGHT_DEADBAND_LIVE_LEG,
    ) == successor
    with pytest.raises(ProgrammeExecutionBlocked, match="operational_execution"):
        require_programme_execution_allowed("cx319_stabilized_tight_deadband")


def test_q4_lower_live_authority_proposal_is_machine_readable_and_non_effective() -> None:
    root = Path(__file__).resolve().parents[1]
    proposal = json.loads(
        (
            root
            / "profiles/qualification/"
            "cx319_q4_lower_live_authority_proposal_v1.json"
        ).read_text(encoding="utf-8")
    )

    assert proposal["authority_id"] == (
        "CX319_Q4_LOWER_FINITE_LIVE_AUTHORITY_PROPOSAL_V1"
    )
    assert proposal["status"] == "draft_non_effective"
    assert proposal["effective"] is False
    assert set(proposal["current_permissions"].values()) == {False}
    assert proposal["required_separate_transition"] == {
        "programme_operation": BOUNDED_TIGHT_DEADBAND_LIVE_LEG,
        "explicit_operator_decision": True,
        "effective_authority_record": True,
        "exact_candidate_and_rehearsal_binding": True,
    }
    assert proposal["proposed_future_entry"]["firmware_entry"] == (
        "verify_installed_exact_q3_image_no_flash"
    )


def test_q4_lower_retry_authority_proposal_is_non_effective_and_reset_bounded() -> None:
    root = Path(__file__).resolve().parents[1]
    proposal = json.loads(
        (
            root
            / "profiles/qualification/"
            "cx319_q4_lower_live_retry_authority_proposal_v1.json"
        ).read_text(encoding="utf-8")
    )

    assert proposal["authority_id"] == (
        "CX319_Q4_LOWER_FINITE_LIVE_RETRY_AUTHORITY_PROPOSAL_V1"
    )
    assert proposal["status"] == "draft_non_effective"
    assert proposal["effective"] is False
    assert set(proposal["current_permissions"].values()) == {False}
    assert proposal["required_separate_transition"] == {
        "programme_operation": BOUNDED_TIGHT_DEADBAND_LIVE_LEG,
        "explicit_operator_decision": True,
        "effective_authority_record": True,
        "exact_candidate_and_rehearsal_binding": True,
    }
    assert proposal["proposed_future_entry"]["board_restart_limit"] == 1
    assert proposal["proposed_future_entry"]["firmware_flash_limit"] == 0
    assert proposal["proposed_future_entry"]["physical_live_run_limit"] == 1
    assert proposal["proposed_future_live_envelope"][
        "phase_or_hybrid_actionable"
    ] is False


def test_q4_manual_restart_proposal_is_non_effective_and_button_only() -> None:
    root = Path(__file__).resolve().parents[1]
    proposal = json.loads(
        (
            root
            / "profiles/qualification/"
            "cx319_q4_lower_live_manual_restart_authority_proposal_v1.json"
        ).read_text(encoding="utf-8")
    )

    assert proposal["authority_id"] == (
        "CX319_Q4_LOWER_MANUAL_RESTART_LIVE_AUTHORITY_PROPOSAL_V1"
    )
    assert proposal["status"] == "draft_non_effective"
    assert proposal["effective"] is False
    assert set(proposal["current_permissions"].values()) == {False}
    assert proposal["proposed_future_entry"]["manual_reset_button_only"] is True
    assert proposal["proposed_future_entry"]["software_restart_commands"] is False
    assert proposal["proposed_future_entry"]["board_restart_limit"] == 1
    assert proposal["proposed_future_entry"]["firmware_flash_limit"] == 0
    assert proposal["proposed_future_entry"]["physical_live_run_limit"] == 1


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
