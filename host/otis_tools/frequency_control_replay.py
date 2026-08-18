"""Deterministic replay for the deployed PPS-gated frequency controller."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
import json
import math
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_POLICY = REPO_ROOT / "profiles/discipline/cx317_pps_gated_i_only_preview_v2.json"
CURRENT_REPLAY_POLICY = (
    REPO_ROOT / "profiles/discipline/current_frequency_control_replay_v1.json"
)
TOOL_VERSION = "frequency_control_replay_v2"
PROVENANCE_FIELDS = (
    "parameter_and_units",
    "acceptance_rejection_threshold",
    "disposition",
    "source_document_and_location",
    "source_conditions_and_applicability",
    "calculation_or_conversion",
    "measurement_uncertainty_and_safety_margin",
    "measured_result",
    "status",
    "consequences_of_failure",
)


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise ValueError(f"{path}: expected a JSON object")
    return value


def _round_half_away(value: float) -> int:
    return math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5)


@dataclass(frozen=True)
class Policy:
    policy_id: str
    config_hash: str
    plant_model_hash: str
    characterization_hash: str
    estimator_hash: str
    nominal_frequency_hz: float
    gain_min: float
    gain_nominal: float
    gain_max: float
    estimator_span_s: int
    decision_cadence_s: int
    settling_exclusion_s: int
    fresh_support_s: int
    full_history_reset_s: int
    future_cadence_s: int
    warmup_s: int
    detection_floor_hz: float
    deadband_hz: float
    integrator_gain: float
    integrator_limit_codes: int
    proposed_max_update_codes: int
    active_update_codes: int
    minimum_code: int
    maximum_code: int
    fail_static_code: int
    temperature_min_c: float
    temperature_max_c: float
    temperature_required_for_control: bool
    out_of_model_hold: bool
    recovery_support_s: int
    provenance: tuple[dict[str, Any], ...]


def load_policy(path: Path = DEFAULT_POLICY) -> Policy:
    value = _read_json(path)
    if set(value) != {
        "schema_version", "policy_id", "status", "bindings", "parameters",
        "rules", "authority", "tolerance_provenance",
    }:
        raise ValueError("I-only policy top-level fields differ")
    if value["schema_version"] != 1 or value["status"] not in {
        "selected_observe_only",
        "selected_observe_only_with_temperature_covariate",
    }:
        raise ValueError("unsupported or non-observe-only I-only policy")
    authority = value["authority"]
    expected_authority = {
        "preview_only": True,
        "control_ready": False,
        "actuation_enabled": False,
        "actuation_authorized": False,
        "actionable": False,
    }
    if authority != expected_authority:
        raise ValueError("I-only authority invariant differs")
    bindings = value["bindings"]
    model_path = REPO_ROOT / str(bindings["plant_model_path"])
    estimator_path = REPO_ROOT / str(bindings["selected_estimator_path"])
    if _sha256_file(model_path) != bindings["plant_model_sha256"]:
        raise ValueError("bound PPS-gated plant model hash differs")
    if _sha256_file(estimator_path) != bindings["selected_estimator_sha256"]:
        raise ValueError("bound selected-estimator hash differs")
    parameters = value["parameters"]
    integer_fields = (
        "estimator_span_s", "preview_decision_cadence_s", "settling_exclusion_s",
        "fresh_support_after_settling_s", "full_history_reset_s",
        "future_minimum_actuation_cadence_s", "startup_warmup_s",
        "integrator_limit_codes", "proposed_future_maximum_update_codes",
        "active_live_update_codes", "dac_min_code", "dac_max_code",
        "crossing_envelope_min_code", "crossing_envelope_max_code",
        "fail_static_code", "recovery_fresh_support_s",
    )
    if any(type(parameters[name]) is not int for name in integer_fields):
        raise ValueError("I-only integer policy field is not an integer")
    numeric_values = [
        value for item in parameters.values()
        for value in ([item] if isinstance(item, (int, float)) and not isinstance(item, bool) else [])
    ]
    if any(not math.isfinite(float(item)) for item in numeric_values):
        raise ValueError("I-only policy contains a non-finite number")
    if not 0 < parameters["gain_min_hz_per_code"] <= parameters["gain_nominal_hz_per_code"] <= parameters["gain_max_hz_per_code"]:
        raise ValueError("I-only plant gain envelope is invalid")
    if parameters["full_history_reset_s"] != parameters["settling_exclusion_s"] + parameters["fresh_support_after_settling_s"]:
        raise ValueError("I-only full-history reset calculation differs")
    expected_future_cadence = math.ceil(
        parameters["full_history_reset_s"] / parameters["estimator_span_s"]
    ) * parameters["estimator_span_s"]
    if parameters["future_minimum_actuation_cadence_s"] != expected_future_cadence:
        raise ValueError("I-only future cadence is not estimator-aligned")
    expected_update = math.ceil(
        parameters["empirical_detection_floor_hz"] / parameters["gain_min_hz_per_code"]
    )
    if parameters["proposed_future_maximum_update_codes"] != expected_update:
        raise ValueError("I-only update size is not tied to measured floor/minimum gain")
    expected_deadband = (
        parameters["empirical_detection_floor_hz"]
        + parameters["maximum_observed_hysteresis_hz"]
        + parameters["centre_repeatability_span_hz"]
    )
    if not math.isclose(parameters["error_deadband_hz"], expected_deadband, rel_tol=0, abs_tol=1e-15):
        raise ValueError("I-only deadband derivation differs")
    expected_integrator_gain = 1.0 / (2.0 * parameters["gain_max_hz_per_code"])
    if not math.isclose(parameters["integrator_gain_codes_per_hz_per_decision"], expected_integrator_gain, rel_tol=0, abs_tol=1e-12):
        raise ValueError("I-only integrator gain derivation differs")
    if parameters["active_live_update_codes"] != 0:
        raise ValueError("live I-only update size must remain zero")
    if not parameters["dac_min_code"] <= parameters["fail_static_code"] <= parameters["dac_max_code"]:
        raise ValueError("fail-static code is outside the clamp")
    provenance = value["tolerance_provenance"]
    if not isinstance(provenance, list) or not provenance:
        raise ValueError("I-only tolerance provenance is empty")
    if any(set(row) != set(PROVENANCE_FIELDS) for row in provenance):
        raise ValueError("I-only tolerance-provenance row fields differ")
    return Policy(
        policy_id=str(value["policy_id"]), config_hash=_sha256_file(path),
        plant_model_hash=str(bindings["plant_model_sha256"]),
        characterization_hash=str(bindings["plant_characterization_sha256"]),
        estimator_hash=str(bindings["selected_estimator_sha256"]),
        nominal_frequency_hz=float(parameters["nominal_frequency_hz"]),
        gain_min=float(parameters["gain_min_hz_per_code"]),
        gain_nominal=float(parameters["gain_nominal_hz_per_code"]),
        gain_max=float(parameters["gain_max_hz_per_code"]),
        estimator_span_s=int(parameters["estimator_span_s"]),
        decision_cadence_s=int(parameters["preview_decision_cadence_s"]),
        settling_exclusion_s=int(parameters["settling_exclusion_s"]),
        fresh_support_s=int(parameters["fresh_support_after_settling_s"]),
        full_history_reset_s=int(parameters["full_history_reset_s"]),
        future_cadence_s=int(parameters["future_minimum_actuation_cadence_s"]),
        warmup_s=int(parameters["startup_warmup_s"]),
        detection_floor_hz=float(parameters["empirical_detection_floor_hz"]),
        deadband_hz=float(parameters["error_deadband_hz"]),
        integrator_gain=float(parameters["integrator_gain_codes_per_hz_per_decision"]),
        integrator_limit_codes=int(parameters["integrator_limit_codes"]),
        proposed_max_update_codes=int(parameters["proposed_future_maximum_update_codes"]),
        active_update_codes=int(parameters["active_live_update_codes"]),
        minimum_code=int(parameters["dac_min_code"]), maximum_code=int(parameters["dac_max_code"]),
        fail_static_code=int(parameters["fail_static_code"]),
        temperature_min_c=float(parameters["temperature_min_c"]),
        temperature_max_c=float(parameters["temperature_max_c"]),
        temperature_required_for_control=bool(
            parameters.get("temperature_required_for_control_eligibility", True)
        ),
        out_of_model_hold=value["policy_id"] == "CX317_PPS_GATED_I_ONLY_PREVIEW_V2",
        recovery_support_s=int(parameters["recovery_fresh_support_s"]),
        provenance=tuple(dict(row) for row in provenance),
    )


def load_current_replay_policy(path: Path = CURRENT_REPLAY_POLICY) -> Policy:
    """Load the tracked replay contract for the controller deployed by CX319."""
    value = _read_json(path)
    if set(value) != {
        "authority", "bindings", "parameters", "policy_id", "provenance",
        "schema_version", "status", "compatibility_floor",
    }:
        raise ValueError("current replay policy top-level fields differ")
    if (
        value["schema_version"] != 1
        or value["policy_id"] != "CX317_POST_CAMPAIGN_FREQUENCY_CONTROL_POLICY_V1"
        or value["status"] != "current_cx319_deployed_wire_replay_contract"
        or value["compatibility_floor"] != "CX319_EVIDENCE_EPOCH_1"
    ):
        raise ValueError("unsupported current replay policy identity")

    authority = value["authority"]
    if (
        authority.get("actionable") is not False
        or authority.get("actuation_authorized") is not False
        or authority.get("hardware_interaction") is not False
    ):
        raise ValueError("current replay authority invariant differs")

    bindings = value["bindings"]
    bound_paths = {
        "current_active_policy_root_sha256": REPO_ROOT / "profiles/discipline/cx317_bounded_active_v2.json",
        "plant_model_sha256": REPO_ROOT / "profiles/plant_models/cx317_pps_gated_v2.json",
        "selected_estimator_sha256": REPO_ROOT / "profiles/estimators/cx317_pps_gated_selected_v1.json",
    }
    for field, bound_path in bound_paths.items():
        if _sha256_file(bound_path) != bindings.get(field):
            raise ValueError(f"current replay {field} binding differs")

    provenance = value["provenance"]
    parameters = value["parameters"]

    integer_fields = (
        "dac_max_code", "dac_min_code", "fresh_support_after_settling_s",
        "full_history_reset_s", "maximum_update_codes",
        "minimum_applied_correction_cadence_s", "nominal_frequency_hz",
        "settling_exclusion_s", "startup_warmup_s",
    )
    if any(type(parameters[name]) is not int for name in integer_fields):
        raise ValueError("current replay integer policy field is not an integer")
    numeric_values = [
        item for item in parameters.values()
        if isinstance(item, (int, float)) and not isinstance(item, bool)
    ]
    if any(not math.isfinite(float(item)) for item in numeric_values):
        raise ValueError("current replay policy contains a non-finite number")
    if not (
        0 < parameters["gain_min_hz_per_code"]
        <= parameters["gain_nominal_hz_per_code"]
        <= parameters["gain_max_hz_per_code"]
    ):
        raise ValueError("current replay plant gain envelope is invalid")
    if parameters["full_history_reset_s"] != (
        parameters["settling_exclusion_s"]
        + parameters["fresh_support_after_settling_s"]
    ):
        raise ValueError("current replay full-history reset calculation differs")
    if parameters["minimum_applied_correction_cadence_s"] < parameters["full_history_reset_s"]:
        raise ValueError("current replay cadence is shorter than history reset")
    expected_update = math.ceil(
        parameters["empirical_detection_floor_hz"]
        / parameters["gain_min_hz_per_code"]
    )
    if parameters["maximum_update_codes"] != expected_update:
        raise ValueError("current replay update size is not evidence-derived")
    expected_integrator_gain = 1.0 / (2.0 * parameters["gain_max_hz_per_code"])
    if not math.isclose(
        parameters["integrator_gain_codes_per_hz_per_decision"],
        expected_integrator_gain,
        rel_tol=0,
        abs_tol=1e-12,
    ):
        raise ValueError("current replay integrator gain derivation differs")
    fail_static_code = int(parameters["fail_static_code"])
    if not parameters["dac_min_code"] <= fail_static_code <= parameters["dac_max_code"]:
        raise ValueError("current replay fail-static code is outside the clamp")
    if parameters["temperature_required_for_control_eligibility"] is not False:
        raise ValueError("current replay temperature role differs")

    return Policy(
        policy_id=str(value["policy_id"]),
        config_hash=_sha256_file(path),
        plant_model_hash=str(bindings["plant_model_sha256"]),
        characterization_hash=str(bindings["source_contract_sha256"]),
        estimator_hash=str(bindings["selected_estimator_sha256"]),
        nominal_frequency_hz=float(parameters["nominal_frequency_hz"]),
        gain_min=float(parameters["gain_min_hz_per_code"]),
        gain_nominal=float(parameters["gain_nominal_hz_per_code"]),
        gain_max=float(parameters["gain_max_hz_per_code"]),
        estimator_span_s=int(parameters["fresh_support_after_settling_s"]),
        decision_cadence_s=int(parameters["minimum_applied_correction_cadence_s"]),
        settling_exclusion_s=int(parameters["settling_exclusion_s"]),
        fresh_support_s=int(parameters["fresh_support_after_settling_s"]),
        full_history_reset_s=int(parameters["full_history_reset_s"]),
        future_cadence_s=int(parameters["minimum_applied_correction_cadence_s"]),
        warmup_s=int(parameters["startup_warmup_s"]),
        detection_floor_hz=float(parameters["empirical_detection_floor_hz"]),
        deadband_hz=float(parameters["error_deadband_hz"]),
        integrator_gain=float(parameters["integrator_gain_codes_per_hz_per_decision"]),
        integrator_limit_codes=int(parameters["maximum_update_codes"]),
        proposed_max_update_codes=int(parameters["maximum_update_codes"]),
        active_update_codes=0,
        minimum_code=int(parameters["dac_min_code"]),
        maximum_code=int(parameters["dac_max_code"]),
        fail_static_code=fail_static_code,
        temperature_min_c=float(parameters["temperature_min_c"]),
        temperature_max_c=float(parameters["temperature_max_c"]),
        temperature_required_for_control=False,
        out_of_model_hold=bool(parameters["out_of_model_hold"]),
        recovery_support_s=int(parameters["recovery_fresh_support_s"]),
        provenance=(dict(provenance),),
    )


@dataclass(frozen=True)
class Observation:
    timestamp_s: int
    frequency_error_hz: float | None
    current_code: int
    temperature_c: float | None = None
    estimator_valid: bool = True
    reference_valid: bool = True
    count_valid: bool = True
    model_applicable: bool = True
    applied_code_matches: bool = True
    i2c_ok: bool = True
    operator_abort: bool = False
    recovery_requested: bool = False
    dac_epoch: bool = False
    frequency_controller_eligible: bool | None = None
    frequency_gate_reason: str | None = None


class IOnlyPreviewEngine:
    def __init__(self, policy: Policy, startup_s: int = 0) -> None:
        self.policy = policy
        self.startup_s = startup_s
        self.state = "WARMUP_INHIBIT"
        self.integrator_codes = 0.0
        self.last_decision_s: int | None = None
        self.qualifying_since_s = startup_s + policy.warmup_s
        self.inhibit_until_s = self.qualifying_since_s
        self.latched_reason = "startup_warmup"

    def note_dac_epoch(
        self, timestamp_s: int, *, preserve_applied_cadence: bool = False
    ) -> None:
        """Reset history at the actual application time, between observations."""
        self.state = "SETTLING_INHIBIT"
        self.latched_reason = "dac_epoch_full_history_reset"
        self.inhibit_until_s = timestamp_s + self.policy.full_history_reset_s
        self.qualifying_since_s = self.inhibit_until_s
        self.integrator_codes = 0.0
        self.last_decision_s = timestamp_s if preserve_applied_cadence else None

    def _result(self, observation: Observation, **values: Any) -> dict[str, Any]:
        result = {
            "timestamp_s": observation.timestamp_s,
            "state": self.state,
            "reason": self.latched_reason,
            "current_code": observation.current_code,
            "frequency_error_hz": observation.frequency_error_hz,
            "integrator_codes": self.integrator_codes,
            "preview_available": False,
            "raw_delta_codes": None,
            "limited_delta_codes": None,
            "proposed_code": None,
            "step_limited": False,
            "range_clamped": False,
            "preview_only": True,
            "control_ready": False,
            "actuation_enabled": False,
            "actuation_authorized": False,
            "actionable": False,
            "active_update_codes": self.policy.active_update_codes,
            "fail_static_code": self.policy.fail_static_code,
        }
        result.update(values)
        return result

    def process(self, observation: Observation) -> dict[str, Any]:
        if observation.operator_abort:
            self.state, self.latched_reason, self.integrator_codes = "ABORTED", "operator_abort", 0.0
            return self._result(observation)
        if self.state == "ABORTED":
            return self._result(observation)
        recoverable_quality_reason = next(
            (reason for active, reason in (
                (not observation.reference_valid, "reference_invalid"),
                (not observation.estimator_valid, "estimator_invalid_or_snapshot_gap"),
                (not observation.count_valid, "count_invalid"),
            ) if active), None
        )
        if recoverable_quality_reason is not None:
            self.state = "QUALIFYING"
            self.latched_reason = recoverable_quality_reason
            self.qualifying_since_s = observation.timestamp_s
            self.inhibit_until_s = observation.timestamp_s + self.policy.recovery_support_s
            self.integrator_codes = 0.0
            self.last_decision_s = None
            return self._result(observation)
        fault_reason = next(
            (reason for active, reason in (
                (not observation.applied_code_matches, "requested_applied_mismatch"),
                (not observation.i2c_ok, "i2c_failure"),
                (not self.policy.minimum_code <= observation.current_code <= self.policy.maximum_code, "current_code_outside_clamp"),
                (self.policy.temperature_required_for_control and observation.temperature_c is None, "temperature_unavailable"),
                (self.policy.temperature_required_for_control and observation.temperature_c is not None and not self.policy.temperature_min_c <= observation.temperature_c <= self.policy.temperature_max_c, "temperature_model_mismatch"),
            ) if active), None
        )
        if fault_reason is not None:
            self.state, self.latched_reason, self.integrator_codes = "FAULT", fault_reason, 0.0
            return self._result(observation)
        if self.state == "FAULT":
            if not observation.recovery_requested:
                return self._result(observation)
            self.state, self.latched_reason = "QUALIFYING", "explicit_recovery_fresh_support"
            self.qualifying_since_s = observation.timestamp_s
            self.inhibit_until_s = observation.timestamp_s + self.policy.recovery_support_s
            self.integrator_codes = 0.0
            return self._result(observation)
        if not observation.model_applicable:
            if self.policy.out_of_model_hold:
                self.state = "OUT_OF_MODEL_HOLD"
                self.latched_reason = "plant_model_inapplicable_hold"
            else:
                self.state = "FAULT"
                self.latched_reason = "plant_model_mismatch"
            self.integrator_codes = 0.0
            self.last_decision_s = None
            return self._result(observation)
        if self.state == "OUT_OF_MODEL_HOLD":
            self.state, self.latched_reason = "QUALIFYING", "model_reapplicable_fresh_support"
            self.qualifying_since_s = observation.timestamp_s
            self.inhibit_until_s = observation.timestamp_s + self.policy.recovery_support_s
            self.integrator_codes = 0.0
            self.last_decision_s = None
            return self._result(observation)
        if observation.dac_epoch:
            self.note_dac_epoch(observation.timestamp_s)
            return self._result(observation)
        if observation.timestamp_s < self.startup_s + self.policy.warmup_s:
            self.state, self.latched_reason = "WARMUP_INHIBIT", "startup_warmup"
            return self._result(observation)
        if observation.timestamp_s < self.inhibit_until_s:
            return self._result(observation)
        if self.state == "WARMUP_INHIBIT":
            self.state, self.latched_reason = "QUALIFYING", "fresh_estimator_support"
            self.qualifying_since_s = observation.timestamp_s
            self.inhibit_until_s = observation.timestamp_s + self.policy.estimator_span_s
            return self._result(observation)
        if self.state == "SETTLING_INHIBIT":
            self.state, self.latched_reason = "QUALIFYING", "dac_epoch_fresh_history_complete"
        if self.state == "QUALIFYING" and observation.timestamp_s < self.inhibit_until_s:
            return self._result(observation)
        if observation.frequency_controller_eligible is False:
            if not observation.frequency_gate_reason:
                raise ValueError(
                    "an ineligible frequency gate requires an exact reason"
                )
            self.state = "TRACKING"
            self.latched_reason = observation.frequency_gate_reason
            self.integrator_codes = 0.0
            return self._result(
                observation,
                preview_available=True,
                raw_delta_codes=0.0,
                limited_delta_codes=0,
                proposed_code=observation.current_code,
            )
        if self.last_decision_s is not None and observation.timestamp_s - self.last_decision_s < self.policy.decision_cadence_s:
            self.state, self.latched_reason = "TRACKING", "decision_cadence_hold"
            return self._result(observation)
        if observation.frequency_error_hz is None or not math.isfinite(observation.frequency_error_hz):
            self.state, self.latched_reason, self.integrator_codes = "FAULT", "frequency_error_unavailable", 0.0
            return self._result(observation)
        error = observation.frequency_error_hz
        self.last_decision_s = observation.timestamp_s
        self.state = "TRACKING"
        if (
            observation.frequency_controller_eligible is None
            and abs(error) <= self.policy.deadband_hz
        ):
            self.integrator_codes, self.latched_reason = 0.0, "inside_evidence_deadband"
            return self._result(
                observation, preview_available=True, raw_delta_codes=0.0,
                limited_delta_codes=0, proposed_code=observation.current_code,
                integrator_codes=self.integrator_codes,
            )
        raw_integrator = self.integrator_codes - self.policy.integrator_gain * error
        limited_integrator = min(
            float(self.policy.integrator_limit_codes),
            max(-float(self.policy.integrator_limit_codes), raw_integrator),
        )
        rounded = _round_half_away(limited_integrator)
        proposed_unclamped = observation.current_code + rounded
        proposed = min(self.policy.maximum_code, max(self.policy.minimum_code, proposed_unclamped))
        actual_delta = proposed - observation.current_code
        step_limited = not math.isclose(raw_integrator, limited_integrator, rel_tol=0, abs_tol=1e-12)
        range_clamped = proposed != proposed_unclamped
        self.integrator_codes = float(actual_delta)
        self.latched_reason = "preview_available_observe_only"
        return self._result(
            observation, preview_available=True, raw_delta_codes=raw_integrator,
            limited_delta_codes=actual_delta, proposed_code=proposed,
            step_limited=step_limited, range_clamped=range_clamped,
            integrator_codes=self.integrator_codes,
        )


def _prime(policy: Policy, *, code: int, error: float, temperature: float = 29.0) -> tuple[IOnlyPreviewEngine, list[dict[str, Any]]]:
    engine = IOnlyPreviewEngine(policy)
    rows = [
        engine.process(Observation(0, error, code, temperature)),
        engine.process(Observation(policy.warmup_s, error, code, temperature)),
        engine.process(Observation(policy.warmup_s + policy.estimator_span_s, error, code, temperature)),
    ]
    return engine, rows


def _scenario(identifier: str, category: str, passed: bool, evidence: Any) -> dict[str, Any]:
    return {"id": identifier, "category": category, "pass": bool(passed), "evidence": evidence}


def run_scenarios(policy: Policy) -> list[dict[str, Any]]:
    scenarios: list[dict[str, Any]] = []
    next_decision_s = (
        policy.warmup_s + policy.estimator_span_s + policy.decision_cadence_s
    )
    for label, gain in (("minimum", policy.gain_min), ("nominal", policy.gain_nominal), ("maximum", policy.gain_max)):
        _, rows = _prime(policy, code=policy.fail_static_code, error=0.02)
        decision = rows[-1]
        residual = 0.02 - (policy.fail_static_code - int(decision["proposed_code"])) * gain
        scenarios.append(_scenario(f"gain_{label}", "plant_gain", decision["preview_available"] and abs(residual) < 0.02, {"gain_hz_per_code": gain, "decision": decision, "simulated_residual_hz": residual}))
    offset_results = []
    for code, error in ((policy.minimum_code, -0.02), (43070, 0.02), (policy.fail_static_code, 0.02), (policy.maximum_code, 0.02)):
        _, rows = _prime(policy, code=code, error=error)
        offset_results.append(rows[-1])
    scenarios.append(_scenario("fixed_offsets_across_range", "range", all(row["preview_available"] for row in offset_results), offset_results))
    noise_rows = []
    engine, _ = _prime(policy, code=policy.fail_static_code, error=0.0)
    for index, error in enumerate((-policy.detection_floor_hz, 0.0, policy.detection_floor_hz), start=1):
        noise_rows.append(engine.process(Observation(policy.warmup_s + policy.estimator_span_s + index * policy.decision_cadence_s, error, policy.fail_static_code, 29.0)))
    scenarios.append(_scenario("quantization_and_fixed_code_noise", "noise", all(row["proposed_code"] == policy.fail_static_code for row in noise_rows), noise_rows))
    _, drift_rows = _prime(policy, code=policy.fail_static_code, error=0.02, temperature=policy.temperature_max_c)
    scenarios.append(_scenario("drift_temperature_correlated_context", "environment", drift_rows[-1]["preview_available"], drift_rows))
    startup_engine = IOnlyPreviewEngine(policy)
    startup_rows = [startup_engine.process(Observation(t, 0.02, policy.fail_static_code, 29.0)) for t in (0, policy.warmup_s - 1, policy.warmup_s, policy.warmup_s + policy.estimator_span_s)]
    scenarios.append(_scenario("startup_warmup_inhibition", "startup", [row["state"] for row in startup_rows] == ["WARMUP_INHIBIT", "WARMUP_INHIBIT", "QUALIFYING", "TRACKING"], startup_rows))
    engine, _ = _prime(policy, code=policy.fail_static_code, error=0.02)
    change_rows = [
        engine.process(Observation(3000, 0.02, policy.fail_static_code, 29.0, dac_epoch=True)),
        engine.process(Observation(3000 + policy.full_history_reset_s - 1, 0.02, policy.fail_static_code, 29.0)),
        engine.process(Observation(3000 + policy.full_history_reset_s, 0.02, policy.fail_static_code, 29.0)),
    ]
    scenarios.append(_scenario("dac_change_full_history_reset", "settling", not change_rows[0]["preview_available"] and not change_rows[1]["preview_available"] and change_rows[2]["preview_available"], change_rows))
    scenarios.append(_scenario("settling_minimum_and_conservative_maximum", "settling", policy.settling_exclusion_s == 900 and policy.full_history_reset_s == 1500 and policy.future_cadence_s == 1800, {"exclusion_s": policy.settling_exclusion_s, "full_reset_s": policy.full_history_reset_s, "future_cadence_s": policy.future_cadence_s, "t95_status": "unavailable"}))
    for identifier, field in (("reference_loss", "reference_valid"), ("malformed_pps", "estimator_valid"), ("snapshot_gap", "estimator_valid"), ("count_fault", "count_valid"), ("model_mismatch", "model_applicable"), ("requested_applied_disagreement", "applied_code_matches"), ("i2c_failure", "i2c_ok")):
        engine, _ = _prime(policy, code=policy.fail_static_code, error=0.02)
        values = {field: False}
        fault = engine.process(Observation(3000, 0.02, policy.fail_static_code, 29.0, **values))
        if identifier in {"reference_loss", "malformed_pps", "snapshot_gap", "count_fault"}:
            recovery = engine.process(Observation(3000 + policy.recovery_support_s - 1, 0.02, policy.fail_static_code, 29.0))
            recovered = engine.process(Observation(3000 + policy.recovery_support_s, 0.02, policy.fail_static_code, 29.0))
            passed = (
                fault["state"] == "QUALIFYING"
                and recovery["state"] == "QUALIFYING"
                and recovered["preview_available"]
            )
        else:
            recovery = engine.process(Observation(3600, 0.02, policy.fail_static_code, 29.0, recovery_requested=True))
            recovered = engine.process(Observation(3600 + policy.recovery_support_s, 0.02, policy.fail_static_code, 29.0))
            initial_state = (
                "OUT_OF_MODEL_HOLD"
                if identifier == "model_mismatch" and policy.out_of_model_hold
                else "FAULT"
            )
            passed = (
                fault["state"] == initial_state
                and recovery["state"] == "QUALIFYING"
                and recovered["preview_available"]
            )
        scenarios.append(_scenario(identifier, "fault_recovery", passed, [fault, recovery, recovered]))
    if not policy.temperature_required_for_control:
        missing_engine, _ = _prime(policy, code=policy.fail_static_code, error=0.02)
        missing = missing_engine.process(
            Observation(next_decision_s, 0.02, policy.fail_static_code, None)
        )
        outside_engine, _ = _prime(policy, code=policy.fail_static_code, error=0.02)
        outside = outside_engine.process(
            Observation(next_decision_s, 0.02, policy.fail_static_code,
                        policy.temperature_max_c + 10.0)
        )
        scenarios.append(_scenario(
            "temperature_covariate_not_gate", "environment",
            missing["preview_available"] and outside["preview_available"],
            [missing, outside],
        ))
    engine, _ = _prime(policy, code=policy.maximum_code, error=-1.0)
    clamp = engine.process(
        Observation(next_decision_s, -1.0, policy.maximum_code, 29.0)
    )
    scenarios.append(_scenario("dac_clamp_slew_and_anti_windup", "limits", clamp["preview_available"] and clamp["range_clamped"] and clamp["proposed_code"] == policy.maximum_code and clamp["integrator_codes"] == 0.0, clamp))
    engine, _ = _prime(policy, code=policy.fail_static_code, error=0.02)
    aborted = engine.process(Observation(3000, 0.02, policy.fail_static_code, 29.0, operator_abort=True))
    after_abort = engine.process(Observation(3600, 0.02, policy.fail_static_code, 29.0, recovery_requested=True))
    scenarios.append(_scenario("operator_abort_fail_static", "abort", aborted["state"] == "ABORTED" and after_abort["state"] == "ABORTED" and not aborted["preview_available"], [aborted, after_abort]))
    return scenarios
