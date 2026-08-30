from __future__ import annotations

from pathlib import Path
import shutil
import subprocess

import pytest

from host.otis_tools.adaptive_steering_offline import RequestReleaseState
from host.otis_tools.cx322_non_effective_operational_semantics import (
    AppliedTransaction,
    Cx322OperationalState,
    MetadataQualification,
    OperationalMode,
    accept_released_request,
    complete_accepted_application,
    complete_metadata_response_then_hold,
    degrade_phase_to_fll,
    metadata_loss,
    requalify_metadata_hold,
    requalify_new_phase_epoch,
)


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tests/cpp/cx322_non_effective_operational_semantics_harness.cpp"


def _compiler() -> str:
    compiler = shutil.which("g++") or shutil.which("clang++")
    if compiler is None:
        pytest.skip("C++17 compiler unavailable")
    return compiler


def test_cx322_non_effective_operational_semantics_native_fixture(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "cx322_non_effective_operational_semantics_harness"
    subprocess.run(
        [
            _compiler(),
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(HARNESS),
            "-o",
            str(executable),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    completed = subprocess.run(
        [str(executable)], check=True, capture_output=True, text=True
    )
    state = Cx322OperationalState(
        mode=OperationalMode.ACTIVE,
        capture_session="session-7",
        measurement_frontier=100,
        last_confirmed_code=0xA83C,
        last_confirmed_dac_epoch=4,
        metadata_sequence=20,
        phase_epoch="phase-7",
        phase_frontier=100,
        rearm_inhibit_reason="none",
    )
    released = metadata_loss(
        state,
        request_state=RequestReleaseState.RELEASED_PENDING,
        request_sequence=31,
        request_nonce=0xC322,
    )
    accepted = accept_released_request(
        released.state,
        request_sequence=31,
        request_nonce=0xC322,
        outcome_sequence=1,
    )
    phase_lost = degrade_phase_to_fll(accepted.state)
    applied = complete_accepted_application(
        phase_lost.state,
        AppliedTransaction(31, 0xC322, 1, 100, 0xA83D, 5, 101),
    )
    response = complete_metadata_response_then_hold(
        applied.state,
        request_sequence=31,
        request_nonce=0xC322,
        response_frontier=102,
    )
    response_parity = (
        "parity_acceptance_response=mode=GNSS_METADATA_HOLD,"
        f"code=0x{response.state.last_confirmed_code:04X},"
        f"dac_epoch={response.state.last_confirmed_dac_epoch},"
        f"measurement_frontier={response.state.measurement_frontier},"
        "phase_degraded=true,effective=false"
    )
    metadata = requalify_metadata_hold(
        response.state,
        MetadataQualification(
            True,
            True,
            "same_receiver_metadata_qualified",
            21,
            103,
            "session-7",
            104,
            0xA83D,
            5,
        ),
    )
    requalified = requalify_new_phase_epoch(
        metadata.state, phase_epoch="phase-8", phase_frontier=105
    )
    requalified_parity = (
        "parity_requalified=mode=ACTIVE,"
        f"code=0x{requalified.state.last_confirmed_code:04X},"
        f"dac_epoch={requalified.state.last_confirmed_dac_epoch},"
        f"measurement_frontier={requalified.state.measurement_frontier},"
        "control_rearm=true,effective=false"
    )
    assert completed.stdout.splitlines() == [
        response_parity,
        requalified_parity,
        "terminal=non_effective_semantics_verified_promotion_blocked_by_d9_gate",
        "native_cases=metadata_acceptance_phase_latch,absorbing_states,"
        "fll_independence,optional_isolation,stale_identity,application_guards",
    ]
