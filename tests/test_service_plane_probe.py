from __future__ import annotations

from pathlib import Path
import json
import os

import pytest

from host.otis_tools.service_plane_probe import (
    execute_probe,
    inspect_raw_log,
    load_probe_contract,
)


def _run(
    tmp_path: Path, *, current_sequence: int = 13001, stage6: bool = False
) -> Path:
    run = tmp_path / "run"
    (run / "raw").mkdir(parents=True)
    (run / "csv").mkdir()
    planned = {
                "basis": "sealed same-topology/backend characterization",
                "command": "CONFIG?",
                "request_count": 60,
                "cadence_period_s": 1.0,
                "planned_trigger_count_seq": 13001,
    }
    manifest = (
        {
            "stage": "CX317_PPS_GATED_I_ONLY_PREVIEW",
            "controller_preview": {"planned_service_load": planned},
            "files": [{"path": "csv/sts.csv", "contract": "health_v1"}],
        }
        if stage6
        else {
            "stage": "CX317_FIXED_CODE_BASELINE",
            "cx317_fixed_code_baseline": {
                "planned_service_plane_probe": planned
            },
        }
    )
    (run / "run_manifest.json").write_text(
        json.dumps(manifest), encoding="utf-8"
    )
    (run / "raw" / "serial.log").write_text(
        f"CNT,1,{current_sequence},2,0,0,domain,1,R,source,0\n",
        encoding="utf-8",
    )
    (run / "capture_in_progress.flag").touch()
    os.mkfifo(run / "control.fifo")
    health_rows = [
        (component, status_key, status_value)
        for (component, status_key), status_value in {
            ("pps_gate", "valid"): "true",
            ("pps_gate", "reference_validity"): "valid",
            ("pps_gate", "count_validity"): "valid",
            ("pps_gate", "boundary_validity"): "valid",
            ("pps_gate", "aperture_validity"): "valid",
            ("pps_gate", "fifo_continuity"): "continuous",
            ("pps_gate", "association_state"): "clean",
            ("capture", "dropped_count"): "0",
        }.items()
    ]
    with (run / "csv" / "sts.csv").open("w", encoding="utf-8") as handle:
        handle.write(
            "record_type,schema_version,status_seq,timestamp_ticks,status_domain,component,status_key,status_value,severity,flags\n"
        )
        for index, (component, status_key, status_value) in enumerate(
            health_rows, 1
        ):
            handle.write(
                f"STS,1,{index},0,rp2040_timer0,{component},{status_key},{status_value},INFO,0\n"
            )
    return run


def _append_sent_marker(run: Path, command: str) -> int:
    with (run / "raw" / "serial.log").open("a", encoding="utf-8") as handle:
        handle.write(
            '# OTIS_HOST {"command":"'
            + command
            + '","event":"host_command_sent","utc":"2026-08-01T00:00:00Z"}\n'
        )
    return 0


def test_not_due_never_sends(tmp_path: Path) -> None:
    run = _run(tmp_path, current_sequence=13000)
    calls: list[str] = []
    result = execute_probe(
        run,
        sender=lambda _fifo, command: calls.append(command) or 0,
        sleep=lambda _seconds: None,
    )
    assert result["status"] == "not_due"
    assert calls == []


def test_exact_manifest_probe_runs_once(tmp_path: Path) -> None:
    run = _run(tmp_path)
    calls: list[str] = []
    sleeps: list[float] = []

    def sender(_fifo: Path, command: str) -> int:
        calls.append(command)
        return _append_sent_marker(run, command)

    result = execute_probe(run, sender=sender, sleep=sleeps.append)
    assert result["status"] == "complete"
    assert result["commands_sent_this_invocation"] == 60
    assert result["observed_total_probe_commands"] == 60
    assert calls == ["CONFIG?"] * 60
    assert sleeps == [1.0] * 60

    again = execute_probe(
        run,
        sender=lambda _fifo, command: calls.append(command) or 0,
        sleep=lambda _seconds: None,
    )
    assert again["status"] == "already_complete"
    assert again["commands_sent_this_invocation"] == 0
    assert len(calls) == 60


def test_stage6_declared_load_uses_same_non_actuating_probe(tmp_path: Path) -> None:
    run = _run(tmp_path, stage6=True)
    calls: list[str] = []

    def sender(_fifo: Path, command: str) -> int:
        calls.append(command)
        return _append_sent_marker(run, command)

    result = execute_probe(run, sender=sender, sleep=lambda _seconds: None)
    assert result["status"] == "complete"
    assert result["dac_command"] is False
    assert calls == ["CONFIG?"] * 60


def test_partial_raw_evidence_sends_only_remainder(tmp_path: Path) -> None:
    run = _run(tmp_path)
    for _ in range(9):
        _append_sent_marker(run, "CONFIG?")
    calls: list[str] = []

    def sender(_fifo: Path, command: str) -> int:
        calls.append(command)
        return _append_sent_marker(run, command)

    result = execute_probe(run, sender=sender, sleep=lambda _seconds: None)
    assert result["status"] == "complete"
    assert result["commands_sent_this_invocation"] == 51
    assert len(calls) == 51


def test_wrong_manifest_command_is_rejected(tmp_path: Path) -> None:
    run = _run(tmp_path)
    manifest_path = run / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["cx317_fixed_code_baseline"]["planned_service_plane_probe"][
        "command"
    ] = "DAC?"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(ValueError, match=r"only CONFIG\?"):
        load_probe_contract(run)


def test_raw_inspection_binds_marker_to_last_count_sequence(tmp_path: Path) -> None:
    raw = tmp_path / "serial.log"
    raw.write_text(
        "CNT,1,13001,2,0,0,domain,1,R,source,0\n"
        '# OTIS_HOST {"command":"CONFIG?","event":"host_command_sent"}\n',
        encoding="utf-8",
    )
    inspection = inspect_raw_log(raw)
    assert inspection.last_count_sequence == 13001
    assert inspection.sent_markers[0].count_sequence == 13001


def test_due_probe_rejects_nonzero_firmware_fault(tmp_path: Path) -> None:
    run = _run(tmp_path)
    with (run / "csv" / "sts.csv").open("a", encoding="utf-8") as handle:
        handle.write(
            "STS,1,99,0,rp2040_timer0,capture,dropped_count,1,WARN,0\n"
        )
    with pytest.raises(RuntimeError, match="health_dropped_count_nonzero"):
        execute_probe(run, sleep=lambda _seconds: None)


def test_due_probe_does_not_promote_d10_diagnostics_to_authority(
    tmp_path: Path,
) -> None:
    run = _run(tmp_path)
    with (run / "csv" / "sts.csv").open("a", encoding="utf-8") as handle:
        handle.write(
            "STS,1,99,0,rp2040_timer0,pps_dual_observer,agreement_state,MISMATCH,WARN,0\n"
        )
        handle.write(
            "STS,1,100,0,rp2040_timer0,pps_d10,buffer_overflow_count,12,WARN,32\n"
        )
    calls: list[str] = []

    result = execute_probe(
        run,
        sender=lambda _fifo, command: calls.append(command)
        or _append_sent_marker(run, command),
        sleep=lambda _seconds: None,
    )

    assert result["status"] == "complete"
    assert calls == ["CONFIG?"] * 60


def test_due_probe_rejects_host_disconnect_marker(tmp_path: Path) -> None:
    run = _run(tmp_path)
    with (run / "raw" / "serial.log").open("a", encoding="utf-8") as handle:
        handle.write(
            '# OTIS_HOST {"event":"serial_disconnected","utc":"2026-08-01T00:00:00Z"}\n'
        )
    with pytest.raises(RuntimeError, match="serial_disconnected"):
        execute_probe(run, sleep=lambda _seconds: None)
