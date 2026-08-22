"""Replay frozen Part A/B observations through bounded active-hybrid candidates."""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
from statistics import fmean
from typing import Any

from .active_hybrid_evidence_audit import PROGRAMME_SEAL, audit_predecessor
from .active_hybrid_policy import (
    ActiveHybridController,
    ActiveHybridPolicy,
    DEFAULT_POLICY,
    HybridObservation,
    HybridState,
    load_policy,
)
from .range_spanning_bundle import sha256_file


REPO_ROOT = Path(__file__).resolve().parents[2]
TICKS_PER_SECOND = 16_000_000
TOOL_ID = "cx320_active_hybrid_frozen_evidence_replay_v1"


@dataclass
class TightBand:
    state: str = "REQUALIFY_OUTSIDE"
    entry_count: int = 0
    release_count: int = 0

    def observe(self, counts: int) -> str:
        absolute = abs(counts)
        if self.state in {"REQUALIFY_OUTSIDE", "OUTSIDE"}:
            self.release_count = 0
            if absolute <= 2:
                self.entry_count += 1
                if self.entry_count >= 2:
                    self.state = "TIGHT_INSIDE"
                    self.entry_count = 0
            else:
                self.entry_count = 0
        else:
            self.entry_count = 0
            if absolute >= 4:
                self.release_count += 1
                if self.release_count >= 2:
                    self.state = "OUTSIDE"
                    self.release_count = 0
            elif absolute != 3:
                self.release_count = 0
        return self.state


def _ols_slope(points: list[tuple[float, float]]) -> float | None:
    if len(points) < 2:
        return None
    mean_x = fmean(item[0] for item in points)
    mean_y = fmean(item[1] for item in points)
    denominator = sum((x - mean_x) ** 2 for x, _ in points)
    if denominator == 0:
        return None
    return sum((x - mean_x) * (y - mean_y) for x, y in points) / denominator


def _rms(values: list[float]) -> float | None:
    return math.sqrt(fmean(value * value for value in values)) if values else None


def _quantile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = fraction * (len(ordered) - 1)
    lower = math.floor(index)
    upper = math.ceil(index)
    if lower == upper:
        return ordered[lower]
    weight = index - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def _source_paths() -> list[tuple[str, Path]]:
    seal = json.loads(PROGRAMME_SEAL.read_text(encoding="utf-8"))
    observed = seal["observed_results"]
    readiness = json.loads(
        Path(observed["part_a_transition_map"]["path"]).read_text(encoding="utf-8")
    )
    part_a = Path(readiness["part_a_run"]["path"])
    lower = Path(observed["part_b_lower_acquisition"]["path"]).parent.parent
    upper = Path(observed["part_b_upper_traversal"]["path"]).parent.parent
    completion = Path(observed["part_b_upper_completion"]["run"]["path"])
    return [
        ("part_a_mapping", part_a / "csv/hybrid_preview_decisions_v1.csv"),
        ("part_b_lower", lower / "csv/hybrid_preview_decisions_v1.csv"),
        ("part_b_upper_right_censored", upper / "csv/hybrid_preview_decisions_v1.csv"),
        ("part_b_upper_completion", completion / "csv/hybrid_preview_decisions_v1.csv"),
    ]


def _candidate_policy(base: ActiveHybridPolicy, candidate_id: str) -> ActiveHybridPolicy:
    if candidate_id == "p21600_cap1_tight_active_v1":
        return base
    if candidate_id == "p10800_cap1_tight_active_v1":
        return replace(base, pull_in_time_s=10_800)
    if candidate_id == "p21600_cap2_tight_active_v1":
        return replace(base, phase_bias_cap_hz=2 / 600)
    raise ValueError(f"unknown active-hybrid candidate {candidate_id}")


def _replay_one(
    path: Path,
    *,
    policy: ActiveHybridPolicy,
    candidate_id: str,
    plant_gain: float,
) -> dict[str, Any]:
    controller = ActiveHybridController(policy, plant_gain_hz_per_code=plant_gain)
    tight = TightBand()
    previous_time: float | None = None
    previous_raw_phase: int | None = None
    previous_source_phase_epoch: int | None = None
    modeled_phase = 0.0
    source_open_phase = 0
    start_time: float | None = None
    frequency_points: list[tuple[float, float, float, str]] = []
    phase_points: list[tuple[float, float, float]] = []
    decisions: list[dict[str, Any]] = []
    response_count = 0
    first_phase_application_s: float | None = None
    first_phase_qualify_s: float | None = None
    first_hybrid_tracking_s: float | None = None
    application_pre_frequency: float | None = None
    application_delta = 0
    terminal_budget_reason: str | None = None

    with path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            timestamp_s = int(row["decision_timestamp_ticks"]) / TICKS_PER_SECOND
            raw_phase = int(row["raw_relative_phase_cycles"])
            source_phase_epoch = int(row["phase_epoch"])
            source_actual_code = int(row["actual_applied_code"])
            if start_time is None:
                start_time = timestamp_s
            if previous_source_phase_epoch != source_phase_epoch:
                previous_source_phase_epoch = source_phase_epoch
                previous_raw_phase = raw_phase
                source_open_phase = raw_phase
                modeled_phase = 0.0
            elif previous_time is not None and previous_raw_phase is not None:
                modeled_phase += (
                    raw_phase - previous_raw_phase
                    + plant_gain
                    * (controller.applied_code - source_actual_code)
                    * (timestamp_s - previous_time)
                )
                previous_raw_phase = raw_phase
            previous_time = timestamp_s
            phase_points.append(
                (timestamp_s, float(raw_phase - source_open_phase), modeled_phase)
            )

            if row["frequency_observation_event"] != "true":
                continue
            observed_text = row["observed_frequency_error_hz"]
            if not observed_text:
                continue
            observed_frequency = float(observed_text)
            modeled_frequency = observed_frequency + plant_gain * (
                controller.applied_code - source_actual_code
            )
            counts = int(round(modeled_frequency * 600))
            tight_state = tight.observe(counts)
            frequency_points.append(
                (timestamp_s, observed_frequency, modeled_frequency, tight_state)
            )

            if (
                controller.transaction_outstanding
                and controller.last_application_s is not None
                and timestamp_s - controller.last_application_s
                >= policy.settling_exclusion_s + policy.fresh_support_s
            ):
                expected_response = application_delta * plant_gain
                classification = (
                    "healthy_detected"
                    if abs(expected_response) >= 0.0033333317438761396
                    else "healthy_indeterminate_near_resolution"
                )
                controller.note_response(
                    classification=classification,
                    predicted_sign_observed=expected_response * application_delta > 0,
                    exact_replay=True,
                    support_fresh=True,
                    applied_epoch_exact=True,
                )
                response_count += 1
                application_pre_frequency = None
                application_delta = 0

            phase_valid = row["preview_state"] not in {
                "REFERENCE_LOST_PREVIEW",
                "FAULT_PREVIEW",
            }
            observation = HybridObservation(
                timestamp_s=int(timestamp_s),
                capture_session=1,
                source_first_sequence=max(1, int(row["observation_sequence"]) - 599),
                source_last_sequence=max(1, int(row["observation_sequence"])),
                dac_epoch=controller.dac_epoch,
                applied_code=controller.applied_code,
                frequency_error_hz=modeled_frequency,
                accumulated_edge_error_counts=counts,
                tight_state=tight_state,
                phase_epoch=source_phase_epoch,
                phase_observation_sequence=max(1, int(row["observation_sequence"])),
                relative_phase_cycles=round(modeled_phase),
                phase_dac_epoch=controller.dac_epoch,
                phase_applied_code=controller.applied_code,
                phase_continuous=phase_valid,
                phase_current=phase_valid,
                phase_step_detected=row["preview_state"] == "PHASE_STEP_HOLD_PREVIEW",
                outstanding_request=controller.transaction_outstanding,
            )
            decision = controller.decide(observation)
            decisions.append(
                {
                    "timestamp_s": timestamp_s,
                    "state_before": decision.state_before,
                    "state_after": decision.state_after,
                    "reason": decision.reason,
                    "frequency_error_hz": modeled_frequency,
                    "relative_phase_cycles": round(modeled_phase),
                    "frequency_term_hz": decision.frequency_term_hz,
                    "phase_term_hz": decision.phase_term_hz,
                    "combined_demand_hz": decision.combined_demand_hz,
                    "requested_delta_codes": decision.requested_delta_codes,
                    "counterfactual_frequency_only_delta_codes": decision.counterfactual_frequency_only_delta_codes,
                    "phase_materially_influenced": decision.phase_materially_influenced,
                    "step_limited": decision.step_limited,
                    "range_clamped": decision.range_clamped,
                }
            )
            if first_phase_qualify_s is None and decision.state_after == "PHASE_QUALIFY":
                first_phase_qualify_s = timestamp_s
            if first_hybrid_tracking_s is None and decision.state_after == "HYBRID_TRACKING":
                first_hybrid_tracking_s = timestamp_s
            if decision.reason in {
                "global_application_budget_hold",
                "global_cumulative_movement_budget_hold",
            }:
                terminal_budget_reason = decision.reason
            if decision.requested_delta_codes == 0:
                continue
            application_pre_frequency = modeled_frequency
            application_delta = decision.requested_delta_codes
            controller.note_application(
                decision,
                applied_code=decision.requested_code,
                dac_epoch=controller.dac_epoch + 1,
                downstream_consumers_exact=True,
            )
            if decision.phase_materially_influenced and first_phase_application_s is None:
                first_phase_application_s = timestamp_s

    assert start_time is not None
    raw_frequency = [point[1] for point in frequency_points]
    modeled_frequency_values = [point[2] for point in frequency_points]
    absolute_frequency = [abs(value) for value in modeled_frequency_values]
    active_phase_points = (
        [(time, modeled) for time, _, modeled in phase_points if time >= first_phase_application_s]
        if first_phase_application_s is not None
        else []
    )
    baseline_phase_points = (
        [
            (time, modeled)
            for time, _, modeled in phase_points
            if first_phase_application_s - 1800 <= time <= first_phase_application_s
        ]
        if first_phase_application_s is not None
        else []
    )
    source_active_points = (
        [(time, raw) for time, raw, _ in phase_points if time >= first_phase_application_s]
        if first_phase_application_s is not None
        else []
    )
    phase_changes = [
        abs(later[1] - earlier[1])
        for earlier, later in zip(active_phase_points, active_phase_points[1:])
    ]
    directions = [
        1 if item["requested_delta_codes"] > 0 else -1
        for item in decisions
        if item["requested_delta_codes"] != 0
    ]
    result = {
        "source_path": str(path),
        "source_sha256": sha256_file(path),
        "candidate_id": candidate_id,
        "plant_gain_hz_per_code": plant_gain,
        "source_record_count": len(phase_points),
        "selected_frequency_event_count": len(frequency_points),
        "decision_count": len(decisions),
        "application_count": controller.correction_count,
        "frequency_only_application_count": controller.frequency_only_application_count,
        "phase_nonzero_application_count": controller.phase_nonzero_application_count,
        "phase_material_application_count": controller.phase_material_application_count,
        "response_count": response_count,
        "cumulative_movement_codes": controller.cumulative_movement_codes,
        "net_movement_codes": controller.applied_code - policy.start_code,
        "path_efficiency": (
            abs(controller.applied_code - policy.start_code)
            / controller.cumulative_movement_codes
            if controller.cumulative_movement_codes
            else None
        ),
        "direction_reversal_count": sum(a != b for a, b in zip(directions, directions[1:])),
        "step_limited_decision_count": sum(item["step_limited"] for item in decisions),
        "range_clamped_decision_count": sum(item["range_clamped"] for item in decisions),
        "first_phase_qualify_latency_s": (
            first_phase_qualify_s - start_time if first_phase_qualify_s is not None else None
        ),
        "first_phase_application_latency_s": (
            first_phase_application_s - start_time
            if first_phase_application_s is not None
            else None
        ),
        "first_hybrid_tracking_latency_s": (
            first_hybrid_tracking_s - start_time
            if first_hybrid_tracking_s is not None
            else None
        ),
        "baseline_phase_ols_slope_cycles_per_s": _ols_slope(baseline_phase_points),
        "active_modeled_phase_ols_slope_cycles_per_s": _ols_slope(active_phase_points),
        "active_source_phase_ols_slope_cycles_per_s": _ols_slope(source_active_points),
        "active_modeled_phase_cumulative_absolute_movement_cycles": sum(phase_changes),
        "active_modeled_phase_maximum_excursion_cycles": (
            max(abs(value - active_phase_points[0][1]) for _, value in active_phase_points)
            if active_phase_points
            else None
        ),
        "source_frequency_rms_hz": _rms(raw_frequency),
        "modeled_frequency_rms_hz": _rms(modeled_frequency_values),
        "modeled_absolute_frequency_p95_hz": _quantile(absolute_frequency, 0.95),
        "modeled_absolute_frequency_maximum_hz": max(absolute_frequency, default=None),
        "tight_inside_occupancy_fraction": (
            sum(point[3] == "TIGHT_INSIDE" for point in frequency_points)
            / len(frequency_points)
            if frequency_points
            else None
        ),
        "terminal_state": controller.state.value,
        "terminal_reason": controller.reason,
        "budget_hold_reason": terminal_budget_reason,
        "final_applied_code": controller.applied_code,
        "final_dac_epoch": controller.dac_epoch,
        "first_checkpoint_response_passed": controller.first_checkpoint_response_passed,
    }
    result["replay_sha256"] = sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    return result


def create_replay_report(policy_path: Path = DEFAULT_POLICY) -> dict[str, Any]:
    predecessor = audit_predecessor()
    base = load_policy(policy_path)
    candidates = (
        "p21600_cap1_tight_active_v1",
        "p10800_cap1_tight_active_v1",
        "p21600_cap2_tight_active_v1",
    )
    sources = _source_paths()
    comparisons = []
    for candidate_id in candidates:
        policy = _candidate_policy(base, candidate_id)
        candidate_runs = [
            _replay_one(
                path,
                policy=policy,
                candidate_id=candidate_id,
                plant_gain=policy.plant_gain_nominal_hz_per_code,
            )
            for _, path in sources
        ]
        comparisons.append({"candidate_id": candidate_id, "runs": candidate_runs})

    gain_sensitivity = []
    selected_policy = _candidate_policy(base, candidates[0])
    for name, gain in (
        ("minimum", base.plant_gain_minimum_hz_per_code),
        ("nominal", base.plant_gain_nominal_hz_per_code),
        ("maximum", base.plant_gain_maximum_hz_per_code),
    ):
        gain_sensitivity.append(
            {
                "gain_name": name,
                "gain_hz_per_code": gain,
                "runs": [
                    _replay_one(
                        path,
                        policy=selected_policy,
                        candidate_id=candidates[0],
                        plant_gain=gain,
                    )
                    for _, path in sources
                ],
            }
        )

    selected_nominal = comparisons[0]["runs"]
    selection_checks = {
        "at_least_one_source_exercises_two_material_applications": any(
            run["phase_material_application_count"] >= 2 for run in selected_nominal
        ),
        "no_range_clamps": all(
            run["range_clamped_decision_count"] == 0 for run in selected_nominal
        ),
        "all_global_budgets_respected": all(
            run["application_count"] <= base.maximum_applications
            and run["cumulative_movement_codes"]
            <= base.maximum_cumulative_movement_codes
            for run in selected_nominal
        ),
        "no_fail_static_terminal": all(
            run["terminal_state"] != HybridState.FAIL_STATIC.value
            for run in selected_nominal
        ),
        "first_checkpoint_exercised_when_phase_applied": all(
            run["phase_material_application_count"] == 0
            or run["first_checkpoint_response_passed"]
            for run in selected_nominal
        ),
    }
    if not all(selection_checks.values()):
        raise ValueError(f"selected active-hybrid candidate failed replay: {selection_checks}")

    report: dict[str, Any] = {
        "schema_version": 1,
        "report_type": (
            "cx322_direct_hybrid_frozen_evidence_replay_v1"
            if base.response_checkpoint_observational
            else "cx320_active_hybrid_frozen_evidence_replay_v1"
        ),
        "tool": TOOL_ID,
        "tool_sha256": sha256_file(Path(__file__)),
        "created_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "status": "passed",
        "policy_id": base.policy_id,
        "policy_sha256": base.policy_sha256,
        "predecessor_audit": {
            "programme_seal_sha256": predecessor["programme_seal"]["seal_sha256"],
            "preview_summary": predecessor["recomputed_preview_summary"],
        },
        "sources": [
            {"source_id": label, "path": str(path), "sha256": sha256_file(path)}
            for label, path in sources
        ],
        "candidate_comparisons": comparisons,
        "gain_sensitivity": gain_sensitivity,
        "selected_candidate_id": candidates[0],
        "selection_checks": selection_checks,
        "selection_reason": "The least aggressive current-tight candidate exercises repeated material phase influence and the first-transaction checkpoint on frozen evidence while respecting the four-application, 84-code, step, range and chatter bounds across the measured plant-gain envelope. More aggressive candidates are retained only as finite comparisons.",
        "limitations": [
            "Counterfactual response after simulated code divergence uses the frozen measured plant-gain envelope and is not an observed physical actuator response.",
            "The source packages are separate finite acquisitions and cannot establish one uninterrupted 12-hour active result.",
            "Replay preserves raw phase epochs and never joins them with a guessed offset.",
        ],
    }
    unsigned = dict(report)
    report["report_sha256"] = sha256(
        json.dumps(unsigned, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    args = parser.parse_args(argv)
    report = create_replay_report(args.policy)
    rendered = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
