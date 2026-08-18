"""Validate the focused CX319 Part A / conditional Part B campaign contract."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROFILE = (
    REPO_ROOT
    / "profiles"
    / "qualification"
    / "cx319_conditional_range_campaign_v3.json"
)
PROGRAMME_ID = "CX319_CONDITIONAL_FINE_MAP_AND_FREQUENCY_TRAVERSAL_V3"

EXPECTED_POINT_PLAN = [
    (0xA800, "opening_outside_closure", 2, 2),
    (0xA830, "central_reference_before_lower", 4, 4),
    (0xA817, "lower_outbound_outside_guard", 4, 6),
    (0xA819, "lower_outbound_candidate_0", 4, 6),
    (0xA81B, "lower_outbound_candidate_1", 4, 6),
    (0xA81D, "lower_outbound_candidate_2", 4, 6),
    (0xA81F, "lower_outbound_candidate_3", 4, 6),
    (0xA821, "lower_outbound_inside_guard", 4, 6),
    (0xA821, "lower_return_inside_guard_new_epoch", 4, 6),
    (0xA81F, "lower_return_candidate_3", 4, 6),
    (0xA81D, "lower_return_candidate_2", 4, 6),
    (0xA81B, "lower_return_candidate_1", 4, 6),
    (0xA819, "lower_return_candidate_0", 4, 6),
    (0xA817, "lower_return_outside_guard", 4, 6),
    (0xA830, "central_reference_between_regions", 4, 4),
    (0xA845, "upper_outbound_inside_guard", 4, 6),
    (0xA847, "upper_outbound_candidate_low", 4, 6),
    (0xA849, "upper_outbound_candidate_mid", 4, 6),
    (0xA84B, "upper_outbound_candidate_high", 4, 6),
    (0xA84D, "upper_outbound_outside_guard", 4, 6),
    (0xA84D, "upper_return_outside_guard_new_epoch", 4, 6),
    (0xA84B, "upper_return_candidate_high", 4, 6),
    (0xA849, "upper_return_candidate_mid", 4, 6),
    (0xA847, "upper_return_candidate_low", 4, 6),
    (0xA845, "upper_return_inside_guard", 4, 6),
    (0xA830, "central_reference_after_upper", 4, 4),
    (0xA800, "final_outside_closure", 2, 2),
]


def _required(value: dict[str, Any], key: str) -> dict[str, Any]:
    selected = value.get(key)
    if not isinstance(selected, dict):
        raise ValueError(f"{key} must be an object")
    return selected


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


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


def _point_tuple(value: object) -> tuple[int, str, int, int]:
    if not isinstance(value, dict):
        raise ValueError("Part A point entries must be objects")
    return (
        int(value.get("code", -1)),
        str(value.get("role", "")),
        int(value.get("minimum_observations", -1)),
        int(value.get("maximum_observations", -1)),
    )


def load_campaign(path: Path = DEFAULT_PROFILE) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != 3 or value.get("programme_id") != PROGRAMME_ID:
        raise ValueError("unsupported conditional range campaign identity")

    authority = _required(value, "operator_authority")
    required_scope = {
        "firmware_build",
        "firmware_flash",
        "serial_access",
        "board_reset",
        "dac_setup_stimuli",
        "physical_rehearsal",
        "part_a_fine_boundary_map",
        "conditional_part_b_frequency_only_traversal",
        "evidence_analysis",
        "evidence_sealing",
        "evidence_registration",
    }
    if not required_scope <= set(authority.get("scope", [])):
        raise ValueError("operator authority does not cover the conditional campaign")
    if (
        authority.get("unattended_execution") is not True
        or authority.get("further_interactive_approval_required_after_exact_bundle") is not False
        or authority.get("phase_or_hybrid_actuation") is not False
    ):
        raise ValueError("operator authority transition is ambiguous")

    frozen = _required(value, "frozen_inputs")
    for label in (
        "preparation_prompt",
        "complete_survey_result",
        "v2_abort_and_recovery_basis",
        "plant_model",
        "selected_frequency_estimator",
        "selected_relative_phase_estimator",
        "tight_deadband_policy",
        "hybrid_preview_baseline",
    ):
        _validate_binding(_required(frozen, label), label)

    model = _required(value, "survey_derived_linear_model")
    if not (
        0.10 <= float(model.get("counts_per_code", 0.0)) <= 0.12
        and float(model.get("maximum_absolute_residual_counts", 1.0)) < 0.6
        and model.get("model_role")
        == "survey_derived_design_and_promotion_envelope_not_calibrated_uncertainty"
    ):
        raise ValueError("survey-derived focusing model differs")

    part_a = _required(value, "part_a")
    if (
        part_a.get("firmware_profile") != "cx319_range_map_part_a"
        or part_a.get("frequency_control_authority") is not False
        or part_a.get("phase_hybrid_authority") is not False
        or part_a.get("selected_estimator_span_s") != 600
        or part_a.get("settling_exclusion_s") != 900
    ):
        raise ValueError("Part A identity, timing, or zero-authority contract differs")
    if part_a.get("fresh_prewrite_reference_requirements") != {
        "d14_rejected_short_count": 0,
        "d14_rejected_long_count": 0,
        "pps_interval_anomaly_count": 0,
        "raw_pps_control_eligible": True,
    }:
        raise ValueError("Part A fresh D14 prewrite requirements differ")
    points = part_a.get("point_plan")
    if not isinstance(points, list) or [_point_tuple(item) for item in points] != EXPECTED_POINT_PLAN:
        raise ValueError("Part A focused point plan differs")
    adaptive = _required(part_a, "adaptive_observation_rule")
    if adaptive != {
        "minimum": 2,
        "boundary_minimum": 4,
        "maximum": 6,
        "extend_to_maximum_when_absolute_counts_mix_two_and_three_or_include_both_entry_and_outside_evidence": True,
        "same_code_application_opens_new_epoch": True,
    }:
        raise ValueError("Part A adaptive observation rule differs")
    gate = _required(part_a, "promotion_gate")
    if not all(
        gate.get(key) is True
        for key in (
            "requires_complete_plan",
            "requires_zero_active_transactions",
            "requires_zero_phase_hybrid_authority",
            "requires_all_reference_capture_transport_partition_and_queue_health",
            "requires_lower_guards_outside_inside",
            "requires_upper_guards_inside_outside",
            "requires_each_direction_single_contiguous_transition_or_honest_mixed_interval",
            "part_b_budget_must_cover_observed_envelope",
        )
    ) or gate.get("maximum_unmixed_transition_bracket_codes") != 2:
        raise ValueError("Part A promotion gate differs")

    part_b = _required(value, "part_b")
    expected_legs = [
        ("lower_acquisition", "cx319_range_part_b_lower", 0xA800, "positive"),
        ("upper_acquisition", "cx319_range_part_b_upper", 0xA890, "negative"),
        ("lower_reacquisition", "cx319_range_part_b_lower", 0xA800, "positive"),
    ]
    observed_legs = [
        (
            str(item.get("leg_id", "")),
            str(item.get("profile_id", "")),
            int(item.get("setup_code", -1)),
            str(item.get("required_direction", "")),
        )
        for item in part_b.get("legs", [])
        if isinstance(item, dict)
    ]
    if (
        observed_legs != expected_legs
        or part_b.get("phase_hybrid_authority") is not False
        or part_b.get("automatic_retry") is not False
        or part_b.get("automatic_restore") is not False
        or part_b.get("minimum_code") != 0xA800
        or part_b.get("maximum_code") != 0xAB00
        or part_b.get("maximum_step_codes") != 21
        or part_b.get("maximum_corrections_per_leg") != 9
        or part_b.get("maximum_cumulative_movement_codes_per_leg") != 189
        or part_b.get("minimum_applied_cadence_s") != 1800
    ):
        raise ValueError("conditional Part B sequence or authority envelope differs")

    monitoring = _required(value, "monitoring")
    if (
        monitoring.get("authoritative_state_required") is not True
        or monitoring.get("stable_poll_interval_s") != 300
        or monitoring.get("stale_evidence_timeout_s") != 900
    ):
        raise ValueError("unattended monitoring contract differs")
    return value


def campaign_summary(path: Path = DEFAULT_PROFILE) -> dict[str, Any]:
    campaign = load_campaign(path)
    part_a = campaign["part_a"]
    points = part_a["point_plan"]
    point_count = len(points)
    minimum_observations = sum(item["minimum_observations"] for item in points)
    maximum_observations = sum(item["maximum_observations"] for item in points)
    base_two_observation_worst_s = part_a["point_timing"][
        "two_observation_worst_case_s"
    ]
    additional_s = part_a["point_timing"]["additional_observation_s"]
    return {
        "programme_id": campaign["programme_id"],
        "part_a_point_count": point_count,
        "part_a_minimum_observations": minimum_observations,
        "part_a_maximum_observations": maximum_observations,
        "part_a_operational_minimum_s": point_count * base_two_observation_worst_s
        + (minimum_observations - 2 * point_count) * additional_s,
        "part_a_operational_maximum_s": point_count * base_two_observation_worst_s
        + (maximum_observations - 2 * point_count) * additional_s,
        "part_b_leg_count": len(campaign["part_b"]["legs"]),
        "part_b_maximum_per_leg_s": 14_400,
        "phase_hybrid_authority": False,
    }
