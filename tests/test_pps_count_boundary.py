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
  return {1u, sequence, sequence,
          (uint64_t)sequence * 16000000ull,
          0xffffffffu - sequence, 0u, 0u, 0u};
}

int main(void) {
  otis_pps_count_boundary_ring_reset();
  uint32_t capacity = otis_pps_count_boundary_ring_capacity();
  assert(capacity >= 7u);
  for (uint32_t sequence = 0u; sequence < capacity; ++sequence) {
    assert(otis_pps_count_boundary_ring_push_from_isr(
        observation(sequence)));
  }
  assert(!otis_pps_count_boundary_ring_push_from_isr(observation(capacity)));
  assert(otis_pps_count_boundary_ring_dropped_count() == 1u);

  OtisPpsCountBoundaryObservation peeked = {};
  assert(otis_pps_count_boundary_ring_peek(&peeked));
  assert(peeked.sequence == 0u);
  assert(otis_pps_count_boundary_ring_depth() == capacity);

  OtisPpsCountBoundaryObservation popped = {};
  assert(otis_pps_count_boundary_ring_pop(&popped));
  assert(popped.sequence == 0u);
  assert(otis_pps_count_boundary_ring_push_from_isr(
      observation(capacity + 1u)));

  while (otis_pps_count_boundary_ring_pop(&popped)) {
  }
  assert(popped.sequence == capacity + 1u);
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


def test_pio_boundary_path_is_hardware_owned_and_reason_contract_is_explicit() -> None:
    source = (FIRMWARE / "otis_count_observation.cpp").read_text(
        encoding="utf-8"
    )
    irq_source = (FIRMWARE / "otis_capture_irq.cpp").read_text(
        encoding="utf-8"
    )
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    backend = (FIRMWARE / "otis_pps_snapshot_backend.cpp").read_text(
        encoding="utf-8"
    )
    assert "sm_config_set_jmp_pin(&config, OTIS_PIN_PPS_REFERENCE)" in backend
    assert "sm_config_set_in_pins(&config, OTIS_GPIO_OSC_OBSERVATION)" in backend
    assert "sm_config_set_in_shift(&config, true, true, 32u)" in backend
    assert "stop_and_sample_h1_pio_counter_from_pps_isr" not in source
    irq_start = irq_source.index("void handle_capture_edge(void)")
    irq_end = irq_source.index("void handle_tcxo_observation_edge", irq_start)
    irq_handler = irq_source[irq_start:irq_end]
    assert "pps_count_boundary_handler" not in irq_handler
    assert "pio_sm_" not in irq_handler
    assert "dma_" not in irq_handler

    foreground_start = source.index(
        "bool otis_count_observation_on_pps_boundary("
    )
    foreground_end = source.index(
        "bool otis_count_observation_service(", foreground_start
    )
    foreground = source[foreground_start:foreground_end]
    assert "!h1_pio_long_gate.initialized || observation" not in foreground
    assert "OTIS_FLAG_GATE_INCOMPLETE" in foreground

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


def test_association_loss_freezes_decision_local_backend_evidence_before_rearm() -> None:
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    drain_start = sketch.index("void drain_pps_count_boundary_ring(void)")
    drain = sketch[drain_start : sketch.index("void emit_build_provenance_status(void)", drain_start)]
    publish = "publish_dual_core_association_loss_decision("
    assert publish in drain
    assert "otis_pps_count_boundary_ring_peek(&next_reference)" in drain
    assert drain.index(publish) < drain.index("otis_count_observation_note_association_loss(")
    assert drain.index(publish) < drain.index("otis_pps_snapshot_backend_rearm()")
    assert drain.index(publish) < drain.index("otis_pps_count_boundary_ring_reset()")

    capsule = sketch[
        sketch.index("void publish_dual_core_association_loss_decision(") :
        sketch.index("#endif", sketch.index("void publish_dual_core_association_loss_decision("))
    ]
    for evidence in (
        '"ASL,1,',
        "pending_reference.reference_sequence",
        "pending_reference.pps_timestamp_ticks",
        "pending_age_ticks",
        "snapshot_stats.producer_ordinal",
        "snapshot_stats.consumer_ordinal",
        "snapshot_stats.backlog_depth",
        "snapshot_stats.fault_flags",
        "queue_stats.timing_progress.loop_sequence",
        "queue_stats.timing_progress.phase_enter_ticks",
        '"unread_snapshot_present_when_decision_made"',
        '"no_unread_snapshot_healthy_backend"',
    ):
        assert evidence in capsule

def test_resource_and_telemetry_contract_name_boundary_ownership() -> None:
    registry = (FIRMWARE / "otis_resource_registry.cpp").read_text(
        encoding="utf-8"
    )
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    config = (FIRMWARE / "otis_config.h").read_text(encoding="utf-8")

    assert '"pps_reference_observer_irq"' in registry
    assert '"pio_state_machine"' in sketch
    assert '"pio_wait_cumulative_snapshot_dma_v1"' in sketch
    assert '"config_snapshot", "begin"' in sketch
    assert '"config_snapshot", "end"' in sketch
    assert sketch.count("emit_build_provenance_status();") == 2
    assert "if (!config_query_provenance_emitted)" in sketch
    assert "config_query_provenance_emitted = true;" in sketch
    assert "OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED 0" in config
    assert "PPS_GATED_RATIO requires the GPIO IRQ backend for the independent D14 REF observer" in config
