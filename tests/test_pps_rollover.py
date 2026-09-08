from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path


HELPER = Path("firmware/arduino/otis_nano_rp2040_connect/otis_timebase_math.h")
SKETCH = Path(
    "firmware/arduino/otis_nano_rp2040_connect/otis_nano_rp2040_connect.ino"
)


def test_native_microsecond_source_and_quantum_are_explicit_in_firmware_status() -> None:
    helper = HELPER.read_text()
    sketch = SKETCH.read_text()

    assert "OTIS_RP2040_MONOTONIC_US_PER_SECOND 1000000ul" in helper
    assert "OTIS_RP2040_MONOTONIC_TIMESTAMP_QUANTUM_US 1ul" in helper
    assert "OTIS_RP2040_MONOTONIC_TIMESTAMP_QUANTUM_NS 1000ul" in helper
    assert '"timestamp_source_counter_hz"' in sketch
    assert '"timestamp_coordinate_hz"' in sketch
    assert '"timestamp_quantum_ns"' in sketch
    assert '"native_local_non_metrological"' in sketch
    assert (
        '"rp2040_timerawl_or_arduino_micros_1mhz_native_us"' in sketch
    )
WRAP_TICKS = 1 << 32
NOMINAL_PPS_TICKS = 1_000_000
SHORT_THRESHOLD_TICKS = 800_000
LONG_THRESHOLD_TICKS = 1_200_000


def _compile_and_run(tmp_path: Path, source: str) -> str:
    source_path = tmp_path / "pps_rollover_check.cpp"
    binary_path = tmp_path / "pps_rollover_check"
    source_path.write_text(source, encoding="utf-8")
    subprocess.run(
        [
            "c++",
            "-std=c++17",
            f"-I{Path.cwd()}",
            str(source_path),
            "-o",
            str(binary_path),
        ],
        check=True,
    )
    return subprocess.check_output([str(binary_path)], text=True)


def test_firmware_pps_interval_helper_is_rollover_safe(tmp_path: Path) -> None:
    source = textwrap.dedent(
        f"""
        #include <stdint.h>
        #include <stdio.h>
        #include "{HELPER}"

        int main(void) {{
          const uint64_t wrap = {WRAP_TICKS}ull;
          const uint64_t nominal = {NOMINAL_PPS_TICKS}ull;
          const uint64_t short_threshold = {SHORT_THRESHOLD_TICKS}ull;
          const uint64_t long_threshold = {LONG_THRESHOLD_TICKS}ull;
          const uint64_t intervals[] = {{
              otis_monotonic_us32_interval(2000000ull, 3000000ull),
              otis_monotonic_us32_interval(wrap - 250000ull, 750000ull),
              otis_monotonic_us32_interval(wrap - 2000000ull, wrap - 1000000ull),
              otis_monotonic_us32_interval(wrap - 1000000ull, 0ull),
              otis_monotonic_us32_interval(0ull, 1000000ull),
              otis_monotonic_us32_interval(4000000ull, 5250000ull),
              otis_monotonic_us32_interval(wrap - 250000ull, 1125000ull),
              otis_monotonic_us32_interval(123456ull, 123456ull),
              short_threshold,
              long_threshold,
          }};
          for (unsigned i = 0; i < sizeof(intervals) / sizeof(intervals[0]); ++i) {{
            printf("%llu,%d\\n",
                   (unsigned long long)intervals[i],
                   (int)otis_classify_pps_interval_us(
                       intervals[i], short_threshold, long_threshold));
          }}
          (void)nominal;
          return 0;
        }}
        """
    )

    rows = [line.split(",") for line in _compile_and_run(tmp_path, source).splitlines()]
    intervals = [int(row[0]) for row in rows]
    classes = [int(row[1]) for row in rows]

    assert intervals == [
        NOMINAL_PPS_TICKS,
        NOMINAL_PPS_TICKS,
        NOMINAL_PPS_TICKS,
        NOMINAL_PPS_TICKS,
        NOMINAL_PPS_TICKS,
        1_250_000,
        1_375_000,
        0,
        SHORT_THRESHOLD_TICKS,
        LONG_THRESHOLD_TICKS,
    ]
    assert classes == [
        1,  # normal away from rollover
        1,  # normal crossing rollover
        1,  # multiple sequential valid intervals spanning rollover: before
        1,  # multiple sequential valid intervals spanning rollover: crossing
        1,  # multiple sequential valid intervals spanning rollover: after
        2,  # genuine long away from rollover
        2,  # genuine long crossing rollover
        0,  # duplicate edge
        1,  # exact short threshold is accepted
        1,  # exact long threshold is accepted
    ]
