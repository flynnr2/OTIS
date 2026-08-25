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
            "-I",
            str(FIRMWARE),
            str(ROOT / "tests/cpp/gnss_receiver_harness.cpp"),
            str(FIRMWARE / "otis_gnss_receiver.cpp"),
            "-o",
            str(executable),
        ],
        check=True,
        cwd=ROOT,
    )
    subprocess.run([str(executable)], check=True, cwd=ROOT)


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
    assert '"$PMTK251,115200*1F\\r\\n"' in source
    assert '"$PMTK414*33\\r\\n"' in source
    assert '"$PMTK314,0,1,0,1,1,0' in source
    assert "OTIS_ENABLE_GNSS_RECEIVER && !OTIS_GNSS_UART_TX_ENABLED" in config
    assert "#define OTIS_GNSS_UART_BAUD 115200u" in config
    assert "OtisResourceType::UartController" in registry
    assert "OTIS_PIN_GNSS_RX" in registry
    assert "OTIS_PIN_GNSS_TX" in registry


def test_gnss_service_is_statically_bounded_and_capture_first() -> None:
    header = (FIRMWARE / "otis_gnss_receiver.h").read_text(encoding="utf-8")
    source = (FIRMWARE / "otis_gnss_receiver.cpp").read_text(encoding="utf-8")
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )

    assert "kOtisGnssMaximumLineBytes = 96u" in header
    assert "kOtisGnssDiscoveryMaximumLineBytes = 256u" in header
    assert "OTIS_GNSS_SERVICE_BYTE_BUDGET" in source
    assert "OTIS_GNSS_SERVICE_TX_BYTE_BUDGET" in source
    assert "while (remaining-- > 0u && uart_is_readable(uart0))" in source
    assert "while (remaining-- > 0u && live_transmit.index" in source
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
        "OTIS_GNSS_SERVICE_BYTE_BUDGET"
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
    assert sketch.count("emit_gnss_receiver_status();") == 3
    assert "emit_gnss_receiver_status(now_ms);" not in sketch
    assert "emit_gnss_receiver_status(millis());" not in sketch
