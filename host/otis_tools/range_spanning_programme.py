"""Validate the frozen CX319 range-spanning programme contract."""

from __future__ import annotations

from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any

from .time_domains import time_domain


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE = (
    REPO_ROOT
    / "profiles"
    / "qualification"
    / "cx319_range_spanning_programme_v1.json"
)
PROGRAMME_ID = "CX319_RANGE_SPANNING_BIDIRECTIONAL_HYBRID_PREVIEW_V1"


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _required(value: dict[str, Any], key: str) -> dict[str, Any]:
    selected = value.get(key)
    if not isinstance(selected, dict):
        raise ValueError(f"{key} must be an object")
    return selected


def _validate_binding(binding: dict[str, Any], label: str) -> None:
    path = REPO_ROOT / str(binding.get("path", ""))
    if not path.is_file():
        raise ValueError(f"{label} source is absent: {path}")
    observed = _sha256_file(path)
    if binding.get("sha256") != observed:
        raise ValueError(
            f"{label} source hash differs: declared={binding.get('sha256')}, "
            f"observed={observed}"
        )


def _monotonic(values: list[int], direction: int) -> bool:
    return all((right - left) * direction > 0 for left, right in zip(values, values[1:]))


def load_programme(path: Path = DEFAULT_PROFILE) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != 1 or value.get("programme_id") != PROGRAMME_ID:
        raise ValueError("unsupported range-spanning programme identity")

    authority = _required(value, "operator_authority")
    required_scope = {
        "firmware_flash",
        "serial_access",
        "board_reset",
        "dac_setup_stimuli",
        "physical_rehearsal",
        "part_a_boundary_map",
        "part_b_frequency_only_traversal",
    }
    if not required_scope <= set(authority.get("scope", [])):
        raise ValueError("operator authority does not cover the physical programme")
    if (
        authority.get("phase_or_hybrid_actuation") is not False
        or authority.get("requires_exact_bundle_before_first_physical_action") is not True
        or authority.get("further_interactive_approval_required_after_exact_bundle") is not False
    ):
        raise ValueError("operator authority transition is ambiguous")

    frozen = _required(value, "frozen_inputs")
    for label in (
        "preparation_prompt",
        "lower_result",
        "upper_result",
        "plant_model",
        "selected_frequency_estimator",
        "selected_relative_phase_estimator",
        "selected_hybrid_preview",
    ):
        _validate_binding(_required(frozen, label), label)

    plant = _required(frozen, "plant_model")
    part_a = _required(value, "part_a")
    points = part_a.get("survey_point_order")
    if not isinstance(points, list) or len(points) < 10 or not all(
        isinstance(code, int) for code in points
    ):
        raise ValueError("Part A survey point order is incomplete")
    minimum = int(plant["characterized_code_min"])
    maximum = int(plant["characterized_code_max"])
    if any(not minimum <= code <= maximum for code in points):
        raise ValueError("Part A survey leaves the characterized DAC range")
    peak_index = points.index(max(points))
    if not _monotonic(points[: peak_index + 1], 1) or not _monotonic(
        points[peak_index:], -1
    ):
        raise ValueError("Part A survey is not one monotonic outbound-and-return trajectory")
    regions = _required(part_a, "survey_regions")
    for name, region in regions.items():
        direction = -1 if "decreasing" in name else 1
        if (
            not isinstance(region, list)
            or len(region) < 3
            or not _monotonic(region, direction)
            or any(abs(right - left) != 4 for left, right in zip(region, region[1:]))
            or any(code not in points for code in region)
        ):
            raise ValueError(f"Part A survey region {name} is not an exact four-code monotonic scan")
    if (
        part_a.get("frequency_control_authority") is not False
        or part_a.get("phase_hybrid_authority") is not False
        or part_a.get("selected_estimator_span_s") != 600
        or part_a.get("settling_exclusion_s") != 900
        or part_a.get("survey_fresh_observations_per_point") != 2
    ):
        raise ValueError(
            "Part A changed authority, estimator timing, or the actual "
            "two-observation deadband transition predicate"
        )

    operational_timing = _required(part_a, "operational_point_timing")
    if operational_timing != {
        "settling_exclusion_s": 900,
        "full_history_reset_s": 1500,
        "selected_estimator_span_s": 600,
        "fresh_policy_observations_required": 2,
        "ideal_minimum_point_duration_s": 2100,
        "worst_case_policy_bearing_duration_s": 2700,
        "host_wait_margin_s": 120,
        "host_wait_timeout_s": 2820,
        "minimum_remaining_wall_before_new_point_s": 3000,
        "basis": (
            "a_selected_estimate_just_before_full_history_reset_is_preserved_"
            "but_not_policy_bearing"
        ),
    }:
        raise ValueError("Part A operational point timing differs")

    fine = _required(part_a, "fine_pass")
    expected_fine = {
        "step_codes": 1,
        "minimum_region_radius_codes": 4,
        "fresh_observations_per_point_minimum": 2,
        "fresh_observations_per_point_maximum": 6,
        "boundary_adjacent_observations_minimum": 4,
        "target_bracket_width_codes": 2,
        "mixed_results_reported_as_interval": True,
        "monotonic_complete_outbound_and_return_required": True,
        "survey_derived_plan_must_be_frozen_before_fine_physical_entry": True,
    }
    if fine != expected_fine:
        raise ValueError("Part A fine-pass sequential rule differs")

    part_b = _required(value, "part_b")
    lower = int(part_b["lower_endpoint_code"])
    upper = int(part_b["upper_endpoint_code"])
    if (lower, upper) != (0xA800, 0xA890):
        raise ValueError("Part B endpoint selection differs")
    budget = _required(part_b, "prospective_automatic_budget")
    if budget != {
        "maximum_step_codes": 21,
        "maximum_corrections": 9,
        "maximum_cumulative_movement_codes": 189,
        "one_request_outstanding": True,
        "automatic_retry": False,
        "automatic_restore": False,
        "minimum_code": 0xA800,
        "maximum_code": 0xAB00,
    }:
        raise ValueError("Part B prospective movement budget differs")
    projection = _required(part_b, "endpoint_projection")
    slope = float(plant["local_slope_hz_per_code"])
    crossing = float(plant["nominal_crossing_code"])
    for code, key in (
        (lower, "lower_accumulated_counts"),
        (upper, "upper_accumulated_counts"),
    ):
        expected = (code - crossing) * slope * 600.0
        if not math.isclose(float(projection[key]), expected, rel_tol=0.0, abs_tol=1e-12):
            raise ValueError(f"Part B {key} projection differs")
    if not (
        float(projection["lower_accumulated_counts"]) < -4
        and float(projection["upper_accumulated_counts"]) > 4
    ):
        raise ValueError("Part B endpoints do not prospectively release the deadband")

    domain = _required(value, "domain_contract")
    semantics = time_domain(str(domain.get("timestamp_domain", "")))
    expected_domain = {
        "timestamp_domain": semantics.name,
        "nominal_hz": semantics.nominal_hz,
        "counter_width_bits": semantics.counter_width_bits,
        "modulus_ticks": semantics.modulus_ticks,
        "rollover": semantics.rollover,
        "maximum_unambiguous_forward_ticks": semantics.maximum_unambiguous_forward_ticks,
        "caller_controlled_rollover_switch": False,
    }
    if domain != expected_domain:
        raise ValueError("programme domain contract contradicts canonical semantics")

    zero = _required(value, "zero_authority_invariants")
    if any(zero.get(key) is not False for key in (
        "hybrid_derived_dac_request",
        "hybrid_frequency_delta_influence",
        "hybrid_frequency_eligibility_influence",
        "hybrid_budget_state_mutation",
        "phase_hybrid_actuation",
    )) or zero.get("raw_observations_preserved") is not True:
        raise ValueError("zero-authority or raw-evidence invariant differs")
    return value


def programme_summary(path: Path = DEFAULT_PROFILE) -> dict[str, Any]:
    programme = load_programme(path)
    points = programme["part_a"]["survey_point_order"]
    dwell = programme["part_a"]["settling_exclusion_s"] + (
        programme["part_a"]["selected_estimator_span_s"]
        * programme["part_a"]["survey_fresh_observations_per_point"]
    )
    return {
        "programme_id": programme["programme_id"],
        "part_a_firmware_profile": programme["part_a"]["firmware_profile"],
        "survey_point_count": len(points),
        "survey_minimum_physical_duration_s": len(points) * dwell,
        "survey_operational_worst_case_duration_s": len(points)
        * programme["part_a"]["operational_point_timing"][
            "worst_case_policy_bearing_duration_s"
        ],
        "survey_first_code": points[0],
        "survey_peak_code": max(points),
        "survey_final_code": points[-1],
        "part_b_endpoints": [
            programme["part_b"]["lower_endpoint_code"],
            programme["part_b"]["upper_endpoint_code"],
        ],
        "phase_hybrid_authority": False,
    }
