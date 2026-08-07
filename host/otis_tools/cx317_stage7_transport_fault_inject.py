"""Inject the exact Stage 7 host-backpressure fault without DAC authority.

The capture process remains the sole serial owner.  This tool stops only that
validated process, fills the normal command FIFO with timestamped CONFIG?
queries, starts the exact Stage 7 rehearsal supervisor without manual-start or
arm permission, and requires its saturated-normal-path fault to enqueue
ACTIVE ABORT on the distinct priority FIFO.  Capture is then resumed and must
send the priority abort before it can process any stale normal command.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import argparse
import json
import os
import signal
import stat
import subprocess
import sys
import tempfile
import time

from .serial_commands import send_timestamped_command_to_fifo


TOOL_VERSION = "cx317_stage7_transport_fault_inject_v1"


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _atomic_json(path: Path, payload: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(payload, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


def _require_fifo(path: Path) -> None:
    if not path.exists() or not stat.S_ISFIFO(path.stat().st_mode):
        raise ValueError(f"required FIFO is not live: {path}")


def _capture_command(pid: int) -> str:
    completed = subprocess.run(
        ["ps", "-p", str(pid), "-o", "command="],
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _wait_for_text(path: Path, text: str, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if path.exists() and text in path.read_text(
            encoding="utf-8", errors="replace"
        ):
            return True
        time.sleep(0.05)
    return False


def inject(
    *,
    capture_pid: int,
    run_dir: Path,
    command_fifo: Path,
    emergency_command_fifo: Path,
    abort_fifo: Path,
    expected_build_identity: str,
    result_path: Path,
    timeout_s: float,
) -> Path:
    if timeout_s <= 0:
        raise ValueError("timeout_s must be positive")
    run_dir = run_dir.resolve()
    fifo_paths = {
        command_fifo.resolve(),
        emergency_command_fifo.resolve(),
        abort_fifo.resolve(),
    }
    if len(fifo_paths) != 3:
        raise ValueError("all three FIFO paths must be distinct")
    if not (run_dir / "capture_in_progress.flag").is_file():
        raise ValueError("capture is not marked in progress")
    for path in fifo_paths:
        _require_fifo(path)

    command = _capture_command(capture_pid)
    if (
        "host.otis_tools.capture_device" not in command
        or str(run_dir) not in command
        or str(command_fifo) not in command
        or str(emergency_command_fifo) not in command
    ):
        raise ValueError(
            "capture PID command does not match the exact run and both FIFOs"
        )

    started_utc = _utc_now()
    stopped = False
    supervisor_exit: int | None = None
    queued = 0
    saturated = False
    events_path = run_dir / "reports/cx317_active_supervisor_events.jsonl"
    raw_path = run_dir / "raw/serial.log"
    supervisor_log = run_dir / "reports/transport_fault_supervisor.log"
    try:
        os.kill(capture_pid, signal.SIGSTOP)
        stopped = True
        for _ in range(100_000):
            try:
                send_timestamped_command_to_fifo(command_fifo, "CONFIG?")
                queued += 1
            except BlockingIOError:
                saturated = True
                break
        if not saturated:
            raise RuntimeError("normal command FIFO did not saturate")

        supervisor_args = [
            sys.executable,
            "-m",
            "host.otis_tools.cx317_stage7_supervisor",
            "--part",
            "rehearsal",
            "--start-code",
            "0xA800",
            "--run-dir",
            str(run_dir),
            "--command-fifo",
            str(command_fifo),
            "--emergency-command-fifo",
            str(emergency_command_fifo),
            "--abort-fifo",
            str(abort_fifo),
            "--expected-build-identity",
            expected_build_identity,
            "--duration-s",
            str(timeout_s),
        ]
        supervisor_log.parent.mkdir(parents=True, exist_ok=True)
        with supervisor_log.open("a", encoding="utf-8") as log_handle:
            supervisor = subprocess.Popen(
                supervisor_args,
                cwd=Path(__file__).resolve().parents[2],
                stdout=log_handle,
                stderr=log_handle,
                text=True,
            )
            try:
                supervisor_exit = supervisor.wait(timeout=timeout_s)
            except subprocess.TimeoutExpired:
                supervisor.terminate()
                supervisor.wait(timeout=5)
                raise RuntimeError("fault-injection supervisor did not exit")
        if supervisor_exit != 2:
            raise RuntimeError(
                "fault-injection supervisor exit was not the expected 2: "
                f"{supervisor_exit}"
            )
        if not _wait_for_text(
            events_path, "emergency_device_abort_submitted", timeout_s
        ):
            raise RuntimeError("supervisor did not submit priority abort")

        os.kill(capture_pid, signal.SIGCONT)
        stopped = False
        if not _wait_for_text(raw_path, "emergency_abort_sent", timeout_s):
            raise RuntimeError("capture did not send the priority abort")
        os.kill(capture_pid, 0)
    finally:
        if stopped:
            os.kill(capture_pid, signal.SIGCONT)

    result = {
        "schema_version": 1,
        "tool": TOOL_VERSION,
        "status": "pass",
        "started_at_utc": started_utc,
        "completed_at_utc": _utc_now(),
        "capture_pid": capture_pid,
        "capture_command": command,
        "run_dir": str(run_dir),
        "normal_command_fifo": str(command_fifo),
        "emergency_command_fifo": str(emergency_command_fifo),
        "independent_abort_fifo": str(abort_fifo),
        "normal_fifo_saturated": saturated,
        "timestamped_config_queries_queued": queued,
        "supervisor_exit": supervisor_exit,
        "supervisor_had_manual_start_authority": False,
        "supervisor_had_arm_authority": False,
        "priority_abort_observed_in_capture": True,
        "capture_resumed": True,
    }
    _atomic_json(result_path, result)
    return result_path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture-pid", type=int, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--command-fifo", type=Path, required=True)
    parser.add_argument("--emergency-command-fifo", type=Path, required=True)
    parser.add_argument("--abort-fifo", type=Path, required=True)
    parser.add_argument("--expected-build-identity", required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--timeout-s", type=float, default=20.0)
    args = parser.parse_args(argv)
    try:
        output = inject(
            capture_pid=args.capture_pid,
            run_dir=args.run_dir,
            command_fifo=args.command_fifo,
            emergency_command_fifo=args.emergency_command_fifo,
            abort_fifo=args.abort_fifo,
            expected_build_identity=args.expected_build_identity,
            result_path=args.result,
            timeout_s=args.timeout_s,
        )
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        parser.error(str(exc))
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
