import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def test_startup_transition_status_follows_canonical_consumption(tmp_path: Path):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    stubs = tmp_path / "stubs"
    (stubs / "hardware/structs").mkdir(parents=True)
    (stubs / "Arduino.h").write_text(
        '#pragma once\n#include <stdint.h>\nclass Stream;\n'
        '#define D10 5\n#define D14 26\n#define D8 20\n#define D9 21\n'
        '#define D6 18\n#define PIN_SERIAL1_RX 1\n#define PIN_SERIAL1_TX 0\n'
        'uint32_t millis();\nuint32_t micros();\nuint64_t time_us_64();\n'
    )
    (stubs / "hardware/structs/timer.h").write_text(
        '#pragma once\n#include <stdint.h>\n'
        'struct mock_timer { uint32_t timerawl; };\nextern mock_timer *timer_hw;\n'
    )
    (stubs / "hardware/pio_instructions.h").write_text('#pragma once\n')
    source = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text()
    boundary = "void emit_pps_count_boundary(" + source.split(
        "void emit_pps_count_boundary(", 1
    )[1].split("\nvoid ", 1)[0]
    (stubs / "count_boundary_bridge.inc").write_text(boundary)
    executable = tmp_path / "count_startup"
    subprocess.run([
        compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
        "-Wno-unused-parameter", "-Wno-unused-const-variable",
        "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
        "-DARDUINO_ARCH_RP2040", "-I", str(stubs),
        "-I", str(ROOT / "tests/cpp/pps_snapshot_backend_stubs"),
        "-I", str(FIRMWARE),
        str(ROOT / "tests/cpp/count_observation_startup_harness.cpp"),
        str(FIRMWARE / "otis_count_observation.cpp"), "-o", str(executable),
    ], check=True, cwd=ROOT)
    result = subprocess.run([str(executable)], check=True, capture_output=True, text=True)
    assert "sequence=2 transition_rows=0" in result.stdout


def test_integrated_boundary_keeps_explicit_phase_status_health_order():
    source = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text()
    boundary = source.split("void emit_pps_count_boundary(", 1)[1].split("\nvoid ", 1)[0]
    stages = [
        "otis_count_observation_on_pps_boundary(",
        "otis_reference_acceptance_format_span(",
        "otis_phase_preview_live_on_reference_selection(",
        "otis_count_observation_emit_pending_boundary_status();",
        "update_adaptive_hybrid_regulation_health();",
        "otis_frequency_regulation_live_on_reference_selection(",
    ]
    assert [boundary.index(stage) for stage in stages] == sorted(
        boundary.index(stage) for stage in stages
    )
    phase_begin = source.split("void setup1()", 1)[1].split("void loop1()", 1)[0]
    assert phase_begin.index("boot_phase_preview_init();") < phase_begin.rindex(
        "&dual_core_timing_boot_complete, true"
    )
