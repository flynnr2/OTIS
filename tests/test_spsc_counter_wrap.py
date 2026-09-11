from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_non_power_of_two_evidence_queue_retains_order_across_counter_wrap(tmp_path):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("native compiler unavailable")
    executable = tmp_path / "queue_wrap"
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
                    str(ROOT / "tests/cpp/spsc_counter_wrap_harness.cpp"),
                    "-I", str(ROOT / "firmware/arduino/otis_nano_rp2040_connect"),
                    "-o", str(executable)], check=True)
    subprocess.run([str(executable)], check=True)
