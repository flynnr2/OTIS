"""Current adaptive FLL/PLL controller with tagged correction debt."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .adaptive_hybrid_contract import ADAPTIVE_HYBRID_PROGRAMME

REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_ID = "OTIS_ADAPTIVE_HYBRID_REGULATION_V1"
POLICY_PATH = REPO_ROOT / "profiles/discipline/adaptive_hybrid_regulation_v1.json"
PICO = 1_000_000_000_000
DEBT_LIMIT = 500_000_000_000
TICKS_PER_SECOND = 1_000_000
PICOCODE_NUMERATOR = 625_000_000_000_000_000_000
PICOCODE_DENOMINATOR = 4_680_182_727


class HybridPolicyError(RuntimeError):
    """The controller entered a state that cannot retain authority."""


@dataclass(frozen=True)
class AdaptiveHybridPolicy:
    policy_id: str
    policy_sha256: str
    frequency_estimator_id: str
    estimator_span_s: int
    controller_gain_codes_per_hz_per_decision: Fraction
    maximum_step_codes: int
    minimum_code: int
    maximum_code: int
    minimum_cadence_s: int
    settling_exclusion_s: int
    maximum_applications: int
    maximum_cumulative_movement_codes: int
    setup_code: int = ADAPTIVE_HYBRID_PROGRAMME.setup_code


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def policy_from_mapping(
    value: dict[str, Any], *, policy_sha256: str
) -> AdaptiveHybridPolicy:
    """Validate the selected policy and consume its inlined control constants."""
    if value.get("policy_id") != POLICY_ID:
        raise ValueError("adaptive-hybrid policy identity differs")
    selection = value.get("maintenance_selection", {})
    arithmetic = value.get("maintenance_arithmetic", {})
    limits = value.get("global_authority_limits", {})
    debt = value.get("correction_debt", {})
    frequency_control = value.get("frequency_control", {})
    parameters = (
        frequency_control.get("parameters", {})
        if isinstance(frequency_control, dict)
        else {}
    )
    authority = (
        frequency_control.get("authority", {})
        if isinstance(frequency_control, dict)
        else {}
    )
    expected_parameters = {
        "nominal_frequency_hz": 10_000_000,
        "gain_min_hz_per_code": 0.00016357422282453626,
        "gain_nominal_hz_per_code": 0.00017008467693813145,
        "gain_max_hz_per_code": 0.00017334010044578463,
        "estimator_span_s": 600,
        "minimum_applied_cadence_s": 1800,
        "settling_exclusion_s": 900,
        "fresh_support_after_settling_s": 600,
        "startup_warmup_s": 1800,
        "error_deadband_hz": 0.006249995628992717,
        "integrator_gain_codes_per_hz_per_decision": 2884.5027706464516,
        "maximum_update_codes": 21,
        "dac_min_code": 43008,
        "dac_max_code": 43776,
    }
    if (
        frequency_control.get("policy_id") != "OTIS_FREQUENCY_CONTROL_POLICY_V1"
        or frequency_control.get("status") != "selected_production_component"
        or frequency_control.get("frequency_estimator_id")
        != "OTIS_PPS_GATED_FREQUENCY_ESTIMATOR_V1"
        or parameters != expected_parameters
        or authority
        != {
            "arming_required": True,
            "one_request_outstanding": True,
            "automatic_retry": False,
            "automatic_restore": False,
            "gnss_qualification_required": True,
            "D14_reference_required": True,
            "D8_count_required": True,
            "D10_external_event_excluded": True,
        }
        or selection.get("requires_tight_state") != "TIGHT_INSIDE"
        or selection.get("required_consecutive_same_sign_windows") != 2
        or selection.get("frontier_support") != "(opening_closing]"
        or arithmetic.get("authoritative_fixed_point_unit")
        != "signed_integer_picocode_1e_minus_12_code"
        or arithmetic.get("picocode_reduced_numerator") != PICOCODE_NUMERATOR
        or arithmetic.get("picocode_reduced_denominator") != PICOCODE_DENOMINATOR
        or arithmetic.get("maximum_absolute_combined_centre_units")
        != 332_041_393_326_771_929_124
        or debt.get("maximum_absolute_total_picocodes") != DEBT_LIMIT
        or limits.get("maximum_outstanding_requests") != 1
        or limits.get("maximum_combined_step_codes")
        != parameters.get("maximum_update_codes")
        or limits.get("minimum_applied_cadence_s")
        != parameters.get("minimum_applied_cadence_s")
        or limits.get("minimum_code") != parameters.get("dac_min_code")
        or limits.get("maximum_code") != parameters.get("dac_max_code")
        or selection.get("window_s") != parameters.get("estimator_span_s")
        or selection.get("selected_frequency_estimator")
        != frequency_control.get("frequency_estimator_id")
    ):
        raise ValueError("adaptive-hybrid maintenance semantics differ")
    return AdaptiveHybridPolicy(
        policy_id=POLICY_ID,
        policy_sha256=policy_sha256,
        frequency_estimator_id=str(selection["selected_frequency_estimator"]),
        estimator_span_s=int(parameters["estimator_span_s"]),
        controller_gain_codes_per_hz_per_decision=Fraction(
            str(parameters["integrator_gain_codes_per_hz_per_decision"])
        ),
        maximum_step_codes=int(parameters["maximum_update_codes"]),
        minimum_code=int(parameters["dac_min_code"]),
        maximum_code=int(parameters["dac_max_code"]),
        minimum_cadence_s=int(parameters["minimum_applied_cadence_s"]),
        settling_exclusion_s=int(parameters["settling_exclusion_s"]),
        maximum_applications=int(limits["maximum_automatic_applications"]),
        maximum_cumulative_movement_codes=int(
            limits["maximum_cumulative_absolute_movement_codes"]
        ),
        setup_code=ADAPTIVE_HYBRID_PROGRAMME.setup_code,
    )


def load_policy(path: Path = POLICY_PATH) -> AdaptiveHybridPolicy:
    """Load the sole selected policy and verify its numerical semantics."""

    return policy_from_mapping(_read_object(path), policy_sha256=_sha256_file(path))

@dataclass(frozen=True)
class AdaptiveHybridDebt:
    fll_picocodes: int = 0
    pll_picocodes: int = 0

    @property
    def total_picocodes(self) -> int:
        return self.fll_picocodes + self.pll_picocodes


@dataclass(frozen=True)
class AdaptiveHybridObservation:
    timestamp_s: int
    timestamp_ticks: int
    capture_session: int
    source_acceptance_epoch: int
    source_opening_accepted_boundary_ordinal: int
    source_closing_accepted_boundary_ordinal: int
    dac_epoch: int
    applied_code: int
    accumulated_edge_error_counts: int
    tight_state: str
    phase_epoch: int
    relative_phase_cycles: int
    frequency_estimator_id: str = "OTIS_PPS_GATED_FREQUENCY_ESTIMATOR_V1"
    phase_valid: bool = True
    authority_valid: bool = True
    settled: bool = True
    cadence_eligible: bool = True
    metadata_qualified: bool = True


@dataclass(frozen=True)
class AdaptiveHybridDecision:
    decision_sequence: int
    reason: str
    requested_delta_codes: int
    requested_code: int
    safe_cap_codes: int
    persistence_count: int
    raw_combined_picocodes: int
    raw_fll_picocodes: int
    raw_pll_picocodes: int
    committed_debt_picocodes: int
    maintenance_request: bool = False
    decision_timestamp_ticks: int = 0
    counterfactual_frequency_only_delta_codes: int = 0
    phase_materially_influenced: bool = False
    step_limited: bool = False
    range_clamped: bool = False
    cadence_limited: bool = False
    count_limited: bool = False
    cumulative_budget_limited: bool = False


def _adaptive_hybrid_round_ratio(numerator: int, denominator: int) -> int:
    magnitude = abs(numerator)
    result = (2 * magnitude + denominator) // (2 * denominator)
    return result if numerator >= 0 else -result


def adaptive_hybrid_centre_to_picocodes(centre_units: int) -> int:
    """Checked reduced quotient/remainder fixed-point conversion."""

    magnitude = abs(centre_units)
    quotient, remainder = divmod(magnitude, PICOCODE_DENOMINATOR)
    result = quotient * PICOCODE_NUMERATOR + _adaptive_hybrid_round_ratio(
        remainder * PICOCODE_NUMERATOR, PICOCODE_DENOMINATOR
    )
    return result if centre_units >= 0 else -result


class AdaptiveHybridPhasePriorityController:
    """Selected tagged-debt maintenance controller, without I/O authority."""

    def __init__(
        self,
        policy: AdaptiveHybridPolicy,
        *,
        setup_applied_code: int | None = None,
        setup_dac_epoch: int = 1,
    ) -> None:
        self.policy = policy
        self.applied_code = 0
        self.dac_epoch = 0
        self.application_count = 0
        self.cumulative_movement_codes = 0
        self.last_application_s: int | None = None
        self.last_application_ticks: int | None = None
        self.chatter_origin_code = 0
        self.direction_history: list[int] = []
        self.debt = AdaptiveHybridDebt()
        self.persistence_sign = 0
        self.persistence_count = 0
        self.persistence_identity: tuple[int, int, int, int, int, bool, str] | None = None
        self.last_closing_accepted_boundary_ordinal: int | None = None
        self.request_pending = False
        self._pending_decision: AdaptiveHybridDecision | None = None
        self._pending_decision_timestamp_s: int | None = None
        self._pending_decision_timestamp_ticks: int | None = None
        self.response_pending = False
        self.metadata_hold = False
        self.metadata_requalified = False
        self.requalification_acceptance_epoch: int | None = None
        self.requalification_accepted_boundary_ordinal: int | None = None
        self.requalification_window_count = 0
        self._requalification_last_closing_accepted_boundary_ordinal: int | None = None
        self._requalification_identity: tuple[int, int, int, int, int, bool, str] | None = None
        self.fail_static_reason: str | None = None
        self.decision_sequence = 0
        self._current_timestamp_ticks = 0
        self.establish_setup(
            applied_code=(
                policy.setup_code if setup_applied_code is None else setup_applied_code
            ),
            dac_epoch=setup_dac_epoch,
        )

    def establish_setup(self, *, applied_code: int, dac_epoch: int) -> None:
        """Bind the controller to an explicitly observed setup code and epoch."""

        if self.request_pending or self.response_pending or self.last_application_s is not None:
            raise HybridPolicyError("setup_establishment_after_control_started")
        if not self.policy.minimum_code <= applied_code <= self.policy.maximum_code:
            raise ValueError("AdaptiveHybrid setup code outside frozen authority range")
        if dac_epoch <= 0:
            raise ValueError("AdaptiveHybrid setup DAC epoch must be positive")
        self.applied_code = applied_code
        self.dac_epoch = dac_epoch
        self.chatter_origin_code = applied_code

    def _reset(self, *, preserve_debt: bool) -> None:
        if not preserve_debt:
            self.debt = AdaptiveHybridDebt()
        self.persistence_sign = 0
        self.persistence_count = 0
        self.persistence_identity = None
        self.last_closing_accepted_boundary_ordinal = None

    def _fail_static(self, reason: str) -> None:
        self.fail_static_reason = reason
        self.request_pending = False
        self._pending_decision = None
        self._pending_decision_timestamp_s = None
        self._pending_decision_timestamp_ticks = None
        self.response_pending = False

    @staticmethod
    def _centre(observation: AdaptiveHybridObservation) -> tuple[int, int, int]:
        phase = max(-36, min(36, -observation.relative_phase_cycles))
        centre = -36 * observation.accumulated_edge_error_counts + phase
        return centre, centre - 18, centre + 18

    @staticmethod
    def _sign(lower: int, upper: int) -> int:
        return 1 if lower > 0 else -1 if upper < 0 else 0

    def _cap(self, centre: int, code: int) -> int:
        lower, upper = centre - 18, centre + 18
        sign = self._sign(lower, upper)
        if not sign:
            return 0
        nearest = lower if sign > 0 else -upper
        cap = min(
            self.policy.maximum_step_codes,
            nearest * 1_000_000_000_000 // (21_600 * 173_340_101),
            max(
                0,
                self.policy.maximum_cumulative_movement_codes
                - self.cumulative_movement_codes,
            ),
        )
        return max(
            0,
            min(
                cap,
                self.policy.maximum_code - code
                if sign > 0
                else code - self.policy.minimum_code,
            ),
        )

    def _bounded_fll_pll_deltas(
        self, observation: AdaptiveHybridObservation, *, phase_enabled: bool = True
    ) -> tuple[int, int, bool, bool]:
        phase = (
            max(-36, min(36, -observation.relative_phase_cycles))
            if phase_enabled
            else 0
        )
        gain = self.policy.controller_gain_codes_per_hz_per_decision
        frequency = gain * Fraction(
            -observation.accumulated_edge_error_counts,
            self.policy.estimator_span_s,
        )
        combined = frequency + gain * Fraction(phase, 21_600)

        def limited(value: Fraction) -> tuple[int, bool, bool]:
            rounded = _adaptive_hybrid_round_ratio(value.numerator, value.denominator)
            step = max(
                -self.policy.maximum_step_codes,
                min(self.policy.maximum_step_codes, rounded),
            )
            requested = min(
                self.policy.maximum_code,
                max(self.policy.minimum_code, self.applied_code + step),
            )
            return (
                requested - self.applied_code,
                step != rounded,
                requested != self.applied_code + step,
            )

        combined_delta, step_limited, range_clamped = limited(combined)
        frequency_delta, _, _ = limited(frequency)
        return combined_delta, frequency_delta, step_limited, range_clamped

    @staticmethod
    def _timestamp_ticks(observation: AdaptiveHybridObservation) -> int:
        return observation.timestamp_ticks

    def _cadence_status(
        self, observation: AdaptiveHybridObservation
    ) -> tuple[bool, bool]:
        if not observation.cadence_eligible:
            return True, False
        if self.last_application_ticks is None:
            return False, False
        timestamp_ticks = self._timestamp_ticks(observation)
        if timestamp_ticks < self.last_application_ticks:
            return True, True
        return (
            timestamp_ticks - self.last_application_ticks
            < self.policy.minimum_cadence_s * TICKS_PER_SECOND,
            False,
        )

    def _chatter_reason(self, delta: int) -> str | None:
        direction = 1 if delta > 0 else -1
        prospective = [*self.direction_history[-3:], direction]
        reversals = sum(a != b for a, b in zip(prospective, prospective[1:]))
        if len(prospective) == 4 and reversals == 3:
            return "prospective_repeated_alternation"
        path = self.cumulative_movement_codes + abs(delta)
        net = abs(self.applied_code + delta - self.chatter_origin_code)
        if path >= 42 and 4 * net <= path:
            return "prospective_low_efficiency_path"
        return None

    def _decision(
        self,
        reason: str,
        delta: int = 0,
        cap: int = 0,
        raw: int = 0,
        fll: int = 0,
        pll: int = 0,
        *,
        maintenance_request: bool = False,
        counterfactual_frequency_only_delta_codes: int = 0,
        phase_materially_influenced: bool = False,
        step_limited: bool = False,
        range_clamped: bool = False,
        cadence_limited: bool = False,
        count_limited: bool = False,
        cumulative_budget_limited: bool = False,
    ) -> AdaptiveHybridDecision:
        return AdaptiveHybridDecision(
            decision_sequence=self.decision_sequence,
            reason=reason,
            requested_delta_codes=delta,
            requested_code=self.applied_code + delta,
            safe_cap_codes=cap,
            persistence_count=self.persistence_count,
            raw_combined_picocodes=raw,
            raw_fll_picocodes=fll,
            raw_pll_picocodes=pll,
            committed_debt_picocodes=self.debt.total_picocodes,
            maintenance_request=maintenance_request,
            decision_timestamp_ticks=self._current_timestamp_ticks,
            counterfactual_frequency_only_delta_codes=(
                counterfactual_frequency_only_delta_codes
            ),
            phase_materially_influenced=phase_materially_influenced,
            step_limited=step_limited,
            range_clamped=range_clamped,
            cadence_limited=cadence_limited,
            count_limited=count_limited,
            cumulative_budget_limited=cumulative_budget_limited,
        )

    def _request_or_hold(
        self,
        observation: AdaptiveHybridObservation,
        *,
        delta: int,
        reason: str,
        cap: int,
        raw: int = 0,
        fll: int = 0,
        pll: int = 0,
        phase_term: int = 0,
        enforce_phase_direction: bool = False,
        maintenance_request: bool = False,
        counterfactual_frequency_only_delta_codes: int = 0,
        phase_materially_influenced: bool = False,
        step_limited: bool = False,
        range_clamped: bool = False,
    ) -> AdaptiveHybridDecision:
        projection = {
            "counterfactual_frequency_only_delta_codes": (
                counterfactual_frequency_only_delta_codes
            ),
            "phase_materially_influenced": phase_materially_influenced,
            "step_limited": step_limited,
            "range_clamped": range_clamped,
        }
        cadence_held, timestamp_backward = self._cadence_status(observation)
        if cadence_held:
            if timestamp_backward:
                self._fail_static("observation_timestamp_backward")
                return self._decision(self.fail_static_reason)
            return self._decision(
                "cadence_hold",
                cap=cap,
                raw=raw,
                fll=fll,
                pll=pll,
                cadence_limited=True,
                **projection,
            )
        if delta and enforce_phase_direction and phase_term and delta * phase_term < 0:
            return self._decision(
                "phase_direction_coherence_hold",
                cap=cap,
                raw=raw,
                fll=fll,
                pll=pll,
                **projection,
            )
        if delta == 0:
            return self._decision(
                "zero_rounded_or_range_hold",
                cap=cap,
                raw=raw,
                fll=fll,
                pll=pll,
                **projection,
            )
        if self.application_count >= self.policy.maximum_applications:
            return self._decision(
                "global_application_budget_hold",
                cap=cap,
                raw=raw,
                fll=fll,
                pll=pll,
                count_limited=True,
                **projection,
            )
        if (
            self.cumulative_movement_codes + abs(delta)
            > self.policy.maximum_cumulative_movement_codes
        ):
            return self._decision(
                "global_cumulative_movement_budget_hold",
                cap=cap,
                raw=raw,
                fll=fll,
                pll=pll,
                cumulative_budget_limited=True,
                **projection,
            )
        chatter = self._chatter_reason(delta)
        if chatter is not None:
            self._fail_static(chatter)
            return self._decision(
                chatter, cap=cap, raw=raw, fll=fll, pll=pll, **projection
            )
        decision = self._decision(
            reason,
            delta,
            cap,
            raw,
            fll,
            pll,
            maintenance_request=maintenance_request,
            **projection,
        )
        self.request_pending = True
        self._pending_decision = decision
        self._pending_decision_timestamp_s = observation.timestamp_s
        self._pending_decision_timestamp_ticks = self._timestamp_ticks(observation)
        return decision

    def _bounded_control_request(
        self,
        observation: AdaptiveHybridObservation,
        *,
        delta: int,
        reason: str,
        phase_term: int = 0,
        reset_debt: bool = True,
        enforce_phase_direction: bool = True,
        counterfactual_frequency_only_delta_codes: int = 0,
        phase_materially_influenced: bool = False,
        step_limited: bool = False,
        range_clamped: bool = False,
    ) -> AdaptiveHybridDecision:
        # A bounded direct-control request is a maintenance boundary, never an
        # implicit continuation of a tagged-debt persistence interval.
        self._reset(preserve_debt=not reset_debt)
        return self._request_or_hold(
            observation,
            delta=delta,
            reason=reason,
            cap=self.policy.maximum_step_codes,
            pll=phase_term,
            phase_term=phase_term,
            enforce_phase_direction=enforce_phase_direction,
            counterfactual_frequency_only_delta_codes=(
                counterfactual_frequency_only_delta_codes
            ),
            phase_materially_influenced=phase_materially_influenced,
            step_limited=step_limited,
            range_clamped=range_clamped,
        )

    def enter_metadata_hold(self) -> None:
        self.metadata_hold = True
        self.metadata_requalified = False
        self.requalification_acceptance_epoch = None
        self.requalification_accepted_boundary_ordinal = None
        self.requalification_window_count = 0
        self._requalification_last_closing_accepted_boundary_ordinal = None
        self._requalification_identity = None
        self._reset(preserve_debt=True)

    def new_policy_activation(self) -> None:
        """Explicit activation boundary; it never inherits maintenance debt."""

        if self.request_pending or self.response_pending:
            self._fail_static("new_policy_activation_with_outstanding_transaction")
            raise HybridPolicyError(self.fail_static_reason)
        self._reset(preserve_debt=False)

    def requalify_metadata(
        self, *, acceptance_epoch: int, accepted_boundary_ordinal: int
    ) -> None:
        if not self.metadata_hold:
            raise HybridPolicyError("metadata requalification without hold")
        if acceptance_epoch <= 0:
            raise ValueError("metadata requalification acceptance epoch must be positive")
        if not 0 <= accepted_boundary_ordinal <= 0xFFFFFFFF:
            raise ValueError("metadata requalification accepted ordinal must be uint32")
        # Fresh serial metadata is necessary but not sufficient to restore
        # actuation.  D14/D8 must provide two complete causally later windows
        # while the last confirmed code and debt remain frozen.
        self.metadata_requalified = True
        self.requalification_acceptance_epoch = acceptance_epoch
        self.requalification_accepted_boundary_ordinal = accepted_boundary_ordinal
        self.requalification_window_count = 0
        self._requalification_last_closing_accepted_boundary_ordinal = None
        self._requalification_identity = None
        self._reset(preserve_debt=True)

    def _advance_metadata_requalification(
        self,
        observation: AdaptiveHybridObservation,
        identity: tuple[int, int, int, int, int, bool, str],
    ) -> str | None:
        """Advance the independent two-window D14/D8 requalification gate."""

        if not self.metadata_hold or not self.metadata_requalified:
            return None
        if self.requalification_accepted_boundary_ordinal is None:
            self._fail_static(
                "metadata_requalification_accepted_boundary_ordinal_missing"
            )
            return self.fail_static_reason
        if observation.source_acceptance_epoch != self.requalification_acceptance_epoch:
            return "metadata_requalification_acceptance_epoch_hold"
        opening_after_frontier = (
            observation.source_opening_accepted_boundary_ordinal
            - self.requalification_accepted_boundary_ordinal
        ) & 0xFFFFFFFF
        if opening_after_frontier > 0x7FFFFFFF:
            return "metadata_requalification_accepted_boundary_ordinal_hold"
        previous = self._requalification_last_closing_accepted_boundary_ordinal
        if previous is not None:
            advance = (
                observation.source_opening_accepted_boundary_ordinal - previous
            ) & 0xFFFFFFFF
            if advance > 0x7FFFFFFF:
                return "metadata_requalification_overlap_hold"
        contiguous = (
            previous is not None
            and observation.source_opening_accepted_boundary_ordinal == previous
            and self._requalification_identity == identity
        )
        self.requalification_window_count = (
            min(2, self.requalification_window_count + 1) if contiguous else 1
        )
        self._requalification_last_closing_accepted_boundary_ordinal = observation.source_closing_accepted_boundary_ordinal
        self._requalification_identity = identity
        if self.requalification_window_count < 2:
            return "metadata_requalification_window_hold"
        self.metadata_hold = False
        self.metadata_requalified = False
        self.requalification_acceptance_epoch = None
        self.requalification_accepted_boundary_ordinal = None
        self._requalification_last_closing_accepted_boundary_ordinal = None
        self._requalification_identity = None
        return None

    def reject_or_expire_request(self) -> None:
        if not self.request_pending or self.response_pending:
            self._fail_static("invalid_request_rejection_transition")
            raise HybridPolicyError(self.fail_static_reason)
        self.request_pending = False
        self._pending_decision = None
        self._pending_decision_timestamp_s = None
        self._pending_decision_timestamp_ticks = None

    def decide(self, observation: AdaptiveHybridObservation) -> AdaptiveHybridDecision:
        self.decision_sequence += 1
        self._current_timestamp_ticks = self._timestamp_ticks(observation)
        if self.fail_static_reason:
            return self._decision(self.fail_static_reason)
        if (
            observation.timestamp_s
            != self._current_timestamp_ticks // TICKS_PER_SECOND
        ):
            self._fail_static("observation_timestamp_domain_mismatch")
            return self._decision(self.fail_static_reason)
        source_distance = (
            observation.source_closing_accepted_boundary_ordinal
            - observation.source_opening_accepted_boundary_ordinal
        ) & 0xFFFFFFFF
        if source_distance == 0 or source_distance > 0x7FFFFFFF:
            self._fail_static("invalid_selected_window_frontier")
            return self._decision(self.fail_static_reason)
        if self.request_pending:
            return self._decision("request_pending_hold")
        if self.response_pending:
            return self._decision("response_pending_hold")
        if not observation.metadata_qualified:
            if not observation.metadata_qualified:
                if not self.metadata_hold or self.metadata_requalified:
                    self.enter_metadata_hold()
            return self._decision("metadata_hold")
        if self.metadata_hold and not self.metadata_requalified:
            return self._decision("metadata_hold")
        if (observation.applied_code != self.applied_code
                or observation.dac_epoch != self.dac_epoch):
            self._fail_static("unknown_or_contradictory_application_or_DAC_epoch")
            return self._decision(self.fail_static_reason)
        identity = (observation.capture_session, observation.source_acceptance_epoch,
                    observation.applied_code,
                    observation.dac_epoch, observation.phase_epoch,
                    observation.phase_valid, observation.frequency_estimator_id)
        if self.persistence_identity is not None and identity != self.persistence_identity:
            old = self.persistence_identity
            if (
                observation.capture_session != old[0]
                or observation.source_acceptance_epoch != old[1]
                or observation.frequency_estimator_id != old[6]
            ):
                self._reset(preserve_debt=False)
            elif observation.applied_code != old[2] or observation.dac_epoch != old[3]:
                self._fail_static("unknown_or_contradictory_application_or_DAC_epoch")
                return self._decision(self.fail_static_reason)
            elif observation.phase_epoch != old[4] or observation.phase_valid != old[5]:
                self.debt = AdaptiveHybridDebt(self.debt.fll_picocodes, 0)
                self._reset(preserve_debt=True)
        if not observation.authority_valid:
            self._reset(preserve_debt=True)
            return self._decision("reference_invalidity_or_authority_hold")
        if not observation.settled:
            self._reset(preserve_debt=True)
            return self._decision("settling_hold")
        metadata_requalification_hold = self._advance_metadata_requalification(
            observation, identity
        )
        if self.fail_static_reason:
            return self._decision(self.fail_static_reason)
        if metadata_requalification_hold in {
            "metadata_requalification_acceptance_epoch_hold",
            "metadata_requalification_accepted_boundary_ordinal_hold",
            "metadata_requalification_overlap_hold",
        }:
            return self._decision(metadata_requalification_hold)
        if not observation.phase_valid:
            self.debt = AdaptiveHybridDebt(self.debt.fll_picocodes, 0)
            self._reset(preserve_debt=True)
            combined_delta, frequency_delta, step_limited, range_clamped = (
                self._bounded_fll_pll_deltas(
                observation, phase_enabled=False
                )
            )
            projection = {
                "counterfactual_frequency_only_delta_codes": frequency_delta,
                "phase_materially_influenced": False,
                "step_limited": step_limited,
                "range_clamped": range_clamped,
            }
            if metadata_requalification_hold:
                return self._decision(metadata_requalification_hold, **projection)
            return self._bounded_control_request(
                observation,
                delta=combined_delta,
                reason="phase_degraded_frequency_only_request_ready",
                reset_debt=False,
                enforce_phase_direction=False,
                **projection,
            )

        # Outside-tight and phase-material paths are complete FLL/PLL control
        # paths. They deliberately precede tagged-debt maintenance.
        (
            combined_delta,
            frequency_delta,
            step_limited,
            range_clamped,
        ) = self._bounded_fll_pll_deltas(observation)
        phase_material = combined_delta != frequency_delta
        projection = {
            "counterfactual_frequency_only_delta_codes": frequency_delta,
            "phase_materially_influenced": phase_material,
            "step_limited": step_limited,
            "range_clamped": range_clamped,
        }
        phase_term = max(-36, min(36, -observation.relative_phase_cycles))
        if observation.tight_state != "TIGHT_INSIDE":
            if metadata_requalification_hold:
                self._reset(preserve_debt=False)
                return self._decision(metadata_requalification_hold, **projection)
            return self._bounded_control_request(
                observation,
                delta=combined_delta,
                reason="outside_tight_ordinary_request_ready",
                phase_term=phase_term,
                **projection,
            )
        if phase_material:
            if metadata_requalification_hold:
                self._reset(preserve_debt=False)
                return self._decision(metadata_requalification_hold, **projection)
            return self._bounded_control_request(
                observation,
                delta=combined_delta,
                reason="phase_material_ordinary_request_ready",
                phase_term=phase_term,
                **projection,
            )
        if self.last_closing_accepted_boundary_ordinal is not None:
            source_advance = (
                observation.source_opening_accepted_boundary_ordinal
                - self.last_closing_accepted_boundary_ordinal
            ) & 0xFFFFFFFF
            if source_advance > 0x7FFFFFFF:
                return self._decision("source_overlap_hold", **projection)
            if source_advance > 0:
                centre, lower, upper = self._centre(observation)
                sign = self._sign(lower, upper)
                if not sign or (self.persistence_count and sign != self.persistence_sign):
                    self._reset(preserve_debt=False)
                self.persistence_count = 1
                self.persistence_sign = sign
                self.persistence_identity = identity
                self.last_closing_accepted_boundary_ordinal = observation.source_closing_accepted_boundary_ordinal
                return self._decision(
                    "source_gap_persistence_restart", **projection
                )
        centre, lower, upper = self._centre(observation)
        sign = self._sign(lower, upper)
        if not sign:
            self._reset(preserve_debt=False)
            return self._decision("zero_containing_interval", **projection)
        if self.persistence_count and self.persistence_sign != sign:
            self._reset(preserve_debt=False)
        same = self.persistence_count and self.persistence_identity == identity and self.persistence_sign == sign
        self.persistence_count = min(2, self.persistence_count + 1) if same else 1
        self.persistence_sign = sign
        self.persistence_identity = identity
        self.last_closing_accepted_boundary_ordinal = observation.source_closing_accepted_boundary_ordinal
        cap = self._cap(centre, observation.applied_code)
        if metadata_requalification_hold:
            return self._decision(
                metadata_requalification_hold, cap=cap, **projection
            )
        cadence_held, timestamp_backward = self._cadence_status(observation)
        if cadence_held:
            if timestamp_backward:
                self._fail_static("observation_timestamp_backward")
                return self._decision(self.fail_static_reason)
            return self._decision(
                "cadence_hold", cap=cap, cadence_limited=True, **projection
            )
        if self.persistence_count < 2:
            return self._decision(
                "persistence_first_interval_hold", cap=cap, **projection
            )
        raw = adaptive_hybrid_centre_to_picocodes(centre)
        fll = adaptive_hybrid_centre_to_picocodes(-36 * observation.accumulated_edge_error_counts)
        pll = raw - fll
        total = raw + self.debt.total_picocodes
        rounded = _adaptive_hybrid_round_ratio(total, PICO)
        delta = max(-cap, min(cap, rounded))
        return self._request_or_hold(
            observation,
            delta=delta,
            reason="maintenance_request_ready",
            cap=cap,
            raw=raw,
            fll=fll,
            pll=pll,
            phase_term=pll,
            enforce_phase_direction=True,
            maintenance_request=True,
            **projection,
        )

    def confirm_application(self, decision: AdaptiveHybridDecision, *, applied_code: int,
                            dac_epoch: int, first_consumer_exact: bool) -> None:
        if (
            not self.request_pending
            or self._pending_decision != decision
            or self._pending_decision_timestamp_s is None
            or self._pending_decision_timestamp_ticks is None
            or decision.requested_delta_codes == 0
        ):
            self._fail_static("invalid_or_unexpected_application")
            raise HybridPolicyError(self.fail_static_reason)
        if (not first_consumer_exact or applied_code != decision.requested_code
                or dac_epoch != self.dac_epoch + 1):
            self._fail_static("application_without_exact_first_consumer")
            raise HybridPolicyError(self.fail_static_reason)
        if decision.maintenance_request:
            total = decision.raw_combined_picocodes + self.debt.total_picocodes
            residual = max(-DEBT_LIMIT, min(DEBT_LIMIT,
                total - decision.requested_delta_codes * PICO))
            fll_weight = abs(decision.raw_fll_picocodes + self.debt.fll_picocodes)
            pll_weight = abs(decision.raw_pll_picocodes + self.debt.pll_picocodes)
            if fll_weight + pll_weight:
                fll_debt = _adaptive_hybrid_round_ratio(residual * fll_weight, fll_weight + pll_weight)
                self.debt = AdaptiveHybridDebt(fll_debt, residual - fll_debt)
            else:
                self.debt = AdaptiveHybridDebt(residual, 0)
        else:
            # A bounded direct-control request begins a new maintenance epoch.
            # It must not manufacture a tagged residual from maintenance-only arithmetic.
            residual = 0
            self.debt = AdaptiveHybridDebt()
        if self.debt.total_picocodes != residual:
            self._fail_static("debt_tag_sum_invariant_failure")
            raise HybridPolicyError(self.fail_static_reason)
        self.applied_code = applied_code
        self.dac_epoch = dac_epoch
        self.application_count += 1
        self.cumulative_movement_codes += abs(decision.requested_delta_codes)
        # Bind cadence to the decision that originated the application.  A
        # later observation while the request is pending is evidence only; it
        # must not move the actuator's causal application frontier.
        self.last_application_s = self._pending_decision_timestamp_s
        self.last_application_ticks = self._pending_decision_timestamp_ticks
        self.direction_history.append(1 if decision.requested_delta_codes > 0 else -1)
        self.request_pending = False
        self._pending_decision = None
        self._pending_decision_timestamp_s = None
        self._pending_decision_timestamp_ticks = None
        self.response_pending = True
        self._reset(preserve_debt=True)

    def complete_response(self, *, fresh_exact: bool) -> None:
        if not self.response_pending or not fresh_exact:
            return
        self.response_pending = False


def decision_dict(decision: AdaptiveHybridDecision) -> dict[str, Any]:
    return asdict(decision)
