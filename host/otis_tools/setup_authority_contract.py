"""Retained and independently replayable initial-setup authority input."""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import Mapping

from .bounded_tight_deadband_prewrite_contract import (
    PrewriteReadiness,
    evaluate_prewrite_readiness,
)


SETUP_AUTHORITY_CONTRACT = "cx319_setup_authority_input_v1"
SETUP_AUTHORITY_PATH = Path("reports/setup_authority_input_v1.json")
SETUP_AUTHORITY_LIFETIME_S = 30


def canonical_health(
    health: Mapping[tuple[str, str], str],
) -> list[dict[str, str]]:
    return [
        {"component": component, "key": key, "value": value}
        for (component, key), value in sorted(health.items())
    ]


def health_from_canonical(
    rows: object,
) -> dict[tuple[str, str], str]:
    if not isinstance(rows, list):
        raise ValueError("setup authority health is not a list")
    health: dict[tuple[str, str], str] = {}
    for item in rows:
        if not isinstance(item, dict):
            raise ValueError("setup authority health row is not an object")
        component = item.get("component")
        key = item.get("key")
        value = item.get("value")
        if not all(isinstance(value, str) for value in (component, key, value)):
            raise ValueError("setup authority health row is not textual")
        identity = (component, key)
        if identity in health:
            raise ValueError(f"duplicate setup authority health key {identity!r}")
        health[identity] = value
    return health


def _canonical_sha256(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def write_setup_authority_input(path: Path, value: dict[str, object]) -> None:
    """Create one immutable authority record and durably publish its name."""

    path.parent.mkdir(parents=True, exist_ok=True)
    unsigned = dict(value)
    unsigned.pop("record_sha256", None)
    retained = {**unsigned, "record_sha256": _canonical_sha256(unsigned)}
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(retained, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    try:
        os.link(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


@dataclass(frozen=True)
class SetupAuthorityReplay:
    exact: bool
    errors: tuple[str, ...]
    readiness: PrewriteReadiness
    request: dict[str, object]


def replay_setup_authority_input(
    path: Path,
    *,
    expected_identity: Mapping[str, str],
    planned_live_stimulus_code: int,
) -> SetupAuthorityReplay:
    value = json.loads(path.read_text(encoding="utf-8"))
    errors: list[str] = []
    if value.get("contract") != SETUP_AUTHORITY_CONTRACT:
        errors.append("setup authority contract identity differs")
    record_hash = value.get("record_sha256")
    unsigned = dict(value)
    unsigned.pop("record_sha256", None)
    if record_hash != _canonical_sha256(unsigned):
        errors.append("setup authority record hash differs")
    health = health_from_canonical(value.get("health"))
    request = value.get("request")
    if not isinstance(request, dict):
        raise ValueError("setup authority request is not an object")
    readiness = evaluate_prewrite_readiness(
        health,
        expected_identity=dict(expected_identity),
        planned_live_stimulus_code=planned_live_stimulus_code,
        active_row_count=int(value.get("active_row_count", -1)),
        dac_row_count=int(value.get("dac_row_count", -1)),
        telemetry_drop_baseline=int(value.get("telemetry_drop_baseline", -1)),
    )
    if not readiness.ready:
        errors.append("retained health does not independently replay eligible")
    active = "cx317_active"
    expected_request: dict[str, object] = {
        "authorization_sequence": request.get("authorization_sequence"),
        "status_generation": int(
            health.get((active, "snapshot_generation_complete"), "0")
        ),
        "query_nonce": int(health.get((active, "query_nonce"), "0")),
        "expires_s": int(health.get((active, "uptime_s"), "0"))
        + SETUP_AUTHORITY_LIFETIME_S,
        "session_id": int(health.get((active, "session_id"), "0")),
        "requested_code": planned_live_stimulus_code,
        "one_shot_ordinal": 1,
        "configuration_identity": expected_identity["build_identity"].split(
            ":", 1
        )[1],
    }
    for key, expected in expected_request.items():
        if request.get(key) != expected:
            errors.append(
                f"setup authority request {key}={request.get(key)!r}, "
                f"expected {expected!r}"
            )
    return SetupAuthorityReplay(
        exact=not errors,
        errors=tuple(errors),
        readiness=readiness,
        request=request,
    )
