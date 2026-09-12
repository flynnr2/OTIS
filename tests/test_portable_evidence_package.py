from __future__ import annotations

import json
import os
import shutil
from hashlib import sha256
from pathlib import Path

import pytest

from host.otis_tools.evidence_package import (
    ANALYSIS_REPORT,
    seal_package,
    validate_package,
)
from host.otis_tools.evidence_registry import register_package
from tests.capture_fixtures import write_simulated_run


def _run(root: Path) -> Path:
    run = root / "run"
    write_simulated_run(run)
    for relative, value in {
        "config/frozen.json": {"profile": "test"},
        "raw/capture.log": "raw\n",
        "control/commands.jsonl": "{}\n",
    }.items():
        path = run / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(value) if isinstance(value, dict) else value)
    (run / "reports/capture_segment_closure_v1.json").parent.mkdir(
        parents=True, exist_ok=True
    )
    (run / "reports/capture_segment_closure_v1.json").write_text(
        json.dumps(
            {
                "historical_run": "/old/run",
                "logical_segment_closed": True,
                "physical_serial_open": False,
                "run_manifest_sha256": sha256(
                    (run / "run_manifest.json").read_bytes()
                ).hexdigest(),
            }
        )
    )
    return run


def test_seal_relocates_and_binds_every_regular_payload(tmp_path):
    run = _run(tmp_path)
    seal_package(run, analysis={"status": "passed", "outcome": "qualified_complete"})
    package = validate_package(run)
    assert package["capture"]["integrity"] == "complete"
    assert package["analysis"]["status"] == "passed"
    assert {entry["path"] for entry in package["inventory"]} >= {
        "run_manifest.json",
        "raw/capture.log",
        ANALYSIS_REPORT.as_posix(),
    }
    moved = tmp_path / "elsewhere" / "run"
    moved.parent.mkdir()
    shutil.copytree(run, moved)
    assert (
        validate_package(moved)["package_content_sha256"]
        == package["package_content_sha256"]
    )


def test_active_missing_analysis_and_late_analysis_are_not_passing(tmp_path):
    run = _run(tmp_path)
    (run / "capture_in_progress.flag").touch()
    with pytest.raises(ValueError, match="active capture"):
        seal_package(run)
    (run / "capture_in_progress.flag").unlink()
    seal_package(run)
    assert validate_package(run)["analysis"] == {
        "status": "review_required",
        "outcome": "undetermined",
    }
    with pytest.raises(FileExistsError, match="sealed package"):
        seal_package(
            run, analysis={"status": "passed", "outcome": "qualified_complete"}
        )


def test_seal_is_immutable_and_registry_is_external_idempotent(tmp_path):
    run = _run(tmp_path)
    seal = seal_package(
        run, analysis={"status": "review_required", "outcome": "bounded_nonpass"}
    )
    before = seal.read_bytes()
    registry = tmp_path / "registry.json"
    receipt = register_package(run, registry)
    assert register_package(run, registry) == receipt
    (run / "raw/capture.log").write_text("changed")
    with pytest.raises(ValueError, match="differs from immutable seal"):
        validate_package(run)
    assert seal.read_bytes() == before


def test_special_payload_is_rejected(tmp_path):
    run = _run(tmp_path)
    (run / "bad").symlink_to(run / "raw/capture.log")
    with pytest.raises(ValueError, match="link or special"):
        seal_package(run)


def test_closure_requires_explicit_closed_serial_and_manifest_bindings(tmp_path):
    run = _run(tmp_path)
    closure = run / "reports/capture_segment_closure_v1.json"
    closure.write_text(
        json.dumps(
            {
                "logical_segment_closed": True,
                "physical_serial_open": True,
                "run_manifest_sha256": "0" * 64,
            }
        )
    )
    seal_package(run)
    assert validate_package(run)["capture"]["integrity"] == "partial"


def test_only_declared_runtime_fifos_are_omitted_and_reported(tmp_path):
    run = _run(tmp_path)
    for relative in (
        "control/normal_commands.fifo",
        "control/emergency_abort.fifo",
    ):
        path = run / relative
        path.unlink(missing_ok=True)
        os.mkfifo(path)
    seal_package(run)
    package = validate_package(run)
    assert package["omitted_runtime_endpoints"] == [
        {"path": "control/emergency_abort.fifo", "type": "fifo"},
        {"path": "control/normal_commands.fifo", "type": "fifo"},
    ]

    unknown = _run(tmp_path / "unknown")
    os.mkfifo(unknown / "raw/undeclared.fifo")
    with pytest.raises(ValueError, match="undeclared FIFO"):
        seal_package(unknown)


def test_lock_nonfinite_and_run_spec_substitution_are_rejected(tmp_path):
    locked = _run(tmp_path / "lock")
    (locked / "capture.lock").touch()
    with pytest.raises(ValueError, match="undeclared lock"):
        seal_package(locked)

    nonfinite = _run(tmp_path / "nonfinite")
    (nonfinite / "run_manifest.json").write_text('{"run_spec":NaN}')
    with pytest.raises(ValueError, match="invalid run record"):
        seal_package(nonfinite)

    substituted = _run(tmp_path / "substituted")
    spec = json.loads((substituted / "run_spec.json").read_text())
    spec["created_utc"] = "2026-09-12T12:00:00Z"
    (substituted / "run_spec.json").write_text(json.dumps(spec))
    with pytest.raises(ValueError, match="run-spec byte binding differs"):
        seal_package(substituted)


@pytest.mark.parametrize(
    "malformed",
    [
        [],
        {"contract": "otis_evidence_registry_v1", "packages": []},
        {
            "contract": "otis_evidence_registry_v1",
            "packages": {
                "a" * 64: {
                    "package_content_sha256": "b" * 64,
                    "capture_integrity": "complete",
                    "analysis": {},
                    "locations": [],
                }
            },
        },
    ],
)
def test_registry_rejects_malformed_root_and_entries(tmp_path, malformed):
    run = _run(tmp_path / "source")
    seal_package(run)
    registry = tmp_path / "registry.json"
    registry.write_text(json.dumps(malformed))
    with pytest.raises(ValueError, match="registry"):
        register_package(run, registry)


def test_run_spec_semantic_identity_is_checked_independently_of_file_binding(tmp_path):
    run = _run(tmp_path)
    spec_path = run / "run_spec.json"
    spec = json.loads(spec_path.read_text())
    spec["created_utc"] = "2026-09-12T12:34:56Z"
    spec_path.write_text(json.dumps(spec))

    record_path = run / "run_manifest.json"
    record = json.loads(record_path.read_text())
    record["run_spec"]["file_sha256"] = sha256(spec_path.read_bytes()).hexdigest()
    record["run_spec"]["size_bytes"] = spec_path.stat().st_size
    unsigned = {
        key: value for key, value in record.items() if key != "run_record_sha256"
    }
    record["run_record_sha256"] = sha256(
        json.dumps(
            unsigned,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    ).hexdigest()
    record_path.write_text(json.dumps(record))

    with pytest.raises(ValueError, match="semantic identity differs"):
        seal_package(run)
