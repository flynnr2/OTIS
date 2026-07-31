"""Acceptance scoring for clean pseudo-PPS hardware-snapshot runs.

The pseudo-PPS generator defines reference-gate timing.  It does not calibrate
the oscillator being counted, so centre frequency and interval variation are
assessed independently.  Raw continuity and fault evidence are separate hard
gates; a fitted or tolerated centre can never waive them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import argparse
import json
import math
from pathlib import Path
import statistics
from typing import Any, Iterable


UINT32_MASK = (1 << 32) - 1
CENTRE_SOURCES = {
    "independent_reference",
    "fitted_run_mean",
    "nominal_with_tolerance",
}


@dataclass(frozen=True)
class CleanIntervalObservation:
    session_id: str
    snapshot_sequence: int
    reference_sequence: int
    counted_edges: int
    load_state: str = "baseline"
    capture_valid: bool = True
    malformed_reference: bool = False
    host_parser_loss: bool = False

    def __post_init__(self) -> None:
        if not self.session_id:
            raise ValueError("session_id must not be empty")
        for name, value in (
            ("snapshot_sequence", self.snapshot_sequence),
            ("reference_sequence", self.reference_sequence),
        ):
            if (
                not isinstance(value, int)
                or isinstance(value, bool)
                or not 0 <= value <= UINT32_MASK
            ):
                raise ValueError(f"{name} must be an unsigned 32-bit integer")
        if (
            not isinstance(self.counted_edges, int)
            or isinstance(self.counted_edges, bool)
            or self.counted_edges <= 0
        ):
            raise ValueError("counted_edges must be a positive integer")
        if self.load_state not in {"baseline", "load"}:
            raise ValueError("load_state must be baseline or load")


@dataclass(frozen=True)
class CleanRunAcceptancePolicy:
    centre_source: str
    centre_evidence: str
    expected_oscillator_hz: float | None
    maximum_centre_offset_hz: float
    maximum_boundary_residual_edges: float
    maximum_adjacent_difference_edges: int
    maximum_load_mean_shift_hz: float
    require_load_comparison: bool = False
    minimum_intervals_per_load_state: int = 1

    def __post_init__(self) -> None:
        if self.centre_source not in CENTRE_SOURCES:
            raise ValueError(
                f"centre_source must be one of {sorted(CENTRE_SOURCES)}"
            )
        if not self.centre_evidence.strip():
            raise ValueError("centre_evidence must document the physical basis")
        if self.centre_source == "fitted_run_mean":
            if self.expected_oscillator_hz is not None:
                raise ValueError(
                    "fitted_run_mean must not supply expected_oscillator_hz"
                )
        elif (
            self.expected_oscillator_hz is None
            or not math.isfinite(self.expected_oscillator_hz)
            or self.expected_oscillator_hz <= 0
        ):
            raise ValueError(
                "the selected centre source requires a positive finite "
                "expected_oscillator_hz"
            )
        for name, value in (
            ("maximum_centre_offset_hz", self.maximum_centre_offset_hz),
            (
                "maximum_boundary_residual_edges",
                self.maximum_boundary_residual_edges,
            ),
            (
                "maximum_load_mean_shift_hz",
                self.maximum_load_mean_shift_hz,
            ),
        ):
            if not math.isfinite(value) or value < 0:
                raise ValueError(f"{name} must be finite and nonnegative")
        if (
            not isinstance(self.maximum_adjacent_difference_edges, int)
            or isinstance(self.maximum_adjacent_difference_edges, bool)
            or self.maximum_adjacent_difference_edges < 0
        ):
            raise ValueError(
                "maximum_adjacent_difference_edges must be a nonnegative integer"
            )
        if (
            not isinstance(self.minimum_intervals_per_load_state, int)
            or isinstance(self.minimum_intervals_per_load_state, bool)
            or self.minimum_intervals_per_load_state < 1
        ):
            raise ValueError(
                "minimum_intervals_per_load_state must be a positive integer"
            )


@dataclass(frozen=True)
class CleanRunAcceptanceReport:
    accepted: bool
    interval_count: int
    fitted_mean_hz: float | None
    expected_oscillator_hz: float | None
    centre_offset_hz: float | None
    maximum_boundary_residual_edges: float | None
    maximum_adjacent_difference_edges: int | None
    baseline_mean_hz: float | None
    load_mean_hz: float | None
    load_mean_shift_hz: float | None
    policy: dict[str, Any]
    checks: dict[str, bool]
    reasons: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _adjacent(previous: int, current: int) -> bool:
    return current == ((previous + 1) & UINT32_MASK)


def score_clean_run(
    observations: Iterable[CleanIntervalObservation],
    policy: CleanRunAcceptancePolicy,
) -> CleanRunAcceptanceReport:
    """Score a clean run without treating nominal frequency as exact truth."""

    rows = tuple(observations)
    counts = [float(row.counted_edges) for row in rows]
    fitted_mean = statistics.fmean(counts) if counts else None
    centre_offset = (
        None
        if fitted_mean is None or policy.expected_oscillator_hz is None
        else fitted_mean - policy.expected_oscillator_hz
    )
    residual = (
        max(abs(value - fitted_mean) for value in counts)
        if fitted_mean is not None
        else None
    )
    adjacent_differences = [
        abs(rows[index].counted_edges - rows[index - 1].counted_edges)
        for index in range(1, len(rows))
    ]
    maximum_adjacent = max(adjacent_differences, default=None)

    baseline = [
        float(row.counted_edges)
        for row in rows
        if row.load_state == "baseline"
    ]
    load = [
        float(row.counted_edges) for row in rows if row.load_state == "load"
    ]
    baseline_mean = statistics.fmean(baseline) if baseline else None
    load_mean = statistics.fmean(load) if load else None
    load_shift = (
        abs(load_mean - baseline_mean)
        if load_mean is not None and baseline_mean is not None
        else None
    )

    continuity = len(rows) >= 2 and all(
        rows[index].session_id == rows[index - 1].session_id
        and _adjacent(
            rows[index - 1].snapshot_sequence,
            rows[index].snapshot_sequence,
        )
        and _adjacent(
            rows[index - 1].reference_sequence,
            rows[index].reference_sequence,
        )
        for index in range(1, len(rows))
    )
    capture_clean = all(row.capture_valid for row in rows)
    reference_clean = all(not row.malformed_reference for row in rows)
    parser_clean = all(not row.host_parser_loss for row in rows)
    centre_ok = (
        fitted_mean is not None
        and (
            policy.centre_source == "fitted_run_mean"
            or (
                centre_offset is not None
                and abs(centre_offset) <= policy.maximum_centre_offset_hz
            )
        )
    )
    quantisation_ok = (
        residual is not None
        and residual <= policy.maximum_boundary_residual_edges
        and maximum_adjacent is not None
        and maximum_adjacent
        <= policy.maximum_adjacent_difference_edges
    )
    enough_load_evidence = (
        len(baseline) >= policy.minimum_intervals_per_load_state
        and len(load) >= policy.minimum_intervals_per_load_state
    )
    load_ok = (
        (not policy.require_load_comparison and load_shift is None)
        or (
            enough_load_evidence
            and load_shift is not None
            and load_shift <= policy.maximum_load_mean_shift_hz
        )
    )

    checks = {
        "oscillator_frequency_offset": centre_ok,
        "boundary_quantisation": quantisation_ok,
        "capture_continuity": continuity and capture_clean,
        "malformed_pps_absent": reference_clean,
        "host_parser_loss_absent": parser_clean,
        "service_plane_load_invariance": load_ok,
    }
    reason_by_check = {
        "oscillator_frequency_offset": "oscillator_centre_outside_evidence_bound",
        "boundary_quantisation": "boundary_quantisation_or_jitter_exceeded",
        "capture_continuity": "snapshot_or_reference_continuity_loss",
        "malformed_pps_absent": "malformed_pps_present",
        "host_parser_loss_absent": "host_parser_loss_present",
        "service_plane_load_invariance": (
            "service_plane_mean_shift_or_evidence_failure"
        ),
    }
    reasons = tuple(
        reason_by_check[name] for name, passed in checks.items() if not passed
    )
    return CleanRunAcceptanceReport(
        accepted=not reasons,
        interval_count=len(rows),
        fitted_mean_hz=fitted_mean,
        expected_oscillator_hz=policy.expected_oscillator_hz,
        centre_offset_hz=centre_offset,
        maximum_boundary_residual_edges=residual,
        maximum_adjacent_difference_edges=maximum_adjacent,
        baseline_mean_hz=baseline_mean,
        load_mean_hz=load_mean,
        load_mean_shift_hz=load_shift,
        policy=asdict(policy),
        checks=checks,
        reasons=reasons,
    )


def _load_input(
    path: Path,
) -> tuple[list[CleanIntervalObservation], CleanRunAcceptancePolicy]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != 1:
        raise ValueError("clean acceptance input schema_version must be 1")
    if set(value) != {"schema_version", "policy", "intervals"}:
        raise ValueError(
            "clean acceptance input fields must be schema_version, policy, intervals"
        )
    return (
        [CleanIntervalObservation(**item) for item in value["intervals"]],
        CleanRunAcceptancePolicy(**value["policy"]),
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Score clean pseudo-PPS interval evidence without assuming an "
            "exactly nominal oscillator frequency."
        )
    )
    parser.add_argument("evidence", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--strict", action="store_true")
    args = parser.parse_args(argv)
    try:
        observations, policy = _load_input(args.evidence)
        report = score_clean_run(observations, policy)
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    encoded = json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n"
    if args.output is None:
        print(encoded, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
        print(args.output)
    return 2 if args.strict and not report.accepted else 0


if __name__ == "__main__":
    raise SystemExit(main())
