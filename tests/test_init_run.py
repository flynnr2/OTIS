from __future__ import annotations

import json
from pathlib import Path

from host.otis_tools.init_run import init_run
from host.otis_tools.run_loader import load_manifest


def test_init_run_creates_run_from_template(tmp_path: Path, monkeypatch) -> None:
    runs_root = tmp_path / "runs"
    template = runs_root / "h0_sw1" / "gps_pps" / "_template"
    (template / "csv").mkdir(parents=True)
    (template / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "template": True,
                "run_id": "template",
                "stage": "SW1",
                "h_phase": "H0",
                "capture_type": "gps_pps",
                "files": [{"path": "csv/ref.csv", "contract": "raw_events_v1"}],
            }
        ),
        encoding="utf-8",
    )
    (template / "config.env").write_text("OTIS_CAPTURE_TYPE=\nOTIS_RUN_ID=\n", encoding="utf-8")
    (template / "csv" / "ref.csv").write_text(
        "record_type,schema_version,event_seq,channel_id,edge,timestamp_ticks,capture_domain,flags\n",
        encoding="utf-8",
    )

    monkeypatch.setattr("host.otis_tools.init_run.RUNS_ROOT", runs_root)
    run_dir = init_run("h0_sw1", "gps_pps", "run_001")

    assert run_dir == runs_root / "h0_sw1" / "gps_pps" / "run_001"
    manifest = load_manifest(run_dir)
    assert manifest.run_id == "run_001"
    assert manifest.data["template"] is False
    assert manifest.data["stage"] == "SW1"
    assert manifest.data["h_phase"] == "H0"
    assert manifest.data["capture_type"] == "gps_pps"
    assert manifest.data["started_at_utc"]
    assert "OTIS_CAPTURE_TYPE=gps_pps" in (run_dir / "config.env").read_text(encoding="utf-8")
    assert "OTIS_RUN_ID=run_001" in (run_dir / "config.env").read_text(encoding="utf-8")


def test_init_run_refuses_existing_run(tmp_path: Path, monkeypatch) -> None:
    runs_root = tmp_path / "runs"
    template = runs_root / "h0_sw1" / "gps_pps" / "_template"
    template.mkdir(parents=True)
    (template / "manifest.json").write_text('{"schema_version": 1, "run_id": "template", "files": []}\n', encoding="utf-8")
    (template / "config.env").write_text("OTIS_CAPTURE_TYPE=\nOTIS_RUN_ID=\n", encoding="utf-8")
    run_dir = runs_root / "h0_sw1" / "gps_pps" / "run_001"
    run_dir.mkdir()

    monkeypatch.setattr("host.otis_tools.init_run.RUNS_ROOT", runs_root)

    try:
        init_run("h0_sw1", "gps_pps", "run_001")
    except FileExistsError as exc:
        assert "--force" in str(exc)
    else:
        raise AssertionError("init_run overwrote an existing run")
