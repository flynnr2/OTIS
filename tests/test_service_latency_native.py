"""Deterministic model checks; not a physical latency qualification."""
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def test_bounded_service_latency_model(tmp_path: Path) -> None:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler unavailable")
    executable = tmp_path / "service_latency"
    subprocess.run(
        [compiler, "-std=c++11", "-Wall", "-Wextra", "-Werror",
         "-fsanitize=undefined,address", "-I", str(FIRMWARE),
         str(ROOT / "tests/cpp/service_latency_harness.cpp"),
         str(FIRMWARE / "otis_service_latency.cpp"), "-o", str(executable)],
        check=True,
    )
    result = subprocess.run([str(executable)], check=True, capture_output=True, text=True)
    assert "sample_bytes=24 stats_bytes=" in result.stdout
