"""Shared, read-only capture closure and campaign finalization checks."""

from __future__ import annotations

from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .active_transactions import _read_csv
from .capture_device import SEGMENT_CLOSURE, SEGMENT_PROTOCOL_ID


SUPERVISOR_STATE = Path("reports/cx317_active_supervisor_state.json")
SUPERVISOR_EVENTS = Path("reports/cx317_active_supervisor_events.jsonl")
CAPTURE_STATE = Path("reports/capture_device_state.json")
HOST_MARKER_PREFIX = "# OTIS_HOST "


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _host_markers(path: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith(HOST_MARKER_PREFIX):
                result.append(json.loads(line[len(HOST_MARKER_PREFIX) :]))
    return result


def _parse_utc(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def _capture_duration(markers: list[dict[str, Any]]) -> float:
    starts = [item for item in markers if item.get("event") == "capture_started"]
    stops = [item for item in markers if item.get("event") == "capture_stopped"]
    if len(starts) != 1 or len(stops) != 1:
        raise ValueError("capture requires exactly one start and stop marker")
    return _parse_utc(str(stops[0]["utc"])) - _parse_utc(str(starts[0]["utc"]))


def _capture_closure(
    run_dir: Path,
    capture_state: dict[str, Any],
    markers: list[dict[str, Any]],
    *,
    allowed_emergency_aborts: int = 0,
    allowed_reconnects: int = 0,
) -> dict[str, Any]:
    """Validate same-owner rotation or one bounded physical serial close."""

    starts = [item for item in markers if item.get("event") == "capture_started"]
    stops = [item for item in markers if item.get("event") == "capture_stopped"]
    if len(starts) != 1 or len(stops) != 1:
        return {"ok": False, "mode": "invalid_marker_cardinality"}
    start, stop = starts[0], stops[0]
    counters_clean = (
        capture_state.get("capture_active") is False
        and int(capture_state.get("reconnect_count", -1)) == allowed_reconnects
        and int(capture_state.get("parser_errors", -1)) == 0
        and int(capture_state.get("malformed_utf8", -1)) == 0
        and int(capture_state.get("commands_rejected", -1)) == 0
        and int(capture_state.get("emergency_aborts_sent", -1))
        == allowed_emergency_aborts
    )
    certificate_path = run_dir / SEGMENT_CLOSURE
    try:
        certificate = json.loads(certificate_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        certificate = {}
    owner_check = certificate.get("serial_owner_check")
    if not isinstance(owner_check, dict):
        owner_check = {}
    manifest_sha256 = _sha256_file(run_dir / "run_manifest.json")
    same_owner = (
        isinstance(start.get("owner_pid"), int)
        and start.get("owner_pid") == stop.get("owner_pid")
        and start.get("owner_pid") == capture_state.get("pid")
        and start.get("transport_generation")
        == stop.get("transport_generation")
        == capture_state.get("transport_generation")
    )
    logical_rotation = (
        capture_state.get("logical_segment_closed") is True
        and capture_state.get("serial_open") is True
        and capture_state.get("physical_serial_open") is True
        and stop.get("logical_rotation") is True
        and isinstance(stop.get("next_run"), str)
        and bool(stop.get("next_run"))
        and same_owner
        and certificate.get("closure_mode") == "same_owner_logical_rotation"
        and owner_check.get("performed") is True
        and owner_check.get("owner_pids") == [capture_state.get("pid")]
    )
    physical_close = (
        capture_state.get("serial_open") is False
        and capture_state.get("physical_serial_open", False) is False
        and stop.get("logical_rotation") in {None, False}
        and certificate.get("closure_mode") == "physical_serial_close"
    )
    certificate_exact = (
        certificate.get("schema_version") == 1
        and certificate.get("protocol") == SEGMENT_PROTOCOL_ID
        and certificate.get("run") == str(run_dir)
        and certificate.get("run_manifest_sha256") == manifest_sha256
        and certificate.get("owner_pid") == capture_state.get("pid")
        and certificate.get("transport_generation")
        == capture_state.get("transport_generation")
        and certificate.get("logical_segment_closed") is True
        and certificate.get("physical_serial_open")
        == capture_state.get("physical_serial_open", False)
        and certificate.get("serial_reopened") is False
        and certificate.get("next_run") == stop.get("next_run")
        and certificate.get("counters", {}).get("reconnect_count")
        == capture_state.get("reconnect_count")
        and certificate.get("counters", {}).get("parser_errors")
        == capture_state.get("parser_errors")
        and certificate.get("counters", {}).get("malformed_utf8")
        == capture_state.get("malformed_utf8")
        and certificate.get("counters", {}).get("commands_rejected")
        == capture_state.get("commands_rejected")
        and certificate.get("counters", {}).get("emergency_aborts_sent")
        == capture_state.get("emergency_aborts_sent")
    )
    mode = (
        "same_owner_logical_rotation"
        if logical_rotation
        else "physical_serial_close"
        if physical_close
        else "invalid"
    )
    return {
        "ok": counters_clean and same_owner and certificate_exact
        and (logical_rotation or physical_close),
        "mode": mode,
        "owner_pid": stop.get("owner_pid"),
        "transport_generation": stop.get("transport_generation"),
        "next_run": stop.get("next_run"),
        "serial_reopened": False if logical_rotation else None,
        "certificate_path": str(SEGMENT_CLOSURE),
        "certificate_sha256": (
            _sha256_file(certificate_path) if certificate_path.is_file() else None
        ),
    }


def _contract_path(manifest: Any, contract: str) -> Path:
    matches = [
        manifest.root / str(item["path"])
        for item in manifest.files
        if item.get("contract") == contract
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one {contract} artifact, got {len(matches)}")
    return matches[0]


def _authority_false(path: Path) -> bool:
    rows = _read_csv(path)
    if not rows:
        return False
    return all(
        row.get(field) == "false"
        for row in rows
        for field in ("actionable", "actuation_authorized", "authorization_consumed")
        if field in row
    )
