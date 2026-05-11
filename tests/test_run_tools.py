from __future__ import annotations

import csv
import json
from pathlib import Path
import shutil

from host.otis_tools.report_run import render_report
from host.otis_tools.run_loader import load_manifest
from host.otis_tools.validate_run import validate_run

EXAMPLE = Path("examples/h0_pps_tcxo_synthetic")


def _copy_example(tmp_path: Path) -> Path:
    run_dir = tmp_path / "run"
    shutil.copytree(EXAMPLE, run_dir)
    return run_dir


def _rewrite_csv_cell(path: Path, row_index: int, field_name: str, value: str) -> None:
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        fieldnames = reader.fieldnames
        rows = list(reader)
    assert fieldnames is not None
    rows[row_index][field_name] = value
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def test_load_manifest() -> None:
    manifest = load_manifest(EXAMPLE)
    assert manifest.run_id == "h0_pps_tcxo_synthetic_001"
    assert manifest.known_channels == frozenset({0, 1, 2})
    assert "rp2040_timer0" in manifest.known_domains


def test_validate_example_run() -> None:
    assert validate_run(EXAMPLE) == 0


def test_render_report_mentions_contracts() -> None:
    report = render_report(EXAMPLE)
    assert "raw_events_v1" in report
    assert "count_observations_v1" in report
    assert "health_v1" in report


def test_validate_run_rejects_bad_channel(tmp_path: Path) -> None:
    run_dir = _copy_example(tmp_path)
    _rewrite_csv_cell(run_dir / "raw_events.csv", 0, "channel_id", "99")

    assert validate_run(run_dir) == 1


def test_validate_run_rejects_reserved_flags(tmp_path: Path) -> None:
    run_dir = _copy_example(tmp_path)
    _rewrite_csv_cell(run_dir / "health.csv", 0, "flags", str(1 << 16))

    assert validate_run(run_dir) == 1


def test_validate_run_accepts_contract_edge_enums(tmp_path: Path) -> None:
    run_dir = _copy_example(tmp_path)
    _rewrite_csv_cell(run_dir / "raw_events.csv", 0, "edge", "B")
    _rewrite_csv_cell(run_dir / "count_observations.csv", 0, "source_edge", "B")

    assert validate_run(run_dir) == 0


def test_validate_run_rejects_invalid_edge(tmp_path: Path) -> None:
    run_dir = _copy_example(tmp_path)
    _rewrite_csv_cell(run_dir / "raw_events.csv", 0, "edge", "X")

    assert validate_run(run_dir) == 1


def test_validate_run_accepts_contract_health_severities(tmp_path: Path) -> None:
    for severity in ("INFO", "WARN", "ERROR", "FATAL"):
        run_dir = tmp_path / severity.lower()
        shutil.copytree(EXAMPLE, run_dir)
        _rewrite_csv_cell(run_dir / "health.csv", 0, "severity", severity)

        assert validate_run(run_dir) == 0


def test_validate_run_rejects_invalid_health_severity(tmp_path: Path) -> None:
    run_dir = _copy_example(tmp_path)
    _rewrite_csv_cell(run_dir / "health.csv", 0, "severity", "CRITICAL")

    assert validate_run(run_dir) == 1


def test_load_manifest_requires_files(tmp_path: Path) -> None:
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "run_manifest.json").write_text(
        json.dumps({"schema_version": 1, "run_id": "empty", "files": []}),
        encoding="utf-8",
    )

    try:
        load_manifest(run_dir)
    except ValueError as exc:
        assert "at least one data file" in str(exc)
    else:
        raise AssertionError("load_manifest accepted an empty file list")
