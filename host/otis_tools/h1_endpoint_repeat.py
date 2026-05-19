from __future__ import annotations

from pathlib import Path
import argparse
import time

from .serial_commands import send_command_to_fifo


DEFAULT_PROFILE = "SLOPE_CENTER_EDGE_300S"
DEFAULT_DWELL_S = 900.0
DEFAULT_STEPS_PER_PASS = 5
DEFAULT_GUARD_S = 90.0
DEFAULT_COMPLETE_TIMEOUT_S = 7200.0


def _complete_count(raw_log: Path) -> int:
    if not raw_log.exists():
        return 0
    count = 0
    with raw_log.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith("DAC,") and ",complete," in line:
                count += 1
    return count


def _wait_for_complete(raw_log: Path, previous_count: int, timeout_s: float, dry_run: bool) -> int:
    if dry_run:
        return previous_count + 1
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        count = _complete_count(raw_log)
        if count > previous_count:
            print(f"# observed DAC complete row {count}", flush=True)
            return count
        time.sleep(10.0)
    raise TimeoutError(f"timed out waiting for next DAC complete row in {raw_log}")


def _send(fifo: Path, command: str, dry_run: bool) -> None:
    print(command, flush=True)
    if not dry_run:
        send_command_to_fifo(fifo, command)


def run_endpoint_repeat(
    fifo: Path,
    *,
    profile: str,
    passes: int,
    pass_seconds: float,
    guard_seconds: float,
    raw_log: Path | None,
    complete_timeout_s: float,
    dry_run: bool,
) -> None:
    if passes < 1:
        raise ValueError("passes must be at least 1")
    if pass_seconds <= 0:
        raise ValueError("pass_seconds must be positive")
    if guard_seconds < 0:
        raise ValueError("guard_seconds must be non-negative")

    complete_count = _complete_count(raw_log) if raw_log is not None else 0

    _send(fifo, "DAC MID", dry_run)
    _send(fifo, "FC0?", dry_run)
    _send(fifo, "SWEEP?", dry_run)

    for index in range(1, passes + 1):
        print(f"# pass {index}/{passes}", flush=True)
        _send(fifo, f"SWEEP LOAD {profile}", dry_run)
        _send(fifo, "SWEEP START", dry_run)
        _send(fifo, "SWEEP?", dry_run)
        if raw_log is not None:
            complete_count = _wait_for_complete(raw_log, complete_count, complete_timeout_s, dry_run)
        if index == passes:
            break
        sleep_s = guard_seconds if raw_log is not None else pass_seconds + guard_seconds
        print(f"# sleeping {sleep_s:.0f}s before next pass", flush=True)
        if not dry_run:
            time.sleep(sleep_s)

    print("# endpoint repeat command schedule complete", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Repeatedly start the H1 center-edge endpoint DAC sweep through capture_device's command FIFO."
    )
    parser.add_argument("--fifo", required=True, type=Path, help="Run-local command FIFO owned by capture_device.")
    parser.add_argument("--profile", default=DEFAULT_PROFILE, help="Sweep profile to load before each pass.")
    parser.add_argument("--passes", type=int, default=18, help="Number of endpoint sweep passes to start.")
    parser.add_argument(
        "--pass-seconds",
        type=float,
        default=DEFAULT_DWELL_S * DEFAULT_STEPS_PER_PASS,
        help="Expected profile runtime before guard time is added. Used only when --raw-log is omitted.",
    )
    parser.add_argument("--guard-seconds", type=float, default=DEFAULT_GUARD_S)
    parser.add_argument("--raw-log", type=Path, help="Optional raw serial log to watch for DAC complete rows.")
    parser.add_argument("--complete-timeout-s", type=float, default=DEFAULT_COMPLETE_TIMEOUT_S)
    parser.add_argument("--dry-run", action="store_true", help="Print commands without writing to the FIFO.")
    args = parser.parse_args()

    try:
        run_endpoint_repeat(
            args.fifo,
            profile=args.profile,
            passes=args.passes,
            pass_seconds=args.pass_seconds,
            guard_seconds=args.guard_seconds,
            raw_log=args.raw_log,
            complete_timeout_s=args.complete_timeout_s,
            dry_run=args.dry_run,
        )
    except (OSError, TimeoutError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
