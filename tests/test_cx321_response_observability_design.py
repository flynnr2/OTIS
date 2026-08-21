from __future__ import annotations

from hashlib import sha256
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
GATE_PATH = (
    ROOT / "profiles/qualification/cx321_bounded_response_observability_v1.json"
)
POLICY_PATH = (
    ROOT / "profiles/discipline/cx321_bounded_active_hybrid_plant_sign_v1.json"
)


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def test_cx321_design_binds_unchanged_measurement_evidence() -> None:
    gate = _load(GATE_PATH)
    policy = _load(POLICY_PATH)

    for document in (gate, policy):
        bindings = document["bindings"]
        for binding in bindings.values():
            if not isinstance(binding, dict) or "path" not in binding:
                continue
            path = ROOT / binding["path"]
            assert path.is_file()
            assert binding["sha256"] == _sha256(path)

    retained = gate["retained_measurement_contract"]
    assert retained["authoritative_span_s"] == 600
    assert retained["settling_exclusion_s"] == 900
    assert retained["response_evidence_complete_s"] == 1500
    assert retained["response_evidence_ack_deadline_s"] == 30
    assert retained["confirmation_evidence_complete_s"] == 2100
    assert retained["response_transaction_estimate_count"] == 1
    assert retained["confirmation_output_changes_response_statistic"] is False
    assert retained["new_or_aggregated_estimator"] is False
    assert retained["diagnostic_trajectory_decision_authority"] is False


def test_twenty_one_codes_is_the_first_bounded_detectable_step() -> None:
    gate = _load(GATE_PATH)
    retained = gate["retained_measurement_contract"]
    derivation = gate["response_observability_derivation"]
    gains = derivation["plant_gain_hz_per_code"]
    floor = retained["empirical_detection_floor_hz"]
    minimum_gain = gains["minimum"]

    unrounded = floor / minimum_gain
    assert math.isclose(
        derivation["unrounded_minimum_detectable_step_codes"],
        unrounded,
        rel_tol=0.0,
        abs_tol=1e-15,
    )
    assert math.ceil(unrounded) == 21
    assert 20 * minimum_gain < floor
    assert 21 * minimum_gain >= floor
    assert math.isclose(
        derivation["twenty_code_expected_response_minimum_hz"],
        20 * minimum_gain,
        rel_tol=0.0,
        abs_tol=1e-18,
    )
    assert math.isclose(
        derivation["twenty_one_code_expected_response_hz"]["minimum"],
        21 * minimum_gain,
        rel_tol=0.0,
        abs_tol=1e-18,
    )
    assert derivation["cx320_six_code_expected_response_hz"]["maximum"] < floor


def test_identification_stimulus_is_bounded_and_moves_toward_nominal() -> None:
    gate = _load(GATE_PATH)
    stimulus = gate["stimulus"]
    setup = gate["setup"]
    setup_code = setup["exact_start_code"]
    minimum_code = stimulus["minimum_code"]
    maximum_code = stimulus["maximum_code"]

    assert setup["pre_identification_automatic_applications_allowed"] == 0
    assert setup["current_code_must_remain_exact_start_code_until_stimulus"]

    negative = stimulus["negative_direction_transition"]
    positive = stimulus["positive_direction_transition"]
    assert negative["requested_delta_codes"] == -21
    assert negative["requested_code"] == setup_code - 21 == 0xA827
    assert negative["distance_from_nearest_range_endpoint_codes"] == min(
        negative["requested_code"] - minimum_code,
        maximum_code - negative["requested_code"],
    ) == 39
    assert positive["requested_delta_codes"] == 21
    assert positive["requested_code"] == setup_code + 21 == 0xA851
    assert positive["distance_from_nearest_range_endpoint_codes"] == min(
        positive["requested_code"] - minimum_code,
        maximum_code - positive["requested_code"],
    ) == 81

    predicted = gate["predicted_post_stimulus_frequency_error_hz"]
    tight_entry_hz = 2.0 / 600.0
    assert predicted["maximum_absolute_hz"] < tight_entry_hz
    assert predicted["inside_two_count_tight_entry_bound"] is True


def test_identification_gate_preserves_controller_and_global_budgets() -> None:
    gate = _load(GATE_PATH)
    policy = _load(POLICY_PATH)
    controller = policy["natural_hybrid_controller"]
    limits = policy["global_authority_limits"]
    timing = gate["finite_timing"]
    response_gate = gate["response_observability_gate"]

    assert controller["semantic_change_from_cx320"] == "none"
    assert controller[
        "identification_stimulus_never_enters_controller_demand_or_counterfactual_materiality"
    ] is True
    assert gate["stimulus"]["counts_as_phase_material_application"] is False
    assert limits["plant_sign_identification_consumes_application_count"] == 1
    assert limits["plant_sign_identification_consumes_movement_codes"] == 21
    assert limits["pre_identification_automatic_applications_allowed"] == 0
    assert limits["identification_requires_current_code_exact_setup"] is True
    assert limits["maximum_applications_remaining_after_identification"] == 3
    assert limits["maximum_movement_remaining_after_identification_codes"] == 63
    assert limits["minimum_natural_phase_material_applications"] == 2
    assert response_gate["response_evidence_ack"] == {
        "deadline_s_after_firmware_response": 30,
        "acknowledges_exact_first_response_and_host_replay": True,
        "acknowledgement_releases_phase_authority": False,
        "state_after_accepted_ack": "PLANT_SIGN_CONFIRM",
        "missing_late_or_inexact_ack": "fail_static",
    }
    assert response_gate["post_ack_confirmation"][
        "changes_observed_response_or_classifier_result"
    ] is False
    assert timing == {
        "clock_domain": "rp2040_timer0",
        "origin_precision": "exact_recorded_device_ticks_no_host_second_rounding",
        "setup_settling_exclusion_s": 900,
        "first_pre_stimulus_selected_estimate_complete_s": 1500,
        "second_pre_stimulus_selected_estimate_and_identification_earliest_s": 2100,
        "settling_exclusion_s": 900,
        "first_post_stimulus_selected_estimate_complete_s": 1500,
        "second_post_stimulus_selected_estimate_complete_s": 2100,
        "next_request_earliest_s": 2400,
        "post_evidence_margin_s": 300,
        "support_boundary_rule": "selected_window_start_at_or_after_exclusion_end_and_window_end_at_exact_declared_offset",
        "request_boundary_rule": "next_request_at_or_after_2400s_never_before",
        "extension": "forbidden",
    }


def test_indeterminate_material_response_is_not_relabelled_as_signed() -> None:
    gate = _load(GATE_PATH)
    policy = _load(POLICY_PATH)
    identification_gate = gate["response_observability_gate"]
    checkpoint = policy["natural_material_response_checkpoint"]
    metrics = policy["prospective_metrics"]

    assert identification_gate["accepted_existing_classifier_outcomes"] == [
        "inside_deadband",
        "healthy_detected",
    ]
    assert identification_gate[
        "classifier_outcome_is_admissibility_not_sign_evidence"
    ]
    assert identification_gate[
        "inside_deadband_label_requires_independent_numeric_sign_and_magnitude_pass"
    ]
    assert identification_gate["healthy_indeterminate_near_resolution_passes"] is False
    assert "healthy_indeterminate_near_resolution" in checkpoint[
        "accepted_response_classes"
    ]
    assert checkpoint["same_run_plant_sign_attestation_exact_and_current_required"]
    assert checkpoint["detected_wrong_sign_or_excess_fails_static"]
    assert checkpoint["healthy_indeterminate_is_not_relabelled_as_signed"]
    assert checkpoint[
        "material_response_sign_reported_separately_as_observed_or_unresolved"
    ]
    assert metrics["identification_stimulus_excluded_from_phase_material_count"]
    assert metrics["identification_stimulus_excluded_from_phase_performance_segments"]


def test_plant_sign_attestation_has_explicit_currentness_and_invalidation() -> None:
    policy = _load(POLICY_PATH)
    currentness = policy["plant_sign_attestation_currentness"]
    timing = policy["finite_timing"]

    assert currentness["validity_horizon"] == (
        "same_finite_run_only_until_terminal_or_invalidation"
    )
    invalidated = set(currentness["invalidated_by"])
    assert {
        "firmware_reset_or_reflash",
        "capture_or_firmware_session_change",
        "D14_or_D8_measurement_discontinuity_or_common_health_fault",
        "manual_external_unacknowledged_or_cross_epoch_DAC_change",
        "exact_replay_or_downstream_epoch_propagation_failure",
    } <= invalidated
    assert currentness["preserved_across"] == [
        "continuous_capture_file_rotation_with_same_session_and_exact_sequence",
        "healthy_exact_acknowledged_natural_DAC_epoch_transition_inside_the_frozen_range_with_noncontradictory_response",
    ]
    assert currentness["invalidation_action"] == "fail_static_no_later_authority"
    assert timing["timing_domain"] == "rp2040_timer0_exact_recorded_ticks"
    assert timing["setup_application_to_identification_earliest_s"] == 2100
    assert timing["identification_to_earliest_natural_material_application_s"] == 4200
    assert timing["setup_application_to_earliest_natural_material_application_s"] == 6300


def test_cx321_design_has_no_effective_physical_authority() -> None:
    for path in (GATE_PATH, POLICY_PATH):
        authority = _load(path)["authority"]
        assert authority["offline_preparation"] is True
        assert authority["effective"] is False
        for operation in (
            "firmware_flash",
            "reset",
            "serial_access",
            "command_fifo",
            "setup_stimulus",
            "dac_write",
            "control_arm",
            "physical_rehearsal",
            "live_acquisition",
        ):
            assert authority[operation] is False
