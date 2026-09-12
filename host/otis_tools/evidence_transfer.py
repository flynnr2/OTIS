"""Transfer sealed portable evidence without interpreting its scientific result."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path, PurePosixPath
import re
import tarfile
import tempfile
from typing import Any

from .evidence_package import PACKAGE_MANIFEST, validate_package

TRANSFER_CONTRACT = "otis_portable_evidence_transfer_v1"


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_member(name: str) -> PurePosixPath:
    path = PurePosixPath(name)
    if not name or path.is_absolute() or ".." in path.parts or path.as_posix() != name:
        raise ValueError(f"invalid archive member: {name}")
    return path


def _expected_files(package: dict[str, Any]) -> list[dict[str, Any]]:
    return sorted([*package["inventory"], {"path": PACKAGE_MANIFEST.as_posix(),
                   "size_bytes": None, "sha256": None}], key=lambda entry: entry["path"])


def _archive_files(archive: Path, destination: Path | None = None) -> list[dict[str, Any]]:
    """Read only safe regular members, optionally creating the received files."""
    entries = []
    seen = set()
    with tarfile.open(archive, "r:gz") as stream:
        for member in stream:
            relative = _safe_member(member.name)
            if not member.isfile() or member.name in seen:
                raise ValueError(f"invalid archive member: {member.name}")
            seen.add(member.name)
            source = stream.extractfile(member)
            if source is None:
                raise ValueError(f"archive member has no content: {member.name}")
            output = None
            digest = sha256()
            size = 0
            try:
                if destination is not None:
                    target = destination.joinpath(*relative.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    output = target.open("xb")
                with source:
                    for block in iter(lambda: source.read(1024 * 1024), b""):
                        digest.update(block)
                        size += len(block)
                        if output is not None:
                            output.write(block)
            finally:
                if output is not None:
                    output.close()
            if size != member.size:
                raise ValueError(f"truncated archive member: {member.name}")
            entries.append({"path": member.name, "size_bytes": size, "sha256": digest.hexdigest()})
    return sorted(entries, key=lambda entry: entry["path"])


def inspect_package(source: Path) -> dict[str, Any]:
    """Report immutable package metadata without replaying a scientific verdict."""
    package = validate_package(source)
    return {"contract": TRANSFER_CONTRACT,
            "package_content_sha256": package["package_content_sha256"],
            "file_count": len(package["inventory"]),
            "uncompressed_bytes": sum(item["size_bytes"] for item in package["inventory"]),
            "capture": package["capture"], "analysis": package["analysis"]}


def publish_package(source: Path, output_dir: Path) -> dict[str, Any]:
    """Archive the exact sealed inventory, then publish an external receipt."""
    source = source.expanduser().resolve()
    package = validate_package(source)
    output = output_dir.expanduser().resolve()
    if output == source or source in output.parents:
        raise ValueError("delivery directory must be outside the source package")
    output.mkdir(parents=True, exist_ok=True)
    content_hash = package["package_content_sha256"]
    archive = output / f"{content_hash}.tar.gz"
    receipt_path = output / f"{content_hash}.transfer.json"
    if archive.exists() or receipt_path.exists():
        raise FileExistsError("delivery already exists")
    with tempfile.TemporaryDirectory(prefix=".otis-publish-", dir=output) as temporary:
        staged = Path(temporary) / archive.name
        with tarfile.open(staged, "w:gz", compresslevel=6) as stream:
            for entry in _expected_files(package):
                stream.add(source / entry["path"], arcname=entry["path"], recursive=False)
        members = _archive_files(staged)
        expected = _expected_files(validate_package(source))
        sealed_member = next(item for item in members if item["path"] == PACKAGE_MANIFEST.as_posix())
        expected = [sealed_member if item["path"] == PACKAGE_MANIFEST.as_posix() else item for item in expected]
        if members != sorted(expected, key=lambda entry: entry["path"]):
            raise ValueError("source changed during publication")
        receipt = {"contract": TRANSFER_CONTRACT, "archive_name": archive.name,
                   "archive_sha256": _file_sha256(staged), "archive_bytes": staged.stat().st_size,
                   "package_content_sha256": content_hash, "source_mutated": False}
        staged_receipt = Path(temporary) / receipt_path.name
        staged_receipt.write_text(json.dumps(receipt, sort_keys=True, indent=2) + "\n", encoding="utf-8")
        os.link(staged, archive)
        os.link(staged_receipt, receipt_path)
    return receipt


def receive_package(archive: Path, *, archive_sha256: str, content_sha256: str, destination: Path) -> Path:
    """Verify a portable archive and atomically promote its exact regular files."""
    if not all(re.fullmatch(r"[0-9a-f]{64}", value) for value in (archive_sha256, content_sha256)):
        raise ValueError("expected identities must be lowercase SHA-256 values")
    if _file_sha256(archive) != archive_sha256:
        raise ValueError("archive checksum differs from sender receipt")
    destination = destination.expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    target = destination / content_sha256
    if target.exists():
        if validate_package(target)["package_content_sha256"] != content_sha256:
            raise ValueError("existing destination differs; refusing replacement")
        return target
    with tempfile.TemporaryDirectory(prefix=".otis-receive-", dir=destination) as temporary:
        staged = Path(temporary) / "package"
        staged.mkdir()
        members = _archive_files(archive, staged)
        package = validate_package(staged)
        expected = _expected_files(package)
        sealed_member = next(item for item in members if item["path"] == PACKAGE_MANIFEST.as_posix())
        expected = [sealed_member if item["path"] == PACKAGE_MANIFEST.as_posix() else item for item in expected]
        if (package["package_content_sha256"] != content_sha256
                or members != sorted(expected, key=lambda entry: entry["path"])):
            raise ValueError("received package inventory differs from its seal")
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
        result = {"verified_local_path": str(receive_package(args.archive, archive_sha256=args.archive_sha256, content_sha256=args.content_sha256, destination=args.destination))}
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
