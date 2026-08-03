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


def test_gnss_uart_is_structurally_receive_only() -> None:
    source = (FIRMWARE / "otis_gnss_receiver.cpp").read_text(encoding="utf-8")
    board = (FIRMWARE / "otis_board.h").read_text(encoding="utf-8")
    registry = (FIRMWARE / "otis_resource_registry.cpp").read_text(
        encoding="utf-8"
    )
    config = (FIRMWARE / "otis_config.h").read_text(encoding="utf-8")

    assert "PIN_SERIAL1_RX" in board and "OTIS_GPIO_GNSS_RX 1u" in board
    assert "PIN_SERIAL1_TX" in board and "OTIS_GPIO_GNSS_TX_SILENT 0u" in board
    assert "gpio_set_function(OTIS_PIN_GNSS_RX, GPIO_FUNC_UART)" in source
    assert "gpio_set_dir(OTIS_PIN_GNSS_TX_SILENT, GPIO_IN)" in source
    assert "gpio_set_function(OTIS_PIN_GNSS_TX_SILENT" not in source
    for forbidden in ("uart_put", "uart_write", "Serial1.write", "Serial1.print"):
        assert forbidden not in source
    assert "#if OTIS_GNSS_UART_TX_ENABLED" in config
    assert "requires Nano TX to remain electrically silent" in config
    assert "OtisResourceType::UartController" in registry
    assert "OTIS_PIN_GNSS_RX" in registry
    assert "OTIS_PIN_GNSS_TX_SILENT" in registry


def test_gnss_service_is_statically_bounded_and_capture_first() -> None:
    header = (FIRMWARE / "otis_gnss_receiver.h").read_text(encoding="utf-8")
    source = (FIRMWARE / "otis_gnss_receiver.cpp").read_text(encoding="utf-8")
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )

    assert "kOtisGnssMaximumLineBytes = 96u" in header
    assert "OTIS_GNSS_SERVICE_BYTE_BUDGET" in source
    assert "while (remaining-- > 0u && uart_is_readable(uart0))" in source
    loop = sketch[sketch.index("void loop()") :]
    assert loop.index("otis_capture_backend_service()") < loop.index(
        "otis_gnss_receiver_service(millis())"
    )
    assert loop.index("drain_pps_count_boundary_ring()") < loop.index(
        "otis_gnss_receiver_service(millis())"
    )
    assert loop.index("drain_capture_ring()") < loop.index(
        "otis_gnss_receiver_service(millis())"
    )
