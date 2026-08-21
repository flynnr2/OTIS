from __future__ import annotations

from collections import Counter
from hashlib import sha256
import json
import math
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DESIGN_PATH = (
    ROOT
    / "profiles/qualification/cx322_pre_envelope_response_observability_v1.json"
)


def _load(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _assert_binding(binding: dict[str, object]) -> None:
    path = ROOT / str(binding["path"])
    assert path.is_file()
    assert binding["sha256"] == _sha256(path)


def _fixture_values(design: dict[str, object]) -> list[int]:
    binding = design["bindings"]["fixed_code_fixture"]
    fixture = _load(ROOT / str(binding["path"]))
    encoding = fixture["encoding"]
    base = int(encoding["base_interval_count"])
    return [base + int(value) for value in encoding["interval_count_offsets"]]


def _timeline_rows(values: list[int], gap: int) -> list[tuple[int, int, int]]:
    prefix = [0]
    for value in values:
        prefix.append(prefix[-1] + value)

    def total(start: int, stop: int) -> int:
        return prefix[stop] - prefix[start]

    timeline_span = (2 * gap) + (3 * 1500)
    rows = []
    for origin in range(len(values) - timeline_span + 1):
        pre1 = total(origin + gap, origin + gap + 1500)
        pre2 = total(origin + gap + 1500, origin + gap + 3000)
        post_start = origin + (2 * gap) + 3000
        post = total(post_start, post_start + 1500)
        rows.append((pre1, pre2, post))
    return rows


def _string_histogram(values: list[int]) -> dict[str, int]:
    return {str(value): count for value, count in sorted(Counter(values).items())}


def test_cx322_design_binds_the_trigger_null_evidence_and_unchanged_controller() -> None:
    design = _load(DESIGN_PATH)

    _assert_binding(design["supersedes"])
    _assert_binding(design["trigger_evidence"])
    for binding in design["bindings"].values():
        _assert_binding(binding)

    trigger = design["trigger_evidence"]
    gate = design["selected_pre_stimulus_gate"]
    assert trigger["pre1_error_counts"] == 3
    assert trigger["pre2_error_counts"] == 2
    assert abs(trigger["difference_counts"]) <= gate[
        "maximum_absolute_pre_difference_counts"
    ]
    assert all(
        abs(trigger[key]) in gate["eligible_absolute_1500s_error_counts"]
        for key in ("pre1_error_counts", "pre2_error_counts")
    )
    assert trigger["pre1_error_counts"] * trigger["pre2_error_counts"] > 0
    assert gate["observed_attempt3_entry_passes"]


def test_pre_envelope_gate_exhaustively_replays_both_boundary_phases() -> None:
    design = _load(DESIGN_PATH)
    values = _fixture_values(design)
    replay = design["fixed_code_null_replay"]

    for gap, key in ((901, "noncoincident_gap_901"), (900, "aligned_gap_900")):
        declared = replay[key]
        complete_rows = _timeline_rows(values, gap)
        rows = [
            row for row in complete_rows if abs(row[1] - row[0]) <= 1
        ]

        positive = [post - max(pre1, pre2) for pre1, pre2, post in rows]
        negative = [min(pre1, pre2) - post for pre1, pre2, post in rows]
        raw_positive = [post - pre2 for _, pre2, post in rows]
        raw_negative = [pre2 - post for _, pre2, post in rows]

        assert declared["complete_timeline_placements"] == len(complete_rows)
        assert declared["eligible_pre_difference_placements"] == len(rows)
        assert math.isclose(
            declared["eligible_fraction"], len(rows) / len(complete_rows)
        )
        assert declared["pre_difference_histogram"] == _string_histogram(
            [pre2 - pre1 for pre1, pre2, _ in rows]
        )
        assert declared["positive_signed_response_histogram"] == _string_histogram(
            positive
        )
        assert declared["negative_signed_response_histogram"] == _string_histogram(
            negative
        )
        assert declared["positive_false_attributions_at_three_counts"] == sum(
            value >= 3 for value in positive
        )
        assert declared["negative_false_attributions_at_three_counts"] == sum(
            value >= 3 for value in negative
        )
        assert declared["synthetic_five_count_shift_passes"] == {
            "positive": sum(value + 5 >= 3 for value in positive),
            "negative": sum(value + 5 >= 3 for value in negative),
        }
        assert declared["synthetic_six_count_shift_passes"] == {
            "positive": sum(value + 6 >= 3 for value in positive),
            "negative": sum(value + 6 >= 3 for value in negative),
        }
        assert all(value < 3 for value in positive + negative)
        assert all(value + 6 >= 3 for value in positive + negative)

        if gap == 901:
            assert sum(value >= 3 for value in raw_positive) == 59
            assert sum(value >= 3 for value in raw_negative) == 0
        else:
            assert sum(value >= 3 for value in raw_positive) == 170
            assert sum(value >= 3 for value in raw_negative) == 0


def test_twenty_five_codes_is_the_smallest_full_replay_step_and_stays_tight() -> None:
    design = _load(DESIGN_PATH)
    derivation = design["stimulus_derivation"]
    gains = derivation["plant_gain_hz_per_code"]
    minimum_gain = gains["minimum_conservative_600s"]
    maximum_gain = gains["maximum_600s"]
    required_counts = derivation[
        "conservative_integer_shift_required_for_full_replay_sensitivity_counts"
    ]

    minimum_step = math.ceil(required_counts / (1500 * minimum_gain))
    assert minimum_step == 25
    assert derivation["minimum_full_replay_step_codes"] == minimum_step
    assert 24 * minimum_gain * 1500 < required_counts
    assert 25 * minimum_gain * 1500 > required_counts
    assert math.isclose(
        derivation["twenty_four_code_expected_response_counts_minimum"],
        24 * minimum_gain * 1500,
    )

    expected = derivation["twenty_five_code_expected_response_counts"]
    assert math.isclose(expected["minimum"], 25 * minimum_gain * 1500)
    assert math.isclose(expected["maximum"], 25 * maximum_gain * 1500)
    plant_binding = design["bindings"]["plant_reconstruction"]
    plant = _load(ROOT / str(plant_binding["path"]))
    assert derivation["retained_gain_sample_code_differences"] == sorted(
        {sample["code_difference"] for sample in plant["drift_cancelled_gain_samples"]}
    )

    # The smallest admitted pre-error is two 1500-second counts.  The largest
    # modeled response therefore produces the worst overshoot toward nominal.
    worst_post_error_counts = expected["maximum"] - 2
    assert math.isclose(
        derivation["worst_modeled_post_stimulus_absolute_1500s_error_counts"],
        worst_post_error_counts,
    )
    assert math.isclose(
        derivation["worst_modeled_post_stimulus_absolute_frequency_error_hz"],
        worst_post_error_counts / 1500,
    )
    assert (
        derivation["worst_modeled_post_stimulus_absolute_frequency_error_hz"]
        < derivation["existing_600s_TIGHT_entry_absolute_frequency_hz"]
    )
    assert derivation[
        "worst_modeled_post_stimulus_error_inside_existing_TIGHT_entry_bound"
    ]


def test_cx322_preserves_required_natural_authority_without_expanding_the_budget() -> None:
    design = _load(DESIGN_PATH)
    budget = design["prospective_campaign_budget"]
    natural_binding = design["bindings"]["unchanged_natural_controller"]
    cx321_policy = _load(ROOT / str(natural_binding["path"]))
    cx321_limits = cx321_policy["global_authority_limits"]

    assert budget["maximum_total_automatic_applications"] == cx321_limits[
        "maximum_total_automatic_applications"
    ]
    assert budget["maximum_cumulative_absolute_movement_codes"] == cx321_limits[
        "maximum_cumulative_absolute_movement_codes"
    ]
    assert budget["maximum_natural_application_step_codes_unchanged"] == cx321_policy[
        "natural_hybrid_controller"
    ]["maximum_combined_step_codes"]
    assert budget["movement_codes_remaining_after_identification"] == 84 - 25
    assert budget["maximum_identification_step_codes"] == 25
    assert budget["maximum_any_automatic_step_codes"] == 25
    assert budget[
        "movement_codes_remaining_after_two_required_maximum_natural_applications"
    ] == 84 - 25 - (2 * 21)
    assert budget["movement_codes_remaining_after_two_required_maximum_natural_applications"] >= 0
    assert design["decision"]["natural_controller_mathematics_changed"] is False

    authority = design["authority"]
    assert authority["offline_analysis"]
    assert all(
        authority[key] is False
        for key in (
            "effective",
            "firmware_flash",
            "reset",
            "serial_access",
            "setup_stimulus",
            "dac_write",
            "control_arm",
            "physical_rehearsal",
            "live_acquisition",
        )
    )
