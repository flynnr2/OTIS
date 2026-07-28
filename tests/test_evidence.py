from __future__ import annotations

import json
from pathlib import Path
import shutil

import pytest

from host.otis_tools.evidence import EVIDENCE_MANIFEST, EvidenceError, create_evidence_snapshot
from host.otis_tools.validate_run import validate_run


EXAMPLE = Path("examples/h0_pps_tcxo_synthetic")


def _completed_run(tmp_path: Path, name: str = "run") -> Path:
    run_dir = tmp_path / name
    shutil.copytree(EXAMPLE, run_dir)
    (run_dir / "COMPLETE").touch()
    return run_dir


def _snapshot(run_dir: Path) -> dict:
    return json.loads((run_dir / EVIDENCE_MANIFEST).read_text(encoding="utf-8"))


def test_snapshot_is_deterministic_and_covers_profile_and_declared_evidence(tmp_path: Path) -> None:
    first = _completed_run(tmp_path, "first")
    second = _completed_run(tmp_path, "second")

    create_evidence_snapshot(first)
    create_evidence_snapshot(second)

    assert _snapshot(first) == _snapshot(second)
    artifacts = {entry["path"]: entry for entry in _snapshot(first)["artifacts"]}
    assert artifacts["run_manifest.json"]["role"] == "run_manifest"
    assert artifacts["raw_events.csv"]["contract"] == "raw_events_v1"
    assert artifacts["selected_profile.yaml"]["role"] == "profile_snapshot"
    assert validate_run(first) == 0


def test_snapshot_covers_raw_bytes_and_detects_later_mutation(tmp_path: Path, capsys) -> None:
    run_dir = _completed_run(tmp_path)
    (run_dir / "raw").mkdir()
    raw_log = run_dir / "raw" / "serial.log"
    raw_log.write_bytes(b"preserved raw bytes\n")
    create_evidence_snapshot(run_dir)

    raw_log.write_bytes(b"changed raw bytes\n")

    assert validate_run(run_dir) == 1
    assert "raw/serial.log: SHA-256 differs from evidence snapshot" in capsys.readouterr().err


def test_snapshot_detects_manifest_mutation_and_new_unsealed_raw_evidence(tmp_path: Path, capsys) -> None:
    run_dir = _completed_run(tmp_path)
    create_evidence_snapshot(run_dir)
    manifest_path = run_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["operator_notes"] = "changed after sealing"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (run_dir / "raw").mkdir()
    (run_dir / "raw" / "late.log").write_text("late evidence\n", encoding="utf-8")

    assert validate_run(run_dir) == 1
    errors = capsys.readouterr().err
    assert "run_manifest.json: SHA-256 differs from evidence snapshot" in errors
    assert "raw/late.log: evidence-bearing artifact is not covered" in errors


def test_snapshot_refuses_in_progress_incomplete_and_overwrite(tmp_path: Path) -> None:
    run_dir = _completed_run(tmp_path)
    (run_dir / "capture_in_progress.flag").touch()
    with pytest.raises(EvidenceError, match="in progress"):
        create_evidence_snapshot(run_dir)

    (run_dir / "capture_in_progress.flag").unlink()
    (run_dir / "COMPLETE").unlink()
    with pytest.raises(EvidenceError, match="COMPLETE"):
        create_evidence_snapshot(run_dir)

    create_evidence_snapshot(run_dir, allow_incomplete=True)
    assert _snapshot(run_dir)["run_state"] == "partial"
    with pytest.raises(FileExistsError, match="already exists"):
        create_evidence_snapshot(run_dir, allow_incomplete=True)


def test_validator_warns_when_legacy_run_has_no_snapshot(tmp_path: Path, capsys) -> None:
    run_dir = _completed_run(tmp_path)

    assert validate_run(run_dir) == 0
    assert "immutable evidence snapshot is missing" in capsys.readouterr().err


def test_snapshot_rejects_manifest_path_escape(tmp_path: Path) -> None:
    run_dir = _completed_run(tmp_path)
    manifest_path = run_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["path"] = "../outside.csv"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(EvidenceError, match="normalized run-relative"):
        create_evidence_snapshot(run_dir)


def test_snapshot_rejects_declared_artifact_through_symlink(tmp_path: Path) -> None:
    run_dir = _completed_run(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "evidence.csv").write_text("not run-local\n", encoding="utf-8")
    (run_dir / "linked").symlink_to(outside, target_is_directory=True)
    manifest_path = run_dir / "run_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["path"] = "linked/evidence.csv"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(EvidenceError, match="symbolic link"):
        create_evidence_snapshot(run_dir)
