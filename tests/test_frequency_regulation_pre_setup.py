from __future__ import annotations

import csv
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from host.otis_tools.contracts import CONTROL_PREVIEW_V1_FIELDS


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def test_pre_setup_selected_estimate_remains_safe_observe(tmp_path: Path) -> None:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    executable = tmp_path / "frequency_regulation_pre_setup"
    dead_strip = ["-Wl,-dead_strip"] if sys.platform == "darwin" else ["-Wl,--gc-sections"]
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
            str(ROOT / "tests/cpp/frequency_regulation_pre_setup_harness.cpp"),
            str(FIRMWARE / "otis_frequency_regulation_engine.cpp"),
            str(FIRMWARE / "otis_integer_count_tight_deadband.cpp"),
            str(FIRMWARE / "otis_monotonic_us_extension.cpp"),
            str(FIRMWARE / "otis_oscillator_snapshot_estimator.cpp"),
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
    assert len(rows) == 2
    controls = [
        dict(zip(CONTROL_PREVIEW_V1_FIELDS, row, strict=True)) for row in rows
    ]
    for control in controls:
        assert control["control_state"] == "SAFE_OBSERVE"
        assert (
            control["transition_reason_code"]
            == "static_dac_code_unavailable_no_control_authority"
        )
        assert control["model_applicability"] == "not_applicable"
        assert control["model_reason_codes"] == "static_dac_code_unavailable"
        assert control["current_dac_code"] == ""
        assert control["proposed_dac_code"] == ""
        assert control["preview_available"] == "false"
        assert control["preview_only"] == "true"
        assert control["actuation_authorized"] == "false"
        assert control["actionable"] == "false"
    assert controls[0]["state_transition"] == "true"
    assert controls[1]["previous_control_state"] == "SAFE_OBSERVE"
    assert controls[1]["state_transition"] == "false"
