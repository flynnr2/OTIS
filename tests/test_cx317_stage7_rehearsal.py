from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def test_deterministic_stage7_rehearsal_sequence_harness(
    tmp_path: Path,
) -> None:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    executable = tmp_path / "cx317_stage7_rehearsal_sequence"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-DOTIS_CX317_ACTIVE_CAMPAIGN=OTIS_CX317_ACTIVE_CAMPAIGN_STAGE7_REHEARSAL",
            "-DOTIS_CX317_SELECTED_SPAN_INTERVALS_CONFIG=120u",
            "-DOTIS_CX317_STARTUP_WARMUP_S=60u",
            "-DOTIS_CX317_SETTLING_EXCLUSION_S=60u",
            "-DOTIS_CX317_FULL_HISTORY_RESET_S=180u",
            "-DOTIS_CX317_RECOVERY_FRESH_SUPPORT_S=120u",
            "-DOTIS_CX317_DECISION_CADENCE_S=240u",
            "-DOTIS_CX317_MINIMUM_APPLIED_CADENCE_S=240u",
            str(
                ROOT
                / "tests/cpp/cx317_stage7_rehearsal_sequence_harness.cpp"
            ),
            str(FIRMWARE / "otis_cx317_active_transaction.cpp"),
            str(FIRMWARE / "otis_cx317_i_only_engine.cpp"),
            "-I",
            str(FIRMWARE),
            "-o",
            str(executable),
        ],
        cwd=ROOT,
        check=True,
    )
    subprocess.run([str(executable)], cwd=ROOT, check=True)
