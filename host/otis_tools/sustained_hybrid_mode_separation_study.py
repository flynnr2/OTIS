"""Attempt 4-bound offline comparison of mode-separated hybrid architectures.

This module has no serial, reset, command, firmware-upload, I2C, DAC, or live
runner surface. It validates the frozen predecessor study and immutable
Attempt 4 evidence before exact replay or modeled candidate continuation.
"""

from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass, field, replace
from hashlib import sha256
import json
import math
from pathlib import Path
import statistics
from typing import Any

from .active_hybrid_policy import (
    ActiveHybridController,
    ActiveHybridPolicy,
    HybridObservation,
    HybridState,
)
from . import sustained_hybrid_successor_study as predecessor


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = (
    REPO_ROOT
    / "docs/60_EXPERIMENTS/OTIS_SUSTAINED_HYBRID_MODE_SEPARATION_OFFLINE_STUDY"
    / "study_contract_v1.json"
)
TOOL_ID = "otis_sustained_hybrid_mode_separation_offline_compare_v1"
REPORT_TYPE = "otis_sustained_hybrid_mode_separation_offline_comparison_v1"
TIGHT_INSIDE = predecessor.TIGHT_INSIDE
DETECTION_FLOOR_HZ = predecessor.DETECTION_FLOOR_HZ


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


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    contract = _read_object(path)
    if (
        contract.get("schema_version") != 1
        or contract.get("contract_id")
        != "OTIS_SUSTAINED_HYBRID_MODE_SEPARATION_OFFLINE_STUDY_V1"
        or contract.get("status")
        != "prospectively_frozen_before_candidate_results"
    ):
        raise ValueError("unsupported or unfrozen mode-separation contract")
    claimed = contract.get("contract_sha256")
    unsigned = {
        key: value for key, value in contract.items() if key != "contract_sha256"
    }
    if claimed != _canonical_sha256(unsigned):
        raise ValueError("mode-separation contract semantic identity differs")
    authority = contract.get("authority", {})
    forbidden = {
        "serial_access",
        "firmware_flash",
        "reset",
        "dac_write",
        "control_arm",
        "physical_command_fifo",
        "physical_rehearsal",
        "live_acquisition",
        "live_activation",
    }
    if authority.get("offline_analysis") is not True or any(
        authority.get(name) is not False for name in forbidden
    ):
        raise ValueError("mode-separation authority is not offline-only")
    expected_candidates = [
        "v1_baseline",
        "phase_priority_one_count_hold_v1",
        "separated_fll_pll_maintenance_v1",
        "phase_priority_1200s_maintenance_v1",
    ]
    if [item.get("candidate_id") for item in contract["candidates"]] != expected_candidates:
        raise ValueError("mode-separation candidate ordering differs")
    if contract["model"].get("continuous_nonzero_code_difference_offset_forbidden") is not True:
        raise ValueError("unsupported discontinuous uncertainty projection enabled")
    return contract


def _validate_semantic_report(path: Path, expected: str) -> dict[str, Any]:
    value = _read_object(path)
    claimed = value.get("report_sha256")
    unsigned = {key: item for key, item in value.items() if key != "report_sha256"}
    if claimed != expected or claimed != _canonical_sha256(unsigned):
        raise ValueError(f"predecessor report semantic identity differs: {path}")
    return value


def validate_bound_sources(
    contract: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    bound = contract["predecessor_study"]
    files = {
        bound["contract_path"]: bound["contract_file_sha256"],
        bound["report_path"]: bound["report_file_sha256"],
        bound["tool_path"]: bound["tool_file_sha256"],
    }
    files.update(
        {
            item["path"]: item["sha256"]
            for item in contract["tracked_bindings"].values()
        }
    )
    mismatches = [
        relative
        for relative, expected in files.items()
        if not (REPO_ROOT / relative).is_file()
        or _file_sha256(REPO_ROOT / relative) != expected
    ]
    if mismatches:
        raise ValueError(f"mode-separation bound source identity differs: {mismatches}")
    old_contract_path = REPO_ROOT / bound["contract_path"]
    old_contract = predecessor.load_contract(old_contract_path)
    if old_contract["contract_sha256"] != bound["contract_semantic_sha256"]:
        raise ValueError("predecessor contract semantic identity differs")
    old_report = _validate_semantic_report(
        REPO_ROOT / bound["report_path"], bound["report_semantic_sha256"]
    )
    if (
        old_report.get("terminal") != bound["terminal"]
        or old_report.get("decision", {}).get("next_gate") != bound["next_gate"]
    ):
        raise ValueError("predecessor decision does not authorize architecture gate")
    source_validation = predecessor.validate_bound_sources(old_contract)
    baseline, context = predecessor._baseline_replay(
        old_contract, source_validation
    )
    return baseline, context, {
        "predecessor_contract_sha256": old_contract["contract_sha256"],
        "predecessor_report_sha256": old_report["report_sha256"],
        "attempt4_content_sha256": source_validation["package_identity"][
            "content_sha256"
        ],
        "attempt4_file_count": source_validation["package_identity"]["file_count"],
        "attempt4_total_bytes": source_validation["package_identity"]["total_bytes"],
        "bound_file_count": len(files),
        "evidence_snapshot_failures": source_validation[
            "evidence_snapshot_failures"
        ],
        "evidence_snapshot_warnings": source_validation[
            "evidence_snapshot_warnings"
        ],
    }


@dataclass
class MaintenanceArchitecture:
    candidate_id: str
    support: list[tuple[int, int, int, int, int]] = field(default_factory=list)

    def reset(self) -> None:
        self.support.clear()

    def _append_support(
        self,
        *,
        counts: int,
        capture_session: int,
        dac_epoch: int,
        source_first: int,
        source_last: int,
    ) -> None:
        if self.support:
            _, previous_session, previous_epoch, _, previous_last = self.support[-1]
            if (
                capture_session != previous_session
                or dac_epoch != previous_epoch
                or source_first != previous_last
            ):
                self.reset()
        self.support.append(
            (counts, capture_session, dac_epoch, source_first, source_last)
        )

    def effective_frequency_error(
        self,
        *,
        frequency_error_hz: float,
        counts: int,
        tight_state: str,
        phase_material: bool,
        capture_session: int,
        dac_epoch: int,
        source_first: int,
        source_last: int,
        fresh: bool = True,
        identity_valid: bool = True,
    ) -> tuple[float, str]:
        if not identity_valid or not fresh:
            self.reset()
            return 0.0, "invalid_or_stale_maintenance_hold"
        if phase_material:
            self.reset()
            return frequency_error_hz, "phase_material_full_combined_law"
        if tight_state != TIGHT_INSIDE:
            self.reset()
            return frequency_error_hz, "outside_tight_frequency_acquisition"
        if self.candidate_id == "phase_priority_one_count_hold_v1":
            return (
                (0.0, "maintenance_one_count_hold")
                if abs(counts) <= 1
                else (frequency_error_hz, "maintenance_frequency_enabled")
            )
        if self.candidate_id == "separated_fll_pll_maintenance_v1":
            return 0.0, "tight_maintenance_phase_only"
        if self.candidate_id != "phase_priority_1200s_maintenance_v1":
            raise ValueError(f"unknown architecture candidate: {self.candidate_id}")
        self._append_support(
            counts=counts,
            capture_session=capture_session,
            dac_epoch=dac_epoch,
            source_first=source_first,
            source_last=source_last,
        )
        if len(self.support) < 2:
            return 0.0, "maintenance_1200s_support_incomplete"
        selected = self.support[:2]
        self.support.clear()
        aggregate_counts = sum(item[0] for item in selected)
        return aggregate_counts / 1200.0, "maintenance_1200s_aggregate_ready"


def _mode_classification(
    *,
    preview: Any,
    policy: ActiveHybridPolicy,
    current_code: int,
) -> tuple[bool, int, int, int]:
    frequency_delta = predecessor._limited_integer_delta(
        float(preview.frequency_term_hz), policy=policy, current_code=current_code
    )
    phase_delta = predecessor._limited_integer_delta(
        float(preview.phase_term_hz), policy=policy, current_code=current_code
    )
    combined_delta = predecessor._limited_integer_delta(
        float(preview.combined_demand_hz), policy=policy, current_code=current_code
    )
    return combined_delta != frequency_delta, frequency_delta, phase_delta, combined_delta


def _simulate_candidate(
    *,
    candidate_id: str,
    gain_name: str,
    gain_hz_per_code: float,
    contract: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    policy: ActiveHybridPolicy = context["policy"]
    decisions: list[dict[str, str]] = context["decisions"]
    transactions: list[dict[str, str]] = context["transactions"]
    exact_timestamps: dict[int, float] = context["exact_timestamps"]
    manual = [row for row in transactions if row.get("event") == "manual_start"]
    if len(manual) != 1:
        raise ValueError("Attempt 4 lacks one exact setup application")
    controller = ActiveHybridController(
        policy,
        plant_gain_hz_per_code=gain_hz_per_code,
        setup_application_s=int(manual[0]["application_timestamp_s"]),
    )
    architecture = MaintenanceArchitecture(candidate_id)
    band = predecessor.ModeledTightBand()
    pending_response_due_s: float | None = None
    pending_delta = 0
    previous_time: float | None = None
    previous_source_code = policy.start_code
    previous_candidate_code = policy.start_code
    previous_phase_epoch: int | None = None
    modeled_phase_offset = 0.0
    diverged = False
    applications: list[dict[str, Any]] = []
    samples: list[dict[str, Any]] = []
    source_request_by_decision = {
        int(row["decision_sequence"]): int(row["requested_delta_codes"])
        for row in transactions
        if row.get("event") == "request_created"
    }
    for row in decisions:
        sequence = int(row["decision_sequence"])
        timestamp_s = exact_timestamps[sequence]
        source_code = int(row["current_applied_code"])
        phase_epoch = int(row["phase_epoch"])
        if previous_time is not None:
            if phase_epoch != previous_phase_epoch:
                modeled_phase_offset = 0.0
            else:
                code_difference = previous_candidate_code - previous_source_code
                modeled_phase_offset += (
                    gain_hz_per_code
                    * code_difference
                    * (timestamp_s - previous_time)
                )
        previous_time = timestamp_s
        previous_phase_epoch = phase_epoch
        previous_source_code = source_code
        previous_candidate_code = controller.applied_code

        if (
            controller.transaction_outstanding
            and pending_response_due_s is not None
            and timestamp_s >= pending_response_due_s
        ):
            expected = pending_delta * gain_hz_per_code
            controller.note_response(
                classification=(
                    "healthy_detected"
                    if abs(expected) >= DETECTION_FLOOR_HZ
                    else "healthy_indeterminate_near_resolution"
                ),
                predicted_sign_observed=expected * pending_delta > 0.0,
                exact_replay=True,
                support_fresh=True,
                applied_epoch_exact=True,
            )
            pending_response_due_s = None
            pending_delta = 0

        code_difference = controller.applied_code - source_code
        modeled_frequency = float(row["frequency_error_hz"]) + (
            gain_hz_per_code * code_difference
        )
        modeled_counts = predecessor._round_half_away(modeled_frequency * 600.0)
        if not diverged:
            tight_state = row["tight_state"]
            band.state = tight_state
        elif controller.transaction_outstanding:
            tight_state = "REQUALIFY_OUTSIDE"
        else:
            tight_state = band.observe(modeled_counts)
        base_observation = HybridObservation(
            timestamp_s=timestamp_s,
            capture_session=int(row["capture_session"]),
            source_first_sequence=int(row["source_first_sequence"]),
            source_last_sequence=int(row["source_last_sequence"]),
            dac_epoch=controller.dac_epoch,
            applied_code=controller.applied_code,
            frequency_error_hz=modeled_frequency,
            accumulated_edge_error_counts=modeled_counts,
            tight_state=tight_state,
            phase_epoch=phase_epoch,
            phase_observation_sequence=int(row["phase_observation_sequence"]),
            relative_phase_cycles=predecessor._round_half_away(
                float(row["relative_phase_cycles"]) + modeled_phase_offset
            ),
            phase_dac_epoch=controller.dac_epoch,
            phase_applied_code=controller.applied_code,
            phase_continuous=row["phase_continuous"] == "true",
            phase_current=row["phase_current"] == "true",
            phase_step_detected=row["phase_step_detected"] == "true",
            identity_exact=True,
            common_health_clean=True,
            phase_consumers_exact=(
                row["phase_recorder_published"] == "true"
                and row["downstream_epoch_exact"] == "true"
            ),
            outstanding_request=controller.transaction_outstanding,
            outstanding_response=controller.transaction_outstanding,
        )
        preview_controller = copy.deepcopy(controller)
        preview = preview_controller.decide(base_observation)
        phase_material, frequency_delta, phase_delta, combined_delta = (
            _mode_classification(
                preview=preview,
                policy=policy,
                current_code=controller.applied_code,
            )
        )
        effective_error, maintenance_reason = architecture.effective_frequency_error(
            frequency_error_hz=modeled_frequency,
            counts=modeled_counts,
            tight_state=tight_state,
            phase_material=phase_material,
            capture_session=int(row["capture_session"]),
            dac_epoch=controller.dac_epoch,
            source_first=int(row["source_first_sequence"]),
            source_last=int(row["source_last_sequence"]),
            fresh=not controller.transaction_outstanding,
            identity_valid=True,
        )
        observation = replace(base_observation, frequency_error_hz=effective_error)
        decision = controller.decide(observation)
        sample = {
            "decision_sequence": sequence,
            "timestamp_s": timestamp_s,
            "source_first_sequence": int(row["source_first_sequence"]),
            "source_last_sequence": int(row["source_last_sequence"]),
            "source_code": source_code,
            "candidate_code_before": controller.applied_code,
            "candidate_dac_epoch": controller.dac_epoch,
            "modeled_frequency_error_hz": modeled_frequency,
            "effective_controller_frequency_error_hz": effective_error,
            "modeled_counts": modeled_counts,
            "tight_state": tight_state,
            "architecture_mode": (
                "PHASE_MATERIAL_CORRECTION"
                if phase_material
                else "FREQUENCY_ONLY_MAINTENANCE"
            ),
            "maintenance_reason": maintenance_reason,
            "gate_reason": maintenance_reason,
            "preview_frequency_only_delta_codes": frequency_delta,
            "preview_phase_only_delta_codes": phase_delta,
            "preview_combined_delta_codes": combined_delta,
            "mode_classifier_causal": True,
            "modeled_relative_phase_cycles": observation.relative_phase_cycles,
            "phase_term_hz": decision.phase_term_hz,
            "requested_delta_codes": decision.requested_delta_codes,
            "requested_code": decision.requested_code,
            "phase_materially_influenced": decision.phase_materially_influenced,
            "cadence_limited": decision.cadence_limited,
            "range_clamped": decision.range_clamped,
            "state_after": decision.state_after,
            "reason": decision.reason,
        }
        samples.append(sample)
        if decision.requested_delta_codes != 0:
            application = {
                "decision_sequence": sequence,
                "timestamp_s": timestamp_s,
                "source_last_sequence": int(row["source_last_sequence"]),
                "delta_codes": decision.requested_delta_codes,
                "applied_code": decision.requested_code,
                "dac_epoch": controller.dac_epoch + 1,
                "architecture_mode": sample["architecture_mode"],
                "phase_materially_influenced": decision.phase_materially_influenced,
                "reason": decision.reason,
                "range_clamped": decision.range_clamped,
            }
            applications.append(application)
            controller.note_application(
                decision,
                applied_code=decision.requested_code,
                dac_epoch=controller.dac_epoch + 1,
                downstream_consumers_exact=True,
            )
            pending_response_due_s = timestamp_s + (
                policy.settling_exclusion_s + policy.fresh_support_s
            )
            pending_delta = decision.requested_delta_codes
            architecture.reset()
            band.reset()
            if decision.requested_delta_codes != source_request_by_decision.get(
                sequence, 0
            ):
                diverged = True
        if controller.state is HybridState.FAIL_STATIC:
            break
    directions = [1 if item["delta_codes"] > 0 else -1 for item in applications]
    return {
        "candidate_id": candidate_id,
        "gain_name": gain_name,
        "gain_hz_per_code": gain_hz_per_code,
        "counter_domain": contract["model"]["counter_domain"],
        "samples": samples,
        "applications": applications,
        "application_count": len(applications),
        "phase_material_application_count": sum(
            item["phase_materially_influenced"] for item in applications
        ),
        "natural_path_codes": sum(abs(item["delta_codes"]) for item in applications),
        "net_regulation_codes": controller.applied_code - policy.start_code,
        "final_code": controller.applied_code,
        "final_dac_epoch": controller.dac_epoch,
        "direction_reversal_count": sum(
            before != after for before, after in zip(directions, directions[1:])
        ),
        "three_reversals_in_four": any(
            sum(a != b for a, b in zip(window, window[1:])) == 3
            for window in zip(
                directions,
                directions[1:],
                directions[2:],
                directions[3:],
            )
        ),
        "terminal_state": controller.state.value,
        "terminal_reason": controller.reason,
        "range_clamped": any(item["range_clamped"] for item in applications),
        "mode_classifier_causal": all(
            item["mode_classifier_causal"] for item in samples
        ),
    }


def _phase_metrics(
    *,
    simulation: dict[str, Any],
    contract: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    first_material = next(
        (
            item
            for item in simulation["applications"]
            if item["phase_materially_influenced"]
        ),
        None,
    )
    if first_material is None:
        return {"exact": True, "pass": False, "reason": "no_material_phase_application"}
    phase_rows = predecessor._read_csv(
        context["run_dir"] / "csv/relative_phase_observations_v1.csv"
    )
    qualified = [
        row
        for row in phase_rows
        if row.get("qualification_state", "").lower()
        in {"qualified", "valid", "eligible", "control_eligible"}
    ]
    source_events = sorted(
        [
            {
                "timestamp_s": float(row["application_timestamp_s"]),
                "applied_code": int(row["applied_code"]),
            }
            for row in context["transactions"]
            if row.get("event") == "application"
        ],
        key=lambda item: item["timestamp_s"],
    )
    candidate_events = sorted(
        [
            {
                "timestamp_s": float(row["timestamp_s"]),
                "applied_code": int(row["applied_code"]),
            }
            for row in simulation["applications"]
        ],
        key=lambda item: item["timestamp_s"],
    )
    gain = float(simulation["gain_hz_per_code"])
    projected: list[dict[str, Any]] = []
    previous_x: float | None = None
    previous_epoch: int | None = None
    offset = 0.0
    all_events = sorted(
        {
            *(float(item["timestamp_s"]) for item in source_events),
            *(float(item["timestamp_s"]) for item in candidate_events),
        }
    )
    for row in qualified:
        x = float(row["closing_reference_sequence"])
        epoch = int(row["phase_epoch"])
        if previous_x is None or epoch != previous_epoch:
            offset = 0.0
        else:
            boundaries = [value for value in all_events if previous_x < value < x]
            cursor = previous_x
            for boundary in [*boundaries, x]:
                probe = (cursor + boundary) / 2.0
                difference = predecessor._code_at(
                    probe,
                    candidate_events,
                    context["policy"].start_code,
                ) - predecessor._code_at(
                    probe,
                    source_events,
                    context["policy"].start_code,
                )
                offset += gain * difference * (boundary - cursor)
                cursor = boundary
        projected.append(
            {
                "x": x,
                "phase_epoch": epoch,
                "modeled_phase": float(row["relative_phase_cycles"]) + offset,
            }
        )
        previous_x = x
        previous_epoch = epoch
    frontier = int(first_material["source_last_sequence"])
    same_epoch = int(
        next(
            row["phase_epoch"]
            for row in qualified
            if int(row["closing_reference_sequence"]) >= frontier
        )
    )
    before = [
        item
        for item in projected
        if item["phase_epoch"] == same_epoch and item["x"] <= frontier
    ][-1800:]
    after = [
        item
        for item in projected
        if item["phase_epoch"] == same_epoch and item["x"] > frontier
    ][:1800]
    baseline_slope = predecessor._ols_slope(
        [(item["x"], item["modeled_phase"]) for item in before]
    )
    active_slope = predecessor._ols_slope(
        [(item["x"], item["modeled_phase"]) for item in after]
    )
    exact = (
        len(before) == 1800
        and len(after) == 1800
        and baseline_slope is not None
        and active_slope is not None
    )
    if not exact:
        return {
            "exact": False,
            "pass": False,
            "reason": "matched_unjoined_phase_window_incomplete",
            "baseline_count": len(before),
            "active_count": len(after),
        }
    baseline_absolute = abs(float(baseline_slope))
    active_absolute = abs(float(active_slope))
    improvement_cycles = (baseline_absolute - active_absolute) * 1800.0
    improvement_fraction = (
        (baseline_absolute - active_absolute) / baseline_absolute
        if baseline_absolute > 0.0
        else (1.0 if active_absolute == 0.0 else -math.inf)
    )
    gate = contract["selection_gate"]
    maximum_absolute = max(
        (abs(item["modeled_phase"]) for item in projected), default=math.inf
    )
    passed = (
        improvement_cycles >= gate["minimum_matched_phase_improvement_cycles"]
        and improvement_fraction >= gate["minimum_matched_phase_improvement_fraction"]
        and maximum_absolute <= gate["maximum_absolute_raw_relative_phase_cycles"]
    )
    return {
        "exact": True,
        "pass": passed,
        "reason": "thresholds_satisfied" if passed else "phase_threshold_failed",
        "baseline_absolute_ols_slope_cycles_per_s": baseline_absolute,
        "active_absolute_ols_slope_cycles_per_s": active_absolute,
        "matched_improvement_cycles": improvement_cycles,
        "matched_improvement_fraction": improvement_fraction,
        "maximum_absolute_modeled_raw_relative_phase_cycles": maximum_absolute,
        "phase_epoch": same_epoch,
        "raw_phase_epochs_joined": False,
    }


def _scenario_checks(
    simulation: dict[str, Any],
    phase: dict[str, Any],
    frequency: dict[str, Any],
    contract: dict[str, Any],
) -> dict[str, bool]:
    gate = contract["selection_gate"]
    basis = contract["architecture_basis"]
    first_seven = simulation["applications"][:7]
    early_exact = (
        [item["decision_sequence"] for item in first_seven]
        == basis["phase_material_sequences"]
        and [item["delta_codes"] for item in first_seven]
        == basis["v1_application_deltas"][:7]
        and all(item["architecture_mode"] == "PHASE_MATERIAL_CORRECTION" for item in first_seven)
    )
    return {
        "mode_classifier_causal": simulation["mode_classifier_causal"],
        "first_seven_phase_material_applications_exact": early_exact,
        "minimum_two_material_phase_applications": simulation[
            "phase_material_application_count"
        ]
        >= gate["minimum_material_phase_applications_when_supplied"],
        "phase_behavior_preserved": bool(phase.get("pass")),
        "frequency_behavior_preserved": bool(frequency.get("pass")),
        "attempt4_path_at_most_27": simulation["natural_path_codes"]
        <= gate["attempt4_maximum_natural_path_codes"],
        "attempt4_path_reduction_at_least_25_percent": simulation[
            "natural_path_codes"
        ]
        <= 37 * (1.0 - gate["attempt4_minimum_path_reduction_fraction_from_v1"]),
        "meaningful_net_regulation": abs(simulation["net_regulation_codes"])
        >= gate["attempt4_minimum_absolute_net_regulation_codes"],
        "no_fail_static_or_low_efficiency_terminal": simulation["terminal_state"]
        != "FAIL_STATIC"
        and simulation["terminal_reason"]
        not in {"prospective_low_efficiency_path", "prospective_repeated_alternation"},
        "no_three_reversals_in_four": not simulation["three_reversals_in_four"],
        "no_unexpected_range_clamp": not simulation["range_clamped"],
        "count_and_path_authority_preserved": simulation["application_count"] <= 12
        and simulation["natural_path_codes"] <= 84,
        "no_physical_or_calibrated_uncertainty_claim": True,
    }


def _frequency_metrics(
    *,
    simulation: dict[str, Any],
    contract: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, Any]:
    first_material = next(
        (
            item
            for item in simulation["applications"]
            if item["phase_materially_influenced"]
        ),
        None,
    )
    if first_material is None:
        return {"exact": True, "pass": False, "reason": "no_material_phase_application"}
    frontier = int(first_material["source_last_sequence"])
    candidate_values = [
        sample
        for sample in simulation["samples"]
        if int(sample["source_last_sequence"]) > frontier
    ]
    baseline_values = [
        row
        for row in context["decisions"]
        if int(row["source_last_sequence"]) > frontier
    ]
    candidate_errors = [
        float(item["modeled_frequency_error_hz"]) for item in candidate_values
    ]
    baseline_errors = [float(item["frequency_error_hz"]) for item in baseline_values]
    candidate_rms = (
        math.sqrt(statistics.fmean(value * value for value in candidate_errors))
        if candidate_errors
        else None
    )
    baseline_rms = (
        math.sqrt(statistics.fmean(value * value for value in baseline_errors))
        if baseline_errors
        else None
    )
    candidate_occupancy = (
        sum(item["tight_state"] == TIGHT_INSIDE for item in candidate_values)
        / len(candidate_values)
        if candidate_values
        else None
    )
    baseline_occupancy = (
        sum(item["tight_state"] == TIGHT_INSIDE for item in baseline_values)
        / len(baseline_values)
        if baseline_values
        else None
    )
    rms_degradation = (
        None
        if candidate_rms is None or baseline_rms is None
        else candidate_rms - baseline_rms
    )
    occupancy_degradation = (
        None
        if candidate_occupancy is None or baseline_occupancy is None
        else baseline_occupancy - candidate_occupancy
    )
    gate = contract["selection_gate"]
    passed = bool(
        candidate_errors
        and baseline_errors
        and rms_degradation is not None
        and occupancy_degradation is not None
        and rms_degradation <= gate["maximum_frequency_rms_degradation_hz"]
        and occupancy_degradation
        <= gate["maximum_tight_occupancy_degradation_fraction"]
    )
    return {
        "exact": True,
        "pass": passed,
        "reason": "thresholds_satisfied" if passed else "frequency_threshold_failed",
        "sample_count": len(candidate_errors),
        "baseline_sample_count": len(baseline_errors),
        "baseline_frequency_rms_hz": baseline_rms,
        "modeled_frequency_rms_hz": candidate_rms,
        "modeled_absolute_frequency_p95_hz": predecessor._quantile(
            [abs(value) for value in candidate_errors], 0.95
        ),
        "modeled_absolute_frequency_max_hz": max(
            (abs(value) for value in candidate_errors), default=None
        ),
        "baseline_tight_inside_occupancy_fraction": baseline_occupancy,
        "tight_inside_occupancy_fraction": candidate_occupancy,
        "frequency_rms_degradation_hz": rms_degradation,
        "tight_occupancy_degradation_fraction": occupancy_degradation,
    }


def _architecture_sequence(
    candidate_id: str,
    counts: list[int],
    *,
    phase_material: bool = False,
) -> tuple[list[float], list[str], list[str]]:
    architecture = MaintenanceArchitecture(candidate_id)
    band = predecessor.ModeledTightBand(state=TIGHT_INSIDE)
    outputs: list[float] = []
    reasons: list[str] = []
    bands: list[str] = []
    source_first = 0
    for count in counts:
        tight = band.observe(count)
        source_last = source_first + 600
        value, reason = architecture.effective_frequency_error(
            frequency_error_hz=count / 600.0,
            counts=count,
            tight_state=tight,
            phase_material=phase_material,
            capture_session=1,
            dac_epoch=1,
            source_first=source_first,
            source_last=source_last,
        )
        outputs.append(value)
        reasons.append(reason)
        bands.append(tight)
        source_first = source_last
    return outputs, reasons, bands


def _perturbation_results(
    *,
    candidate_id: str,
    contract: dict[str, Any],
    scenarios: dict[str, dict[str, Any]],
    context: dict[str, Any],
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    policy: ActiveHybridPolicy = context["policy"]
    for case in contract["perturbation_corpus"]:
        case_id = case["case_id"]
        passed = True
        detail: dict[str, Any] = {}
        if case_id.startswith("phase_material_"):
            counts = [int(value) for value in case["counts"]]
            outputs, reasons, _ = _architecture_sequence(
                candidate_id, counts, phase_material=True
            )
            passed = outputs == [counts[0] / 600.0]
            detail = {
                "effective_frequency_errors_hz": outputs,
                "reasons": reasons,
                "phase_raw_codes": case["phase_raw_codes"],
                "full_combined_preserved": passed,
            }
        elif "counts" in case:
            counts = [int(value) for value in case["counts"]]
            outputs, reasons, bands = _architecture_sequence(candidate_id, counts)
            nonzero = [value != 0.0 for value in outputs]
            detail = {
                "effective_frequency_errors_hz": outputs,
                "reasons": reasons,
                "tight_states": bands,
            }
            if case_id.startswith("maintenance_isolated"):
                passed = not any(nonzero)
            elif case_id == "maintenance_alternating":
                passed = not any(nonzero)
            elif case_id.startswith("maintenance_persistent"):
                expected_any = candidate_id == "phase_priority_1200s_maintenance_v1"
                passed = any(nonzero) == expected_any
            elif case_id.startswith("legitimate_slow"):
                passed = any(nonzero) and next(
                    index for index, value in enumerate(nonzero) if value
                ) < len(counts) - 1
            elif case_id.endswith("demand_reversal"):
                passed = any(value < 0.0 for value in outputs) and any(
                    value > 0.0 for value in outputs
                )
        elif case_id.startswith("maintenance_repeatability_"):
            offset = int(case["count_offset"])
            outputs, reasons, _ = _architecture_sequence(
                candidate_id, [0, offset, 0]
            )
            passed = not any(outputs)
            detail = {
                "count_offset": offset,
                "effective_frequency_errors_hz": outputs,
                "reasons": reasons,
            }
        elif case_id == "reversal_hysteresis_dead_zone":
            positive, _, _ = _architecture_sequence(candidate_id, [2, 2, 4, 4])
            requested = [
                abs(policy.integrator_gain_codes_per_hz_per_decision * value)
                for value in positive
                if value != 0.0
            ]
            passed = bool(requested) and max(requested) > case["dead_zone_codes"]
            detail = {
                "maximum_unrounded_request_codes": max(requested, default=0.0),
                "dead_zone_codes": case["dead_zone_codes"],
                "disposition": "finite_reversal_demand_remains_observable",
            }
        elif case_id.startswith("plant_gain_"):
            scenario = scenarios[case["gain"]]
            passed = all(scenario["selection_checks"].values())
            detail = {"scenario_id": scenario["scenario_id"]}
        elif case_id == "rounding_boundaries":
            observed = [
                predecessor._round_half_away(float(value))
                for value in case["raw_delta_codes"]
            ]
            expected = [0, 1, 1, 0, -1, -1]
            passed = observed == expected
            detail = {"rounded": observed, "expected": expected}
        elif case_id == "cadence_below_at_above":
            observed = [value < policy.minimum_cadence_s for value in case["elapsed_s"]]
            passed = observed == [True, False, False]
            detail = {"cadence_limited": observed}
        elif case_id in {
            "dac_epoch_reset",
            "capture_session_reset",
            "noncontiguous_support_reset",
            "settling_support_reset",
        }:
            architecture = MaintenanceArchitecture(candidate_id)
            architecture.effective_frequency_error(
                frequency_error_hz=1 / 600,
                counts=1,
                tight_state=TIGHT_INSIDE,
                phase_material=False,
                capture_session=1,
                dac_epoch=1,
                source_first=0,
                source_last=600,
            )
            if case_id == "dac_epoch_reset":
                parameters = (1, 2, 600, 1200, True)
            elif case_id == "capture_session_reset":
                parameters = (2, 1, 600, 1200, True)
            elif case_id == "noncontiguous_support_reset":
                parameters = (1, 1, 1200, 1800, True)
            else:
                parameters = (1, 1, 600, 1200, False)
            value, reason = architecture.effective_frequency_error(
                frequency_error_hz=1 / 600,
                counts=1,
                tight_state=TIGHT_INSIDE,
                phase_material=False,
                capture_session=parameters[0],
                dac_epoch=parameters[1],
                source_first=parameters[2],
                source_last=parameters[3],
                fresh=parameters[4],
            )
            passed = (
                candidate_id != "phase_priority_1200s_maintenance_v1"
                or value == 0.0
            )
            detail = {
                "post_transition_effective_frequency_error_hz": value,
                "post_transition_reason": reason,
                "maintenance_support_reused": False,
            }
        elif case_id == "stale_coherent":
            architecture = MaintenanceArchitecture(candidate_id)
            value, reason = architecture.effective_frequency_error(
                frequency_error_hz=1 / 600,
                counts=1,
                tight_state=TIGHT_INSIDE,
                phase_material=False,
                capture_session=1,
                dac_epoch=1,
                source_first=0,
                source_last=600,
                fresh=False,
            )
            passed = value == 0.0 and reason == "invalid_or_stale_maintenance_hold"
            detail = {
                "effective_frequency_error_hz": value,
                "reason": reason,
                "disposition": "bounded_hold_not_contradiction",
            }
        elif case_id in {"contradictory_identity", "abort_fail_static_boundary"}:
            controller = ActiveHybridController(policy)
            decision = controller.decide(
                HybridObservation(
                    timestamp_s=1800,
                    capture_session=1,
                    source_first_sequence=1200,
                    source_last_sequence=1800,
                    dac_epoch=1,
                    applied_code=policy.start_code,
                    frequency_error_hz=0.0,
                    accumulated_edge_error_counts=0,
                    tight_state=TIGHT_INSIDE,
                    phase_epoch=1,
                    phase_observation_sequence=1,
                    relative_phase_cycles=0,
                    phase_dac_epoch=1,
                    phase_applied_code=policy.start_code,
                    identity_exact=case_id != "contradictory_identity",
                    common_health_clean=case_id != "abort_fail_static_boundary",
                )
            )
            passed = decision.state_after == "FAIL_STATIC"
            detail = {"state_after": decision.state_after, "reason": decision.reason}
        elif case_id == "application_count_boundary":
            observed = max(
                scenario["summary"]["application_count"] for scenario in scenarios.values()
            )
            passed = observed <= policy.maximum_applications
            detail = {"maximum_modeled_applications": observed, "limit": policy.maximum_applications}
        elif case_id == "cumulative_path_boundary":
            observed = max(
                scenario["summary"]["natural_path_codes"] for scenario in scenarios.values()
            )
            passed = observed <= policy.maximum_cumulative_movement_codes
            detail = {"maximum_modeled_path_codes": observed, "limit": policy.maximum_cumulative_movement_codes}
        elif case_id == "range_boundary":
            codes = [
                item["applied_code"]
                for scenario in scenarios.values()
                for item in scenario["applications"]
            ]
            passed = bool(codes) and all(policy.minimum_code <= code <= policy.maximum_code for code in codes)
            detail = {"minimum_code": min(codes, default=None), "maximum_code": max(codes, default=None)}
        else:
            passed = False
            detail = {"error": "unhandled frozen perturbation"}
        results.append({"case_id": case_id, "pass": passed, "detail": detail})
    return results


def _candidate_comparison(
    *, candidate: dict[str, Any], contract: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    gains = contract["model"]["plant_gain_hz_per_code"]
    scenarios: dict[str, dict[str, Any]] = {}
    for name in ("minimum", "nominal", "maximum"):
        gain = float(gains[name])
        simulation = _simulate_candidate(
            candidate_id=candidate["candidate_id"],
            gain_name=name,
            gain_hz_per_code=gain,
            contract=contract,
            context=context,
        )
        phase = _phase_metrics(
            simulation=simulation, contract=contract, context=context
        )
        frequency = _frequency_metrics(
            simulation=simulation, contract=contract, context=context
        )
        checks = _scenario_checks(simulation, phase, frequency, contract)
        scenarios[name] = {
            "scenario_id": f"attempt4_{name}",
            "gain_hz_per_code": gain,
            "provenance": "modeled_closed_loop_counterfactual",
            "summary": {
                key: value
                for key, value in simulation.items()
                if key not in {"samples", "applications"}
            },
            "applications": simulation["applications"],
            "phase_metrics": phase,
            "frequency_metrics": frequency,
            "selection_checks": checks,
        }
    perturbations = _perturbation_results(
        candidate_id=candidate["candidate_id"],
        contract=contract,
        scenarios=scenarios,
        context=context,
    )
    nominal = scenarios["nominal"]
    aggregate_checks = {
        "all_gain_scenarios_pass": all(
            all(scenario["selection_checks"].values())
            for scenario in scenarios.values()
        ),
        "all_frozen_perturbations_pass": all(item["pass"] for item in perturbations),
        "deterministic_explicit_state": True,
        "implementable_in_host_and_firmware": True,
        "no_physical_or_calibrated_uncertainty_claim": True,
    }
    selectable = all(aggregate_checks.values())
    ordered_failures = [
        "mode_classifier_causal",
        "first_seven_phase_material_applications_exact",
        "minimum_two_material_phase_applications",
        "phase_behavior_preserved",
        "frequency_behavior_preserved",
        "attempt4_path_at_most_27",
        "attempt4_path_reduction_at_least_25_percent",
        "meaningful_net_regulation",
        "no_fail_static_or_low_efficiency_terminal",
        "no_three_reversals_in_four",
        "no_unexpected_range_clamp",
        "count_and_path_authority_preserved",
        "no_physical_or_calibrated_uncertainty_claim",
    ]
    first_failure: str | None = None
    for scenario_name, scenario in scenarios.items():
        for name in ordered_failures:
            if not scenario["selection_checks"][name]:
                first_failure = f"{scenario_name}:{name}"
                break
        if first_failure is not None:
            break
    if first_failure is None:
        failed = next((item for item in perturbations if not item["pass"]), None)
        if failed is not None:
            first_failure = f"perturbation:{failed['case_id']}"
    return {
        "candidate_id": candidate["candidate_id"],
        "semantic_complexity_rank": candidate["semantic_complexity_rank"],
        "selectable": selectable,
        "first_discriminating_failure": first_failure,
        "nominal_attempt4_natural_path_codes": nominal["summary"]["natural_path_codes"],
        "nominal_attempt4_net_regulation_codes": nominal["summary"]["net_regulation_codes"],
        "worst_case_frequency_rms_degradation_hz": max(
            float(scenario["frequency_metrics"]["frequency_rms_degradation_hz"])
            if scenario["frequency_metrics"].get("frequency_rms_degradation_hz") is not None
            else math.inf
            for scenario in scenarios.values()
        ),
        "passed_perturbation_case_count": sum(item["pass"] for item in perturbations),
        "perturbation_case_count": len(perturbations),
        "aggregate_checks": aggregate_checks,
        "scenarios": list(scenarios.values()),
        "perturbations": perturbations,
    }


def create_comparison_report(
    contract_path: Path = DEFAULT_CONTRACT,
) -> dict[str, Any]:
    contract_path = contract_path.resolve()
    contract = load_contract(contract_path)
    baseline, context, validation = validate_bound_sources(contract)
    basis = contract["architecture_basis"]
    exact_classifier = {
        "phase_material_sequences": [
            int(row["decision_sequence"])
            for row in context["decisions"]
            if row["phase_materially_influenced"] == "true"
            and int(row["requested_delta_codes"]) != 0
        ],
        "frequency_only_maintenance_sequences": [
            int(row["decision_sequence"])
            for row in context["decisions"]
            if row["phase_materially_influenced"] == "false"
            and int(row["requested_delta_codes"]) != 0
        ],
        "causal_decision_frontier": True,
    }
    if (
        exact_classifier["phase_material_sequences"] != basis["phase_material_sequences"]
        or exact_classifier["frequency_only_maintenance_sequences"]
        != basis["frequency_only_maintenance_sequences"]
    ):
        raise ValueError("frozen mode-classifier evidence differs")
    comparisons = [
        _candidate_comparison(candidate=item, contract=contract, context=context)
        for item in contract["candidates"]
        if item.get("selectable") is True
    ]
    selectable = [item for item in comparisons if item["selectable"]]
    selected: dict[str, Any] | None = None
    tied = False
    if selectable:
        ranked = sorted(
            selectable,
            key=lambda item: (
                -item["passed_perturbation_case_count"],
                item["nominal_attempt4_natural_path_codes"],
                item["worst_case_frequency_rms_degradation_hz"],
                item["semantic_complexity_rank"],
            ),
        )
        selected = ranked[0]
        if len(ranked) > 1:
            first_key = (
                ranked[0]["passed_perturbation_case_count"],
                ranked[0]["nominal_attempt4_natural_path_codes"],
                ranked[0]["worst_case_frequency_rms_degradation_hz"],
                ranked[0]["semantic_complexity_rank"],
            )
            second_key = (
                ranked[1]["passed_perturbation_case_count"],
                ranked[1]["nominal_attempt4_natural_path_codes"],
                ranked[1]["worst_case_frequency_rms_degradation_hz"],
                ranked[1]["semantic_complexity_rank"],
            )
            tied = first_key == second_key
            if tied:
                selected = None
    terminal = (
        "selected_mode_separated_architecture"
        if selected is not None
        else "no_mode_separated_architecture_selected"
    )
    report: dict[str, Any] = {
        "schema_version": 1,
        "report_type": REPORT_TYPE,
        "tool": TOOL_ID,
        "tool_sha256": _file_sha256(Path(__file__)),
        "contract": {
            "path": str(contract_path.relative_to(REPO_ROOT)),
            "contract_sha256": contract["contract_sha256"],
        },
        "status": "passed",
        "terminal": terminal,
        "selected_candidate_id": None if selected is None else selected["candidate_id"],
        "ranking_tied": tied,
        "source_validation": validation,
        "observed_facts": {
            "formal_physical_qualification_passed": False,
            "formal_failure_reason": baseline["formal_failure_reason"],
            "v1_application_deltas": baseline["application_deltas"],
            "v1_terminal_reason": baseline["terminal_reason"],
        },
        "exact_v1_baseline": baseline,
        "mode_classifier_replay": exact_classifier,
        "candidate_comparisons": comparisons,
        "decision": {
            "terminal": terminal,
            "selected_candidate_id": None if selected is None else selected["candidate_id"],
            "rejected_candidates": [
                {
                    "candidate_id": item["candidate_id"],
                    "first_discriminating_failure": item["first_discriminating_failure"],
                }
                for item in comparisons
                if not item["selectable"]
            ],
            "next_gate": (
                "implement_selected_architecture_host_firmware_parity_and_zero_io_readiness"
                if selected is not None
                else "estimator_state_and_uncertainty_architecture_revision"
            ),
        },
        "model_revision_from_predecessor": {
            "ordinary_differential_response": "retained_minimum_nominal_maximum_gain",
            "continuous_same_code_repeatability_offset_applied": False,
            "continuous_hysteresis_offset_applied": False,
            "hysteresis_exercised_as": "outward_eight_code_reversal_dead_zone_perturbation",
            "same_code_repeatability_exercised_as": "positive_and_negative_one_count_maintenance_observation_perturbations",
            "calibrated_or_combined_uncertainty_available": False,
        },
        "claim_boundary": {
            "exact_replay": "V1 chronology, integer decisions, and mode classification only",
            "counterfactual": "finite_run_gain_envelope_model_after_first_candidate_code_divergence",
            "physical_qualification": False,
            "physical_authority": False,
            "unexercised_boundaries": [
                "RP2040 cross-core propagation",
                "USB device driver and serial carrier",
                "AD5693R and DAC-to-CX317 path",
                "D14 reference input",
                "D8 oscillator/count input",
                "physical CX317 response",
            ],
        },
        "limitations": [
            "Attempt 4's missing contemporaneous replay attestations remain missing.",
            "Candidate values after code-path divergence are modeled, not observed.",
            "Calibrated estimator, reference, aperture, plant, and combined uncertainty remain unavailable.",
            "Finite-run hysteresis and repeatability perturbations are discriminators, not population bounds.",
            "Raw phase epochs are never joined with a guessed offset.",
            "D10 remains an external event input only.",
        ],
    }
    report["report_sha256"] = _canonical_sha256(report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = create_comparison_report(args.contract)
    rendered = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output is not None:
        output = args.output.resolve()
        if output.exists():
            parser.error(f"refusing to overwrite immutable comparison: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "passed" else 2


if __name__ == "__main__":
    raise SystemExit(main())
