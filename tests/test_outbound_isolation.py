from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def test_outbound_saturation_does_not_fault_internal_service(tmp_path: Path) -> None:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    executable = tmp_path / "outbound_isolation"
    subprocess.run(
        [
            compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
            "-I", str(FIRMWARE),
            str(ROOT / "tests/cpp/outbound_isolation_harness.cpp"),
            str(FIRMWARE / "otis_dual_core_partition.cpp"),
            "-o", str(executable),
        ],
        check=True,
    )
    subprocess.run([str(executable)], check=True)
