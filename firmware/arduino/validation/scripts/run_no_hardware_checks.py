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
    "tests/test_gnss_baud_characterization_preflight.py",
    "tests/test_gnss_baud_envelope_bundle.py",
    "tests/test_gnss_baud_envelope_host.py",
    "tests/test_run_tools.py",
    "tests/test_diagnostics_contract.py",
    "tests/test_active_status_contract.py",
    "tests/test_programme_status.py",
    "tests/test_frequency_control_replay.py",
    "tests/test_frequency_control_firmware_parity.py",
    "tests/test_active_transaction_firmware.py",
    "tests/test_active_hybrid_policy.py",
    "tests/test_active_hybrid_programme_contract.py",
    "tests/test_active_hybrid_preflight.py",
    "tests/test_active_hybrid_activation.py",
    "tests/test_active_hybrid_firmware_parity.py",
    "tests/test_active_hybrid_contract.py",
    "tests/test_active_hybrid_programme.py",
    "tests/test_active_transactions.py",
    "tests/test_cx321_response_observability_design.py",
    "tests/test_cx321_plant_sign_firmware.py",
    "tests/test_cx321_plant_sign_evidence_guard.py",
    "tests/test_pps_gate_math.py",
    "tests/test_tight_deadband_policy.py",
    "tests/test_time_domains.py",
    "tests/test_range_spanning_programme.py",
)

CAMPAIGN_TESTS = (
    "tests/test_gnss_baud_characterization_preflight.py",
    "tests/test_gnss_baud_envelope_bundle.py",
    "tests/test_gnss_baud_envelope_host.py",
    "tests/test_programme_status.py",
    "tests/test_active_status_contract.py",
    "tests/test_diagnostics_contract.py",
    "tests/test_count_observation_ownership.py",
    "tests/test_memory_budget_ownership.py",
    "tests/test_serial_frame_arbiter.py",
    "tests/test_capture_device.py",
    "tests/test_capture_segment_rotation.py",
    "tests/test_capture_owner_handoff.py",
    "tests/test_abort_transport.py",
    "tests/test_active_transactions.py",
    "tests/test_active_hybrid_policy.py",
    "tests/test_active_hybrid_firmware_parity.py",
    "tests/test_active_hybrid_contract.py",
    "tests/test_active_hybrid_programme.py",
    "tests/test_active_hybrid_programme_contract.py",
    "tests/test_active_hybrid_preflight.py",
    "tests/test_active_hybrid_live_supervisor.py",
    "tests/test_active_hybrid_live_rehearsal.py",
    "tests/test_active_hybrid_live_analyze.py",
    "tests/test_active_hybrid_run.py",
    "tests/test_cx321_response_observability_design.py",
    "tests/test_cx321_plant_sign_firmware.py",
    "tests/test_cx321_plant_sign_evidence_guard.py",
    "tests/test_frequency_control_supervisor.py",
    "tests/test_control_evidence_replay.py",
    "tests/test_pps_snapshot_reconstruction.py",
    "tests/test_pps_cumulative_span_estimator.py",
    "tests/test_reference_relative_phase_estimator.py",
    "tests/test_time_domains.py",
    "tests/test_range_spanning_programme.py",
    "tests/test_range_spanning_operational_path.py",
    "tests/test_evidence.py",
    "tests/test_evidence_finalization.py",
    "tests/test_evidence_index.py",
    "tests/test_no_write_qualification_operational_rehearsal.py",
    "tests/test_bounded_tight_deadband_bundle.py",
)

HISTORICAL_GUIDANCE = (
    "Historical verification is intentionally outside current HEAD. Check out "
    "the exact source revision recorded by the package manifest or scientific "
    "report, then run that revision's documented verification command."
)


def commands_for_tier(tier: str) -> tuple[tuple[str, ...], ...]:
    if tier == "fast":
        return (
            (PYTHON, "-m", "pytest", "-q", *FAST_TESTS),
            (PYTHON, "tools/firmware_matrix.py", "--tier", "fast"),
        )
    if tier == "campaign":
        return (
            (PYTHON, "-m", "pytest", "-q", *CAMPAIGN_TESTS),
            (PYTHON, "tools/firmware_matrix.py", "--tier", "campaign"),
        )
    if tier == "release":
        return (
            (PYTHON, "-m", "pytest", "-m", "not historical"),
            (PYTHON, "tools/firmware_matrix.py", "--tier", "release"),
        )
    if tier == "historical":
        return ()
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
        choices=("fast", "campaign", "release", "historical"),
        default="release",
        help="Executable no-hardware verification tier (default: release).",
    )
    args = parser.parse_args()

    if args.tier == "historical":
        print(HISTORICAL_GUIDANCE)
        return 0

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
