from __future__ import annotations

from pathlib import Path

from host.otis_tools.h1_endpoint_repeat import run_endpoint_repeat


def test_endpoint_repeat_dry_run_prints_command_schedule(tmp_path: Path, capsys) -> None:
    run_endpoint_repeat(
        tmp_path / "commands.fifo",
        profile="SLOPE_CENTER_EDGE_300S",
        passes=2,
        pass_seconds=4500,
        guard_seconds=90,
        raw_log=tmp_path / "serial.log",
        complete_timeout_s=1,
        dry_run=True,
    )

    assert capsys.readouterr().out.splitlines() == [
        "DAC MID",
        "FC0?",
        "SWEEP?",
        "# pass 1/2",
        "SWEEP LOAD SLOPE_CENTER_EDGE_300S",
        "SWEEP START",
        "SWEEP?",
        "# sleeping 90s before next pass",
        "# pass 2/2",
        "SWEEP LOAD SLOPE_CENTER_EDGE_300S",
        "SWEEP START",
        "SWEEP?",
        "# endpoint repeat command schedule complete",
    ]
