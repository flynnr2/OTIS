"""Publish an offline-only analysis addendum without mutating source evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any

from .adaptive_hybrid_analyze import DEFAULT_SEAL, analyze
from .evidence import package_identity
from .evidence_finalization import journal_path_for
from .evidence_index import (
    ANALYSIS_SUPERSESSION_JOURNAL,
    ANALYSIS_SUPERSESSION_TOOL_MODULES,
    load_index,
    register_analysis_supersession,
    source_registration_projection,
    validate_completed_diagnostic_journal,
    validate_index_location,
)


TOOL_ID = "adaptive_hybrid_analysis_supersession_v1"
REPORT_NAME = "adaptive_hybrid_analysis_supersession_v1.json"
CORRECTED_SEAL_NAME = "adaptive_hybrid_physical_seal_superseding_v1.json"
SUPERSESSION_REASON = (
    "deterministic_offline_consumer_contract_correction:"
    "firmware_binary64_measurement_projection_and_inhibited_zero_write_"
    "maintenance_applicability"
)
REPO_ROOT = Path(__file__).resolve().parents[2]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} does not contain an object")
    return value


def _atomic_new_json(path: Path, value: dict[str, Any]) -> None:
    from .adaptive_hybrid_analyze import _atomic_new_json

    _atomic_new_json(path, value)


def _atomic_copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    with source.open("rb") as input_stream, tempfile.NamedTemporaryFile(
        "wb",
        dir=destination.parent,
        prefix=f".{destination.name}.",
        suffix=".tmp",
        delete=False,
    ) as output_stream:
        for block in iter(lambda: input_stream.read(1024 * 1024), b""):
            output_stream.write(block)
        output_stream.flush()
        os.fsync(output_stream.fileno())
        temporary = Path(output_stream.name)
    try:
        os.link(temporary, destination)
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def _decision_tool_sha256() -> dict[str, str]:
    module_root = Path(__file__).resolve().parent
    return {
        name: _sha256_file(module_root / f"{name}.py")
        for name in sorted(ANALYSIS_SUPERSESSION_TOOL_MODULES)
    }


def _current_host_source() -> dict[str, str]:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=normal"],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout
    if status:
        raise ValueError("analysis supersession requires a clean host source tree")
    if len(revision) != 40:
        raise ValueError("analysis supersession host source revision is malformed")
    return {"revision": revision, "source_state": "clean"}


def _original_registration(
    *, index_path: Path, source_content_sha256: str, source_run_dir: Path,
) -> dict[str, Any]:
    index = load_index(index_path)
    record = index["packages"].get(source_content_sha256)
    if not (
        isinstance(record, dict)
        and record.get("attempt_classification") == "diagnostic"
        and str(source_run_dir) in record.get("storage_locations", [])
    ):
        raise ValueError(
            "analysis supersession requires the exact registered diagnostic package"
        )
    return record


def _default_addendum_dir(
    source_run_dir: Path,
    *,
    source_content_sha256: str,
    decision_toolset_sha256: str,
) -> Path:
    return (
        source_run_dir.parent
        / ".otis-analysis-supersessions"
        / (
            f"{source_run_dir.name}-{source_content_sha256[:12]}-"
            f"{decision_toolset_sha256[:12]}"
        )
    )


def _prepare_addendum_directory(source: Path, destination: Path) -> None:
    if (
        destination == source
        or source in destination.parents
        or destination in source.parents
    ):
        raise ValueError("analysis addendum must be outside the source package")
    allowed_entries = {
        CORRECTED_SEAL_NAME,
        REPORT_NAME,
        ANALYSIS_SUPERSESSION_JOURNAL.name,
    }
    if destination.exists():
        unexpected = sorted(
            path.name
            for path in destination.iterdir()
            if path.name not in allowed_entries
        )
        if unexpected:
            raise ValueError(
                "analysis addendum directory contains unexpected entries: "
                + ", ".join(unexpected)
            )
    else:
        destination.mkdir(parents=True)


def supersede_analysis(
    *,
    source_run_dir: Path,
    evidence_index_path: Path,
    addendum_dir: Path | None = None,
) -> dict[str, Any]:
    """Replay one exact diagnostic package and register a separate addendum."""

    source = source_run_dir.resolve()
    index_path = validate_index_location(evidence_index_path)
    if (source / "capture_in_progress.flag").exists():
        raise ValueError("cannot supersede analysis while capture is active")
    source_before = package_identity(source)
    source_manifest = _read_object(source / "run_manifest.json")
    original_seal_path = source / DEFAULT_SEAL
    original_seal = _read_object(original_seal_path)
    original_registration = _original_registration(
        index_path=index_path,
        source_content_sha256=source_before["content_sha256"],
        source_run_dir=source,
    )
    if (
        original_seal.get("status") != "review_required"
        or original_registration.get("analyzer_identity")
        != original_seal.get("tool_sha256")
    ):
        raise ValueError("source diagnostic seal or registration identity differs")

    finalization_journal_path = journal_path_for(source)
    finalization_journal_sha256 = _sha256_file(finalization_journal_path)
    finalization_journal = _read_object(finalization_journal_path)
    if (
        finalization_journal.get("expected_content_sha256")
        != source_before["content_sha256"]
        or any(
            finalization_journal.get("phases", {}).get(phase) is None
            for phase in (
                "capture_closed",
                "completion",
                "snapshot",
                "analysis",
                "seal",
                "registration",
            )
        )
    ):
        raise ValueError("source diagnostic finalization journal is not complete")
    validate_completed_diagnostic_journal(
        finalization_journal,
        source={
            "content_sha256": source_before["content_sha256"],
            "path": str(source),
        },
        original_seal=original_seal,
        source_manifest=source_manifest,
    )

    tool_hashes = _decision_tool_sha256()
    toolset_hash = _canonical_sha256(tool_hashes)
    current_host_source = _current_host_source()
    destination = (
        addendum_dir.resolve()
        if addendum_dir is not None
        else _default_addendum_dir(
            source,
            source_content_sha256=source_before["content_sha256"],
            decision_toolset_sha256=toolset_hash,
        )
    )
    _prepare_addendum_directory(source, destination)
    corrected_seal_path = destination / CORRECTED_SEAL_NAME
    report_path = destination / REPORT_NAME
    journal_copy_path = destination / ANALYSIS_SUPERSESSION_JOURNAL
    if journal_copy_path.is_file():
        if _sha256_file(journal_copy_path) != finalization_journal_sha256:
            raise ValueError("retained finalization journal copy differs")
    else:
        _atomic_copy(finalization_journal_path, journal_copy_path)
    if (
        _sha256_file(finalization_journal_path) != finalization_journal_sha256
        or _sha256_file(journal_copy_path) != finalization_journal_sha256
    ):
        raise RuntimeError("source finalization journal changed during retention")
    if corrected_seal_path.is_file():
        corrected_seal = _read_object(corrected_seal_path)
    else:
        corrected_seal_path, corrected_seal = analyze(
            source,
            output_path=corrected_seal_path,
            prior_review_seal_path=original_seal_path,
        )
    if (
        corrected_seal.get("status") != "passed"
        or corrected_seal.get("primary_decision") != "inhibited_zero_write_complete"
        or corrected_seal.get("tool_sha256")
        != tool_hashes["adaptive_hybrid_analyze"]
    ):
        raise ValueError("corrected offline analysis is not the exact passing result")
    source_after = package_identity(source)
    if source_after != source_before:
        raise RuntimeError("offline analysis changed the registered source package")

    if report_path.is_file():
        report = _read_object(report_path)
        registered = register_analysis_supersession(
            index_path=index_path,
            addendum_path=destination,
        )
        return {
            "status": corrected_seal["status"],
            "primary_decision": corrected_seal["primary_decision"],
            "source_content_sha256": source_before["content_sha256"],
            "source_package_unchanged": True,
            "original_seal_sha256": original_seal["seal_sha256"],
            "corrected_seal": str(corrected_seal_path),
            "corrected_seal_sha256": corrected_seal["seal_sha256"],
            "supersession_report": str(report_path),
            "supersession_sha256": report["supersession_sha256"],
            "addendum_content_sha256": registered["content_sha256"],
            "evidence_index": str(index_path),
            "physical_rerun": False,
            "device_or_actuator_io": False,
        }

    unsigned: dict[str, Any] = {
        "schema_version": 1,
        "report_type": TOOL_ID,
        "created_utc": _utc_now(),
        "supersession_reason": SUPERSESSION_REASON,
        "review_authority": "operator_authorized_deterministic_offline_repair",
        "acceptance_criterion_unchanged": True,
        "actionable": False,
        "actuation_authorized": False,
        "physical_rerun": False,
        "device_or_actuator_io": False,
        "hardware_interaction": False,
        "new_control_or_terminal_authority": False,
        "current_host_source": current_host_source,
        "source_package": {
            "path": str(source),
            "content_sha256": source_before["content_sha256"],
            "file_count": source_before["file_count"],
            "total_bytes": source_before["total_bytes"],
            "firmware_source_revision": source_manifest.get("firmware", {}).get(
                "source_revision"
            ),
            "source_sha256": corrected_seal["source_sha256"],
        },
        "original_index_registration": {
            "index_id": load_index(index_path)["index_id"],
            "immutable_record_sha256": _canonical_sha256(
                source_registration_projection(original_registration)
            ),
            "attempt_classification": original_registration[
                "attempt_classification"
            ],
            "analyzer_identity": original_registration["analyzer_identity"],
        },
        "original_finalization_journal": {
            "path": ANALYSIS_SUPERSESSION_JOURNAL.as_posix(),
            "source_path_at_supersession": str(finalization_journal_path),
            "file_sha256": _sha256_file(journal_copy_path),
            "primary_failure": finalization_journal.get("primary_failure"),
            "secondary_failures": finalization_journal.get("secondary_failures"),
        },
        "original_seal": {
            "path": DEFAULT_SEAL.as_posix(),
            "file_sha256": _sha256_file(original_seal_path),
            "seal_sha256": original_seal["seal_sha256"],
            "status": original_seal["status"],
            "primary_decision": original_seal["primary_decision"],
            "tool": original_seal["tool"],
            "tool_sha256": original_seal["tool_sha256"],
            "failed_checks": sorted(
                key
                for key, value in original_seal.get("checks", {}).items()
                if value is not True
            ),
        },
        "corrected_seal": {
            "path": CORRECTED_SEAL_NAME,
            "file_sha256": _sha256_file(corrected_seal_path),
            "seal_sha256": corrected_seal["seal_sha256"],
            "status": corrected_seal["status"],
            "primary_decision": corrected_seal["primary_decision"],
            "tool": corrected_seal["tool"],
            "tool_sha256": corrected_seal["tool_sha256"],
        },
        "decision_tool_sha256": tool_hashes,
        "decision_toolset_sha256": toolset_hash,
    }
    report = {**unsigned, "supersession_sha256": _canonical_sha256(unsigned)}
    _atomic_new_json(report_path, report)
    if package_identity(source) != source_before:
        raise RuntimeError("supersession publication changed the source package")
    registered = register_analysis_supersession(
        index_path=index_path,
        addendum_path=destination,
    )
    return {
        "status": corrected_seal["status"],
        "primary_decision": corrected_seal["primary_decision"],
        "source_content_sha256": source_before["content_sha256"],
        "source_package_unchanged": True,
        "original_seal_sha256": original_seal["seal_sha256"],
        "corrected_seal": str(corrected_seal_path),
        "corrected_seal_sha256": corrected_seal["seal_sha256"],
        "supersession_report": str(report_path),
        "supersession_sha256": report["supersession_sha256"],
        "addendum_content_sha256": registered["content_sha256"],
        "evidence_index": str(index_path),
        "physical_rerun": False,
        "device_or_actuator_io": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("source_run_dir", type=Path)
    parser.add_argument("--evidence-index", type=Path, required=True)
    parser.add_argument("--addendum-dir", type=Path)
    args = parser.parse_args(argv)
    result = supersede_analysis(
        source_run_dir=args.source_run_dir,
        evidence_index_path=args.evidence_index,
        addendum_dir=args.addendum_dir,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
