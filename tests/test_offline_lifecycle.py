"""Offline failure cannot require reacquisition or mutate a sealed source."""

import json
import shutil
from hashlib import sha256
from pathlib import Path

import pytest

from host.otis_tools import offline
from host.otis_tools.adaptive_hybrid_analyze import analyze
from host.otis_tools.evidence_package import validate_package
from host.otis_tools.run_loader import load_manifest
from tests.capture_fixtures import write_simulated_run


def _closed_run(root: Path) -> Path:
    root.mkdir()
    write_simulated_run(root)
    (root / "raw").mkdir()
    counters = {
        "bytes_written": 44,
        "lines_seen": 1,
        "lines_parsed": 0,
        "malformed_utf8": 0,
        "parser_errors": 0,
        "reconnect_count": 0,
        "commands_sent": 0,
        "commands_rejected": 0,
        "emergency_aborts_sent": 0,
    }
    marker = {
        "event": "capture_stopped",
        "utc": "2026-09-12T10:02:00Z",
        **counters,
        "normal_command_buffered_bytes_discarded": 0,
        "emergency_abort_latched": False,
        "owner_pid": 42,
        "transport_generation": 1,
    }
    (root / "raw/serial.log").write_text(
        "retained incomplete scientific observations\n"
        + "# OTIS_HOST "
        + json.dumps(marker, sort_keys=True)
        + "\n"
    )
    (root / "reports").mkdir()
    (root / "reports/capture_segment_closure_v1.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "protocol": "otis_capture_closure_v1",
                "closed_utc": "2026-09-12T10:02:00Z",
                "run": str(root),
                "logical_segment_closed": True,
                "physical_serial_open": False,
                "run_manifest_sha256": sha256(
                    (root / "run_manifest.json").read_bytes()
                ).hexdigest(),
                "device": "/dev/ttys999",
                "baud": 115200,
                "owner_pid": 42,
                "transport_generation": 1,
                "closure_mode": "physical_serial_close",
                "serial_reopened": False,
                "counters": counters,
            }
        )
    )
    return root


def test_failed_analysis_seals_diagnostic_without_claiming_scientific_pass(tmp_path):
    run = _closed_run(tmp_path / "acquisition")
    raw = (run / "raw/serial.log").read_bytes()
    result = offline.finish_run(run)
    assert Path(result["package_directory"]) == run.resolve()
    assert Path(result["package_manifest"]) == run.resolve() / "evidence_package_v1.json"
    assert validate_package(Path(result["package_directory"]))["package_content_sha256"] == result["package_content_sha256"]
    assert result["capture"]["integrity"] == "complete"
    assert result["analysis"]["status"] == "review_required"
    assert result["analysis"]["outcome"] == "undetermined"
    assert (run / "raw/serial.log").read_bytes() == raw
    report = json.loads((run / "reports/offline_analysis_v1.json").read_text())
    assert report["failure_class"] == "offline_analysis_failure"
    assert report["firmware_authority"] is False
    analyzer_path = Path(
        __import__(
            "host.otis_tools.adaptive_hybrid_analyze", fromlist=["__file__"]
        ).__file__
    )
    assert report["analyzer"] == {
        "path": "host/otis_tools/adaptive_hybrid_analyze.py",
        "sha256": sha256(analyzer_path.read_bytes()).hexdigest(),
    }
    assert not list((run / "reports").glob(".offline-analysis-*"))
    assert (
        validate_package(run)["package_content_sha256"]
        == result["package_content_sha256"]
    )


def test_analyzer_identity_is_checked_before_analysis_report_creation(
    tmp_path, monkeypatch
):
    run = _closed_run(tmp_path / "acquisition")
    monkeypatch.setattr(
        offline,
        "_verify_frozen_analyzer",
        lambda _root: (_ for _ in ()).throw(ValueError("frozen analyzer differs")),
    )
    monkeypatch.setattr(
        offline,
        "analyze",
        lambda _root: pytest.fail("mismatched analyzer was invoked"),
    )
    result = offline.finish_run(run)
    report = json.loads((run / "reports/offline_analysis_v1.json").read_text())
    assert result["analysis"]["status"] == "review_required"
    assert report["failure_class"] == "offline_analysis_failure"
    assert report["error"] == "frozen analyzer differs"


def test_package_retry_only_validates_and_retries_optional_registration(
    tmp_path, monkeypatch
):
    run = _closed_run(tmp_path / "acquisition")
    first = offline.finish_run(run)
    before = {p.relative_to(run): p.read_bytes() for p in run.rglob("*") if p.is_file()}
    monkeypatch.setattr(
        offline, "analyze", lambda _: pytest.fail("sealed package was reanalysed")
    )
    monkeypatch.setattr(
        offline,
        "register_package",
        lambda *_: (_ for _ in ()).throw(OSError("registry unavailable")),
    )
    second = offline.finish_run(run, registry_path=tmp_path / "external-registry.json")
    assert second["package_content_sha256"] == first["package_content_sha256"]
    assert second["registration"]["status"] == "failed"
    assert before == {
        p.relative_to(run): p.read_bytes() for p in run.rglob("*") if p.is_file()
    }


def test_run_and_seal_relocate_without_rewriting_spec_or_record(tmp_path):
    original = _closed_run(tmp_path / "original")
    first = offline.finish_run(original)
    moved = tmp_path / "other-machine" / "renamed-run"
    shutil.copytree(original, moved)
    shutil.rmtree(original)
    manifest = load_manifest(moved)
    assert manifest.run_id == "original"
    assert manifest.data["host"]["serial_device"] == "/dev/ttys999"
    assert (
        validate_package(moved)["package_content_sha256"]
        == first["package_content_sha256"]
    )
    with pytest.raises(ValueError, match="sealed evidence is immutable"):
        analyze(moved)


def test_active_capture_cannot_be_finalized_by_offline_tools(tmp_path):
    run = _closed_run(tmp_path / "acquisition")
    (run / "capture_in_progress.flag").touch()
    with pytest.raises(ValueError, match="cannot close"):
        offline.finish_run(run)
    assert not (run / "reports/offline_analysis_v1.json").exists()


def test_offline_finalization_rejects_symlink_run_root(tmp_path):
    run = _closed_run(tmp_path / "acquisition")
    alias = tmp_path / "run-alias"
    alias.symlink_to(run, target_is_directory=True)
    with pytest.raises(ValueError, match="symlink run directory"):
        offline.finish_run(alias)
    assert not (run / "evidence_package_v1.json").exists()
