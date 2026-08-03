from __future__ import annotations

from pathlib import Path

import pytest

from host.otis_tools.cx317_pps_plant_characterize import (
    AcknowledgedDwell,
    DwellSummary,
    TICKS_PER_SECOND,
    _markdown_table,
    align_acknowledged_dwells,
    bidirectional_hysteresis,
    build_interval_policy,
    characterize_run,
    crossing_and_repeatability,
    drift_cancelled_gain_samples,
    load_markdown_provenance_table,
)
from host.otis_tools.pps_cumulative_span_estimator import IntervalEvidence
from host.otis_tools.timebase import RP2040_TIMER0_MICROS_WRAP_TICKS


def _plan(codes: list[int]) -> dict:
    return {
        "sequence": [
            {"label": f"step_{index}", "code": code}
            for index, code in enumerate(codes)
        ],
        "final_safe_code": codes[-1],
    }


def test_acknowledgements_bind_plan_dac_health_and_millis_wrap_epoch() -> None:
    codes = [0xA950, 0xA850]
    wrap_ms = RP2040_TIMER0_MICROS_WRAP_TICKS // 16_000
    elapsed = [2_000, wrap_ms + 4_000]
    raw_ticks = [value * 16_000 % RP2040_TIMER0_MICROS_WRAP_TICKS for value in elapsed]
    executor = {
        "status": "complete_fail_static",
        "last_verified_code": codes[-1],
        "acknowledgements": [
            {
                "seq": index + 1,
                "requested_code": code,
                "applied_code": code,
                "clamped": False,
                "event": "manual_apply",
                "flags": 0,
            }
            for index, code in enumerate(codes)
        ],
    }
    dac_rows = [
        {
            "seq": str(index + 1),
            "elapsed_ms": str(elapsed[index]),
            "dac_code_requested": str(code),
            "dac_code_applied": str(code),
            "dac_code_clamped": "0",
            "event": "manual_apply",
            "flags": "0",
        }
        for index, code in enumerate(codes)
    ]
    health_rows = [
        {
            "component": "dac",
            "status_key": "accepted_code",
            "status_value": f"0x{code:04X}",
            "timestamp_ticks": str(raw_ticks[index]),
        }
        for index, code in enumerate(codes)
    ]

    dwells = align_acknowledged_dwells(
        _plan(codes), executor, dac_rows, health_rows
    )

    assert [item.code for item in dwells] == codes
    assert [item.accepted_unwrapped_ticks for item in dwells] == [
        value * 16_000 for value in elapsed
    ]
    assert dwells[1].accepted_unwrapped_ticks > RP2040_TIMER0_MICROS_WRAP_TICKS


def _interval(sequence: int, opening_s: int, closing_s: int) -> IntervalEvidence:
    return IntervalEvidence(
        session_id="1",
        opening_snapshot_sequence=sequence - 1,
        closing_snapshot_sequence=sequence,
        interval_counted_edges=10_000_000,
        opening_reference_event_sequence=sequence - 1,
        closing_reference_event_sequence=sequence,
        opening_reference_timestamp_ticks=opening_s * TICKS_PER_SECOND,
        closing_reference_timestamp_ticks=closing_s * TICKS_PER_SECOND,
        cnt_sequence=sequence,
    )


def test_interval_policy_excludes_precommand_transition_and_settling() -> None:
    intervals = tuple(_interval(index, index - 1, index) for index in range(1, 46))
    dwells = (
        AcknowledgedDwell(0, "first", 0xA950, 1, 15_000, 15 * TICKS_PER_SECOND, 15 * TICKS_PER_SECOND),
        AcknowledgedDwell(1, "second", 0xA850, 2, 35_000, 35 * TICKS_PER_SECOND, 35 * TICKS_PER_SECOND),
    )

    policy, ticks = build_interval_policy(intervals, dwells, settling_exclusion_s=5)

    by_sequence: dict[int, tuple[str, bool]] = {}
    for item in policy["ranges"]:
        for sequence in range(
            item["first_closing_snapshot_sequence"],
            item["last_closing_snapshot_sequence"] + 1,
        ):
            by_sequence[sequence] = (
                item["control_epoch"], item["settling_excluded"]
            )
    assert by_sequence[14] == ("pre_campaign_uncommanded", True)
    assert by_sequence[15] == (dwells[0].epoch, True)  # straddles acknowledgement
    assert by_sequence[20] == (dwells[0].epoch, True)  # opening is before cutoff
    assert by_sequence[21] == (dwells[0].epoch, False)
    assert by_sequence[35] == (dwells[1].epoch, True)
    assert by_sequence[41] == (dwells[1].epoch, False)
    assert ticks[45] == (44 * TICKS_PER_SECOND, 45 * TICKS_PER_SECOND)


def _visit(index: int, label: str, code: int, seconds: float, offset_hz: float = 0.0) -> DwellSummary:
    drift = 1e-7 * seconds
    frequency = 10_000_000.0 + 0.001 * (code - 0xA950) + drift + offset_hz
    return DwellSummary(
        index=index,
        label=label,
        epoch=f"e{index}",
        code=code,
        acknowledged_ticks=int(seconds * TICKS_PER_SECOND),
        settled_interval_count=1_500,
        selected_estimate_count=2,
        selected_count_increment_hz=1 / 600,
        selected_frequency_values_hz=(frequency, frequency),
        representative_frequency_hz=frequency,
        representative_ticks=seconds * TICKS_PER_SECOND,
        selected_population_stddev_hz=0.0,
        selected_range_hz=0.0,
        diagnostic_estimate_count=1_441,
        diagnostic_frequency_min_hz=frequency,
        diagnostic_frequency_max_hz=frequency,
    )


def test_gain_crossing_repeatability_and_hysteresis_use_bound_sequence() -> None:
    visits = (
        _visit(0, "centre_1", 0xA950, 1_000),
        _visit(1, "lower_interior_1", 0xA850, 3_400, -0.0005),
        _visit(2, "lower_endpoint", 0xA800, 5_800),
        _visit(3, "lower_interior_2", 0xA850, 8_200, 0.0005),
        _visit(4, "centre_2", 0xA950, 10_600),
        _visit(5, "upper_interior_1", 0xAA50, 13_000, -0.0005),
        _visit(6, "upper_endpoint", 0xAB00, 15_400),
        _visit(7, "upper_interior_2", 0xAA50, 17_800, 0.0005),
        _visit(8, "final_safe_centre", 0xA950, 20_200),
    )

    gains = drift_cancelled_gain_samples(visits)
    crossing, repeatability, nominal_gain = crossing_and_repeatability(
        visits, gains, 10_000_000.0 + 1e-7 * 10_600
    )
    hysteresis = bidirectional_hysteresis(visits, nominal_gain)

    assert len(gains) == 6
    assert all(item["hz_per_code"] > 0 for item in gains)
    assert crossing["nominal_code_rounded"] == 0xA950
    assert crossing["observed_drift_adjusted_bracket"] is not None
    assert repeatability["visit_count"] == 3
    assert len(hysteresis) == 2
    assert all(item["absolute_equivalent_codes"] > 0 for item in hysteresis)


def test_offline_analyser_refuses_active_capture(tmp_path: Path) -> None:
    (tmp_path / "capture_in_progress.flag").touch()
    with pytest.raises(ValueError, match="capture is still in progress"):
        characterize_run(tmp_path)


def test_markdown_table_is_padded_and_declares_alignment() -> None:
    table = _markdown_table(
        ("Name", "Value"),
        (("short", 1), ("longer name", 20)),
        alignments=("left", "right"),
    )

    assert table == [
        "| Name        | Value |",
        "| :---------- | ----: |",
        "| short       |     1 |",
        "| longer name |    20 |",
    ]


def test_completed_physical_provenance_table_is_loaded_for_rerender(tmp_path: Path) -> None:
    source = tmp_path / "PHYSICAL_SAFETY_GATE_WORKING.md"
    source.write_text(
        "# Gate\n\n"
        "## Tolerance provenance\n\n"
        "| Parameter | Threshold | Disposition | Source | Applicability | Calculation | Uncertainty | Measured | Status | Consequence |\n"
        "|---|---|---|---|---|---|---|---|---|---|\n"
        "| rail, V | 3.13..3.47 | hard safety limit | datasheet p. 2 | this rig | direct | unavailable | 3.292 | pass | stop |\n\n"
        "## Next\n",
        encoding="utf-8",
    )

    rows = load_markdown_provenance_table(source)

    assert rows == [
        {
            "parameter_and_units": "rail, V",
            "acceptance_rejection_threshold": "3.13..3.47",
            "disposition": "hard safety limit",
            "source_document_and_location": "datasheet p. 2",
            "source_conditions_and_applicability": "this rig",
            "calculation_or_conversion": "direct",
            "measurement_uncertainty_and_safety_margin": "unavailable",
            "measured_result": "3.292",
            "status": "pass",
            "consequences_of_failure": "stop",
        }
    ]
