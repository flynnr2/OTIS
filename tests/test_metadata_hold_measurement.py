from __future__ import annotations

from pathlib import Path
import re
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"
HARNESS = ROOT / "tests/cpp/metadata_hold_measurement_harness.cpp"


def _compiler() -> str:
    compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    return compiler


def test_metadata_hold_preserves_d14_d8_measurement_history_natively(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "metadata_hold_measurement"
    subprocess.run(
        [
            _compiler(),
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(HARNESS),
            str(FIRMWARE / "otis_selected_phase_frequency_preview_engine.cpp"),
            str(FIRMWARE / "otis_oscillator_snapshot_estimator.cpp"),
            "-I",
            str(FIRMWARE),
            "-o",
            str(executable),
        ],
        cwd=ROOT,
        check=True,
    )
    subprocess.run([str(executable)], cwd=ROOT, check=True)


def test_boundary_routes_same_accepted_selection_to_both_previews() -> None:
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text()
    start = sketch.index("void emit_pps_count_boundary(")
    end = sketch.index("\nvoid ", start)
    boundary = sketch[start:end]
    assert "receiver_metadata_qualified" not in boundary
    assert re.search(r"otis_phase_preview_live_on_reference_selection\(\s*&selection, closing_extended_ticks", boundary)
    assert re.search(r"otis_frequency_regulation_live_on_reference_selection\(\s*&selection, closing_extended_ticks", boundary)
    phase = boundary.index("otis_phase_preview_live_on_reference_selection(")
    health = boundary.index("update_adaptive_hybrid_regulation_health();")
    frequency = boundary.index("otis_frequency_regulation_live_on_reference_selection(")
    assert phase < health < frequency
    health_start = re.search(r"void update_adaptive_hybrid_regulation_health\([^)]*\)\s*\{", sketch).start()
    health_end = sketch.index("\nvoid ", health_start)
    health_body = sketch[health_start:health_end]
    assert "health.gnss_metadata_valid = dual_core_receiver_qualified_for_control();" in health_body
    assert "accepted.tracking && accepted.anchor_current" in health_body
    assert "tcxo.last_observation_valid" not in health_body
