"""Replay and immutably seal one finite physical CX320 qualification run.

The analyzer is deliberately offline-only.  It has no serial, command FIFO,
reset, flash, or actuator surface.  A superseding analysis may reinterpret an
unchanged acquisition with corrected host code, but cannot replace either the
raw evidence or the prospectively frozen predicates.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import math
import os
from pathlib import Path
import re
import tempfile
from typing import Any

from .active_hybrid_activation import (
    LIVE_STAGE,
    PROGRAMME_ID,
    validate_frozen_run_manifest,
)
from .active_hybrid_evidence_guard import (
    replay_response_before_acknowledgement,
)
from .active_hybrid_policy import ActiveHybridController, HybridObservation, load_policy
from .active_status_contract import latest_complete_health
from .active_transactions import (
    ACTIVE_CSV,
    HEALTH_CSV,
    CampaignSpec,
    _read_csv,
    validate_transaction_history,
)
from .campaign_finalization import (
    CAPTURE_STATE,
    SUPERVISOR_EVENTS,
    SUPERVISOR_STATE,
    _capture_closure,
    _contract_path,
    _host_markers,
)
from .contracts import CsvValidationContext, validate_csv
from .control_evidence_replay import (
    _capsules_exact,
    _measurement_replay,
    _response_replay,
)
from .evidence import EVIDENCE_MANIFEST, validate_evidence_snapshot
from .frequency_control_supervisor import DAC_CSV, RPH_CSV, TDB_CSV
from .run_loader import (
    CAPTURE_IN_PROGRESS_FLAG,
    COMPLETE_MARKER,
    RunManifest,
)
from .tight_deadband_policy import replay_tight_deadband


TOOL_ID = "cx320_active_hybrid_live_analyze_v1"
SEAL_TYPE = "cx320_active_hybrid_physical_seal_v1"
DEFAULT_SEAL = Path("reports/cx320_active_hybrid_physical_seal_v1.json")
ACTIVE_HYBRID_CSV = Path("csv/active_hybrid_decisions_v1.csv")
TERMINAL_DECISIONS = frozenset(
    {
        "bounded_active_hybrid_control_passed",
        "phase_influence_not_exercised",
        "first_phase_transaction_passed_sustained_result_incomplete",
        "phase_channel_degraded_frequency_control_retained",
        "hybrid_response_wrong_or_frequency_not_reacquired",
        "hybrid_policy_chatter_or_budget_nonpass",
        "frequency_performance_materially_degraded",
        "right_censored_incomplete",
        "measurement_authority_or_platform_fault",
        "operator_abort",
    }
)


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(value: dict[str, Any]) -> str:
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _atomic_new_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite immutable CX320 seal: {path}")
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _read_object_or_empty(
    path: Path, failures: list[str], label: str
) -> dict[str, Any]:
    try:
        return _read_object(path)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        failures.append(f"{label}: {exc}")
        return {}


def _read_events_or_empty(
    path: Path, failures: list[str]
) -> list[dict[str, Any]]:
    try:
        values = [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        if not all(isinstance(item, dict) for item in values):
            raise ValueError("event stream contains a non-object")
        return values
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        failures.append(f"supervisor events: {exc}")
        return []


def _bool(value: object) -> bool:
    if value is True or value == "true":
        return True
    if value is False or value == "false":
        return False
    raise ValueError(f"malformed Boolean: {value!r}")


def _close(observed: float, expected: float) -> bool:
    return math.isclose(observed, expected, rel_tol=0.0, abs_tol=5e-12)


def _ols_slope(rows: list[dict[str, str]]) -> float:
    x = [float(row["closing_reference_sequence"]) for row in rows]
    y = [float(row["relative_phase_cycles"]) for row in rows]
    x_mean = sum(x) / len(x)
    y_mean = sum(y) / len(y)
    denominator = sum((item - x_mean) ** 2 for item in x)
    if denominator == 0.0:
        raise ValueError("phase comparison has no reference-sequence span")
    return sum(
        (x_item - x_mean) * (y_item - y_mean)
        for x_item, y_item in zip(x, y, strict=True)
    ) / denominator


def _qualified_phase_rows(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    accepted = {"qualified", "valid", "eligible", "control_eligible"}
    return [
        row
        for row in rows
        if row.get("qualification_state", "").lower() in accepted
    ]


def _metric_contract(
    policy_document: dict[str, Any], *, comparison_observations: int
) -> dict[str, Any]:
    frozen = policy_document.get("prospective_metrics")
    if not isinstance(frozen, dict):
        raise ValueError("CX320 policy lacks prospective metric thresholds")
    comparison = frozen.get("comparison_segment")
    if (
        comparison
        != "last_1800s_continuous_frequency_only_PHASE_QUALIFY_residence_immediately_before_first_phase_material_application"
        or comparison_observations != 1_800
        or frozen.get("active_segment")
        != "from_first_phase_material_application_until_terminal_or_qualified_endpoint"
        or frozen.get("primary_phase_metric")
        != "absolute_OLS_slope_of_raw_relative_phase_cycles_per_second_within_each_unjoined_phase_epoch"
    ):
        raise ValueError("CX320 prospective comparison definition differs")
    result = {
        "comparison_observations": comparison_observations,
        "comparison_segment": comparison,
        "active_segment": frozen["active_segment"],
        "primary_phase_metric": frozen["primary_phase_metric"],
        "phase_improvement_minimum_fraction": float(
            frozen["phase_improvement_minimum_fraction"]
        ),
        "phase_improvement_minimum_cycles_over_matched_1800s": float(
            frozen["phase_improvement_minimum_cycles_over_matched_1800s"]
        ),
        "maximum_frequency_RMS_degradation_hz": float(
            frozen["maximum_frequency_RMS_degradation_hz"]
        ),
        "maximum_tight_occupancy_fraction_degradation": float(
            frozen["maximum_tight_occupancy_fraction_degradation"]
        ),
        "minimum_material_phase_applications": int(
            frozen["minimum_material_phase_applications"]
        ),
    }
    if (
        result["phase_improvement_minimum_fraction"] != 0.1
        or result["phase_improvement_minimum_cycles_over_matched_1800s"] != 1.0
        or not math.isclose(
            result["maximum_frequency_RMS_degradation_hz"],
            1.0 / 600.0,
            rel_tol=0.0,
            abs_tol=1e-18,
        )
        or result["maximum_tight_occupancy_fraction_degradation"] != 0.1
        or result["minimum_material_phase_applications"] != 2
    ):
        raise ValueError("CX320 prospective acceptance thresholds differ")
    return result


def _phase_metrics(
    rph_rows: list[dict[str, str]],
    first_material: dict[str, str] | None,
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    """Compare unjoined baseline and active phase epochs without joining resets."""

    empty: dict[str, Any] = {
        "exact": False,
        "reason": "no_phase_material_application",
        "comparison_observation_count": thresholds["comparison_observations"],
        "baseline_observation_count": 0,
        "active_observation_count": 0,
        "absolute_ols_slope_baseline_cycles_per_s": None,
        "absolute_ols_slope_matched_active_cycles_per_s": None,
        "absolute_ols_slope_active_segment_cycles_per_s": None,
        "active_unjoined_epoch_slopes": [],
        "matched_1800_improvement_cycles": None,
        "matched_1800_improvement_fraction": None,
        "thresholds": {
            "minimum_improvement_cycles": thresholds[
                "phase_improvement_minimum_cycles_over_matched_1800s"
            ],
            "minimum_improvement_fraction": thresholds[
                "phase_improvement_minimum_fraction"
            ],
        },
        "pass": False,
    }
    if first_material is None:
        return empty
    phase_epoch = int(first_material["phase_epoch"])
    capture_session = int(first_material["capture_session"])
    influence_sequence = int(first_material["phase_observation_sequence"])
    influence_reference = int(first_material["source_last_sequence"])
    qualified = sorted(
        (
            row
            for row in _qualified_phase_rows(rph_rows)
            if int(row["capture_session"]) == capture_session
        ),
        key=lambda row: int(row["closing_reference_sequence"]),
    )
    before = [
        row
        for row in qualified
        if int(row["phase_epoch"]) == phase_epoch
        and int(row["closing_reference_sequence"]) <= influence_reference
        and int(row["observation_sequence"]) <= influence_sequence
    ]
    comparison_observations = int(thresholds["comparison_observations"])
    baseline = before[-comparison_observations:]
    active_by_epoch: dict[int, list[dict[str, str]]] = {}
    for row in qualified:
        if int(row["closing_reference_sequence"]) > influence_reference:
            active_by_epoch.setdefault(int(row["phase_epoch"]), []).append(row)
    active_epoch_rows = sorted(
        active_by_epoch.items(),
        key=lambda item: int(item[1][0]["closing_reference_sequence"]),
    )
    matched_epoch = next(
        (
            (epoch, rows)
            for epoch, rows in active_epoch_rows
            if len(rows) >= comparison_observations
        ),
        None,
    )
    active_segment = matched_epoch[1] if matched_epoch is not None else []
    active = active_segment[:comparison_observations]
    result = {**empty}
    result.update(
        {
            "phase_epoch": phase_epoch,
            "capture_session": capture_session,
            "first_material_phase_observation_sequence": influence_sequence,
            "first_material_source_reference_sequence": influence_reference,
            "baseline_observation_count": len(baseline),
            "active_observation_count": len(active),
            "active_segment_observation_count": len(active_segment),
        }
    )
    if len(baseline) != comparison_observations or len(active) != comparison_observations:
        result["reason"] = "matched_1800_same_epoch_observations_incomplete"
        return result
    baseline_sequences = [int(row["observation_sequence"]) for row in baseline]
    active_sequences = [int(row["observation_sequence"]) for row in active]
    baseline_references = [
        int(row["closing_reference_sequence"]) for row in baseline
    ]
    active_references = [int(row["closing_reference_sequence"]) for row in active]
    contiguous = (
        baseline_sequences
        == list(range(baseline_sequences[0], baseline_sequences[0] + len(baseline)))
        and active_sequences
        == list(range(active_sequences[0], active_sequences[0] + len(active)))
        and baseline_references
        == list(
            range(
                baseline_references[0],
                baseline_references[0] + len(baseline_references),
            )
        )
        and active_references
        == list(
            range(
                active_references[0],
                active_references[0] + len(active_references),
            )
        )
        and matched_epoch is not None
        and matched_epoch[0] != phase_epoch
    )
    if not contiguous:
        result["reason"] = "matched_1800_phase_sequence_not_contiguous"
        return result
    baseline_slope = abs(_ols_slope(baseline))
    active_slope = abs(_ols_slope(active))
    active_segment_slope = abs(_ols_slope(active_segment))
    improvement_cycles = (
        baseline_slope - active_slope
    ) * comparison_observations
    improvement_fraction = (
        (baseline_slope - active_slope) / baseline_slope
        if baseline_slope > 0.0
        else (1.0 if active_slope == 0.0 else -math.inf)
    )
    passed = (
        improvement_cycles
        >= thresholds["phase_improvement_minimum_cycles_over_matched_1800s"]
        and improvement_fraction
        >= thresholds["phase_improvement_minimum_fraction"]
    )
    result.update(
        {
            "exact": True,
            "reason": "thresholds_satisfied" if passed else "phase_improvement_below_frozen_threshold",
            "baseline_first_observation_sequence": baseline_sequences[0],
            "baseline_last_observation_sequence": baseline_sequences[-1],
            "baseline_first_reference_sequence": int(
                baseline[0]["closing_reference_sequence"]
            ),
            "baseline_last_reference_sequence": int(
                baseline[-1]["closing_reference_sequence"]
            ),
            "matched_active_phase_epoch": matched_epoch[0],
            "active_first_observation_sequence": active_sequences[0],
            "active_last_observation_sequence": active_sequences[-1],
            "active_first_reference_sequence": int(
                active[0]["closing_reference_sequence"]
            ),
            "active_last_reference_sequence": int(
                active_segment[-1]["closing_reference_sequence"]
            ),
            "active_global_last_reference_sequence": max(
                int(row["closing_reference_sequence"])
                for _, rows in active_epoch_rows
                for row in rows
            ),
            "absolute_ols_slope_baseline_cycles_per_s": baseline_slope,
            "absolute_ols_slope_matched_active_cycles_per_s": active_slope,
            "absolute_ols_slope_active_segment_cycles_per_s": active_segment_slope,
            "baseline_cumulative_absolute_movement_cycles": sum(
                abs(
                    int(later["relative_phase_cycles"])
                    - int(earlier["relative_phase_cycles"])
                )
                for earlier, later in zip(baseline, baseline[1:])
            ),
            "active_segment_cumulative_absolute_movement_cycles": sum(
                abs(
                    int(later["relative_phase_cycles"])
                    - int(earlier["relative_phase_cycles"])
                )
                for earlier, later in zip(active_segment, active_segment[1:])
            ),
            "baseline_maximum_excursion_from_opening_cycles": max(
                abs(
                    int(row["relative_phase_cycles"])
                    - int(baseline[0]["relative_phase_cycles"])
                )
                for row in baseline
            ),
            "active_segment_maximum_excursion_from_opening_cycles": max(
                abs(
                    int(row["relative_phase_cycles"])
                    - int(active_segment[0]["relative_phase_cycles"])
                )
                for row in active_segment
            ),
            "active_unjoined_epoch_slopes": [
                {
                    "phase_epoch": epoch,
                    "qualified_observation_count": len(rows),
                    "absolute_ols_slope_cycles_per_s": (
                        abs(_ols_slope(rows)) if len(rows) >= 2 else None
                    ),
                }
                for epoch, rows in active_epoch_rows
            ],
            "matched_1800_improvement_cycles": improvement_cycles,
            "matched_1800_improvement_fraction": (
                improvement_fraction if math.isfinite(improvement_fraction) else None
            ),
            "pass": passed,
        }
    )
    return result


def _frequency_metrics(
    estimate_rows: list[dict[str, str]],
    tdb_rows: list[dict[str, str]],
    phase: dict[str, Any],
    thresholds: dict[str, Any],
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "exact": False,
        "baseline_selected_estimate_count": 0,
        "active_selected_estimate_count": 0,
        "baseline_frequency_residual_rms_hz": None,
        "active_frequency_residual_rms_hz": None,
        "frequency_rms_degradation_hz": None,
        "baseline_tight_inside_occupancy_fraction": None,
        "active_tight_inside_occupancy_fraction": None,
        "tight_inside_occupancy_degradation_fraction": None,
        "thresholds": {
            "maximum_frequency_rms_degradation_hz": thresholds[
                "maximum_frequency_RMS_degradation_hz"
            ],
            "maximum_tight_occupancy_degradation_fraction": thresholds[
                "maximum_tight_occupancy_fraction_degradation"
            ],
        },
        "pass": False,
    }
    if not phase.get("exact"):
        return result
    baseline_first = int(phase["baseline_first_reference_sequence"])
    baseline_last = int(phase["baseline_last_reference_sequence"])
    active_first = int(phase["first_material_source_reference_sequence"]) + 1
    active_last = int(phase["active_global_last_reference_sequence"])
    selected = [
        row
        for row in estimate_rows
        if row.get("estimator_version") == "cx317_selected_600s_nonoverlap_v1"
        and row.get("observation_validity") == "valid"
        and row.get("reference_validity") == "valid"
        and row.get("reference_continuity") == "true"
        and row.get("count_validity") == "valid"
        and row.get("count_continuity") == "true"
        and row.get("diagnostic_health") == "healthy"
    ]
    baseline = [
        row
        for row in selected
        if baseline_first <= int(row["source_reference_last_seq"]) <= baseline_last
    ]
    active = [
        row
        for row in selected
        if active_first <= int(row["source_reference_last_seq"]) <= active_last
    ]
    tdb_by_estimate = {row.get("estimate_id"): row for row in tdb_rows}
    result["baseline_selected_estimate_count"] = len(baseline)
    result["active_selected_estimate_count"] = len(active)
    # The 1,800-observation baseline has three independent 600 s windows.  The
    # active comparison retains every selected window through the endpoint.
    if len(baseline) != 3 or len(active) < 3:
        return result

    def rms(rows: list[dict[str, str]]) -> float:
        return math.sqrt(
            sum(float(row["frequency_error_hz"]) ** 2 for row in rows) / len(rows)
        )

    def occupancy(rows: list[dict[str, str]]) -> float:
        states = [tdb_by_estimate.get(row["estimate_id"], {}) for row in rows]
        if any(not item for item in states):
            raise ValueError("frequency comparison lacks a TDB decision")
        return sum(item.get("state_after") == "TIGHT_INSIDE" for item in states) / len(states)

    try:
        baseline_rms = rms(baseline)
        active_rms = rms(active)
        baseline_occupancy = occupancy(baseline)
        active_occupancy = occupancy(active)
    except (KeyError, TypeError, ValueError):
        return result
    rms_degradation = active_rms - baseline_rms
    occupancy_degradation = baseline_occupancy - active_occupancy
    passed = (
        rms_degradation <= thresholds["maximum_frequency_RMS_degradation_hz"]
        and occupancy_degradation
        <= thresholds["maximum_tight_occupancy_fraction_degradation"]
    )
    result.update(
        {
            "exact": True,
            "baseline_frequency_residual_rms_hz": baseline_rms,
            "active_frequency_residual_rms_hz": active_rms,
            "frequency_rms_degradation_hz": rms_degradation,
            "baseline_tight_inside_occupancy_fraction": baseline_occupancy,
            "active_tight_inside_occupancy_fraction": active_occupancy,
            "tight_inside_occupancy_degradation_fraction": occupancy_degradation,
            "pass": passed,
        }
    )
    return result


def _replay_ahy(
    decisions: list[dict[str, str]],
    transactions: list[dict[str, str]],
    *,
    policy_path: Path,
    expected_run_identity: str,
    expected_build_identity: str,
    expected_profile_identity: str,
) -> dict[str, Any]:
    """Replay the complete policy state and both integer request paths."""

    policy = load_policy(policy_path)
    controller = ActiveHybridController(policy)
    request_rows: dict[int, dict[str, str]] = {}
    application_rows: dict[int, dict[str, str]] = {}
    response_rows: dict[int, dict[str, str]] = {}
    mapping_exact = True
    mappings = {
        "request_created": request_rows,
        "application": application_rows,
        "response": response_rows,
    }
    for row in transactions:
        target = mappings.get(row.get("event", ""))
        if target is None:
            continue
        try:
            sequence = int(row["decision_sequence"])
        except (KeyError, TypeError, ValueError):
            mapping_exact = False
            continue
        if sequence in target:
            mapping_exact = False
        target[sequence] = row
    comparisons: list[dict[str, Any]] = []
    exact = mapping_exact
    prior_record_sequence = 0
    seen_decisions: set[int] = set()
    for row in decisions:
        try:
            record_sequence = int(row["hybrid_record_sequence"])
            decision_sequence = int(row["decision_sequence"])
            identity_exact = (
                row["run_identity"] == expected_run_identity
                and row["build_identity"] == expected_build_identity
                and row["profile_identity"] == expected_profile_identity
                and row["active_policy_sha256"] == policy.policy_sha256
                and row["frequency_estimator_sha256"]
                == policy.frequency_estimator_sha256
                and row["phase_estimator_sha256"] == policy.phase_estimator_sha256
                and row["response_policy_sha256"] == policy.response_policy_sha256
            )
            observation = HybridObservation(
                timestamp_s=int(row["decision_timestamp_s"]),
                capture_session=int(row["capture_session"]),
                source_first_sequence=int(row["source_first_sequence"]),
                source_last_sequence=int(row["source_last_sequence"]),
                dac_epoch=int(row["dac_epoch"]),
                applied_code=int(row["current_applied_code"]),
                frequency_error_hz=float(row["frequency_error_hz"]),
                accumulated_edge_error_counts=int(
                    row["accumulated_edge_error_counts"]
                ),
                tight_state=row["tight_state"],
                phase_epoch=int(row["phase_epoch"]),
                phase_observation_sequence=int(row["phase_observation_sequence"]),
                relative_phase_cycles=int(row["relative_phase_cycles"]),
                phase_dac_epoch=int(row["phase_dac_epoch"]),
                phase_applied_code=int(row["phase_applied_code"]),
                phase_continuous=_bool(row["phase_continuous"]),
                phase_current=_bool(row["phase_current"]),
                phase_step_detected=_bool(row["phase_step_detected"]),
                identity_exact=identity_exact,
                common_health_clean=True,
                phase_consumers_exact=(
                    _bool(row["phase_recorder_published"])
                    and _bool(row["downstream_epoch_exact"])
                ),
                outstanding_request=False,
                outstanding_response=False,
            )
            replayed = controller.decide(observation)
            numerical_exact = (
                row["state_before"] == replayed.state_before
                and row["state_after"] == replayed.state_after
                and row["reason"] == replayed.reason
                and _close(
                    float(row["frequency_term_hz"]), replayed.frequency_term_hz
                )
                and _close(float(row["phase_term_hz"]), replayed.phase_term_hz)
                and _close(
                    float(row["combined_demand_hz"]), replayed.combined_demand_hz
                )
                and _close(
                    float(row["raw_combined_delta_codes"]),
                    replayed.raw_combined_delta_codes,
                )
                and int(row["requested_delta_codes"])
                == replayed.requested_delta_codes
                and int(row["requested_code"]) == replayed.requested_code
                and int(row["counterfactual_frequency_only_delta_codes"])
                == replayed.counterfactual_frequency_only_delta_codes
                and _bool(row["phase_materially_influenced"])
                == replayed.phase_materially_influenced
                and _bool(row["step_limited"]) == replayed.step_limited
                and _bool(row["range_clamped"]) == replayed.range_clamped
                and _bool(row["cadence_limited"]) == replayed.cadence_limited
                and _bool(row["count_limited"]) == replayed.count_limited
                and _bool(row["cumulative_budget_limited"])
                == replayed.cumulative_budget_limited
                and int(row["correction_count_before"])
                == replayed.correction_count_before
                and int(row["cumulative_movement_before_codes"])
                == replayed.cumulative_movement_before_codes
            )
            sequence_exact = (
                record_sequence == prior_record_sequence + 1
                and decision_sequence not in seen_decisions
            )
            request = request_rows.get(decision_sequence)
            transaction_exact = (
                (replayed.requested_delta_codes == 0 and request is None)
                or (
                    replayed.requested_delta_codes != 0
                    and request is not None
                    and int(request["requested_delta_codes"])
                    == replayed.requested_delta_codes
                    and int(request["requested_code"]) == replayed.requested_code
                    and int(request["request_sequence"]) == int(row["request_sequence"])
                )
            )
            row_exact = identity_exact and numerical_exact and sequence_exact and transaction_exact
            comparisons.append(
                {
                    "decision_sequence": decision_sequence,
                    "requested_delta_codes": replayed.requested_delta_codes,
                    "counterfactual_frequency_only_delta_codes": replayed.counterfactual_frequency_only_delta_codes,
                    "phase_materially_influenced": replayed.phase_materially_influenced,
                    "identity_exact": identity_exact,
                    "numerical_exact": numerical_exact,
                    "sequence_exact": sequence_exact,
                    "transaction_binding_exact": transaction_exact,
                    "exact": row_exact,
                }
            )
            exact &= row_exact
            prior_record_sequence = record_sequence
            seen_decisions.add(decision_sequence)
            if replayed.requested_delta_codes != 0:
                application = application_rows.get(decision_sequence)
                response = response_rows.get(decision_sequence)
                if application is None or response is None:
                    raise ValueError("nonzero AHY decision lacks complete ACT application/response")
                controller.note_application(
                    replayed,
                    applied_code=int(application["applied_code"]),
                    dac_epoch=int(application["dac_epoch"]),
                    downstream_consumers_exact=True,
                )
                healthy_class = response.get("response_class") in {
                    "healthy_detected",
                    "healthy_indeterminate_near_resolution",
                    "inside_deadband",
                }
                controller.note_response(
                    classification=str(response.get("response_class", "")),
                    predicted_sign_observed=healthy_class,
                    exact_replay=True,
                    support_fresh=True,
                    applied_epoch_exact=(
                        int(response["applied_code"]) == int(application["applied_code"])
                        and int(response["dac_epoch"]) == int(application["dac_epoch"])
                    ),
                )
        except (KeyError, TypeError, ValueError) as exc:
            exact = False
            comparisons.append(
                {
                    "decision_sequence": row.get("decision_sequence"),
                    "exact": False,
                    "error": str(exc),
                }
            )
    unmatched_requests = sorted(set(request_rows) - seen_decisions)
    exact &= not unmatched_requests and bool(decisions)
    phase_nonzero_count = 0
    for row in decisions:
        try:
            phase_nonzero_count += float(row["phase_term_hz"]) != 0.0
        except (KeyError, TypeError, ValueError):
            exact = False
    return {
        "exact": exact,
        "decision_count": len(decisions),
        "phase_nonzero_decision_count": phase_nonzero_count,
        "phase_material_decision_count": sum(row["phase_materially_influenced"] == "true" for row in decisions),
        "unmatched_request_decision_sequences": unmatched_requests,
        "comparisons": comparisons,
    }


def _response_attestations(
    run_dir: Path,
    active_rows: list[dict[str, str]],
) -> tuple[bool, dict[str, str], list[dict[str, Any]]]:
    exact = True
    hashes: dict[str, str] = {}
    comparisons: list[dict[str, Any]] = []
    for response in (row for row in active_rows if row.get("event") == "response"):
        try:
            request_sequence: object = int(response["request_sequence"])
            record_sequence: object = int(response["transaction_record_sequence"])
            relative = Path("reports") / f"step_{request_sequence:03d}" / (
                f"record_{record_sequence:06d}_response_replay_attestation.json"
            )
            path = run_dir / relative
            replayed = replay_response_before_acknowledgement(
                active_hybrid_csv=run_dir / ACTIVE_HYBRID_CSV,
                active_transactions_csv=run_dir / ACTIVE_CSV,
                response_row=response,
            )
            retained = _read_object(path)
            row_exact = retained == replayed
            if path.is_file():
                hashes[str(relative)] = _sha256_file(path)
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            row_exact = False
            replayed = {"error": str(exc)}
            request_sequence = response.get("request_sequence")
            record_sequence = response.get("transaction_record_sequence")
        exact &= row_exact
        comparisons.append(
            {
                "request_sequence": request_sequence,
                "record_sequence": record_sequence,
                "exact": row_exact,
                "replayed_attestation_sha256": replayed.get("attestation_sha256"),
            }
        )
    return exact, hashes, comparisons


def _cx320_commands_exact(
    markers: list[dict[str, Any]],
    events: list[dict[str, Any]],
    capture_state: dict[str, Any],
    *,
    setup_code: int,
    allowed_emergency_aborts: int,
) -> bool:
    submitted = [
        str(item["command"])
        for item in events
        if item.get("event") == "command_submitted"
    ]
    sent = [
        str(item["command"])
        for item in markers
        if item.get("event") == "host_command_sent"
    ]
    acknowledged = [
        str(item["command"])
        for item in events
        if item.get("event") == "host_written"
    ]
    setup = re.compile(
        rf"ACTIVE SETUP [1-9][0-9]* [1-9][0-9]* [1-9][0-9]* "
        rf"[1-9][0-9]* [1-9][0-9]* 0x{setup_code:04X} 1 [0-9a-f]{{64}}",
        re.IGNORECASE,
    )
    allowed_fixed = {"CONFIG?", "DUALCORE?", "DAC?", "ACTIVE?"}
    grammar_exact = all(
        command in allowed_fixed
        or re.fullmatch(r"ACTIVE SNAPSHOT [1-9][0-9]*", command)
        or setup.fullmatch(command)
        or re.fullmatch(r"ACTIVE LEASE [1-9][0-9]*", command)
        or re.fullmatch(r"ACTIVE ARM [1-9][0-9]* [1-9][0-9]* [1-9][0-9]*", command)
        or re.fullmatch(r"ACTIVE EVIDENCE [1-9][0-9]* [1-4]", command)
        for command in submitted
    )
    expected_sent = [*submitted, *(["ACTIVE ABORT"] * allowed_emergency_aborts)]
    return (
        submitted == acknowledged
        and sent == expected_sent
        and grammar_exact
        and submitted.count("CONFIG?") == 1
        and submitted.count("DUALCORE?") == 1
        and submitted.count("DAC?") == 1
        and sum(setup.fullmatch(command) is not None for command in submitted) == 1
        and int(capture_state.get("emergency_aborts_sent", 0))
        == allowed_emergency_aborts
    )


def _wall_origin_and_setup_order_exact(
    manifest: dict[str, Any],
    supervisor_state: dict[str, Any],
    supervisor_events: list[dict[str, Any]],
    markers: list[dict[str, Any]],
) -> bool:
    capture_starts = [
        index for index, item in enumerate(markers) if item.get("event") == "capture_started"
    ]
    setup_markers = [
        index
        for index, item in enumerate(markers)
        if item.get("event") == "host_command_sent"
        and str(item.get("command", "")).startswith("ACTIVE SETUP ")
    ]
    supervisor_starts = [
        index
        for index, item in enumerate(supervisor_events)
        if item.get("event") == "cx320_live_supervisor_started"
    ]
    setup_requests = [
        index
        for index, item in enumerate(supervisor_events)
        if item.get("event") == "cx320_exact_setup_requested"
    ]
    wall_origin = manifest.get("started_at_utc")
    return (
        isinstance(wall_origin, str)
        and bool(wall_origin)
        and supervisor_state.get("wall_origin_utc") == wall_origin
        and len(capture_starts) == 1
        and len(setup_markers) == 1
        and capture_starts[0] < setup_markers[0]
        and len(supervisor_starts) == 1
        and len(setup_requests) == 1
        and supervisor_starts[0] < setup_requests[0]
        and supervisor_events[supervisor_starts[0]].get("wall_origin_utc")
        == wall_origin
        and supervisor_events[supervisor_starts[0]].get("manifest_sha256")
        == manifest.get("manifest_sha256")
    )
def _application_contract(
    active_rows: list[dict[str, str]],
    decisions: list[dict[str, str]],
    dac_rows: list[dict[str, str]],
    *,
    setup_code: int,
    minimum_code: int,
    maximum_code: int,
    maximum_step: int,
    maximum_applications: int,
    maximum_cumulative: int,
    minimum_cadence_s: int,
) -> dict[str, Any]:
    manual = [row for row in active_rows if row.get("event") == "manual_start"]
    applications = [row for row in active_rows if row.get("event") == "application"]
    responses = [row for row in active_rows if row.get("event") == "response"]
    material_decisions = {
        int(row["decision_sequence"])
        for row in decisions
        if row.get("phase_materially_influenced") == "true"
        and int(row.get("requested_delta_codes", "0")) != 0
    }
    material_applications = [
        row
        for row in applications
        if int(row["decision_sequence"]) in material_decisions
    ]
    frequency_only_applications = [
        row
        for row in applications
        if int(row["decision_sequence"]) not in material_decisions
    ]
    times = [int(row["application_timestamp_s"]) for row in applications]
    movements = [abs(int(row["requested_delta_codes"])) for row in applications]
    epochs_exact = (
        len(manual) == 1
        and int(manual[0].get("applied_code", "-1")) == setup_code
        and int(manual[0].get("dac_epoch", "-1")) == 1
        and len(responses) == len(applications)
        and [int(row["dac_epoch"]) for row in applications]
        == list(range(2, len(applications) + 2))
        and all(
            int(response["dac_epoch"]) == int(application["dac_epoch"])
            for application, response in zip(applications, responses, strict=True)
        )
    )
    dac_exact = (
        len(dac_rows) == len(applications) + 1
        and bool(dac_rows)
        and dac_rows[0].get("event") == "manual_apply"
        and int(dac_rows[0]["dac_code_requested"]) == setup_code
        and int(dac_rows[0]["dac_code_applied"]) == setup_code
        and int(dac_rows[0]["dac_code_clamped"]) == 0
        and int(dac_rows[0]["flags"]) == 0
        and all(
            dac.get("event") == "active_apply"
            and int(dac["dac_code_requested"]) == int(application["requested_code"])
            and int(dac["dac_code_applied"]) == int(application["applied_code"])
            and int(dac["dac_code_clamped"]) == 0
            and int(dac["flags"]) == 0
            for dac, application in zip(dac_rows[1:], applications, strict=True)
        )
    )
    budgets_exact = (
        len(applications) <= maximum_applications
        and sum(movements) <= maximum_cumulative
        and all(0 < movement <= maximum_step for movement in movements)
        and all(
            minimum_code <= int(row["applied_code"]) <= maximum_code
            for row in applications
        )
        and all(
            later - earlier >= minimum_cadence_s
            for earlier, later in zip(times, times[1:])
        )
        and all(row.get("clamped") == "false" for row in applications)
    )
    first_checkpoint = (
        bool(material_applications)
        and any(
            int(response["request_sequence"])
            == int(material_applications[0]["request_sequence"])
            and response.get("response_class")
            in {"healthy_detected", "healthy_indeterminate_near_resolution"}
            for response in responses
        )
    )
    later_authority_gated = (
        len(material_applications) <= 1
        or (
            first_checkpoint
            and int(material_applications[1]["application_timestamp_s"])
            > int(material_applications[0]["application_timestamp_s"])
        )
    )
    response_classes_healthy = all(
        row.get("response_class")
        in {"healthy_detected", "healthy_indeterminate_near_resolution"}
        for row in responses
    )
    return {
        "exact": epochs_exact and dac_exact and budgets_exact and later_authority_gated,
        "setup_count": len(manual),
        "automatic_application_count": len(applications),
        "frequency_only_application_count": len(frequency_only_applications),
        "phase_nonzero_application_count": sum(
            float(decision.get("phase_term_hz", "0")) != 0.0
            and any(
                int(application["decision_sequence"]) == int(decision["decision_sequence"])
                for application in applications
            )
            for decision in decisions
        ),
        "phase_material_application_count": len(material_applications),
        "first_phase_checkpoint_passed": first_checkpoint,
        "later_authority_gated_by_first_checkpoint": later_authority_gated,
        "all_response_classes_healthy": response_classes_healthy,
        "application_epochs_exact": epochs_exact,
        "dac_application_exact": dac_exact,
        "budgets_range_step_cadence_and_clamp_exact": budgets_exact,
        "cumulative_movement_codes": sum(movements),
        "maximum_application_budget": maximum_applications,
        "maximum_cumulative_movement_codes": maximum_cumulative,
    }


def _classify_decision(
    *,
    integrity_exact: bool,
    operator_abort: bool,
    platform_terminal: bool,
    phase_degraded: bool,
    endpoint_complete: bool,
    material_applications: int,
    first_checkpoint_passed: bool,
    responses_healthy: bool,
    tight_reacquired_and_retained: bool,
    policy_limits_exact: bool,
    phase_pass: bool,
    frequency_pass: bool,
    minimum_material_applications: int,
) -> tuple[str, str]:
    if operator_abort:
        return "bounded_nonpass", "operator_abort"
    if platform_terminal or not integrity_exact:
        return "failed", "measurement_authority_or_platform_fault"
    if phase_degraded:
        return "bounded_nonpass", "phase_channel_degraded_frequency_control_retained"
    if not policy_limits_exact:
        return "bounded_nonpass", "hybrid_policy_chatter_or_budget_nonpass"
    if material_applications == 0:
        return "bounded_nonpass", "phase_influence_not_exercised"
    if not first_checkpoint_passed or not responses_healthy:
        return "bounded_nonpass", "hybrid_response_wrong_or_frequency_not_reacquired"
    if not tight_reacquired_and_retained:
        return "bounded_nonpass", "hybrid_response_wrong_or_frequency_not_reacquired"
    if material_applications < minimum_material_applications:
        return (
            "bounded_nonpass",
            "first_phase_transaction_passed_sustained_result_incomplete",
        )
    if not endpoint_complete:
        return "bounded_nonpass", "right_censored_incomplete"
    if not frequency_pass:
        return "bounded_nonpass", "frequency_performance_materially_degraded"
    if not phase_pass:
        return "bounded_nonpass", "hybrid_response_wrong_or_frequency_not_reacquired"
    return "passed", "bounded_active_hybrid_control_passed"


def _source_hashes(
    run_dir: Path,
    manifest: RunManifest,
    manifest_value: dict[str, Any],
    capsule_hashes: dict[str, str],
    attestation_hashes: dict[str, str],
) -> tuple[dict[str, str], list[str]]:
    paths = {
        "run_manifest.json",
        str(EVIDENCE_MANIFEST),
        str(COMPLETE_MARKER),
        "raw/serial.log",
        str(CAPTURE_STATE),
        str(SUPERVISOR_STATE),
        str(SUPERVISOR_EVENTS),
        "reports/capture_segment_closure_v1.json",
        *(str(item["path"]) for item in manifest.files if not item.get("optional") or (run_dir / str(item["path"])).is_file()),
        *(str(item) for item in manifest_value.get("evidence_artifacts", [])),
        *capsule_hashes,
        *attestation_hashes,
    }
    evidence_path = run_dir / EVIDENCE_MANIFEST
    if evidence_path.is_file():
        try:
            evidence = _read_object(evidence_path)
            artifacts = evidence.get("artifacts", [])
            if isinstance(artifacts, list):
                paths.update(
                    str(item["path"])
                    for item in artifacts
                    if isinstance(item, dict) and isinstance(item.get("path"), str)
                )
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            pass
    paths.update(
        path.relative_to(run_dir).as_posix()
        for path in (run_dir / "reports").glob("step_*/*.json")
        if path.is_file()
    )
    missing = [
        relative for relative in sorted(paths) if not (run_dir / relative).is_file()
    ]
    hashes: dict[str, str] = {}
    for relative in sorted(paths):
        path = run_dir / relative
        if not path.is_file():
            continue
        try:
            hashes[relative] = _sha256_file(path)
        except OSError:
            missing.append(relative)
    return hashes, sorted(set(missing))


def analyze(
    run_dir: Path,
    *,
    output_path: Path | None = None,
    supersedes_seal: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    run_dir = run_dir.resolve()
    if (run_dir / CAPTURE_IN_PROGRESS_FLAG).exists():
        raise ValueError("CX320 live capture is still active")
    if not (run_dir / COMPLETE_MARKER).is_file():
        raise ValueError("CX320 live run is not marked complete")
    manifest_value = validate_frozen_run_manifest(run_dir / "run_manifest.json")
    if manifest_value.get("stage") != LIVE_STAGE:
        raise ValueError("run is not the frozen CX320 live stage")
    manifest = RunManifest(
        root=run_dir,
        path=run_dir / "run_manifest.json",
        data=manifest_value,
    )
    policy_path = Path(str(manifest_value["policy"]["path"])).resolve()
    policy = load_policy(policy_path)
    policy_document = _read_object(policy_path)
    metric_contract = _metric_contract(
        policy_document,
        comparison_observations=policy.phase_qualification_residence_s,
    )
    control = manifest_value["cx320"]["automatic_control"]
    setup_code = int(manifest_value["cx320"]["setup"]["code"])
    build_identity = str(manifest_value["firmware"]["build_identity"])
    spec = CampaignSpec(
        campaign="cx320_active_hybrid",
        profile=str(manifest_value["profile_identity"]),
        run_identity=str(manifest_value["run_identity"]),
        start_code=setup_code,
        correction_limit=int(control["maximum_total_applications"]),
        cumulative_limit=int(control["maximum_cumulative_movement_codes"]),
        minimum_code=int(control["minimum_code"]),
        maximum_code=int(control["maximum_code"]),
        maximum_step=int(control["maximum_step_codes"]),
    )
    identities = {
        "estimator_sha256": policy.frequency_estimator_sha256,
        "model_sha256": policy.plant_model_sha256,
        "active_policy_sha256": policy.policy_sha256,
        "response_policy_sha256": policy.response_policy_sha256,
        "numerical_policy_sha256": policy.policy_sha256,
    }
    retained_input_failures: list[str] = []

    validations: dict[str, dict[str, Any]] = {}
    for contract in manifest_value["contracts"]:
        try:
            result = validate_csv(
                _contract_path(manifest, contract),
                CsvValidationContext(
                    contract=contract,
                    known_channels=manifest.known_channels,
                    known_domains=manifest.known_domains,
                ),
            )
            validations[contract] = {
                "ok": result.ok,
                "rows": result.row_count,
                "errors": list(result.errors),
                "warnings": list(result.warnings),
            }
        except (KeyError, OSError, TypeError, ValueError) as exc:
            retained_input_failures.append(f"{contract}: {exc}")
            validations[contract] = {
                "ok": False,
                "rows": 0,
                "errors": [str(exc)],
                "warnings": [],
            }

    active_rows = _read_csv(run_dir / ACTIVE_CSV)
    decision_rows = _read_csv(run_dir / ACTIVE_HYBRID_CSV)
    rph_rows = _read_csv(run_dir / RPH_CSV)
    tdb_rows = _read_csv(run_dir / TDB_CSV)
    dac_rows = _read_csv(run_dir / DAC_CSV)
    transaction_history_exact = bool(active_rows)
    transaction_error = ""
    try:
        validate_transaction_history(
            active_rows, spec, identities, build_identity, dual_core=True
        )
    except (KeyError, TypeError, ValueError) as exc:
        transaction_history_exact = False
        transaction_error = str(exc)

    try:
        response_exact, response_replay = _response_replay(
            active_rows, spec.minimum_code, spec.maximum_code
        )
    except (KeyError, TypeError, ValueError) as exc:
        response_exact = False
        response_replay = [{"exact": False, "error": str(exc)}]
    replay_manifest = json.loads(json.dumps(manifest_value))
    replay_manifest["policy"]["bindings"] = policy_document["bindings"]
    try:
        measurement_exact, measurement_replay, estimates_by_id = _measurement_replay(
            manifest, replay_manifest
        )
    except (KeyError, OSError, TypeError, ValueError) as exc:
        measurement_exact = False
        measurement_replay = {"reason": str(exc)}
        estimates_by_id = {}
    ahy_replay = _replay_ahy(
        decision_rows,
        active_rows,
        policy_path=policy_path,
        expected_run_identity=spec.run_identity,
        expected_build_identity=build_identity,
        expected_profile_identity=spec.profile,
    )

    supervisor_state = _read_object_or_empty(
        run_dir / SUPERVISOR_STATE,
        retained_input_failures,
        "supervisor state",
    )
    capture_state = _read_object_or_empty(
        run_dir / CAPTURE_STATE,
        retained_input_failures,
        "capture state",
    )
    supervisor_events = _read_events_or_empty(
        run_dir / SUPERVISOR_EVENTS, retained_input_failures
    )
    try:
        markers = _host_markers(run_dir / "raw/serial.log")
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        retained_input_failures.append(f"raw serial markers: {exc}")
        markers = []
    try:
        capsule_exact, capsule_hashes = _capsules_exact(
            run_dir, active_rows, supervisor_events, supervisor_state
        )
    except (KeyError, OSError, TypeError, ValueError) as exc:
        capsule_exact = False
        capsule_hashes = {}
        retained_input_failures.append(f"transaction capsules: {exc}")
    attestation_exact, attestation_hashes, attestation_replay = _response_attestations(
        run_dir, active_rows
    )
    terminal = supervisor_state.get("terminal", {})
    if not isinstance(terminal, dict):
        terminal = {}
    operator_abort = terminal.get("primary_decision") == "operator_abort"
    platform_terminal = terminal.get("primary_decision") == (
        "measurement_authority_or_platform_fault"
    )
    terminal_requires_abort = (
        terminal.get("result") in {"aborted", "nonpass"}
        and terminal.get("reason") != "cx320_16h_absolute_wall_endpoint"
    )
    allowed_emergency_aborts = 1 if terminal_requires_abort else 0
    abort_submissions = sum(
        item.get("event") == "emergency_device_abort_submitted"
        for item in supervisor_events
    )
    try:
        abort_sends = int(capture_state.get("emergency_aborts_sent", 0))
    except (TypeError, ValueError):
        abort_sends = -1
        retained_input_failures.append("capture emergency abort count is malformed")
    abort_ordering_exact = (
        abort_submissions == allowed_emergency_aborts
        and abort_sends == allowed_emergency_aborts
    )
    if allowed_emergency_aborts:
        abort_positions = [
            index
            for index, item in enumerate(markers)
            if item.get("event") == "host_command_sent"
            and item.get("command") == "ACTIVE ABORT"
        ]
        stop_positions = [
            index
            for index, item in enumerate(markers)
            if item.get("event") == "capture_stopped"
        ]
        abort_ordering_exact &= (
            len(abort_positions) == 1
            and len(stop_positions) == 1
            and abort_positions[0] < stop_positions[0]
        )
    try:
        capture_closure = _capture_closure(
            run_dir,
            capture_state,
            markers,
            allowed_emergency_aborts=allowed_emergency_aborts,
        )
    except (KeyError, OSError, TypeError, ValueError) as exc:
        capture_closure = {"ok": False, "error": str(exc)}
        retained_input_failures.append(f"capture closure: {exc}")
    try:
        command_exact = _cx320_commands_exact(
            markers,
            supervisor_events,
            capture_state,
            setup_code=setup_code,
            allowed_emergency_aborts=allowed_emergency_aborts,
        )
    except (KeyError, TypeError, ValueError) as exc:
        command_exact = False
        retained_input_failures.append(f"command stream: {exc}")
    wall_origin_exact = _wall_origin_and_setup_order_exact(
        manifest_value, supervisor_state, supervisor_events, markers
    )
    try:
        applications = _application_contract(
            active_rows,
            decision_rows,
            dac_rows,
            setup_code=setup_code,
            minimum_code=spec.minimum_code,
            maximum_code=spec.maximum_code,
            maximum_step=spec.maximum_step,
            maximum_applications=spec.correction_limit,
            maximum_cumulative=spec.cumulative_limit,
            minimum_cadence_s=int(control["minimum_applied_cadence_s"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        retained_input_failures.append(f"application history: {exc}")
        applications = {
            "exact": False,
            "setup_count": 0,
            "automatic_application_count": 0,
            "frequency_only_application_count": 0,
            "phase_nonzero_application_count": 0,
            "phase_material_application_count": 0,
            "first_phase_checkpoint_passed": False,
            "later_authority_gated_by_first_checkpoint": False,
            "all_response_classes_healthy": False,
            "application_epochs_exact": False,
            "dac_application_exact": False,
            "budgets_range_step_cadence_and_clamp_exact": False,
            "cumulative_movement_codes": 0,
            "error": str(exc),
        }

    try:
        tdb_replay = replay_tight_deadband(run_dir / TDB_CSV)
        tdb_replay_exact = tdb_replay.exact
        tdb_replay_detail: dict[str, Any] = tdb_replay.as_dict()
    except (KeyError, OSError, TypeError, ValueError) as exc:
        tdb_replay_exact = False
        tdb_replay_detail = {"exact": False, "error": str(exc)}
        retained_input_failures.append(f"tight-deadband replay: {exc}")
    first_material: dict[str, str] | None = None
    for row in decision_rows:
        try:
            is_material_application = (
                row.get("phase_materially_influenced") == "true"
                and int(row.get("requested_delta_codes", "0")) != 0
            )
        except (TypeError, ValueError):
            is_material_application = False
            retained_input_failures.append(
                "active-hybrid material application field is malformed"
            )
        if is_material_application:
            first_material = row
            break
    try:
        phase_metrics = _phase_metrics(rph_rows, first_material, metric_contract)
        frequency_metrics = _frequency_metrics(
            list(estimates_by_id.values()), tdb_rows, phase_metrics, metric_contract
        )
    except (KeyError, TypeError, ValueError) as exc:
        retained_input_failures.append(f"frozen scientific metrics: {exc}")
        phase_metrics = {"exact": False, "pass": False, "error": str(exc)}
        frequency_metrics = {"exact": False, "pass": False, "error": str(exc)}
    try:
        evidence_failures, evidence_warnings = validate_evidence_snapshot(
            run_dir, manifest
        )
        evidence = _read_object(run_dir / EVIDENCE_MANIFEST)
    except (KeyError, OSError, TypeError, ValueError) as exc:
        evidence_failures = [str(exc)]
        evidence_warnings = []
        evidence = {}

    health = latest_complete_health(run_dir / HEALTH_CSV)
    latest_hybrid_state = health.get(("cx317_active", "hybrid_state"), "")
    terminal_static_code = terminal.get(
        "last_confirmed_code", supervisor_state.get("terminal_static_code")
    )
    applied_rows = [
        row
        for row in active_rows
        if row.get("event") in {"manual_start", "application"}
    ]
    try:
        last_applied_code = (
            int(applied_rows[-1]["applied_code"]) if applied_rows else None
        )
    except (KeyError, TypeError, ValueError):
        last_applied_code = None
        retained_input_failures.append("last applied ACT code is malformed")
    terminal_is_abort = terminal.get("result") == "aborted"
    try:
        static_terminal_exact = (
            health.get(("cx317_active", "state"))
            == ("ABORTED" if terminal_is_abort else "DISARMED")
            and health.get(("cx317_active", "evidence_phase")) == "evidence_clear"
            and health.get(("cx317_active", "fail_static"))
            == ("true" if terminal_is_abort else "false")
            and health.get(("cx317_active", "evidence_pending")) == "false"
            and health.get(("cx317_active", "evidence_request_sequence"), "0")
            == "0"
            and supervisor_state.get("arm_pending") is False
            and terminal_static_code is not None
            and int(terminal_static_code) == last_applied_code
        )
    except (TypeError, ValueError):
        static_terminal_exact = False
        retained_input_failures.append("terminal static code is malformed")
    endpoint_complete = (
        terminal.get("result") == "healthy_stop"
        and terminal.get("reason") == "cx320_12h_qualified_endpoint_complete"
    )
    phase_degraded = (
        terminal.get("primary_decision")
        == "phase_channel_degraded_frequency_control_retained"
        or latest_hybrid_state == "PHASE_DEGRADED_FREQUENCY_ONLY"
    )
    no_fault_or_chatter = (
        (latest_hybrid_state != "FAIL_STATIC" or terminal_is_abort)
        and applications["budgets_range_step_cadence_and_clamp_exact"] is True
        and not any(
            row.get("state_after") == "FAIL_STATIC"
            or row.get("range_clamped") == "true"
            for row in decision_rows
        )
        and not any(
            any(
                marker in row.get("reason", "").lower()
                for marker in (
                    "chatter",
                    "repeated_alternation",
                    "low_efficiency_path",
                    "uncontrolled_reversal",
                )
            )
            for row in decision_rows
        )
    )
    terminal_tight_inside = bool(tdb_rows) and tdb_rows[-1].get(
        "state_after"
    ) == "TIGHT_INSIDE"
    first_checkpoint_exact = (
        applications["first_phase_checkpoint_passed"] is True
        and supervisor_state.get("first_phase_checkpoint_passed") is True
    )
    progressive_authority_exact = (
        applications["later_authority_gated_by_first_checkpoint"] is True
        and (
            applications["phase_material_application_count"] <= 1
            or (
                first_checkpoint_exact
                and supervisor_state.get("later_authority_released") is True
            )
        )
    )
    source_hashes, missing_source_artifacts = _source_hashes(
        run_dir,
        manifest,
        manifest_value,
        capsule_hashes,
        attestation_hashes,
    )

    common_checks = {
        "frozen_live_manifest_exact": True,
        "all_declared_csv_contracts_validate": all(
            item["ok"] for item in validations.values()
        ),
        "evidence_snapshot_complete_and_unchanged": (
            evidence.get("run_state") == "complete"
            and not evidence_failures
            and not evidence_warnings
        ),
        "transaction_history_exact": transaction_history_exact,
        "durable_transaction_capsules_exact": capsule_exact,
        "response_classifier_replay_exact": response_exact,
        "response_pre_acknowledgement_attestations_exact": attestation_exact,
        "raw_measurement_and_estimator_replay_exact": measurement_exact,
        "active_hybrid_decision_and_materiality_replay_exact": ahy_replay["exact"],
        "tight_deadband_replay_exact": tdb_replay_exact,
        "setup_dac_epoch_application_and_budget_exact": applications["exact"],
        "progressive_first_checkpoint_and_later_authority_exact": progressive_authority_exact,
        "capture_closed_cleanly_with_one_owner": capture_closure["ok"],
        "command_stream_exact": command_exact,
        "wall_origin_capture_identity_and_setup_order_exact": wall_origin_exact,
        "abort_submission_delivery_and_close_order_exact": abort_ordering_exact,
        "terminal_disarmed_evidence_clear_no_outstanding_static_code": static_terminal_exact,
        "registration_source_artifacts_present": not missing_source_artifacts,
        "retained_inputs_readable": not retained_input_failures,
    }
    acquisition_check_names = {
        "frozen_live_manifest_exact",
        "capture_closed_cleanly_with_one_owner",
        "command_stream_exact",
        "wall_origin_capture_identity_and_setup_order_exact",
        "abort_submission_delivery_and_close_order_exact",
        "terminal_disarmed_evidence_clear_no_outstanding_static_code",
    }
    acquisition_gate_passed = all(
        common_checks[name] for name in acquisition_check_names
    )
    finalization_gate_passed = all(common_checks.values())
    integrity_exact = all(common_checks.values())
    status, primary_decision = _classify_decision(
        integrity_exact=integrity_exact,
        operator_abort=operator_abort,
        platform_terminal=platform_terminal,
        phase_degraded=phase_degraded,
        endpoint_complete=endpoint_complete,
        material_applications=int(applications["phase_material_application_count"]),
        first_checkpoint_passed=first_checkpoint_exact,
        responses_healthy=bool(applications["all_response_classes_healthy"]),
        tight_reacquired_and_retained=terminal_tight_inside,
        policy_limits_exact=no_fault_or_chatter,
        phase_pass=bool(phase_metrics["pass"]),
        frequency_pass=bool(frequency_metrics["pass"]),
        minimum_material_applications=int(
            metric_contract["minimum_material_phase_applications"]
        ),
    )
    if primary_decision not in TERMINAL_DECISIONS:
        raise AssertionError("CX320 analyzer produced an undeclared terminal decision")

    scientific_acceptance_checks = {
        "minimum_two_material_physical_applications": (
            applications["phase_material_application_count"]
            >= metric_contract["minimum_material_phase_applications"]
        ),
        "first_checkpoint_passed_before_later_authority": (
            first_checkpoint_exact and progressive_authority_exact
        ),
        "all_completed_responses_healthy": applications[
            "all_response_classes_healthy"
        ],
        "phase_improvement_thresholds_pass": bool(phase_metrics["pass"]),
        "frequency_degradation_thresholds_pass": bool(
            frequency_metrics["pass"]
        ),
        "terminal_tight_inside_reacquired_and_retained": terminal_tight_inside,
        "no_chatter_clamp_or_policy_fault": no_fault_or_chatter,
        "qualified_12h_endpoint_complete": endpoint_complete,
        "terminal_static_without_outstanding_authority": static_terminal_exact,
    }

    supersession: dict[str, Any] | None = None
    if supersedes_seal is not None:
        prior_path = supersedes_seal.resolve()
        prior = _read_object(prior_path)
        claimed = prior.get("seal_sha256")
        prior_unsigned = {key: value for key, value in prior.items() if key != "seal_sha256"}
        if claimed != _canonical_sha256(prior_unsigned):
            raise ValueError("superseded CX320 seal semantic identity differs")
        if prior.get("source_artifacts_sha256") != source_hashes:
            raise ValueError("superseding replay source evidence differs from the prior seal")
        if prior.get("missing_source_artifacts", []) != missing_source_artifacts:
            raise ValueError("superseding replay missing-source set differs")
        supersession = {
            "supersedes_path": str(prior_path),
            "supersedes_file_sha256": _sha256_file(prior_path),
            "supersedes_seal_sha256": claimed,
            "reason": "deterministic_offline_consumer_replay_over_unchanged_sources",
        }

    unsigned: dict[str, Any] = {
        "schema_version": 1,
        "seal_type": SEAL_TYPE,
        "tool": TOOL_ID,
        "tool_sha256": _sha256_file(Path(__file__)),
        "created_utc": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "programme_id": PROGRAMME_ID,
        "stage": LIVE_STAGE,
        "run_id": manifest_value["run_id"],
        "run_identity": manifest_value["run_identity"],
        "build_identity": build_identity,
        "policy_sha256": policy.policy_sha256,
        "uf2_sha256": manifest_value["firmware"]["uf2"]["sha256"],
        "bundle_sha256": manifest_value["bundle"]["bundle_sha256"],
        "proposal_sha256": manifest_value["proposal"]["proposal_sha256"],
        "activation_sha256": manifest_value["activation"]["activation_sha256"],
        "status": status,
        "primary_decision": primary_decision,
        "checks": common_checks,
        "scientific_acceptance_checks": scientific_acceptance_checks,
        "acquisition_gate": {
            "passed": acquisition_gate_passed,
            "checks": {
                name: common_checks[name] for name in sorted(acquisition_check_names)
            },
        },
        "offline_finalization_gate": {
            "passed": finalization_gate_passed,
            "replayable_without_physical_repeat": (
                acquisition_gate_passed and not finalization_gate_passed
            ),
        },
        "declared_contract_validations": validations,
        "transaction_replay": {
            "exact": transaction_history_exact,
            "error": transaction_error,
            "capsules_exact": capsule_exact,
            "response_classifier_exact": response_exact,
            "response_classifier_comparisons": response_replay,
            "response_attestations_exact": attestation_exact,
            "response_attestation_comparisons": attestation_replay,
        },
        "measurement_replay": {
            "exact": measurement_exact,
            "detail": measurement_replay,
        },
        "active_hybrid_replay": ahy_replay,
        "application_counts_and_budgets": applications,
        "frozen_metric_contract": metric_contract,
        "phase_performance": phase_metrics,
        "frequency_performance": frequency_metrics,
        "tight_deadband_replay": tdb_replay_detail,
        "terminal": {
            "supervisor_terminal": terminal,
            "endpoint_complete": endpoint_complete,
            "latest_hybrid_state": latest_hybrid_state,
            "static_code": terminal_static_code,
            "static_terminal_exact": static_terminal_exact,
            "abort_submission_count": abort_submissions,
            "abort_delivery_count": abort_sends,
        },
        "evidence_snapshot_validation": {
            "failures": list(evidence_failures),
            "warnings": list(evidence_warnings),
        },
        "source_artifacts_sha256": source_hashes,
        "missing_source_artifacts": missing_source_artifacts,
        "retained_input_failures": retained_input_failures,
        "supersession": supersession,
        "claim_boundary": {
            "observed": (
                "ACT application and response rows, DAC epochs, RPH phase observations, "
                "selected frequency estimates, health, capture, and command evidence are "
                "physical observations only when their independent replay checks pass."
            ),
            "counterfactual": (
                "counterfactual_frequency_only_delta_codes and removal-of-phase comparisons "
                "are deterministic host replays; they are not additional actuator applications "
                "or observed physical responses."
            ),
            "physical_application_counts_are_not_inferred_from_counterfactuals": True,
        },
        "limitations": [
            "D14 is the sole PPS/reference input; D8 is the oscillator/count input; D10 is not timing authority.",
            "The within-run comparison establishes reference-relative behavior, not UTC, absolute phase, calibrated delay, or traceable frequency accuracy.",
            "A superseding seal may correct only deterministic offline interpretation of unchanged source evidence; it cannot move a frozen threshold.",
        ],
    }
    unsigned["seal_sha256"] = _canonical_sha256(unsigned)
    destination = (
        output_path.resolve()
        if output_path is not None
        else run_dir / DEFAULT_SEAL
    )
    _atomic_new_json(destination, unsigned)
    return destination, unsigned


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--supersedes-seal", type=Path)
    args = parser.parse_args(argv)
    path, seal = analyze(
        args.run_dir,
        output_path=args.output,
        supersedes_seal=args.supersedes_seal,
    )
    print(json.dumps({"path": str(path), **seal}, indent=2, sort_keys=True))
    return 0 if seal["status"] != "failed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
