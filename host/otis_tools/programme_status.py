"""Fail-closed programme execution status for operational host tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATUS_PATH = REPO_ROOT / "profiles/programme_status_v1.json"
STATUS_ID = "otis_programme_status_v1"


class ProgrammeExecutionBlocked(RuntimeError):
    """Raised before side effects when a programme is not executable."""


def load_programme_status(
    path: Path = DEFAULT_STATUS_PATH,
) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("programme status root must be an object")
    if value.get("schema_version") != 1 or value.get("status_id") != STATUS_ID:
        raise ValueError("unsupported programme status contract")
    programmes = value.get("programmes")
    if not isinstance(programmes, dict) or not programmes:
        raise ValueError("programme status must declare programmes")
    for programme_id, status in programmes.items():
        if not isinstance(programme_id, str) or not programme_id:
            raise ValueError("programme id must be a non-empty string")
        if not isinstance(status, dict):
            raise ValueError(f"programme {programme_id} status must be an object")
        if not isinstance(status.get("state"), str) or not status["state"]:
            raise ValueError(f"programme {programme_id} must declare state")
        if not isinstance(status.get("execution_allowed"), bool):
            raise ValueError(
                f"programme {programme_id} must declare execution_allowed"
            )
        if not isinstance(status.get("effective_date"), str):
            raise ValueError(
                f"programme {programme_id} must declare effective_date"
            )
    active = value.get("active_programme")
    if active is not None and active not in programmes:
        raise ValueError("active_programme must be null or name a declared programme")
    if active is not None and not programmes[active]["execution_allowed"]:
        raise ValueError("active_programme must permit execution")
    return value


def require_programme_execution_allowed(
    programme_id: str,
    *,
    path: Path = DEFAULT_STATUS_PATH,
) -> dict[str, Any]:
    status_document = load_programme_status(path)
    status = status_document["programmes"].get(programme_id)
    if not isinstance(status, dict):
        raise ProgrammeExecutionBlocked(
            f"programme {programme_id!r} has no execution status"
        )
    if (
        status_document["active_programme"] != programme_id
        or not status["execution_allowed"]
    ):
        state = status["state"]
        prerequisite = status.get("resume_prerequisite", "operator_decision")
        raise ProgrammeExecutionBlocked(
            f"programme {programme_id} execution is blocked: state={state}; "
            f"resume_prerequisite={prerequisite}"
        )
    return status
