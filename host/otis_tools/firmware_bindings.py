"""Independent host verification of the fixed firmware's repository bindings."""

from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_MANIFEST_PATH = (
    REPO_ROOT / "firmware/arduino/firmware_build_manifest.json"
)


def _canonical_sha256(value: object) -> str:
    return sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    ).hexdigest()


def _bound_file(relative: str) -> Path:
    relative_path = Path(relative)
    if relative_path.is_absolute() or any(
        part in {"", ".", ".."} for part in relative_path.parts
    ):
        raise ValueError(f"unsafe fixed-firmware repository binding: {relative!r}")
    path = REPO_ROOT / relative_path
    resolved = path.resolve(strict=True)
    if resolved != path.absolute() or not resolved.is_relative_to(REPO_ROOT):
        raise ValueError(f"fixed-firmware binding traverses a symlink: {relative}")
    if not resolved.is_file():
        raise ValueError(f"fixed-firmware binding is not a regular file: {relative}")
    return resolved


def fixed_firmware_repository_bindings() -> dict[str, Any]:
    manifest = json.loads(BUILD_MANIFEST_PATH.read_text(encoding="utf-8"))
    profile_paths = manifest.get("profile_bindings")
    contract = manifest.get("forwarded_clock_contract")
    if not isinstance(profile_paths, dict) or not isinstance(contract, dict):
        raise ValueError("fixed-firmware repository bindings are malformed")
    profiles: dict[str, dict[str, Any]] = {}
    for name, relative in profile_paths.items():
        if not isinstance(name, str) or not isinstance(relative, str):
            raise ValueError("fixed-firmware profile binding is malformed")
        path = _bound_file(relative)
        data = path.read_bytes()
        profiles[name] = {
            "path": relative,
            "size_bytes": len(data),
            "sha256": sha256(data).hexdigest(),
        }
    return {
        "profiles": profiles,
        "forwarded_clock_contract": contract,
        "forwarded_clock_contract_sha256": _canonical_sha256(contract),
    }


def current_profile_sha256(name: str) -> str:
    profiles = fixed_firmware_repository_bindings()["profiles"]
    try:
        return str(profiles[name]["sha256"])
    except KeyError as exc:
        raise ValueError(f"unknown fixed-firmware profile binding: {name}") from exc


def current_forwarded_clock_contract() -> tuple[dict[str, Any], str]:
    bindings = fixed_firmware_repository_bindings()
    return (
        dict(bindings["forwarded_clock_contract"]),
        str(bindings["forwarded_clock_contract_sha256"]),
    )
