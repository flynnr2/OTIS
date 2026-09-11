from __future__ import annotations

import csv
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

from host.otis_tools.contracts import CONTRACT_FIELDS
from host.otis_tools.firmware_host_contract import FRONTIERS

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def test_actual_metadata_and_delayed_selected_response_fit_without_consumer(tmp_path):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    executable = tmp_path / "metadata_selected_response"
    dead_strip = ["-Wl,-dead_strip"] if sys.platform == "darwin" else ["-Wl,--gc-sections"]
    sources = [
        "otis_regulation_transaction.cpp", "otis_active_hybrid_decision_types.cpp",
        "otis_active_hybrid_decision_format.cpp", "otis_adaptive_hybrid_regulation.cpp",
        "otis_adaptive_hybrid_maintenance_format.cpp", "otis_adaptive_hybrid_maintenance_record.cpp",
        "otis_adaptive_hybrid_wide.cpp", "otis_decimal_format.cpp", "otis_dual_core_partition.cpp",
        "otis_frequency_regulation_engine.cpp", "otis_integer_count_tight_deadband.cpp",
        "otis_monotonic_us_extension.cpp", "otis_oscillator_snapshot_estimator.cpp",
    ]
    subprocess.run([
        compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror", "-Wno-unused-variable",
        "-Wno-unused-function", "-Wno-missing-field-initializers", "-ffunction-sections", "-fdata-sections",
        '-DOTIS_BUILD_IMAGE_ID="adaptive_hybrid_regulation"',
        str(ROOT / "tests/cpp/metadata_selected_response_frontier_harness.cpp"),
        str(ROOT / "tests/cpp/frequency_operational_decision_bridge.cpp"),
        *(str(FIRMWARE / name) for name in sources), "-I", str(FIRMWARE), *dead_strip,
        "-o", str(executable),
    ], check=True)
    result = subprocess.run([str(executable)], check=True, capture_output=True, text=True)
    rows = list(csv.reader(result.stdout.splitlines()))
    assert len(rows) == FRONTIERS["adaptive_hybrid_evidence"]["metadata_response_frontier"]
    assert [row[0] for row in rows] == ["AHM", "APS", "EST", "EST", "TDB", "AHY", "AHM", "ACT", "AHM", "CTL"]
    maintenance = [dict(zip(CONTRACT_FIELDS["active_hybrid_maintenance_v2"], row, strict=True))
        for row in rows if row[0] == "AHM"]
    assert [row["event"] for row in maintenance] == ["gnss_metadata_hold_enter", "decision", "response_complete"]
    assert [int(row["event_timestamp_ticks"]) for row in maintenance] == [5000000100, 5000000200, 5000000200]
    decision = dict(zip(CONTRACT_FIELDS["active_hybrid_decisions_v3"], next(row for row in rows if row[0] == "AHY"), strict=True))
    assert decision["decision_timestamp_ticks"] == "5000000200"
    assert decision["decision_timestamp_s"] == "5000"
    for values in (row for row in rows if row[0] == "EST"):
        estimate = dict(zip(CONTRACT_FIELDS["estimates_v3"], values, strict=True))
        assert int(estimate["estimator_timestamp_ticks"]) == 4999999000 % (1 << 32)
        assert estimate["time_domain"] == "rp2040_monotonic_us32"
