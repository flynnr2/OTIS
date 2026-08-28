from pathlib import Path
import json


ROOT = Path(__file__).resolve().parents[1]
SKETCH = ROOT / "firmware" / "arduino" / "otis_nano_rp2040_connect"


def test_d9_output_has_one_fixed_gpin0_integer_one_path() -> None:
    source = (SKETCH / "otis_forwarded_clock_output.cpp").read_text()
    assert "CLOCKS_CLK_GPOUT0_CTRL_AUXSRC_VALUE_CLKSRC_GPIN0" in source
    assert "constexpr uint32_t kIntegerDivider = 1u" in source
    assert "constexpr uint32_t kFractionalDivider = 0u" in source
    assert "clock_gpio_init_int_frac16" in source
    assert "clk_sys" not in source
    assert "clk_ref" not in source
    assert "clk_peri" not in source


def test_d9_output_is_compile_time_selected_and_d6_cannot_select_it() -> None:
    config = (SKETCH / "otis_config.h").read_text()
    assert "OTIS_ENABLE_FORWARDED_D9_OUTPUT" in config
    assert "OTIS_ENABLE_FORWARDED_D6_MONITOR && !OTIS_ENABLE_FORWARDED_D9_OUTPUT" in config
    assert "compile-time" in config


def test_d9_profile_keeps_control_disabled_and_uses_115200_target() -> None:
    matrix = json.loads((ROOT / "firmware" / "arduino" / "firmware_matrix.json").read_text())
    profile = next(item for item in matrix["profiles"] if item["id"] == "d9_forwarded_output_no_control")
    defines = profile["defines"]
    assert defines["OTIS_ENABLE_FORWARDED_D9_OUTPUT"] == "1"
    assert defines["OTIS_ENABLE_FORWARDED_D6_MONITOR"] == "0"
    assert defines["OTIS_ENABLE_CX317_BOUNDED_ACTIVE"] == "0"
    assert defines["OTIS_ENABLE_CX322_DIRECT_HYBRID"] == "0"
    assert defines["OTIS_GNSS_UART_BAUD"] == "115200u"
