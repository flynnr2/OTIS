"""Detached local supervision; observations never authorize commands or restart.

The ordinary live runner remains the sole command owner. This wrapper records
transitions independently and survives loss of the invoking terminal. No API,
network, reviewer response, or model budget is required.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from .adaptive_hybrid_contract import (
    QUALIFIED_APERTURE_MILESTONES,
    UNATTENDED_MONITOR_INTERVAL_S,
    UNATTENDED_STALE_AFTER_S,
    UNATTENDED_STORAGE_RESERVE_BYTES,
)
from .adaptive_hybrid_transactions import SUPERVISOR_STATE, _atomic_json
from .capture_device import CAPTURE_STATE


def read_object(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise TypeError(f"expected object: {path}")
    return value


class Observer:
    """Read-only progress observer with explicit missing/stale evidence."""

    def __init__(self, run_dir: Path):
        self.run_dir = run_dir
        self.last_bytes = None
        self.last_progress_ns = time.monotonic_ns()

    def sample(self) -> dict:
        now = time.monotonic_ns()
        capture = read_object(self.run_dir / CAPTURE_STATE)
        owner = read_object(self.run_dir / SUPERVISOR_STATE)
        byte_count = capture.get("bytes_written")
        if type(byte_count) is int and byte_count != self.last_bytes:
            self.last_bytes = byte_count
            self.last_progress_ns = now
        updated = capture.get("updated_monotonic_ns")
        stale_ns = UNATTENDED_STALE_AFTER_S * 1_000_000_000
        fresh = type(updated) is int and 0 <= now - updated < stale_ns
        apertures = owner.get("qualified_d14_accepted_apertures")
        hold = owner.get("host_verification_hold")
        free = shutil.disk_usage(self.run_dir).free
        return {
            "capture_fresh": fresh,
            "raw_evidence_advancing": now - self.last_progress_ns < stale_ns,
            "capture_active": capture.get("capture_active"),
            "serial_open": capture.get("serial_open"),
            "qualified_checkpoint": max((n for n in QUALIFIED_APERTURE_MILESTONES
                                          if type(apertures) is int and apertures >= n), default=None),
            "hybrid_state": owner.get("latest_hybrid_state"),
            "completed_responses": owner.get("response_count"),
            "review_hold": None if hold is None else {
                key: hold.get(key) for key in ("entered_utc", "source", "error", "request_sequence", "applied_code", "dac_epoch")
            },
            "metadata_hold": owner.get("gnss_metadata_hold") is not None,
            "storage_low": free < UNATTENDED_STORAGE_RESERVE_BYTES,
            "terminal": owner.get("terminal"),
        }


def supervise(command: list[str], run_dir: Path, directory: Path) -> int:
    """Do not stop/restart the live owner for any observer or publication error."""
    observer = Observer(run_dir)
    with (directory / "owner.log").open("ab", buffering=0) as output:
        child = subprocess.Popen(command, stdin=subprocess.DEVNULL, stdout=output,
                                 stderr=subprocess.STDOUT, start_new_session=True)
    try:
        _atomic_json(directory / "started.json", {
            "monitor_pid": os.getpid(), "owner_pid": child.pid,
            "run_directory": str(run_dir), "automatic_restart": False,
        })
    except OSError as error:
        print(f"launch publication unavailable: {error}", file=sys.stderr, flush=True)
    # Sleep prevention follows the owner even if this observer is lost.
    if sys.platform == "darwin":
        try:
            subprocess.Popen(["/usr/bin/caffeinate", "-ims", "-w", str(child.pid)],
                             stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                             stderr=subprocess.DEVNULL)
        except OSError as error:
            print(f"sleep prevention unavailable: {error}", file=sys.stderr, flush=True)
    previous = None
    while True:
        code = child.poll()
        try:
            state = observer.sample()
        except (OSError, ValueError, TypeError, AttributeError) as error:
            state = {"observation_unavailable": str(error), "review_required": True}
        state["owner_exit_code"] = code
        if state != previous:
            record = {"observed_monotonic_ns": time.monotonic_ns(),
                      "command_authority": False, "reviewer_response_required_for_capture": False,
                      "state": state}
            try:
                with (directory / "transitions.jsonl").open("a") as stream:
                    stream.write(json.dumps(record, sort_keys=True) + "\n")
                    stream.flush()
                    os.fsync(stream.fileno())
                _atomic_json(directory / "status.json", record)
                previous = state
            except OSError as error:
                # Storage/notification failure cannot tear down capture.
                print(f"monitor publication unavailable: {error}", file=sys.stderr, flush=True)
        try:
            _atomic_json(directory / "heartbeat.json", {
                "observed_monotonic_ns": time.monotonic_ns(),
                "monitor_pid": os.getpid(), "owner_pid": child.pid,
                "owner_exit_code": code,
            })
        except OSError:
            pass
        if code is not None:
            return code
        time.sleep(UNATTENDED_MONITOR_INTERVAL_S)


def launch(run_args: list[str]) -> dict:
    # Reuse the production CLI argument parser and validation in the child.
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--run-dir", required=True, type=Path)
    parsed, _ = parser.parse_known_args(run_args)
    run_dir = parsed.run_dir.resolve()
    directory = run_dir.with_name(run_dir.name + ".unattended")
    if run_dir.exists():
        raise ValueError("unattended launch requires a fresh run directory")
    if "--rehearse" not in run_args and shutil.disk_usage(run_dir.parent).free < 50 * 1024**3:
        raise ValueError("seven-day entry requires at least 50 GiB free for raw and derived evidence")
    directory.mkdir(parents=True, exist_ok=False)  # One-use launch guard.
    with (directory / "monitor.log").open("ab", buffering=0) as output:
        worker = subprocess.Popen(
            [sys.executable, "-m", "host.otis_tools.unattended", "--worker", str(directory), *run_args],
            stdin=subprocess.DEVNULL, stdout=output, stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if (directory / "started.json").exists():
            return {**read_object(directory / "started.json"),
                    "monitor_directory": str(directory), "status": "launched_entry_pending"}
        if worker.poll() is not None:
            raise RuntimeError(f"unattended launcher stopped; inspect {directory}")
        time.sleep(0.05)
    raise TimeoutError(f"launch acknowledgement unavailable; do not retry; inspect {directory}")


def main() -> int:
    args = sys.argv[1:]
    if args[:1] != ["--worker"]:
        print(json.dumps(launch(args), indent=2))
        return 0
    directory = Path(args[1])
    run_args = args[2:]
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--run-dir", required=True, type=Path)
    parsed, _ = parser.parse_known_args(run_args)
    if "--rehearse" in run_args:
        run_args.remove("--rehearse")
        command = [sys.executable, "-m", "tools.rehearse_host", *run_args]
    else:
        command = [sys.executable, "-m", "host.otis_tools", "run", *run_args]
    return supervise(command,
                     parsed.run_dir.resolve(), directory)


if __name__ == "__main__":
    raise SystemExit(main())
