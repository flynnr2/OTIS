from __future__ import annotations

import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest


HELPER = Path(
    "firmware/arduino/otis_nano_rp2040_connect/otis_pps_gate_math.h"
)
FIRMWARE = Path("firmware/arduino/otis_nano_rp2040_connect")
WRAP_TICKS = (1 << 32) * 16


def _compile_and_run(tmp_path: Path, source: str) -> list[str]:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is not available")
    source_path = tmp_path / "pps_gate_math_check.cpp"
    binary_path = tmp_path / "pps_gate_math_check"
    source_path.write_text(source, encoding="utf-8")
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            f"-I{Path.cwd()}",
            str(source_path),
            "-o",
            str(binary_path),
        ],
        check=True,
    )
    return subprocess.check_output([str(binary_path)], text=True).splitlines()


def test_pps_boundary_assessment_covers_rollover_duplicate_intervals_and_flags(
    tmp_path: Path,
) -> None:
    source = textwrap.dedent(
        f"""
        #include <stdint.h>
        #include <stdio.h>
        #include "{HELPER}"

        int main(void) {{
          const uint64_t wrap = {WRAP_TICKS}ull;
          const uint64_t duplicate_maximum = 100000ull * 16ull;
          const uint64_t minimum = 800000ull * 16ull;
          const uint64_t maximum = 1200000ull * 16ull;
          const uint64_t opens[] = {{
              16000000ull,
              wrap - 4000000ull,
              16000000ull,
              16000000ull,
              16000000ull,
              16000000ull,
              16000000ull,
          }};
          const uint64_t closes[] = {{
              32000000ull,
              12000000ull,
              16800000ull,
              16000000ull,
              26000000ull,
              37000000ull,
              32000000ull,
          }};
          const uint32_t flags[] = {{
              OTIS_FLAG_TIMESTAMP_RECONSTRUCTED,
              OTIS_FLAG_TIMESTAMP_RECONSTRUCTED,
              OTIS_FLAG_TIMESTAMP_RECONSTRUCTED,
              OTIS_FLAG_TIMESTAMP_RECONSTRUCTED,
              OTIS_FLAG_TIMESTAMP_RECONSTRUCTED,
              OTIS_FLAG_TIMESTAMP_RECONSTRUCTED,
              OTIS_FLAG_CAPTURE_RING_OVERRUN,
          }};
          for (unsigned i = 0; i < 7; ++i) {{
            OtisPpsBoundaryAssessment result =
                otis_pps_gate_assess_boundary(
                    opens[i], closes[i], flags[i], duplicate_maximum,
                    minimum, maximum);
            printf("%d,%llu,%d\\n", result.valid ? 1 : 0,
                   (unsigned long long)result.interval_ticks,
                   (int)result.reason);
          }}
          return 0;
        }}
        """
    )
    rows = _compile_and_run(tmp_path, source)
    assert rows == [
        "1,16000000,0",  # nominal
        "1,16000000,0",  # nominal across timer rollover
        "0,800000,1",  # physically injectable 50 ms duplicate
        "0,0,1",  # identical-timestamp duplicate
        "0,10000000,2",  # short
        "0,21000000,3",  # long
        "0,16000000,4",  # otherwise-nominal flagged capture
    ]


def test_pps_backend_exposes_independent_validity_and_unavailable_uncertainty() -> None:
    source = (FIRMWARE / "otis_count_observation.cpp").read_text(
        encoding="utf-8"
    )
    for key in (
        "reference_validity",
        "reference_reason",
        "count_validity",
        "count_reason",
        "counter_aperture_uncertainty_ns",
        "reference_frequency_uncertainty_ppb",
    ):
        assert f'"{key}"' in source
    assert '"unavailable"' in source


def test_pps_backend_times_out_before_the_first_reference_and_preserves_raw_boundary() -> None:
    source = (FIRMWARE / "otis_count_observation.cpp").read_text(
        encoding="utf-8"
    )
    service = source[source.index("bool otis_count_observation_service(") :]
    assert "pps_gated_ratio.state == PpsGateState::Armed" in service
    assert "kReferenceReasonMissingPps" in service

    reference_start = source.index("bool otis_count_observation_on_reference(")
    reference_end = source.index(
        "bool otis_count_observation_service(", reference_start
    )
    reference = source[reference_start:reference_end]
    assert (
        "runtime_state->tcxo.last_gate_close_ticks = timestamp_ticks;"
        in reference
    )
    assert "otis_timer0_interval_ticks(" in reference


def test_pps_counter_restarts_before_reporting_and_inhibits_rejected_anchor() -> None:
    source = (FIRMWARE / "otis_count_observation.cpp").read_text(
        encoding="utf-8"
    )
    reference_start = source.index("bool otis_count_observation_on_reference(")
    reference_end = source.index(
        "bool otis_count_observation_service(", reference_start
    )
    reference = source[reference_start:reference_end]
    completed = reference[reference.index("uint32_t remaining =") :]
    assert completed.index("stop_h1_pio_long_gate_counter()") < completed.index(
        "start_h1_pio_long_gate_counter(timestamp_ticks)"
    )
    assert completed.index(
        "start_h1_pio_long_gate_counter(timestamp_ticks)"
    ) < completed.index("emit_count_observation(")
    assert "gate_open_inhibited = !raw_boundary.valid" in completed
    assert "OtisPpsBoundaryReason::PreviousBoundaryInvalid" in completed
    assert '"reference_previous_boundary_invalid"' in source


def test_phase4_live_adapter_uses_modular_pps_boundaries_and_separate_validity() -> None:
    source = (FIRMWARE / "otis_phase4_observe_preview.cpp").read_text(
        encoding="utf-8"
    )
    assert '#include "otis_timebase_math.h"' in source
    assert "const uint64_t gate_ticks = otis_timer0_interval_ticks(" in source
    assert (
        "OTIS_TCXO_COUNTER_BACKEND == "
        "OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO"
    ) in source
    assert "flags & OTIS_FLAG_REFERENCE_VALIDITY_SUSPECT" in source
