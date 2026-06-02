#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path


SCRIPT_PATH = Path(__file__).resolve()
REPO_ROOT = SCRIPT_PATH.parents[4]


COMMANDS: tuple[tuple[str, ...], ...] = (
    ("python3", "-m", "pytest"),
    (
        "python3",
        "tools/otis_wire_validate.py",
        "firmware/arduino/validation/golden/synthetic_sw1_excerpt.txt",
        "--profile",
        "synthetic",
    ),
    (
        "python3",
        "tools/otis_wire_validate.py",
        "firmware/arduino/validation/golden/gpio_loopback_sw1_excerpt.txt",
        "--profile",
        "gpio_loopback",
    ),
    (
        "python3",
        "tools/otis_wire_validate.py",
        "firmware/arduino/validation/golden/gpin0_observe_sw1_excerpt.txt",
        "--profile",
        "gpin0_observe",
    ),
    (
        "python3",
        "-m",
        "host.otis_tools.validate_run",
        "examples/h0_pps_tcxo_synthetic",
    ),
    (
        "python3",
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
        printable = " ".join(command)
        print(f"$ {printable}", flush=True)
        if args.list:
            continue
        result = subprocess.run(command, cwd=REPO_ROOT)
        if result.returncode != 0:
            return result.returncode
    return 0


if __name__ == "__main__":
    sys.exit(main())
