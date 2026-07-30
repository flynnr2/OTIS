from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


FIRMWARE = Path("firmware/arduino/otis_nano_rp2040_connect")
HELPER = FIRMWARE / "otis_pps_count_boundary.h"


def _compiler() -> str:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is not available")
    return compiler


def test_snapshot_and_sequence_wrap_validity_and_control_gating(
    tmp_path: Path,
) -> None:
    source = tmp_path / "pps_count_boundary_check.cpp"
    binary = tmp_path / "pps_count_boundary_check"
    source.write_text(
        textwrap.dedent(
            f"""
            #include <assert.h>
            #include <stdint.h>
            #include "{HELPER}"

            int main(void) {{
              OtisCounterSnapshotDelta ordinary =
                  otis_counter_snapshot_delta_u32(100u, 125u, 1000u);
              assert(ordinary.valid && ordinary.count == 25u);
              assert(!ordinary.wrap_handled && !ordinary.wrap_ambiguous);

              OtisCounterSnapshotDelta wrapped =
                  otis_counter_snapshot_delta_u32(
                      0xfffffff0u, 0x00000010u, 1000u);
              assert(wrapped.valid && wrapped.count == 32u);
              assert(wrapped.wrap_handled && !wrapped.wrap_ambiguous);

              OtisCounterSnapshotDelta ambiguous =
                  otis_counter_snapshot_delta_u32(
                      0xfffffff0u, 0x00001000u, 1000u);
              assert(!ambiguous.valid && ambiguous.wrap_ambiguous);

              assert(otis_boundary_sequence_relation(41u, 42u) ==
                     OtisBoundarySequenceRelation::Continuous);
              assert(otis_boundary_sequence_relation(
                         0xffffffffu, 0u) ==
                     OtisBoundarySequenceRelation::Continuous);
              assert(otis_boundary_sequence_relation(42u, 42u) ==
                     OtisBoundarySequenceRelation::Duplicate);
              assert(otis_boundary_sequence_relation(42u, 44u) ==
                     OtisBoundarySequenceRelation::Gap);

              OtisPpsCountWindowValidity clean =
                  otis_pps_count_window_validity(
                      true, true,
                      OtisBoundarySequenceRelation::Continuous,
                      OTIS_PPS_APERTURE_NONE, true, true);
              assert(clean.control_eligible);

              OtisPpsCountWindowValidity unqualified =
                  otis_pps_count_window_validity(
                      true, true,
                      OtisBoundarySequenceRelation::Continuous,
                      OTIS_PPS_APERTURE_NONE, false, true);
              assert(!unqualified.control_eligible);
              assert(unqualified.reference_interval_valid);
              assert(unqualified.counter_window_valid);

              // Synthetic regression: a nominal timestamp interval and a
              // nonzero partial count cannot overcome explicit aperture
              // provenance. No frequency threshold participates here.
              const uint32_t observed_partial_count = 5437639u;
              assert(observed_partial_count > 0u);
              OtisPpsCountWindowValidity partial =
                  otis_pps_count_window_validity(
                      true, true,
                      OtisBoundarySequenceRelation::Continuous,
                      OTIS_PPS_APERTURE_PHYSICAL_APERTURE_INCOMPLETE,
                      true, true);
              assert(!partial.counter_window_valid);
              assert(!partial.control_eligible);

              OtisPpsCountWindowValidity gap =
                  otis_pps_count_window_validity(
                      true, true, OtisBoundarySequenceRelation::Gap,
                      OTIS_PPS_APERTURE_OBSERVATION_OVERFLOW, true, true);
              assert(!gap.observation_pair_valid);
              assert(!gap.fifo_continuous);
              assert(!gap.control_eligible);
              return 0;
            }}
            """
        ),
        encoding="utf-8",
    )
    subprocess.run(
        [
            _compiler(),
            "-std=c++17",
            f"-I{Path.cwd()}",
            str(source),
            "-o",
            str(binary),
        ],
        check=True,
    )
    subprocess.run([str(binary)], check=True)


def test_boundary_ring_overflow_is_counted_and_latched(
    tmp_path: Path,
) -> None:
    (tmp_path / "Arduino.h").write_text(
        """
#ifndef ARDUINO_H
#define ARDUINO_H
inline void noInterrupts(void) {}
inline void interrupts(void) {}
#endif
""",
        encoding="utf-8",
    )
    source = tmp_path / "pps_count_boundary_ring_check.cpp"
    binary = tmp_path / "pps_count_boundary_ring_check"
    source.write_text(
        """
#include <assert.h>
#include "otis_pps_count_boundary_ring.h"

static OtisPpsCountBoundaryObservation observation(uint32_t sequence) {
  return {sequence, (uint64_t)sequence * 16000000ull, 10000000u, 0u, 0u};
}

int main(void) {
  otis_pps_count_boundary_ring_reset();
  assert(otis_pps_count_boundary_ring_capacity() == 7u);
  for (uint32_t sequence = 0u; sequence < 7u; ++sequence) {
    assert(otis_pps_count_boundary_ring_push_from_isr(
        observation(sequence)));
  }
  assert(!otis_pps_count_boundary_ring_push_from_isr(observation(7u)));
  assert(otis_pps_count_boundary_ring_dropped_count() == 1u);

  OtisPpsCountBoundaryObservation popped = {};
  assert(otis_pps_count_boundary_ring_pop(&popped));
  assert(popped.sequence == 0u);
  assert(otis_pps_count_boundary_ring_push_from_isr(observation(8u)));

  while (otis_pps_count_boundary_ring_pop(&popped)) {
  }
  assert(popped.sequence == 8u);
  assert((popped.aperture_flags &
          OTIS_PPS_APERTURE_OBSERVATION_OVERFLOW) != 0u);
  assert(otis_pps_count_boundary_ring_depth() == 0u);
  return 0;
}
""",
        encoding="utf-8",
    )
    subprocess.run(
        [
            _compiler(),
            "-std=c++17",
            "-I",
            str(tmp_path),
            "-I",
            str(FIRMWARE),
            str(source),
            str(FIRMWARE / "otis_pps_count_boundary_ring.cpp"),
            "-o",
            str(binary),
        ],
        check=True,
    )
    subprocess.run([str(binary)], check=True)


def test_irq_critical_path_is_bounded_and_reason_contract_is_explicit() -> None:
    source = (FIRMWARE / "otis_count_observation.cpp").read_text(
        encoding="utf-8"
    )
    irq_source = (FIRMWARE / "otis_capture_irq.cpp").read_text(
        encoding="utf-8"
    )
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    start = source.index("void capture_pps_count_boundary_from_isr(")
    end = source.index("#endif", start)
    handler = source[start:end]
    for forbidden in (
        "_blocking",
        "emit_",
        "Serial",
        "malloc",
        "new ",
        "delay(",
        "frequency_count",
    ):
        assert forbidden not in handler
    assert handler.index(
        "stop_and_sample_h1_pio_counter_from_pps_isr"
    ) < handler.index("start_h1_pio_counter_from_pps_isr")
    assert handler.index(
        "start_h1_pio_counter_from_pps_isr"
    ) < handler.index("otis_pps_count_boundary_ring_push_from_isr")
    irq_start = irq_source.index("void handle_capture_edge(void)")
    irq_end = irq_source.index("void handle_tcxo_observation_edge", irq_start)
    irq_handler = irq_source[irq_start:irq_end]
    assert irq_handler.index("pps_count_boundary_handler(") < irq_handler.index(
        "digitalRead("
    )

    foreground_start = source.index(
        "bool otis_count_observation_on_pps_boundary("
    )
    foreground_end = source.index(
        "bool otis_count_observation_service(", foreground_start
    )
    foreground = source[foreground_start:foreground_end]
    assert "!h1_pio_long_gate.initialized || observation" not in foreground
    assert "OTIS_FLAG_GATE_INCOMPLETE" in sketch[
        sketch.index("void emit_pps_count_boundary(") :
        sketch.index("void drain_pps_count_boundary_ring(")
    ]

    required_reasons = {
        "boundary_capture_unavailable",
        "boundary_sequence_gap",
        "boundary_sequence_duplicate",
        "boundary_observation_overflow",
        "counter_snapshot_invalid",
        "counter_wrap_handled",
        "counter_wrap_ambiguous",
        "physical_aperture_incomplete",
        "reference_missing_pps",
        "reference_pps_duplicate",
        "reference_pps_short_interval",
        "reference_pps_long_interval",
        "reference_previous_boundary_invalid",
        "count_saturated",
        "count_zero",
    }
    for reason in required_reasons:
        assert f'"{reason}"' in source


def test_resource_and_telemetry_contract_name_boundary_ownership() -> None:
    registry = (FIRMWARE / "otis_resource_registry.cpp").read_text(
        encoding="utf-8"
    )
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    config = (FIRMWARE / "otis_config.h").read_text(encoding="utf-8")

    assert '"pps_reference_and_count_boundary_irq"' in registry
    assert '"pps_gpio_irq"' in sketch
    assert '"pps_isr_stop_sample_restart_v1"' in sketch
    assert '"config_snapshot", "begin"' in sketch
    assert '"config_snapshot", "end"' in sketch
    assert "OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED 0" in config
    assert "PPS_GATED_RATIO requires the GPIO IRQ capture backend" in config
