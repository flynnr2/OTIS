from __future__ import annotations

import csv
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from host.otis_tools.contracts import CONTROL_PREVIEW_V1_FIELDS, ESTIMATE_V3_FIELDS
from host.otis_tools.firmware_host_contract import validate_record_wire_values

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def test_native_capture_fault_does_not_publish_orphan_control_preview(
    tmp_path: Path,
) -> None:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    executable = tmp_path / "frequency_regulation_capture_fault"
    dead_strip = (
        ["-Wl,-dead_strip"]
        if sys.platform == "darwin"
        else ["-Wl,--gc-sections"]
    )
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-Wno-missing-field-initializers",
            "-Wno-unused-variable",
            "-Wno-unused-function",
            "-ffunction-sections",
            "-fdata-sections",
            str(ROOT / "tests/cpp/frequency_regulation_capture_fault_harness.cpp"),
            str(FIRMWARE / "otis_frequency_regulation_engine.cpp"),
            str(FIRMWARE / "otis_integer_count_tight_deadband.cpp"),
            str(FIRMWARE / "otis_monotonic_us_extension.cpp"),
            str(FIRMWARE / "otis_oscillator_snapshot_estimator.cpp"),
            str(FIRMWARE / "otis_phase_preview_live.cpp"),
            str(FIRMWARE / "otis_selected_phase_frequency_preview_engine.cpp"),
            str(FIRMWARE / "otis_decimal_format.cpp"),
            "-I",
            str(FIRMWARE),
            *dead_strip,
            "-o",
            str(executable),
        ],
        cwd=ROOT,
        check=True,
    )
    completed = subprocess.run(
        [str(executable)], cwd=ROOT, check=True, capture_output=True, text=True
    )
    rows = list(csv.reader(completed.stdout.splitlines()))

    # The harness exercises startup, a source discontinuity, valid and unknown
    # actuator contexts, an explicit capture fault, and both recovery paths.
    # Only the four selected-estimator evaluations cross the host boundary.
    assert len(rows) == 8
    assert [row[0] for row in rows] == ["EST", "CTL"] * 4
    for estimate_row, control_row in zip(rows[::2], rows[1::2], strict=True):
        assert validate_record_wire_values("estimates_v3", estimate_row) == ()
        assert validate_record_wire_values("control_previews_v1", control_row) == ()
        estimate = dict(zip(ESTIMATE_V3_FIELDS, estimate_row, strict=True))
        control = dict(zip(CONTROL_PREVIEW_V1_FIELDS, control_row, strict=True))
        assert control["est_input_ref"] == estimate["estimate_id"]
        assert (
            control["decision_timestamp_ticks"]
            == estimate["estimator_timestamp_ticks"]
        )
        assert control["time_domain"] == estimate["time_domain"]
        assert control["decision_timestamp_ticks"] != "0"
        assert control["preview_only"] == "true"
        assert control["actuation_authorized"] == "false"
        assert control["actionable"] == "false"

    controls = [
        dict(zip(CONTROL_PREVIEW_V1_FIELDS, row, strict=True))
        for row in rows[1::2]
    ]
    assert [control["control_seq"] for control in controls] == [
        "0",
        "1",
        "2",
        "3",
    ]
    assert all(
        control["model_applicability"] == "not_applicable"
        for control in controls[:2]
    )
    assert all(control["current_dac_code"] == "" for control in controls[:2])
    assert all(
        control["model_applicability"] == "applicable" for control in controls[2:]
    )
    assert all(
        control["current_dac_code"] == str(0xA844) for control in controls[2:]
    )
