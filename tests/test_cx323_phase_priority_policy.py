from __future__ import annotations

import pytest

from host.otis_tools.active_hybrid_policy import (
    ActiveHybridController,
    CX323Debt,
    CX323Observation,
    CX323PhasePriorityController,
    HybridPolicyError,
    load_cx323_policy,
    load_policy,
)


def _controller() -> CX323PhasePriorityController:
    return CX323PhasePriorityController(load_cx323_policy())


def _observation(
    controller: CX323PhasePriorityController,
    timestamp_s: int,
    opening: int,
    closing: int,
    *,
    counts: int = -1,
    phase: int = -4,
    **changes: object,
) -> CX323Observation:
    values: dict[str, object] = {
        "timestamp_s": timestamp_s,
        "timestamp_ticks": timestamp_s * 16_000_000,
        "capture_session": 1,
        "source_first_sequence": opening,
        "source_last_sequence": closing,
        "dac_epoch": controller.dac_epoch,
        "applied_code": controller.applied_code,
        "accumulated_edge_error_counts": counts,
        "tight_state": "TIGHT_INSIDE",
        "phase_epoch": 1,
        "relative_phase_cycles": phase,
    }
    values.update(changes)
    return CX323Observation(**values)


def _persistent(
    controller: CX323PhasePriorityController, *, counts: int, phase: int,
    timestamp_s: int = 0,
) -> tuple:
    first = controller.decide(
        _observation(controller, timestamp_s, timestamp_s, timestamp_s + 600,
                     counts=counts, phase=phase)
    )
    second = controller.decide(
        _observation(controller, timestamp_s + 600, timestamp_s + 600,
                     timestamp_s + 1200, counts=counts, phase=phase)
    )
    return first, second


def test_loads_exact_selected_profile_without_changing_legacy_loaders() -> None:
    policy = load_cx323_policy()

    assert policy.policy_id == "CX323_PHASE_PRIORITY_PERSISTENT_MAINTENANCE_V1"
    assert policy.policy_sha256 == (
        "5943a1c33496a9354456ee1b8fec4c6f96b9e817b6d22cc8ee58385dc98ef43f"
    )
    assert load_policy().policy_id == "CX320_BOUNDED_ACTIVE_HYBRID_TIGHT_V1"
    assert isinstance(ActiveHybridController(load_policy()), ActiveHybridController)


def test_frozen_maintenance_sequences_and_legacy_path_classification() -> None:
    for counts in (1, -1):
        controller = _controller()
        first = controller.decide(_observation(controller, 0, 0, 600, counts=counts, phase=0))
        reset = controller.decide(_observation(controller, 600, 600, 1200, counts=0, phase=0))
        assert first.reason == "persistence_first_interval_hold"
        assert reset.requested_delta_codes == 0

    positive = _controller()
    first, second = _persistent(positive, counts=1, phase=0)
    assert first.reason == "persistence_first_interval_hold"
    assert second.requested_delta_codes == -4

    negative = _controller()
    _, second = _persistent(negative, counts=-1, phase=0)
    assert second.requested_delta_codes == 4

    zero = _controller()
    assert zero.decide(_observation(zero, 0, 0, 600, counts=0, phase=0)).reason == "zero_containing_interval"

    outside = _controller()
    outside_decision = outside.decide(
        _observation(outside, 0, 0, 600, counts=2, phase=0, tight_state="OUTSIDE")
    )
    assert outside_decision.reason == "outside_tight_legacy_request_ready"
    assert outside_decision.requested_delta_codes == -10
    assert outside.request_pending is True

    nonmaterial = _controller()
    assert nonmaterial.decide(_observation(nonmaterial, 0, 0, 600, counts=-1, phase=-5)).reason == "persistence_first_interval_hold"
    material = _controller()
    assert material.decide(
        _observation(material, 0, 0, 600, counts=-1, phase=-6)
    ).reason == "phase_material_legacy_request_ready"


def test_shared_endpoint_persistence_overlap_gap_and_hold_debt_lifecycle() -> None:
    controller = _controller()
    first = controller.decide(_observation(controller, 0, 0, 600))
    contiguous = controller.decide(_observation(controller, 600, 600, 1200))
    assert first.persistence_count == 1
    assert contiguous.requested_delta_codes == 5
    controller.reject_or_expire_request()

    controller.debt = CX323Debt(10, 20)
    overlap = controller.decide(_observation(controller, 1200, 599, 1199))
    assert overlap.reason == "source_overlap_hold"
    assert controller.debt == CX323Debt(10, 20)
    gap = controller.decide(_observation(controller, 1800, 1201, 1801))
    assert gap.reason == "source_gap_persistence_restart"
    assert gap.persistence_count == 1
    assert controller.debt == CX323Debt(10, 20)

    settled = controller.decide(_observation(controller, 2400, 1801, 2401, settled=False))
    authority = controller.decide(_observation(controller, 3000, 2401, 3001, authority_valid=False))
    assert settled.reason == "settling_hold"
    assert authority.reason == "reference_invalidity_or_authority_hold"
    assert controller.debt == CX323Debt(10, 20)


def test_picocode_debt_application_response_metadata_and_phase_loss() -> None:
    controller = _controller()
    _, request = _persistent(controller, counts=-1, phase=-4)
    assert request.requested_delta_codes == 5
    assert request.raw_combined_picocodes == 5_341_671_780_415
    controller.confirm_application(request, applied_code=43090, dac_epoch=2, first_consumer_exact=True)
    assert controller.debt.total_picocodes == 341_671_780_415
    assert controller.debt.fll_picocodes + controller.debt.pll_picocodes == controller.debt.total_picocodes
    assert controller.response_pending is True
    controller.complete_response(fresh_exact=True)
    assert controller.response_pending is False

    controller.enter_metadata_hold()
    assert controller.decide(_observation(controller, 1200, 1200, 1800)).reason == "metadata_hold"
    frozen = controller.debt
    controller.requalify_metadata(1800)
    first = controller.decide(_observation(controller, 1800, 1800, 2400))
    second = controller.decide(_observation(controller, 2400, 2400, 3000))
    assert first.reason == "metadata_requalification_window_hold"
    assert first.persistence_count == 1
    assert controller.metadata_hold is False
    assert controller.requalification_window_count == 2
    assert second.requested_delta_codes != 0
    assert controller.debt == frozen

    controller.reject_or_expire_request()
    controller.debt = CX323Debt(101, 202)
    phase_loss = controller.decide(
        _observation(controller, 3600, 3000, 3600, phase_valid=False)
    )
    assert phase_loss.reason == "phase_degraded_frequency_only_request_ready"
    assert phase_loss.requested_delta_codes == 5
    assert controller.debt == CX323Debt(101, 0)
    controller.confirm_application(
        phase_loss,
        applied_code=controller.applied_code + 5,
        dac_epoch=controller.dac_epoch + 1,
        first_consumer_exact=True,
    )
    assert controller.debt == CX323Debt()


def test_rejection_is_not_incomplete_application_and_limits_hold() -> None:
    controller = _controller()
    _, request = _persistent(controller, counts=-1, phase=-4)
    with pytest.raises(HybridPolicyError, match="application_without_exact_first_consumer"):
        controller.confirm_application(request, applied_code=43090, dac_epoch=2, first_consumer_exact=False)
    assert controller.fail_static_reason == "application_without_exact_first_consumer"

    limited = _controller()
    limited.application_count = limited.policy.maximum_applications
    _, count_hold = _persistent(limited, counts=-1, phase=-4)
    assert count_hold.reason == "global_application_budget_hold"
    movement = _controller()
    movement.cumulative_movement_codes = movement.policy.maximum_cumulative_movement_codes
    _, movement_hold = _persistent(movement, counts=-1, phase=-4)
    assert movement_hold.requested_delta_codes == 0
    assert movement_hold.safe_cap_codes == 0

    cap = _controller()
    _, capped = _persistent(cap, counts=1, phase=0)
    assert capped.safe_cap_codes == 4
    assert capped.requested_delta_codes == -4


def test_phase_epoch_and_new_activation_reset_the_required_debt_tags() -> None:
    controller = _controller()
    controller.debt = CX323Debt(111, 222)
    first = controller.decide(_observation(controller, 0, 0, 600))
    epoch = controller.decide(
        _observation(controller, 600, 600, 1200, phase_epoch=2)
    )
    assert first.persistence_count == 1
    assert epoch.reason == "persistence_first_interval_hold"
    assert controller.debt == CX323Debt(111, 0)
    controller.new_policy_activation()
    assert controller.debt == CX323Debt()


def test_legacy_paths_execute_complete_transaction_and_reset_maintenance_debt() -> None:
    controller = _controller()
    controller.debt = CX323Debt(123, 456)
    decision = controller.decide(
        _observation(
            controller, 0, 1000, 1600, counts=2, phase=0, tight_state="OUTSIDE"
        )
    )
    assert decision.reason == "outside_tight_legacy_request_ready"
    assert decision.maintenance_request is False
    assert decision.requested_delta_codes == -10
    assert controller.debt == CX323Debt()
    controller.confirm_application(
        decision,
        applied_code=decision.requested_code,
        dac_epoch=2,
        first_consumer_exact=True,
    )
    assert controller.response_pending is True
    assert controller.debt == CX323Debt()
    assert controller.decide(
        _observation(controller, 600, 1600, 2200, tight_state="OUTSIDE")
    ).reason == "response_pending_hold"
    controller.complete_response(fresh_exact=True)
    assert controller.response_pending is False


def test_legacy_gates_are_range_aware_and_preserve_cx322_safety_limits() -> None:
    at_range = CX323PhasePriorityController(
        load_cx323_policy(), setup_applied_code=0xAB00, setup_dac_epoch=7
    )
    range_decision = at_range.decide(
        _observation(at_range, 0, 0, 600, counts=-1, phase=-36)
    )
    # Both legacy alternatives clamp to the same range endpoint, so the phase
    # term is not materially influential after the final request is formed.
    assert range_decision.reason == "persistence_first_interval_hold"
    assert at_range.dac_epoch == 7

    cadence = _controller()
    cadence.last_application_s = 0
    cadence.last_application_ticks = 0
    assert cadence.decide(
        _observation(cadence, 1, 0, 600, counts=2, phase=0, tight_state="OUTSIDE")
    ).reason == "cadence_hold"

    count_limited = _controller()
    count_limited.application_count = count_limited.policy.maximum_applications
    assert count_limited.decide(
        _observation(count_limited, 0, 0, 600, counts=2, phase=0, tight_state="OUTSIDE")
    ).reason == "global_application_budget_hold"

    movement_limited = _controller()
    movement_limited.cumulative_movement_codes = (
        movement_limited.policy.maximum_cumulative_movement_codes - 1
    )
    assert movement_limited.decide(
        _observation(movement_limited, 0, 0, 600, counts=2, phase=0, tight_state="OUTSIDE")
    ).reason == "global_cumulative_movement_budget_hold"

    direction = _controller()
    assert direction.decide(
        _observation(direction, 0, 0, 600, counts=-1, phase=6)
    ).reason == "phase_direction_coherence_hold"

    alternating = _controller()
    alternating.direction_history = [1, -1, 1]
    assert alternating.decide(
        _observation(alternating, 0, 0, 600, counts=2, phase=0, tight_state="OUTSIDE")
    ).reason == "prospective_repeated_alternation"
    assert alternating.fail_static_reason == "prospective_repeated_alternation"

    inefficient = _controller()
    inefficient.cumulative_movement_codes = 41
    inefficient.chatter_origin_code = inefficient.applied_code + 10
    assert inefficient.decide(
        _observation(inefficient, 0, 0, 600, counts=-2, phase=0, tight_state="OUTSIDE")
    ).reason == "prospective_low_efficiency_path"


def test_gap_with_zero_or_opposite_sign_resets_tagged_debt() -> None:
    zero_gap = _controller()
    zero_gap.decide(_observation(zero_gap, 0, 0, 600, counts=-1, phase=0))
    zero_gap.debt = CX323Debt(17, 19)
    decision = zero_gap.decide(_observation(zero_gap, 600, 601, 1201, counts=0, phase=0))
    assert decision.reason == "source_gap_persistence_restart"
    assert zero_gap.debt == CX323Debt()

    opposite_gap = _controller()
    opposite_gap.decide(_observation(opposite_gap, 0, 0, 600, counts=-1, phase=0))
    opposite_gap.debt = CX323Debt(23, 29)
    decision = opposite_gap.decide(
        _observation(opposite_gap, 600, 601, 1201, counts=1, phase=0)
    )
    assert decision.reason == "source_gap_persistence_restart"
    assert opposite_gap.debt == CX323Debt()


def test_application_cadence_uses_the_originating_request_timestamp() -> None:
    controller = _controller()
    first = controller.decide(_observation(controller, 0, 0, 600))
    assert first.reason == "persistence_first_interval_hold"
    request = controller.decide(_observation(controller, 600, 600, 1200))
    assert request.requested_delta_codes != 0

    pending = controller.decide(_observation(controller, 601, 1200, 1800))
    assert pending.reason == "request_pending_hold"
    controller.confirm_application(
        request,
        applied_code=request.requested_code,
        dac_epoch=2,
        first_consumer_exact=True,
    )

    assert controller.last_application_s == 600
