from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SKETCH = ROOT / "firmware" / "arduino" / "otis_nano_rp2040_connect"


def test_monitor_reuses_snapshot_program_on_d6_with_d14_as_read_only_condition() -> None:
    source = (SKETCH / "otis_forwarded_clock_monitor.cpp").read_text()

    assert '#include "otis_pps_snapshot.pio.h"' in source
    assert "OTIS_GPIO_FORWARDED_CLOCK_MONITOR" in source
    assert "sm_config_set_in_pins(&config, OTIS_GPIO_FORWARDED_CLOCK_MONITOR)" in source
    assert "sm_config_set_jmp_pin(&config, OTIS_PIN_PPS_REFERENCE)" in source
    assert "gpio_set_dir(OTIS_GPIO_FORWARDED_CLOCK_MONITOR, false)" in source
    assert "gpio_set_dir(OTIS_PIN_PPS_REFERENCE" not in source
    assert "gpio_set_function(OTIS_PIN_PPS_REFERENCE" not in source


def test_monitor_claims_independent_pio_resources_and_never_dma() -> None:
    source = (SKETCH / "otis_forwarded_clock_monitor.cpp").read_text()

    assert "pio_claim_unused_sm" in source
    assert "pio_add_program" in source
    assert "OTIS_OWNER_FORWARDED_CLOCK_MONITOR" in source
    assert "otis_resource_registry_bind_pio_state_machine" in source
    assert "otis_resource_registry_bind_pio_program" in source
    assert "dma_" not in source
    assert "hardware/dma.h" not in source


def test_monitor_service_drains_at_most_one_raw_word_per_reference_boundary() -> None:
    header = (SKETCH / "otis_forwarded_clock_monitor.h").read_text()
    source = (SKETCH / "otis_forwarded_clock_monitor.cpp").read_text()

    assert "otis_forwarded_clock_monitor_service(uint32_t reference_session," in header
    assert "Exactly one PIO FIFO word may be read per associated D14 boundary" in source
    body = source.split("bool otis_forwarded_clock_monitor_service(", 1)[1].split(
        "bool otis_forwarded_clock_monitor_read", 1
    )[0]
    assert body.count("pio_sm_get(monitor.pio, sm)") == 1
    assert "OTIS_FORWARDED_CLOCK_MONITOR_STATUS_FIFO_BACKLOG" in body


def test_monitor_contract_is_explicitly_diagnostic_only() -> None:
    header = (SKETCH / "otis_forwarded_clock_monitor.h").read_text()

    assert "diagnostic sidecar" in header
    assert "not an input to D14/D8" in header
    assert "control eligibility, or actuation" in header
    assert "reference_session" in header
    assert "reference_sequence" in header
