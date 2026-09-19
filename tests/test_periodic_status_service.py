"""Run production periodic rows and the Core 0 loop against bounded I/O seams."""
from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest
from test_output_queue_consumer_ownership import function_body

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def definition(source: str, name: str) -> str:
    match = re.search(rf"^[\w:*&<> ]+\b{name}\s*\([^;{{}}]*\)\s*\{{", source, re.MULTILINE)
    assert match, name
    return source[match.start():match.end() - 1] + "{" + function_body(source, name) + "}\n"


def test_periodic_status_preserves_rows_and_yields_real_loop(tmp_path: Path) -> None:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text()
    frequency = (FIRMWARE / "otis_frequency_regulation_live.cpp").read_text()
    view = re.search(r"struct OtisPeriodicStatusView \{.*?\n\};", sketch, re.DOTALL)
    assert view
    constants = "\n".join(
        re.search(rf"constexpr [^;]+\b{name}[^;]+;", frequency).group()
        for name in ("kEstimatorMethod", "kPolicyHash", "kPlantModelHash", "kActiveLiveUpdateCodes")
    )
    extracted = view.group() + "\n" + constants + "\n"
    extracted += definition(frequency, "otis_frequency_regulation_live_status_rows")
    extracted += "\n".join(definition(sketch, name) for name in (
        "emit_gnss_receiver_snapshot", "emit_periodic_status_rows",
        "abandon_periodic_status", "service_periodic_status_transport",
        "emit_periodic_status", "service_dual_core_serial_frame_transport", "loop",
    ))
    # Exercise the production cancellation boundary without substituting a
    # simulated CONFIG report for the separately verified full command path.
    before_query = function_body(sketch, "execute_serial_command").split(
        "if (command.kind == OtisSerialCommandKind::Help)", 1
    )[0]
    assert "abandon_periodic_status();" in before_query
    extracted += "void periodic_before_query(const OtisParsedSerialCommand &command) {" + before_query + "}\n"
    (tmp_path / "periodic_production.inc").write_text(extracted)
    (tmp_path / "Arduino.h").write_text(
        "#pragma once\n#include <stdint.h>\nclass Stream {};\nuint32_t millis();\n"
    )
    executable = tmp_path / "periodic_status"
    subprocess.run([
        compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
        "-I", str(tmp_path), "-I", str(FIRMWARE),
        str(ROOT / "tests/cpp/periodic_status_service_harness.cpp"),
        str(FIRMWARE / "otis_status_rows.cpp"),
        str(FIRMWARE / "otis_emit.cpp"),
        str(FIRMWARE / "otis_serial_frame_arbiter.cpp"),
        str(FIRMWARE / "otis_transport_liveness.cpp"),
        "-o", str(executable),
    ], check=True)
    subprocess.run([str(executable)], check=True, timeout=20)
