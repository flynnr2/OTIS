"""Predetermined, non-actuating Stage 6 dual-core live-proof scheduler."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import argparse
import csv
import json
import os
import select
import time

from .serial_commands import send_command_to_fifo


EXPECTED_CODE = 0xA82A


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class Schedule:
    service_load_start_s: float = 2500.0
    service_load_count: int = 60
    service_load_period_s: float = 1.0
    invalidation_s: float = 2700.0
    recovery_s: float = 2720.0
    final_status_s: float = 4650.0


class AuditLog:
    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self._handle = path.open("a", encoding="utf-8")

    def write(self, event: str, **fields: object) -> None:
        row = {"utc": _utc_now(), "event": event, **fields}
        self._handle.write(json.dumps(row, sort_keys=True) + "\n")
        self._handle.flush()
        os.fsync(self._handle.fileno())

    def close(self) -> None:
        self._handle.close()


def _read_dac_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists() or path.stat().st_size == 0:
        return []
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _exact_state_ack(path: Path) -> bool:
    rows = _read_dac_rows(path)
    if len(rows) != 1:
        return False
    row = rows[0]
    return (
        row["event"] == "manual_apply"
        and int(row["dac_code_requested"]) == EXPECTED_CODE
        and int(row["dac_code_applied"]) == EXPECTED_CODE
        and int(row["dac_code_clamped"]) == 0
        and int(row["flags"]) == 0
    )


def _open_abort_fifo(path: Path) -> int:
    if path.exists() and not path.is_fifo():
        raise ValueError(f"abort path exists and is not a FIFO: {path}")
    if not path.exists():
        os.mkfifo(path, 0o600)
    return os.open(path, os.O_RDONLY | os.O_NONBLOCK)


def _abort_requested(fd: int) -> bool:
    readable, _, _ = select.select([fd], [], [], 0)
    if not readable:
        return False
    payload = os.read(fd, 4096).decode("ascii", errors="replace")
    return any(line.strip().upper() == "ABORT" for line in payload.splitlines())


def _wait_until(deadline: float, abort_fd: int) -> bool:
    while time.monotonic() < deadline:
        if _abort_requested(abort_fd):
            return False
        time.sleep(min(1.0, max(0.0, deadline - time.monotonic())))
    return not _abort_requested(abort_fd)


def run(command_fifo: Path, run_dir: Path, abort_fifo: Path, schedule: Schedule) -> int:
    audit = AuditLog(run_dir / "supervisor" / "stage6_schedule.jsonl")
    abort_fd = _open_abort_fifo(abort_fifo)
    try:
        audit.write("supervisor_started", authority="non_actuating_predetermined_only")
        send_command_to_fifo(command_fifo, "CONFIG?")
        audit.write("command_scheduled", command="CONFIG?", purpose="exact_live_identity")
        time.sleep(3.0)
        if _abort_requested(abort_fd):
            audit.write("aborted_fail_static", commands_after_abort=0)
            return 2
        send_command_to_fifo(command_fifo, f"DAC SET 0x{EXPECTED_CODE:04X}")
        audit.write(
            "command_scheduled", command=f"DAC SET 0x{EXPECTED_CODE:04X}",
            purpose="idempotent_volatile_state_establishment_not_feedback",
        )
        ack_deadline = time.monotonic() + 15.0
        dac_path = run_dir / "csv" / "dac_steps.csv"
        while not _exact_state_ack(dac_path):
            if _abort_requested(abort_fd) or time.monotonic() >= ack_deadline:
                audit.write("state_ack_failed_fail_static", dac_rows=len(_read_dac_rows(dac_path)))
                return 3
            time.sleep(0.25)
        epoch = time.monotonic()
        audit.write("state_ack_exact", code=EXPECTED_CODE, schedule_epoch_monotonic=epoch)

        if not _wait_until(epoch + schedule.service_load_start_s, abort_fd):
            audit.write("aborted_fail_static", commands_after_abort=0)
            return 2
        for index in range(schedule.service_load_count):
            if _abort_requested(abort_fd):
                audit.write("aborted_fail_static", commands_after_abort=0)
                return 2
            send_command_to_fifo(command_fifo, "CONFIG?")
            audit.write("command_scheduled", command="CONFIG?", service_index=index + 1)
            if index + 1 < schedule.service_load_count:
                if not _wait_until(
                    epoch + schedule.service_load_start_s
                    + (index + 1) * schedule.service_load_period_s,
                    abort_fd,
                ):
                    audit.write("aborted_fail_static", commands_after_abort=0)
                    return 2

        if not _wait_until(epoch + schedule.invalidation_s, abort_fd):
            audit.write("aborted_fail_static", commands_after_abort=0)
            return 2
        send_command_to_fifo(command_fifo, "DUALCORE INVALIDATE_GNSS")
        audit.write("command_scheduled", command="DUALCORE INVALIDATE_GNSS")

        if not _wait_until(epoch + schedule.recovery_s, abort_fd):
            audit.write("aborted_fail_static", commands_after_abort=0)
            return 2
        send_command_to_fifo(command_fifo, "DUALCORE RECOVER")
        audit.write("command_scheduled", command="DUALCORE RECOVER")

        if not _wait_until(epoch + schedule.final_status_s, abort_fd):
            audit.write("aborted_fail_static", commands_after_abort=0)
            return 2
        send_command_to_fifo(command_fifo, "DUALCORE?")
        audit.write("command_scheduled", command="DUALCORE?", purpose="terminal_queue_and_authority_status")
        audit.write("schedule_complete", feedback_dac_commands=0, total_dac_commands=1)
        return 0
    finally:
        os.close(abort_fd)
        audit.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--command-fifo", type=Path, required=True)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--abort-fifo", type=Path, required=True)
    args = parser.parse_args(argv)
    return run(args.command_fifo, args.run_dir, args.abort_fifo, Schedule())


if __name__ == "__main__":
    raise SystemExit(main())
