from __future__ import annotations

from dataclasses import replace
import math

import pytest

from host.otis_tools.pps_cumulative_span_estimator import (
    DEFAULT_CONFIG,
    IntervalEvidence,
    estimate_spans,
    load_config,
)
from host.otis_tools.pps_fixed_code_baseline import (
    METRIC_PROVENANCE,
    _interpolated_temperature,
    _temperature_correlation_metrics,
    allan_deviation,
    select_declared_analysis_intervals,
    span_linear_drift,
    summarize_spans,
    withheld_span_windows,
)


def test_metric_provenance_keeps_descriptive_statistics_non_authoritative() -> None:
    assert set(METRIC_PROVENANCE) == {
        "population_standard_deviation",
        "median_absolute_deviation",
        "robust_scale_1p4826_mad",
        "finite_run_range",
        "overlapping_allan_deviation",
        "linear_drift",
        "near_air_temperature_association",
        "service_plane_segment_comparison",
    }
    combined = " ".join(
        str(field)
        for value in METRIC_PROVENANCE.values()
        for field in value.values()
    ).lower()
    assert "not calibrated uncertainty" in combined
    assert "no isolated firmware-jitter attribution" in combined
    assert "not cx317 case/oven temperature" in combined


def _config(*, spans: tuple[int, ...] = (1, 2, 4)):
    return replace(
        load_config(DEFAULT_CONFIG),
        candidate_spans_s=spans,
        output_modes=("non_overlapping", "overlapping"),
    )


def _interval(
    closing: int,
    *,
    counted: int = 10_000_000,
    valid: bool = True,
    reasons: tuple[str, ...] = (),
    session: str = "1",
    epoch: str = "static",
) -> IntervalEvidence:
    return IntervalEvidence(
        session_id=session,
        opening_snapshot_sequence=closing - 1,
        closing_snapshot_sequence=closing,
        interval_counted_edges=counted,
        opening_reference_event_sequence=1000 + closing - 1,
        closing_reference_event_sequence=1000 + closing,
        opening_reference_timestamp_ticks=(closing - 1) * 16_000_000,
        closing_reference_timestamp_ticks=closing * 16_000_000,
        cnt_sequence=closing,
        valid=valid,
        reasons=reasons,
        control_epoch=epoch,
    )


def test_span_summary_reports_robust_spread_and_independence() -> None:
    config = _config(spans=(2,))
    intervals = tuple(
        _interval(index + 1, counted=value)
        for index, value in enumerate((10_000_000, 10_000_002, 10_000_000, 10_000_004))
    )
    summary = summarize_spans(estimate_spans(intervals, config))
    nonoverlap = next(item for item in summary if item["mode"] == "non_overlapping")
    overlap = next(item for item in summary if item["mode"] == "overlapping")
    assert nonoverlap["eligible_estimate_count"] == 2
    assert nonoverlap["effective_independent_estimate_count"] == 2
    assert nonoverlap["median_hz"] == 10_000_001.5
    assert nonoverlap["range_hz"] == 1.0
    assert nonoverlap["median_absolute_deviation_hz"] == 0.5
    assert overlap["eligible_estimate_count"] == 3
    assert overlap["effective_independent_estimate_count"] == 2
    assert overlap["independent_control_decisions"] is False


def test_allan_deviation_is_zero_for_constant_frequency() -> None:
    config = _config(spans=(1, 2, 4))
    results = allan_deviation(
        tuple(_interval(index + 1) for index in range(8)),
        config,
        10_000_000.0,
    )
    assert [item["difference_term_count"] for item in results] == [7, 5, 1]
    assert all(item["overlapping_allan_deviation_hz"] == 0.0 for item in results)
    assert all(item["overlapping_allan_deviation_fractional"] == 0.0 for item in results)


def test_allan_deviation_separates_fault_segments() -> None:
    config = _config(spans=(1,))
    intervals = (
        _interval(1, counted=9_999_999),
        _interval(2, counted=10_000_001),
        _interval(3, valid=False, reasons=("dma_fault",)),
        _interval(4, counted=9_999_999),
        _interval(5, counted=10_000_001),
    )
    result = allan_deviation(intervals, config, 10_000_000.0)[0]
    assert result["difference_term_count"] == 2
    assert result["overlapping_allan_deviation_hz"] == pytest.approx(math.sqrt(2.0))


def test_withheld_windows_name_fault_and_continuity_reasons() -> None:
    config = _config(spans=(1, 2))
    intervals = (
        _interval(1),
        _interval(2, valid=False, reasons=("dma_fault",)),
        _interval(3, session="2"),
        _interval(4, session="2", epoch="changed"),
    )
    results = {item["span_seconds"]: item for item in withheld_span_windows(intervals, config)}
    assert results[1]["withheld_window_count"] == 1
    assert results[1]["withheld_reason_window_counts"] == {"dma_fault": 1}
    assert results[2]["withheld_window_count"] == 3
    assert results[2]["withheld_reason_window_counts"]["dma_fault"] == 2
    assert results[2]["withheld_reason_window_counts"]["session_boundary"] == 1
    assert results[2]["withheld_reason_window_counts"]["control_epoch_boundary"] == 1
    assert results[2]["fresh_support_recovery_time_s"] == 2


def test_fixed_code_baseline_requires_declared_stable_bounds() -> None:
    intervals = tuple(_interval(index) for index in range(1, 5))
    with pytest.raises(ValueError, match="requires declared stable"):
        select_declared_analysis_intervals(
            intervals,
            {
                "stage": "CX317_FIXED_CODE_BASELINE",
                "cx317_fixed_code_baseline": {
                    "declared_stable_first_count_seq": None,
                    "declared_stable_last_count_seq": None,
                },
            },
        )


def test_declared_stable_bounds_exclude_warmup_exactly() -> None:
    intervals = tuple(_interval(index) for index in range(1, 7))
    selected, description = select_declared_analysis_intervals(
        intervals,
        {
            "stage": "CX317_FIXED_CODE_BASELINE",
            "cx317_fixed_code_baseline": {
                "declared_warmup_first_count_seq": 1,
                "declared_warmup_last_count_seq": 2,
                "declared_stable_first_count_seq": 3,
                "declared_stable_last_count_seq": 6,
            },
        },
    )
    assert [interval.cnt_sequence for interval in selected] == [3, 4, 5, 6]
    assert description == {
        "status": "manifest_declared_stable_interval",
        "first_count_sequence": 3,
        "last_count_sequence": 6,
        "interval_count": 4,
        "warmup_first_count_sequence": 1,
        "warmup_last_count_sequence": 2,
        "warmup_excluded": True,
    }


def test_declared_stable_bounds_fail_when_a_sequence_is_missing() -> None:
    intervals = (_interval(1), _interval(2), _interval(4))
    with pytest.raises(ValueError, match="exact continuous"):
        select_declared_analysis_intervals(
            intervals,
            {
                "stage": "CX317_FIXED_CODE_BASELINE",
                "cx317_fixed_code_baseline": {
                    "declared_stable_first_count_seq": 2,
                    "declared_stable_last_count_seq": 4,
                },
            },
        )


def test_span_linear_drift_reports_each_mode_and_span() -> None:
    config = _config(spans=(2,))
    intervals = tuple(
        _interval(index + 1, counted=10_000_000 + index)
        for index in range(8)
    )
    results = {
        item["mode"]: item
        for item in span_linear_drift(estimate_spans(intervals, config), config)
    }
    assert set(results) == {"non_overlapping", "overlapping"}
    assert results["non_overlapping"]["sample_count"] == 4
    assert results["non_overlapping"]["correlated_outputs"] is False
    assert results["non_overlapping"]["slope_hz_per_s"] == pytest.approx(1.0)
    assert results["overlapping"]["sample_count"] == 7
    assert results["overlapping"]["correlated_outputs"] is True
    assert results["overlapping"]["slope_hz_per_s"] == pytest.approx(1.0)


def test_span_linear_drift_withholds_discontinuous_series() -> None:
    config = _config(spans=(2,))
    intervals = (
        _interval(1),
        _interval(2),
        _interval(3, valid=False, reasons=("dma_fault",)),
        _interval(4),
        _interval(5),
    )
    results = span_linear_drift(estimate_spans(intervals, config), config)
    assert results
    assert all(item["status"] == "unavailable" for item in results)
    assert all(
        item["reason"] == "estimate_series_not_exactly_continuous"
        for item in results
    )


def test_temperature_interpolation_requires_bracketing_samples() -> None:
    ticks = [100, 200, 300]
    temperatures = [20.0, 22.0, 24.0]
    assert _interpolated_temperature(150, ticks, temperatures) == pytest.approx(21.0)
    assert _interpolated_temperature(250, ticks, temperatures) == pytest.approx(23.0)
    assert _interpolated_temperature(99, ticks, temperatures) is None
    assert _interpolated_temperature(300, ticks, temperatures) is None


def test_temperature_metrics_report_time_confounding_without_causality() -> None:
    metrics = _temperature_correlation_metrics(
        [10.0, 10.0, 11.0, 11.0],
        [20.0, 21.0, 22.0, 23.0],
        [0.0, 1.0, 2.0, 3.0],
    )
    assert metrics["pearson_frequency_temperature_correlation"] == pytest.approx(
        2.0 / math.sqrt(5.0)
    )
    assert metrics["simple_frequency_temperature_r_squared"] == pytest.approx(
        0.8
    )
    assert metrics["pearson_temperature_elapsed_correlation"] == pytest.approx(
        1.0
    )
