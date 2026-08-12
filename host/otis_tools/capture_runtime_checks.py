"""Current serial-ownership, capture-health, and obstruction checks."""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import time
from typing import Any, Callable

from .serial_commands import send_command_to_fifo, send_timestamped_command_to_fifo


HOST_MARKER_PREFIX = "# OTIS_HOST "
TOOL_ID = "capture_runtime_checks_v1"


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _wait_until(
    predicate: Callable[[], bool], timeout_s: float, description: str
) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.05)
    raise RuntimeError(f"timed out waiting for {description}")


def _markers(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    result = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith(HOST_MARKER_PREFIX):
                result.append(json.loads(line[len(HOST_MARKER_PREFIX) :]))
    return result


def _health_has(path: Path, component: str, key: str, value: str) -> bool:
    if not path.exists():
        return False
    with path.open("r", newline="", encoding="utf-8") as handle:
        return any(
            row.get("component") == component
            and row.get("status_key") == key
            and row.get("status_value") == value
            for row in csv.DictReader(handle)
        )


def _serial_owner_pids(device: str) -> set[int]:
    result = subprocess.run(
        ["lsof", "-t", device], text=True, capture_output=True, check=False
    )
    if result.returncode not in {0, 1}:
        raise ValueError(f"cannot inspect serial owners: {result.stderr.strip()}")
    return {
        int(line) for line in result.stdout.splitlines() if line.strip().isdigit()
    }


def _capture_state_ready(run_dir: Path, pid: int) -> bool:
    path = run_dir / "reports/capture_device_state.json"
    try:
        state = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return (
        state.get("pid") == pid
        and state.get("capture_active") is True
        and state.get("serial_open") is True
    )


def _inject_transport_fault(
    *,
    capture_pid: int,
    device: str,
    run_dir: Path,
    normal_fifo: Path,
    emergency_fifo: Path,
) -> dict[str, Any]:
    owner_pids = _serial_owner_pids(device)
    if owner_pids != {capture_pid}:
        raise ValueError(f"capture is not sole serial owner: {sorted(owner_pids)}")
    started = _utc_now()
    stopped = False
    queued = 0
    saturated = False
    resumed_owner_pids: set[int] = set()
    try:
        os.kill(capture_pid, signal.SIGSTOP)
        stopped = True
        for _ in range(100_000):
            try:
                send_timestamped_command_to_fifo(normal_fifo, "CONFIG?")
                queued += 1
            except BlockingIOError:
                saturated = True
                break
        if not saturated:
            raise RuntimeError("normal command FIFO did not saturate")
        send_command_to_fifo(emergency_fifo, "ACTIVE ABORT")
        os.kill(capture_pid, signal.SIGCONT)
        stopped = False
        raw_path = run_dir / "raw/serial.log"
        _wait_until(
            lambda: any(
                row.get("event") == "emergency_abort_sent"
                for row in _markers(raw_path)
            ),
            10.0,
            "priority abort transmission",
        )
        _wait_until(
            lambda: _serial_owner_pids(device) == {capture_pid},
            5.0,
            "sole serial ownership after capture resume",
        )
        resumed_owner_pids = _serial_owner_pids(device)
    finally:
        if stopped:
            os.kill(capture_pid, signal.SIGCONT)
    return {
        "schema_version": 1,
        "tool": TOOL_ID,
        "status": "pass",
        "started_utc": started,
        "completed_utc": _utc_now(),
        "capture_pid": capture_pid,
        "serial_device": device,
        "serial_owner_pids": sorted(owner_pids),
        "serial_owner_pids_after_resume": sorted(resumed_owner_pids),
        "sole_serial_owner_verified": True,
        "sole_serial_owner_verified_after_resume": resumed_owner_pids == {capture_pid},
        "owner_pid_unchanged_across_obstruction": owner_pids == resumed_owner_pids == {capture_pid},
        "normal_fifo_saturated": saturated,
        "timestamped_config_queries_queued": queued,
        "priority_abort_enqueued_while_capture_stopped": True,
        "priority_abort_observed_in_capture": True,
        "capture_resumed": True,
    }
