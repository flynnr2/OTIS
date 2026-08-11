from __future__ import annotations

from pathlib import Path

from host.otis_tools.cx319_g1_operational_rehearsal import (
    _exercise_timing_contract,
)


def test_accelerated_rehearsal_crosses_both_startup_clocks(
    tmp_path: Path,
) -> None:
    result = _exercise_timing_contract(
        {
            "firmware": {
                "source_sha256": "a" * 64,
                "configuration_sha256": "b" * 64,
            }
        },
        tmp_path,
    )

    assert all(value is True for key, value in result.items() if key != "contract_id")
