from __future__ import annotations

import json
import time
from pathlib import Path

from host.otis_tools.instrument_monitor import RecordingMonitor
from host.otis_tools.instrument_recorder import read_recorder_status


def _state(path: Path, *, recording: bool = True, applications: int = 0,
           capture_count: int = 1,
           observed_ns: int | None = None) -> None:
    path.write_text(json.dumps({
        "recording": recording, "serial_open": recording,
        "observed_monotonic_ns": time.monotonic_ns() if observed_ns is None else observed_ns,
        "status_interval_s": 1, "instrument_fresh_limit_s": 10,
        "instrument_age_s": 0.1, "last_record_age_s": 0.1,
        "observed_record_counts": {"IAP": applications, "IRS": 0,
                                   "REF": capture_count, "SNP": capture_count,
                                   "CNT": capture_count, "APS": capture_count},
        "instrument": {"session": 42, "mode": "AUTO_DISCIPLINE",
                       "state": "ACQUIRING_OR_TRACKING", "reason": "acquiring",
                       "applied_code": 43085, "dac_epoch": 1,
                       "completed_command_sequence": 0,
                       "fields": {"fault": "none", "telemetry_dropped": "0"}},
        "recording_error": None,
    }))


def test_status_recomputes_writer_and_instrument_freshness_after_writer_dies(tmp_path: Path) -> None:
    observed = time.monotonic_ns()
    _state(tmp_path / "recorder_state.json", observed_ns=observed)
    fresh = read_recorder_status(tmp_path, now_monotonic_ns=observed + 1_000_000_000)
    assert fresh["writer_fresh"] and fresh["instrument_fresh"]
    stale = read_recorder_status(tmp_path, now_monotonic_ns=observed + 20_000_000_000)
    assert not stale["writer_fresh"] and not stale["instrument_fresh"]
    assert stale["instrument_age_s"] > 20


def test_independent_monitor_reports_material_changes_hourly_summary_and_close(tmp_path: Path) -> None:
    state_path = tmp_path / "recorder_state.json"
    _state(state_path)
    clock = [100.0]
    monitor = RecordingMonitor(tmp_path, summary_interval_s=3600, max_log_bytes=1200,
                               monotonic=lambda: clock[0])
    first = monitor.poll_once()
    assert first["writer_fresh"]
    assert first["capture_fresh"] is None
    assert monitor.poll_once()["capture_fresh"] is None
    _state(state_path, applications=1, capture_count=2)
    assert monitor.poll_once()["capture_fresh"] is True
    clock[0] += 3600
    stale = monitor.poll_once()
    assert stale["capture_fresh"] is False
    _state(state_path, recording=False, applications=1)
    (tmp_path / "recording_manifest.json").write_text("{}")
    result = monitor.run()
    assert result["status"] == "closed"
    rows = [json.loads(line) for path in sorted(tmp_path.glob("monitor-events-*.jsonl"))
            for line in path.read_text().splitlines()]
    assert sum(row["event"] == "periodic_summary" for row in rows) == 2
    assert any(row["event"] == "material_change" and
               isinstance(row["changes"].get("application_records"), dict) and
               row["changes"]["application_records"].get("after") == 1
               for row in rows)
    assert rows[-1]["event"] == "recording_closed"
    assert all(row["delivery"] == "local_durable_file" for row in rows)


def test_monitor_delivery_failure_is_visible_without_instrument_action(tmp_path, monkeypatch, capsys):
    _state(tmp_path / 'recorder_state.json')
    monitor = RecordingMonitor(tmp_path)

    def fail_delivery():
        raise OSError('simulated full output device')

    monkeypatch.setattr(monitor, '_open_log', fail_delivery)
    result = monitor.run()
    assert result['status'] == 'delivery_failed'
    assert 'simulated full output device' in capsys.readouterr().err
    recorded = json.loads((tmp_path / 'monitor_delivery_failure.json').read_text())
    assert recorded['status'] == 'delivery_failed'
    assert recorded['events_written'] == 0
    assert json.loads((tmp_path / 'recorder_state.json').read_text())['recording'] is True
