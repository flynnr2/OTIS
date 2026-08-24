"""Replay CX322 evidence and synthesize bounded sustained-hybrid continuations.

This is an offline design tool.  It has no serial, firmware-upload, command,
or actuator surface.  Its synthetic plant is explicitly a sensitivity model;
the retained CX322 records remain the source for observed response facts.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any

from .active_hybrid_policy import (
    ActiveHybridController,
    HybridObservation,
    HybridState,
    load_policy,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_ID = "otis_sustained_hybrid_continuation_synthesis_v1"
DEFAULT_POLICY = (
    REPO_ROOT / "profiles/discipline/otis_sustained_hybrid_regulation_v1.json"
)
DEFAULT_PREDECESSOR = (
    REPO_ROOT
    / "runs/cx322_bounded_hybrid_fact_gathering"
    / "stage5_live_attempt7_20260822T1921Z"
)


def _canonical_sha256(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _read_csv(path: Path) -> list[dict[str, str]]:
    import csv

    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _round_half_away(value: float) -> int:
    return math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5)


def _simulate(
    *,
    policy_path: Path,
    gain_hz_per_code: float,
    maximum_automatic_applications: int,
    intrinsic_frequency_error_hz: float,
    opening_phase_cycles: int,
) -> dict[str, Any]:
    base = load_policy(policy_path)
    policy = replace(
        base,
        maximum_applications=maximum_automatic_applications,
    )
    controller = ActiveHybridController(
        policy, plant_gain_hz_per_code=gain_hz_per_code, setup_application_s=0
    )
    # Continuation synthesis starts at the already proven post-checkpoint
    # HYBRID_TRACKING boundary.  Complete entry/transaction propagation is a
    # separate deterministic firmware and real-process rehearsal gate.
    controller.state = HybridState.HYBRID_TRACKING
    controller.reason = "synthetic_continuation_from_exact_CX322_checkpoint"
    controller.first_checkpoint_response_passed = True
    controller.phase_session = 1
    controller.phase_epoch = 1

    phase = float(opening_phase_cycles)
    application_due_response_s: int | None = None
    samples: list[tuple[int, float]] = []
    applications: list[dict[str, Any]] = []
    for timestamp_s in range(600, policy.qualified_duration_s + 1, 600):
        actual_frequency_error = (
            intrinsic_frequency_error_hz
            + gain_hz_per_code * (controller.applied_code - policy.start_code)
        )
        phase += actual_frequency_error * 600.0
        samples.append((timestamp_s, phase))
        if (
            controller.transaction_outstanding
            and application_due_response_s is not None
            and timestamp_s >= application_due_response_s
        ):
            controller.note_response(
                classification="healthy_detected",
                predicted_sign_observed=True,
                exact_replay=True,
                support_fresh=True,
                applied_epoch_exact=True,
            )
            application_due_response_s = None
        observation = HybridObservation(
            timestamp_s=float(timestamp_s),
            capture_session=1,
            source_first_sequence=max(1, timestamp_s - 599),
            source_last_sequence=timestamp_s,
            dac_epoch=controller.dac_epoch,
            applied_code=controller.applied_code,
            frequency_error_hz=(
                _round_half_away(actual_frequency_error * 600.0) / 600.0
            ),
            accumulated_edge_error_counts=_round_half_away(
                actual_frequency_error * 600.0
            ),
            tight_state=(
                "TIGHT_INSIDE"
                if abs(actual_frequency_error) < 4.0 / 600.0
                else "OUTSIDE"
            ),
            phase_epoch=1,
            phase_observation_sequence=timestamp_s,
            relative_phase_cycles=_round_half_away(phase),
            phase_dac_epoch=controller.dac_epoch,
            phase_applied_code=controller.applied_code,
            outstanding_request=controller.transaction_outstanding,
            outstanding_response=controller.transaction_outstanding,
        )
        decision = controller.decide(observation)
        if decision.requested_delta_codes != 0:
            controller.note_application(
                decision,
                applied_code=decision.requested_code,
                dac_epoch=controller.dac_epoch + 1,
                downstream_consumers_exact=True,
            )
            application_due_response_s = timestamp_s + 1500
            applications.append(
                {
                    "timestamp_s": timestamp_s,
                    "delta_codes": decision.requested_delta_codes,
                    "applied_code": decision.requested_code,
                    "dac_epoch": controller.dac_epoch,
                    "reason": decision.reason,
                }
            )
        if controller.state is HybridState.FAIL_STATIC:
            break

    natural = [
        item
        for item in applications
        if item["reason"] != "deliberate_reversal_challenge_request_ready"
    ]
    challenges = [
        item
        for item in applications
        if item["reason"] == "deliberate_reversal_challenge_request_ready"
    ]
    initial_direction = (
        (1 if natural[0]["delta_codes"] > 0 else -1) if natural else None
    )
    natural_reversal = next(
        (
            item
            for item in natural[1:]
            if (1 if item["delta_codes"] > 0 else -1) != initial_direction
        ),
        None,
    )
    challenge = challenges[0] if challenges else None
    challenge_recovery = (
        next(
            (
                item
                for item in natural
                if item["timestamp_s"] > challenge["timestamp_s"]
                and (1 if item["delta_codes"] > 0 else -1)
                == -(1 if challenge["delta_codes"] > 0 else -1)
            ),
            None,
        )
        if challenge is not None
        else None
    )
    reversal = challenge_recovery if challenge is not None else natural_reversal
    final_samples = [item for item in samples if item[0] >= policy.qualified_duration_s - 21_600]
    final_slope: float | None = None
    if len(final_samples) >= 2:
        x_mean = sum(item[0] for item in final_samples) / len(final_samples)
        y_mean = sum(item[1] for item in final_samples) / len(final_samples)
        denominator = sum((item[0] - x_mean) ** 2 for item in final_samples)
        if denominator > 0.0:
            final_slope = sum(
                (x - x_mean) * (y - y_mean) for x, y in final_samples
            ) / denominator
    return {
        "gain_hz_per_code": gain_hz_per_code,
        "maximum_automatic_applications": maximum_automatic_applications,
        "intrinsic_frequency_error_hz": intrinsic_frequency_error_hz,
        "opening_phase_cycles": opening_phase_cycles,
        "applications": applications,
        "automatic_application_count": controller.automatic_application_count,
        "physical_application_count": controller.correction_count,
        "cumulative_movement_codes": controller.cumulative_movement_codes,
        "natural_reversal": natural_reversal,
        "deliberate_challenge": challenge,
        "deliberate_challenge_recovery": challenge_recovery,
        "selected_reversal": reversal,
        "post_reversal_s": (
            policy.qualified_duration_s - reversal["timestamp_s"]
            if reversal is not None
            else None
        ),
        "maximum_absolute_phase_cycles": max(abs(value) for _, value in samples),
        "final_21600s_OLS_phase_slope_cycles_per_s": final_slope,
        "fail_static": controller.state is HybridState.FAIL_STATIC,
        "terminal_code": controller.applied_code,
    }


def synthesize(
    *, predecessor_run: Path, policy_path: Path, output_path: Path
) -> dict[str, Any]:
    predecessor_run = predecessor_run.resolve()
    policy_path = policy_path.resolve()
    seal_path = predecessor_run / "reports/cx322_direct_hybrid_physical_seal_v1.json"
    seal = _read_object(seal_path)
    claimed_seal = seal.get("seal_sha256")
    unsigned_seal = {key: value for key, value in seal.items() if key != "seal_sha256"}
    seal_semantic_exact = claimed_seal == _canonical_sha256(unsigned_seal)
    if not seal_semantic_exact:
        raise ValueError("predecessor seal semantic identity differs")
    policy = load_policy(policy_path)
    active = _read_csv(predecessor_run / "csv/active_transactions_v1.csv")
    decisions = _read_csv(predecessor_run / "csv/active_hybrid_decisions_v1.csv")
    applications = [row for row in active if row.get("event") == "application"]
    responses = {
        row["request_sequence"]: row
        for row in active
        if row.get("event") == "response"
    }
    six_code = [row for row in applications if abs(int(row["requested_delta_codes"])) == 6]
    observed = [
        abs(float(responses[row["request_sequence"]]["observed_response_hz"]))
        for row in six_code
    ]
    predicted_min = 6 * policy.plant_gain_minimum_hz_per_code
    predicted_max = 6 * policy.plant_gain_maximum_hz_per_code
    response_resolution_hz = 1.0 / 600.0
    matched_response_consistent = bool(observed) and all(
        predicted_min - response_resolution_hz
        <= value
        <= predicted_max + response_resolution_hz
        for value in observed
    )

    gains = [
        policy.plant_gain_minimum_hz_per_code,
        policy.plant_gain_nominal_hz_per_code,
        policy.plant_gain_maximum_hz_per_code,
    ]
    simulations = [
        _simulate(
            policy_path=policy_path,
            gain_hz_per_code=gain,
            maximum_automatic_applications=budget,
            intrinsic_frequency_error_hz=frequency,
            opening_phase_cycles=phase,
        )
        for gain in gains
        for budget in (10, 12, 14)
        for frequency in (-1.0 / 600.0, 0.0, 1.0 / 600.0)
        for phase in (-26, 0, 26)
    ]
    simulations_bounded = all(
        not item["fail_static"]
        and item["physical_application_count"] <= 15
        and item["cumulative_movement_codes"] <= 84
        and 0xA800 <= item["terminal_code"] <= 0xAB00
        for item in simulations
    )
    default_cases = [
        item for item in simulations if item["maximum_automatic_applications"] == 12
    ]
    default_reversal_exercised = all(
        item["selected_reversal"] is not None for item in default_cases
    )
    checks = {
        "predecessor_seal_exact_and_passed": (
            seal_semantic_exact
            and seal.get("status") == "passed"
            and seal.get("primary_decision")
            == "bounded_direct_hybrid_evidence_acquired"
        ),
        "predecessor_integrity_checks_all_passed": all(
            seal.get("checks", {}).values()
        ),
        "matched_six_code_response_consistent_at_600s_resolution": matched_response_consistent,
        "all_gain_budget_frequency_phase_sensitivities_bounded": simulations_bounded,
        "default_twelve_application_cases_exercise_reversal_or_challenge_recovery": default_reversal_exercised,
        "challenge_plus_recovery_fits_shared_movement_budget": 21 + 21 <= 84,
        "policy_preserves_predecessor_gain_bounds": gains
        == [
            0.00016357422282453626,
            0.00017008467693813145,
            0.00017334010044578463,
        ],
    }
    report: dict[str, Any] = {
        "schema_version": 1,
        "report_type": "otis_sustained_hybrid_continuation_synthesis_v1",
        "tool": TOOL_ID,
        "tool_sha256": _file_sha256(Path(__file__)),
        "created_utc": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "programme_id": "OTIS_SUSTAINED_HYBRID_REGULATION_V1",
        "policy_sha256": policy.policy_sha256,
        "selected_candidate_id": "p21600_cap1_tight_active_v1",
        "predecessor": {
            "run_dir": str(predecessor_run),
            "seal_path": str(seal_path),
            "seal_file_sha256": _file_sha256(seal_path),
            "seal_sha256": claimed_seal,
            "source_run_id": seal.get("run_id"),
            "source_build_identity": seal.get("build_identity"),
            "source_uf2_sha256": seal.get("uf2_sha256"),
            "terminal_code": int(applications[-1]["applied_code"]),
            "terminal_frequency_error_hz": float(decisions[-1]["frequency_error_hz"]),
            "terminal_raw_relative_phase_cycles": int(decisions[-1]["relative_phase_cycles"]),
        },
        "matched_response": {
            "six_code_application_count": len(six_code),
            "observed_absolute_response_hz": observed,
            "predicted_absolute_response_hz": {
                "minimum": predicted_min,
                "maximum": predicted_max,
            },
            "comparison_resolution_hz": response_resolution_hz,
            "interpretation": "consistent_at_apparatus_resolution_not_a_recalibration",
        },
        "sensitivity_matrix": {
            "gain_count": len(gains),
            "automatic_application_budgets": [10, 12, 14],
            "intrinsic_frequency_errors_hz": [-1.0 / 600.0, 0.0, 1.0 / 600.0],
            "opening_phase_cycles": [-26, 0, 26],
            "case_count": len(simulations),
            "cases": simulations,
            "synthetic_boundary": "reference_controller_plus_static_gain_model_not_firmware_or_physical_propagation",
        },
        "selection_checks": checks,
        "status": "passed" if all(checks.values()) else "rejected",
    }
    report["report_sha256"] = _canonical_sha256(report)
    output_path = output_path.resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        raise FileExistsError(f"refusing to overwrite synthesis: {output_path}")
    output_path.write_text(
        json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
    )
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--predecessor-run", type=Path, default=DEFAULT_PREDECESSOR)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = synthesize(
        predecessor_run=args.predecessor_run,
        policy_path=args.policy,
        output_path=args.output,
    )
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0 if result["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
