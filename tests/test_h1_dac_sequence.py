from __future__ import annotations

from pathlib import Path

import pytest

from host.otis_tools.h1_dac_sequence import RUN_017_RESTORE_CODE, run_017_schedule, run_sequence


def test_run_017_schedule_matches_planned_codes_and_duration() -> None:
    schedule = run_017_schedule()

    assert [step.code for step in schedule] == [
        0x8000,
        0x8800,
        0x8000,
        0x7800,
        0x8000,
        0x9000,
        0x8000,
        0x7000,
        0x8000,
    ]
    assert [step.dwell_s for step in schedule] == [
        10800.0,
        2700.0,
        2700.0,
        2700.0,
        2700.0,
        2700.0,
        2700.0,
        2700.0,
        7200.0,
    ]
    assert RUN_017_RESTORE_CODE == 0x8000


def test_run_017_rejects_short_final_dwell() -> None:
    with pytest.raises(ValueError, match="final dwell"):
        run_017_schedule(final_dwell_s=7199)


def test_run_017_runner_requires_run_id(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="run_017"):
        run_sequence(
            tmp_path / "run_999",
            tmp_path / "run_999" / "control" / "commands.fifo",
            final_dwell_s=7200,
            ack_timeout_s=1,
            dry_run=True,
            log_path=None,
        )
