from __future__ import annotations

import csv
import io
import shutil
import subprocess
from pathlib import Path

import pytest

from host.otis_tools.contracts import (
    CONTROL_PREVIEW_V1_FIELDS,
    CsvValidationContext,
    ESTIMATE_V2_FIELDS,
    validate_csv,
)
from host.otis_tools.frequency_control_replay import (
    IOnlyPreviewEngine,
    Observation,
    load_current_replay_policy,
)
from host.otis_tools.pps_cumulative_span_estimator import (
    IntervalEvidence,
    estimate_spans,
    load_config,
)


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def _compiler() -> str:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    return compiler


@pytest.fixture(scope="session")
def cx317_engine_harness(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("cx317_engine") / "engine"
    subprocess.run(
        [
            _compiler(), "-std=c++17", "-Wall", "-Wextra", "-Werror",
            str(ROOT / "tests/cpp/cx317_i_only_engine_harness.cpp"),
            str(FIRMWARE / "otis_cx317_i_only_engine.cpp"),
            "-I", str(FIRMWARE), "-o", str(output),
        ],
        check=True,
        cwd=ROOT,
    )
    return output


@pytest.fixture(scope="session")
def cx317_live_harness(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("cx317_live") / "live"
    subprocess.run(
        [
            _compiler(), "-std=c++17", "-Wall", "-Wextra", "-Werror",
            "-DOTIS_ENABLE_CX317_I_ONLY_PREVIEW=1",
            "-DOTIS_PPS_BOUNDARY_BACKEND_QUALIFIED=1",
            "-DOTIS_ENABLE_ENV_SENSORS=1",
            "-DOTIS_ENABLE_DAC_AD5693R=1",
            str(ROOT / "tests/cpp/cx317_preview_live_harness.cpp"),
            str(FIRMWARE / "otis_cx317_preview_live.cpp"),
                str(FIRMWARE / "otis_cx317_i_only_engine.cpp"),
                str(FIRMWARE / "otis_cx317_snapshot_estimator.cpp"),
                str(FIRMWARE / "otis_decimal_format.cpp"),
                "-I", str(FIRMWARE), "-o", str(output),
        ],
        check=True,
        cwd=ROOT,
    )
    return output


@pytest.fixture(scope="session")
def cx317_estimator_harness(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("cx317_estimator") / "estimator"
    subprocess.run(
        [
            _compiler(), "-std=c++17", "-Wall", "-Wextra", "-Werror",
            str(ROOT / "tests/cpp/cx317_snapshot_estimator_harness.cpp"),
            str(FIRMWARE / "otis_cx317_snapshot_estimator.cpp"),
            "-I", str(FIRMWARE), "-o", str(output),
        ],
        check=True,
        cwd=ROOT,
    )
    return output


def _python_rows() -> dict[str, list[dict[str, object]]]:
    policy = load_current_replay_policy()
    base = lambda timestamp: Observation(timestamp, 0.02, policy.fail_static_code, 29.0)
    output: dict[str, list[dict[str, object]]] = {}

    nominal = IOnlyPreviewEngine(policy)
    output["nominal"] = [nominal.process(base(t)) for t in (0, 1800, 2400)]

    settling = IOnlyPreviewEngine(policy)
    rows = [settling.process(base(t)) for t in (0, 1800, 2400)]
    rows.append(settling.process(Observation(3000, 0.02, policy.fail_static_code, 29.0, dac_epoch=True)))
    rows.extend(settling.process(base(t)) for t in (4499, 4500))
    output["settling"] = rows

    fault = IOnlyPreviewEngine(policy)
    rows = [fault.process(base(t)) for t in (0, 1800, 2400)]
    rows.append(fault.process(Observation(3000, 0.02, policy.fail_static_code, 29.0, reference_valid=False)))
    rows.append(fault.process(Observation(3600, 0.02, policy.fail_static_code, 29.0, recovery_requested=True)))
    rows.append(fault.process(base(4200)))
    output["fault"] = rows

    model = IOnlyPreviewEngine(policy)
    rows = [model.process(base(t)) for t in (0, 1800, 2400)]
    rows.append(model.process(Observation(
        3000, 0.02, policy.fail_static_code, None, model_applicable=False
    )))
    rows.append(model.process(base(3600)))
    rows.append(model.process(base(4200)))
    output["model_hold"] = rows

    abort = IOnlyPreviewEngine(policy)
    output["abort"] = [
        abort.process(Observation(0, 0.02, policy.fail_static_code, 29.0, operator_abort=True)),
        abort.process(base(3000)),
    ]
    return output


def test_cpp_controller_matches_host_replay(cx317_engine_harness: Path) -> None:
    completed = subprocess.run([str(cx317_engine_harness)], check=True, text=True, capture_output=True)
    cpp_rows = list(csv.DictReader(io.StringIO(completed.stdout)))
    expected = _python_rows()
    positions = {key: 0 for key in expected}
    state_names = {
        0: "WARMUP_INHIBIT", 1: "QUALIFYING", 2: "SETTLING_INHIBIT",
        3: "TRACKING", 4: "OUT_OF_MODEL_HOLD", 5: "FAULT", 6: "ABORTED",
    }
    for row in cpp_rows:
        scenario = row["scenario"]
        host = expected[scenario][positions[scenario]]
        positions[scenario] += 1
        assert state_names[int(row["state"])] == host["state"]
        assert row["reason"] == host["reason"]
        assert (row["preview_available"] == "1") is host["preview_available"]
        assert int(row["limited_delta_codes"]) == (host["limited_delta_codes"] or 0)
        assert int(row["proposed_code"]) == (host["proposed_code"] or 0)
        assert float(row["integrator_codes"]) == pytest.approx(host["integrator_codes"])
        assert row["actionable"] == "0"
        if host["preview_available"]:
            assert float(row["raw_delta_codes"]) == pytest.approx(host["raw_delta_codes"])


def test_current_firmware_preserves_deployed_controller_wire_identity() -> None:
    preview = (FIRMWARE / "otis_cx317_preview_live.cpp").read_text(
        encoding="utf-8"
    )
    engine = (FIRMWARE / "otis_cx317_i_only_engine.cpp").read_text(
        encoding="utf-8"
    )

    assert "CX317_POST_CAMPAIGN_FREQUENCY_CONTROL_POLICY_V1" in preview
    assert (
        "bd1c8c2fef6239740733316cdfc4aab34ffe14f65e6ece5f76b965d21c42cc0f"
        in preview
    )
    assert "0.00017072602587382669" in preview
    assert "kDecisionCadenceS = 1800u" in engine
    assert "kActiveLiveUpdateCodes = 0" in engine


def test_cpp_estimator_matches_host_cumulative_snapshot_method(
    cx317_estimator_harness: Path,
) -> None:
    completed = subprocess.run(
        [str(cx317_estimator_harness)], check=True, text=True, capture_output=True
    )
    firmware_rows = list(csv.DictReader(io.StringIO(completed.stdout)))
    intervals = []
    for sequence in range(1, 1262):
        invalid = sequence == 661
        intervals.append(
            IntervalEvidence(
                session_id="1",
                opening_snapshot_sequence=sequence - 1,
                closing_snapshot_sequence=sequence,
                interval_counted_edges=10_000_000 + (1 if sequence % 17 == 0 else 0),
                opening_reference_event_sequence=sequence - 1,
                closing_reference_event_sequence=sequence,
                opening_reference_timestamp_ticks=(sequence - 1) * 16_000_000,
                closing_reference_timestamp_ticks=sequence * 16_000_000,
                cnt_sequence=sequence,
                valid=not invalid,
                reasons=() if not invalid else ("synthetic_gap",),
                control_epoch="static_a950",
            )
        )
    host = [
        row
        for row in estimate_spans(intervals, load_config())
        if (row.mode == "overlapping" and row.span_seconds == 60)
        or (row.mode == "non_overlapping" and row.span_seconds == 600)
    ]
    host.sort(key=lambda row: (row.last_snapshot_sequence, row.span_seconds))
    firmware_rows.sort(
        key=lambda row: (int(row["last_sequence"]), 60 if row["kind"] == "diagnostic" else 600)
    )
    assert len(firmware_rows) == len(host)
    for actual, expected in zip(firmware_rows, host, strict=True):
        assert actual["kind"] == ("diagnostic" if expected.span_seconds == 60 else "selected")
        assert int(actual["first_sequence"]) == expected.first_snapshot_sequence
        assert int(actual["last_sequence"]) == expected.last_snapshot_sequence
        assert float(actual["frequency_hz"]) == pytest.approx(expected.authoritative_frequency_hz)
        if expected.span_seconds == 600:
            assert int(actual["selected_accumulated_edge_error_counts"]) == (
                expected.total_contiguous_counted_edges - 600 * 10_000_000
            )


def test_live_wire_records_are_well_shaped_and_non_actionable(
    cx317_live_harness: Path,
    tmp_path: Path,
) -> None:
    completed = subprocess.run([str(cx317_live_harness)], check=True, text=True, capture_output=True)
    lines = completed.stdout.splitlines()
    estimate_header = lines[0].split(",")
    control_header = lines[1].split(",")
    assert estimate_header == ESTIMATE_V2_FIELDS
    assert control_header == CONTROL_PREVIEW_V1_FIELDS
    estimates = list(csv.DictReader([lines[0], *[line for line in lines[2:] if line.startswith("EST,")]]))
    controls = list(csv.DictReader([lines[1], *[line for line in lines[2:] if line.startswith("CTL,")]]))
    assert any("diagnostic60" in row["estimate_id"] for row in estimates)
    selected = [row for row in estimates if "selected600" in row["estimate_id"]]
    assert len(selected) == 1
    assert float(selected[0]["frequency_estimate_hz"]) == pytest.approx(10_000_000.0)
    assert controls
    assert all(row["preview_only"] == "true" for row in controls)
    assert all(row["actuation_authorized"] == "false" for row in controls)
    assert all(row["actionable"] == "false" for row in controls)
    for name, header, rows, contract in (
        ("estimates.csv", lines[0], [line for line in lines[2:] if line.startswith("EST,")], "estimates_v2"),
        ("control.csv", lines[1], [line for line in lines[2:] if line.startswith("CTL,")], "control_previews_v1"),
    ):
        path = tmp_path / name
        path.write_text("\n".join([header, *rows]) + "\n", encoding="utf-8")
        result = validate_csv(
            path,
            CsvValidationContext(
                contract=contract,
                known_channels=frozenset(),
                known_domains=frozenset({"rp2040_timer0"}),
            ),
        )
        assert result.errors == ()


def test_live_preview_controlled_fault_requires_explicit_fresh_recovery(
    cx317_live_harness: Path,
) -> None:
    completed = subprocess.run(
        [str(cx317_live_harness), "recovery"],
        check=True,
        text=True,
        capture_output=True,
    )
    lines = completed.stdout.splitlines()
    controls = list(csv.DictReader([
        lines[1], *[line for line in lines[2:] if line.startswith("CTL,")]
    ]))

    assert completed.stderr.strip() == "recovery_fixture_pass"
    assert any(row["control_state"] == "FAULT" for row in controls)
    assert any(
        row["decision_reason_code"] == "explicit_recovery_fresh_support"
        for row in controls
    )
    assert controls[-1]["decision_reason_code"] == "inside_evidence_deadband"
    assert controls[-1]["preview_available"] == "true"
    assert all(row["actuation_authorized"] == "false" for row in controls)
    assert all(row["actionable"] == "false" for row in controls)


def test_preview_sources_have_no_actuator_dependency_or_actionable_path() -> None:
    sources = "\n".join(
        (FIRMWARE / name).read_text(encoding="utf-8")
        for name in (
            "otis_cx317_i_only_engine.h", "otis_cx317_i_only_engine.cpp",
            "otis_cx317_snapshot_estimator.h", "otis_cx317_snapshot_estimator.cpp",
            "otis_cx317_preview_live.h", "otis_cx317_preview_live.cpp",
        )
    ).lower()
    for forbidden in ("otis_dac_ad5693r", "set_raw", "wire.h", "actuator_callback"):
        assert forbidden not in sources
    assert "kactiveliveupdatecodes = 0" in sources
    assert "decision->actuation_enabled = false" in sources
    assert "decision->actuation_authorized = false" in sources
    assert "decision->actionable = false" in sources


def test_current_profile_keeps_dac_manual_only() -> None:
    import json

    matrix = json.loads((ROOT / "firmware/arduino/firmware_matrix.json").read_text())
    profile = next(item for item in matrix["profiles"] if item["id"] == "cx319_tight_lower")
    defines = profile["defines"]
    assert defines["OTIS_ENABLE_CX317_I_ONLY_PREVIEW"] == "1"
    assert defines["OTIS_ENABLE_DUAL_CORE_PARTITION"] == "1"
    assert defines["OTIS_ENABLE_GNSS_RECEIVER"] == "1"
    assert defines["OTIS_GNSS_UART_TX_ENABLED"] == "0"
    assert defines["OTIS_ENABLE_OBSERVE_ONLY_DISCIPLINE_PREVIEW"] == "0"
    assert defines["OTIS_ENABLE_DAC_AD5693R"] == "1"
    assert defines["OTIS_ENABLE_H1_DAC_SWEEP"] == "0"
    assert defines["OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED"] == "1"


def test_sketch_passes_backend_validity_not_zero_wire_flags_to_preview() -> None:
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    start = sketch.index("void emit_pps_count_boundary(")
    end = sketch.index("void drain_pps_count_boundary_ring(", start)
    integration = sketch[start:end]

    assert "window_completed && runtime_state.tcxo.last_observation_valid" in integration
    assert "last_window_flags == OTIS_FLAG_NONE" not in integration
    assert "OTIS_FLAG_TIMESTAMP_RECONSTRUCTED" in integration
