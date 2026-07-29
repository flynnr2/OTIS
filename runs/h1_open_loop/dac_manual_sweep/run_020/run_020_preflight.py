#!/usr/bin/env python3
"""Fail-closed Run 020 firmware and measurement preflight."""

from __future__ import annotations

import argparse
import csv
import io
from pathlib import Path
import sys
import time

REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from host.otis_tools.serial_commands import send_command_to_fifo


EXPECTED_STATUS = {
    ("firmware", "version"): "SW1",
    ("firmware", "config_id"): "run_020_crossing_v1",
    ("system", "mode"): "H1_OCXO_OBSERVE_OPEN_LOOP",
    ("build", "capture_backend"): "irq",
    ("build", "tcxo_counter_backend"): "pio_long_gate_gpio20",
    ("capture", "counter_gate_period_us"): "300000000",
    ("build", "enable_pps_dual_observer"): "1",
    ("build", "enable_dac_ad5693r"): "1",
    ("build", "enable_h1_dac_sweep"): "1",
    ("build", "enable_env_sensors"): "1",
    ("build", "enable_env_sht4x"): "1",
    ("build", "enable_env_bmp280"): "1",
    ("sweep", "default_dwell_ms"): "2400000",
    ("sweep", "slope_dwell_ms"): "2400000",
    ("sweep", "tiny_step_codes"): "0x0300",
    ("sweep", "center_code"): "0xAE00",
    ("dac", "enabled"): "true",
    ("dac", "initialized"): "true",
    ("dac", "last_write_ok"): "true",
    ("dac", "min_code"): "0x6000",
    ("dac", "max_code"): "0xFC00",
    ("dac", "last_applied_code"): "0x8000",
    ("fc0", "measurement_mode"): "raw_edge_long_gate",
    ("fc0", "gate_period_us"): "300000000",
    ("fc0", "fc0_fault"): "false",
    ("sweep", "running"): "false",
    ("sweep", "pending_start"): "false",
    ("sweep", "profile"): "tiny_plus_minus_2",
    ("sweep", "step_count"): "9",
    ("sweep", "clamps_configured"): "true",
    ("capture", "dropped_count"): "0",
    ("capture", "error_flags"): "0",
    ("pps_d14", "rejected_short_count"): "0",
    ("pps_d14", "rejected_long_count"): "0",
    ("pps_d10", "buffer_overflow_count"): "0",
    ("pps_dual_observer", "d14_raw_minus_d10_raw"): "0",
    ("pps_dual_observer", "agreement_state"): "MATCHING",
}

EXPECTED_PROFILE = [
    (0, 0xAE00, 2_400_000),
    (1, 0xB100, 2_400_000),
    (2, 0xAE00, 2_400_000),
    (3, 0xAB00, 2_400_000),
    (4, 0xAE00, 2_400_000),
    (5, 0xB400, 2_400_000),
    (6, 0xAE00, 2_400_000),
    (7, 0xA800, 2_400_000),
    (8, 0xAE00, 2_400_000),
]

READY_STATUS = {
    ("fc0", "valid"): "true",
    ("fc0", "last_window_invalid_reason"): "none",
    ("fc0", "fc0_valid_for_control"): "true",
    ("fc0", "fc0_fault"): "false",
}

WAIT_HEALTH_STATUS = {
    ("capture", "dropped_count"): "0",
    ("capture", "error_flags"): "0",
    ("pps_d14", "rejected_short_count"): "0",
    ("pps_d14", "rejected_long_count"): "0",
    ("pps_d10", "buffer_overflow_count"): "0",
    ("pps_dual_observer", "d14_raw_minus_d10_raw"): "0",
    ("pps_dual_observer", "agreement_state"): "MATCHING",
}


def _records_since(raw_log: Path, offset: int) -> tuple[dict[tuple[str, str], str], list[tuple[int, int, int]], bool]:
    with raw_log.open("rb") as handle:
        handle.seek(offset)
        text = handle.read().decode("utf-8", errors="replace")

    status: dict[tuple[str, str], str] = {}
    profile: list[tuple[int, int, int]] = []
    environment_seen = False
    for row in csv.reader(io.StringIO(text)):
        if not row:
            continue
        if row[0] == "STS" and len(row) >= 10:
            status[(row[5], row[6])] = row[7]
        elif row[0] == "DAC" and len(row) >= 13 and row[11] == "profile_step":
            profile.append((int(row[4]), int(row[6]), int(row[10])))
        elif row[0] == "ENV":
            environment_seen = True
    return status, profile, environment_seen


def _mismatches(
    status: dict[tuple[str, str], str],
    expected: dict[tuple[str, str], str],
) -> list[str]:
    return [
        f"{component}.{key}: expected {value!r}, observed {status.get((component, key))!r}"
        for (component, key), value in expected.items()
        if status.get((component, key)) != value
    ]


def verify_preflight(
    fifo: Path,
    raw_log: Path,
    response_timeout_s: float = 20.0,
    qualification_timeout_s: float = 1800.0,
) -> None:
    if not raw_log.exists() or raw_log.stat().st_size == 0:
        raise RuntimeError(f"capture is not producing {raw_log}")
    offset = raw_log.stat().st_size

    commands = (
        "SWEEP STOP",
        "DAC SET 0x8000",
        "CONFIG?",
        "DAC?",
        "FC0?",
        "SWEEP LOAD TINY_PLUS_MINUS_2",
        "SWEEP?",
    )
    for command in commands:
        send_command_to_fifo(fifo, command)
        time.sleep(0.15)

    deadline = time.monotonic() + response_timeout_s
    last_status: dict[tuple[str, str], str] = {}
    last_profile: list[tuple[int, int, int]] = []
    environment_seen = False
    while time.monotonic() < deadline:
        last_status, last_profile, environment_seen = _records_since(raw_log, offset)
        if (
            all(key in last_status for key in EXPECTED_STATUS)
            and len(last_profile) >= len(EXPECTED_PROFILE)
            and environment_seen
        ):
            break
        time.sleep(0.5)

    failures = _mismatches(last_status, EXPECTED_STATUS)
    observed_profile = last_profile[-len(EXPECTED_PROFILE) :]
    if observed_profile != EXPECTED_PROFILE:
        failures.append(
            "profile plan mismatch: expected "
            f"{EXPECTED_PROFILE!r}, observed {observed_profile!r}"
        )
    if not environment_seen:
        failures.append("no ENV record observed during preflight")

    if failures:
        detail = "\n  - ".join(failures)
        raise RuntimeError(f"RUN 020 PREFLIGHT FAILED; SWEEP NOT STARTED:\n  - {detail}")

    print("RUN 020 STATIC PREFLIGHT PASSED", flush=True)
    print("  waiting for FC0 startup qualification; sweep remains stopped", flush=True)
    qualification_deadline = time.monotonic() + qualification_timeout_s
    next_query = 0.0
    next_progress = 0.0
    while time.monotonic() < qualification_deadline:
        now = time.monotonic()
        if now >= next_query:
            send_command_to_fifo(fifo, "FC0?")
            next_query = now + 10.0
        last_status, _, _ = _records_since(raw_log, offset)

        health_failures = _mismatches(last_status, WAIT_HEALTH_STATUS)
        if last_status.get(("fc0", "fc0_fault")) == "true":
            health_failures.append("fc0.fc0_fault asserted during qualification")
        if health_failures:
            detail = "\n  - ".join(health_failures)
            raise RuntimeError(
                f"RUN 020 PREFLIGHT FAILED DURING QUALIFICATION; SWEEP NOT STARTED:\n  - {detail}"
            )

        if not _mismatches(last_status, READY_STATUS):
            break
        if now >= next_progress:
            print(
                "  FC0 waiting:"
                f" uptime={last_status.get(('system', 'uptime_seconds'), '?')}s"
                f" valid={last_status.get(('fc0', 'valid'), '?')}"
                f" inhibit={last_status.get(('fc0', 'startup_inhibit_active'), '?')}"
                f" clean_windows={last_status.get(('fc0', 'fc0_clean_window_count'), '?')}"
                f" control_qualified={last_status.get(('fc0', 'fc0_valid_for_control'), '?')}",
                flush=True,
            )
            next_progress = now + 60.0
        time.sleep(1.0)
    else:
        detail = "\n  - ".join(_mismatches(last_status, READY_STATUS))
        raise RuntimeError(
            "RUN 020 PREFLIGHT TIMED OUT WAITING FOR FC0; SWEEP NOT STARTED:"
            f"\n  - {detail}"
        )

    print("RUN 020 PREFLIGHT PASSED", flush=True)
    print("  firmware configuration: exact match", flush=True)
    print("  measurement/PPS health: clean and control-qualified", flush=True)
    print("  DAC restored to 0x8000", flush=True)
    print("  non-actuating profile plan: AE00,B100,AE00,AB00,AE00,B400,AE00,A800,AE00", flush=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fifo", required=True, type=Path)
    parser.add_argument("--raw-log", required=True, type=Path)
    parser.add_argument("--response-timeout-s", type=float, default=20.0)
    parser.add_argument("--qualification-timeout-s", type=float, default=1800.0)
    args = parser.parse_args()
    try:
        verify_preflight(
            args.fifo,
            args.raw_log,
            args.response_timeout_s,
            args.qualification_timeout_s,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        raise SystemExit(str(exc)) from exc


if __name__ == "__main__":
    main()
