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
import statistics
import tempfile
from typing import Any

from .active_hybrid_activation import (
    LIVE_STAGE,
    PROGRAMME_ID,
    validate_frozen_run_manifest,
)
from .active_hybrid_programme_contract import (
    ActiveHybridProgramme,
    CX320_PROGRAMME,
    CX322_D9_D6_72H_PROGRAMME,
    programme_from_mapping,
    progressive_checkpoint_contract,
)
from .active_hybrid_live_supervisor import (
    forwarded_output_integration_prewrite_evidence,
)
from .active_hybrid_evidence_guard import (
    ResponseCheckpointRejected,
    _cx321_natural_replay_handoff,
    replay_active_hybrid_history,
    replay_response_before_acknowledgement,
)
from .active_hybrid_policy import load_policy
from .active_control_supervisor import RP2040_TIMER0_TICKS_PER_SECOND
from .active_status_contract import latest_complete_health
from .active_transactions import (
    ACTIVE_CSV,
    HEALTH_CSV,
    CampaignSpec,
    _join_cx321_psq_response_to_act,
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
from .cx321_plant_sign_evidence_guard import (
    PlantSignReplayContext,
    complete_plant_sign_evidence_chain,
    plant_sign_terminal_decision_from_record,
    replay_plant_sign_evidence,
    replay_plant_sign_leading_prefix,
    replay_plant_sign_terminal_prefix,
    replay_plant_sign_windows_against_snapshots,
)
from .evidence import EVIDENCE_MANIFEST, validate_evidence_snapshot
from .frequency_control_supervisor import DAC_CSV, RPH_CSV, TDB_CSV
from .pps_cumulative_span_estimator import COUNT_INVALID_FLAGS
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
PRE_SETUP_PROVENANCE_UNRESOLVED = "pre_setup_provenance_unresolved"
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


def _tight_deadband_policy_sha256(policy_document: dict[str, Any]) -> str:
    binding = policy_document.get("bindings", {}).get(
        "frequency_policy_predecessor", {}
    )
    identity = binding.get("sha256") if isinstance(binding, dict) else None
    if not isinstance(identity, str) or not re.fullmatch(r"[0-9a-f]{64}", identity):
        raise ValueError("CX320 tight-deadband predecessor identity is unavailable")
    return identity


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


def _semantic_identity_exact(value: dict[str, Any], identity_key: str) -> bool:
    claimed = value.get(identity_key)
    unsigned = {key: item for key, item in value.items() if key != identity_key}
    return isinstance(claimed, str) and claimed == _canonical_sha256(unsigned)


def _historical_manifest_for_superseding_replay(
    manifest_path: Path, supersedes_seal: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Bind a once-validated frozen manifest after current semantics advance.

    This is intentionally available only to a superseding offline replay.  It
    does not reinterpret the old authority contract: it requires the original
    seal to attest that the exact manifest passed its then-current validator,
    then rechecks every copied bundle/proposal/activation byte and semantic
    identity named by that unchanged manifest.
    """

    manifest_path = manifest_path.resolve()
    manifest = _read_object(manifest_path)
    if not _semantic_identity_exact(manifest, "manifest_sha256"):
        raise ValueError("historical run manifest semantic identity differs")
    prior_path = supersedes_seal.resolve()
    prior = _read_object(prior_path)
    if not _semantic_identity_exact(prior, "seal_sha256"):
        raise ValueError("historical predecessor seal semantic identity differs")
    frozen_manifest_attested = (
        prior.get("acquisition_gate", {})
        .get("checks", {})
        .get("frozen_live_manifest_exact")
        is True
    )
    if not frozen_manifest_attested:
        raise ValueError("historical predecessor did not attest the frozen manifest")

    exact_links = (
        prior.get("run_id") == manifest.get("run_id")
        and prior.get("run_identity") == manifest.get("run_identity")
        and prior.get("build_identity")
        == manifest.get("firmware", {}).get("build_identity")
        and prior.get("bundle_sha256")
        == manifest.get("bundle", {}).get("bundle_sha256")
        and prior.get("proposal_sha256")
        == manifest.get("proposal", {}).get("proposal_sha256")
        and prior.get("activation_sha256")
        == manifest.get("activation", {}).get("activation_sha256")
    )
    if not exact_links:
        raise ValueError("historical predecessor and manifest identities differ")

    semantic_keys = {
        "bundle": "bundle_sha256",
        "proposal": "proposal_sha256",
        "activation": "activation_sha256",
    }
    artifact_bindings: dict[str, dict[str, Any]] = {}
    for name, semantic_key in semantic_keys.items():
        binding = manifest.get(name, {})
        path = Path(str(binding.get("path", ""))).resolve()
        if (
            path.is_symlink()
            or not path.is_file()
            or path.parent != manifest_path.parent
            or path.stat().st_size != binding.get("size_bytes")
            or _sha256_file(path) != binding.get("sha256")
        ):
            raise ValueError(f"historical {name} byte binding differs")
        artifact = _read_object(path)
        if (
            not _semantic_identity_exact(artifact, semantic_key)
            or artifact.get(semantic_key) != binding.get(semantic_key)
        ):
            raise ValueError(f"historical {name} semantic binding differs")
        artifact_bindings[name] = {
            "path": str(path),
            "sha256": binding["sha256"],
            semantic_key: binding[semantic_key],
        }
    return manifest, {
        "mode": "superseding_replay_of_once_validated_historical_manifest",
        "current_contract_validation": False,
        "historical_manifest_semantic_identity_exact": True,
        "predecessor_frozen_manifest_attestation_exact": True,
        "artifact_bindings": artifact_bindings,
        "supersedes_seal_sha256": prior["seal_sha256"],
    }


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
    continuous_active = active_by_epoch.get(phase_epoch, [])
    matched_epoch = (
        (phase_epoch, continuous_active)
        if len(continuous_active) >= comparison_observations
        else None
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
        and matched_epoch[0] == phase_epoch
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
    expected_active_policy_sha256: str | None = None,
    plant_sign_records: list[dict[str, str]] | None = None,
    estimate_rows: list[dict[str, str]] | None = None,
    maximum_applications: int | None = None,
    maximum_cumulative_movement_codes: int | None = None,
    phase_checkpoint_required: bool = True,
) -> dict[str, Any]:
    """Replay the complete policy state and both integer request paths."""

    if plant_sign_records is not None:
        handoffs = [
            row for row in plant_sign_records if row.get("event") == "handoff"
        ]
        terminal_prefix = bool(plant_sign_records) and (
            plant_sign_terminal_decision_from_record(plant_sign_records[-1])
            is not None
        )
        if not handoffs and terminal_prefix and not decisions:
            return {
                "exact": True,
                "decision_count": 0,
                "phase_nonzero_decision_count": 0,
                "phase_material_decision_count": 0,
                "unmatched_request_decision_sequences": [],
                "completed_response_decision_sequences": [],
                "all_response_checkpoints_passed": True,
                "comparisons": [],
                "natural_controller_not_reached": True,
            }

    return replay_active_hybrid_history(
        decisions,
        transactions,
        policy_path=policy_path,
        expected_run_identity=expected_run_identity,
        expected_build_identity=expected_build_identity,
        expected_profile_identity=expected_profile_identity,
        expected_active_policy_sha256=expected_active_policy_sha256,
        plant_sign_handoff=(
            None
            if plant_sign_records is None
            else _cx321_natural_replay_handoff(
                plant_sign_records, transactions
            )
        ),
        estimate_rows=estimate_rows,
        maximum_applications=maximum_applications,
        maximum_cumulative_movement_codes=maximum_cumulative_movement_codes,
        phase_checkpoint_required=phase_checkpoint_required,
    )



def _response_attestations(
    run_dir: Path,
    active_rows: list[dict[str, str]],
    supervisor_events: list[dict[str, Any]],
    programme: ActiveHybridProgramme = CX320_PROGRAMME,
    policy_path: Path | None = None,
    expected_active_policy_sha256: str | None = None,
    allow_superseded_attestation_tool_identity: bool = False,
) -> tuple[bool, dict[str, str], list[dict[str, Any]], frozenset[int]]:
    exact = True
    hashes: dict[str, str] = {}
    comparisons: list[dict[str, Any]] = []
    rejected_record_sequences: set[int] = set()
    for response in (row for row in active_rows if row.get("event") == "response"):
        relative: Path | None = None
        retained_tool_identity_superseded = False
        try:
            request_sequence: object = int(response["request_sequence"])
            record_sequence: object = int(response["transaction_record_sequence"])
            relative = Path("reports") / f"step_{request_sequence:03d}" / (
                f"record_{record_sequence:06d}_response_replay_attestation.json"
            )
            path = run_dir / relative
            estimates_path = run_dir / "csv/estimates_v2.csv"
            replayed = replay_response_before_acknowledgement(
                active_hybrid_csv=run_dir / ACTIVE_HYBRID_CSV,
                active_transactions_csv=run_dir / ACTIVE_CSV,
                response_row=response,
                policy_path=policy_path,
                expected_profile_identity=programme.profile_id,
                expected_active_policy_sha256=expected_active_policy_sha256,
                plant_sign_csv=(
                    run_dir / "csv/plant_sign_qualification_v1.csv"
                    if programme.identification_required
                    else None
                ),
                estimates_csv=(estimates_path if estimates_path.is_file() else None),
                maximum_applications=programme.authorized_maximum_applications,
                maximum_cumulative_movement_codes=(
                    programme.authorized_maximum_cumulative_movement_codes
                ),
                phase_checkpoint_required=bool(
                    progressive_checkpoint_contract(programme).get(
                        "phase_material_application_count_is_acquisition_pass_gate",
                        True,
                    )
                ),
            )
            retained = _read_object(path) if path.is_file() else {}
            phase_acknowledged = any(
                item.get("event") == "transaction_phase_acknowledged"
                and int(item.get("record_sequence", -1)) == record_sequence
                and int(item.get("phase", -1)) == 4
                for item in supervisor_events
            )
            recovered_host_hold = any(
                item.get("event") == f"{programme.key}_host_verification_hold_entered"
                and int(item.get("record_sequence", -1)) == record_sequence
                and int(item.get("request_sequence", -1)) == request_sequence
                for item in supervisor_events
            )
            retained_tool_identity_superseded = (
                allow_superseded_attestation_tool_identity
                and bool(retained)
                and _semantic_identity_exact(retained, "attestation_sha256")
                and _semantic_identity_exact(replayed, "attestation_sha256")
                and {
                    key: value
                    for key, value in retained.items()
                    if key not in {"tool_sha256", "attestation_sha256"}
                }
                == {
                    key: value
                    for key, value in replayed.items()
                    if key not in {"tool_sha256", "attestation_sha256"}
                }
            )
            row_exact = retained == replayed or retained_tool_identity_superseded or (
                not path.exists() and not phase_acknowledged and recovered_host_hold
            )
            if path.is_file():
                hashes[str(relative)] = _sha256_file(path)
            checkpoint_passed = True
            expected_rejection = False
        except ResponseCheckpointRejected as exc:
            request_sequence = int(response["request_sequence"])
            record_sequence = int(response["transaction_record_sequence"])
            relative = Path("reports") / f"step_{request_sequence:03d}" / (
                f"record_{record_sequence:06d}_response_replay_attestation.json"
            )
            path = run_dir / relative
            phase_acknowledged = any(
                item.get("event") == "transaction_phase_acknowledged"
                and int(item.get("record_sequence", -1)) == record_sequence
                and int(item.get("phase", -1)) == 4
                for item in supervisor_events
            )
            rejection_recorded = any(
                (
                    item.get("event")
                    == f"{programme.key}_first_phase_response_checkpoint_rejected"
                    and int(item.get("request_sequence", -1)) == request_sequence
                )
                or (
                    item.get("event") == f"{programme.key}_live_supervisor_fault"
                    and item.get("error")
                    == "CX320 independent host replay differs from the firmware decision"
                )
                for item in supervisor_events
            )
            row_exact = (
                not path.exists()
                and not phase_acknowledged
                and rejection_recorded
            )
            if row_exact:
                rejected_record_sequences.add(record_sequence)
            replayed = {"error": str(exc)}
            checkpoint_passed = False
            expected_rejection = row_exact
        except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
            row_exact = False
            replayed = {"error": str(exc)}
            request_sequence = response.get("request_sequence")
            record_sequence = response.get("transaction_record_sequence")
            checkpoint_passed = False
            expected_rejection = False
        exact &= row_exact
        comparisons.append(
            {
                "request_sequence": request_sequence,
                "record_sequence": record_sequence,
                "exact": row_exact,
                "replayed_attestation_sha256": replayed.get("attestation_sha256"),
                "checkpoint_passed": checkpoint_passed,
                "expected_rejection": expected_rejection,
                **(
                    {"retained_attestation_tool_identity_superseded": True}
                    if retained_tool_identity_superseded
                    else {}
                ),
            }
        )
    return exact, hashes, comparisons, frozenset(rejected_record_sequences)


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
        # Forwarded-output integrations re-query CONFIG? periodically so D9
        # source/divider/readback continuity is retained throughout the run.
        # Exact submitted/written/sent equality above makes every repetition
        # accountable; requiring exactly one contradicts the real supervisor.
        and submitted.count("CONFIG?") >= 1
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
    programme: ActiveHybridProgramme = CX320_PROGRAMME,
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
        if item.get("event") == f"{programme.key}_live_supervisor_started"
    ]
    setup_requests = [
        index
        for index, item in enumerate(supervisor_events)
        if item.get("event") == f"{programme.key}_exact_setup_requested"
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


def _pre_setup_commands_exact(
    markers: list[dict[str, Any]],
    events: list[dict[str, Any]],
    capture_state: dict[str, Any],
) -> bool:
    """Verify the bounded query/lease path before setup became possible."""

    submitted = [
        str(item["command"])
        for item in events
        if item.get("event") == "command_submitted"
    ]
    acknowledged = [
        str(item["command"])
        for item in events
        if item.get("event") == "host_written"
    ]
    sent = [
        str(item["command"])
        for item in markers
        if item.get("event") == "host_command_sent"
    ]
    grammar_exact = all(
        command in {"CONFIG?", "DUALCORE?", "DAC?", "ACTIVE?"}
        or re.fullmatch(r"ACTIVE SNAPSHOT [1-9][0-9]*", command)
        or re.fullmatch(r"ACTIVE LEASE [1-9][0-9]*", command)
        for command in submitted
    )
    return (
        bool(submitted)
        and submitted == acknowledged
        and sent == [*submitted, "ACTIVE ABORT"]
        and grammar_exact
        and submitted.count("CONFIG?") >= 1
        and submitted.count("DUALCORE?") == 1
        and submitted.count("DAC?") == 1
        and int(capture_state.get("emergency_aborts_sent", 0)) == 1
    )


def _pre_setup_wall_origin_exact(
    manifest: dict[str, Any],
    supervisor_state: dict[str, Any],
    supervisor_events: list[dict[str, Any]],
    markers: list[dict[str, Any]],
    programme: ActiveHybridProgramme,
) -> bool:
    capture_starts = [
        item for item in markers if item.get("event") == "capture_started"
    ]
    setup_markers = [
        item
        for item in markers
        if item.get("event") == "host_command_sent"
        and str(item.get("command", "")).startswith("ACTIVE SETUP ")
    ]
    supervisor_starts = [
        item
        for item in supervisor_events
        if item.get("event") == f"{programme.key}_live_supervisor_started"
    ]
    setup_requests = [
        item
        for item in supervisor_events
        if item.get("event") == f"{programme.key}_exact_setup_requested"
    ]
    wall_origin = manifest.get("started_at_utc")
    return (
        isinstance(wall_origin, str)
        and bool(wall_origin)
        and supervisor_state.get("wall_origin_utc") == wall_origin
        and len(capture_starts) == 1
        and not setup_markers
        and len(supervisor_starts) == 1
        and not setup_requests
        and supervisor_starts[0].get("wall_origin_utc") == wall_origin
        and supervisor_starts[0].get("manifest_sha256")
        == manifest.get("manifest_sha256")
    )


def _pre_setup_provenance_terminal_facts(
    *,
    programme: ActiveHybridProgramme,
    terminal: dict[str, Any],
    supervisor_state: dict[str, Any],
    health: dict[tuple[str, str], str],
    active_rows: list[dict[str, str]],
    decision_rows: list[dict[str, str]],
    dac_rows: list[dict[str, str]],
    estimate_rows: list[dict[str, str]],
    command_stream_exact: bool,
    wall_origin_exact: bool,
    abort_ordering_exact: bool,
    capture_closure_exact: bool,
    d9_readback_exact: bool,
    aligned_interval_count: int,
) -> dict[str, Any]:
    """Recognize only a clean terminal before setup or DAC authority existed."""

    readiness = supervisor_state.get("latest_prewrite_readiness")
    readiness = readiness if isinstance(readiness, dict) else {}
    no_control_records = not active_rows and not decision_rows and not dac_rows
    no_estimator_records = not estimate_rows
    setup_or_application_authority_reached = (
        not no_control_records
        or supervisor_state.get("manual_start_sent") is True
        or supervisor_state.get("setup_requested_utc") is not None
        or supervisor_state.get("setup_confirmed_utc") is not None
    )
    state_exact = (
        supervisor_state.get("manual_start_sent") is False
        and supervisor_state.get("setup_requested_utc") is None
        and supervisor_state.get("setup_confirmed_utc") is None
        and supervisor_state.get("setup_authority_path") is None
        and supervisor_state.get("prewrite_contract_ready_utc") is None
        and supervisor_state.get("arm_pending") is False
        and supervisor_state.get("terminal_static_code") is None
        and readiness.get("physical_dac_confirmation")
        == "unknown_before_live_stimulus"
    )
    dac_provenance_unresolved = (
        health.get(("dac", "applied_code_known")) == "false"
        and health.get(("dac", "last_applied_code")) == "unavailable"
        and health.get(("cx317_active", "confirmed_applied_code_known"))
        == "false"
        and health.get(("cx317_active", "confirmed_applied_code"))
        == "unavailable"
        and health.get(("cx317_active", "dac_epoch")) == "0"
    )
    firmware_terminal_exact = (
        health.get(("cx317_active", "state")) == "ABORTED"
        and health.get(("cx317_active", "hybrid_state")) == "SETUP_PENDING"
        and health.get(("cx317_active", "fail_static")) == "true"
        and health.get(("cx317_active", "manual_start_confirmed")) == "false"
        and health.get(("cx317_active", "evidence_pending")) == "false"
        and health.get(("cx317_active", "evidence_phase")) == "evidence_clear"
        and health.get(("cx317_active", "evidence_request_sequence"), "0") == "0"
        and health.get(("cx317_active", "correction_count")) == "0"
        and health.get(("cx317_active", "automatic_application_count")) == "0"
        and health.get(("cx317_active", "cumulative_movement_codes")) == "0"
    )
    supervisor_terminal_exact = (
        terminal.get("result") == "aborted"
        and terminal.get("primary_decision")
        == "measurement_authority_or_platform_fault"
        and terminal.get("reason")
        == f"{programme.key}_live_supervisor_fault:live active_fail_static asserted"
    )
    exact = (
        programme.forwarded_output_integration
        and programme.terminal_after_first_response
        and supervisor_terminal_exact
        and state_exact
        and dac_provenance_unresolved
        and firmware_terminal_exact
        and no_control_records
        and no_estimator_records
        and command_stream_exact
        and wall_origin_exact
        and abort_ordering_exact
        and capture_closure_exact
        and d9_readback_exact
        and aligned_interval_count > 0
    )
    return {
        "exact": exact,
        "supervisor_terminal_exact": supervisor_terminal_exact,
        "pre_setup_state_exact": state_exact,
        "dac_provenance_unresolved": dac_provenance_unresolved,
        "firmware_terminal_exact": firmware_terminal_exact,
        "no_control_records": no_control_records,
        "no_estimator_records": no_estimator_records,
        "command_stream_exact": command_stream_exact,
        "wall_origin_exact_without_setup": wall_origin_exact,
        "abort_ordering_exact": abort_ordering_exact,
        "capture_closure_exact": capture_closure_exact,
        "d9_readback_exact": d9_readback_exact,
        "aligned_d14_d8_d6_interval_count": aligned_interval_count,
        "setup_or_application_authority_reached": (
            setup_or_application_authority_reached
        ),
        "measurement_authority_fault_claimed": False if exact else None,
    }


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
    maximum_automatic_applications: int | None = None,
    maximum_deliberate_challenges: int = 0,
    maximum_cumulative: int,
    minimum_cadence_s: int,
    response_checkpoint_observational: bool = False,
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
    challenge_decisions = {
        int(row["decision_sequence"])
        for row in decisions
        if row.get("reason") == "deliberate_reversal_challenge_request_ready"
    }
    challenge_applications = [
        row
        for row in applications
        if int(row["decision_sequence"]) in challenge_decisions
    ]
    natural_applications = [
        row
        for row in applications
        if int(row["decision_sequence"]) not in challenge_decisions
    ]
    automatic_limit = (
        maximum_applications
        if maximum_automatic_applications is None
        else maximum_automatic_applications
    )


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
    cadence_times = (
        [int(manual[0]["application_timestamp_s"]), *times]
        if len(manual) == 1
        else times
    )
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
        and len(natural_applications) <= automatic_limit
        and len(challenge_applications) <= maximum_deliberate_challenges
        and sum(movements) <= maximum_cumulative
        and all(0 < movement <= maximum_step for movement in movements)
        and all(
            minimum_code <= int(row["applied_code"]) <= maximum_code
            for row in applications
        )
        and all(
            later - earlier >= minimum_cadence_s
            for earlier, later in zip(cadence_times, cadence_times[1:])
        )
        and all(row.get("clamped") == "false" for row in applications)
    )
    observational_classes = {
        "healthy_detected",
        "healthy_indeterminate_near_resolution",
        "inside_deadband",
        "limit_reached",
        "wrong_sign",
        "excess_response",
        "growing_error",
    }
    gated_classes = {
        "healthy_detected",
        "healthy_indeterminate_near_resolution",
        "inside_deadband",
    }
    admissible_classes = (
        observational_classes if response_checkpoint_observational else gated_classes
    )
    first_checkpoint = (
        bool(material_applications)
        and any(
            int(response["request_sequence"])
            == int(material_applications[0]["request_sequence"])
            and response.get("response_class") in admissible_classes
            and (
                response_checkpoint_observational
                or float(response["observed_response_hz"])
                * int(response["requested_delta_codes"])
                > 0.0
            )
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
        row.get("response_class") in gated_classes for row in responses
    )
    response_observations_exact = all(
        row.get("response_class") in admissible_classes for row in responses
    )
    response_signs_observed = all(
        float(row["observed_response_hz"])
        * int(row["requested_delta_codes"])
        > 0.0
        for row in responses
    )
    return {
        "exact": epochs_exact and dac_exact and budgets_exact and later_authority_gated,
        "setup_count": len(manual),
        "automatic_application_count": len(natural_applications),
        "physical_control_application_count": len(applications),
        "deliberate_challenge_application_count": len(challenge_applications),
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
        "first_phase_observation_checkpoint_exact": (
            first_checkpoint if response_checkpoint_observational else None
        ),
        "later_authority_gated_by_first_checkpoint": later_authority_gated,
        "all_response_classes_healthy": response_classes_healthy,
        "all_response_predicted_signs_observed": response_signs_observed,
        "all_response_checkpoints_passed": (
            response_observations_exact
            and (response_checkpoint_observational or response_signs_observed)
        ),
        "response_checkpoint_mode": (
            "observational_non_terminal"
            if response_checkpoint_observational
            else "admission_gate"
        ),
        "application_epochs_exact": epochs_exact,
        "dac_application_exact": dac_exact,
        "budgets_range_step_cadence_and_clamp_exact": budgets_exact,
        "cumulative_movement_codes": sum(movements),
        "maximum_application_budget": maximum_applications,
        "maximum_automatic_application_budget": automatic_limit,
        "maximum_deliberate_challenges": maximum_deliberate_challenges,
        "maximum_cumulative_movement_codes": maximum_cumulative,
    }


def _response_dependent_consumer_propagation(
    active_rows: list[dict[str, str]],
    decision_rows: list[dict[str, str]],
) -> dict[str, Any]:
    """Verify each response identity through its first dependent AHY decision."""

    comparisons: list[dict[str, Any]] = []
    exact = True
    ordered_decisions = sorted(
        decision_rows, key=lambda row: int(row["decision_sequence"])
    )
    for response in (row for row in active_rows if row.get("event") == "response"):
        request_sequence = int(response["request_sequence"])
        source_decision_sequence = int(response["decision_sequence"])
        consumer = next(
            (
                row
                for row in ordered_decisions
                if int(row["decision_sequence"]) > source_decision_sequence
                and not (
                    row.get("authority_state") == "AWAITING_RESPONSE"
                    and int(row.get("request_sequence", "0")) == request_sequence
                )
            ),
            None,
        )
        row_exact = bool(
            consumer is not None
            and int(consumer.get("request_sequence", "0")) == request_sequence
            and int(consumer.get("application_sequence", "0"))
            == int(response["application_sequence"])
            and consumer.get("response_class") == response.get("response_class")
            and int(consumer.get("actual_applied_code", "-1"))
            == int(response["applied_code"])
            and int(consumer.get("actual_dac_epoch", "-1"))
            == int(response["dac_epoch"])
            and consumer.get("downstream_epoch_exact") == "true"
        )
        exact &= row_exact
        comparisons.append(
            {
                "request_sequence": request_sequence,
                "response_record_sequence": int(
                    response["transaction_record_sequence"]
                ),
                "expected_response_class": response.get("response_class"),
                "expected_applied_code": int(response["applied_code"]),
                "expected_dac_epoch": int(response["dac_epoch"]),
                "consumer_decision_sequence": (
                    None if consumer is None else int(consumer["decision_sequence"])
                ),
                "consumer_response_class": (
                    None if consumer is None else consumer.get("response_class")
                ),
                "consumer_request_sequence": (
                    None
                    if consumer is None
                    else int(consumer.get("request_sequence", "0"))
                ),
                "consumer_application_sequence": (
                    None
                    if consumer is None
                    else int(consumer.get("application_sequence", "0"))
                ),
                "consumer_applied_code": (
                    None
                    if consumer is None
                    else int(consumer.get("actual_applied_code", "-1"))
                ),
                "consumer_dac_epoch": (
                    None
                    if consumer is None
                    else int(consumer.get("actual_dac_epoch", "-1"))
                ),
                "consumer_reason": (
                    None if consumer is None else consumer.get("reason")
                ),
                "exact": row_exact,
            }
        )
    return {"exact": exact, "comparisons": comparisons}


def _response_horizon_facts(
    active_rows: list[dict[str, str]],
    decisions: list[dict[str, str]],
    *,
    horizons_s: list[int],
    settling_exclusion_s: int,
) -> dict[str, Any]:
    applications = [row for row in active_rows if row.get("event") == "application"]
    responses = {
        int(row["request_sequence"]): row
        for row in active_rows
        if row.get("event") == "response"
    }
    decision_rows = sorted(
        decisions, key=lambda row: int(row["decision_timestamp_s"])
    )
    terminal_timestamp_s = max(
        (int(row["decision_timestamp_s"]) for row in decision_rows), default=None
    )
    per_application: list[dict[str, Any]] = []
    pooled: dict[int, list[float]] = {horizon: [] for horizon in horizons_s}
    directions: dict[int, list[bool]] = {horizon: [] for horizon in horizons_s}
    for application in applications:
        request_sequence = int(application["request_sequence"])
        applied_s = int(application["application_timestamp_s"])
        epoch = int(application["dac_epoch"])
        code = int(application["applied_code"])
        delta = int(application["requested_delta_codes"])
        pre_error = float(application["pre_error_hz"])
        next_application = next(
            (
                row
                for row in applications
                if int(row["application_timestamp_s"]) > applied_s
            ),
            None,
        )
        horizon_facts: list[dict[str, Any]] = []
        for horizon in horizons_s:
            target_s = applied_s + horizon
            source = "AHY_selected_estimate"
            candidate: dict[str, str] | None = next(
                (
                    row
                    for row in decision_rows
                    if int(row["decision_timestamp_s"]) >= target_s
                    and int(row["dac_epoch"]) == epoch
                    and int(row["current_applied_code"]) == code
                ),
                None,
            )
            if horizon == 1500 and request_sequence in responses:
                response = responses[request_sequence]
                actual_s = int(response["application_timestamp_s"]) + 1500
                observed = float(response["observed_response_hz"])
                post_error = float(response["post_error_hz"])
                source = "ACT_exact_response_checkpoint"
            elif candidate is not None:
                post_error = float(candidate["frequency_error_hz"])
                observed = post_error - pre_error
                actual_s = int(candidate["decision_timestamp_s"])
            else:
                censor_reason = (
                    "right_censored_by_subsequent_application"
                    if next_application is not None
                    and int(next_application["application_timestamp_s"]) <= target_s
                    else "right_censored_at_terminal"
                    if terminal_timestamp_s is not None
                    and terminal_timestamp_s < target_s
                    else "no_exact_same_epoch_estimate_available"
                )
                horizon_facts.append(
                    {
                        "horizon_s": horizon,
                        "available": False,
                        "censor_reason": censor_reason,
                        "target_timestamp_s": target_s,
                    }
                )
                continue
            signed = observed * delta
            gain = observed / delta
            pooled[horizon].append(gain)
            directions[horizon].append(signed > 0.0)
            horizon_facts.append(
                {
                    "horizon_s": horizon,
                    "available": True,
                    "source": source,
                    "target_timestamp_s": target_s,
                    "actual_timestamp_s": actual_s,
                    "actual_elapsed_s": actual_s - applied_s,
                    "settling_exclusion_complete": horizon >= settling_exclusion_s,
                    "pre_error_hz": pre_error,
                    "post_error_hz": post_error,
                    "observed_response_hz": observed,
                    "signed_response_with_command_hz_codes": signed,
                    "direction_matches_positive_gain_prior": signed > 0.0,
                    "observed_gain_hz_per_code": gain,
                    "dac_epoch": epoch,
                    "applied_code": code,
                }
            )
        per_application.append(
            {
                "request_sequence": request_sequence,
                "decision_sequence": int(application["decision_sequence"]),
                "application_timestamp_s": applied_s,
                "requested_delta_codes": delta,
                "applied_code": code,
                "dac_epoch": epoch,
                "horizons": horizon_facts,
            }
        )
    pooled_by_horizon: dict[str, Any] = {}
    for horizon in horizons_s:
        gains = pooled[horizon]
        signs = directions[horizon]
        pooled_by_horizon[str(horizon)] = {
            "available_application_count": len(gains),
            "positive_direction_count": sum(signs),
            "nonpositive_direction_count": len(signs) - sum(signs),
            "positive_direction_fraction": sum(signs) / len(signs) if signs else None,
            "observed_gain_hz_per_code_minimum": min(gains) if gains else None,
            "observed_gain_hz_per_code_median": (
                statistics.median(gains) if gains else None
            ),
            "observed_gain_hz_per_code_maximum": max(gains) if gains else None,
        }
    return {
        "horizons_s": horizons_s,
        "per_application": per_application,
        "pooled_by_horizon": pooled_by_horizon,
        "missing_horizons_are_explicitly_right_censored_not_zero": True,
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
    fact_gathering: bool = False,
    early_safety_terminal: bool = False,
    pre_setup_provenance_unresolved: bool = False,
) -> tuple[str, str]:
    if operator_abort:
        return "bounded_nonpass", "operator_abort"
    if pre_setup_provenance_unresolved and integrity_exact:
        return "bounded_nonpass", PRE_SETUP_PROVENANCE_UNRESOLVED
    if fact_gathering and early_safety_terminal:
        return "bounded_nonpass", "bounded_direct_hybrid_early_safety_stop"
    if platform_terminal or not integrity_exact:
        return "failed", "measurement_authority_or_platform_fault"
    if fact_gathering:
        if not policy_limits_exact:
            return "failed", "measurement_authority_or_platform_fault"
        if not endpoint_complete:
            return "bounded_nonpass", "right_censored_incomplete"
        return "passed", "bounded_direct_hybrid_evidence_acquired"
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


def _campaign18_outcome(
    *,
    integrity_exact: bool,
    operator_abort: bool,
    platform_terminal: bool,
    endpoint_complete: bool,
    terminal: dict[str, Any],
    controller_authority_inhibited: bool,
) -> tuple[str, str]:
    if operator_abort:
        return "bounded_nonpass", "cx322_d9_d6_72h_operator_abort"
    if platform_terminal:
        reason = str(terminal.get("reason", "")).lower()
        if "d9" in reason and ("configuration" in reason or "readback" in reason):
            decision = "cx322_d9_d6_72h_D9_configuration_or_readback_fault"
        elif any(item in reason for item in ("transaction", "acknowledg", "controller")):
            decision = "cx322_d9_d6_72h_controller_or_transaction_fault"
        elif any(item in reason for item in ("d14", "d8", "capture")):
            decision = "cx322_d9_d6_72h_D14_D8_authority_or_capture_fault"
        else:
            decision = "cx322_d9_d6_72h_identity_or_evidence_fault"
        return "failed", decision
    if not integrity_exact:
        return "failed", "cx322_d9_d6_72h_identity_or_evidence_fault"
    if not endpoint_complete:
        return "bounded_nonpass", "cx322_d9_d6_72h_right_censored_incomplete"
    if controller_authority_inhibited:
        return (
            "bounded_nonpass",
            "cx322_d9_d6_72h_controller_or_transaction_fault",
        )
    return "passed", "cx322_d9_d6_72h_qualified_engineering_complete"


def _sustained_regulation_outcome(
    *,
    integrity_exact: bool,
    operator_abort: bool,
    platform_terminal: bool,
    endpoint_complete: bool,
    terminal: dict[str, Any],
    supervisor_state: dict[str, Any],
    active_rows: list[dict[str, str]],
    decision_rows: list[dict[str, str]],
    phase_rows: list[dict[str, str]],
    applications: dict[str, Any],
    no_fault_or_chatter: bool,
    frequency_pass: bool,
    qualified_duration_s: int,
) -> tuple[str, str, dict[str, Any]]:
    """Apply the frozen 24-hour reversal/recovery decision contract."""

    application_rows = [
        row for row in active_rows if row.get("event") == "application"
    ]
    decisions_by_sequence = {
        int(row["decision_sequence"]): row for row in decision_rows
    }
    classified: list[dict[str, Any]] = []
    for row in application_rows:
        decision = decisions_by_sequence.get(int(row["decision_sequence"]), {})
        delta = int(row["requested_delta_codes"])
        classified.append(
            {
                "request_sequence": int(row["request_sequence"]),
                "decision_sequence": int(row["decision_sequence"]),
                "application_timestamp_s": int(row["application_timestamp_s"]),
                "applied_code": int(row["applied_code"]),
                "dac_epoch": int(row["dac_epoch"]),
                "delta_codes": delta,
                "direction": 1 if delta > 0 else -1,
                "kind": (
                    "deliberate_challenge"
                    if decision.get("reason")
                    == "deliberate_reversal_challenge_request_ready"
                    else "natural_automatic"
                ),
                "decision_reason": decision.get("reason"),
                "phase_epoch": int(decision.get("phase_epoch", "0") or "0"),
                "phase_observation_sequence": int(
                    decision.get("phase_observation_sequence", "0") or "0"
                ),
            }
        )
    natural = [row for row in classified if row["kind"] == "natural_automatic"]
    challenges = [row for row in classified if row["kind"] == "deliberate_challenge"]
    initial_natural_direction = natural[0]["direction"] if natural else None
    natural_reversal = next(
        (
            row
            for row in natural[1:]
            if row["direction"] != initial_natural_direction
        ),
        None,
    )
    challenge = challenges[0] if challenges else None
    challenge_recovery = (
        next(
            (
                row
                for row in natural
                if row["application_timestamp_s"]
                > challenge["application_timestamp_s"]
                and row["direction"] == -challenge["direction"]
            ),
            None,
        )
        if challenge is not None
        else None
    )
    reversal = challenge_recovery if challenge is not None else natural_reversal
    qualified_origin_ticks = supervisor_state.get(
        "qualified_origin_timestamp_ticks"
    )
    endpoint_device_ticks = (
        qualified_origin_ticks
        + qualified_duration_s * RP2040_TIMER0_TICKS_PER_SECOND
        if type(qualified_origin_ticks) is int
        else None
    )
    post_reversal_ticks = (
        endpoint_device_ticks
        - reversal["application_timestamp_s"]
        * RP2040_TIMER0_TICKS_PER_SECOND
        if endpoint_device_ticks is not None and reversal is not None
        else None
    )
    post_reversal_s = (
        post_reversal_ticks / RP2040_TIMER0_TICKS_PER_SECOND
        if post_reversal_ticks is not None
        else None
    )

    valid_phase = [
        row
        for row in _qualified_phase_rows(phase_rows)
        if int(row.get("phase_epoch", "0") or "0") > 0
    ]
    maximum_absolute_phase_cycles = max(
        (abs(int(row["relative_phase_cycles"])) for row in valid_phase),
        default=None,
    )
    final_phase_rows: list[dict[str, str]] = []
    final_phase_slope: float | None = None
    final_phase_slope_numerator: int | None = None
    final_phase_slope_denominator: int | None = None
    final_phase_window_contiguous = False
    if reversal is not None and valid_phase:
        terminal_phase_epoch = int(valid_phase[-1]["phase_epoch"])
        terminal_phase_sequence = int(valid_phase[-1]["observation_sequence"])
        window_start_sequence = max(
            reversal["phase_observation_sequence"],
            terminal_phase_sequence - 21_600 + 1,
        )
        final_phase_rows = [
            row
            for row in valid_phase
            if int(row["phase_epoch"]) == terminal_phase_epoch
            and int(row["observation_sequence"]) >= window_start_sequence
        ]
        if len(final_phase_rows) >= 2:
            x = [int(row["observation_sequence"]) for row in final_phase_rows]
            y = [int(row["relative_phase_cycles"]) for row in final_phase_rows]
            final_phase_window_contiguous = x == list(range(x[0], x[0] + len(x)))
            count = len(x)
            numerator = count * sum(
                x_value * y_value
                for x_value, y_value in zip(x, y, strict=True)
            ) - sum(x) * sum(y)
            denominator = count * sum(value * value for value in x) - sum(x) ** 2
            if denominator > 0:
                final_phase_slope_numerator = numerator
                final_phase_slope_denominator = denominator
                final_phase_slope = numerator / denominator

    phase_bound_pass = (
        maximum_absolute_phase_cycles is not None
        and maximum_absolute_phase_cycles <= 36
    )
    final_slope_pass = (
        final_phase_slope_numerator is not None
        and final_phase_slope_denominator is not None
        and abs(final_phase_slope_numerator) * 3600
        <= final_phase_slope_denominator
        and len(final_phase_rows) >= 21_600
        and final_phase_window_contiguous
    )
    post_reversal_pass = (
        post_reversal_ticks is not None
        and post_reversal_ticks
        >= 21_600 * RP2040_TIMER0_TICKS_PER_SECOND
    )
    physical_accounting_exact = (
        applications.get("automatic_application_count", 0) <= 12
        and applications.get("physical_control_application_count", 0) <= 13
        and applications.get("deliberate_challenge_application_count", 0) <= 1
        and applications.get("cumulative_movement_codes", 0) <= 84
    )
    facts = {
        "classified_applications": classified,
        "initial_natural_direction": initial_natural_direction,
        "natural_reversal": natural_reversal,
        "deliberate_challenge": challenge,
        "deliberate_challenge_recovery": challenge_recovery,
        "selected_reversal": reversal,
        "endpoint_device_ticks": endpoint_device_ticks,
        "counter_domain": "rp2040_timer0",
        "post_reversal_ticks": post_reversal_ticks,
        "post_reversal_qualified_s": post_reversal_s,
        "post_reversal_minimum_s": 21_600,
        "maximum_absolute_raw_relative_phase_cycles": maximum_absolute_phase_cycles,
        "maximum_absolute_raw_relative_phase_limit_cycles": 36,
        "final_phase_window_row_count": len(final_phase_rows),
        "final_phase_window_contiguous": final_phase_window_contiguous,
        "final_phase_OLS_slope_cycles_per_s": final_phase_slope,
        "final_phase_OLS_slope_exact_numerator": final_phase_slope_numerator,
        "final_phase_OLS_slope_exact_denominator": final_phase_slope_denominator,
        "maximum_absolute_final_phase_slope_cycles_per_s": 1.0 / 3600.0,
        "phase_bound_pass": phase_bound_pass,
        "final_phase_slope_pass": final_slope_pass,
        "frequency_preservation_pass": frequency_pass,
        "physical_accounting_exact": physical_accounting_exact,
        "no_chatter_or_path_exhaustion": no_fault_or_chatter,
    }
    terminal_primary = terminal.get("primary_decision")
    if platform_terminal or not integrity_exact:
        return "failed", "measurement_authority_or_platform_fault", facts
    if operator_abort:
        return "bounded_nonpass", "operator_abort", facts
    if terminal_primary == "hybrid_policy_chatter_or_path_exhaustion" or not no_fault_or_chatter:
        return "bounded_nonpass", "hybrid_policy_chatter_or_path_exhaustion", facts
    if not physical_accounting_exact:
        return "failed", "measurement_authority_or_platform_fault", facts
    if terminal_primary == "phase_or_frequency_regulation_not_sustained":
        return "bounded_nonpass", "phase_or_frequency_regulation_not_sustained", facts
    if not endpoint_complete:
        return "bounded_nonpass", "right_censored_incomplete", facts
    if reversal is None:
        if challenge is not None:
            return "bounded_nonpass", "deliberate_reversal_recovery_not_demonstrated", facts
        return "bounded_nonpass", "reversal_not_observed_within_authorized_window", facts
    if not post_reversal_pass:
        return "bounded_nonpass", "deliberate_reversal_recovery_not_demonstrated", facts
    if not (phase_bound_pass and final_slope_pass and frequency_pass):
        return "bounded_nonpass", "phase_or_frequency_regulation_not_sustained", facts
    return (
        "passed",
        (
            "sustained_hybrid_regulation_demonstrated_challenge_reversal"
            if challenge is not None
            else "sustained_hybrid_regulation_demonstrated_natural_reversal"
        ),
        facts,
    )


def _legacy_checkpoint_terminal_misclassified(
    terminal: dict[str, Any], *, checkpoint_rejection_evidence_exact: bool
) -> bool:
    """Recognize only attempt-9's exact legacy platform-label escape."""

    return (
        checkpoint_rejection_evidence_exact
        and terminal.get("result") == "aborted"
        and terminal.get("primary_decision")
        == "measurement_authority_or_platform_fault"
        and terminal.get("reason")
        == (
            "cx320_live_supervisor_fault:CX320 independent host replay "
            "differs from the firmware decision"
        )
    )


def _legacy_first_response_endpoint_misclassified(
    *,
    programme: ActiveHybridProgramme,
    terminal: dict[str, Any],
    applications: dict[str, Any],
    active_hybrid_replay_exact: bool,
    transaction_history_exact: bool,
    capsules_exact: bool,
    response_attestations_exact: bool,
    supervisor_events: list[dict[str, Any]],
    static_terminal_exact: bool,
) -> bool:
    """Recognize the integrated smoke endpoint that the old supervisor missed.

    The frozen integration contract made the phase-material checkpoint
    observational, but the live supervisor accidentally required it before
    taking the first-complete-response terminal.  Correction is deliberately
    narrow: one exact application, its complete four-phase acknowledgement
    chain, one healthy retained response, and the exact wall endpoint.
    """

    if not (
        programme.forwarded_output_integration
        and programme.terminal_after_first_response
        and progressive_checkpoint_contract(programme).get(
            "phase_material_application_count_is_acquisition_pass_gate",
            True,
        )
        is False
        and terminal.get("result") == "nonpass"
        and terminal.get("primary_decision") == "right_censored_incomplete"
        and terminal.get("reason")
        == f"{programme.key}_2h_absolute_wall_endpoint"
        and applications.get("exact") is True
        and applications.get("automatic_application_count") == 1
        and applications.get("physical_control_application_count") == 1
        and applications.get("frequency_only_application_count") == 1
        and applications.get("phase_material_application_count") == 0
        and applications.get("all_response_checkpoints_passed") is True
        and active_hybrid_replay_exact
        and transaction_history_exact
        and capsules_exact
        and response_attestations_exact
        and static_terminal_exact
    ):
        return False
    phase_acknowledgements = [
        (int(item.get("request_sequence", 0)), int(item.get("phase", 0)))
        for item in supervisor_events
        if item.get("event") == "transaction_phase_acknowledged"
    ]
    retained_responses = [
        item
        for item in supervisor_events
        if item.get("event") == "response_retained_as_nonterminal_observation"
        and item.get("response_class")
        in {"healthy_detected", "healthy_indeterminate_near_resolution", "inside_deadband"}
    ]
    return (
        phase_acknowledgements == [(1, 1), (1, 2), (1, 3), (1, 4)]
        and len(retained_responses) == 1
        and int(retained_responses[0].get("request_sequence", 0)) == 1
    )


def _legacy_plant_terminal_decision(
    terminal: dict[str, Any], rows: list[dict[str, str]]
) -> str | None:
    """Recover CX321's exact early science terminal from its retained PSQ row."""

    if not (
        rows
        and terminal.get("result") == "aborted"
        and terminal.get("primary_decision")
        == "measurement_authority_or_platform_fault"
        and terminal.get("reason")
        == "cx321_live_supervisor_fault:live active_fail_static asserted"
    ):
        return None
    return plant_sign_terminal_decision_from_record(rows[-1])


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


def _cx321_plant_sign_replay(
    run_dir: Path,
    manifest: RunManifest,
    manifest_value: dict[str, Any],
    terminal: dict[str, Any],
) -> dict[str, Any]:
    path = _contract_path(manifest, "plant_sign_qualification_v1")
    rows = _read_csv(path)
    decision = terminal.get("primary_decision") or terminal.get(
        "preliminary_decision"
    )
    corrected_decision = _legacy_plant_terminal_decision(terminal, rows)
    if corrected_decision is not None:
        decision = corrected_decision
    if not rows:
        if not isinstance(decision, str) or not decision:
            raise ValueError(
                "CX321 empty plant-sign evidence lacks a preceding terminal"
            )
        if decision in {
            "plant_sign_qualification_not_exercised",
            "plant_sign_qualification_failed",
        }:
            raise ValueError(
                "CX321 plant-sign scientific terminal lacks PSQ evidence"
            )
        return {
            "exact_replay": True,
            "scientific_terminal_exact": False,
            "right_censored_by_other_terminal": True,
            "terminal_preceded_pre1": True,
            "events": [],
        }
    bindings = manifest_value["identification"]["bindings"]
    context = PlantSignReplayContext(
        run_identity=str(manifest_value["run_identity"]),
        build_identity=str(manifest_value["firmware"]["build_identity"]),
        profile_identity=str(manifest_value["profile_identity"]),
        policy_sha256=str(manifest_value["programme_policy"]["sha256"]),
        plant_sign_gate_sha256=str(bindings["plant_sign_gate"]["sha256"]),
        identification_estimator_sha256=str(
            bindings["identification_estimator"]["sha256"]
        ),
        identification_estimator_config_sha256=str(
            manifest_value["identification"]["estimator_runtime_config"][
                "sha256"
            ]
        ),
        natural_frequency_estimator_sha256=str(
            bindings["natural_frequency_estimator"]["sha256"]
        ),
        capture_session=int(rows[0]["capture_session"]),
    )
    snapshots = _read_csv(_contract_path(manifest, "pps_snapshots_v1"))
    snapshot_proof = replay_plant_sign_windows_against_snapshots(
        rows, snapshots, context
    )
    response = next(
        (row for row in rows if row.get("event") == "response"), None
    )
    complete_chain: dict[str, Any] | None = None
    if response is not None:
        transaction_rows = _read_csv(
            _contract_path(manifest, "active_transactions_v1")
        )
        act_responses = [
            row
            for row in transaction_rows
            if row.get("event") == "response"
            and row.get("request_sequence")
            == response.get("request_sequence")
        ]
        if len(act_responses) != 1:
            raise ValueError(
                "CX321 response lacks exactly one matching ACT response"
            )
        psq_replay = replay_plant_sign_evidence(rows[:5], context)
        act_join = _join_cx321_psq_response_to_act(
            psq_response=response,
            act_response=act_responses[0],
            timer_hz=context.timer_hz,
        )
        complete_chain = complete_plant_sign_evidence_chain(
            psq_replay=psq_replay,
            snapshot_window_proof=snapshot_proof,
            act_response_join=act_join,
        )

    def with_complete_proof(result: dict[str, Any]) -> dict[str, Any]:
        return {
            **result,
            "snapshot_window_proof": snapshot_proof,
            **(
                {"complete_evidence_chain": complete_chain}
                if complete_chain is not None
                else {}
            ),
        }

    if decision in {
        "plant_sign_qualification_not_exercised",
        "plant_sign_qualification_failed",
    }:
        return with_complete_proof(
            {
                **replay_plant_sign_terminal_prefix(
                    rows, context, terminal_decision=str(decision)
                ),
                "legacy_supervisor_terminal_misclassification_corrected": (
                    corrected_decision is not None
                ),
            }
        )
    if tuple(row.get("event") for row in rows) == (
        "pre1",
        "pre2",
        "request",
        "application",
        "response",
        "response_ack",
        "handoff",
    ):
        result = replay_plant_sign_evidence(
            rows,
            context,
            require_ack_handoff=True,
            expected_ack_attestation_sha256=(
                None
                if complete_chain is None
                else str(complete_chain["attestation_sha256"])
            ),
        )
        return with_complete_proof(
            {**result, "scientific_terminal_exact": True}
        )
    # A non-plant terminal (for example an operator abort) may right-censor a
    # strictly replayed progressing prefix.  It is not plant science.
    prefix = replay_plant_sign_leading_prefix(
        rows,
        context,
        expected_ack_attestation_sha256=(
            None
            if complete_chain is None
            else str(complete_chain["attestation_sha256"])
        ),
    )
    return with_complete_proof(
        {
            **prefix,
            "scientific_terminal_exact": False,
            "right_censored_by_other_terminal": True,
        }
    )


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
    manifest_validation: dict[str, Any]
    try:
        manifest_value = validate_frozen_run_manifest(run_dir / "run_manifest.json")
        manifest_validation = {
            "mode": "current_contract",
            "current_contract_validation": True,
        }
    except ValueError:
        if supersedes_seal is None:
            raise
        manifest_value, manifest_validation = (
            _historical_manifest_for_superseding_replay(
                run_dir / "run_manifest.json", supersedes_seal
            )
        )
    programme = programme_from_mapping(manifest_value)
    if manifest_value.get("stage") != programme.live_stage:
        raise ValueError(
            f"run is not the frozen {programme.key.upper()} live stage"
        )
    manifest = RunManifest(
        root=run_dir,
        path=run_dir / "run_manifest.json",
        data=manifest_value,
    )
    policy_path = Path(str(manifest_value["policy"]["path"])).resolve()
    policy = load_policy(policy_path)
    policy_document = _read_object(policy_path)
    tight_deadband_policy_sha256 = _tight_deadband_policy_sha256(policy_document)
    metric_contract = _metric_contract(
        policy_document,
        comparison_observations=policy.phase_qualification_residence_s,
    )
    programme_section = manifest_value[programme.manifest_section]
    control = programme_section["automatic_control"]
    setup_code = int(programme_section["setup"]["code"])
    build_identity = str(manifest_value["firmware"]["build_identity"])
    spec = CampaignSpec(
        campaign=programme.campaign_name,
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
        "active_policy_sha256": (
            str(manifest_value["programme_policy"]["sha256"])
            if programme.identification_required
            else policy.policy_sha256
        ),
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
                    tight_deadband_policy_sha256=tight_deadband_policy_sha256,
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
            active_rows,
            spec.minimum_code,
            spec.maximum_code,
            response_classification_observational=(
                policy.response_checkpoint_observational
            ),
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
    plant_sign_records = (
        _read_csv(_contract_path(manifest, "plant_sign_qualification_v1"))
        if programme.identification_required
        else None
    )
    try:
        try:
            exact_estimate_rows = _read_csv(
                _contract_path(manifest, "estimates_v2")
            )
        except (KeyError, OSError, TypeError, ValueError):
            exact_estimate_rows = None
        ahy_replay = _replay_ahy(
            decision_rows,
            active_rows,
            policy_path=policy_path,
            expected_run_identity=spec.run_identity,
            expected_build_identity=build_identity,
            expected_profile_identity=spec.profile,
            expected_active_policy_sha256=(
                str(manifest_value["programme_policy"]["sha256"])
                if programme.identification_required
                else policy.policy_sha256
            ),
            plant_sign_records=plant_sign_records,
            estimate_rows=exact_estimate_rows,
            maximum_applications=programme.authorized_maximum_applications,
            maximum_cumulative_movement_codes=(
                programme.authorized_maximum_cumulative_movement_codes
            ),
            phase_checkpoint_required=bool(
                progressive_checkpoint_contract(programme).get(
                    "phase_material_application_count_is_acquisition_pass_gate",
                    True,
                )
            ),
        )
    except (KeyError, OSError, TypeError, ValueError) as exc:
        retained_input_failures.append(f"active-hybrid replay: {exc}")
        ahy_replay = {"exact": False, "error": str(exc)}

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
    (
        attestation_exact,
        attestation_hashes,
        attestation_replay,
        rejected_response_record_sequences,
    ) = _response_attestations(
        run_dir,
        active_rows,
        supervisor_events,
        programme,
        policy_path,
        (
            str(manifest_value["programme_policy"]["sha256"])
            if programme.identification_required
            else policy.policy_sha256
        ),
        allow_superseded_attestation_tool_identity=(supersedes_seal is not None),
    )
    try:
        capsule_exact, capsule_hashes = _capsules_exact(
            run_dir,
            active_rows,
            supervisor_events,
            supervisor_state,
            permitted_unacknowledged_sequences=(
                rejected_response_record_sequences
            ),
        )
    except (KeyError, OSError, TypeError, ValueError) as exc:
        capsule_exact = False
        capsule_hashes = {}
        retained_input_failures.append(f"transaction capsules: {exc}")
    terminal = supervisor_state.get("terminal", {})
    if not isinstance(terminal, dict):
        terminal = {}
    plant_sign_replay: dict[str, Any] = {
        "exact_replay": not programme.identification_required,
        "scientific_terminal_exact": not programme.identification_required,
    }
    if programme.identification_required:
        try:
            plant_sign_replay = _cx321_plant_sign_replay(
                run_dir, manifest, manifest_value, terminal
            )
        except (KeyError, OSError, TypeError, ValueError) as exc:
            retained_input_failures.append(f"CX321 plant-sign replay: {exc}")
            plant_sign_replay = {
                "exact_replay": False,
                "scientific_terminal_exact": False,
                "error": str(exc),
            }
    legacy_plant_terminal_misclassified = bool(
        plant_sign_replay.get(
            "legacy_supervisor_terminal_misclassification_corrected"
        )
    )
    operator_abort = terminal.get("primary_decision") == "operator_abort"
    response_rows = [row for row in active_rows if row.get("event") == "response"]
    terminal_rejected_response_exact = (
        len(rejected_response_record_sequences) == 1
        and bool(response_rows)
        and int(response_rows[-1]["transaction_record_sequence"])
        in rejected_response_record_sequences
    )
    checkpoint_rejection_evidence_exact = (
        terminal_rejected_response_exact
        and all(
        item.get("exact") is True
        for item in attestation_replay
        if item.get("expected_rejection") is True
        )
    )
    legacy_checkpoint_terminal_misclassified = (
        _legacy_checkpoint_terminal_misclassified(
            terminal,
            checkpoint_rejection_evidence_exact=(
                checkpoint_rejection_evidence_exact
            ),
        )
    )
    frozen_checkpoint_rejection_exact = (
        checkpoint_rejection_evidence_exact
        and (
            legacy_checkpoint_terminal_misclassified
            or terminal.get("primary_decision")
            == "hybrid_response_wrong_or_frequency_not_reacquired"
        )
    )
    platform_terminal = (
        terminal.get("primary_decision")
        == "measurement_authority_or_platform_fault"
        and not legacy_checkpoint_terminal_misclassified
        and not legacy_plant_terminal_misclassified
    )
    terminal_requires_abort = (
        terminal.get("result") in {"aborted", "nonpass"}
        and "absolute_wall_endpoint" not in str(terminal.get("reason", ""))
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
        manifest_value,
        supervisor_state,
        supervisor_events,
        markers,
        programme,
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
            maximum_automatic_applications=(
                programme.authorized_maximum_applications
            ),
            maximum_deliberate_challenges=programme.maximum_deliberate_challenges,
            maximum_cumulative=spec.cumulative_limit,
            minimum_cadence_s=int(control["minimum_applied_cadence_s"]),
            response_checkpoint_observational=(
                programme.response_checkpoint_observational
            ),
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
            "all_response_predicted_signs_observed": False,
            "all_response_checkpoints_passed": False,
            "application_epochs_exact": False,
            "dac_application_exact": False,
            "budgets_range_step_cadence_and_clamp_exact": False,
            "cumulative_movement_codes": 0,
            "error": str(exc),
        }

    response_consumer_propagation = (
        _response_dependent_consumer_propagation(active_rows, decision_rows)
        if programme.sustained_regulation
        else {"exact": True, "comparisons": []}
    )

    response_horizon_facts: dict[str, Any] | None = None
    if programme.response_checkpoint_observational:
        try:
            fact_outputs = policy_document.get("fact_gathering_outputs", {})
            horizons = fact_outputs.get("response_horizons_s")
            if horizons != [600, 1500, 3600, 7200]:
                raise ValueError("CX322 response horizons differ from the frozen set")
            response_horizon_facts = _response_horizon_facts(
                active_rows,
                decision_rows,
                horizons_s=[int(value) for value in horizons],
                settling_exclusion_s=policy.settling_exclusion_s,
            )
        except (KeyError, TypeError, ValueError) as exc:
            retained_input_failures.append(f"response horizon facts: {exc}")
            response_horizon_facts = {"exact": False, "error": str(exc)}

    try:
        tdb_replay = replay_tight_deadband(
            run_dir / TDB_CSV,
            policy_sha256=tight_deadband_policy_sha256,
        )
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
    forwarded_output_integration: dict[str, Any] | None = None
    if programme.forwarded_output_integration:
        integration_missing, integration_mismatches = (
            forwarded_output_integration_prewrite_evidence(health)
        )
        d9_missing = [
            item
            for item in integration_missing
            if not item.startswith("forwarded_clock_monitor.")
        ]
        d6_missing = [
            item
            for item in integration_missing
            if item.startswith("forwarded_clock_monitor.")
        ]
        monitor_path = _contract_path(
            manifest, "forwarded_monitor_snapshots_v1"
        )
        monitor_rows = _read_csv(monitor_path)
        d14_rows = _read_csv(_contract_path(manifest, "pps_snapshots_v1"))
        d8_rows = _read_csv(_contract_path(manifest, "count_observations_v1"))
        d14_sequences = [int(row["snapshot_sequence"]) for row in d14_rows]
        aligned_intervals_exact = (
            bool(d14_rows)
            and len(d14_rows) == len(d8_rows) == len(monitor_rows)
            and d14_sequences
            == list(range(d14_sequences[0], d14_sequences[-1] + 1))
            and all(
                d14["status"] == "0"
                and d6["status"] == "0"
                and int(d8["flags"]) & COUNT_INVALID_FLAGS == 0
                and d14["snapshot_sequence"] == d8["count_seq"]
                and d14["snapshot_sequence"] == d6["snapshot_sequence"]
                and d14["reference_timestamp_ticks"] == d8["gate_close_ticks"]
                and d14["reference_timestamp_ticks"]
                == d6["reference_timestamp_ticks"]
                and d8["channel_id"] == "2"
                and d6["channel_id"] == "3"
                for d14, d8, d6 in zip(
                    d14_rows, d8_rows, monitor_rows, strict=True
                )
            )
        )
        forwarded_output_integration = {
            "d9_digital_configuration_and_readback_exact": (
                not d9_missing and not integration_mismatches
            ),
            "d9_missing": d9_missing,
            "d9_mismatches": list(integration_mismatches),
            "d9_waveform_load_jitter_or_independent_frequency_qualified": False,
            "d6_status_observable": not d6_missing,
            "d6_status_missing": d6_missing,
            "d6_monitor_snapshot_count": len(monitor_rows),
            "d14_snapshot_count": len(d14_rows),
            "d8_count_observation_count": len(d8_rows),
            "d14_d8_d6_intervals_aligned_and_valid": aligned_intervals_exact,
            "aligned_d14_d8_d6_interval_count": (
                len(d14_rows) if aligned_intervals_exact else 0
            ),
            "d6_latest_state": health.get(
                ("forwarded_clock_monitor", "state"), "unavailable"
            ),
            "d6_latest_fault_flags": health.get(
                ("forwarded_clock_monitor", "fault_flags"), "unavailable"
            ),
            "d6_control_validity_or_terminal_authority": False,
        }
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
            and (
                supervisor_state.get("arm_pending") is False
                or legacy_plant_terminal_misclassified
            )
            and terminal_static_code is not None
            and int(terminal_static_code) == last_applied_code
        )
    except (TypeError, ValueError):
        static_terminal_exact = False
        retained_input_failures.append("terminal static code is malformed")
    pre_setup_terminal_claimed = (
        programme.forwarded_output_integration
        and programme.terminal_after_first_response
        and terminal.get("result") == "aborted"
        and terminal.get("primary_decision")
        == "measurement_authority_or_platform_fault"
        and terminal.get("reason")
        == f"{programme.key}_live_supervisor_fault:live active_fail_static asserted"
    )
    if pre_setup_terminal_claimed:
        try:
            pre_setup_command_exact = _pre_setup_commands_exact(
                markers, supervisor_events, capture_state
            )
        except (KeyError, TypeError, ValueError):
            pre_setup_command_exact = False
    else:
        # The pre-setup abort grammar is only evidence for that terminal.  A
        # successful setup has a different command grammar and must not be
        # judged by a predicate that expressly forbids ACTIVE SETUP.
        pre_setup_command_exact = True
    pre_setup_wall_origin_exact = _pre_setup_wall_origin_exact(
        manifest_value,
        supervisor_state,
        supervisor_events,
        markers,
        programme,
    )
    aligned_interval_count = (
        int(
            (forwarded_output_integration or {}).get(
                "aligned_d14_d8_d6_interval_count", 0
            )
        )
        if programme.forwarded_output_integration
        else 0
    )
    pre_setup_provenance = _pre_setup_provenance_terminal_facts(
        programme=programme,
        terminal=terminal,
        supervisor_state=supervisor_state,
        health=health,
        active_rows=active_rows,
        decision_rows=decision_rows,
        dac_rows=dac_rows,
        estimate_rows=(
            exact_estimate_rows
            if isinstance(exact_estimate_rows, list)
            else []
        ),
        command_stream_exact=pre_setup_command_exact,
        wall_origin_exact=pre_setup_wall_origin_exact,
        abort_ordering_exact=abort_ordering_exact,
        capture_closure_exact=bool(capture_closure["ok"]),
        d9_readback_exact=bool(
            forwarded_output_integration
            and forwarded_output_integration[
                "d9_digital_configuration_and_readback_exact"
            ]
        ),
        aligned_interval_count=aligned_interval_count,
    )
    pre_setup_provenance_exact = bool(pre_setup_provenance["exact"])
    if pre_setup_provenance_exact:
        retained_input_failures = [
            failure
            for failure in retained_input_failures
            if not failure.startswith("active-hybrid replay:")
        ]
        ahy_replay = {
            "exact": False,
            "not_reached_before_terminal": True,
            "reason": "no setup, application, estimate, or active-hybrid records",
        }
    legacy_first_response_endpoint_misclassified = (
        _legacy_first_response_endpoint_misclassified(
            programme=programme,
            terminal=terminal,
            applications=applications,
            active_hybrid_replay_exact=bool(ahy_replay.get("exact")),
            transaction_history_exact=transaction_history_exact,
            capsules_exact=capsule_exact,
            response_attestations_exact=attestation_exact,
            supervisor_events=supervisor_events,
            static_terminal_exact=static_terminal_exact,
        )
    )
    engineering_endpoint_complete = (
        programme.terminal_after_first_response
        and (
            (
                terminal.get("result") == "healthy_stop"
                and terminal.get("reason")
                == (
                    f"{programme.key}_first_complete_application_"
                    "consumer_and_response"
                )
            )
            or legacy_first_response_endpoint_misclassified
        )
    )
    endpoint_complete = engineering_endpoint_complete or (
        terminal.get("result") == "healthy_stop"
        and terminal.get("reason") == programme.qualified_endpoint_reason
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
        and supervisor_state.get(
            (
                "first_phase_observation_checkpoint_exact"
                if programme.response_checkpoint_observational
                else "first_phase_checkpoint_passed"
            )
        )
        is True
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
        "response_identity_through_first_dependent_decision_exact": (
            response_consumer_propagation["exact"]
        ),
        "capture_closed_cleanly_with_one_owner": capture_closure["ok"],
        "command_stream_exact": command_exact,
        "wall_origin_capture_identity_and_setup_order_exact": wall_origin_exact,
        "abort_submission_delivery_and_close_order_exact": abort_ordering_exact,
        "terminal_disarmed_evidence_clear_no_outstanding_static_code": static_terminal_exact,
        "registration_source_artifacts_present": not missing_source_artifacts,
        "retained_inputs_readable": not retained_input_failures,
        "plant_sign_evidence_replay_exact": bool(
            plant_sign_replay.get("exact_replay")
        ),
        **(
            {
                "integrated_d9_digital_configuration_and_readback_exact": bool(
                    forwarded_output_integration
                    and forwarded_output_integration[
                        "d9_digital_configuration_and_readback_exact"
                    ]
                )
            }
            if programme.forwarded_output_integration
            else {}
        ),
        **(
            {"pre_setup_provenance_terminal_exact": True}
            if pre_setup_provenance_exact
            else {}
        ),
    }
    acquisition_check_names = (
        {
            "frozen_live_manifest_exact",
            "capture_closed_cleanly_with_one_owner",
            "abort_submission_delivery_and_close_order_exact",
            "pre_setup_provenance_terminal_exact",
        }
        if pre_setup_provenance_exact
        else {
            "frozen_live_manifest_exact",
            "capture_closed_cleanly_with_one_owner",
            "command_stream_exact",
            "wall_origin_capture_identity_and_setup_order_exact",
            "abort_submission_delivery_and_close_order_exact",
            "terminal_disarmed_evidence_clear_no_outstanding_static_code",
            "response_identity_through_first_dependent_decision_exact",
        }
    )
    if programme.forwarded_output_integration:
        acquisition_check_names.add(
            "integrated_d9_digital_configuration_and_readback_exact"
        )
    acquisition_gate_passed = all(
        common_checks[name] for name in acquisition_check_names
    )
    finalization_check_names = set(common_checks)
    if pre_setup_provenance_exact:
        finalization_check_names -= {
            "transaction_history_exact",
            "raw_measurement_and_estimator_replay_exact",
            "active_hybrid_decision_and_materiality_replay_exact",
            "setup_dac_epoch_application_and_budget_exact",
            "command_stream_exact",
            "wall_origin_capture_identity_and_setup_order_exact",
            "terminal_disarmed_evidence_clear_no_outstanding_static_code",
        }
    finalization_gate_passed = all(
        common_checks[name] for name in finalization_check_names
    )
    integrity_exact = finalization_gate_passed
    sustained_regulation: dict[str, Any] | None = None
    if programme is CX322_D9_D6_72H_PROGRAMME:
        status, primary_decision = _campaign18_outcome(
            integrity_exact=integrity_exact,
            operator_abort=operator_abort,
            platform_terminal=platform_terminal,
            endpoint_complete=endpoint_complete,
            terminal=terminal,
            controller_authority_inhibited=isinstance(
                supervisor_state.get("controller_authority_inhibited_reason"),
                str,
            ),
        )
    elif programme.sustained_regulation:
        status, primary_decision, sustained_regulation = (
            _sustained_regulation_outcome(
                integrity_exact=integrity_exact,
                operator_abort=operator_abort,
                platform_terminal=platform_terminal,
                endpoint_complete=endpoint_complete,
                terminal=terminal,
                supervisor_state=supervisor_state,
                active_rows=active_rows,
                decision_rows=decision_rows,
                phase_rows=rph_rows,
                applications=applications,
                no_fault_or_chatter=no_fault_or_chatter,
                frequency_pass=bool(frequency_metrics["pass"]),
                qualified_duration_s=programme.qualified_duration_s,
            )
        )
    else:
        status, primary_decision = _classify_decision(
            integrity_exact=integrity_exact,
            operator_abort=operator_abort,
            platform_terminal=platform_terminal,
            phase_degraded=phase_degraded,
            endpoint_complete=endpoint_complete,
            material_applications=int(applications["phase_material_application_count"]),
            first_checkpoint_passed=first_checkpoint_exact,
            responses_healthy=bool(applications["all_response_checkpoints_passed"]),
            tight_reacquired_and_retained=terminal_tight_inside,
            policy_limits_exact=no_fault_or_chatter,
            phase_pass=bool(phase_metrics["pass"]),
            frequency_pass=bool(frequency_metrics["pass"]),
            minimum_material_applications=int(
                metric_contract["minimum_material_phase_applications"]
            ),
            fact_gathering=programme.response_checkpoint_observational,
            pre_setup_provenance_unresolved=pre_setup_provenance_exact,
            early_safety_terminal=(
                terminal.get("primary_decision")
                == "bounded_direct_hybrid_early_safety_stop"
            ),
        )
        if (
            programme.terminal_after_first_response
            and engineering_endpoint_complete
            and primary_decision == "bounded_direct_hybrid_evidence_acquired"
        ):
            primary_decision = "bounded_integrated_engineering_evidence_acquired"
    preliminary_decision = terminal.get("preliminary_decision")
    plant_terminal_decision = (
        plant_sign_replay.get("terminal_decision")
        if plant_sign_replay.get("scientific_terminal_exact") is True
        else terminal.get("primary_decision")
    )
    if (
        programme.identification_required
        and (plant_terminal_decision or preliminary_decision)
        in {
            "plant_sign_qualification_not_exercised",
            "plant_sign_qualification_failed",
        }
        and plant_sign_replay.get("scientific_terminal_exact") is True
    ):
        status = "bounded_nonpass"
        primary_decision = str(plant_terminal_decision or preliminary_decision)
    if primary_decision not in programme.terminal_decisions:
        raise AssertionError(
            f"{programme.key.upper()} analyzer produced an undeclared terminal decision"
        )

    scientific_acceptance_checks = {
        "minimum_two_material_physical_applications": (
            applications["phase_material_application_count"]
            >= metric_contract["minimum_material_phase_applications"]
        ),
        "first_checkpoint_passed_before_later_authority": (
            first_checkpoint_exact and progressive_authority_exact
        ),
        "all_completed_response_classifications_healthy": applications[
            "all_response_classes_healthy"
        ],
        "all_completed_response_sign_checkpoints_passed": applications[
            "all_response_predicted_signs_observed"
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
    descriptive_prior_comparisons = (
        scientific_acceptance_checks
        if programme.response_checkpoint_observational
        else None
    )

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
        "seal_type": f"{programme.key}_active_hybrid_physical_seal_v1",
        "tool": TOOL_ID,
        "tool_sha256": _sha256_file(Path(__file__)),
        "created_utc": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "programme_id": programme.programme_id,
        "stage": programme.live_stage,
        "run_id": manifest_value["run_id"],
        "run_identity": manifest_value["run_identity"],
        "build_identity": build_identity,
        "policy_sha256": policy.policy_sha256,
        "uf2_sha256": manifest_value["firmware"]["uf2"]["sha256"],
        "bundle_sha256": manifest_value["bundle"]["bundle_sha256"],
        "proposal_sha256": manifest_value["proposal"]["proposal_sha256"],
        "activation_sha256": manifest_value["activation"]["activation_sha256"],
        "manifest_validation": manifest_validation,
        "status": status,
        "primary_decision": primary_decision,
        "checks": common_checks,
        **(
            {
                "descriptive_prior_comparisons": descriptive_prior_comparisons,
                "scientific_acceptance_checks": {},
            }
            if programme.response_checkpoint_observational and not programme.sustained_regulation
            else {"scientific_acceptance_checks": scientific_acceptance_checks}
        ),
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
            "frozen_checkpoint_rejection_exact": (
                frozen_checkpoint_rejection_exact
            ),
            "unacknowledged_rejected_response_record_sequences": sorted(
                rejected_response_record_sequences
            ),
            "response_dependent_consumer_propagation": (
                response_consumer_propagation
            ),
        },
        "measurement_replay": {
            "exact": measurement_exact,
            "detail": measurement_replay,
        },
        "active_hybrid_replay": ahy_replay,
        "application_counts_and_budgets": applications,
        "pre_setup_provenance_terminal": pre_setup_provenance,
        **(
            {"forwarded_output_integration": forwarded_output_integration}
            if forwarded_output_integration is not None
            else {}
        ),
        **(
            {"sustained_regulation": sustained_regulation}
            if sustained_regulation is not None
            else {}
        ),
        **(
            {"response_horizon_facts": response_horizon_facts}
            if programme.response_checkpoint_observational
            else {}
        ),
        "frozen_metric_contract": metric_contract,
        "phase_performance": phase_metrics,
        "frequency_performance": frequency_metrics,
        "tight_deadband_replay": tdb_replay_detail,
        "plant_sign_replay": plant_sign_replay,
        "terminal": {
            "supervisor_terminal": terminal,
            "legacy_supervisor_terminal_misclassification_corrected": (
                legacy_checkpoint_terminal_misclassified
                or legacy_plant_terminal_misclassified
                or legacy_first_response_endpoint_misclassified
            ),
            "offline_corrected_primary_decision": (
                primary_decision
                if (
                    legacy_checkpoint_terminal_misclassified
                    or legacy_plant_terminal_misclassified
                    or legacy_first_response_endpoint_misclassified
                    or pre_setup_provenance_exact
                )
                else None
            ),
            "frozen_checkpoint_rejection_exact": (
                frozen_checkpoint_rejection_exact
            ),
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
        else run_dir / programme.physical_seal_path
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
