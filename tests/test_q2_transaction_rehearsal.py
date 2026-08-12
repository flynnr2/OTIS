from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def test_q2_transaction_case_engine(tmp_path: Path) -> None:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    executable = tmp_path / "q2_transaction_rehearsal"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(FIRMWARE),
            str(ROOT / "tests/cpp/q2_transaction_rehearsal_harness.cpp"),
            str(FIRMWARE / "otis_q2_transaction_rehearsal.cpp"),
            str(FIRMWARE / "otis_setup_authority.cpp"),
            str(FIRMWARE / "otis_cx317_active_transaction.cpp"),
            "-o",
            str(executable),
        ],
        check=True,
    )
    subprocess.run([str(executable)], check=True)


def test_q2_case_engine_cannot_reach_the_physical_dac_driver() -> None:
    source = (FIRMWARE / "otis_q2_transaction_rehearsal.cpp").read_text(
        encoding="utf-8"
    )
    assert "otis_dac_ad5693r" not in source
    assert "Wire." not in source


def test_q2_serial_surface_is_diagnostic_profile_gated() -> None:
    source = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    q2_handler = source[
        source.index("OtisSerialCommandKind::Q2Case") :
        source.index("OtisSerialCommandKind::ActiveQuery")
    ]
    guard = source[
        source.rfind("#if", 0, source.index("OtisSerialCommandKind::Q2Case")) :
        source.index("OtisSerialCommandKind::Q2Case")
    ]
    assert "OTIS_CX317_ACTIVE_CAMPAIGN_STAGE7_REHEARSAL" in guard
    assert "otis_q2_transaction_run_case" in q2_handler
    assert "otis_dac_ad5693r_set_raw" not in q2_handler
