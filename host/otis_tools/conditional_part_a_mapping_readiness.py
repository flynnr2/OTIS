"""Replay a sealed CX319 Part A map against a mapping-informed Part B gate."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from statistics import stdev
from typing import Any

from .conditional_part_a_bundle import BUNDLE_TYPE
from .conditional_part_a_promotion import PROMOTION_TYPE, _classification
from .range_spanning_bundle import _atomic_new_json, canonical_sha256, sha256_file


REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEMA_VERSION = 1
TOOL_ID = "cx319_conditional_part_a_mapping_readiness_v1"
READINESS_TYPE = "cx319_mapping_informed_frequency_only_part_b_readiness_v1"
DEFAULT_CONTRACT = (
    REPO_ROOT
    / "profiles"
    / "qualification"
    / "cx319_mapping_informed_part_b_readiness_v1.json"
)

TRANSITION_SPECS = {
    "lower_outbound": [
        "lower_outbound_outside_guard",
        "lower_outbound_candidate_0",
        "lower_outbound_candidate_1",
        "lower_outbound_candidate_2",
        "lower_outbound_candidate_3",
        "lower_outbound_inside_guard",
    ],
    "lower_return": [
        "lower_return_inside_guard_new_epoch",
        "lower_return_candidate_3",
        "lower_return_candidate_2",
        "lower_return_candidate_1",
        "lower_return_candidate_0",
        "lower_return_outside_guard",
    ],
    "upper_outbound": [
        "upper_outbound_inside_guard",
        "upper_outbound_candidate_low",
        "upper_outbound_candidate_mid",
        "upper_outbound_candidate_high",
        "upper_outbound_outside_guard",
    ],
    "upper_return": [
        "upper_return_outside_guard_new_epoch",
        "upper_return_candidate_high",
        "upper_return_candidate_mid",
        "upper_return_candidate_low",
        "upper_return_inside_guard",
    ],
}


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _read(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _resolved_source_path(path: str) -> Path:
    candidate = Path(path)
    return candidate if candidate.is_absolute() else REPO_ROOT / candidate


def validate_contract(path: Path = DEFAULT_CONTRACT) -> dict[str, Any]:
    path = path.resolve()
    value = _read(path, "mapping-informed readiness contract")
    if (
        value.get("schema_version") != 1
        or value.get("contract_id")
        != "cx319_mapping_informed_part_b_readiness_v1"
        or value.get("status")
        != "frozen_offline_replay_contract_non_authorizing"
        or value.get("effective_physical_authority") is not False
    ):
        raise ValueError("mapping-informed readiness contract identity differs")
    bindings = value.get("source_bindings")
    if not isinstance(bindings, dict) or not bindings:
        raise ValueError("mapping-informed readiness sources are absent")
    for label, binding in bindings.items():
        if not isinstance(binding, dict):
            raise ValueError(f"mapping-informed source is not an object: {label}")
        source = _resolved_source_path(str(binding.get("path", "")))
        if not source.is_file() or binding.get("sha256") != sha256_file(source):
            raise ValueError(f"mapping-informed source binding differs: {label}")
    expectations = value.get("derived_expectations", {})
    direct_minimum = float(expectations.get("direct_plant_counts_per_code_minimum", 0))
    sigma = float(expectations.get("fixed_code_standard_deviation_counts", 0))
    stage5 = _read(
        _resolved_source_path(bindings["stage_5_plant_characterization"]["path"]),
        "Stage 5 plant characterization",
    )
    maximum_directional = max(
        float(item["absolute_equivalent_codes"])
        for item in stage5.get("bidirectional_hysteresis", [])
    )
    if (
        direct_minimum <= 0
        or int(expectations.get("maximum_descriptive_mixed_interval_width_codes", -1))
        != math.ceil(1.0 / direct_minimum)
        or int(expectations.get("maximum_directional_displacement_codes", -1))
        != math.ceil(maximum_directional)
        or not math.isclose(
            float(expectations.get("maximum_point_sample_standard_deviation_counts", 0)),
            2.0 * sigma,
            rel_tol=0,
            abs_tol=1e-6,
        )
        or int(expectations.get("maximum_point_observed_span_counts", -1))
        != math.ceil(4.0 * sigma)
    ):
        raise ValueError("mapping-informed derived expectation differs")
    envelope = value.get("part_b_envelope", {})
    if (
        envelope.get("maximum_step_codes") != 21
        or envelope.get("maximum_corrections_per_leg") != 9
        or envelope.get("maximum_cumulative_movement_codes_per_leg") != 189
        or envelope.get("automatic_retry") is not False
        or envelope.get("automatic_restore") is not False
        or envelope.get("phase_or_hybrid_actionable") is not False
    ):
        raise ValueError("mapping-informed Part B envelope differs")
    return value


def _describe_transition(points: list[dict[str, Any]]) -> dict[str, Any]:
    codes = [int(item["code"]) for item in points]
    counts = [list(map(int, item["integer_edge_error_counts"])) for item in points]
    classifications = [_classification(item) for item in counts]
    mixed_codes = [
        code for code, classification in zip(codes, classifications)
        if classification == "mixed"
    ]
    if mixed_codes:
        interval = [min(mixed_codes), max(mixed_codes)]
        basis = "observed_mixed_code_distribution"
    else:
        changes = [
            sorted((left, right))
            for left, right, first, second in zip(
                codes, codes[1:], classifications, classifications[1:]
            )
            if first != second
        ]
        interval = changes[0] if len(changes) == 1 else []
        basis = "adjacent_clear_classifications" if interval else "not_bracketed"
    width = interval[1] - interval[0] if len(interval) == 2 else None
    return {
        "codes": codes,
        "classifications": classifications,
        "means_counts": [sum(item) / len(item) for item in counts],
        "inside_occupancy": [
            sum(abs(value) <= 2 for value in item) / len(item) for item in counts
        ],
        "transition_interval_codes": interval,
        "transition_interval_hex": [f"0x{code:04X}" for code in interval],
        "transition_width_codes": width,
        "basis": basis,
    }


def _shared_within_direction_slope(
    grouped_points: dict[str, list[dict[str, Any]]]
) -> float:
    numerator = 0.0
    denominator = 0.0
    for points in grouped_points.values():
        rows = [
            (float(point["code"]), float(value))
            for point in points
            for value in point["integer_edge_error_counts"]
        ]
        mean_code = sum(code for code, _ in rows) / len(rows)
        mean_count = sum(count for _, count in rows) / len(rows)
        numerator += sum(
            (code - mean_code) * (count - mean_count) for code, count in rows
        )
        denominator += sum((code - mean_code) ** 2 for code, _ in rows)
    if denominator == 0:
        raise ValueError("shared within-direction slope is undefined")
    return numerator / denominator


def evaluate_mapping(
    point_results: list[dict[str, Any]], contract: dict[str, Any]
) -> dict[str, Any]:
    failures: list[str] = []
    by_role = {
        str(item.get("role", "")): item
        for item in point_results
        if isinstance(item, dict)
    }
    required_roles = {
        role for roles in TRANSITION_SPECS.values() for role in roles
    } | {
        "opening_outside_closure",
        "central_reference_before_lower",
        "central_reference_between_regions",
        "central_reference_after_upper",
        "final_outside_closure",
    }
    missing = sorted(required_roles - set(by_role))
    if missing:
        return {
            "status": "not_ready",
            "failures": [f"required_roles_absent:{','.join(missing)}"],
            "transitions": {},
        }

    grouped = {
        name: [by_role[role] for role in roles]
        for name, roles in TRANSITION_SPECS.items()
    }
    transitions = {
        name: _describe_transition(points) for name, points in grouped.items()
    }
    expectations = contract["derived_expectations"]
    maximum_width = int(
        expectations["maximum_descriptive_mixed_interval_width_codes"]
    )
    for name, transition in transitions.items():
        width = transition["transition_width_codes"]
        if width is None:
            failures.append(f"{name}:transition_not_bracketed")
        elif width > maximum_width:
            failures.append(f"{name}:mixed_interval_width_exceeds_{maximum_width}")

    directional_displacement: dict[str, Any] = {}
    maximum_displacement = int(
        expectations["maximum_directional_displacement_codes"]
    )
    for region in ("lower", "upper"):
        outbound = transitions[f"{region}_outbound"]["transition_interval_codes"]
        returned = transitions[f"{region}_return"]["transition_interval_codes"]
        if len(outbound) != 2 or len(returned) != 2:
            continue
        displacement = abs(sum(outbound) / 2.0 - sum(returned) / 2.0)
        directional_displacement[region] = {
            "outbound_midpoint_code": sum(outbound) / 2.0,
            "return_midpoint_code": sum(returned) / 2.0,
            "absolute_displacement_codes": displacement,
            "maximum_allowed_codes": maximum_displacement,
            "passed": displacement <= maximum_displacement,
        }
        if displacement > maximum_displacement:
            failures.append(f"{region}:directional_displacement_exceeds_{maximum_displacement}")

    slope = _shared_within_direction_slope(grouped)
    slope_minimum = float(expectations["manufacturer_counts_per_code_minimum"])
    slope_maximum = float(expectations["manufacturer_counts_per_code_maximum"])
    if not slope_minimum <= slope <= slope_maximum:
        failures.append("shared_positive_slope_outside_manufacturer_range")

    variance_rows = []
    maximum_stddev = float(
        expectations["maximum_point_sample_standard_deviation_counts"]
    )
    maximum_span = int(expectations["maximum_point_observed_span_counts"])
    for role in sorted(required_roles):
        counts = list(map(int, by_role[role]["integer_edge_error_counts"]))
        sample_stddev = stdev(counts) if len(counts) > 1 else 0.0
        observed_span = max(counts) - min(counts)
        passed = sample_stddev <= maximum_stddev and observed_span <= maximum_span
        variance_rows.append(
            {
                "role": role,
                "code": int(by_role[role]["code"]),
                "observation_count": len(counts),
                "sample_standard_deviation_counts": sample_stddev,
                "observed_span_counts": observed_span,
                "passed": passed,
            }
        )
        if not passed:
            failures.append(f"{role}:point_variance_exceeds_gross_screen")

    reference_roles = [
        "central_reference_before_lower",
        "central_reference_between_regions",
        "central_reference_after_upper",
    ]
    references_inside = all(
        all(abs(int(value)) <= 2 for value in by_role[role]["integer_edge_error_counts"])
        for role in reference_roles
    )
    closures_outside = all(
        all(abs(int(value)) >= 3 for value in by_role[role]["integer_edge_error_counts"])
        for role in ("opening_outside_closure", "final_outside_closure")
    )
    if not references_inside:
        failures.append("central_references_not_consistently_inside")
    if not closures_outside:
        failures.append("endpoint_closures_not_consistently_outside")

    envelope = contract["part_b_envelope"]
    inside_code = int(envelope["known_inside_reference_code"])
    maximum_step = int(envelope["maximum_step_codes"])
    maximum_corrections = int(envelope["maximum_corrections_per_leg"])
    cumulative_budget = int(envelope["maximum_cumulative_movement_codes_per_leg"])
    reachability: dict[str, Any] = {}
    for leg, setup in (
        ("lower", int(envelope["lower_setup_code"])),
        ("upper", int(envelope["upper_setup_code"])),
    ):
        required_codes = abs(inside_code - setup)
        required_corrections = math.ceil(required_codes / maximum_step)
        passed = (
            required_codes <= cumulative_budget
            and required_corrections <= maximum_corrections
        )
        reachability[leg] = {
            "setup_code": setup,
            "known_inside_code": inside_code,
            "required_movement_codes": required_codes,
            "minimum_maximum_step_corrections": required_corrections,
            "maximum_cumulative_budget_codes": cumulative_budget,
            "maximum_correction_count": maximum_corrections,
            "passed": passed,
        }
        if not passed:
            failures.append(f"{leg}:known_inside_region_not_reachable")

    return {
        "status": "ready" if not failures else "not_ready",
        "transitions": transitions,
        "directional_displacement": directional_displacement,
        "shared_within_direction_slope_counts_per_code": slope,
        "manufacturer_slope_envelope_counts_per_code": [
            slope_minimum,
            slope_maximum,
        ],
        "point_variance": variance_rows,
        "central_references_consistently_inside": references_inside,
        "endpoint_closures_consistently_outside": closures_outside,
        "part_b_reachability": reachability,
        "failures": failures,
    }


def create_readiness(
    *,
    contract_path: Path,
    part_a_bundle_path: Path,
    part_a_run_dir: Path,
    historical_promotion_path: Path,
    output_path: Path,
) -> dict[str, Any]:
    contract_path = contract_path.resolve()
    part_a_bundle_path = part_a_bundle_path.resolve()
    part_a_run_dir = part_a_run_dir.resolve()
    historical_promotion_path = historical_promotion_path.resolve()
    contract = validate_contract(contract_path)
    bundle = _read(part_a_bundle_path, "historical Part A bundle")
    bundle_unsigned = {
        key: value for key, value in bundle.items() if key != "bundle_sha256"
    }
    expected_bundle = contract["source_bindings"]["historical_v3_part_a_bundle"]
    if (
        bundle.get("schema_version") != 3
        or bundle.get("bundle_type") != BUNDLE_TYPE
        or bundle.get("bundle_sha256") != canonical_sha256(bundle_unsigned)
        or bundle.get("bundle_sha256") != expected_bundle["bundle_sha256"]
        or sha256_file(part_a_bundle_path) != expected_bundle["sha256"]
    ):
        raise ValueError("historical Part A bundle identity differs")

    paths = {
        "analysis": part_a_run_dir / "reports/range_spanning_analysis_v1.json",
        "seal": part_a_run_dir / "reports/range_spanning_seal_v1.json",
        "state": part_a_run_dir / "reports/range_spanning_supervisor_state.json",
        "complete": part_a_run_dir / "COMPLETE",
        "evidence_manifest": part_a_run_dir / "evidence_manifest.json",
        "run_manifest": part_a_run_dir / "run_manifest.json",
        "historical_promotion": historical_promotion_path,
        "active_transactions": part_a_run_dir / "csv/active_transactions_v1.csv",
    }
    analysis = _read(paths["analysis"], "Part A analysis")
    seal = _read(paths["seal"], "Part A seal")
    state = _read(paths["state"], "Part A supervisor state")
    complete = _read(paths["complete"], "Part A complete marker")
    promotion = _read(paths["historical_promotion"], "historical Part A promotion")
    promotion_unsigned = {
        key: value for key, value in promotion.items() if key != "promotion_sha256"
    }
    evidence_failures: list[str] = []
    terminal = state.get("terminal")
    if not (
        analysis.get("status") == "passed"
        and analysis.get("failures") == []
        and seal.get("status") == "passed"
        and seal.get("analysis_sha256") == analysis.get("analysis_sha256")
    ):
        evidence_failures.append("analysis_or_seal_not_exact_pass")
    if not (
        terminal == complete.get("terminal")
        and isinstance(terminal, dict)
        and terminal.get("result") == "healthy_stop"
        and terminal.get("reason") == "survey_prefix_complete"
        and int(terminal.get("completed_point_count", -1)) == 27
        and len(analysis.get("point_results", [])) == 27
    ):
        evidence_failures.append("part_a_terminal_or_point_count_differs")
    active_lines = paths["active_transactions"].read_text(encoding="utf-8").splitlines()
    if len(active_lines) > 1:
        evidence_failures.append("active_transactions_present")
    if not (
        promotion.get("schema_version") == 3
        and promotion.get("promotion_type") == PROMOTION_TYPE
        and promotion.get("status") == "not_promoted"
        and promotion.get("part_b_frequency_only_authorized") is False
        and promotion.get("promotion_sha256") == canonical_sha256(promotion_unsigned)
    ):
        evidence_failures.append("historical_non_promotion_not_preserved")

    mapping = evaluate_mapping(list(analysis.get("point_results", [])), contract)
    readiness_failures = [*evidence_failures, *mapping["failures"]]
    ready = not readiness_failures
    unsigned = {
        "schema_version": SCHEMA_VERSION,
        "readiness_type": READINESS_TYPE,
        "tool": TOOL_ID,
        "tool_sha256": sha256_file(Path(__file__)),
        "created_utc": _utc_now(),
        "status": "ready" if ready else "not_ready",
        "part_a_scientific_result": (
            "successful_transition_map" if not evidence_failures else "not_established"
        ),
        "historical_v3_promotion_status": promotion.get("status"),
        "mapping_informed_part_b_eligible": ready,
        "physical_authority_granted": False,
        "phase_or_hybrid_actuation_authorized": False,
        "contract": {
            "path": str(contract_path),
            "file_sha256": sha256_file(contract_path),
            "contract_id": contract["contract_id"],
        },
        "part_a_bundle": {
            "path": str(part_a_bundle_path),
            "file_sha256": sha256_file(part_a_bundle_path),
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "part_a_run": {
            "path": str(part_a_run_dir),
            "run_id": part_a_run_dir.name,
        },
        "source_artifacts": {
            label: {"path": str(path), "sha256": sha256_file(path)}
            for label, path in paths.items()
        },
        "source_semantic_identities": {
            "analysis_sha256": analysis.get("analysis_sha256"),
            "seal_sha256": seal.get("seal_sha256"),
            "evidence_snapshot_digest": _read(
                paths["evidence_manifest"], "Part A evidence manifest"
            ).get("snapshot_digest"),
            "historical_promotion_sha256": promotion.get("promotion_sha256"),
        },
        "mapping_evaluation": mapping,
        "evidence_failures": evidence_failures,
        "failures": readiness_failures,
        "claims_boundary": (
            "This replay accepts the sealed Part A acquisition as a successful map "
            "and establishes eligibility to freeze a new frequency-only Part B "
            "proposal. It does not alter the historical V3 non-promotion, grant "
            "physical authority, or authorize phase/hybrid actuation."
        ),
    }
    result = {**unsigned, "readiness_sha256": canonical_sha256(unsigned)}
    _atomic_new_json(output_path.resolve(), result)
    return result


def validate_readiness_record(path: Path) -> dict[str, Any]:
    path = path.resolve()
    value = _read(path, "mapping-informed Part A readiness record")
    unsigned = {key: item for key, item in value.items() if key != "readiness_sha256"}
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("readiness_type") != READINESS_TYPE
        or value.get("tool") != TOOL_ID
        or value.get("tool_sha256") != sha256_file(Path(__file__))
        or value.get("status") != "ready"
        or value.get("part_a_scientific_result") != "successful_transition_map"
        or value.get("historical_v3_promotion_status") != "not_promoted"
        or value.get("mapping_informed_part_b_eligible") is not True
        or value.get("physical_authority_granted") is not False
        or value.get("phase_or_hybrid_actuation_authorized") is not False
        or value.get("failures") != []
        or value.get("readiness_sha256") != canonical_sha256(unsigned)
    ):
        raise ValueError("mapping-informed readiness identity or outcome differs")
    contract_path = Path(value["contract"]["path"])
    contract = validate_contract(contract_path)
    if (
        value["contract"].get("file_sha256") != sha256_file(contract_path)
        or value["contract"].get("contract_id") != contract["contract_id"]
    ):
        raise ValueError("mapping-informed readiness contract binding differs")
    for label, binding in value.get("source_artifacts", {}).items():
        source = Path(binding["path"])
        if not source.is_file() or binding.get("sha256") != sha256_file(source):
            raise ValueError(f"mapping-informed readiness source differs: {label}")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    create.add_argument("--part-a-bundle", type=Path, required=True)
    create.add_argument("--part-a-run-dir", type=Path, required=True)
    create.add_argument("--historical-promotion", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("record", type=Path)
    args = parser.parse_args(argv)
    if args.command == "create":
        result = create_readiness(
            contract_path=args.contract,
            part_a_bundle_path=args.part_a_bundle,
            part_a_run_dir=args.part_a_run_dir,
            historical_promotion_path=args.historical_promotion,
            output_path=args.output,
        )
    else:
        result = validate_readiness_record(args.record)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
