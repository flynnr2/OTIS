import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def test_observation_precommit_same_message_identity_and_diagnostic_isolation(tmp_path):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("native compiler unavailable")
    executable = tmp_path / "observation_latency"
    subprocess.run([
        compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
        "-I", str(FIRMWARE),
        str(ROOT / "tests/cpp/observation_queue_latency_harness.cpp"),
        str(FIRMWARE / "otis_dual_core_partition.cpp"),
        "-o", str(executable),
    ], check=True)
    subprocess.run([str(executable)], check=True)
