"""Host-only bounded hybrid phase/frequency preview for the CX318 programme.

CX317 is the oscillator identity.  Every output is counterfactual and this
module has no command, active-controller, actuator, serial, DAC, or I2C path.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
import json
import math
from typing import Any

from jsonschema import Draft202012Validator

from .cx318_relative_phase import CandidateEstimate, PhaseRecord


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE = (
    REPO_ROOT / "profiles/discipline/cx318_hybrid_preview_candidates_v1.json"
)
DEFAULT_SCHEMA = (
    REPO_ROOT / "schemas/cx318_hybrid_preview_candidates_v1.schema.json"
)


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def load_profile(
    path: Path = DEFAULT_PROFILE, schema_path: Path = DEFAULT_SCHEMA
) -> tuple[dict[str, Any], str]:
    profile = json.loads(path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(profile)
    for binding in profile["bindings"].values():
        source = REPO_ROOT / binding["path"]
        if not source.is_file() or _sha256_file(source) != binding["sha256"]:
            raise ValueError(f"hybrid-preview source binding differs: {source}")
    if any(profile["authority"].values()):
        raise ValueError("hybrid-preview authority must remain false")
    combinations = {
        (int(item["pull_in_time_s"]), float(item["phase_bias_cap_hz"]), item["band_policy"])
        for item in profile["candidates"]
    }
    expected = {
        (pull, cap, band)
        for pull in (3600, 10800, 21600)
        for cap in (1 / 600, 2 / 600)
        for band in ("historical_v2", "tight_hysteretic")
    }
    if combinations != expected or len(profile["candidates"]) != 12:
        raise ValueError("hybrid-preview candidate grid is not the frozen Cartesian product")
    if "LOCKED" in profile["state_machine"]["states"]:
        raise ValueError("hybrid preview may not claim a locked state")
    return profile, _sha256_file(path)


def _round_half_away(value: float) -> int:
    if not math.isfinite(value):
        raise ValueError("cannot round a non-finite preview value")
    return math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5)


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, value))


@dataclass(frozen=True)
class HybridPreviewDecision:
    candidate_id: str
    phase_epoch: int
    observation_sequence: int
    dac_epoch: int
    timestamp_s: float
    raw_relative_phase_cycles: int
    modeled_relative_phase_cycles: float
    observed_frequency_error_hz: float | None
    modeled_frequency_error_hz: float | None
    frequency_term_hz: float | None
    phase_bias_hz: float
    combined_desired_frequency_change_hz: float | None
    actual_applied_code: int
    shadow_code_before: int
    shadow_code_after: int
    band_state_before: str
    band_state_after: str
    preview_state: str
    decision_reason: str
    frequency_observation_event: bool
    counterfactual_decision: bool
    counterfactual_correction: bool
    raw_delta_codes: float | None
    limited_delta_codes: int | None
    step_limited: bool
    range_clamped: bool
    correction_count: int
    cumulative_movement_codes: int
    alternating_correction_count: int
    modeled_not_observed_after_divergence: bool
    uncertainty_status: str = "unavailable"
    actionable: bool = False
    actuation_authorized: bool = False
    authorization_consumed: bool = False


class HybridCandidateEngine:
    """Pure state for one frozen, coherent counterfactual candidate."""

    def __init__(
        self,
        profile: dict[str, Any],
        candidate: dict[str, Any],
        *,
        start_code: int,
        gain_hz_per_code: float | None = None,
        phase_enabled: bool = True,
    ) -> None:
        numerical = profile["numerical_policy"]
        if not int(numerical["minimum_code"]) <= start_code <= int(
            numerical["maximum_code"]
        ):
            raise ValueError("counterfactual start code is outside the hard range")
        self.profile = profile
        self.candidate = candidate
        self.candidate_id = str(candidate["candidate_id"])
        self.pull_in_s = int(candidate["pull_in_time_s"])
        self.cap_hz = float(candidate["phase_bias_cap_hz"])
        self.band_policy_id = str(candidate["band_policy"])
        self.band_policy = profile["band_policies"][self.band_policy_id]
        self.gain = float(
            numerical["gain_hz_per_code"]["nominal"]
            if gain_hz_per_code is None
            else gain_hz_per_code
        )
        if not math.isfinite(self.gain) or self.gain <= 0:
            raise ValueError("preview plant gain must be finite and positive")
        self.integrator_gain = float(
            numerical["integrator_gain_codes_per_hz_per_decision"]
        )
        self.maximum_step = int(numerical["maximum_step_codes"])
        self.minimum_code = int(numerical["minimum_code"])
        self.maximum_code = int(numerical["maximum_code"])
        self.frequency_support_s = int(numerical["frequency_support_s"])
        self.decision_cadence_s = int(
            numerical["counterfactual_decision_cadence_s"]
        )
        self.requalification_s = int(numerical["settling_exclusion_s"]) + int(
            numerical["fresh_support_after_settling_s"]
        )
        self.step_hold_s = int(numerical["phase_step_hold_s"])
        self.maximum_corrections = int(numerical["maximum_corrections"])
        self.maximum_path = int(numerical["maximum_cumulative_movement_codes"])
        self.phase_enabled = phase_enabled
        self.start_code = start_code
        self.actual_code = start_code
        self.shadow_code = start_code
        self.actual_dac_epoch: int | None = None
        self.phase_epoch: int | None = None
        self.modeled_phase = 0.0
        self.previous_raw_phase = 0
        self.previous_timestamp_s: float | None = None
        self.last_frequency_event_s: float | None = None
        self.last_observed_frequency_hz: float | None = None
        self.last_decision_s: float | None = None
        self.last_correction_s: float | None = None
        self.phase_hold_until_s: float | None = None
        self.band_state = str(self.band_policy["initial_state"])
        self.entry_count = 0
        self.release_count = 0
        self.integrator_codes = 0.0
        self.correction_count = 0
        self.path_codes = 0
        self.directions: list[int] = []
        self.terminal_reason: str | None = None
        self.had_reference_loss = False

    def _reset_band_and_support(self) -> None:
        self.band_state = str(self.band_policy["initial_state"])
        self.entry_count = 0
        self.release_count = 0
        self.integrator_codes = 0.0
        self.last_frequency_event_s = None
        self.last_observed_frequency_hz = None
        self.last_decision_s = None
        self.last_correction_s = None

    def _update_band(self, modeled_frequency_hz: float) -> None:
        absolute = abs(modeled_frequency_hz)
        if self.band_policy_id == "historical_v2":
            threshold = float(self.band_policy["entry_absolute_hz_lte"])
            self.band_state = "INSIDE" if absolute <= threshold else "OUTSIDE"
            self.entry_count = 0
            self.release_count = 0
            return

        counts = absolute * self.frequency_support_s
        if self.band_state in {"OUTSIDE", "REQUALIFY_OUTSIDE"}:
            self.release_count = 0
            if counts <= int(self.band_policy["entry_absolute_600s_counts_lte"]):
                self.entry_count += 1
                if self.entry_count >= int(
                    self.band_policy["entry_consecutive_fresh_estimates"]
                ):
                    self.band_state = "INSIDE"
                    self.entry_count = 0
            else:
                self.entry_count = 0
        else:
            self.entry_count = 0
            if counts >= int(self.band_policy["release_absolute_600s_counts_gte"]):
                self.release_count += 1
                if self.release_count >= int(
                    self.band_policy["release_consecutive_fresh_estimates"]
                ):
                    self.band_state = "OUTSIDE"
                    self.release_count = 0
            elif counts < 3 or counts > 3:
                self.release_count = 0

    def _dither_reason(self, delta: int) -> str | None:
        guard = self.profile["dither_guard"]
        direction = 1 if delta > 0 else -1
        window = int(guard["alternation_window_corrections"])
        prospective = [*self.directions[-(window - 1) :], direction]
        reversals = sum(a != b for a, b in zip(prospective, prospective[1:]))
        if len(prospective) == window and reversals >= int(
            guard["maximum_consecutive_direction_reversals"]
        ):
            return "prospective_repeated_alternation"
        path = self.path_codes + abs(delta)
        net = abs(self.shadow_code + delta - self.start_code)
        if path >= int(guard["low_efficiency_minimum_path_codes"]) and net <= float(
            guard["low_efficiency_maximum_absolute_net_to_path_ratio"]
        ) * path:
            return "prospective_low_net_excess_path"
        return None

    def _state(self, frequency_available: bool, timestamp_s: float) -> str:
        if self.terminal_reason is not None:
            return "FAULT_PREVIEW"
        if self.phase_hold_until_s is not None and timestamp_s < self.phase_hold_until_s:
            return "PHASE_STEP_HOLD_PREVIEW"
        if not frequency_available:
            return "RECOVER_PREVIEW" if self.had_reference_loss else "RELATIVE_PHASE_ACQUIRE"
        if self.band_state == "INSIDE":
            return "HYBRID_TRACKING_PREVIEW"
        return "FREQUENCY_ACQUIRED_PREVIEW"

    def _output(
        self,
        record: PhaseRecord,
        *,
        timestamp_s: float,
        before_code: int,
        before_band: str,
        observed_frequency: float | None,
        modeled_frequency: float | None,
        phase_bias: float,
        combined: float | None,
        reason: str,
        frequency_event: bool = False,
        decision: bool = False,
        correction: bool = False,
        raw_delta: float | None = None,
        limited_delta: int | None = None,
        step_limited: bool = False,
        range_clamped: bool = False,
    ) -> HybridPreviewDecision:
        alternating = sum(a != b for a, b in zip(self.directions, self.directions[1:]))
        return HybridPreviewDecision(
            candidate_id=self.candidate_id,
            phase_epoch=record.phase_epoch,
            observation_sequence=record.observation_sequence,
            dac_epoch=record.dac_epoch,
            timestamp_s=timestamp_s,
            raw_relative_phase_cycles=record.relative_phase_cycles,
            modeled_relative_phase_cycles=self.modeled_phase,
            observed_frequency_error_hz=observed_frequency,
            modeled_frequency_error_hz=modeled_frequency,
            frequency_term_hz=(-modeled_frequency if modeled_frequency is not None else None),
            phase_bias_hz=phase_bias,
            combined_desired_frequency_change_hz=combined,
            actual_applied_code=self.actual_code,
            shadow_code_before=before_code,
            shadow_code_after=self.shadow_code,
            band_state_before=before_band,
            band_state_after=self.band_state,
            preview_state=self._state(modeled_frequency is not None, timestamp_s),
            decision_reason=reason,
            frequency_observation_event=frequency_event,
            counterfactual_decision=decision,
            counterfactual_correction=correction,
            raw_delta_codes=raw_delta,
            limited_delta_codes=limited_delta,
            step_limited=step_limited,
            range_clamped=range_clamped,
            correction_count=self.correction_count,
            cumulative_movement_codes=self.path_codes,
            alternating_correction_count=alternating,
            modeled_not_observed_after_divergence=self.shadow_code != self.actual_code,
        )

    def invalidate(
        self,
        record: PhaseRecord,
        *,
        timestamp_s: float,
        actual_applied_code: int,
        reason: str,
    ) -> HybridPreviewDecision:
        before = self.shadow_code
        before_band = self.band_state
        self.actual_code = actual_applied_code
        self.shadow_code = actual_applied_code
        self.actual_dac_epoch = record.dac_epoch
        self.phase_epoch = None
        self.previous_timestamp_s = None
        self.phase_hold_until_s = None
        self.had_reference_loss = True
        self._reset_band_and_support()
        output = self._output(
            record,
            timestamp_s=timestamp_s,
            before_code=before,
            before_band=before_band,
            observed_frequency=None,
            modeled_frequency=None,
            phase_bias=0.0,
            combined=None,
            reason=reason,
        )
        return HybridPreviewDecision(
            **{**asdict(output), "preview_state": "REFERENCE_LOST_PREVIEW"}
        )

    def process(
        self,
        record: PhaseRecord,
        estimate: CandidateEstimate,
        *,
        timestamp_s: float,
        actual_applied_code: int,
        phase_step_detected: bool = False,
    ) -> HybridPreviewDecision:
        if (
            record.phase_epoch != estimate.phase_epoch
            or record.observation_sequence != estimate.observation_sequence
            or record.dac_epoch != estimate.dac_epoch
            or record.relative_phase_cycles != estimate.raw_relative_phase_cycles
            or not self.minimum_code <= actual_applied_code <= self.maximum_code
            or not math.isfinite(timestamp_s)
        ):
            raise ValueError("malformed or mismatched hybrid-preview input")
        before_code = self.shadow_code
        before_band = self.band_state
        new_phase_epoch = self.phase_epoch != record.phase_epoch
        new_dac_epoch = self.actual_dac_epoch != record.dac_epoch
        if new_phase_epoch or new_dac_epoch:
            self.phase_epoch = record.phase_epoch
            self.actual_dac_epoch = record.dac_epoch
            self.actual_code = actual_applied_code
            self.shadow_code = actual_applied_code
            self.modeled_phase = float(record.relative_phase_cycles)
            self.previous_raw_phase = record.relative_phase_cycles
            self.previous_timestamp_s = timestamp_s
            self.phase_hold_until_s = None
            self._reset_band_and_support()
            reason = "phase_epoch_reseed" if new_phase_epoch else "dac_epoch_bumpless_reseed"
            return self._output(
                record,
                timestamp_s=timestamp_s,
                before_code=before_code,
                before_band=before_band,
                observed_frequency=None,
                modeled_frequency=None,
                phase_bias=0.0,
                combined=None,
                reason=reason,
            )
        assert self.previous_timestamp_s is not None
        if timestamp_s <= self.previous_timestamp_s:
            self.terminal_reason = "nonmonotonic_preview_time"
            return self._output(
                record,
                timestamp_s=timestamp_s,
                before_code=before_code,
                before_band=before_band,
                observed_frequency=None,
                modeled_frequency=None,
                phase_bias=0.0,
                combined=None,
                reason=self.terminal_reason,
            )

        interval_s = timestamp_s - self.previous_timestamp_s
        raw_increment = record.relative_phase_cycles - self.previous_raw_phase
        self.modeled_phase += raw_increment + self.gain * (
            self.shadow_code - actual_applied_code
        ) * interval_s
        self.actual_code = actual_applied_code
        self.previous_raw_phase = record.relative_phase_cycles
        self.previous_timestamp_s = timestamp_s

        if phase_step_detected:
            self.phase_hold_until_s = timestamp_s + self.step_hold_s
            self._reset_band_and_support()
            return self._output(
                record,
                timestamp_s=timestamp_s,
                before_code=before_code,
                before_band=before_band,
                observed_frequency=None,
                modeled_frequency=None,
                phase_bias=0.0,
                combined=None,
                reason="phase_step_hold_started",
            )

        frequency = estimate.estimated_frequency_error_hz
        frequency_event = (
            estimate.qualification_state == "qualified"
            and frequency is not None
            and math.isfinite(frequency)
            and (self.phase_hold_until_s is None or timestamp_s >= self.phase_hold_until_s)
            and (
                self.last_frequency_event_s is None
                or timestamp_s - self.last_frequency_event_s >= self.frequency_support_s
            )
        )
        if not frequency_event:
            modeled = (
                None
                if self.last_observed_frequency_hz is None
                else self.last_observed_frequency_hz
                + self.gain * (self.shadow_code - self.actual_code)
            )
            phase_bias = (
                _clamp(-self.modeled_phase / self.pull_in_s, -self.cap_hz, self.cap_hz)
                if modeled is not None and self.band_state == "INSIDE" and self.phase_enabled
                else 0.0
            )
            frequency_term = None if modeled is None else -modeled
            combined = None if frequency_term is None else frequency_term + phase_bias
            return self._output(
                record,
                timestamp_s=timestamp_s,
                before_code=before_code,
                before_band=before_band,
                observed_frequency=self.last_observed_frequency_hz,
                modeled_frequency=modeled,
                phase_bias=phase_bias,
                combined=combined,
                reason="frequency_support_or_decision_cadence_hold",
            )

        self.last_frequency_event_s = timestamp_s
        self.last_observed_frequency_hz = float(frequency)
        modeled_frequency = float(frequency) + self.gain * (
            self.shadow_code - self.actual_code
        )
        self._update_band(modeled_frequency)
        phase_bias = (
            _clamp(-self.modeled_phase / self.pull_in_s, -self.cap_hz, self.cap_hz)
            if self.band_state == "INSIDE" and self.phase_enabled
            else 0.0
        )
        frequency_term = -modeled_frequency
        combined = frequency_term + phase_bias

        if self.terminal_reason is not None:
            reason = self.terminal_reason
        elif self.last_correction_s is not None and timestamp_s - self.last_correction_s < self.requalification_s:
            reason = "counterfactual_settling_and_fresh_support"
        elif self.last_decision_s is not None and timestamp_s - self.last_decision_s < self.decision_cadence_s:
            reason = "counterfactual_decision_cadence_hold"
        else:
            self.last_decision_s = timestamp_s
            if self.band_state == "INSIDE" and (not self.phase_enabled or abs(phase_bias) < 1e-15):
                self.integrator_codes = 0.0
                return self._output(
                    record,
                    timestamp_s=timestamp_s,
                    before_code=before_code,
                    before_band=before_band,
                    observed_frequency=float(frequency),
                    modeled_frequency=modeled_frequency,
                    phase_bias=phase_bias,
                    combined=combined,
                    reason="inside_band_zero_phase_hold",
                    frequency_event=True,
                    decision=True,
                    raw_delta=0.0,
                    limited_delta=0,
                )
            raw_delta = self.integrator_codes + self.integrator_gain * combined
            limited_float = _clamp(
                raw_delta, -float(self.maximum_step), float(self.maximum_step)
            )
            step_limited = not math.isclose(raw_delta, limited_float, abs_tol=1e-12)
            rounded = _round_half_away(limited_float)
            unclamped = self.shadow_code + rounded
            proposed = min(self.maximum_code, max(self.minimum_code, unclamped))
            range_clamped = proposed != unclamped
            delta = proposed - self.shadow_code
            if (
                delta != 0
                and self.band_state == "INSIDE"
                and self.phase_enabled
                and abs(phase_bias) >= 1e-15
                and delta * phase_bias < 0
            ):
                self.integrator_codes = 0.0
                return self._output(
                    record,
                    timestamp_s=timestamp_s,
                    before_code=before_code,
                    before_band=before_band,
                    observed_frequency=float(frequency),
                    modeled_frequency=modeled_frequency,
                    phase_bias=phase_bias,
                    combined=combined,
                    reason="phase_direction_coherence_hold",
                    frequency_event=True,
                    decision=True,
                    raw_delta=raw_delta,
                    limited_delta=0,
                    step_limited=step_limited,
                    range_clamped=range_clamped,
                )
            if delta == 0:
                self.integrator_codes = 0.0
                reason = "hard_range_or_zero_rounded_hold"
            elif self.correction_count + 1 > self.maximum_corrections or self.path_codes + abs(delta) > self.maximum_path:
                self.terminal_reason = "counterfactual_budget_hold"
                self.integrator_codes = 0.0
                reason = self.terminal_reason
            else:
                dither = self._dither_reason(delta)
                if dither is not None:
                    self.terminal_reason = dither
                    self.integrator_codes = 0.0
                    reason = dither
                else:
                    self.shadow_code = proposed
                    self.correction_count += 1
                    self.path_codes += abs(delta)
                    self.directions.append(1 if delta > 0 else -1)
                    self.last_correction_s = timestamp_s
                    self.integrator_codes = 0.0
                    reason = "counterfactual_correction_modeled"
                    return self._output(
                        record,
                        timestamp_s=timestamp_s,
                        before_code=before_code,
                        before_band=before_band,
                        observed_frequency=float(frequency),
                        modeled_frequency=modeled_frequency,
                        phase_bias=phase_bias,
                        combined=combined,
                        reason=reason,
                        frequency_event=True,
                        decision=True,
                        correction=True,
                        raw_delta=raw_delta,
                        limited_delta=delta,
                        step_limited=step_limited,
                        range_clamped=range_clamped,
                    )
            return self._output(
                record,
                timestamp_s=timestamp_s,
                before_code=before_code,
                before_band=before_band,
                observed_frequency=float(frequency),
                modeled_frequency=modeled_frequency,
                phase_bias=phase_bias,
                combined=combined,
                reason=reason,
                frequency_event=True,
                decision=True,
                raw_delta=raw_delta,
                limited_delta=delta,
                step_limited=step_limited,
                range_clamped=range_clamped,
            )

        return self._output(
            record,
            timestamp_s=timestamp_s,
            before_code=before_code,
            before_band=before_band,
            observed_frequency=float(frequency),
            modeled_frequency=modeled_frequency,
            phase_bias=phase_bias,
            combined=combined,
            reason=reason,
            frequency_event=True,
        )


class HybridPreviewSuite:
    def __init__(
        self,
        profile: dict[str, Any],
        *,
        start_code: int,
        gain_hz_per_code: float | None = None,
        phase_enabled: bool = True,
    ) -> None:
        self.engines = [
            HybridCandidateEngine(
                profile,
                item,
                start_code=start_code,
                gain_hz_per_code=gain_hz_per_code,
                phase_enabled=phase_enabled,
            )
            for item in profile["candidates"]
        ]

    def process(
        self,
        record: PhaseRecord,
        estimate: CandidateEstimate | None,
        *,
        timestamp_s: float,
        actual_applied_code: int,
        phase_step_detected: bool = False,
    ) -> list[HybridPreviewDecision]:
        if estimate is None or record.qualification_state == "invalid":
            return [
                engine.invalidate(
                    record,
                    timestamp_s=timestamp_s,
                    actual_applied_code=actual_applied_code,
                    reason=record.discontinuity_reason or "invalid_phase_input",
                )
                for engine in self.engines
            ]
        return [
            engine.process(
                record,
                estimate,
                timestamp_s=timestamp_s,
                actual_applied_code=actual_applied_code,
                phase_step_detected=phase_step_detected,
            )
            for engine in self.engines
        ]


def deterministic_digest(decisions: list[HybridPreviewDecision]) -> str:
    return sha256(
        json.dumps(
            [asdict(value) for value in decisions],
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    ).hexdigest()
