from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
import json
import os

import pytest

import host.otis_tools.cx318_stage4_premise_command as premise


def _live_run(tmp_path: Path) -> tuple[Path, Path]:
    run = tmp_path / "stage4/setup"
    campaign = run.parent
    (run / "raw").mkdir(parents=True)
    (run / "reports").mkdir()
    (run / "csv").mkdir()
    (run / "control").mkdir()
    (campaign / "PROGRAMME_STATE.md").write_text(
        "# CX318 test campaign ledger\n", encoding="utf-8"
    )
    (run / "run_manifest.json").write_text(json.dumps({
        "schema_version": 1,
        "template": False,
        "run_id": run.name,
        "stage": premise.EXPECTED_STAGE,
        "host": {"serial_device": "/dev/cu.test"},
        "domains": [{"name": "rp2040_timer0", "nominal_hz": 16_000_000}],
        "channels": [],
        "files": [{"path": "csv/health.csv", "contract": "health_v1"}],
    }), encoding="utf-8")
    (run / premise.CAPTURE_IN_PROGRESS_FLAG).write_text("\n", encoding="utf-8")
    (run / "reports/capture_device_state.json").write_text(json.dumps({
        "capture_active": True,
        "serial_open": True,
        "parser_errors": 0,
        "malformed_utf8": 0,
        "reconnect_count": 0,
        "commands_rejected": 0,
        "commands_sent": 3,
        "pid": 456,
    }), encoding="utf-8")
    raw = ['# OTIS_HOST {"event":"capture_started"}']
    for command in premise.EXPECTED_PRECOMMANDS:
        raw.extend([
            f'# OTIS_HOST {json.dumps({"event": "host_command_accepted", "command": command})}',
            f'# OTIS_HOST {json.dumps({"event": "host_command_sent", "command": command})}',
        ])
    (run / "raw/serial.log").write_text("\n".join(raw) + "\n", encoding="utf-8")
    (run / "csv/dac_steps.csv").write_text("record_type\n", encoding="utf-8")
    (run / "csv/active_transactions_v1.csv").write_text("record_type\n", encoding="utf-8")
    (run / "csv/environment.csv").write_text(
        "source\n"
        "sht4x\n"
        "bmp280\n",
        encoding="utf-8",
    )
    (run / "csv/pps_snapshots.csv").write_text(
        "session,snapshot_sequence,reference_sequence,status\n"
        "1,1,1,0\n"
        "1,2,2,0\n",
        encoding="utf-8",
    )
    (run / "csv/count_observations.csv").write_text(
        "count_seq\n"
        "1\n"
        "2\n",
        encoding="utf-8",
    )
    health = [
        ("build", "profile_id", "cx318_stage4_premise_setup"),
        ("build", "enable_cx318_stage4_premise_setup", "1"),
        ("build", "enable_cx318_stage4_preview", "0"),
        ("build", "enable_cx317_i_only_preview", "0"),
        ("build", "enable_cx317_bounded_active", "0"),
        ("build", "enable_dac_ad5693r", "1"),
        ("cx318_premise", "allowed_code", "0xA828"),
        ("cx318_premise", "write_consumed", "false"),
        ("cx318_premise", "actionable", "false"),
        ("cx318_premise", "actuation_authorized", "false"),
        ("cx318_premise", "automatic_authority", "false"),
        ("dac", "applied_code_known", "false"),
        ("dac", "last_write_ok", "false"),
        ("dac", "last_requested_code", "0x0000"),
        ("dac", "last_applied_code", "unavailable"),
    ]
    (run / "csv/health.csv").write_text(
        "component,status_key,status_value\n"
        + "".join(f"{component},{key},{value}\n" for component, key, value in health),
        encoding="utf-8",
    )
    fifo = run / "control/commands.fifo"
    os.mkfifo(fifo)
    return run, fifo


def test_latch_is_durable_before_the_only_enqueue(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, fifo = _live_run(tmp_path)
    events: list[str] = []
    monkeypatch.setattr(premise.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(
        returncode=0, stdout="456\n", stderr="",
    ))

    def send(_fifo: Path, command: str) -> None:
        latch = json.loads((run / premise.LATCH_PATH).read_text(encoding="utf-8"))
        campaign_latch = json.loads(
            (run.parent / premise.CAMPAIGN_LATCH_PATH).read_text(encoding="utf-8")
        )
        assert latch["status"] == "attempt_latched_before_enqueue"
        assert campaign_latch["status"] == "attempt_latched_before_enqueue"
        assert campaign_latch["run_latch_path"] == (
            run.relative_to(run.parent).as_posix() + "/" + premise.LATCH_PATH.as_posix()
        )
        events.append(command)

    monkeypatch.setattr(premise, "send_timestamped_command_to_fifo", send)
    path = premise.latch_and_send(run_dir=run, command_fifo=fifo)

    assert path == run / premise.LATCH_PATH
    assert events == [premise.COMMAND]
    assert (run.parent / premise.CAMPAIGN_LATCH_PATH).is_file()
    with pytest.raises(FileExistsError, match="already latched"):
        premise.latch_and_send(run_dir=run, command_fifo=fifo)


def test_enqueue_failure_retains_no_retry_latch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    run, fifo = _live_run(tmp_path)
    monkeypatch.setattr(premise.subprocess, "run", lambda *_args, **_kwargs: SimpleNamespace(
        returncode=0, stdout="456\n", stderr="",
    ))
    monkeypatch.setattr(
        premise, "send_timestamped_command_to_fifo",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("enqueue failed")),
    )

    with pytest.raises(RuntimeError, match="enqueue failed"):
        premise.latch_and_send(run_dir=run, command_fifo=fifo)
    assert (run / premise.LATCH_PATH).is_file()
    assert (run.parent / premise.CAMPAIGN_LATCH_PATH).is_file()
