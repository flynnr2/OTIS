from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path


HELPER = Path("firmware/arduino/otis_nano_rp2040_connect/otis_timebase_math.h")
WRAP_TICKS = (1 << 32) * 16
NOMINAL_PPS_TICKS = 16_000_000
SHORT_THRESHOLD_TICKS = 8_000_000
LONG_THRESHOLD_TICKS = 19_200_000


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
              otis_timer0_interval_ticks(32000000ull, 48000000ull),
              otis_timer0_interval_ticks(wrap - 4000000ull, 12000000ull),
              otis_timer0_interval_ticks(wrap - 32000000ull, wrap - 16000000ull),
              otis_timer0_interval_ticks(wrap - 16000000ull, 0ull),
              otis_timer0_interval_ticks(0ull, 16000000ull),
              otis_timer0_interval_ticks(64000000ull, 84000000ull),
              otis_timer0_interval_ticks(wrap - 4000000ull, 18000000ull),
              otis_timer0_interval_ticks(123456ull, 123456ull),
              short_threshold,
              long_threshold,
          }};
          for (unsigned i = 0; i < sizeof(intervals) / sizeof(intervals[0]); ++i) {{
            printf("%llu,%d\\n",
                   (unsigned long long)intervals[i],
                   (int)otis_classify_pps_interval_ticks(
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
        20_000_000,
        22_000_000,
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
