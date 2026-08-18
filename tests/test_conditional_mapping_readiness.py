from __future__ import annotations

from copy import deepcopy

import pytest

from host.otis_tools.conditional_part_a_mapping_readiness import evaluate_mapping


def _contract() -> dict[str, object]:
    return {
        "derived_expectations": {
            "manufacturer_counts_per_code_minimum": 0.06935814,
            "manufacturer_counts_per_code_maximum": 0.13871628,
            "maximum_descriptive_mixed_interval_width_codes": 11,
            "maximum_directional_displacement_codes": 8,
            "maximum_point_sample_standard_deviation_counts": 0.986013,
            "maximum_point_observed_span_counts": 2,
        },
        "part_b_envelope": {
            "known_inside_reference_code": 0xA830,
            "lower_setup_code": 0xA800,
            "upper_setup_code": 0xA890,
            "maximum_step_codes": 21,
            "maximum_corrections_per_leg": 9,
            "maximum_cumulative_movement_codes_per_leg": 189,
        },
    }


def _point(role: str, code: int, counts: list[int]) -> dict[str, object]:
    return {
        "role": role,
        "code": code,
        "integer_edge_error_counts": counts,
    }


def _mapped_points() -> list[dict[str, object]]:
    return [
        _point("opening_outside_closure", 0xA800, [-6, -5]),
        _point("central_reference_before_lower", 0xA830, [-1, 0, 0, -1]),
        _point("lower_outbound_outside_guard", 0xA817, [-3, -3, -3, -3]),
        _point("lower_outbound_candidate_0", 0xA819, [-3, -2, -3, -4, -2, -2]),
        _point("lower_outbound_candidate_1", 0xA81B, [-2, -3, -2, -3, -2, -2]),
        _point("lower_outbound_candidate_2", 0xA81D, [-2, -3, -2, -3, -2, -3]),
        _point("lower_outbound_candidate_3", 0xA81F, [-2, -2, -2, -2]),
        _point("lower_outbound_inside_guard", 0xA821, [-2, -2, -2, -2]),
        _point("lower_return_inside_guard_new_epoch", 0xA821, [-2, -1, -2, -2]),
        _point("lower_return_candidate_3", 0xA81F, [-2, -3, -2, -2, -3, -2]),
        _point("lower_return_candidate_2", 0xA81D, [-3, -2, -2, -3, -2, -3]),
        _point("lower_return_candidate_1", 0xA81B, [-3, -2, -3, -3, -2, -3]),
        _point("lower_return_candidate_0", 0xA819, [-3, -3, -3, -4]),
        _point("lower_return_outside_guard", 0xA817, [-3, -4, -3, -4]),
        _point("central_reference_between_regions", 0xA830, [-1, -1, -2, -1]),
        _point("upper_outbound_inside_guard", 0xA845, [1, 2, 1, 1]),
        _point("upper_outbound_candidate_low", 0xA847, [1, 1, 2, 1]),
        _point("upper_outbound_candidate_mid", 0xA849, [2, 1, 2, 2]),
        _point("upper_outbound_candidate_high", 0xA84B, [2, 2, 2, 3, 2, 2]),
        _point("upper_outbound_outside_guard", 0xA84D, [2, 3, 2, 3, 2, 3]),
        _point("upper_return_outside_guard_new_epoch", 0xA84D, [2, 3, 3, 3, 3, 3]),
        _point("upper_return_candidate_high", 0xA84B, [3, 3, 3, 2, 3, 2]),
        _point("upper_return_candidate_mid", 0xA849, [2, 3, 2, 3, 2, 3]),
        _point("upper_return_candidate_low", 0xA847, [3, 2, 2, 3, 2, 3]),
        _point("upper_return_inside_guard", 0xA845, [2, 2, 2, 3, 2, 3]),
        _point("central_reference_after_upper", 0xA830, [0, 0, 1, -1]),
        _point("final_outside_closure", 0xA800, [-5, -5]),
    ]


def test_mapping_informed_gate_accepts_the_quantized_transition_distribution() -> None:
    result = evaluate_mapping(_mapped_points(), _contract())  # type: ignore[arg-type]

    assert result["status"] == "ready"
    assert result["failures"] == []
    assert result["shared_within_direction_slope_counts_per_code"] == pytest.approx(
        0.12041328698339128
    )
    assert {
        name: value["transition_width_codes"]
        for name, value in result["transitions"].items()
    } == {
        "lower_outbound": 4,
        "lower_return": 4,
        "upper_outbound": 2,
        "upper_return": 8,
    }
    assert result["part_b_reachability"]["lower"]["minimum_maximum_step_corrections"] == 3
    assert result["part_b_reachability"]["upper"]["minimum_maximum_step_corrections"] == 5


def test_mapping_informed_gate_rejects_a_deliberate_high_variance_fixture() -> None:
    points = deepcopy(_mapped_points())
    selected = next(
        item for item in points if item["role"] == "lower_outbound_candidate_0"
    )
    selected["integer_edge_error_counts"] = [-4, 0, -4, 0, -4, 0]

    result = evaluate_mapping(points, _contract())  # type: ignore[arg-type]

    assert result["status"] == "not_ready"
    assert "lower_outbound_candidate_0:point_variance_exceeds_gross_screen" in result[
        "failures"
    ]


def test_mapping_informed_gate_rejects_a_response_with_the_wrong_sign() -> None:
    points = deepcopy(_mapped_points())
    for point in points:
        point["integer_edge_error_counts"] = [
            -value for value in point["integer_edge_error_counts"]  # type: ignore[union-attr]
        ]

    result = evaluate_mapping(points, _contract())  # type: ignore[arg-type]

    assert result["status"] == "not_ready"
    assert "shared_positive_slope_outside_manufacturer_range" in result["failures"]
