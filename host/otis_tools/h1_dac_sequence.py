from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
import argparse
import csv
import signal
import time

from .serial_commands import send_command_to_fifo


RUN_017_CODES = (0x8000, 0x8800, 0x8000, 0x7800, 0x8000, 0x9000, 0x8000, 0x7000, 0x8000)
RUN_017_DWELLS_S = (10800.0, 2700.0, 2700.0, 2700.0, 2700.0, 2700.0, 2700.0, 2700.0, 7200.0)
RUN_017_LABELS = (
    "warmup_initial_center",
    "positive_medium",
    "center_b",
    "negative_medium",
    "center_c",
    "positive_large",
    "center_d",
    "negative_large",
    "final_center",
)
RUN_017_RESTORE_CODE = 0x8000


@dataclass(frozen=True)
class DacSequenceStep:
    label: str
    code: int
    dwell_s: float


def run_017_schedule(final_dwell_s: float = RUN_017_DWELLS_S[-1]) -> tuple[DacSequenceStep, ...]:
    if final_dwell_s < RUN_017_DWELLS_S[-1]:
        raise ValueError("run_017 final dwell must be at least 7200 seconds")
    dwells = (*RUN_017_DWELLS_S[:-1], float(final_dwell_s))
    return tuple(
        DacSequenceStep(label=label, code=code, dwell_s=dwell)
        for label, code, dwell in zip(RUN_017_LABELS, RUN_017_CODES, dwells)
    )


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _format_code(code: int) -> str:
    return f"0x{code:04X}"


def _write_log(log_path: Path | None, message: str) -> None:
    line = f"{_utc_now()} {message}"
    print(line, flush=True)
    if log_path is not None:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")


def _matching_dac_status_count(sts_csv: Path, code: int) -> int:
    if not sts_csv.exists():
        return 0
    expected = _format_code(code)
    count = 0
    with sts_csv.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if (
                row.get("component") == "dac"
                and row.get("status_key") == "accepted_code"
                and row.get("status_value") == expected
            ):
                count += 1
    return count


def _wait_for_dac_ack(sts_csv: Path, code: int, previous_count: int, timeout_s: float, dry_run: bool) -> None:
    if dry_run:
        return
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if _matching_dac_status_count(sts_csv, code) > previous_count:
            return
        time.sleep(1.0)
    raise TimeoutError(f"timed out waiting for dac accepted_code={_format_code(code)} in {sts_csv}")


def _send_dac_set(fifo: Path, code: int, dry_run: bool, log_path: Path | None) -> None:
    command = f"DAC SET {_format_code(code)}"
    _write_log(log_path, f"command {command}")
    if not dry_run:
        send_command_to_fifo(fifo, command)


def _sleep_monotonic(dwell_s: float, stop_requested: callable, log_path: Path | None, dry_run: bool) -> None:
    if dry_run:
        _write_log(log_path, f"dry_run_skip_sleep dwell_s={dwell_s:.0f}")
        return
    deadline = time.monotonic() + dwell_s
    while True:
        if stop_requested():
            raise KeyboardInterrupt
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 30.0))


def run_sequence(
    run_dir: Path,
    fifo: Path,
    *,
    final_dwell_s: float,
    ack_timeout_s: float,
    dry_run: bool,
    log_path: Path | None,
) -> None:
    if run_dir.name != "run_017":
        raise ValueError("this runner is specific to run_017 and requires a run_dir named run_017")
    if ack_timeout_s <= 0:
        raise ValueError("ack_timeout_s must be positive")
    schedule = run_017_schedule(final_dwell_s)
    sts_csv = run_dir / "csv" / "sts.csv"
    interrupted = False

    _write_log(log_path, "run_017 H1 DAC sequence plan")
    elapsed = 0.0
    for index, step in enumerate(schedule, start=1):
        _write_log(
            log_path,
            f"plan step={index} label={step.label} code={_format_code(step.code)} "
            f"dwell_s={step.dwell_s:.0f} planned_start_s={elapsed:.0f}",
        )
        elapsed += step.dwell_s

    stop_flag = {"requested": False}

    def _request_stop(signum, _frame):
        stop_flag["requested"] = True
        _write_log(log_path, f"signal_received signum={signum}")

    previous_handlers = {
        signal.SIGINT: signal.getsignal(signal.SIGINT),
        signal.SIGTERM: signal.getsignal(signal.SIGTERM),
    }
    signal.signal(signal.SIGINT, _request_stop)
    signal.signal(signal.SIGTERM, _request_stop)

    try:
        for index, step in enumerate(schedule, start=1):
            if stop_flag["requested"]:
                raise KeyboardInterrupt
            _write_log(log_path, f"transition_start step={index} label={step.label} code={_format_code(step.code)}")
            previous_ack_count = _matching_dac_status_count(sts_csv, step.code)
            _send_dac_set(fifo, step.code, dry_run, log_path)
            _wait_for_dac_ack(sts_csv, step.code, previous_ack_count, ack_timeout_s, dry_run)
            _write_log(log_path, f"transition_ack step={index} label={step.label} code={_format_code(step.code)}")
            _sleep_monotonic(step.dwell_s, lambda: stop_flag["requested"], log_path, dry_run)
            _write_log(log_path, f"dwell_complete step={index} label={step.label} code={_format_code(step.code)}")
    except KeyboardInterrupt:
        interrupted = True
        raise
    finally:
        signal.signal(signal.SIGINT, previous_handlers[signal.SIGINT])
        signal.signal(signal.SIGTERM, previous_handlers[signal.SIGTERM])
        _write_log(log_path, f"restore_start code={_format_code(RUN_017_RESTORE_CODE)} interrupted={str(interrupted).lower()}")
        previous_ack_count = _matching_dac_status_count(sts_csv, RUN_017_RESTORE_CODE)
        _send_dac_set(fifo, RUN_017_RESTORE_CODE, dry_run, log_path)
        _wait_for_dac_ack(sts_csv, RUN_017_RESTORE_CODE, previous_ack_count, ack_timeout_s, dry_run)
        _write_log(log_path, f"restore_ack code={_format_code(RUN_017_RESTORE_CODE)}")


def main() -> None:
    default_run_dir = Path("runs/h1_open_loop/dac_manual_sweep/run_017")
    parser = argparse.ArgumentParser(description="Run the fixed run_017 H1 DAC timed sequence through capture_device's FIFO.")
    parser.add_argument("--run-dir", type=Path, default=default_run_dir)
    parser.add_argument("--fifo", type=Path, help="Run-local command FIFO owned by capture_device.")
    parser.add_argument("--final-dwell-s", type=float, default=RUN_017_DWELLS_S[-1], help="Final 0x8000 dwell; must be at least 7200 s.")
    parser.add_argument("--ack-timeout-s", type=float, default=30.0, help="Seconds to wait for STS dac/accepted_code acknowledgement.")
    parser.add_argument("--log", type=Path, help="Sequence command log. Defaults to RUN_DIR/control/run_017_sequence.log.")
    parser.add_argument("--dry-run", action="store_true", help="Print the plan and commands without writing to the FIFO.")
    args = parser.parse_args()

    fifo = args.fifo or args.run_dir / "control" / "commands.fifo"
    log_path = args.log if args.log is not None else args.run_dir / "control" / "run_017_sequence.log"
    try:
        run_sequence(
            args.run_dir,
            fifo,
            final_dwell_s=args.final_dwell_s,
            ack_timeout_s=args.ack_timeout_s,
            dry_run=args.dry_run,
            log_path=log_path,
        )
    except (OSError, TimeoutError, ValueError, KeyboardInterrupt) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
