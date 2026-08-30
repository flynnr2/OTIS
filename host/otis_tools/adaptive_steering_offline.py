"""Pure primitives for the adaptive-steering offline evidence programme.

This module deliberately has no repository, package, device, process, or clock I/O.
It provides exact, reusable mechanics for a separate provenance-preserving derived
evidence generator.  Values that participate in controller decisions are retained as
``Fraction`` instances; callers must make any conversion to display-only floating
point explicit.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from decimal import Decimal
from enum import Enum
from fractions import Fraction
import math
from typing import Any, Mapping, Sequence, Tuple, Union


ExactInput = Union[int, str, Decimal, Fraction]


def _as_fraction(value: ExactInput, *, name: str = "value") -> Fraction:
    """Return an exact rational, rejecting binary floating-point inputs."""

    if isinstance(value, bool) or isinstance(value, float):
        raise TypeError(f"{name} must be an exact integer, decimal, string, or Fraction")
    try:
        return value if isinstance(value, Fraction) else Fraction(value)
    except (TypeError, ValueError, ZeroDivisionError) as exc:
        raise TypeError(f"{name} is not an exact rational value") from exc


# ---------------------------------------------------------------------------
# Continuity segmentation


@dataclass(frozen=True)
class CounterRule:
    """Continuity rule for a counter carried by every included record.

    ``modulus=None`` declares a non-wrapping counter.  A wrapping counter must
    declare its modulus.  ``maximum_forward_delta`` prevents a mathematically
    possible wrap from hiding a gap or implausible movement.
    """

    key: str
    modulus: int | None = None
    maximum_forward_delta: int | None = None
    allow_equal: bool = False

    def __post_init__(self) -> None:
        if not self.key:
            raise ValueError("counter key must be nonempty")
        if self.modulus is not None and self.modulus <= 1:
            raise ValueError("counter modulus must be greater than one")
        if self.maximum_forward_delta is not None and self.maximum_forward_delta <= 0:
            raise ValueError("maximum_forward_delta must be positive")
        if (
            self.modulus is not None
            and self.maximum_forward_delta is not None
            and self.maximum_forward_delta >= self.modulus
        ):
            raise ValueError("maximum_forward_delta must be smaller than modulus")


@dataclass(frozen=True)
class ContinuityRequest:
    """The exact continuity dimensions requested by an analysis population."""

    identity_keys: Tuple[str, ...] = ()
    consecutive_keys: Tuple[str, ...] = ()
    valid_keys: Tuple[str, ...] = ()
    counter_rules: Tuple[CounterRule, ...] = ()
    explicit_break_key: str | None = None

    def __post_init__(self) -> None:
        requested = [
            *self.identity_keys,
            *self.consecutive_keys,
            *self.valid_keys,
            *(rule.key for rule in self.counter_rules),
        ]
        if any(not key for key in requested):
            raise ValueError("continuity keys must be nonempty")
        if len(requested) != len(set(requested)):
            raise ValueError("a continuity key may have only one rule")


@dataclass(frozen=True)
class ContinuityBreak:
    """A boundary immediately before, or exclusion of, ``record_index``."""

    record_index: int
    reasons: Tuple[str, ...]
    record_excluded: bool


@dataclass(frozen=True)
class ContinuitySegment:
    segment_index: int
    record_indices: Tuple[int, ...]

    @property
    def start_index(self) -> int:
        return self.record_indices[0]

    @property
    def end_index(self) -> int:
        return self.record_indices[-1]


@dataclass(frozen=True)
class ContinuitySegmentation:
    segments: Tuple[ContinuitySegment, ...]
    breaks: Tuple[ContinuityBreak, ...]
    excluded_record_indices: Tuple[int, ...]


def _integer_field(record: Mapping[str, Any], key: str) -> int | None:
    value = record.get(key)
    return value if isinstance(value, int) and not isinstance(value, bool) else None


def segment_continuity(
    records: Sequence[Mapping[str, Any]], request: ContinuityRequest
) -> ContinuitySegmentation:
    """Segment records without bridging any requested continuity boundary.

    Missing/invalid records are excluded.  A valid record at an identity,
    sequence, counter, or declared boundary begins a new segment and remains
    available to that segment.  Every such choice is represented by a stable,
    machine-readable reason string.
    """

    segments: list[ContinuitySegment] = []
    breaks: list[ContinuityBreak] = []
    excluded: list[int] = []
    active_indices: list[int] = []
    previous: Mapping[str, Any] | None = None

    def close_segment() -> None:
        nonlocal active_indices
        if active_indices:
            segments.append(
                ContinuitySegment(len(segments), tuple(active_indices))
            )
            active_indices = []

    all_required_keys = (
        *request.identity_keys,
        *request.consecutive_keys,
        *request.valid_keys,
        *(rule.key for rule in request.counter_rules),
    )

    for index, record in enumerate(records):
        exclusion_reasons = tuple(
            f"missing_key:{key}" for key in all_required_keys if key not in record
        )
        if not exclusion_reasons:
            exclusion_reasons = tuple(
                f"invalid_flag:{key}" for key in request.valid_keys if record[key] is not True
            )
        if not exclusion_reasons:
            bad_sequences = tuple(
                f"invalid_integer:{key}"
                for key in request.consecutive_keys
                if _integer_field(record, key) is None
            )
            bad_counters = tuple(
                f"invalid_integer:{rule.key}"
                for rule in request.counter_rules
                if _integer_field(record, rule.key) is None
                or (
                    rule.modulus is not None
                    and not 0 <= int(record[rule.key]) < rule.modulus
                )
            )
            exclusion_reasons = (*bad_sequences, *bad_counters)

        if exclusion_reasons:
            close_segment()
            breaks.append(ContinuityBreak(index, exclusion_reasons, True))
            excluded.append(index)
            previous = None
            continue

        boundary_reasons: list[str] = []
        if request.explicit_break_key is not None:
            declared = record.get(request.explicit_break_key)
            if declared not in (None, "", False):
                boundary_reasons.append(f"explicit_break:{declared}")

        if previous is not None:
            for key in request.identity_keys:
                if record[key] != previous[key]:
                    boundary_reasons.append(f"identity_changed:{key}")
            for key in request.consecutive_keys:
                if int(record[key]) != int(previous[key]) + 1:
                    boundary_reasons.append(f"nonconsecutive:{key}")
            for rule in request.counter_rules:
                before = int(previous[rule.key])
                after = int(record[rule.key])
                if rule.modulus is None:
                    delta = after - before
                    if delta < 0:
                        boundary_reasons.append(
                            f"illegal_backward_movement:{rule.key}"
                        )
                        continue
                else:
                    delta = (after - before) % rule.modulus
                if delta == 0 and not rule.allow_equal:
                    boundary_reasons.append(f"counter_not_advanced:{rule.key}")
                elif (
                    rule.maximum_forward_delta is not None
                    and delta > rule.maximum_forward_delta
                ):
                    boundary_reasons.append(f"counter_gap:{rule.key}")

        if boundary_reasons:
            close_segment()
            breaks.append(ContinuityBreak(index, tuple(boundary_reasons), False))

        active_indices.append(index)
        previous = record

    close_segment()
    return ContinuitySegmentation(tuple(segments), tuple(breaks), tuple(excluded))


# ---------------------------------------------------------------------------
# Exact overlapping Allan and Hadamard deviation


class DeviationStatistic(str, Enum):
    ALLAN = "overlapping_allan_deviation"
    HADAMARD = "overlapping_hadamard_deviation"


class InsufficientDeviationSupport(ValueError):
    def __init__(
        self,
        statistic: DeviationStatistic,
        sample_count: int,
        averaging_factor: int,
        term_count: int,
        minimum_term_count: int,
    ) -> None:
        self.statistic = statistic
        self.sample_count = sample_count
        self.averaging_factor = averaging_factor
        self.term_count = term_count
        self.minimum_term_count = minimum_term_count
        super().__init__(
            f"{statistic.value} has {term_count} terms; "
            f"minimum is {minimum_term_count}"
        )


@dataclass(frozen=True)
class DeviationEstimate:
    statistic: DeviationStatistic
    averaging_factor: int
    base_sampling_interval: Fraction
    tau: Fraction
    sample_count: int
    term_count: int
    squared_difference_sum: Fraction
    normalization: int
    variance: Fraction
    population_count: int = 1

    @property
    def deviation(self) -> float:
        return math.sqrt(float(self.variance))

    def equivalent_hz(self, nominal_frequency_hz: ExactInput = 10_000_000) -> float:
        nominal = _as_fraction(nominal_frequency_hz, name="nominal_frequency_hz")
        if nominal <= 0:
            raise ValueError("nominal_frequency_hz must be positive")
        return self.deviation * float(nominal)


def _overlapping_deviation(
    fractional_frequency_samples: Sequence[ExactInput],
    *,
    statistic: DeviationStatistic,
    averaging_factor: int,
    base_sampling_interval: ExactInput,
    minimum_term_count: int,
) -> DeviationEstimate:
    if (
        not isinstance(averaging_factor, int)
        or isinstance(averaging_factor, bool)
        or averaging_factor <= 0
    ):
        raise ValueError("averaging_factor must be a positive integer")
    if (
        not isinstance(minimum_term_count, int)
        or isinstance(minimum_term_count, bool)
        or minimum_term_count <= 0
    ):
        raise ValueError("minimum_term_count must be a positive integer")
    base = _as_fraction(base_sampling_interval, name="base_sampling_interval")
    if base <= 0:
        raise ValueError("base_sampling_interval must be positive")
    samples = tuple(
        _as_fraction(value, name="fractional_frequency_sample")
        for value in fractional_frequency_samples
    )
    block_count = 2 if statistic is DeviationStatistic.ALLAN else 3
    term_count = len(samples) - block_count * averaging_factor + 1
    if term_count < minimum_term_count:
        raise InsufficientDeviationSupport(
            statistic,
            len(samples),
            averaging_factor,
            max(0, term_count),
            minimum_term_count,
        )

    prefix = [Fraction(0)]
    for sample in samples:
        prefix.append(prefix[-1] + sample)

    def mean(opening: int) -> Fraction:
        closing = opening + averaging_factor
        return (prefix[closing] - prefix[opening]) / averaging_factor

    squared_difference_sum = Fraction(0)
    for opening in range(term_count):
        first = mean(opening)
        second = mean(opening + averaging_factor)
        if statistic is DeviationStatistic.ALLAN:
            difference = second - first
        else:
            third = mean(opening + 2 * averaging_factor)
            difference = third - 2 * second + first
        squared_difference_sum += difference * difference

    normalization = 2 if statistic is DeviationStatistic.ALLAN else 6
    variance = squared_difference_sum / (normalization * term_count)
    return DeviationEstimate(
        statistic=statistic,
        averaging_factor=averaging_factor,
        base_sampling_interval=base,
        tau=base * averaging_factor,
        sample_count=len(samples),
        term_count=term_count,
        squared_difference_sum=squared_difference_sum,
        normalization=normalization,
        variance=variance,
    )


def overlapping_allan_deviation(
    fractional_frequency_samples: Sequence[ExactInput],
    *,
    averaging_factor: int,
    base_sampling_interval: ExactInput = 1,
    minimum_term_count: int = 1,
) -> DeviationEstimate:
    """Compute overlapping Allan deviation from one contiguous population."""

    return _overlapping_deviation(
        fractional_frequency_samples,
        statistic=DeviationStatistic.ALLAN,
        averaging_factor=averaging_factor,
        base_sampling_interval=base_sampling_interval,
        minimum_term_count=minimum_term_count,
    )


def overlapping_hadamard_deviation(
    fractional_frequency_samples: Sequence[ExactInput],
    *,
    averaging_factor: int,
    base_sampling_interval: ExactInput = 1,
    minimum_term_count: int = 1,
) -> DeviationEstimate:
    """Compute overlapping Hadamard deviation from one contiguous population."""

    return _overlapping_deviation(
        fractional_frequency_samples,
        statistic=DeviationStatistic.HADAMARD,
        averaging_factor=averaging_factor,
        base_sampling_interval=base_sampling_interval,
        minimum_term_count=minimum_term_count,
    )


def pool_deviation_estimates(
    estimates: Sequence[DeviationEstimate],
) -> DeviationEstimate:
    """Pool same-tau segment numerators without stitching segment endpoints."""

    if not estimates:
        raise ValueError("at least one deviation estimate is required")
    reference = estimates[0]
    compatible = (
        reference.statistic,
        reference.averaging_factor,
        reference.base_sampling_interval,
        reference.tau,
        reference.normalization,
    )
    for estimate in estimates[1:]:
        candidate = (
            estimate.statistic,
            estimate.averaging_factor,
            estimate.base_sampling_interval,
            estimate.tau,
            estimate.normalization,
        )
        if candidate != compatible:
            raise ValueError("only estimates of the same statistic and tau may be pooled")
    term_count = sum(estimate.term_count for estimate in estimates)
    numerator = sum(
        (estimate.squared_difference_sum for estimate in estimates), Fraction(0)
    )
    return DeviationEstimate(
        statistic=reference.statistic,
        averaging_factor=reference.averaging_factor,
        base_sampling_interval=reference.base_sampling_interval,
        tau=reference.tau,
        sample_count=sum(estimate.sample_count for estimate in estimates),
        term_count=term_count,
        squared_difference_sum=numerator,
        normalization=reference.normalization,
        variance=numerator / (reference.normalization * term_count),
        population_count=sum(estimate.population_count for estimate in estimates),
    )


# ---------------------------------------------------------------------------
# Exact rounding and interval sign


def round_half_away_from_zero(value: ExactInput) -> int:
    """Round an exact rational to nearest integer, resolving halves outward."""

    rational = _as_fraction(value)
    magnitude = abs(rational)
    rounded_magnitude = (
        2 * magnitude.numerator + magnitude.denominator
    ) // (2 * magnitude.denominator)
    return rounded_magnitude if rational >= 0 else -rounded_magnitude


class IntervalSign(str, Enum):
    NEGATIVE = "negative"
    CONTAINS_ZERO = "contains_zero"
    POSITIVE = "positive"


@dataclass(frozen=True)
class RationalInterval:
    lower: Fraction
    upper: Fraction

    def __post_init__(self) -> None:
        lower = _as_fraction(self.lower, name="interval lower")
        upper = _as_fraction(self.upper, name="interval upper")
        if lower > upper:
            raise ValueError("interval lower bound exceeds upper bound")
        object.__setattr__(self, "lower", lower)
        object.__setattr__(self, "upper", upper)

    @property
    def sign(self) -> IntervalSign:
        if self.lower > 0:
            return IntervalSign.POSITIVE
        if self.upper < 0:
            return IntervalSign.NEGATIVE
        return IntervalSign.CONTAINS_ZERO

    def __add__(self, other: "RationalInterval") -> "RationalInterval":
        return RationalInterval(self.lower + other.lower, self.upper + other.upper)

    def divide_by_positive_interval(
        self, denominator: "RationalInterval"
    ) -> "RationalInterval":
        if denominator.lower <= 0:
            raise ValueError("plant-gain interval must be strictly positive")
        quotients = (
            self.lower / denominator.lower,
            self.lower / denominator.upper,
            self.upper / denominator.lower,
            self.upper / denominator.upper,
        )
        return RationalInterval(min(quotients), max(quotients))


def combined_correction_demand_interval(
    fll_frequency_demand: RationalInterval,
    pll_frequency_demand: RationalInterval,
    *,
    positive_plant_gain: RationalInterval | None = None,
) -> RationalInterval:
    """Combine bounded FLL/PLL demand and optionally convert it to code demand."""

    combined = fll_frequency_demand + pll_frequency_demand
    return (
        combined
        if positive_plant_gain is None
        else combined.divide_by_positive_interval(positive_plant_gain)
    )


# ---------------------------------------------------------------------------
# Tagged correction-debt transaction state


class DebtMode(str, Enum):
    ACTIVE = "active"
    HOLD = "hold"
    FROZEN = "frozen"
    FLL_FALLBACK = "fll_fallback"
    IDENTITY_FAULT = "identity_fault"


class ProposalStatus(str, Enum):
    PROPOSED = "proposed"
    ACCEPTED = "accepted"


class DebtEvent(str, Enum):
    REQUEST_PROPOSED = "request_proposed"
    PROPOSAL_ACCEPTED = "proposal_accepted"
    DEBT_UPDATED_WITHOUT_REQUEST = "debt_updated_without_request"
    APPLICATION_COMMITTED = "application_committed"
    RESPONSE_COMPLETED = "response_completed"
    PROPOSAL_REJECTED = "proposal_rejected"
    PROPOSAL_EXPIRED = "proposal_expired"
    SUPPRESSED = "suppressed"
    HOLD_ENTERED = "hold_entered"
    REQUALIFIED = "requalified"
    FROZEN = "frozen"
    PLL_DEBT_DISCARDED = "pll_debt_discarded"
    DEBT_RESET = "debt_reset"
    IDENTITY_FAULT = "identity_fault"


@dataclass(frozen=True)
class DebtProvenance:
    policy_id: str
    plant_gain_id: str
    capture_session: str
    estimator_id: str
    evidence_frontier: int
    applied_code: int
    dac_epoch: int
    phase_epoch: str | None = None
    phase_frontier: int | None = None

    def __post_init__(self) -> None:
        for name in ("policy_id", "plant_gain_id", "capture_session", "estimator_id"):
            if not getattr(self, name):
                raise ValueError(f"{name} must be nonempty")
        if self.evidence_frontier < 0 or self.dac_epoch < 0:
            raise ValueError("evidence frontier and DAC epoch must be nonnegative")
        if (self.phase_epoch is None) != (self.phase_frontier is None):
            raise ValueError("phase epoch and frontier must be present together")
        if self.phase_frontier is not None and self.phase_frontier < 0:
            raise ValueError("phase frontier must be nonnegative")


@dataclass(frozen=True)
class TaggedCorrectionDebt:
    fll_codes: Fraction
    pll_codes: Fraction
    provenance: DebtProvenance
    update_reason: str

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "fll_codes", _as_fraction(self.fll_codes, name="fll debt")
        )
        object.__setattr__(
            self, "pll_codes", _as_fraction(self.pll_codes, name="pll debt")
        )
        if not self.update_reason:
            raise ValueError("debt update reason must be nonempty")

    @property
    def total_codes(self) -> Fraction:
        return self.fll_codes + self.pll_codes


@dataclass(frozen=True)
class DebtLimits:
    minimum_code: int
    maximum_code: int
    maximum_step_codes: int
    maximum_abs_committed_debt_codes: Fraction

    def __post_init__(self) -> None:
        maximum_debt = _as_fraction(
            self.maximum_abs_committed_debt_codes,
            name="maximum_abs_committed_debt_codes",
        )
        object.__setattr__(self, "maximum_abs_committed_debt_codes", maximum_debt)
        if any(
            isinstance(value, bool) or not isinstance(value, int)
            for value in (
                self.minimum_code,
                self.maximum_code,
                self.maximum_step_codes,
            )
        ):
            raise ValueError("code and step limits must be integers")
        if self.minimum_code >= self.maximum_code:
            raise ValueError("minimum_code must be lower than maximum_code")
        if self.maximum_step_codes <= 0 or maximum_debt <= 0:
            raise ValueError("step and debt limits must be positive")


@dataclass(frozen=True)
class PendingDebtProposal:
    decision_id: str
    request_id: str
    provenance: DebtProvenance
    prior_committed: TaggedCorrectionDebt
    raw_fll_increment_codes: Fraction
    raw_pll_increment_codes: Fraction
    candidate_fll_codes: Fraction
    candidate_pll_codes: Fraction
    limited_fll_codes: Fraction
    limited_pll_codes: Fraction
    limited_total_codes: Fraction
    integer_request_delta_codes: int
    requested_code: int
    maximum_abs_committed_debt_codes: Fraction
    limit_reasons: Tuple[str, ...]
    status: ProposalStatus = ProposalStatus.PROPOSED


@dataclass(frozen=True)
class CorrectionDebtState:
    committed: TaggedCorrectionDebt
    mode: DebtMode = DebtMode.ACTIVE
    mode_reason: str = "initialized"
    pending: PendingDebtProposal | None = None
    response_pending_request_id: str | None = None

    @property
    def actionable(self) -> bool:
        return (
            self.mode in (DebtMode.ACTIVE, DebtMode.FLL_FALLBACK)
            and self.pending is None
            and self.response_pending_request_id is None
        )


@dataclass(frozen=True)
class DebtTransition:
    state: CorrectionDebtState
    event: DebtEvent
    reason: str
    proposal: PendingDebtProposal | None = None
    limit_reasons: Tuple[str, ...] = ()


class OutstandingDebtTransitionError(RuntimeError):
    pass


def initial_correction_debt(provenance: DebtProvenance) -> CorrectionDebtState:
    return CorrectionDebtState(
        committed=TaggedCorrectionDebt(
            Fraction(0), Fraction(0), provenance, "initialized_zero_debt"
        )
    )


def _identity_contradictions(
    committed: DebtProvenance, current: DebtProvenance
) -> Tuple[str, ...]:
    fields = (
        "policy_id",
        "plant_gain_id",
        "capture_session",
        "estimator_id",
        "applied_code",
        "dac_epoch",
    )
    return tuple(
        f"identity_contradiction:{field}"
        for field in fields
        if getattr(committed, field) != getattr(current, field)
    )


def fail_correction_debt_identity(
    state: CorrectionDebtState, reason: str
) -> DebtTransition:
    if not reason:
        raise ValueError("identity fault reason must be nonempty")
    faulted = replace(state, mode=DebtMode.IDENTITY_FAULT, mode_reason=reason)
    return DebtTransition(faulted, DebtEvent.IDENTITY_FAULT, reason)


def _clamp_fraction(value: Fraction, lower: Fraction, upper: Fraction) -> Fraction:
    return min(upper, max(lower, value))


def _allocate_limited_components(
    fll: Fraction, pll: Fraction, limited_total: Fraction
) -> tuple[Fraction, Fraction]:
    """Apply an explicit proportional component back-calculation rule."""

    total = fll + pll
    if limited_total == total:
        return fll, pll
    if total == 0:
        if limited_total != 0:
            raise ValueError("zero component total cannot allocate nonzero demand")
        return fll, pll
    scale = limited_total / total
    return fll * scale, pll * scale


def _cancel_opposing_components(
    fll: Fraction, pll: Fraction
) -> tuple[Fraction, Fraction]:
    """Remove equal-and-opposite hidden authority before retaining tags."""

    if fll == 0 or pll == 0 or (fll > 0) == (pll > 0):
        return fll, pll
    total = fll + pll
    if total == 0:
        return Fraction(0), Fraction(0)
    if (total > 0) == (fll > 0):
        return total, Fraction(0)
    return Fraction(0), total


def evaluate_correction_debt(
    state: CorrectionDebtState,
    *,
    provenance: DebtProvenance,
    decision_id: str,
    request_id: str,
    raw_fll_increment_codes: ExactInput,
    raw_pll_increment_codes: ExactInput,
    limits: DebtLimits,
) -> DebtTransition:
    """Evaluate one otherwise eligible, cadence-eligible causal decision.

    A nonzero integer result creates an immutable pending proposal while leaving
    committed debt untouched.  A zero result atomically commits the bounded
    post-limit residual without creating a transaction.
    """

    if not decision_id or not request_id:
        raise ValueError("decision_id and request_id must be nonempty")
    if state.mode not in (DebtMode.ACTIVE, DebtMode.FLL_FALLBACK):
        reason = f"mode:{state.mode.value}:{state.mode_reason}"
        return DebtTransition(state, DebtEvent.SUPPRESSED, reason)
    if state.pending is not None:
        return DebtTransition(state, DebtEvent.SUPPRESSED, "transaction_outstanding")
    if state.response_pending_request_id is not None:
        return DebtTransition(state, DebtEvent.SUPPRESSED, "response_outstanding")

    fll_increment = _as_fraction(raw_fll_increment_codes, name="raw FLL increment")
    pll_increment = _as_fraction(raw_pll_increment_codes, name="raw PLL increment")
    if state.mode is DebtMode.FLL_FALLBACK and pll_increment != 0:
        return DebtTransition(
            state, DebtEvent.SUPPRESSED, "pll_increment_forbidden_in_fll_fallback"
        )

    contradictions = _identity_contradictions(state.committed.provenance, provenance)
    if contradictions:
        return fail_correction_debt_identity(state, ";".join(contradictions))
    if not limits.minimum_code <= provenance.applied_code <= limits.maximum_code:
        return fail_correction_debt_identity(
            state, "applied_code_outside_declared_range"
        )
    if provenance.evidence_frontier <= state.committed.provenance.evidence_frontier:
        return DebtTransition(state, DebtEvent.SUPPRESSED, "noncausal_evidence_frontier")

    phase_is_material = state.committed.pll_codes != 0 or pll_increment != 0
    if phase_is_material:
        prior = state.committed.provenance
        if provenance.phase_epoch is None:
            return DebtTransition(state, DebtEvent.SUPPRESSED, "phase_frontier_unavailable")
        if prior.phase_epoch is not None and provenance.phase_epoch != prior.phase_epoch:
            return DebtTransition(
                state,
                DebtEvent.SUPPRESSED,
                "phase_epoch_changed_requires_pll_discard",
            )
        if (
            prior.phase_frontier is not None
            and provenance.phase_frontier is not None
            and provenance.phase_frontier <= prior.phase_frontier
        ):
            return DebtTransition(state, DebtEvent.SUPPRESSED, "noncausal_phase_frontier")

    candidate_fll = state.committed.fll_codes + fll_increment
    candidate_pll = state.committed.pll_codes + pll_increment
    residual_cap = limits.maximum_abs_committed_debt_codes
    reasons: list[str] = []

    # At a hard endpoint discard only outward component debt before combining;
    # an opposing inward component remains eligible to move off the endpoint.
    backcalculated_fll = candidate_fll
    backcalculated_pll = candidate_pll
    if provenance.applied_code == limits.maximum_code:
        if backcalculated_fll > 0:
            backcalculated_fll = Fraction(0)
            reasons.append("upper_endpoint_fll_backcalculated")
        if backcalculated_pll > 0:
            backcalculated_pll = Fraction(0)
            reasons.append("upper_endpoint_pll_backcalculated")
    elif provenance.applied_code == limits.minimum_code:
        if backcalculated_fll < 0:
            backcalculated_fll = Fraction(0)
            reasons.append("lower_endpoint_fll_backcalculated")
        if backcalculated_pll < 0:
            backcalculated_pll = Fraction(0)
            reasons.append("lower_endpoint_pll_backcalculated")

    backcalculated_fll, backcalculated_pll = _cancel_opposing_components(
        backcalculated_fll, backcalculated_pll
    )
    candidate_total = backcalculated_fll + backcalculated_pll
    lower = max(
        Fraction(-limits.maximum_step_codes),
        Fraction(limits.minimum_code - provenance.applied_code),
    )
    upper = min(
        Fraction(limits.maximum_step_codes),
        Fraction(limits.maximum_code - provenance.applied_code),
    )
    limited_total = _clamp_fraction(candidate_total, lower, upper)
    if limited_total != candidate_total:
        if abs(candidate_total) > limits.maximum_step_codes:
            reasons.append("step_backcalculated")
        if not (
            limits.minimum_code
            <= provenance.applied_code + candidate_total
            <= limits.maximum_code
        ):
            reasons.append("range_backcalculated")
    limited_fll, limited_pll = _allocate_limited_components(
        backcalculated_fll, backcalculated_pll, limited_total
    )
    integer_request = round_half_away_from_zero(limited_total)
    requested_code = provenance.applied_code + integer_request
    if not limits.minimum_code <= requested_code <= limits.maximum_code:
        return fail_correction_debt_identity(state, "rounded_request_outside_range")

    if integer_request == 0:
        committed_total = _clamp_fraction(
            limited_total, -residual_cap, residual_cap
        )
        if committed_total != limited_total:
            reasons.append("committed_residual_debt_capped")
        committed_fll, committed_pll = _allocate_limited_components(
            limited_fll, limited_pll, committed_total
        )
        committed = TaggedCorrectionDebt(
            committed_fll,
            committed_pll,
            provenance,
            "debt_updated_without_request",
        )
        updated = replace(
            state,
            committed=committed,
            mode_reason="debt_updated_without_request",
        )
        return DebtTransition(
            updated,
            DebtEvent.DEBT_UPDATED_WITHOUT_REQUEST,
            "debt_updated_without_request",
            limit_reasons=tuple(reasons),
        )

    pending = PendingDebtProposal(
        decision_id=decision_id,
        request_id=request_id,
        provenance=provenance,
        prior_committed=state.committed,
        raw_fll_increment_codes=fll_increment,
        raw_pll_increment_codes=pll_increment,
        candidate_fll_codes=candidate_fll,
        candidate_pll_codes=candidate_pll,
        limited_fll_codes=limited_fll,
        limited_pll_codes=limited_pll,
        limited_total_codes=limited_total,
        integer_request_delta_codes=integer_request,
        requested_code=requested_code,
        maximum_abs_committed_debt_codes=residual_cap,
        limit_reasons=tuple(reasons),
    )
    proposed = replace(state, pending=pending, mode_reason="request_proposed")
    return DebtTransition(
        proposed,
        DebtEvent.REQUEST_PROPOSED,
        "request_proposed",
        pending,
        tuple(reasons),
    )


def mark_debt_proposal_accepted(
    state: CorrectionDebtState, request_id: str
) -> DebtTransition:
    pending = state.pending
    if pending is None or pending.request_id != request_id:
        return fail_correction_debt_identity(state, "acceptance_identity_mismatch")
    if pending.status is ProposalStatus.ACCEPTED:
        return fail_correction_debt_identity(state, "duplicate_acceptance")
    accepted = replace(pending, status=ProposalStatus.ACCEPTED)
    updated = replace(state, pending=accepted, mode_reason="proposal_accepted")
    return DebtTransition(updated, DebtEvent.PROPOSAL_ACCEPTED, "proposal_accepted", accepted)


def resolve_unaccepted_debt_proposal(
    state: CorrectionDebtState, *, request_id: str, outcome: str
) -> DebtTransition:
    if outcome not in ("rejected", "expired"):
        raise ValueError("outcome must be 'rejected' or 'expired'")
    pending = state.pending
    if pending is None or pending.request_id != request_id:
        return fail_correction_debt_identity(state, f"{outcome}_identity_mismatch")
    if pending.status is ProposalStatus.ACCEPTED:
        return fail_correction_debt_identity(
            state, f"{outcome}_after_acceptance"
        )
    updated = replace(state, pending=None, mode_reason=f"proposal_{outcome}")
    event = (
        DebtEvent.PROPOSAL_REJECTED
        if outcome == "rejected"
        else DebtEvent.PROPOSAL_EXPIRED
    )
    return DebtTransition(updated, event, f"proposal_{outcome}")


def commit_debt_application(
    state: CorrectionDebtState,
    *,
    request_id: str,
    actual_applied_code: int,
    actual_dac_epoch: int,
    first_consumer_frontier: int,
) -> DebtTransition:
    pending = state.pending
    if pending is None or pending.request_id != request_id:
        return fail_correction_debt_identity(state, "application_identity_mismatch")
    if pending.status is not ProposalStatus.ACCEPTED:
        return fail_correction_debt_identity(state, "application_before_acceptance")
    if actual_applied_code != pending.requested_code:
        return fail_correction_debt_identity(state, "applied_code_contradiction")
    if actual_dac_epoch != pending.provenance.dac_epoch + 1:
        return fail_correction_debt_identity(state, "dac_epoch_contradiction")
    if first_consumer_frontier <= pending.provenance.evidence_frontier:
        return fail_correction_debt_identity(state, "first_consumer_not_causally_later")

    actual_delta = actual_applied_code - pending.provenance.applied_code
    raw_residual_total = pending.limited_total_codes - actual_delta
    residual_total = _clamp_fraction(
        raw_residual_total,
        -pending.maximum_abs_committed_debt_codes,
        pending.maximum_abs_committed_debt_codes,
    )
    limit_reasons: Tuple[str, ...] = ()
    if residual_total != raw_residual_total:
        limit_reasons = ("committed_residual_debt_capped",)
    residual_fll, residual_pll = _allocate_limited_components(
        pending.limited_fll_codes,
        pending.limited_pll_codes,
        residual_total,
    )
    provenance = replace(
        pending.provenance,
        evidence_frontier=first_consumer_frontier,
        applied_code=actual_applied_code,
        dac_epoch=actual_dac_epoch,
    )
    committed = TaggedCorrectionDebt(
        residual_fll,
        residual_pll,
        provenance,
        "confirmed_application_residual",
    )
    updated = replace(
        state,
        committed=committed,
        pending=None,
        response_pending_request_id=request_id,
        mode_reason="application_committed_response_pending",
    )
    return DebtTransition(
        updated,
        DebtEvent.APPLICATION_COMMITTED,
        "application_committed_response_pending",
        limit_reasons=limit_reasons,
    )


def complete_debt_response(
    state: CorrectionDebtState, *, request_id: str, response_frontier: int
) -> DebtTransition:
    if state.response_pending_request_id != request_id:
        return fail_correction_debt_identity(state, "response_identity_mismatch")
    if response_frontier <= state.committed.provenance.evidence_frontier:
        return fail_correction_debt_identity(state, "response_not_causally_later")
    provenance = replace(
        state.committed.provenance, evidence_frontier=response_frontier
    )
    committed = replace(
        state.committed,
        provenance=provenance,
        update_reason="required_response_completed",
    )
    updated = replace(
        state,
        committed=committed,
        response_pending_request_id=None,
        mode_reason=(
            state.mode_reason
            if state.mode is DebtMode.HOLD
            else "required_response_completed"
        ),
    )
    return DebtTransition(
        updated, DebtEvent.RESPONSE_COMPLETED, "required_response_completed"
    )


def suppress_correction_debt(
    state: CorrectionDebtState, reason: str
) -> DebtTransition:
    """Record cadence/persistence/direction suppression without accruing debt."""

    if not reason:
        raise ValueError("suppression reason must be nonempty")
    return DebtTransition(state, DebtEvent.SUPPRESSED, reason)


def enter_correction_debt_hold(
    state: CorrectionDebtState, reason: str
) -> DebtTransition:
    """Freeze committed debt while preserving any exact outstanding transaction."""

    if not reason:
        raise ValueError("hold reason must be nonempty")
    if state.mode in (DebtMode.FROZEN, DebtMode.IDENTITY_FAULT):
        return DebtTransition(
            state,
            DebtEvent.SUPPRESSED,
            f"mode:{state.mode.value}:{state.mode_reason}",
        )
    held = replace(state, mode=DebtMode.HOLD, mode_reason=reason)
    return DebtTransition(held, DebtEvent.HOLD_ENTERED, reason)


def requalify_correction_debt(
    state: CorrectionDebtState,
    *,
    fresh_observation: DebtProvenance,
    target_mode: DebtMode = DebtMode.ACTIVE,
) -> DebtTransition:
    if state.mode is not DebtMode.HOLD:
        raise ValueError("only held debt may be requalified")
    if state.pending is not None or state.response_pending_request_id is not None:
        raise OutstandingDebtTransitionError(
            "outstanding transaction/response must resolve before requalification"
        )
    if target_mode not in (DebtMode.ACTIVE, DebtMode.FLL_FALLBACK):
        raise ValueError("requalification target must be active or FLL fallback")
    contradictions = _identity_contradictions(
        state.committed.provenance, fresh_observation
    )
    if contradictions:
        return fail_correction_debt_identity(state, ";".join(contradictions))
    if fresh_observation.evidence_frontier <= state.committed.provenance.evidence_frontier:
        return DebtTransition(state, DebtEvent.SUPPRESSED, "requalification_not_fresh")
    resumed = replace(
        state, mode=target_mode, mode_reason="fresh_post_requalification_observation"
    )
    return DebtTransition(
        resumed,
        DebtEvent.REQUALIFIED,
        "fresh_post_requalification_observation",
    )


def freeze_correction_debt(
    state: CorrectionDebtState, reason: str
) -> DebtTransition:
    if not reason:
        raise ValueError("freeze reason must be nonempty")
    if state.mode is DebtMode.IDENTITY_FAULT:
        return DebtTransition(
            state, DebtEvent.IDENTITY_FAULT, state.mode_reason
        )
    if state.pending is not None or state.response_pending_request_id is not None:
        raise OutstandingDebtTransitionError(
            "cannot freeze away an outstanding transaction or response"
        )
    frozen = replace(state, mode=DebtMode.FROZEN, mode_reason=reason)
    return DebtTransition(frozen, DebtEvent.FROZEN, reason)


def discard_pll_correction_debt(
    state: CorrectionDebtState, reason: str
) -> DebtTransition:
    """Remove phase-origin debt while retaining healthy FLL-origin debt."""

    if not reason:
        raise ValueError("PLL-debt discard reason must be nonempty")
    if state.pending is not None or state.response_pending_request_id is not None:
        raise OutstandingDebtTransitionError(
            "PLL debt may be discarded only after the exact transaction/response resolves"
        )
    provenance = replace(
        state.committed.provenance, phase_epoch=None, phase_frontier=None
    )
    committed = TaggedCorrectionDebt(
        state.committed.fll_codes,
        Fraction(0),
        provenance,
        reason,
    )
    mode = (
        state.mode
        if state.mode in (DebtMode.HOLD, DebtMode.FROZEN, DebtMode.IDENTITY_FAULT)
        else DebtMode.FLL_FALLBACK
    )
    updated = replace(state, committed=committed, mode=mode, mode_reason=reason)
    return DebtTransition(updated, DebtEvent.PLL_DEBT_DISCARDED, reason)


def reset_correction_debt(
    state: CorrectionDebtState,
    *,
    provenance: DebtProvenance,
    reason: str,
    mode: DebtMode = DebtMode.ACTIVE,
) -> DebtTransition:
    """Explicitly discard all debt at a declared session/DAC/phase reset."""

    if not reason:
        raise ValueError("debt reset reason must be nonempty")
    if state.pending is not None or state.response_pending_request_id is not None:
        raise OutstandingDebtTransitionError(
            "cannot reset away an outstanding transaction or response"
        )
    if mode not in (DebtMode.ACTIVE, DebtMode.HOLD, DebtMode.FLL_FALLBACK):
        raise ValueError("reset mode must be active, hold, or FLL fallback")
    committed = TaggedCorrectionDebt(Fraction(0), Fraction(0), provenance, reason)
    reset = CorrectionDebtState(committed=committed, mode=mode, mode_reason=reason)
    return DebtTransition(reset, DebtEvent.DEBT_RESET, reason)


# ---------------------------------------------------------------------------
# Transaction-aware metadata loss and local degradation containment


class RequestReleaseState(str, Enum):
    """Ownership frontier of a request when metadata qualification is lost."""

    UNUSED_ARM = "unused_arm"
    PRIVATE_UNRELEASED = "private_unreleased"
    RELEASED_PENDING = "released_pending"
    RELEASE_ACCEPTED = "release_accepted"
    RESPONSE_PENDING = "response_pending"
    OUTCOME_RESOLVED = "outcome_resolved"
    FAIL_STATIC = "fail_static"


@dataclass(frozen=True)
class MetadataLossDisposition:
    source_state: RequestReleaseState
    next_state: RequestReleaseState
    action: str
    outcome_owner: str
    enter_hold_now: bool
    hold_after_resolution: bool
    core1_may_mutate_request: bool
    preserve_d14_d8_response: bool
    fail_static: bool


def metadata_loss_disposition(
    state: RequestReleaseState,
    *,
    authoritative_outcome: str | None = None,
) -> MetadataLossDisposition:
    """Resolve metadata loss without transferring request ownership.

    This is a pure reference transition.  It deliberately distinguishes a
    private Core-1 request from one already released to Core 0, and never
    infers a transaction outcome from silence.
    """

    if state is RequestReleaseState.UNUSED_ARM:
        return MetadataLossDisposition(
            state,
            RequestReleaseState.OUTCOME_RESOLVED,
            "withdraw_unused_arm_then_enter_metadata_hold",
            "core1",
            True,
            False,
            True,
            False,
            False,
        )
    if state is RequestReleaseState.PRIVATE_UNRELEASED:
        return MetadataLossDisposition(
            state,
            RequestReleaseState.OUTCOME_RESOLVED,
            "private_unreleased_withdrawn_then_enter_metadata_hold",
            "core1",
            True,
            False,
            True,
            False,
            False,
        )
    if state is RequestReleaseState.RELEASED_PENDING:
        if authoritative_outcome is None:
            return MetadataLossDisposition(
                state,
                state,
                "preserve_released_request_await_core0_outcome",
                "core0",
                False,
                True,
                False,
                False,
                False,
            )
        if authoritative_outcome in ("rejected", "expired"):
            return MetadataLossDisposition(
                state,
                RequestReleaseState.OUTCOME_RESOLVED,
                f"record_exact_{authoritative_outcome}_then_enter_metadata_hold",
                "core0",
                True,
                False,
                False,
                False,
                False,
            )
        if authoritative_outcome == "accepted":
            return MetadataLossDisposition(
                state,
                RequestReleaseState.RELEASE_ACCEPTED,
                "complete_application_first_consumer_and_response_then_enter_metadata_hold",
                "core0",
                False,
                True,
                False,
                True,
                False,
            )
        return MetadataLossDisposition(
            state,
            RequestReleaseState.FAIL_STATIC,
            "unknown_or_contradictory_core0_outcome_fail_static",
            "core0",
            False,
            False,
            False,
            False,
            True,
        )
    if state is RequestReleaseState.RELEASE_ACCEPTED:
        return MetadataLossDisposition(
            state,
            state,
            "complete_application_first_consumer_and_response_then_enter_metadata_hold",
            "core0",
            False,
            True,
            False,
            True,
            False,
        )
    if state is RequestReleaseState.RESPONSE_PENDING:
        return MetadataLossDisposition(
            state,
            state,
            "preserve_d14_d8_response_inhibit_rearm_then_enter_metadata_hold",
            "core0",
            False,
            True,
            False,
            True,
            False,
        )
    if state is RequestReleaseState.OUTCOME_RESOLVED:
        return MetadataLossDisposition(
            state,
            state,
            "enter_or_remain_in_metadata_hold",
            "none",
            True,
            False,
            False,
            False,
            False,
        )
    return MetadataLossDisposition(
        state,
        RequestReleaseState.FAIL_STATIC,
        "remain_actuator_provenance_fail_static",
        "none",
        False,
        False,
        False,
        False,
        True,
    )


class EfficiencyMode(str, Enum):
    HYBRID = "hybrid"
    FLL_ONLY = "fll_only"
    STATIC_INHIBIT = "static_inhibit"


@dataclass(frozen=True)
class EfficiencyState:
    mode: EfficiencyMode = EfficiencyMode.HYBRID
    fll_local_low_efficiency_count: int = 0
    reason: str = "initialized"

    def __post_init__(self) -> None:
        if self.fll_local_low_efficiency_count < 0:
            raise ValueError("low-efficiency count must be nonnegative")


@dataclass(frozen=True)
class EfficiencyTransition:
    state: EfficiencyState
    phase_materially_influenced: bool
    action: str
    measurement_continues: bool = True


def record_low_efficiency(
    state: EfficiencyState,
    *,
    phase_materially_influenced: bool,
    repeated_fll_limit: int = 2,
) -> EfficiencyTransition:
    """Apply component-local fallback before a fail-static actuation inhibit."""

    if repeated_fll_limit <= 0:
        raise ValueError("repeated_fll_limit must be positive")
    if state.mode is EfficiencyMode.STATIC_INHIBIT:
        return EfficiencyTransition(
            state, phase_materially_influenced, "remain_static_inhibit"
        )
    if phase_materially_influenced and state.mode is EfficiencyMode.HYBRID:
        fallback = EfficiencyState(
            mode=EfficiencyMode.FLL_ONLY,
            fll_local_low_efficiency_count=0,
            reason="phase_material_low_efficiency_pll_disabled",
        )
        return EfficiencyTransition(
            fallback,
            phase_materially_influenced,
            "discard_pll_debt_and_fallback_to_fll",
        )

    count = state.fll_local_low_efficiency_count + 1
    if count >= repeated_fll_limit:
        inhibited = EfficiencyState(
            mode=EfficiencyMode.STATIC_INHIBIT,
            fll_local_low_efficiency_count=count,
            reason="repeated_fll_local_low_efficiency",
        )
        return EfficiencyTransition(
            inhibited,
            phase_materially_influenced,
            "inhibit_automatic_actuation_retain_last_confirmed_code",
        )
    updated = replace(
        state,
        fll_local_low_efficiency_count=count,
        reason="fll_local_low_efficiency_observed",
    )
    return EfficiencyTransition(
        updated, phase_materially_influenced, "retain_path_pending_repeat_threshold"
    )


@dataclass(frozen=True)
class CanonicalControlState:
    """Minimal state that an optional evidence component must not mutate."""

    canonical_state_digest: str
    d14_d8_measurement_healthy: bool
    control_authority_state: str

    def __post_init__(self) -> None:
        if not self.canonical_state_digest or not self.control_authority_state:
            raise ValueError("canonical identity and authority state must be nonempty")


@dataclass(frozen=True)
class OptionalFaultDisposition:
    canonical: CanonicalControlState
    component: str
    fault: str
    component_failed: bool
    backpressure_permitted: bool
    canonical_mutation_permitted: bool
    terminal_permitted: bool


def contain_optional_evidence_fault(
    canonical: CanonicalControlState,
    *,
    component: str,
    fault: str,
) -> OptionalFaultDisposition:
    """Contain a shadow, D10, or D6-local failure at zero control authority."""

    allowed = {
        "shadow": {
            "input_drop",
            "output_drop",
            "stale",
            "killed",
            "stalled",
            "delayed",
            "corrupt",
            "rejected",
            "model_infeasible",
        },
        "d10": {"absent", "noise", "invalid", "overflow", "queue_failure"},
        "d6": {"absent", "stalled", "corrupt", "overflow", "queue_failure"},
    }
    if component not in allowed:
        raise ValueError("component must be 'shadow', 'd10', or 'd6'")
    if fault not in allowed[component]:
        raise ValueError(f"unsupported {component} fault: {fault}")
    return OptionalFaultDisposition(
        canonical=canonical,
        component=component,
        fault=fault,
        component_failed=True,
        backpressure_permitted=False,
        canonical_mutation_permitted=False,
        terminal_permitted=False,
    )


# ---------------------------------------------------------------------------
# Same-sign, non-overlapping persistence


class PersistenceMode(str, Enum):
    ACTIVE = "active"
    HOLD = "hold"
    FROZEN = "frozen"
    AWAITING_POST_REQUALIFICATION_OBSERVATION = (
        "awaiting_post_requalification_observation"
    )


@dataclass(frozen=True)
class PersistenceIdentity:
    capture_session: str
    continuity_segment: str
    applied_code: int
    dac_epoch: int
    phase_state_id: str

    def __post_init__(self) -> None:
        if not self.capture_session or not self.continuity_segment or not self.phase_state_id:
            raise ValueError("persistence identity fields must be nonempty")
        if self.dac_epoch < 0:
            raise ValueError("DAC epoch must be nonnegative")


@dataclass(frozen=True)
class DemandIntervalObservation:
    identity: PersistenceIdentity
    opening_frontier: int
    closing_frontier: int
    combined_demand: RationalInterval
    qualified: bool = True
    settled: bool = True
    cadence_eligible: bool = True

    def __post_init__(self) -> None:
        if self.opening_frontier < 0 or self.closing_frontier <= self.opening_frontier:
            raise ValueError("demand interval must have increasing nonnegative frontiers")


@dataclass(frozen=True)
class PersistenceState:
    required_count: int
    sign: IntervalSign | None = None
    count: int = 0
    identity: PersistenceIdentity | None = None
    last_opening_frontier: int | None = None
    last_closing_frontier: int | None = None
    mode: PersistenceMode = PersistenceMode.ACTIVE
    requalification_frontier: int | None = None
    reason: str = "initialized"

    def __post_init__(self) -> None:
        if self.required_count <= 0:
            raise ValueError("required persistence count must be positive")
        if self.count < 0 or self.count > self.required_count:
            raise ValueError("persistence count is outside its bounded range")

    @property
    def satisfied(self) -> bool:
        return self.count >= self.required_count


@dataclass(frozen=True)
class PersistenceTransition:
    state: PersistenceState
    reason: str
    advanced: bool


def initial_persistence(required_count: int) -> PersistenceState:
    return PersistenceState(required_count=required_count)


def advance_persistence(
    state: PersistenceState, observation: DemandIntervalObservation
) -> PersistenceTransition:
    """Consume one fresh interval without double-counting overlapping support."""

    if state.mode is PersistenceMode.HOLD:
        return PersistenceTransition(
            state, f"persistence_hold:{state.reason}", False
        )
    if state.mode is PersistenceMode.FROZEN:
        return PersistenceTransition(state, f"persistence_frozen:{state.reason}", False)
    if observation.qualified is not True:
        return PersistenceTransition(state, "interval_unqualified", False)
    if observation.settled is not True:
        return PersistenceTransition(state, "settling_incomplete", False)
    if observation.cadence_eligible is not True:
        return PersistenceTransition(state, "cadence_ineligible", False)

    resuming = (
        state.mode is PersistenceMode.AWAITING_POST_REQUALIFICATION_OBSERVATION
    )
    if resuming:
        assert state.requalification_frontier is not None
        if observation.opening_frontier < state.requalification_frontier:
            return PersistenceTransition(
                state, "observation_not_wholly_post_requalification", False
            )

    identity_changed = state.identity is not None and observation.identity != state.identity
    if (
        state.last_closing_frontier is not None
        and not identity_changed
        and observation.opening_frontier < state.last_closing_frontier
    ):
        return PersistenceTransition(state, "overlapping_interval", False)

    sign = observation.combined_demand.sign
    gap = (
        state.last_closing_frontier is not None
        and observation.opening_frontier != state.last_closing_frontier
    )

    if sign is IntervalSign.CONTAINS_ZERO:
        updated = replace(
            state,
            sign=None,
            count=0,
            identity=observation.identity,
            last_opening_frontier=observation.opening_frontier,
            last_closing_frontier=observation.closing_frontier,
            mode=PersistenceMode.ACTIVE,
            requalification_frontier=None,
            reason="zero_containing_interval_reset",
        )
        return PersistenceTransition(updated, "zero_containing_interval_reset", False)

    same_sign = sign is state.sign
    if state.count == 0:
        count = 1
        reason = "persistence_started"
    elif identity_changed:
        count = 1
        reason = "identity_epoch_reset"
    elif not resuming and gap:
        count = 1
        reason = "noncontiguous_interval_reset"
    elif not same_sign:
        count = 1
        reason = "demand_sign_changed_reset"
    else:
        count = min(state.required_count, state.count + 1)
        reason = (
            "persistence_satisfied"
            if count == state.required_count and state.count < state.required_count
            else "same_sign_persistence_advanced"
        )

    updated = replace(
        state,
        sign=sign,
        count=count,
        identity=observation.identity,
        last_opening_frontier=observation.opening_frontier,
        last_closing_frontier=observation.closing_frontier,
        mode=PersistenceMode.ACTIVE,
        requalification_frontier=None,
        reason=reason,
    )
    return PersistenceTransition(updated, reason, True)


def hold_persistence(state: PersistenceState, reason: str) -> PersistenceTransition:
    if not reason:
        raise ValueError("persistence hold reason must be nonempty")
    if state.mode is PersistenceMode.FROZEN:
        return PersistenceTransition(
            state, f"persistence_frozen:{state.reason}", False
        )
    held = replace(state, mode=PersistenceMode.HOLD, reason=reason)
    return PersistenceTransition(held, reason, False)


def requalify_persistence(
    state: PersistenceState, *, requalification_frontier: int
) -> PersistenceTransition:
    if state.mode is not PersistenceMode.HOLD:
        raise ValueError("only held persistence may be requalified")
    if requalification_frontier < 0:
        raise ValueError("requalification frontier must be nonnegative")
    awaiting = replace(
        state,
        mode=PersistenceMode.AWAITING_POST_REQUALIFICATION_OBSERVATION,
        requalification_frontier=requalification_frontier,
        reason="awaiting_complete_post_requalification_observation",
    )
    return PersistenceTransition(
        awaiting, "awaiting_complete_post_requalification_observation", False
    )


def freeze_persistence(
    state: PersistenceState, reason: str
) -> PersistenceTransition:
    """Freeze history across an outstanding transaction or finite authority gate."""

    if not reason:
        raise ValueError("persistence freeze reason must be nonempty")
    frozen = replace(state, mode=PersistenceMode.FROZEN, reason=reason)
    return PersistenceTransition(frozen, reason, False)


def resume_frozen_persistence(
    state: PersistenceState, reason: str
) -> PersistenceTransition:
    """Resume a non-metadata freeze without treating it as requalification."""

    if state.mode is not PersistenceMode.FROZEN:
        raise ValueError("only frozen persistence may be resumed")
    if not reason:
        raise ValueError("persistence resume reason must be nonempty")
    active = replace(state, mode=PersistenceMode.ACTIVE, reason=reason)
    return PersistenceTransition(active, reason, False)


def reset_persistence(state: PersistenceState, reason: str) -> PersistenceTransition:
    reset = PersistenceState(required_count=state.required_count, reason=reason)
    return PersistenceTransition(reset, reason, False)
