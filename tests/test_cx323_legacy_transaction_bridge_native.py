from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def test_cx323_legacy_nonmaintenance_decision_completes_real_transaction(
    tmp_path: Path,
) -> None:
    compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
    if compiler is None:
        pytest.skip("C++ compiler unavailable")
    executable = tmp_path / "cx323_legacy_transaction_bridge_harness"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(FIRMWARE),
            str(ROOT / "tests/cpp/cx323_legacy_transaction_bridge_harness.cpp"),
            str(FIRMWARE / "otis_cx317_active_transaction.cpp"),
            str(FIRMWARE / "otis_cx323_phase_priority_maintenance.cpp"),
            str(FIRMWARE / "otis_cx323_wide.cpp"),
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run([str(executable)], check=True)
