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
WRAP_TICKS = 1 << 32


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
          const uint64_t duplicate_maximum = 100000ull;
          const uint64_t minimum = 800000ull;
          const uint64_t maximum = 1200000ull;
          const uint64_t opens[] = {{
              1000000ull,
              wrap - 250000ull,
              1000000ull,
              1000000ull,
              1000000ull,
              1000000ull,
              1000000ull,
          }};
          const uint64_t closes[] = {{
              2000000ull,
              750000ull,
              1050000ull,
              1000000ull,
              1625000ull,
              2312500ull,
              2000000ull,
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
        "1,1000000,0",  # nominal
        "1,1000000,0",  # nominal across local-counter rollover
        "0,50000,1",  # physically injectable 50 ms duplicate
        "0,0,1",  # identical-timestamp duplicate
        "0,625000,2",  # short
        "0,1312500,3",  # long
        "0,1000000,4",  # otherwise-nominal flagged capture
    ]


def test_observed_185us_double_edge_is_rejected_without_latching_current_eligibility(
    tmp_path: Path,
) -> None:
    source = textwrap.dedent(
        f"""
        #include <stdint.h>
        #include <stdio.h>
        #include "{HELPER}"

        int main(void) {{
          const uint64_t duplicate_maximum = 100000ull;
          const uint64_t minimum = 800000ull;
          const uint64_t maximum = 1200000ull;
          const uint64_t intervals_us[] = {{747525ull, 185ull, 252289ull,
                                            1000000ull, 1000000ull,
                                            1000000ull, 1000000ull}};
          uint64_t opening = 0ull;
          bool previous_boundary_inhibited = false;
          unsigned clean_windows = 0u;
          for (unsigned i = 0; i < 7; ++i) {{
            const uint64_t closing = opening + intervals_us[i];
            OtisPpsBoundaryAssessment raw = otis_pps_gate_assess_boundary(
                opening, closing, 0u, duplicate_maximum, minimum, maximum);
            const bool effective_valid = raw.valid && !previous_boundary_inhibited;
            previous_boundary_inhibited = !raw.valid;
            clean_windows = effective_valid ? clean_windows + 1u : 0u;
            printf("%d,%d,%u,%d\\n", raw.valid ? 1 : 0, (int)raw.reason,
                   clean_windows, clean_windows >= 3u ? 1 : 0);
            opening = closing;
          }}
          return 0;
        }}
        """
    )
    assert _compile_and_run(tmp_path, source) == [
        "0,2,0,0",  # 747.525 ms: rejected short candidate
        "0,1,0,0",  # 185 us: rejected duplicate candidate
        "0,2,0,0",  # 252.289 ms: rejected short candidate
        "1,0,0,0",  # clean cadence, explicit recovery-inhibit window
        "1,0,1,0",
        "1,0,2,0",
        "1,0,3,1",  # current eligibility can recover after three clean windows
    ]

    firmware = (FIRMWARE / "otis_count_observation.cpp").read_text(
        encoding="utf-8"
    )
    assert 'return "suspect";' in firmware
    assert 'return "requalifying";' in firmware
    assert "control_ready_clean_windows" in firmware


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
    assert "otis_pps_diagnostics_poll" in service
    assert "OtisPpsDiagnosticsTransition::PhysicalPpsMissing" in service
    assert "kReferenceReasonMissingPps" in service

    reference_start = source.index(
        "bool otis_count_observation_on_pps_boundary("
    )
    reference_end = source.index(
        "bool otis_count_observation_service(", reference_start
    )
    reference = source[reference_start:reference_end]
    assert (
        "runtime_state->tcxo.last_gate_close_ticks =\n"
        "      observation->pps_timestamp_ticks;"
        in reference
    )
    assert "otis_monotonic_us32_interval(" in reference


def test_pps_counter_boundary_is_owned_by_pio_and_inhibits_rejected_anchor() -> None:
    source = (FIRMWARE / "otis_count_observation.cpp").read_text(
        encoding="utf-8"
    )
    backend = (FIRMWARE / "otis_pps_snapshot_backend.cpp").read_text(
        encoding="utf-8"
    )
    pio_source = (FIRMWARE / "otis_pps_snapshot.pio").read_text(
        encoding="utf-8"
    )
    assert "sm_config_set_jmp_pin(&config, OTIS_PIN_PPS_REFERENCE)" in backend
    assert "sm_config_set_in_shift(&config, true, true, 32u)" in backend
    assert "in x, 32" in pio_source
    assert "stop_and_sample_h1_pio_counter_from_pps_isr" not in source

    reference_start = source.index(
        "bool otis_count_observation_on_pps_boundary("
    )
    reference_end = source.index(
        "bool otis_count_observation_service(", reference_start
    )
    reference = source[reference_start:reference_end]
    assert "stop_h1_pio_long_gate_counter" not in reference
    assert "start_h1_pio_long_gate_counter" not in reference
    assert "previous_boundary_inhibited" in reference
    assert "OtisPpsBoundaryReason::PreviousBoundaryInvalid" in reference
    assert '"reference_previous_boundary_invalid"' in source
