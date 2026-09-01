"""Deterministic bounded active-hybrid controller reference.

The controller has one combined output and no transport or actuator surface.
Frequency acquisition and phase steering share the same integer request,
cadence, range, count, and cumulative-movement limits.  Live authority remains
the responsibility of the transaction layer and an exact programme bundle.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from fractions import Fraction
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
SUPPORTED_POLICY_IDS = {
    POLICY_ID,
    "CX322_BOUNDED_HYBRID_FACT_GATHERING_V1",
    "OTIS_SUSTAINED_HYBRID_REGULATION_V1",
}
CX323_POLICY_ID = "CX323_PHASE_PRIORITY_PERSISTENT_MAINTENANCE_V1"
CX323_POLICY_PATH = (
    REPO_ROOT / "profiles/discipline/cx323_phase_priority_persistent_maintenance_v2.json"
)
CX323_POLICY_SHA256 = "24ec5210b897b3ea9dd64aa5946c69e02e277c09922f5a5208f3476d6eaba926"
CX323_LEGACY_POLICY_SHA256 = "36e16b0553add14f5f3f1ea0cc9753af113964b039551a86d6b5564a89282e24"
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
    maximum_physical_applications: int
    maximum_cumulative_movement_codes: int
    qualified_duration_s: int
    wall_clock_limit_s: int
    phase_entry_consecutive_estimates: int
    phase_entry_absolute_counts_lte: int
    phase_release_consecutive_estimates: int
    phase_release_absolute_counts_gte: int
    start_code: int
    response_checkpoint_observational: bool
    reversal_challenge_enabled: bool
    natural_reversal_window_s: int
    challenge_latest_s: int
    challenge_step_codes: int


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _is_unavailable_historical_binding(name: str, source: Path) -> bool:
    """Recognize the one sealed run-package reference absent from clean trees.

    ``runs/`` is deliberately ignored.  The policy remains bound to the
    predecessor seal SHA, but an offline policy/replay reader must not require
    a local copy of that historical package merely to exercise current
    semantics.  The no-I/O preflight separately calls ``audit_predecessor``;
    that gate requires and fully verifies the sealed physical package before a
    proposal can progress.
    """
    try:
        relative = source.relative_to(REPO_ROOT)
    except ValueError:
        return False
    return name == "predecessor_programme_seal" and relative.parts[:1] == ("runs",)


def load_policy(path: Path = DEFAULT_POLICY) -> ActiveHybridPolicy | "CX323Policy":
    value = _read_object(path)
    if value.get("policy_id") == CX323_POLICY_ID:
        return load_cx323_policy(path)
    policy_id = value.get("policy_id")
    if value.get("schema_version") != 1 or policy_id not in SUPPORTED_POLICY_IDS:
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
    response_checkpoint = value.get("response_checkpoint", {})
    if not all(
        isinstance(section, dict)
        for section in (bindings, numerical, limits, timing, tight, setup, authority)
    ):
        raise ValueError("active-hybrid policy sections must be objects")

    for name, binding in bindings.items():
        if not isinstance(binding, dict):
            raise ValueError(f"binding {name} must be an object")
        source = REPO_ROOT / str(binding.get("path", ""))
        if not source.is_file() and _is_unavailable_historical_binding(name, source):
            continue
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

    if (
        isinstance(response_checkpoint, dict)
        and response_checkpoint.get("mode") == "observational_non_terminal"
    ):
        predecessor_binding = bindings.get("natural_policy_predecessor")
        if not isinstance(predecessor_binding, dict):
            raise ValueError("observational policy lacks its natural-policy predecessor")
        predecessor = _read_object(
            REPO_ROOT / str(predecessor_binding.get("path", ""))
        )
        predecessor_numerical = predecessor.get("numerical_policy", {})
        predecessor_limits = predecessor.get("global_authority_limits", {})
        predecessor_gains = predecessor_numerical.get(
            "plant_gain_hz_per_code", {}
        )
        numerical_fields = {
            "controller_type",
            "frequency_term",
            "phase_term",
            "phase_pull_in_time_s",
            "absolute_phase_bias_cap_hz",
            "integrator_gain_codes_per_hz_per_decision",
            "rounding",
            "anti_windup",
            "phase_direction_coherence",
            "settling_exclusion_s",
            "fresh_support_after_settling_s",
            "response_support_total_s",
            "phase_qualification_residence_s",
            "phase_zero",
            "phase_unit",
            "phase_epoch_join",
        }
        limit_fields = {
            "maximum_total_automatic_applications",
            "maximum_combined_step_codes",
            "maximum_cumulative_absolute_movement_codes",
            "minimum_applied_cadence_s",
            "minimum_code",
            "maximum_code",
            "maximum_outstanding_requests",
            "automatic_retry",
            "automatic_restoration",
        }
        if policy_id == "OTIS_SUSTAINED_HYBRID_REGULATION_V1":
            limit_fields.remove("maximum_total_automatic_applications")
        if (
            any(
                numerical.get(name) != predecessor_numerical.get(name)
                for name in numerical_fields
            )
            or any(
                gains.get(name) != predecessor_gains.get(name)
                for name in {"minimum", "nominal", "maximum"}
            )
            or tight != predecessor.get("tight_hysteretic_band")
            or any(
                limits.get(name) != predecessor_limits.get(name)
                for name in limit_fields
            )
        ):
            raise ValueError(
                "observational policy changes the frozen natural controller"
            )

    challenge = value.get("reversal_challenge", {})
    if not isinstance(challenge, dict):
        raise ValueError("active-hybrid reversal challenge must be an object")
    policy = ActiveHybridPolicy(
        policy_id=str(policy_id),
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
        maximum_physical_applications=int(
            limits.get(
                "maximum_total_physical_control_applications_including_challenge",
                limits["maximum_total_automatic_applications"],
            )
        ),
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
        response_checkpoint_observational=(
            isinstance(response_checkpoint, dict)
            and response_checkpoint.get("mode") == "observational_non_terminal"
        ),
        reversal_challenge_enabled=bool(challenge),
        natural_reversal_window_s=int(
            challenge.get("natural_reversal_window_qualified_s", 0)
        ),
        challenge_latest_s=int(
            challenge.get("first_eligible_challenge_no_later_than_qualified_s", 0)
        ),
        challenge_step_codes=int(challenge.get("default_step_codes", 0)),
    )
    sustained = policy.policy_id == "OTIS_SUSTAINED_HYBRID_REGULATION_V1"
    if (
        policy.pull_in_time_s != 21_600
        or not math.isclose(policy.phase_bias_cap_hz, 1 / 600, rel_tol=0, abs_tol=1e-18)
        or policy.maximum_step_codes != 21
        or policy.minimum_code != 0xA800
        or policy.maximum_code != 0xAB00
        or policy.minimum_cadence_s != 1_800
        or policy.phase_qualification_residence_s != 1_800
        or policy.maximum_applications != (12 if sustained else 4)
        or policy.maximum_physical_applications != (13 if sustained else 4)
        or policy.maximum_cumulative_movement_codes != 84
        or policy.qualified_duration_s != (86_400 if sustained else 43_200)
        or policy.wall_clock_limit_s != (108_000 if sustained else 57_600)
        or policy.start_code != 0xA83C
        or policy.reversal_challenge_enabled is not sustained
        or (sustained and policy.natural_reversal_window_s != 43_200)
        or (sustained and policy.challenge_latest_s != 50_400)
        or (sustained and policy.challenge_step_codes != 21)
    ):
        raise ValueError("active-hybrid frozen envelope differs")
    return policy


@dataclass(frozen=True)
class HybridObservation:
    timestamp_s: float
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
    timestamp_s: float
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
    global_last_application_s: int | None
    natural_chatter_origin_code: int
    natural_cumulative_movement_codes: int
    natural_direction_count: int
    plant_sign_attestation_id: str | None
    plant_sign_handoff_first_consumer: bool
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
        self.automatic_application_count = 0
        self.cumulative_movement_codes = 0
        self.last_application_s = setup_application_s
        # CX320 starts its natural-controller path at the setup code, so these
        # values evolve in lockstep with the global authority counters.  CX321
        # deliberately rebases only this natural chatter/path history after
        # its separately classified plant-sign transaction.
        self.natural_chatter_origin_code = policy.start_code
        self.natural_cumulative_movement_codes = 0
        self.direction_history: list[int] = []
        self.transaction_outstanding = False
        self.outstanding_phase_material = False
        self.outstanding_deliberate_challenge = False
        self.first_checkpoint_response_passed = False
        self.phase_material_application_count = 0
        self.frequency_only_application_count = 0
        self.phase_nonzero_application_count = 0
        self.phase_epoch: int | None = None
        self.phase_session: int | None = None
        self.phase_qualification_started_s: float | None = None
        self.fault_reason: str | None = None
        self.plant_sign_attestation_id: str | None = None
        self._plant_sign_handoff_first_consumer_pending = False
        self.qualified_origin_s: float | None = None
        self.natural_initial_direction: int | None = None
        self.natural_reversal_observed = False
        self.deliberate_challenge_applied = False
        self.deliberate_challenge_cancelled = False
        self.deliberate_challenge_unexercised = False
        self.deliberate_challenge_recovery_applied = False
        self.deliberate_challenge_direction: int | None = None
        self.deliberate_challenge_code: int | None = None
        self.deliberate_challenge_dac_epoch: int | None = None
        self.deliberate_challenge_application_s: float | None = None

    def rebase_after_plant_sign(
        self,
        *,
        applied_code: int,
        dac_epoch: int,
        application_s: int,
        qualification_started_s: int,
        attestation_id: str,
    ) -> None:
        """Enter CX321's unchanged natural controller after plant-sign pass.

        The identification move consumes the shared physical authority budget
        and cadence, but it is not a natural controller decision and therefore
        must not contaminate reversal, path-efficiency, materiality, or phase-
        performance history.  This is an explicit one-time handoff rather than
        a general controller reset.
        """

        if (
            self.state is HybridState.FAIL_STATIC
            or self.transaction_outstanding
            or self.correction_count != 0
            or self.cumulative_movement_codes != 0
            or self.direction_history
            or not attestation_id.strip()
            or applied_code < self.policy.minimum_code
            or applied_code > self.policy.maximum_code
            or dac_epoch != 2
            or application_s < 0
            or qualification_started_s < application_s
        ):
            self._fault("invalid_plant_sign_handoff")
            raise HybridPolicyError(self.reason)
        movement = abs(applied_code - self.policy.start_code)
        if movement != self.policy.maximum_step_codes:
            self._fault("plant_sign_handoff_movement_mismatch")
            raise HybridPolicyError(self.reason)

        self.applied_code = applied_code
        self.dac_epoch = dac_epoch
        self.correction_count = 1
        self.automatic_application_count = 1
        self.cumulative_movement_codes = movement
        self.last_application_s = application_s
        self.natural_chatter_origin_code = applied_code
        self.natural_cumulative_movement_codes = 0
        self.direction_history = []
        self.transaction_outstanding = False
        self.outstanding_phase_material = False
        self.phase_material_application_count = 0
        self.frequency_only_application_count = 0
        self.phase_nonzero_application_count = 0
        self.first_checkpoint_response_passed = False
        self.phase_epoch = None
        self.phase_session = None
        self.phase_qualification_started_s = qualification_started_s
        self.state = HybridState.PHASE_QUALIFY
        self.reason = "plant_sign_attested_fresh_phase_qualification"
        self.plant_sign_attestation_id = attestation_id
        self._plant_sign_handoff_first_consumer_pending = True

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
        path = self.natural_cumulative_movement_codes + abs(delta)
        net = abs(self.applied_code + delta - self.natural_chatter_origin_code)
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
        automatic_count = (
            self.automatic_application_count
            if self.policy.reversal_challenge_enabled
            else self.correction_count
        )
        if automatic_count + 1 > self.policy.maximum_applications:
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
        handoff_first_consumer = self._plant_sign_handoff_first_consumer_pending
        deliberate_challenge_decision = False

        if handoff_first_consumer:
            if (
                self.plant_sign_attestation_id is None
                or self.correction_count != 1
                or self.cumulative_movement_codes != self.policy.maximum_step_codes
                or self.natural_cumulative_movement_codes != 0
                or self.direction_history
                or self.natural_chatter_origin_code != self.applied_code
            ):
                self._fault("plant_sign_first_consumer_handoff_mismatch")
            self._plant_sign_handoff_first_consumer_pending = False

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
            if self.policy.reversal_challenge_enabled and self.qualified_origin_s is None:
                self.qualified_origin_s = observation.timestamp_s
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
                    self.reason = (
                        "first_phase_observation_recorded_and_tight_reacquired"
                        if self.policy.response_checkpoint_observational
                        else "first_phase_checkpoint_passed_and_tight_reacquired"
                    )
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
                    natural_direction = 1 if delta > 0 else -1 if delta < 0 else 0
                    natural_reversal_ready = (
                        natural_direction != 0
                        and self.natural_initial_direction is not None
                        and natural_direction != self.natural_initial_direction
                    )
                    qualified_elapsed_s = (
                        observation.timestamp_s - self.qualified_origin_s
                        if self.qualified_origin_s is not None
                        else 0.0
                    )
                    challenge_due = (
                        self.policy.reversal_challenge_enabled
                        and self.policy.natural_reversal_window_s
                        <= qualified_elapsed_s
                        <= self.policy.challenge_latest_s
                        and not natural_reversal_ready
                        and not self.natural_reversal_observed
                        and not self.deliberate_challenge_applied
                        and not self.deliberate_challenge_cancelled
                        and not self.deliberate_challenge_unexercised
                    )
                    if challenge_due:
                        challenge_direction = self.natural_initial_direction or -1
                        challenge_code = (
                            observation.applied_code
                            + challenge_direction * self.policy.challenge_step_codes
                        )
                        if (
                            not self.policy.minimum_code
                            <= challenge_code
                            <= self.policy.maximum_code
                            or self.cumulative_movement_codes
                            + self.policy.challenge_step_codes
                            > self.policy.maximum_cumulative_movement_codes
                        ):
                            self.deliberate_challenge_unexercised = True
                            delta = 0
                            reason = "deliberate_reversal_challenge_budget_or_range_unavailable"
                        else:
                            delta = challenge_direction * self.policy.challenge_step_codes
                            raw_delta = float(delta)
                            step_limited = False
                            range_clamped = False
                            deliberate_challenge_decision = True
                            reason = "deliberate_reversal_challenge_request_ready"
                    elif delta != 0 and phase_authorized and delta * phase_term < 0:
                        delta = 0
                        reason = "phase_direction_coherence_hold"
                    elif delta == 0:
                        reason = "zero_rounded_or_range_hold"
                    elif (
                        self.automatic_application_count
                        if self.policy.reversal_challenge_enabled
                        else self.correction_count
                    ) + 1 > self.policy.maximum_applications:
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
                    elif not deliberate_challenge_decision:
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
                    if (
                        delta != 0
                        and not deliberate_challenge_decision
                        and self.deliberate_challenge_applied
                        and (1 if delta > 0 else -1)
                        == -self.deliberate_challenge_direction
                    ):
                        reason = "deliberate_reversal_challenge_recovery_request_ready"

            if (
                self.policy.reversal_challenge_enabled
                and self.qualified_origin_s is not None
                and observation.timestamp_s - self.qualified_origin_s
                > self.policy.challenge_latest_s
                and not self.natural_reversal_observed
                and not self.deliberate_challenge_applied
                and not self.deliberate_challenge_cancelled
            ):
                self.deliberate_challenge_unexercised = True

        material = (
            not deliberate_challenge_decision
            and phase_term != 0.0
            and delta != counterfactual_delta
        )
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
            global_last_application_s=self.last_application_s,
            natural_chatter_origin_code=self.natural_chatter_origin_code,
            natural_cumulative_movement_codes=self.natural_cumulative_movement_codes,
            natural_direction_count=len(self.direction_history),
            plant_sign_attestation_id=self.plant_sign_attestation_id,
            plant_sign_handoff_first_consumer=handoff_first_consumer,
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
        deliberate_challenge = (
            decision.reason == "deliberate_reversal_challenge_request_ready"
        )
        if not deliberate_challenge:
            self.automatic_application_count += 1
        self.cumulative_movement_codes += abs(decision.requested_delta_codes)
        if not deliberate_challenge:
            self.natural_cumulative_movement_codes += abs(
                decision.requested_delta_codes
            )
        self.last_application_s = decision.timestamp_s
        direction = 1 if decision.requested_delta_codes > 0 else -1
        if deliberate_challenge:
            self.deliberate_challenge_applied = True
            self.deliberate_challenge_direction = direction
            self.deliberate_challenge_code = applied_code
            self.deliberate_challenge_dac_epoch = dac_epoch
            self.deliberate_challenge_application_s = decision.timestamp_s
        else:
            if self.natural_initial_direction is None:
                self.natural_initial_direction = direction
            elif direction != self.natural_initial_direction:
                self.natural_reversal_observed = True
                if not self.deliberate_challenge_applied:
                    self.deliberate_challenge_cancelled = True
            if (
                self.deliberate_challenge_applied
                and direction == -self.deliberate_challenge_direction
            ):
                self.deliberate_challenge_recovery_applied = True
            self.direction_history.append(direction)
        self.transaction_outstanding = True
        self.outstanding_deliberate_challenge = deliberate_challenge
        self.outstanding_phase_material = (
            deliberate_challenge or decision.phase_materially_influenced
        )
        if not deliberate_challenge and decision.phase_term_hz != 0.0:
            self.phase_nonzero_application_count += 1
        if not deliberate_challenge and decision.phase_materially_influenced:
            self.phase_material_application_count += 1
            if self.phase_material_application_count == 1:
                self.state = HybridState.FIRST_PHASE_TRANSACTION
                self.first_checkpoint_response_passed = False
                self.reason = "first_phase_application_checkpoint_required"
        elif not deliberate_challenge:
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
        recognized = classification in {
            "healthy_detected",
            "healthy_indeterminate_near_resolution",
            "inside_deadband",
            "limit_reached",
            "wrong_sign",
            "excess_response",
            "growing_error",
            "measurement_or_actuator_fault",
        }
        evidence_exact = exact_replay and support_fresh and applied_epoch_exact
        healthy = (
            recognized
            and classification != "measurement_or_actuator_fault"
            and evidence_exact
            and (
                self.policy.response_checkpoint_observational
                or (
                    classification
                    in {
                        "healthy_detected",
                        "healthy_indeterminate_near_resolution",
                        "inside_deadband",
                    }
                    and predicted_sign_observed
                )
            )
        )
        was_phase_material = self.outstanding_phase_material
        was_deliberate_challenge = self.outstanding_deliberate_challenge
        self.transaction_outstanding = False
        self.outstanding_phase_material = False
        self.outstanding_deliberate_challenge = False
        if not healthy:
            self._fault("hybrid_response_wrong_or_checkpoint_evidence_invalid")
            return
        if was_deliberate_challenge:
            self.reason = "deliberate_reversal_challenge_response_observation_recorded"
        elif was_phase_material and self.phase_material_application_count == 1:
            self.first_checkpoint_response_passed = True
            self.reason = (
                "first_phase_observation_recorded_tight_reacquisition_required"
                if self.policy.response_checkpoint_observational
                else "first_phase_response_passed_tight_reacquisition_required"
            )
        else:
            self.reason = (
                "response_observation_recorded"
                if self.policy.response_checkpoint_observational
                else "response_passed"
            )

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
            "automatic_application_count": self.automatic_application_count,
            "cumulative_movement_codes": self.cumulative_movement_codes,
            "global_last_application_s": self.last_application_s,
            "natural_chatter_origin_code": self.natural_chatter_origin_code,
            "natural_cumulative_movement_codes": self.natural_cumulative_movement_codes,
            "natural_direction_count": len(self.direction_history),
            "plant_sign_attestation_id": self.plant_sign_attestation_id,
            "phase_nonzero_application_count": self.phase_nonzero_application_count,
            "phase_material_application_count": self.phase_material_application_count,
            "frequency_only_application_count": self.frequency_only_application_count,
            "transaction_outstanding": self.transaction_outstanding,
            "first_checkpoint_response_passed": self.first_checkpoint_response_passed,
            "qualified_origin_s": self.qualified_origin_s,
            "natural_initial_direction": self.natural_initial_direction,
            "natural_reversal_observed": self.natural_reversal_observed,
            "deliberate_challenge_applied": self.deliberate_challenge_applied,
            "deliberate_challenge_cancelled": self.deliberate_challenge_cancelled,
            "deliberate_challenge_unexercised": self.deliberate_challenge_unexercised,
            "deliberate_challenge_recovery_applied": self.deliberate_challenge_recovery_applied,
            "deliberate_challenge_direction": self.deliberate_challenge_direction,
            "deliberate_challenge_code": self.deliberate_challenge_code,
            "deliberate_challenge_dac_epoch": self.deliberate_challenge_dac_epoch,
            "deliberate_challenge_application_s": self.deliberate_challenge_application_s,
        }


def decision_dict(decision: HybridDecision) -> dict[str, Any]:
    return asdict(decision)


# CX323 is deliberately a separate controller/oracle.  The CX320/CX322 class
# above remains the exact historical implementation and must not gain CX323
# state, fixed-point arithmetic, or metadata semantics by accident.
_CX323_PICO = 1_000_000_000_000
_CX323_DEBT_LIMIT = 500_000_000_000
_CX323_TICKS_PER_SECOND = 16_000_000
_CX323_NUMERATOR = 625_000_000_000_000_000_000
_CX323_DENOMINATOR = 4_680_182_727
_CX323_GAIN = Fraction("2884.5027706464516")
# The selected profile's campaign setup code.  It is named rather than derived
# from a range offset so that the hardware/setup binding is explicit.
_CX323_DEFAULT_SETUP_CODE = 0xA84D


@dataclass(frozen=True)
class CX323Policy:
    policy_id: str
    policy_sha256: str
    frequency_estimator_id: str
    maximum_step_codes: int
    minimum_code: int
    maximum_code: int
    minimum_cadence_s: int
    settling_exclusion_s: int
    maximum_applications: int
    maximum_cumulative_movement_codes: int
    setup_code: int = _CX323_DEFAULT_SETUP_CODE


def load_cx323_policy(path: Path = CX323_POLICY_PATH) -> CX323Policy:
    """Load and bind the selected CX323 host/oracle policy profile."""

    value = _read_object(path)
    observed_sha256 = _sha256_file(path)
    if (
        (value.get("schema_version"), observed_sha256)
        not in {
            (2, CX323_POLICY_SHA256),
            (1, CX323_LEGACY_POLICY_SHA256),
        }
        or value.get("policy_id") != CX323_POLICY_ID
        or value.get("candidate_id")
        != "cx323_phase_priority_persistent_cap_tagged_debt_v1"
        or value.get("status")
        != "selected_for_implementation_native_parity_and_rehearsal_pending"
    ):
        raise ValueError("CX323 policy profile identity differs")
    bindings = value.get("bindings")
    if not isinstance(bindings, dict):
        raise ValueError("CX323 policy bindings must be an object")
    for name, binding in bindings.items():
        if not isinstance(binding, dict) or "path" not in binding:
            raise ValueError(f"CX323 binding {name} differs")
        expected = binding.get("sha256", binding.get("file_sha256"))
        source = REPO_ROOT / str(binding["path"])
        if not isinstance(expected, str) or not source.is_file() or _sha256_file(source) != expected:
            raise ValueError(f"CX323 binding differs: {name}")
    selection = value.get("maintenance_selection", {})
    arithmetic = value.get("maintenance_arithmetic", {})
    limits = value.get("global_authority_limits", {})
    debt = value.get("correction_debt", {})
    if (
        selection.get("requires_tight_state") != "TIGHT_INSIDE"
        or selection.get("required_consecutive_same_sign_windows") != 2
        or selection.get("frontier_support") != "(opening_closing]"
        or arithmetic.get("authoritative_fixed_point_unit")
        != "signed_integer_picocode_1e_minus_12_code"
        or arithmetic.get("picocode_reduced_numerator") != _CX323_NUMERATOR
        or arithmetic.get("picocode_reduced_denominator") != _CX323_DENOMINATOR
        or arithmetic.get("maximum_absolute_combined_centre_units")
        != 332_041_393_326_771_929_124
        or arithmetic.get("native_boundary_contract")
        != "OTIS_CX323_SUSTAINED_HYBRID_SUCCESSOR_STUDY_V3"
        or debt.get("maximum_absolute_total_picocodes") != _CX323_DEBT_LIMIT
        or limits.get("maximum_outstanding_requests") != 1
    ):
        raise ValueError("CX323 frozen maintenance semantics differ")
    return CX323Policy(
        policy_id=CX323_POLICY_ID,
        policy_sha256=_sha256_file(path),
        frequency_estimator_id=str(selection["selected_frequency_estimator"]),
        maximum_step_codes=int(limits["maximum_combined_step_codes"]),
        minimum_code=int(limits["minimum_code"]),
        maximum_code=int(limits["maximum_code"]),
        minimum_cadence_s=int(limits["minimum_applied_cadence_s"]),
        settling_exclusion_s=900,
        maximum_applications=int(limits["maximum_automatic_applications"]),
        maximum_cumulative_movement_codes=int(
            limits["maximum_cumulative_absolute_movement_codes"]
        ),
        setup_code=_CX323_DEFAULT_SETUP_CODE,
    )


@dataclass(frozen=True)
class CX323Debt:
    fll_picocodes: int = 0
    pll_picocodes: int = 0

    @property
    def total_picocodes(self) -> int:
        return self.fll_picocodes + self.pll_picocodes


@dataclass(frozen=True)
class CX323Observation:
    timestamp_s: int
    capture_session: int
    source_first_sequence: int
    source_last_sequence: int
    dac_epoch: int
    applied_code: int
    accumulated_edge_error_counts: int
    tight_state: str
    phase_epoch: int
    relative_phase_cycles: int
    frequency_estimator_id: str = "cx317_selected_600s_nonoverlap_v1"
    phase_valid: bool = True
    authority_valid: bool = True
    settled: bool = True
    cadence_eligible: bool = True
    metadata_qualified: bool = True
    # Exact extended rp2040_timer0 counter.  None is retained only for
    # historical/offline fixtures, where timestamp_s is projected exactly.
    timestamp_ticks: int | None = None


@dataclass(frozen=True)
class CX323Decision:
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


def _cx323_round_ratio(numerator: int, denominator: int) -> int:
    magnitude = abs(numerator)
    result = (2 * magnitude + denominator) // (2 * denominator)
    return result if numerator >= 0 else -result


def cx323_centre_to_picocodes(centre_units: int) -> int:
    """Checked reduced quotient/remainder fixed-point conversion."""

    magnitude = abs(centre_units)
    quotient, remainder = divmod(magnitude, _CX323_DENOMINATOR)
    result = quotient * _CX323_NUMERATOR + _cx323_round_ratio(
        remainder * _CX323_NUMERATOR, _CX323_DENOMINATOR
    )
    return result if centre_units >= 0 else -result


class CX323PhasePriorityController:
    """Selected tagged-debt maintenance controller, without I/O authority."""

    def __init__(
        self,
        policy: CX323Policy,
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
        self.debt = CX323Debt()
        self.persistence_sign = 0
        self.persistence_count = 0
        self.persistence_identity: tuple[int, int, int, int, bool, str] | None = None
        self.last_closing_frontier: int | None = None
        self.request_pending = False
        self._pending_decision: CX323Decision | None = None
        self._pending_decision_timestamp_s: int | None = None
        self._pending_decision_timestamp_ticks: int | None = None
        self.response_pending = False
        self.metadata_hold = False
        self.metadata_requalified = False
        self.requalification_frontier: int | None = None
        self.requalification_window_count = 0
        self._requalification_last_closing_frontier: int | None = None
        self._requalification_identity: tuple[int, int, int, int, bool, str] | None = None
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
            raise ValueError("CX323 setup code outside frozen authority range")
        if dac_epoch <= 0:
            raise ValueError("CX323 setup DAC epoch must be positive")
        self.applied_code = applied_code
        self.dac_epoch = dac_epoch
        self.chatter_origin_code = applied_code

    def _reset(self, *, preserve_debt: bool) -> None:
        if not preserve_debt:
            self.debt = CX323Debt()
        self.persistence_sign = 0
        self.persistence_count = 0
        self.persistence_identity = None
        self.last_closing_frontier = None

    def _fail_static(self, reason: str) -> None:
        self.fail_static_reason = reason
        self.request_pending = False
        self._pending_decision = None
        self._pending_decision_timestamp_s = None
        self._pending_decision_timestamp_ticks = None
        self.response_pending = False

    @staticmethod
    def _centre(observation: CX323Observation) -> tuple[int, int, int]:
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

    def _legacy_deltas(
        self, observation: CX323Observation, *, phase_enabled: bool = True
    ) -> tuple[int, int, bool, bool]:
        phase = (
            max(-36, min(36, -observation.relative_phase_cycles))
            if phase_enabled
            else 0
        )
        frequency = _CX323_GAIN * Fraction(-observation.accumulated_edge_error_counts, 600)
        combined = frequency + _CX323_GAIN * Fraction(phase, 21_600)

        def limited(value: Fraction) -> tuple[int, bool, bool]:
            rounded = _cx323_round_ratio(value.numerator, value.denominator)
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
    def _timestamp_ticks(observation: CX323Observation) -> int:
        return (
            observation.timestamp_s * _CX323_TICKS_PER_SECOND
            if observation.timestamp_ticks is None
            else observation.timestamp_ticks
        )

    def _cadence_status(
        self, observation: CX323Observation
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
            < self.policy.minimum_cadence_s * _CX323_TICKS_PER_SECOND,
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
    ) -> CX323Decision:
        return CX323Decision(
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
        observation: CX323Observation,
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
    ) -> CX323Decision:
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

    def _legacy_request(
        self,
        observation: CX323Observation,
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
    ) -> CX323Decision:
        # Legacy/outside paths are a maintenance boundary, never an implicit
        # continuation of a tagged-debt persistence interval.
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
        self.requalification_frontier = None
        self.requalification_window_count = 0
        self._requalification_last_closing_frontier = None
        self._requalification_identity = None
        self._reset(preserve_debt=True)

    def new_policy_activation(self) -> None:
        """Explicit activation boundary; it never inherits maintenance debt."""

        if self.request_pending or self.response_pending:
            self._fail_static("new_policy_activation_with_outstanding_transaction")
            raise HybridPolicyError(self.fail_static_reason)
        self._reset(preserve_debt=False)

    def requalify_metadata(self, evidence_frontier: int) -> None:
        if not self.metadata_hold:
            raise HybridPolicyError("metadata requalification without hold")
        if evidence_frontier <= 0:
            raise ValueError("metadata requalification frontier must be positive")
        # Fresh serial metadata is necessary but not sufficient to restore
        # actuation.  D14/D8 must provide two complete causally later windows
        # while the last confirmed code and debt remain frozen.
        self.metadata_requalified = True
        self.requalification_frontier = evidence_frontier
        self.requalification_window_count = 0
        self._requalification_last_closing_frontier = None
        self._requalification_identity = None
        self._reset(preserve_debt=True)

    def _advance_metadata_requalification(
        self,
        observation: CX323Observation,
        identity: tuple[int, int, int, int, bool, str],
    ) -> str | None:
        """Advance the independent two-window D14/D8 requalification gate."""

        if not self.metadata_hold or not self.metadata_requalified:
            return None
        if self.requalification_frontier is None:
            self._fail_static("metadata_requalification_frontier_missing")
            return self.fail_static_reason
        if observation.source_first_sequence < self.requalification_frontier:
            return "metadata_requalification_frontier_hold"
        previous = self._requalification_last_closing_frontier
        if previous is not None and observation.source_first_sequence < previous:
            return "metadata_requalification_overlap_hold"
        contiguous = (
            previous is not None
            and observation.source_first_sequence == previous
            and self._requalification_identity == identity
        )
        self.requalification_window_count = (
            min(2, self.requalification_window_count + 1) if contiguous else 1
        )
        self._requalification_last_closing_frontier = observation.source_last_sequence
        self._requalification_identity = identity
        if self.requalification_window_count < 2:
            return "metadata_requalification_window_hold"
        self.metadata_hold = False
        self.metadata_requalified = False
        self.requalification_frontier = None
        self._requalification_last_closing_frontier = None
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

    def decide(self, observation: CX323Observation) -> CX323Decision:
        self.decision_sequence += 1
        self._current_timestamp_ticks = self._timestamp_ticks(observation)
        if self.fail_static_reason:
            return self._decision(self.fail_static_reason)
        if (
            observation.timestamp_s
            != self._current_timestamp_ticks // _CX323_TICKS_PER_SECOND
        ):
            self._fail_static("observation_timestamp_domain_mismatch")
            return self._decision(self.fail_static_reason)
        if observation.source_last_sequence <= observation.source_first_sequence:
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
        identity = (observation.capture_session, observation.applied_code,
                    observation.dac_epoch, observation.phase_epoch,
                    observation.phase_valid, observation.frequency_estimator_id)
        if self.persistence_identity is not None and identity != self.persistence_identity:
            old = self.persistence_identity
            if observation.capture_session != old[0] or observation.frequency_estimator_id != old[5]:
                self._reset(preserve_debt=False)
            elif observation.applied_code != old[1] or observation.dac_epoch != old[2]:
                self._fail_static("unknown_or_contradictory_application_or_DAC_epoch")
                return self._decision(self.fail_static_reason)
            elif observation.phase_epoch != old[3] or observation.phase_valid != old[4]:
                self.debt = CX323Debt(self.debt.fll_picocodes, 0)
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
            "metadata_requalification_frontier_hold",
            "metadata_requalification_overlap_hold",
        }:
            return self._decision(metadata_requalification_hold)
        if not observation.phase_valid:
            self.debt = CX323Debt(self.debt.fll_picocodes, 0)
            self._reset(preserve_debt=True)
            combined_legacy, frequency_legacy, step_limited, range_clamped = (
                self._legacy_deltas(
                observation, phase_enabled=False
                )
            )
            projection = {
                "counterfactual_frequency_only_delta_codes": frequency_legacy,
                "phase_materially_influenced": False,
                "step_limited": step_limited,
                "range_clamped": range_clamped,
            }
            if metadata_requalification_hold:
                return self._decision(metadata_requalification_hold, **projection)
            return self._legacy_request(
                observation,
                delta=combined_legacy,
                reason="phase_degraded_frequency_only_request_ready",
                reset_debt=False,
                enforce_phase_direction=False,
                **projection,
            )

        # The CX322-compatible paths are complete control paths, not merely
        # labels.  They deliberately precede the tagged-debt frontier and
        # persistence state machine.
        (
            combined_legacy,
            frequency_legacy,
            step_limited,
            range_clamped,
        ) = self._legacy_deltas(observation)
        phase_material = combined_legacy != frequency_legacy
        projection = {
            "counterfactual_frequency_only_delta_codes": frequency_legacy,
            "phase_materially_influenced": phase_material,
            "step_limited": step_limited,
            "range_clamped": range_clamped,
        }
        phase_term = max(-36, min(36, -observation.relative_phase_cycles))
        if observation.tight_state != "TIGHT_INSIDE":
            if metadata_requalification_hold:
                self._reset(preserve_debt=False)
                return self._decision(metadata_requalification_hold, **projection)
            return self._legacy_request(
                observation,
                delta=combined_legacy,
                reason="outside_tight_legacy_request_ready",
                phase_term=phase_term,
                **projection,
            )
        if phase_material:
            if metadata_requalification_hold:
                self._reset(preserve_debt=False)
                return self._decision(metadata_requalification_hold, **projection)
            return self._legacy_request(
                observation,
                delta=combined_legacy,
                reason="phase_material_legacy_request_ready",
                phase_term=phase_term,
                **projection,
            )
        if self.last_closing_frontier is not None:
            if observation.source_first_sequence < self.last_closing_frontier:
                return self._decision("source_overlap_hold", **projection)
            if observation.source_first_sequence > self.last_closing_frontier:
                centre, lower, upper = self._centre(observation)
                sign = self._sign(lower, upper)
                if not sign or (self.persistence_count and sign != self.persistence_sign):
                    self._reset(preserve_debt=False)
                self.persistence_count = 1
                self.persistence_sign = sign
                self.persistence_identity = identity
                self.last_closing_frontier = observation.source_last_sequence
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
        self.last_closing_frontier = observation.source_last_sequence
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
        raw = cx323_centre_to_picocodes(centre)
        fll = cx323_centre_to_picocodes(-36 * observation.accumulated_edge_error_counts)
        pll = raw - fll
        total = raw + self.debt.total_picocodes
        rounded = _cx323_round_ratio(total, _CX323_PICO)
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

    def confirm_application(self, decision: CX323Decision, *, applied_code: int,
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
            residual = max(-_CX323_DEBT_LIMIT, min(_CX323_DEBT_LIMIT,
                total - decision.requested_delta_codes * _CX323_PICO))
            fll_weight = abs(decision.raw_fll_picocodes + self.debt.fll_picocodes)
            pll_weight = abs(decision.raw_pll_picocodes + self.debt.pll_picocodes)
            if fll_weight + pll_weight:
                fll_debt = _cx323_round_ratio(residual * fll_weight, fll_weight + pll_weight)
                self.debt = CX323Debt(fll_debt, residual - fll_debt)
            else:
                self.debt = CX323Debt(residual, 0)
        else:
            # A legacy request begins a new maintenance epoch.  It must not
            # manufacture a tagged residual from maintenance-only arithmetic.
            residual = 0
            self.debt = CX323Debt()
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
