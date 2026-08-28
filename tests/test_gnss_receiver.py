from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def test_bounded_gnss_parser_fixtures(tmp_path: Path) -> None:
    executable = tmp_path / "gnss_receiver_harness"
    subprocess.run(
        [
            "c++",
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-DOTIS_GNSS_HOST_TEST",
            "-DOTIS_GNSS_UART_BAUD=9600u",
            "-I",
            str(FIRMWARE),
            str(ROOT / "tests/cpp/gnss_receiver_harness.cpp"),
            str(FIRMWARE / "otis_gnss_receiver.cpp"),
            str(FIRMWARE / "otis_gnss_uart_rx.cpp"),
            "-o",
            str(executable),
        ],
        check=True,
        cwd=ROOT,
    )
    subprocess.run([str(executable)], check=True, cwd=ROOT)


def test_operational_115200_fixed_bootstrap_and_no_scan_recovery(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "gnss_operational_baud_harness"
    subprocess.run(
        [
            "c++",
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-DOTIS_GNSS_HOST_TEST",
            "-DOTIS_GNSS_UART_BAUD=115200u",
            "-DOTIS_ENABLE_GNSS_RECEIVER=1",
            "-DOTIS_GNSS_UART_TX_ENABLED=1",
            "-DOTIS_GNSS_OPERATIONAL_CONFIG_BLIND_PROMOTION=1",
            "-I",
            str(FIRMWARE),
            str(ROOT / "tests/cpp/gnss_operational_baud_harness.cpp"),
            str(FIRMWARE / "otis_gnss_receiver.cpp"),
            str(FIRMWARE / "otis_gnss_uart_rx.cpp"),
            "-o",
            str(executable),
        ],
        check=True,
        cwd=ROOT,
    )
    subprocess.run([str(executable)], check=True, cwd=ROOT)


def test_characterization_parser_and_stale_baud_epoch_gate(tmp_path: Path) -> None:
    executable = tmp_path / "gnss_baud_characterization_harness"
    subprocess.run(
        [
            "c++",
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-DOTIS_GNSS_HOST_TEST",
            "-DOTIS_GNSS_UART_BAUD=9600u",
            "-DOTIS_GNSS_COMMAND_RESPONSE_TIMEOUT_MS=2000u",
            "-DOTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION=1",
            "-DOTIS_GNSS_DISCOVERY_STARTUP_BAUD_HINT=57600u",
            "-DOTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD=1",
            "-I",
            str(FIRMWARE),
            str(ROOT / "tests/cpp/gnss_baud_characterization_harness.cpp"),
            str(FIRMWARE / "otis_gnss_receiver.cpp"),
            str(FIRMWARE / "otis_gnss_uart_rx.cpp"),
            "-o",
            str(executable),
        ],
        check=True,
        cwd=ROOT,
    )
    subprocess.run([str(executable)], check=True, cwd=ROOT)


def test_resume_startup_115200_attachment_and_request_one_binding(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "gnss_baud_characterization_resume_harness"
    subprocess.run(
        [
            "c++",
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-DOTIS_GNSS_HOST_TEST",
            "-DOTIS_GNSS_UART_BAUD=9600u",
            "-DOTIS_GNSS_COMMAND_RESPONSE_TIMEOUT_MS=2000u",
            "-DOTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION=1",
            "-DOTIS_GNSS_DISCOVERY_STARTUP_BAUD_HINT=57600u",
            "-DOTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD=1",
            "-DOTIS_GNSS_BAUD_CHARACTERIZATION_RESUME=1",
            "-I",
            str(FIRMWARE),
            str(ROOT / "tests/cpp/gnss_baud_characterization_harness.cpp"),
            str(FIRMWARE / "otis_gnss_receiver.cpp"),
            str(FIRMWARE / "otis_gnss_uart_rx.cpp"),
            "-o",
            str(executable),
        ],
        check=True,
        cwd=ROOT,
    )
    subprocess.run([str(executable)], check=True, cwd=ROOT)


def test_characterization_startup_baud_hint_rejects_invalid_value(
    tmp_path: Path,
) -> None:
    source = tmp_path / "invalid_startup_hint.cpp"
    source.write_text('#include "otis_config.h"\n', encoding="utf-8")
    result = subprocess.run(
        [
            "c++",
            "-std=c++17",
            "-DOTIS_GNSS_HOST_TEST",
            "-DOTIS_GNSS_UART_BAUD=9600u",
            "-DOTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION=1",
            "-DOTIS_GNSS_DISCOVERY_STARTUP_BAUD_HINT=4800u",
            "-I",
            str(FIRMWARE),
            "-c",
            str(source),
            "-o",
            str(tmp_path / "invalid_startup_hint.o"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert (
        "GNSS characterization startup baud hint must be in the frozen "
        "five-rate set."
    ) in result.stderr


def test_retained_startup_baud_requires_an_explicit_characterization_hint(
    tmp_path: Path,
) -> None:
    source = tmp_path / "missing_startup_hint.cpp"
    source.write_text('#include "otis_config.h"\n', encoding="utf-8")
    result = subprocess.run(
        [
            "c++",
            "-std=c++17",
            "-DOTIS_GNSS_HOST_TEST",
            "-DOTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION=1",
            "-DOTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD=1",
            "-I",
            str(FIRMWARE),
            "-c",
            str(source),
            "-o",
            str(tmp_path / "missing_startup_hint.o"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert (
        "Retaining a discovered startup baud requires an explicit nonzero hint."
        in result.stderr
    )


def test_operational_promotion_rejects_an_unqualified_settle(
    tmp_path: Path,
) -> None:
    source = tmp_path / "invalid_operational_settle.cpp"
    source.write_text('#include "otis_config.h"\n', encoding="utf-8")
    result = subprocess.run(
        [
            "c++",
            "-std=c++17",
            "-DOTIS_GNSS_HOST_TEST",
            "-DOTIS_ENABLE_GNSS_RECEIVER=1",
            "-DOTIS_GNSS_UART_TX_ENABLED=1",
            "-DOTIS_GNSS_UART_BAUD=115200u",
            "-DOTIS_GNSS_OPERATIONAL_CONFIG_BLIND_PROMOTION=1",
            "-DOTIS_GNSS_OPERATIONAL_PROMOTION_SETTLE_MS=999u",
            "-I",
            str(FIRMWARE),
            "-c",
            str(source),
            "-o",
            str(tmp_path / "invalid_operational_settle.o"),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert result.returncode != 0
    assert (
        "GNSS operational promotion settle must be between 1 and 5 seconds."
        in result.stderr
    )


def test_gnss_uart_has_only_the_bounded_discovery_configuration_tx_path() -> None:
    source = (FIRMWARE / "otis_gnss_receiver.cpp").read_text(encoding="utf-8")
    board = (FIRMWARE / "otis_board.h").read_text(encoding="utf-8")
    registry = (FIRMWARE / "otis_resource_registry.cpp").read_text(
        encoding="utf-8"
    )
    config = (FIRMWARE / "otis_config.h").read_text(encoding="utf-8")

    assert "PIN_SERIAL1_RX" in board and "OTIS_GPIO_GNSS_RX 1u" in board
    assert "PIN_SERIAL1_TX" in board and "OTIS_GPIO_GNSS_TX 0u" in board
    assert "gpio_set_function(OTIS_PIN_GNSS_RX, GPIO_FUNC_UART)" in source
    assert "gpio_set_function(OTIS_PIN_GNSS_TX, GPIO_FUNC_UART)" in source
    assert source.count("uart_get_hw(uart0)->dr =") == 1
    for forbidden in (
        "uart_putc",
        "uart_puts",
        "uart_write_blocking",
        "Serial1.write",
        "Serial1.print",
    ):
        assert forbidden not in source
    assert '"$PMTK605*31\\r\\n"' in source
    assert '"$PMTK251,9600*17\\r\\n"' in source
    assert '"$PMTK251,115200*1F\\r\\n"' in source
    assert "finite write-only promotion is a boot transaction" in source
    assert "OTIS_GNSS_OPERATIONAL_CONFIG_BLIND_PROMOTION" in source
    assert "OTIS_GNSS_OPERATIONAL_PROMOTION_SETTLE_MS" in source
    assert '"$PMTK414*33\\r\\n"' in source
    assert '"$PMTK314,0,1,0,1,1,0' in source
    assert "OtisGnssLinkState::ObserveConfiguredOutput" in source
    assert "Pmtk314AckObservedExact" in source
    assert "last_identity_response_baud" in source
    assert "output_query_timeout_count" in source
    assert "OTIS_ENABLE_GNSS_RECEIVER && !OTIS_GNSS_UART_TX_ENABLED" in config
    assert "#define OTIS_GNSS_UART_BAUD 115200u" in config
    assert "#define OTIS_GNSS_DISCOVERY_STARTUP_BAUD_HINT 0u" in config
    assert (
        "#define OTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD 0"
        in config
    )
    assert (
        "GNSS characterization startup baud hint must be in the frozen "
        "five-rate set."
    ) in config
    assert source.index('#include "otis_config.h"') < source.index(
        "#if OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION"
    )
    assert "OtisResourceType::UartController" in registry
    assert "OTIS_PIN_GNSS_RX" in registry
    assert "OTIS_PIN_GNSS_TX" in registry


def test_gnss_service_is_statically_bounded_and_capture_first() -> None:
    header = (FIRMWARE / "otis_gnss_receiver.h").read_text(encoding="utf-8")
    source = (FIRMWARE / "otis_gnss_receiver.cpp").read_text(encoding="utf-8")
    ring_header = (FIRMWARE / "otis_gnss_uart_rx.h").read_text(encoding="utf-8")
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    assert (
        "uart0_configuration_blind_default_or_retained_115200_v1"
    ) in sketch
    assert "operational_bootstrap_peripheral_complete_count" in sketch
    assert "post_bootstrap_target_baud_command_attempt_count" in sketch
    assert "post_bootstrap_baud_change_count" in sketch
    assert '"initial_discovery_outcome", "not_applicable"' in sketch
    assert "continuous wrong-baud noise" in source
    assert "otis_gnss_uart_rx_ring_discard_all" in source
    assert "otis_gnss_link_tick_may_advance_with_rx_backlog" in source
    assert "otis_gnss_uart_rx_bounded_hardware_discard" in source

    assert "kOtisGnssMaximumLineBytes = 96u" in header
    assert "kOtisGnssDiscoveryMaximumLineBytes = 256u" in header
    assert "kOtisGnssUartRxConsumerByteBudget = 128u" in ring_header
    assert "kOtisGnssUartRxConsumerTickBudget = 4000u" in ring_header
    assert "kOtisGnssUartRxTransitionHardwareDiscardBudget = 32u" in ring_header
    assert ring_header.count("uint64_t consumer_service_call_count;") == 2
    assert '"consumer_service_call_count_width_bits", 64u' in sketch
    assert "OTIS_GNSS_SERVICE_TX_BYTE_BUDGET" in source
    assert "OTIS_GNSS_DISCOVERY_STARTUP_BAUD_HINT" in source
    assert (
        "OTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD"
        in source
    )
    assert "while ((hardware->fr & UART_UARTFR_RXFE_BITS) == 0u)" in source
    assert "otis_gnss_uart_rx_ring_push_from_isr" in source
    assert "while (remaining-- > 0u && live_transmit.index" in source
    service = source[
        source.index("void otis_gnss_receiver_service") :
        source.index("void otis_gnss_receiver_get_snapshot")
    ]
    assert service.index("complete_live_transmit_if_drained(now_ms)") < (
        service.index("service_live_uart_rx_ring(now_ms)")
    )
    assert service.index("service_live_uart_rx_ring(now_ms)") < service.index(
        "otis_gnss_uart_rx_ring_depth(&live_uart_rx_ring) == 0u"
    ) < service.index("otis_gnss_link_tick_may_advance_with_rx_backlog") < (
        service.index("otis_gnss_link_tick(&live_link, now_ms)")
    )
    loop1 = sketch[sketch.index("void loop1()") : sketch.index("void loop()")]
    loop = sketch[sketch.index("void loop()") :]
    dual_start = loop.index("#if OTIS_ENABLE_DUAL_CORE_PARTITION")
    dual_end = loop.index("#endif", dual_start)
    dual_core0 = loop[dual_start:dual_end]
    legacy = loop[loop.index("// Capture service always runs first") :]

    assert "otis_capture_backend_service()" in loop1
    assert "drain_pps_count_boundary_ring()" in loop1
    assert "drain_capture_ring()" in loop1
    assert "otis_gnss_receiver_service(millis())" not in loop1
    assert "otis_gnss_receiver_service(now_ms)" in dual_core0
    assert "drain_pps_count_boundary_ring()" not in dual_core0
    assert "drain_capture_ring()" not in dual_core0

    assert legacy.index("otis_capture_backend_service()") < legacy.index(
        "otis_gnss_receiver_service(millis())"
    )
    main_path = legacy[legacy.index("emit_protocol_banner_if_serial_ready()") :]
    assert main_path.index("drain_pps_count_boundary_ring()") < main_path.index(
        "otis_gnss_receiver_service(millis())"
    )
    assert main_path.index("drain_capture_ring()") < main_path.index(
        "otis_gnss_receiver_service(millis())"
    )
    assert "otis_gnss_receiver_service(millis())" in legacy[
        legacy.index("if (otis_cx317_active_live_transport_busy())") :
        legacy.index("emit_protocol_banner_if_serial_ready()")
    ]


def test_gnss_begin_is_constant_time_and_does_not_gate_timing_boot() -> None:
    source = (FIRMWARE / "otis_gnss_receiver.cpp").read_text(encoding="utf-8")
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    begin_start = source.index("bool otis_gnss_receiver_begin(void)")
    begin = source[
        begin_start : source.index("void otis_gnss_receiver_service", begin_start)
    ]
    assert "otis_gnss_link_reset" in begin
    assert "begin_pending_link_action" in begin
    assert "while (" not in begin
    assert "delay(" not in begin

    setup = sketch[sketch.index("void setup()") : sketch.index("void setup1()")]
    timing_handoff = setup.rindex(
        "__atomic_store_n(&dual_core_service_boot_ready"
    )
    assert setup.index("boot_phase_peripherals_init();") < timing_handoff
    assert "otis_gnss_receiver_service(millis())" in setup[
        timing_handoff:
    ]


def test_status_output_interleaves_bounded_gnss_service() -> None:
    receiver_source = (FIRMWARE / "otis_gnss_receiver.cpp").read_text(
        encoding="utf-8"
    )
    status_source = (FIRMWARE / "otis_status_emit.cpp").read_text(
        encoding="utf-8"
    )

    assert "bool live_receiver_started = false;" in receiver_source
    service = receiver_source[
        receiver_source.index("void otis_gnss_receiver_service") :
    ]
    assert service.index("if (!live_receiver_started) return;") < service.index(
        "service_live_uart_rx_ring(now_ms)"
    )

    emitter = status_source[status_source.index("void otis_status_emit(") :]
    assert emitter.index("otis_emit_health(") < emitter.index(
        "otis_gnss_receiver_service(millis())"
    )
    assert "#if OTIS_ENABLE_GNSS_RECEIVER" in emitter


def test_gnss_status_freshness_uses_a_local_post_service_clock_anchor() -> None:
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    status = sketch[
        sketch.index("void emit_gnss_receiver_status(void)") :
        sketch.index("void emit_h0_pin_status(void)")
    ]

    assert status.index("const uint32_t now_ms = millis();") < status.index(
        "otis_gnss_receiver_get_snapshot(now_ms, &status);"
    )
    assert sketch.count("emit_gnss_receiver_status();") >= 3
    assert "emit_gnss_receiver_status(now_ms);" not in sketch
    assert "emit_gnss_receiver_status(millis());" not in sketch


def test_startup_attachment_telemetry_and_local_request_invariants() -> None:
    receiver = (FIRMWARE / "otis_gnss_receiver.cpp").read_text(encoding="utf-8")
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    status = sketch[
        sketch.index("void emit_gnss_receiver_status(void)") :
        sketch.index("void emit_h0_pin_status(void)")
    ]
    for key in (
        "startup_hint_attempted",
        "startup_hint_baud",
        "startup_hint_identity_outcome",
        "startup_fallback_entered",
        "initial_discovery_identity_baud",
        "initial_discovery_outcome",
        "pmtk605_peripheral_complete_count",
        "pmtk605_last_peripheral_complete_ticks",
        "pmtk605_last_peripheral_complete_ticks_available",
        "pmtk605_last_peripheral_complete_ticks_domain",
    ):
        assert f'"{key}"' in status
    assert '"rp2040_timer0_extended"' in status

    request = receiver[
        receiver.index("OtisGnssRequestDisposition otis_gnss_receiver_request_baud_transition") :
        receiver.index("OtisGnssRequestDisposition otis_gnss_receiver_begin_status_challenge")
    ]
    assert ": 1u;" in request
    assert "request.request_sequence == 1u" in request
    assert "request.segment_ordinal == 1u" in request
    assert "request.target_baud == live_link.confirmed_baud" in request
    binding = request[
        request.index("if (retained_startup_binding) {") :
        request.index("close_collectors_for_planned_transition();")
    ]
    assert "AwaitFreshMetadata" in binding
    assert "TransmitTargetBaud" not in binding
    assert "queue_link_action" not in binding

    live_begin = receiver[
        receiver.index("bool otis_gnss_receiver_begin(void)") :
        receiver.index("void otis_gnss_receiver_service", receiver.index("bool otis_gnss_receiver_begin(void)"))
    ]
    assert "live_characterization.baud_epoch = 1u;" in live_begin
    pending_action = receiver[
        receiver.index("void begin_pending_link_action") :
        receiver.index("bool otis_gnss_receiver_begin(void)")
    ]
    assert (
        "live_link.state == OtisGnssLinkState::SelectTargetBaud &&\n"
        "        live_characterization.request_available"
    ) in pending_action
    assert "live_characterization.baud_epoch++;" in pending_action
    assert "OtisGnssLinkState::SelectCandidateBaud" not in pending_action


def test_characterization_coherent_snapshot_contains_host_decision_schema() -> None:
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    count_source = (FIRMWARE / "otis_count_observation.cpp").read_text(
        encoding="utf-8"
    )
    receiver_source = (FIRMWARE / "otis_gnss_receiver.cpp").read_text(
        encoding="utf-8"
    )
    fields = sketch[
        sketch.index("void emit_gnss_characterization_snapshot_fields") :
        sketch.index("void emit_gnss_receiver_status(void)")
    ]
    required = {
        "capture": (
            "dropped_count",
            "pps_count_boundary_dropped_count",
        ),
        "pps_d14": ("rejected_short_count", "rejected_long_count"),
        "pps_gate": (
            "boundary_ring_dropped_count",
            "rejected_window_count",
            "missing_pps_count",
            "pps_interval_anomaly_count",
            "boundary_sequence_gap_count",
            "boundary_sequence_duplicate_count",
            "boundary_overflow_count",
            "counter_snapshot_invalid_count",
            "physical_aperture_incomplete_count",
            "association_loss_count",
            "snapshot_continuity_loss_count",
            "physical_pps_missing_count",
            "characterization_mirror_generation",
            "characterization_mirror_capture_session",
            "characterization_mirror_reference_sequence",
        ),
        "dual_core": (
            "service_publish_failures",
            "telemetry_dropped",
            "partition_fault",
        ),
        "gnss_baud_characterization": (
            "request_seq",
            "metadata_frontier",
            "extended_counter_ticks",
            "target_command_transmit_complete",
            "target_identity_confirmed",
            "target_output_confirmed",
        ),
        "gnss_uart_rx": (
            "phase_window_ring_high_water",
            "completed_peak_challenge_sequence",
            "completed_peak_retention_policy",
        ),
        "build": ("profile_id", "source_sha256", "config_sha256"),
    }
    for component, keys in required.items():
        assert f'"{component}"' in fields
        for key in keys:
            assert f'"{key}"' in fields

    status = sketch[
        sketch.index("void emit_gnss_receiver_status(void)") :
        sketch.index("void emit_h0_pin_status(void)")
    ]
    assert status.index('"snapshot", "begin"') < status.index(
        "emit_gnss_characterization_snapshot_fields"
    ) < status.index('"snapshot", "end"')
    assert status.index('"snapshot", "end"') < status.index(
        "otis_gnss_receiver_finish_status_snapshot"
    )
    assert "status_challenge_phase_snapshot_pending = false" not in (
        receiver_source[
            receiver_source.index("void otis_gnss_receiver_get_snapshot") :
            receiver_source.index(
                "OtisGnssRequestDisposition otis_gnss_receiver_request_baud_transition"
            )
        ]
    )
    assert "otis_gnss_completed_peak_prepare_next" in receiver_source
    assert "otis_gnss_completed_peak_publish" in receiver_source
    gate_status = count_source[
        count_source.index("void emit_pps_gate_status") :
        count_source.index("void emit_pps_gate_window_status")
    ]
    assert gate_status.index('"snapshot", "begin"') < gate_status.index(
        '"snapshot_generation"'
    ) < gate_status.index('"snapshot", "end"')


def test_characterization_snapshot_counter_is_d14_session_bound() -> None:
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    boundary = sketch[
        sketch.index("void note_gnss_d14_snapshot_boundary") :
        sketch.index("#endif", sketch.index("void note_gnss_d14_snapshot_boundary"))
    ]
    assert "otis_timer0_extension_advance_boundary" in boundary
    assert "capture_session" in boundary
    assert "reference_sequence" in boundary
    assert "kGnssSnapshotProjectionMaximumDistanceTicks = 19200000ull" in sketch
    assert "otis_timer0_extension_project_nearest" in sketch
    assert '"snapshot_counter_domain"' in sketch
    assert '"rp2040_timer0_extended"' in sketch
