from __future__ import annotations

from collections import Counter
from fractions import Fraction
from hashlib import sha256
import json
import math
from pathlib import Path

from host.otis_tools.pps_cumulative_span_estimator import load_config


ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "profiles/estimators/cx321_plant_sign_1500_config_v1.json"
ESTIMATOR_PATH = ROOT / "profiles/estimators/cx321_plant_sign_1500_v1.json"
PLANT_RECONSTRUCTION_PATH = (
    ROOT / "profiles/qualification/cx321_plant_parity_1500_reconstruction_v1.json"
)
COMPARISON_PATH = (
    ROOT / "profiles/qualification/cx321_response_observability_comparison_v1.json"
)
GATE_PATH = (
    ROOT / "profiles/qualification/cx321_bounded_response_observability_v2.json"
)
POLICY_PATH = (
    ROOT / "profiles/discipline/cx321_bounded_active_hybrid_plant_sign_v2.json"
)
FIXTURE_PATH = ROOT / "tests/fixtures/cx321_stage3_stable_interval_counts_v1.json"


def _load(file_path: Path) -> dict[str, object]:
    return json.loads(file_path.read_text(encoding="utf-8"))


def _sha256(file_path: Path) -> str:
    return sha256(file_path.read_bytes()).hexdigest()


def _assert_path_binding(binding: dict[str, object]) -> None:
    file_path = ROOT / str(binding["path"])
    assert file_path.is_file()
    assert binding["sha256"] == _sha256(file_path)


def _fixture_counts() -> tuple[dict[str, object], list[int]]:
    fixture = _load(FIXTURE_PATH)
    encoding = fixture["encoding"]
    base = encoding["base_interval_count"]
    values = [base + int(item) for item in encoding["interval_count_offsets"]]
    return fixture, values


def _prefix(values: list[int]) -> list[int]:
    result = [0]
    for value in values:
        result.append(result[-1] + value)
    return result


def test_cx321_v2_binds_executable_config_comparison_and_contracts() -> None:
    estimator = _load(ESTIMATOR_PATH)
    comparison = _load(COMPARISON_PATH)
    gate = _load(GATE_PATH)
    policy = _load(POLICY_PATH)

    _assert_path_binding(estimator["base_estimator"])
    runtime = estimator["runtime_config"]
    assert runtime["path"] == "profiles/estimators/cx321_plant_sign_1500_config_v1.json"
    assert runtime["file_sha256"] == _sha256(CONFIG_PATH)
    strict_config = load_config(CONFIG_PATH)
    assert strict_config.candidate_spans_s == (1500,)
    assert strict_config.output_modes == ("non_overlapping",)
    assert runtime["canonical_config_hash"] == strict_config.config_hash

    _assert_path_binding(comparison["selected_estimator"])
    replay_fixture = comparison["fixed_code_null_evidence"]["derived_replay_fixture"]
    _assert_path_binding(replay_fixture)
    _assert_path_binding(gate["supersedes"])
    _assert_path_binding(policy["supersedes"])
    for document in (gate, policy):
        for binding in document["bindings"].values():
            if isinstance(binding, dict) and "path" in binding:
                _assert_path_binding(binding)


def test_1500_estimator_has_exact_arithmetic_and_plant_parity_provenance() -> None:
    estimator = _load(ESTIMATOR_PATH)
    selected = estimator["authoritative_policy"]
    arithmetic = estimator["exact_arithmetic"]
    evidence = estimator["qualification_evidence"]
    reconstruction = _load(PLANT_RECONSTRUCTION_PATH)

    assert selected["span_s"] == 1500
    assert selected["output_mode"] == "non_overlapping"
    assert selected["count_increment_hz"] == 1 / 1500
    assert selected["stage3_nonoverlapping_range_counts"] == 2
    assert selected["empirical_detection_floor_counts"] == 3
    assert selected["empirical_detection_floor_hz"] == 3 / 1500
    assert selected["stage3_independent_estimate_count"] == 28
    assert arithmetic["response_verdict_domain"] == "exact_integer_counts"
    assert arithmetic["floating_frequency_subtraction_forbidden_for_verdicts"]

    fixed = evidence["fixed_code"]
    plant = evidence["plant_dwell_parity"]
    _assert_path_binding(plant["exact_reconstruction"])
    assert fixed["stable_interval_count"] == 43227
    assert fixed["observed_range_counts"] == 2
    assert plant["visit_count"] == 9
    assert plant["one_complete_1500s_window_per_visit"]

    visits = reconstruction["visits"]
    assert [visit["total_count"] for visit in visits] == plant["window_total_counts"]
    for visit in visits:
        assert visit["last_cnt_sequence"] - visit["first_cnt_sequence"] + 1 == 1500
        assert visit["closing_snp_sequence"] - visit["opening_snp_sequence"] == 1500
        assert visit["representative_tick_numerator"] == (
            visit["opening_unwrapped_timer_ticks"]
            + visit["closing_unwrapped_timer_ticks"]
        )
        assert visit["representative_tick_denominator"] == 2

    visits_by_label = {visit["label"]: visit for visit in visits}
    gains = []
    for sample in reconstruction["drift_cancelled_gain_samples"]:
        target = visits_by_label[sample["target_label"]]
        bracket_1, bracket_2 = (
            visits_by_label[label] for label in sample["bracket_labels"]
        )
        alpha = Fraction(sample["interpolation_fraction"])
        baseline_frequency = (
            (1 - alpha) * Fraction(bracket_1["total_count"], 1500)
            + alpha * Fraction(bracket_2["total_count"], 1500)
        )
        target_frequency = Fraction(target["total_count"], 1500)
        reconstructed_gain = abs(target_frequency - baseline_frequency) / sample[
            "code_difference"
        ]
        declared_gain = Fraction(sample["gain_hz_per_code"])
        assert reconstructed_gain == declared_gain
        gains.append(declared_gain)
    assert len(gains) == 6
    envelope = plant["exact_drift_cancelled_gain_hz_per_code"]
    assert min(gains) == Fraction(envelope["minimum"])
    assert max(gains) == Fraction(envelope["maximum"])


def test_fixture_replays_every_declared_600_and_1500_null_outcome() -> None:
    fixture, values = _fixture_counts()
    comparison = _load(COMPARISON_PATH)
    candidates = comparison["candidates"]
    validation = fixture["validation"]
    source = fixture["source"]
    assert len(values) == validation["interval_count"] == 43227
    assert Counter(values) == Counter(
        {int(key): count for key, count in validation["interval_value_counts"].items()}
    )
    assert source["cnt_sha256"] == comparison["fixed_code_null_evidence"][
        "source_paths_and_sha256"
    ]["counts"]["sha256"]

    prefix = _prefix(values)

    def total(start: int, stop: int) -> int:
        return prefix[stop] - prefix[start]

    rows_600: list[tuple[int, int]] = []
    for origin in range(len(values) - 4202 + 1):
        pre_1 = total(origin + 901, origin + 1501)
        pre_2 = total(origin + 1501, origin + 2101)
        if pre_1 != pre_2:
            continue
        post_1 = total(origin + 3002, origin + 3602)
        post_2 = total(origin + 3602, origin + 4202)
        rows_600.append((post_1 - pre_2, post_2 - pre_2))

    current = candidates["single_window_600_two_count"]
    persistent_one = candidates["persistent_600_one_count"]
    persistent_two = candidates["persistent_600_two_count"]
    assert current["timeline_faithful_null_placements"] == 39026
    assert len(rows_600) == current["eligible_exact_stable_pre_placements"] == 9564
    current_false = {
        "positive_command_direction": sum(first >= 2 for first, _ in rows_600),
        "negative_command_direction": sum(-first >= 2 for first, _ in rows_600),
    }
    current_false["either_direction_total"] = sum(current_false.values())
    assert current_false == current["false_attributions"]
    assert current["synthetic_two_count_shift_replay_passes"] == {
        "positive_command_direction": sum(first + 2 >= 2 for first, _ in rows_600),
        "negative_command_direction": sum(-first + 2 >= 2 for first, _ in rows_600),
        "eligible_per_direction": len(rows_600),
    }
    persistent_one_false = {
        "positive_command_direction": sum(
            first >= 1 and second >= 1 for first, second in rows_600
        ),
        "negative_command_direction": sum(
            -first >= 1 and -second >= 1 for first, second in rows_600
        ),
    }
    persistent_one_false["either_direction_total"] = sum(
        persistent_one_false.values()
    )
    assert persistent_one_false == persistent_one["false_attributions"]
    assert persistent_two["false_attributions"]["either_direction_total"] == 0
    assert persistent_two["synthetic_two_count_shift_replay_passes"] == {
        "positive_command_direction": sum(
            first + 2 >= 2 and second + 2 >= 2 for first, second in rows_600
        ),
        "negative_command_direction": sum(
            -first + 2 >= 2 and -second + 2 >= 2 for first, second in rows_600
        ),
        "eligible_per_direction": len(rows_600),
    }

    rows_1500: list[int] = []
    for origin in range(len(values) - 6302 + 1):
        pre_1 = total(origin + 901, origin + 2401)
        pre_2 = total(origin + 2401, origin + 3901)
        if pre_1 != pre_2:
            continue
        post = total(origin + 4802, origin + 6302)
        rows_1500.append(post - pre_2)

    selected = candidates["selected_single_window_1500_three_count"]
    assert selected["timeline_faithful_null_placements"] == 36926
    assert len(rows_1500) == selected["eligible_exact_stable_pre_placements"] == 18219
    histogram = {str(key): count for key, count in sorted(Counter(rows_1500).items())}
    assert histogram == selected["first_response_delta_count_histogram"]
    assert all(abs(delta) < 3 for delta in rows_1500)
    assert selected["false_attributions"]["either_direction_total"] == 0
    assert all(delta + 5 >= 3 for delta in rows_1500)
    assert all(-delta + 5 >= 3 for delta in rows_1500)

    rows_600_aligned: list[tuple[int, int]] = []
    for origin in range(len(values) - 4200 + 1):
        pre_1 = total(origin + 900, origin + 1500)
        pre_2 = total(origin + 1500, origin + 2100)
        if pre_1 != pre_2:
            continue
        post_1 = total(origin + 3000, origin + 3600)
        post_2 = total(origin + 3600, origin + 4200)
        rows_600_aligned.append((post_1 - pre_2, post_2 - pre_2))

    rows_1500_aligned: list[int] = []
    for origin in range(len(values) - 6300 + 1):
        pre_1 = total(origin + 900, origin + 2400)
        pre_2 = total(origin + 2400, origin + 3900)
        if pre_1 != pre_2:
            continue
        post = total(origin + 4800, origin + 6300)
        rows_1500_aligned.append(post - pre_2)

    aligned = comparison["boundary_phase_replays"]["900"]
    assert aligned["single_window_600"] == {
        "complete_placements": 39028,
        "eligible": len(rows_600_aligned),
        "false_positive_direction": sum(
            first >= 2 for first, _ in rows_600_aligned
        ),
        "false_negative_direction": sum(
            -first >= 2 for first, _ in rows_600_aligned
        ),
        "synthetic_two_count_positive_passes": sum(
            first + 2 >= 2 for first, _ in rows_600_aligned
        ),
        "synthetic_two_count_negative_passes": sum(
            -first + 2 >= 2 for first, _ in rows_600_aligned
        ),
    }
    assert aligned["persistent_600_one_count"] == {
        "false_positive_direction": sum(
            first >= 1 and second >= 1 for first, second in rows_600_aligned
        ),
        "false_negative_direction": sum(
            -first >= 1 and -second >= 1 for first, second in rows_600_aligned
        ),
    }
    assert aligned["persistent_600_two_count"] == {
        "false_positive_direction": 0,
        "false_negative_direction": 0,
        "synthetic_two_count_positive_passes": sum(
            first + 2 >= 2 and second + 2 >= 2
            for first, second in rows_600_aligned
        ),
        "synthetic_two_count_negative_passes": sum(
            -first + 2 >= 2 and -second + 2 >= 2
            for first, second in rows_600_aligned
        ),
    }
    assert aligned["selected_1500"] == {
        "complete_placements": 36928,
        "eligible": len(rows_1500_aligned),
        "histogram": {
            str(key): count for key, count in sorted(Counter(rows_1500_aligned).items())
        },
        "false_positive_direction": sum(delta >= 3 for delta in rows_1500_aligned),
        "false_negative_direction": sum(-delta >= 3 for delta in rows_1500_aligned),
    }
    assert len(rows_1500_aligned) == 18219
    assert all(delta + 5 >= 3 and -delta + 5 >= 3 for delta in rows_1500_aligned)


def test_selected_step_has_margin_beyond_the_arithmetic_minimum() -> None:
    gate = _load(GATE_PATH)
    measurement = gate["measurement_contract"]
    derivation = gate["response_observability_derivation"]
    gains = derivation["plant_gain_hz_per_code"]
    minimum_gain = gains["minimum_conservative_600s"]
    floor_hz = measurement["identification_empirical_floor_hz"]

    assert math.ceil(floor_hz / minimum_gain) == 13
    assert derivation["arithmetic_floor_clearing_step_codes"] == 13
    assert 12 * minimum_gain < floor_hz <= 13 * minimum_gain
    assert math.isclose(
        derivation["thirteen_code_expected_response_counts_minimum"],
        13 * minimum_gain * 1500,
        rel_tol=0.0,
        abs_tol=1e-12,
    )
    assert derivation["selected_step_codes"] == 21
    minimum_response_counts = 21 * minimum_gain * 1500
    assert math.isclose(
        derivation["twenty_one_code_expected_response_counts"]["minimum"],
        minimum_response_counts,
        rel_tol=0.0,
        abs_tol=1e-12,
    )
    assert minimum_response_counts - measurement["identification_empirical_floor_counts"] > 2
    assert derivation["cx320_six_code_expected_response_hz"]["maximum"] < floor_hz


def test_identification_stimulus_is_bounded_and_moves_toward_nominal() -> None:
    gate = _load(GATE_PATH)
    stimulus = gate["stimulus"]
    setup = gate["setup"]
    pre = gate["pre_stimulus_gate"]
    setup_code = setup["exact_start_code"]
    minimum_code = stimulus["minimum_code"]
    maximum_code = stimulus["maximum_code"]

    assert pre["estimate_count"] == 2
    assert pre["estimate_span_s"] == 1500
    assert pre["exact_same_total_count_required"]
    assert pre["eligible_absolute_1500s_error_counts"] == [1, 2, 3, 4, 5]
    assert pre["natural_600s_TIGHT_INSIDE_state_also_required"]
    assert pre["first_full_interval_after_exclusion_required"]
    assert setup["pre_identification_automatic_applications_allowed"] == 0

    negative = stimulus["negative_direction_transition"]
    positive = stimulus["positive_direction_transition"]
    assert negative["requested_code"] == setup_code - 21 == 0xA827
    assert positive["requested_code"] == setup_code + 21 == 0xA851
    for transition in (negative, positive):
        assert minimum_code <= transition["requested_code"] <= maximum_code

    predicted = gate["predicted_post_stimulus_frequency_error"]
    assert predicted["maximum_absolute_hz"] < 2 / 600
    assert predicted["maximum_absolute_1500s_counts"] < 5
    assert predicted["inside_existing_TIGHT_entry_bound"]


def test_identification_verdict_uses_exact_application_origin_and_finite_support() -> None:
    gate = _load(GATE_PATH)
    response = gate["response_observability_gate"]
    timing = gate["finite_timing"]

    assert response["response_counts_formula"] == "post_total_counts - pre_total_counts"
    assert response["detected_magnitude_formula"] == "abs(response_counts) >= 3"
    assert response["maximum_response_counts"] == 14
    threshold = response["existing_21_code_upper_empirical_classifier_threshold_hz"]
    assert 14 / 1500 <= threshold < 15 / 1500
    assert response["second_post_estimate_required"] is False
    assert response["healthy_below_floor_passes"] is False
    assert response["response_evidence_ack"]["deadline_s_after_firmware_response"] == 30

    assert timing["setup_settling_exclusion_deadline_s"] == 900
    assert timing["first_pre_stimulus_estimate_complete_lower_bound_s"] == 2400
    assert timing[
        "second_pre_stimulus_estimate_and_identification_decision_lower_bound_s"
    ] == 3900
    assert timing["post_identification_response_complete_lower_bound_s"] == 2400
    assert "exact_acknowledged_identification_application_tick" in timing[
        "identification_request_application_timestamp_rule"
    ]
    assert timing["extension"] == "forbidden"


def test_handoff_preserves_control_law_and_separates_global_and_natural_history() -> None:
    gate = _load(GATE_PATH)
    policy = _load(POLICY_PATH)
    controller = policy["natural_hybrid_controller"]
    limits = policy["global_authority_limits"]
    handoff = policy["identification_to_natural_handoff"]
    checkpoint = policy["natural_material_response_checkpoint"]
    timing = policy["finite_timing"]

    assert controller["control_law_mathematics_change_from_cx320"] == "none"
    assert controller["frequency_estimator_span_s"] == 600
    assert controller[
        "identification_stimulus_never_enters_controller_demand_or_counterfactual_materiality"
    ]
    assert gate["stimulus"]["counts_as_phase_material_application"] is False
    assert limits["plant_sign_identification_consumes_application_count"] == 1
    assert limits["plant_sign_identification_consumes_movement_codes"] == 21
    assert limits["maximum_applications_remaining_after_identification"] == 3
    assert limits["maximum_movement_remaining_after_identification_codes"] == 63
    assert limits["minimum_natural_phase_material_applications"] == 2
    assert handoff["global_correction_count_after_identification"] == 1
    assert handoff["global_cumulative_movement_codes_after_identification"] == 21
    assert handoff["identification_enters_global_minimum_cadence"]
    assert handoff["identification_enters_natural_direction_history"] is False
    assert handoff["identification_enters_natural_chatter_path_or_net_displacement"] is False
    assert handoff["natural_direction_history_at_handoff"] == "empty"
    assert checkpoint["frequency_estimator_span_s"] == 600
    assert checkpoint["healthy_indeterminate_is_not_relabelled_as_signed"]
    assert timing["setup_application_to_identification_decision_lower_bound_s"] == 3900
    assert timing[
        "identification_application_to_first_eligible_natural_selected_epoch_lower_bound_s"
    ] == 4500
    assert timing[
        "setup_application_to_first_eligible_natural_request_lower_bound_s_excluding_identification_transaction_latency"
    ] == 8400


def test_plant_sign_attestation_is_same_run_and_fail_static_on_identity_loss() -> None:
    policy = _load(POLICY_PATH)
    currentness = policy["plant_sign_attestation_currentness"]
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
    assert currentness["invalidation_action"] == "fail_static_no_later_authority"


def test_cx321_v2_has_no_effective_physical_authority() -> None:
    for file_path in (GATE_PATH, POLICY_PATH):
        authority = _load(file_path)["authority"]
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

    estimator_authority = _load(ESTIMATOR_PATH)["authority"]
    assert estimator_authority["offline_preparation"] is True
    assert estimator_authority["effective"] is False
    assert estimator_authority["actuation_authorized"] is False
    assert estimator_authority["controller_ported_to_firmware"] is False
