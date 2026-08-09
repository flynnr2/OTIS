from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def test_decimal_formatter_avoids_cross_core_libc_float_state(tmp_path: Path) -> None:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    executable = tmp_path / "decimal_format"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(ROOT / "tests/cpp/decimal_format_harness.cpp"),
            str(FIRMWARE / "otis_decimal_format.cpp"),
            "-I",
            str(FIRMWARE),
            "-o",
            str(executable),
        ],
        cwd=ROOT,
        check=True,
    )
    subprocess.run([str(executable)], cwd=ROOT, check=True)


def test_core1_evidence_paths_do_not_use_libc_float_formatting() -> None:
    for name in ("otis_cx317_preview_live.cpp", "otis_cx317_active_live.cpp"):
        source = (FIRMWARE / name).read_text(encoding="utf-8")
        assert "%.12f" not in source
        assert "%.9f" not in source
        assert "%.15g" not in source
        assert "otis_format_fixed(" in source
