from __future__ import annotations

import csv
import io
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path

import pytest

from host.otis_tools.active_hybrid_policy import (
    ActiveHybridController,
    HybridObservation,
    load_policy,
)


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def _compiler() -> str:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    return compiler


@pytest.fixture(scope="session")
def active_hybrid_harness(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("active_hybrid") / "engine"
    subprocess.run(
        [
            _compiler(),
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(ROOT / "tests/cpp/active_hybrid_policy_engine_harness.cpp"),
            str(FIRMWARE / "otis_active_hybrid_policy_engine.cpp"),
            "-I",
            str(FIRMWARE),
            "-o",
            str(output),
        ],
        check=True,
        cwd=ROOT,
    )
    return output


def _observation(
    timestamp_s: int,
    *,
    code: int = 0xA83C,
    dac_epoch: int = 1,
    frequency_hz: float = 0.0,
    tight_state: str = "TIGHT_INSIDE",
    phase_cycles: int = -24,
    phase_sequence: int = 1,
    **overrides: object,
) -> HybridObservation:
    values: dict[str, object] = {
        "timestamp_s": timestamp_s,
        "capture_session": 1,
        "source_first_sequence": max(1, timestamp_s - 599),
        "source_last_sequence": max(1, timestamp_s),
        "dac_epoch": dac_epoch,
        "applied_code": code,
        "frequency_error_hz": frequency_hz,
        "accumulated_edge_error_counts": 0,
        "tight_state": tight_state,
        "phase_epoch": 1,
        "phase_observation_sequence": phase_sequence,
        "relative_phase_cycles": phase_cycles,
        "phase_dac_epoch": dac_epoch,
        "phase_applied_code": code,
    }
    values.update(overrides)
    return HybridObservation(**values)


def _decision(controller: ActiveHybridController, observation: HybridObservation) -> dict[str, object]:
    value = controller.decide(observation)
    return value.__dict__


def _simple_phase(phase_cycles: int) -> list[dict[str, object]]:
    controller = ActiveHybridController(load_policy())
    return [
        _decision(controller, _observation(1800)),
        _decision(controller, _observation(3600, phase_cycles=phase_cycles, phase_sequence=2)),
    ]


def _python_rows() -> dict[str, list[dict[str, object]]]:
    rows: dict[str, list[dict[str, object]]] = {
        "phase_positive": _simple_phase(-24),
        "phase_negative": _simple_phase(24),
        "phase_small_zero": _simple_phase(-1),
        "phase_cap": _simple_phase(-1000),
    }

    for name, phase_cycles in (
        ("phase_frequency_material", -24),
        ("phase_frequency_nonmaterial", -1),
    ):
        controller = ActiveHybridController(load_policy())
        rows[name] = [
            _decision(controller, _observation(1800)),
            _decision(
                controller,
                _observation(
                    3600,
                    frequency_hz=-0.001,
                    phase_cycles=phase_cycles,
                    phase_sequence=2,
                ),
            ),
        ]

    for name, error in (("frequency_negative", 0.01), ("frequency_positive", -0.01)):
        controller = ActiveHybridController(load_policy())
        rows[name] = [_decision(controller, _observation(1800, frequency_hz=error, tight_state="OUTSIDE"))]

    controller = ActiveHybridController(load_policy())
    progressive = [_decision(controller, _observation(1800))]
    first = controller.decide(_observation(3600, phase_cycles=-24, phase_sequence=2))
    progressive.append(first.__dict__)
    controller.note_application(
        first,
        applied_code=first.requested_code,
        dac_epoch=2,
        downstream_consumers_exact=True,
    )
    progressive.append(
        _decision(
            controller,
            _observation(
                4200,
                code=first.requested_code,
                dac_epoch=2,
                phase_cycles=-23,
                phase_sequence=3,
                outstanding_request=True,
            ),
        )
    )
    controller.note_response(
        classification="healthy_indeterminate_near_resolution",
        predicted_sign_observed=True,
        exact_replay=True,
        support_fresh=True,
        applied_epoch_exact=True,
    )
    progressive.append(
        _decision(controller, _observation(5400, code=first.requested_code, dac_epoch=2, phase_cycles=-22, phase_sequence=4))
    )
    progressive.append(
        _decision(controller, _observation(6000, code=first.requested_code, dac_epoch=2, phase_cycles=-21, phase_sequence=5))
    )
    rows["progressive"] = progressive

    controller = ActiveHybridController(load_policy())
    controller.last_application_s = 1000
    rows["cadence"] = [_decision(controller, _observation(2000, frequency_hz=0.01, tight_state="OUTSIDE"))]

    controller = ActiveHybridController(load_policy())
    controller.correction_count = 4
    rows["count"] = [_decision(controller, _observation(1800, frequency_hz=0.01, tight_state="OUTSIDE"))]

    controller = ActiveHybridController(load_policy())
    controller.cumulative_movement_codes = 80
    rows["cumulative"] = [_decision(controller, _observation(1800, frequency_hz=0.01, tight_state="OUTSIDE"))]

    controller = ActiveHybridController(load_policy())
    controller.applied_code = 0xAB00
    rows["range"] = [_decision(controller, _observation(1800, code=0xAB00, frequency_hz=-0.01, tight_state="OUTSIDE"))]

    controller = ActiveHybridController(load_policy())
    rows["direction_hold"] = [
        _decision(controller, _observation(1800)),
        _decision(controller, _observation(3600, frequency_hz=0.003, phase_cycles=-24, phase_sequence=2)),
    ]

    controller = ActiveHybridController(load_policy())
    controller.direction_history = [1, -1, 1]
    rows["alternation"] = [_decision(controller, _observation(1800, frequency_hz=0.01, tight_state="OUTSIDE"))]

    controller = ActiveHybridController(load_policy())
    rows["phase_degrade"] = [
        _decision(controller, _observation(1800)),
        _decision(controller, _observation(3600, phase_sequence=2, phase_continuous=False)),
    ]

    controller = ActiveHybridController(load_policy())
    rows["identity_fault"] = [
        _decision(controller, _observation(1800)),
        _decision(controller, _observation(3600, identity_exact=False)),
    ]

    controller = ActiveHybridController(load_policy())
    rows["epoch_fault"] = [_decision(controller, _observation(1800, dac_epoch=2))]
    return rows


def test_complete_cpp_host_policy_decision_parity(active_hybrid_harness: Path) -> None:
    completed = subprocess.run(
        [str(active_hybrid_harness)], check=True, text=True, capture_output=True
    )
    firmware = list(csv.DictReader(io.StringIO(completed.stdout)))
    host = _python_rows()
    positions = {name: 0 for name in host}
    bool_fields = (
        "phase_materially_influenced",
        "step_limited",
        "range_clamped",
        "cadence_limited",
        "count_limited",
        "cumulative_budget_limited",
    )
    int_fields = (
        "requested_delta_codes",
        "requested_code",
        "counterfactual_frequency_only_delta_codes",
        "correction_count_before",
        "cumulative_movement_before_codes",
    )
    float_fields = (
        "frequency_term_hz",
        "phase_term_hz",
        "combined_demand_hz",
        "raw_combined_delta_codes",
    )
    for actual in firmware:
        scenario = actual["scenario"]
        expected = host[scenario][positions[scenario]]
        positions[scenario] += 1
        for field in ("state_before", "state_after", "reason"):
            assert actual[field] == expected[field]
        for field in bool_fields:
            assert (actual[field] == "1") is expected[field]
        for field in int_fields:
            assert int(actual[field]) == expected[field]
        for field in float_fields:
            assert float(actual[field]) == pytest.approx(expected[field], abs=1e-15)
    assert all(positions[name] == len(rows) for name, rows in host.items())
