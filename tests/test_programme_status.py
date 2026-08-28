from __future__ import annotations
import json
from pathlib import Path

import pytest

from host.otis_tools.programme_status import (
    NO_WRITE_BENCH_REHEARSAL,
    BOUNDED_TIGHT_DEADBAND_LIVE_LEG,
    BOUNDED_TIGHT_DEADBAND_UPPER_LIVE_LEG,
    OFFLINE_PREPARATION,
    ProgrammeExecutionBlocked,
    load_programme_status,
    require_programme_execution_allowed,
    require_programme_operation_allowed,
)


def test_tracked_status_closes_prior_work_and_selects_integrated_engineering() -> None:
    status = load_programme_status()

    assert status["active_programme"] == (
        "cx322_d9_d6_integration_engineering"
    )
    integrated = status["programmes"][status["active_programme"]]
    assert integrated["allowed_operations"] == [
        "offline_preparation",
        "cx322_d9_d6_integration_engineering_live"
    ]
    assert integrated["finite_envelope"][
        "maximum_total_automatic_applications"
    ] == 1
    assert integrated["finite_envelope"][
        "maximum_cumulative_absolute_movement_codes"
    ] == 21
    assert integrated["finite_envelope"]["absolute_wall_clock_limit_s"] == 7200
    assert integrated["serial"]["baud"] == 115200
    assert integrated["serial"]["stored_device_path_authority"] is False
    assert status["programmes"]["platform_stabilization"] == {
        "state": "completed",
        "allowed_operations": [],
        "effective_date": "2026-08-11",
        "authority": "passed_completion_gate",
    }
    successor = status["programmes"]["cx319_stabilized_tight_deadband"]
    assert successor["state"] == "completed_mapping_informed_part_b_frozen"
    assert successor["allowed_operations"] == ["historical_validation"]
    assert successor["authority"] == "completed_programme_no_live_authority"
    assert successor["next_gate"] == "cx320_bounded_active_hybrid_offline_preparation"
    cx320 = status["programmes"]["cx320_bounded_active_hybrid"]
    assert cx320["state"] == (
        "stage5_bounded_nonpass_successor_design_requires_new_authority"
    )
    assert cx320["allowed_operations"] == ["historical_validation"]
    assert cx320["physical_authority_effective"] is False
    assert cx320["exact_bundle"]["bundle_sha256"] == (
        "824860d845855a378a7ca77ff238d13be63d41c983f3ba6796a844df6dd36c54"
    )
    assert cx320["operational_rehearsal"]["rehearsal_sha256"] == (
        "51ea2a7b4eb00ea8ff4a155f9f260c1ea5e5802f676991833388490bbcf41a39"
    )
    assert cx320["stage5_attempts"][0]["setup_applications"] == 0
    assert cx320["stage5_attempts"][0]["automatic_applications"] == 0
    assert cx320["stage5_attempts"][0]["classification"] == (
        "platform_escape_into_campaign"
    )
    assert cx320["stage5_attempts"][1]["setup_requests"] == 1
    assert cx320["stage5_attempts"][1]["setup_applications"] == 0
    assert cx320["stage5_attempts"][1]["automatic_applications"] == 0
    assert cx320["stage5_attempts"][2]["setup_requests"] == 1
    assert cx320["stage5_attempts"][2]["setup_applications"] == 1
    assert cx320["stage5_attempts"][2]["automatic_applications"] == 0
    assert cx320["stage5_attempts"][2]["classification"] == (
        "platform_escape_into_campaign"
    )
    assert cx320["stage5_attempts"][3]["setup_requests"] == 1
    assert cx320["stage5_attempts"][3]["setup_applications"] == 1
    assert cx320["stage5_attempts"][3]["automatic_applications"] == 0
    assert cx320["stage5_attempts"][3]["last_confirmed_code"] == 0xA83C
    assert cx320["stage5_attempts"][3]["classification"] == (
        "firmware_defect_under_intended_stress"
    )
    assert cx320["stage5_attempts"][4]["setup_requests"] == 1
    assert cx320["stage5_attempts"][4]["setup_applications"] == 1
    assert cx320["stage5_attempts"][4]["automatic_applications"] == 0
    assert cx320["stage5_attempts"][4]["last_confirmed_code"] == 0xA83C
    assert cx320["stage5_attempts"][4]["classification"] == (
        "platform_escape_into_campaign"
    )
    assert cx320["stage5_attempts"][5]["setup_applications"] == 1
    assert cx320["stage5_attempts"][5]["automatic_applications"] == 0
    assert cx320["stage5_attempts"][5]["phase_material_requests_observed"] == 1
    assert cx320["stage5_attempts"][5]["missed_phase_material_delta_codes"] == -6
    assert cx320["stage5_attempts"][5]["classification"] == (
        "platform_escape_into_campaign"
    )
    assert cx320["stage5_attempts"][6]["automatic_applications"] == 1
    assert cx320["stage5_attempts"][6]["phase_material_applications"] == 1
    assert cx320["stage5_attempts"][6]["last_confirmed_code"] == 43062
    assert cx320["stage5_attempts"][6]["response_support_elapsed_s"] == 1499
    assert cx320["stage5_attempts"][6]["response_support_required_s"] == 1500
    assert cx320["stage5_attempts"][7]["automatic_applications"] == 0
    assert cx320["stage5_attempts"][7]["last_confirmed_code"] == 43068
    assert cx320["stage5_attempts"][7]["qualified_origin_timestamp_ticks"] == (
        38_429_602_864
    )
    assert cx320["stage5_attempts"][7]["timestamp_above_lower_bound_ticks"] == (
        13_602_864
    )
    attempt9 = cx320["stage5_attempts"][8]
    assert attempt9["automatic_applications"] == 1
    assert attempt9["phase_material_applications"] == 1
    assert attempt9["last_confirmed_code"] == 0xA836
    assert attempt9["last_confirmed_dac_epoch"] == 2
    assert attempt9["response_support_elapsed_s"] == 1500
    assert attempt9["response_class_healthy"] is True
    assert attempt9["response_predicted_sign_observed"] is False
    assert attempt9["response_checkpoint_passed"] is False
    assert attempt9["terminal"] == (
        "hybrid_response_wrong_or_frequency_not_reacquired"
    )
    assert cx320["operational_rehearsal"]["setup_authority_qualification"] == {
        "firmware_startup_inhibit_s": 600,
        "observed_historical_qualification_s": 612,
        "host_deadline_s": 660,
        "accelerated_boundary_passed": True,
        "atomic_handoff_hybrid_state": "SETUP_PENDING",
        "first_post_setup_consumer_passed": True,
    }
    assert cx320["operational_rehearsal"][
        "first_active_hybrid_wire_field_count"
    ] == 56
    assert cx320["operational_rehearsal"]["capture_parser_errors"] == 0
    assert cx320["operational_rehearsal"]["priority_abort_observed"] is True
    assert cx320["operational_rehearsal"][
        "post_abort_complete_active_snapshot"
    ] is True
    assert cx320["effective_activation"]["attempt_ordinal"] == 9
    assert cx320["effective_activation"]["automatic_retry"] is False
    assert cx320["effective_activation"]["effective"] is False
    assert cx320["effective_activation"]["consumed"] is True
    assert cx320["effective_activation"]["consumed_by_run_id"] == (
        "stage5_live_attempt9_20260820T1854Z"
    )
    assert cx320["effective_activation"]["activation_sha256"] == (
        "126b7901ab7653d96628a127aa2fa879e11b3f37bb0d566c19700db463eb18db"
    )
    cx321 = status["programmes"]["cx321_bounded_active_hybrid_successor"]
    assert cx321["state"] == "stage5_bounded_nonpass_plant_sign_not_exercised"
    assert cx321["allowed_operations"] == [OFFLINE_PREPARATION]
    assert cx321["physical_authority_effective"] is False
    assert cx321["predecessor_programme"] == "cx320_bounded_active_hybrid"
    assert cx321["plant_sign_gate"]["selected_step_codes"] == 21
    assert cx321["plant_sign_gate"]["identification_span_s"] == 1500
    assert cx321["plant_sign_gate"]["identification_floor_counts"] == 3
    assert cx321["plant_sign_gate"]["natural_hybrid_request_scaled"] is False
    assert cx321["selected_policy"]["remaining_application_count"] == 3
    assert cx321["selected_policy"]["remaining_movement_codes"] == 63
    assert cx321["selected_policy"][
        "natural_control_law_mathematics_change_from_cx320"
    ] == "none"
    assert cx321["selected_policy"][
        "identification_natural_history_separation_required"
    ] is True
    assert cx321["verification"]["firmware_implementation_pending"] is False
    assert cx321["verification"][
        "affected_current_and_release_verification_passed"
    ] is True
    assert cx321["verification"]["current_tests_passed"] == 985
    assert cx321["verification"]["supported_firmware_profiles_passed"] == 8
    assert cx321["verification"]["expected_failure_guards_passed"] == 8
    assert cx321["verification"]["complete_operational_rehearsal_pending"] is False
    assert cx321["verification"]["exact_bundle_pending"] is False
    assert cx321["exact_bundle"]["bundle_sha256"] == (
        "ee62a069fbd574b5043c0bc3fd55506d6375b03bfca9dadd981088c168161072"
    )
    assert cx321["authority_proposal"]["proposal_sha256"] == (
        "5fd21276a830c81eb032ed88cb5998093d558239d5f482ee9d9c725f11b2c567"
    )
    assert cx321["effective_activation"]["activation_sha256"] == (
        "ec73aa3da9b86a3cb4ab697afcbc6bd69954053600578526ea3981d3021672a4"
    )
    assert cx321["effective_activation"]["attempt_ordinal"] == 3
    assert cx321["effective_activation"]["effective"] is False
    assert cx321["effective_activation"]["consumed"] is True
    assert cx321["effective_activation"]["consumed_by_run_id"] == (
        "stage5_live_attempt3_20260821T1543Z"
    )
    assert cx321["stage5_attempts"][0]["capture_started"] is False
    assert cx321["stage5_attempts"][0]["setup_applications"] == 0
    assert cx321["stage5_attempts"][0]["automatic_applications"] == 0
    assert cx321["stage5_attempts"][0]["scientific_result"] == (
        "none_prewrite_no_capture_setup_dac_write_or_control_arm"
    )
    assert cx321["stage5_attempts"][1]["capture_started"] is True
    assert cx321["stage5_attempts"][1]["parser_errors"] == 0
    assert cx321["stage5_attempts"][1]["setup_applications"] == 0
    assert cx321["stage5_attempts"][1]["automatic_applications"] == 0
    assert cx321["stage5_attempts"][1]["scientific_result"] == (
        "none_prewrite_status_transport_alias_required"
    )
    assert cx321["stage5_attempts"][2]["terminal"] == (
        "plant_sign_qualification_not_exercised"
    )
    assert cx321["stage5_attempts"][2]["pre1_total_count"] == 15_000_000_003
    assert cx321["stage5_attempts"][2]["pre2_total_count"] == 15_000_000_002
    assert cx321["stage5_attempts"][2]["identification_applications"] == 0
    cx322 = status["programmes"]["cx322_bounded_hybrid_fact_gathering"]
    assert cx322["state"] == (
        "stage5_evidence_acquired_successor_decision_pending"
    )
    assert cx322["allowed_operations"] == [OFFLINE_PREPARATION]
    assert cx322["physical_authority_effective"] is False
    assert cx322["selected_policy"][
        "natural_control_law_mathematics_change_from_cx320"
    ] == "none"
    assert cx322["selected_policy"]["response_checkpoint_mode"] == (
        "observational_non_terminal"
    )
    assert cx322["verification"]["exact_firmware_build_pending"] is False
    assert cx322["verification"]["exact_bundle_pending"] is False
    assert cx322["verification"]["structural_preflight_pending"] is False
    assert cx322["verification"]["complete_operational_rehearsal_pending"] is False
    assert cx322["exact_bundle"]["bundle_sha256"] == (
        "79d064f03be1e1de1df8b3e3972a291c09aed5f2df638a69c7ca1beac39d4fcb"
    )
    assert cx322["authority_proposal"]["proposal_sha256"] == (
        "ddd6fe825e73c0ec06ee31f1b6a0146d5e334b2eb459d1ad026ec0cb52be066c"
    )
    assert cx322["structural_preflight"]["status"] == "passed"
    assert cx322["operational_rehearsal"]["status"] == "passed"
    assert cx322["operational_rehearsal"][
        "firmware_phase4_consumption_confirmed"
    ] is True
    assert cx322["operational_rehearsal"][
        "later_authority_release_observed"
    ] is True
    assert cx322["operational_rehearsal"]["physical_actions_performed"] == 0
    assert cx322["operator_authority"]["bundle_sha256"] == (
        "79d064f03be1e1de1df8b3e3972a291c09aed5f2df638a69c7ca1beac39d4fcb"
    )
    assert cx322["effective_activation"]["activation_sha256"] == (
        "62a0740605343ebabbefe640f0ef574a0bae1e0c4dfb927fe6c5ea5419b89b65"
    )
    assert cx322["effective_activation"]["attempt_ordinal"] == 7
    assert cx322["effective_activation"]["effective"] is False
    assert cx322["effective_activation"]["consumed"] is True
    assert cx322["effective_activation"]["consumed_by_run_id"] == (
        "stage5_live_attempt7_20260822T1921Z"
    )
    assert cx322["effective_activation"]["predecessor_seal_sha256"] == (
        "09e18bb1f043effb79c41951099548f22c8de616f5c96362c6dc28bbdd6e0d30"
    )
    sustained = status["programmes"]["otis_sustained_hybrid_regulation_v1"]
    assert sustained["state"] == (
        "closed_after_attempt4_physical_failure_and_scientific_rejection"
    )
    assert sustained["physical_authority_effective"] is False
    assert sustained["allowed_operations"] == ["historical_validation"]
    assert sustained["attempt2_operator_authority"]["attempt_ordinal"] == 2
    assert sustained["attempt2_operator_authority"]["physical_live_run_limit"] == 1
    assert sustained["attempt2_operator_authority"]["automatic_retry"] is False
    assert sustained["attempt3_operator_authority"]["attempt_ordinal"] == 3
    assert sustained["attempt3_operator_authority"]["physical_live_run_limit"] == 1
    assert sustained["attempt3_operator_authority"]["automatic_retry"] is False
    assert sustained["attempts"][0]["classification"] == (
        "platform_escape_into_campaign"
    )
    assert sustained["attempts"][0]["terminal_reason"] == (
        "response_identity_not_propagated_through_first_dependent_decision"
    )
    assert sustained["attempts"][0]["abort_deliveries"] == 1
    assert sustained["attempts"][0]["last_confirmed_code"] == 0xA836
    assert sustained["attempts"][1]["classification"] == (
        "firmware_defect_under_intended_setup_integration"
    )
    assert sustained["attempts"][1]["terminal_reason"] == (
        "setup_status_generation_advanced_during_current_authority_handoff"
    )
    assert sustained["attempts"][1]["setup_status_generation"] == 122
    assert sustained["attempts"][1]["core1_current_status_generation"] == 123
    assert sustained["attempts"][1]["setup_applications"] == 0
    assert sustained["attempts"][1]["qualified_origin_established"] is False
    assert sustained["attempts"][1]["abort_deliveries"] == 1
    assert sustained["selected_policy"][
        "characterization_is_an_entry_or_terminal_failure_gate"
    ] is False
    assert sustained["finite_envelope"]["maximum_automatic_applications"] == 12
    assert sustained["finite_envelope"][
        "maximum_physical_applications_including_challenge"
    ] == 13
    attempt4 = sustained["attempts"][3]
    assert attempt4["physical_qualification_passed"] is False
    assert attempt4["physical_qualification_terminal_reason"] == (
        "missing_contemporaneous_pre_phase4_response_replay_attestations"
    )
    assert attempt4["scientific_terminal"] == "prospective_low_efficiency_path"
    assert attempt4["active_hybrid_decisions"] == 52
    assert attempt4["automatic_applications"] == 11
    assert attempt4["cumulative_natural_movement_codes"] == 37
    assert attempt4["last_confirmed_code"] == 0xA835
    assert sustained["authority_consumption"]["latest_consumed_attempt"] == 4
    assert sustained["authority_consumption"]["attempt5_authorized"] is False
    study = status["programmes"][
        "otis_sustained_hybrid_successor_offline_study"
    ]
    assert study["state"] == "no_controller_successor_selected"
    assert study["allowed_operations"] == ["historical_validation"]
    assert study["physical_authority_effective"] is False
    assert set(study["authority_boundary"].values()) == {False}
    assert study["study_contract"]["contract_sha256"] == (
        "d60c26c90d7f06f4c605f2b35159209315f4c1b035dd9831f76c78e1200ea7cf"
    )
    assert study["comparison"]["report_sha256"] == (
        "d3b48818b082d9e8797c9a78316b1ae286f8bdcf5eb4ef34b66f286223717523"
    )
    assert study["comparison"]["selected_candidate_id"] is None
    assert study["successor_outputs"] == {
        "policy_created": False,
        "firmware_profile_created": False,
        "exact_bundle_created": False,
        "authority_proposal_created": False,
        "physical_rehearsal_performed": False,
        "physical_actions_performed": 0,
    }
    architecture_study = status["programmes"][
        "otis_sustained_hybrid_mode_separation_offline_study"
    ]
    assert architecture_study["state"] == (
        "no_mode_separated_architecture_selected"
    )
    assert architecture_study["allowed_operations"] == ["historical_validation"]
    assert architecture_study["physical_authority_effective"] is False
    assert set(architecture_study["authority_boundary"].values()) == {False}
    assert architecture_study["study_contract"]["contract_sha256"] == (
        "c02ce352d5224b5ed395d48d62a2ddc8a99654d08b95ad23a182186a716a37eb"
    )
    assert architecture_study["comparison"]["report_sha256"] == (
        "6b971643c106fabe0cec2c267f733ded330469ad7596125fb2dd33e57a6b9aef"
    )
    assert architecture_study["comparison"]["selected_candidate_id"] is None
    assert architecture_study["successor_outputs"] == {
        "policy_created": False,
        "firmware_profile_created": False,
        "exact_bundle_created": False,
        "authority_proposal_created": False,
        "physical_rehearsal_performed": False,
        "physical_actions_performed": 0,
    }
    equilibrium_study = status["programmes"][
        "otis_sustained_hybrid_equilibrium_estimator_feasibility_study"
    ]
    assert equilibrium_study["state"] == (
        "equilibrium_state_not_observable_targeted_characterization_required"
    )
    assert equilibrium_study["allowed_operations"] == ["historical_validation"]
    assert equilibrium_study["physical_authority_effective"] is False
    assert set(equilibrium_study["authority_boundary"].values()) == {False}
    assert equilibrium_study["study_contract"]["contract_sha256"] == (
        "ab2ec34269d0cb21b7895e459201e6d8c500ae050304d8f9f3bd5a829caed682"
    )
    assert equilibrium_study["recovery_attempt_contract"]["contract_sha256"] == (
        "534beecf00ac09087fdbb3f1c36f03660753c29d8a7d3d4ff0756aa9c3f24f80"
    )
    assert equilibrium_study["observability_report"]["report_sha256"] == (
        "dae8dcc78cd816152246e06df1886ed572e873ed2ca1fd52e38c91f80228b21b"
    )
    assert equilibrium_study["observability_report"][
        "equilibrium_interval_computed"
    ] is True
    assert equilibrium_study["observability_report"]["eligible_model_count"] == 0
    assert equilibrium_study["observability_report"][
        "first_discriminating_failure"
    ]["failure_id"] == "identification_complete_feasible_set_nonempty"
    assert equilibrium_study["initial_invalid_attempt"]["preserved"] is True
    assert equilibrium_study["initial_invalid_attempt"]["report_sha256"] == (
        "b98bf927170c0f8f868007cf5aa497898d3d7c65a57583b30c299dacd64547c3"
    )
    assert equilibrium_study["next_step_requirements"]["document_count"] == 1
    assert equilibrium_study["next_step_requirements"]["effective"] is False
    assert equilibrium_study["study_outputs"] == {
        "equilibrium_estimator_selected": False,
        "trajectory_study_authorized": False,
        "policy_created": False,
        "firmware_profile_created": False,
        "exact_bundle_created": False,
        "authority_proposal_created": False,
        "physical_rehearsal_performed": False,
        "physical_actions_performed": 0,
    }
    targeted = status["programmes"]["otis_targeted_equilibrium_characterization_v1"]
    assert targeted["state"] == (
        "attempt6_complete_equilibrium_state_not_observable_closed"
    )
    assert targeted["physical_authority_effective"] is False
    assert targeted["exact_bundle"]["bundle_sha256"] == (
        "4d69a99cbd0483241035912974dca2476283dadf553f4a92df70d1be2ca69343"
    )
    assert targeted["attempt1"]["completed_dwells"] == 0
    assert targeted["attempt1"]["dac_stimuli"] == 0
    assert targeted["attempt1"]["priority_abort_deliveries"] == 1
    assert targeted["gnss_baud_transition_qualification"]["status"] == "passed"
    assert targeted["gnss_baud_transition_qualification"][
        "special_gate_required_for_unchanged_future_runs"
    ] is False
    assert targeted["gnss_output_configuration_qualification"]["status"] == "passed"
    assert targeted["authority_consumption"]["consumed"] is True
    assert targeted["authority_consumption"]["second_live_attempt_authorized"] is True
    assert targeted["authority_consumption"]["second_live_attempt_consumed"] is True
    assert targeted["authority_consumption"]["third_live_attempt_authorized"] is True
    assert targeted["authority_consumption"]["third_live_attempt_consumed"] is True
    assert targeted["authority_consumption"]["fourth_live_attempt_authorized"] is True
    assert targeted["authority_consumption"]["fourth_live_attempt_consumed"] is True
    assert targeted["authority_consumption"]["fifth_live_attempt_authorized"] is True
    assert targeted["authority_consumption"]["fifth_live_attempt_consumed"] is True
    assert targeted["authority_consumption"]["sixth_live_attempt_authorized"] is True
    assert targeted["authority_consumption"]["sixth_live_attempt_consumed"] is True
    assert targeted["attempt2_operator_authority"][
        "reuses_attempt1_baud_transition_qualification"
    ] is True
    assert targeted["attempt2"]["completed_dwells"] == 0
    assert targeted["attempt2"]["dac_stimuli"] == 0
    assert targeted["attempt2"]["pmtk514_field_count"] == 22
    assert targeted["attempt2"]["last_identity_response_baud"] == 115200
    assert targeted["attempt2"]["priority_abort_deliveries"] == 1
    assert targeted["attempt3"]["prewrite_gate_passed"] is True
    assert targeted["attempt3"]["completed_dwells"] == 0
    assert targeted["attempt3"]["dac_stimuli"] == 0
    assert targeted["attempt3"]["classification"] == "platform_escape_into_campaign"
    assert targeted["attempt4"]["classification"] == "platform_escape_into_campaign"
    assert targeted["attempt4"]["first_dwell_minimum_duration_acquired"] is True
    assert targeted["attempt4"]["completed_dwells_under_frozen_predicate"] == 0
    assert targeted["attempt4"]["dac_stimuli"] == 1
    assert targeted["attempt4"]["post_application_metadata_dequalification_count"] == 18
    assert [
        row["integer_edge_error_counts"]
        for row in targeted["attempt4"]["raw_d14_d8_support_windows"]
    ] == [3, 2, 1]
    assert targeted["attempt5"]["classification"] == "platform_escape_into_campaign"
    assert targeted["attempt5"]["prewrite_gate_passed"] is False
    assert targeted["attempt5"]["completed_dwells"] == 0
    assert targeted["attempt5"]["dac_stimuli"] == 0
    assert targeted["attempt5"]["last_identity_response_baud"] == 115200
    assert targeted["attempt5"]["requested_target_baud"] == 9600
    assert targeted["attempt5"]["priority_abort_deliveries"] == 1
    assert targeted["attempt6"]["classification"] == "completed_campaign"
    assert targeted["attempt6"]["terminal"] == "healthy_stop"
    assert targeted["attempt6"]["scientific_terminal"] == (
        "equilibrium_state_not_observable"
    )
    assert targeted["attempt6"]["completed_dwells"] == 12
    assert targeted["attempt6"]["identification_supports"] == 21
    assert targeted["attempt6"]["held_out_supports"] == 15
    assert targeted["attempt6"]["eligible_model_count"] == 0
    assert targeted["attempt6"]["confirmed_baud"] == 9600
    assert targeted["attempt6"]["last_identity_response_baud"] == 9600
    assert targeted["attempt6"]["parser_errors"] == 0
    assert targeted["attempt6"]["reconnects"] == 0
    assert targeted["attempt6_exact_bundle"]["bundle_sha256"] == (
        "8a1e06d438ca05c5caca8869ea3e5c8b2566b1d394523fd0edcc4436834d9b1a"
    )
    assert targeted["attempt6_exact_bundle"]["firmware_elf_sha256"] == (
        "f91b3955542f6a9d16200d74edd64cafdfc780dc6fdc8792a4907cafebba4d05"
    )
    assert targeted["verification"]["attempt6_physical_acquisition_complete"] is True
    assert targeted["verification"]["attempt6_evidence_registration_passed"] is True
    adaptive = targeted["successor_architecture_decision"]
    assert adaptive["status"] == "adaptive_fll_pll_selected_offline_contract_pending"
    assert adaptive["durable_equilibrium_code_required"] is False
    assert adaptive["future_drift_prediction_required"] is False
    assert adaptive["independent_competing_loops_allowed"] is False
    assert adaptive["future_estimator_authority"] == "zero_until_separately_promoted"
    assert adaptive["future_estimator_failure_effect"] == "estimator_local_only"
    assert adaptive["future_estimator_may_invalidate_canonical_evidence"] is False
    assert adaptive["future_estimator_may_inhibit_reactive_baseline"] is False
    assert adaptive["future_estimator_may_change_physical_terminal"] is False
    assert adaptive["existing_bounded_fll_qualification_reused"] is True
    assert adaptive["existing_coherent_fll_pll_integration_evidence_reused"] is True
    assert adaptive["cx322_positive_combined_control_evidence_reused"] is True
    assert adaptive["existing_selected_frequency_estimator_reused"] is True
    assert adaptive["existing_relative_phase_estimator_reused"] is True
    assert adaptive["existing_active_hybrid_engine_and_transaction_path_reused"] is True
    assert adaptive["existing_replay_and_operational_platform_reused"] is True
    assert adaptive["unchanged_fll_fll_pll_requalification_required"] is False
    assert adaptive["new_general_characterization_required"] is False
    assert adaptive["remaining_work_class"] == (
        "minimal_sustained_operation_policy_delta_then_use"
    )
    assert adaptive["d10_current_steering_profile_claimed"] is False
    assert adaptive["gnss_serial_metadata_transient_disposition"] == (
        "bounded_static_control_hold_not_run_failure"
    )
    assert adaptive[
        "gnss_metadata_hold_preserves_D14_D8_capture_and_canonical_history"
    ] is True
    assert adaptive[
        "gnss_metadata_recovery_requires_fresh_causal_requalification"
    ] is True
    assert adaptive["physical_authority_created"] is False
    assert adaptive["firmware_profile_created"] is False
    assert adaptive["exact_bundle_created"] is False
    assert adaptive["automatic_successor_created"] is False
    assert targeted["verification"]["post_attempt5_affected_profile_build_passed"] is True
    assert targeted["verification"]["post_attempt5_compiled_elf_target_command"] == (
        "$PMTK251,9600*17"
    )
    assert targeted["verification"][
        "post_attempt4_profile_boundary_and_campaign_tests_passed"
    ] == 45
    assert targeted["verification"]["post_attempt4_affected_profile_build_passed"] is True
    assert targeted["verification"]["post_attempt4_release_verification_pending"] is False
    assert targeted["verification"]["post_attempt4_release_host_native_tests_passed"] == 1076
    assert targeted["verification"]["post_attempt4_release_supported_profiles_passed"] == 10
    assert targeted["verification"][
        "post_attempt4_release_expected_failure_guards_passed"
    ] == 8
    assert targeted["verification"][
        "post_attempt2_release_verification_pending"
    ] is False
    assert targeted["verification"][
        "post_attempt2_release_host_native_tests_passed"
    ] == 1073
    assert cx322["stage5_attempts"][0]["setup_applications"] == 1
    assert cx322["stage5_attempts"][0]["automatic_applications"] == 0
    assert cx322["stage5_attempts"][0]["qualified_origin_established"] is False
    assert cx322["stage5_attempts"][0]["offline_finalization_recovered_without_physical_io"] is True
    assert cx322["stage5_attempts"][1]["selected_estimate_boundaries"] == 1
    assert cx322["stage5_attempts"][1]["active_hybrid_decisions_recorded"] == 0
    assert cx322["stage5_attempts"][1]["automatic_applications"] == 0
    assert cx322["stage5_attempts"][1]["qualified_origin_established"] is False
    assert cx322["stage5_attempts"][2]["automatic_applications"] == 1
    assert cx322["stage5_attempts"][2]["last_observed_applied_code"] == 43063
    assert cx322["stage5_attempts"][2]["qualified_origin_established"] is True
    assert cx322["stage5_attempts"][2]["frequency_only_applications"] == 1
    assert cx322["stage5_attempts"][2]["phase_nonzero_applications"] == 1
    assert cx322["stage5_attempts"][2]["phase_material_applications"] == 0
    assert cx322["stage5_attempts"][3]["completed_response_observations"] == 1
    assert cx322["stage5_attempts"][3]["response_class"] == (
        "healthy_indeterminate_near_resolution"
    )
    assert cx322["stage5_attempts"][3]["observed_response_hz"] == 0.0
    assert cx322["stage5_attempts"][3]["acquisition_gate_passed"] is True
    assert cx322["stage5_attempts"][4]["automatic_applications"] == 1
    assert cx322["stage5_attempts"][4]["last_observed_applied_code"] == 43062
    assert cx322["stage5_attempts"][4]["phase_material_applications"] == 1
    assert cx322["stage5_attempts"][4]["exact_timer_replay_after_host_repair"] is True
    assert cx322["stage5_attempts"][5]["second_application_released"] is False
    assert cx322["stage5_attempts"][5]["predicted_direction_observed"] is True
    attempt7 = cx322["stage5_attempts"][6]
    assert attempt7["terminal"] == "bounded_direct_hybrid_evidence_acquired"
    assert attempt7["qualified_endpoint_complete"] is True
    assert attempt7["automatic_applications"] == 4
    assert attempt7["phase_material_applications"] == 4
    assert attempt7["cumulative_movement_codes"] == 14
    assert attempt7["application_budget_exhausted"] is True
    assert attempt7["terminal_relative_phase_cycles"] == -26
    assert attempt7["terminal_request_held_by_global_application_budget"] is True
    assert attempt7["acquisition_gate_passed"] is True
    assert attempt7["offline_finalization_gate_passed"] is True
    assert attempt7["evidence_registration_valid"] is True
    assert cx322["next_gate"] == "offline_successor_design_decision"
    range_authority = successor["range_spanning_operator_authority"]
    assert range_authority["requires_exact_bundle_before_physical_action"] is True
    assert range_authority[
        "further_interactive_approval_required_after_exact_bundle"
    ] is False
    assert range_authority["phase_or_hybrid_actuation"] is False
    assert range_authority["part_b_requires_complete_part_a_result"] is True
    range_result = successor["range_spanning_part_a_survey_prefix_result"]
    assert range_result["status"] == "passed_survey_prefix"
    assert range_result["completed_point_count"] == 8
    assert range_result["last_confirmed_applied_code"] == 0xA844
    assert range_result["last_confirmed_band_state"] == "TIGHT_INSIDE"
    assert range_result["lower_increasing_entry_coarse_bracket"] == [
        0xA800,
        0xA820,
    ]
    assert range_result["automatic_transactions"] == 0
    assert range_result["phase_or_hybrid_actuation"] is False
    assert range_result["part_a_complete"] is False
    assert range_result["part_b_executable"] is False
    complete_survey = successor["range_spanning_part_a_complete_survey_result"]
    assert complete_survey["status"] == (
        "passed_complete_survey_requires_fine_pass"
    )
    assert complete_survey["completed_point_count"] == 30
    assert complete_survey["final_applied_code"] == 0xA800
    assert complete_survey["final_band_state"] == "OUTSIDE"
    assert complete_survey["lower_increasing_entry_coarse_bracket"] == [
        0xA800,
        0xA820,
    ]
    assert complete_survey["upper_increasing_release_bracket"] == [
        0xA848,
        0xA84C,
    ]
    assert complete_survey["upper_decreasing_entry_bracket"] == [
        0xA844,
        0xA848,
    ]
    assert complete_survey["lower_decreasing_release_bracket"] == [
        0xA818,
        0xA81C,
    ]
    assert complete_survey["hybrid_preview"] == {
        "status": "candidate_requires_revision",
        "candidate_id": "p21600_cap1_v2",
        "terminal_reason": "prospective_low_net_excess_path",
        "first_fault_preview_sequence": 40519,
        "first_fault_dac_epoch": 15,
        "modeled_corrections": 20,
        "cumulative_movement_codes": 236,
        "rejected_proposed_delta_codes": -15,
        "actionable": False,
        "actuation_authorized": False,
    }
    assert complete_survey["automatic_transactions"] == 0
    assert complete_survey["phase_or_hybrid_actuation"] is False
    assert complete_survey["survey_complete"] is True
    assert complete_survey["part_a_complete"] is False
    assert complete_survey["part_b_executable"] is False
    assert complete_survey["physical_rerun_for_reanalysis"] is False
    focused = successor["current_session_rebinding_focused_no_write_authority"]
    assert focused["operator_instruction"] == "authorized"
    assert focused["effective"] is False
    assert focused["consumed"] is True
    assert focused["consumed_by_run_id"] == (
        "focused_session_rebinding_20260813T085754Z"
    )
    assert focused["programme_operation"] == NO_WRITE_BENCH_REHEARSAL
    assert focused["exact_firmware_flash_limit"] == 1
    assert focused["physical_no_write_attempt_limit"] == 1
    assert focused["post_capture_observation_limit_s"] == 120
    assert focused["q2_repeat_authorized"] is False
    assert focused["q3_repeat_authorized"] is False
    assert focused["live_authority"] is False
    assert {
        focused["dac_value_writes"],
        focused["setup_stimuli"],
        focused["control_arms"],
        focused["automatic_corrections"],
    } == {0}
    nonpass = successor["current_session_rebinding_focused_no_write_nonpass"]
    assert nonpass["failure_class"] == (
        "platform_escape_into_focused_physical_qualification"
    )
    assert nonpass["firmware_flash_passed"] is True
    assert nonpass["exact_installed_firmware_confirmed"] is True
    assert nonpass["snapshot_commands_sent"] == 395
    assert nonpass["snapshot_generations_begun"] == 403
    assert nonpass["snapshot_generations_complete"] == 394
    assert nonpass["observed_states"] == ["DISARMED"]
    assert nonpass["observed_reasons"] == ["initialized_disarmed"]
    assert nonpass["observed_fail_static"] == [False]
    assert nonpass["observed_sessions"] == [1]
    assert nonpass["telemetry_dropped_final"] == 48
    assert nonpass["live_authority"] is False
    readiness = successor["current_session_absence_no_flash_offline_readiness"]
    assert readiness["outcome"] == (
        "offline_ready_for_separate_no_flash_authority_decision"
    )
    assert readiness["firmware_flashes_proposed"] == 0
    assert readiness["manual_resets_proposed"] == 1
    assert readiness["snapshot_query_count"] == 3
    assert readiness["minimum_snapshot_cadence_s"] == 5
    assert readiness["post_attach_deadline_s"] == 30
    assert readiness["q2_q3_repeated"] is False
    assert readiness["physical_authority_effective"] is False
    assert readiness["live_authority_effective"] is False
    authority = successor[
        "current_session_absence_no_flash_low_cadence_authority"
    ]
    assert authority["operator_instruction"] == (
        "I authorize the no-flash low-cadence proposal and I am at the bench"
    )
    assert authority["physical_presence_confirmed"] is True
    assert authority["effective"] is False
    assert authority["consumed"] is True
    assert authority["consumed_by_attempt_id"] == (
        "session_absence_no_flash_low_cadence_20260813T091617Z"
    )
    assert authority["terminal_reason"] == (
        "operator_reset_after_observer_wait_timeout_before_capture"
    )
    assert authority["programme_operation"] == NO_WRITE_BENCH_REHEARSAL
    assert authority["firmware_flash_limit"] == 0
    assert authority["manual_reset_button_limit"] == 1
    assert authority["physical_no_write_attempt_limit"] == 1
    assert authority["snapshot_query_count"] == 3
    assert authority["minimum_snapshot_cadence_s"] == 5
    assert authority["post_attach_deadline_s"] == 30
    assert authority["q2_repeat_authorized"] is False
    assert authority["q3_repeat_authorized"] is False
    assert authority["live_authority"] is False
    assert {
        authority["dac_value_writes"],
        authority["setup_stimuli"],
        authority["control_arms"],
        authority["automatic_corrections"],
    } == {0}
    retry = successor[
        "current_session_absence_no_flash_low_cadence_retry_authority"
    ]
    assert retry["operator_instruction"] == (
        "you are authorized to continue with flashing the board, etc."
    )
    assert retry["physical_presence_confirmed"] is True
    assert retry["effective"] is False
    assert retry["consumed"] is False
    assert retry["superseded_by"] == "q4_unattended_phase_authority"
    assert retry["programme_operation"] == NO_WRITE_BENCH_REHEARSAL
    assert retry["firmware_flash_limit"] == 0
    assert retry["manual_reset_button_limit"] == 1
    assert retry["physical_no_write_attempt_limit"] == 1
    assert retry["operator_wait_liveness_bound_s"] == 7200
    assert retry["snapshot_query_count"] == 3
    assert retry["minimum_snapshot_cadence_s"] == 5
    assert retry["post_attach_deadline_s"] == 30
    assert retry["q2_repeat_authorized"] is False
    assert retry["q3_repeat_authorized"] is False
    assert retry["live_authority"] is False
    assert {
        retry["dac_value_writes"],
        retry["setup_stimuli"],
        retry["control_arms"],
        retry["automatic_corrections"],
    } == {0}
    unattended = successor["q4_unattended_phase_authority"]
    assert unattended["effective"] is False
    assert unattended["completed"] is True
    assert unattended["completed_by_run_id"] == (
        "g3_upper_live_20260813T173645Z/live_leg_b"
    )
    assert unattended["unattended"] is True
    assert unattended["physical_presence_or_timely_reply_required"] is False
    assert unattended["q4_phase_fully_authorized"] is True
    assert unattended["exact_firmware_flash_for_entry_or_recovery"] is True
    assert unattended["board_reset_for_entry_or_timeout_recovery"] is True
    assert unattended["no_write_physical_qualification"] is True
    assert unattended["fresh_q4_candidate_preparation"] is True
    assert unattended[
        "bounded_q4_lower_live_execution_after_passing_candidate_gate"
    ] is True
    assert unattended["reuse_unchanged_q2_q3"] is True
    assert unattended["finite_recovery_only"] is True
    assert unattended["preserve_failed_attempts"] is True
    assert unattended["minimum_code"] == 0xA800
    assert unattended["maximum_code"] == 0xAB00
    assert unattended["phase_or_hybrid_actionable"] is False
    assert unattended["g4_authorized"] is False
    superseded_pass = successor[
        "superseded_current_session_absence_exact_flash_qualification_pass"
    ]
    assert superseded_pass["run_id"] == (
        "session_absence_exact_flash_low_cadence_20260813T092834Z"
    )
    stop = successor["q4_current_image_asl_formatter_prewrite_stop"]
    assert stop["failure_class"] == (
        "firmware_defect_under_intended_prewrite_stress"
    )
    assert stop["repair_commit"] == (
        "21e8cf9de247ab53bad097c37dba3b12702dc5b4"
    )
    assert stop["malformed_utf8"] == 1
    assert stop["scientific_result"] is False
    assert {
        stop["setup_stimuli"],
        stop["dac_value_writes"],
        stop["control_arms"],
        stop["automatic_corrections"],
    } == {0}
    current_pass = successor[
        "current_session_absence_exact_flash_qualification_pass"
    ]
    assert current_pass["status"] == "passed"
    assert current_pass["run_id"] == (
        "asl_formatter_exact_flash_qualification_20260813T094505Z"
    )
    assert current_pass["uf2_sha256"] == (
        "1f3563c244b3da47ea9d477b685e8edd"
        "91e13659cc3c33e6f0c1404fd1879d11"
    )
    assert current_pass["firmware_flashes"] == 1
    assert current_pass["snapshot_queries"] == 3
    assert current_pass["snapshot_send_cadence_s"] == [5.002208, 5.000738]
    assert current_pass["observed_states"] == ["DISARMED"]
    assert current_pass["observed_reasons"] == ["initialized_disarmed"]
    assert current_pass["observed_fail_static"] == [False]
    assert current_pass["observed_sessions"] == [1]
    assert current_pass["telemetry_dropped_observations"] == [0, 0]
    assert current_pass["association_loss_rows"] == 0
    assert current_pass["asl_formatter_source_contract_regression_tests"] == 23
    assert current_pass["q2_q3_reused"] is True
    assert current_pass["q4_live_result"] is False
    assert {
        current_pass["serial_reconnects"],
        current_pass["serial_malformed_utf8"],
        current_pass["serial_parser_errors"],
        current_pass["active_transaction_rows"],
        current_pass["dac_step_rows"],
        current_pass["setup_stimuli"],
        current_pass["dac_value_writes"],
        current_pass["control_arms"],
        current_pass["automatic_corrections"],
    } == {0}
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
        "effective": False,
        "consumed": True,
        "consumed_by_activation_sha256": (
            "73eb4dac26ecf9be89dcd2af67efd330"
            "d336e5376e6f4dcfbd593bb79114d15d"
        ),
        "consumed_by_restart_observation_sha256": (
            "349ad8e0a47cf27a5aa1116d4a503073"
            "78f33d29acf9cc146ddccbd5f72f201d"
        ),
        "consumed_by_run_id": "live_leg_a_manual_restart_20260813T083106Z",
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
    assert successor["q4_lower_manual_restart_prewrite_stop"] == {
        "record": (
            "docs/60_EXPERIMENTS/"
            "CX319_STABILIZED_TIGHT_DEADBAND_PROGRAMME/"
            "26_Q4_LOWER_SIDE_MANUAL_RESTART_PREWRITE_STOP.md"
        ),
        "run_id": "live_leg_a_manual_restart_20260813T083106Z",
        "activation_sha256": (
            "73eb4dac26ecf9be89dcd2af67efd330"
            "d336e5376e6f4dcfbd593bb79114d15d"
        ),
        "activation_file_sha256": (
            "fa4366b659f45f3f42a00f5ea70cd4fc"
            "95ba8d39c916886258be71f9a8cd860f"
        ),
        "restart_observation_sha256": (
            "349ad8e0a47cf27a5aa1116d4a503073"
            "78f33d29acf9cc146ddccbd5f72f201d"
        ),
        "run_manifest_sha256": (
            "5d54612b7468f9fd9e9428a5cabc6c92"
            "203dc5a1fc86def066f08eac4f9da0fb"
        ),
        "terminal_reason": (
            "cx319_g2_supervisor_fault:active live-health snapshot did not "
            "complete within 2.000 s: generation=2"
        ),
        "evidence_content_sha256": (
            "38002306a1f6885105502da78ab91fb4"
            "2063b2def384a2cf9accae98c749e3bb"
        ),
        "observed_incomplete_generation_state": "FAULT",
        "observed_incomplete_generation_reason": "session_change_clears_arming",
        "observed_incomplete_generation_fail_static": True,
        "host_snapshot_completion_timeout_old_s": 2,
        "host_snapshot_completion_timeout_new_s": 30,
        "setup_stimuli": 0,
        "dac_value_writes": 0,
        "control_arms": 0,
        "automatic_corrections": 0,
        "scientific_result": False,
        "failure_class": "platform_escape_masking_firmware_entry_stop",
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
        "g3_authority_consumed": True,
        "g3_consumed_by_run_id": "g3_upper_live_20260813T173645Z/live_leg_b",
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
        "g3_live_execution": False,
        "consumed": True,
        "consumed_by_run_id": "g3_upper_live_20260813T173645Z/live_leg_b",
        "existing_bounded_envelope": True,
        "manual_reset_expected_after_successful_upload": False,
        "operator_assistance_required_if_upload_or_reenumeration_fails": True,
        "proposal_bundle_sha256": (
            "1db8416d1d2577b07c954a9bfb339fa6"
            "eda48559ff14d32f4dd540656e919b02"
        ),
        "proposal_file_sha256": (
            "c24c53931803898b8fca09831c7578d7"
            "fd5f815e12008a3da3064d8b4f94e40e"
        ),
        "preflight_file_sha256": (
            "89103a7ee8c78918c8789e23c3171589"
            "9d245d0606483d3aaf07f598f187465c"
        ),
        "operational_rehearsal_content_sha256": (
            "a39b2d8e4d9505613d6cd376babc9d81"
            "cb2ceb90c57d2d259da44dda1c84c3ad"
        ),
        "operational_rehearsal_seal_sha256": (
            "ae3c15131169ab27db31611d3f5d5f36"
            "1682a43cd1005fd94c6ea12048790461"
        ),
        "upper_build_manifest_sha256": (
            "307f321da6b5ad5f5fef9f4e2ce31bc5"
            "1948fbc5db41d2eb0c0fea6b925acb27"
        ),
        "upper_uf2_sha256": (
            "0fb15bc7b5b4f63d174aabaffcefc27b"
            "d096d4cdc76723863b1f712d7628edb4"
        ),
    }
    upper = successor["q4_g3_upper_physical_qualification_result"]
    assert upper["status"] == (
        "scientific_bounded_nonpass_with_terminal_platform_escape"
    )
    assert upper["selected_estimate_count"] == 25
    assert upper["selected_error_counts_minimum"] == 1
    assert upper["selected_error_counts_maximum"] == 3
    assert upper["selected_error_counts_mean"] == 1.96
    assert upper["automatic_corrections"] == 0
    assert upper["scientific_outcome"] == (
        "stimulus_nonactionable_stable_tight_hold"
    )
    assert upper["platform_failure_class"] == (
        "terminal_abort_delivery_race_after_scientific_bounded_nonpass"
    )
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
        "unbounded_or_unrecorded_retry",
        "automatic_restore",
        "duration_extension",
        "consumed_g3_live_authority_reuse",
        "range_spanning_continuation_without_exact_state_preserving_bundle_and_rehearsal",
        "phase_or_hybrid_actuation",
        "g4_progression",
    ]
    with pytest.raises(ProgrammeExecutionBlocked, match="operational_execution"):
        require_programme_execution_allowed("platform_stabilization")

    with pytest.raises(ProgrammeExecutionBlocked, match="is blocked"):
        require_programme_operation_allowed(
            "cx322_bounded_hybrid_fact_gathering",
            "cx322_stage5_bounded_hybrid_fact_gathering_live",
        )
    with pytest.raises(ProgrammeExecutionBlocked, match="is blocked"):
        require_programme_operation_allowed(
            "cx322_bounded_hybrid_fact_gathering", OFFLINE_PREPARATION
        )
    with pytest.raises(ProgrammeExecutionBlocked, match="is blocked"):
        require_programme_operation_allowed(
            "otis_sustained_hybrid_regulation_v1", OFFLINE_PREPARATION
        )
    with pytest.raises(ProgrammeExecutionBlocked, match="is blocked"):
        require_programme_operation_allowed(
            "otis_sustained_hybrid_regulation_v1",
            "otis_sustained_hybrid_regulation_live",
        )
    with pytest.raises(ProgrammeExecutionBlocked, match="is blocked"):
        require_programme_operation_allowed(
            "otis_sustained_hybrid_successor_offline_study", OFFLINE_PREPARATION
        )
    with pytest.raises(ProgrammeExecutionBlocked, match="is blocked"):
        require_programme_operation_allowed(
            "otis_sustained_hybrid_mode_separation_offline_study",
            OFFLINE_PREPARATION,
        )
    with pytest.raises(ProgrammeExecutionBlocked, match="is blocked"):
        require_programme_operation_allowed(
            "otis_sustained_hybrid_equilibrium_estimator_feasibility_study",
            OFFLINE_PREPARATION,
        )
    with pytest.raises(ProgrammeExecutionBlocked, match="is blocked"):
        require_programme_operation_allowed(
            "cx321_bounded_active_hybrid_successor", OFFLINE_PREPARATION
        )
    with pytest.raises(ProgrammeExecutionBlocked, match="is blocked"):
        require_programme_operation_allowed(
            "cx321_bounded_active_hybrid_successor",
            "cx321_stage5_bounded_active_hybrid_live",
        )
    with pytest.raises(ProgrammeExecutionBlocked, match="is blocked"):
        require_programme_operation_allowed(
            "cx320_bounded_active_hybrid",
            "cx320_stage5_bounded_active_hybrid_live",
        )
    with pytest.raises(ProgrammeExecutionBlocked, match="is blocked"):
        require_programme_operation_allowed(
            "cx320_bounded_active_hybrid", OFFLINE_PREPARATION
        )
    for blocked_operation in (
        OFFLINE_PREPARATION,
        NO_WRITE_BENCH_REHEARSAL,
        BOUNDED_TIGHT_DEADBAND_LIVE_LEG,
        BOUNDED_TIGHT_DEADBAND_UPPER_LIVE_LEG,
    ):
        with pytest.raises(ProgrammeExecutionBlocked, match="is blocked"):
            require_programme_operation_allowed(
                "cx319_stabilized_tight_deadband",
                blocked_operation,
            )
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


def test_session_absence_no_flash_proposal_is_narrow_and_non_effective() -> None:
    root = Path(__file__).resolve().parents[1]
    proposal = json.loads(
        (
            root
            / "profiles/qualification/"
            "cx319_current_session_absence_no_flash_authority_proposal_v1.json"
        ).read_text(encoding="utf-8")
    )

    assert proposal["effective"] is False
    assert proposal["operator_authority_required"] is True
    assert proposal["firmware_flash_limit"] == 0
    assert proposal["manual_reset_button_limit"] == 1
    assert proposal["snapshot_query_count"] == 3
    assert proposal["minimum_snapshot_cadence_s"] == 5
    assert proposal["post_attach_deadline_s"] == 30
    assert proposal["q2_repeat_authorized"] is False
    assert proposal["q3_repeat_authorized"] is False
    assert proposal["live_authority"] is False
    assert {
        proposal["dac_value_writes"],
        proposal["setup_stimuli"],
        proposal["control_arms"],
        proposal["automatic_corrections"],
    } == {0}


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
