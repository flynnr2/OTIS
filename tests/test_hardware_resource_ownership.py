from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest


FIRMWARE = Path("firmware/arduino/otis_nano_rp2040_connect")


def test_resource_collision_rules_cover_exact_and_ranged_resources(
    tmp_path: Path,
) -> None:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is not available")

    harness = tmp_path / "resource_registry_test.cpp"
    harness.write_text(
        """
#include <cassert>
#include "otis_resource_registry.h"

int main() {
  OtisResourceClaim gpio_a = {
      OtisResourceType::Gpio, 0, 20, 1, "owner_a", "role_a", true};
  OtisResourceClaim gpio_b = {
      OtisResourceType::Gpio, 0, 20, 1, "owner_b", "role_b", true};
  OtisResourceClaim irq = {
      OtisResourceType::GpioIrq, 0, 20, 1, "owner_b", "role_b", true};
  OtisResourceClaim pending = {
      OtisResourceType::Gpio, 0, kOtisResourceDynamicIndex, 1,
      "owner_c", "role_c", false};
  OtisResourceClaim pio_program_a = {
      OtisResourceType::PioInstructionMemory, 0, 0, 5,
      "owner_a", "program_a", true};
  OtisResourceClaim pio_program_adjacent = {
      OtisResourceType::PioInstructionMemory, 0, 5, 5,
      "owner_b", "program_b", true};
  OtisResourceClaim pio_program_overlap = {
      OtisResourceType::PioInstructionMemory, 0, 4, 5,
      "owner_c", "program_c", true};

  assert(otis_resource_claims_conflict(gpio_a, gpio_b));
  assert(!otis_resource_claims_conflict(gpio_a, irq));
  assert(!otis_resource_claims_conflict(gpio_a, pending));
  assert(!otis_resource_claims_conflict(
      pio_program_a, pio_program_adjacent));
  assert(otis_resource_claims_conflict(
      pio_program_a, pio_program_overlap));
  return 0;
}
""",
        encoding="utf-8",
    )
    executable = tmp_path / "resource_registry_test"
    subprocess.run(
        [
            compiler,
            "-std=c++11",
            "-I",
            str(FIRMWARE),
            str(harness),
            "-o",
            str(executable),
        ],
        check=True,
    )
    subprocess.run([str(executable)], check=True)


def test_registry_preflight_precedes_safe_mode_and_hardware_mode_setup() -> None:
    source = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    setup = source[source.index("void setup()") : source.index("void loop()")]
    assert setup.index("otis_resource_registry_begin()") < setup.index(
        "otisBootSafeModeRequested()"
    )

    run_mode_start = source.index("void boot_phase_run_mode(void)")
    run_mode_end = source.index("void service_loopback_output(void)", run_mode_start)
    run_mode = source[run_mode_start:run_mode_end]
    assert run_mode.index("setup_mode();") < run_mode.index(
        "emit_resource_ownership_status();"
    )
    assert run_mode.index("emit_resource_ownership_status();") < run_mode.index(
        "otisBootBreadcrumbMarkRunMode();"
    )
    loop = source[source.index("void loop()") :]
    assert loop.index("emit_protocol_banner_if_serial_ready();") < loop.index(
        "emit_resource_ownership_status();"
    )
    ownership_status_start = source.index(
        "void emit_resource_ownership_status(void)"
    )
    ownership_status_end = source.index(
        "void emit_protocol_banner_if_serial_ready(void)", ownership_status_start
    )
    ownership_status = source[ownership_status_start:ownership_status_end]
    assert "resource_ownership_status_emitted" in ownership_status
    assert "!otis_transport_ready()" in ownership_status


def test_pio_allocations_are_bound_to_the_registry() -> None:
    edge_source = (FIRMWARE / "otis_capture_pio.cpp").read_text(encoding="utf-8")
    count_source = (FIRMWARE / "otis_count_observation.cpp").read_text(
        encoding="utf-8"
    )

    for source, owner in (
        (edge_source, "OTIS_OWNER_EDGE_CAPTURE"),
        (count_source, "OTIS_OWNER_COUNT_OBSERVATION"),
    ):
        claim_index = source.index("pio_claim_unused_sm")
        bind_sm_index = source.index(
            "otis_resource_registry_bind_pio_state_machine", claim_index
        )
        bind_program_index = source.index(
            "otis_resource_registry_bind_pio_program", bind_sm_index
        )
        assert claim_index < bind_sm_index < bind_program_index
        assert owner in source[bind_sm_index:bind_program_index + 300]


def test_i2c_controller_has_one_initializer() -> None:
    direct_initializers = []
    for path in FIRMWARE.glob("*.cpp"):
        if "Wire.begin();" in path.read_text(encoding="utf-8"):
            direct_initializers.append(path.name)

    assert direct_initializers == ["otis_i2c_bus.cpp"]
    assert "otis_i2c_bus_begin()" in (
        FIRMWARE / "otis_dac_ad5693r.cpp"
    ).read_text(encoding="utf-8")
    assert "otis_i2c_bus_begin()" in (
        FIRMWARE / "otis_env_sensors.cpp"
    ).read_text(encoding="utf-8")


def test_pps_gated_counter_is_a_read_only_client_of_d14() -> None:
    source = (FIRMWARE / "otis_count_observation.cpp").read_text(encoding="utf-8")
    pps_backend_start = source.index(
        "#elif OTIS_TCXO_COUNTER_BACKEND == "
        "OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO"
    )
    pps_backend_end = source.index(
        "#elif OTIS_TCXO_COUNTER_BACKEND == OTIS_TCXO_COUNTER_BACKEND_GPIO_IRQ",
        pps_backend_start,
    )
    pps_backend = source[pps_backend_start:pps_backend_end]

    assert "digitalRead(OTIS_PIN_PPS_REFERENCE)" in pps_backend
    assert "pinMode(OTIS_PIN_PPS_REFERENCE" not in pps_backend


def test_all_requested_resource_classes_have_diagnostics() -> None:
    source = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    for key in (
        "gpio_claim_count",
        "irq_claim_count",
        "pio_sm_claim_count",
        "pio_imem_claim_count",
        "dma_claim_count",
        "timer_claim_count",
        "clock_claim_count",
    ):
        assert f'"{key}"' in source

    assert '"conflict_count"' in source
    assert '"binding_failure_count"' in source
    assert '"complete"' in source
