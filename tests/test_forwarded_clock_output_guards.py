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
    assert ">> CLOCKS_CLK_GPOUT0_CTRL_AUXSRC_LSB" in source
    assert "CLOCKS_CLK_GPOUT0_DIV_INT_BITS" in source
    assert ">>\n      CLOCKS_CLK_GPOUT0_DIV_INT_LSB" in source
    assert "CLOCKS_CLK_GPOUT0_DIV_FRAC_BITS" in source
    assert ">>\n      CLOCKS_CLK_GPOUT0_DIV_FRAC_LSB" in source
    assert "div >> 16u" not in source
    assert "clk_sys" not in source
    assert "clk_ref" not in source
    assert "clk_peri" not in source
    assert "GPIO_DRIVE_STRENGTH_2MA" in source
    assert "GPIO_SLEW_RATE_SLOW" in source
    assert "clock_stop(clk_gpout0)" in source
    assert "invalid_or_transitioning_runtime_readback_contradiction" in source


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
    assert defines["OTIS_ENABLE_CX317_I_ONLY_PREVIEW"] == "0"
    assert defines["OTIS_ENABLE_DUAL_CORE_PARTITION"] == "1"
    assert defines["OTIS_ENABLE_D9_D6_READINESS_PROFILE"] == "1"
    assert defines["OTIS_GNSS_UART_BAUD"] == "115200u"


def test_exact_d6_qualification_profile_is_non_actuating() -> None:
    matrix = json.loads((ROOT / "firmware" / "arduino" / "firmware_matrix.json").read_text())
    profile = next(item for item in matrix["profiles"] if item["id"] == "d9_d6_forwarded_output_no_control")
    defines = profile["defines"]
    assert defines["OTIS_ENABLE_FORWARDED_D9_OUTPUT"] == "1"
    assert defines["OTIS_ENABLE_FORWARDED_D6_MONITOR"] == "1"
    assert defines["OTIS_ENABLE_CX317_BOUNDED_ACTIVE"] == "0"
    assert defines["OTIS_ENABLE_CX317_I_ONLY_PREVIEW"] == "0"
    assert defines["OTIS_ENABLE_DUAL_CORE_PARTITION"] == "1"
    assert defines["OTIS_ENABLE_D9_D6_READINESS_PROFILE"] == "1"
    assert defines["OTIS_ENABLE_DAC_AD5693R"] == "0"
    assert defines["OTIS_ENABLE_GNSS_RECEIVER"] == "0"


def test_three_readiness_strata_change_only_output_and_monitor_selectors() -> None:
    matrix = json.loads((ROOT / "firmware" / "arduino" / "firmware_matrix.json").read_text())
    profiles = {item["id"]: item["defines"] for item in matrix["profiles"]}
    baseline = profiles["d9_disabled_no_control_baseline"]
    output = profiles["d9_forwarded_output_no_control"]
    monitor = profiles["d9_d6_forwarded_output_no_control"]
    variable = {"OTIS_ENABLE_FORWARDED_D9_OUTPUT", "OTIS_ENABLE_FORWARDED_D6_MONITOR"}
    assert {key: value for key, value in output.items() if key not in variable} == {
        key: value for key, value in baseline.items() if key not in variable
    }
    assert {key: value for key, value in monitor.items() if key not in variable} == {
        key: value for key, value in baseline.items() if key not in variable
    }
    assert (baseline["OTIS_ENABLE_FORWARDED_D9_OUTPUT"], baseline["OTIS_ENABLE_FORWARDED_D6_MONITOR"]) == ("0", "0")
    assert (output["OTIS_ENABLE_FORWARDED_D9_OUTPUT"], output["OTIS_ENABLE_FORWARDED_D6_MONITOR"]) == ("1", "0")
    assert (monitor["OTIS_ENABLE_FORWARDED_D9_OUTPUT"], monitor["OTIS_ENABLE_FORWARDED_D6_MONITOR"]) == ("1", "1")


def test_d9_frequency_only_profile_preserves_law_but_has_distinct_24h_envelope() -> None:
    matrix = json.loads((ROOT / "firmware" / "arduino" / "firmware_matrix.json").read_text())
    profiles = {item["id"]: item["defines"] for item in matrix["profiles"]}
    candidate = profiles["d9_d6_frequency_only_lower"]
    baseline = profiles["cx319_tight_lower"]
    excluded = {
        "OTIS_ENABLE_FORWARDED_D9_OUTPUT",
        "OTIS_ENABLE_FORWARDED_D6_MONITOR",
        "OTIS_CX317_ACTIVE_CAMPAIGN",
        "OTIS_CX317_ACTIVE_CORRECTION_LIMIT",
        "OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES",
    }
    assert {key: value for key, value in candidate.items() if key not in excluded} == {
        key: value for key, value in baseline.items() if key not in excluded
    }
    assert candidate["OTIS_ENABLE_FORWARDED_D9_OUTPUT"] == "1"
    assert candidate["OTIS_ENABLE_FORWARDED_D6_MONITOR"] == "1"
    assert candidate.get("OTIS_ENABLE_CX320_ACTIVE_HYBRID", "0") == "0"
    assert candidate.get("OTIS_ENABLE_CX321_ACTIVE_HYBRID", "0") == "0"
    assert candidate.get("OTIS_ENABLE_CX322_DIRECT_HYBRID", "0") == "0"
    assert candidate["OTIS_CX317_ACTIVE_CAMPAIGN"] == (
        "OTIS_CX317_ACTIVE_CAMPAIGN_D9_D6_FREQUENCY_ONLY_ENDURANCE"
    )
    assert candidate["OTIS_CX317_ACTIVE_CORRECTION_LIMIT"] == "48u"
    assert candidate["OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES"] == "1008u"

    config = (SKETCH / "otis_config.h").read_text()
    live = (SKETCH / "otis_cx317_active_live.cpp").read_text()
    assert "OTIS_CX317_ACTIVE_CAMPAIGN_D9_D6_FREQUENCY_ONLY_ENDURANCE 17" in config
    assert "OTIS_CX317_ACTIVE_CORRECTION_LIMIT != 48u" in config
    assert "OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES != 1008u" in config
    assert 'kRunIdentity[] = "d9_d6_frequency_only_endurance:1"' in live
    assert 'kExpectedProfile[] = "d9_d6_frequency_only_lower"' in live


def test_d9_d6_72h_profile_changes_only_sustained_authority_envelope() -> None:
    matrix = json.loads((ROOT / "firmware" / "arduino" / "firmware_matrix.json").read_text())
    profiles = {item["id"]: item["defines"] for item in matrix["profiles"]}
    baseline = profiles["cx322_d9_d6_integration_engineering"]
    candidate = profiles["cx322_d9_d6_72h_sustained_engineering"]
    envelope = {
        "OTIS_CX317_ACTIVE_CAMPAIGN",
        "OTIS_CX317_ACTIVE_CORRECTION_LIMIT",
        "OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES",
        "OTIS_ACTIVE_HYBRID_MAX_AUTOMATIC_APPLICATIONS",
        "OTIS_ACTIVE_HYBRID_MAX_CUMULATIVE_MOVEMENT_CODES",
    }
    assert {key: value for key, value in candidate.items() if key not in envelope} == {
        key: value for key, value in baseline.items() if key not in envelope
    }
    assert candidate["OTIS_CX317_ACTIVE_CAMPAIGN"] == (
        "OTIS_CX317_ACTIVE_CAMPAIGN_D9_D6_72H_SUSTAINED_HYBRID"
    )
    assert candidate["OTIS_CX317_ACTIVE_CORRECTION_LIMIT"] == "144u"
    assert candidate["OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES"] == "3024u"
    assert candidate["OTIS_ACTIVE_HYBRID_MAX_AUTOMATIC_APPLICATIONS"] == "144u"
    assert candidate["OTIS_ACTIVE_HYBRID_MAX_CUMULATIVE_MOVEMENT_CODES"] == "3024u"
    assert candidate.get("OTIS_ENABLE_SUSTAINED_HYBRID_REGULATION", "0") == "0"
    assert candidate.get("OTIS_ACTIVE_HYBRID_ENABLE_REVERSAL_CHALLENGE", "0") == "0"

    config = (SKETCH / "otis_config.h").read_text()
    policy = (SKETCH / "otis_active_hybrid_policy_engine.cpp").read_text()
    live = (SKETCH / "otis_cx317_active_live.cpp").read_text()
    assert "OTIS_CX317_ACTIVE_CAMPAIGN_D9_D6_72H_SUSTAINED_HYBRID 18" in config
    assert "OTIS_ACTIVE_HYBRID_MAX_CUMULATIVE_MOVEMENT_CODES != 3024u" in config
    assert "OTIS_ACTIVE_HYBRID_MAX_CUMULATIVE_MOVEMENT_CODES" in policy
    assert 'kRunIdentity[] = "cx322_d9_d6_72h_sustained_engineering:1"' in live
    assert 'kExpectedProfile[] = "cx322_d9_d6_72h_sustained_engineering"' in live


def test_d6_monitor_is_initialized_and_serviced_after_authoritative_d8_pair() -> None:
    sketch = (SKETCH / "otis_nano_rp2040_connect.ino").read_text()
    setup1 = sketch.split("void setup1()", 1)[1].split("void loop1()", 1)[0]
    assert setup1.index("boot_phase_timer_init();") < setup1.index(
        "boot_phase_forwarded_output_init();"
    ) < setup1.index("boot_phase_forwarded_monitor_init();") < setup1.index(
        "boot_phase_pps_input_init();"
    )
    drain = sketch.split("void drain_pps_count_boundary_ring(void)", 1)[1].split(
        "void emit_build_provenance_status", 1
    )[0]
    assert drain.index("emit_pps_count_boundary(observation, snapshot.status);") < drain.index(
        "service_forwarded_clock_monitor_boundary(observation);"
    )
    assert "otis_dual_core_publish_monitor_observation" in sketch
    assert "otis_dual_core_take_monitor_observation" in sketch


def test_d6_resource_binding_failure_is_explicitly_fail_local() -> None:
    registry = (SKETCH / "otis_resource_registry.cpp").read_text()
    assert "owner_is_fail_local_diagnostic" in registry
    assert "OTIS_OWNER_FORWARDED_CLOCK_MONITOR" in registry
    complete = registry.split("bool otis_resource_registry_complete", 1)[1].split(
        "uint8_t otis_resource_registry_claim_count", 1
    )[0]
    assert "!owner_is_fail_local_diagnostic(registry.claims[i].owner)" in complete
