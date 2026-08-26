"""Offline equilibrium-estimator feasibility comparator.

The comparator is deliberately fail-closed.  It validates the frozen study
contract, predecessor reports, Attempt 4 replay, and every retained plant
source binding before it evaluates an equilibrium interval.  It has no live,
serial, firmware, command, DAC, or actuator surface.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable

from . import sustained_hybrid_mode_separation_study as mode_study
from . import sustained_hybrid_successor_study as successor_study


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = (
    REPO_ROOT
    / "docs/60_EXPERIMENTS/"
    "OTIS_SUSTAINED_HYBRID_EQUILIBRIUM_ESTIMATOR_FEASIBILITY_STUDY/"
    "study_contract_v1.json"
)
TOOL_ID = "otis_sustained_hybrid_equilibrium_estimator_feasibility_v1"
REPORT_TYPE = (
    "otis_sustained_hybrid_equilibrium_estimator_observability_report_v1"
)
INVALID_TERMINAL = "study_invalid_due_to_evidence_or_model_binding_failure"
NOT_OBSERVABLE_TERMINAL = (
    "equilibrium_state_not_observable_targeted_characterization_required"
)
OBSERVABLE_TERMINAL = (
    "equilibrium_state_observable_for_bounded_trajectory_study"
)


def _canonical_sha256(value: object) -> str:
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


@dataclass(frozen=True, order=True)
class ClosedInterval:
    """Exact closed interval used by the frozen set-membership construction."""

    lower: Fraction
    upper: Fraction

    def __post_init__(self) -> None:
        if self.lower > self.upper:
            raise ValueError("closed interval lower endpoint exceeds upper endpoint")

    @property
    def width(self) -> Fraction:
        return self.upper - self.lower

    def intersect(self, other: "ClosedInterval") -> "ClosedInterval | None":
        lower = max(self.lower, other.lower)
        upper = min(self.upper, other.upper)
        return None if lower > upper else ClosedInterval(lower, upper)

    def add(self, other: "ClosedInterval") -> "ClosedInterval":
        return ClosedInterval(self.lower + other.lower, self.upper + other.upper)

    def subtract(self, other: "ClosedInterval") -> "ClosedInterval":
        return ClosedInterval(self.lower - other.upper, self.upper - other.lower)

    def divide_positive(self, other: "ClosedInterval") -> "ClosedInterval":
        if other.lower <= 0:
            raise ValueError("divisor interval must be strictly positive")
        candidates = (
            self.lower / other.lower,
            self.lower / other.upper,
            self.upper / other.lower,
            self.upper / other.upper,
        )
        return ClosedInterval(min(candidates), max(candidates))

    def as_strings(self) -> dict[str, str]:
        return {
            "lower": _fraction_string(self.lower),
            "upper": _fraction_string(self.upper),
            "width": _fraction_string(self.width),
        }


def _fraction_string(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"


def count_quantization_interval(
    count_error: int,
    *,
    support_seconds: int = 600,
    perturbation_counts: int = 0,
) -> ClosedInterval:
    """Return the half-count-closed frequency interval in exact Hz fractions."""

    if support_seconds <= 0:
        raise ValueError("support_seconds must be positive")
    centre = Fraction(count_error + perturbation_counts, support_seconds)
    half_count = Fraction(1, 2 * support_seconds)
    return ClosedInterval(centre - half_count, centre + half_count)


def equilibrium_interval_from_observation(
    *,
    applied_code: int,
    frequency_error_hz: ClosedInterval,
    gain_hz_per_code: ClosedInterval,
    nuisance_hz: ClosedInterval,
) -> ClosedInterval:
    """Invert y=g(a-e)+n for the complete one-observation equilibrium set."""

    response = frequency_error_hz.subtract(nuisance_hz)
    displacement = response.divide_positive(gain_hz_per_code)
    applied = Fraction(applied_code, 1)
    return ClosedInterval(
        applied - displacement.upper,
        applied - displacement.lower,
    )


def intersect_all(intervals: Iterable[ClosedInterval]) -> ClosedInterval | None:
    iterator = iter(intervals)
    try:
        result = next(iterator)
    except StopIteration:
        raise ValueError("at least one interval is required") from None
    for interval in iterator:
        result = result.intersect(interval)
        if result is None:
            return None
    return result


def worst_integer_midpoint_return_error_codes(interval: ClosedInterval) -> int:
    """Smallest worst-case integer-code error for a closed rational interval."""

    lower_floor = interval.lower.numerator // interval.lower.denominator
    upper_ceil = -(-interval.upper.numerator // interval.upper.denominator)
    candidates = range(lower_floor, upper_ceil + 1)
    return min(
        max(abs(Fraction(code) - interval.lower), abs(Fraction(code) - interval.upper))
        for code in candidates
    ).__ceil__()


def select_terminal(
    *,
    identity_failures: list[dict[str, Any]],
    baseline_exact: bool,
    model_evaluated: bool,
    all_feasibility_checks_passed: bool,
) -> tuple[str, str]:
    if identity_failures:
        return INVALID_TERMINAL, identity_failures[0]["failure_id"]
    if not baseline_exact:
        return INVALID_TERMINAL, "exact_v1_baseline_mismatch"
    if not model_evaluated:
        return INVALID_TERMINAL, "frozen_model_not_evaluated"
    if all_feasibility_checks_passed:
        return OBSERVABLE_TERMINAL, "all_frozen_feasibility_checks_passed"
    return NOT_OBSERVABLE_TERMINAL, "first_failed_feasibility_check"


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    contract = _read_object(path)
    if (
        contract.get("schema_version") != 1
        or contract.get("contract_id")
        != "OTIS_SUSTAINED_HYBRID_EQUILIBRIUM_ESTIMATOR_FEASIBILITY_STUDY_V1"
        or contract.get("status")
        != "prospectively_frozen_before_equilibrium_results"
    ):
        raise ValueError("unsupported or unfrozen equilibrium study contract")
    claimed = contract.get("contract_sha256")
    unsigned = {
        key: value for key, value in contract.items() if key != "contract_sha256"
    }
    if claimed != _canonical_sha256(unsigned):
        raise ValueError("equilibrium study contract semantic identity differs")
    authority = contract.get("authority", {})
    forbidden = {
        "serial_access",
        "firmware_flash",
        "reset",
        "gnss_transmission",
        "dac_write",
        "control_arm",
        "physical_command_fifo",
        "physical_rehearsal",
        "live_acquisition",
        "live_activation",
        "effective_authority_creation",
    }
    if authority.get("offline_analysis") is not True or any(
        authority.get(name) is not False for name in forbidden
    ):
        raise ValueError("equilibrium study authority is not offline-only")
    if contract.get("terminal_outcomes") != [
        OBSERVABLE_TERMINAL,
        NOT_OBSERVABLE_TERMINAL,
        INVALID_TERMINAL,
    ]:
        raise ValueError("equilibrium study terminal ordering differs")
    if len(contract.get("model_hypotheses", [])) > 3:
        raise ValueError("equilibrium study freezes more than three models")
    if (
        contract.get("usefulness_gate", {}).get(
            "maximum_equilibrium_interval_span_codes"
        )
        != 18
    ):
        raise ValueError("equilibrium usefulness threshold differs")
    tool_binding = contract.get("output", {}).get("tool", {})
    tool_path = REPO_ROOT / str(tool_binding.get("path", ""))
    if (
        not tool_path.is_file()
        or tool_binding.get("sha256") != _file_sha256(tool_path)
    ):
        raise ValueError("equilibrium comparator identity differs")
    return contract


def _validate_file_bindings(
    bindings: Iterable[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    failures: list[dict[str, Any]] = []
    for binding in bindings:
        relative = str(binding["path"])
        path = REPO_ROOT / relative
        exists = path.is_file()
        actual = _file_sha256(path) if exists else None
        exact = exists and actual == binding["sha256"]
        row = {
            "path": relative,
            "role": binding["role"],
            "required": bool(binding.get("required", True)),
            "expected_sha256": binding["sha256"],
            "actual_sha256": actual,
            "exists": exists,
            "exact": exact,
        }
        rows.append(row)
        if row["required"] and not exact:
            failures.append(
                {
                    "failure_id": (
                        "required_source_missing"
                        if not exists
                        else "required_source_identity_mismatch"
                    ),
                    "path": relative,
                    "expected_sha256": binding["sha256"],
                    "actual_sha256": actual,
                }
            )
    return rows, failures


def _reproduce_predecessors(contract: dict[str, Any]) -> dict[str, Any]:
    successor = successor_study.create_comparison_report()
    mode = mode_study.create_comparison_report()
    expected = contract["predecessor_reproduction"]
    successor_exact = (
        successor["report_sha256"] == expected["successor_report_semantic_sha256"]
        and successor["terminal"] == "no_controller_successor_selected"
    )
    mode_exact = (
        mode["report_sha256"] == expected["mode_report_semantic_sha256"]
        and mode["terminal"] == "no_mode_separated_architecture_selected"
    )
    baseline = mode["exact_v1_baseline"]
    baseline_expected = contract["exact_v1_baseline"]
    baseline_exact = all(
        baseline.get(key) == value for key, value in baseline_expected.items()
    )
    return {
        "successor_report_reproduced": successor_exact,
        "successor_report_semantic_sha256": successor["report_sha256"],
        "successor_terminal": successor["terminal"],
        "mode_report_reproduced": mode_exact,
        "mode_report_semantic_sha256": mode["report_sha256"],
        "mode_terminal": mode["terminal"],
        "exact_v1_baseline_reproduced": baseline_exact,
        "exact_v1_baseline": baseline,
        "mode_classifier_replay": mode["mode_classifier_replay"],
        "source_validation": mode["source_validation"],
    }


def _attempt4_inventory(contract: dict[str, Any]) -> dict[str, Any]:
    run_dir = REPO_ROOT / contract["attempt4"]["run_dir"]
    decisions = _read_csv(run_dir / "csv/active_hybrid_decisions_v1.csv")
    transactions = _read_csv(run_dir / "csv/active_transactions_v1.csv")
    estimates = _read_csv(run_dir / "csv/estimates_v2.csv")
    phase = _read_csv(run_dir / "csv/relative_phase_observations_v1.csv")
    applications = [
        {
            "decision_sequence": int(row["decision_sequence"]),
            "decision_timestamp_s": int(row["decision_timestamp_s"]),
            "source_first_sequence": int(row["source_first_sequence"]),
            "source_last_sequence": int(row["source_last_sequence"]),
            "applied_dac_code_before": int(row["current_applied_code"]),
            "dac_epoch_before": int(row["dac_epoch"]),
            "requested_delta_codes": int(row["requested_delta_codes"]),
            "requested_code": int(row["requested_code"]),
            "phase_material": row["phase_materially_influenced"] == "true",
            "provenance": "observed_AHY_request_before_transaction",
        }
        for row in decisions
        if int(row["requested_delta_codes"]) != 0
    ]
    selected = [
        row
        for row in estimates
        if row["estimator_version"] == "cx317_selected_600s_nonoverlap_v1"
    ]
    terminal = decisions[-1]
    return {
        "evidence_class": "held_out_physical_validation_only",
        "run_dir": contract["attempt4"]["run_dir"],
        "decision_count": len(decisions),
        "transaction_record_count": len(transactions),
        "selected_600s_output_count": len(selected),
        "phase_observation_count": len(phase),
        "phase_epochs": sorted({int(row["phase_epoch"]) for row in phase}),
        "application_chronology": applications,
        "terminal": {
            "decision_sequence": int(terminal["decision_sequence"]),
            "status": terminal["state_after"],
            "reason": terminal["reason"],
            "applied_dac_code": int(terminal["current_applied_code"]),
            "dac_epoch": int(terminal["dac_epoch"]),
            "capture_session": int(terminal["capture_session"]),
            "source_first_sequence": int(terminal["source_first_sequence"]),
            "source_last_sequence": int(terminal["source_last_sequence"]),
            "phase_epoch": int(terminal["phase_epoch"]),
        },
        "modeled_candidate_continuations_eligible": False,
        "D10_used": False,
    }


def _plant_inventory(contract: dict[str, Any]) -> dict[str, Any]:
    path = REPO_ROOT / contract["plant_characterization"]["summary_path"]
    value = _read_object(path)
    visits = [
        {
            "label": item["label"],
            "code": item["code"],
            "dac_epoch": item["epoch"],
            "acknowledged_ticks": item["acknowledged_ticks"],
            "selected_600s_values_hz": item["selected_frequency_values_hz"],
            "selected_output_count": item["selected_estimate_count"],
            "settled_interval_count": item["settled_interval_count"],
            "provenance": "observed_stage5_physical_characterization",
        }
        for item in value["dwell_visits"]
    ]
    return {
        "evidence_class": "physical_characterization_identification_candidate",
        "source_immutability_verified_by_original_report": value[
            "source_immutability_verified"
        ],
        "dwell_count": len(visits),
        "dwells": visits,
        "gain_samples": value["plant_gain"],
        "natural_return_and_reversal_observations": value[
            "bidirectional_hysteresis"
        ],
        "same_code_return_observations": value["centre_repeatability"],
        "temperature_context": value["temperature_context"],
        "settling": value["settling"],
        "calibrated_or_combined_uncertainty_available": False,
    }


def create_observability_report(
    contract_path: Path = DEFAULT_CONTRACT,
) -> dict[str, Any]:
    contract_path = contract_path.resolve()
    contract = load_contract(contract_path)
    predecessor = _reproduce_predecessors(contract)
    bindings = [
        *contract["tracked_bindings"],
        *contract["attempt4"]["file_bindings"],
        *contract["plant_characterization"]["source_bindings"],
    ]
    validation_rows, identity_failures = _validate_file_bindings(bindings)
    if not predecessor["successor_report_reproduced"]:
        identity_failures.append(
            {"failure_id": "successor_report_reproduction_mismatch"}
        )
    if not predecessor["mode_report_reproduced"]:
        identity_failures.append({"failure_id": "mode_report_reproduction_mismatch"})
    baseline_exact = predecessor["exact_v1_baseline_reproduced"]
    model_evaluated = not identity_failures and baseline_exact
    terminal, first_failure = select_terminal(
        identity_failures=identity_failures,
        baseline_exact=baseline_exact,
        model_evaluated=model_evaluated,
        all_feasibility_checks_passed=False,
    )
    if model_evaluated:
        raise RuntimeError(
            "all frozen identities unexpectedly passed; estimator evaluation "
            "requires a separately reviewed comparator revision"
        )

    gate_rows = []
    gate_names = contract["feasibility_gate_order"]
    for index, name in enumerate(gate_names, start=1):
        if index == 1:
            gate_rows.append(
                {
                    "index": index,
                    "gate": name,
                    "status": "failed",
                    "passed": False,
                    "reason": first_failure,
                }
            )
        else:
            gate_rows.append(
                {
                    "index": index,
                    "gate": name,
                    "status": "not_evaluated_after_required_stage0_stop",
                    "passed": False,
                    "reason": first_failure,
                }
            )

    report: dict[str, Any] = {
        "schema_version": 1,
        "report_type": REPORT_TYPE,
        "study_identity": contract["contract_id"],
        "status": "complete_bounded_terminal",
        "terminal": terminal,
        "first_discriminating_failure": first_failure,
        "tool": {
            "tool_id": TOOL_ID,
            "path": str(Path(__file__).resolve().relative_to(REPO_ROOT)),
            "sha256": _file_sha256(Path(__file__)),
        },
        "contract": {
            "path": str(contract_path.relative_to(REPO_ROOT)),
            "contract_sha256": contract["contract_sha256"],
            "file_sha256": _file_sha256(contract_path),
        },
        "source_identity_validation": {
            "all_required_exact": not identity_failures,
            "bindings": validation_rows,
            "failures": identity_failures,
        },
        "predecessor_and_baseline_reproduction": predecessor,
        "evidence_inventory": {
            "plant_characterization": _plant_inventory(contract),
            "attempt4_validation": _attempt4_inventory(contract),
            "rapid_characterization": contract["evidence_partition"][
                "sensitivity_only"
            ],
            "excluded": contract["evidence_partition"]["excluded"],
        },
        "state_and_observation_semantics": contract[
            "state_and_observation_semantics"
        ],
        "evidence_partition": contract["evidence_partition"],
        "model_hypotheses": [
            {
                **hypothesis,
                "evaluation_status": "not_evaluated_due_to_binding_failure",
                "structural_identifiability": None,
                "complete_feasible_equilibrium_set": None,
                "held_out_prediction": None,
                "sensitivity_results": None,
            }
            for hypothesis in contract["model_hypotheses"]
        ],
        "nuisance_and_arithmetic_semantics": contract[
            "nuisance_and_arithmetic_semantics"
        ],
        "usefulness_gate": contract["usefulness_gate"],
        "uninformative_baseline": contract["uninformative_baseline"],
        "feasibility_gate_checks": gate_rows,
        "decision": {
            "terminal": terminal,
            "first_discriminating_failure": first_failure,
            "equilibrium_interval_computed": False,
            "next_gate": (
                "recover_and_identity_validate_the_exact_stage5_open_loop_plan_"
                "or_freeze_one_replacement_characterization"
            ),
        },
        "provenance_labels": {
            "observed": [
                "retained Stage 5 dwell observations",
                "retained Attempt 4 requests, applications, epochs, supports, and terminal",
            ],
            "reconstructed": [
                "exact predecessor comparator and V1 baseline replays",
            ],
            "derived": [
                "source SHA-256 comparisons and evidence inventory counts",
                "prospectively frozen usefulness threshold",
            ],
            "bounded": [
                "model and nuisance rules frozen but not numerically evaluated",
            ],
            "modeled": [],
        },
        "limitations": [
            "The exact Stage 5 open-loop plan bound by the plant model, run manifest, and characterization report is unavailable, including at the recorded source commit.",
            "No equilibrium interval, held-out prediction, sensitivity result, or observability claim was computed after the required Stage 0 stop.",
            "Attempt 4 remains a failed physical qualification because the eleven contemporaneous pre-phase-4 response-replay attestations are absent.",
            "Calibrated reference, aperture, estimator, plant, and combined uncertainty remain unavailable.",
            "Raw phase epochs were not joined, D10 was not used, and no physical boundary was exercised.",
        ],
        "authority": contract["authority"],
        "physical_actions_performed": 0,
    }
    report["report_sha256"] = _canonical_sha256(report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = create_observability_report(args.contract)
    rendered = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output is not None:
        output = args.output.resolve()
        if output.exists():
            parser.error(f"refusing to overwrite immutable report: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "complete_bounded_terminal" else 2


if __name__ == "__main__":
    raise SystemExit(main())
