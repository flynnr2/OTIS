from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def test_chunked_serial_frames_have_one_owner_until_complete(tmp_path: Path) -> None:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    executable = tmp_path / "serial_frame_arbiter"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(FIRMWARE),
            str(ROOT / "tests/cpp/serial_frame_arbiter_harness.cpp"),
            str(FIRMWARE / "otis_serial_frame_arbiter.cpp"),
            "-o",
            str(executable),
        ],
        check=True,
    )
    subprocess.run([str(executable)], check=True)


def test_dual_core_loop_dispatches_exactly_one_chunked_writer() -> None:
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    dispatch = sketch[
        sketch.index("bool service_dual_core_serial_frame_transport(void)") :
        sketch.index("#endif", sketch.index("bool service_dual_core_serial_frame_transport(void)"))
    ]
    assert "switch (owner)" in dispatch
    assert dispatch.count("service_dual_core_evidence_transport();") == 1
    assert dispatch.count("otis_observe_only_discipline_live_service_transport();") == 1
    assert dispatch.count("otis_cx317_preview_live_service_transport();") == 1
    assert dispatch.count("otis_phase_preview_transport_service();") == 1

    loop = sketch[sketch.index("void loop()") :]
    dual_core = loop[
        loop.index("#if OTIS_ENABLE_DUAL_CORE_PARTITION") :
        loop.index("// Capture service always runs first.")
    ]
    guard_end = dual_core.index("service_dual_core_outputs();")
    guard = dual_core[:guard_end]
    assert "frame_active = service_dual_core_serial_frame_transport();" in guard
    assert "if (frame_active)" in guard
    assert guard.index("otis_gnss_receiver_service(now_ms);") < guard.index(
        "frame_active = service_dual_core_serial_frame_transport();"
    )
    for writer in (
        "service_dual_core_evidence_transport();",
        "otis_observe_only_discipline_live_service_transport();",
        "otis_cx317_preview_live_service_transport();",
        "otis_phase_preview_transport_service();",
    ):
        assert writer not in dual_core
