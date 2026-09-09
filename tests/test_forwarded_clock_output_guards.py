from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKETCH = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def test_d9_output_has_one_fixed_gpin0_integer_one_path() -> None:
    source = (SKETCH / "otis_forwarded_clock_output.cpp").read_text()
    assert "CLOCKS_CLK_GPOUT0_CTRL_AUXSRC_VALUE_CLKSRC_GPIN0" in source
    assert "constexpr uint32_t kIntegerDivider = 1u" in source
    assert "constexpr uint32_t kFractionalDivider = 0u" in source
    assert "clock_gpio_init_int_frac16" in source
    assert "clk_sys" not in source
    assert "clk_ref" not in source
    assert "clk_peri" not in source
    assert "GPIO_DRIVE_STRENGTH_2MA" in source
    assert "GPIO_SLEW_RATE_SLOW" in source
    assert "clock_stop(clk_gpout0)" in source
    assert "invalid_or_transitioning_runtime_readback_contradiction" in source


def test_d9_and_d6_are_fixed_on_and_have_zero_control_authority() -> None:
    config = (SKETCH / "otis_config.h").read_text()
    assert "OTIS_ENABLE_FORWARDED_D9_OUTPUT" not in config
    assert "OTIS_ENABLE_FORWARDED_D6_MONITOR" not in config

    sketch = (SKETCH / "otis_nano_rp2040_connect.ino").read_text()
    setup = sketch.split("void setup1()", 1)[1].split("void loop1()", 1)[0]
    assert setup.index("boot_phase_forwarded_output_init();") < setup.index(
        "boot_phase_forwarded_monitor_init();"
    )
    assert setup.index("boot_phase_forwarded_monitor_init();") < setup.index(
        "boot_phase_pps_input_init();"
    )


def test_d6_resource_binding_failure_is_explicitly_fail_local() -> None:
    registry = (SKETCH / "otis_resource_registry.cpp").read_text()
    assert "owner_is_fail_local_diagnostic" in registry
    assert "OTIS_OWNER_FORWARDED_CLOCK_MONITOR" in registry
    completion = registry.split("bool otis_resource_registry_complete", 1)[1].split(
        "uint8_t otis_resource_registry_claim_count", 1
    )[0]
    assert "!owner_is_fail_local_diagnostic(registry.claims[i].owner)" in completion
