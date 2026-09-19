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
                      otis_down_counter_snapshot_delta_u32(125u, 100u, 1000u);
              assert(ordinary.valid && ordinary.count == 25u);
              assert(!ordinary.wrap_handled && !ordinary.wrap_ambiguous);

                  OtisCounterSnapshotDelta wrapped =
                      otis_down_counter_snapshot_delta_u32(
                          0x00000010u, 0xfffffff0u, 1000u);
              assert(wrapped.valid && wrapped.count == 32u);
              assert(wrapped.wrap_handled && !wrapped.wrap_ambiguous);

                  OtisCounterSnapshotDelta ambiguous =
                      otis_down_counter_snapshot_delta_u32(
                          0x00001000u, 0xfffffff0u, 1000u);
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
                      OTIS_PPS_APERTURE_NONE, true);
              assert(clean.control_eligible);

              OtisPpsCountWindowValidity otherwise_inhibited =
                  otis_pps_count_window_validity(
                      true, true,
                      OtisBoundarySequenceRelation::Continuous,
                      OTIS_PPS_APERTURE_NONE, false);
              assert(!otherwise_inhibited.control_eligible);
              assert(otherwise_inhibited.reference_interval_valid);
              assert(otherwise_inhibited.counter_window_valid);

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
                      true);
              assert(!partial.counter_window_valid);
              assert(!partial.control_eligible);

              OtisPpsCountWindowValidity gap =
                  otis_pps_count_window_validity(
                      true, true, OtisBoundarySequenceRelation::Gap,
                      OTIS_PPS_APERTURE_OBSERVATION_OVERFLOW, true);
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



def test_no_independent_gpio_pairing_or_automatic_rearm():
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text()
    drain = sketch.split("void drain_reference_snapshots(void)", 1)[1].split("void emit_build_provenance_status", 1)[0]
    assert "otis_pps_snapshot_backend_pop" in drain
    assert "otis_reference_boundary(snapshot)" in drain
    assert "otis_pps_snapshot_backend_rearm" not in sketch
    assert "OtisPpsSnapshotAssociationGuard" not in HELPER.read_text()
    for retired in ("otis_capture_irq", "otis_capture_ring", "otis_pps_count_boundary_ring"):
        assert retired not in sketch
    assert "snapshot.timestamp_uncertainty_ticks" in drain
    assert "emit_pps_count_boundary(observation, snapshot.status, first_consumption_ticks)" in drain
