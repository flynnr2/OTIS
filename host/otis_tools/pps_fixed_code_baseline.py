"""Characterize a fixed-code PPS cumulative-snapshot baseline.

This host-only analysis consumes ``PPS_CUMULATIVE_SNAPSHOT_SPAN_V1`` inputs.
It reports empirical spread, stability, drift, service-plane segments and
optional near-oscillator temperature association without selecting a control
span or turning characterization statistics into uncertainty claims.
"""

from __future__ import annotations

from bisect import bisect_right
from collections import Counter, defaultdict
from hashlib import sha256
from pathlib import Path
import argparse
import csv
import json
import math
import statistics
import tempfile
from typing import Any, Iterable

from .contracts import CsvValidationContext, validate_csv
from .pps_cumulative_span_estimator import (
    DEFAULT_CONFIG,
    OUTPUT_DIR as ESTIMATOR_OUTPUT_DIR,
    IntervalEvidence,
    RunInputs,
    SpanEstimate,
    SpanEstimatorConfig,
    _contiguous_segments,
    estimate_spans,
    load_config,
    load_run_inputs,
)
from .run_loader import load_manifest
from .timebase import RP2040_TIMER0_MICROS_WRAP_TICKS, unwrap_ticks


TOOL_VERSION = "pps_fixed_code_baseline_v1"
OUTPUT_DIR = ESTIMATOR_OUTPUT_DIR
OUTPUT_NAME = "fixed_code_baseline_analysis_v1.json"

METRIC_PROVENANCE = {
    "population_standard_deviation": {
        "calculation": "sqrt(sum((x-mean(x))^2)/N) over the reported finite-run estimator outputs",
        "authority": "characterization only; not calibrated uncertainty or isolated firmware jitter",
    },
    "median_absolute_deviation": {
        "calculation": "median(abs(x-median(x))) over the reported finite-run estimator outputs",
        "authority": "characterization only; no acceptance threshold",
    },
    "robust_scale_1p4826_mad": {
        "calculation": "1.4826 multiplied by median absolute deviation; normal-consistency conversion",
        "authority": "characterization only; the conversion does not establish normality, independence, calibrated uncertainty, or a control threshold",
    },
    "finite_run_range": {
        "calculation": "maximum observed value minus minimum observed value",
        "authority": "direct finite-run characterization only; not a population or guaranteed bound",
    },
    "overlapping_allan_deviation": {
        "calculation": "sqrt(mean((successive tau-averages differ)^2)/2) within each exact continuous accepted segment; no detrend",
        "authority": "stability characterization only; reference and aperture uncertainty remain unavailable",
    },
    "linear_drift": {
        "calculation": "ordinary least-squares frequency slope versus nominal accepted-interval time",
        "authority": "characterization only; no causal attribution or extrapolation guarantee",
    },
    "near_air_temperature_association": {
        "calculation": "linear interpolation between bracketing SHT41 near-air samples, followed by Pearson association and temperature/time confounding diagnostics",
        "authority": "characterization only; not CX317 case/oven temperature, causality, a sensitivity coefficient, or an applicability bound",
    },
    "service_plane_segment_comparison": {
        "calculation": "statistics for estimator windows wholly contained in manifest-declared quiet/load segments",
        "authority": "end-to-end characterization only; no isolated firmware-jitter attribution",
    },
}


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _median_absolute_deviation(values: list[float]) -> float | None:
    if not values:
        return None
    centre = statistics.median(values)
    return statistics.median(abs(value - centre) for value in values)


def _pearson(values_a: list[float], values_b: list[float]) -> float | None:
    if len(values_a) != len(values_b) or len(values_a) < 2:
        return None
    mean_a = statistics.fmean(values_a)
    mean_b = statistics.fmean(values_b)
    covariance = sum(
        (value_a - mean_a) * (value_b - mean_b)
        for value_a, value_b in zip(values_a, values_b, strict=True)
    )
    variance_a = sum((value - mean_a) ** 2 for value in values_a)
    variance_b = sum((value - mean_b) ** 2 for value in values_b)
    if variance_a == 0 or variance_b == 0:
        return None
    return covariance / math.sqrt(variance_a * variance_b)


def _temperature_correlation_metrics(
    frequencies_hz: list[float],
    temperatures_c: list[float],
    elapsed_markers: list[float],
) -> dict[str, float | None]:
    """Return diagnostic associations without assigning thermal causality.

    Elapsed markers may be nominal seconds or monotonically increasing count
    sequences because Pearson correlation is invariant to affine scaling.  The
    simple R-squared value is descriptive only; it is not a thermal model or a
    guaranteed applicability limit.
    """

    frequency_temperature = _pearson(frequencies_hz, temperatures_c)
    return {
        "pearson_frequency_temperature_correlation": frequency_temperature,
        "simple_frequency_temperature_r_squared": (
            frequency_temperature * frequency_temperature
            if frequency_temperature is not None
            else None
        ),
        "pearson_temperature_elapsed_correlation": _pearson(
            temperatures_c, elapsed_markers
        ),
    }


def summarize_spans(estimates: Iterable[SpanEstimate]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], list[SpanEstimate]] = defaultdict(list)
    for estimate in estimates:
        grouped[(estimate.mode, estimate.span_seconds)].append(estimate)
    nonoverlap_counts = {
        span_s: len(items)
        for (mode, span_s), items in grouped.items()
        if mode == "non_overlapping"
    }
    output: list[dict[str, Any]] = []
    for (mode, span_s), items in grouped.items():
        values = [item.authoritative_frequency_hz for item in items]
        mad = _median_absolute_deviation(values)
        output.append(
            {
                "mode": mode,
                "span_seconds": span_s,
                "eligible_estimate_count": len(items),
                "effective_independent_estimate_count": (
                    len(items)
                    if mode == "non_overlapping"
                    else nonoverlap_counts.get(span_s, 0)
                ),
                "independent_control_decisions": mode == "non_overlapping",
                "count_increment_hz": items[0].count_increment_hz,
                "mean_hz": statistics.fmean(values),
                "median_hz": statistics.median(values),
                "population_stddev_hz": (
                    statistics.pstdev(values) if len(values) > 1 else 0.0
                ),
                "median_absolute_deviation_hz": mad,
                "robust_scale_1p4826_mad_hz": (
                    1.4826 * mad if mad is not None else None
                ),
                "minimum_hz": min(values),
                "maximum_hz": max(values),
                "range_hz": max(values) - min(values),
                "lag1_correlation": _pearson(values[:-1], values[1:]),
                "correlation_note": (
                    "overlapping estimates are correlated analysis outputs and are not independent decisions"
                    if mode == "overlapping"
                    else "lag-1 correlation is characterization only"
                ),
            }
        )
    return output


def _allan_terms(values: list[float], averaging_intervals: int) -> list[float]:
    if averaging_intervals <= 0 or len(values) < 2 * averaging_intervals:
        return []
    prefix = [0.0]
    for value in values:
        prefix.append(prefix[-1] + value)
    terms: list[float] = []
    for start in range(len(values) - 2 * averaging_intervals + 1):
        first = (
            prefix[start + averaging_intervals] - prefix[start]
        ) / averaging_intervals
        second = (
            prefix[start + 2 * averaging_intervals]
            - prefix[start + averaging_intervals]
        ) / averaging_intervals
        terms.append((second - first) ** 2)
    return terms


def allan_deviation(
    intervals: Iterable[IntervalEvidence],
    config: SpanEstimatorConfig,
    nominal_frequency_hz: float | None,
) -> list[dict[str, Any]]:
    segments = _contiguous_segments(intervals)
    output: list[dict[str, Any]] = []
    for span_s in config.candidate_spans_s:
        averaging_intervals = int(
            round(span_s / config.nominal_reference_interval_s)
        )
        terms: list[float] = []
        for segment in segments:
            values = [
                item.interval_counted_edges / config.nominal_reference_interval_s
                for item in segment
            ]
            terms.extend(_allan_terms(values, averaging_intervals))
        absolute = math.sqrt(sum(terms) / (2.0 * len(terms))) if terms else None
        output.append(
            {
                "tau_s": span_s,
                "averaging_intervals": averaging_intervals,
                "difference_term_count": len(terms),
                "overlapping_allan_deviation_hz": absolute,
                "overlapping_allan_deviation_fractional": (
                    absolute / nominal_frequency_hz
                    if absolute is not None
                    and nominal_frequency_hz is not None
                    and nominal_frequency_hz > 0
                    else None
                ),
                "preprocessing": "none; no detrend; continuous accepted segments evaluated separately",
            }
        )
    return output


def _span_continuity_reasons(window: tuple[IntervalEvidence, ...]) -> set[str]:
    reasons: set[str] = set()
    for interval in window:
        reasons.update(interval.reasons)
        if interval.settling_excluded:
            reasons.add("settling_excluded")
        if not interval.valid and not interval.reasons:
            reasons.add("interval_invalid_unspecified")
    for opening, closing in zip(window, window[1:]):
        if opening.session_id != closing.session_id:
            reasons.add("session_boundary")
        if opening.closing_snapshot_sequence != closing.opening_snapshot_sequence:
            reasons.add("snapshot_sequence_discontinuity")
        if (
            opening.closing_reference_event_sequence
            != closing.opening_reference_event_sequence
        ):
            reasons.add("reference_sequence_discontinuity")
        if opening.control_epoch != closing.control_epoch:
            reasons.add("control_epoch_boundary")
    return reasons


def withheld_span_windows(
    intervals: tuple[IntervalEvidence, ...], config: SpanEstimatorConfig
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for span_s in config.candidate_spans_s:
        required = int(round(span_s / config.nominal_reference_interval_s))
        candidates = max(0, len(intervals) - required + 1)
        withheld = 0
        reasons: Counter[str] = Counter()
        for start in range(candidates):
            window = intervals[start : start + required]
            window_reasons = _span_continuity_reasons(window)
            if window_reasons:
                withheld += 1
                reasons.update(window_reasons)
        output.append(
            {
                "span_seconds": span_s,
                "overlapping_candidate_window_count": candidates,
                "eligible_window_count": candidates - withheld,
                "withheld_window_count": withheld,
                "withheld_reason_window_counts": dict(sorted(reasons.items())),
                "clean_time_to_first_estimate_s": span_s,
                "fresh_support_recovery_time_s": span_s,
            }
        )
    return output


def _linear_drift(intervals: tuple[IntervalEvidence, ...], config: SpanEstimatorConfig) -> dict[str, Any]:
    segments = _contiguous_segments(intervals)
    if len(segments) != 1 or len(segments[0]) < 2:
        return {
            "status": "unavailable",
            "reason": "requires_exactly_one_continuous_segment_with_at_least_two_intervals",
            "slope_hz_per_s": None,
        }
    values = [
        item.interval_counted_edges / config.nominal_reference_interval_s
        for item in segments[0]
    ]
    times = [
        (index + 0.5) * config.nominal_reference_interval_s
        for index in range(len(values))
    ]
    mean_t = statistics.fmean(times)
    mean_y = statistics.fmean(values)
    denominator = sum((value - mean_t) ** 2 for value in times)
    slope = sum(
        (time - mean_t) * (value - mean_y)
        for time, value in zip(times, values, strict=True)
    ) / denominator
    return {
        "status": "characterization_only",
        "method": "ordinary least squares versus nominal accepted-interval time; no causal attribution",
        "sample_count": len(values),
        "slope_hz_per_s": slope,
        "slope_hz_per_hour": slope * 3600.0,
    }


def span_linear_drift(
    estimates: Iterable[SpanEstimate], config: SpanEstimatorConfig
) -> list[dict[str, Any]]:
    """Report drift separately for every estimator mode/span.

    A regression is withheld when an output series crosses a continuity,
    session, or control-epoch boundary.  Overlapping results remain explicitly
    correlated characterization rather than independent evidence.
    """

    grouped: dict[tuple[str, int], list[SpanEstimate]] = defaultdict(list)
    for estimate in estimates:
        grouped[(estimate.mode, estimate.span_seconds)].append(estimate)
    output: list[dict[str, Any]] = []
    for (mode, span_s), items in sorted(grouped.items()):
        expected_step = (
            1
            if mode == "overlapping"
            else int(round(span_s / config.nominal_reference_interval_s))
        )
        continuous = all(
            opening.session_id == closing.session_id
            and opening.control_epoch == closing.control_epoch
            and closing.last_cnt_sequence - opening.last_cnt_sequence
            == expected_step
            for opening, closing in zip(items, items[1:])
        )
        if len(items) < 2 or not continuous:
            output.append(
                {
                    "mode": mode,
                    "span_seconds": span_s,
                    "status": "unavailable",
                    "reason": (
                        "fewer_than_two_estimates"
                        if len(items) < 2
                        else "estimate_series_not_exactly_continuous"
                    ),
                    "sample_count": len(items),
                    "slope_hz_per_s": None,
                    "slope_hz_per_hour": None,
                }
            )
            continue
        times = [
            (item.last_cnt_sequence - items[0].last_cnt_sequence)
            * config.nominal_reference_interval_s
            for item in items
        ]
        values = [item.authoritative_frequency_hz for item in items]
        mean_t = statistics.fmean(times)
        mean_y = statistics.fmean(values)
        denominator = sum((value - mean_t) ** 2 for value in times)
        slope = sum(
            (time - mean_t) * (value - mean_y)
            for time, value in zip(times, values, strict=True)
        ) / denominator
        output.append(
            {
                "mode": mode,
                "span_seconds": span_s,
                "status": "characterization_only",
                "method": "ordinary least squares versus nominal accepted-interval time; no causal attribution",
                "sample_count": len(items),
                "correlated_outputs": mode == "overlapping",
                "slope_hz_per_s": slope,
                "slope_hz_per_hour": slope * 3600.0,
            }
        )
    return output


def select_declared_analysis_intervals(
    intervals: tuple[IntervalEvidence, ...], manifest_data: dict[str, Any]
) -> tuple[tuple[IntervalEvidence, ...], dict[str, Any]]:
    """Restrict a fixed-code run to its manifest-declared stable interval.

    Stage 3 evidence must not silently mix the required warmup with the stable
    analysis interval.  Non-Stage-3 inputs remain usable for preparation and
    regression comparisons, but their undeclared scope is labelled explicitly.
    """

    baseline = manifest_data.get("cx317_fixed_code_baseline")
    baseline_data = baseline if isinstance(baseline, dict) else {}
    first = baseline_data.get("declared_stable_first_count_seq")
    last = baseline_data.get("declared_stable_last_count_seq")
    requires_declaration = manifest_data.get("stage") == "CX317_FIXED_CODE_BASELINE"
    if first is None or last is None:
        if requires_declaration:
            raise ValueError(
                "CX317 fixed-code baseline requires declared stable first/last count sequences"
            )
        return intervals, {
            "status": "not_declared_non_stage3_input",
            "first_count_sequence": None,
            "last_count_sequence": None,
            "interval_count": len(intervals),
            "warmup_excluded": False,
        }
    if (
        isinstance(first, bool)
        or isinstance(last, bool)
        or not isinstance(first, int)
        or not isinstance(last, int)
        or first < 0
        or last < first
    ):
        raise ValueError("declared stable count-sequence bounds are invalid")
    selected = tuple(
        interval for interval in intervals if first <= interval.cnt_sequence <= last
    )
    expected_sequences = list(range(first, last + 1))
    observed_sequences = [interval.cnt_sequence for interval in selected]
    if observed_sequences != expected_sequences:
        raise ValueError(
            "declared stable interval is not present as one exact continuous count-sequence range"
        )
    return selected, {
        "status": "manifest_declared_stable_interval",
        "first_count_sequence": first,
        "last_count_sequence": last,
        "interval_count": len(selected),
        "warmup_first_count_sequence": baseline_data.get(
            "declared_warmup_first_count_seq"
        ),
        "warmup_last_count_sequence": baseline_data.get(
            "declared_warmup_last_count_seq"
        ),
        "warmup_excluded": True,
    }


def _service_plane_summary(
    estimates: tuple[SpanEstimate, ...], manifest_data: dict[str, Any]
) -> list[dict[str, Any]]:
    phase5 = manifest_data.get("phase5_pps_backend_qualification", {})
    segments = phase5.get("service_plane_segments", []) if isinstance(phase5, dict) else []
    output: list[dict[str, Any]] = []
    for segment in segments if isinstance(segments, list) else []:
        try:
            first = int(segment["first_count_seq"])
            last = int(segment["last_count_seq"])
            label = str(segment["label"])
            service_mode = str(segment["mode"])
        except (KeyError, TypeError, ValueError):
            continue
        selected: dict[tuple[str, int], list[float]] = defaultdict(list)
        for estimate in estimates:
            if estimate.first_cnt_sequence >= first and estimate.last_cnt_sequence <= last:
                selected[(estimate.mode, estimate.span_seconds)].append(
                    estimate.authoritative_frequency_hz
                )
        for (mode, span_s), values in selected.items():
            output.append(
                {
                    "label": label,
                    "service_mode": service_mode,
                    "first_count_sequence": first,
                    "last_count_sequence": last,
                    "estimator_mode": mode,
                    "span_seconds": span_s,
                    "estimate_count": len(values),
                    "mean_hz": statistics.fmean(values),
                    "population_stddev_hz": (
                        statistics.pstdev(values) if len(values) > 1 else 0.0
                    ),
                    "attribution_note": "end-to-end characterization; no isolated firmware-jitter attribution",
                }
            )
    return output


def _environment_path(manifest: Any) -> Path | None:
    matches = [
        manifest.root / str(item["path"])
        for item in manifest.files
        if item.get("contract") == "environment_v1"
        and (manifest.root / str(item["path"])).is_file()
    ]
    return matches[0] if len(matches) == 1 else None


def _align_modulo_timestamps(reference: list[int], other: list[int]) -> list[int]:
    if not reference or not other:
        return other
    reference_mid = (reference[0] + reference[-1]) / 2.0
    other_mid = (other[0] + other[-1]) / 2.0
    offset_wraps = round(
        (reference_mid - other_mid) / RP2040_TIMER0_MICROS_WRAP_TICKS
    )
    offset = offset_wraps * RP2040_TIMER0_MICROS_WRAP_TICKS
    return [value + offset for value in other]


def _interpolated_temperature(
    tick: int, environment_ticks: list[int], temperatures: list[float]
) -> float | None:
    right = bisect_right(environment_ticks, tick)
    if right == 0 or right == len(environment_ticks):
        return None
    left = right - 1
    opening_tick = environment_ticks[left]
    closing_tick = environment_ticks[right]
    if closing_tick == opening_tick:
        return None
    fraction = (tick - opening_tick) / (closing_tick - opening_tick)
    return temperatures[left] + fraction * (
        temperatures[right] - temperatures[left]
    )


def _near_temperature_samples(
    environment_path: Path, manifest: Any
) -> tuple[list[int], list[float]]:
    validation = validate_csv(
        environment_path,
        CsvValidationContext(
            contract="environment_v1",
            known_channels=manifest.known_channels,
            known_domains=manifest.known_domains,
            template=manifest.is_template,
            allow_rp2040_timer0_wrap=True,
        ),
    )
    if validation.errors:
        raise ValueError(f"{environment_path}: " + "; ".join(validation.errors))
    with environment_path.open("r", newline="", encoding="utf-8") as handle:
        rows = [
            row
            for row in csv.DictReader(handle)
            if row["role"] == "vcocxo_near" and row["temperature_c"].strip()
        ]
    ticks, _ = unwrap_ticks([int(row["timestamp_ticks"]) for row in rows])
    temperatures = [float(row["temperature_c"]) for row in rows]
    return ticks, temperatures


def _temperature_association(
    intervals: tuple[IntervalEvidence, ...],
    config: SpanEstimatorConfig,
    environment_path: Path | None,
    manifest: Any,
) -> tuple[dict[str, Any], dict[str, str]]:
    if environment_path is None:
        return (
            {
                "status": "unavailable",
                "reason": "environment_v1_source_unavailable",
                "paired_sample_count": 0,
            },
            {},
        )
    environment_ticks, temperatures = _near_temperature_samples(
        environment_path, manifest
    )
    if len(environment_ticks) < 2:
        return (
            {
                "status": "unavailable",
                "reason": "fewer_than_two_near_vcocxo_temperature_samples",
                "paired_sample_count": 0,
            },
            {"environment": _sha256_file(environment_path)},
        )
    valid_intervals = [item for item in intervals if item.effective_valid]
    interval_ticks, _ = unwrap_ticks(
        [item.closing_reference_timestamp_ticks for item in valid_intervals]
    )
    environment_ticks = _align_modulo_timestamps(interval_ticks, environment_ticks)
    paired_frequency: list[float] = []
    paired_temperature: list[float] = []
    paired_elapsed: list[float] = []
    for elapsed_index, (interval, tick) in enumerate(
        zip(valid_intervals, interval_ticks, strict=True)
    ):
        temperature = _interpolated_temperature(
            tick, environment_ticks, temperatures
        )
        if temperature is None:
            continue
        paired_frequency.append(
            interval.interval_counted_edges / config.nominal_reference_interval_s
        )
        paired_temperature.append(temperature)
        paired_elapsed.append(
            elapsed_index * config.nominal_reference_interval_s
        )
    correlation_metrics = _temperature_correlation_metrics(
        paired_frequency, paired_temperature, paired_elapsed
    )
    return (
        {
            "status": (
                "characterization_only"
                if len(paired_frequency) >= 2
                else "unavailable"
            ),
            "reason": (
                "linear_interpolation_between_bracketing_vcocxo_near_samples"
                if len(paired_frequency) >= 2
                else "fewer_than_two_frequency_temperature_pairs"
            ),
            "paired_sample_count": len(paired_frequency),
            "temperature_min_c": (
                min(paired_temperature) if paired_temperature else None
            ),
            "temperature_max_c": (
                max(paired_temperature) if paired_temperature else None
            ),
            **correlation_metrics,
            "causal_attribution": False,
            "sensor_uncertainty_status": "unavailable",
            "interpretation": "near-air association and temperature/time confounding are characterization only; the observed temperature range is context, not a demonstrated CX317 sensitivity bound",
        },
        {"environment": _sha256_file(environment_path)},
    )


def temperature_association_by_span(
    intervals: tuple[IntervalEvidence, ...],
    estimates: Iterable[SpanEstimate],
    environment_path: Path | None,
    manifest: Any,
) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], list[SpanEstimate]] = defaultdict(list)
    for estimate in estimates:
        grouped[(estimate.mode, estimate.span_seconds)].append(estimate)
    if not grouped:
        return []
    if environment_path is None:
        return [
            {
                "mode": mode,
                "span_seconds": span_s,
                "status": "unavailable",
                "reason": "environment_v1_source_unavailable",
                "paired_sample_count": 0,
            }
            for mode, span_s in sorted(grouped)
        ]
    environment_ticks, temperatures = _near_temperature_samples(
        environment_path, manifest
    )
    if len(environment_ticks) < 2:
        return [
            {
                "mode": mode,
                "span_seconds": span_s,
                "status": "unavailable",
                "reason": "fewer_than_two_near_vcocxo_temperature_samples",
                "paired_sample_count": 0,
            }
            for mode, span_s in sorted(grouped)
        ]
    valid_intervals = [item for item in intervals if item.effective_valid]
    interval_ticks, _ = unwrap_ticks(
        [item.closing_reference_timestamp_ticks for item in valid_intervals]
    )
    ticks_by_count_sequence = {
        int(interval.cnt_sequence): tick
        for interval, tick in zip(valid_intervals, interval_ticks, strict=True)
        if interval.cnt_sequence is not None
    }
    environment_ticks = _align_modulo_timestamps(interval_ticks, environment_ticks)
    output: list[dict[str, Any]] = []
    for (mode, span_s), items in sorted(grouped.items()):
        paired_frequency: list[float] = []
        paired_temperature: list[float] = []
        paired_elapsed: list[float] = []
        for estimate in items:
            tick = ticks_by_count_sequence.get(estimate.last_cnt_sequence)
            if tick is None:
                continue
            temperature = _interpolated_temperature(
                tick, environment_ticks, temperatures
            )
            if temperature is None:
                continue
            paired_frequency.append(estimate.authoritative_frequency_hz)
            paired_temperature.append(temperature)
            paired_elapsed.append(float(estimate.last_cnt_sequence))
        correlation_metrics = _temperature_correlation_metrics(
            paired_frequency, paired_temperature, paired_elapsed
        )
        output.append(
            {
                "mode": mode,
                "span_seconds": span_s,
                "status": (
                    "characterization_only"
                    if len(paired_frequency) >= 2
                    else "unavailable"
                ),
                "reason": (
                    "linear_interpolation_at_estimate_closing_boundary"
                    if len(paired_frequency) >= 2
                    else "fewer_than_two_frequency_temperature_pairs"
                ),
                "paired_sample_count": len(paired_frequency),
                "temperature_min_c": (
                    min(paired_temperature) if paired_temperature else None
                ),
                "temperature_max_c": (
                    max(paired_temperature) if paired_temperature else None
                ),
                **correlation_metrics,
                "correlated_outputs": mode == "overlapping",
                "causal_attribution": False,
                "sensor_uncertainty_status": "unavailable",
                "interpretation": "near-air association and temperature/time confounding are characterization only; the observed temperature range is context, not a demonstrated CX317 sensitivity bound",
            }
        )
    return output


def analyze_baseline(
    run_dir: Path,
    *,
    config_path: Path = DEFAULT_CONFIG,
    interval_policy_path: Path | None = None,
    output_path: Path | None = None,
) -> Path:
    config = load_config(config_path)
    inputs: RunInputs = load_run_inputs(
        run_dir, config, interval_policy_path=interval_policy_path
    )
    manifest = load_manifest(run_dir)
    analysis_intervals, analysis_interval = select_declared_analysis_intervals(
        inputs.intervals, manifest.data
    )
    estimates = estimate_spans(analysis_intervals, config)
    oscillator = manifest.data.get("oscillator", {})
    nominal_frequency = (
        float(oscillator["nominal_frequency_hz"])
        if isinstance(oscillator, dict)
        and isinstance(oscillator.get("nominal_frequency_hz"), (int, float))
        and float(oscillator["nominal_frequency_hz"]) > 0
        else None
    )
    environment_path = _environment_path(manifest)
    temperature, extra_hashes = _temperature_association(
        analysis_intervals, config, environment_path, manifest
    )
    source_hashes = dict(inputs.source_hashes)
    source_paths = dict(inputs.source_paths)
    if environment_path is not None:
        source_paths["environment"] = environment_path
        source_hashes.update(extra_hashes)
    invalid_reasons = Counter(
        reason
        for interval in analysis_intervals
        if not interval.effective_valid
        for reason in (
            interval.reasons
            or (("settling_excluded",) if interval.settling_excluded else ("interval_invalid_unspecified",))
        )
    )
    report = {
        "schema_version": 1,
        "tool_version": TOOL_VERSION,
        "run_id": manifest.run_id,
        "method_id": config.method_id,
        "config_hash": config.config_hash,
        "source_evidence": {
            name: {"path": str(path), "sha256": source_hashes[name]}
            for name, path in source_paths.items()
        },
        "source_immutability_verified": True,
        "metric_provenance": METRIC_PROVENANCE,
        "authoritative_denominator": "nominal accepted PPS interval count; timer normalization diagnostic-only",
        "raw_snapshot_count": inputs.raw_snapshot_count,
        "full_run_valid_adjacent_interval_count": inputs.valid_adjacent_interval_count,
        "full_run_invalid_interval_count": inputs.invalid_interval_count,
        "analysis_interval": analysis_interval,
        "valid_adjacent_interval_count": sum(
            interval.effective_valid for interval in analysis_intervals
        ),
        "invalid_interval_count": sum(
            not interval.effective_valid for interval in analysis_intervals
        ),
        "invalid_interval_reason_counts": dict(sorted(invalid_reasons.items())),
        "span_statistics": summarize_spans(estimates),
        "withheld_span_windows": withheld_span_windows(analysis_intervals, config),
        "stability": {
            "method": "overlapping Allan deviation of accepted one-second absolute-frequency observations, separated at continuity boundaries",
            "nominal_frequency_hz": nominal_frequency,
            "results": allan_deviation(
                analysis_intervals, config, nominal_frequency
            ),
        },
        "linear_drift": {
            "raw_one_second_intervals": _linear_drift(
                analysis_intervals, config
            ),
            "by_estimator_span": span_linear_drift(estimates, config),
        },
        "temperature_association": {
            "raw_one_second_intervals": temperature,
            "by_estimator_span": temperature_association_by_span(
                analysis_intervals, estimates, environment_path, manifest
            ),
        },
        "service_plane_segments": _service_plane_summary(
            estimates, manifest.data
        ),
        "uncertainty_status": "unavailable",
        "uncertainty_reason_codes": [
            "counter_aperture_uncertainty_unavailable",
            "reference_uncertainty_unavailable",
            "calibration_uncertainty_unavailable",
            "environmental_causality_unavailable",
        ],
        "selection_status": "not_selected_by_stage3_analysis",
    }
    destination = output_path or run_dir / OUTPUT_DIR / OUTPUT_NAME
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(report, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(destination)
    if {
        name: _sha256_file(path) for name, path in source_paths.items()
    } != source_hashes:
        destination.unlink(missing_ok=True)
        raise RuntimeError("source evidence changed while writing baseline analysis")
    return destination


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Characterize a fixed-code cumulative-PPS baseline without selecting a controller."
    )
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--interval-policy", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    try:
        destination = analyze_baseline(
            args.run_dir,
            config_path=args.config,
            interval_policy_path=args.interval_policy,
            output_path=args.output,
        )
    except (
        FileNotFoundError,
        ValueError,
        OverflowError,
        RuntimeError,
        json.JSONDecodeError,
    ) as exc:
        parser.error(str(exc))
    print(destination)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
