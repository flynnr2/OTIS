from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


@pytest.mark.parametrize("harness", ["gnss_operational_baud_harness.cpp",
                                     "adafruit_gnss_harness.cpp"])
def test_fixed_operational_gnss_path_is_native_verified(tmp_path: Path, harness: str) -> None:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    executable = tmp_path / "gnss_operational_harness"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-DOTIS_GNSS_HOST_TEST",
            "-I",
            str(FIRMWARE),
            "-I", str(ROOT / "firmware/arduino/libraries/Adafruit_GPS/src"),
            str(ROOT / "firmware/arduino/libraries/Adafruit_GPS/src/Adafruit_GNSS.cpp"),
            str(ROOT / "firmware/arduino/libraries/Adafruit_GPS/src/Adafruit_NMEA.cpp"),
            str(ROOT / "tests/cpp" / harness),
            str(FIRMWARE / "otis_gnss_receiver.cpp"),
            str(FIRMWARE / "otis_gnss_uart_rx.cpp"),
            "-o",
            str(executable),
        ],
        check=True,
        cwd=ROOT,
    )
    subprocess.run([str(executable)], check=True, cwd=ROOT)


def test_fixed_receiver_uses_115200_without_characterization_or_scan() -> None:
    config = (FIRMWARE / "otis_config.h").read_text(encoding="utf-8")
    source = (FIRMWARE / "otis_gnss_receiver.cpp").read_text(encoding="utf-8")
    assert "#define OTIS_GNSS_UART_BAUD 115200u" in config
    assert "BAUD_CHARACTERIZATION" not in config
    assert "DISCOVERY_STARTUP_BAUD_HINT" not in config
    assert "RETAIN_DISCOVERED_STARTUP_BAUD" not in config
    assert "kGnssCandidateBauds" not in source


def test_gnss_configuration_tx_is_bounded_and_metadata_is_qualification_only() -> None:
    config = (FIRMWARE / "otis_config.h").read_text(encoding="utf-8")
    source = (FIRMWARE / "otis_gnss_receiver.cpp").read_text(encoding="utf-8")
    assert "OTIS_GNSS_UART_TX_ENABLED" not in config
    assert "OTIS_GNSS_COMMAND_RESPONSE_TIMEOUT_MS" in config
    assert 'constexpr char kGnssTargetBaudCommand[] = "$PMTK251,115200*1F\\r\\n"' in source
    assert "uart_get_hw(uart0)->dr" in source

    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    assert "otis_gnss_receiver_service(now_ms);" in sketch
    assert sketch.index("otis_gnss_receiver_service(now_ms);") < sketch.index(
        "service_dual_core_serial_frame_transport();"
    )
