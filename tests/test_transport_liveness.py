from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def test_transport_liveness_zero_intermittent_restore_and_wrap(
    tmp_path: Path,
) -> None:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    executable = tmp_path / "transport_liveness"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(FIRMWARE),
            str(ROOT / "tests/cpp/transport_liveness_harness.cpp"),
            str(FIRMWARE / "otis_transport_liveness.cpp"),
            str(FIRMWARE / "otis_serial_command.cpp"),
            str(FIRMWARE / "otis_dual_core_partition.cpp"),
            "-o",
            str(executable),
        ],
        check=True,
    )
    subprocess.run([str(executable)], check=True)


def test_obstructed_frame_still_services_rx_and_fault_drains() -> None:
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    loop = sketch[sketch.index("void loop()") :]
    dual = loop
    first_observe = dual.index("bool transport_live = otis_transport_liveness_observe(")
    service = dual.index("frame_active = service_dual_core_serial_frame_transport();")
    second_observe = dual.index(
        "transport_live = otis_transport_liveness_observe(", service + 1
    )
    assert first_observe < service < second_observe
    assert "if (transport_live)" in dual[first_observe:service]
    assert "OtisTransportLivenessState::FrameObstructed" in dual[:first_observe]
    assert "service_serial_commands(false);" in dual
    assert "OtisPartitionFault::TransportObstructed" in dual
    assert "discard_dual_core_outputs_after_transport_fault();" in dual
    assert "OtisRunControlKind::Abort" in dual
    assert "OTIS_MAXIMUM_SUPPORTED_TX_OBSTRUCTION_MS = 2000u" in (
        FIRMWARE / "otis_transport_liveness.h"
    ).read_text(encoding="utf-8")


def test_absent_carrier_abandons_only_outbound_framing_before_liveness() -> None:
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    loop = sketch[sketch.index("void loop()") :]
    dual = loop
    carrier = dual.index("if (!otis_transport_ready())")
    liveness = dual.index("bool transport_live = otis_transport_liveness_observe(")
    assert carrier < liveness
    absent = dual[carrier:liveness]
    assert "otis_transport_liveness_note_carrier_absent(" in absent
    assert "abandon_dual_core_serial_frames_on_carrier_loss();" in absent
    assert "service_serial_commands(false);" in absent
    assert "return;" in absent

    abandon = sketch[
        sketch.index("void abandon_dual_core_serial_frames_on_carrier_loss(void)") :
        sketch.index("OtisRegulationStaticCodeState regulation_static_code_state(")
    ]
    assert "dual_core_evidence_transport_active = false;" in abandon
    assert "otis_phase_preview_transport_abandon_active_frame()" in abandon
    assert "otis_serial_frame_arbiter_reset(" in abandon
    assert "config_query_provenance_emitted = false;" in abandon


def test_core1_capture_drain_has_one_ring_budget() -> None:
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    body = sketch[
        sketch.index("void drain_reference_snapshots(void)") :
        sketch.index("void emit_build_provenance_status(")
    ]
    assert "uint32_t budget = 128u;" in body
    assert "while (budget-- > 0u && otis_pps_snapshot_backend_pop(&snapshot))" in body
