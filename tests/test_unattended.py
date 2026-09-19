from __future__ import annotations

import json
import sys
import time

import pytest

from host.otis_tools import unattended
from host.otis_tools.adaptive_hybrid_transactions import SUPERVISOR_STATE
from host.otis_tools.capture_device import CAPTURE_STATE


def test_observer_records_unanswered_hold_without_changing_owner(tmp_path, monkeypatch):
    (tmp_path / "reports").mkdir()
    now = 1_000_000_000
    monkeypatch.setattr(unattended.time, "monotonic_ns", lambda: now)
    capture = {"bytes_written": 100, "updated_monotonic_ns": now,
               "capture_active": True, "serial_open": True}
    owner = {"qualified_d14_accepted_apertures": 259200,
             "lease_sequence": 1,
             "host_verification_hold": {"source": "verifier", "error": "review", "request_sequence": 2},
             "terminal": None}
    (tmp_path / CAPTURE_STATE).write_text(json.dumps(capture))
    (tmp_path / SUPERVISOR_STATE).write_text(json.dumps(owner))
    observer = unattended.Observer(tmp_path)
    first = observer.sample()
    assert first["qualified_checkpoint"] == 259200
    assert first["capture_fresh"] and first["raw_evidence_advancing"]
    now += 16_000_000_000
    later = observer.sample()
    assert not later["capture_fresh"] and not later["raw_evidence_advancing"]
    assert later["review_hold"]["request_sequence"] == 2
    now += 30_000_000_000
    capture.update(bytes_written=200, updated_monotonic_ns=now)
    (tmp_path / CAPTURE_STATE).write_text(json.dumps(capture))
    stalled_owner = observer.sample()
    assert stalled_owner["capture_fresh"] and stalled_owner["raw_evidence_advancing"]
    assert not stalled_owner["supervisor_ownership_service_advancing"]
    assert json.loads((tmp_path / SUPERVISOR_STATE).read_text()) == owner


def test_missing_observations_do_not_kill_or_restart_owner(tmp_path, monkeypatch):
    directory = tmp_path / "monitor"
    directory.mkdir()
    marker = tmp_path / "completed"
    monkeypatch.setattr(unattended, "UNATTENDED_MONITOR_INTERVAL_S", 0.02)
    result = unattended.supervise(
        [sys.executable, "-c", "import time,pathlib; time.sleep(.1); pathlib.Path(__import__('sys').argv[1]).write_text('done')", str(marker)],
        tmp_path / "absent-run", directory,
    )
    assert result == 0 and marker.read_text() == "done"
    events = [json.loads(line) for line in (directory / "transitions.jsonl").read_text().splitlines()]
    assert events[0]["state"]["review_required"] is True
    assert events[-1]["state"]["owner_exit_code"] == 0
    assert all(event["command_authority"] is False for event in events)


def test_duplicate_launch_refuses_before_process_creation(tmp_path, monkeypatch):
    (tmp_path / "run.unattended").mkdir()
    monkeypatch.setattr(unattended.subprocess, "Popen", lambda *a, **k: pytest.fail("duplicate launch spawned"))
    with pytest.raises(FileExistsError):
        unattended.launch(["--rehearse", "--run-dir", str(tmp_path / "run")])


def test_monitor_loss_does_not_terminate_detached_owner(tmp_path):
    import subprocess
    marker = tmp_path / "owner-finished"
    directory = tmp_path / "monitor"
    directory.mkdir()
    code = (
        "import pathlib,sys; from host.otis_tools.unattended import supervise; "
        "supervise([sys.executable,'-c',"
        "\"import time,pathlib; time.sleep(1); pathlib.Path(__import__('sys').argv[1]).write_text('done')\","
        "sys.argv[1]],pathlib.Path(sys.argv[2])/'run',pathlib.Path(sys.argv[2]))"
    )
    monitor = subprocess.Popen([sys.executable, "-c", code, str(marker), str(directory)], start_new_session=True)
    deadline = time.monotonic() + 5
    while not (directory / "started.json").exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert (directory / "started.json").exists()
    monitor.terminate()
    monitor.wait(timeout=2)
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.02)
    assert marker.read_text() == "done"
