from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def test_dual_core_partition_native_isolation_harness(tmp_path: Path) -> None:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    executable = tmp_path / "dual_core_partition"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(ROOT / "tests/cpp/dual_core_partition_harness.cpp"),
            str(FIRMWARE / "otis_dual_core_partition.cpp"),
            "-I",
            str(FIRMWARE),
            "-o",
            str(executable),
        ],
        cwd=ROOT,
        check=True,
    )
    subprocess.run([str(executable)], cwd=ROOT, check=True)


def test_cross_core_messages_are_pointer_free_fixed_values() -> None:
    contract = (FIRMWARE / "otis_dual_core_contract.h").read_text(
        encoding="utf-8"
    )
    queue = (FIRMWARE / "otis_spsc_queue.h").read_text(encoding="utf-8")

    assert "const char *" not in contract.split(
        "struct OtisActuatorTransactionGuard", 1
    )[0]
    assert "std::is_trivially_copyable<Message>" in queue
    assert "slots_[Capacity]" in queue
    assert "new " not in queue
    assert "malloc" not in queue
    assert "try_push(const Message &message)" in queue
    assert "try_pop(Message *message)" in queue


def test_queue_classes_match_stage6_loss_contract() -> None:
    header = (FIRMWARE / "otis_dual_core_partition.h").read_text(
        encoding="utf-8"
    )
    source = (FIRMWARE / "otis_dual_core_partition.cpp").read_text(
        encoding="utf-8"
    )

    for fault in (
        "ServiceToTimingExhausted",
        "ObservationExhausted",
        "CriticalExhausted",
        "ActuatorTimeout",
        "ActuatorAcknowledgementMismatch",
    ):
        assert fault in header
    assert "telemetry_dropped" in header
    assert "increment_saturating(&telemetry_dropped)" in source
    assert "otis_dual_core_latch_fault" in source
    assert "deadline_ticks" in (
        FIRMWARE / "otis_dual_core_contract.h"
    ).read_text(encoding="utf-8")


def test_stage6_profile_has_real_core0_core1_runtime_partition() -> None:
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    setup1 = sketch[sketch.index("void setup1()") : sketch.index("void loop1()")]
    loop1 = sketch[sketch.index("void loop1()") : sketch.index("void loop()")]
    loop0 = sketch[sketch.index("void loop()") :]

    for call in (
        "boot_phase_timer_init();",
        "boot_phase_pps_input_init();",
        "boot_phase_preview_init();",
    ):
        assert call in setup1
    assert "otis_dual_core_set_timing_owner_active(true)" in setup1
    for call in (
        "service_dual_core_timing_inputs();",
        "otis_pps_dual_observer_service();",
        "otis_capture_backend_service();",
        "drain_pps_count_boundary_ring();",
        "drain_capture_ring();",
        "service_tcxo_gate();",
    ):
        assert call in loop1
    assert loop1.index("otis_capture_backend_service();") < loop1.index(
        "service_tcxo_gate();"
    )

    dual_core0 = loop0[
        loop0.index("#if OTIS_ENABLE_DUAL_CORE_PARTITION") :
        loop0.index("#endif", loop0.index("#if OTIS_ENABLE_DUAL_CORE_PARTITION"))
    ]
    for call in (
        "service_dual_core_outputs();",
        "otis_gnss_receiver_service(millis());",
        "service_serial_commands();",
        "service_environment_sensors();",
        "publish_dual_core_service_metadata(millis());",
    ):
        assert call in dual_core0
    assert "drain_pps_count_boundary_ring();" not in dual_core0
    assert "service_tcxo_gate();" not in dual_core0
    assert "bool core1_separate_stack = true;" in sketch


def test_stage6_routes_raw_evidence_and_environment_by_value() -> None:
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    count = (FIRMWARE / "otis_count_observation.cpp").read_text(
        encoding="utf-8"
    )

    assert "OtisObservationMessageKind::RawEdge" in sketch
    assert "OtisObservationMessageKind::PpsSnapshot" in sketch
    assert "OtisObservationMessageKind::CountObservation" in count
    assert "OtisServiceMessageKind::Environment" in sketch
    assert "OtisServiceMessageKind::ReceiverQualification" in sketch
    assert "OtisServiceMessageKind::AppliedDacState" in sketch
    assert "OtisCriticalMessageKind::StateTransition" in (
        FIRMWARE / "otis_cx317_preview_live.cpp"
    ).read_text(encoding="utf-8")


def test_core1_status_never_bypasses_cross_core_transport() -> None:
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    helper_start = sketch.index("void emit_status_u32(")
    helper_end = sketch.index("void emit_status_i32(", helper_start)
    helper = sketch[helper_start:helper_end]

    assert "emit_status(component, key, buffer, severity, flags);" in helper
    assert "otis_status_emit_u32" not in helper
    timing_health_start = sketch.index("void publish_dual_core_timing_health(")
    timing_health_end = sketch.index(
        "void publish_dual_core_service_metadata(", timing_health_start
    )
    timing_health = sketch[timing_health_start:timing_health_end]
    assert "publish_dual_core_timing_status" in timing_health
    assert "otis_transport_" not in timing_health


def test_live_receiver_invalidation_fixture_is_bounded_and_non_actuating() -> None:
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    start = sketch.index(
        "OtisSerialCommandKind::DualCoreInvalidateGnss"
    )
    end = sketch.index(
        "OtisSerialCommandKind::DualCoreOther", start
    )
    branch = sketch[start:end]

    assert "SyntheticReceiverInvalidation" in branch
    assert "duration_ms = 5000u" in branch
    assert "otis_dual_core_publish_service" in branch
    assert "otis_dac_ad5693r_set_raw" not in branch
    assert "handle_dac_set" not in branch
    assert "active" not in branch.lower()
