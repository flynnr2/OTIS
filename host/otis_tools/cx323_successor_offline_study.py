"""Offline-only, exact CX323 successor comparator.

The comparator deliberately has no device, serial, command, or actuator
surface.  It checks the frozen contract and retained Attempt 4 evidence, keeps
decisions 1--27 as physical-source replay, and marks every later calculation
as a counterfactual diagnostic.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, replace
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
import subprocess
from typing import Any, Mapping


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_V1_CONTRACT = REPO_ROOT / (
    "docs/60_EXPERIMENTS/OTIS_CX323_SUSTAINED_HYBRID_SUCCESSOR_STUDY/"
    "study_contract_v1.json"
)
DEFAULT_CONTRACT = REPO_ROOT / (
    "docs/60_EXPERIMENTS/OTIS_CX323_SUSTAINED_HYBRID_SUCCESSOR_STUDY/"
    "study_contract_v2.json"
)
EXPECTED_V1_CONTRACT_SHA256 = "8041ebb49269fdf5b81ca23e6e5637029d356e83af6e48428ab5cc88f8df827c"
EXPECTED_CONTRACT_SHA256 = "20b729dce477349704ce09e7cacf14047525450d50230c8f114f75959289d707"
V1_CONTRACT_ID = "OTIS_CX323_SUSTAINED_HYBRID_SUCCESSOR_STUDY_V1"
CONTRACT_ID = "OTIS_CX323_SUSTAINED_HYBRID_SUCCESSOR_STUDY_V2"
TOOL_ID = "otis_cx323_successor_offline_study_v2"
REPORT_TYPE = "otis_cx323_successor_offline_comparison_v2"

BASELINE_ID = "cx323_unchanged_baseline"
NO_DEBT_ID = "cx323_phase_priority_persistent_cap_no_debt_v1"
TAGGED_DEBT_ID = "cx323_phase_priority_persistent_cap_tagged_debt_v1"
EXPECTED_CANDIDATES = (BASELINE_ID, NO_DEBT_ID, TAGGED_DEBT_ID)
SOURCE_REPLAY = "exact_physical_source_replay"
COUNTERFACTUAL = "counterfactual_not_observed_after_divergence"

HZ_UNITS = 21_600
HALF_WIDTH_UNITS = 18
PLANT_GAIN_MAX = Fraction(173_340_101, 1_000_000_000_000)
LEGACY_GAIN = Fraction("2884.5027706464516")
MAX_STEP = 21
MIN_CODE = 43_008
MAX_CODE = 43_776
MAX_APPLICATIONS = 144
MAX_MOVEMENT = 3_024
PERSISTENCE_REQUIRED = 2
PICOCODES_PER_CODE = 1_000_000_000_000
MAX_DEBT_PICOCODES = 500_000_000_000
PICOCODE_REDUCED_NUMERATOR = 625_000_000_000_000_000_000
PICOCODE_REDUCED_DENOMINATOR = 4_680_182_727


def canonical_sha256(value: object) -> str:
    return sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                             allow_nan=False).encode("utf-8")).hexdigest()


def file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1_048_576), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_historical_git_blob(
    repo_root: Path, relative_path: str, expected_sha256: str
) -> None:
    """Validate a superseded binding against its exact retained Git blob.

    Promotion is allowed to advance the current architecture document. A
    frozen offline result must continue to validate the pre-promotion content
    it actually used rather than silently rebinding to the new document.
    """

    revisions = subprocess.run(
        ["git", "rev-list", "HEAD", "--", relative_path],
        cwd=repo_root,
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    ).stdout.splitlines()
    for revision in revisions:
        blob = subprocess.run(
            ["git", "show", f"{revision}:{relative_path}"],
            cwd=repo_root,
            check=False,
            capture_output=True,
            timeout=10,
        )
        if blob.returncode == 0 and sha256(blob.stdout).hexdigest() == expected_sha256:
            return
    raise ValueError("architecture binding identity differs from current and historical Git content")


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root is not an object: {path}")
    return value


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as source:
        return list(csv.DictReader(source))


def _int(value: str, field: str) -> int:
    try:
        return int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"invalid integer {field}: {value!r}") from exc


def _bool(value: str, field: str) -> bool:
    if value == "true":
        return True
    if value == "false":
        return False
    raise ValueError(f"invalid Boolean {field}: {value!r}")


def round_half_away_from_zero(value: Fraction) -> int:
    """Exact nearest-integer rounding; a half always moves away from zero."""

    magnitude = abs(value)
    rounded = (2 * magnitude.numerator + magnitude.denominator) // (
        2 * magnitude.denominator
    )
    return rounded if value >= 0 else -rounded


def load_v1_contract(path: Path = DEFAULT_V1_CONTRACT) -> dict[str, Any]:
    contract = _read_object(path)
    unsigned = {key: value for key, value in contract.items()
                if key != "contract_sha256"}
    if contract.get("contract_sha256") != EXPECTED_V1_CONTRACT_SHA256:
        raise ValueError("CX323 V1 contract does not carry the frozen identity")
    if canonical_sha256(unsigned) != EXPECTED_V1_CONTRACT_SHA256:
        raise ValueError("CX323 V1 contract semantic identity differs")
    if (contract.get("schema_version"), contract.get("contract_id"), contract.get("status")) != (
        1, V1_CONTRACT_ID, "prospectively_frozen_before_candidate_results"
    ):
        raise ValueError("unsupported or unfrozen CX323 contract")
    if tuple(row.get("candidate_id") for row in contract.get("candidates", [])) != EXPECTED_CANDIDATES:
        raise ValueError("CX323 candidate identity or ordering differs")
    superseded = contract.get("pre_execution_draft_superseded", {})
    if superseded.get("candidate_execution_under_superseded_draft") is not False:
        raise ValueError("superseded draft incorrectly permits candidate execution")
    authority = contract.get("authority", {})
    forbidden = ("serial_access", "firmware_flash", "reset", "dac_write", "control_arm",
                 "physical_command_fifo", "physical_rehearsal", "live_acquisition",
                 "live_activation")
    if authority.get("offline_analysis") is not True or any(authority.get(key) is not False for key in forbidden):
        raise ValueError("CX323 authority is not offline-only")
    return contract


def validate_v1_controller_constants(contract: Mapping[str, Any]) -> None:
    """Reject drift between executable constants and frozen V1 semantics."""

    retained = contract["retained_unchanged_semantics"]
    exact = contract["exact_maintenance_observation"]
    expected = {
        "frequency_window_s": 600,
        "phase_pull_in_s": 21_600,
        "minimum_applied_cadence_s": 1_800,
        "settling_exclusion_s": 900,
        "fresh_response_support_s": 600,
        "maximum_step_codes": MAX_STEP,
        "minimum_code": MIN_CODE,
        "maximum_code": MAX_CODE,
        "maximum_automatic_applications": MAX_APPLICATIONS,
        "maximum_cumulative_absolute_movement_codes": MAX_MOVEMENT,
    }
    if any(retained.get(key) != value for key, value in expected.items()):
        raise ValueError("hardcoded controller constants differ from V1 semantics")
    if (Fraction(retained.get("legacy_integrator_gain_codes_per_hz_per_decision", "0")) != LEGACY_GAIN
            or exact.get("half_width_units") != HALF_WIDTH_UNITS
            or exact.get("general_cap_codes") != MAX_STEP
            or exact.get("one_count_absolute_cap_codes") != 4
            or exact.get("positive_plant_gain_maximum_hz_per_code_conservative_rational")
            != "173340101/1000000000000"
            or contract["persistence"].get("required_consecutive_intervals")
            != PERSISTENCE_REQUIRED):
        raise ValueError("hardcoded maintenance constants differ from V1 semantics")


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    """Load V2 and independently bind its exact V1 base contract."""

    contract = _read_object(path)
    unsigned = {key: value for key, value in contract.items()
                if key != "contract_sha256"}
    if contract.get("contract_sha256") != EXPECTED_CONTRACT_SHA256 or canonical_sha256(unsigned) != EXPECTED_CONTRACT_SHA256:
        raise ValueError("CX323 V2 contract semantic identity differs")
    if (contract.get("schema_version"), contract.get("contract_id"), contract.get("status")) != (
        2, CONTRACT_ID, "prospectively_refrozen_after_v1_contract_defect_before_candidate_reexecution"
    ):
        raise ValueError("unsupported or unfrozen CX323 V2 contract")
    base = contract.get("base_contract", {})
    if base != {"path": str(DEFAULT_V1_CONTRACT.relative_to(REPO_ROOT)),
                "contract_id": V1_CONTRACT_ID,
                "contract_sha256": EXPECTED_V1_CONTRACT_SHA256}:
        raise ValueError("CX323 V2 base-contract binding differs")
    v1 = load_v1_contract(REPO_ROOT / base["path"])
    validate_v1_controller_constants(v1)
    inherited = contract.get("inherited_semantics", {})
    if inherited.get("source_bindings") != "exactly_study_contract_v1" or inherited.get("selection_rule") != "exactly_study_contract_v1":
        raise ValueError("CX323 V2 does not retain required V1 semantics")
    correction = contract.get("semantic_corrections", {}).get("selected_window_frontier_domain", {})
    if correction.get("overlap") != "opening_frontier_lt_previous_closing_frontier" or correction.get("contiguous") != "opening_frontier_eq_previous_closing_frontier" or correction.get("gap") != "opening_frontier_gt_previous_closing_frontier":
        raise ValueError("CX323 V2 shared-endpoint correction differs")
    fixed = contract["semantic_corrections"].get("fixed_point_debt_representation", {})
    fixture = fixed.get("bounded_debt_fixture", {})
    if (fixed.get("authoritative_state_unit")
            != "signed_integer_picocode_1e_minus_12_code"
            or fixed.get("maximum_absolute_committed_total_picocodes")
            != MAX_DEBT_PICOCODES
            or fixture != {
                "first_committed_total_debt_picocodes": 341_671_780_415,
                "next_raw_combined_demand_picocodes": 5_475_213_574_925,
                "next_candidate_total_demand_picocodes": 5_816_885_355_340,
                "no_debt_final_delta_codes": 5,
                "tagged_debt_final_delta_codes": 6,
                "no_debt_distance_picocodes": 475_213_574_925,
                "tagged_debt_distance_picocodes": 183_114_644_660,
                "transactions_per_candidate": 2,
                "exact_fraction_audit_only_first_residual_codes": "1599086365/4680182727",
                "exact_fraction_audit_only_tagged_distance_codes": "31741111/173340101",
            }
            or fixed.get("phase_loss")
            != "discard_committed_PLL_debt_picocodes_and_preserve_committed_FLL_debt_picocodes"
            or tuple(contract["semantic_corrections"].get("fixed_point_mandatory_checks", ())) != (
                "controller_committed_debt_fields_are_integers",
                "tag_sum_equals_bounded_total_residual_exactly",
                "positive_and_negative_half_away_rounding_boundaries",
                "positive_and_negative_residual_clamp_boundaries",
                "overflow_safe_reduced_quotient_remainder_proof",
                "independent_integer_quotient_remainder_reference_matches_Python_oracle",
            )
            or fixed.get("exact_picocode_conversion", {}) != {
                "reduced_numerator": PICOCODE_REDUCED_NUMERATOR,
                "reduced_denominator": PICOCODE_REDUCED_DENOMINATOR,
                "input": "combined_centre_units_or_component_centre_units",
                "algorithm": "on_absolute_input_compute_q_and_r_by_divmod(input,reduced_denominator);compute_q_times_reduced_numerator_plus_round_half_away_from_zero(r_times_reduced_numerator/reduced_denominator);restore_input_sign",
                "prohibited_intermediate": "do_not_form_input_times_1000000000000000000000000",
                "required_intermediate": "signed_128_bit_or_equivalent_checked_quotient_remainder_arithmetic",
                "signed_64_bit_count_domain_maximum_absolute_centre_units": 332041393326771929088,
                "maximum_q_times_reduced_numerator": 44341403516250000000000000000000,
                "maximum_r_times_reduced_numerator": 1542141866250000000000000000000,
                "signed_128_maximum": 170141183460469231731687303715884105727,
            }):
        raise ValueError("CX323 V2 fixed-point correction differs")
    if tuple(contract.get("terminal_outcomes", ())) != (
        "cx323_tagged_debt_candidate_selected_non_effective",
        "cx323_no_debt_candidate_selected_architecture_amendment_required",
        "cx323_no_successor_selected",
    ):
        raise ValueError("CX323 V2 terminal outcomes differ")
    return contract


def validate_bound_sources(contract: Mapping[str, Any], *, repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    """Validate immutable retained inputs, including the source replay binding."""

    source = contract["source"]
    root = repo_root.resolve()
    run_dir = (root / source["run_dir"]).resolve()
    try:
        run_dir.relative_to(root)
    except ValueError as exc:
        raise ValueError("bound run directory escapes repository") from exc
    if not run_dir.is_dir():
        raise ValueError("bound Attempt 4 run directory is unavailable")
    validated: list[dict[str, str]] = []
    for relative, expected in source["bound_files"].items():
        path = run_dir / relative
        if not path.is_file() or file_sha256(path) != expected:
            raise ValueError(f"bound source identity differs: {relative}")
        validated.append({"path": relative, "sha256": expected})
    replay = root / "runs/d9_adaptive_steering_integration_20260828/long_runs" / "hybrid_72h_attempt4_superseding_host_replay_v1.json"
    if not replay.is_file() or file_sha256(replay) != source["superseding_host_replay_sha256"]:
        raise ValueError("superseding host replay identity differs")
    architecture_relative = contract["architecture_binding"]["path"]
    architecture = root / architecture_relative
    expected_architecture_sha256 = contract["architecture_binding"]["file_sha256"]
    if not architecture.is_file() or file_sha256(architecture) != expected_architecture_sha256:
        _validate_historical_git_blob(
            root, architecture_relative, expected_architecture_sha256
        )
    manifest = _read_object(run_dir / "run_manifest.json")
    seal = _read_object(run_dir / "reports/cx322_d9_d6_72h_physical_seal_v1.json")
    for field in ("run_id", "run_identity", "profile_identity"):
        if manifest.get(field) != source[field]:
            raise ValueError(f"run manifest {field} differs")
    if (seal.get("run_id"), seal.get("run_identity"), seal.get("build_identity"),
            seal.get("uf2_sha256"), seal.get("seal_sha256")) != (
        source["run_id"], source["run_identity"], source["firmware_build_identity"],
        source["uf2_sha256"], source["frozen_failed_seal_sha256"]
    ):
        raise ValueError("physical seal identity transcript differs")
    return {"run_dir": run_dir, "bound_file_count": len(validated),
            "bound_files": validated, "run_id": source["run_id"],
            "run_identity": source["run_identity"], "profile_identity": source["profile_identity"],
            "firmware_build_identity": source["firmware_build_identity"],
            "uf2_sha256": source["uf2_sha256"],
            "registered_content_sha256": source["registered_content_sha256"],
            "frozen_failed_seal_sha256": source["frozen_failed_seal_sha256"],
            "superseding_host_replay_sha256": source["superseding_host_replay_sha256"]}


def correction_interval(counts: int, relative_phase_cycles: int) -> tuple[int, int, int]:
    frequency = -36 * counts
    phase = max(-36, min(36, -relative_phase_cycles))
    centre = frequency + phase
    return centre, centre - HALF_WIDTH_UNITS, centre + HALF_WIDTH_UNITS


def interval_sign(lower: int, upper: int) -> int:
    return 1 if lower > 0 else -1 if upper < 0 else 0


def safe_cap_codes(centre_units: int) -> int:
    lower, upper = centre_units - HALF_WIDTH_UNITS, centre_units + HALF_WIDTH_UNITS
    sign = interval_sign(lower, upper)
    if sign == 0:
        return 0
    nearest_zero = lower if sign > 0 else -upper
    return min(MAX_STEP, nearest_zero * PLANT_GAIN_MAX.denominator //
               (HZ_UNITS * PLANT_GAIN_MAX.numerator))


def raw_components(counts: int, relative_phase_cycles: int) -> tuple[Fraction, Fraction]:
    frequency = Fraction(-36 * counts * 1_000_000_000_000,
                         HZ_UNITS * 2 * 173_340_101)
    phase_units = max(-36, min(36, -relative_phase_cycles))
    phase = Fraction(phase_units * 1_000_000_000_000,
                     HZ_UNITS * 2 * 173_340_101)
    return frequency, phase


def exact_raw_maintenance_codes(centre_units: int) -> Fraction:
    return Fraction(centre_units * 1_000_000_000_000,
                    HZ_UNITS * 2 * 173_340_101)


def _round_ratio_half_away(numerator: int, denominator: int) -> int:
    """Exact signed quotient/remainder rounding without floating point."""

    if denominator <= 0:
        raise ValueError("rounding denominator must be positive")
    magnitude = abs(numerator)
    rounded = (2 * magnitude + denominator) // (2 * denominator)
    return rounded if numerator >= 0 else -rounded


def centre_to_picocodes(centre_units: int) -> int:
    """V2 reduced quotient/remainder controller conversion.

    It never forms the prohibited ``centre_units * 10**24`` intermediate.
    """

    magnitude = abs(centre_units)
    quotient, remainder = divmod(magnitude, PICOCODE_REDUCED_DENOMINATOR)
    result = quotient * PICOCODE_REDUCED_NUMERATOR + _round_ratio_half_away(
        remainder * PICOCODE_REDUCED_NUMERATOR, PICOCODE_REDUCED_DENOMINATOR
    )
    return result if centre_units >= 0 else -result


def legacy_delta(counts: int, relative_phase_cycles: int) -> tuple[int, int]:
    """Return exact legacy combined and frequency-only deltas before gates."""

    phase_units = max(-36, min(36, -relative_phase_cycles))
    frequency_only = LEGACY_GAIN * Fraction(-counts, 600)
    combined = frequency_only + LEGACY_GAIN * Fraction(phase_units, HZ_UNITS)
    def limit(value: Fraction) -> int:
        return max(-MAX_STEP, min(MAX_STEP, round_half_away_from_zero(value)))
    return limit(combined), limit(frequency_only)


@dataclass(frozen=True)
class Identity:
    capture_session: str
    applied_code: int
    dac_epoch: int
    phase_epoch: str
    phase_valid: bool
    estimator_id: str


@dataclass(frozen=True)
class Debt:
    """Authoritative controller debt state in signed integer picocodes."""

    fll: int = 0
    pll: int = 0

    @property
    def total(self) -> int:
        return self.fll + self.pll


@dataclass(frozen=True)
class State:
    sign: int = 0
    count: int = 0
    identity: Identity | None = None
    last_closing_frontier: int | None = None
    debt: Debt = Debt()
    mode: str = "active"
    requalification_frontier: int | None = None
    fail_static: bool = False
    application_count: int = 0
    cumulative_movement: int = 0
    request_pending: bool = False
    response_pending: bool = False


@dataclass(frozen=True)
class Observation:
    identity: Identity
    opening_frontier: int
    closing_frontier: int
    counts: int
    relative_phase_cycles: int
    qualified: bool = True
    settled: bool = True
    cadence_eligible: bool = True


@dataclass(frozen=True)
class Decision:
    state: State
    delta: int
    cap: int
    reason: str
    raw_fll_picocodes: int = 0
    raw_pll_picocodes: int = 0


def _reset(state: State, *, debt: Debt | None = None) -> State:
    return State(debt=Debt() if debt is None else debt, mode=state.mode,
                 requalification_frontier=state.requalification_frontier,
                 application_count=state.application_count,
                 cumulative_movement=state.cumulative_movement)


def enter_metadata_hold(state: State) -> State:
    return replace(state, mode="metadata_hold", sign=0, count=0, identity=None,
                   last_closing_frontier=None)


def causal_requalify(state: State, frontier: int) -> State:
    if state.mode != "metadata_hold":
        raise ValueError("causal requalification requires metadata hold")
    return State(debt=state.debt, mode="awaiting_post_requalification",
                 requalification_frontier=frontier,
                 application_count=state.application_count,
                 cumulative_movement=state.cumulative_movement)


def new_policy_activation(state: State) -> State:
    """A new policy activation is the explicit FLL/PLL debt reset boundary."""

    return _reset(state)


def _identity_transition(state: State, observation: Observation) -> tuple[State, str | None]:
    previous = state.identity
    if previous is None or previous == observation.identity:
        return state, None
    if previous.capture_session != observation.identity.capture_session:
        return _reset(state), "capture_session_reset"
    if previous.applied_code != observation.identity.applied_code or previous.dac_epoch != observation.identity.dac_epoch:
        return replace(state, fail_static=True), "actuator_provenance_fail_static"
    if previous.phase_epoch != observation.identity.phase_epoch or previous.phase_valid != observation.identity.phase_valid:
        return _reset(state, debt=Debt(fll=state.debt.fll)), "phase_epoch_reset"
    return _reset(state), "estimator_identity_reset"


def evaluate_maintenance(state: State, observation: Observation, *, tagged_debt: bool) -> Decision:
    """Apply the frozen request order through a possible maintenance request.

    This function intentionally stops before request acceptance: a non-zero
    request cannot alter committed debt until :func:`confirm_application`.
    """

    if observation.closing_frontier <= observation.opening_frontier:
        raise ValueError("observation frontier is not increasing")
    if state.fail_static:
        return Decision(state, 0, 0, "actuator_provenance_fail_static")
    if state.request_pending:
        return Decision(state, 0, 0, "request_pending_hold")
    if state.response_pending:
        return Decision(state, 0, 0, "response_pending_hold")
    if state.mode == "metadata_hold":
        return Decision(state, 0, 0, "metadata_hold_frozen")
    if state.mode == "awaiting_post_requalification":
        if observation.opening_frontier < (state.requalification_frontier or 0):
            return Decision(state, 0, 0, "observation_not_post_requalification")
        state = State(debt=state.debt, application_count=state.application_count,
                      cumulative_movement=state.cumulative_movement)
    state, identity_reason = _identity_transition(state, observation)
    if identity_reason == "actuator_provenance_fail_static":
        return Decision(state, 0, 0, identity_reason)
    if not observation.qualified:
        return Decision(_reset(state, debt=state.debt), 0, 0, "reference_invalidity")
    if not observation.settled:
        return Decision(_reset(state, debt=state.debt), 0, 0, "settling_hold")
    if state.last_closing_frontier is not None:
        # Selected estimator windows use (opening, closing]; the endpoint is
        # shared by contiguous windows and must advance persistence exactly.
        if observation.opening_frontier < state.last_closing_frontier:
            return Decision(state, 0, 0, "source_overlap_hold")
        if observation.opening_frontier > state.last_closing_frontier:
            centre, lower, upper = correction_interval(
                observation.counts, observation.relative_phase_cycles
            )
            sign = interval_sign(lower, upper)
            if sign == 0:
                return Decision(_reset(state), 0, 0, "zero_containing_interval")
            restarted = State(sign=sign, count=1, identity=observation.identity,
                              last_closing_frontier=observation.closing_frontier,
                              debt=state.debt,
                              application_count=state.application_count,
                              cumulative_movement=state.cumulative_movement)
            return Decision(restarted, 0, safe_cap_codes(centre), "source_gap_restart")
    centre, lower, upper = correction_interval(observation.counts, observation.relative_phase_cycles)
    sign = interval_sign(lower, upper)
    if sign == 0:
        return Decision(_reset(state), 0, 0, "zero_containing_interval")
    opposite = state.count > 0 and state.identity == observation.identity and state.sign != sign
    if opposite:
        state = _reset(state)
    same = state.count > 0 and state.identity == observation.identity and state.sign == sign
    advanced = State(sign=sign, count=min(PERSISTENCE_REQUIRED, state.count + 1) if same else 1,
                     identity=observation.identity, last_closing_frontier=observation.closing_frontier,
                     debt=state.debt if tagged_debt else Debt(),
                     application_count=state.application_count,
                     cumulative_movement=state.cumulative_movement)
    if not observation.cadence_eligible:
        return Decision(advanced, 0, safe_cap_codes(centre), "cadence_hold_no_accrual")
    if advanced.count < PERSISTENCE_REQUIRED:
        return Decision(advanced, 0, safe_cap_codes(centre), "persistence_first_interval_hold")
    centre, _, _ = correction_interval(
        observation.counts, observation.relative_phase_cycles
    )
    raw_combined = centre_to_picocodes(centre)
    fll = centre_to_picocodes(-36 * observation.counts)
    pll = raw_combined - fll
    requested = raw_combined + (advanced.debt.total if tagged_debt else 0)
    # The frozen order is round first, then bound the integer magnitude.
    rounded = round_half_away_from_zero(Fraction(requested, PICOCODES_PER_CODE))
    cap = min(safe_cap_codes(centre), MAX_STEP, MAX_MOVEMENT - advanced.cumulative_movement,
              MAX_CODE - observation.identity.applied_code if rounded > 0 else
              observation.identity.applied_code - MIN_CODE)
    if advanced.application_count >= MAX_APPLICATIONS:
        return Decision(advanced, 0, cap, "global_application_budget_hold", fll, pll)
    delta = max(-cap, min(cap, rounded))
    if delta and pll and delta * pll < 0:
        return Decision(advanced, 0, cap, "phase_direction_coherence_hold", fll, pll)
    if delta == 0:
        # A zero final request never commits or accrues new debt.
        return Decision(advanced, 0, cap, "zero_final_request_no_debt_accrual", fll, pll)
    return Decision(replace(advanced, request_pending=True), delta, cap,
                    "maintenance_request_ready", fll, pll)


def confirm_application(decision: Decision, *, applied_code: int, dac_epoch: int,
                        first_consumer_exact: bool, tagged_debt: bool) -> State:
    """Commit back-calculated, tagged residual only after exact propagation."""

    state = decision.state
    if decision.delta == 0:
        return state
    if not first_consumer_exact:
        return replace(state, fail_static=True, request_pending=False,
                       response_pending=False)
    if not state.request_pending:
        raise ValueError("exact application requires a pending request")
    if applied_code != state.identity.applied_code + decision.delta or dac_epoch != state.identity.dac_epoch + 1:
        return replace(state, fail_static=True)
    debt = Debt()
    if tagged_debt:
        total_before = (
            decision.raw_fll_picocodes + decision.raw_pll_picocodes
            + state.debt.total
        )
        # The residual is explicitly back-calculated after all request caps and
        # then bounded to the frozen committed-state limit.  The unbounded
        # amount remains reconstructable from raw components and delta.
        residual = max(
            -MAX_DEBT_PICOCODES,
            min(MAX_DEBT_PICOCODES, total_before - decision.delta * PICOCODES_PER_CODE),
        )
        # Retain provenance tags by allocating the exact residual in proportion
        # to the signed component demand.  This does not hide cap/range removal.
        fll_weight = abs(decision.raw_fll_picocodes + state.debt.fll)
        pll_weight = abs(decision.raw_pll_picocodes + state.debt.pll)
        if fll_weight + pll_weight:
            fll_debt = round_half_away_from_zero(
                Fraction(residual * fll_weight, fll_weight + pll_weight)
            )
            debt = Debt(fll_debt, residual - fll_debt)
        else:
            debt = Debt(fll=residual)
        if debt.total != residual or abs(debt.total) > MAX_DEBT_PICOCODES:
            raise ValueError("fixed-point debt tag invariant differs")
    return State(debt=debt, application_count=state.application_count + 1,
                 cumulative_movement=state.cumulative_movement + abs(decision.delta),
                 response_pending=True)


def reject_or_expire_request(state: State) -> State:
    """Explicit unaccepted-request lifecycle; no application has occurred."""

    if not state.request_pending or state.response_pending:
        raise ValueError("rejection/expiry requires only a pending request")
    return replace(state, request_pending=False, response_pending=False)


def complete_response(state: State, *, fresh_exact_response: bool) -> State:
    """Clear a pending response only after the frozen exact response horizon."""

    if not state.response_pending or not fresh_exact_response:
        return state
    return replace(state, response_pending=False)


@dataclass
class Chatter:
    origin_code: int
    code: int
    movement: int = 0
    directions: tuple[int, ...] = ()


def chatter_guard(chatter: Chatter, delta: int) -> str | None:
    direction = 1 if delta > 0 else -1
    trial = chatter.directions[-3:] + (direction,)
    if len(trial) == 4 and sum(left != right for left, right in zip(trial, trial[1:])) == 3:
        return "prospective_repeated_alternation"
    path = chatter.movement + abs(delta)
    if path >= 42 and Fraction(abs(chatter.code + delta - chatter.origin_code), path) <= Fraction(1, 4):
        return "prospective_low_efficiency_path"
    return None


def apply_chatter(chatter: Chatter, delta: int) -> Chatter:
    return Chatter(chatter.origin_code, chatter.code + delta, chatter.movement + abs(delta),
                   chatter.directions + ((1 if delta > 0 else -1),))


def _source_rows(bound: Mapping[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    root = Path(bound["run_dir"])
    return _read_csv(root / "csv/active_hybrid_decisions_v1.csv"), _read_csv(root / "csv/active_transactions_v1.csv")


def _exact_prefix(contract: Mapping[str, Any], bound: Mapping[str, Any], decisions: list[dict[str, str]], transactions: list[dict[str, str]]) -> dict[str, Any]:
    frozen = contract["frozen_evaluation"]["exact_physical_prefix"]
    terminal = contract["observed_terminal"]
    expected_sequences = list(range(1, terminal["decision_count"] + 1))
    if [_int(row["decision_sequence"], "decision_sequence") for row in decisions] != expected_sequences:
        raise ValueError("source decision sequence is not exact and contiguous")
    for row in decisions:
        if (row["run_identity"], row["build_identity"], row["profile_identity"]) != (bound["run_identity"], bound["firmware_build_identity"], bound["profile_identity"]):
            raise ValueError("source decision identity differs")
    applications = [row for row in transactions if row["event"] == "application"]
    if len(applications) != terminal["automatic_application_count"]:
        raise ValueError("source application count differs")
    by_sequence = {_int(row["decision_sequence"], "transaction decision sequence"): row for row in applications}
    requested = [row for row in decisions if _int(row["requested_delta_codes"], "requested delta")]
    if set(by_sequence) != {_int(row["decision_sequence"], "decision sequence") for row in requested}:
        raise ValueError("request/application identity differs")
    for row in requested:
        transaction = by_sequence[_int(row["decision_sequence"], "decision sequence")]
        if (_int(transaction["requested_delta_codes"], "transaction delta"),
            _int(transaction["applied_code"], "applied code"),
            _int(transaction["dac_epoch"], "DAC epoch")) != (
            _int(row["requested_delta_codes"], "requested delta"),
            _int(row["current_applied_code"], "current code") + _int(row["requested_delta_codes"], "requested delta"),
            _int(row["dac_epoch"], "DAC epoch") + 1):
            raise ValueError("request acceptance/application propagation differs")
    prefix = decisions[:frozen["last_exact_decision_sequence"]]
    prefix_applications = [row for row in applications if _int(row["decision_sequence"], "decision sequence") <= frozen["last_exact_decision_sequence"]]
    phase_apps = [row for row in prefix if _int(row["requested_delta_codes"], "requested delta") and _bool(row["phase_materially_influenced"], "phase material")]
    if len(prefix_applications) != frozen["expected_exact_application_count"] or len(phase_apps) != frozen["expected_exact_phase_material_application_count"]:
        raise ValueError("exact physical prefix totals differ")
    fields = ("decision_sequence", "source_first_sequence", "source_last_sequence", "accumulated_edge_error_counts", "tight_state", "relative_phase_cycles", "current_applied_code", "dac_epoch", "phase_epoch", "requested_delta_codes", "requested_code", "phase_materially_influenced", "reason")
    return {"provenance": SOURCE_REPLAY, "last_decision_sequence": frozen["last_exact_decision_sequence"],
            "decision_count": len(prefix), "application_count": len(prefix_applications),
            "phase_material_application_count": len(phase_apps),
            "semantic_transcript_sha256": canonical_sha256([{field: row[field] for field in fields} for row in prefix]),
            "candidate_identity": {candidate: "exact_source_semantics_identical_through_decision_27" for candidate in EXPECTED_CANDIDATES}}


def _baseline(rows: list[dict[str, str]]) -> dict[str, Any]:
    applications = [_int(row["requested_delta_codes"], "requested delta") for row in rows if _int(row["requested_delta_codes"], "requested delta")]
    terminal = next((row["reason"] for row in rows if row["reason"].startswith("prospective_")), None)
    reversals = sum(a != b for a, b in zip((1 if x > 0 else -1 for x in applications), (1 if x > 0 else -1 for x in applications[1:])))
    return {"candidate_id": BASELINE_ID, "provenance": SOURCE_REPLAY,
            "decision_range": [_int(rows[0]["decision_sequence"], "sequence"), _int(rows[-1]["decision_sequence"], "sequence")],
            "controller_terminal": terminal, "application_count": len(applications),
            "cumulative_absolute_movement_codes": sum(abs(item) for item in applications),
            "reversal_count": reversals, "applications": applications}


def _frontier(candidate_id: str, rows: list[dict[str, str]]) -> dict[str, Any]:
    """Use retained observations only as a counterfactual same-frontier input."""

    tagged = candidate_id == TAGGED_DEBT_ID
    state = State()
    chatter = Chatter(_int(rows[0]["current_applied_code"], "current code"), _int(rows[0]["current_applied_code"], "current code"))
    output: list[dict[str, Any]] = []
    applications: list[int] = []
    terminal: str | None = None
    for row in rows:
        phase_material = _bool(row["phase_materially_influenced"], "phase material")
        tight = row["tight_state"] == "TIGHT_INSIDE"
        if not tight or phase_material:
            state = _reset(state)
            delta = _int(row["requested_delta_codes"], "source delta")
            reason = "unchanged_frequency_acquisition" if not tight else "unchanged_phase_material"
            cap = 0
        elif row["reason"] == "request_or_response_checkpoint_outstanding":
            delta, cap, reason = 0, 0, "source_checkpoint_hold"
        else:
            identity = Identity(row["capture_session"], chatter.code, _int(row["dac_epoch"], "DAC epoch"), row["phase_epoch"],
                                _bool(row["phase_continuous"], "phase continuous") and _bool(row["phase_current"], "phase current") and not _bool(row["phase_step_detected"], "phase step"),
                                row["frequency_estimator_sha256"])
            observed = Observation(identity, _int(row["source_first_sequence"], "source first"), _int(row["source_last_sequence"], "source last"),
                                   _int(row["accumulated_edge_error_counts"], "counts"), _int(row["relative_phase_cycles"], "phase cycles"))
            decision = evaluate_maintenance(state, observed, tagged_debt=tagged)
            state, delta, cap, reason = decision.state, decision.delta, decision.cap, decision.reason
        if delta:
            guard = chatter_guard(chatter, delta)
            if guard:
                terminal, delta, reason = guard, 0, guard
            else:
                applications.append(delta)
                chatter = apply_chatter(chatter, delta)
                if tight and not phase_material:
                    state = complete_response(
                        confirm_application(
                            decision, applied_code=chatter.code,
                            dac_epoch=_int(row["dac_epoch"], "DAC epoch") + 1,
                            first_consumer_exact=True, tagged_debt=tagged,
                        ),
                        fresh_exact_response=True,
                    )
        output.append({"decision_sequence": _int(row["decision_sequence"], "sequence"), "provenance": COUNTERFACTUAL,
                       "requested_delta_codes": delta, "safe_cap_codes": cap, "reason": reason})
    directions = [1 if value > 0 else -1 for value in applications]
    return {"candidate_id": candidate_id, "provenance": COUNTERFACTUAL,
            "claim": "term_attribution_and_candidate_decision_diagnostic_not_physical_post_divergence_replay",
            "decision_range": [output[0]["decision_sequence"], output[-1]["decision_sequence"]], "first_decision": output[0],
            "controller_terminal": terminal, "application_count": len(applications),
            "cumulative_absolute_movement_codes": sum(abs(item) for item in applications),
            "reversal_count": sum(left != right for left, right in zip(directions, directions[1:])),
            "applications": applications, "decisions": output}


def _sequence(case: Mapping[str, Any], candidate_id: str) -> dict[str, Any]:
    tagged = candidate_id == TAGGED_DEBT_ID
    if case["case_id"] == "phase_material_rounding_boundary":
        details = []
        for item in case["observations"]:
            centre, _, _ = correction_interval(item["accumulated_edge_error_counts"], item["relative_phase_cycles"])
            combined, frequency_only = legacy_delta(item["accumulated_edge_error_counts"], item["relative_phase_cycles"])
            material = combined != frequency_only
            path = "unchanged_phase_material" if material else "maintenance_phase_nonmaterial"
            details.append({"centre_units": centre, "legacy_frequency_only_delta_codes": frequency_only,
                            "legacy_combined_delta_codes": combined, "path": path,
                            "pass": (centre == item["expected_combined_centre_units"] and frequency_only == item["expected_legacy_frequency_only_delta_codes"] and combined == item["expected_legacy_combined_delta_codes"] and path == item["expected_path"])})
        return {"case_id": case["case_id"], "candidate_id": candidate_id, "details": details, "pass": all(x["pass"] for x in details)}
    state = State(); chatter = Chatter(43_085, 43_085); applications: list[int] = []; reasons: list[str] = []; terminal = None; epoch = 1
    for index, (count, tight) in enumerate(zip(case["counts"], case.get("tight_states", ["TIGHT_INSIDE"] * len(case["counts"])) )):
        if case["case_id"] == "outside_tight_two_count_recovery":
            tight = "OUTSIDE"
        if tight != "TIGHT_INSIDE":
            state = _reset(state); delta = legacy_delta(count, 0)[0]; reason = "unchanged_frequency_acquisition"
        else:
            decision = evaluate_maintenance(state, Observation(Identity("fixture", chatter.code, epoch, "phase", True, "selected"), index * 600, (index + 1) * 600, count, 0), tagged_debt=tagged)
            state, delta, reason = decision.state, decision.delta, decision.reason
        if delta:
            guard = chatter_guard(chatter, delta)
            if guard:
                terminal = guard; reasons.append(guard); break
            applications.append(delta); chatter = apply_chatter(chatter, delta)
            if tight == "TIGHT_INSIDE":
                state = complete_response(
                    confirm_application(
                        decision, applied_code=chatter.code, dac_epoch=epoch + 1,
                        first_consumer_exact=True, tagged_debt=tagged,
                    ),
                    fresh_exact_response=True,
                )
                epoch += 1
        reasons.append(reason)
    passed = True
    if "expected_applications" in case: passed &= len(applications) == case["expected_applications"]
    if "expected_delta_sign" in case: passed &= bool(applications) and (1 if applications[-1] > 0 else -1) == case["expected_delta_sign"]
    if "maximum_absolute_delta_codes" in case: passed &= bool(applications) and abs(applications[-1]) <= case["maximum_absolute_delta_codes"]
    if "expected_path" in case: passed &= case["expected_path"] in reasons
    if "expected_guard" in case: passed &= terminal == case["expected_guard"]
    return {"case_id": case["case_id"], "candidate_id": candidate_id, "applications": applications, "reasons": reasons, "terminal": terminal, "pass": bool(passed)}


def bounded_debt_residual_fixture() -> dict[str, Any]:
    """Execute the frozen two-transaction debt-release fixture exactly."""

    # Explicitly keep the two candidate state machines separate.
    no_state = State(); tagged_state = State(); code = 43085; epoch = 13
    no_first = evaluate_maintenance(no_state, Observation(Identity("fixture", code, epoch, "phase-1", True, "selected"), 0, 600, -1, -4), tagged_debt=False)
    no_second = evaluate_maintenance(no_first.state, Observation(Identity("fixture", code, epoch, "phase-1", True, "selected"), 600, 1200, -1, -4), tagged_debt=False)
    tagged_first = evaluate_maintenance(tagged_state, Observation(Identity("fixture", code, epoch, "phase-1", True, "selected"), 0, 600, -1, -4), tagged_debt=True)
    tagged_second = evaluate_maintenance(tagged_first.state, Observation(Identity("fixture", code, epoch, "phase-1", True, "selected"), 600, 1200, -1, -4), tagged_debt=True)
    tagged_after_application = confirm_application(tagged_second, applied_code=43090, dac_epoch=14, first_consumer_exact=True, tagged_debt=True)
    no_after_application = confirm_application(no_second, applied_code=43090, dac_epoch=14, first_consumer_exact=True, tagged_debt=False)
    tagged_after = complete_response(tagged_after_application, fresh_exact_response=True)
    no_after = complete_response(no_after_application, fresh_exact_response=True)
    no_next_1 = evaluate_maintenance(no_after, Observation(Identity("fixture", 43090, 14, "phase-1", True, "selected"), 1800, 2400, -1, -5), tagged_debt=False)
    no_next_2 = evaluate_maintenance(no_next_1.state, Observation(Identity("fixture", 43090, 14, "phase-1", True, "selected"), 2400, 3000, -1, -5), tagged_debt=False)
    tagged_next_1 = evaluate_maintenance(tagged_after, Observation(Identity("fixture", 43090, 14, "phase-1", True, "selected"), 1800, 2400, -1, -5), tagged_debt=True)
    tagged_next_2 = evaluate_maintenance(tagged_next_1.state, Observation(Identity("fixture", 43090, 14, "phase-1", True, "selected"), 2400, 3000, -1, -5), tagged_debt=True)
    no_total = centre_to_picocodes(41)
    tagged_total = no_total + tagged_after.debt.total
    no_distance = abs(no_total - no_next_2.delta * PICOCODES_PER_CODE)
    tagged_distance = abs(tagged_total - tagged_next_2.delta * PICOCODES_PER_CODE)
    expected_residual = 341_671_780_415
    return {"case_id": "bounded_debt_residual_release", "exact": True,
            "first_hold": tagged_first.reason, "first_cap_codes": tagged_second.cap,
            "no_debt_final_delta_codes": no_next_2.delta, "tagged_debt_final_delta_codes": tagged_next_2.delta,
            "final_safe_cap_codes": tagged_next_2.cap,
            "tagged_debt_residual_picocodes": tagged_after.debt.total,
            "tagged_debt_fll_picocodes": tagged_after.debt.fll,
            "tagged_debt_pll_picocodes": tagged_after.debt.pll,
            "no_debt_total_picocodes": no_total,
            "tagged_debt_total_picocodes": tagged_total,
            "no_debt_distance_picocodes": no_distance,
            "tagged_debt_distance_picocodes": tagged_distance,
            "exact_fraction_audit_only_first_residual_codes": "1599086365/4680182727",
            "exact_fraction_audit_only_tagged_distance_codes": "31741111/173340101",
            "no_debt_transaction_count": 2, "tagged_debt_transaction_count": 2, "additional_transactions": 0,
            "pass": (no_first.reason == "persistence_first_interval_hold" and tagged_first.reason == "persistence_first_interval_hold" and no_second.delta == tagged_second.delta == 5 and tagged_second.cap == 5 and tagged_after.debt.total == expected_residual and tagged_after.debt.total == tagged_after.debt.fll + tagged_after.debt.pll and no_next_1.reason == tagged_next_1.reason == "persistence_first_interval_hold" and no_next_2.delta == 5 and tagged_next_2.delta == 6 and tagged_next_2.cap == 6 and no_distance == 475_213_574_925 and tagged_distance == 183_114_644_660)}


def fixed_point_results() -> list[dict[str, Any]]:
    """Execute the V2 fixed-point parity, clamp, and intermediate checks."""

    fixture = bounded_debt_residual_fixture()
    half_away = (
        round_half_away_from_zero(Fraction(1, 2)) == 1
        and round_half_away_from_zero(Fraction(-1, 2)) == -1
        and round_half_away_from_zero(Fraction(3, 2)) == 2
        and round_half_away_from_zero(Fraction(-3, 2)) == -2
    )
    clamp = lambda value: max(-MAX_DEBT_PICOCODES, min(MAX_DEBT_PICOCODES, value))
    clamp_boundaries = (
        clamp(MAX_DEBT_PICOCODES + 1) == MAX_DEBT_PICOCODES
        and clamp(-MAX_DEBT_PICOCODES - 1) == -MAX_DEBT_PICOCODES
        and clamp(MAX_DEBT_PICOCODES) == MAX_DEBT_PICOCODES
        and clamp(-MAX_DEBT_PICOCODES) == -MAX_DEBT_PICOCODES
    )
    maximum_centre = 332_041_393_326_771_929_088
    maximum_q_product = 44_341_403_516_250_000_000_000_000_000_000
    maximum_r_product = 1_542_141_866_250_000_000_000_000_000_000
    signed_128_maximum = 170_141_183_460_469_231_731_687_303_715_884_105_727
    quotient, remainder = divmod(maximum_centre, PICOCODE_REDUCED_DENOMINATOR)
    centres = (-maximum_centre, -41, -40, -1, 0, 1, 40, 41, maximum_centre)
    # The Fraction path is analysis-only oracle arithmetic; the controller
    # conversion above is the reduced integer quotient/remainder path.
    oracle_matches = all(
        centre_to_picocodes(centre) == round_half_away_from_zero(
            Fraction(centre * PICOCODE_REDUCED_NUMERATOR,
                     PICOCODE_REDUCED_DENOMINATOR)
        )
        for centre in centres
    )
    return [
        {"check": "controller_committed_debt_fields_are_integers", "pass": all(isinstance(value, int) for value in (fixture["tagged_debt_residual_picocodes"], fixture["tagged_debt_fll_picocodes"], fixture["tagged_debt_pll_picocodes"]))},
        {"check": "tag_sum_equals_bounded_total_residual_exactly", "pass": fixture["tagged_debt_fll_picocodes"] + fixture["tagged_debt_pll_picocodes"] == fixture["tagged_debt_residual_picocodes"]},
        {"check": "positive_and_negative_half_away_rounding_boundaries", "pass": half_away},
        {"check": "positive_and_negative_residual_clamp_boundaries", "pass": clamp_boundaries},
        {"check": "overflow_safe_reduced_quotient_remainder_proof",
         "maximum_q_times_reduced_numerator": quotient * PICOCODE_REDUCED_NUMERATOR,
         "maximum_r_times_reduced_numerator": remainder * PICOCODE_REDUCED_NUMERATOR,
         "signed_128_maximum": signed_128_maximum,
         "pass": (quotient * PICOCODE_REDUCED_NUMERATOR == maximum_q_product
                  and remainder * PICOCODE_REDUCED_NUMERATOR == maximum_r_product
                  and maximum_q_product < signed_128_maximum
                  and maximum_r_product < signed_128_maximum)},
        {"check": "independent_integer_quotient_remainder_reference_matches_Python_oracle",
         "scope": "offline reference equivalence only; native firmware parity remains a promotion gate",
         "pass": oracle_matches and fixture["pass"]},
    ]


def promotion_time_fixed_point_gates(contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Record, but do not satisfy, the V2 native-firmware promotion gates."""

    return [{"gate": gate, "status": "unmet_future_promotion_gate"}
            for gate in contract["semantic_corrections"]["promotion_time_fixed_point_checks"]]


def deterministic_sequence_results(contract: Mapping[str, Any], candidate_id: str) -> list[dict[str, Any]]:
    return [bounded_debt_residual_fixture() if case["case_id"] == "bounded_debt_residual_release" else _sequence(case, candidate_id) for case in contract["frozen_evaluation"]["deterministic_sequences"]]


def gain_no_zero_cross_proofs(contract: Mapping[str, Any]) -> list[dict[str, Any]]:
    results = []
    for gain_text in contract["frozen_evaluation"]["gain_cases"]:
        gain = Fraction(gain_text)
        for centre in (-72, -36, 36, 72):
            cap = safe_cap_codes(centre); nearest = centre - HALF_WIDTH_UNITS if centre > 0 else -(centre + HALF_WIDTH_UNITS)
            results.append({"gain": gain_text, "centre_units": centre, "safe_cap_codes": cap,
                            "pass": cap * gain <= Fraction(nearest, HZ_UNITS)})
    return results


def identity_and_fault_results(
    v1_contract: Mapping[str, Any], v2_contract: Mapping[str, Any]
) -> list[dict[str, Any]]:
    """Discriminating exact checks for every frozen identity/fault transition."""

    identity = Identity("A", 43085, 13, "P1", True, "E")
    first = evaluate_maintenance(State(), Observation(identity, 0, 600, -1, -4), tagged_debt=True).state
    overlap = evaluate_maintenance(first, Observation(identity, 500, 1100, -1, -4), tagged_debt=True)
    gap = evaluate_maintenance(first, Observation(identity, 700, 1300, -1, -4), tagged_debt=True)
    session = evaluate_maintenance(first, Observation(replace(identity, capture_session="B"), 600, 1200, -1, -4), tagged_debt=True)
    provenance = evaluate_maintenance(first, Observation(replace(identity, applied_code=43086), 600, 1200, -1, -4), tagged_debt=True)
    phase = evaluate_maintenance(replace(first, debt=Debt(200_000_000_000, 166_666_666_667)), Observation(replace(identity, phase_epoch="P2"), 600, 1200, -1, -4), tagged_debt=True)
    settling = evaluate_maintenance(first, Observation(identity, 600, 1200, -1, -4, settled=False), tagged_debt=True)
    held = enter_metadata_hold(replace(first, debt=Debt(250_000_000_000, 142_857_142_857)))
    frozen = evaluate_maintenance(held, Observation(identity, 600, 1200, -1, -4), tagged_debt=True)
    requalified = causal_requalify(held, 1200)
    post1 = evaluate_maintenance(requalified, Observation(identity, 1200, 1800, -1, -4), tagged_debt=True)
    post2 = evaluate_maintenance(post1.state, Observation(identity, 1800, 2400, -1, -4), tagged_debt=True)
    invalid = evaluate_maintenance(first, Observation(identity, 600, 1200, -1, -4, qualified=False), tagged_debt=True)
    requested = evaluate_maintenance(first, Observation(identity, 600, 1200, -1, -4), tagged_debt=True)
    rejected = reject_or_expire_request(requested.state)
    accepted = confirm_application(requested, applied_code=43090, dac_epoch=14, first_consumer_exact=True, tagged_debt=True)
    completed = complete_response(accepted, fresh_exact_response=True)
    cases = [
        ("source_overlap", overlap.state == first and overlap.reason == "source_overlap_hold" and overlap.delta == 0,
         "persistence_state_unchanged_no_debt_accrual_no_request"),
        ("source_gap", gap.state.count == 1 and gap.state.debt == Debt() and gap.reason == "source_gap_restart" and gap.delta == 0,
         "persistence_restarted_at_one_no_debt_accrual_no_request"),
        ("capture_session_change", session.state.count == 1 and session.delta == 0,
         "maintenance_state_reset_then_common_session_policy_applies"),
        ("applied_code_or_DAC_epoch_change_without_owned_application", provenance.state.fail_static,
         "actuator_provenance_fail_static"),
        ("phase_epoch_change", phase.state.count == 1 and phase.state.debt.fll == 200_000_000_000 and phase.state.debt.pll == 0,
         "persistence_reset_and_PLL_debt_discarded_without_invalidating_FLL_evidence"),
        ("settling_hold", settling.reason == "settling_hold" and settling.delta == 0,
         "persistence_reset_no_debt_accrual_no_request"),
        ("metadata_hold_and_causal_requalification", frozen.state == held and post1.delta == 0 and post1.reason == "persistence_first_interval_hold" and post2.delta != 0,
         "debt_frozen_in_hold_persistence_reset_first_window_hold_second_window_eligible"),
        ("reference_invalidity", invalid.reason == "reference_invalidity" and invalid.delta == 0,
         "maintenance_state_reset_and_existing_authoritative_fault_or_hold_semantics_unchanged"),
        ("request_rejection_or_expiry", requested.state.request_pending and not rejected.request_pending and not rejected.response_pending and rejected.debt == requested.state.debt,
         "request_pending_cleared_prior_committed_debt_unchanged_response_pending_false"),
        ("application_and_first_consumer", requested.state.request_pending and not accepted.request_pending and accepted.response_pending and accepted.debt != requested.state.debt and accepted.count == 0,
         "exact_application_commits_back_calculated_residual_resets_persistence_clears_request_pending_and_sets_response_pending"),
        ("response_completion", accepted.response_pending and not completed.response_pending and completed.debt == accepted.debt,
         "fresh_exact_response_clears_response_pending_without_changing_committed_residual"),
        ("unknown_application_or_epoch", confirm_application(requested, applied_code=43090, dac_epoch=14, first_consumer_exact=False, tagged_debt=True).fail_static and confirm_application(requested, applied_code=43091, dac_epoch=14, first_consumer_exact=True, tagged_debt=True).fail_static,
         "actuator_provenance_fail_static"),
    ]
    expected = [case["case_id"] for case in v1_contract["frozen_evaluation"]["identity_and_fault_cases"]]
    if [case_id for case_id, _, _ in cases] != expected:
        raise ValueError("identity/fault case order differs from frozen contract")
    replacements = v2_contract["semantic_corrections"]["identity_and_fault_case_replacements"]
    for case_id, _, observed in cases:
        if case_id in replacements and replacements[case_id]["expected"] != observed:
            raise ValueError("V2 identity/fault transition differs from contract")
    return [{"case_id": case_id, "expected_transition": observed, "pass": passed}
            for case_id, passed, observed in cases]


def unchanged_guard_results() -> dict[str, Any]:
    chatter = Chatter(0, 0); result = None
    for delta in (-19, 19, -19, 19):
        result = chatter_guard(chatter, delta)
        if result: break
        chatter = apply_chatter(chatter, delta)
    low = apply_chatter(Chatter(0, 0), 21)
    low_result = chatter_guard(low, -21)
    return {"alternation": {"pass": result == "prospective_repeated_alternation"},
            "low_efficiency": {"pass": low_result == "prospective_low_efficiency_path"}}


def create_report(contract_path: Path = DEFAULT_CONTRACT, *, repo_root: Path = REPO_ROOT) -> dict[str, Any]:
    contract = load_contract(contract_path)
    v1_contract = load_v1_contract(repo_root / contract["base_contract"]["path"])
    validate_v1_controller_constants(v1_contract)
    bound = validate_bound_sources(v1_contract, repo_root=repo_root)
    decisions, transactions = _source_rows(bound); prefix = _exact_prefix(v1_contract, bound, decisions, transactions)
    divergence = v1_contract["frozen_evaluation"]["exact_physical_prefix"]["expected_first_candidate_divergence_decision_sequence"]
    rows = [row for row in decisions if _int(row["decision_sequence"], "sequence") >= divergence]
    baseline = _baseline(rows); diagnostics = {candidate: _frontier(candidate, rows) for candidate in (NO_DEBT_ID, TAGGED_DEBT_ID)}
    first_action = v1_contract["frozen_evaluation"]["exact_physical_prefix"]["expected_first_candidate_action"]
    prefix_gate = all(diagnostics[candidate]["first_decision"]["requested_delta_codes"] == 0 and diagnostics[candidate]["first_decision"]["reason"] == first_action for candidate in diagnostics)
    sequences = {candidate: deterministic_sequence_results(v1_contract, candidate) for candidate in diagnostics}
    gains = gain_no_zero_cross_proofs(v1_contract)
    faults = identity_and_fault_results(v1_contract, contract)
    guards = unchanged_guard_results()
    fixed_point = fixed_point_results()
    promotion_gates = promotion_time_fixed_point_gates(contract)
    candidates = []
    for candidate in diagnostics:
        diagnostic = diagnostics[candidate]
        gates = {"exact_physical_prefix_and_first_divergence": prefix_gate,
                 "all_deterministic_sequence_expectations": all(item["pass"] for item in sequences[candidate]),
                 "all_gain_no_zero_cross_proofs": all(item["pass"] for item in gains),
                 "all_identity_and_fault_transitions": all(item["pass"] for item in faults),
                 "unchanged_alternation_and_low_efficiency_guards": all(item["pass"] for item in guards.values()),
                 "same_frontier_no_terminal_and_nonincreasing_actuator_cost": diagnostic["controller_terminal"] is None and diagnostic["application_count"] <= baseline["application_count"] and diagnostic["cumulative_absolute_movement_codes"] <= baseline["cumulative_absolute_movement_codes"] and diagnostic["reversal_count"] <= baseline["reversal_count"]}
        if list(gates) != v1_contract["selection_rule"]["common_mandatory_gates"]: raise ValueError("common gate order differs from contract")
        candidates.append({"candidate_id": candidate, "common_gates": gates, "common_gates_pass": all(gates.values()), "same_frontier_diagnostic": diagnostic, "deterministic_sequences": sequences[candidate]})
    by_id = {item["candidate_id"]: item for item in candidates}; debt_case = bounded_debt_residual_fixture()
    debt_preferred = (by_id[TAGGED_DEBT_ID]["common_gates_pass"] and debt_case["pass"] and all(item["pass"] for item in fixed_point) and debt_case["tagged_debt_distance_picocodes"] < debt_case["no_debt_distance_picocodes"] and debt_case["tagged_debt_transaction_count"] == debt_case["no_debt_transaction_count"] and all(diagnostics[TAGGED_DEBT_ID][key] <= baseline[key] for key in ("application_count", "cumulative_absolute_movement_codes", "reversal_count")))
    if debt_preferred: selected, terminal = TAGGED_DEBT_ID, "cx323_tagged_debt_candidate_selected_non_effective"
    elif by_id[NO_DEBT_ID]["common_gates_pass"]: selected, terminal = NO_DEBT_ID, "cx323_no_debt_candidate_selected_architecture_amendment_required"
    else: selected, terminal = None, "cx323_no_successor_selected"
    if terminal not in contract["terminal_outcomes"]: raise ValueError("terminal differs from frozen contract")
    report: dict[str, Any] = {"schema_version": 2, "report_type": REPORT_TYPE, "tool_id": TOOL_ID,
        "contract_id": CONTRACT_ID, "contract_sha256": EXPECTED_CONTRACT_SHA256,
        "v1_base_contract": contract["base_contract"],
        "superseded_v1_execution": contract["superseded_candidate_execution"],
        "source_validation": {key: value for key, value in bound.items() if key != "run_dir"},
        "claim_boundary": v1_contract["claim_boundary"], "exact_physical_prefix": prefix,
        "post_divergence_provenance": COUNTERFACTUAL, "unchanged_baseline_same_frontier": baseline,
        "gain_no_zero_cross_proofs": gains, "identity_and_fault_transitions": faults,
        "unchanged_guards": guards, "fixed_point_mandatory_checks": fixed_point,
        "unmet_promotion_time_fixed_point_gates": promotion_gates,
        "candidates": candidates, "tagged_debt_preference_case": debt_case,
        "selection": {"selected_candidate_id": selected, "terminal": terminal,
                      "effective_or_promoted": False, "physical_authority_granted": False}}
    report["report_sha256"] = canonical_sha256(report)
    return report


def _write_report(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = create_report(args.contract)
    if args.output: _write_report(args.output, report)
    else: print(json.dumps(report, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
