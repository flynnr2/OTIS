from __future__ import annotations

from pathlib import Path
from concurrent.futures import ProcessPoolExecutor

import pytest

from host.otis_tools.evidence_index import (
    load_index,
    mothball_package,
    package_identity,
    register_package,
    validate_index,
)


def _register(index_path: Path, package: Path) -> dict:
    return register_package(
        index_path=index_path,
        package_path=package,
        source_revision="revision-1",
        build_identity="build-sha256-1",
        profile_identity="fixed-code-profile-1",
        attempt_classification="successful_rehearsal",
        result_or_failure_reason="all rehearsal gates passed",
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
            profile_identity="fixed-code-profile-1",
            attempt_classification="successful_rehearsal",
            result_or_failure_reason="all rehearsal gates passed",
            analyzer_identity="platform-rehearsal-analyzer-1",
        )


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
