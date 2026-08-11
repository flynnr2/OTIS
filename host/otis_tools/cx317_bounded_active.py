"""Bounded CX317 active-control authority, transaction and response model.

This is the deterministic host reference for the Stage 3 firmware state
machine.  It never opens a serial device and never writes a DAC.  The live
executor must provide exact run/build bindings and may only serialize requests
that this state machine has made actionable.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from enum import Enum
from hashlib import sha256
from pathlib import Path
import json
import math
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY = REPO_ROOT / "profiles/discipline/cx317_bounded_active_v2.json"
TOOL_VERSION = "cx317_bounded_active_reference_v2"
CURRENT_POLICY_ID = "CX317_BOUNDED_ACTIVE_I_ONLY_V2"


class ActiveError(RuntimeError):
    """A fail-closed authority or transaction violation."""


class ActiveState(str, Enum):
    DISARMED = "disarmed"
    ARMED = "armed"
    REQUEST_PENDING = "request_pending"
    ACCEPTED_AWAITING_APPLICATION = "accepted_awaiting_application"
    AWAITING_RESPONSE = "awaiting_response"
    OUT_OF_MODEL_HOLD = "out_of_model_hold"
    FAULT = "fault"
    ABORTED = "aborted"


class ResponseClass(str, Enum):
    HEALTHY_DETECTED = "healthy_detected"
    HEALTHY_INDETERMINATE = "healthy_indeterminate_near_resolution"
    INSIDE_DEADBAND = "inside_deadband"
    LIMIT_REACHED = "limit_reached"
    WRONG_SIGN = "wrong_sign"
    EXCESS_RESPONSE = "excess_response"
    GROWING_ERROR = "growing_error"
    MEASUREMENT_OR_ACTUATOR_FAULT = "measurement_or_actuator_fault"


def _file_hash(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


@dataclass(frozen=True)
class CampaignLimits:
    name: str
    firmware_profile: str
    run_binding_tag: int
    start_code: int
    maximum_corrections: int
    maximum_cumulative_movement_codes: int


@dataclass(frozen=True)
class ActivePolicy:
    policy_id: str
    policy_hash: str
    estimator_hash: str
    model_hash: str
    numerical_policy_hash: str
    response_hash: str
    response_policy_path: Path
    minimum_code: int
    maximum_code: int
    maximum_step_codes: int
    minimum_cadence_s: int
    settling_exclusion_s: int
    fresh_support_s: int
    full_history_reset_s: int
    startup_warmup_s: int
    temperature_min_c: float
    temperature_max_c: float
    arm_lifetime_s: int
    capture_lease_age_s: int
    campaigns: dict[str, CampaignLimits]


def load_policy(path: Path = DEFAULT_POLICY) -> ActivePolicy:
    value = _read_object(path)
    if value.get("schema_version") != 1:
        raise ValueError("active policy schema_version must be 1")
    policy_id = value.get("policy_id")
    if policy_id != CURRENT_POLICY_ID:
        raise ValueError("unsupported active policy identity")
    bindings = value.get("bindings")
    parameters = value.get("parameters")
    campaigns_value = value.get("campaigns")
    authority = value.get("authority")
    transaction = value.get("transaction")
    if not all(
        isinstance(item, dict)
        for item in (bindings, parameters, campaigns_value, authority, transaction)
    ):
        raise ValueError("active policy sections must be objects")

    for key in (
        "automatic_retry",
        "automatic_restore",
    ):
        if parameters.get(key) is not False:
            raise ValueError(f"active policy {key} must be false")
    required_authority = {
        "default_profiles_actuation_enabled": False,
        "dedicated_profiles_actuation_enabled": True,
        "arming_required": True,
        "arming_consumed_by_one_request": True,
        "actionable_only_during_request_handoff": True,
        "actionable_cleared_on_acceptance_or_fault": True,
        "reboot_or_session_change_clears_arming": True,
        "exact_run_build_profile_estimator_model_policy_response_bindings_required": True,
        "gnss_metadata_and_identity_required": True,
        "raw_reference_and_count_required": True,
        "confirmed_applied_code_required": True,
        "capture_owner_lease_and_abort_health_required": True,
    }
    required_authority.update(
        {
            "model_applicability_required_for_new_request": True,
            "temperature_context_required_for_measurement": False,
            "temperature_context_required_for_control": False,
            "measurement_validity_and_control_eligibility_separate": True,
            "out_of_model_is_fail_static_hold": True,
        }
    )
    if {key: authority.get(key) for key in required_authority} != required_authority:
        raise ValueError("active authority invariants differ")
    if transaction.get("controller_type") != "incremental_I_only_frequency_control":
        raise ValueError("active controller is not incremental I-only")
    if transaction.get("request_is_not_applied_code") is not True:
        raise ValueError("active request/application separation differs")

    binding_paths = {
        "plant_model_sha256": bindings["plant_model_path"],
        "selected_estimator_sha256": bindings["selected_estimator_path"],
        "numerical_preview_policy_sha256": bindings["numerical_preview_policy_path"],
        "response_policy_sha256": bindings["response_policy_path"],
    }
    for hash_key, relative in binding_paths.items():
        if _file_hash(REPO_ROOT / str(relative)) != bindings.get(hash_key):
            raise ValueError(f"active binding hash differs for {relative}")
    if bindings.get("measurement_backend") != "OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO":
        raise ValueError("active measurement backend differs")
    if bindings.get("snapshot_backend") != "pio_wait_cumulative_snapshot_dma_v1":
        raise ValueError("active snapshot backend differs")

    campaigns: dict[str, CampaignLimits] = {}
    for name in ("A", "B"):
        item = campaigns_value.get(name)
        if not isinstance(item, dict):
            raise ValueError(f"campaign {name} binding is missing")
        campaigns[name] = CampaignLimits(
            name=name,
            firmware_profile=str(item["firmware_profile"]),
            run_binding_tag=int(item["run_binding_tag"]),
            start_code=int(item["start_code"]),
            maximum_corrections=int(item["maximum_corrections"]),
            maximum_cumulative_movement_codes=int(
                item["maximum_cumulative_movement_codes"]
            ),
        )
    if (
        campaigns["A"].start_code != 0xA950
        or campaigns["A"].maximum_corrections != 16
        or campaigns["A"].maximum_cumulative_movement_codes != 336
        or campaigns["B"].start_code != 0xA800
        or campaigns["B"].maximum_corrections != 8
        or campaigns["B"].maximum_cumulative_movement_codes != 168
    ):
        raise ValueError("immutable campaign limits differ")

    integer_fields = {
        "maximum_update_codes": 21,
        "dac_min_code": 0xA800,
        "dac_max_code": 0xAB00,
        "minimum_applied_correction_cadence_s": 1800,
        "settling_exclusion_s": 900,
        "fresh_support_after_settling_s": 600,
        "full_history_reset_s": 1500,
        "startup_warmup_s": 1800,
        "arming_maximum_lifetime_s": 120,
        "capture_lease_maximum_age_s": 30,
    }
    if {key: int(parameters.get(key, -1)) for key in integer_fields} != integer_fields:
        raise ValueError("immutable active numerical limits differ")
    if integer_fields["full_history_reset_s"] != (
        integer_fields["settling_exclusion_s"]
        + integer_fields["fresh_support_after_settling_s"]
    ):
        raise ValueError("active history reset timing differs")

    return ActivePolicy(
        policy_id=str(value["policy_id"]),
        policy_hash=_file_hash(path),
        estimator_hash=str(bindings["selected_estimator_sha256"]),
        model_hash=str(bindings["plant_model_sha256"]),
        numerical_policy_hash=str(bindings["numerical_preview_policy_sha256"]),
        response_hash=str(bindings["response_policy_sha256"]),
        response_policy_path=REPO_ROOT / str(bindings["response_policy_path"]),
        minimum_code=integer_fields["dac_min_code"],
        maximum_code=integer_fields["dac_max_code"],
        maximum_step_codes=integer_fields["maximum_update_codes"],
        minimum_cadence_s=integer_fields["minimum_applied_correction_cadence_s"],
        settling_exclusion_s=integer_fields["settling_exclusion_s"],
        fresh_support_s=integer_fields["fresh_support_after_settling_s"],
        full_history_reset_s=integer_fields["full_history_reset_s"],
        startup_warmup_s=integer_fields["startup_warmup_s"],
        temperature_min_c=float(parameters["temperature_min_c"]),
        temperature_max_c=float(parameters["temperature_max_c"]),
        arm_lifetime_s=integer_fields["arming_maximum_lifetime_s"],
        capture_lease_age_s=integer_fields["capture_lease_maximum_age_s"],
        campaigns=campaigns,
    )


@dataclass(frozen=True)
class Eligibility:
    run_identity_matches: bool = True
    build_identity_matches: bool = True
    profile_identity_matches: bool = True
    estimator_identity_matches: bool = True
    model_identity_matches: bool = True
    policy_identity_matches: bool = True
    response_identity_matches: bool = True
    session_continuous: bool = True
    gnss_metadata_valid: bool = True
    gnss_identity_stable: bool = True
    gnss_3d_evidence: bool = True
    raw_pps_valid: bool = True
    count_valid: bool = True
    estimator_valid: bool = True
    model_applicable: bool = True
    temperature_valid: bool = True
    applied_code_confirmed: bool = True
    capture_owner_live: bool = True
    abort_path_live: bool = True
    transaction_evidence_available: bool = True

    def reasons(self) -> tuple[str, ...]:
        return tuple(
            key
            for key, value in asdict(self).items()
            if value is not True
        )

    def arm_reasons(self) -> tuple[str, ...]:
        """Identity/transport preconditions needed to accept a short-lived arm."""
        excluded = {"estimator_valid", "model_applicable", "temperature_valid"}
        return tuple(
            key
            for key, value in asdict(self).items()
            if key not in excluded and value is not True
        )

    def control_reasons(self) -> tuple[str, ...]:
        """Preconditions needed to turn a fresh estimate into a request."""
        return tuple(
            key
            for key, value in asdict(self).items()
            if key != "temperature_valid" and value is not True
        )

    def response_measurement_reasons(self) -> tuple[str, ...]:
        """Evidence needed to classify a response, independent of model context."""
        excluded = {"model_applicable", "temperature_valid"}
        return tuple(
            key
            for key, value in asdict(self).items()
            if key not in excluded and value is not True
        )


@dataclass(frozen=True)
class ArmSpec:
    run_binding_tag: int
    build_hash: str
    profile_id: str
    estimator_hash: str
    model_hash: str
    policy_hash: str
    response_hash: str
    numerical_policy_hash: str
    session_id: int
    start_code: int
    minimum_code: int
    maximum_code: int
    maximum_step_codes: int
    correction_limit: int
    cumulative_limit_codes: int
    authorization_sequence: int
    nonce: int
    expires_s: int


@dataclass(frozen=True)
class ControlDecision:
    decision_sequence: int
    source_first_sequence: int
    source_last_sequence: int
    timestamp_s: int
    current_applied_code: int
    requested_delta_codes: int
    requested_code: int
    pre_error_hz: float


@dataclass(frozen=True)
class ActionableRequest:
    request_sequence: int
    authorization_sequence: int
    nonce: int
    session_id: int
    decision_sequence: int
    source_first_sequence: int
    source_last_sequence: int
    timestamp_s: int
    current_applied_code: int
    requested_delta_codes: int
    requested_code: int
    pre_error_hz: float
    correction_ordinal: int
    cumulative_after_codes: int
    actionable: bool = True


@dataclass(frozen=True)
class AcceptedRequest:
    request_sequence: int
    authorization_sequence: int
    nonce: int
    accepted_code: int
    accepted_timestamp_s: int
    actionable: bool = False


@dataclass(frozen=True)
class AppliedAcknowledgement:
    request_sequence: int
    authorization_sequence: int
    nonce: int
    requested_code: int
    accepted_code: int
    applied_code: int
    application_sequence: int
    application_timestamp_s: int
    i2c_ok: bool
    clamped: bool = False
    ambiguous: bool = False


@dataclass(frozen=True)
class ResponseResult:
    classification: ResponseClass
    reason: str
    observed_response_hz: float | None
    cumulative_response_hz: float | None
    consecutive_indeterminate: int


@dataclass
class StepCapsule:
    request: ActionableRequest
    accepted: AcceptedRequest | None = None
    applied: AppliedAcknowledgement | None = None
    dac_epoch: int | None = None
    response: ResponseResult | None = None


class ResponseClassifier:
    def __init__(
        self,
        response_path: Path | None = None,
        *,
        legacy_response_deadband_enabled: bool = True,
    ) -> None:
        response_path = response_path or (
            REPO_ROOT / "profiles/discipline/cx317_response_classification_v2.json"
        )
        value = _read_object(response_path)
        if value.get("policy_id") not in {
            "CX317_BOUNDED_RESPONSE_CLASSIFICATION_V1",
            "CX317_BOUNDED_RESPONSE_CLASSIFICATION_V2",
        }:
            raise ValueError("unsupported response policy")
        p = value["parameters"]
        self.gain_min = float(p["gain_min_hz_per_code"])
        self.gain_max = float(p["gain_max_hz_per_code"])
        self.floor = float(p["empirical_detection_floor_hz"])
        self.deadband = float(p["error_deadband_hz"])
        self.wrong_sign_minimum = float(p["wrong_sign_minimum_hz"])
        self.growth_margin = float(p["growing_error_margin_hz"])
        self.excess_margin = float(p["excess_response_additive_margin_hz"])
        self.maximum_indeterminate = int(p["maximum_consecutive_indeterminate"])
        self.legacy_response_deadband_enabled = legacy_response_deadband_enabled
        self.baseline_error_hz: float | None = None
        self.cumulative_delta_codes = 0
        self.consecutive_indeterminate = 0

    def classify(
        self,
        *,
        pre_error_hz: float,
        post_error_hz: float,
        applied_delta_codes: int,
        current_code: int,
        minimum_code: int,
        maximum_code: int,
        evidence_healthy: bool = True,
    ) -> ResponseResult:
        if (
            not evidence_healthy
            or applied_delta_codes == 0
            or not math.isfinite(pre_error_hz)
            or not math.isfinite(post_error_hz)
        ):
            self.consecutive_indeterminate = 0
            return ResponseResult(
                ResponseClass.MEASUREMENT_OR_ACTUATOR_FAULT,
                "invalid_response_evidence",
                None,
                None,
                self.consecutive_indeterminate,
            )
        if self.baseline_error_hz is None:
            self.baseline_error_hz = pre_error_hz
        self.cumulative_delta_codes += applied_delta_codes
        observed = post_error_hz - pre_error_hz
        cumulative = post_error_hz - self.baseline_error_hz

        if (
            self.legacy_response_deadband_enabled
            and abs(post_error_hz) <= self.deadband
        ):
            self.consecutive_indeterminate = 0
            return ResponseResult(
                ResponseClass.INSIDE_DEADBAND,
                "post_error_inside_frozen_deadband",
                observed,
                cumulative,
                0,
            )
        if self.legacy_response_deadband_enabled and (
            (current_code <= minimum_code and post_error_hz > self.deadband)
            or (current_code >= maximum_code and post_error_hz < -self.deadband)
        ):
            self.consecutive_indeterminate = 0
            return ResponseResult(
                ResponseClass.LIMIT_REACHED,
                "hard_code_endpoint_blocks_required_direction",
                observed,
                cumulative,
                0,
            )
        if (
            observed * applied_delta_codes < 0.0
            and abs(observed) >= self.wrong_sign_minimum
        ) or (
            cumulative * self.cumulative_delta_codes < 0.0
            and abs(cumulative) >= self.wrong_sign_minimum
        ):
            self.consecutive_indeterminate = 0
            return ResponseResult(
                ResponseClass.WRONG_SIGN,
                "observed_response_opposes_positive_plant_gain",
                observed,
                cumulative,
                0,
            )
        if abs(post_error_hz) > abs(pre_error_hz) + self.growth_margin:
            self.consecutive_indeterminate = 0
            return ResponseResult(
                ResponseClass.GROWING_ERROR,
                "absolute_error_grew_beyond_frozen_margin",
                observed,
                cumulative,
                0,
            )
        maximum_response = abs(applied_delta_codes) * self.gain_max + self.excess_margin
        if abs(observed) > maximum_response:
            self.consecutive_indeterminate = 0
            return ResponseResult(
                ResponseClass.EXCESS_RESPONSE,
                "response_exceeds_gain_envelope_plus_empirical_margin",
                observed,
                cumulative,
                0,
            )
        if (
            observed * applied_delta_codes > 0.0
            and abs(observed) >= self.floor
        ) or (
            cumulative * self.cumulative_delta_codes > 0.0
            and abs(cumulative) >= self.floor
        ):
            self.consecutive_indeterminate = 0
            return ResponseResult(
                ResponseClass.HEALTHY_DETECTED,
                "response_detected_with_commanded_sign",
                observed,
                cumulative,
                0,
            )

        self.consecutive_indeterminate += 1
        cumulative_expected = abs(self.cumulative_delta_codes) * self.gain_min
        if (
            self.consecutive_indeterminate > self.maximum_indeterminate
            and cumulative_expected >= 2.0 * self.floor
        ):
            return ResponseResult(
                ResponseClass.MEASUREMENT_OR_ACTUATOR_FAULT,
                "persistent_response_absence_after_cumulative_expected_detection",
                observed,
                cumulative,
                self.consecutive_indeterminate,
            )
        return ResponseResult(
            ResponseClass.HEALTHY_INDETERMINATE,
            "healthy_evidence_below_empirical_detection_floor",
            observed,
            cumulative,
            self.consecutive_indeterminate,
        )


class ActiveTransactionEngine:
    def __init__(
        self,
        policy: ActivePolicy,
        campaign: str,
        *,
        build_hash: str,
        session_id: int,
        initial_applied_code: int,
    ) -> None:
        if campaign not in policy.campaigns:
            raise ValueError(f"unknown campaign {campaign!r}")
        limits = policy.campaigns[campaign]
        if initial_applied_code != limits.start_code:
            raise ValueError("initial applied code differs from campaign binding")
        if not build_hash:
            raise ValueError("exact build hash is required")
        self.policy = policy
        self.limits = limits
        self.build_hash = build_hash
        self.session_id = session_id
        self.state = ActiveState.DISARMED
        self.reason = "initialized_disarmed"
        self.applied_code = initial_applied_code
        self.correction_count = 0
        self.cumulative_movement_codes = 0
        self.dac_epoch = 0
        self.last_application_s: int | None = None
        self.last_decision_sequence = 0
        self.last_request_sequence = 0
        self.last_authorization_sequence = 0
        self.arm_spec: ArmSpec | None = None
        self.pending: StepCapsule | None = None
        self.capsules: list[StepCapsule] = []
        self.response_classifier = ResponseClassifier(policy.response_policy_path)

    @staticmethod
    def _require_health(reasons: tuple[str, ...]) -> None:
        if reasons:
            raise ActiveError("eligibility failed: " + ",".join(reasons))

    def _fault(self, reason: str) -> None:
        self.state = ActiveState.FAULT
        self.reason = reason
        self.arm_spec = None
        if self.pending is not None and self.pending.request.actionable:
            self.pending.request = ActionableRequest(
                **{
                    **asdict(self.pending.request),
                    "actionable": False,
                }
            )

    def expected_arm_spec(
        self,
        *,
        authorization_sequence: int,
        nonce: int,
        expires_s: int,
    ) -> ArmSpec:
        return ArmSpec(
            run_binding_tag=self.limits.run_binding_tag,
            build_hash=self.build_hash,
            profile_id=self.limits.firmware_profile,
            estimator_hash=self.policy.estimator_hash,
            model_hash=self.policy.model_hash,
            policy_hash=self.policy.policy_hash,
            response_hash=self.policy.response_hash,
            numerical_policy_hash=self.policy.numerical_policy_hash,
            session_id=self.session_id,
            start_code=self.limits.start_code,
            minimum_code=self.policy.minimum_code,
            maximum_code=self.policy.maximum_code,
            maximum_step_codes=self.policy.maximum_step_codes,
            correction_limit=self.limits.maximum_corrections,
            cumulative_limit_codes=self.limits.maximum_cumulative_movement_codes,
            authorization_sequence=authorization_sequence,
            nonce=nonce,
            expires_s=expires_s,
        )

    def arm(self, spec: ArmSpec, health: Eligibility, now_s: int) -> None:
        if self.state in {ActiveState.FAULT, ActiveState.ABORTED}:
            raise ActiveError(f"cannot arm latched state {self.state.value}")
        if self.state is ActiveState.OUT_OF_MODEL_HOLD:
            reasons = health.control_reasons()
            if reasons:
                raise ActiveError(
                    "out-of-model hold requires applicable model and fresh support: "
                    + ",".join(reasons)
                )
            self.state = ActiveState.DISARMED
            self.reason = "out_of_model_hold_requalified"
        if self.state is not ActiveState.DISARMED or self.pending is not None:
            self._fault("arm_while_not_disarmed")
            raise ActiveError(self.reason)
        try:
            self._require_health(health.arm_reasons())
        except ActiveError:
            self._fault("arm_eligibility_failed")
            raise
        expected = self.expected_arm_spec(
            authorization_sequence=spec.authorization_sequence,
            nonce=spec.nonce,
            expires_s=spec.expires_s,
        )
        if spec != expected:
            self._fault("arm_binding_mismatch")
            raise ActiveError(self.reason)
        if spec.authorization_sequence <= self.last_authorization_sequence:
            self._fault("stale_or_duplicate_authorization_sequence")
            raise ActiveError(self.reason)
        if spec.nonce == 0:
            self._fault("zero_authorization_nonce")
            raise ActiveError(self.reason)
        if spec.expires_s <= now_s or spec.expires_s - now_s > self.policy.arm_lifetime_s:
            self._fault("arming_expiry_outside_short_lived_bound")
            raise ActiveError(self.reason)
        if self.correction_count >= self.limits.maximum_corrections:
            self._fault("correction_count_limit_reached")
            raise ActiveError(self.reason)
        self.arm_spec = spec
        self.state = ActiveState.ARMED
        self.reason = "exact_binding_armed"

    def request(
        self,
        decision: ControlDecision,
        health: Eligibility,
        now_s: int,
    ) -> ActionableRequest:
        if self.state is not ActiveState.ARMED or self.arm_spec is None:
            self._fault("request_without_current_arm")
            raise ActiveError(self.reason)
        spec = self.arm_spec
        self.arm_spec = None
        try:
            self._require_health(health.control_reasons())
        except ActiveError:
            self._fault("request_eligibility_failed")
            raise
        if now_s > spec.expires_s:
            self._fault("authorization_expired")
            raise ActiveError(self.reason)
        if decision.timestamp_s != now_s:
            self._fault("decision_timestamp_mismatch")
            raise ActiveError(self.reason)
        if decision.decision_sequence <= self.last_decision_sequence:
            self._fault("duplicate_stale_or_reordered_decision")
            raise ActiveError(self.reason)
        if (
            decision.source_first_sequence <= 0
            or decision.source_last_sequence < decision.source_first_sequence
        ):
            self._fault("invalid_source_observation_references")
            raise ActiveError(self.reason)
        if decision.current_applied_code != self.applied_code:
            self._fault("decision_applied_code_mismatch")
            raise ActiveError(self.reason)
        delta = decision.requested_delta_codes
        if delta == 0:
            self.state = ActiveState.DISARMED
            self.reason = "zero_delta_disarmed_without_request"
            raise ActiveError(self.reason)
        if abs(delta) > self.policy.maximum_step_codes:
            self._fault("step_limit_exceeded")
            raise ActiveError(self.reason)
        if decision.requested_code != self.applied_code + delta:
            self._fault("requested_code_delta_mismatch")
            raise ActiveError(self.reason)
        if not self.policy.minimum_code <= decision.requested_code <= self.policy.maximum_code:
            self._fault("requested_code_outside_hard_range")
            raise ActiveError(self.reason)
        if self.correction_count + 1 > self.limits.maximum_corrections:
            self._fault("correction_count_limit_exceeded")
            raise ActiveError(self.reason)
        cumulative_after = self.cumulative_movement_codes + abs(delta)
        if cumulative_after > self.limits.maximum_cumulative_movement_codes:
            self._fault("cumulative_movement_limit_exceeded")
            raise ActiveError(self.reason)
        if (
            self.last_application_s is not None
            and now_s - self.last_application_s < self.policy.minimum_cadence_s
        ):
            self._fault("minimum_applied_correction_cadence_violated")
            raise ActiveError(self.reason)
        self.last_request_sequence += 1
        request = ActionableRequest(
            request_sequence=self.last_request_sequence,
            authorization_sequence=spec.authorization_sequence,
            nonce=spec.nonce,
            session_id=self.session_id,
            decision_sequence=decision.decision_sequence,
            source_first_sequence=decision.source_first_sequence,
            source_last_sequence=decision.source_last_sequence,
            timestamp_s=now_s,
            current_applied_code=self.applied_code,
            requested_delta_codes=delta,
            requested_code=decision.requested_code,
            pre_error_hz=decision.pre_error_hz,
            correction_ordinal=self.correction_count + 1,
            cumulative_after_codes=cumulative_after,
        )
        self.last_decision_sequence = decision.decision_sequence
        self.last_authorization_sequence = spec.authorization_sequence
        self.pending = StepCapsule(request=request)
        self.state = ActiveState.REQUEST_PENDING
        self.reason = "one_actionable_request_created"
        return request

    def accept(self, request: ActionableRequest, now_s: int) -> AcceptedRequest:
        if self.state is not ActiveState.REQUEST_PENDING or self.pending is None:
            self._fault("accept_without_pending_request")
            raise ActiveError(self.reason)
        if request != self.pending.request or not request.actionable:
            self._fault("accepted_request_identity_mismatch")
            raise ActiveError(self.reason)
        accepted = AcceptedRequest(
            request_sequence=request.request_sequence,
            authorization_sequence=request.authorization_sequence,
            nonce=request.nonce,
            accepted_code=request.requested_code,
            accepted_timestamp_s=now_s,
        )
        self.pending.request = ActionableRequest(
            **{**asdict(request), "actionable": False}
        )
        self.pending.accepted = accepted
        self.state = ActiveState.ACCEPTED_AWAITING_APPLICATION
        self.reason = "request_consumed_actionable_cleared"
        return accepted

    def acknowledge_application(self, acknowledgement: AppliedAcknowledgement) -> None:
        if (
            self.state is not ActiveState.ACCEPTED_AWAITING_APPLICATION
            or self.pending is None
            or self.pending.accepted is None
        ):
            self._fault("application_ack_without_acceptance")
            raise ActiveError(self.reason)
        request = self.pending.request
        accepted = self.pending.accepted
        identity = (
            acknowledgement.request_sequence == request.request_sequence
            and acknowledgement.authorization_sequence == request.authorization_sequence
            and acknowledgement.nonce == request.nonce
            and acknowledgement.requested_code == request.requested_code
            and acknowledgement.accepted_code == accepted.accepted_code
        )
        outcome = (
            acknowledgement.i2c_ok
            and not acknowledgement.clamped
            and not acknowledgement.ambiguous
            and acknowledgement.applied_code == request.requested_code
            and acknowledgement.application_sequence == self.correction_count + 1
        )
        if not identity or not outcome:
            self.pending.applied = acknowledgement
            self.capsules.append(self.pending)
            self._fault("application_acknowledgement_mismatch_or_failure")
            raise ActiveError(self.reason)
        self.applied_code = acknowledgement.applied_code
        self.correction_count += 1
        self.cumulative_movement_codes = request.cumulative_after_codes
        self.last_application_s = acknowledgement.application_timestamp_s
        self.dac_epoch += 1
        self.pending.applied = acknowledgement
        self.pending.dac_epoch = self.dac_epoch
        self.state = ActiveState.AWAITING_RESPONSE
        self.reason = "applied_history_reset_response_required"

    def record_response(
        self,
        *,
        post_error_hz: float,
        evidence_healthy: bool | None = None,
        measurement_healthy: bool | None = None,
        control_eligible_after_response: bool = True,
    ) -> ResponseResult:
        if (
            self.state is not ActiveState.AWAITING_RESPONSE
            or self.pending is None
            or self.pending.applied is None
        ):
            self._fault("response_without_applied_transaction")
            raise ActiveError(self.reason)
        request = self.pending.request
        if measurement_healthy is None:
            measurement_healthy = (
                True if evidence_healthy is None else evidence_healthy
            )
        elif evidence_healthy is not None and evidence_healthy != measurement_healthy:
            raise ValueError("conflicting response evidence flags")
        result = self.response_classifier.classify(
            pre_error_hz=request.pre_error_hz,
            post_error_hz=post_error_hz,
            applied_delta_codes=request.requested_delta_codes,
            current_code=self.applied_code,
            minimum_code=self.policy.minimum_code,
            maximum_code=self.policy.maximum_code,
            evidence_healthy=measurement_healthy,
        )
        self.pending.response = result
        self.capsules.append(self.pending)
        self.pending = None
        if result.classification in {
            ResponseClass.WRONG_SIGN,
            ResponseClass.EXCESS_RESPONSE,
            ResponseClass.GROWING_ERROR,
            ResponseClass.MEASUREMENT_OR_ACTUATOR_FAULT,
        }:
            self._fault("response_stop:" + result.classification.value)
        elif not control_eligible_after_response:
            self.state = ActiveState.OUT_OF_MODEL_HOLD
            self.reason = "response_valid_out_of_model_hold"
            self.arm_spec = None
        else:
            self.state = ActiveState.DISARMED
            self.reason = "response_accepted_new_arm_required"
        return result

    def transact_decision(
        self,
        decision: ControlDecision,
        health: Eligibility,
        now_s: int,
    ) -> tuple[ActionableRequest, AcceptedRequest]:
        request = self.request(decision, health, now_s)
        return request, self.accept(request, now_s)

    def abort(self, reason: str = "operator_abort") -> None:
        self.state = ActiveState.ABORTED
        self.reason = reason
        self.arm_spec = None
        self.pending = None

    def note_application_timeout(self) -> None:
        """Latch a missing actuator acknowledgement without retry or restore."""
        if self.state is not ActiveState.ACCEPTED_AWAITING_APPLICATION:
            self._fault("application_timeout_without_acceptance")
        else:
            self._fault("application_acknowledgement_timeout")

    def note_session_change(self, new_session_id: int) -> None:
        if new_session_id != self.session_id:
            self._fault("session_change_clears_arming")

    def status(self) -> dict[str, Any]:
        return {
            "tool_version": TOOL_VERSION,
            "state": self.state.value,
            "reason": self.reason,
            "applied_code": self.applied_code,
            "correction_count": self.correction_count,
            "correction_limit": self.limits.maximum_corrections,
            "cumulative_movement_codes": self.cumulative_movement_codes,
            "cumulative_limit_codes": self.limits.maximum_cumulative_movement_codes,
            "dac_epoch": self.dac_epoch,
            "armed": self.arm_spec is not None,
            "outstanding_request": self.pending is not None,
            "actionable": bool(
                self.pending is not None and self.pending.request.actionable
            ),
            "automatic_restore": False,
            "automatic_retry": False,
        }
