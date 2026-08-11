from __future__ import annotations

import json
from pathlib import Path

import pytest

from host.otis_tools import capture_owner_handoff as handoff
from host.otis_tools.run_loader import CAPTURE_IN_PROGRESS_FLAG


def _run(path: Path, *, active: bool, pid: int | None = None) -> Path:
    path.mkdir(parents=True)
    (path / "run_manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "template": False,
        "run_id": path.name,
        "host": {"serial_device": "/dev/cu.usbmodem14601"},
        "domains": [],
        "channels": [],
        "contracts": {"health_v1": 1},
        "files": [{
            "contract": "health_v1",
            "path": "csv/health.csv",
            "optional": True,
        }],
    }), encoding="utf-8")
    if active:
        (path / "reports").mkdir()
        (path / handoff.STATE_PATH).write_text(json.dumps({
            "pid": pid,
            "capture_active": True,
            "serial_open": True,
            "parser_errors": 0,
            "malformed_utf8": 0,
            "reconnect_count": 0,
        }), encoding="utf-8")
        (path / CAPTURE_IN_PROGRESS_FLAG).write_text("active\n", encoding="utf-8")
    return path


def test_handoff_rejects_nonsole_source_owner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _run(tmp_path / "source", active=True, pid=10)
    target = _run(tmp_path / "target", active=False)
    monkeypatch.setattr(handoff, "_owner_pids", lambda _device: {10, 11})
    with pytest.raises(ValueError, match="sole serial owner"):
        handoff.perform_handoff(from_run=source, to_run=target, duration_s=60)


def test_handoff_stops_exact_capture_and_opens_prepared_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _run(tmp_path / "source", active=True, pid=10)
    target = _run(tmp_path / "target", active=False)
    alive = {10}

    def owners(_device: str) -> set[int]:
        return set(alive)

    def interrupt(pid: int) -> None:
        alive.discard(pid)
        if pid == 10:
            (source / CAPTURE_IN_PROGRESS_FLAG).unlink()

    def spawn(arguments: list[str]) -> int:
        assert arguments[0:3] == [handoff.sys.executable, "-m", "host.otis_tools.capture_device"]
        assert "--device" in arguments and "--duration-s" in arguments
        alive.add(20)
        (target / "reports").mkdir()
        (target / handoff.STATE_PATH).write_text(json.dumps({
            "pid": 20,
            "capture_active": True,
            "serial_open": True,
            "parser_errors": 0,
            "malformed_utf8": 0,
            "reconnect_count": 0,
        }), encoding="utf-8")
        (target / CAPTURE_IN_PROGRESS_FLAG).write_text("active\n", encoding="utf-8")
        return 20

    monkeypatch.setattr(handoff, "_owner_pids", owners)
    monkeypatch.setattr(handoff, "_process_command", lambda _pid: f"host.otis_tools.capture_device --run-dir {source}")
    monkeypatch.setattr(handoff, "_process_alive", lambda pid: pid in alive)
    monkeypatch.setattr(handoff, "_signal_interrupt", interrupt)
    monkeypatch.setattr(handoff, "_spawn", spawn)
    result = handoff.perform_handoff(
        from_run=source,
        to_run=target,
        duration_s=300,
        command_fifo=target / "control/normal.fifo",
    )
    assert result["status"] == "passed"
    assert result["source_pid"] == 10
    assert result["target_pid"] == 20
    assert result["elapsed_s"] <= result["maximum_gap_s"]
    assert (target / handoff.REPORT_PATH).is_file()
