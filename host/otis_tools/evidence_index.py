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
    "completed_campaign",
    "interrupted_campaign",
    "diagnostic",
    "historical",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


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
    profile_identity: str,
    attempt_classification: str,
    result_or_failure_reason: str,
    analyzer_identity: str,
) -> dict[str, Any]:
    required = {
        "source_revision": source_revision,
        "build_identity": build_identity,
        "profile_identity": profile_identity,
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

    location = package_path.expanduser().resolve()
    identity = package_identity(location)
    content_sha256 = identity["content_sha256"]
    immutable_metadata = {
        "source_revision": source_revision,
        "build_identity": build_identity,
        "profile_identity": profile_identity,
        "attempt_classification": attempt_classification,
        "result_or_failure_reason": result_or_failure_reason,
        "analyzer_identity": analyzer_identity,
    }
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
    register.add_argument("--profile-identity", required=True)
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
            profile_identity=args.profile_identity,
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
