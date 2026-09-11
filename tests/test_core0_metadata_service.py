"""Execute the actual sketch's Core 0 dispatch with native service doubles."""
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def test_metadata_dispatch_survives_every_transport_path(tmp_path):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler unavailable")
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text()
    # loop is the final sketch function. Compile its actual control flow;
    # neither a copied dispatcher nor a substring assertion proves this path.
    loop = sketch[sketch.index("void loop() {"):]
    (tmp_path / "core0_loop.inc").write_text(loop)
    executable = tmp_path / "core0_metadata_service"
    subprocess.run([
        compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
        "-I", str(FIRMWARE), "-I", str(tmp_path),
        str(ROOT / "tests/cpp/core0_metadata_service_harness.cpp"),
        str(FIRMWARE / "otis_transport_liveness.cpp"),
        "-o", str(executable),
    ], check=True)
    subprocess.run([str(executable)], check=True)
