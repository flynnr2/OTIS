"""Content-addressed index for OTIS raw evidence stored outside Git.

The index records package identity and lifecycle metadata. It deliberately has
no delete operation: future raw-package deletion requires a separate reviewed
operator-authorized procedure after OTIS reaches a declared mature milestone.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any, Iterable


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INDEX = (
    Path.home() / ".local" / "share" / "otis" / "evidence_index_v1.json"
)
INDEX_ID = "otis_evidence_index_v1"
SCHEMA_VERSION = 1
ATTEMPT_CLASSIFICATIONS = {
    "successful_rehearsal",
    "failed_rehearsal",
    "successful_qualification",
    "failed_qualification",
    "completed_campaign",
    "interrupted_campaign",
    "diagnostic",
    "historical",
}
SUCCESS_CLASSIFICATIONS = frozenset(
    {
        "successful_rehearsal",
        "successful_qualification",
        "completed_campaign",
    }
)
CURRENT_SEAL_TYPE = "adaptive_hybrid_physical_seal_v1"
CURRENT_ANALYZER_ID = "adaptive_hybrid_analyze_v1"
CURRENT_SEAL_PATH = Path("reports/adaptive_hybrid_physical_seal_v1.json")
LOWER_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
CURRENT_SEAL_FIELDS = frozenset(
    {
        "schema_version",
        "seal_type",
        "tool",
        "tool_sha256",
        "created_utc",
        "run_id",
        "run_identity",
        "build_identity",
        "image_identity",
        "programme_id",
        "policy_id",
        "status",
        "primary_decision",
        "terminal_result",
        "terminal_reason",
        "checks",
        "csv_validation",
        "exact_lifecycle_records",
        "maintenance_replay",
        "measurement_replay",
        "response_replay",
        "transaction_capsule_sha256",
        "evidence_snapshot",
        "source_sha256",
        "D10_semantics",
        "limitations",
        "seal_sha256",
    }
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value


def _validated_success_package(
    location: Path,
    *,
    source_revision: str,
    build_identity: str,
    image_identity: str,
    attempt_classification: str,
    result_or_failure_reason: str,
    analyzer_identity: str,
) -> dict[str, str]:
    """Validate the complete current package behind a successful classification."""

    if not location.is_dir():
        raise ValueError(
            "successful evidence registration requires a completed package directory"
        )
    required = {
        "completion marker": location / "COMPLETE",
        "run manifest": location / "run_manifest.json",
        "evidence snapshot": location / "evidence_manifest.json",
        "analyzer seal": location / CURRENT_SEAL_PATH,
    }
    missing = [label for label, path in required.items() if not path.is_file()]
    if missing:
        raise ValueError(
            "successful evidence registration requires " + ", ".join(missing)
        )

    # Imports remain local so raw, interrupted, failed, diagnostic, and historical
    # inventory registration does not acquire the current live-programme graph.
    from .adaptive_hybrid_activation import validate_frozen_run_manifest
    from .adaptive_hybrid_contract import programme_from_mapping
    from .evidence import validate_evidence_snapshot
    from .run_loader import load_manifest

    try:
        manifest_value = validate_frozen_run_manifest(required["run manifest"])
        manifest = load_manifest(location)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"successful evidence registration requires an exact current run manifest: {exc}"
        ) from exc
    programme = programme_from_mapping(manifest_value)
    if programme.physical_seal_path != CURRENT_SEAL_PATH:
        raise ValueError("successful evidence registration seal path differs")

    completion = _read_object(required["completion marker"], "completion marker")
    if (
        completion.get("completion")
        != "adaptive_hybrid_finite_physical_campaign"
        or not isinstance(completion.get("terminal"), dict)
    ):
        raise ValueError("successful evidence registration completion marker differs")

    snapshot = _read_object(required["evidence snapshot"], "evidence snapshot")
    failures, warnings = validate_evidence_snapshot(location, manifest)
    if failures or warnings or snapshot.get("run_state") != "complete":
        detail = "; ".join([*failures, *warnings]) or "run_state is not complete"
        raise ValueError(
            "successful evidence registration requires an exact complete evidence "
            f"snapshot: {detail}"
        )

    seal = _read_object(required["analyzer seal"], "analyzer seal")
    if set(seal) != CURRENT_SEAL_FIELDS:
        raise ValueError("successful evidence registration analyzer seal fields differ")
    claimed_seal_sha256 = seal.get("seal_sha256")
    unsigned_seal = {
        key: value for key, value in seal.items() if key != "seal_sha256"
    }
    checks = seal.get("checks")
    snapshot_result = seal.get("evidence_snapshot")
    if (
        seal.get("schema_version") != 1
        or seal.get("seal_type") != CURRENT_SEAL_TYPE
        or seal.get("tool") != CURRENT_ANALYZER_ID
        or not isinstance(claimed_seal_sha256, str)
        or not LOWER_HEX_64.fullmatch(claimed_seal_sha256)
        or claimed_seal_sha256 != _canonical_sha256(unsigned_seal)
        or seal.get("status") != "passed"
        or not isinstance(checks, dict)
        or not checks
        or not all(value is True for value in checks.values())
        or not isinstance(snapshot_result, dict)
        or snapshot_result.get("path") != "evidence_manifest.json"
        or snapshot_result.get("failures") != []
        or snapshot_result.get("warnings") != []
    ):
        raise ValueError(
            "successful evidence registration requires an exact passing analyzer seal"
        )

    terminal = completion["terminal"]
    firmware = manifest_value.get("firmware", {})
    policy = manifest_value.get("policy", {})
    host = manifest_value.get("host", {})
    tool_bindings = host.get("tool_bindings", {}) if isinstance(host, dict) else {}
    analyzer_binding = (
        tool_bindings.get("adaptive_hybrid_analyze", {})
        if isinstance(tool_bindings, dict)
        else {}
    )
    expected = {
        "run_id": manifest.run_id,
        "run_identity": manifest_value.get("run_identity"),
        "build_identity": build_identity,
        "image_identity": image_identity,
        "programme_id": manifest_value.get("programme_id"),
        "policy_id": policy.get("policy_id") if isinstance(policy, dict) else None,
        "tool_sha256": analyzer_identity,
        "terminal_result": terminal.get("result"),
        "terminal_reason": terminal.get("reason"),
    }
    mismatched = sorted(
        field for field, expected_value in expected.items()
        if seal.get(field) != expected_value
    )
    if mismatched:
        raise ValueError(
            "successful evidence registration metadata differs from analyzer seal: "
            + ", ".join(mismatched)
        )
    if (
        not isinstance(firmware, dict)
        or firmware.get("source_revision") != source_revision
        or firmware.get("build_identity") != build_identity
        or manifest_value.get("image_identity") != image_identity
        or analyzer_binding.get("sha256") != analyzer_identity
        or not isinstance(seal.get("primary_decision"), str)
        or seal["primary_decision"] not in result_or_failure_reason
    ):
        raise ValueError(
            "successful evidence registration metadata differs from the completed package"
        )
    if (
        attempt_classification == "successful_qualification"
        and (
            seal.get("terminal_result") != "healthy_stop"
            or seal.get("primary_decision") != programme.qualified_endpoint_reason
        )
    ):
        raise ValueError(
            "successful qualification registration requires the qualified endpoint"
        )
    if attempt_classification == "successful_rehearsal":
        raise ValueError(
            "successful rehearsal registration is unavailable until the current "
            "operational-rehearsal producer and seal contract exist"
        )

    sealed_sources = seal.get("source_sha256")
    expected_sources = {
        str(item["path"]): _sha256_file(location / str(item["path"]))
        for item in manifest.files
        if (location / str(item.get("path", ""))).is_file()
    }
    if sealed_sources != expected_sources:
        raise ValueError(
            "successful evidence registration analyzer source identities differ"
        )

    return {
        "contract": "otis_validated_success_package_v1",
        "evidence_snapshot_sha256": str(snapshot["snapshot_digest"]),
        "seal_path": CURRENT_SEAL_PATH.as_posix(),
        "seal_sha256": claimed_seal_sha256,
        "seal_status": str(seal["status"]),
        "primary_decision": str(seal["primary_decision"]),
    }


def _package_files(path: Path) -> Iterable[tuple[str, Path]]:
    if path.is_symlink():
        raise ValueError(f"evidence package may not be a symlink: {path}")
    if path.is_file():
        yield path.name, path
        return
    if not path.is_dir():
        raise ValueError(f"evidence package does not exist: {path}")
    for candidate in sorted(path.rglob("*")):
        if candidate.is_symlink():
            raise ValueError(
                f"evidence package contains a symlink: {candidate}"
            )
        if candidate.is_file():
            yield candidate.relative_to(path).as_posix(), candidate


def package_identity(path: Path) -> dict[str, Any]:
    """Return a stable identity for one file or a recursively hashed tree."""

    source = path.expanduser().resolve()
    entries: list[dict[str, Any]] = []
    tree_digest = sha256()
    total_bytes = 0
    for relative_path, candidate in _package_files(source):
        size = candidate.stat().st_size
        file_sha256 = _sha256_file(candidate)
        entries.append(
            {
                "relative_path": relative_path,
                "size_bytes": size,
                "sha256": file_sha256,
            }
        )
        encoded = json.dumps(
            entries[-1], sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        tree_digest.update(len(encoded).to_bytes(8, "big"))
        tree_digest.update(encoded)
        total_bytes += size
    if source.is_dir() and not entries:
        tree_digest.update(b"OTIS_EMPTY_EVIDENCE_DIRECTORY_V1")
    return {
        "content_sha256": tree_digest.hexdigest(),
        "file_count": len(entries),
        "total_bytes": total_bytes,
        "files": entries,
    }


def _assert_index_outside_repo(index_path: Path) -> Path:
    resolved = index_path.expanduser().resolve()
    try:
        resolved.relative_to(REPO_ROOT.resolve())
    except ValueError:
        return resolved
    raise ValueError("evidence index must be stored outside the Git repository")


def validate_index_location(index_path: Path) -> Path:
    """Validate and resolve an index location without creating any files."""

    return _assert_index_outside_repo(index_path)


def _empty_index(now: str | None = None) -> dict[str, Any]:
    timestamp = now or _utc_now()
    return {
        "schema_version": SCHEMA_VERSION,
        "index_id": INDEX_ID,
        "created_utc": timestamp,
        "updated_utc": timestamp,
        "packages": {},
    }


def _lock_path(index_path: Path) -> Path:
    return index_path.with_name(f".{index_path.name}.lock")


@contextmanager
def _index_lock(index_path: Path, *, exclusive: bool):  # type: ignore[no-untyped-def]
    path = _assert_index_outside_repo(index_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(_lock_path(path), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(
            descriptor,
            fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH,
        )
        yield path
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _load_index_unlocked(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _empty_index()
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported evidence index schema_version")
    if data.get("index_id") != INDEX_ID:
        raise ValueError("unexpected evidence index identity")
    if not isinstance(data.get("packages"), dict):
        raise ValueError("evidence index packages must be an object")
    return data


def _save_index_unlocked(path: Path, index: dict[str, Any]) -> None:
    index["updated_utc"] = _utc_now()
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(index, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    try:
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def load_index(index_path: Path) -> dict[str, Any]:
    with _index_lock(index_path, exclusive=False) as path:
        return _load_index_unlocked(path)


def save_index(index_path: Path, index: dict[str, Any]) -> None:
    with _index_lock(index_path, exclusive=True) as path:
        _save_index_unlocked(path, index)


def register_package(
    *,
    index_path: Path,
    package_path: Path,
    source_revision: str,
    build_identity: str,
    image_identity: str,
    attempt_classification: str,
    result_or_failure_reason: str,
    analyzer_identity: str,
    expected_content_sha256: str | None = None,
) -> dict[str, Any]:
    required = {
        "source_revision": source_revision,
        "build_identity": build_identity,
        "image_identity": image_identity,
        "result_or_failure_reason": result_or_failure_reason,
        "analyzer_identity": analyzer_identity,
    }
    missing = sorted(name for name, value in required.items() if not value.strip())
    if missing:
        raise ValueError(f"empty required evidence metadata: {', '.join(missing)}")
    if attempt_classification not in ATTEMPT_CLASSIFICATIONS:
        raise ValueError(
            "attempt_classification must be one of: "
            + ", ".join(sorted(ATTEMPT_CLASSIFICATIONS))
        )
    if expected_content_sha256 is not None and not LOWER_HEX_64.fullmatch(
        expected_content_sha256
    ):
        raise ValueError("expected evidence content identity must be lowercase SHA-256")

    location = package_path.expanduser().resolve()
    identity = package_identity(location)
    content_sha256 = identity["content_sha256"]
    if (
        expected_content_sha256 is not None
        and content_sha256 != expected_content_sha256
    ):
        raise ValueError("evidence package differs from expected content identity")
    package_validation = None
    if attempt_classification in SUCCESS_CLASSIFICATIONS:
        package_validation = _validated_success_package(
            location,
            source_revision=source_revision,
            build_identity=build_identity,
            image_identity=image_identity,
            attempt_classification=attempt_classification,
            result_or_failure_reason=result_or_failure_reason,
            analyzer_identity=analyzer_identity,
        )
        if package_identity(location) != identity:
            raise ValueError("evidence package changed during success validation")
    immutable_metadata: dict[str, Any] = {
        "source_revision": source_revision,
        "build_identity": build_identity,
        "image_identity": image_identity,
        "attempt_classification": attempt_classification,
        "result_or_failure_reason": result_or_failure_reason,
        "analyzer_identity": analyzer_identity,
    }
    if package_validation is not None:
        immutable_metadata["package_validation"] = package_validation
    with _index_lock(index_path, exclusive=True) as locked_path:
        index = _load_index_unlocked(locked_path)
        existing = index["packages"].get(content_sha256)
        if existing is not None:
            for key, value in immutable_metadata.items():
                if existing.get(key) != value:
                    raise ValueError(
                        "content identity already registered with different "
                        f"{key}"
                    )
            locations = existing["storage_locations"]
            if str(location) not in locations:
                locations.append(str(location))
                _save_index_unlocked(locked_path, index)
            return existing

        now = _utc_now()
        record = {
            "content_sha256": content_sha256,
            "file_count": identity["file_count"],
            "total_bytes": identity["total_bytes"],
            "file_manifest": identity["files"],
            "storage_locations": [str(location)],
            **immutable_metadata,
            "lifecycle_status": "active",
            "registered_utc": now,
            "mothball": None,
        }
        index["packages"][content_sha256] = record
        _save_index_unlocked(locked_path, index)
        return record


def validate_index(index_path: Path) -> dict[str, Any]:
    index = load_index(index_path)
    results: list[dict[str, Any]] = []
    valid = True
    for content_sha256, record in sorted(index["packages"].items()):
        location_results = []
        any_matching_location = False
        for raw_location in record.get("storage_locations", []):
            location = Path(raw_location)
            if not location.exists():
                location_results.append(
                    {"location": raw_location, "status": "missing"}
                )
                continue
            observed = package_identity(location)["content_sha256"]
            status = "match" if observed == content_sha256 else "mismatch"
            any_matching_location |= status == "match"
            location_results.append(
                {
                    "location": raw_location,
                    "status": status,
                    "observed_content_sha256": observed,
                }
            )
        package_valid = any_matching_location
        valid &= package_valid
        results.append(
            {
                "content_sha256": content_sha256,
                "valid": package_valid,
                "locations": location_results,
            }
        )
    return {
        "index_id": INDEX_ID,
        "valid": valid,
        "package_count": len(results),
        "packages": results,
    }


def mothball_package(
    *,
    index_path: Path,
    content_sha256: str,
    reviewed_summary_path: Path,
    reason: str,
    confirm_no_active_dependency: bool,
) -> dict[str, Any]:
    if not confirm_no_active_dependency:
        raise ValueError("mothball requires confirmation of no active dependency")
    if not reason.strip():
        raise ValueError("mothball reason must be non-empty")
    summary = reviewed_summary_path.expanduser().resolve()
    if not summary.is_file():
        raise ValueError(f"reviewed summary does not exist: {summary}")
    with _index_lock(index_path, exclusive=True) as locked_path:
        index = _load_index_unlocked(locked_path)
        try:
            record = index["packages"][content_sha256]
        except KeyError as exc:
            raise ValueError("unknown evidence content identity") from exc
        record["lifecycle_status"] = "mothballed"
        record["mothball"] = {
            "mothballed_utc": _utc_now(),
            "reason": reason,
            "no_active_dependency_confirmed": True,
            "reviewed_summary_path": str(summary),
            "reviewed_summary_sha256": _sha256_file(summary),
        }
        _save_index_unlocked(locked_path, index)
        return record


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    commands = parser.add_subparsers(dest="command", required=True)

    register = commands.add_parser("register")
    register.add_argument("package", type=Path)
    register.add_argument("--source-revision", required=True)
    register.add_argument("--build-identity", required=True)
    register.add_argument("--image-identity", required=True)
    register.add_argument(
        "--attempt-classification",
        required=True,
        choices=sorted(ATTEMPT_CLASSIFICATIONS),
    )
    register.add_argument("--result-or-failure-reason", required=True)
    register.add_argument("--analyzer-identity", required=True)

    commands.add_parser("validate")
    commands.add_parser("list")

    mothball = commands.add_parser("mothball")
    mothball.add_argument("content_sha256")
    mothball.add_argument("--reviewed-summary", type=Path, required=True)
    mothball.add_argument("--reason", required=True)
    mothball.add_argument(
        "--confirm-no-active-dependency", action="store_true", required=True
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "register":
        result = register_package(
            index_path=args.index,
            package_path=args.package,
            source_revision=args.source_revision,
            build_identity=args.build_identity,
            image_identity=args.image_identity,
            attempt_classification=args.attempt_classification,
            result_or_failure_reason=args.result_or_failure_reason,
            analyzer_identity=args.analyzer_identity,
        )
    elif args.command == "validate":
        result = validate_index(args.index)
    elif args.command == "list":
        result = load_index(args.index)
    else:
        result = mothball_package(
            index_path=args.index,
            content_sha256=args.content_sha256,
            reviewed_summary_path=args.reviewed_summary,
            reason=args.reason,
            confirm_no_active_dependency=args.confirm_no_active_dependency,
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("valid", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
