from __future__ import annotations

import csv
import io
import json
from pathlib import Path
import shutil
import sys

from host.otis_tools.capture_serial import capture_serial
from host.otis_tools.report_run import render_report
from host.otis_tools.run_loader import load_manifest
from host.otis_tools.validate_run import validate_run

EXAMPLE = Path("examples/h0_pps_tcxo_synthetic")
TEMPLATE_EXAMPLES = [
    Path("examples/h0_usb_synthetic"),
    Path("examples/h0_gpio_loopback"),
    Path("examples/h0_gps_pps"),
    Path("examples/h0_pps_tcxo_real"),
]


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


def test_validate_bringup_templates() -> None:
    for run_dir in TEMPLATE_EXAMPLES:
        assert validate_run(run_dir) == 0


def test_validate_run_accepts_gps_pps_bringup_records(tmp_path: Path) -> None:
    run_dir = tmp_path / "gps_pps"
    shutil.copytree(Path("examples/h0_gps_pps"), run_dir)
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    manifest["run_id"] = "gps_pps_test"
    manifest["template"] = False
    (run_dir / "run_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "raw_events.csv").write_text(
        "\n".join(
            [
                "record_type,schema_version,event_seq,channel_id,edge,timestamp_ticks,capture_domain,flags",
                "REF,1,1000,1,R,16000000,rp2040_timer0,16",
                "REF,1,1001,1,R,32000000,rp2040_timer0,16",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (run_dir / "health.csv").write_text(
        "\n".join(
            [
                "record_type,schema_version,status_seq,timestamp_ticks,status_domain,component,status_key,status_value,severity,flags",
                "STS,1,1,1,rp2040_timer0,system,mode,SW1_GPS_PPS,INFO,32768",
                "",
            ]
        ),
        encoding="utf-8",
    )

    assert validate_run(run_dir) == 0


def test_capture_serial_splits_records(tmp_path: Path, monkeypatch) -> None:
    run_dir = tmp_path / "captured"
    monkeypatch.setattr(
        sys,
        "stdin",
        io.StringIO(
            "\n".join(
                [
                    "record_type,schema_version,event_seq,channel_id,edge,timestamp_ticks,capture_domain,flags",
                    "STS,1,1,1,rp2040_timer0,system,mode,SW1_GPS_PPS,INFO,32768",
                    "REF,1,1000,1,R,16000000,rp2040_timer0,16",
                    "REF,1,1001,1,R,32000000,rp2040_timer0,16",
                    "",
                ]
            )
        ),
    )

    assert capture_serial(run_dir, Path("examples/h0_gps_pps"), "captured_gps_pps") == 0
    assert validate_run(run_dir) == 0


def test_render_report_mentions_contracts() -> None:
    report = render_report(EXAMPLE)
    assert "raw_events_v1" in report
    assert "count_observations_v1" in report
    assert "health_v1" in report


def test_validate_run_rejects_bad_channel(tmp_path: Path) -> None:
    run_dir = _copy_example(tmp_path)
    _rewrite_csv_cell(run_dir / "raw_events.csv", 0, "channel_id", "99")

    assert validate_run(run_dir) == 1


def test_validate_run_rejects_non_monotonic_raw_timestamps(tmp_path: Path) -> None:
    run_dir = _copy_example(tmp_path)
    _rewrite_csv_cell(run_dir / "raw_events.csv", 1, "timestamp_ticks", "1")

    assert validate_run(run_dir) == 1


def test_validate_run_rejects_malformed_rows(tmp_path: Path) -> None:
    run_dir = _copy_example(tmp_path)
    with (run_dir / "raw_events.csv").open("a", encoding="utf-8") as handle:
        handle.write("EVT,1,1004,0,R,1632000100,rp2040_timer0,0,extra\n")

    assert validate_run(run_dir) == 1


def test_validate_run_rejects_bad_pps_cadence(tmp_path: Path) -> None:
    run_dir = _copy_example(tmp_path)
    _rewrite_csv_cell(run_dir / "raw_events.csv", 3, "timestamp_ticks", "1700000000")

    assert validate_run(run_dir) == 1


def test_validate_run_rejects_zero_count_without_flag(tmp_path: Path) -> None:
    run_dir = _copy_example(tmp_path)
    _rewrite_csv_cell(run_dir / "count_observations.csv", 0, "counted_edges", "0")

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
