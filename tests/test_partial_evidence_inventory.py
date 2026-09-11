"""Partial capture keeps the canonical evidence scope without claiming success."""
from __future__ import annotations

import csv
from hashlib import sha256
import json
from pathlib import Path

import pytest

from host.otis_tools.adaptive_hybrid_run import _create_partial_evidence_snapshot
from host.otis_tools.evidence import (
    EvidenceError, FIRMWARE_PROVENANCE_FORMAT, FIRMWARE_PROVENANCE_STATUS_FIELDS,
    create_evidence_snapshot, create_partial_evidence_snapshot,
    validate_evidence_snapshot,
)
from host.otis_tools.run_loader import RunManifest


def retained_run(tmp_path: Path, *, malformed_provenance=False) -> RunManifest:
    run = tmp_path / "run"
    for directory in ("raw", "csv", "reports", "carrier"):
        (run / directory).mkdir(parents=True)
    (run / "raw/serial.log").write_bytes(b"unchanged raw observations\r\n")
    (run / "reports/diagnostic.json").write_text('{"retained_fault": true}\n')
    (run / "carrier/board.json").write_text('{"board": "retained"}\n')
    (run / "COMPLETE").write_text("partial capture closed\n")
    health = run / "csv/health.csv"
    with health.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(("component", "status_key", "status_value"))
        writer.writerow(("build", "provenance_format",
            "malformed" if malformed_provenance else FIRMWARE_PROVENANCE_FORMAT))
        for (component, key), output in FIRMWARE_PROVENANCE_STATUS_FIELDS.items():
            value = "fixture"
            if output == "git_commit":
                value = "a" * 40
            elif output.endswith("sha256") or output == "invocation_id":
                value = "b" * 64
            elif output == "source_state":
                value = "clean"
            writer.writerow((component, key, value))
    data = {
        "schema_version": 1, "run_id": run.name, "template": False,
        "evidence_epoch": "OTIS_ADAPTIVE_HYBRID_EVIDENCE_EPOCH_1",
        "stage": "OTIS_ADAPTIVE_HYBRID_REGULATION_LIVE",
        "programme_id": "OTIS_ADAPTIVE_HYBRID_REGULATION_V1",
        "image_identity": "adaptive_hybrid_regulation",
        "adaptive_hybrid": {"profile_id": "adaptive_hybrid_regulation"},
        "firmware": {"build_provenance_required": True},
        "files": [
            {"path": "csv/health.csv", "contract": "health_v1"},
            {"path": "csv/missing_counts.csv", "contract": "count_observations_v1"},
        ],
    }
    path = run / "run_manifest.json"
    path.write_text(json.dumps(data))
    return RunManifest(run, path, data)


def test_runner_partial_inventory_keeps_carrier_reports_and_emitted_provenance(tmp_path):
    manifest = retained_run(tmp_path)
    with pytest.raises(EvidenceError, match="required declared artifact is missing"):
        create_evidence_snapshot(manifest.root, allow_incomplete=True, manifest=manifest)
    snapshot_path = _create_partial_evidence_snapshot(manifest.root)
    snapshot = json.loads(snapshot_path.read_text())
    assert snapshot["run_state"] == "partial"
    artifacts = {item["path"]: item for item in snapshot["artifacts"]}
    assert {"raw/serial.log", "csv/health.csv", "reports/diagnostic.json",
            "carrier/board.json", "COMPLETE", "run_manifest.json"} == set(artifacts)
    for path, item in artifacts.items():
        assert item["sha256"] == sha256((manifest.root / path).read_bytes()).hexdigest()
    assert snapshot["firmware_build_provenance"]["source_sha256"] == "b" * 64
    failures, _ = validate_evidence_snapshot(manifest.root, manifest)
    assert any("required declared artifact is missing" in failure for failure in failures)
    assert not any("provenance" in failure for failure in failures)


def test_malformed_provenance_stays_retained_and_invalid_in_partial_snapshot(tmp_path):
    manifest = retained_run(tmp_path, malformed_provenance=True)
    health_before = (manifest.root / "csv/health.csv").read_bytes()
    snapshot = json.loads(create_partial_evidence_snapshot(manifest.root, manifest=manifest).read_text())
    assert "firmware_build_provenance" not in snapshot
    assert (manifest.root / "csv/health.csv").read_bytes() == health_before
    assert any(item["path"] == "csv/health.csv" for item in snapshot["artifacts"])
    failures, _ = validate_evidence_snapshot(manifest.root, manifest)
    assert any("unsupported emitted firmware provenance format" in failure for failure in failures)


@pytest.mark.parametrize("obstruction", ["capture_active", "symlink", "post_snapshot_artifact"])
def test_partial_inventory_preserves_capture_and_path_guards(tmp_path, obstruction):
    manifest = retained_run(tmp_path)
    if obstruction == "capture_active":
        (manifest.root / "capture_in_progress.flag").touch()
    elif obstruction == "symlink":
        (manifest.root / "carrier/escape").symlink_to(tmp_path / "outside")
    else:
        (manifest.root / "reports/adaptive_hybrid_physical_seal_v1.json").write_text("{}")
    with pytest.raises(EvidenceError):
        create_partial_evidence_snapshot(manifest.root, manifest=manifest)
    assert not (manifest.root / "evidence_manifest.json").exists()
