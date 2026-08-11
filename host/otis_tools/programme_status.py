"""Fail-closed programme execution status for operational host tools."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_STATUS_PATH = REPO_ROOT / "profiles/programme_status_v2.json"
STATUS_ID = "otis_programme_status_v2"
SCHEMA_VERSION = 2
OFFLINE_PREPARATION = "offline_preparation"
OPERATIONAL_EXECUTION = "operational_execution"
CX319_G1_NO_WRITE_BENCH_REHEARSAL = "g1_no_write_bench_rehearsal"
CX319_G2_LIVE_LEG = "g2_live_leg"


class ProgrammeExecutionBlocked(RuntimeError):
    """Raised before side effects when a programme is not executable."""


def load_programme_status(
    path: Path = DEFAULT_STATUS_PATH,
) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("programme status root must be an object")
    if (
        value.get("schema_version") != SCHEMA_VERSION
        or value.get("status_id") != STATUS_ID
    ):
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
        allowed_operations = status.get("allowed_operations")
        if (
            not isinstance(allowed_operations, list)
            or any(
                not isinstance(operation, str) or not operation
                for operation in allowed_operations
            )
            or len(set(allowed_operations)) != len(allowed_operations)
        ):
            raise ValueError(
                f"programme {programme_id} must declare unique allowed_operations"
            )
        if not isinstance(status.get("effective_date"), str):
            raise ValueError(
                f"programme {programme_id} must declare effective_date"
            )
    active = value.get("active_programme")
    if active is not None and active not in programmes:
        raise ValueError("active_programme must be null or name a declared programme")
    if active is not None and not programmes[active]["allowed_operations"]:
        raise ValueError("active_programme must permit at least one operation")
    return value


def require_programme_operation_allowed(
    programme_id: str,
    operation: str,
    *,
    path: Path = DEFAULT_STATUS_PATH,
) -> dict[str, Any]:
    if not isinstance(operation, str) or not operation:
        raise ValueError("programme operation must be a non-empty string")
    status_document = load_programme_status(path)
    status = status_document["programmes"].get(programme_id)
    if not isinstance(status, dict):
        raise ProgrammeExecutionBlocked(
            f"programme {programme_id!r} has no execution status"
        )
    if (
        status_document["active_programme"] != programme_id
        or operation not in status["allowed_operations"]
    ):
        state = status["state"]
        prerequisite = status.get(
            "next_gate",
            status.get("resume_prerequisite", "operator_decision"),
        )
        raise ProgrammeExecutionBlocked(
            f"programme {programme_id} operation {operation!r} is blocked: "
            f"state={state}; "
            f"resume_prerequisite={prerequisite}"
        )
    return status


def require_programme_execution_allowed(
    programme_id: str,
    *,
    path: Path = DEFAULT_STATUS_PATH,
) -> dict[str, Any]:
    """Compatibility guard for operational tools with physical side effects.

    New tools should request their exact operation explicitly. Historical
    tools retain this wrapper and therefore require the deliberately absent
    broad operational-execution authority.
    """

    return require_programme_operation_allowed(
        programme_id,
        OPERATIONAL_EXECUTION,
        path=path,
    )
