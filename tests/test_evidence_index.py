from __future__ import annotations

from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
from hashlib import sha256
import json

import pytest

from host.otis_tools import adaptive_hybrid_activation
from host.otis_tools.evidence import create_evidence_snapshot
from host.otis_tools.evidence_index import (
    CURRENT_SEAL_PATH,
    _parser,
    load_index,
    mothball_package,
    package_identity,
    register_package,
    validate_index,
)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True) + "\n", encoding="utf-8")


def test_register_cli_uses_exact_image_identity_option(tmp_path: Path) -> None:
    args = _parser().parse_args(
        [
            "--index", str(tmp_path / "index.json"), "register", str(tmp_path / "run"),
            "--source-revision", "revision-1", "--build-identity", "build-1",
            "--image-identity", "adaptive_hybrid_regulation",
            "--attempt-classification", "successful_rehearsal",
            "--result-or-failure-reason", "passed", "--analyzer-identity", "analyzer-1",
        ]
    )
    assert args.image_identity == "adaptive_hybrid_regulation"
    with pytest.raises(SystemExit):
        _parser().parse_args(
            [
                "--index", str(tmp_path / "index.json"), "register", str(tmp_path / "run"),
                "--source-revision", "revision-1", "--build-identity", "build-1",
                "--profile-identity", "adaptive_hybrid_regulation",
                "--attempt-classification", "successful_rehearsal",
                "--result-or-failure-reason", "passed", "--analyzer-identity", "analyzer-1",
            ]
        )


def _register(index_path: Path, package: Path) -> dict:
    return register_package(
        index_path=index_path,
        package_path=package,
        source_revision="revision-1",
        build_identity="build-sha256-1",
        image_identity="adaptive_hybrid_regulation",
        attempt_classification="diagnostic",
        result_or_failure_reason="raw diagnostic evidence retained",
        analyzer_identity="platform-rehearsal-analyzer-1",
    )


def _parallel_register(arguments: tuple[str, str]) -> str:
    index, package = arguments
    return str(_register(Path(index), Path(package))["content_sha256"])


def test_package_identity_is_recursive_deterministic_and_content_addressed(
    tmp_path: Path,
) -> None:
    package = tmp_path / "run"
    package.mkdir()
    (package / "b.txt").write_text("two\n", encoding="utf-8")
    nested = package / "nested"
    nested.mkdir()
    (nested / "a.txt").write_text("one\n", encoding="utf-8")

    first = package_identity(package)
    second = package_identity(package)
    assert first == second
    assert first["file_count"] == 2
    assert [entry["relative_path"] for entry in first["files"]] == [
        "b.txt",
        "nested/a.txt",
    ]

    (nested / "a.txt").write_text("changed\n", encoding="utf-8")
    assert package_identity(package)["content_sha256"] != first["content_sha256"]


def test_register_validate_and_detect_package_mutation(tmp_path: Path) -> None:
    index_path = tmp_path / "external" / "index.json"
    package = tmp_path / "run"
    package.mkdir()
    evidence = package / "raw.csv"
    evidence.write_text("record\n", encoding="utf-8")

    record = _register(index_path, package)
    assert record["lifecycle_status"] == "active"
    assert validate_index(index_path)["valid"] is True

    evidence.write_text("mutated\n", encoding="utf-8")
    validation = validate_index(index_path)
    assert validation["valid"] is False
    assert validation["packages"][0]["locations"][0]["status"] == "mismatch"


def test_duplicate_content_rejects_conflicting_provenance(tmp_path: Path) -> None:
    index_path = tmp_path / "index.json"
    package = tmp_path / "run"
    package.mkdir()
    (package / "raw.csv").write_text("record\n", encoding="utf-8")
    _register(index_path, package)

    with pytest.raises(ValueError, match="different source_revision"):
        register_package(
            index_path=index_path,
            package_path=package,
            source_revision="other-revision",
            build_identity="build-sha256-1",
            image_identity="adaptive_hybrid_regulation",
            attempt_classification="diagnostic",
            result_or_failure_reason="all rehearsal gates passed",
            analyzer_identity="platform-rehearsal-analyzer-1",
        )


@pytest.mark.parametrize(
    "classification",
    ("successful_rehearsal", "successful_qualification", "completed_campaign"),
)
def test_success_classification_rejects_arbitrary_unsealed_directory(
    tmp_path: Path, classification: str
) -> None:
    package = tmp_path / "run"
    package.mkdir()
    (package / "raw.csv").write_text("record\n", encoding="utf-8")

    with pytest.raises(
        ValueError, match="successful evidence registration requires"
    ):
        register_package(
            index_path=tmp_path / "index.json",
            package_path=package,
            source_revision="revision-1",
            build_identity="build-sha256-1",
            image_identity="adaptive_hybrid_regulation",
            attempt_classification=classification,
            result_or_failure_reason="claimed success",
            analyzer_identity="analyzer-1",
        )
    assert not (tmp_path / "index.json").exists()


def test_successful_qualification_derives_validation_from_completed_package(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    run = tmp_path / "run"
    (run / "raw").mkdir(parents=True)
    raw = run / "raw/serial.log"
    raw.write_text("retained serial evidence\n", encoding="utf-8")
    analyzer_identity = "a" * 64
    source_revision = "1" * 40
    build_identity = "source:configuration"
    primary_decision = "adaptive_hybrid_qualified_complete"
    manifest = {
        "schema_version": 1,
        "evidence_epoch": "OTIS_ADAPTIVE_HYBRID_EVIDENCE_EPOCH_1",
        "template": False,
        "run_id": run.name,
        "stage": "OTIS_ADAPTIVE_HYBRID_REGULATION_LIVE",
        "programme_id": "OTIS_ADAPTIVE_HYBRID_REGULATION_V1",
        "run_identity": "adaptive_hybrid_regulation:1",
        "image_identity": "adaptive_hybrid_regulation",
        "adaptive_hybrid": {"profile_id": "adaptive_hybrid_regulation"},
        "firmware": {
            "source_revision": source_revision,
            "build_identity": build_identity,
        },
        "policy": {"policy_id": "OTIS_ADAPTIVE_HYBRID_REGULATION_V1"},
        "host": {
            "tool_bindings": {
                "adaptive_hybrid_analyze": {"sha256": analyzer_identity}
            }
        },
        "files": [{"path": "raw/serial.log"}],
    }
    _write_json(run / "run_manifest.json", manifest)
    completion = {
        "completion": "adaptive_hybrid_finite_physical_campaign",
        "terminal": {
            "result": "healthy_stop",
            "reason": primary_decision,
        },
        "orchestration_error": None,
    }
    _write_json(run / "COMPLETE", completion)
    snapshot_path = create_evidence_snapshot(run)
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    seal = {
        "schema_version": 1,
        "seal_type": "adaptive_hybrid_physical_seal_v1",
        "tool": "adaptive_hybrid_analyze_v1",
        "tool_sha256": analyzer_identity,
        "created_utc": "2026-09-09T00:00:00Z",
        "run_id": run.name,
        "run_identity": manifest["run_identity"],
        "build_identity": build_identity,
        "image_identity": manifest["image_identity"],
        "programme_id": manifest["programme_id"],
        "policy_id": manifest["policy"]["policy_id"],
        "status": "passed",
        "primary_decision": primary_decision,
        "terminal_result": "healthy_stop",
        "terminal_reason": primary_decision,
        "checks": {"all_current_checks": True},
        "csv_validation": {},
        "exact_lifecycle_records": {},
        "maintenance_replay": {},
        "measurement_replay": {},
        "response_replay": {},
        "transaction_capsule_sha256": {},
        "evidence_snapshot": {
            "path": "evidence_manifest.json",
            "failures": [],
            "warnings": [],
        },
        "source_sha256": {"raw/serial.log": sha256(raw.read_bytes()).hexdigest()},
        "D10_semantics": {},
        "limitations": [],
    }
    seal["seal_sha256"] = sha256(
        json.dumps(seal, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    _write_json(run / CURRENT_SEAL_PATH, seal)
    monkeypatch.setattr(
        adaptive_hybrid_activation,
        "validate_frozen_run_manifest",
        lambda _path: manifest,
    )

    with pytest.raises(ValueError, match="metadata differs"):
        register_package(
            index_path=tmp_path / "external/index.json",
            package_path=run,
            source_revision=source_revision,
            build_identity=build_identity,
            image_identity="adaptive_hybrid_regulation",
            attempt_classification="successful_qualification",
            result_or_failure_reason=f"qualified: {primary_decision}",
            analyzer_identity="b" * 64,
        )

    record = register_package(
        index_path=tmp_path / "external/index.json",
        package_path=run,
        source_revision=source_revision,
        build_identity=build_identity,
        image_identity="adaptive_hybrid_regulation",
        attempt_classification="successful_qualification",
        result_or_failure_reason=f"qualified: {primary_decision}",
        analyzer_identity=analyzer_identity,
    )

    assert record["package_validation"] == {
        "contract": "otis_validated_success_package_v1",
        "evidence_snapshot_sha256": snapshot["snapshot_digest"],
        "seal_path": CURRENT_SEAL_PATH.as_posix(),
        "seal_sha256": seal["seal_sha256"],
        "seal_status": "passed",
        "primary_decision": primary_decision,
    }


def test_mothball_requires_dependency_confirmation_and_reviewed_summary(
    tmp_path: Path,
) -> None:
    index_path = tmp_path / "index.json"
    package = tmp_path / "run"
    package.mkdir()
    (package / "raw.csv").write_text("record\n", encoding="utf-8")
    record = _register(index_path, package)
    summary = tmp_path / "summary.md"
    summary.write_text("Reviewed result.\n", encoding="utf-8")

    with pytest.raises(ValueError, match="no active dependency"):
        mothball_package(
            index_path=index_path,
            content_sha256=record["content_sha256"],
            reviewed_summary_path=summary,
            reason="superseded by reviewed result",
            confirm_no_active_dependency=False,
        )

    updated = mothball_package(
        index_path=index_path,
        content_sha256=record["content_sha256"],
        reviewed_summary_path=summary,
        reason="superseded by reviewed result",
        confirm_no_active_dependency=True,
    )
    assert updated["lifecycle_status"] == "mothballed"
    assert updated["mothball"]["reviewed_summary_sha256"]


def test_index_is_never_allowed_inside_git_repository(tmp_path: Path) -> None:
    package = tmp_path / "run"
    package.mkdir()
    with pytest.raises(ValueError, match="outside the Git repository"):
        load_index(Path(__file__).resolve().parents[1] / "evidence-index.json")


def test_parallel_registration_preserves_every_package(tmp_path: Path) -> None:
    index_path = tmp_path / "external" / "index.json"
    packages: list[Path] = []
    for ordinal in range(12):
        package = tmp_path / f"run-{ordinal}"
        package.mkdir()
        (package / "raw.csv").write_text(f"record-{ordinal}\n", encoding="utf-8")
        packages.append(package)

    with ProcessPoolExecutor(max_workers=6) as executor:
        identities = list(
            executor.map(
                _parallel_register,
                [(str(index_path), str(package)) for package in packages],
            )
        )

    index = load_index(index_path)
    assert len(set(identities)) == 12
    assert set(index["packages"]) == set(identities)
    assert validate_index(index_path)["valid"] is True
