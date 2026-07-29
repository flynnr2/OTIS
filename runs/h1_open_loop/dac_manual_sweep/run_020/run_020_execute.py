#!/usr/bin/env python3
"""Run the single focused Run 020 crossing profile and always restore 0x8000."""

from __future__ import annotations

import argparse
from pathlib import Path
import sys
import time

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from host.otis_tools.serial_commands import send_command_to_fifo
from run_020_preflight import verify_preflight


def complete_count(raw_log: Path) -> int:
    count = 0
    with raw_log.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("DAC,") and ",complete," in line:
                count += 1
    return count


def send(fifo: Path, command: str) -> None:
    print(command, flush=True)
    send_command_to_fifo(fifo, command)


def run(fifo: Path, raw_log: Path, timeout_s: float) -> None:
    verify_preflight(fifo, raw_log)
    before = complete_count(raw_log)
    started = False
    try:
        send(fifo, "SWEEP START")
        started = True
        send(fifo, "SWEEP?")
        deadline = time.monotonic() + timeout_s
        while time.monotonic() < deadline:
            current = complete_count(raw_log)
            if current > before:
                print(f"RUN 020 PROFILE COMPLETE (completion row {current})", flush=True)
                return
            time.sleep(10.0)
        raise TimeoutError(f"no sweep completion within {timeout_s:.0f} seconds")
    finally:
        if started:
            try:
                send(fifo, "SWEEP STOP")
            except (OSError, SystemExit) as exc:
                print(f"WARNING: SWEEP STOP failed: {exc}", flush=True)
        try:
            send(fifo, "DAC SET 0x8000")
            send(fifo, "DAC?")
        except (OSError, SystemExit) as exc:
            print(f"WARNING: automatic 0x8000 restoration failed: {exc}", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fifo", required=True, type=Path)
    parser.add_argument("--raw-log", required=True, type=Path)
    parser.add_argument("--timeout-s", type=float, default=22_200.0)
    args = parser.parse_args()
    try:
        run(args.fifo, args.raw_log, args.timeout_s)
    except (OSError, RuntimeError, TimeoutError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
