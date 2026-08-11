from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from typing import Iterable, Protocol


ESTIMATOR_METHOD_ID = "LOCAL_PPS_BOUNDARY_INTERPOLATED_V1"
MEASUREMENT_BACKEND = "OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE"
REFERENCE_INVALID_FLAGS = (
    (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 5) | (1 << 12)
)

ESTIMATOR_METHOD_DEFINITION = {
    "boundary_interpolation": "independent_bracketing_accepted_pps_pairs",
    "count_window_semantics": "oscillator_edges_between_capture_tick_boundaries",
    "estimator_method_id": ESTIMATOR_METHOD_ID,
    "extrapolation_policy": "prohibited",
    "measurement_backend": MEASUREMENT_BACKEND,
    "reference_acceptance": "clean_flags_strictly_increasing_sequence_interval_0.8_to_1.2_seconds",
    "reference_interval_max_s": 1.2,
    "reference_interval_min_s": 0.8,
    "reference_invalid_flag_mask": REFERENCE_INVALID_FLAGS,
    "reference_time_mapping": "piecewise_linear_adjacent_accepted_pps",
    "required_timing_domain": "rp2040_timer0",
}


def _canonical_contract_bytes(value: dict[str, object]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


ESTIMATOR_METHOD_DEFINITION_HASH = hashlib.sha256(
    _canonical_contract_bytes(ESTIMATOR_METHOD_DEFINITION)
).hexdigest()


def estimator_method_contract() -> dict[str, object]:
    return {
        **ESTIMATOR_METHOD_DEFINITION,
        "method_definition_hash": ESTIMATOR_METHOD_DEFINITION_HASH,
    }


class ReferenceLike(Protocol):
    seq: int
    ticks: int
    flags: int


@dataclass(frozen=True)
class PpsTimePoint:
    tick: int
    second: float
    seq: int


@dataclass(frozen=True)
class PpsTimeMapping:
    second: float
    before_tick: int
    after_tick: int
    before_seq: int
    after_seq: int
    segment_rate_ticks_per_s: float


@dataclass(frozen=True)
class BoundaryEstimate:
    valid: bool
    reason_codes: tuple[str, ...]
    pps_time_open: float | None = None
    pps_time_close: float | None = None
    gate_seconds: float | None = None
    frequency_hz: float | None = None
    pps_before_open_timestamp: int | None = None
    pps_after_open_timestamp: int | None = None
    pps_before_close_timestamp: int | None = None
    pps_after_close_timestamp: int | None = None
    pps_before_open_seq: int | None = None
    pps_after_open_seq: int | None = None
    pps_before_close_seq: int | None = None
    pps_after_close_seq: int | None = None
    pps_support_count: int = 0
    max_pps_gap_seconds: float | None = None

    @property
    def evaluation_tick(self) -> int | None:
        return self.pps_after_close_timestamp


class BoundaryPpsTimeMapper:
    def __init__(
        self,
        segments: tuple[tuple[PpsTimePoint, ...], ...],
        *,
        domain_hz: float,
        max_gap_seconds: float,
    ):
        self.segments = segments
        self.domain_hz = domain_hz
        self.max_gap_seconds = max_gap_seconds

    @classmethod
    def from_references(
        cls,
        references: Iterable[ReferenceLike],
        *,
        domain_hz: float,
        nominal_interval_s: float,
        interval_tolerance_s: float,
        invalid_flag_mask: int = REFERENCE_INVALID_FLAGS,
    ) -> "BoundaryPpsTimeMapper":
        if not math.isfinite(domain_hz) or domain_hz <= 0:
            raise ValueError("domain_hz must be finite and positive")
        if not math.isfinite(nominal_interval_s) or nominal_interval_s <= 0:
            raise ValueError("nominal_interval_s must be finite and positive")
        if not math.isfinite(interval_tolerance_s) or interval_tolerance_s < 0:
            raise ValueError("interval_tolerance_s must be finite and non-negative")

        minimum_ticks = (
            nominal_interval_s - interval_tolerance_s
        ) * domain_hz
        maximum_ticks = (
            nominal_interval_s + interval_tolerance_s
        ) * domain_hz
        segments: list[tuple[PpsTimePoint, ...]] = []
        current: list[PpsTimePoint] = []
        previous: ReferenceLike | None = None

        for reference in references:
            if previous is None:
                previous = reference
                continue
            interval_ticks = reference.ticks - previous.ticks
            accepted = (
                not (previous.flags & invalid_flag_mask)
                and not (reference.flags & invalid_flag_mask)
                and reference.seq > previous.seq
                and minimum_ticks <= interval_ticks <= maximum_ticks
            )
            if not accepted:
                if len(current) >= 2:
                    segments.append(tuple(current))
                current = []
                previous = reference
                continue
            if not current:
                current.append(PpsTimePoint(previous.ticks, 0.0, previous.seq))
            current.append(
                PpsTimePoint(
                    reference.ticks,
                    current[-1].second + nominal_interval_s,
                    reference.seq,
                )
            )
            previous = reference

        if len(current) >= 2:
            segments.append(tuple(current))
        return cls(
            tuple(segments),
            domain_hz=domain_hz,
            max_gap_seconds=nominal_interval_s + interval_tolerance_s,
        )

    def map_tick(self, tick: int) -> tuple[PpsTimeMapping | None, int | None]:
        for segment_index, segment in enumerate(self.segments):
            if len(segment) < 2 or tick < segment[0].tick or tick > segment[-1].tick:
                continue
            for before, after in zip(segment, segment[1:]):
                if before.tick <= tick <= after.tick:
                    tick_span = after.tick - before.tick
                    second_span = after.second - before.second
                    if tick_span <= 0 or second_span <= 0:
                        return None, None
                    second = (
                        before.second
                        + (tick - before.tick) * second_span / tick_span
                    )
                    return (
                        PpsTimeMapping(
                            second=second,
                            before_tick=before.tick,
                            after_tick=after.tick,
                            before_seq=before.seq,
                            after_seq=after.seq,
                            segment_rate_ticks_per_s=tick_span / second_span,
                        ),
                        segment_index,
                    )
        return None, None

    def estimate_gate(
        self,
        gate_open: int,
        gate_close: int,
        counted_edges: int,
    ) -> BoundaryEstimate:
        if gate_close <= gate_open:
            return BoundaryEstimate(False, ("invalid_count_window",))
        if counted_edges <= 0:
            return BoundaryEstimate(False, ("count_zero",))

        open_mapping, open_segment = self.map_tick(gate_open)
        close_mapping, close_segment = self.map_tick(gate_close)
        reasons: list[str] = []
        if open_mapping is None:
            reasons.append("missing_pps_before_or_after_count_window_start")
        if close_mapping is None:
            reasons.append("missing_pps_before_or_after_count_window_end")
        if open_mapping is None or close_mapping is None:
            return BoundaryEstimate(False, tuple(reasons))
        if open_segment != close_segment:
            return BoundaryEstimate(
                False,
                ("count_window_crosses_invalid_pps_segment",),
                pps_time_open=open_mapping.second,
                pps_time_close=close_mapping.second,
                pps_before_open_timestamp=open_mapping.before_tick,
                pps_after_open_timestamp=open_mapping.after_tick,
                pps_before_close_timestamp=close_mapping.before_tick,
                pps_after_close_timestamp=close_mapping.after_tick,
                pps_before_open_seq=open_mapping.before_seq,
                pps_after_open_seq=open_mapping.after_seq,
                pps_before_close_seq=close_mapping.before_seq,
                pps_after_close_seq=close_mapping.after_seq,
            )

        gate_seconds = close_mapping.second - open_mapping.second
        if not math.isfinite(gate_seconds) or gate_seconds <= 0:
            return BoundaryEstimate(
                False,
                ("non_positive_reference_duration",),
            )
        segment = self.segments[open_segment]
        support = [
            point
            for point in segment
            if open_mapping.before_tick <= point.tick <= close_mapping.after_tick
        ]
        observed_gaps = [
            (after.tick - before.tick) / self.domain_hz
            for before, after in zip(support, support[1:])
        ]
        max_gap = max(observed_gaps, default=None)
        if max_gap is not None and max_gap > self.max_gap_seconds:
            return BoundaryEstimate(
                False,
                ("reference_support_gap_exceeded",),
            )
        frequency_hz = counted_edges / gate_seconds
        if not math.isfinite(frequency_hz) or frequency_hz <= 0:
            return BoundaryEstimate(False, ("invalid_frequency_result",))
        return BoundaryEstimate(
            True,
            (),
            pps_time_open=open_mapping.second,
            pps_time_close=close_mapping.second,
            gate_seconds=gate_seconds,
            frequency_hz=frequency_hz,
            pps_before_open_timestamp=open_mapping.before_tick,
            pps_after_open_timestamp=open_mapping.after_tick,
            pps_before_close_timestamp=close_mapping.before_tick,
            pps_after_close_timestamp=close_mapping.after_tick,
            pps_before_open_seq=open_mapping.before_seq,
            pps_after_open_seq=open_mapping.after_seq,
            pps_before_close_seq=close_mapping.before_seq,
            pps_after_close_seq=close_mapping.after_seq,
            pps_support_count=len(support),
            max_pps_gap_seconds=max_gap,
        )
