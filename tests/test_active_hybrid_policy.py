from __future__ import annotations

import pytest

from host.otis_tools.active_hybrid_policy import (
    ActiveHybridController,
    HybridObservation,
    HybridPolicyError,
    HybridState,
    load_policy,
)


def _observation(
    timestamp_s: int,
    *,
    code: int = 0xA83C,
    dac_epoch: int = 1,
    frequency_hz: float = 0.0,
    counts: int = 0,
    tight_state: str = "TIGHT_INSIDE",
    phase_cycles: int = -24,
    phase_epoch: int = 1,
    phase_sequence: int = 1,
    outstanding: bool = False,
    **overrides: object,
) -> HybridObservation:
    values = {
        "timestamp_s": timestamp_s,
        "capture_session": 1,
        "source_first_sequence": max(1, timestamp_s - 599),
        "source_last_sequence": max(1, timestamp_s),
        "dac_epoch": dac_epoch,
        "applied_code": code,
        "frequency_error_hz": frequency_hz,
        "accumulated_edge_error_counts": counts,
        "tight_state": tight_state,
        "phase_epoch": phase_epoch,
        "phase_observation_sequence": phase_sequence,
        "relative_phase_cycles": phase_cycles,
        "phase_dac_epoch": dac_epoch,
        "phase_applied_code": code,
        "outstanding_request": outstanding,
    }
    values.update(overrides)
    return HybridObservation(**values)


def _pass_response(controller: ActiveHybridController) -> None:
    controller.note_response(
        classification="healthy_indeterminate_near_resolution",
        predicted_sign_observed=True,
        exact_replay=True,
        support_fresh=True,
        applied_epoch_exact=True,
    )


def test_policy_is_exact_bound_and_non_effective() -> None:
    policy = load_policy()

    assert policy.policy_id == "CX320_BOUNDED_ACTIVE_HYBRID_TIGHT_V1"
    assert policy.start_code == 0xA83C
    assert policy.maximum_applications == 4
    assert policy.maximum_cumulative_movement_codes == 84
    assert policy.qualified_duration_s == 12 * 60 * 60
    assert policy.wall_clock_limit_s == 16 * 60 * 60


def test_frequency_acquisition_and_phase_share_one_global_budget() -> None:
    controller = ActiveHybridController(load_policy())
    acquisition = controller.decide(
        _observation(
            1800,
            frequency_hz=0.01,
            counts=6,
            tight_state="OUTSIDE",
        )
    )

    assert acquisition.state_after == "FREQUENCY_ACQUIRE"
    assert acquisition.phase_term_hz == 0.0
    assert acquisition.requested_delta_codes == -21
    controller.note_application(
        acquisition,
        applied_code=0xA827,
        dac_epoch=2,
        downstream_consumers_exact=True,
    )
    assert controller.correction_count == 1
    assert controller.cumulative_movement_codes == 21
    assert controller.frequency_only_application_count == 1
    _pass_response(controller)


def test_first_material_transaction_blocks_later_authority_until_checkpoint() -> None:
    controller = ActiveHybridController(load_policy())
    entered = controller.decide(_observation(1800))
    assert entered.state_after == "PHASE_QUALIFY"
    assert entered.requested_delta_codes == 0

    first = controller.decide(
        _observation(3600, phase_cycles=-24, phase_sequence=2)
    )
    assert first.reason == "phase_material_request_ready"
    assert first.phase_term_hz > 0
    assert first.requested_delta_codes > 0
    assert first.counterfactual_frequency_only_delta_codes == 0
    assert first.phase_materially_influenced

    controller.note_application(
        first,
        applied_code=first.requested_code,
        dac_epoch=2,
        downstream_consumers_exact=True,
    )
    assert controller.state is HybridState.FIRST_PHASE_TRANSACTION
    blocked = controller.decide(
        _observation(
            4200,
            code=first.requested_code,
            dac_epoch=2,
            phase_cycles=-23,
            phase_sequence=3,
            outstanding=True,
        )
    )
    assert blocked.requested_delta_codes == 0
    assert blocked.reason == "request_or_response_checkpoint_outstanding"

    _pass_response(controller)
    reacquired = controller.decide(
        _observation(
            5400,
            code=first.requested_code,
            dac_epoch=2,
            phase_cycles=-22,
            phase_sequence=4,
        )
    )
    assert reacquired.state_after == "HYBRID_TRACKING"
    assert reacquired.requested_delta_codes == 0
    assert controller.first_checkpoint_response_passed

    repeated = controller.decide(
        _observation(
            6000,
            code=first.requested_code,
            dac_epoch=2,
            phase_cycles=-21,
            phase_sequence=5,
        )
    )
    assert repeated.phase_materially_influenced
    assert repeated.requested_delta_codes > 0


def test_phase_invalidation_degrades_only_at_a_clean_boundary() -> None:
    controller = ActiveHybridController(load_policy())
    controller.decide(_observation(1800))
    degraded = controller.decide(
        _observation(3600, phase_continuous=False, phase_sequence=2)
    )

    assert degraded.state_after == "PHASE_DEGRADED_FREQUENCY_ONLY"
    assert degraded.phase_term_hz == 0.0
    assert degraded.requested_delta_codes == 0


def test_phase_invalidation_during_material_transaction_is_fail_static() -> None:
    controller = ActiveHybridController(load_policy())
    controller.decide(_observation(1800))
    decision = controller.decide(_observation(3600, phase_sequence=2))
    controller.note_application(
        decision,
        applied_code=decision.requested_code,
        dac_epoch=2,
        downstream_consumers_exact=True,
    )
    failed = controller.decide(
        _observation(
            4200,
            code=decision.requested_code,
            dac_epoch=2,
            phase_sequence=3,
            phase_continuous=False,
            outstanding=True,
        )
    )

    assert failed.state_after == "FAIL_STATIC"
    assert failed.reason == "phase_invalid_during_transaction_or_response_horizon"


def test_wrong_sign_or_inexact_response_fails_static() -> None:
    controller = ActiveHybridController(load_policy())
    controller.decide(_observation(1800))
    decision = controller.decide(_observation(3600, phase_sequence=2))
    controller.note_application(
        decision,
        applied_code=decision.requested_code,
        dac_epoch=2,
        downstream_consumers_exact=True,
    )

    controller.note_response(
        classification="wrong_sign",
        predicted_sign_observed=False,
        exact_replay=True,
        support_fresh=True,
        applied_epoch_exact=True,
    )
    assert controller.state is HybridState.FAIL_STATIC


def test_application_identity_mismatch_latches_fail_static() -> None:
    controller = ActiveHybridController(load_policy())
    controller.decide(_observation(1800))
    decision = controller.decide(_observation(3600, phase_sequence=2))

    with pytest.raises(HybridPolicyError, match="application_or_downstream_epoch_mismatch"):
        controller.note_application(
            decision,
            applied_code=decision.requested_code,
            dac_epoch=99,
            downstream_consumers_exact=True,
        )
    assert controller.state is HybridState.FAIL_STATIC


def test_shared_health_or_epoch_ambiguity_fails_closed() -> None:
    controller = ActiveHybridController(load_policy())

    failed = controller.decide(_observation(1800, common_health_clean=False))
    assert failed.state_after == "FAIL_STATIC"
    assert failed.requested_delta_codes == 0

    controller = ActiveHybridController(load_policy())
    mismatched = controller.decide(_observation(1800, dac_epoch=2))
    assert mismatched.state_after == "FAIL_STATIC"
    assert mismatched.reason == "actual_applied_code_or_dac_epoch_ambiguous"


def test_snapshot_contains_distinct_frequency_phase_and_material_counts() -> None:
    controller = ActiveHybridController(load_policy())
    snapshot = controller.snapshot()

    assert snapshot["applied_code"] == 0xA83C
    assert snapshot["dac_epoch"] == 1
    assert snapshot["frequency_only_application_count"] == 0
    assert snapshot["phase_nonzero_application_count"] == 0
    assert snapshot["phase_material_application_count"] == 0
