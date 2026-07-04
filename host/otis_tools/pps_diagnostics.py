from __future__ import annotations

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class PpsIntervalClassification:
    classification: str
    raw_interval_ticks: int
    expected_interval_ticks: float | None
    interval_error_ticks: float | None
    interval_error_seconds: float | None
    missed_pulse_count: int | None
    usable_for_calibration: bool


def classify_pps_interval(
    interval_ticks: int,
    expected_interval_ticks: float | None,
    *,
    normal_min_ratio: float = 0.8,
    normal_max_ratio: float = 1.2,
    integer_tolerance_ratio: float = 0.2,
) -> PpsIntervalClassification:
    if expected_interval_ticks is None or expected_interval_ticks <= 0 or not math.isfinite(expected_interval_ticks):
        return PpsIntervalClassification("unknown", interval_ticks, expected_interval_ticks, None, None, None, False)
    if interval_ticks <= 0:
        return PpsIntervalClassification(
            "impossible_interval",
            interval_ticks,
            expected_interval_ticks,
            interval_ticks - expected_interval_ticks,
            (interval_ticks - expected_interval_ticks) / expected_interval_ticks,
            None,
            False,
        )

    ratio = interval_ticks / expected_interval_ticks
    error_ticks = interval_ticks - expected_interval_ticks
    error_seconds = error_ticks / expected_interval_ticks
    if normal_min_ratio <= ratio <= normal_max_ratio:
        return PpsIntervalClassification("normal_interval", interval_ticks, expected_interval_ticks, error_ticks, error_seconds, 0, True)
    if ratio < normal_min_ratio:
        return PpsIntervalClassification("short_interval", interval_ticks, expected_interval_ticks, error_ticks, error_seconds, None, False)

    nearest_integer = round(ratio)
    if nearest_integer >= 2 and abs(ratio - nearest_integer) <= integer_tolerance_ratio:
        missed = nearest_integer - 1
        label = "likely_missed_1_pps" if missed == 1 else "likely_missed_n_pps"
        return PpsIntervalClassification(label, interval_ticks, expected_interval_ticks, error_ticks, error_seconds, missed, False)
    return PpsIntervalClassification("long_interval", interval_ticks, expected_interval_ticks, error_ticks, error_seconds, None, False)
