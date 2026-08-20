from __future__ import annotations

import csv
import json
from pathlib import Path

from host.otis_tools import active_hybrid_monitor as monitor


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _write_csv(path: Path, row: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(row))
        writer.writeheader()
        writer.writerow(row)


def _fixture(tmp_path: Path, monkeypatch) -> tuple[Path, float]:
    run_dir = tmp_path / "run"
    now = 2_000_000_000.0
    manifest = {
        "run_id": "fixture",
        "bundle": {"bundle_sha256": "b" * 64},
        "activation": {"activation_sha256": "a" * 64},
        "host": {"serial_device": "/dev/fixture"},
    }
    monkeypatch.setattr(
        monitor,
        "validate_frozen_run_manifest",
        lambda path: manifest,
    )
    _write_json(
        run_dir / monitor.CAPTURE_STATE,
        {
            "pid": 321,
            "capture_active": True,
            "serial_open": True,
            "malformed_utf8": 0,
            "parser_errors": 0,
            "reconnect_count": 0,
            "commands_rejected": 0,
            "bytes_written": 100,
            "lines_parsed": 4,
            "commands_sent": 2,
            "emergency_aborts_sent": 0,
        },
    )
    _write_json(
        run_dir / monitor.SUPERVISOR_STATE,
        {
            "terminal": None,
            "latest_hybrid_state": "PHASE_QUALIFY",
            "phase_material_application_count": 1,
            "first_phase_checkpoint_passed": True,
        },
    )
    raw = run_dir / monitor.RAW_SERIAL
    raw.parent.mkdir(parents=True)
    raw.write_text("record\n", encoding="utf-8")
    for path in (run_dir / monitor.CAPTURE_STATE, raw):
        path.touch()
        monkeypatch.setattr(monitor, "_age_s", lambda path, now: 1.0)
    monkeypatch.setattr(monitor, "_serial_owner_pids", lambda device: {321})
    monkeypatch.setattr(monitor, "_pid_alive", lambda pid: True)
    return run_dir, now


def test_running_snapshot_reports_owner_and_scientific_progress(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir, now = _fixture(tmp_path, monkeypatch)
    _write_csv(
        run_dir / monitor.HYBRID,
        {
            "decision_sequence": "8",
            "dac_epoch": "2",
            "hybrid_state": "PHASE_QUALIFY",
            "phase_material_application": "true",
            "applied_delta_codes": "4",
        },
    )

    result = monitor.snapshot(run_dir, now=now)

    assert result["status"] == "running"
    assert result["integrity_faults"] == []
    assert result["capture"]["serial_owner_pids"] == [321]
    assert result["progress"]["phase_material_application_count"] == 1
    assert result["progress"]["active_hybrid_decisions"]["rows"] == 1


def test_stale_capture_and_wrong_owner_are_faults(tmp_path: Path, monkeypatch) -> None:
    run_dir, now = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(monitor, "_age_s", lambda path, now: 30.0)
    monkeypatch.setattr(monitor, "_serial_owner_pids", lambda device: {999})

    result = monitor.snapshot(run_dir, now=now)

    assert result["status"] == "fault"
    assert "capture_state_stale" in result["integrity_faults"]
    assert "raw_evidence_stale" in result["integrity_faults"]
    assert "sole_serial_owner_mismatch" in result["integrity_faults"]


def test_terminal_snapshot_does_not_require_live_owner(tmp_path: Path, monkeypatch) -> None:
    run_dir, now = _fixture(tmp_path, monkeypatch)
    _write_json(
        run_dir / monitor.SUPERVISOR_STATE,
        {"terminal": {"result": "healthy_stop", "reason": "finite"}},
    )
    monkeypatch.setattr(monitor, "_serial_owner_pids", lambda device: set())
    monkeypatch.setattr(monitor, "_age_s", lambda path, now: 60.0)

    result = monitor.snapshot(run_dir, now=now)

    assert result["status"] == "terminal"
    assert "sole_serial_owner_mismatch" not in result["integrity_faults"]
    assert "raw_evidence_stale" not in result["integrity_faults"]
