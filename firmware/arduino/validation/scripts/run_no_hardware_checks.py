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
    "tests/test_python_name_resolution.py",
    "tests/test_current_code_surface.py",
    "tests/test_current_profiles.py",
    "tests/test_firmware_build.py",
    "tests/test_instrument_native.py",
    "tests/test_instrument_integration_native.py",
    "tests/test_instrument_contract.py",
    "tests/test_adaptive_hybrid_policy.py",
    "tests/test_adaptive_hybrid_policy_native.py",
    "tests/test_metadata_hold_measurement.py",
    "tests/test_gnss_receiver.py",
    "tests/test_outbound_isolation.py",
    "tests/test_serial_frame_arbiter.py",
    "tests/test_diagnostic_transport_admission.py",
)

CAMPAIGN_TESTS = FAST_TESTS + (
    "tests/test_instrument_recorder.py",
    "tests/test_instrument_monitor.py",
    "tests/test_core0_description_transport.py",
    "tests/test_raw_measurement_replay.py",
    "tests/test_external_event_isolation.py",
    "tests/test_hardware_resource_ownership.py",
    "tests/test_count_observation_ownership.py",
    "tests/test_output_queue_consumer_ownership.py",
    "tests/test_pps_snapshot_contract.py",
    "tests/test_adafruit_devices.py",
    "tests/test_forwarded_clock_output_guards.py",
    "tests/test_forwarded_clock_monitor_backend.py",
    "tests/test_phase_preview_binding.py",
    "tests/test_frequency_regulation_capture_fault.py",
)


def commands_for_tier(tier: str) -> tuple[tuple[str, ...], ...]:
    if tier == "fast":
        tests = FAST_TESTS
    elif tier == "campaign":
        tests = CAMPAIGN_TESTS
    elif tier == "release":
        tests = ()
    else:
        raise ValueError(f"unsupported verification tier: {tier}")
    pytest_command = (
        (PYTHON, "-m", "pytest", "-q", *tests)
        if tests
        else (PYTHON, "-m", "pytest", "-q")
    )
    return (
        pytest_command,
        (PYTHON, "tools/build_firmware.py"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run current OTIS validation checks without bench hardware."
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="Print commands without executing them.",
    )
    parser.add_argument(
        "--tier",
        choices=("fast", "campaign", "release"),
        default="release",
        help="No-hardware verification tier (default: release).",
    )
    args = parser.parse_args()

    for command in commands_for_tier(args.tier):
        print("$ " + " ".join(command), flush=True)
        if args.list:
            continue
        result = subprocess.run(command, cwd=REPO_ROOT)
        if result.returncode != 0:
            return result.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
