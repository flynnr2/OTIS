"""Portable, immutable closure for one completed OTIS acquisition."""

from __future__ import annotations

import json
import math
import os
import stat
import tempfile
from hashlib import sha256
from pathlib import Path, PurePosixPath
from typing import Any

PACKAGE_CONTRACT = "otis_portable_evidence_package_v1"
PACKAGE_MANIFEST = Path("evidence_package_v1.json")
RUN_MANIFEST = Path("run_manifest.json")
RUN_SPEC_CONTRACT = "otis_run_spec_v1"
RUN_RECORD_CONTRACT = "otis_run_record_v1"
CAPTURE_ACTIVE = Path("capture_in_progress.flag")
CAPTURE_CLOSURE = Path("reports/capture_segment_closure_v1.json")
ANALYSIS_REPORT = Path("reports/offline_analysis_v1.json")
_RUNTIME_FIFOS = {
    "normal_command": "control/normal_commands.fifo",
    "emergency_abort": "control/emergency_abort.fifo",
}
_OUTCOMES = frozenset(
    {
        "qualified_complete",
        "bounded_nonpass",
        "interrupted_incomplete",
        "diagnostic_complete",
        "undetermined",
    }
)


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON value is forbidden: {value}")


def _json_bytes(value: Any) -> bytes:
    try:
        return (
            json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            )
            + "\n"
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise ValueError("package metadata is not finite canonical JSON") from error


def _identity_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("ascii")
    except (TypeError, ValueError) as error:
        raise ValueError("retained identity is not finite canonical JSON") from error


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _safe_relative(value: str) -> PurePosixPath:
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or ".." in path.parts
        or path.as_posix() != value
    ):
        raise ValueError(f"unsafe package path: {value!r}")
    return path


def safe_join(root: Path, relative: str) -> Path:
    """Resolve a portable package member beneath *root* without link traversal."""

    path = root.joinpath(*_safe_relative(relative).parts)
    resolved_root = root.resolve()
    resolved_parent = path.parent.resolve()
    if resolved_root not in (resolved_parent, *resolved_parent.parents):
        raise ValueError(f"unsafe package path: {relative!r}")
    return path


def _portable(value: Any) -> Any:
    if isinstance(value, str):
        # Evidence strings may describe historical device or acquisition paths.
        # Only inventory/member paths are used to resolve package files.
        return value
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("portable metadata contains a non-finite number")
        return value
    if isinstance(value, list):
        return [_portable(item) for item in value]
    if isinstance(value, dict) and all(isinstance(key, str) for key in value):
        return {key: _portable(item) for key, item in value.items()}
    raise ValueError("portable metadata must be finite JSON with string keys")


def _read_object(path: Path, description: str) -> dict[str, Any]:
    try:
        value = json.loads(
            path.read_text(encoding="utf-8"), parse_constant=_reject_json_constant
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        raise ValueError(f"invalid {description}: {path}") from error
    if not isinstance(value, dict):
        raise TypeError(f"{description} must be a JSON object")
    return _portable(value)


def _validate_run_binding(root: Path) -> tuple[dict[str, Any], set[str]]:
    """Validate retained record/spec identities without current runtime code."""

    record_path = root / RUN_MANIFEST
    record = _read_object(record_path, "run record")
    expected_record_keys = {
        "schema_version",
        "contract",
        "execution_kind",
        "run_id",
        "started_at_utc",
        "serial_device",
        "run_spec",
        "entry_authorization",
        "run_record_sha256",
    }
    binding = record.get("run_spec")
    if (
        set(record) != expected_record_keys
        or record.get("schema_version") != 1
        or record.get("contract") != RUN_RECORD_CONTRACT
        or not isinstance(binding, dict)
        or set(binding) != {"path", "sha256", "file_sha256", "size_bytes"}
    ):
        raise ValueError("run record shape or run-spec binding differs")
    unsigned_record = {
        key: item for key, item in record.items() if key != "run_record_sha256"
    }
    if (
        record.get("run_record_sha256")
        != sha256(_identity_bytes(unsigned_record)).hexdigest()
    ):
        raise ValueError("run record content identity differs")
    relative = binding.get("path")
    if not isinstance(relative, str):
        raise TypeError("run-spec binding path is malformed")
    spec_path = safe_join(root, relative)
    if relative != "run_spec.json" or spec_path.is_symlink() or not spec_path.is_file():
        raise ValueError("run specification is not the retained portable regular file")
    if (
        not isinstance(binding.get("size_bytes"), int)
        or isinstance(binding.get("size_bytes"), bool)
        or binding["size_bytes"] != spec_path.stat().st_size
        or binding.get("file_sha256") != _sha256(spec_path)
    ):
        raise ValueError("retained run-spec byte binding differs")
    spec = _read_object(spec_path, "run specification")
    unsigned_spec = {
        key: item for key, item in spec.items() if key != "run_spec_sha256"
    }
    spec_sha256 = sha256(_identity_bytes(unsigned_spec)).hexdigest()
    if (
        spec.get("schema_version") != 1
        or spec.get("contract") != RUN_SPEC_CONTRACT
        or spec.get("run_spec_sha256") != spec_sha256
        or binding.get("sha256") != spec_sha256
    ):
        raise ValueError("retained run-spec semantic identity differs")
    runtime = spec.get("runtime")
    topology = runtime.get("topology") if isinstance(runtime, dict) else None
    fifos = topology.get("fifos") if isinstance(topology, dict) else None
    if fifos != _RUNTIME_FIFOS:
        raise ValueError("run specification runtime FIFO declaration differs")
    return record, set(fifos.values())


def _validate_omissions(
    value: object, *, allowed_fifos: set[str]
) -> list[dict[str, str]]:
    if not isinstance(value, list):
        raise TypeError("runtime endpoint omissions must be a list")
    expected = sorted(
        value, key=lambda item: item.get("path", "") if isinstance(item, dict) else ""
    )
    if value != expected:
        raise ValueError("runtime endpoint omissions are not ordered")
    paths: list[str] = []
    for item in value:
        if (
            not isinstance(item, dict)
            or set(item) != {"path", "type"}
            or item.get("type") != "fifo"
            or item.get("path") not in allowed_fifos
        ):
            raise ValueError("runtime endpoint omission is undeclared or malformed")
        paths.append(str(item["path"]))
    if len(paths) != len(set(paths)):
        raise ValueError("runtime endpoint omissions are duplicated")
    return [{"path": path, "type": "fifo"} for path in paths]


def _inventory(
    root: Path,
    *,
    allowed_fifos: set[str],
    retained_omissions: object | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    entries: list[dict[str, Any]] = []
    omitted_paths: set[str] = set()
    for path in root.rglob("*"):
        relative = path.relative_to(root).as_posix()
        if relative == PACKAGE_MANIFEST.as_posix():
            continue
        mode = path.lstat().st_mode
        if stat.S_ISDIR(mode):
            continue
        if path.name.endswith(".lock"):
            raise ValueError(f"package contains an undeclared lock file: {relative}")
        if stat.S_ISFIFO(mode):
            if relative not in allowed_fifos:
                raise ValueError(f"package contains an undeclared FIFO: {relative}")
            omitted_paths.add(relative)
            continue
        if not stat.S_ISREG(mode):
            raise ValueError(f"package contains a link or special file: {relative}")
        entries.append(
            {
                "path": relative,
                "size_bytes": path.stat().st_size,
                "sha256": _sha256(path),
            }
        )
    retained = (
        []
        if retained_omissions is None
        else _validate_omissions(retained_omissions, allowed_fifos=allowed_fifos)
    )
    retained_paths = {item["path"] for item in retained}
    unexpected = (
        omitted_paths - retained_paths if retained_omissions is not None else set()
    )
    if unexpected:
        raise ValueError("package gained an unrecorded runtime FIFO")
    for relative in retained_paths:
        candidate = safe_join(root, relative)
        if candidate.exists() and not stat.S_ISFIFO(candidate.lstat().st_mode):
            raise ValueError("omitted runtime endpoint became a packaged payload")
    omissions = sorted(
        ({"path": path, "type": "fifo"} for path in omitted_paths | retained_paths),
        key=lambda item: item["path"],
    )
    return sorted(entries, key=lambda entry: entry["path"]), omissions


def _analysis(root: Path) -> dict[str, Any]:
    report = root / ANALYSIS_REPORT
    if not report.exists():
        return {"status": "review_required", "outcome": "undetermined"}
    value = _read_object(report, "analysis report")
    if value.get("status") not in {"passed", "review_required"}:
        raise ValueError("analysis report status must be passed or review_required")
    if value.get("outcome") not in _OUTCOMES:
        raise ValueError("analysis report outcome is not recognised")
    return {
        "status": value["status"],
        "outcome": value["outcome"],
        "path": ANALYSIS_REPORT.as_posix(),
        "sha256": _sha256(report),
    }


def _unsigned(
    root: Path, *, retained_omissions: object | None = None
) -> dict[str, Any]:
    run_manifest = root / RUN_MANIFEST
    if not run_manifest.is_file() or run_manifest.is_symlink():
        raise ValueError("package is missing its regular run_manifest.json")
    record, allowed_fifos = _validate_run_binding(root)
    inventory, omissions = _inventory(
        root,
        allowed_fifos=allowed_fifos,
        retained_omissions=retained_omissions,
    )
    if not any(entry["path"].startswith("raw/") for entry in inventory):
        raise ValueError("package is missing canonical raw capture evidence")
    closure = root / CAPTURE_CLOSURE
    capture: dict[str, Any] = {"integrity": "partial", "closure_path": None}
    if closure.is_file() and not closure.is_symlink():
        capture["closure_path"] = CAPTURE_CLOSURE.as_posix()
        try:
            closure_value = _read_object(closure, "capture closure")
        except ValueError:
            closure_value = {}
        if (
            closure_value.get("logical_segment_closed") is True
            and closure_value.get("physical_serial_open") is False
            and closure_value.get("run_manifest_sha256") == _sha256(run_manifest)
        ):
            capture["integrity"] = "complete"
    return {
        "contract": PACKAGE_CONTRACT,
        "run_manifest": record,
        "capture": capture,
        "analysis": _analysis(root),
        "inventory": inventory,
        "omitted_runtime_endpoints": omissions,
    }


def _atomic_create(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=path.parent, prefix=".package-", delete=False
    ) as stream:
        stream.write(_json_bytes(value))
        staged = Path(stream.name)
    try:
        os.link(staged, path)
    except FileExistsError:
        raise FileExistsError(
            f"immutable package file already exists: {path}"
        ) from None
    finally:
        staged.unlink(missing_ok=True)


def seal_package(run_dir: Path, *, analysis: dict[str, Any] | None = None) -> Path:
    """Create the one immutable portable package manifest for a closed run."""

    source = run_dir.expanduser()
    if source.is_symlink():
        raise ValueError("run directory must not be a symlink")
    root = source.resolve()
    if not root.is_dir():
        raise ValueError("run directory must be a real directory")
    if (root / CAPTURE_ACTIVE).exists():
        raise ValueError("active capture cannot be sealed")
    seal = root / PACKAGE_MANIFEST
    if seal.exists():
        raise FileExistsError(
            "sealed package cannot be changed; make a linked report/package"
        )
    if analysis is not None:
        report = root / ANALYSIS_REPORT
        if report.exists():
            raise FileExistsError("analysis report already exists")
        _atomic_create(report, _portable(analysis))
    unsigned = _unsigned(root)
    manifest = {
        **unsigned,
        "package_content_sha256": sha256(_json_bytes(unsigned)).hexdigest(),
    }
    _atomic_create(seal, manifest)
    return seal


def validate_package(run_dir: Path) -> dict[str, Any]:
    """Verify immutable package metadata and every regular payload byte."""

    source = run_dir.expanduser()
    if source.is_symlink():
        raise ValueError("run directory must not be a symlink")
    root = source.resolve()
    if (root / CAPTURE_ACTIVE).exists():
        raise ValueError("active capture cannot be validated")
    recorded = _read_object(root / PACKAGE_MANIFEST, "package manifest")
    identity = recorded.pop("package_content_sha256", None)
    if not isinstance(identity, str) or len(identity) != 64:
        raise ValueError("package manifest has no valid content identity")
    current = _unsigned(
        root, retained_omissions=recorded.get("omitted_runtime_endpoints")
    )
    if recorded != current or identity != sha256(_json_bytes(current)).hexdigest():
        raise ValueError("package payload or metadata differs from immutable seal")
    return {**current, "package_content_sha256": identity}
