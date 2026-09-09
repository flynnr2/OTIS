from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def test_adaptive_hybrid_status_getter_preserves_application_and_checkpoint(
    tmp_path: Path,
) -> None:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    executable = tmp_path / "adaptive_hybrid_active_status"
    dead_strip = ["-Wl,-dead_strip"] if sys.platform == "darwin" else ["-Wl,--gc-sections"]
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-Wno-unused-variable",
            "-Wno-unused-function",
            "-ffunction-sections",
            "-fdata-sections",
            str(ROOT / "tests/cpp/adaptive_hybrid_active_status_harness.cpp"),
            str(FIRMWARE / "otis_regulation_transaction.cpp"),
            str(FIRMWARE / "otis_active_hybrid_policy_engine.cpp"),
            str(FIRMWARE / "otis_active_hybrid_decision_format.cpp"),
            str(FIRMWARE / "otis_adaptive_hybrid_regulation.cpp"),
            str(FIRMWARE / "otis_adaptive_hybrid_maintenance_format.cpp"),
            str(FIRMWARE / "otis_adaptive_hybrid_maintenance_record.cpp"),
            str(FIRMWARE / "otis_adaptive_hybrid_wide.cpp"),
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
    subprocess.run([str(executable)], cwd=ROOT, check=True)
