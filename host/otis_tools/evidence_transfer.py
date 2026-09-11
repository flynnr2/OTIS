"""Deliver closed evidence as immutable archives; never operate a live capture."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import tarfile
import tempfile
from typing import Any

from .evidence import package_identity


TRANSFER_CONTRACT = "otis_evidence_transfer_v1"
SEAL_PATH = Path("reports/adaptive_hybrid_physical_seal_v1.json")
INERT_RUNTIME_FIFO_PATHS = frozenset(
    {
        "control/emergency_abort.fifo",
        "control/host_abort.fifo",
        "control/normal_commands.fifo",
    }
)


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _closed_package(
    source: Path,
) -> tuple[dict[str, Any], list[dict[str, str]]]:
    if source.is_symlink() or not source.is_dir():
        raise ValueError("source must be a real package directory")
    if (source / "capture_in_progress.flag").exists():
        raise ValueError("active capture cannot be published")
    for relative in (Path("COMPLETE"), Path("run_manifest.json"),
                     Path("evidence_manifest.json"), SEAL_PATH):
        if not (source / relative).is_file():
            raise ValueError(f"closed package is missing {relative}")
    omitted_runtime_endpoints: list[dict[str, str]] = []
    for path in source.rglob("*"):
        mode = path.lstat().st_mode
        if stat.S_ISREG(mode) or stat.S_ISDIR(mode):
            continue
        relative = path.relative_to(source).as_posix()
        if stat.S_ISFIFO(mode) and relative in INERT_RUNTIME_FIFO_PATHS:
            omitted_runtime_endpoints.append(
                {"relative_path": relative, "type": "fifo"}
            )
            continue
        raise ValueError(f"package contains a link or special file: {path}")
    return package_identity(source), sorted(
        omitted_runtime_endpoints, key=lambda entry: entry["relative_path"]
    )


def inspect_package(source: Path) -> dict[str, Any]:
    """Measure a closed package without interpreting its scientific verdict."""
    identity, omitted_runtime_endpoints = _closed_package(source.expanduser())
    return {
        "contract": TRANSFER_CONTRACT,
        "content_sha256": identity["content_sha256"],
        "file_count": identity["file_count"],
        "uncompressed_bytes": identity["total_bytes"],
        "omitted_runtime_endpoints": omitted_runtime_endpoints,
        "scientific_validation_performed": False,
    }


def _archive_files(archive: Path, destination: Path | None = None) -> list[dict[str, Any]]:
    """Hash regular members; optionally copy them without tar extraction APIs."""
    entries: dict[str, dict[str, Any]] = {}
    with tarfile.open(archive, "r:gz") as stream:
        for member in stream:
            path = PurePosixPath(member.name)
            if (not member.isfile() or path.is_absolute()
                    or not path.parts or ".." in path.parts
                    or path.as_posix() != member.name
                    or member.name in entries):
                raise ValueError(f"invalid or repeated archive member: {member.name}")
            digest = sha256()
            size = 0
            output = None
            try:
                if destination is not None:
                    target = destination.joinpath(*path.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    output = target.open("xb")
                source = stream.extractfile(member)
                if source is None:
                    raise ValueError(f"archive member has no content: {member.name}")
                with source:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(block)
                        size += len(block)
                        if output is not None:
                            output.write(block)
                if size != member.size:
                    raise ValueError(f"truncated archive member: {member.name}")
            finally:
                if output is not None:
                    output.close()
            entries[member.name] = {
                "relative_path": member.name,
                "size_bytes": size,
                "sha256": digest.hexdigest(),
            }
    return [entries[name] for name in sorted(entries)]


def publish_package(source: Path, output_dir: Path) -> dict[str, Any]:
    """Publish archive first and receipt last, without overwriting either."""
    source = source.expanduser()
    identity, omitted_runtime_endpoints = _closed_package(source)
    source = source.resolve()
    output = output_dir.expanduser().resolve()
    if output == source or source in output.parents:
        raise ValueError("delivery directory must be outside the source package")
    output.mkdir(parents=True, exist_ok=True)
    archive = output / f"{identity['content_sha256']}.tar.gz"
    receipt_path = output / f"{identity['content_sha256']}.transfer.json"
    if archive.exists() or receipt_path.exists():
        raise ValueError("delivery already exists; verify or use a new delivery directory")
    with tempfile.TemporaryDirectory(prefix=".otis-publish-", dir=output) as temporary:
        staged = Path(temporary) / archive.name
        with tarfile.open(staged, "w:gz", compresslevel=6) as stream:
            for entry in identity["files"]:
                stream.add(source / entry["relative_path"],
                           arcname=entry["relative_path"], recursive=False)
        if _archive_files(staged) != identity["files"]:
            raise ValueError("source changed during publication")
        current_identity, current_omitted_runtime_endpoints = _closed_package(source)
        if (current_identity != identity
                or current_omitted_runtime_endpoints
                != omitted_runtime_endpoints):
            raise ValueError("source changed during publication")
        receipt = {
            "contract": TRANSFER_CONTRACT,
            "archive_name": archive.name,
            "archive_sha256": _file_sha256(staged),
            "archive_bytes": staged.stat().st_size,
            "package": identity,
            "omitted_runtime_endpoints": omitted_runtime_endpoints,
            "scientific_validation_performed": False,
            "source_mutated": False,
        }
        staged_receipt = Path(temporary) / receipt_path.name
        staged_receipt.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n")
        # Same-filesystem links publish complete files and refuse replacement.
        os.link(staged, archive)
        os.link(staged_receipt, receipt_path)
    return receipt


def receive_package(archive: Path, *, archive_sha256: str,
                    content_sha256: str, destination: Path) -> Path:
    """Verify sender identities and promote a complete local copy atomically."""
    if not all(re.fullmatch(r"[0-9a-f]{64}", value)
               for value in (archive_sha256, content_sha256)):
        raise ValueError("expected identities must be lowercase SHA-256 values")
    if _file_sha256(archive) != archive_sha256:
        raise ValueError("archive checksum differs from sender receipt")
    destination = destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / content_sha256
    if target.exists():
        identity, _ = _closed_package(target)
        if identity["content_sha256"] != content_sha256:
            raise ValueError("existing destination differs; refusing replacement")
        return target
    with tempfile.TemporaryDirectory(prefix=".otis-receive-", dir=destination) as temporary:
        staged = Path(temporary) / "package"
        staged.mkdir()
        members = _archive_files(archive, staged)
        identity, _ = _closed_package(staged)
        if (identity["content_sha256"] != content_sha256
                or identity["files"] != members
                or _file_sha256(archive) != archive_sha256):
            raise ValueError("received package or archive identity differs")
        staged.rename(target)
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    inspect = commands.add_parser("inspect")
    inspect.add_argument("source", type=Path)
    publish = commands.add_parser("publish")
    publish.add_argument("source", type=Path)
    publish.add_argument("--output-dir", required=True, type=Path)
    receive = commands.add_parser("receive")
    receive.add_argument("archive", type=Path)
    receive.add_argument("--archive-sha256", required=True)
    receive.add_argument("--content-sha256", required=True)
    receive.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == "inspect":
        result = inspect_package(args.source)
    elif args.command == "publish":
        result = publish_package(args.source, args.output_dir)
    else:
        result = {"verified_local_path": str(receive_package(
            args.archive, archive_sha256=args.archive_sha256,
            content_sha256=args.content_sha256, destination=args.destination))}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
