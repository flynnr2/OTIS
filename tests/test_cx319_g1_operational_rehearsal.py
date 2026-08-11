from __future__ import annotations

import os
from pathlib import Path

from host.otis_tools.cx319_g1_operational_rehearsal import (
    _exercise_timing_contract,
    _ignore_nonregular_entries,
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


def test_replay_copy_excludes_stale_runtime_fifos(tmp_path: Path) -> None:
    (tmp_path / "regular.txt").write_text("evidence\n", encoding="utf-8")
    (tmp_path / "directory").mkdir()
    fifo = tmp_path / "normal.fifo"
    fifo.parent.mkdir(exist_ok=True)
    os.mkfifo(fifo)

    ignored = _ignore_nonregular_entries(
        str(tmp_path), ["regular.txt", "directory", "normal.fifo"]
    )

    assert ignored == ["normal.fifo"]
