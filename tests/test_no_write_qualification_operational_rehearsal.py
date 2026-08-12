from __future__ import annotations

import os
from pathlib import Path

from host.otis_tools.no_write_qualification_operational_rehearsal import (
    _exercise_timing_contract,
    _ignore_nonregular_entries,
    _replace_capture_stop_target,
    _replace_build_identity,
    _source_exercised_q1_detach,
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


def test_replay_rebinds_the_logical_rotation_target(tmp_path: Path) -> None:
    log = tmp_path / "serial.log"
    log.write_text(
        '# OTIS_HOST {"event":"capture_started"}\n'
        '# OTIS_HOST {"event":"capture_stopped","logical_rotation":true,'
        '"next_run":"/old"}\n',
        encoding="utf-8",
    )

    _replace_capture_stop_target(log, tmp_path / "transition")

    assert str(tmp_path / "transition") in log.read_text(encoding="utf-8")
    assert '"next_run": "/old"' not in log.read_text(encoding="utf-8")


def test_replay_preserves_declared_q1_detach_evidence(tmp_path: Path) -> None:
    reports = tmp_path / "reports"
    reports.mkdir()
    state = reports / "capture_device_state.json"
    state.write_text(
        '{"reconnect_count":3,"intentional_detach_count":3}',
        encoding="utf-8",
    )

    assert _source_exercised_q1_detach(tmp_path) is True


def test_transition_replay_allows_no_complete_build_snapshot(
    tmp_path: Path,
) -> None:
    health = tmp_path / "health.csv"
    health.write_text(
        "record_type,component,status_key,status_value\n"
        "STS,cx317_active,critical_record,abort_accepted_on_core1\n",
        encoding="utf-8",
    )

    assert _replace_build_identity(
        health, "a" * 64 + ":" + "b" * 64, required=False
    ) is False
