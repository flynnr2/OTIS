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
        "EvidenceExhausted",
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


def test_dual_core_preview_transport_excludes_other_core0_writers_mid_frame() -> None:
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    loop0 = sketch[sketch.index("void loop()") :]
    dual_core0 = loop0[
        loop0.index("#if OTIS_ENABLE_DUAL_CORE_PARTITION") :
        loop0.index("#endif", loop0.index("#if OTIS_ENABLE_DUAL_CORE_PARTITION"))
    ]
    busy_guard_start = dual_core0.index(
        "if (otis_phase4_observe_preview_transport_busy()"
    )
    ordinary_writers_start = dual_core0.index("service_dual_core_outputs();")
    busy_guard = dual_core0[busy_guard_start:ordinary_writers_start]

    assert busy_guard_start < ordinary_writers_start
    assert "otis_phase4_observe_preview_service_transport();" in busy_guard
    assert "otis_cx317_preview_live_service_transport();" in busy_guard
    assert "otis_status_led_poll(millis());" in busy_guard
    assert "return;" in busy_guard
    for interleaving_writer in (
        "service_dual_core_outputs();",
        "emit_protocol_banner_if_serial_ready();",
        "emit_run_mode_status_if_ready();",
        "emit_resource_ownership_status();",
        "service_serial_commands();",
        "service_environment_sensors();",
        "emit_periodic_status();",
    ):
        assert interleaving_writer not in busy_guard


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


def test_manual_dac_ack_never_mutates_core1_preview_from_core0() -> None:
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    start = sketch.index("void handle_dac_set(")
    end = sketch.index("void emit_pseudo_pps_status(", start)
    handler = sketch[start:end]
    preview_call = "otis_cx317_preview_live_on_dac_applied(requested_code"

    assert preview_call in handler
    guard = handler.rindex("#if !OTIS_ENABLE_DUAL_CORE_PARTITION", 0, handler.index(preview_call))
    assert handler.index("#endif", handler.index(preview_call)) > guard
    service_start = sketch.index("void service_dual_core_timing_inputs(")
    service_end = sketch.index("void service_dual_core_outputs(", service_start)
    service = sketch[service_start:service_end]
    assert "OtisServiceMessageKind::AppliedDacState" in service
    assert "otis_cx317_preview_live_on_dac_applied(" in service


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

    boundary_start = sketch.index("void emit_pps_count_boundary(")
    boundary_end = sketch.index("void drain_pps_count_boundary_ring(", boundary_start)
    boundary = sketch[boundary_start:boundary_end]
    assert "dual_core_receiver_qualified_for_control()" in boundary
    assert "preview_receiver_valid" in boundary


def test_live_receiver_recovery_is_explicit_qualified_and_non_actuating() -> None:
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    start = sketch.index("OtisSerialCommandKind::DualCoreRecover")
    end = sketch.index("OtisSerialCommandKind::DualCoreOther", start)
    branch = sketch[start:end]

    assert "OtisRunControlKind::Recover" in branch
    assert "otis_dual_core_publish_service" in branch
    assert "otis_dac_ad5693r_set_raw" not in branch
    assert "handle_dac_set" not in branch
    service_start = sketch.index("void service_dual_core_timing_inputs(")
    service_end = sketch.index("void service_dual_core_outputs(", service_start)
    service = sketch[service_start:service_end]
    assert "dual_core_receiver_qualified_for_control()" in service
    assert "otis_cx317_preview_live_request_recovery()" in service
    assert "explicit_recovery_accepted_fresh_support_required" in service
