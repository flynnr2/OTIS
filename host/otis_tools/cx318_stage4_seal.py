"""Post-capture, no-hardware evidence binding for CX318 Stage 4.

This module deliberately has no capture, serial, command, firmware, or report
path.  It binds an already-closed run to an external JSON document after the
RPH/PHE/HPR artifacts are present in the manifest.  Live RPH rows retain their
``live_stream_unsealed`` source identity: their completed-file SHA-256 belongs
in this external binding, never in the source CSV.
"""

from __future__ import annotations

import argparse
import csv
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any

from .contracts import CsvValidationContext, validate_csv
from .evidence import (
    EVIDENCE_MANIFEST,
    EvidenceError,
    create_evidence_snapshot,
    validate_evidence_snapshot,
)
from .run_loader import CAPTURE_IN_PROGRESS_FLAG, load_manifest


REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_ID = "CX318_STAGE4_POST_CAPTURE_SEAL_V1"
BINDING_SCHEMA_VERSION = 1
DIGEST_ALGORITHM = "sha256"
RAW_SERIAL_RELATIVE_PATH = "raw/serial.log"
SOURCE_RPH_RELATIVE_PATH = "csv/relative_phase_observations_v1.csv"
ANALYSIS_RELATIVE_PATH = "reports/cx318_stage4_live_analysis_v1.json"
REQUIRED_STAGE4_ARTIFACTS = {
    "csv/relative_phase_observations_v1.csv": "relative_phase_observations_v1",
    "csv/phase_estimator_outputs_v1.csv": "phase_estimator_outputs_v1",
    "csv/hybrid_preview_decisions_v1.csv": "hybrid_preview_decisions_v1",
}
PROFILE_PATHS = (
    Path("profiles/estimators/cx318_relative_phase_selected_v1.json"),
    Path("profiles/discipline/cx318_hybrid_preview_selected_v1.json"),
    Path("profiles/estimators/cx317_pps_gated_selected_v1.json"),
)
FIRMWARE_MATRIX_PATH = Path("firmware/arduino/firmware_matrix.json")
FIRMWARE_PROFILE_ID = "cx318_stage4_nonactuating_preview"
EXPECTED_STAGE = "CX318_STAGE4_NONACTUATING_LIVE_PREVIEW"
ANALYZED_CONTRACTS = (
    "count_observations_v1",
    "pps_snapshots_v1",
    "health_v1",
    "environment_v1",
    "dac_steps_v1",
    "active_transactions_v1",
    "relative_phase_observations_v1",
    "phase_estimator_outputs_v1",
    "hybrid_preview_decisions_v1",
)
REQUIRED_ANALYSIS_CHECKS = {
    *(f"contract_{contract}" for contract in ANALYZED_CONTRACTS),
    "stage_identity",
    "finite_capture_complete",
    "selected_profile_semantics",
    "exact_static_code_binding",
    "capture_transport_continuity",
    "zero_dac_active_or_unapproved_commands",
    "live_health_fail_static_and_authority_guards",
    "raw_to_split_csv_exact_association",
    "exact_firmware_build_binding",
    "stage4_build_profile_and_defines",
    "emitted_static_code_and_epoch_identity",
    "one_complete_record_group_per_snapshot",
    "live_host_firmware_phase_hybrid_parity",
    "single_continuous_qualified_phase_epoch",
    "minimum_authoritative_frequency_estimates",
    "finite_live_duration",
    "both_environment_streams_present",
    "source_artifacts_unchanged",
}


class Stage4SealError(ValueError):
    """The run cannot safely be bound as closed CX318 Stage 4 evidence."""


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_digest(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return sha256(encoded.encode("utf-8")).hexdigest()


def _relative_to_run(run_dir: Path, path: Path) -> str:
    return path.relative_to(run_dir).as_posix()


def _contract_path(manifest, contract: str) -> Path:
    matches = [
        manifest.root / str(entry["path"])
        for entry in manifest.files
        if entry.get("contract") == contract
    ]
    if len(matches) != 1:
        raise Stage4SealError(
            f"expected exactly one analyzed {contract} artifact, got {len(matches)}"
        )
    return matches[0]


def _analyzed_source_digests(run_dir: Path, manifest) -> dict[str, str]:
    paths = [_contract_path(manifest, contract) for contract in ANALYZED_CONTRACTS]
    paths.extend(
        [
            run_dir / RAW_SERIAL_RELATIVE_PATH,
            run_dir / "reports/capture_device_state.json",
        ]
    )
    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise Stage4SealError(
            "analyzed source artifact is missing: "
            + ", ".join(_relative_to_run(run_dir, path) for path in missing)
        )
    return {
        _relative_to_run(run_dir, path): _sha256_file(path)
        for path in paths
    }


def _validate_analysis(run_dir: Path, manifest, analysis: Any) -> None:
    if (
        not isinstance(analysis, dict)
        or analysis.get("tool") != "cx318_stage4_live_analyze_v1"
        or analysis.get("status") != "passed"
        or analysis.get("run_id") != manifest.run_id
    ):
        raise Stage4SealError("declared Stage 4 analysis identity/status is invalid")
    if analysis.get("run_manifest_sha256") != _sha256_file(manifest.path):
        raise Stage4SealError("declared Stage 4 analysis is stale for the run manifest")
    checks = analysis.get("checks")
    if not isinstance(checks, list):
        raise Stage4SealError("declared Stage 4 analysis has no check inventory")
    identifiers: dict[str, bool] = {}
    for check in checks:
        if not isinstance(check, dict) or not isinstance(check.get("identifier"), str):
            raise Stage4SealError("declared Stage 4 analysis check is malformed")
        identifier = check["identifier"]
        if identifier in identifiers:
            raise Stage4SealError(f"duplicate Stage 4 analysis check: {identifier}")
        identifiers[identifier] = check.get("passed") is True
    missing = sorted(REQUIRED_ANALYSIS_CHECKS - set(identifiers))
    failed = sorted(identifier for identifier, passed in identifiers.items() if not passed)
    if missing or failed:
        raise Stage4SealError(
            "declared Stage 4 analysis is incomplete or failed: "
            + json.dumps({"missing": missing, "failed": failed}, sort_keys=True)
        )
    current_sources = _analyzed_source_digests(run_dir, manifest)
    if analysis.get("source_artifacts_sha256") != dict(sorted(current_sources.items())):
        raise Stage4SealError("declared Stage 4 analysis is stale for source artifacts")
    selected_identities = analysis.get("selected_profile_contract", {}).get(
        "identities"
    )
    expected_profile_identities = {
        "phase_selected_sha256": _sha256_file(REPO_ROOT / PROFILE_PATHS[0]),
        "hybrid_selected_sha256": _sha256_file(REPO_ROOT / PROFILE_PATHS[1]),
        "frequency_selected_sha256": _sha256_file(REPO_ROOT / PROFILE_PATHS[2]),
    }
    if selected_identities != expected_profile_identities:
        raise Stage4SealError("declared Stage 4 analysis profile identities are stale")


def _declared_stage4_artifacts(run_dir: Path, manifest) -> dict[str, Any]:
    declared = {
        entry.get("path"): entry.get("contract")
        for entry in manifest.files
        if isinstance(entry, dict)
    }
    for relative_path, contract in REQUIRED_STAGE4_ARTIFACTS.items():
        if declared.get(relative_path) != contract:
            raise Stage4SealError(
                "Stage 4 artifact must be declared before evidence snapshot: "
                f"{relative_path} ({contract})"
            )
        if not (run_dir / relative_path).is_file():
            raise Stage4SealError(
                f"declared Stage 4 artifact is missing: {relative_path}"
            )
        result = validate_csv(
            run_dir / relative_path,
            CsvValidationContext(
                contract=contract,
                known_channels=manifest.known_channels,
                known_domains=manifest.known_domains,
                allow_rp2040_timer0_wrap=True,
            ),
        )
        if not result.ok or result.row_count == 0:
            details = "; ".join(result.errors[:4]) or "artifact is header-only"
            raise Stage4SealError(
                f"invalid Stage 4 artifact {relative_path}: {details}"
            )

    rph_path = run_dir / SOURCE_RPH_RELATIVE_PATH
    with rph_path.open("r", newline="", encoding="utf-8") as handle:
        source_identities = {
            row.get("source_file_sha256", "") for row in csv.DictReader(handle)
        }
    if source_identities != {"live_stream_unsealed"}:
        raise Stage4SealError(
            "source RPH must preserve only the live_stream_unsealed identity"
        )

    evidence_artifacts = manifest.data.get("evidence_artifacts", [])
    if not isinstance(evidence_artifacts, list) or ANALYSIS_RELATIVE_PATH not in evidence_artifacts:
        raise Stage4SealError(
            f"Stage 4 analysis must be declared before evidence snapshot: {ANALYSIS_RELATIVE_PATH}"
        )
    analysis_path = run_dir / ANALYSIS_RELATIVE_PATH
    try:
        analysis = json.loads(analysis_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage4SealError(f"cannot read declared Stage 4 analysis: {exc}") from exc
    _validate_analysis(run_dir, manifest, analysis)
    return analysis


def _source_csv_digests(run_dir: Path) -> dict[str, str]:
    csv_dir = run_dir / "csv"
    if not csv_dir.is_dir():
        raise Stage4SealError("run has no csv directory")
    return {
        _relative_to_run(run_dir, path): _sha256_file(path)
        for path in sorted(csv_dir.rglob("*.csv"))
        if path.is_file()
    }


def _profile_identities() -> list[dict[str, str]]:
    identities: list[dict[str, str]] = []
    for relative_path in PROFILE_PATHS:
        path = REPO_ROOT / relative_path
        if not path.is_file():
            raise Stage4SealError(f"required CX318 profile is missing: {relative_path}")
        try:
            profile = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise Stage4SealError(f"cannot read CX318 profile {relative_path}: {exc}") from exc
        profile_id = profile.get("profile_id")
        if not isinstance(profile_id, str) or not profile_id:
            raise Stage4SealError(f"CX318 profile has no profile_id: {relative_path}")
        identities.append(
            {
                "path": relative_path.as_posix(),
                "profile_id": profile_id,
                "sha256": _sha256_file(path),
            }
        )
    return identities


def _firmware_profile_identity() -> dict[str, str]:
    matrix_path = REPO_ROOT / FIRMWARE_MATRIX_PATH
    try:
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage4SealError(f"cannot read firmware matrix: {exc}") from exc
    profile = next(
        (
            item
            for item in matrix.get("profiles", [])
            if isinstance(item, dict) and item.get("id") == FIRMWARE_PROFILE_ID
        ),
        None,
    )
    if profile is None:
        raise Stage4SealError(f"firmware matrix lacks {FIRMWARE_PROFILE_ID}")
    return {
        "path": FIRMWARE_MATRIX_PATH.as_posix(),
        "profile_id": FIRMWARE_PROFILE_ID,
        "matrix_sha256": _sha256_file(matrix_path),
        "profile_sha256": _canonical_digest(profile),
    }


def _snapshot_for_closed_run(run_dir: Path, manifest) -> tuple[Path, dict[str, Any], bool]:
    snapshot_path = run_dir / EVIDENCE_MANIFEST
    created = False
    if snapshot_path.exists():
        failures, _warnings = validate_evidence_snapshot(run_dir, manifest)
        if failures:
            raise Stage4SealError("existing evidence snapshot is invalid: " + "; ".join(failures))
    else:
        try:
            snapshot_path = create_evidence_snapshot(run_dir)
        except (EvidenceError, FileExistsError, FileNotFoundError, json.JSONDecodeError) as exc:
            raise Stage4SealError(f"cannot create evidence snapshot: {exc}") from exc
        created = True
    try:
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise Stage4SealError(f"cannot read evidence snapshot: {exc}") from exc
    if snapshot.get("run_state") != "complete":
        raise Stage4SealError("evidence snapshot is not a completed-run snapshot")
    return snapshot_path, snapshot, created


def _snapshot_artifacts(snapshot: dict[str, Any]) -> dict[str, dict[str, Any]]:
    artifacts = snapshot.get("artifacts")
    if not isinstance(artifacts, list):
        raise Stage4SealError("evidence snapshot lacks an artifact inventory")
    result: dict[str, dict[str, Any]] = {}
    for artifact in artifacts:
        if not isinstance(artifact, dict):
            raise Stage4SealError("evidence snapshot artifact is malformed")
        path = artifact.get("path")
        digest = artifact.get("sha256")
        if not isinstance(path, str) or not isinstance(digest, str):
            raise Stage4SealError("evidence snapshot artifact identity is malformed")
        result[path] = artifact
    return result


def seal(run_dir: Path, output: Path) -> dict[str, Any]:
    """Create an external Stage 4 binding for an already completed capture.

    ``output`` must be outside ``run_dir``.  The output is intentionally absent
    from both the run evidence snapshot and the hash used as its own identity.
    """
    run_dir = run_dir.resolve()
    output = output.resolve()
    if output == run_dir or run_dir in output.parents:
        raise Stage4SealError("binding output must be outside the source run")
    if output.exists():
        raise FileExistsError(f"refusing to overwrite existing binding: {output}")
    if (run_dir / CAPTURE_IN_PROGRESS_FLAG).exists():
        raise Stage4SealError("capture is in progress; refusing post-capture seal")

    try:
        manifest = load_manifest(run_dir)
    except (FileNotFoundError, ValueError, json.JSONDecodeError) as exc:
        raise Stage4SealError(f"cannot load run manifest: {exc}") from exc
    if manifest.is_template:
        raise Stage4SealError("template directories cannot be sealed as Stage 4 evidence")
    if manifest.data.get("stage") != EXPECTED_STAGE:
        raise Stage4SealError(
            f"run stage must be {EXPECTED_STAGE}"
        )
    if not (run_dir / "COMPLETE").is_file():
        raise Stage4SealError("COMPLETE marker is required before Stage 4 sealing")
    analysis = _declared_stage4_artifacts(run_dir, manifest)

    raw_serial = run_dir / RAW_SERIAL_RELATIVE_PATH
    source_rph = run_dir / SOURCE_RPH_RELATIVE_PATH
    if not raw_serial.is_file():
        raise Stage4SealError(f"required immutable raw serial log is missing: {RAW_SERIAL_RELATIVE_PATH}")
    if not source_rph.is_file():
        raise Stage4SealError(f"required source RPH is missing: {SOURCE_RPH_RELATIVE_PATH}")
    source_before = _source_csv_digests(run_dir)
    raw_before = _sha256_file(raw_serial)
    rph_before = _sha256_file(source_rph)

    # This is deliberately after declaration/existence checks: the snapshot
    # must cover the complete Stage 4 derived artifact set.
    snapshot_path, snapshot, snapshot_created = _snapshot_for_closed_run(run_dir, manifest)
    if raw_before != _sha256_file(raw_serial) or rph_before != _sha256_file(source_rph):
        raise Stage4SealError("raw serial log or source RPH changed while sealing")
    if source_before != _source_csv_digests(run_dir):
        raise Stage4SealError("a source CSV changed while sealing")

    artifacts_by_path = _snapshot_artifacts(snapshot)
    for relative_path in (
        RAW_SERIAL_RELATIVE_PATH,
        *REQUIRED_STAGE4_ARTIFACTS,
        ANALYSIS_RELATIVE_PATH,
    ):
        if relative_path not in artifacts_by_path:
            raise Stage4SealError(
                f"evidence snapshot does not cover declared Stage 4 artifact: {relative_path}"
            )
    if artifacts_by_path[RAW_SERIAL_RELATIVE_PATH]["sha256"] != raw_before:
        raise Stage4SealError("evidence snapshot raw serial SHA-256 differs from completed file")
    if artifacts_by_path[SOURCE_RPH_RELATIVE_PATH]["sha256"] != rph_before:
        raise Stage4SealError("evidence snapshot source RPH SHA-256 differs from completed file")

    payload: dict[str, Any] = {
        "schema_version": BINDING_SCHEMA_VERSION,
        "binding_type": "cx318_stage4_post_capture_external_binding_v1",
        "digest_algorithm": DIGEST_ALGORITHM,
        "run": {
            "run_id": manifest.run_id,
            "manifest_path": _relative_to_run(run_dir, manifest.path),
            "manifest_sha256": _sha256_file(manifest.path),
        },
        "raw_serial": {"path": RAW_SERIAL_RELATIVE_PATH, "sha256": raw_before},
        "source_relative_phase": {"path": SOURCE_RPH_RELATIVE_PATH, "sha256": rph_before},
        "live_analysis": {
            "path": ANALYSIS_RELATIVE_PATH,
            "sha256": _sha256_file(run_dir / ANALYSIS_RELATIVE_PATH),
            "status": analysis["status"],
        },
        "tool_identity": {
            "tool_id": TOOL_ID,
            "path": _relative_to_run(REPO_ROOT, Path(__file__).resolve()),
            "sha256": _sha256_file(Path(__file__).resolve()),
        },
        "profile_identities": _profile_identities(),
        "build_identities": {
            "firmware_profile": _firmware_profile_identity(),
            "emitted_firmware_build_provenance": snapshot.get("firmware_build_provenance"),
            "manifest_firmware": manifest.data.get("firmware"),
            "manifest_build": manifest.data.get("build"),
        },
        "evidence_snapshot": {
            "path": _relative_to_run(run_dir, snapshot_path),
            "sha256": _sha256_file(snapshot_path),
            "snapshot_digest": snapshot.get("snapshot_digest"),
            "created_by_this_seal": snapshot_created,
        },
        "artifact_inventory": snapshot["artifacts"],
    }
    binding = {**payload, "binding_sha256": _canonical_digest(payload)}
    output.parent.mkdir(parents=True, exist_ok=True)
    encoded = (json.dumps(binding, indent=2, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
    with output.open("xb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    return binding


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        binding = seal(args.run_dir, args.output)
    except (Stage4SealError, FileExistsError) as exc:
        raise SystemExit(str(exc)) from exc
    print(f"{args.output.resolve()} binding_sha256={binding['binding_sha256']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
