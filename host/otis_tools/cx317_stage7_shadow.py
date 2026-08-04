"""Exact non-actionable Stage 7 deadband-candidate shadow engine."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
from pathlib import Path
import argparse
import json
import math
import tempfile
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = (
    REPO_ROOT / "profiles/discipline/cx317_stage7_shadow_deadband_v1.json"
)
CONTRACT_SHA256 = (
    "85c686f9e2ca7997ddf00cf8039c1c8d0d61bfdb217d4104bdbc5519a66e3bf9"
)
TOOL_VERSION = "cx317_stage7_shadow_v1"


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _round_half_away(value: float) -> int:
    return math.floor(value + 0.5) if value >= 0.0 else math.ceil(value - 0.5)


@dataclass(frozen=True)
class Candidate:
    candidate_id: str
    kind: str
    entry_threshold_hz: float
    release_threshold_hz: float
    entry_consecutive: int
    release_consecutive: int


@dataclass(frozen=True)
class ShadowContract:
    contract_id: str
    contract_sha256: str
    authoritative_deadband_hz: float
    detection_floor_hz: float
    gain_min: float
    gain_nominal: float
    gain_max: float
    integrator_gain: float
    maximum_step: int
    cadence_s: int
    settling_s: int
    fresh_support_s: int
    minimum_code: int
    maximum_code: int
    part_a_start_code: int
    alternation_window: int
    alternation_reversals: int
    low_efficiency_path_codes: int
    low_efficiency_net_path_ratio: float
    budgets: dict[str, tuple[int, int]]
    candidates: tuple[Candidate, ...]


@dataclass(frozen=True)
class ShadowObservation:
    observation_sequence: int
    estimate_id: str
    timestamp_s: int
    frequency_error_hz: float
    actual_applied_code: int
    actual_dac_epoch: int = 0
    eligible: bool = True


@dataclass(frozen=True)
class ShadowDecision:
    record_type: str
    schema_version: int
    candidate_id: str
    observation_sequence: int
    estimate_id: str
    timestamp_s: int
    observed_error_hz: float
    counterfactual_error_hz: float
    actual_applied_code: int
    shadow_code_before: int
    shadow_code_after: int
    band_state_before: str
    band_state_after: str
    state_before: str
    state_after: str
    transition: str | None
    entry_consecutive_count: int
    release_consecutive_count: int
    integrator_before_codes: float
    raw_delta_codes: float | None
    limited_delta_codes: int | None
    proposed_code: int | None
    step_limited: bool
    range_clamped: bool
    counterfactual_write: bool
    correction_count: int
    path_codes: int
    net_movement_codes: int
    alternating_correction_count: int
    decision_reason: str
    actionable: bool
    actuation_authorized: bool
    authorization_consumed: bool


def load_contract(path: Path = DEFAULT_CONTRACT) -> ShadowContract:
    if _sha256_file(path) != CONTRACT_SHA256:
        raise ValueError("Stage 7 shadow contract hash differs from the freeze")
    value = json.loads(path.read_text(encoding="utf-8"))
    expected_top = {
        "schema_version",
        "contract_id",
        "status",
        "bindings",
        "authority",
        "observation_contract",
        "numerical_contract",
        "candidates",
        "state_machine",
        "dither_contract",
        "budgets",
        "acceptance_metrics",
        "outputs",
    }
    if set(value) != expected_top:
        raise ValueError("Stage 7 shadow contract top-level fields differ")
    if (
        value["schema_version"] != 1
        or value["contract_id"] != "CX317_STAGE7_SHADOW_DEADBAND_V1"
        or value["status"] != "frozen_before_stage7_part_a_non_actionable"
    ):
        raise ValueError("unsupported Stage 7 shadow contract identity")

    bindings = value["bindings"]
    bound_paths = {
        "stage7_prompt_sha256": bindings["stage7_prompt_path"],
        "post_campaign_policy_sha256": bindings["post_campaign_policy_path"],
        "selected_estimator_sha256": bindings["selected_estimator_path"],
        "plant_model_sha256": bindings["plant_model_path"],
        "active_policy_sha256": bindings["active_policy_path"],
        "response_policy_sha256": bindings["response_policy_path"],
    }
    for hash_field, relative_path in bound_paths.items():
        if _sha256_file(REPO_ROOT / relative_path) != bindings[hash_field]:
            raise ValueError(f"Stage 7 shadow binding differs: {hash_field}")

    authority = value["authority"]
    forbidden_true = {
        "actionable",
        "actuation_authorized",
        "may_consume_authorization",
        "may_change_live_controller_state",
        "may_change_live_response_state",
        "may_change_live_budget",
        "may_issue_command",
        "may_write_dac",
        "candidate_adoption_during_stage7",
    }
    if any(authority.get(field) is not False for field in forbidden_true):
        raise ValueError("Stage 7 shadow contract grants authority")
    if authority.get("counterfactual_only_after_code_divergence") is not True:
        raise ValueError("Stage 7 shadow divergence semantics differ")

    numerical = value["numerical_contract"]
    finite = [
        item
        for item in numerical.values()
        if isinstance(item, (int, float)) and not isinstance(item, bool)
    ]
    if any(not math.isfinite(float(item)) for item in finite):
        raise ValueError("Stage 7 shadow numerical contract is non-finite")
    if not (
        0.0 < numerical["gain_min_hz_per_code"]
        <= numerical["gain_nominal_hz_per_code"]
        <= numerical["gain_max_hz_per_code"]
    ):
        raise ValueError("Stage 7 shadow gain envelope differs")
    if numerical["full_history_reset_s"] != (
        numerical["settling_exclusion_s"]
        + numerical["fresh_support_after_settling_s"]
    ):
        raise ValueError("Stage 7 shadow history reset differs")
    if numerical["minimum_cadence_s"] < numerical["full_history_reset_s"]:
        raise ValueError("Stage 7 shadow cadence is too short")
    if numerical["rounding_rule"] != "round_half_away_from_zero_after_step_limit":
        raise ValueError("Stage 7 shadow rounding differs")

    candidates: list[Candidate] = []
    identifiers: set[str] = set()
    floor = float(numerical["empirical_detection_floor_hz"])
    for row in value["candidates"]:
        identifier = str(row["candidate_id"])
        if identifier in identifiers:
            raise ValueError("Stage 7 shadow candidate identity is duplicated")
        identifiers.add(identifier)
        kind = str(row["kind"])
        entry = float(row["entry_threshold_hz"])
        release = float(row["release_threshold_hz"])
        entry_count = int(row["entry_consecutive_fresh_estimates"])
        release_count = int(row["release_consecutive_fresh_estimates"])
        if (
            kind not in {"symmetric", "hysteretic"}
            or entry < floor
            or release < entry
            or entry_count < 1
            or release_count < 1
        ):
            raise ValueError(f"invalid Stage 7 shadow candidate {identifier}")
        if kind == "symmetric" and (
            entry != release or entry_count != 1 or release_count != 1
        ):
            raise ValueError("symmetric Stage 7 candidate semantics differ")
        candidates.append(
            Candidate(identifier, kind, entry, release, entry_count, release_count)
        )
    baseline = next(
        (item for item in candidates if item.candidate_id == "v2_symmetric_baseline"),
        None,
    )
    if baseline is None or baseline.entry_threshold_hz != float(
        numerical["authoritative_v2_deadband_hz"]
    ):
        raise ValueError("Stage 7 V2 shadow baseline differs")

    budgets = value["budgets"]
    normalized_budgets = {
        "part_a": (
            int(budgets["part_a"]["maximum_corrections"]),
            int(budgets["part_a"]["maximum_sum_absolute_movement_codes"]),
        ),
        "part_b": (
            int(budgets["part_b"]["maximum_corrections"]),
            int(budgets["part_b"]["maximum_sum_absolute_movement_codes"]),
        ),
    }
    if normalized_budgets != {"part_a": (4, 84), "part_b": (32, 672)}:
        raise ValueError("Stage 7 shadow budgets differ")
    if (
        budgets.get("one_request_outstanding") is not True
        or budgets.get("automatic_retry") is not False
        or budgets.get("automatic_restore") is not False
    ):
        raise ValueError("Stage 7 shadow transaction authority differs")

    dither = value["dither_contract"]
    if (
        dither.get("evaluation") != "prospective_before_counterfactual_request"
        or dither.get("outcome") != "DITHER_HOLD_without_counterfactual_write"
        or dither.get("authoritative_part_b_rule_must_match") is not True
    ):
        raise ValueError("Stage 7 shadow dither semantics differ")

    return ShadowContract(
        contract_id=value["contract_id"],
        contract_sha256=CONTRACT_SHA256,
        authoritative_deadband_hz=float(
            numerical["authoritative_v2_deadband_hz"]
        ),
        detection_floor_hz=floor,
        gain_min=float(numerical["gain_min_hz_per_code"]),
        gain_nominal=float(numerical["gain_nominal_hz_per_code"]),
        gain_max=float(numerical["gain_max_hz_per_code"]),
        integrator_gain=float(
            numerical["integrator_gain_codes_per_hz_per_decision"]
        ),
        maximum_step=int(numerical["maximum_step_codes"]),
        cadence_s=int(numerical["minimum_cadence_s"]),
        settling_s=int(numerical["settling_exclusion_s"]),
        fresh_support_s=int(numerical["fresh_support_after_settling_s"]),
        minimum_code=int(numerical["minimum_code"]),
        maximum_code=int(numerical["maximum_code"]),
        part_a_start_code=int(numerical["part_a_initial_code"]),
        alternation_window=int(dither["alternation_window_corrections"]),
        alternation_reversals=int(
            dither["stop_when_prospective_consecutive_direction_reversals_reach"]
        ),
        low_efficiency_path_codes=int(
            dither["low_efficiency_minimum_prospective_path_codes"]
        ),
        low_efficiency_net_path_ratio=float(
            dither["low_efficiency_maximum_abs_net_to_path_ratio"]
        ),
        budgets=normalized_budgets,
        candidates=tuple(candidates),
    )


class CandidateEngine:
    """Pure deterministic counterfactual state for one frozen candidate."""

    def __init__(
        self,
        contract: ShadowContract,
        candidate: Candidate,
        *,
        part: str,
        start_code: int,
    ) -> None:
        if part not in contract.budgets:
            raise ValueError(f"unknown Stage 7 part {part!r}")
        if not contract.minimum_code <= start_code <= contract.maximum_code:
            raise ValueError("shadow start code is outside the hard range")
        self.contract = contract
        self.candidate = candidate
        self.part = part
        self.start_code = start_code
        self.shadow_code = start_code
        self.band_state = "INSIDE"
        self.terminal_state: str | None = None
        self.entry_count = 0
        self.release_count = 0
        self.integrator_codes = 0.0
        self.last_decision_s: int | None = None
        self.last_application_s: int | None = None
        self.correction_count = 0
        self.path_codes = 0
        self.directions: list[int] = []

    def _counterfactual_error(self, observation: ShadowObservation) -> float:
        return observation.frequency_error_hz + self.contract.gain_nominal * (
            self.shadow_code - observation.actual_applied_code
        )

    def _update_band(self, absolute_error: float) -> str | None:
        candidate = self.candidate
        previous = self.band_state
        if candidate.kind == "symmetric":
            self.band_state = (
                "INSIDE"
                if absolute_error <= candidate.entry_threshold_hz
                else "OUTSIDE"
            )
            self.entry_count = 0
            self.release_count = 0
        elif self.band_state == "INSIDE":
            self.entry_count = 0
            if absolute_error > candidate.release_threshold_hz:
                self.release_count += 1
                if self.release_count >= candidate.release_consecutive:
                    self.band_state = "OUTSIDE"
                    self.release_count = 0
            else:
                self.release_count = 0
        else:
            self.release_count = 0
            if absolute_error <= candidate.entry_threshold_hz:
                self.entry_count += 1
                if self.entry_count >= candidate.entry_consecutive:
                    self.band_state = "INSIDE"
                    self.entry_count = 0
            else:
                self.entry_count = 0
        if previous != self.band_state:
            return f"{previous.lower()}_to_{self.band_state.lower()}"
        return None

    def _prospective_dither_reason(self, delta: int) -> str | None:
        direction = 1 if delta > 0 else -1
        prospective_directions = [
            *self.directions[-(self.contract.alternation_window - 1) :],
            direction,
        ]
        reversals = sum(
            left != right
            for left, right in zip(
                prospective_directions, prospective_directions[1:]
            )
        )
        if (
            len(prospective_directions) == self.contract.alternation_window
            and reversals >= self.contract.alternation_reversals
        ):
            return "prospective_repeated_alternation"
        prospective_path = self.path_codes + abs(delta)
        prospective_net = abs((self.shadow_code + delta) - self.start_code)
        if (
            prospective_path >= self.contract.low_efficiency_path_codes
            and prospective_net
            <= self.contract.low_efficiency_net_path_ratio * prospective_path
        ):
            return "prospective_low_net_excess_path"
        return None

    def process(self, observation: ShadowObservation) -> ShadowDecision:
        before_code = self.shadow_code
        before_band_state = self.band_state
        before_state = self.terminal_state or self.band_state
        integrator_before = self.integrator_codes
        raw_delta: float | None = None
        limited_delta: int | None = None
        proposed: int | None = None
        step_limited = False
        clamped = False
        write = False
        reason = "unprocessed"
        transition: str | None = None

        if self.terminal_state is not None:
            counterfactual_error = self._counterfactual_error(observation)
            reason = f"terminal_{self.terminal_state.lower()}"
        elif (
            not observation.eligible
            or not math.isfinite(observation.frequency_error_hz)
            or not self.contract.minimum_code
            <= observation.actual_applied_code
            <= self.contract.maximum_code
        ):
            self.terminal_state = "FAULT"
            counterfactual_error = math.nan
            self.integrator_codes = 0.0
            reason = "invalid_authoritative_observation"
        else:
            counterfactual_error = self._counterfactual_error(observation)
            if not math.isfinite(counterfactual_error):
                self.terminal_state = "FAULT"
                self.integrator_codes = 0.0
                reason = "nonfinite_counterfactual_error"
            else:
                transition = self._update_band(abs(counterfactual_error))
                since_application = (
                    None
                    if self.last_application_s is None
                    else observation.timestamp_s - self.last_application_s
                )
                if since_application is not None and since_application < 0:
                    self.terminal_state = "FAULT"
                    self.integrator_codes = 0.0
                    reason = "nonmonotonic_observation_time"
                elif (
                    since_application is not None
                    and since_application < self.contract.settling_s
                ):
                    reason = "counterfactual_settling_exclusion"
                elif (
                    since_application is not None
                    and since_application
                    < self.contract.settling_s + self.contract.fresh_support_s
                ):
                    reason = "counterfactual_fresh_support"
                elif (
                    self.last_decision_s is not None
                    and observation.timestamp_s - self.last_decision_s
                    < self.contract.cadence_s
                ):
                    reason = "counterfactual_decision_cadence_hold"
                else:
                    self.last_decision_s = observation.timestamp_s
                    if self.band_state == "INSIDE":
                        self.integrator_codes = 0.0
                        raw_delta = 0.0
                        limited_delta = 0
                        proposed = self.shadow_code
                        reason = transition or "inside_candidate_deadband"
                    else:
                        raw_delta = (
                            self.integrator_codes
                            - self.contract.integrator_gain * counterfactual_error
                        )
                        limited_integrator = min(
                            float(self.contract.maximum_step),
                            max(-float(self.contract.maximum_step), raw_delta),
                        )
                        step_limited = not math.isclose(
                            raw_delta, limited_integrator, rel_tol=0.0, abs_tol=1e-12
                        )
                        rounded = _round_half_away(limited_integrator)
                        unclamped = self.shadow_code + rounded
                        proposed = min(
                            self.contract.maximum_code,
                            max(self.contract.minimum_code, unclamped),
                        )
                        clamped = proposed != unclamped
                        limited_delta = proposed - self.shadow_code
                        if limited_delta == 0:
                            self.integrator_codes = 0.0
                            reason = (
                                "counterfactual_hard_range_hold"
                                if clamped
                                else "counterfactual_zero_rounded_delta"
                            )
                        else:
                            max_corrections, max_path = self.contract.budgets[self.part]
                            if (
                                self.correction_count + 1 > max_corrections
                                or self.path_codes + abs(limited_delta) > max_path
                            ):
                                self.terminal_state = "BUDGET_HOLD"
                                self.integrator_codes = 0.0
                                reason = "counterfactual_budget_hold"
                            else:
                                dither_reason = self._prospective_dither_reason(
                                    limited_delta
                                )
                                if dither_reason is not None:
                                    self.terminal_state = "DITHER_HOLD"
                                    self.integrator_codes = 0.0
                                    reason = dither_reason
                                else:
                                    direction = 1 if limited_delta > 0 else -1
                                    self.shadow_code = proposed
                                    self.correction_count += 1
                                    self.path_codes += abs(limited_delta)
                                    self.directions.append(direction)
                                    self.last_application_s = observation.timestamp_s
                                    self.integrator_codes = 0.0
                                    self.entry_count = 0
                                    self.release_count = 0
                                    write = True
                                    reason = "counterfactual_exact_application"

        alternating = sum(
            left != right for left, right in zip(self.directions, self.directions[1:])
        )
        state_after = (
            self.terminal_state
            if self.terminal_state is not None
            else "SETTLING"
            if write
            else self.band_state
        )
        return ShadowDecision(
            record_type="SHD",
            schema_version=1,
            candidate_id=self.candidate.candidate_id,
            observation_sequence=observation.observation_sequence,
            estimate_id=observation.estimate_id,
            timestamp_s=observation.timestamp_s,
            observed_error_hz=observation.frequency_error_hz,
            counterfactual_error_hz=counterfactual_error,
            actual_applied_code=observation.actual_applied_code,
            shadow_code_before=before_code,
            shadow_code_after=self.shadow_code,
            band_state_before=before_band_state,
            band_state_after=self.band_state,
            state_before=before_state,
            state_after=state_after,
            transition=transition,
            entry_consecutive_count=self.entry_count,
            release_consecutive_count=self.release_count,
            integrator_before_codes=integrator_before,
            raw_delta_codes=raw_delta,
            limited_delta_codes=limited_delta,
            proposed_code=proposed,
            step_limited=step_limited,
            range_clamped=clamped,
            counterfactual_write=write,
            correction_count=self.correction_count,
            path_codes=self.path_codes,
            net_movement_codes=self.shadow_code - self.start_code,
            alternating_correction_count=alternating,
            decision_reason=reason,
            actionable=False,
            actuation_authorized=False,
            authorization_consumed=False,
        )


def run_shadow(
    observations: Iterable[ShadowObservation],
    *,
    contract: ShadowContract | None = None,
    part: str,
    start_code: int,
) -> list[ShadowDecision]:
    selected = contract or load_contract()
    engines = [
        CandidateEngine(selected, candidate, part=part, start_code=start_code)
        for candidate in selected.candidates
    ]
    output: list[ShadowDecision] = []
    last_sequence = -1
    last_timestamp = -1
    for observation in observations:
        if (
            observation.observation_sequence <= last_sequence
            or observation.timestamp_s < last_timestamp
        ):
            raise ValueError("Stage 7 shadow observations are not monotonic")
        last_sequence = observation.observation_sequence
        last_timestamp = observation.timestamp_s
        output.extend(engine.process(observation) for engine in engines)
    return output


def _read_jsonl(path: Path) -> list[ShadowObservation]:
    observations: list[ShadowObservation] = []
    for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
            observations.append(ShadowObservation(**row))
        except (TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(f"{path}:{line_number}: {exc}") from exc
    return observations


def _write_atomic_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.",
        suffix=".tmp", delete=False,
    ) as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("observations", type=Path, help="JSONL ShadowObservation input")
    parser.add_argument("--part", choices=("part_a", "part_b"), required=True)
    parser.add_argument("--start-code", type=lambda value: int(value, 0), required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        contract = load_contract()
        decisions = run_shadow(
            _read_jsonl(args.observations), contract=contract,
            part=args.part, start_code=args.start_code,
        )
        _write_atomic_json(
            args.output,
            {
                "tool": TOOL_VERSION,
                "contract_id": contract.contract_id,
                "contract_sha256": contract.contract_sha256,
                "decisions": [asdict(item) for item in decisions],
            },
        )
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(args.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
