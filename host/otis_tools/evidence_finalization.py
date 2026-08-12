"""Durable, retryable evidence-finalization and registration journal."""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Iterator

from .evidence_index import package_identity, register_package


CONTRACT_ID = "otis_evidence_finalization_v1"
PHASES = (
    "capture_closed",
    "completion",
    "snapshot",
    "analysis",
    "seal",
    "registration",
)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def journal_path_for(run_dir: Path) -> Path:
    run = run_dir.expanduser().resolve()
    return run.parent / ".otis-finalization" / f"{run.name}.json"


@contextmanager
def _locked(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(
        path.with_name(f".{path.name}.lock"),
        os.O_RDWR | os.O_CREAT,
        0o600,
    )
    try:
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _atomic_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
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


def _read(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("contract") != CONTRACT_ID:
        raise ValueError("unexpected evidence finalization journal identity")
    if tuple(value.get("phase_order", ())) != PHASES:
        raise ValueError("evidence finalization phase order differs")
    return value


def begin_finalization(
    *,
    run_dir: Path,
    index_path: Path,
    registration: dict[str, str],
    required_seal: Path,
) -> Path:
    """Create or validate the out-of-package recovery intent."""

    run = run_dir.expanduser().resolve()
    path = journal_path_for(run)
    with _locked(path):
        if path.exists():
            value = _read(path)
            if value["run_dir"] != str(run):
                raise ValueError("finalization journal run path differs")
            return path
        now = _utc_now()
        _atomic_json(
            path,
            {
                "contract": CONTRACT_ID,
                "created_utc": now,
                "updated_utc": now,
                "run_dir": str(run),
                "index_path": str(index_path.expanduser().resolve()),
                "required_seal": str(required_seal),
                "registration": registration,
                "expected_content_sha256": None,
                "phase_order": list(PHASES),
                "phases": {phase: None for phase in PHASES},
                "primary_failure": None,
                "secondary_failures": [],
            },
        )
    return path


def advance_phase(
    journal_path: Path, phase: str, details: dict[str, Any] | None = None
) -> dict[str, Any]:
    if phase not in PHASES:
        raise ValueError(f"unknown finalization phase {phase!r}")
    with _locked(journal_path):
        value = _read(journal_path)
        index = PHASES.index(phase)
        incomplete = [name for name in PHASES[:index] if value["phases"][name] is None]
        if incomplete:
            raise ValueError(
                f"cannot complete {phase} before {', '.join(incomplete)}"
            )
        observed = value["phases"][phase]
        retained = {"completed_utc": _utc_now(), "details": details or {}}
        if observed is not None:
            if observed.get("details") != retained["details"]:
                raise ValueError(f"finalization phase {phase} differs on retry")
            return value
        value["phases"][phase] = retained
        value["updated_utc"] = retained["completed_utc"]
        _atomic_json(journal_path, value)
        return value


def set_registration_intent(
    journal_path: Path,
    *,
    registration: dict[str, str],
    expected_content_sha256: str,
) -> dict[str, Any]:
    with _locked(journal_path):
        value = _read(journal_path)
        if value["phases"]["seal"] is None:
            raise ValueError("registration intent requires a completed seal")
        existing = value.get("expected_content_sha256")
        if existing not in {None, expected_content_sha256}:
            raise ValueError("sealed package identity changed")
        value["registration"] = registration
        value["expected_content_sha256"] = expected_content_sha256
        value["updated_utc"] = _utc_now()
        _atomic_json(journal_path, value)
        return value


def record_failure(
    journal_path: Path, *, phase: str, error: BaseException
) -> dict[str, Any]:
    failure = {
        "phase": phase,
        "error_type": type(error).__name__,
        "error": str(error),
        "observed_utc": _utc_now(),
    }
    with _locked(journal_path):
        value = _read(journal_path)
        if value["primary_failure"] is None:
            value["primary_failure"] = failure
        else:
            value["secondary_failures"].append(failure)
        value["updated_utc"] = failure["observed_utc"]
        _atomic_json(journal_path, value)
        return value


def recover_registration(journal_path: Path) -> dict[str, Any]:
    """Register an unchanged sealed package, retrying idempotently."""

    value = _read(journal_path)
    for phase in PHASES[:-1]:
        if value["phases"][phase] is None:
            raise ValueError(f"finalization is not recoverable before {phase}")
    run_dir = Path(value["run_dir"])
    required = (
        run_dir / "COMPLETE",
        run_dir / "evidence_manifest.json",
        run_dir / value["required_seal"],
    )
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise ValueError("sealed package recovery files are missing: " + ", ".join(missing))
    observed_identity = package_identity(run_dir)["content_sha256"]
    if observed_identity != value.get("expected_content_sha256"):
        raise ValueError("sealed package differs from registration intent")
    metadata = value["registration"]
    record = register_package(
        index_path=Path(value["index_path"]),
        package_path=run_dir,
        source_revision=metadata["source_revision"],
        build_identity=metadata["build_identity"],
        profile_identity=metadata["profile_identity"],
        attempt_classification=metadata["attempt_classification"],
        result_or_failure_reason=metadata["result_or_failure_reason"],
        analyzer_identity=metadata["analyzer_identity"],
    )
    advance_phase(
        journal_path,
        "registration",
        {"content_sha256": record["content_sha256"]},
    )
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("journal", type=Path)
    args = parser.parse_args(argv)
    print(json.dumps(recover_registration(args.journal), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
