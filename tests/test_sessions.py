from __future__ import annotations

import json
from pathlib import Path

from host.otis_tools.run_loader import load_manifest
from host.otis_tools.sessions import detect_run_sessions


def _write_manifest(run_dir: Path, files: list[dict]) -> None:
    run_dir.mkdir(parents=True)
    (run_dir / "run_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": run_dir.name,
                "template": False,
                "files": files,
            }
        ),
        encoding="utf-8",
    )


def test_continuous_run_remains_one_session(tmp_path: Path) -> None:
    run_dir = tmp_path / "continuous"
    _write_manifest(run_dir, [{"path": "csv/health.csv", "contract": "health_v1"}])
    (run_dir / "csv").mkdir()
    (run_dir / "csv" / "health.csv").write_text(
        "\n".join(
            [
                "record_type,schema_version,status_seq,timestamp_ticks,status_domain,component,status_key,status_value,severity,flags",
                "STS,1,1,1,rp2040_timer0,system,mode,H1,INFO,0",
                "STS,1,2,2,rp2040_timer0,system,mode,H1,INFO,0",
                "",
            ]
        ),
        encoding="utf-8",
    )

    summary = detect_run_sessions(load_manifest(run_dir))

    assert summary.session_count == 1
    assert summary.split_reasons == ()


def test_sequence_restart_starts_new_session(tmp_path: Path) -> None:
    run_dir = tmp_path / "sequence_restart"
    _write_manifest(run_dir, [{"path": "csv/health.csv", "contract": "health_v1"}])
    (run_dir / "csv").mkdir()
    (run_dir / "csv" / "health.csv").write_text(
        "\n".join(
            [
                "record_type,schema_version,status_seq,timestamp_ticks,status_domain,component,status_key,status_value,severity,flags",
                "STS,1,10,10,rp2040_timer0,system,mode,H1,INFO,0",
                "STS,1,1,1,rp2040_timer0,system,mode,H1,INFO,0",
                "",
            ]
        ),
        encoding="utf-8",
    )

    summary = detect_run_sessions(load_manifest(run_dir))

    assert summary.session_count == 2
    assert summary.sessions[1].start_reason == "health.csv:status_seq_restart_or_rollback"


def test_boot_mid_run_starts_new_session(tmp_path: Path) -> None:
    run_dir = tmp_path / "boot_mid_run"
    _write_manifest(run_dir, [{"path": "csv/health.csv", "contract": "health_v1"}])
    (run_dir / "raw").mkdir()
    (run_dir / "raw" / "serial.log").write_text(
        "STS,1,1,1,rp2040_timer0,system,mode,H1,INFO,0\nBOOT OTIS\nSTS,1,1,1,rp2040_timer0,system,mode,H1,INFO,0\n",
        encoding="utf-8",
    )

    summary = detect_run_sessions(load_manifest(run_dir))

    assert summary.session_count == 2
    assert summary.reboot_marker_count == 1
    assert summary.sessions[1].start_reason == "firmware_boot_or_header_marker_after_capture_started"
