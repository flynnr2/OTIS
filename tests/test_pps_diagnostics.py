from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware" / "arduino" / "otis_nano_rp2040_connect"
HARNESS = ROOT / "tests" / "cpp" / "pps_diagnostics_harness.cpp"
HEADER = FIRMWARE / "otis_pps_diagnostics.h"


def test_pps_diagnostics_state_machine(tmp_path: Path) -> None:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is not available")

    binary = tmp_path / "pps_diagnostics_harness"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-pedantic",
            "-I",
            str(FIRMWARE),
            str(HARNESS),
            "-o",
            str(binary),
        ],
        check=True,
    )
    subprocess.run([str(binary)], check=True)


def test_pps_diagnostics_core_has_no_service_plane_dependencies() -> None:
    source = HEADER.read_text(encoding="utf-8")
    for prohibited in (
        "Arduino.h",
        "Serial",
        "snprintf",
        "printf(",
        "malloc(",
        "calloc(",
        "realloc(",
        "operator new",
        "otis_emit_",
        "otis_transport_",
    ):
        assert prohibited not in source

    assert "otis_timer0_interval_ticks" in source
    assert "latest_physical_pps" in source
    assert "latest_snapshot_produced" in source
    assert "latest_snapshot_drained" in source
    assert "latest_measurement_reconstructed" in source
    assert "latest_telemetry_emitted" in source
    assert "latest_control_observed" in source
