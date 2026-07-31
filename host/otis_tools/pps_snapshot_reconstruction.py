"""Fail-closed reconstruction of PPS-owned cumulative counter snapshots.

The hardware snapshot backend uses a wrapping 32-bit down-counter.  This
module deliberately depends only on immutable snapshot content: foreground
arrival time and drain latency are retained as evidence but never participate
in interval-count arithmetic.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
from typing import Iterable


UINT32_MODULUS = 1 << 32
UINT32_MASK = UINT32_MODULUS - 1


class SnapshotSequenceRelation(str, Enum):
    ADJACENT = "adjacent"
    DUPLICATE = "duplicate"
    GAP_OR_OUT_OF_ORDER = "gap_or_out_of_order"


@dataclass(frozen=True)
class SnapshotObservation:
    """One immutable hardware snapshot after foreground association.

    ``raw_counter_value`` is the PIO X register value, not an interval count.
    ``foreground_arrival_ticks`` is intentionally diagnostic-only.
    """

    sequence: int
    session_id: str
    raw_counter_value: int
    reference_timestamp_ticks: int
    reference_sequence: int | None = None
    capture_valid: bool = True
    capture_faults: tuple[str, ...] = ()
    foreground_arrival_ticks: int | None = None

    def __post_init__(self) -> None:
        _require_u32(self.sequence, "sequence")
        _require_u32(self.raw_counter_value, "raw_counter_value")
        if not self.session_id:
            raise ValueError("session_id must not be empty")
        if self.reference_timestamp_ticks < 0:
            raise ValueError("reference_timestamp_ticks must be non-negative")
        if self.reference_sequence is not None:
            _require_u32(self.reference_sequence, "reference_sequence")
        if self.foreground_arrival_ticks is not None and self.foreground_arrival_ticks < 0:
            raise ValueError("foreground_arrival_ticks must be non-negative")
        if any(not reason for reason in self.capture_faults):
            raise ValueError("capture_faults must contain non-empty reason codes")


@dataclass(frozen=True)
class ReconstructionPolicy:
    max_oscillator_hz: float
    timestamp_ticks_per_second: float
    timestamp_modulus: int | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("max_oscillator_hz", self.max_oscillator_hz),
            ("timestamp_ticks_per_second", self.timestamp_ticks_per_second),
        ):
            if not math.isfinite(value) or value <= 0:
                raise ValueError(f"{name} must be finite and positive")
        if self.timestamp_modulus is not None and self.timestamp_modulus <= 1:
            raise ValueError("timestamp_modulus must be greater than one")


@dataclass(frozen=True)
class DownCounterDelta:
    count: int
    wrap_handled: bool


@dataclass(frozen=True)
class SnapshotReconstruction:
    state: str
    session_id: str
    closing_sequence: int
    opening_sequence: int | None = None
    interval_count: int | None = None
    elapsed_reference_ticks: int | None = None
    sequence_relation: SnapshotSequenceRelation | None = None
    counter_wrap_handled: bool = False
    sequence_wrap_handled: bool = False
    timestamp_wrap_handled: bool = False
    reasons: tuple[str, ...] = ()

    @property
    def valid(self) -> bool:
        return self.state == "valid"

    @property
    def anchor_only(self) -> bool:
        return self.state == "anchor"


def _require_u32(value: int, name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= UINT32_MASK:
        raise ValueError(f"{name} must be an unsigned 32-bit integer")


def down_counter_delta_u32(previous_x: int, current_x: int) -> DownCounterDelta:
    """Return ``(previous_x - current_x) mod 2^32`` for a PIO down-counter."""

    _require_u32(previous_x, "previous_x")
    _require_u32(current_x, "current_x")
    return DownCounterDelta(
        count=(previous_x - current_x) & UINT32_MASK,
        wrap_handled=current_x > previous_x,
    )


def snapshot_sequence_relation_u32(
    previous_sequence: int, current_sequence: int
) -> SnapshotSequenceRelation:
    _require_u32(previous_sequence, "previous_sequence")
    _require_u32(current_sequence, "current_sequence")
    distance = (current_sequence - previous_sequence) & UINT32_MASK
    if distance == 1:
        return SnapshotSequenceRelation.ADJACENT
    if distance == 0:
        return SnapshotSequenceRelation.DUPLICATE
    return SnapshotSequenceRelation.GAP_OR_OUT_OF_ORDER


def _elapsed_ticks(
    opening: int, closing: int, modulus: int | None
) -> tuple[int | None, bool]:
    if closing > opening:
        return closing - opening, False
    if closing == opening:
        return None, False
    if modulus is None or opening >= modulus or closing >= modulus:
        return None, False
    elapsed = (closing - opening) % modulus
    return (elapsed, True) if elapsed > 0 else (None, False)


class SnapshotReconstructor:
    """Stateful adjacent-pair reconstruction with explicit reacquisition."""

    def __init__(self, policy: ReconstructionPolicy):
        self.policy = policy
        self._anchor: SnapshotObservation | None = None
        self._ever_anchored = False
        self._reacquiring = False

    @property
    def anchor(self) -> SnapshotObservation | None:
        return self._anchor

    def clear_anchor(self) -> None:
        self._anchor = None
        self._reacquiring = True

    def _anchor_result(
        self, observation: SnapshotObservation, *reasons: str
    ) -> SnapshotReconstruction:
        self._anchor = observation
        self._ever_anchored = True
        return SnapshotReconstruction(
            state="anchor",
            session_id=observation.session_id,
            closing_sequence=observation.sequence,
            reasons=tuple(reasons),
        )

    def _invalid_result(
        self,
        observation: SnapshotObservation,
        *,
        previous: SnapshotObservation | None = None,
        relation: SnapshotSequenceRelation | None = None,
        reasons: tuple[str, ...],
        retain_current_as_anchor: bool,
        elapsed_ticks: int | None = None,
        timestamp_wrap: bool = False,
    ) -> SnapshotReconstruction:
        self._anchor = observation if retain_current_as_anchor else None
        self._ever_anchored = self._ever_anchored or retain_current_as_anchor
        self._reacquiring = True
        return SnapshotReconstruction(
            state="invalid",
            session_id=observation.session_id,
            opening_sequence=previous.sequence if previous is not None else None,
            closing_sequence=observation.sequence,
            elapsed_reference_ticks=elapsed_ticks,
            sequence_relation=relation,
            sequence_wrap_handled=(
                previous is not None
                and relation is SnapshotSequenceRelation.ADJACENT
                and previous.sequence == UINT32_MASK
                and observation.sequence == 0
            ),
            timestamp_wrap_handled=timestamp_wrap,
            reasons=reasons,
        )

    def observe(self, observation: SnapshotObservation) -> SnapshotReconstruction:
        if not observation.capture_valid or observation.capture_faults:
            reasons = ["capture_invalid"] if not observation.capture_valid else []
            reasons.extend(observation.capture_faults)
            return self._invalid_result(
                observation,
                reasons=tuple(dict.fromkeys(reasons)),
                retain_current_as_anchor=False,
            )

        previous = self._anchor
        if previous is None:
            reason = (
                "reacquisition_anchor"
                if self._reacquiring or self._ever_anchored
                else "first_anchor"
            )
            return self._anchor_result(observation, reason)

        if observation.session_id != previous.session_id:
            self._reacquiring = True
            return self._anchor_result(observation, "session_boundary")

        relation = snapshot_sequence_relation_u32(
            previous.sequence, observation.sequence
        )
        if relation is not SnapshotSequenceRelation.ADJACENT:
            reason = (
                "snapshot_sequence_duplicate"
                if relation is SnapshotSequenceRelation.DUPLICATE
                else "snapshot_sequence_gap_or_out_of_order"
            )
            return self._invalid_result(
                observation,
                previous=previous,
                relation=relation,
                reasons=(reason,),
                retain_current_as_anchor=True,
            )

        if (
            previous.reference_sequence is not None
            and observation.reference_sequence is not None
        ):
            reference_relation = snapshot_sequence_relation_u32(
                previous.reference_sequence, observation.reference_sequence
            )
            if reference_relation is not SnapshotSequenceRelation.ADJACENT:
                reason = (
                    "reference_sequence_duplicate"
                    if reference_relation is SnapshotSequenceRelation.DUPLICATE
                    else "reference_sequence_gap_or_out_of_order"
                )
                return self._invalid_result(
                    observation,
                    previous=previous,
                    relation=relation,
                    reasons=(reason,),
                    retain_current_as_anchor=True,
                )

        elapsed_ticks, timestamp_wrap = _elapsed_ticks(
            previous.reference_timestamp_ticks,
            observation.reference_timestamp_ticks,
            self.policy.timestamp_modulus,
        )
        if elapsed_ticks is None:
            return self._invalid_result(
                observation,
                previous=previous,
                relation=relation,
                reasons=("reference_interval_non_positive_or_ambiguous",),
                retain_current_as_anchor=True,
            )

        maximum_edges = (
            elapsed_ticks
            * self.policy.max_oscillator_hz
            / self.policy.timestamp_ticks_per_second
        )
        if maximum_edges >= UINT32_MODULUS:
            return self._invalid_result(
                observation,
                previous=previous,
                relation=relation,
                reasons=("counter_full_wrap_cannot_be_excluded",),
                retain_current_as_anchor=True,
                elapsed_ticks=elapsed_ticks,
                timestamp_wrap=timestamp_wrap,
            )

        delta = down_counter_delta_u32(
            previous.raw_counter_value, observation.raw_counter_value
        )
        if delta.count == 0:
            return self._invalid_result(
                observation,
                previous=previous,
                relation=relation,
                reasons=("count_zero",),
                retain_current_as_anchor=True,
                elapsed_ticks=elapsed_ticks,
                timestamp_wrap=timestamp_wrap,
            )

        self._anchor = observation
        self._reacquiring = False
        return SnapshotReconstruction(
            state="valid",
            session_id=observation.session_id,
            opening_sequence=previous.sequence,
            closing_sequence=observation.sequence,
            interval_count=delta.count,
            elapsed_reference_ticks=elapsed_ticks,
            sequence_relation=relation,
            counter_wrap_handled=delta.wrap_handled,
            sequence_wrap_handled=(
                previous.sequence == UINT32_MASK and observation.sequence == 0
            ),
            timestamp_wrap_handled=timestamp_wrap,
            reasons=(),
        )


def reconstruct_snapshots(
    observations: Iterable[SnapshotObservation], policy: ReconstructionPolicy
) -> tuple[SnapshotReconstruction, ...]:
    reconstructor = SnapshotReconstructor(policy)
    return tuple(reconstructor.observe(observation) for observation in observations)
