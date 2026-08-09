from __future__ import annotations

import json
from pathlib import Path

import host.otis_tools.cx318_stage4_firmware_parity as parity


def _write_fixture(tmp_path: Path, *, nominal_hz: int = 10_000_000) -> Path:
    run = tmp_path / "runs" / "selected"
    (run / "csv").mkdir(parents=True)
    (run / "run_manifest.json").write_text(
        json.dumps(
            {
                "oscillator": {"nominal_frequency_hz": nominal_hz},
                "domains": [{"name": "rp2040_timer0", "nominal_hz": 16_000_000}],
                "active_campaign": {"start_code": 43088},
            }
        ),
        encoding="utf-8",
    )
    (run / "csv" / "pps_snapshots.csv").write_text(
        "\n".join(
            (
                "session,snapshot_sequence,cumulative_down_counter,reference_sequence,reference_timestamp_ticks,status,backend",
                "1,1,100000000,1,16000000,0,pio_wait_cumulative_snapshot_dma_v1",
                f"1,2,{100000000 - nominal_hz},2,32000000,0,pio_wait_cumulative_snapshot_dma_v1",
                f"1,3,{100000000 - 2 * nominal_hz},3,48000000,0,pio_wait_cumulative_snapshot_dma_v1",
                "",
            )
        ),
        encoding="utf-8",
    )
    (run / "csv" / "count_observations.csv").write_text(
        "\n".join(
            (
                "count_seq,counted_edges,flags",
                f"1,{nominal_hz},0",
                f"2,{nominal_hz},0",
                f"3,{nominal_hz},0",
                "",
            )
        ),
        encoding="utf-8",
    )
    corpus = {
        "schema_version": 1,
        "corpus_id": "small_cx318_parity_fixture",
        "explicit_runs": [{"class": "fixture", "path": "runs/selected"}],
        "discovered_run_groups": [],
        "adequate_raw_input": {
            "required_run_manifest": "run_manifest.json",
            "snapshot_candidates": ["csv/pps_snapshots.csv"],
            "count_candidates": ["csv/count_observations.csv"],
            "minimum_snapshot_rows": 2,
        },
    }
    path = tmp_path / "corpus.json"
    path.write_text(json.dumps(corpus), encoding="utf-8")
    return path


def test_declared_fixture_runs_selected_firmware_parity_and_cli_report(tmp_path: Path) -> None:
    corpus = _write_fixture(tmp_path)
    harness = parity.compile_harness(tmp_path / "selected_preview")

    report = parity.run_corpus(corpus, repo_root=tmp_path, harness=harness)

    assert report["status"] == "passed"
    assert report["declared_run_count"] == 1
    assert report["eligible_run_count"] == 1
    assert report["boundary_count"] == 3
    assert report["mismatch_count"] == 0
    assert report["runs"][0]["sources_unchanged"] is True
    assert set(report["firmware_sources"]) == {"engine", "header", "harness"}

    output = tmp_path / "report.json"
    assert parity.main(
        [
            "--corpus",
            str(corpus),
            "--repo-root",
            str(tmp_path),
            "--harness",
            str(harness),
            "--output",
            str(output),
        ]
    ) == 0
    assert json.loads(output.read_text(encoding="utf-8"))["status"] == "passed"


def test_incompatible_static_firmware_rate_is_explicitly_not_eligible(tmp_path: Path) -> None:
    corpus = _write_fixture(tmp_path, nominal_hz=16_000_000)
    harness = parity.compile_harness(tmp_path / "selected_preview")

    report = parity.run_corpus(corpus, repo_root=tmp_path, harness=harness)

    assert report["eligible_run_count"] == 0
    assert report["ineligible_firmware_static_contract_run_count"] == 1
    assert report["runs"][0]["status"] == "ineligible_firmware_static_contract"


def test_unexpected_missing_source_fails_closed(tmp_path: Path) -> None:
    corpus = _write_fixture(tmp_path)
    (tmp_path / "runs/selected/csv/count_observations.csv").unlink()
    harness = parity.compile_harness(tmp_path / "selected_preview")

    report = parity.run_corpus(corpus, repo_root=tmp_path, harness=harness)

    assert report["status"] == "failed"
    assert report["failed_run_count"] == 1
    assert report["runs"][0]["error"] == "a Stage 2 replay source is now missing"


def test_first_mismatches_are_bounded(tmp_path: Path, monkeypatch) -> None:
    corpus = _write_fixture(tmp_path)
    harness = parity.compile_harness(tmp_path / "selected_preview")
    monkeypatch.setattr(parity, "compare_engine_output", lambda *_args: ["forced mismatch"])

    report = parity.run_corpus(
        corpus,
        repo_root=tmp_path,
        harness=harness,
        max_mismatches=1,
    )

    assert report["status"] == "failed"
    assert report["mismatch_count"] == 3
    assert len(report["runs"][0]["first_mismatches"]) == 1
