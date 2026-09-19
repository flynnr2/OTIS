"""Compile the actual FIFO IRQ backend through a reusable native hardware port."""

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "firmware/arduino/otis_nano_rp2040_connect"
STUBS = ROOT / "tests/cpp/pps_snapshot_backend_stubs"
HARNESS = ROOT / "tests/cpp/pps_snapshot_backend_irq_harness.cpp"


def test_fifo_irq_backend_lifecycle_faults_and_rearm(tmp_path: Path) -> None:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("backend verification requires a native C++ compiler")
    binary = tmp_path / "pps_snapshot_backend_irq"
    subprocess.run(
        [
            compiler,
            "-std=gnu++20",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-DARDUINO_ARCH_RP2040=1",
            "-DPICO_NO_HARDWARE=0",
            "-DPICO_PIO_VERSION=0",
            f"-I{STUBS}",
            f"-I{BACKEND}",
            str(HARNESS),
            "-o",
            str(binary),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run([str(binary)], check=True, capture_output=True, text=True)
