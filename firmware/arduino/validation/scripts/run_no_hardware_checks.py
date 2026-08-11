#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[4]


PYTHON = sys.executable


FAST_TESTS = (
    "tests/test_firmware_matrix.py",
    "tests/test_measurement_semantics.py",
    "tests/test_pps_count_boundary.py",
    "tests/test_pps_snapshot_reconstruction.py",
    "tests/test_diagnostics_contract.py",
    "tests/test_active_status_contract.py",
    "tests/test_programme_status.py",
    "tests/test_dual_core_partition.py",
    "tests/test_serial_frame_arbiter.py",
    "tests/test_capture_device.py",
)

CAMPAIGN_TESTS = (
    "tests/test_programme_status.py",
    "tests/test_active_status_contract.py",
    "tests/test_diagnostics_contract.py",
    "tests/test_count_observation_ownership.py",
    "tests/test_memory_budget_ownership.py",
    "tests/test_serial_frame_arbiter.py",
    "tests/test_capture_device.py",
    "tests/test_cx318_capture_segment.py",
    "tests/test_cx318_capture_handoff.py",
    "tests/test_cx317_abort_path.py",
    "tests/test_cx317_stage7_transport_rehearsal.py",
    "tests/test_evidence.py",
    "tests/test_evidence_index.py",
    "tests/test_platform_rehearsal.py",
)


COMMON_FIXTURE_COMMANDS: tuple[tuple[str, ...], ...] = (
    (
        PYTHON,
        "tools/otis_wire_validate.py",
        "firmware/arduino/validation/golden/synthetic_sw1_excerpt.txt",
        "--profile",
        "synthetic",
    ),
    (
        PYTHON,
        "tools/otis_wire_validate.py",
        "firmware/arduino/validation/golden/gpio_loopback_sw1_excerpt.txt",
        "--profile",
        "gpio_loopback",
    ),
    (
        PYTHON,
        "tools/otis_wire_validate.py",
        "firmware/arduino/validation/golden/gpin0_observe_sw1_excerpt.txt",
        "--profile",
        "gpin0_observe",
    ),
    (
        PYTHON,
        "-m",
        "host.otis_tools.validate_run",
        "examples/h0_pps_tcxo_synthetic",
    ),
    (
        PYTHON,
        "-m",
        "host.otis_tools.report_run",
        "examples/h0_pps_tcxo_synthetic",
    ),
)


def commands_for_tier(tier: str) -> tuple[tuple[str, ...], ...]:
    if tier == "fast":
        return (
            (PYTHON, "-m", "pytest", "-q", *FAST_TESTS),
            (PYTHON, "tools/firmware_matrix.py", "--tier", "fast"),
            *COMMON_FIXTURE_COMMANDS,
        )
    if tier == "standard_campaign":
        return (
            (PYTHON, "-m", "pytest", "-q", *CAMPAIGN_TESTS),
            (
                PYTHON,
                "tools/firmware_matrix.py",
                "--tier",
                "standard_campaign",
            ),
            *COMMON_FIXTURE_COMMANDS,
        )
    if tier == "release":
        return (
            (PYTHON, "-m", "pytest"),
            (PYTHON, "tools/firmware_matrix.py", "--tier", "release"),
            *COMMON_FIXTURE_COMMANDS,
        )
    raise ValueError(f"unsupported verification tier: {tier}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run OTIS validation checks that do not require bench hardware."
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print commands without executing them.",
    )
    parser.add_argument(
        "--tier",
        choices=("fast", "standard_campaign", "release"),
        default="release",
        help="Executable no-hardware verification tier (default: release).",
    )
    args = parser.parse_args()

    for command in commands_for_tier(args.tier):
        resolved_command = (
            (sys.executable, *command[1:])
            if command and command[0] == "python3"
            else command
        )
        printable = " ".join(resolved_command)
        print(f"$ {printable}", flush=True)
        if args.list:
            continue
        result = subprocess.run(resolved_command, cwd=REPO_ROOT)
        if result.returncode != 0:
            return result.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
