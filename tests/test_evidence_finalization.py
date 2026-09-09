from __future__ import annotations

from pathlib import Path
import json

import pytest

from host.otis_tools.evidence_finalization import (
    PHASES,
    advance_phase,
    begin_finalization,
    journal_path_for,
    record_failure,
    recover_registration,
    set_registration_intent,
)
from host.otis_tools.evidence_index import load_index, package_identity
from host.otis_tools.evidence import (
    FIRMWARE_PROVENANCE_FORMAT,
    FIRMWARE_PROVENANCE_STATUS_FIELDS,
)


ROOT = Path(__file__).resolve().parents[1]


def _registration() -> dict[str, str]:
    return {
        "source_revision": "revision",
        "build_identity": "build",
        "image_identity": "adaptive_hybrid_regulation",
        "attempt_classification": "diagnostic",
        "result_or_failure_reason": "retained diagnostic package",
        "analyzer_identity": "analyzer",
    }


def _completed_registration() -> dict[str, str]:
    return {
        **_registration(),
        "attempt_classification": "completed_campaign",
        "result_or_failure_reason": "adaptive_hybrid_qualified_complete",
    }


def test_evidence_provenance_uses_fixed_image_identity_without_profile_artifacts() -> None:
    assert FIRMWARE_PROVENANCE_FORMAT == "otis_fixed_firmware_build_v1"
    assert FIRMWARE_PROVENANCE_STATUS_FIELDS[("build", "image_id")] == (
        "image_id"
    )
    assert all("profile" not in key and "profile" not in value for key, value in (
        (field[1], output)
        for field, output in FIRMWARE_PROVENANCE_STATUS_FIELDS.items()
    ))

    schema = json.loads(
        (ROOT / "schemas/run_evidence_v1.schema.json").read_text(encoding="utf-8")
    )
    provenance = schema["properties"]["firmware_build_provenance"]
    assert "image_id" in provenance["required"]
    assert "profile_id" not in provenance["required"]
    assert set(schema["properties"]["artifacts"]["items"]["properties"]["role"]["enum"]) == {
        "run_manifest",
        "raw_evidence",
        "declared_artifact",
        "completion_marker",
        "retained_evidence",
    }


@pytest.mark.parametrize("failed_phase", PHASES)
def test_failure_at_each_phase_preserves_the_primary_failure(
    tmp_path: Path, failed_phase: str
) -> None:
    run = tmp_path / f"run-{failed_phase}"
    run.mkdir()
    path = begin_finalization(
        run_dir=run,
        index_path=tmp_path / "external" / "index.json",
        registration=_registration(),
        required_seal=Path("reports/seal.json"),
    )
    for phase in PHASES[: PHASES.index(failed_phase)]:
        advance_phase(path, phase, {"phase": phase})

    primary = record_failure(
        path, phase=failed_phase, error=RuntimeError("primary failure")
    )
    secondary = record_failure(
        path, phase=failed_phase, error=OSError("secondary cleanup failure")
    )

    assert primary["primary_failure"]["error"] == "primary failure"
    assert secondary["primary_failure"]["error"] == "primary failure"
    assert secondary["secondary_failures"][-1]["error"] == (
        "secondary cleanup failure"
    )
    assert begin_finalization(
        run_dir=run,
        index_path=tmp_path / "external" / "index.json",
        registration=_registration(),
        required_seal=Path("reports/seal.json"),
    ) == path


def test_sealed_package_registration_is_discoverable_and_idempotent(
    tmp_path: Path,
) -> None:
    run = tmp_path / "run"
    (run / "reports").mkdir(parents=True)
    (run / "COMPLETE").write_text("complete\n", encoding="utf-8")
    (run / "evidence_manifest.json").write_text("{}\n", encoding="utf-8")
    (run / "reports/seal.json").write_text("{}\n", encoding="utf-8")
    index = tmp_path / "external" / "index.json"
    journal = begin_finalization(
        run_dir=run,
        index_path=index,
        registration=_registration(),
        required_seal=Path("reports/seal.json"),
    )
    for phase in PHASES[:-1]:
        advance_phase(journal, phase, {"phase": phase})
    identity = package_identity(run)["content_sha256"]
    set_registration_intent(
        journal,
        registration=_registration(),
        expected_content_sha256=identity,
    )

    first = recover_registration(journal)
    second = recover_registration(journal)

    assert first["content_sha256"] == identity
    assert second["content_sha256"] == identity
    assert set(load_index(index)["packages"]) == {identity}
    assert journal_path_for(run) == journal


def test_recovery_refuses_a_mutated_sealed_package(tmp_path: Path) -> None:
    run = tmp_path / "run"
    (run / "reports").mkdir(parents=True)
    (run / "COMPLETE").write_text("complete\n", encoding="utf-8")
    (run / "evidence_manifest.json").write_text("{}\n", encoding="utf-8")
    (run / "reports/seal.json").write_text("{}\n", encoding="utf-8")
    journal = begin_finalization(
        run_dir=run,
        index_path=tmp_path / "external" / "index.json",
        registration=_registration(),
        required_seal=Path("reports/seal.json"),
    )
    for phase in PHASES[:-1]:
        advance_phase(journal, phase, {})
    set_registration_intent(
        journal,
        registration=_registration(),
        expected_content_sha256=package_identity(run)["content_sha256"],
    )
    (run / "late.txt").write_text("mutation\n", encoding="utf-8")

    with pytest.raises(ValueError, match="differs from registration intent"):
        recover_registration(journal)


def test_recovery_cannot_promote_an_unvalidated_package_to_completed_campaign(
    tmp_path: Path,
) -> None:
    run = tmp_path / "run"
    index = tmp_path / "external" / "index.json"
    seal = Path("reports/adaptive_hybrid_physical_seal_v1.json")
    (run / seal.parent).mkdir(parents=True)
    (run / "COMPLETE").write_text("{}\n", encoding="utf-8")
    (run / "evidence_manifest.json").write_text("{}\n", encoding="utf-8")
    (run / seal).write_text("{}\n", encoding="utf-8")
    journal = begin_finalization(
        run_dir=run,
        index_path=index,
        registration=_completed_registration(),
        required_seal=seal,
    )
    for phase in PHASES[:-1]:
        advance_phase(journal, phase, {})
    set_registration_intent(
        journal,
        registration=_completed_registration(),
        expected_content_sha256=package_identity(run)["content_sha256"],
    )

    with pytest.raises(
        ValueError, match="successful evidence registration requires"
    ):
        recover_registration(journal)
    assert not index.exists()
