from __future__ import annotations

import ast
import csv
from dataclasses import asdict
from hashlib import sha256
import json
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

from host.otis_tools.cx318_hybrid_preview import (
    HybridCandidateEngine,
    HybridPreviewSuite,
    deterministic_digest,
    load_profile,
)
from host.otis_tools.cx318_relative_phase import CandidateEstimate, PhaseRecord


def _record(
    sequence: int,
    phase: int,
    *,
    edge_error: int | None = 0,
    phase_epoch: int = 1,
    dac_epoch: int = 0,
    qualification: str = "qualified",
    reason: str | None = None,
) -> PhaseRecord:
    return PhaseRecord(
        phase_epoch=phase_epoch,
        observation_sequence=sequence,
        capture_session=1,
        opening_snapshot_sequence=sequence,
        closing_snapshot_sequence=sequence + 1,
        opening_reference_sequence=sequence,
        closing_reference_sequence=sequence + 1,
        dac_epoch=dac_epoch,
        interval_edges=None if edge_error is None else 10_000_000 + edge_error,
        edge_error_cycles=edge_error,
        relative_phase_cycles=phase,
        relative_phase_time_ns=phase * 100,
        qualification_state=qualification,
        observation_age_s=0.0,
        discontinuity_reason=reason,
        calibrated_uncertainty_status="unavailable",
        source_backend="pio_wait_cumulative_snapshot_dma_v1",
        method_id="CX318_RELATIVE_PHASE_RAW_ACCUMULATOR_V1",
        configuration_sha256="a" * 64,
        accepted=qualification == "qualified",
    )


def _estimate(
    record: PhaseRecord, frequency: float | None, *, qualified: bool = True
) -> CandidateEstimate:
    return CandidateEstimate(
        candidate_id="CX318_RELATIVE_PHASE_RAW_ACCUMULATOR_V1",
        phase_epoch=record.phase_epoch,
        observation_sequence=record.observation_sequence,
        dac_epoch=record.dac_epoch,
        raw_relative_phase_cycles=record.relative_phase_cycles,
        filtered_relative_phase_cycles=float(record.relative_phase_cycles),
        estimated_frequency_error_hz=frequency,
        qualification_state="qualified" if qualified else "initializing",
        uncertainty_status="unavailable",
    )


def _engine(candidate_id: str, *, phase_enabled: bool = True, gain: float | None = None):
    profile, _ = load_profile()
    candidate = next(
        item for item in profile["candidates"] if item["candidate_id"] == candidate_id
    )
    return HybridCandidateEngine(
        profile,
        candidate,
        start_code=43_344,
        phase_enabled=phase_enabled,
        gain_hz_per_code=gain,
    )


def test_profile_is_exact_cartesian_grid_source_bound_and_zero_authority() -> None:
    profile, digest = load_profile()

    assert len(digest) == 64
    assert len(profile["candidates"]) == 12
    assert {
        (item["pull_in_time_s"], item["phase_bias_cap_hz"], item["band_policy"])
        for item in profile["candidates"]
    } == {
        (pull, cap, band)
        for pull in (3600, 10800, 21600)
        for cap in (1 / 600, 2 / 600)
        for band in ("historical_v2", "tight_hysteretic")
    }
    assert all(value is False for value in profile["authority"].values())
    assert "LOCKED" not in profile["state_machine"]["states"]
    assert profile["oscillator_identity"] == "CX317"
    assert profile["programme_label"] == "CX318"


def test_module_imports_only_host_measurement_and_validation_dependencies() -> None:
    path = Path("host/otis_tools/cx318_hybrid_preview.py")
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        node.module or ""
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    assert not any(
        forbidden in name.lower()
        for name in imported
        for forbidden in ("serial", "active", "actuator", "dac", "i2c", "transaction")
    )


def test_positive_phase_produces_negative_phase_frequency_bias_and_code_delta() -> None:
    engine = _engine("p3600_cap2_v2")
    opening = _record(0, 10, edge_error=None)
    engine.process(opening, _estimate(opening, None, qualified=False), timestamp_s=0, actual_applied_code=43_344)
    sample = _record(600, 10)
    output = engine.process(sample, _estimate(sample, 0.0), timestamp_s=600, actual_applied_code=43_344)

    assert output.phase_bias_hz == pytest.approx(-10 / 3600)
    assert output.combined_desired_frequency_change_hz < 0
    assert output.limited_delta_codes is not None and output.limited_delta_codes < 0
    assert output.shadow_code_after < output.actual_applied_code
    assert output.actionable is False
    assert output.actuation_authorized is False
    assert output.authorization_consumed is False


def test_frequency_only_zero_phase_mode_preserves_existing_sign_and_deadband() -> None:
    engine = _engine("p3600_cap1_v2", phase_enabled=False)
    opening = _record(0, 0, edge_error=None)
    engine.process(opening, _estimate(opening, None, qualified=False), timestamp_s=0, actual_applied_code=43_344)
    inside = _record(600, 0)
    held = engine.process(inside, _estimate(inside, 0.005), timestamp_s=600, actual_applied_code=43_344)
    outside = _record(2400, 0)
    corrected = engine.process(outside, _estimate(outside, 0.01), timestamp_s=2400, actual_applied_code=43_344)

    assert held.limited_delta_codes == 0
    assert held.shadow_code_after == 43_344
    assert corrected.limited_delta_codes == -21
    assert corrected.shadow_code_after == 43_323


def test_tight_band_requires_two_fresh_entry_observations_and_retains_at_three_counts() -> None:
    engine = _engine("p10800_cap1_tight", phase_enabled=False)
    opening = _record(0, 0, edge_error=None)
    engine.process(opening, _estimate(opening, None, qualified=False), timestamp_s=0, actual_applied_code=43_344)
    first = _record(600, 0)
    output1 = engine.process(first, _estimate(first, 2 / 600), timestamp_s=600, actual_applied_code=43_344)
    second = _record(1200, 0)
    output2 = engine.process(second, _estimate(second, 2 / 600), timestamp_s=1200, actual_applied_code=43_344)
    three = _record(1800, 0)
    output3 = engine.process(three, _estimate(three, 3 / 600), timestamp_s=1800, actual_applied_code=43_344)

    assert output1.band_state_after == "REQUALIFY_OUTSIDE"
    assert output2.band_state_after == "INSIDE"
    assert output3.band_state_after == "INSIDE"


def test_phase_step_hold_preserves_raw_phase_then_recovers_with_fresh_support() -> None:
    engine = _engine("p3600_cap1_v2")
    opening = _record(0, 0, edge_error=None)
    engine.process(opening, _estimate(opening, None, qualified=False), timestamp_s=0, actual_applied_code=43_344)
    step = _record(1, 5, edge_error=5)
    held = engine.process(
        step,
        _estimate(step, None, qualified=False),
        timestamp_s=1,
        actual_applied_code=43_344,
        phase_step_detected=True,
    )
    before_recovery = _record(600, 5)
    waiting = engine.process(before_recovery, _estimate(before_recovery, 0.0), timestamp_s=600, actual_applied_code=43_344)
    recovered_record = _record(601, 5)
    recovered = engine.process(recovered_record, _estimate(recovered_record, 0.0), timestamp_s=601, actual_applied_code=43_344)

    assert held.preview_state == "PHASE_STEP_HOLD_PREVIEW"
    assert held.raw_relative_phase_cycles == 5
    assert waiting.preview_state == "PHASE_STEP_HOLD_PREVIEW"
    assert recovered.preview_state == "HYBRID_TRACKING_PREVIEW"
    assert recovered.raw_relative_phase_cycles == 5


def test_single_interval_error_is_not_guessed_to_be_a_phase_step() -> None:
    engine = _engine("p3600_cap1_v2")
    opening = _record(0, 0, edge_error=None)
    engine.process(opening, _estimate(opening, None, qualified=False), timestamp_s=0, actual_applied_code=43_344)
    ambiguous = _record(1, 5, edge_error=5)
    output = engine.process(
        ambiguous,
        _estimate(ambiguous, None, qualified=False),
        timestamp_s=1,
        actual_applied_code=43_344,
    )

    assert output.preview_state != "PHASE_STEP_HOLD_PREVIEW"
    assert output.raw_relative_phase_cycles == 5


def test_reference_loss_and_new_epoch_recovery_never_join_phase_offsets() -> None:
    profile, _ = load_profile()
    suite = HybridPreviewSuite(profile, start_code=43_344)
    invalid = _record(10, 12, qualification="invalid", reason="reference_invalid_or_stale")
    lost = suite.process(invalid, None, timestamp_s=10, actual_applied_code=43_344)
    reopened = _record(0, 0, phase_epoch=2, edge_error=None, qualification="epoch_open")
    recovering = suite.process(
        reopened,
        _estimate(reopened, None, qualified=False),
        timestamp_s=11,
        actual_applied_code=43_344,
    )

    assert all(item.preview_state == "REFERENCE_LOST_PREVIEW" for item in lost)
    assert all(item.preview_state == "RECOVER_PREVIEW" for item in recovering)
    assert all(item.modeled_relative_phase_cycles == 0 for item in recovering)


def test_actual_dac_epoch_reseeds_counterfactual_but_preserves_raw_phase() -> None:
    engine = _engine("p3600_cap2_v2")
    opening = _record(0, -10, edge_error=None)
    engine.process(opening, _estimate(opening, None, qualified=False), timestamp_s=0, actual_applied_code=43_344)
    sample = _record(600, -10)
    engine.process(sample, _estimate(sample, -0.01), timestamp_s=600, actual_applied_code=43_344)
    transitioned = _record(601, -11, dac_epoch=1)
    output = engine.process(transitioned, _estimate(transitioned, None, qualified=False), timestamp_s=601, actual_applied_code=43_365)

    assert output.raw_relative_phase_cycles == -11
    assert output.modeled_relative_phase_cycles == -11
    assert output.shadow_code_after == 43_365
    assert output.decision_reason == "dac_epoch_bumpless_reseed"


def test_post_divergence_frequency_and_phase_are_explicitly_modeled() -> None:
    engine = _engine("p3600_cap2_v2")
    opening = _record(0, -20, edge_error=None)
    engine.process(opening, _estimate(opening, None, qualified=False), timestamp_s=0, actual_applied_code=43_344)
    first = _record(600, -20)
    correction = engine.process(first, _estimate(first, 0.0), timestamp_s=600, actual_applied_code=43_344)
    next_record = _record(601, -20)
    modeled = engine.process(next_record, _estimate(next_record, 0.0), timestamp_s=601, actual_applied_code=43_344)

    assert correction.counterfactual_correction is True
    assert modeled.modeled_not_observed_after_divergence is True
    assert modeled.modeled_relative_phase_cycles != modeled.raw_relative_phase_cycles
    assert modeled.modeled_frequency_error_hz != modeled.observed_frequency_error_hz


def test_gain_sensitivity_is_visible_after_counterfactual_divergence() -> None:
    profile, _ = load_profile()
    candidate = next(item for item in profile["candidates"] if item["candidate_id"] == "p3600_cap2_v2")
    gains = profile["numerical_policy"]["gain_hz_per_code"]
    engines = [
        HybridCandidateEngine(profile, candidate, start_code=43_344, gain_hz_per_code=gains[key])
        for key in ("minimum", "nominal", "maximum")
    ]
    opening = _record(0, -20, edge_error=None)
    first = _record(600, -20)
    later = _record(2400, -20)
    outputs = []
    for engine in engines:
        engine.process(opening, _estimate(opening, None, qualified=False), timestamp_s=0, actual_applied_code=43_344)
        engine.process(first, _estimate(first, 0.0), timestamp_s=600, actual_applied_code=43_344)
        outputs.append(engine.process(later, _estimate(later, 0.0), timestamp_s=2400, actual_applied_code=43_344))

    assert len({item.modeled_frequency_error_hz for item in outputs}) == 3
    assert len({item.modeled_relative_phase_cycles for item in outputs}) == 3


def test_sealed_stage7b_frequency_only_forced_zero_replays_shadow_codes_exactly() -> None:
    run = Path(
        "runs/cx317_bounded_closed_loop_acquisition/campaign_20260803T080615Z/"
        "stage7/part_b_final_20260807T073432Z"
    )
    with (run / "reports/stage7_authoritative_observations_v1.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        observations = list(csv.DictReader(handle))
    with (run / "reports/stage7_shadow_decisions_v1.csv").open(
        newline="", encoding="utf-8"
    ) as handle:
        expected = [
            row
            for row in csv.DictReader(handle)
            if row["candidate_id"] == "v2_symmetric_baseline"
        ]

    engine = _engine(
        "p3600_cap1_v2",
        phase_enabled=False,
        gain=0.00017072602587382669,
    )
    opening = _record(0, 0, edge_error=None, dac_epoch=0)
    engine.process(opening, _estimate(opening, None, qualified=False), timestamp_s=0, actual_applied_code=43_029)
    actual = []
    for row in observations:
        record = _record(
            int(row["timestamp_s"]),
            0,
            edge_error=0,
            dac_epoch=int(row["actual_dac_epoch"]),
        )
        actual.append(
            engine.process(
                record,
                _estimate(record, float(row["frequency_error_hz"])),
                timestamp_s=float(row["timestamp_s"]),
                actual_applied_code=int(row["actual_applied_code"]),
            )
        )

    assert len(actual) == len(expected)
    assert [item.shadow_code_after for item in actual] == [
        int(row["shadow_code_after"]) for row in expected
    ]
    assert [item.counterfactual_correction for item in actual] == [
        row["counterfactual_write"] == "true" for row in expected
    ]


def test_repeated_preview_is_deterministic() -> None:
    profile, _ = load_profile()

    def replay():
        suite = HybridPreviewSuite(profile, start_code=43_344)
        decisions = []
        opening = _record(0, -10, edge_error=None)
        decisions.extend(suite.process(opening, _estimate(opening, None, qualified=False), timestamp_s=0, actual_applied_code=43_344))
        for timestamp in (600, 1200, 1800, 2400, 3000):
            record = _record(timestamp, -10 - timestamp // 600)
            decisions.extend(suite.process(record, _estimate(record, -1 / 600), timestamp_s=timestamp, actual_applied_code=43_344))
        return decisions

    first = replay()
    second = replay()
    assert deterministic_digest(first) == deterministic_digest(second)
    assert [asdict(item) for item in first] == [asdict(item) for item in second]


def test_selected_profile_is_schema_valid_bound_nonactionable_and_stage4_only() -> None:
    profile_path = Path("profiles/discipline/cx318_hybrid_preview_selected_v1.json")
    schema_path = Path("schemas/cx318_hybrid_preview_selected_v1.schema.json")
    profile = json.loads(profile_path.read_text(encoding="utf-8"))
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    Draft202012Validator(schema).validate(profile)

    for binding in profile["bindings"].values():
        source = Path(binding["path"])
        assert source.is_file()
        assert sha256(source.read_bytes()).hexdigest() == binding["sha256"]
    assert profile["selection"]["selected_candidate_id"] == "p21600_cap1_v2"
    assert profile["sealed_stage7b_nominal_evidence"]["terminal_fault_preview"] is False
    assert profile["parity_and_fault_evidence"]["frequency_only_phase_forced_zero_exact"] is True
    assert all(value is False for value in profile["authority"].values())
    assert profile["stage4_boundary"]["host_firmware_parity_required_before_live_preview"] is True
