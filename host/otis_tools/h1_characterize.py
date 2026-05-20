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
from .timebase import RP2040_TIMER0_MICROS_WRAP_TICKS, unwrap_ticks


COUNT_CONTRACT = "count_observations_v1"
DAC_CONTRACT = "dac_steps_v1"
ENV_CONTRACT = "environment_v1"
RAW_EVENTS_CONTRACT = "raw_events_v1"
DEFAULT_SETTLING_DISCARD_SECONDS = 0.0
DEFAULT_WARMUP_SECONDS = 1800.0
DEFAULT_STABILITY_PPM = 0.1
DEFAULT_STARTUP_INHIBIT_SECONDS = 600.0
DEFAULT_STARTUP_READY_CLEAN_WINDOWS = 3
FLAG_SOURCE_HEALTH_SUSPECT = 1 << 5
FLAG_INPUT_STUCK_LOW = 1 << 9
FLAG_INPUT_STUCK_HIGH = 1 << 10
INVALID_COUNT_FLAGS = (
    FLAG_SOURCE_HEALTH_SUSPECT | FLAG_INPUT_STUCK_LOW | FLAG_INPUT_STUCK_HIGH
)


@dataclass(frozen=True)
class CountWindow:
    seq: int
    elapsed_s: float
    gate_seconds: float
    counted_edges: int
    measured_hz: float
    ppm: float | None


@dataclass(frozen=True)
class PpsClockEstimate:
    domain: str
    sample_count: int
    interval_count: int
    tick_rate_hz: float
    median_tick_rate_hz: float | None
    nominal_tick_rate_hz: float | None
    mean_ppm_vs_nominal: float | None
    median_ppm_vs_nominal: float | None
    interval_stddev_ticks: float | None
    interval_mad_ticks: float | None
    interval_stddev_us: float | None
    interval_mad_us: float | None
    wrap_count: int
    note: str


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
class EnvironmentSample:
    seq: int
    elapsed_s: float
    source: str
    role: str
    temperature_c: float | None
    relative_humidity_pct: float | None
    pressure_pa: float | None


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
    env_temperature_min_c: float | None
    env_temperature_max_c: float | None
    env_temperature_delta_c: float | None
    env_temperature_mean_c: float | None


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
class CenterBracketedSlope:
    group_id: str
    center_before_group_id: str
    target_group_id: str
    center_after_group_id: str
    center_code: int
    target_code: int
    delta_code: int
    center_before_hz: float
    target_hz: float
    center_after_hz: float
    bracket_center_hz: float
    target_delta_hz: float
    center_drift_hz: float
    hz_per_code: float
    ppm_per_code: float | None
    center_before_voltage_v: float | None
    target_voltage_v: float | None
    center_after_voltage_v: float | None
    bracket_center_voltage_v: float | None
    target_delta_voltage_v: float | None
    hz_per_v: float | None
    ppm_per_v: float | None
    note: str


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
class StartupControlEstimate:
    inhibit_s: float
    required_clean_windows: int
    raw_window_count: int
    invalid_window_count: int
    startup_discarded_window_count: int
    clean_window_count_at_end: int
    first_control_eligible_elapsed_s: float | None
    first_post_inhibit_bad_elapsed_s: float | None
    valid_for_control: bool
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
    pps_clock: PpsClockEstimate | None
    count_windows: tuple[CountWindow, ...]
    dac_events: tuple[DacEvent, ...]
    environment_samples: tuple[EnvironmentSample, ...]
    points: tuple[CharacterizationPoint, ...]
    slopes: tuple[SlopePoint, ...]
    center_bracketed_slopes: tuple[CenterBracketedSlope, ...]
    settling: tuple[SettlingEstimate, ...]
    warmup: WarmupEstimate
    startup_control: StartupControlEstimate
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


def _manifest_files(manifest: RunManifest, contract: str, fallback: str) -> tuple[Path, ...]:
    paths: list[Path] = []
    seen: set[Path] = set()
    for entry in manifest.files:
        if entry.get("contract") != contract:
            continue
        path = manifest.root / str(entry.get("path", fallback))
        if path not in seen:
            paths.append(path)
            seen.add(path)
    fallback_path = manifest.root / fallback
    if not paths and fallback_path.exists():
        paths.append(fallback_path)
    return tuple(paths)


def _dac_voltage_from_manifest(manifest: RunManifest, code: int) -> float | None:
    dac = manifest.data.get("dac")
    safety_limits = manifest.data.get("safety_limits")
    if not isinstance(dac, dict) or not isinstance(safety_limits, dict):
        return None

    min_code = _parse_int(safety_limits.get("dac_min_code"))
    max_code = _parse_int(safety_limits.get("dac_max_code"))
    mid_code = _parse_int(dac.get("nominal_code"))
    min_v = _parse_float(dac.get("measured_output_min_v"))
    mid_v = _parse_float(dac.get("measured_output_mid_v"))
    max_v = _parse_float(dac.get("measured_output_max_v"))
    if None in (min_code, mid_code, max_code, min_v, mid_v, max_v):
        return None
    if min_code == mid_code or mid_code == max_code:
        return None

    if code <= mid_code:
        return min_v + (code - min_code) * (mid_v - min_v) / (mid_code - min_code)
    return mid_v + (code - mid_code) * (max_v - mid_v) / (max_code - mid_code)


def _count_window_invalid(flags: int, counted_edges: int) -> bool:
    return counted_edges == 0 or bool(flags & INVALID_COUNT_FLAGS)


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


def _unwrap_count_gate(
    gate_domain: str,
    gate_open: int,
    gate_close: int,
    previous_open_raw: int | None,
    tick_offset_by_domain: dict[str, int],
) -> tuple[int, int]:
    if gate_domain != "rp2040_timer0":
        return gate_open, gate_close

    half_modulus = RP2040_TIMER0_MICROS_WRAP_TICKS // 2
    if previous_open_raw is not None and gate_open < previous_open_raw and previous_open_raw - gate_open > half_modulus:
        tick_offset_by_domain[gate_domain] = tick_offset_by_domain.get(gate_domain, 0) + RP2040_TIMER0_MICROS_WRAP_TICKS

    offset = tick_offset_by_domain.get(gate_domain, 0)
    gate_open_unwrapped = gate_open + offset
    close_offset = offset
    if gate_close < gate_open and gate_open - gate_close > half_modulus:
        close_offset += RP2040_TIMER0_MICROS_WRAP_TICKS
    gate_close_unwrapped = gate_close + close_offset
    return gate_open_unwrapped, gate_close_unwrapped


def _ref_csv_paths(manifest: RunManifest) -> tuple[Path, ...]:
    paths = [
        path
        for path in _manifest_files(manifest, RAW_EVENTS_CONTRACT, "csv/ref.csv")
        if path.name == "ref.csv"
    ]
    fallback = manifest.root / "csv" / "ref.csv"
    if fallback.exists() and fallback not in paths:
        paths.append(fallback)
    return tuple(paths)


def _estimate_pps_clock(
    manifest: RunManifest,
    gate_hz_by_domain: dict[str, float],
    warnings: list[str],
) -> PpsClockEstimate | None:
    rows: list[dict[str, str]] = []
    for path in _ref_csv_paths(manifest):
        rows.extend(_read_csv(path))
    if not rows:
        return None

    segments: list[list[tuple[int, int, str]]] = [[]]
    previous_seq: int | None = None
    skipped = 0
    for index, row in enumerate(rows, start=1):
        record_type = str(row.get("record_type", "REF"))
        if record_type and record_type != "REF":
            continue
        seq = _parse_int(row.get("event_seq")) or index
        ticks = _parse_int(row.get("timestamp_ticks"))
        domain = str(row.get("capture_domain", ""))
        if ticks is None or not domain:
            skipped += 1
            continue
        if previous_seq is not None and seq <= previous_seq:
            segments.append([])
        previous_seq = seq
        segments[-1].append((seq, ticks, domain))

    populated = [segment for segment in segments if len(segment) >= 2]
    if skipped:
        warnings.append(f"ref.csv: skipped {skipped} REF row(s) without timestamp_ticks or capture_domain")
    if not populated:
        return None
    if len(populated) > 1:
        warnings.append("ref.csv: multiple capture segments detected; using the final segment for PPS clock calibration")

    segment = populated[-1]
    domains = {domain for _, _, domain in segment}
    if len(domains) != 1:
        warnings.append("ref.csv: final REF segment spans multiple capture domains; PPS clock calibration unavailable")
        return None
    domain = next(iter(domains))
    nominal_rate = gate_hz_by_domain.get(domain)
    if not nominal_rate:
        warnings.append(f"ref.csv: capture_domain={domain} has no nominal_hz; PPS clock calibration unavailable")
        return None

    unwrapped, wrap_count = unwrap_ticks([ticks for _, ticks, _ in segment])
    intervals = [float(current - previous) for previous, current in zip(unwrapped, unwrapped[1:])]
    valid_intervals = [
        interval
        for interval in intervals
        if 0.8 <= interval / nominal_rate <= 1.2
    ]
    if len(valid_intervals) < 2:
        warnings.append("ref.csv: insufficient sane PPS intervals for clock calibration")
        return None
    if len(valid_intervals) != len(intervals):
        warnings.append(
            f"ref.csv: ignored {len(intervals) - len(valid_intervals)} PPS interval(s) outside 0.8..1.2 nominal seconds"
        )

    tick_rate = _mean(valid_intervals)
    median_rate = _median(valid_intervals)
    if tick_rate is None:
        return None
    stddev_ticks = _stddev(valid_intervals)
    mad_ticks = _mad(valid_intervals)
    mean_ppm = 1_000_000.0 * (tick_rate - nominal_rate) / nominal_rate
    median_ppm = 1_000_000.0 * (median_rate - nominal_rate) / nominal_rate if median_rate is not None else None
    return PpsClockEstimate(
        domain=domain,
        sample_count=len(segment),
        interval_count=len(valid_intervals),
        tick_rate_hz=tick_rate,
        median_tick_rate_hz=median_rate,
        nominal_tick_rate_hz=nominal_rate,
        mean_ppm_vs_nominal=mean_ppm,
        median_ppm_vs_nominal=median_ppm,
        interval_stddev_ticks=stddev_ticks,
        interval_mad_ticks=mad_ticks,
        interval_stddev_us=stddev_ticks / tick_rate * 1_000_000.0 if stddev_ticks is not None else None,
        interval_mad_us=mad_ticks / tick_rate * 1_000_000.0 if mad_ticks is not None else None,
        wrap_count=wrap_count,
        note="estimated from the final REF/PPS segment; count gates in this domain use this rate instead of nominal_hz",
    )


def _effective_gate_hz(
    gate_domain: str,
    gate_hz_by_domain: dict[str, float],
    pps_clock: PpsClockEstimate | None,
) -> float | None:
    if pps_clock is not None and gate_domain == pps_clock.domain:
        return pps_clock.tick_rate_hz
    return gate_hz_by_domain.get(gate_domain)


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
    pps_clock: PpsClockEstimate | None,
    nominal_hz: float | None,
    warnings: list[str],
) -> tuple[CountWindow, ...]:
    rows = _read_csv(_manifest_file(manifest, COUNT_CONTRACT, "csv/cnt.csv"))
    segments: list[list[CountWindow]] = [[]]
    first_open_s: float | None = None
    previous_open_raw: int | None = None
    previous_seq: int | None = None
    tick_offset_by_domain: dict[str, int] = {}
    skipped_invalid_count = 0
    for index, row in enumerate(rows, start=1):
        gate_open = _parse_int(row.get("gate_open_ticks"))
        gate_close = _parse_int(row.get("gate_close_ticks"))
        counted = _parse_int(row.get("counted_edges"))
        flags = _parse_int(row.get("flags")) or 0
        seq = _parse_int(row.get("count_seq")) or index
        gate_domain = str(row.get("gate_domain", ""))
        gate_hz = _effective_gate_hz(gate_domain, gate_hz_by_domain, pps_clock)
        if gate_open is None or gate_close is None or counted is None or not gate_hz:
            warnings.append(f"cnt.csv row {index}: skipped because count/window fields or gate domain nominal_hz are unavailable")
            continue
        if _count_window_invalid(flags, counted):
            skipped_invalid_count += 1
            continue
        gate_open_unwrapped, gate_close_unwrapped = _unwrap_count_gate(
            gate_domain,
            gate_open,
            gate_close,
            previous_open_raw,
            tick_offset_by_domain,
        )
        if previous_seq is not None and seq <= previous_seq:
            warnings.append(f"cnt.csv row {index}: detected count_seq reset; starting a new analysis segment")
            segments.append([])
            first_open_s = None
            tick_offset_by_domain = {}
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
    if skipped_invalid_count:
        warnings.append(f"cnt.csv: skipped {skipped_invalid_count} invalid or startup-suspect count observation(s)")
    if len(populated) > 1:
        warnings.append("cnt.csv: multiple capture segments detected; using the final segment for H1 characterization")
    return tuple(populated[-1] if populated else [])


def _load_dac_events(manifest: RunManifest, warnings: list[str]) -> tuple[DacEvent, ...]:
    rows = _read_csv(_manifest_file(manifest, DAC_CONTRACT, "csv/dac_steps.csv"))
    events: list[DacEvent] = []
    used_manifest_voltage = False
    for index, row in enumerate(rows, start=1):
        code = _parse_int(row.get("dac_code_applied"))
        elapsed_ms = _parse_float(row.get("elapsed_ms"))
        if code is None or elapsed_ms is None:
            continue
        voltage = _parse_float(row.get("ocxo_tune_voltage_measured_v"))
        if voltage is None:
            voltage = _parse_float(row.get("dac_voltage_measured_v"))
        if voltage is None:
            voltage = _dac_voltage_from_manifest(manifest, code)
            used_manifest_voltage = used_manifest_voltage or voltage is not None
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
    if used_manifest_voltage:
        warnings.append("dac_steps.csv: voltage fields were empty for at least one row; used manifest measured DAC voltage model")
    return tuple(sorted(events, key=lambda item: (item.elapsed_s, item.seq)))


def _load_environment_samples(manifest: RunManifest, gate_hz_by_domain: dict[str, float], warnings: list[str]) -> tuple[EnvironmentSample, ...]:
    rows = _read_csv(_manifest_file(manifest, ENV_CONTRACT, "csv/environment.csv"))
    samples: list[EnvironmentSample] = []
    for index, row in enumerate(rows, start=1):
        ticks = _parse_int(row.get("timestamp_ticks"))
        domain = str(row.get("observation_domain", ""))
        domain_hz = gate_hz_by_domain.get(domain)
        if ticks is None or not domain_hz:
            warnings.append(f"environment.csv row {index}: skipped because timestamp or observation_domain nominal_hz is unavailable")
            continue
        tick_s = ticks / domain_hz
        samples.append(
            EnvironmentSample(
                seq=_parse_int(row.get("env_seq")) or index,
                elapsed_s=tick_s,
                source=str(row.get("source", "")),
                role=str(row.get("role", "")),
                temperature_c=_parse_float(row.get("temperature_c")),
                relative_humidity_pct=_parse_float(row.get("relative_humidity_pct")),
                pressure_pa=_parse_float(row.get("pressure_pa")),
            )
        )
    return tuple(sorted(samples, key=lambda item: (item.elapsed_s, item.seq)))


def _startup_control_estimate(
    manifest: RunManifest,
    gate_hz_by_domain: dict[str, float],
    pps_clock: PpsClockEstimate | None,
    inhibit_s: float = DEFAULT_STARTUP_INHIBIT_SECONDS,
    required_clean_windows: int = DEFAULT_STARTUP_READY_CLEAN_WINDOWS,
) -> StartupControlEstimate:
    rows = _read_csv(_manifest_file(manifest, COUNT_CONTRACT, "csv/cnt.csv"))
    windows: list[tuple[float, bool]] = []
    current_segment: list[tuple[float, bool]] = []
    first_open_s: float | None = None
    previous_open_raw: int | None = None
    previous_seq: int | None = None
    tick_offset_by_domain: dict[str, int] = {}

    for index, row in enumerate(rows, start=1):
        gate_open = _parse_int(row.get("gate_open_ticks"))
        gate_close = _parse_int(row.get("gate_close_ticks"))
        counted = _parse_int(row.get("counted_edges"))
        flags = _parse_int(row.get("flags")) or 0
        seq = _parse_int(row.get("count_seq")) or index
        gate_domain = str(row.get("gate_domain", ""))
        gate_hz = _effective_gate_hz(gate_domain, gate_hz_by_domain, pps_clock)
        if gate_open is None or gate_close is None or counted is None or not gate_hz:
            continue
        if previous_seq is not None and seq <= previous_seq:
            if current_segment:
                windows = current_segment
            current_segment = []
            first_open_s = None
            tick_offset_by_domain = {}
        gate_open_unwrapped, gate_close_unwrapped = _unwrap_count_gate(
            gate_domain,
            gate_open,
            gate_close,
            previous_open_raw,
            tick_offset_by_domain,
        )
        previous_open_raw = gate_open
        previous_seq = seq
        if gate_close_unwrapped <= gate_open_unwrapped:
            continue
        if first_open_s is None:
            first_open_s = gate_open_unwrapped / gate_hz
        midpoint_s = ((gate_open_unwrapped + gate_close_unwrapped) / 2.0) / gate_hz
        current_segment.append(
            (midpoint_s - first_open_s, _count_window_invalid(flags, counted))
        )

    if current_segment:
        windows = current_segment

    clean_streak = 0
    invalid_count = 0
    startup_discard_count = 0
    first_eligible: float | None = None
    first_post_inhibit_bad: float | None = None
    for elapsed_s, invalid in windows:
        if elapsed_s < inhibit_s:
            startup_discard_count += 1
            clean_streak = 0
            if invalid:
                invalid_count += 1
            continue
        if invalid:
            invalid_count += 1
            clean_streak = 0
            if first_post_inhibit_bad is None:
                first_post_inhibit_bad = elapsed_s
            continue
        clean_streak += 1
        if clean_streak >= required_clean_windows and first_eligible is None:
            first_eligible = elapsed_s

    valid_for_control = first_eligible is not None and first_post_inhibit_bad is None
    if not windows:
        note = "insufficient data: startup control gate requires count windows"
    elif first_eligible is None:
        note = "not control-eligible: inhibit window did not expire with enough clean FC0 windows"
    elif first_post_inhibit_bad is not None:
        note = "not control-eligible: at least one invalid FC0 window occurred after startup inhibit"
    else:
        note = "control-eligible after startup inhibit and clean-window requirement"
    return StartupControlEstimate(
        inhibit_s=inhibit_s,
        required_clean_windows=required_clean_windows,
        raw_window_count=len(windows),
        invalid_window_count=invalid_count,
        startup_discarded_window_count=startup_discard_count,
        clean_window_count_at_end=clean_streak,
        first_control_eligible_elapsed_s=first_eligible,
        first_post_inhibit_bad_elapsed_s=first_post_inhibit_bad,
        valid_for_control=valid_for_control,
        note=note,
    )


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
    env_samples: list[EnvironmentSample],
    discarded_count: int,
) -> CharacterizationPoint:
    hz_values = [sample.measured_hz for sample in samples]
    ppm_values = [sample.ppm for sample in samples if sample.ppm is not None]
    temp_values = [sample.temperature_c for sample in env_samples if sample.temperature_c is not None]
    temp_min = min(temp_values) if temp_values else None
    temp_max = max(temp_values) if temp_values else None
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
        env_temperature_min_c=temp_min,
        env_temperature_max_c=temp_max,
        env_temperature_delta_c=temp_max - temp_min if temp_min is not None and temp_max is not None else None,
        env_temperature_mean_c=_mean(temp_values),
    )


def _build_points(
    counts: tuple[CountWindow, ...],
    events: tuple[DacEvent, ...],
    env_samples: tuple[EnvironmentSample, ...],
    settling_discard_s: float,
) -> tuple[CharacterizationPoint, ...]:
    analysis_events = _analysis_dwell_events(events)
    assigned = _assigned_samples(counts, analysis_events)
    primary_env_samples = [
        sample for sample in env_samples
        if sample.source == "sht4x" and sample.role == "vcocxo_near" and sample.temperature_c is not None
    ]
    if not analysis_events:
        return (
            _summarize_group("all_counts", None, None, None, "unknown", [sample for _, sample in assigned], primary_env_samples, 0),
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
        group_env = [
            sample
            for sample in primary_env_samples
            if sample.temperature_c is not None
            and sample.elapsed_s >= event.elapsed_s
            and (end_s is None or sample.elapsed_s < end_s)
        ]
        points.append(
            _summarize_group(
                group_id=f"step_{event.step_index}_{event.seq}",
                step_index=event.step_index,
                code=event.code,
                voltage=event.voltage_v,
                direction=_direction(previous_code, event.code),
                samples=kept,
                env_samples=group_env,
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


def _build_center_bracketed_slopes(points: tuple[CharacterizationPoint, ...]) -> tuple[CenterBracketedSlope, ...]:
    usable = [point for point in points if point.sample_count and point.dac_code is not None and point.median_hz is not None]
    estimates: list[CenterBracketedSlope] = []
    for before, target, after in zip(usable, usable[1:], usable[2:]):
        if before.dac_code is None or target.dac_code is None or after.dac_code is None:
            continue
        if before.median_hz is None or target.median_hz is None or after.median_hz is None:
            continue
        if before.dac_code != after.dac_code or target.dac_code == before.dac_code:
            continue
        delta_code = target.dac_code - before.dac_code
        if delta_code == 0:
            continue
        bracket_center_hz = (before.median_hz + after.median_hz) / 2.0
        target_delta_hz = target.median_hz - bracket_center_hz
        target_delta_ppm = None
        if before.median_ppm is not None and target.median_ppm is not None and after.median_ppm is not None:
            target_delta_ppm = target.median_ppm - ((before.median_ppm + after.median_ppm) / 2.0)
        bracket_center_voltage = None
        target_delta_voltage = None
        hz_per_v = None
        ppm_per_v = None
        if before.voltage_v is not None and target.voltage_v is not None and after.voltage_v is not None:
            bracket_center_voltage = (before.voltage_v + after.voltage_v) / 2.0
            target_delta_voltage = target.voltage_v - bracket_center_voltage
            if target_delta_voltage != 0:
                hz_per_v = target_delta_hz / target_delta_voltage
                if target_delta_ppm is not None:
                    ppm_per_v = target_delta_ppm / target_delta_voltage
        estimates.append(
            CenterBracketedSlope(
                group_id=f"{before.group_id}__{target.group_id}__{after.group_id}",
                center_before_group_id=before.group_id,
                target_group_id=target.group_id,
                center_after_group_id=after.group_id,
                center_code=before.dac_code,
                target_code=target.dac_code,
                delta_code=delta_code,
                center_before_hz=before.median_hz,
                target_hz=target.median_hz,
                center_after_hz=after.median_hz,
                bracket_center_hz=bracket_center_hz,
                target_delta_hz=target_delta_hz,
                center_drift_hz=after.median_hz - before.median_hz,
                hz_per_code=target_delta_hz / delta_code,
                ppm_per_code=target_delta_ppm / delta_code if target_delta_ppm is not None else None,
                center_before_voltage_v=before.voltage_v,
                target_voltage_v=target.voltage_v,
                center_after_voltage_v=after.voltage_v,
                bracket_center_voltage_v=bracket_center_voltage,
                target_delta_voltage_v=target_delta_voltage,
                hz_per_v=hz_per_v,
                ppm_per_v=ppm_per_v,
                note="target step compared with average of same-code center dwells before and after",
            )
        )
    return tuple(estimates)


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
    pps_clock = _estimate_pps_clock(manifest, gate_hz_by_domain, warnings)
    counts = _load_counts(manifest, gate_hz_by_domain, pps_clock, resolved_nominal_hz, warnings)
    startup_control = _startup_control_estimate(manifest, gate_hz_by_domain, pps_clock)
    dac_events = _load_dac_events(manifest, warnings)
    if not dac_events:
        warnings.append("dac_steps.csv unavailable or empty; DAC-code grouping and voltage plots are limited")
    environment_samples = _load_environment_samples(manifest, gate_hz_by_domain, warnings)
    primary_temp_samples = [
        sample for sample in environment_samples
        if sample.source == "sht4x" and sample.role == "vcocxo_near" and sample.temperature_c is not None
    ]
    if environment_samples and not primary_temp_samples:
        warnings.append("environment.csv present, but no source=sht4x role=vcocxo_near temperature samples were found")
    points = _build_points(counts, dac_events, environment_samples, settling_discard_s)
    return H1Analysis(
        run_dir=run_dir,
        manifest=manifest,
        nominal_hz=resolved_nominal_hz,
        gate_hz_by_domain=gate_hz_by_domain,
        settling_discard_s=settling_discard_s,
        warmup_s=warmup_s,
        stability_ppm=stability_ppm,
        pps_clock=pps_clock,
        count_windows=counts,
        dac_events=dac_events,
        environment_samples=environment_samples,
        points=points,
        slopes=_build_slopes(points),
        center_bracketed_slopes=_build_center_bracketed_slopes(points),
        settling=_settling(counts, dac_events),
        warmup=_warmup(counts, resolved_nominal_hz, warmup_s, stability_ppm),
        startup_control=startup_control,
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
    "env_temperature_min_c",
    "env_temperature_max_c",
    "env_temperature_delta_c",
    "env_temperature_mean_c",
]

BRACKETED_SLOPE_FIELDS = [
    "group_id",
    "center_before_group_id",
    "target_group_id",
    "center_after_group_id",
    "center_code",
    "target_code",
    "delta_code",
    "center_before_hz",
    "target_hz",
    "center_after_hz",
    "bracket_center_hz",
    "target_delta_hz",
    "center_drift_hz",
    "hz_per_code",
    "ppm_per_code",
    "center_before_voltage_v",
    "target_voltage_v",
    "center_after_voltage_v",
    "bracket_center_voltage_v",
    "target_delta_voltage_v",
    "hz_per_v",
    "ppm_per_v",
    "note",
]


def write_points_csv(analysis: H1Analysis, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=POINT_FIELDS)
        writer.writeheader()
        for point in analysis.points:
            writer.writerow({field: getattr(point, field) for field in POINT_FIELDS})


def write_center_bracketed_slopes_csv(analysis: H1Analysis, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=BRACKETED_SLOPE_FIELDS)
        writer.writeheader()
        for estimate in analysis.center_bracketed_slopes:
            writer.writerow({field: getattr(estimate, field) for field in BRACKETED_SLOPE_FIELDS})


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
    primary_env = [
        sample for sample in analysis.environment_samples
        if sample.source == "sht4x" and sample.role == "vcocxo_near" and sample.temperature_c is not None
    ]
    temp_elapsed = [(sample.elapsed_s, sample.temperature_c) for sample in primary_env if sample.temperature_c is not None]
    if _plot_xy(plots_dir / "vcocxo_temperature_vs_elapsed.png", temp_elapsed, connect=True):
        written.append(plots_dir / "vcocxo_temperature_vs_elapsed.png")
    temp_ppm = [
        (point.env_temperature_mean_c, point.median_ppm)
        for point in analysis.points
        if point.env_temperature_mean_c is not None and point.median_ppm is not None
    ]
    if _plot_xy(plots_dir / "vcocxo_temperature_vs_ppm.png", temp_ppm, connect=False):
        written.append(plots_dir / "vcocxo_temperature_vs_ppm.png")
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
        f"- environment_samples: {len(analysis.environment_samples)}",
        "",
        "## Formulas",
        "- gate_seconds = gate_ticks / pps_calibrated_tick_rate when a sane REF/PPS stream exists for the gate domain",
        "- gate_seconds = gate_ticks / nominal_domain_hz when PPS calibration is unavailable",
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

    lines.extend(["", "## PPS-Calibrated Clock"])
    if analysis.pps_clock is None:
        lines.append("- unavailable: no sane REF/PPS segment for gate-domain calibration")
    else:
        pps = analysis.pps_clock
        lines.extend(
            [
                f"- domain: {pps.domain}",
                f"- ref_samples: {pps.sample_count}",
                f"- valid_pps_intervals: {pps.interval_count}",
                f"- calibrated_tick_rate_hz: {_format(pps.tick_rate_hz)}",
                f"- median_tick_rate_hz: {_format(pps.median_tick_rate_hz)}",
                f"- nominal_tick_rate_hz: {_format(pps.nominal_tick_rate_hz)}",
                f"- mean_ppm_vs_nominal: {_format(pps.mean_ppm_vs_nominal)}",
                f"- median_ppm_vs_nominal: {_format(pps.median_ppm_vs_nominal)}",
                f"- interval_stddev_ticks: {_format(pps.interval_stddev_ticks)}",
                f"- interval_mad_ticks: {_format(pps.interval_mad_ticks)}",
                f"- interval_stddev_us: {_format(pps.interval_stddev_us)}",
                f"- interval_mad_us: {_format(pps.interval_mad_us)}",
                f"- wrap_count: {pps.wrap_count}",
                f"- note: {pps.note}",
            ]
        )

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
            f"median_ppm={_format(point.median_ppm)}, "
            f"vcocxo_temp_c={_format(point.env_temperature_min_c)}..{_format(point.env_temperature_max_c)}, "
            f"temp_delta_c={_format(point.env_temperature_delta_c)}"
        )

    lines.extend(["", "## Near-VCOCXO Temperature"])
    primary_env = [
        sample for sample in analysis.environment_samples
        if sample.source == "sht4x" and sample.role == "vcocxo_near" and sample.temperature_c is not None
    ]
    if not primary_env:
        lines.append("- unavailable: no SHT4x vcocxo_near temperature samples")
    else:
        temps = [sample.temperature_c for sample in primary_env if sample.temperature_c is not None]
        lines.append(
            f"- source=sht4x role=vcocxo_near samples={len(primary_env)}, "
            f"temperature_c={_format(min(temps))}..{_format(max(temps))}, "
            f"delta_c={_format(max(temps) - min(temps))}, mean_c={_format(_mean(temps))}"
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

    lines.extend(["", "## Center-Bracketed Slopes"])
    if not analysis.center_bracketed_slopes:
        lines.append("- unavailable: need center-target-center dwell triples with populated count windows")
    for estimate in analysis.center_bracketed_slopes:
        lines.append(
            f"- center {estimate.center_code} -> target {estimate.target_code} -> center {estimate.center_code}: "
            f"delta_code={estimate.delta_code}, target_delta_hz={_format(estimate.target_delta_hz)}, "
            f"center_drift_hz={_format(estimate.center_drift_hz)}, Hz/code={_format(estimate.hz_per_code)}, "
            f"ppm/code={_format(estimate.ppm_per_code)}, Hz/V={_format(estimate.hz_per_v)}, "
            f"ppm/V={_format(estimate.ppm_per_v)}; {estimate.note}"
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

    startup = analysis.startup_control
    lines.extend(
        [
            "",
            "## Startup Control Eligibility",
            f"- startup_inhibit_s: {_format(startup.inhibit_s)}",
            f"- required_clean_windows: {startup.required_clean_windows}",
            f"- raw_count_windows: {startup.raw_window_count}",
            f"- invalid_count_windows: {startup.invalid_window_count}",
            f"- startup_discarded_windows: {startup.startup_discarded_window_count}",
            f"- first_control_eligible_elapsed_s: {_format(startup.first_control_eligible_elapsed_s)}",
            f"- first_post_inhibit_bad_elapsed_s: {_format(startup.first_post_inhibit_bad_elapsed_s)}",
            f"- fc0_observed_valid: {str(startup.raw_window_count > 0).lower()}",
            f"- fc0_valid_for_control: {str(startup.valid_for_control).lower()}",
            f"- fc0_fault: {str(startup.first_post_inhibit_bad_elapsed_s is not None).lower()}",
            f"- clean_window_count_at_end: {startup.clean_window_count_at_end}",
            f"- note: {startup.note}",
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
    lines.append("- csv/h1_center_bracketed_slopes.csv")
    if written_plots:
        lines.extend(f"- {path.relative_to(analysis.run_dir)}" for path in written_plots)
    else:
        lines.append("- plots: none generated; supported data was insufficient")

    open_loop_slope_known = any(
        (slope.hz_per_v is not None and abs(slope.hz_per_v) > 0.0)
        or (slope.hz_per_code is not None and abs(slope.hz_per_code) > 0.0)
        for slope in analysis.slopes
    ) or any(abs(estimate.hz_per_code) > 0.0 for estimate in analysis.center_bracketed_slopes)
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
            f"- fc0_valid_for_control: {str(analysis.startup_control.valid_for_control).lower()}",
            f"- recommended_next_action: {action}",
        ]
    )
    return "\n".join(lines) + "\n"


def write_outputs(analysis: H1Analysis) -> tuple[Path, Path, list[Path]]:
    points_path = analysis.run_dir / "csv" / "h1_characterization_points.csv"
    bracketed_slopes_path = analysis.run_dir / "csv" / "h1_center_bracketed_slopes.csv"
    report_path = analysis.run_dir / "reports" / "h1_characterization_summary.md"
    write_points_csv(analysis, points_path)
    write_center_bracketed_slopes_csv(analysis, bracketed_slopes_path)
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
