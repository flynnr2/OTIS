from __future__ import annotations

from copy import deepcopy
import math

import pytest

from host.otis_tools.pps_estimator_selection import (
    METHOD_ID,
    REQUIRED_CANDIDATE_SPANS_S,
    _boxcar_3db_ratio,
    evaluate_selection_data,
)


ALL_SPANS_S = (1, 5, 10, 30, *REQUIRED_CANDIDATE_SPANS_S)


def _baseline() -> dict:
    statistics = []
    drift = []
    temperature = []
    withheld = []
    for span in ALL_SPANS_S:
        independent_count = 21_600 // span
        for mode, count in (
            ("non_overlapping", independent_count),
            ("overlapping", 21_600 - span + 1),
        ):
            statistics.append(
                {
                    "mode": mode,
                    "span_seconds": span,
                    "eligible_estimate_count": count,
                    "count_increment_hz": 1.0 / span,
                    "range_hz": 0.02,
                    "robust_scale_1p4826_mad_hz": 0.005,
                    "population_stddev_hz": 0.006,
                    "lag1_correlation": 0.9 if mode == "overlapping" else 0.0,
                }
            )
            drift.append(
                {
                    "mode": mode,
                    "span_seconds": span,
                    "status": "characterization_only",
                }
            )
            temperature.append(
                {
                    "mode": mode,
                    "span_seconds": span,
                    "status": "characterization_only",
                }
            )
        withheld.append(
            {
                "span_seconds": span,
                "withheld_window_count": 0,
                "clean_time_to_first_estimate_s": span,
                "fresh_support_recovery_time_s": span,
            }
        )
    return {
        "method_id": METHOD_ID,
        "config_hash": "baseline-config",
        "source_immutability_verified": True,
        "analysis_interval": {
            "status": "manifest_declared_stable_interval",
            "interval_count": 21_600,
        },
        "invalid_interval_count": 0,
        "span_statistics": statistics,
        "withheld_span_windows": withheld,
        "linear_drift": {"by_estimator_span": drift},
        "temperature_association": {
            "raw_one_second_intervals": {
                "temperature_min_c": 29.0,
                "temperature_max_c": 30.0,
            },
            "by_estimator_span": temperature,
        },
    }


def _prior() -> dict:
    return {
        "control_path": {"estimated_v_per_code": 0.00004},
        "plant_response": {
            "local_slope": {
                "hz_per_code": 0.00018,
                "uncertainty": {"hz_per_v_min": 4.0, "hz_per_v_max": 5.0},
            },
            "settling_evidence": {"t95_s_min": 50.0, "t95_s_max": 650.0},
            "applicability": {
                "temperature_range_c": {"min_c": 28.0, "max_c": 31.0}
            },
        },
    }


def test_boxcar_bandwidth_root_is_mathematically_consistent() -> None:
    ratio = _boxcar_3db_ratio()
    assert ratio == pytest.approx(0.44294647068945234)
    response = math.sin(math.pi * ratio) / (math.pi * ratio)
    assert response == pytest.approx(1.0 / math.sqrt(2.0))


def test_evaluation_reports_all_candidates_without_selecting() -> None:
    result = evaluate_selection_data(_baseline(), _prior())
    assert [item["span_seconds"] for item in result["candidates"]] == list(
        ALL_SPANS_S
    )
    assert result["evaluated_spans_s"] == list(ALL_SPANS_S)
    assert result["selection_status"] == "not_selected_by_evaluation_tool"
    assert result["actuation_authority"] is False
    assert result["historical_prior"][
        "stage3_temperature_within_recorded_run020_context"
    ]
    sixty = next(item for item in result["candidates"] if item["span_seconds"] == 60)
    assert sixty["empirical_detection_floor_hz"] == pytest.approx(0.02 + 1 / 60)
    assert sixty["conditional_smallest_step_codes_at_prior_minimum_gain"] == 230
    assert sixty["boxcar_group_delay_s"] == 30.0
    assert sixty["required_stage4_candidate"] is True
    assert sixty["independent_decision_cadence_status"].startswith(
        "candidate non-overlapping estimator epoch only"
    )
    assert (
        sixty["startup_and_recovery_provenance"]["disposition"]
        == "architecture screen"
    )
    assert sixty["settling_comparison_provenance"]["source_hierarchy"] == [3, 4]
    assert sixty["empirical_detection_floor_provenance"]["source_hierarchy"] == [
        2,
        4,
        5,
    ]
    assert sixty["empirical_detection_floor_provenance"]["control_authority"] is False
    assert (
        sixty["conditional_code_domain_provenance"]["applicability"]
        == "historical comparison only; not a current PPS-gated plant specification or controller-step authority"
    )
    assert result["stable_duration_provenance"]["disposition"] == "architecture screen"
    assert result["stable_duration_provenance"]["source_hierarchy"] == 5
    assert result["candidate_span_provenance"]["disposition"] == (
        "characterization reference"
    )
    assert result["historical_prior"]["source_hierarchy"] == 3
    assert all(
        item["shorter_diagnostic_candidate"]
        for item in result["candidates"]
        if item["span_seconds"] < 60
    )


def test_outside_prior_temperature_retains_only_historical_comparison() -> None:
    baseline = _baseline()
    baseline["temperature_association"]["raw_one_second_intervals"][
        "temperature_max_c"
    ] = 33.0
    result = evaluate_selection_data(baseline, _prior())
    assert not result["historical_prior"][
        "stage3_temperature_within_recorded_run020_context"
    ]
    assert all(
        item["code_domain_resolution_status"]
        == "conditional_historical_comparison_only_outside_recorded_temperature_context"
        for item in result["candidates"]
    )
    assert all(
        item["conditional_smallest_step_codes_at_prior_minimum_gain"] == 230
        and item["conditional_predicted_response_hz_at_prior_minimum_gain"]
        == pytest.approx(0.0368)
        and item["code_domain_control_authority"] is False
        for item in result["candidates"]
        if item["span_seconds"] == 60
    )


@pytest.mark.parametrize(
    ("mutation", "message"),
    [
        (lambda value: value.update(invalid_interval_count=1), "invalid evidence"),
        (
            lambda value: value["analysis_interval"].update(interval_count=21_599),
            "21,600 stable intervals",
        ),
        (
            lambda value: value.update(source_immutability_verified=False),
            "immutability",
        ),
    ],
)
def test_evaluation_fails_closed_on_inadequate_stage3_evidence(
    mutation, message: str
) -> None:
    baseline = deepcopy(_baseline())
    mutation(baseline)
    with pytest.raises(ValueError, match=message):
        evaluate_selection_data(baseline, _prior())
