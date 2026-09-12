"""One-shot, read-only view of the two live owner snapshots.

This module has no watch process, command path, hold authority, or retained
state of its own. The capture worker and foreground experiment owner publish
the facts; this projection only makes them convenient to inspect.
"""
from __future__ import annotations

import argparse
import json
import os
import time
from pathlib import Path
from typing import Any

from .adaptive_hybrid_transactions import SUPERVISOR_STATE
from .capture_device import CAPTURE_STATE, _serial_owner_pids
from .run_loader import load_manifest

TOOL_ID = "adaptive_hybrid_live_view_v1"


def _read_object(path: Path) -> dict[str, Any] | None:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    if not isinstance(value, dict):
        raise ValueError(f"runtime state root is not an object: {path}")
    return value


def _pid_alive(value: object) -> bool:
    if type(value) is not int or value <= 0:
        return False
    try:
        os.kill(value, 0)
    except OSError:
        return False
    return True


def snapshot(run_dir: Path, *, now_monotonic_ns: int | None = None) -> dict[str, Any]:
    """Project owner-published facts without deriving an authority verdict."""
    run_dir = run_dir.resolve()
    manifest = load_manifest(run_dir).data
    capture = _read_object(run_dir / CAPTURE_STATE)
    supervisor = _read_object(run_dir / SUPERVISOR_STATE)
    now_ns = time.monotonic_ns() if now_monotonic_ns is None else now_monotonic_ns
    capture_pid = None if capture is None else capture.get("pid")
    updated_ns = None if capture is None else capture.get("updated_monotonic_ns")
    age_ns = (
        now_ns - updated_ns
        if type(updated_ns) is int and 0 < updated_ns <= now_ns
        else None
    )
    host = manifest.get("host")
    device = host.get("serial_device") if isinstance(host, dict) else None
    owners: list[int] | None = None
    if isinstance(device, str) and device:
        owners = sorted(_serial_owner_pids(device))
    terminal = None if supervisor is None else supervisor.get("terminal")
    hold = None if supervisor is None else supervisor.get("host_verification_hold")
    phase = (
        "terminal" if isinstance(terminal, dict)
        else "review_hold" if isinstance(hold, dict)
        else "observing"
    )
    return {
        "schema_version": 1,
        "tool": TOOL_ID,
        "run_directory": str(run_dir),
        "phase": phase,
        "monitor_command_authority": False,
        "supervisor_control_authority": (
            None if supervisor is None else supervisor.get("control_authority")
        ),
        "capture": {
            "pid": capture_pid,
            "pid_alive": _pid_alive(capture_pid),
            "heartbeat_age_ns": age_ns,
            "capture_active": None if capture is None else capture.get("capture_active"),
            "serial_open": None if capture is None else capture.get("serial_open"),
            "serial_owner_pids": owners,
            "bytes_written": None if capture is None else capture.get("bytes_written"),
            "lines_parsed": None if capture is None else capture.get("lines_parsed"),
            "commands_sent": None if capture is None else capture.get("commands_sent"),
            "emergency_abort_latched": (
                None if capture is None else capture.get("emergency_abort_latched")
            ),
        },
        "progress": None if supervisor is None else {
            "startup_census": supervisor.get("startup_census"),
            "qualified_origin_estimate_id": supervisor.get("qualified_origin_estimate_id"),
            "qualified_d14_accepted_apertures": supervisor.get("qualified_d14_accepted_apertures"),
            "qualified_acceptance_ordinal_endpoint": supervisor.get("qualified_acceptance_ordinal_endpoint"),
            "latest_hybrid_state": supervisor.get("latest_hybrid_state"),
            "response_count": supervisor.get("response_count"),
            "host_verification_hold": hold,
            "terminal": terminal,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args(argv)
    try:
        value = snapshot(args.run_dir)
    except (OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(value, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
