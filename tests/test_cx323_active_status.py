from __future__ import annotations

import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"
MATRIX = ROOT / "firmware/arduino/firmware_matrix.json"
PROFILE_ID = "cx323_d9_d6_72h_adaptive_hybrid"


def test_exact_cx323_status_getter_preserves_application_and_checkpoint(
    tmp_path: Path,
) -> None:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")

    matrix = json.loads(MATRIX.read_text(encoding="utf-8"))
    profile = next(
        candidate
        for candidate in matrix["profiles"]
        if candidate["id"] == PROFILE_ID
    )
    defines = [
        f"-D{name}={value}" for name, value in profile["defines"].items()
    ]
    defines.append(f'-DOTIS_BUILD_PROFILE_ID="{PROFILE_ID}"')

    executable = tmp_path / "cx323_active_status"
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
            # The complete production translation unit contains one
            # target-only acceptance local that is unused in this exact host
            # preprocessing path.  It is unrelated to the linked getter.
            "-Wno-unused-variable",
            "-Wno-unused-function",
            "-ffunction-sections",
            "-fdata-sections",
            *defines,
            str(ROOT / "tests/cpp/cx323_active_status_harness.cpp"),
            str(FIRMWARE / "otis_cx317_active_transaction.cpp"),
            str(FIRMWARE / "otis_active_hybrid_policy_engine.cpp"),
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
