"""Derive the fail-closed Part A -> frequency-only Part B promotion record."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from .conditional_part_a_bundle import BUNDLE_TYPE
from .range_spanning_bundle import (
    _atomic_new_json,
    canonical_sha256,
    sha256_file,
    validate_bundle,
)


TOOL_ID = "cx319_conditional_part_a_promotion_v3"
PROMOTION_TYPE = "cx319_conditional_part_a_frequency_only_promotion_v3"


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _classification(counts: list[int]) -> str:
    inside = any(abs(value) <= 2 for value in counts)
    outside = any(abs(value) >= 3 for value in counts)
    if inside and outside:
        return "mixed"
    return "inside" if inside else "outside"


def _transition(
    points: list[dict[str, Any]], *, start: str, end: str
) -> tuple[dict[str, Any], list[str]]:
    failures: list[str] = []
    classes = [_classification(list(item["integer_edge_error_counts"])) for item in points]
    codes = [int(item["code"]) for item in points]
    rank = {start: 0, "mixed": 1, end: 2}
    if classes[0] != start:
        failures.append(f"start_guard_{classes[0]}_expected_{start}")
    if classes[-1] != end:
        failures.append(f"end_guard_{classes[-1]}_expected_{end}")
    if any(value not in rank for value in classes) or any(
        rank[right] < rank[left] for left, right in zip(classes, classes[1:])
    ):
        failures.append("noncontiguous_or_reversing_classification")
    mixed_codes = [code for code, value in zip(codes, classes) if value == "mixed"]
    if mixed_codes:
        interval = [min(mixed_codes), max(mixed_codes)]
        basis = (
            "honest_mixed_code"
            if len(mixed_codes) == 1
            else "honest_contiguous_mixed_interval"
        )
    else:
        transitions = [
            (codes[index], codes[index + 1])
            for index in range(len(codes) - 1)
            if classes[index] != classes[index + 1]
        ]
        if len(transitions) != 1:
            failures.append("single_transition_bracket_absent")
            interval = []
        else:
            interval = sorted(transitions[0])
        basis = "adjacent_clear_classifications"
    width = interval[1] - interval[0] if len(interval) == 2 else None
    if width is not None and width > 2:
        failures.append(f"transition_bracket_width_{width}_exceeds_2")
    return (
        {
            "codes": codes,
            "classifications": classes,
            "transition_interval_codes": interval,
            "transition_interval_hex": [f"0x{code:04X}" for code in interval],
            "transition_width_codes": width,
            "basis": basis,
        },
        failures,
    )


def create_promotion(
    *, bundle_path: Path, run_dir: Path, output_path: Path
) -> dict[str, Any]:
    bundle_path = bundle_path.resolve()
    run_dir = run_dir.resolve()
    bundle = validate_bundle(bundle_path)
    if bundle.get("bundle_type") != BUNDLE_TYPE:
        raise ValueError("promotion requires the focused conditional Part A bundle")
    analysis_path = run_dir / "reports/range_spanning_analysis_v1.json"
    seal_path = run_dir / "reports/range_spanning_seal_v1.json"
    state_path = run_dir / "reports/range_spanning_supervisor_state.json"
    complete_path = run_dir / "COMPLETE"
    analysis = _read(analysis_path)
    seal = _read(seal_path)
    state = _read(state_path)
    complete = _read(complete_path)
    failures: list[str] = []
    points = analysis.get("point_results", [])
    expected_count = len(bundle["part_a_segment"]["point_plans"])
    if not (
        analysis.get("status") == "passed"
        and seal.get("status") == "passed"
        and seal.get("analysis_sha256") == analysis.get("analysis_sha256")
    ):
        failures.append("part_a_analysis_or_seal_nonpass")
    if len(points) != expected_count:
        failures.append("focused_point_plan_incomplete")
    terminal = state.get("terminal")
    if not (
        terminal == complete.get("terminal")
        and isinstance(terminal, dict)
        and terminal.get("result") == "healthy_stop"
        and terminal.get("reason") == "survey_prefix_complete"
        and int(terminal.get("completed_point_count", -1)) == expected_count
    ):
        failures.append("focused_part_a_terminal_differs")

    by_role = {
        str(item.get("role", "")): item for item in points if isinstance(item, dict)
    }
    required_roles = [item["role"] for item in bundle["part_a_segment"]["point_plans"]]
    # The two new-epoch turnaround roles make every role unique.
    if sorted(by_role) != sorted(required_roles):
        failures.append("focused_point_roles_incomplete_or_duplicated")

    transition_specs = {
        "lower_outbound": (
            [
                "lower_outbound_outside_guard",
                "lower_outbound_candidate_0",
                "lower_outbound_candidate_1",
                "lower_outbound_candidate_2",
                "lower_outbound_candidate_3",
                "lower_outbound_inside_guard",
            ],
            "outside",
            "inside",
        ),
        "lower_return": (
            [
                "lower_return_inside_guard_new_epoch",
                "lower_return_candidate_3",
                "lower_return_candidate_2",
                "lower_return_candidate_1",
                "lower_return_candidate_0",
                "lower_return_outside_guard",
            ],
            "inside",
            "outside",
        ),
        "upper_outbound": (
            [
                "upper_outbound_inside_guard",
                "upper_outbound_candidate_low",
                "upper_outbound_candidate_mid",
                "upper_outbound_candidate_high",
                "upper_outbound_outside_guard",
            ],
            "inside",
            "outside",
        ),
        "upper_return": (
            [
                "upper_return_outside_guard_new_epoch",
                "upper_return_candidate_high",
                "upper_return_candidate_mid",
                "upper_return_candidate_low",
                "upper_return_inside_guard",
            ],
            "outside",
            "inside",
        ),
    }
    transitions: dict[str, Any] = {}
    if not failures:
        for name, (roles, start, end) in transition_specs.items():
            result, transition_failures = _transition(
                [by_role[role] for role in roles], start=start, end=end
            )
            transitions[name] = result
            failures.extend(f"{name}:{item}" for item in transition_failures)

    directional_displacement: dict[str, Any] = {}
    if transitions:
        for region, outbound, returned in (
            ("lower", "lower_outbound", "lower_return"),
            ("upper", "upper_outbound", "upper_return"),
        ):
            first = transitions[outbound]["transition_interval_codes"]
            second = transitions[returned]["transition_interval_codes"]
            if len(first) == len(second) == 2:
                midpoint_first = sum(first) / 2.0
                midpoint_second = sum(second) / 2.0
                displacement = abs(midpoint_first - midpoint_second)
                directional_displacement[region] = {
                    "outbound_midpoint_code": midpoint_first,
                    "return_midpoint_code": midpoint_second,
                    "absolute_displacement_codes": displacement,
                    "maximum_allowed_codes": 4,
                    "passed": displacement <= 4,
                }
                if displacement > 4:
                    failures.append(f"{region}_directional_displacement_exceeds_4")

    references = [
        item
        for item in points
        if str(item.get("role", "")).startswith("central_reference")
    ]
    closures = [
        item
        for item in points
        if str(item.get("role", ""))
        in {"opening_outside_closure", "final_outside_closure"}
    ]
    if len(references) != 3 or any(
        _classification(list(item["integer_edge_error_counts"])) != "inside"
        for item in references
    ):
        failures.append("central_drift_reference_not_consistently_inside")
    if len(closures) != 2 or any(
        _classification(list(item["integer_edge_error_counts"])) != "outside"
        for item in closures
    ):
        failures.append("endpoint_closure_not_consistently_outside")

    active_rows = run_dir / "csv/active_transactions_v1.csv"
    if active_rows.is_file() and len(active_rows.read_text(encoding="utf-8").splitlines()) > 1:
        failures.append("active_transactions_present_in_zero_authority_part_a")

    budget_checks: dict[str, Any] = {}
    if transitions:
        for leg, setup, transition_name in (
            ("lower", 0xA800, "lower_outbound"),
            ("upper", 0xA890, "upper_outbound"),
        ):
            interval = transitions[transition_name]["transition_interval_codes"]
            required = max(abs(setup - code) for code in interval) if interval else 10**9
            budget_checks[leg] = {
                "setup_code": setup,
                "maximum_observed_codes_to_transition": required,
                "maximum_cumulative_budget_codes": 189,
                "passed": required <= 189,
            }
            if required > 189:
                failures.append(f"part_b_{leg}_budget_does_not_cover_observed_transition")

    status = "promoted" if not failures else "not_promoted"
    unsigned = {
        "schema_version": 3,
        "promotion_type": PROMOTION_TYPE,
        "tool": TOOL_ID,
        "created_utc": _utc_now(),
        "status": status,
        "part_b_frequency_only_authorized": status == "promoted",
        "phase_or_hybrid_actuation_authorized": False,
        "bundle_sha256": bundle["bundle_sha256"],
        "bundle_file_sha256": sha256_file(bundle_path),
        "run_id": run_dir.name,
        "source_artifacts": {
            "analysis_sha256": analysis.get("analysis_sha256"),
            "analysis_file_sha256": sha256_file(analysis_path),
            "seal_sha256": seal.get("seal_sha256"),
            "seal_file_sha256": sha256_file(seal_path),
            "state_file_sha256": sha256_file(state_path),
            "complete_file_sha256": sha256_file(complete_path),
        },
        "transitions": transitions,
        "directional_displacement": directional_displacement,
        "reference_point_count": len(references),
        "closure_point_count": len(closures),
        "part_b_budget_checks": budget_checks,
        "failures": failures,
        "claims_boundary": (
            "Promotion authorizes only the three frozen frequency-only Part B legs; "
            "phase and hybrid preview remain non-actionable."
            if status == "promoted"
            else "Part A is sealed without Part B, phase, or hybrid actuation authority."
        ),
    }
    result = {**unsigned, "promotion_sha256": canonical_sha256(unsigned)}
    _atomic_new_json(output_path.resolve(), result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    result = create_promotion(
        bundle_path=args.bundle, run_dir=args.run_dir, output_path=args.output
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "promoted" else 1


if __name__ == "__main__":
    raise SystemExit(main())
