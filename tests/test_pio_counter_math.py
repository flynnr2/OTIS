from __future__ import annotations

import subprocess
import textwrap
from pathlib import Path


HELPER = Path(
    "firmware/arduino/otis_nano_rp2040_connect/otis_pio_counter_math.h"
)


def test_pio_counter_sample_preserves_value_and_marks_saturation(
    tmp_path: Path,
) -> None:
    source_path = tmp_path / "pio_counter_check.cpp"
    binary_path = tmp_path / "pio_counter_check"
    source_path.write_text(
        textwrap.dedent(
            f"""
            #include <stdint.h>
            #include <stdio.h>
            #include "{HELPER}"

            int main(void) {{
              const uint32_t initial = 0xffffffffu;
              const uint32_t remaining[] = {{
                  0xffffffffu,
                  0xfffffffeu,
                  1u,
                  0u,
              }};
              for (unsigned i = 0;
                   i < sizeof(remaining) / sizeof(remaining[0]); ++i) {{
                OtisPioCounterSample sample =
                    otis_pio_counter_sample(initial, remaining[i]);
                printf("%llu,%d\\n",
                       (unsigned long long)sample.counted_edges,
                       sample.saturated ? 1 : 0);
              }}
              return 0;
            }}
            """
        ),
        encoding="utf-8",
    )
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

    assert subprocess.check_output([str(binary_path)], text=True).splitlines() == [
        "0,0",
        "1,0",
        "4294967294,0",
        "4294967295,1",
    ]
