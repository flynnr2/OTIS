"""Bounded serial-owner handoff for evidence captures.

The Stage 4 firmware deliberately treats loss of its non-droppable raw
observation queue as fail-static.  This tool closes one verified capture and
opens the next prepared run without leaving an unbounded analysis gap between
serial owners.  It never sends a firmware, DAC, controller, or GPS command.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
from typing import Any

from .run_loader import CAPTURE_IN_PROGRESS_FLAG, load_manifest


TOOL_ID = "cx318_capture_handoff_v1"
STATE_PATH = Path("reports/capture_device_state.json")
REPORT_PATH = Path("reports/capture_handoff_v1.json")


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace(
        "+00:00", "Z"
    )


def _read_state(run_dir: Path) -> dict[str, Any]:
    value = json.loads((run_dir / STATE_PATH).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"capture state is not an object: {run_dir / STATE_PATH}")
    return value


def _serial_device(run_dir: Path) -> str:
    manifest = load_manifest(run_dir)
    device = manifest.data.get("host", {}).get("serial_device")
    if not isinstance(device, str) or not device.startswith("/dev/cu.usbmodem"):
        raise ValueError(f"run does not bind an exact USB serial device: {run_dir}")
    return device


def _owner_pids(device: str) -> set[int]:
    result = subprocess.run(
        ["lsof", "-t", device], text=True, capture_output=True, check=False,
    )
    if result.returncode not in {0, 1}:
        raise RuntimeError(f"lsof failed for {device}: {result.stderr.strip()}")
    return {int(line) for line in result.stdout.splitlines() if line.strip()}


def _process_command(pid: int) -> str:
    result = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="],
        text=True, capture_output=True, check=False,
    )
    return result.stdout.strip() if result.returncode == 0 else ""


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    return True


def _signal_interrupt(pid: int) -> None:
    os.kill(pid, signal.SIGINT)


def _spawn(arguments: list[str]) -> int:
    process = subprocess.Popen(
        arguments,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    return process.pid


def _write_report(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"handoff report already exists: {path}")
    temporary = path.with_suffix(path.suffix + f".tmp.{os.getpid()}")
    with temporary.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def perform_handoff(
    *, from_run: Path, to_run: Path, duration_s: float,
    command_fifo: Path | None = None, emergency_command_fifo: Path | None = None,
    maximum_gap_s: float = 5.0, status_interval_s: float = 5.0,
) -> dict[str, Any]:
    from_run = from_run.resolve()
    to_run = to_run.resolve()
    if from_run == to_run:
        raise ValueError("handoff source and target runs must differ")
    if duration_s <= 0 or maximum_gap_s <= 0 or status_interval_s <= 0:
        raise ValueError("handoff durations and limits must be positive")
    device = _serial_device(from_run)
    if _serial_device(to_run) != device:
        raise ValueError("handoff runs bind different serial devices")
    source = _read_state(from_run)
    source_pid = source.get("pid")
    if (
        not isinstance(source_pid, int)
        or source.get("capture_active") is not True
        or source.get("serial_open") is not True
        or source.get("parser_errors") != 0
        or source.get("malformed_utf8") != 0
    ):
        raise ValueError("source capture is not a clean active serial owner")
    if _owner_pids(device) != {source_pid}:
        raise ValueError("source capture is not the sole serial owner")
    command = _process_command(source_pid)
    if (
        "host.otis_tools.capture_device" not in command
        or from_run.name not in command
    ):
        raise ValueError("source PID is not the exact declared capture process")
    if (to_run / CAPTURE_IN_PROGRESS_FLAG).exists() or (to_run / STATE_PATH).exists():
        raise ValueError("target capture run has already been started")

    arguments = [
        sys.executable, "-m", "host.otis_tools.capture_device",
        "--device", device,
        "--baud", "115200",
        "--run-dir", str(to_run),
        "--status-interval", str(status_interval_s),
        "--duration-s", str(duration_s),
    ]
    if command_fifo is not None:
        arguments += [
            "--command-fifo", str(command_fifo.resolve()),
            "--write-timeout-s", "1",
            "--normal-command-max-age-s", "2",
        ]
    if emergency_command_fifo is not None:
        arguments += [
            "--emergency-command-fifo", str(emergency_command_fifo.resolve()),
        ]

    interrupted_utc = _utc_now()
    started = time.monotonic()
    _signal_interrupt(source_pid)
    while time.monotonic() - started < maximum_gap_s:
        if (
            not _process_alive(source_pid)
            and not (from_run / CAPTURE_IN_PROGRESS_FLAG).exists()
            and not _owner_pids(device)
        ):
            break
        time.sleep(0.02)
    else:
        raise TimeoutError("source capture did not release serial inside handoff bound")

    target_pid = _spawn(arguments)
    while time.monotonic() - started < maximum_gap_s:
        state_path = to_run / STATE_PATH
        if state_path.is_file():
            target = _read_state(to_run)
            if (
                target.get("pid") == target_pid
                and target.get("capture_active") is True
                and target.get("serial_open") is True
                and target.get("reconnect_count") == 0
                and target.get("parser_errors") == 0
                and _owner_pids(device) == {target_pid}
            ):
                elapsed = time.monotonic() - started
                report = {
                    "schema_version": 1,
                    "tool": TOOL_ID,
                    "status": "passed",
                    "interrupted_utc": interrupted_utc,
                    "target_opened_utc": _utc_now(),
                    "elapsed_s": elapsed,
                    "maximum_gap_s": maximum_gap_s,
                    "serial_device": device,
                    "source_run": str(from_run),
                    "source_pid": source_pid,
                    "target_run": str(to_run),
                    "target_pid": target_pid,
                    "commands_sent": 0,
                }
                _write_report(to_run / REPORT_PATH, report)
                return report
        if not _process_alive(target_pid):
            raise RuntimeError("target capture exited before opening serial")
        time.sleep(0.02)
    if _process_alive(target_pid):
        _signal_interrupt(target_pid)
    raise TimeoutError("target capture did not open serial inside handoff bound")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from-run", type=Path, required=True)
    parser.add_argument("--to-run", type=Path, required=True)
    parser.add_argument("--duration-s", type=float, required=True)
    parser.add_argument("--command-fifo", type=Path)
    parser.add_argument("--emergency-command-fifo", type=Path)
    parser.add_argument("--maximum-gap-s", type=float, default=5.0)
    parser.add_argument("--status-interval-s", type=float, default=5.0)
    args = parser.parse_args(argv)
    report = perform_handoff(
        from_run=args.from_run,
        to_run=args.to_run,
        duration_s=args.duration_s,
        command_fifo=args.command_fifo,
        emergency_command_fifo=args.emergency_command_fifo,
        maximum_gap_s=args.maximum_gap_s,
        status_interval_s=args.status_interval_s,
    )
    print(json.dumps(report, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
