from __future__ import annotations

import csv
import io
import math
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from host.otis_tools.phase_frequency_hybrid_preview import HybridCandidateEngine, load_profile as load_hybrid_profile
from host.otis_tools.reference_relative_phase_estimator import CandidateSuite, RelativePhaseAccumulator, Snapshot, load_profile as load_phase_profile


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"
ENGINE = FIRMWARE / "otis_selected_phase_frequency_preview_engine.cpp"
HEADER = FIRMWARE / "otis_selected_phase_frequency_preview_engine.h"
HARNESS = ROOT / "tests/cpp/selected_phase_frequency_preview_engine_harness.cpp"
START_CODE = 0xA950
TICKS_PER_SECOND = 16_000_000
TICK_MODULUS = TICKS_PER_SECOND * (1 << 32) // 1_000_000


@dataclass(frozen=True)
class Input:
    session: int
    sequence: int
    counter: int
    reference_sequence: int
    reference_ticks: int
    status: int
    counted_edges: int | None
    dac_epoch: int
    timestamp_s: float
    actual_code: int = START_CODE
    reference_qualified: bool = True
    reset: bool = False
    phase_step: bool = False


def _compiler() -> str:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    return compiler


@pytest.fixture(scope="session")
def cx318_harness(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("cx318_stage4") / "selected_preview"
    subprocess.run(
        [
            _compiler(),
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(HARNESS),
            str(ENGINE),
            "-I",
            str(FIRMWARE),
            "-o",
            str(output),
        ],
        check=True,
        cwd=ROOT,
    )
    return output


def _run_cpp(executable: Path, inputs: list[Input]) -> list[dict[str, str]]:
    lines = [str(START_CODE)]
    for item in inputs:
        lines.append(
            " ".join(
                str(value)
                for value in (
                    item.session,
                    item.sequence,
                    item.counter,
                    item.reference_sequence,
                    item.reference_ticks,
                    item.status,
                    item.counted_edges or 0,
                    item.dac_epoch,
                    format(item.timestamp_s, ".17g"),
                    item.actual_code,
                    int(item.counted_edges is not None),
                    int(item.reference_qualified),
                    int(item.reset),
                    int(item.phase_step),
                )
            )
        )
    completed = subprocess.run(
        [str(executable)],
        input="\n".join(lines) + "\n",
        text=True,
        capture_output=True,
        check=True,
        cwd=ROOT,
    )
    return list(csv.DictReader(io.StringIO(completed.stdout)))


def _run_host(inputs: list[Input]):
    phase_profile, phase_hash = load_phase_profile()
    hybrid_profile, _ = load_hybrid_profile()
    candidate = next(
        item
        for item in hybrid_profile["candidates"]
        if item["candidate_id"] == "p21600_cap1_v2"
    )
    phase = RelativePhaseAccumulator(
        nominal_edges=10_000_000,
        timer_ticks_per_second=TICKS_PER_SECOND,
        period_ns_per_cycle=100,
        configuration_sha256=phase_hash,
        reference_timestamp_domain="rp2040_timer0",
        reference_interval_minimum_s=float(phase_profile["validity"]["reference_interval_minimum_s"]),
        reference_interval_maximum_s=float(phase_profile["validity"]["reference_interval_maximum_s"]),
    )
    estimates = CandidateSuite(phase_profile)
    hybrid = HybridCandidateEngine(hybrid_profile, candidate, start_code=START_CODE)
    outputs = []
    for item in inputs:
        record = phase.process(
            Snapshot(
                session=item.session,
                snapshot_sequence=item.sequence,
                cumulative_down_counter=item.counter,
                reference_sequence=item.reference_sequence,
                reference_timestamp_ticks=item.reference_ticks,
                status=item.status,
            ),
            counted_edges=item.counted_edges,
            reference_qualified=item.reference_qualified,
            dac_epoch=item.dac_epoch,
            reset=item.reset,
        )
        candidates = estimates.process(record)
        raw = next(
            (
                value
                for value in candidates
                if value.candidate_id == "CX318_RELATIVE_PHASE_RAW_ACCUMULATOR_V1"
            ),
            None,
        )
        if raw is None or record.qualification_state == "invalid":
            decision = hybrid.invalidate(
                record,
                timestamp_s=item.timestamp_s,
                actual_applied_code=item.actual_code,
                reason=record.discontinuity_reason or "invalid_phase_input",
            )
        else:
            decision = hybrid.process(
                record,
                raw,
                timestamp_s=item.timestamp_s,
                actual_applied_code=item.actual_code,
                phase_step_detected=item.phase_step,
            )
        outputs.append((record, raw, decision))
    return outputs


def _boolean(value: str) -> bool:
    return value == "1"


def _compare(cpp: list[dict[str, str]], host) -> None:
    assert len(cpp) == len(host)
    integer_fields = {
        "phase_epoch": lambda r, d: r.phase_epoch,
        "observation_sequence": lambda r, d: r.observation_sequence,
        "dac_epoch": lambda r, d: r.dac_epoch,
        "capture_session": lambda r, d: r.capture_session,
        "opening_snapshot_sequence": lambda r, d: r.opening_snapshot_sequence,
        "closing_snapshot_sequence": lambda r, d: r.closing_snapshot_sequence,
        "opening_reference_sequence": lambda r, d: r.opening_reference_sequence,
        "closing_reference_sequence": lambda r, d: r.closing_reference_sequence,
        "interval_edges": lambda r, d: r.interval_edges or 0,
        "edge_error_cycles": lambda r, d: r.edge_error_cycles or 0,
        "relative_phase_cycles": lambda r, d: r.relative_phase_cycles,
        "relative_phase_time_ns": lambda r, d: int(r.relative_phase_time_ns),
        "shadow_code_before": lambda r, d: d.shadow_code_before,
        "shadow_code_after": lambda r, d: d.shadow_code_after,
        "actual_applied_code": lambda r, d: d.actual_applied_code,
        "limited_delta_codes": lambda r, d: d.limited_delta_codes or 0,
        "correction_count": lambda r, d: d.correction_count,
        "cumulative_movement_codes": lambda r, d: d.cumulative_movement_codes,
        "alternating_correction_count": lambda r, d: d.alternating_correction_count,
    }
    exact_fields = {
        "phase_state": lambda r, d: r.qualification_state,
        "phase_reason": lambda r, d: r.discontinuity_reason or "",
        "band_state_before": lambda r, d: d.band_state_before,
        "band_state_after": lambda r, d: d.band_state_after,
        "preview_state": lambda r, d: d.preview_state,
        "decision_reason": lambda r, d: d.decision_reason,
    }
    boolean_fields = {
        "phase_accepted": lambda r, d: r.accepted,
        "interval_available": lambda r, d: r.interval_edges is not None,
        "frequency_available": lambda r, d: d.modeled_frequency_error_hz is not None,
        "frequency_observation_event": lambda r, d: d.frequency_observation_event,
        "counterfactual_decision": lambda r, d: d.counterfactual_decision,
        "counterfactual_correction": lambda r, d: d.counterfactual_correction,
        "raw_delta_available": lambda r, d: d.raw_delta_codes is not None,
        "step_limited": lambda r, d: d.step_limited,
        "range_clamped": lambda r, d: d.range_clamped,
        "modeled_not_observed_after_divergence": lambda r, d: d.modeled_not_observed_after_divergence,
    }
    float_fields = {
        "observed_frequency_error_hz": lambda r, d: d.observed_frequency_error_hz,
        "modeled_relative_phase_cycles": lambda r, d: d.modeled_relative_phase_cycles,
        "modeled_frequency_error_hz": lambda r, d: d.modeled_frequency_error_hz,
        "frequency_term_hz": lambda r, d: d.frequency_term_hz,
        "phase_bias_hz": lambda r, d: d.phase_bias_hz,
        "combined_desired_frequency_change_hz": lambda r, d: d.combined_desired_frequency_change_hz,
        "raw_delta_codes": lambda r, d: d.raw_delta_codes,
    }
    for actual, (record, raw_estimate, decision) in zip(cpp, host, strict=True):
        raw_frequency = (
            None
            if raw_estimate is None
            else raw_estimate.estimated_frequency_error_hz
        )
        assert _boolean(actual["raw_frequency_available"]) is (
            raw_frequency is not None
        )
        if raw_frequency is None:
            assert float(actual["raw_frequency_error_hz"]) == 0.0
        else:
            assert math.isclose(
                float(actual["raw_frequency_error_hz"]),
                float(raw_frequency),
                rel_tol=2.0 * math.ulp(float(raw_frequency))
                / max(abs(float(raw_frequency)), 1.0),
                abs_tol=max(1e-15, 2.0 * math.ulp(float(raw_frequency))),
            )
        for field, getter in integer_fields.items():
            assert int(actual[field]) == getter(record, decision), field
        for field, getter in exact_fields.items():
            assert actual[field] == getter(record, decision), field
        for field, getter in boolean_fields.items():
            assert _boolean(actual[field]) is getter(record, decision), field
        for field, getter in float_fields.items():
            expected = getter(record, decision)
            serialized = float(actual[field])
            if expected is None:
                assert serialized == 0.0, field
            else:
                # The harness serializes C++ doubles with 17 significant digits.
                # One ulp plus a tiny absolute floor is the parity contract.
                assert math.isclose(
                    serialized,
                    float(expected),
                    rel_tol=2.0 * math.ulp(float(expected)) / max(abs(float(expected)), 1.0),
                    abs_tol=max(1e-15, 2.0 * math.ulp(float(expected))),
                ), field


def _stream(edge_errors: list[int], *, start_sequence: int = 1) -> list[Input]:
    counter = 0xF0000000
    values = [
        Input(1, start_sequence, counter, start_sequence, start_sequence * TICKS_PER_SECOND, 0, None, 0, float(start_sequence))
    ]
    for offset, error in enumerate(edge_errors, start=1):
        sequence = start_sequence + offset
        edges = 10_000_000 + error
        counter = (counter - edges) % (1 << 32)
        values.append(
            Input(1, sequence, counter, sequence, sequence * TICKS_PER_SECOND, 0, edges, 0, float(sequence))
        )
    return values


def test_exact_selected_phase_and_hybrid_parity_with_rounding_and_cap(
    cx318_harness: Path,
) -> None:
    # A retained 50-cycle step makes phase bias reach the 1/600 Hz cap once the
    # rolling 600-interval frequency support no longer contains the step. The
    # resulting non-integral deltas also exercise half-away-from-zero rounding.
    inputs = _stream([50, *([0] * 2399)])
    cpp = _run_cpp(cx318_harness, inputs)
    host = _run_host(inputs)
    _compare(cpp, host)
    assert any(
        math.isclose(abs(decision.phase_bias_hz), 1 / 600, abs_tol=1e-15)
        for _, _, decision in host
    )
    assert any(
        decision.raw_delta_codes is not None
        and not math.isclose(decision.raw_delta_codes, round(decision.raw_delta_codes), abs_tol=1e-12)
        for _, _, decision in host
    )


def test_epoch_reference_loss_recovery_and_phase_step_parity(
    cx318_harness: Path,
) -> None:
    inputs = _stream([0] * 5)
    last = inputs[-1]
    inputs.append(
        Input(1, 7, last.counter, 7, 7 * TICKS_PER_SECOND, 0, 10_000_000, 0, 7.0, reference_qualified=False)
    )
    counter = (last.counter - 10_000_000) % (1 << 32)
    inputs.append(Input(1, 8, counter, 8, 8 * TICKS_PER_SECOND, 0, 10_000_000, 0, 8.0))
    counter = (counter - 10_000_005) % (1 << 32)
    inputs.append(Input(1, 9, counter, 9, 9 * TICKS_PER_SECOND, 0, 10_000_005, 0, 9.0, phase_step=True))
    counter = (counter - 10_000_000) % (1 << 32)
    inputs.append(Input(1, 11, counter, 11, 11 * TICKS_PER_SECOND, 0, 10_000_000, 0, 11.0))
    cpp = _run_cpp(cx318_harness, inputs)
    host = _run_host(inputs)
    _compare(cpp, host)
    assert cpp[6]["preview_state"] == "REFERENCE_LOST_PREVIEW"
    assert cpp[7]["preview_state"] == "RECOVER_PREVIEW"
    assert cpp[8]["preview_state"] == "PHASE_STEP_HOLD_PREVIEW"
    assert cpp[9]["phase_reason"] == "snapshot_or_reference_sequence_gap"


def test_dac_epoch_reseed_clears_unavailable_frequency_payload(
    cx318_harness: Path,
) -> None:
    inputs = _stream([0] * 600)
    last = inputs[-1]
    inputs.append(
        Input(
            last.session,
            last.sequence + 1,
            (last.counter - 10_000_000) % (1 << 32),
            last.reference_sequence + 1,
            last.reference_ticks + TICKS_PER_SECOND,
            0,
            10_000_000,
            1,
            last.timestamp_s + 1.0,
            actual_code=START_CODE,
        )
    )

    cpp = _run_cpp(cx318_harness, inputs)
    host = _run_host(inputs)
    _compare(cpp, host)
    assert _boolean(cpp[-1]["frequency_available"]) is False
    assert float(cpp[-1]["observed_frequency_error_hz"]) == 0.0


def test_engine_has_no_authority_or_io_dependency() -> None:
    header = HEADER.read_text(encoding="utf-8")
    source = ENGINE.read_text(encoding="utf-8")
    includes = [line for line in (header + source).splitlines() if line.startswith("#include")]
    assert includes == [
        "#include <stdint.h>",
        '#include "otis_selected_phase_frequency_preview_engine.h"',
        "#include <math.h>",
        "#include <stddef.h>",
        "#include <string.h>",
    ]
    for forbidden in (
        "otis_cx317_active",
        "otis_cx317_active_transaction",
        "otis_cx317_active_actuator",
        "otis_dac_ad5693r",
        "otis_serial_command",
        "otis_i2c_bus",
        "authorization_consumed",
        "actuation_authorized",
        "actionable",
    ):
        assert forbidden not in source
