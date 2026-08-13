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
    assert "OTIS_TELEMETRY_KEY_CAPACITY = 40u" in contract
    assert "char key[OTIS_TELEMETRY_KEY_CAPACITY]" in contract


def test_queue_classes_match_stage6_loss_contract() -> None:
    header = (FIRMWARE / "otis_dual_core_partition.h").read_text(
        encoding="utf-8"
    )
    source = (FIRMWARE / "otis_dual_core_partition.cpp").read_text(
        encoding="utf-8"
    )

    for fault in (
        "ServiceToTimingExhausted",
        "BootTelemetryExhausted",
        "BootHandshakeTimeout",
        "ObservationExhausted",
        "CriticalExhausted",
        "EvidenceExhausted",
        "PhasePreviewQueueExhausted",
        "PhasePreviewFault",
        "ActuatorTimeout",
        "ActuatorAcknowledgementMismatch",
    ):
        assert fault in header
    assert "telemetry_dropped" in header
    assert "increment_saturating(&telemetry_dropped)" in source
    assert "otis_dual_core_latch_fault" in source
    assert "monotonic_deadline_s" in (
        FIRMWARE / "otis_dual_core_contract.h"
    ).read_text(encoding="utf-8")


def test_stage7_active_status_burst_is_formula_derived_and_fits_queue() -> None:
    header = (FIRMWARE / "otis_dual_core_partition.h").read_text(
        encoding="utf-8"
    )

    assert "OTIS_CX317_ACTIVE_STATUS_FIELD_COUNT = 33u" in header
    assert "OTIS_CX317_ACTIVE_STATUS_ENVELOPE_COUNT = 3u" in header
    assert "OTIS_TIMING_HEALTH_NONACTIVE_TELEMETRY_BURST = 70u" in header
    assert (
        "OTIS_TIMING_HEALTH_NONACTIVE_TELEMETRY_BURST +\n"
        "    OTIS_CX317_ACTIVE_STATUS_TELEMETRY_BURST"
    ) in header
    assert (
        "OTIS_TIMING_HEALTH_TELEMETRY_BURST +\n"
        "    OTIS_CX317_ACTIVE_STATUS_TELEMETRY_BURST"
    ) in header
    assert "OTIS_MAXIMUM_CONCURRENT_TELEMETRY_BURST == 142u" in header
    assert "OTIS_MAXIMUM_BOOT_TELEMETRY_BURST = 169u" in header
    assert "OTIS_TELEMETRY_QUEUE_DEPTH = 192u" in header
    assert "OTIS_TELEMETRY_QUEUE_DEPTH >=\n" in header


def test_service_queue_fault_diagnostics_are_complete_and_bounded() -> None:
    source = (FIRMWARE / "otis_dual_core_partition.cpp").read_text(
        encoding="utf-8"
    )
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    take_start = source.index("bool otis_dual_core_take_service(")
    take_end = source.index("bool otis_dual_core_publish_observation(", take_start)
    take = source[take_start:take_end]
    loop_start = sketch.index("void loop1()")
    loop_end = sketch.index("void loop()", loop_start)
    loop = sketch[loop_start:loop_end]

    assert "kDualCoreTimingTracePeriodMs = 250u" in sketch
    assert "dual_core_timing_trace_due(now_ms)" in loop
    assert "if (trace_timing_loop)" in loop
    assert "consumed < OTIS_SERVICE_TO_TIMING_QUEUE_DEPTH" in sketch
    assert "increment_saturating" not in take.split(
        "if (!service_to_timing.try_pop(message)) return false;", 1
    )[0]
    assert "service_take_accounting\", \"successful_only" in sketch
    assert "fault_breadcrumb_coherent" in sketch
    assert "timing_breadcrumb_generation" in source
    for key in (
        "fault_failing_publish_ticks",
        "fault_last_taken_kind",
        "fault_last_taken_sequence",
        "fault_last_taken_ticks",
        "fault_last_snapshot_session",
    ):
        assert key in sketch


def test_dual_core_boot_waits_and_telemetry_publication_are_bounded() -> None:
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    partition = (FIRMWARE / "otis_dual_core_partition.cpp").read_text(
        encoding="utf-8"
    )
    setup0 = sketch[sketch.index("void setup()") : sketch.index("void setup1()")]
    setup1 = sketch[sketch.index("void setup1()") : sketch.index("void loop1()")]
    boot_publish = partition[
        partition.index("bool otis_dual_core_publish_boot_telemetry(") :
        partition.index("bool otis_dual_core_take_telemetry(")
    ]

    assert "kDualCoreBootHandshakeTimeoutMs = 10000u" in sketch
    assert "timing_boot_wait_started_ms" in setup0
    assert "service_boot_wait_started_ms" in setup1
    assert "BootFatal::DualCoreHandshakeTimeout" in setup0
    assert "while" not in boot_publish
    assert "BootTelemetryExhausted" in boot_publish


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
    carrier_gate = loop1.index("if (!dual_core_serial_carrier_seen)")
    for call in (
        "service_dual_core_timing_inputs();",
        "otis_pps_dual_observer_service();",
        "otis_capture_backend_service();",
        "drain_pps_count_boundary_ring();",
        "drain_capture_ring();",
        "service_tcxo_gate();",
        "publish_dual_core_timing_health(now_ms);",
    ):
        assert loop1.index(call) < carrier_gate

    dual_core0 = loop0[
        loop0.index("#if OTIS_ENABLE_DUAL_CORE_PARTITION") :
        loop0.index("// Capture service always runs first.")
    ]
    for call in (
        "service_dual_core_outputs();",
        "otis_gnss_receiver_service(now_ms);",
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
        loop0.index("// Capture service always runs first.")
    ]
    context = sketch[
        sketch.index("OtisSetupAuthorityContext current_dual_core_setup_authority_context(") :
        sketch.index("OtisSetupExecutionContext current_dual_core_setup_execution_context(")
    ]
    assert "active.setup_gnss_eligible" in context
    assert "dual_core_receiver_qualified_for_control()" in context
    assert "dual_core_receiver.identity_stable" in context
    assert "dual_core_receiver.gsa_3d" in context
    busy_guard_start = dual_core0.index("if (frame_active)")
    ordinary_writers_start = dual_core0.index("service_dual_core_outputs();")
    busy_guard = dual_core0[busy_guard_start:ordinary_writers_start]

    assert busy_guard_start < ordinary_writers_start
    assert "otis_status_led_poll(now_ms);" in busy_guard
    assert "service_serial_commands(false);" in busy_guard
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

    dispatch = sketch[
        sketch.index("bool service_dual_core_serial_frame_transport(void)") :
        sketch.index("#endif", sketch.index("bool service_dual_core_serial_frame_transport(void)"))
    ]
    assert "switch (owner)" in dispatch
    assert "otis_serial_frame_arbiter_release" in dispatch
    for writer in (
        "service_dual_core_evidence_transport();",
        "otis_observe_only_discipline_live_service_transport();",
        "otis_cx317_preview_live_service_transport();",
        "otis_phase_preview_transport_service();",
    ):
        assert dispatch.count(writer) == 1


def test_dual_core_cx317_preview_copy_does_not_nest_full_frames_on_core1_stack() -> None:
    preview = (FIRMWARE / "otis_cx317_preview_live.cpp").read_text(
        encoding="utf-8"
    )
    enqueue_start = preview.index("bool enqueue(const char *data, size_t length) {")
    enqueue_end = preview.index("bool code_context_valid(", enqueue_start)
    enqueue = preview[enqueue_start:enqueue_end]
    dual_core_path = enqueue[
        enqueue.index("#if OTIS_ENABLE_DUAL_CORE_PARTITION") :
        enqueue.index("#else", enqueue.index("#if OTIS_ENABLE_DUAL_CORE_PARTITION"))
    ]

    assert "OtisEvidenceFrameMessage evidence_frame_scratch = {};" in preview
    assert "evidence_frame_scratch.data[length] = '\\0';" in dual_core_path
    assert "otis_dual_core_publish_evidence(&evidence_frame_scratch)" in dual_core_path
    assert "Frame frame = {};" not in dual_core_path
    assert "OtisEvidenceFrameMessage message = {};" not in dual_core_path


def test_dual_core_timing_paths_keep_full_formatters_out_of_automatic_storage() -> None:
    preview = (FIRMWARE / "otis_cx317_preview_live.cpp").read_text(
        encoding="utf-8"
    )
    active = (FIRMWARE / "otis_cx317_active_live.cpp").read_text(
        encoding="utf-8"
    )
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )

    assert "char formatter_scratch[kFrameCapacity] = {};" in preview
    assert preview.count("char frame[kFrameCapacity];") == 3
    assert preview.count("#if OTIS_ENABLE_DUAL_CORE_PARTITION\n  char *frame = formatter_scratch;") == 3

    assert "OtisEvidenceFrameMessage evidence_frame_scratch = {};" in active
    assert "OtisEvidenceFrameMessage message = {};" not in active
    assert active.count("otis_dual_core_publish_evidence(&evidence_frame_scratch)") == 2

    assert "OtisEvidenceFrameMessage dual_core_association_loss_scratch = {};" in sketch
    association_start = sketch.index(
        "void publish_dual_core_association_loss_decision("
    )
    association_end = sketch.index("\n}\n#endif", association_start)
    association = sketch[association_start:association_end]
    assert "OtisEvidenceFrameMessage message = {};" not in association
    assert (
        "otis_dual_core_publish_evidence(&dual_core_association_loss_scratch);"
        in association
    )


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


def test_applied_ack_advances_core1_dac_cache_before_health_check() -> None:
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    service_start = sketch.index("void service_dual_core_timing_inputs(")
    service_end = sketch.index("void service_dual_core_outputs(", service_start)
    service = sketch[service_start:service_end]
    applied_branch = service[
        service.index("OtisServiceMessageKind::ActuatorAcknowledgement") :
    ]

    assert applied_branch.index(
        "otis_cx317_active_live_on_cross_core_ack"
    ) < applied_branch.index(
        "otis_cx317_dual_core_static_state_on_applied_ack"
    )
    assert "OtisPartitionFault::ActuatorAcknowledgementMismatch" in applied_branch


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
