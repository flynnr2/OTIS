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
    assert setup.index("boot_phase_early_init()") < setup.index(
        "otisBootSafeModeRequested()"
    )
    early_start = source.index("void boot_phase_early_init(void)")
    early_end = source.index("void boot_phase_clocks_init(void)", early_start)
    assert "otis_resource_registry_begin()" in source[early_start:early_end]

    run_mode_start = source.index("void boot_phase_run_mode(void)")
    run_mode_end = source.index("void service_loopback_output(void)", run_mode_start)
    run_mode = source[run_mode_start:run_mode_end]
    assert "setup_mode();" not in run_mode
    assert run_mode.index("otis_boot_capability_mark_run_mode(") < run_mode.index(
        "enter_boot_phase(BootPhase::RunMode)"
    )
    assert run_mode.index("enter_boot_phase(BootPhase::RunMode)") < run_mode.index(
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


def test_pps_gated_counter_associates_independent_ref_with_pio_authority() -> None:
    count_source = (FIRMWARE / "otis_count_observation.cpp").read_text(
        encoding="utf-8"
    )
    sketch_source = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )

    assert "digitalRead(OTIS_PIN_PPS_REFERENCE)" not in count_source
    assert "pps_rising_edge" not in count_source
    assert "otis_pps_snapshot_backend_begin(" in count_source
    assert "otis_count_observation_on_pps_boundary(" in count_source

    emit_start = sketch_source.index("void emit_pps_count_boundary(")
    emit_end = sketch_source.index(
        "void drain_pps_count_boundary_ring(", emit_start
    )
    emit_body = sketch_source[emit_start:emit_end]
    assert "otis_count_observation_on_pps_boundary(" in emit_body
    assert "otis_capture_ticks_now()" not in emit_body

    drain_start = sketch_source.index("void drain_pps_count_boundary_ring(")
    drain_end = sketch_source.index("void emit_common_boot_status(", drain_start)
    drain_body = sketch_source[drain_start:drain_end]
    assert "otis_pps_snapshot_backend_pop" in drain_body
    assert "otis_emit_pps_snapshot" in drain_body
    assert "another_reference_waiting" in drain_body

    loop_body = sketch_source[sketch_source.index("void loop()") :]
    assert loop_body.index("otis_capture_backend_service()") < loop_body.index(
        "service_tcxo_gate()"
    )
    assert loop_body.index("drain_pps_count_boundary_ring()") < loop_body.index(
        "service_serial_commands()"
    )
    assert loop_body.index("drain_capture_ring()") < loop_body.index(
        "service_tcxo_gate()"
    )

    reference_handler_start = count_source.index(
        "bool otis_count_observation_on_pps_boundary("
    )
    reference_handler_end = count_source.index(
        "bool otis_count_observation_service(", reference_handler_start
    )
    reference_handler = count_source[reference_handler_start:reference_handler_end]
    assert "previous.capture_flags | observation->capture_flags" in reference_handler
    assert "stop_h1_pio_long_gate_counter" not in reference_handler
    assert "start_h1_pio_long_gate_counter" not in reference_handler


def test_irq_constructs_one_captured_event_for_diagnostics_and_ref() -> None:
    irq_source = (FIRMWARE / "otis_capture_irq.cpp").read_text(encoding="utf-8")
    ring_source = (FIRMWARE / "otis_capture_ring.cpp").read_text(encoding="utf-8")

    handler_start = irq_source.index("void handle_capture_edge(void)")
    handler_end = irq_source.index(
        "void handle_tcxo_observation_edge(void)", handler_start
    )
    handler = irq_source[handler_start:handler_end]
    assert handler.count("otis_capture_ticks_now_from_isr()") == 1
    assert handler.count("gpio_get(capture_gpio)") == 1
    assert "const OtisCapturedEdge captured_event" in handler
    assert "pps_count_boundary_handler" not in handler
    assert "pio_sm_" not in handler
    assert "dma_" not in handler
    assert "otis_capture_ring_push_from_isr(captured_event)" in handler
    assert "d14_last_raw_timestamp = timestamp" not in handler
    assert "d14_last_accepted_timestamp = timestamp" not in handler
    foreground_start = irq_source.index(
        "void otis_capture_irq_process_reference_foreground("
    )
    foreground = irq_source[foreground_start:]
    assert "d14_last_raw_timestamp = record.timestamp_ticks" in foreground
    assert "d14_last_accepted_timestamp = record.timestamp_ticks" in foreground
    assert "otis_capture_ticks_now()" not in ring_source


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
