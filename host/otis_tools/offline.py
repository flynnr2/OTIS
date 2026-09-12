"""Analyse and package closed acquisitions without owning a live instrument."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from typing import Any

from . import adaptive_hybrid_analyze
from .adaptive_hybrid_analyze import analyze
from .evidence_package import (
    ANALYSIS_CONTRACT,
    ANALYSIS_REPORT,
    CAPTURE_ACTIVE,
    PACKAGE_MANIFEST,
    seal_package,
    validate_package,
)
from .evidence_registry import register_package
from .run_loader import load_manifest
from .run_spec import load_run_spec, verify_current_host_toolset

_ANALYZER_PATH = Path(adaptive_hybrid_analyze.__file__).resolve()
_REPO_ROOT = Path(__file__).resolve().parents[2]


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=".offline-analysis-",
        delete=False,
    ) as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n")
        staged = Path(stream.name)
    try:
        os.link(staged, path)
    except FileExistsError:
        raise FileExistsError(
            f"offline analysis report already exists: {path}"
        ) from None
    finally:
        staged.unlink(missing_ok=True)


def _verify_frozen_analysis_toolset(root: Path) -> None:
    manifest = load_manifest(root)
    spec = load_run_spec(root / manifest.data["run_spec"]["path"])
    verify_current_host_toolset(spec)


def finish_run(run_dir: Path, *, registry_path: Path | None = None) -> dict[str, Any]:
    """Retain analysis success or failure, seal once, optionally record location.

    A closed acquisition is the input. Failure here has no firmware, capture,
    terminal, abort, or retry authority. Repeating finalization only validates
    the existing immutable result and retries optional registration.
    """

    source = run_dir.expanduser()
    if source.is_symlink():
        raise ValueError("offline finalization refuses a symlink run directory")
    root = source.resolve()
    if (root / CAPTURE_ACTIVE).exists():
        raise ValueError("capture remains active; offline finalization cannot close it")
    if not (root / PACKAGE_MANIFEST).exists():
        report = root / ANALYSIS_REPORT
        if not report.exists():
            try:
                _verify_frozen_analysis_toolset(root)
                analyze(root)
            except Exception as error:  # noqa: BLE001 - retain any analyzer failure
                # Diagnostic evidence is useful even when analysis cannot run.
                # Never label an analyzer exception as scientific rejection.
                diagnostic = {
                    "contract": ANALYSIS_CONTRACT,
                    "created_utc": datetime.now(timezone.utc).isoformat(),
                    "status": "review_required",
                    "outcome": "undetermined",
                    "failure_class": "offline_analysis_failure",
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "analyzer": {
                        "path": _ANALYZER_PATH.relative_to(_REPO_ROOT).as_posix(),
                        "sha256": sha256(_ANALYZER_PATH.read_bytes()).hexdigest(),
                    },
                    "firmware_authority": False,
                }
                _atomic_json(report, diagnostic)
        seal_package(root)
    package = validate_package(root)
    result = {
        "package_directory": str(root),
        "package_manifest": str(root / PACKAGE_MANIFEST),
        "package_content_sha256": package["package_content_sha256"],
        "capture": package["capture"],
        "analysis": package["analysis"],
        "registration": None,
    }
    if registry_path is not None:
        # Optional location bookkeeping cannot change the package or result.
        try:
            result["registration"] = register_package(root, registry_path)
        except (OSError, ValueError) as error:
            result["registration"] = {"status": "failed", "error": str(error)}
    return result
