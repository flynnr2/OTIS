"""Deterministic bounded active-hybrid controller reference.

The controller has one combined output and no transport or actuator surface.
Frequency acquisition and phase steering share the same integer request,
cadence, range, count, and cumulative-movement limits.  Live authority remains
the responsibility of the transaction layer and an exact programme bundle.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY = (
    REPO_ROOT / "profiles/discipline/cx320_bounded_active_hybrid_tight_v1.json"
)
POLICY_ID = "CX320_BOUNDED_ACTIVE_HYBRID_TIGHT_V1"
TOOL_ID = "cx320_active_hybrid_policy_reference_v1"


class HybridPolicyError(RuntimeError):
    """A fail-closed policy, identity, or transition violation."""


class HybridState(str, Enum):
    FREQUENCY_ACQUIRE = "FREQUENCY_ACQUIRE"
    PHASE_QUALIFY = "PHASE_QUALIFY"
    FIRST_PHASE_TRANSACTION = "FIRST_PHASE_TRANSACTION"
    HYBRID_TRACKING = "HYBRID_TRACKING"
    PHASE_DEGRADED_FREQUENCY_ONLY = "PHASE_DEGRADED_FREQUENCY_ONLY"
    FAIL_STATIC = "FAIL_STATIC"


@dataclass(frozen=True)
class ActiveHybridPolicy:
    policy_id: str
    policy_sha256: str
    frequency_estimator_id: str
    frequency_estimator_sha256: str
    phase_estimator_id: str
    phase_estimator_sha256: str
    plant_model_id: str
    plant_model_sha256: str
    response_policy_sha256: str
    pull_in_time_s: int
    phase_bias_cap_hz: float
    integrator_gain_codes_per_hz_per_decision: float
    plant_gain_minimum_hz_per_code: float
    plant_gain_nominal_hz_per_code: float
    plant_gain_maximum_hz_per_code: float
    maximum_step_codes: int
    minimum_code: int
    maximum_code: int
    minimum_cadence_s: int
    settling_exclusion_s: int
    fresh_support_s: int
    phase_qualification_residence_s: int
    maximum_applications: int
    maximum_cumulative_movement_codes: int
    qualified_duration_s: int
    wall_clock_limit_s: int
    phase_entry_consecutive_estimates: int
    phase_entry_absolute_counts_lte: int
    phase_release_consecutive_estimates: int
    phase_release_absolute_counts_gte: int
    start_code: int


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def load_policy(path: Path = DEFAULT_POLICY) -> ActiveHybridPolicy:
    value = _read_object(path)
    if value.get("schema_version") != 1 or value.get("policy_id") != POLICY_ID:
        raise ValueError("unsupported active-hybrid policy identity")
    if value.get("status") != "offline_candidate_non_effective":
        raise ValueError("active-hybrid policy must remain non-effective before authority")

    bindings = value.get("bindings")
    numerical = value.get("numerical_policy")
    limits = value.get("global_authority_limits")
    timing = value.get("finite_timing")
    tight = value.get("tight_hysteretic_band")
    setup = value.get("setup")
    authority = value.get("authority")
    if not all(
        isinstance(section, dict)
        for section in (bindings, numerical, limits, timing, tight, setup, authority)
    ):
        raise ValueError("active-hybrid policy sections must be objects")

    for name, binding in bindings.items():
        if not isinstance(binding, dict):
            raise ValueError(f"binding {name} must be an object")
        source = REPO_ROOT / str(binding.get("path", ""))
        if not source.is_file() or _sha256_file(source) != binding.get("sha256"):
            raise ValueError(f"active-hybrid binding differs: {source}")

    required_false = {
        "effective",
        "firmware_flash",
        "reset",
        "serial_access",
        "command_fifo",
        "setup_stimulus",
        "dac_write",
        "control_arm",
        "physical_rehearsal",
        "live_acquisition",
    }
    if any(authority.get(name) is not False for name in required_false):
        raise ValueError("physical active-hybrid authority must remain non-effective")
    if authority.get("offline_preparation") is not True:
        raise ValueError("offline preparation must remain enabled")

    if numerical.get("controller_type") != "one_incremental_combined_frequency_phase_output":
        raise ValueError("active-hybrid controller must have one combined output")
    if numerical.get("rounding") != "half_away_from_zero_after_step_limit":
        raise ValueError("active-hybrid rounding rule differs")
    if limits.get("automatic_retry") is not False or limits.get("automatic_restoration") is not False:
        raise ValueError("automatic retry and restoration must remain forbidden")
    if int(limits["maximum_outstanding_requests"]) != 1:
        raise ValueError("active-hybrid outstanding request limit differs")

    estimator = _read_object(REPO_ROOT / bindings["frequency_estimator"]["path"])
    phase = _read_object(REPO_ROOT / bindings["phase_estimator"]["path"])
    plant = _read_object(REPO_ROOT / bindings["plant_model"]["path"])
    gains = numerical["plant_gain_hz_per_code"]

    policy = ActiveHybridPolicy(
        policy_id=POLICY_ID,
        policy_sha256=_sha256_file(path),
        frequency_estimator_id="cx317_selected_600s_nonoverlap_v1",
        frequency_estimator_sha256=str(bindings["frequency_estimator"]["sha256"]),
        phase_estimator_id=str(phase["selection"]["selected_estimator_id"]),
        phase_estimator_sha256=str(bindings["phase_estimator"]["sha256"]),
        plant_model_id=str(plant["model_id"]),
        plant_model_sha256=str(bindings["plant_model"]["sha256"]),
        response_policy_sha256=str(bindings["response_policy"]["sha256"]),
        pull_in_time_s=int(numerical["phase_pull_in_time_s"]),
        phase_bias_cap_hz=float(numerical["absolute_phase_bias_cap_hz"]),
        integrator_gain_codes_per_hz_per_decision=float(
            numerical["integrator_gain_codes_per_hz_per_decision"]
        ),
        plant_gain_minimum_hz_per_code=float(gains["minimum"]),
        plant_gain_nominal_hz_per_code=float(gains["nominal"]),
        plant_gain_maximum_hz_per_code=float(gains["maximum"]),
        maximum_step_codes=int(limits["maximum_combined_step_codes"]),
        minimum_code=int(limits["minimum_code"]),
        maximum_code=int(limits["maximum_code"]),
        minimum_cadence_s=int(limits["minimum_applied_cadence_s"]),
        settling_exclusion_s=int(numerical["settling_exclusion_s"]),
        fresh_support_s=int(numerical["fresh_support_after_settling_s"]),
        phase_qualification_residence_s=int(
            numerical["phase_qualification_residence_s"]
        ),
        maximum_applications=int(limits["maximum_total_automatic_applications"]),
        maximum_cumulative_movement_codes=int(
            limits["maximum_cumulative_absolute_movement_codes"]
        ),
        qualified_duration_s=int(timing["qualified_duration_s"]),
        wall_clock_limit_s=int(timing["absolute_wall_clock_limit_s"]),
        phase_entry_consecutive_estimates=int(
            tight["entry_consecutive_fresh_estimates"]
        ),
        phase_entry_absolute_counts_lte=int(tight["entry_absolute_counts_lte"]),
        phase_release_consecutive_estimates=int(
            tight["release_consecutive_fresh_estimates"]
        ),
        phase_release_absolute_counts_gte=int(tight["release_absolute_counts_gte"]),
        start_code=int(setup["exact_start_code"]),
    )
    if (
        policy.pull_in_time_s != 21_600
        or not math.isclose(policy.phase_bias_cap_hz, 1 / 600, rel_tol=0, abs_tol=1e-18)
        or policy.maximum_step_codes != 21
        or policy.minimum_code != 0xA800
        or policy.maximum_code != 0xAB00
        or policy.minimum_cadence_s != 1_800
        or policy.phase_qualification_residence_s != 1_800
        or policy.maximum_applications != 4
        or policy.maximum_cumulative_movement_codes != 84
        or policy.qualified_duration_s != 43_200
        or policy.wall_clock_limit_s != 57_600
        or policy.start_code != 0xA83C
    ):
        raise ValueError("active-hybrid frozen envelope differs")
    return policy


@dataclass(frozen=True)
class HybridObservation:
    timestamp_s: int
    capture_session: int
    source_first_sequence: int
    source_last_sequence: int
    dac_epoch: int
    applied_code: int
    frequency_error_hz: float
    accumulated_edge_error_counts: int
    tight_state: str
    phase_epoch: int
    phase_observation_sequence: int
    relative_phase_cycles: int
    phase_dac_epoch: int
    phase_applied_code: int
    phase_continuous: bool = True
    phase_current: bool = True
    phase_step_detected: bool = False
    identity_exact: bool = True
    common_health_clean: bool = True
    phase_consumers_exact: bool = True
    outstanding_request: bool = False
    outstanding_response: bool = False


@dataclass(frozen=True)
class HybridDecision:
    decision_sequence: int
    state_before: str
    state_after: str
    reason: str
    timestamp_s: int
    capture_session: int
    source_first_sequence: int
    source_last_sequence: int
    frequency_estimator_id: str
    frequency_estimator_sha256: str
    frequency_error_hz: float
    accumulated_edge_error_counts: int
    tight_state: str
    phase_estimator_id: str
    phase_estimator_sha256: str
    phase_epoch: int
    phase_observation_sequence: int
    relative_phase_cycles: int
    dac_epoch: int
    current_applied_code: int
    frequency_term_hz: float
    phase_term_hz: float
    combined_demand_hz: float
    raw_combined_delta_codes: float
    requested_delta_codes: int
    requested_code: int
    counterfactual_frequency_only_delta_codes: int
    phase_materially_influenced: bool
    step_limited: bool
    range_clamped: bool
    cadence_limited: bool
    count_limited: bool
    cumulative_budget_limited: bool
    correction_count_before: int
    cumulative_movement_before_codes: int
    actionable: bool = False


def _round_half_away(value: float) -> int:
    if not math.isfinite(value):
        raise HybridPolicyError("cannot round non-finite controller demand")
    return math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5)


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, value))


class ActiveHybridController:
    """One-output progressive-authority controller with explicit checkpoints."""

    def __init__(
        self,
        policy: ActiveHybridPolicy,
        *,
        plant_gain_hz_per_code: float | None = None,
        setup_application_s: int | None = None,
    ) -> None:
        self.policy = policy
        self.plant_gain = (
            policy.plant_gain_nominal_hz_per_code
            if plant_gain_hz_per_code is None
            else float(plant_gain_hz_per_code)
        )
        if not (
            math.isfinite(self.plant_gain)
            and policy.plant_gain_minimum_hz_per_code
            <= self.plant_gain
            <= policy.plant_gain_maximum_hz_per_code
        ):
            raise ValueError("plant gain is outside the frozen measured envelope")
        if setup_application_s is not None and setup_application_s < 0:
            raise ValueError("setup application timestamp must be nonnegative")
        self.state = HybridState.FREQUENCY_ACQUIRE
        self.reason = "initialized_frequency_acquire"
        self.decision_sequence = 0
        self.applied_code = policy.start_code
        # The exact setup transaction is the first physical epoch.  The
        # controller is initialized only after that epoch has propagated.
        self.dac_epoch = 1
        self.correction_count = 0
        self.cumulative_movement_codes = 0
        self.last_application_s = setup_application_s
        self.direction_history: list[int] = []
        self.transaction_outstanding = False
        self.outstanding_phase_material = False
        self.first_checkpoint_response_passed = False
        self.phase_material_application_count = 0
        self.frequency_only_application_count = 0
        self.phase_nonzero_application_count = 0
        self.phase_epoch: int | None = None
        self.phase_session: int | None = None
        self.phase_qualification_started_s: int | None = None
        self.fault_reason: str | None = None

    def _fault(self, reason: str) -> None:
        self.state = HybridState.FAIL_STATIC
        self.reason = reason
        self.fault_reason = reason
        self.transaction_outstanding = False

    def _phase_exact(self, observation: HybridObservation) -> bool:
        return (
            observation.phase_continuous
            and observation.phase_current
            and not observation.phase_step_detected
            and observation.phase_consumers_exact
            and observation.phase_epoch > 0
            and observation.phase_observation_sequence > 0
            and observation.phase_dac_epoch == observation.dac_epoch
            and observation.phase_applied_code == observation.applied_code
        )

    def _limited_delta(self, demand_hz: float, current_code: int) -> tuple[float, int, bool, bool]:
        raw = self.policy.integrator_gain_codes_per_hz_per_decision * demand_hz
        limited = _clamp(
            raw,
            -float(self.policy.maximum_step_codes),
            float(self.policy.maximum_step_codes),
        )
        step_limited = not math.isclose(raw, limited, rel_tol=0, abs_tol=1e-12)
        rounded = _round_half_away(limited)
        unclamped = current_code + rounded
        requested_code = min(
            self.policy.maximum_code,
            max(self.policy.minimum_code, unclamped),
        )
        return raw, requested_code - current_code, step_limited, requested_code != unclamped

    def _chatter_reason(self, delta: int) -> str | None:
        direction = 1 if delta > 0 else -1
        prospective = [*self.direction_history[-3:], direction]
        reversals = sum(a != b for a, b in zip(prospective, prospective[1:]))
        if len(prospective) == 4 and reversals == 3:
            return "prospective_repeated_alternation"
        path = self.cumulative_movement_codes + abs(delta)
        net = abs(self.applied_code + delta - self.policy.start_code)
        if path >= 42 and net <= 0.25 * path:
            return "prospective_low_efficiency_path"
        return None

    def _frequency_only_counterfactual_delta(
        self, frequency_term_hz: float, current_code: int
    ) -> int:
        """Replay the final integer request with only the phase term removed."""

        _, delta, _, _ = self._limited_delta(frequency_term_hz, current_code)
        if delta == 0:
            return 0
        if self.correction_count + 1 > self.policy.maximum_applications:
            return 0
        if (
            self.cumulative_movement_codes + abs(delta)
            > self.policy.maximum_cumulative_movement_codes
        ):
            return 0
        if self._chatter_reason(delta) is not None:
            return 0
        return delta

    def decide(self, observation: HybridObservation) -> HybridDecision:
        self.decision_sequence += 1
        before = self.state
        cadence_limited = False
        count_limited = False
        cumulative_limited = False
        step_limited = False
        range_clamped = False
        progressive_release_transition = False
        frequency_term = -float(observation.frequency_error_hz)
        phase_term = 0.0
        combined = 0.0
        raw_delta = 0.0
        delta = 0
        counterfactual_delta = 0
        reason = self.reason

        phase_exact_now = self._phase_exact(observation)
        if self.state is HybridState.FAIL_STATIC:
            reason = self.fault_reason or "fail_static_latched"
        elif not observation.identity_exact or not observation.common_health_clean:
            self._fault("measurement_authority_or_common_health_fault")
            reason = self.reason
        elif observation.applied_code != self.applied_code or observation.dac_epoch != self.dac_epoch:
            self._fault("actual_applied_code_or_dac_epoch_ambiguous")
            reason = self.reason
        elif observation.outstanding_request != self.transaction_outstanding:
            self._fault("transaction_outstanding_identity_mismatch")
            reason = self.reason
        elif (
            self.transaction_outstanding
            and self.outstanding_phase_material
            and not phase_exact_now
        ):
            self._fault("phase_invalid_during_transaction_or_response_horizon")
            reason = self.reason
        elif self.transaction_outstanding or observation.outstanding_response:
            reason = "request_or_response_checkpoint_outstanding"
        else:
            phase_exact = phase_exact_now
            if phase_exact:
                if self.phase_session is None:
                    self.phase_session = observation.capture_session
                    self.phase_epoch = observation.phase_epoch
                elif (
                    observation.capture_session != self.phase_session
                    or observation.phase_epoch != self.phase_epoch
                ):
                    phase_exact = False

            if not phase_exact and self.state in {
                HybridState.PHASE_QUALIFY,
                HybridState.FIRST_PHASE_TRANSACTION,
                HybridState.HYBRID_TRACKING,
            }:
                self.state = HybridState.PHASE_DEGRADED_FREQUENCY_ONLY
                self.reason = "phase_evidence_invalid_at_clean_boundary"
                reason = self.reason

            if self.state is HybridState.FIRST_PHASE_TRANSACTION:
                if self.first_checkpoint_response_passed and observation.tight_state == "TIGHT_INSIDE":
                    self.state = HybridState.HYBRID_TRACKING
                    self.reason = "first_phase_checkpoint_passed_and_tight_reacquired"
                    reason = self.reason
                    progressive_release_transition = True
                else:
                    reason = "first_phase_checkpoint_or_tight_reacquisition_pending"
            elif self.state is HybridState.FREQUENCY_ACQUIRE and observation.tight_state == "TIGHT_INSIDE":
                self.state = HybridState.PHASE_QUALIFY
                self.phase_qualification_started_s = observation.timestamp_s
                self.reason = "two_fresh_tight_estimates_enter_phase_qualification"
                reason = self.reason
            elif self.state is HybridState.PHASE_QUALIFY:
                if observation.tight_state != "TIGHT_INSIDE":
                    self.state = HybridState.FREQUENCY_ACQUIRE
                    self.phase_qualification_started_s = None
                    self.reason = "tight_frequency_residence_lost"
                    reason = self.reason
                elif phase_exact:
                    self.reason = "phase_qualified_first_transaction_eligible"
                    reason = self.reason

            phase_authorized = (
                phase_exact
                and observation.tight_state == "TIGHT_INSIDE"
                and self.state in {HybridState.PHASE_QUALIFY, HybridState.HYBRID_TRACKING}
                and reason != "two_fresh_tight_estimates_enter_phase_qualification"
                and not progressive_release_transition
                and (
                    self.state is HybridState.HYBRID_TRACKING
                    or (
                        self.phase_qualification_started_s is not None
                        and observation.timestamp_s
                        - self.phase_qualification_started_s
                        >= self.policy.phase_qualification_residence_s
                    )
                )
            )
            frequency_authorized = (
                observation.tight_state != "TIGHT_INSIDE"
                and self.state
                in {
                    HybridState.FREQUENCY_ACQUIRE,
                    HybridState.PHASE_DEGRADED_FREQUENCY_ONLY,
                }
            )
            if phase_authorized:
                phase_term = _clamp(
                    -float(observation.relative_phase_cycles)
                    / float(self.policy.pull_in_time_s),
                    -self.policy.phase_bias_cap_hz,
                    self.policy.phase_bias_cap_hz,
                )
                combined = frequency_term + phase_term
            elif frequency_authorized:
                combined = frequency_term

            if phase_authorized or frequency_authorized:
                if (
                    self.last_application_s is not None
                    and observation.timestamp_s - self.last_application_s
                    < self.policy.minimum_cadence_s
                ):
                    cadence_limited = True
                    reason = "minimum_applied_cadence_hold"
                else:
                    raw_delta, delta, step_limited, range_clamped = self._limited_delta(
                        combined, observation.applied_code
                    )
                    counterfactual_delta = self._frequency_only_counterfactual_delta(
                        frequency_term, observation.applied_code
                    )
                    if delta != 0 and phase_authorized and delta * phase_term < 0:
                        delta = 0
                        reason = "phase_direction_coherence_hold"
                    elif delta == 0:
                        reason = "zero_rounded_or_range_hold"
                    elif self.correction_count + 1 > self.policy.maximum_applications:
                        count_limited = True
                        delta = 0
                        reason = "global_application_budget_hold"
                    elif (
                        self.cumulative_movement_codes + abs(delta)
                        > self.policy.maximum_cumulative_movement_codes
                    ):
                        cumulative_limited = True
                        delta = 0
                        reason = "global_cumulative_movement_budget_hold"
                    else:
                        chatter = self._chatter_reason(delta)
                        if chatter is not None:
                            self._fault(chatter)
                            delta = 0
                            reason = self.reason
                        else:
                            reason = (
                                "phase_material_request_ready"
                                if phase_authorized and delta != counterfactual_delta
                                else "combined_nonmaterial_request_ready"
                                if phase_authorized
                                else "frequency_acquisition_request_ready"
                            )

        material = phase_term != 0.0 and delta != counterfactual_delta
        return HybridDecision(
            decision_sequence=self.decision_sequence,
            state_before=before.value,
            state_after=self.state.value,
            reason=reason,
            timestamp_s=observation.timestamp_s,
            capture_session=observation.capture_session,
            source_first_sequence=observation.source_first_sequence,
            source_last_sequence=observation.source_last_sequence,
            frequency_estimator_id=self.policy.frequency_estimator_id,
            frequency_estimator_sha256=self.policy.frequency_estimator_sha256,
            frequency_error_hz=observation.frequency_error_hz,
            accumulated_edge_error_counts=observation.accumulated_edge_error_counts,
            tight_state=observation.tight_state,
            phase_estimator_id=self.policy.phase_estimator_id,
            phase_estimator_sha256=self.policy.phase_estimator_sha256,
            phase_epoch=observation.phase_epoch,
            phase_observation_sequence=observation.phase_observation_sequence,
            relative_phase_cycles=observation.relative_phase_cycles,
            dac_epoch=observation.dac_epoch,
            current_applied_code=observation.applied_code,
            frequency_term_hz=frequency_term,
            phase_term_hz=phase_term,
            combined_demand_hz=combined,
            raw_combined_delta_codes=raw_delta,
            requested_delta_codes=delta,
            requested_code=observation.applied_code + delta,
            counterfactual_frequency_only_delta_codes=counterfactual_delta,
            phase_materially_influenced=material,
            step_limited=step_limited,
            range_clamped=range_clamped,
            cadence_limited=cadence_limited,
            count_limited=count_limited,
            cumulative_budget_limited=cumulative_limited,
            correction_count_before=self.correction_count,
            cumulative_movement_before_codes=self.cumulative_movement_codes,
            actionable=False,
        )

    def note_application(
        self,
        decision: HybridDecision,
        *,
        applied_code: int,
        dac_epoch: int,
        downstream_consumers_exact: bool,
    ) -> None:
        if self.state is HybridState.FAIL_STATIC:
            raise HybridPolicyError("cannot apply after fail-static")
        if self.transaction_outstanding or decision.requested_delta_codes == 0:
            self._fault("invalid_or_overlapping_application")
            raise HybridPolicyError(self.reason)
        if (
            applied_code != decision.requested_code
            or dac_epoch != self.dac_epoch + 1
            or not downstream_consumers_exact
        ):
            self._fault("application_or_downstream_epoch_mismatch")
            raise HybridPolicyError(self.reason)
        self.applied_code = applied_code
        self.dac_epoch = dac_epoch
        self.correction_count += 1
        self.cumulative_movement_codes += abs(decision.requested_delta_codes)
        self.last_application_s = decision.timestamp_s
        self.direction_history.append(1 if decision.requested_delta_codes > 0 else -1)
        self.transaction_outstanding = True
        self.outstanding_phase_material = decision.phase_materially_influenced
        if decision.phase_term_hz != 0.0:
            self.phase_nonzero_application_count += 1
        if decision.phase_materially_influenced:
            self.phase_material_application_count += 1
            if self.phase_material_application_count == 1:
                self.state = HybridState.FIRST_PHASE_TRANSACTION
                self.first_checkpoint_response_passed = False
                self.reason = "first_phase_application_checkpoint_required"
        else:
            self.frequency_only_application_count += 1
            self.reason = "application_confirmed_response_required"

    def note_response(
        self,
        *,
        classification: str,
        predicted_sign_observed: bool,
        exact_replay: bool,
        support_fresh: bool,
        applied_epoch_exact: bool,
    ) -> None:
        if not self.transaction_outstanding:
            self._fault("response_without_outstanding_application")
            raise HybridPolicyError(self.reason)
        healthy = (
            classification
            in {
                "healthy_detected",
                "healthy_indeterminate_near_resolution",
                "inside_deadband",
            }
            and predicted_sign_observed
            and exact_replay
            and support_fresh
            and applied_epoch_exact
        )
        was_phase_material = self.outstanding_phase_material
        self.transaction_outstanding = False
        self.outstanding_phase_material = False
        if not healthy:
            self._fault("hybrid_response_wrong_or_checkpoint_evidence_invalid")
            return
        if was_phase_material and self.phase_material_application_count == 1:
            self.first_checkpoint_response_passed = True
            self.reason = "first_phase_response_passed_tight_reacquisition_required"
        else:
            self.reason = "response_passed"

    def degrade_phase(self, reason: str = "phase_channel_degraded") -> None:
        if self.transaction_outstanding:
            self._fault("phase_invalid_during_transaction_or_response_horizon")
            return
        if self.state is not HybridState.FAIL_STATIC:
            self.state = HybridState.PHASE_DEGRADED_FREQUENCY_ONLY
            self.phase_epoch = None
            self.phase_session = None
            self.reason = reason

    def snapshot(self) -> dict[str, Any]:
        return {
            "tool": TOOL_ID,
            "policy_id": self.policy.policy_id,
            "policy_sha256": self.policy.policy_sha256,
            "state": self.state.value,
            "reason": self.reason,
            "applied_code": self.applied_code,
            "dac_epoch": self.dac_epoch,
            "correction_count": self.correction_count,
            "cumulative_movement_codes": self.cumulative_movement_codes,
            "phase_nonzero_application_count": self.phase_nonzero_application_count,
            "phase_material_application_count": self.phase_material_application_count,
            "frequency_only_application_count": self.frequency_only_application_count,
            "transaction_outstanding": self.transaction_outstanding,
            "first_checkpoint_response_passed": self.first_checkpoint_response_passed,
        }


def decision_dict(decision: HybridDecision) -> dict[str, Any]:
    return asdict(decision)
