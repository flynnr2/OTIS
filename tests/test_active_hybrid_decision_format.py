from __future__ import annotations

import csv
import io
from pathlib import Path
import shutil
import subprocess

import pytest

from host.otis_tools.contracts import ACTIVE_HYBRID_DECISION_V1_FIELDS


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def test_firmware_active_hybrid_formatter_emits_the_exact_wire_contract(
    tmp_path: Path,
) -> None:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    executable = tmp_path / "active_hybrid_decision_format"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(ROOT / "tests/cpp/active_hybrid_decision_format_harness.cpp"),
            str(FIRMWARE / "otis_active_hybrid_decision_format.cpp"),
            str(FIRMWARE / "otis_active_hybrid_policy_engine.cpp"),
            str(FIRMWARE / "otis_decimal_format.cpp"),
            "-I",
            str(FIRMWARE),
            "-o",
            str(executable),
        ],
        check=True,
        cwd=ROOT,
    )
    completed = subprocess.run(
        [str(executable)], check=True, text=True, capture_output=True
    )
    values = next(csv.reader(io.StringIO(completed.stdout)))
    assert len(values) == len(ACTIVE_HYBRID_DECISION_V1_FIELDS) == 56
    row = dict(zip(ACTIVE_HYBRID_DECISION_V1_FIELDS, values, strict=True))
    assert row["record_type"] == "AHY"
    assert row["reason"] == "minimum_applied_cadence_hold"
    assert row["response_policy_sha256"] == "response_policy_sha256"
    assert row["actionable"] == "false"
