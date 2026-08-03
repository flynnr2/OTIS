from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def test_active_transaction_cpp_harness(tmp_path: Path) -> None:
    compiler = shutil.which("g++") or shutil.which("clang++")
    if compiler is None:
        pytest.skip("C++ compiler unavailable")
    executable = tmp_path / "cx317_active_transaction_harness"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(FIRMWARE),
            str(ROOT / "tests/cpp/cx317_active_transaction_harness.cpp"),
            str(FIRMWARE / "otis_cx317_active_transaction.cpp"),
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run([str(executable)], check=True)


def test_active_transaction_source_has_no_restore_retry_or_heap_path() -> None:
    source = (FIRMWARE / "otis_cx317_active_transaction.cpp").read_text(
        encoding="utf-8"
    )
    header = (FIRMWARE / "otis_cx317_active_transaction.h").read_text(
        encoding="utf-8"
    )

    assert "new " not in source
    assert "malloc(" not in source
    assert "free(" not in source
    assert "automatic_restore" not in source
    assert "retry" not in source.lower()
    assert "ActionableRequest" in header
    assert "AcceptedRequest" in header
    assert "AppliedAck" in header
    assert "actionable = false" in source
