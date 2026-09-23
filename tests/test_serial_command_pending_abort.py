import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
FW = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def test_hold_bypasses_one_deferred_normal_command_while_status_frame_pending(tmp_path):
    compiler = shutil.which("c++")
    if not compiler:
        pytest.skip("host C++ compiler unavailable")
    source = (FW / "otis_nano_rp2040_connect.ino").read_text()
    start = source.index("void service_serial_commands(bool output_allowed = true) {")
    opening = source.index("{", start)
    depth = 0
    for position in range(opening, len(source)):
        if source[position] == "{":
            depth += 1
        elif source[position] == "}":
            depth -= 1
            if depth == 0:
                break
    else:
        pytest.fail("command service function unterminated")
    (tmp_path / "serial_command_service.inc").write_text(source[start : position + 1])
    binary = tmp_path / "pending_abort"
    subprocess.run(
        [compiler, "-std=c++17", "-Wall", "-Wextra", "-Werror",
         "-fsanitize=address,undefined", "-fno-omit-frame-pointer",
         f"-I{FW}", f"-I{tmp_path}",
         str(ROOT / "tests/cpp/serial_command_pending_abort_harness.cpp"),
         str(FW / "otis_serial_command.cpp"), "-o", str(binary)],
        check=True,
    )
    subprocess.run([str(binary)], check=True, timeout=15)
