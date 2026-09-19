from pathlib import Path
import shutil
import subprocess

import pytest
from tools import build_firmware

ROOT = Path(__file__).resolve().parents[1]
LIBS = ROOT / "firmware/arduino/libraries"
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def test_real_adafruit_sensor_drivers_with_bus_faults(tmp_path):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler unavailable")
    executable = tmp_path / "environment"
    includes = [ROOT / "tests/cpp/sensor_stubs", FIRMWARE,
                LIBS / "Adafruit_SHT4X", LIBS / "Adafruit_BMP280_Library",
                LIBS / "Adafruit_BusIO", LIBS / "Adafruit_Sensor"]
    sources = [ROOT / "tests/cpp/adafruit_environment_harness.cpp",
               FIRMWARE / "otis_env_sensors.cpp", FIRMWARE / "otis_i2c_bus.cpp",
               LIBS / "Adafruit_SHT4X/Adafruit_SHT4x.cpp",
               LIBS / "Adafruit_BMP280_Library/Adafruit_BMP280.cpp",
               LIBS / "Adafruit_BusIO/Adafruit_I2CDevice.cpp",
               LIBS / "Adafruit_BusIO/Adafruit_SPIDevice.cpp"]
    subprocess.run([compiler, "-std=c++17", "-Wall", "-Wextra",
                    *[arg for path in includes for arg in ("-I", str(path))],
                    *map(str, sources), "-o", str(executable)], check=True)
    subprocess.run([str(executable)], check=True, timeout=10)


def test_dependency_edits_are_rejected_and_bound_into_firmware(tmp_path, monkeypatch):
    paths = set(build_firmware.source_input_paths(build_firmware.load_manifest()))
    assert LIBS / "Adafruit_GPS/src/Adafruit_GNSS.cpp" in paths
    assert LIBS / "Adafruit_BMP280_Library/Adafruit_BMP280.cpp" in paths
    shutil.copytree(LIBS, tmp_path / "libraries")
    monkeypatch.setattr(build_firmware, "LIBRARIES", tmp_path / "libraries")
    changed = tmp_path / "libraries/Adafruit_BMP280_Library/Adafruit_BMP280.cpp"
    changed.write_text(changed.read_text() + "\n// changed\n")
    with pytest.raises(build_firmware.BuildError, match="library bytes differ"):
        build_firmware.vendored_library_paths()
