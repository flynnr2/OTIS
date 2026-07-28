from __future__ import annotations

from hashlib import sha256
from pathlib import Path, PurePosixPath
import argparse
import json
import os
import shutil

from .run_loader import CAPTURE_IN_PROGRESS_FLAG, COMPLETE_MARKER, load_manifest


EVIDENCE_MANIFEST = "evidence_manifest.json"
EVIDENCE_SCHEMA_VERSION = 1
DIGEST_ALGORITHM = "sha256"
PROFILE_SNAPSHOT = "selected_profile.yaml"
REPO_ROOT = Path(__file__).resolve().parents[2]


class EvidenceError(ValueError):
    pass


def _digest_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise EvidenceError("artifact path must be a non-empty string")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value != path.as_posix():
        raise EvidenceError(f"artifact path is not a normalized run-relative path: {value!r}")
    return value


def _artifact_path(run_dir: Path, rel_path: str) -> Path:
    path = run_dir / rel_path
    current = run_dir
    for part in PurePosixPath(rel_path).parts:
        current = current / part
        if current.is_symlink():
            raise EvidenceError(f"artifact path traverses a symbolic link: {rel_path}")
    return path


def _snapshot_payload(snapshot: dict) -> dict:
    return {
        "schema_version": snapshot["schema_version"],
        "run_id": snapshot["run_id"],
        "run_state": snapshot["run_state"],
        "digest_algorithm": snapshot["digest_algorithm"],
        "artifacts": snapshot["artifacts"],
    }


def _snapshot_digest(snapshot: dict) -> str:
    canonical = json.dumps(
        _snapshot_payload(snapshot),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def _copy_profile_snapshot(run_dir: Path, manifest) -> None:
    profile = manifest.data.get("profile")
    if not isinstance(profile, dict) or not profile.get("name"):
        return
    destination = run_dir / PROFILE_SNAPSHOT
    if destination.exists():
        return
    source = REPO_ROOT / "profiles" / f"{profile['name']}.yaml"
    if not source.is_file():
        raise EvidenceError(f"cannot snapshot missing profile: {source}")
    shutil.copyfile(source, destination)


def _artifact_sources(run_dir: Path, manifest) -> dict[str, dict[str, object]]:
    sources: dict[str, dict[str, object]] = {
        manifest.path.relative_to(run_dir).as_posix(): {"role": "run_manifest"}
    }

    for name, role in (("config.env", "configuration"), (PROFILE_SNAPSHOT, "profile_snapshot")):
        if _artifact_path(run_dir, name).is_file():
            sources[name] = {"role": role}

    raw_dir = run_dir / "raw"
    if raw_dir.is_dir():
        for path in sorted(raw_dir.rglob("*")):
            if path.is_file():
                sources[path.relative_to(run_dir).as_posix()] = {"role": "raw_evidence"}
    for legacy_name in ("serial_raw.log", "raw_serial.log"):
        if _artifact_path(run_dir, legacy_name).is_file():
            sources[legacy_name] = {"role": "raw_evidence"}

    for entry in manifest.files:
        rel_path = _safe_relative_path(entry.get("path"))
        path = _artifact_path(run_dir, rel_path)
        if not path.is_file():
            if entry.get("optional"):
                continue
            raise EvidenceError(f"required declared artifact is missing: {rel_path}")
        metadata: dict[str, object] = {"role": "declared_artifact"}
        if entry.get("contract"):
            metadata["contract"] = str(entry["contract"])
        sources[rel_path] = metadata
    return sources


def create_evidence_snapshot(run_dir: Path, allow_incomplete: bool = False) -> Path:
    run_dir = run_dir.resolve()
    if (run_dir / CAPTURE_IN_PROGRESS_FLAG).exists():
        raise EvidenceError("capture is in progress; refusing to snapshot mutable evidence")
    if not allow_incomplete and not (run_dir / COMPLETE_MARKER).exists():
        raise EvidenceError(
            f"{COMPLETE_MARKER} marker is missing; pass --allow-incomplete "
            "only for an intentional partial-run snapshot"
        )

    destination = run_dir / EVIDENCE_MANIFEST
    if destination.exists():
        raise FileExistsError(f"evidence snapshot already exists: {destination}")

    manifest = load_manifest(run_dir)
    if manifest.is_template:
        raise EvidenceError("template directories cannot be sealed as run evidence")
    _copy_profile_snapshot(run_dir, manifest)

    artifacts = []
    for rel_path, metadata in sorted(_artifact_sources(run_dir, manifest).items()):
        path = _artifact_path(run_dir, rel_path)
        artifacts.append(
            {
                "path": rel_path,
                **metadata,
                "size_bytes": path.stat().st_size,
                "sha256": _digest_file(path),
            }
        )

    snapshot = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "run_id": manifest.run_id,
        "run_state": "complete" if (run_dir / COMPLETE_MARKER).exists() else "partial",
        "digest_algorithm": DIGEST_ALGORITHM,
        "artifacts": artifacts,
    }
    snapshot["snapshot_digest"] = _snapshot_digest(snapshot)
    encoded = (json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    with destination.open("xb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    return destination


def validate_evidence_snapshot(run_dir: Path, manifest) -> tuple[list[str], list[str]]:
    path = run_dir / EVIDENCE_MANIFEST
    if not path.exists():
        if manifest.is_template:
            return [], []
        return [], [f"{EVIDENCE_MANIFEST}: immutable evidence snapshot is missing"]

    failures: list[str] = []
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{EVIDENCE_MANIFEST}: cannot read snapshot: {exc}"], []
    if not isinstance(snapshot, dict):
        return [f"{EVIDENCE_MANIFEST}: root must be an object"], []
    if snapshot.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        failures.append(f"{EVIDENCE_MANIFEST}: unsupported schema_version {snapshot.get('schema_version')!r}")
    if snapshot.get("run_id") != manifest.run_id:
        failures.append(f"{EVIDENCE_MANIFEST}: run_id does not match run manifest")
    if snapshot.get("run_state") not in {"complete", "partial"}:
        failures.append(f"{EVIDENCE_MANIFEST}: run_state must be 'complete' or 'partial'")
    if snapshot.get("digest_algorithm") != DIGEST_ALGORITHM:
        failures.append(f"{EVIDENCE_MANIFEST}: digest_algorithm must be {DIGEST_ALGORITHM!r}")

    artifacts = snapshot.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return failures + [f"{EVIDENCE_MANIFEST}: artifacts must be a non-empty array"], []
    allowed_snapshot_keys = {
        "schema_version",
        "run_id",
        "run_state",
        "digest_algorithm",
        "artifacts",
        "snapshot_digest",
    }
    extra_snapshot_keys = set(snapshot) - allowed_snapshot_keys
    if extra_snapshot_keys:
        failures.append(f"{EVIDENCE_MANIFEST}: unsupported fields {sorted(extra_snapshot_keys)}")
    required_snapshot_keys = ("schema_version", "run_id", "run_state", "digest_algorithm", "artifacts")
    if all(key in snapshot for key in required_snapshot_keys):
        if snapshot.get("snapshot_digest") != _snapshot_digest(snapshot):
            failures.append(f"{EVIDENCE_MANIFEST}: snapshot_digest does not match canonical snapshot content")

    seen: set[str] = set()
    listed: set[str] = set()
    previous = ""
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            failures.append(f"{EVIDENCE_MANIFEST}: artifact {index} must be an object")
            continue
        allowed_artifact_keys = {"path", "role", "contract", "size_bytes", "sha256"}
        required_artifact_keys = {"path", "role", "size_bytes", "sha256"}
        extra_artifact_keys = set(artifact) - allowed_artifact_keys
        missing_artifact_keys = required_artifact_keys - set(artifact)
        if extra_artifact_keys:
            failures.append(
                f"{EVIDENCE_MANIFEST}: artifact {index} has unsupported fields {sorted(extra_artifact_keys)}"
            )
        if missing_artifact_keys:
            failures.append(
                f"{EVIDENCE_MANIFEST}: artifact {index} is missing fields {sorted(missing_artifact_keys)}"
            )
        if artifact.get("role") not in {
            "run_manifest",
            "configuration",
            "profile_snapshot",
            "raw_evidence",
            "declared_artifact",
        }:
            failures.append(f"{EVIDENCE_MANIFEST}: artifact {index} has an unsupported evidence role")
        if "contract" in artifact and (
            not isinstance(artifact["contract"], str) or not artifact["contract"]
        ):
            failures.append(f"{EVIDENCE_MANIFEST}: artifact {index} contract must be a non-empty string")
        try:
            rel_path = _safe_relative_path(artifact.get("path"))
        except EvidenceError as exc:
            failures.append(f"{EVIDENCE_MANIFEST}: artifact {index}: {exc}")
            continue
        if rel_path == EVIDENCE_MANIFEST:
            failures.append(f"{EVIDENCE_MANIFEST}: snapshot must not include itself")
        if rel_path in seen:
            failures.append(f"{EVIDENCE_MANIFEST}: duplicate artifact path {rel_path!r}")
        if previous and rel_path < previous:
            failures.append(f"{EVIDENCE_MANIFEST}: artifacts are not sorted by path")
        seen.add(rel_path)
        listed.add(rel_path)
        previous = rel_path
        try:
            artifact_path = _artifact_path(run_dir, rel_path)
        except EvidenceError as exc:
            failures.append(str(exc))
            continue
        if not artifact_path.is_file():
            failures.append(f"{rel_path}: snapshotted artifact is missing or is not a regular file")
            continue
        size = artifact_path.stat().st_size
        if not isinstance(artifact.get("size_bytes"), int) or artifact["size_bytes"] < 0:
            failures.append(f"{rel_path}: snapshot size_bytes is malformed")
        elif artifact["size_bytes"] != size:
            failures.append(f"{rel_path}: size differs from evidence snapshot")
        expected_digest = artifact.get("sha256")
        if (
            not isinstance(expected_digest, str)
            or len(expected_digest) != 64
            or any(character not in "0123456789abcdef" for character in expected_digest)
        ):
            failures.append(f"{rel_path}: snapshot SHA-256 is malformed")
        elif _digest_file(artifact_path) != expected_digest:
            failures.append(f"{rel_path}: SHA-256 differs from evidence snapshot")

    try:
        required = _artifact_sources(run_dir, manifest)
    except EvidenceError as exc:
        failures.append(str(exc))
    else:
        required_paths = set(required)
        for rel_path in sorted(required_paths - listed):
            failures.append(f"{rel_path}: evidence-bearing artifact is not covered by {EVIDENCE_MANIFEST}")
        for rel_path in sorted(listed - required_paths):
            failures.append(f"{rel_path}: snapshotted artifact is outside the defined evidence scope")
        artifact_by_path = {
            artifact.get("path"): artifact
            for artifact in artifacts
            if isinstance(artifact, dict) and isinstance(artifact.get("path"), str)
        }
        for rel_path in sorted(required_paths & listed):
            artifact = artifact_by_path.get(rel_path, {})
            expected = required[rel_path]
            if artifact.get("role") != expected["role"]:
                failures.append(f"{rel_path}: evidence role does not match snapshot scope")
            if artifact.get("contract") != expected.get("contract"):
                failures.append(f"{rel_path}: evidence contract does not match run manifest")
    return failures, []


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an immutable SHA-256 evidence snapshot for an OTIS run.")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="Snapshot a run without a COMPLETE marker; the partial status remains explicit.",
    )
    args = parser.parse_args()
    try:
        path = create_evidence_snapshot(args.run_dir, args.allow_incomplete)
    except (EvidenceError, FileExistsError, FileNotFoundError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc
    print(path)


if __name__ == "__main__":
    main()
