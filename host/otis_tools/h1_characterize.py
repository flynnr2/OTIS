from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import argparse
import csv
import math
import struct
import sys
import zlib

from .run_loader import RunManifest, load_manifest
from .timebase import RP2040_TIMER0_MICROS_WRAP_TICKS


COUNT_CONTRACT = "count_observations_v1"
DAC_CONTRACT = "dac_steps_v1"
DEFAULT_SETTLING_DISCARD_SECONDS = 0.0
DEFAULT_WARMUP_SECONDS = 1800.0
DEFAULT_STABILITY_PPM = 0.1


@dataclass(frozen=True)
class CountWindow:
    seq: int
    elapsed_s: float
    gate_seconds: float
    counted_edges: int
    measured_hz: float
    ppm: float | None


@dataclass(frozen=True)
class DacEvent:
    seq: int
    elapsed_s: float
    step_index: int
    code: int
    voltage_v: float | None
    dwell_s: float | None
    event: str


@dataclass(frozen=True)
class CharacterizationPoint:
    group_id: str
    step_index: int | None
    dac_code: int | None
    voltage_v: float | None
    direction: str
    discarded_count: int
    sample_count: int
    elapsed_start_s: float | None
    elapsed_end_s: float | None
    median_hz: float | None
    mean_hz: float | None
    stddev_hz: float | None
    mad_hz: float | None
    iqr_hz: float | None
    median_ppm: float | None
    mean_ppm: float | None
    stddev_ppm: float | None
    mad_ppm: float | None
    iqr_ppm: float | None


@dataclass(frozen=True)
class SlopePoint:
    from_code: int | None
    to_code: int | None
    from_voltage_v: float | None
    to_voltage_v: float | None
    hz_per_v: float | None
    ppm_per_v: float | None
    hz_per_code: float | None
    ppm_per_code: float | None


@dataclass(frozen=True)
class SettlingEstimate:
    step_index: int
    from_code: int | None
    to_code: int | None
    baseline_hz: float | None
    final_hz: float | None
    response_50_s: float | None
    response_90_s: float | None
    response_95_s: float | None
    overshoot_percent: float | None
    residual_drift_hz_per_s: float | None
    note: str


@dataclass(frozen=True)
class WarmupEstimate:
    sample_count: int
    initial_frequency_hz: float | None
    initial_ppm: float | None
    total_elapsed_s: float | None
    drift_after_warmup_hz_per_s: float | None
    drift_after_warmup_ppm_per_hour: float | None
    practical_stability_time_s: float | None
    note: str


@dataclass(frozen=True)
class HysteresisEstimate:
    code: int
    up_median_hz: float | None
    down_median_hz: float | None
    delta_hz: float | None
    repeated_center_span_hz: float | None
    note: str


@dataclass(frozen=True)
class H1Analysis:
    run_dir: Path
    manifest: RunManifest
    nominal_hz: float | None
    gate_hz_by_domain: dict[str, float]
    settling_discard_s: float
    warmup_s: float
    stability_ppm: float
    count_windows: tuple[CountWindow, ...]
    dac_events: tuple[DacEvent, ...]
    points: tuple[CharacterizationPoint, ...]
    slopes: tuple[SlopePoint, ...]
    settling: tuple[SettlingEstimate, ...]
    warmup: WarmupEstimate
    hysteresis: tuple[HysteresisEstimate, ...]
    warnings: tuple[str, ...]


def _parse_float(value: object) -> float | None:
    if value in (None, ""):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if math.isfinite(parsed) else None


def _parse_int(value: object) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(str(value), 0)
    except (TypeError, ValueError):
        return None


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _manifest_file(manifest: RunManifest, contract: str, fallback: str) -> Path:
    for entry in manifest.files:
        if entry.get("contract") == contract:
            return manifest.root / str(entry.get("path", fallback))
    return manifest.root / fallback


def _domain_hz(manifest: RunManifest) -> dict[str, float]:
    domains: dict[str, float] = {}
    for domain in manifest.data.get("domains", []):
        if not isinstance(domain, dict):
            continue
        nominal = _parse_float(domain.get("nominal_hz"))
        name = domain.get("name")
        if name and nominal:
            domains[str(name)] = nominal
    return domains


def _nominal_hz(manifest: RunManifest, override: float | None) -> float | None:
    if override:
        return override
    oscillator = manifest.data.get("oscillator")
    if isinstance(oscillator, dict):
        nominal = _parse_float(oscillator.get("nominal_frequency_hz"))
        if nominal:
            return nominal
    observation = manifest.data.get("observation_domain")
    if isinstance(observation, dict):
        nominal = _parse_float(observation.get("nominal_hz"))
        if nominal:
            return nominal
    for domain in manifest.data.get("domains", []):
        if isinstance(domain, dict) and domain.get("name") == "h1_ocxo_open_loop":
            nominal = _parse_float(domain.get("nominal_hz"))
            if nominal:
                return nominal
    return None


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    sorted_values = sorted(values)
    middle = len(sorted_values) // 2
    if len(sorted_values) % 2:
        return sorted_values[middle]
    return (sorted_values[middle - 1] + sorted_values[middle]) / 2.0


def _mean(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def _stddev(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    mean = sum(values) / len(values)
    return math.sqrt(sum((value - mean) ** 2 for value in values) / (len(values) - 1))


def _percentile(sorted_values: list[float], fraction: float) -> float | None:
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    index = fraction * (len(sorted_values) - 1)
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return sorted_values[lower]
    return sorted_values[lower] + (sorted_values[upper] - sorted_values[lower]) * (index - lower)


def _iqr(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    sorted_values = sorted(values)
    q1 = _percentile(sorted_values, 0.25)
    q3 = _percentile(sorted_values, 0.75)
    if q1 is None or q3 is None:
        return None
    return q3 - q1


def _mad(values: list[float]) -> float | None:
    median = _median(values)
    if median is None:
        return None
    return _median([abs(value - median) for value in values])


def _slope_xy(samples: list[tuple[float, float]]) -> float | None:
    if len(samples) < 2:
        return None
    xs = [sample[0] for sample in samples]
    ys = [sample[1] for sample in samples]
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    denominator = sum((x - x_mean) ** 2 for x in xs)
    if denominator == 0:
        return None
    return sum((x - x_mean) * (y - y_mean) for x, y in samples) / denominator


def _format(value: float | int | None, digits: int = 6) -> str:
    if value is None:
        return "unavailable"
    if isinstance(value, int):
        return str(value)
    if value == 0:
        return "0"
    if abs(value) >= 1000:
        return f"{value:.3f}"
    return f"{value:.{digits}g}"


def _load_counts(
    manifest: RunManifest,
    gate_hz_by_domain: dict[str, float],
    nominal_hz: float | None,
    warnings: list[str],
) -> tuple[CountWindow, ...]:
    rows = _read_csv(_manifest_file(manifest, COUNT_CONTRACT, "csv/cnt.csv"))
    segments: list[list[CountWindow]] = [[]]
    first_open_s: float | None = None
    previous_open_raw: int | None = None
    previous_seq: int | None = None
    tick_offset_by_domain: dict[str, int] = {}
    skipped_flagged_zero_count = 0
    for index, row in enumerate(rows, start=1):
        gate_open = _parse_int(row.get("gate_open_ticks"))
        gate_close = _parse_int(row.get("gate_close_ticks"))
        counted = _parse_int(row.get("counted_edges"))
        flags = _parse_int(row.get("flags")) or 0
        seq = _parse_int(row.get("count_seq")) or index
        gate_domain = str(row.get("gate_domain", ""))
        gate_hz = gate_hz_by_domain.get(gate_domain)
        if gate_open is None or gate_close is None or counted is None or not gate_hz:
            warnings.append(f"cnt.csv row {index}: skipped because count/window fields or gate domain nominal_hz are unavailable")
            continue
        if counted == 0 and flags:
            skipped_flagged_zero_count += 1
            continue
        if (
            previous_open_raw is not None
            and gate_domain == "rp2040_timer0"
            and gate_open < previous_open_raw
            and previous_open_raw - gate_open > RP2040_TIMER0_MICROS_WRAP_TICKS // 2
        ):
            tick_offset_by_domain[gate_domain] = tick_offset_by_domain.get(gate_domain, 0) + RP2040_TIMER0_MICROS_WRAP_TICKS
        offset = tick_offset_by_domain.get(gate_domain, 0)
        gate_open_unwrapped = gate_open + offset
        gate_close_unwrapped = gate_close + offset
        if previous_seq is not None and seq <= previous_seq:
            warnings.append(f"cnt.csv row {index}: detected count_seq reset; starting a new analysis segment")
            segments.append([])
            first_open_s = None
            tick_offset_by_domain = {}
            offset = 0
            gate_open_unwrapped = gate_open
            gate_close_unwrapped = gate_close
        previous_open_raw = gate_open
        previous_seq = seq
        gate_seconds = (gate_close_unwrapped - gate_open_unwrapped) / gate_hz
        if gate_seconds <= 0:
            warnings.append(f"cnt.csv row {index}: skipped because gate window is non-positive")
            continue
        midpoint_s = ((gate_open_unwrapped + gate_close_unwrapped) / 2.0) / gate_hz
        if first_open_s is None:
            first_open_s = gate_open_unwrapped / gate_hz
        elapsed_s = midpoint_s
        measured_hz = counted / gate_seconds
        ppm = 1_000_000.0 * (measured_hz - nominal_hz) / nominal_hz if nominal_hz else None
        segments[-1].append(
            CountWindow(
                seq=seq,
                elapsed_s=elapsed_s,
                gate_seconds=gate_seconds,
                counted_edges=counted,
                measured_hz=measured_hz,
                ppm=ppm,
            )
        )
    populated = [segment for segment in segments if segment]
    if skipped_flagged_zero_count:
        warnings.append(f"cnt.csv: skipped {skipped_flagged_zero_count} flagged zero-count observation(s)")
    if len(populated) > 1:
        warnings.append("cnt.csv: multiple capture segments detected; using the final segment for H1 characterization")
    return tuple(populated[-1] if populated else [])


def _load_dac_events(manifest: RunManifest) -> tuple[DacEvent, ...]:
    rows = _read_csv(_manifest_file(manifest, DAC_CONTRACT, "csv/dac_steps.csv"))
    events: list[DacEvent] = []
    for index, row in enumerate(rows, start=1):
        code = _parse_int(row.get("dac_code_applied"))
        elapsed_ms = _parse_float(row.get("elapsed_ms"))
        if code is None or elapsed_ms is None:
            continue
        voltage = _parse_float(row.get("ocxo_tune_voltage_measured_v"))
        if voltage is None:
            voltage = _parse_float(row.get("dac_voltage_measured_v"))
        dwell_ms = _parse_float(row.get("dwell_ms"))
        events.append(
            DacEvent(
                seq=_parse_int(row.get("seq")) or index,
                elapsed_s=elapsed_ms / 1000.0,
                step_index=_parse_int(row.get("step_index")) or 0,
                code=code,
                voltage_v=voltage,
                dwell_s=dwell_ms / 1000.0 if dwell_ms is not None else None,
                event=str(row.get("event", "")),
            )
        )
    return tuple(sorted(events, key=lambda item: (item.elapsed_s, item.seq)))


def _direction(previous_code: int | None, current_code: int | None) -> str:
    if previous_code is None or current_code is None:
        return "unknown"
    if current_code > previous_code:
        return "up"
    if current_code < previous_code:
        return "down"
    return "repeat"


def _assigned_samples(
    counts: tuple[CountWindow, ...],
    events: tuple[DacEvent, ...],
) -> list[tuple[DacEvent | None, CountWindow]]:
    if not events:
        return [(None, count) for count in counts]
    assigned: list[tuple[DacEvent | None, CountWindow]] = []
    event_index = 0
    for count in counts:
        while event_index + 1 < len(events) and events[event_index + 1].elapsed_s <= count.elapsed_s:
            event_index += 1
        event = events[event_index] if events[event_index].elapsed_s <= count.elapsed_s else None
        assigned.append((event, count))
    return assigned


def _analysis_dwell_events(events: tuple[DacEvent, ...]) -> tuple[DacEvent, ...]:
    dwell_events = [event for event in events if event.event == "dwell_start"]
    if dwell_events:
        return tuple(dwell_events)
    non_step_events = {"fc0_window", "dwell_complete", "complete", "clear"}
    step_events = [event for event in events if event.step_index >= 0 and event.event not in non_step_events]
    return tuple(step_events)


def _summarize_group(
    group_id: str,
    step_index: int | None,
    code: int | None,
    voltage: float | None,
    direction: str,
    samples: list[CountWindow],
    discarded_count: int,
) -> CharacterizationPoint:
    hz_values = [sample.measured_hz for sample in samples]
    ppm_values = [sample.ppm for sample in samples if sample.ppm is not None]
    return CharacterizationPoint(
        group_id=group_id,
        step_index=step_index,
        dac_code=code,
        voltage_v=voltage,
        direction=direction,
        discarded_count=discarded_count,
        sample_count=len(samples),
        elapsed_start_s=min((sample.elapsed_s for sample in samples), default=None),
        elapsed_end_s=max((sample.elapsed_s for sample in samples), default=None),
        median_hz=_median(hz_values),
        mean_hz=_mean(hz_values),
        stddev_hz=_stddev(hz_values),
        mad_hz=_mad(hz_values),
        iqr_hz=_iqr(hz_values),
        median_ppm=_median(ppm_values),
        mean_ppm=_mean(ppm_values),
        stddev_ppm=_stddev(ppm_values),
        mad_ppm=_mad(ppm_values),
        iqr_ppm=_iqr(ppm_values),
    )


def _build_points(
    counts: tuple[CountWindow, ...],
    events: tuple[DacEvent, ...],
    settling_discard_s: float,
) -> tuple[CharacterizationPoint, ...]:
    analysis_events = _analysis_dwell_events(events)
    assigned = _assigned_samples(counts, analysis_events)
    if not analysis_events:
        return (
            _summarize_group("all_counts", None, None, None, "unknown", [sample for _, sample in assigned], 0),
        )

    points: list[CharacterizationPoint] = []
    previous_code: int | None = None
    for event in analysis_events:
        next_events = [candidate.elapsed_s for candidate in analysis_events if candidate.elapsed_s > event.elapsed_s]
        end_s = min(next_events) if next_events else None
        all_samples = [
            sample
            for assigned_event, sample in assigned
            if assigned_event == event and (end_s is None or sample.elapsed_s < end_s)
        ]
        kept = [sample for sample in all_samples if sample.elapsed_s >= event.elapsed_s + settling_discard_s]
        points.append(
            _summarize_group(
                group_id=f"step_{event.step_index}_{event.seq}",
                step_index=event.step_index,
                code=event.code,
                voltage=event.voltage_v,
                direction=_direction(previous_code, event.code),
                samples=kept,
                discarded_count=len(all_samples) - len(kept),
            )
        )
        previous_code = event.code
    return tuple(points)


def _build_slopes(points: tuple[CharacterizationPoint, ...]) -> tuple[SlopePoint, ...]:
    usable = [point for point in points if point.sample_count and point.median_hz is not None]
    slopes: list[SlopePoint] = []
    for previous, current in zip(usable, usable[1:]):
        delta_hz = current.median_hz - previous.median_hz
        delta_ppm = None
        if previous.median_ppm is not None and current.median_ppm is not None:
            delta_ppm = current.median_ppm - previous.median_ppm
        delta_code = None
        if previous.dac_code is not None and current.dac_code is not None:
            delta_code = current.dac_code - previous.dac_code
        delta_v = None
        if previous.voltage_v is not None and current.voltage_v is not None:
            delta_v = current.voltage_v - previous.voltage_v
        slopes.append(
            SlopePoint(
                from_code=previous.dac_code,
                to_code=current.dac_code,
                from_voltage_v=previous.voltage_v,
                to_voltage_v=current.voltage_v,
                hz_per_v=delta_hz / delta_v if delta_v not in (None, 0) else None,
                ppm_per_v=delta_ppm / delta_v if delta_ppm is not None and delta_v not in (None, 0) else None,
                hz_per_code=delta_hz / delta_code if delta_code not in (None, 0) else None,
                ppm_per_code=delta_ppm / delta_code if delta_ppm is not None and delta_code not in (None, 0) else None,
            )
        )
    return tuple(slopes)


def _threshold_time(samples: list[CountWindow], baseline: float, final: float, fraction: float, step_time_s: float) -> float | None:
    target = baseline + (final - baseline) * fraction
    increasing = final >= baseline
    for sample in samples:
        if (increasing and sample.measured_hz >= target) or (not increasing and sample.measured_hz <= target):
            return max(0.0, sample.elapsed_s - step_time_s)
    return None


def _settling(
    counts: tuple[CountWindow, ...],
    events: tuple[DacEvent, ...],
) -> tuple[SettlingEstimate, ...]:
    analysis_events = _analysis_dwell_events(events)
    if len(analysis_events) < 2 or len(counts) < 4:
        return (
            SettlingEstimate(
                step_index=0,
                from_code=None,
                to_code=None,
                baseline_hz=None,
                final_hz=None,
                response_50_s=None,
                response_90_s=None,
                response_95_s=None,
                overshoot_percent=None,
                residual_drift_hz_per_s=None,
                note="insufficient data: settling analysis requires DAC transitions and multiple count windows",
            ),
        )
    estimates: list[SettlingEstimate] = []
    for previous, current, next_event in zip(analysis_events, analysis_events[1:], list(analysis_events[2:]) + [None]):
        before = [sample for sample in counts if previous.elapsed_s <= sample.elapsed_s < current.elapsed_s]
        after_end = next_event.elapsed_s if next_event else math.inf
        after = [sample for sample in counts if current.elapsed_s <= sample.elapsed_s < after_end]
        if len(before) < 2 or len(after) < 3:
            estimates.append(
                SettlingEstimate(
                    step_index=current.step_index,
                    from_code=previous.code,
                    to_code=current.code,
                    baseline_hz=None,
                    final_hz=None,
                    response_50_s=None,
                    response_90_s=None,
                    response_95_s=None,
                    overshoot_percent=None,
                    residual_drift_hz_per_s=None,
                    note="insufficient data for this transition",
                )
            )
            continue
        baseline = _median([sample.measured_hz for sample in before[-max(2, len(before) // 2) :]])
        final_samples = after[-max(2, len(after) // 2) :]
        final = _median([sample.measured_hz for sample in final_samples])
        if baseline is None or final is None or baseline == final:
            note = "insufficient response amplitude"
            overshoot = None
        else:
            delta = final - baseline
            after_values = [sample.measured_hz for sample in after]
            extreme = max(after_values) if delta > 0 else min(after_values)
            overshoot = max(0.0, (extreme - final) / abs(delta) * 100.0) if delta > 0 else max(0.0, (final - extreme) / abs(delta) * 100.0)
            note = "estimated from median before-step baseline and last-half after-step final value"
        residual = _slope_xy([(sample.elapsed_s, sample.measured_hz) for sample in final_samples])
        estimates.append(
            SettlingEstimate(
                step_index=current.step_index,
                from_code=previous.code,
                to_code=current.code,
                baseline_hz=baseline,
                final_hz=final,
                response_50_s=_threshold_time(after, baseline, final, 0.50, current.elapsed_s) if baseline is not None and final is not None else None,
                response_90_s=_threshold_time(after, baseline, final, 0.90, current.elapsed_s) if baseline is not None and final is not None else None,
                response_95_s=_threshold_time(after, baseline, final, 0.95, current.elapsed_s) if baseline is not None and final is not None else None,
                overshoot_percent=overshoot,
                residual_drift_hz_per_s=residual,
                note=note,
            )
        )
    return tuple(estimates)


def _warmup(counts: tuple[CountWindow, ...], nominal_hz: float | None, warmup_s: float, stability_ppm: float) -> WarmupEstimate:
    if len(counts) < 3:
        return WarmupEstimate(len(counts), None, None, None, None, None, None, "insufficient data: warmup analysis requires at least 3 count windows")
    first = counts[0]
    total_elapsed = counts[-1].elapsed_s - counts[0].elapsed_s
    tail = [sample for sample in counts if sample.elapsed_s >= counts[0].elapsed_s + warmup_s]
    if len(tail) < 2:
        tail = list(counts[-max(2, len(counts) // 3) :])
        tail_note = "used final third because requested warmup window exceeds run duration"
    else:
        tail_note = f"used samples after {warmup_s:g} s"
    drift_hz_per_s = _slope_xy([(sample.elapsed_s, sample.measured_hz) for sample in tail])
    drift_ppm_per_hour = None
    if drift_hz_per_s is not None and nominal_hz:
        drift_ppm_per_hour = drift_hz_per_s * 3600.0 * 1_000_000.0 / nominal_hz

    stability_time = None
    if nominal_hz and all(sample.ppm is not None for sample in counts):
        for index, sample in enumerate(counts):
            remaining = [abs(candidate.ppm - counts[-1].ppm) for candidate in counts[index:] if candidate.ppm is not None and counts[-1].ppm is not None]
            if remaining and max(remaining) <= stability_ppm:
                stability_time = sample.elapsed_s - counts[0].elapsed_s
                break
    return WarmupEstimate(
        sample_count=len(counts),
        initial_frequency_hz=first.measured_hz,
        initial_ppm=first.ppm,
        total_elapsed_s=total_elapsed,
        drift_after_warmup_hz_per_s=drift_hz_per_s,
        drift_after_warmup_ppm_per_hour=drift_ppm_per_hour,
        practical_stability_time_s=stability_time,
        note=tail_note if stability_time is not None or nominal_hz else f"{tail_note}; ppm stability unavailable without nominal_hz",
    )


def _hysteresis(points: tuple[CharacterizationPoint, ...]) -> tuple[HysteresisEstimate, ...]:
    by_code: dict[int, list[CharacterizationPoint]] = {}
    for point in points:
        if point.dac_code is not None and point.sample_count and point.median_hz is not None:
            by_code.setdefault(point.dac_code, []).append(point)
    estimates: list[HysteresisEstimate] = []
    for code, code_points in sorted(by_code.items()):
        up = [point.median_hz for point in code_points if point.direction == "up" and point.median_hz is not None]
        down = [point.median_hz for point in code_points if point.direction == "down" and point.median_hz is not None]
        repeat = [point.median_hz for point in code_points if point.direction == "repeat" and point.median_hz is not None]
        up_median = _median(up)
        down_median = _median(down)
        repeated_span = max(repeat) - min(repeat) if len(repeat) >= 2 else None
        if up_median is None or down_median is None:
            note = "up/down comparison unavailable"
        else:
            note = "up/down medians compared at repeated DAC code"
        if repeated_span is not None:
            note += "; repeated-code span available"
        estimates.append(
            HysteresisEstimate(
                code=code,
                up_median_hz=up_median,
                down_median_hz=down_median,
                delta_hz=up_median - down_median if up_median is not None and down_median is not None else None,
                repeated_center_span_hz=repeated_span,
                note=note,
            )
        )
    return tuple(estimates)


def analyze_run(
    run_dir: Path,
    *,
    nominal_hz: float | None = None,
    settling_discard_s: float = DEFAULT_SETTLING_DISCARD_SECONDS,
    warmup_s: float = DEFAULT_WARMUP_SECONDS,
    stability_ppm: float = DEFAULT_STABILITY_PPM,
) -> H1Analysis:
    manifest = load_manifest(run_dir)
    warnings: list[str] = []
    resolved_nominal_hz = _nominal_hz(manifest, nominal_hz)
    if resolved_nominal_hz is None:
        warnings.append("nominal_hz unavailable; ppm and ppm-derived slopes are unavailable")
    gate_hz_by_domain = _domain_hz(manifest)
    counts = _load_counts(manifest, gate_hz_by_domain, resolved_nominal_hz, warnings)
    dac_events = _load_dac_events(manifest)
    if not dac_events:
        warnings.append("dac_steps.csv unavailable or empty; DAC-code grouping and voltage plots are limited")
    points = _build_points(counts, dac_events, settling_discard_s)
    return H1Analysis(
        run_dir=run_dir,
        manifest=manifest,
        nominal_hz=resolved_nominal_hz,
        gate_hz_by_domain=gate_hz_by_domain,
        settling_discard_s=settling_discard_s,
        warmup_s=warmup_s,
        stability_ppm=stability_ppm,
        count_windows=counts,
        dac_events=dac_events,
        points=points,
        slopes=_build_slopes(points),
        settling=_settling(counts, dac_events),
        warmup=_warmup(counts, resolved_nominal_hz, warmup_s, stability_ppm),
        hysteresis=_hysteresis(points),
        warnings=tuple(warnings),
    )


POINT_FIELDS = [
    "group_id",
    "step_index",
    "dac_code",
    "voltage_v",
    "direction",
    "discarded_count",
    "sample_count",
    "elapsed_start_s",
    "elapsed_end_s",
    "median_hz",
    "mean_hz",
    "stddev_hz",
    "mad_hz",
    "iqr_hz",
    "median_ppm",
    "mean_ppm",
    "stddev_ppm",
    "mad_ppm",
    "iqr_ppm",
]


def write_points_csv(analysis: H1Analysis, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=POINT_FIELDS)
        writer.writeheader()
        for point in analysis.points:
            writer.writerow({field: getattr(point, field) for field in POINT_FIELDS})


def _png_chunk(kind: bytes, data: bytes) -> bytes:
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def _write_png(path: Path, width: int, height: int, pixels: list[tuple[int, int, int]]) -> None:
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        start = y * width
        for red, green, blue in pixels[start : start + width]:
            raw.extend((red, green, blue))
    data = b"\x89PNG\r\n\x1a\n"
    data += _png_chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
    data += _png_chunk(b"IDAT", zlib.compress(bytes(raw), level=9))
    data += _png_chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def _set_pixel(pixels: list[tuple[int, int, int]], width: int, height: int, x: int, y: int, color: tuple[int, int, int]) -> None:
    if 0 <= x < width and 0 <= y < height:
        pixels[y * width + x] = color


def _draw_line(
    pixels: list[tuple[int, int, int]],
    width: int,
    height: int,
    x0: int,
    y0: int,
    x1: int,
    y1: int,
    color: tuple[int, int, int],
) -> None:
    dx = abs(x1 - x0)
    dy = -abs(y1 - y0)
    sx = 1 if x0 < x1 else -1
    sy = 1 if y0 < y1 else -1
    err = dx + dy
    while True:
        _set_pixel(pixels, width, height, x0, y0, color)
        if x0 == x1 and y0 == y1:
            break
        e2 = 2 * err
        if e2 >= dy:
            err += dy
            x0 += sx
        if e2 <= dx:
            err += dx
            y0 += sy


def _plot_xy(path: Path, samples: list[tuple[float, float]], *, connect: bool = True) -> bool:
    clean = [(x, y) for x, y in samples if math.isfinite(x) and math.isfinite(y)]
    if len(clean) < 2:
        return False
    width, height = 900, 540
    margin_left, margin_right, margin_top, margin_bottom = 70, 30, 30, 60
    pixels = [(255, 255, 255)] * (width * height)
    axis = (45, 55, 72)
    grid = (224, 228, 236)
    ink = (19, 102, 196)
    point = (185, 38, 42)
    x_values = [item[0] for item in clean]
    y_values = [item[1] for item in clean]
    x_min, x_max = min(x_values), max(x_values)
    y_min, y_max = min(y_values), max(y_values)
    if x_min == x_max:
        x_min -= 0.5
        x_max += 0.5
    if y_min == y_max:
        y_min -= 0.5
        y_max += 0.5
    y_pad = (y_max - y_min) * 0.08
    y_min -= y_pad
    y_max += y_pad

    def sx(value: float) -> int:
        return int(margin_left + (value - x_min) / (x_max - x_min) * (width - margin_left - margin_right))

    def sy(value: float) -> int:
        return int(height - margin_bottom - (value - y_min) / (y_max - y_min) * (height - margin_top - margin_bottom))

    for fraction in (0.0, 0.25, 0.5, 0.75, 1.0):
        x = int(margin_left + fraction * (width - margin_left - margin_right))
        y = int(margin_top + fraction * (height - margin_top - margin_bottom))
        _draw_line(pixels, width, height, x, margin_top, x, height - margin_bottom, grid)
        _draw_line(pixels, width, height, margin_left, y, width - margin_right, y, grid)
    _draw_line(pixels, width, height, margin_left, margin_top, margin_left, height - margin_bottom, axis)
    _draw_line(pixels, width, height, margin_left, height - margin_bottom, width - margin_right, height - margin_bottom, axis)

    mapped = [(sx(x), sy(y)) for x, y in clean]
    if connect:
        for previous, current in zip(mapped, mapped[1:]):
            _draw_line(pixels, width, height, previous[0], previous[1], current[0], current[1], ink)
    for x, y in mapped:
        for dx in range(-3, 4):
            for dy in range(-3, 4):
                if dx * dx + dy * dy <= 9:
                    _set_pixel(pixels, width, height, x + dx, y + dy, point)
    _write_png(path, width, height, pixels)
    return True


def write_plots(analysis: H1Analysis, plots_dir: Path) -> list[Path]:
    written: list[Path] = []
    dac_hz = [(float(point.dac_code), point.median_hz) for point in analysis.points if point.dac_code is not None and point.median_hz is not None]
    if _plot_xy(plots_dir / "dac_code_vs_hz.png", dac_hz, connect=False):
        written.append(plots_dir / "dac_code_vs_hz.png")
    voltage_ppm = [(point.voltage_v, point.median_ppm) for point in analysis.points if point.voltage_v is not None and point.median_ppm is not None]
    if _plot_xy(plots_dir / "dac_voltage_vs_ppm.png", voltage_ppm, connect=False):
        written.append(plots_dir / "dac_voltage_vs_ppm.png")
    settling = [(sample.elapsed_s, sample.measured_hz) for sample in analysis.count_windows]
    if analysis.dac_events and _plot_xy(plots_dir / "settling_response.png", settling, connect=True):
        written.append(plots_dir / "settling_response.png")
    warmup = [(sample.elapsed_s - analysis.count_windows[0].elapsed_s, sample.ppm if sample.ppm is not None else sample.measured_hz) for sample in analysis.count_windows] if analysis.count_windows else []
    if _plot_xy(plots_dir / "warmup_drift.png", warmup, connect=True):
        written.append(plots_dir / "warmup_drift.png")
    return written


def render_report(analysis: H1Analysis, written_plots: list[Path] | None = None) -> str:
    written_plots = written_plots or []
    lines: list[str] = [
        "# H1 Characterization Summary",
        "",
        "## Inputs",
        f"- run_id: {analysis.manifest.run_id}",
        f"- run_dir: {analysis.run_dir}",
        f"- nominal_hz: {_format(analysis.nominal_hz)}",
        f"- settling_discard_s: {_format(analysis.settling_discard_s)}",
        f"- warmup_s: {_format(analysis.warmup_s)}",
        f"- stability_ppm: {_format(analysis.stability_ppm)}",
        f"- count_windows: {len(analysis.count_windows)}",
        f"- dac_events: {len(analysis.dac_events)}",
        "",
        "## Formulas",
        "- measured_hz = counted_edges / gate_seconds",
        "- ppm = 1e6 * (measured_hz - nominal_hz) / nominal_hz",
        "- Hz/V = delta Hz / delta V",
        "- ppm/V = delta ppm / delta V",
        "- Hz/code and ppm/code are computed when voltage is unavailable.",
        "- settling_discard_s removes initial count windows in each DAC dwell before per-step summary statistics are computed.",
    ]
    if analysis.warnings:
        lines.extend(["", "## Warnings"])
        lines.extend(f"- {warning}" for warning in analysis.warnings)

    lines.extend(["", "## DAC Step Summaries"])
    if not analysis.points:
        lines.append("- unavailable: no count windows")
    for point in analysis.points:
        lines.append(
            f"- {point.group_id}: code={_format(point.dac_code)}, voltage_v={_format(point.voltage_v)}, "
            f"direction={point.direction}, windows={point.sample_count}, discarded={point.discarded_count}, "
            f"elapsed_s={_format(point.elapsed_start_s)}..{_format(point.elapsed_end_s)}, "
            f"median_hz={_format(point.median_hz)}, mean_hz={_format(point.mean_hz)}, "
            f"stddev_hz={_format(point.stddev_hz)}, MAD_hz={_format(point.mad_hz)}, IQR_hz={_format(point.iqr_hz)}, "
            f"median_ppm={_format(point.median_ppm)}"
        )

    lines.extend(["", "## Local Slopes"])
    usable_slopes = [slope for slope in analysis.slopes if any(value is not None for value in (slope.hz_per_v, slope.hz_per_code))]
    if not usable_slopes:
        lines.append("- unavailable: need at least two populated DAC/code summary points")
    for slope in usable_slopes:
        lines.append(
            f"- {_format(slope.from_code)} -> {_format(slope.to_code)}: "
            f"Hz/V={_format(slope.hz_per_v)}, ppm/V={_format(slope.ppm_per_v)}, "
            f"Hz/code={_format(slope.hz_per_code)}, ppm/code={_format(slope.ppm_per_code)}"
        )

    lines.extend(["", "## Settling Behavior"])
    for estimate in analysis.settling:
        lines.append(
            f"- step_index={estimate.step_index}, code={_format(estimate.from_code)}->{_format(estimate.to_code)}: "
            f"baseline_hz={_format(estimate.baseline_hz)}, final_hz={_format(estimate.final_hz)}, "
            f"t50_s={_format(estimate.response_50_s)}, t90_s={_format(estimate.response_90_s)}, "
            f"t95_s={_format(estimate.response_95_s)}, overshoot_percent={_format(estimate.overshoot_percent)}, "
            f"residual_drift_hz_per_s={_format(estimate.residual_drift_hz_per_s)}; {estimate.note}"
        )

    warmup = analysis.warmup
    lines.extend(
        [
            "",
            "## Warmup Drift",
            f"- samples: {warmup.sample_count}",
            f"- initial_frequency_hz: {_format(warmup.initial_frequency_hz)}",
            f"- initial_ppm: {_format(warmup.initial_ppm)}",
            f"- total_elapsed_s: {_format(warmup.total_elapsed_s)}",
            f"- drift_after_warmup_hz_per_s: {_format(warmup.drift_after_warmup_hz_per_s)}",
            f"- drift_after_warmup_ppm_per_hour: {_format(warmup.drift_after_warmup_ppm_per_hour)}",
            f"- practical_stability_time_s: {_format(warmup.practical_stability_time_s)}",
            f"- note: {warmup.note}",
        ]
    )

    lines.extend(["", "## Hysteresis / Sweep Direction"])
    if not analysis.hysteresis:
        lines.append("- unavailable: no repeated DAC-code summary points")
    for estimate in analysis.hysteresis:
        lines.append(
            f"- code={estimate.code}: up_median_hz={_format(estimate.up_median_hz)}, "
            f"down_median_hz={_format(estimate.down_median_hz)}, delta_hz={_format(estimate.delta_hz)}, "
            f"repeated_center_span_hz={_format(estimate.repeated_center_span_hz)}; {estimate.note}"
        )

    lines.extend(["", "## Generated Artifacts"])
    lines.append("- csv/h1_characterization_points.csv")
    if written_plots:
        lines.extend(f"- {path.relative_to(analysis.run_dir)}" for path in written_plots)
    else:
        lines.append("- plots: none generated; supported data was insufficient")

    open_loop_slope_known = any(
        (slope.hz_per_v is not None and abs(slope.hz_per_v) > 0.0)
        or (slope.hz_per_code is not None and abs(slope.hz_per_code) > 0.0)
        for slope in analysis.slopes
    )
    safe_voltage_window_known = _parse_float(analysis.manifest.data.get("safety_limits", {}).get("control_voltage_min_v") if isinstance(analysis.manifest.data.get("safety_limits"), dict) else None) is not None and _parse_float(analysis.manifest.data.get("safety_limits", {}).get("control_voltage_max_v") if isinstance(analysis.manifest.data.get("safety_limits"), dict) else None) is not None
    settling_known = open_loop_slope_known and any(
        estimate.baseline_hz is not None
        and estimate.final_hz is not None
        and abs(estimate.final_hz - estimate.baseline_hz) > 0.0
        and "estimated" in estimate.note
        for estimate in analysis.settling
    )
    warmup_known = warmup.drift_after_warmup_hz_per_s is not None and warmup.total_elapsed_s is not None and warmup.total_elapsed_s >= 60.0
    if not open_loop_slope_known:
        action = "capture a DAC sweep with repeated count windows at two or more DAC codes"
    elif not safe_voltage_window_known:
        action = "record measured safe OCXO tune voltage limits in the run manifest"
    elif not settling_known:
        action = "capture step-response dwell data long enough to estimate 90%/95% settling"
    elif not warmup_known:
        action = "capture a longer warmup/free-run dataset"
    else:
        action = "review anomalies manually before planning SW2 closed-loop experiments"
    lines.extend(
        [
            "",
            "## SW2 Readiness",
            f"- open_loop_slope_known: {str(open_loop_slope_known).lower()}",
            f"- safe_voltage_window_known: {str(safe_voltage_window_known).lower()}",
            f"- settling_time_characterized: {str(settling_known).lower()}",
            f"- warmup_characterized: {str(warmup_known).lower()}",
            f"- recommended_next_action: {action}",
        ]
    )
    return "\n".join(lines) + "\n"


def write_outputs(analysis: H1Analysis) -> tuple[Path, Path, list[Path]]:
    points_path = analysis.run_dir / "csv" / "h1_characterization_points.csv"
    report_path = analysis.run_dir / "reports" / "h1_characterization_summary.md"
    write_points_csv(analysis, points_path)
    plots = write_plots(analysis, analysis.run_dir / "plots")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(render_report(analysis, plots), encoding="utf-8")
    return report_path, points_path, plots


def characterize_run(
    run_dir: Path,
    *,
    nominal_hz: float | None = None,
    settling_discard_s: float = DEFAULT_SETTLING_DISCARD_SECONDS,
    warmup_s: float = DEFAULT_WARMUP_SECONDS,
    stability_ppm: float = DEFAULT_STABILITY_PPM,
) -> tuple[H1Analysis, Path, Path, list[Path]]:
    analysis = analyze_run(
        run_dir,
        nominal_hz=nominal_hz,
        settling_discard_s=settling_discard_s,
        warmup_s=warmup_s,
        stability_ppm=stability_ppm,
    )
    report_path, points_path, plots = write_outputs(analysis)
    return analysis, report_path, points_path, plots


def main() -> None:
    parser = argparse.ArgumentParser(description="Analyze H1 open-loop OCXO/DAC characterization runs.")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--nominal-hz", type=float, default=None, help="OCXO nominal frequency for ppm calculations.")
    parser.add_argument("--settling-discard-s", type=float, default=DEFAULT_SETTLING_DISCARD_SECONDS)
    parser.add_argument("--warmup-s", type=float, default=DEFAULT_WARMUP_SECONDS)
    parser.add_argument("--stability-ppm", type=float, default=DEFAULT_STABILITY_PPM)
    args = parser.parse_args()

    try:
        analysis, report_path, points_path, plots = characterize_run(
            args.run_dir,
            nominal_hz=args.nominal_hz,
            settling_discard_s=args.settling_discard_s,
            warmup_s=args.warmup_s,
            stability_ppm=args.stability_ppm,
        )
    except Exception as exc:
        print(f"ERROR H1 characterization failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(f"wrote {report_path}")
    print(f"wrote {points_path}")
    for plot in plots:
        print(f"wrote {plot}")
    if analysis.warnings:
        for warning in analysis.warnings:
            print(f"WARN {warning}", file=sys.stderr)


if __name__ == "__main__":
    main()
