"""External location registry for already validated portable evidence."""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

from .evidence_package import validate_package

REGISTRY_CONTRACT = "otis_evidence_registry_v1"
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_OUTCOMES = {
    "qualified_complete",
    "bounded_nonpass",
    "interrupted_incomplete",
    "diagnostic_complete",
    "undetermined",
}


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite registry JSON value is forbidden: {value}")


def _validate_analysis(value: object) -> bool:
    if not isinstance(value, dict) or value.get("status") not in {
        "passed",
        "review_required",
    } or value.get("outcome") not in _OUTCOMES:
        return False
    if set(value) == {"status", "outcome"}:
        return value == {"status": "review_required", "outcome": "undetermined"}
    return (
        set(value) == {"status", "outcome", "path", "sha256"}
        and value.get("path") == "reports/offline_analysis_v1.json"
        and bool(_HEX64.fullmatch(str(value.get("sha256", ""))))
    )


def _atomic_write(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=".registry-",
        delete=False,
    ) as stream:
        json.dump(
            value,
            stream,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        stream.write("\n")
        staged = Path(stream.name)
    try:
        os.replace(staged, path)
    finally:
        staged.unlink(missing_ok=True)


def _validate_entry(identity: str, value: object) -> dict[str, Any]:
    if (
        not _HEX64.fullmatch(identity)
        or not isinstance(value, dict)
        or set(value)
        != {
            "package_content_sha256",
            "capture_integrity",
            "analysis",
            "locations",
        }
        or value.get("package_content_sha256") != identity
        or value.get("capture_integrity") not in {"complete", "partial"}
        or not _validate_analysis(value.get("analysis"))
        or not isinstance(value.get("locations"), list)
    ):
        raise ValueError("registry entry shape or identity differs")
    locations = value["locations"]
    if any(not isinstance(item, str) for item in locations) or locations != sorted(
        set(locations)
    ) or any(not Path(item).is_absolute() for item in locations):
        raise ValueError("registry package locations are malformed")
    return value


def _load(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"contract": REGISTRY_CONTRACT, "packages": {}}
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), parse_constant=_reject_json_constant
        )
    except (OSError, json.JSONDecodeError, ValueError) as error:
        raise ValueError("registry is not valid JSON") from error
    if (
        not isinstance(value, dict)
        or set(value) != {"contract", "packages"}
        or value.get("contract") != REGISTRY_CONTRACT
        or not isinstance(value.get("packages"), dict)
    ):
        raise ValueError("registry contract is not recognised")
    for identity, entry in value["packages"].items():
        _validate_entry(identity, entry)
    return value


def register_package(package_dir: Path, registry_path: Path) -> dict[str, Any]:
    """Register a validated package location without changing the package."""

    package = validate_package(package_dir)
    registry_path = registry_path.expanduser().resolve()
    registry = _load(registry_path)
    content_hash = package["package_content_sha256"]
    location = str(package_dir.expanduser().resolve())
    expected = {
        "package_content_sha256": content_hash,
        "capture_integrity": package["capture"]["integrity"],
        "analysis": package["analysis"],
    }
    entry = registry["packages"].get(content_hash)
    if entry is None:
        entry = {**expected, "locations": []}
        registry["packages"][content_hash] = entry
    else:
        _validate_entry(content_hash, entry)
        if any(entry.get(key) != value for key, value in expected.items()):
            raise ValueError("registry entry contradicts the validated package")
    if location not in entry["locations"]:
        entry["locations"].append(location)
        entry["locations"].sort()
        _atomic_write(registry_path, registry)
    return {
        "contract": REGISTRY_CONTRACT,
        "package_content_sha256": content_hash,
        "registry_path": str(registry_path),
        "locations": list(entry["locations"]),
    }
