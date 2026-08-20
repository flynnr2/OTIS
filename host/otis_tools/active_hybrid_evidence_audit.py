"""Audit the frozen CX319 handoff and recompute its active-hybrid preview summary."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from typing import Any

from .conditional_part_a_mapping_readiness import validate_readiness_record
from .conditional_part_b_bundle import (
    _validate_lower_reacquisition_predecessor,
    _validate_upper_completion_predecessor,
)
from .evidence import validate_evidence_snapshot
from .range_spanning_bundle import canonical_sha256, sha256_file
from .run_loader import load_manifest


REPO_ROOT = Path(__file__).resolve().parents[2]
PROGRAMME_SEAL = REPO_ROOT / (
    "runs/cx319_range_spanning/mapping_informed_part_b_v4_20260817/"
    "final_decision_20260818/cx319_mapping_informed_part_b_programme_seal_v1.json"
)
PROFILE_BINDINGS = (
    REPO_ROOT / "profiles/estimators/cx317_pps_gated_selected_v1.json",
    REPO_ROOT / "profiles/estimators/cx318_relative_phase_selected_v1.json",
    REPO_ROOT / "profiles/plant_models/cx317_pps_gated_v2.json",
    REPO_ROOT / "profiles/discipline/cx319_stabilized_tight_deadband_v1.json",
    REPO_ROOT / "profiles/discipline/cx319_conditional_part_b_hybrid_observation_v1.json",
)
EXPECTED_PROFILE_SHA256 = {
    "profiles/estimators/cx317_pps_gated_selected_v1.json": "5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c",
    "profiles/estimators/cx318_relative_phase_selected_v1.json": "449c828d2affeff858eb91535e81da0bc9c44840369d741dc1f917a8d662acb4",
    "profiles/plant_models/cx317_pps_gated_v2.json": "86c7acd3e22d206b1806c0ee2723b4f9051442d9624f7339982122c6caeaa0b2",
    "profiles/discipline/cx319_stabilized_tight_deadband_v1.json": "352daed21b3063c7d58dd8b266f3639f3cbed2500ff59fd2c530243727a5bb3a",
    "profiles/discipline/cx319_conditional_part_b_hybrid_observation_v1.json": "68ba4b1b915424104fb9e8331273e52d89c7957b19e973ce650cd93056ce015d",
}
EXPECTED_SUMMARY = {
    "zero_authority_hybrid_records": 38_993,
    "hybrid_tracking_preview_records": 22_787,
    "counterfactual_correction_proposals": 22,
    "nonzero_phase_term_proposals": 12,
    "material_phase_term_proposals": 9,
    "step_limited_proposals": 7,
    "range_clamped_proposals": 0,
    "fault_preview_records": 0,
}
TOOL_ID = "cx320_active_hybrid_predecessor_audit_v1"


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _validate_canonical_seal(value: dict[str, Any], label: str) -> None:
    claimed = value.get("seal_sha256")
    unsigned = {key: item for key, item in value.items() if key != "seal_sha256"}
    if claimed != canonical_sha256(unsigned):
        raise ValueError(f"{label} canonical seal_sha256 differs")


def _round_half_away(value: float) -> int:
    return math.floor(value + 0.5) if value >= 0 else math.ceil(value - 0.5)


def _frequency_only_delta(row: dict[str, str]) -> int:
    gain = 2884.5027706464516
    raw = gain * float(row["frequency_term_hz"])
    rounded = _round_half_away(min(21.0, max(-21.0, raw)))
    before = int(row["shadow_code_before"])
    requested = min(0xAB00, max(0xA800, before + rounded))
    return requested - before


def _preview_summary(paths: list[Path]) -> dict[str, int]:
    summary = {key: 0 for key in EXPECTED_SUMMARY}
    for path in paths:
        with path.open(newline="", encoding="utf-8") as handle:
            for row in csv.DictReader(handle):
                summary["zero_authority_hybrid_records"] += 1
                if row["actionable"] != "false" or row["actuation_authorized"] != "false":
                    raise ValueError(f"historical preview carries authority: {path}")
                if row["preview_state"] == "HYBRID_TRACKING_PREVIEW":
                    summary["hybrid_tracking_preview_records"] += 1
                if row["preview_state"] == "FAULT_PREVIEW":
                    summary["fault_preview_records"] += 1
                if row["counterfactual_correction"] != "true":
                    continue
                summary["counterfactual_correction_proposals"] += 1
                phase_term = float(row["phase_bias_hz"])
                if abs(phase_term) > 1e-15:
                    summary["nonzero_phase_term_proposals"] += 1
                observed_delta = int(row["counterfactual_delta_codes"])
                if _frequency_only_delta(row) != observed_delta:
                    summary["material_phase_term_proposals"] += 1
                if row["step_limited"] == "true":
                    summary["step_limited_proposals"] += 1
                if row["range_clamped"] == "true":
                    summary["range_clamped_proposals"] += 1
    return summary


def _validate_snapshot(run_dir: Path, expected: dict[str, Any]) -> dict[str, str]:
    evidence_path = run_dir / "evidence_manifest.json"
    if sha256_file(evidence_path) != expected["sha256"]:
        raise ValueError(f"evidence manifest file identity differs: {evidence_path}")
    snapshot = _read(evidence_path)
    if snapshot.get("snapshot_digest") != expected["snapshot_digest"]:
        raise ValueError(f"evidence snapshot digest differs: {evidence_path}")
    failures, warnings = validate_evidence_snapshot(run_dir, load_manifest(run_dir))
    if failures:
        raise ValueError(f"evidence snapshot validation failed for {run_dir}: {failures}")
    return {
        "path": str(evidence_path),
        "sha256": expected["sha256"],
        "snapshot_digest": expected["snapshot_digest"],
        "warnings": ";".join(warnings),
    }


def audit_predecessor(seal_path: Path = PROGRAMME_SEAL) -> dict[str, Any]:
    seal_path = seal_path.resolve()
    seal = _read(seal_path)
    if (
        seal.get("seal_type") != "cx319_mapping_informed_part_b_programme_seal_v1"
        or seal.get("programme_id") != "CX319_MAPPING_INFORMED_FREQUENCY_TRAVERSAL_V4"
        or seal.get("status") != "passed"
        or seal.get("decision") != "programme_objective_satisfied"
    ):
        raise ValueError("unexpected predecessor programme seal identity or decision")
    _validate_canonical_seal(seal, "predecessor programme")

    observed = seal["observed_results"]
    readiness_path = Path(observed["part_a_transition_map"]["path"])
    if sha256_file(readiness_path) != observed["part_a_transition_map"]["file_sha256"]:
        raise ValueError("Part A readiness file identity differs")
    readiness = validate_readiness_record(readiness_path)
    if readiness["readiness_sha256"] != observed["part_a_transition_map"]["readiness_sha256"]:
        raise ValueError("Part A readiness semantic identity differs")

    upper_path = Path(observed["part_b_upper_traversal"]["path"])
    completion_path = Path(observed["part_b_upper_completion"]["path"])
    upper = _validate_upper_completion_predecessor(upper_path)
    completion = _validate_lower_reacquisition_predecessor(completion_path)
    if completion["predecessor_leg_seal_sha256"] != upper["seal_sha256"]:
        raise ValueError("upper completion does not bind the right-censored upper leg")

    lower_path = Path(observed["part_b_lower_acquisition"]["path"])
    lower = _read(lower_path)
    for label, path, expected in (
        ("lower", lower_path, observed["part_b_lower_acquisition"]),
        ("upper", upper_path, observed["part_b_upper_traversal"]),
        ("upper completion", completion_path, observed["part_b_upper_completion"]),
    ):
        if sha256_file(path) != expected["file_sha256"]:
            raise ValueError(f"{label} bound file identity differs")
        value = _read(path)
        _validate_canonical_seal(value, label)
        if value["seal_sha256"] != expected["seal_sha256"]:
            raise ValueError(f"{label} semantic seal identity differs")

    if seal["lower_reacquisition"] != {
        **seal["lower_reacquisition"],
        "physical_acquisition_performed": False,
        "disposition": "inferred_pass",
    }:
        raise ValueError("lower reacquisition claim boundary differs")

    run_dirs = [
        lower_path.parent.parent,
        upper_path.parent.parent,
        Path(completion["run"]["path"]),
    ]
    snapshot_records = [
        _validate_snapshot(run_dirs[0], observed["part_b_lower_acquisition"]["evidence_snapshot"]),
        _validate_snapshot(run_dirs[1], observed["part_b_upper_traversal"]["evidence_snapshot"]),
        _validate_snapshot(run_dirs[2], observed["part_b_upper_completion"]["evidence_snapshot"]),
    ]
    preview_paths = [run_dir / "csv/hybrid_preview_decisions_v1.csv" for run_dir in run_dirs]
    if any(not path.is_file() for path in preview_paths):
        raise ValueError("a bound physical preview stream is missing")
    summary = _preview_summary(preview_paths)
    if summary != EXPECTED_SUMMARY:
        raise ValueError(f"physical preview summary differs: {summary}")

    profile_hashes = {}
    for path in PROFILE_BINDINGS:
        relative = path.relative_to(REPO_ROOT).as_posix()
        observed_hash = sha256_file(path)
        if observed_hash != EXPECTED_PROFILE_SHA256[relative]:
            raise ValueError(f"frozen profile identity differs: {relative}")
        profile_hashes[relative] = observed_hash

    return {
        "schema_version": 1,
        "audit_type": "cx320_active_hybrid_predecessor_audit_v1",
        "tool": TOOL_ID,
        "tool_sha256": sha256_file(Path(__file__)),
        "created_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "status": "passed",
        "programme_seal": {
            "path": str(seal_path),
            "file_sha256": sha256_file(seal_path),
            "seal_sha256": seal["seal_sha256"],
        },
        "claims_boundary": {
            "physical_part_b_acquisitions": 2,
            "upper_result_spans_original_and_completion_acquisitions": True,
            "lower_reacquisition": "inferred_not_physically_observed",
            "phase_or_hybrid_actuation_used": False,
            "upper_original_bounded_nonpass_preserved": True,
            "upper_completion_supersession": "host_only_over_unchanged_evidence",
        },
        "profile_hashes": profile_hashes,
        "evidence_snapshots": snapshot_records,
        "preview_streams": [
            {"path": str(path), "sha256": sha256_file(path)} for path in preview_paths
        ],
        "recomputed_preview_summary": summary,
        "last_confirmed_dac_state": {
            "code": 43068,
            "code_hex": "0xA83C",
            "predecessor_dac_epoch": 1,
            "future_flash_or_reset_effect": "physically_applied_code_unknown_until_new_exact_setup_acknowledgement",
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seal", type=Path, default=PROGRAMME_SEAL)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    result = audit_predecessor(args.seal)
    rendered = json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
