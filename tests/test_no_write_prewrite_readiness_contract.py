from __future__ import annotations

from host.otis_tools.no_write_prewrite_readiness_contract import (
    RUNTIME_CONTRACT_ID,
    canonical_prewrite_fixture,
    evaluate_prewrite_readiness,
)


IDENTITY = {
    "run_identity": "cx319_tight_lower:3195001",
    "build_identity": "a" * 64 + ":" + "b" * 64,
    "profile_identity": "cx319_tight_lower",
    "estimator_sha256": "c" * 64,
    "model_sha256": "d" * 64,
    "active_policy_sha256": "e" * 64,
    "response_policy_sha256": "f" * 64,
    "numerical_policy_sha256": "1" * 64,
}


def _readiness(health, *, baseline: int = 0):  # type: ignore[no-untyped-def]
    return evaluate_prewrite_readiness(
        health,
        expected_identity=IDENTITY,
        planned_live_stimulus_code=0xA808,
        active_row_count=0,
        dac_row_count=0,
        telemetry_drop_baseline=baseline,
    )


def test_g1_fixture_requires_the_gnss_state_needed_by_g2() -> None:
    health = canonical_prewrite_fixture(
        expected_identity=IDENTITY,
        planned_live_stimulus_code=0xA808,
    )

    readiness = _readiness(health)

    assert readiness.ready is True
    assert readiness.contract_id == RUNTIME_CONTRACT_ID
    assert health[("gnss_receiver", "identity_epoch")] == "1"
    assert health[("gnss_receiver", "link_state")] == "online"
    assert health[("gnss_receiver", "confirmed_baud")] == "115200"
    assert health[("gnss_receiver", "configuration_confirmed")] == "true"
    assert health[("gnss_receiver", "control_eligible")] == "true"
    assert health[("gnss_receiver", "operational_bootstrap_state")] == "complete"
    assert health[("gnss_receiver", "operational_bootstrap_attempt_count")] == "2"
    assert health[("gnss_receiver", "target_baud_command_attempt_count")] == "2"
    assert (
        health[
            (
                "gnss_receiver",
                "post_bootstrap_target_baud_command_attempt_count",
            )
        ]
        == "0"
    )
    assert health[("gnss_receiver", "local_uart_baud")] == "115200"
    assert health[("gnss_receiver", "post_bootstrap_baud_change_count")] == "0"


def test_g1_rejects_incomplete_operational_baud_promotion() -> None:
    health = canonical_prewrite_fixture(
        expected_identity=IDENTITY,
        planned_live_stimulus_code=0xA808,
    )
    health[("gnss_receiver", "operational_bootstrap_state")] = "in_progress"
    health[("gnss_receiver", "operational_bootstrap_attempt_count")] = "1"

    readiness = _readiness(health)

    assert readiness.ready is False
    assert any(
        "gnss_receiver.operational_bootstrap_state='in_progress'" in item
        for item in readiness.mismatches
    )


def test_g1_rejects_any_post_bootstrap_promotion_attempt() -> None:
    health = canonical_prewrite_fixture(
        expected_identity=IDENTITY,
        planned_live_stimulus_code=0xA808,
    )
    health[
        (
            "gnss_receiver",
            "post_bootstrap_target_baud_command_attempt_count",
        )
    ] = "1"

    readiness = _readiness(health)

    assert readiness.ready is False
    assert any(
        "post_bootstrap_target_baud_command_attempt_count='1'" in item
        for item in readiness.mismatches
    )


def test_g1_rejects_the_epoch_two_state_observed_in_g2_v7() -> None:
    health = canonical_prewrite_fixture(
        expected_identity=IDENTITY,
        planned_live_stimulus_code=0xA808,
    )
    health.update(
        {
            ("gnss_receiver", "identity_epoch"): "2",
            ("gnss_receiver", "identity_stable"): "false",
            ("gnss_receiver", "metadata_control_eligible"): "false",
            ("gnss_receiver", "raw_pps_control_eligible"): "false",
            ("gnss_receiver", "control_eligible"): "false",
        }
    )

    readiness = _readiness(health)

    assert readiness.ready is False
    assert any(
        "gnss_receiver.identity_epoch='2'" in item
        for item in readiness.mismatches
    )


def test_g1_accepts_only_the_frozen_nonzero_attach_baseline() -> None:
    health = canonical_prewrite_fixture(
        expected_identity=IDENTITY,
        planned_live_stimulus_code=0xA808,
    )
    health[("dual_core", "telemetry_dropped")] = "3"

    assert _readiness(health, baseline=3).ready is True
    assert _readiness(health, baseline=2).ready is False
