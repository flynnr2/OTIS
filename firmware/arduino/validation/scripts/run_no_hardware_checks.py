#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[4]


PYTHON = sys.executable


COMMANDS: tuple[tuple[str, ...], ...] = (
    (PYTHON, "-m", "pytest"),
    (PYTHON, "tools/firmware_matrix.py"),
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


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run OTIS validation checks that do not require bench hardware."
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print commands without executing them.",
    )
    args = parser.parse_args()

    for command in COMMANDS:
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
