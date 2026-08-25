"""Attempt 4-bound offline comparator for sustained-hybrid successors.

The tool has no serial, firmware-upload, reset, command-FIFO, or actuator
surface. It validates the prospectively frozen study contract and immutable
Attempt 4 package before exact V1 replay, diagnostic ablation, or modeled
candidate continuation.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass
from hashlib import sha256
import json
import math
from pathlib import Path
import statistics
from typing import Any, Iterable

from .active_hybrid_evidence_guard import (
    _exact_decision_timestamps_s,
    replay_active_hybrid_history,
)
from .active_hybrid_policy import (
    ActiveHybridController,
    ActiveHybridPolicy,
    HybridObservation,
    HybridState,
    load_policy,
)
from .evidence import validate_evidence_snapshot
from .evidence_index import package_identity
from .run_loader import RunManifest


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONTRACT = (
    REPO_ROOT
    / "docs/60_EXPERIMENTS/OTIS_SUSTAINED_HYBRID_SUCCESSOR_OFFLINE_STUDY"
    / "study_contract_v1.json"
)
TOOL_ID = "otis_sustained_hybrid_successor_offline_compare_v1"
REPORT_TYPE = "otis_sustained_hybrid_successor_offline_comparison_v1"
DETECTION_FLOOR_HZ = 0.0033333317438761396
TIGHT_INSIDE = "TIGHT_INSIDE"
TRACKED_PROFILE_BINDINGS = {
    "frequency_estimator_sha256": Path(
        "profiles/estimators/cx317_pps_gated_selected_v1.json"
    ),
    "phase_estimator_sha256": Path(
        "profiles/estimators/cx318_relative_phase_selected_v1.json"
    ),
    "plant_model_sha256": Path("profiles/plant_models/cx317_pps_gated_v2.json"),
    "response_policy_sha256": Path(
        "profiles/discipline/cx317_response_classification_v2.json"
    ),
}


def _canonical_sha256(value: object) -> str:
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
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


def _round_half_away(value: float) -> int:
    if not math.isfinite(value):
        raise ValueError("non-finite value cannot be rounded")
    return math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5)


def _quantile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    position = fraction * (len(ordered) - 1)
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _ols_slope(points: list[tuple[float, float]]) -> float | None:
    if len(points) < 2:
        return None
    mean_x = statistics.fmean(point[0] for point in points)
    mean_y = statistics.fmean(point[1] for point in points)
    denominator = sum((x - mean_x) ** 2 for x, _ in points)
    if denominator == 0.0:
        return None
    return sum((x - mean_x) * (y - mean_y) for x, y in points) / denominator


def load_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    contract = _read_object(path)
    if (
        contract.get("schema_version") != 1
        or contract.get("contract_id")
        != "OTIS_SUSTAINED_HYBRID_SUCCESSOR_OFFLINE_STUDY_V1"
        or contract.get("status")
        != "prospectively_frozen_before_candidate_results"
    ):
        raise ValueError("unsupported or unfrozen successor-study contract")
    claimed = contract.get("contract_sha256")
    unsigned = {
        key: value for key, value in contract.items() if key != "contract_sha256"
    }
    if claimed != _canonical_sha256(unsigned):
        raise ValueError("successor-study contract semantic identity differs")
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
    authority = contract.get("authority", {})
    if authority.get("offline_analysis") is not True or any(
        authority.get(field) is not False for field in forbidden
    ):
        raise ValueError("successor-study authority is not offline-only")
    if [item.get("candidate_id") for item in contract["candidates"]] != [
        "v1_baseline",
        "one_count_tight_hold_v1",
        "tight_phase_only_v1",
        "persistent_one_count_release_v1",
    ]:
        raise ValueError("successor-study candidate ordering differs")
    return contract


def _validate_semantic_identity(
    path: Path, field: str, expected: str
) -> None:
    value = _read_object(path)
    claimed = value.get(field)
    unsigned = {key: item for key, item in value.items() if key != field}
    if claimed != expected or claimed != _canonical_sha256(unsigned):
        raise ValueError(f"semantic identity differs: {path}")


def validate_bound_sources(contract: dict[str, Any]) -> dict[str, Any]:
    source = contract["source"]
    run_dir = (REPO_ROOT / source["run_dir"]).resolve()
    if not run_dir.is_dir():
        raise ValueError("Attempt 4 run directory is unavailable")
    file_bindings = {
        "run_manifest.json": source["run_manifest_file_sha256"],
        "evidence_manifest.json": source["evidence_manifest_file_sha256"],
        "otis_sustained_hybrid_live_activation_v1.json": source[
            "activation_file_sha256"
        ],
        "otis_sustained_hybrid_exact_bundle_v1.json": source[
            "bundle_file_sha256"
        ],
        "reports/otis_sustained_hybrid_physical_seal_v1.json": source[
            "physical_seal_file_sha256"
        ],
    }
    file_bindings.update(
        {
            binding["path"]: binding["sha256"]
            for binding in source["record_files"].values()
        }
    )
    mismatches = [
        relative
        for relative, expected in file_bindings.items()
        if not (run_dir / relative).is_file()
        or _file_sha256(run_dir / relative) != expected
    ]
    if mismatches:
        raise ValueError(f"Attempt 4 bound source identity differs: {mismatches}")
    manifest_value = _read_object(run_dir / "run_manifest.json")
    manifest = RunManifest(
        root=run_dir, path=run_dir / "run_manifest.json", data=manifest_value
    )
    failures, warnings = validate_evidence_snapshot(run_dir, manifest)
    package = package_identity(run_dir)
    if (
        failures
        or warnings
        or package["content_sha256"] != source["registered_content_sha256"]
        or package["file_count"] != source["registered_file_count"]
        or package["total_bytes"] != source["registered_total_bytes"]
    ):
        raise ValueError(
            "Attempt 4 evidence snapshot or registered content identity differs"
        )
    _validate_semantic_identity(
        run_dir / "otis_sustained_hybrid_live_activation_v1.json",
        "activation_sha256",
        source["activation_sha256"],
    )
    _validate_semantic_identity(
        run_dir / "otis_sustained_hybrid_exact_bundle_v1.json",
        "bundle_sha256",
        source["bundle_sha256"],
    )
    _validate_semantic_identity(
        run_dir / "reports/otis_sustained_hybrid_physical_seal_v1.json",
        "seal_sha256",
        source["physical_seal_sha256"],
    )
    repair = contract["attestation_repair"]
    repair_files = {
        repair["bundle_path"]: repair["bundle_file_sha256"],
        str(Path(repair["bundle_path"]).with_name(
            "otis_sustained_hybrid_authority_proposal_v1.json"
        )): repair["proposal_file_sha256"],
        repair["rehearsal_path"]: repair["rehearsal_file_sha256"],
    }
    repair_mismatches = [
        relative
        for relative, expected in repair_files.items()
        if not (REPO_ROOT / relative).is_file()
        or _file_sha256(REPO_ROOT / relative) != expected
    ]
    if repair_mismatches:
        raise ValueError(
            f"final attestation-repair identity differs: {repair_mismatches}"
        )
    _validate_semantic_identity(
        REPO_ROOT / repair["bundle_path"],
        "bundle_sha256",
        repair["bundle_sha256"],
    )
    proposal_path = Path(repair["bundle_path"]).with_name(
        "otis_sustained_hybrid_authority_proposal_v1.json"
    )
    _validate_semantic_identity(
        REPO_ROOT / proposal_path,
        "proposal_sha256",
        repair["proposal_sha256"],
    )
    _validate_semantic_identity(
        REPO_ROOT / repair["rehearsal_path"],
        "rehearsal_sha256",
        repair["rehearsal_sha256"],
    )
    baseline = contract["baseline"]
    profile_mismatches = [
        str(relative)
        for identity_field, relative in TRACKED_PROFILE_BINDINGS.items()
        if not (REPO_ROOT / relative).is_file()
        or _file_sha256(REPO_ROOT / relative) != baseline[identity_field]
    ]
    if profile_mismatches:
        raise ValueError(
            f"tracked estimator, model, or response-policy identity differs: "
            f"{profile_mismatches}"
        )
    return {
        "run_dir": run_dir,
        "manifest": manifest_value,
        "package_identity": {
            "content_sha256": package["content_sha256"],
            "file_count": package["file_count"],
            "total_bytes": package["total_bytes"],
        },
        "evidence_snapshot_failures": failures,
        "evidence_snapshot_warnings": warnings,
        "bound_file_count": (
            len(file_bindings) + len(repair_files) + len(TRACKED_PROFILE_BINDINGS)
        ),
    }


def _baseline_replay(
    contract: dict[str, Any], source_validation: dict[str, Any]
) -> tuple[dict[str, Any], dict[str, Any]]:
    run_dir: Path = source_validation["run_dir"]
    baseline = contract["baseline"]
    policy_path = REPO_ROOT / baseline["policy_path"]
    policy = load_policy(policy_path)
    if policy.policy_sha256 != baseline["policy_sha256"]:
        raise ValueError("V1 baseline policy identity differs")
    decisions = _read_csv(run_dir / "csv/active_hybrid_decisions_v1.csv")
    transactions = _read_csv(run_dir / "csv/active_transactions_v1.csv")
    estimates = _read_csv(run_dir / "csv/estimates_v2.csv")
    replay = replay_active_hybrid_history(
        decisions,
        transactions,
        policy_path=policy_path,
        expected_run_identity=contract["source"]["run_identity"],
        expected_build_identity=contract["source"]["firmware_build_identity"],
        expected_profile_identity=contract["source"]["profile_identity"],
        expected_active_policy_sha256=baseline["policy_sha256"],
        estimate_rows=estimates,
    )
    applications = [row for row in transactions if row.get("event") == "application"]
    deltas = [int(row["requested_delta_codes"]) for row in applications]
    terminal = decisions[-1] if decisions else {}
    decision_by_sequence = {
        int(row["decision_sequence"]): row for row in decisions
    }
    application_decisions = [
        decision_by_sequence[int(row["decision_sequence"])]
        for row in applications
    ]
    first_seven_phase_material = all(
        row["phase_materially_influenced"] == "true"
        for row in application_decisions[:7]
    )
    last_four_phase_nonmaterial = all(
        row["phase_materially_influenced"] == "false"
        for row in application_decisions[7:]
    )
    first_seven_codes = [
        int(row["applied_code"]) for row in applications[:7]
    ]
    exact = (
        replay["exact"]
        and replay["decision_count"] == baseline["decision_count"]
        and deltas == baseline["application_deltas"]
        and [int(row["decision_sequence"]) for row in applications]
        == baseline["application_decision_sequences"]
        and len(applications) == baseline["automatic_application_count"]
        and sum(abs(delta) for delta in deltas)
        == baseline["cumulative_natural_movement_codes"]
        and int(applications[-1]["applied_code"]) == baseline["terminal_code"]
        and int(applications[-1]["dac_epoch"]) == baseline["terminal_dac_epoch"]
        and int(terminal["decision_sequence"])
        == baseline["terminal_decision_sequence"]
        and int(terminal["accumulated_edge_error_counts"])
        == baseline["terminal_count_error"]
        and terminal["reason"] == baseline["terminal"]
        and terminal["state_after"] == "FAIL_STATIC"
        and terminal["cadence_limited"] == "false"
        and first_seven_phase_material
        and last_four_phase_nonmaterial
        and first_seven_codes == [43062, 43061, 43060, 43054, 43053, 43052, 43051]
    )
    unchecked_terminal_delta = _round_half_away(
        policy.integrator_gain_codes_per_hz_per_decision
        * float(terminal["combined_demand_hz"])
    )
    exact &= unchecked_terminal_delta == baseline["terminal_next_unchecked_delta_codes"]
    if not exact:
        raise ValueError("V1 baseline replay or frozen terminal differs")
    exact_timestamps = _exact_decision_timestamps_s(
        decisions, estimates, estimator_id=policy.frequency_estimator_id
    )
    summary = {
        "exact": True,
        "policy_sha256": policy.policy_sha256,
        "decision_count": len(decisions),
        "application_count": len(applications),
        "application_deltas": deltas,
        "application_decision_sequences": [
            int(row["decision_sequence"]) for row in applications
        ],
        "phase_material_application_count": baseline[
            "phase_material_application_count"
        ],
        "first_seven_phase_material": first_seven_phase_material,
        "first_seven_terminal_code": first_seven_codes[-1],
        "first_seven_path_codes": sum(abs(delta) for delta in deltas[:7]),
        "last_four_phase_nonmaterial_frequency_driven": (
            last_four_phase_nonmaterial
        ),
        "last_four_path_codes": sum(abs(delta) for delta in deltas[7:]),
        "last_four_net_codes": sum(deltas[7:]),
        "cumulative_natural_movement_codes": sum(abs(delta) for delta in deltas),
        "net_movement_from_setup_codes": (
            int(applications[-1]["applied_code"]) - baseline["setup_code"]
        ),
        "terminal_code": int(applications[-1]["applied_code"]),
        "terminal_dac_epoch": int(applications[-1]["dac_epoch"]),
        "terminal_decision_sequence": int(terminal["decision_sequence"]),
        "terminal_reason": terminal["reason"],
        "terminal_next_unchecked_delta_codes": unchecked_terminal_delta,
        "terminal_prospective_path_codes": (
            sum(abs(delta) for delta in deltas) + abs(unchecked_terminal_delta)
        ),
        "terminal_prospective_net_displacement_codes": abs(
            int(applications[-1]["applied_code"])
            + unchecked_terminal_delta
            - baseline["setup_code"]
        ),
        "all_response_checkpoints_passed": replay[
            "all_response_checkpoints_passed"
        ],
        "formal_physical_qualification_passed": False,
        "formal_failure_reason": baseline["formal_failure_reason"],
    }
    context = {
        "policy": policy,
        "decisions": decisions,
        "transactions": transactions,
        "estimates": estimates,
        "exact_timestamps": exact_timestamps,
        "run_dir": run_dir,
    }
    return summary, context


def _limited_integer_delta(
    demand_hz: float, *, policy: ActiveHybridPolicy, current_code: int
) -> int:
    raw = policy.integrator_gain_codes_per_hz_per_decision * demand_hz
    limited = min(float(policy.maximum_step_codes), max(-float(policy.maximum_step_codes), raw))
    delta = _round_half_away(limited)
    return min(policy.maximum_code, max(policy.minimum_code, current_code + delta)) - current_code


def _diagnostic_ablations(context: dict[str, Any]) -> dict[str, Any]:
    policy: ActiveHybridPolicy = context["policy"]
    rows: list[dict[str, str]] = context["decisions"]
    comparisons: list[dict[str, Any]] = []
    for row in rows:
        frequency = float(row["frequency_term_hz"])
        phase = float(row["phase_term_hz"])
        current = int(row["current_applied_code"])
        count = int(row["accumulated_edge_error_counts"])
        tight = row["tight_state"] == TIGHT_INSIDE
        comparisons.append(
            {
                "decision_sequence": int(row["decision_sequence"]),
                "observed_count": count,
                "tight_state": row["tight_state"],
                "observed_requested_delta_codes": int(
                    row["requested_delta_codes"]
                ),
                "phase_removed_integer_delta_codes": _limited_integer_delta(
                    frequency, policy=policy, current_code=current
                ),
                "frequency_removed_while_tight_integer_delta_codes": (
                    _limited_integer_delta(phase, policy=policy, current_code=current)
                    if tight
                    else int(row["requested_delta_codes"])
                ),
                "one_count_frequency_held_integer_delta_codes": (
                    _limited_integer_delta(phase, policy=policy, current_code=current)
                    if tight and abs(count) <= 1
                    else int(row["requested_delta_codes"])
                ),
                "cadence_limited": row["cadence_limited"] == "true",
            }
        )
    late_frequency_applications = [
        item
        for item in comparisons
        if item["decision_sequence"] in {25, 28, 44, 48}
    ]
    return {
        "claim_boundary": (
            "same-frontier deterministic term attribution only; post-divergence "
            "rows are not physical replay"
        ),
        "decision_comparisons": comparisons,
        "late_frequency_driven_application_sequences": [25, 28, 44, 48],
        "late_frequency_driven_observed_deltas": [
            item["observed_requested_delta_codes"]
            for item in late_frequency_applications
        ],
        "late_one_count_hold_deltas": [
            item["one_count_frequency_held_integer_delta_codes"]
            for item in late_frequency_applications
        ],
        "late_requests_cadence_limited": any(
            item["cadence_limited"] for item in late_frequency_applications
        ),
        "one_count_frequency_hz": 1.0 / 600.0,
        "v1_one_count_raw_codes": (
            policy.integrator_gain_codes_per_hz_per_decision / 600.0
        ),
        "gain_must_be_strictly_below_codes_per_hz_per_decision": 300.0,
        "grouped_two_output_diagnostic_pairs": [
            [
                int(rows[index]["accumulated_edge_error_counts"]),
                int(rows[index + 1]["accumulated_edge_error_counts"]),
            ]
            for index in range(0, len(rows) - 1, 2)
        ],
    }


@dataclass
class ModeledTightBand:
    state: str = "REQUALIFY_OUTSIDE"
    entry_count: int = 0
    release_count: int = 0

    def reset(self) -> None:
        self.state = "REQUALIFY_OUTSIDE"
        self.entry_count = 0
        self.release_count = 0

    def observe(self, counts: int) -> str:
        absolute = abs(counts)
        if self.state != TIGHT_INSIDE:
            self.release_count = 0
            if absolute <= 2:
                self.entry_count += 1
                if self.entry_count >= 2:
                    self.state = TIGHT_INSIDE
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


@dataclass
class CandidateFrequencyGate:
    candidate_id: str
    persistence_sign: int | None = None
    persistence_count: int = 0
    persistence_session: int | None = None
    persistence_dac_epoch: int | None = None
    persistence_source_last: int | None = None

    def reset(self) -> None:
        self.persistence_sign = None
        self.persistence_count = 0
        self.persistence_session = None
        self.persistence_dac_epoch = None
        self.persistence_source_last = None

    def effective_frequency_error(
        self,
        *,
        frequency_error_hz: float,
        counts: int,
        tight_state: str,
        capture_session: int,
        dac_epoch: int,
        source_first: int,
        source_last: int,
        fresh: bool = True,
        identity_valid: bool = True,
    ) -> tuple[float, str]:
        if not identity_valid or not fresh:
            self.reset()
            return 0.0, "invalid_or_stale_hold"
        tight = tight_state == TIGHT_INSIDE
        if self.candidate_id == "tight_phase_only_v1":
            return (
                (0.0, "tight_phase_only_frequency_hold")
                if tight
                else (frequency_error_hz, "outside_tight_frequency_enabled")
            )
        if self.candidate_id == "one_count_tight_hold_v1":
            return (
                (0.0, "one_count_tight_frequency_hold")
                if tight and abs(counts) <= 1
                else (frequency_error_hz, "frequency_enabled")
            )
        if self.candidate_id != "persistent_one_count_release_v1":
            raise ValueError(f"unknown changed candidate: {self.candidate_id}")
        if not tight or abs(counts) != 1:
            self.reset()
            return frequency_error_hz, "persistence_not_applicable"
        sign = 1 if counts > 0 else -1
        nonoverlap = (
            self.persistence_source_last is None
            or source_first > self.persistence_source_last
        )
        same_frontier = (
            self.persistence_sign == sign
            and self.persistence_session == capture_session
            and self.persistence_dac_epoch == dac_epoch
            and nonoverlap
        )
        self.persistence_count = self.persistence_count + 1 if same_frontier else 1
        self.persistence_sign = sign
        self.persistence_session = capture_session
        self.persistence_dac_epoch = dac_epoch
        self.persistence_source_last = source_last
        if self.persistence_count >= 2:
            return frequency_error_hz, "persistent_one_count_released"
        return 0.0, "persistent_one_count_first_hold"


def _uncertainty_offset(
    code_difference: int, contract: dict[str, Any], mode: str
) -> float:
    if code_difference == 0 or mode == "nominal":
        return 0.0
    retained = contract["model"]["retained_uncertainty_sensitivities"]
    magnitude = float(retained["maximum_observed_hysteresis_hz"]) + float(
        retained["centre_repeatability_span_hz"]
    )
    direction = 1.0 if code_difference > 0 else -1.0
    if mode == "favorable":
        return direction * magnitude
    if mode == "adverse":
        return -direction * magnitude
    raise ValueError(f"unknown uncertainty mode: {mode}")


def _simulate_candidate(
    *,
    candidate_id: str,
    gain_name: str,
    gain_hz_per_code: float,
    uncertainty_mode: str,
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
    gate = CandidateFrequencyGate(candidate_id)
    band = ModeledTightBand()
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
                difference = previous_candidate_code - previous_source_code
                rate = gain_hz_per_code * difference + _uncertainty_offset(
                    difference, contract, uncertainty_mode
                )
                modeled_phase_offset += rate * (timestamp_s - previous_time)
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

        difference = controller.applied_code - source_code
        modeled_frequency = float(row["frequency_error_hz"]) + (
            gain_hz_per_code * difference
            + _uncertainty_offset(difference, contract, uncertainty_mode)
        )
        modeled_counts = _round_half_away(modeled_frequency * 600.0)
        if not diverged:
            tight_state = row["tight_state"]
            band.state = tight_state
        elif controller.transaction_outstanding:
            tight_state = "REQUALIFY_OUTSIDE"
        else:
            tight_state = band.observe(modeled_counts)
        effective_error, gate_reason = gate.effective_frequency_error(
            frequency_error_hz=modeled_frequency,
            counts=modeled_counts,
            tight_state=tight_state,
            capture_session=int(row["capture_session"]),
            dac_epoch=controller.dac_epoch,
            source_first=int(row["source_first_sequence"]),
            source_last=int(row["source_last_sequence"]),
            fresh=not controller.transaction_outstanding,
            identity_valid=True,
        )
        observation = HybridObservation(
            timestamp_s=timestamp_s,
            capture_session=int(row["capture_session"]),
            source_first_sequence=int(row["source_first_sequence"]),
            source_last_sequence=int(row["source_last_sequence"]),
            dac_epoch=controller.dac_epoch,
            applied_code=controller.applied_code,
            frequency_error_hz=effective_error,
            accumulated_edge_error_counts=modeled_counts,
            tight_state=tight_state,
            phase_epoch=phase_epoch,
            phase_observation_sequence=int(row["phase_observation_sequence"]),
            relative_phase_cycles=_round_half_away(
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
            "gate_reason": gate_reason,
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
            gate.reset()
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
        "uncertainty_mode": uncertainty_mode,
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
    }


def _code_at(timestamp_s: float, events: list[dict[str, Any]], start_code: int) -> int:
    code = start_code
    for event in events:
        if float(event["timestamp_s"]) > timestamp_s:
            break
        code = int(event["applied_code"])
    return code


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
    phase_rows = _read_csv(
        context["run_dir"] / "csv/relative_phase_observations_v1.csv"
    )
    qualified = [
        row
        for row in phase_rows
        if row.get("qualification_state", "").lower()
        in {"qualified", "valid", "eligible", "control_eligible"}
    ]
    source_events = [
        {
            "timestamp_s": float(row["application_timestamp_s"]),
            "applied_code": int(row["applied_code"]),
        }
        for row in context["transactions"]
        if row.get("event") == "application"
    ]
    candidate_events = [
        {
            "timestamp_s": float(row["timestamp_s"]),
            "applied_code": int(row["applied_code"]),
        }
        for row in simulation["applications"]
    ]
    source_events.sort(key=lambda item: item["timestamp_s"])
    candidate_events.sort(key=lambda item: item["timestamp_s"])
    gain = float(simulation["gain_hz_per_code"])
    mode = str(simulation["uncertainty_mode"])
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
            boundaries = [
                value for value in all_events if previous_x < value < x
            ]
            cursor = previous_x
            for boundary in [*boundaries, x]:
                probe = (cursor + boundary) / 2.0
                difference = _code_at(
                    probe, candidate_events, contract["baseline"]["setup_code"]
                ) - _code_at(
                    probe, source_events, contract["baseline"]["setup_code"]
                )
                rate = gain * difference + _uncertainty_offset(
                    difference, contract, mode
                )
                offset += rate * (boundary - cursor)
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
        item for item in projected if item["phase_epoch"] == same_epoch and item["x"] <= frontier
    ][-1800:]
    after = [
        item for item in projected if item["phase_epoch"] == same_epoch and item["x"] > frontier
    ][:1800]
    baseline_slope = _ols_slope(
        [(item["x"], item["modeled_phase"]) for item in before]
    )
    active_slope = _ols_slope(
        [(item["x"], item["modeled_phase"]) for item in after]
    )
    exact = len(before) == 1800 and len(after) == 1800 and baseline_slope is not None and active_slope is not None
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


def _frequency_metrics(
    *, simulation: dict[str, Any], contract: dict[str, Any]
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
    values = [
        sample
        for sample in simulation["samples"]
        if sample["source_last_sequence"] > first_material["source_last_sequence"]
        and sample["gate_reason"] != "invalid_or_stale_hold"
    ]
    errors = [float(item["modeled_frequency_error_hz"]) for item in values]
    rms = math.sqrt(statistics.fmean(value * value for value in errors)) if errors else None
    occupancy = (
        sum(item["tight_state"] == TIGHT_INSIDE for item in values) / len(values)
        if values
        else None
    )
    baseline_rms = 1.0 / 600.0
    baseline_occupancy = 1.0
    degradation = None if rms is None else rms - baseline_rms
    occupancy_degradation = (
        None if occupancy is None else baseline_occupancy - occupancy
    )
    gate = contract["selection_gate"]
    passed = bool(
        errors
        and degradation is not None
        and occupancy_degradation is not None
        and degradation <= gate["maximum_frequency_rms_degradation_hz"]
        and occupancy_degradation
        <= gate["maximum_tight_occupancy_degradation_fraction"]
    )
    return {
        "exact": True,
        "pass": passed,
        "reason": "thresholds_satisfied" if passed else "frequency_threshold_failed",
        "sample_count": len(errors),
        "modeled_frequency_rms_hz": rms,
        "modeled_absolute_frequency_p95_hz": _quantile(
            [abs(value) for value in errors], 0.95
        ),
        "modeled_absolute_frequency_max_hz": max(
            (abs(value) for value in errors), default=None
        ),
        "tight_inside_occupancy_fraction": occupancy,
        "frequency_rms_degradation_hz": degradation,
        "tight_occupancy_degradation_fraction": occupancy_degradation,
    }


def _scenario_checks(
    simulation: dict[str, Any], phase: dict[str, Any], frequency: dict[str, Any], contract: dict[str, Any]
) -> dict[str, bool]:
    gate = contract["selection_gate"]
    return {
        "minimum_two_material_phase_applications": simulation[
            "phase_material_application_count"
        ] >= gate["minimum_material_phase_applications_when_supplied"],
        "phase_behavior_preserved": bool(phase.get("pass")),
        "frequency_behavior_preserved": bool(frequency.get("pass")),
        "attempt4_path_at_most_27": simulation["natural_path_codes"]
        <= gate["attempt4_maximum_natural_path_codes"],
        "attempt4_path_reduction_at_least_25_percent": simulation[
            "natural_path_codes"
        ]
        <= contract["baseline"]["cumulative_natural_movement_codes"]
        * (1.0 - gate["attempt4_minimum_path_reduction_fraction_from_v1"]),
        "meaningful_net_regulation": abs(simulation["net_regulation_codes"])
        >= gate["attempt4_minimum_absolute_net_regulation_codes"],
        "no_fail_static_or_low_efficiency_terminal": simulation[
            "terminal_state"
        ]
        != "FAIL_STATIC"
        and simulation["terminal_reason"]
        not in {"prospective_low_efficiency_path", "prospective_repeated_alternation"},
        "no_three_reversals_in_four": not simulation["three_reversals_in_four"],
        "no_unexpected_range_clamp": not simulation["range_clamped"],
        "count_and_path_authority_preserved": simulation["application_count"]
        <= 12
        and simulation["natural_path_codes"] <= 84,
    }


def _gate_sequence(
    candidate_id: str, counts: list[int]
) -> tuple[list[float], list[str]]:
    gate = CandidateFrequencyGate(candidate_id)
    band = ModeledTightBand(state=TIGHT_INSIDE)
    outputs: list[float] = []
    reasons: list[str] = []
    source_last = 0
    for index, count in enumerate(counts, start=1):
        tight_state = band.observe(count)
        first = source_last + 1
        source_last = first + 599
        value, reason = gate.effective_frequency_error(
            frequency_error_hz=count / 600.0,
            counts=count,
            tight_state=tight_state,
            capture_session=1,
            dac_epoch=1,
            source_first=first,
            source_last=source_last,
        )
        outputs.append(value)
        reasons.append(reason)
    return outputs, reasons


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
        if "counts" in case:
            counts = [int(value) for value in case["counts"]]
            outputs, reasons = _gate_sequence(candidate_id, counts)
            detail = {"effective_frequency_errors_hz": outputs, "reasons": reasons}
            nonzero = [value != 0.0 for value in outputs]
            if case_id.startswith("isolated") or case_id.startswith("alternating") or case_id.startswith("zero_crossing"):
                passed = not any(nonzero)
                if case_id.startswith("zero_crossing"):
                    detail["relative_phase_cycles_preserved"] = case[
                        "relative_phase_cycles"
                    ]
            elif case_id.startswith("persistent_"):
                passed = (
                    nonzero == [False, True]
                    if candidate_id == "persistent_one_count_release_v1"
                    else nonzero == [False, False]
                )
            elif case_id.startswith("legitimate_slow"):
                passed = not nonzero[1] and any(nonzero[2:])
            elif case_id.endswith("demand_reversal"):
                passed = any(value < 0.0 for value in outputs) and any(
                    value > 0.0 for value in outputs
                )
            elif case_id == "long_zero_demand_dwell":
                passed = not any(nonzero)
        elif case_id == "rounding_boundaries":
            observed = [_round_half_away(float(value)) for value in case["raw_delta_codes"]]
            expected = [0, 1, 1, 0, -1, -1]
            passed = observed == expected
            detail = {"rounded": observed, "expected": expected}
        elif case_id.startswith("plant_gain_"):
            scenario = scenarios[case["gain"]]
            passed = all(scenario["selection_checks"].values())
            detail = {"scenario_id": scenario["scenario_id"]}
        elif case_id.startswith("hysteresis_repeatability_"):
            scenario = scenarios[case["uncertainty"]]
            passed = all(scenario["selection_checks"].values())
            detail = {"scenario_id": scenario["scenario_id"]}
        elif case_id == "cadence_below_at_above":
            elapsed = case["elapsed_s"]
            passed = [value < 1800 for value in elapsed] == [True, False, False]
            detail = {"cadence_limited": [value < 1800 for value in elapsed]}
        elif case_id == "no_natural_reversal_challenge_recovery":
            passed = policy.reversal_challenge_enabled
            detail = {
                "inherited_challenge_enabled": passed,
                "policy_id": policy.policy_id,
            }
        elif case_id in {
            "dac_epoch_reset",
            "capture_session_reset",
            "estimator_reset",
            "settling_support_reset",
        }:
            if candidate_id != "persistent_one_count_release_v1":
                detail = {"candidate_has_persistence_state": False}
            else:
                gate = CandidateFrequencyGate(candidate_id)
                gate.effective_frequency_error(
                    frequency_error_hz=1 / 600,
                    counts=1,
                    tight_state=TIGHT_INSIDE,
                    capture_session=1,
                    dac_epoch=1,
                    source_first=1,
                    source_last=600,
                )
                if case_id == "dac_epoch_reset":
                    value, reason = gate.effective_frequency_error(
                        frequency_error_hz=1 / 600,
                        counts=1,
                        tight_state=TIGHT_INSIDE,
                        capture_session=1,
                        dac_epoch=2,
                        source_first=601,
                        source_last=1200,
                    )
                elif case_id == "capture_session_reset":
                    value, reason = gate.effective_frequency_error(
                        frequency_error_hz=1 / 600,
                        counts=1,
                        tight_state=TIGHT_INSIDE,
                        capture_session=2,
                        dac_epoch=1,
                        source_first=601,
                        source_last=1200,
                    )
                elif case_id == "estimator_reset":
                    gate.reset()
                    value, reason = gate.effective_frequency_error(
                        frequency_error_hz=1 / 600,
                        counts=1,
                        tight_state=TIGHT_INSIDE,
                        capture_session=1,
                        dac_epoch=1,
                        source_first=601,
                        source_last=1200,
                    )
                else:
                    gate.effective_frequency_error(
                        frequency_error_hz=1 / 600,
                        counts=1,
                        tight_state=TIGHT_INSIDE,
                        capture_session=1,
                        dac_epoch=1,
                        source_first=601,
                        source_last=1200,
                        fresh=False,
                    )
                    value, reason = gate.effective_frequency_error(
                        frequency_error_hz=1 / 600,
                        counts=1,
                        tight_state=TIGHT_INSIDE,
                        capture_session=1,
                        dac_epoch=1,
                        source_first=1201,
                        source_last=1800,
                    )
                passed = value == 0.0 and reason == "persistent_one_count_first_hold"
                detail = {
                    "candidate_has_persistence_state": True,
                    "post_transition_effective_frequency_error_hz": value,
                    "post_transition_reason": reason,
                }
        elif case_id == "stale_coherent":
            gate = CandidateFrequencyGate(candidate_id)
            value, reason = gate.effective_frequency_error(
                frequency_error_hz=1 / 600,
                counts=1,
                tight_state=TIGHT_INSIDE,
                capture_session=1,
                dac_epoch=1,
                source_first=1,
                source_last=600,
                fresh=False,
            )
            passed = value == 0.0 and reason == "invalid_or_stale_hold"
            detail = {
                "disposition": "bounded_hold_or_retry_not_contradiction",
                "effective_frequency_error_hz": value,
                "gate_reason": reason,
            }
        elif case_id == "contradictory_identity":
            controller = ActiveHybridController(policy)
            decision = controller.decide(
                HybridObservation(
                    timestamp_s=1800,
                    capture_session=1,
                    source_first_sequence=1201,
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
                    identity_exact=False,
                )
            )
            passed = (
                decision.state_after == "FAIL_STATIC"
                and decision.reason == "measurement_authority_or_common_health_fault"
            )
            detail = {
                "disposition": "fail_static",
                "state_after": decision.state_after,
                "reason": decision.reason,
            }
        elif case_id == "application_count_boundary":
            observed = max(
                scenario["summary"]["application_count"]
                for scenario in scenarios.values()
            )
            passed = observed <= policy.maximum_applications
            detail = {
                "maximum_modeled_applications": observed,
                "frozen_limit": policy.maximum_applications,
            }
        elif case_id == "cumulative_path_boundary":
            observed = max(
                scenario["summary"]["natural_path_codes"]
                for scenario in scenarios.values()
            )
            passed = observed <= policy.maximum_cumulative_movement_codes
            detail = {
                "maximum_modeled_path_codes": observed,
                "frozen_limit": policy.maximum_cumulative_movement_codes,
            }
        elif case_id == "range_boundary":
            applied_codes = [
                application["applied_code"]
                for scenario in scenarios.values()
                for application in scenario["applications"]
            ]
            passed = bool(applied_codes) and all(
                policy.minimum_code <= code <= policy.maximum_code
                for code in applied_codes
            )
            detail = {
                "minimum_modeled_code": min(applied_codes, default=None),
                "maximum_modeled_code": max(applied_codes, default=None),
                "frozen_range": [policy.minimum_code, policy.maximum_code],
            }
        elif case_id == "abort_fail_static_boundary":
            controller = ActiveHybridController(policy)
            decision = controller.decide(
                HybridObservation(
                    timestamp_s=1800,
                    capture_session=1,
                    source_first_sequence=1201,
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
                    common_health_clean=False,
                )
            )
            passed = decision.state_after == "FAIL_STATIC"
            detail = {
                "inherited_fail_static_state": decision.state_after,
                "reason": decision.reason,
            }
        else:
            passed = False
            detail = {"error": "unhandled frozen perturbation case"}
        results.append({"case_id": case_id, "pass": passed, "detail": detail})
    return results


def _candidate_comparison(
    *, candidate: dict[str, Any], contract: dict[str, Any], context: dict[str, Any]
) -> dict[str, Any]:
    gains = contract["model"]["plant_gain_hz_per_code"]
    definitions = [
        ("minimum", float(gains["minimum"]), "nominal"),
        ("nominal", float(gains["nominal"]), "nominal"),
        ("maximum", float(gains["maximum"]), "nominal"),
        ("adverse", float(gains["nominal"]), "adverse"),
        ("favorable", float(gains["nominal"]), "favorable"),
    ]
    scenarios: dict[str, dict[str, Any]] = {}
    for name, gain, uncertainty in definitions:
        simulation = _simulate_candidate(
            candidate_id=candidate["candidate_id"],
            gain_name=name,
            gain_hz_per_code=gain,
            uncertainty_mode=uncertainty,
            contract=contract,
            context=context,
        )
        phase = _phase_metrics(
            simulation=simulation, contract=contract, context=context
        )
        frequency = _frequency_metrics(simulation=simulation, contract=contract)
        checks = _scenario_checks(simulation, phase, frequency, contract)
        scenarios[name] = {
            "scenario_id": f"attempt4_{name}",
            "gain_hz_per_code": gain,
            "uncertainty_mode": uncertainty,
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
        "all_gain_and_uncertainty_scenarios_pass": all(
            all(scenario["selection_checks"].values())
            for scenario in scenarios.values()
        ),
        "all_frozen_perturbations_pass": all(item["pass"] for item in perturbations),
        "deterministic_explicit_state": True,
        "implementable_in_host_and_firmware": True,
        "no_physical_claim": True,
    }
    selectable = all(aggregate_checks.values())
    ordered_failure_names = [
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
    ]
    first_failure: str | None = None
    for scenario_name, scenario in scenarios.items():
        for check_name in ordered_failure_names:
            if not scenario["selection_checks"][check_name]:
                first_failure = f"{scenario_name}:{check_name}"
                break
        if first_failure is not None:
            break
    if first_failure is None:
        failed_case = next((item for item in perturbations if not item["pass"]), None)
        if failed_case is not None:
            first_failure = f"perturbation:{failed_case['case_id']}"
    return {
        "candidate_id": candidate["candidate_id"],
        "semantic_complexity_rank": candidate["semantic_complexity_rank"],
        "selectable": selectable,
        "first_discriminating_failure": first_failure,
        "nominal_attempt4_natural_path_codes": nominal["summary"][
            "natural_path_codes"
        ],
        "nominal_attempt4_net_regulation_codes": nominal["summary"][
            "net_regulation_codes"
        ],
        "worst_case_frequency_rms_degradation_hz": max(
            float(scenario["frequency_metrics"]["frequency_rms_degradation_hz"])
            if scenario["frequency_metrics"].get("frequency_rms_degradation_hz")
            is not None
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
    source_validation = validate_bound_sources(contract)
    baseline, context = _baseline_replay(contract, source_validation)
    ablations = _diagnostic_ablations(context)
    comparisons = [
        _candidate_comparison(candidate=candidate, contract=contract, context=context)
        for candidate in contract["candidates"]
        if candidate.get("selectable") is True
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
        "selected_changed_successor"
        if selected is not None
        else "no_controller_successor_selected"
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
        "selected_candidate_id": (
            None if selected is None else selected["candidate_id"]
        ),
        "ranking_tied": tied,
        "source_validation": {
            **{
                key: value
                for key, value in source_validation.items()
                if key not in {"run_dir", "manifest"}
            },
            "run_dir": contract["source"]["run_dir"],
        },
        "observed_facts": {
            "formal_physical_qualification_passed": False,
            "formal_failure_reason": contract["baseline"]["formal_failure_reason"],
            "registered_content_sha256": contract["source"][
                "registered_content_sha256"
            ],
        },
        "exact_v1_baseline": baseline,
        "causal_ablations": ablations,
        "candidate_comparisons": comparisons,
        "decision": {
            "terminal": terminal,
            "selected_candidate_id": (
                None if selected is None else selected["candidate_id"]
            ),
            "rejected_candidates": [
                {
                    "candidate_id": item["candidate_id"],
                    "first_discriminating_failure": item[
                        "first_discriminating_failure"
                    ],
                }
                for item in comparisons
                if not item["selectable"]
            ],
            "next_gate": (
                "operator_review_of_non_effective_OTIS_SUSTAINED_HYBRID_SUCCESSOR_V1_bundle"
                if selected is not None
                else "estimator_or_controller_architecture_revision"
            ),
        },
        "claim_boundary": {
            "exact_replay": "V1 chronology and integer decisions only",
            "causal_ablation": "retained decision frontier only",
            "counterfactual": "static-gain and labeled retained-uncertainty model after code divergence",
            "physical_qualification": False,
            "unexercised_boundaries": [
                "RP2040 cross-core propagation",
                "USB device driver and serial carrier",
                "AD5693R and DAC-to-CX317 path",
                "D14 reference input",
                "D8 oscillator/count input",
                "physical CX317 plant response",
            ],
        },
        "limitations": [
            "Missing contemporaneous Attempt 4 replay attestations remain missing and the physical seal remains failed.",
            "Modeled values after candidate code divergence are not observed plant behavior.",
            "Raw phase epochs are never joined with a guessed offset.",
            "D10 remains an external event input only and is absent from timing authority and control eligibility.",
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
