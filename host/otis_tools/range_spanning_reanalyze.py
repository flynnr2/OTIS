"""Create a provenance-linked host-only supersession for CX319 Part A evidence."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import subprocess
from typing import Any

from .evidence import validate_evidence_snapshot
from .evidence_index import (
    DEFAULT_INDEX,
    load_index,
    package_identity,
    register_package,
)
from .range_spanning_analyze import analyze
from .range_spanning_bundle import (
    _atomic_new_json,
    canonical_sha256,
    sha256_file,
    validate_bundle_for_offline_reanalysis,
)
from .run_loader import load_manifest


TOOL_ID = "cx319_range_spanning_offline_reanalysis_v1"
RESULT_TYPE = "cx319_range_spanning_analysis_supersession_v1"
SEAL_TYPE = "cx319_range_spanning_superseding_seal_v1"
ORIGINAL_ANALYSIS = Path("reports/range_spanning_analysis_v1.json")
ORIGINAL_SEAL = Path("reports/range_spanning_seal_v1.json")
REANALYSIS = Path("reports/range_spanning_reanalysis_v1.json")
BASE_SEAL = Path("reports/range_spanning_reanalysis_base_seal_v1.json")
SUPERSESSION = Path("reports/range_spanning_analysis_supersession_v1.json")
SUPERSEDING_SEAL = Path("reports/range_spanning_superseding_seal_v1.json")


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _read_json(path: Path, description: str) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{description} must be a JSON object: {path}")
    return value


def _repository_state() -> dict[str, str]:
    root = Path(__file__).resolve().parents[2]
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=root,
        text=True,
        capture_output=True,
        check=True,
        timeout=10,
    ).stdout
    return {
        "git_commit": revision,
        "source_state": "dirty" if status else "clean",
    }


def _effective_analyzer() -> dict[str, Any]:
    directory = Path(__file__).resolve().parent
    paths = {
        "analyzer": directory / "range_spanning_analyze.py",
        "bundle_validator": directory / "range_spanning_bundle.py",
        "contracts": directory / "contracts.py",
        "reanalysis": Path(__file__).resolve(),
        "run_loader": directory / "run_loader.py",
        "run_validator": directory / "validate_run.py",
    }
    bindings = {
        name: {
            "path": str(path),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        }
        for name, path in sorted(paths.items())
    }
    return {
        "identity": canonical_sha256(bindings),
        "bindings": bindings,
    }


def _registered_source(
    *, source_run: Path, expected_content_sha256: str, index_path: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    identity = package_identity(source_run)
    if identity["content_sha256"] != expected_content_sha256:
        raise ValueError("source package content identity differs")
    index = load_index(index_path)
    record = index.get("packages", {}).get(expected_content_sha256)
    if not isinstance(record, dict):
        raise ValueError("source package content identity is not registered")
    if str(source_run) not in record.get("storage_locations", []):
        raise ValueError("exact source path is not a registered storage location")
    indexed_files = {
        str(item["relative_path"]): item for item in record.get("file_manifest", [])
    }
    observed_files = {
        str(item["relative_path"]): item for item in identity.get("files", [])
    }
    if indexed_files != observed_files:
        raise ValueError("source package file manifest differs from registration")
    return identity, record


def _validated_snapshot_artifacts(
    source_run: Path, source_identity: dict[str, Any]
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = load_manifest(source_run)
    failures, warnings = validate_evidence_snapshot(source_run, manifest)
    if failures or warnings:
        raise ValueError(
            "source evidence snapshot validation failed: "
            + "; ".join([*failures, *warnings])
        )
    snapshot_path = source_run / "evidence_manifest.json"
    snapshot = _read_json(snapshot_path, "source evidence snapshot")
    observed = {
        str(item["relative_path"]): item
        for item in source_identity.get("files", [])
    }
    artifacts: list[dict[str, Any]] = []
    for item in snapshot.get("artifacts", []):
        path = str(item.get("path", ""))
        actual = observed.get(path)
        if actual is None or any(
            actual.get(field) != item.get(field)
            for field in ("sha256", "size_bytes")
        ):
            raise ValueError(f"source snapshot artifact differs: {path}")
        artifacts.append(
            {
                "path": path,
                "sha256": str(item["sha256"]),
                "size_bytes": int(item["size_bytes"]),
            }
        )
    if not artifacts:
        raise ValueError("source evidence snapshot has no artifacts")
    return snapshot, artifacts


def reanalyze(
    *,
    source_run: Path,
    bundle_path: Path,
    output_dir: Path,
    source_content_sha256: str,
    review_authority: str,
    evidence_index_path: Path = DEFAULT_INDEX,
) -> dict[str, Any]:
    source_run = source_run.resolve()
    bundle_path = bundle_path.resolve()
    output_dir = output_dir.resolve()
    if output_dir.exists():
        raise FileExistsError(f"reanalysis output already exists: {output_dir}")
    if not review_authority.strip():
        raise ValueError("review authority must be non-empty")

    source_identity, source_record = _registered_source(
        source_run=source_run,
        expected_content_sha256=source_content_sha256,
        index_path=evidence_index_path,
    )
    snapshot, source_artifacts = _validated_snapshot_artifacts(
        source_run, source_identity
    )
    activation = _read_json(
        source_run / "range_spanning_live_activation_v1.json",
        "source live activation",
    )
    bundle_file_sha256 = sha256_file(bundle_path)
    if activation.get("bundle", {}).get("sha256") != bundle_file_sha256:
        raise ValueError("source activation bundle file identity differs")
    bundle = validate_bundle_for_offline_reanalysis(bundle_path)
    if activation.get("bundle", {}).get("bundle_sha256") != bundle["bundle_sha256"]:
        raise ValueError("source activation bundle semantic identity differs")

    original_analysis_path = source_run / ORIGINAL_ANALYSIS
    original_seal_path = source_run / ORIGINAL_SEAL
    original_analysis = _read_json(original_analysis_path, "original analysis")
    original_seal = _read_json(original_seal_path, "original seal")
    if original_analysis.get("status") != "failed":
        raise ValueError("source analysis is not the expected failed verdict")
    if original_analysis.get("failures", [None])[0] != (
        "canonical_contract_validation_failed"
    ):
        raise ValueError("source analysis failed outside canonical validation")

    output_dir.mkdir(parents=True)
    (output_dir / "reports").mkdir()
    analysis = analyze(
        bundle_path=bundle_path,
        run_dir=source_run,
        output_path=output_dir / REANALYSIS,
        seal_path=output_dir / BASE_SEAL,
        offline_reanalysis=True,
    )
    if analysis.get("status") != "passed":
        raise RuntimeError(
            "corrected offline reanalysis did not pass: "
            + "; ".join(str(item) for item in analysis.get("failures", []))
        )

    effective_analyzer = _effective_analyzer()
    repository = _repository_state()
    reason = (
        "The original validator treated every nonzero limited counterfactual "
        "proposal as applied shadow-code movement. The rejected firmware row "
        "was a dither-guarded decision with counterfactual_correction=false; "
        "the frozen criterion is unchanged and the corrected validator applies "
        "the movement equality only to applied counterfactual corrections."
    )
    supersession_unsigned: dict[str, Any] = {
        "schema_version": 1,
        "result_type": RESULT_TYPE,
        "tool": TOOL_ID,
        "status": "passed",
        "created_utc": _utc_now(),
        "source_package": {
            "run_id": source_run.name,
            "path": str(source_run),
            "content_sha256": source_content_sha256,
            "file_count": source_identity["file_count"],
            "total_bytes": source_identity["total_bytes"],
            "registered_utc": source_record.get("registered_utc"),
            "attempt_classification": source_record.get("attempt_classification"),
            "source_revision": source_record.get("source_revision"),
            "build_identity": source_record.get("build_identity"),
            "profile_identity": source_record.get("profile_identity"),
        },
        "source_evidence_snapshot": {
            "path": str(source_run / "evidence_manifest.json"),
            "file_sha256": sha256_file(source_run / "evidence_manifest.json"),
            "snapshot_digest": snapshot["snapshot_digest"],
            "verified_artifacts": source_artifacts,
        },
        "frozen_bundle": {
            "path": str(bundle_path),
            "file_sha256": bundle_file_sha256,
            "bundle_sha256": bundle["bundle_sha256"],
            "frozen_host_tool_bindings": bundle["host_tools"],
        },
        "superseded_product": {
            "analysis_path": str(original_analysis_path),
            "analysis_file_sha256": sha256_file(original_analysis_path),
            "analysis_sha256": original_analysis.get("analysis_sha256"),
            "analysis_status": original_analysis.get("status"),
            "analysis_failures": original_analysis.get("failures"),
            "seal_path": str(original_seal_path),
            "seal_file_sha256": sha256_file(original_seal_path),
            "seal_sha256": original_seal.get("seal_sha256"),
            "seal_status": original_seal.get("status"),
            "registered_analyzer_identity": source_record.get("analyzer_identity"),
        },
        "replacement_product": {
            "analysis_path": REANALYSIS.as_posix(),
            "analysis_file_sha256": sha256_file(output_dir / REANALYSIS),
            "analysis_sha256": analysis["analysis_sha256"],
            "analysis_status": analysis["status"],
            "completed_point_count": analysis["completed_point_count"],
            "base_seal_path": BASE_SEAL.as_posix(),
            "base_seal_file_sha256": sha256_file(output_dir / BASE_SEAL),
            "effective_analyzer": effective_analyzer,
            "repository": repository,
        },
        "supersession_reason": reason,
        "review_authority": review_authority,
        "criterion_changed": False,
        "raw_evidence_unchanged": True,
        "physical_rerun": False,
        "hardware_interaction": False,
        "actionable": False,
        "actuation_authorized": False,
        "claims_boundary": analysis["claims_boundary"],
    }
    supersession = {
        **supersession_unsigned,
        "supersession_sha256": canonical_sha256(supersession_unsigned),
    }
    _atomic_new_json(output_dir / SUPERSESSION, supersession)

    seal_unsigned = {
        "schema_version": 1,
        "seal_type": SEAL_TYPE,
        "tool": TOOL_ID,
        "status": "passed",
        "source_content_sha256": source_content_sha256,
        "source_snapshot_digest": snapshot["snapshot_digest"],
        "bundle_sha256": bundle["bundle_sha256"],
        "analysis_sha256": analysis["analysis_sha256"],
        "analysis_file_sha256": sha256_file(output_dir / REANALYSIS),
        "supersession_sha256": supersession["supersession_sha256"],
        "supersession_file_sha256": sha256_file(output_dir / SUPERSESSION),
        "effective_analyzer_identity": effective_analyzer["identity"],
        "review_authority": review_authority,
        "hardware_interaction": False,
        "actionable": False,
        "actuation_authorized": False,
        "claims_boundary": analysis["claims_boundary"],
    }
    seal = {**seal_unsigned, "seal_sha256": canonical_sha256(seal_unsigned)}
    _atomic_new_json(output_dir / SUPERSEDING_SEAL, seal)

    product_unsigned = {
        "schema_version": 1,
        "product_type": "cx319_range_spanning_reanalysis_product_v1",
        "source_content_sha256": source_content_sha256,
        "files": [
            {
                "path": path.relative_to(output_dir).as_posix(),
                "sha256": sha256_file(path),
                "size_bytes": path.stat().st_size,
            }
            for path in sorted((output_dir / "reports").iterdir())
        ],
    }
    product = {
        **product_unsigned,
        "product_manifest_sha256": canonical_sha256(product_unsigned),
    }
    _atomic_new_json(output_dir / "product_manifest.json", product)

    registered = register_package(
        index_path=evidence_index_path,
        package_path=output_dir,
        source_revision=repository["git_commit"],
        build_identity=str(source_record["build_identity"]),
        profile_identity=str(source_record["profile_identity"]),
        attempt_classification="completed_campaign",
        result_or_failure_reason=(
            "CX319 Part A 30-point physical acquisition passed host-only "
            "reanalysis; supersedes deterministic validator failure in source "
            + source_content_sha256
        ),
        analyzer_identity=str(effective_analyzer["identity"]),
    )
    return {
        "status": "passed",
        "source_content_sha256": source_content_sha256,
        "reanalysis_dir": str(output_dir),
        "analysis_sha256": analysis["analysis_sha256"],
        "supersession_sha256": supersession["supersession_sha256"],
        "seal_sha256": seal["seal_sha256"],
        "registered_content_sha256": registered["content_sha256"],
        "completed_point_count": analysis["completed_point_count"],
        "physical_rerun": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-run", type=Path, required=True)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-content-sha256", required=True)
    parser.add_argument("--review-authority", required=True)
    parser.add_argument("--evidence-index", type=Path, default=DEFAULT_INDEX)
    args = parser.parse_args(argv)
    result = reanalyze(
        source_run=args.source_run,
        bundle_path=args.bundle,
        output_dir=args.output_dir,
        source_content_sha256=args.source_content_sha256,
        review_authority=args.review_authority,
        evidence_index_path=args.evidence_index,
    )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
