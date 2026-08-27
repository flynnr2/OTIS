from __future__ import annotations

from dataclasses import replace
from fractions import Fraction
import math

import pytest

from host.otis_tools.adaptive_steering_offline import (
    CanonicalControlState,
    ContinuityRequest,
    CounterRule,
    DebtEvent,
    DebtLimits,
    DebtMode,
    DebtProvenance,
    DemandIntervalObservation,
    EfficiencyMode,
    EfficiencyState,
    InsufficientDeviationSupport,
    IntervalSign,
    OutstandingDebtTransitionError,
    PersistenceIdentity,
    PersistenceMode,
    RationalInterval,
    RequestReleaseState,
    advance_persistence,
    combined_correction_demand_interval,
    contain_optional_evidence_fault,
    commit_debt_application,
    complete_debt_response,
    discard_pll_correction_debt,
    enter_correction_debt_hold,
    evaluate_correction_debt,
    freeze_correction_debt,
    freeze_persistence,
    hold_persistence,
    initial_correction_debt,
    initial_persistence,
    mark_debt_proposal_accepted,
    metadata_loss_disposition,
    overlapping_allan_deviation,
    overlapping_hadamard_deviation,
    pool_deviation_estimates,
    requalify_correction_debt,
    requalify_persistence,
    record_low_efficiency,
    reset_correction_debt,
    reset_persistence,
    resume_frozen_persistence,
    resolve_unaccepted_debt_proposal,
    round_half_away_from_zero,
    segment_continuity,
    suppress_correction_debt,
)


@pytest.mark.parametrize(
    ("state", "action"),
    [
        (
            RequestReleaseState.UNUSED_ARM,
            "withdraw_unused_arm_then_enter_metadata_hold",
        ),
        (
            RequestReleaseState.PRIVATE_UNRELEASED,
            "private_unreleased_withdrawn_then_enter_metadata_hold",
        ),
    ],
)
def test_metadata_loss_withdraws_only_core1_owned_request_state(
    state: RequestReleaseState, action: str
) -> None:
    transition = metadata_loss_disposition(state)

    assert transition.next_state is RequestReleaseState.OUTCOME_RESOLVED
    assert transition.action == action
    assert transition.outcome_owner == "core1"
    assert transition.core1_may_mutate_request
    assert transition.enter_hold_now
    assert not transition.fail_static


def test_metadata_loss_preserves_released_request_for_core0_resolution() -> None:
    pending = metadata_loss_disposition(RequestReleaseState.RELEASED_PENDING)

    assert pending.next_state is RequestReleaseState.RELEASED_PENDING
    assert pending.outcome_owner == "core0"
    assert not pending.core1_may_mutate_request
    assert not pending.enter_hold_now
    assert pending.hold_after_resolution

    for outcome in ("rejected", "expired"):
        resolved = metadata_loss_disposition(
            RequestReleaseState.RELEASED_PENDING,
            authoritative_outcome=outcome,
        )
        assert resolved.next_state is RequestReleaseState.OUTCOME_RESOLVED
        assert resolved.action == f"record_exact_{outcome}_then_enter_metadata_hold"
        assert resolved.enter_hold_now
        assert not resolved.core1_may_mutate_request


def test_metadata_loss_acceptance_and_response_complete_before_hold() -> None:
    accepted = metadata_loss_disposition(
        RequestReleaseState.RELEASED_PENDING,
        authoritative_outcome="accepted",
    )
    assert accepted.next_state is RequestReleaseState.RELEASE_ACCEPTED
    assert accepted.preserve_d14_d8_response
    assert accepted.hold_after_resolution
    assert not accepted.enter_hold_now
    assert "first_consumer" in accepted.action

    response = metadata_loss_disposition(RequestReleaseState.RESPONSE_PENDING)
    assert response.preserve_d14_d8_response
    assert response.hold_after_resolution
    assert "inhibit_rearm" in response.action


def test_metadata_loss_never_infers_unknown_released_outcome() -> None:
    ambiguous = metadata_loss_disposition(
        RequestReleaseState.RELEASED_PENDING,
        authoritative_outcome="silence_interpreted_as_unchanged",
    )

    assert ambiguous.next_state is RequestReleaseState.FAIL_STATIC
    assert ambiguous.fail_static
    assert not ambiguous.core1_may_mutate_request


def test_low_efficiency_falls_back_from_phase_then_inhibits_repeated_fll() -> None:
    fallback = record_low_efficiency(
        EfficiencyState(), phase_materially_influenced=True
    )
    assert fallback.state.mode is EfficiencyMode.FLL_ONLY
    assert fallback.action == "discard_pll_debt_and_fallback_to_fll"
    assert fallback.measurement_continues

    first_fll = record_low_efficiency(
        fallback.state, phase_materially_influenced=False
    )
    assert first_fll.state.mode is EfficiencyMode.FLL_ONLY
    assert first_fll.state.fll_local_low_efficiency_count == 1

    repeated_fll = record_low_efficiency(
        first_fll.state, phase_materially_influenced=False
    )
    assert repeated_fll.state.mode is EfficiencyMode.STATIC_INHIBIT
    assert repeated_fll.action == (
        "inhibit_automatic_actuation_retain_last_confirmed_code"
    )
    assert repeated_fll.measurement_continues


@pytest.mark.parametrize("fault", ["killed", "stalled", "corrupt", "rejected"])
def test_shadow_fault_is_zero_authority_and_canonical_state_invariant(
    fault: str,
) -> None:
    canonical = CanonicalControlState("canonical-digest", True, "active")
    disposition = contain_optional_evidence_fault(
        canonical, component="shadow", fault=fault
    )

    assert disposition.canonical == canonical
    assert disposition.component_failed
    assert not disposition.backpressure_permitted
    assert not disposition.canonical_mutation_permitted
    assert not disposition.terminal_permitted


@pytest.mark.parametrize(
    "fault", ["absent", "noise", "invalid", "overflow", "queue_failure"]
)
def test_d10_fault_is_local_and_d14_d8_control_state_invariant(fault: str) -> None:
    canonical = CanonicalControlState("canonical-digest", True, "eligible")
    disposition = contain_optional_evidence_fault(
        canonical, component="d10", fault=fault
    )

    assert disposition.canonical == canonical
    assert disposition.canonical.d14_d8_measurement_healthy
    assert disposition.canonical.control_authority_state == "eligible"
    assert not disposition.canonical_mutation_permitted
    assert not disposition.terminal_permitted


def test_continuity_segmenter_honors_only_requested_keys_and_reports_breaks() -> None:
    records = [
        {"session": "a", "seq": 10, "valid": True, "ignored": 1},
        {"session": "a", "seq": 11, "valid": True, "ignored": 999},
        {"session": "b", "seq": 12, "valid": True},
        {"session": "b", "seq": 14, "valid": True},
        {"session": "b", "seq": 15, "valid": False},
        {"session": "b", "seq": 16, "valid": True},
        {
            "session": "b",
            "seq": 17,
            "valid": True,
            "declared_break": "boot",
        },
    ]
    result = segment_continuity(
        records,
        ContinuityRequest(
            identity_keys=("session",),
            consecutive_keys=("seq",),
            valid_keys=("valid",),
            explicit_break_key="declared_break",
        ),
    )

    assert [segment.record_indices for segment in result.segments] == [
        (0, 1),
        (2,),
        (3,),
        (5,),
        (6,),
    ]
    assert result.excluded_record_indices == (4,)
    assert [(item.record_index, item.reasons, item.record_excluded) for item in result.breaks] == [
        (2, ("identity_changed:session",), False),
        (3, ("nonconsecutive:seq",), False),
        (4, ("invalid_flag:valid",), True),
        (6, ("explicit_break:boot",), False),
    ]


def test_continuity_counter_wrap_is_contract_driven_and_large_delta_breaks() -> None:
    records = [{"tick": value} for value in (14, 15, 0, 8, 9)]
    result = segment_continuity(
        records,
        ContinuityRequest(
            counter_rules=(CounterRule("tick", modulus=16, maximum_forward_delta=2),)
        ),
    )

    assert [segment.record_indices for segment in result.segments] == [(0, 1, 2), (3, 4)]
    assert result.breaks[0].reasons == ("counter_gap:tick",)

    nonwrapping = segment_continuity(
        [{"tick": 3}, {"tick": 2}],
        ContinuityRequest(counter_rules=(CounterRule("tick"),)),
    )
    assert nonwrapping.breaks[0].reasons == ("illegal_backward_movement:tick",)


def test_continuity_missing_or_malformed_requested_key_is_excluded() -> None:
    result = segment_continuity(
        [{"seq": 1}, {"seq": "2"}, {}, {"seq": 4}],
        ContinuityRequest(consecutive_keys=("seq",)),
    )

    assert [segment.record_indices for segment in result.segments] == [(0,), (3,)]
    assert result.excluded_record_indices == (1, 2)
    assert result.breaks[0].reasons == ("invalid_integer:seq",)
    assert result.breaks[1].reasons == ("missing_key:seq",)


def test_overlapping_deviation_analytic_constant_linear_and_quadratic_fixtures() -> None:
    constant = [Fraction(7, 10**9)] * 12
    assert overlapping_allan_deviation(
        constant, averaging_factor=2
    ).variance == 0
    assert overlapping_hadamard_deviation(
        constant, averaging_factor=2
    ).variance == 0

    linear_frequency = list(range(12))
    allan = overlapping_allan_deviation(linear_frequency, averaging_factor=2)
    hadamard = overlapping_hadamard_deviation(
        linear_frequency, averaging_factor=2
    )
    assert allan.term_count == 9  # N - 2m + 1
    assert allan.squared_difference_sum == 9 * 4
    assert allan.variance == 2
    assert allan.deviation == pytest.approx(math.sqrt(2))
    assert hadamard.term_count == 7  # N - 3m + 1
    assert hadamard.variance == 0

    quadratic_frequency = [index * index for index in range(10)]
    quadratic_hadamard = overlapping_hadamard_deviation(
        quadratic_frequency, averaging_factor=2
    )
    assert quadratic_hadamard.term_count == 5
    assert quadratic_hadamard.squared_difference_sum == 5 * 64
    assert quadratic_hadamard.variance == Fraction(32, 3)
    assert quadratic_hadamard.deviation == pytest.approx(math.sqrt(32 / 3))


def test_deviation_pooling_weights_exact_terms_without_stitching_segments() -> None:
    first = overlapping_allan_deviation(range(6), averaging_factor=1)
    second = overlapping_allan_deviation(range(100, 107), averaging_factor=1)
    pooled = pool_deviation_estimates((first, second))

    assert first.term_count == 5
    assert second.term_count == 6
    assert pooled.term_count == 11
    assert pooled.population_count == 2
    assert pooled.squared_difference_sum == 11
    assert pooled.variance == Fraction(1, 2)
    # A stitched 13-sample population would have 12 terms, including the gap.
    assert pooled.term_count != pooled.sample_count - 1


def test_deviation_requires_declared_support_and_exact_inputs() -> None:
    with pytest.raises(InsufficientDeviationSupport) as exc_info:
        overlapping_hadamard_deviation(
            range(6), averaging_factor=2, minimum_term_count=2
        )
    assert exc_info.value.term_count == 1

    with pytest.raises(TypeError, match="exact"):
        overlapping_allan_deviation([0.0, 1.0], averaging_factor=1)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (Fraction(0), 0),
        (Fraction(49, 100), 0),
        (Fraction(1, 2), 1),
        (Fraction(3, 2), 2),
        (Fraction(-49, 100), 0),
        (Fraction(-1, 2), -1),
        (Fraction(-3, 2), -2),
    ],
)
def test_exact_rational_rounding_is_half_away_from_zero(
    value: Fraction, expected: int
) -> None:
    assert round_half_away_from_zero(value) == expected


def test_combined_demand_sign_has_no_sign_when_interval_contains_zero() -> None:
    combined = combined_correction_demand_interval(
        RationalInterval(1, 2),
        RationalInterval(-2, -1),
        positive_plant_gain=RationalInterval(1, 2),
    )
    assert combined == RationalInterval(-1, 1)
    assert combined.sign is IntervalSign.CONTAINS_ZERO
    assert RationalInterval(0, 1).sign is IntervalSign.CONTAINS_ZERO
    assert RationalInterval(-1, 0).sign is IntervalSign.CONTAINS_ZERO

    positive = combined_correction_demand_interval(
        RationalInterval(2, 3),
        RationalInterval(-1, Fraction(-1, 2)),
    )
    negative = combined_correction_demand_interval(
        RationalInterval(-3, -2), RationalInterval(0, 1)
    )
    assert positive.sign is IntervalSign.POSITIVE
    assert negative.sign is IntervalSign.NEGATIVE


def _provenance(
    *,
    evidence_frontier: int = 0,
    applied_code: int = 100,
    dac_epoch: int = 1,
    capture_session: str = "session-a",
    phase_epoch: str | None = "phase-a",
    phase_frontier: int | None = 0,
) -> DebtProvenance:
    return DebtProvenance(
        policy_id="policy-a",
        plant_gain_id="gain-a",
        capture_session=capture_session,
        estimator_id="selected-600-a",
        evidence_frontier=evidence_frontier,
        applied_code=applied_code,
        dac_epoch=dac_epoch,
        phase_epoch=phase_epoch,
        phase_frontier=phase_frontier,
    )


LIMITS = DebtLimits(
    minimum_code=90,
    maximum_code=110,
    maximum_step_codes=2,
    maximum_abs_committed_debt_codes=Fraction(1, 2),
)


def _evaluate(
    state,
    *,
    frontier: int,
    fll: Fraction,
    pll: Fraction = Fraction(0),
    request_id: str = "request-1",
):
    return evaluate_correction_debt(
        state,
        provenance=_provenance(
            evidence_frontier=frontier, phase_frontier=frontier
        ),
        decision_id=f"decision-{frontier}",
        request_id=request_id,
        raw_fll_increment_codes=fll,
        raw_pll_increment_codes=pll,
        limits=LIMITS,
    )


def test_zero_request_commits_bounded_tagged_debt_without_transaction() -> None:
    state = initial_correction_debt(_provenance())
    transition = _evaluate(
        state, frontier=1, fll=Fraction(1, 4), pll=Fraction(1, 8)
    )

    assert transition.event is DebtEvent.DEBT_UPDATED_WITHOUT_REQUEST
    assert transition.state.pending is None
    assert transition.state.committed.fll_codes == Fraction(1, 4)
    assert transition.state.committed.pll_codes == Fraction(1, 8)
    assert transition.state.committed.total_codes == Fraction(3, 8)
    assert transition.state.committed.provenance.evidence_frontier == 1


def test_pending_proposal_is_immutable_until_exact_application_commit() -> None:
    initial = initial_correction_debt(_provenance())
    zero = _evaluate(
        initial, frontier=1, fll=Fraction(1, 4), pll=Fraction(1, 8)
    ).state
    proposed = _evaluate(zero, frontier=2, fll=Fraction(1, 2))

    assert proposed.event is DebtEvent.REQUEST_PROPOSED
    assert proposed.state.committed == zero.committed
    assert proposed.proposal is proposed.state.pending
    assert proposed.proposal is not None
    assert proposed.proposal.limited_total_codes == Fraction(7, 8)
    assert proposed.proposal.integer_request_delta_codes == 1

    suppressed = _evaluate(proposed.state, frontier=3, fll=Fraction(5))
    assert suppressed.event is DebtEvent.SUPPRESSED
    assert suppressed.reason == "transaction_outstanding"
    assert suppressed.state == proposed.state

    accepted = mark_debt_proposal_accepted(proposed.state, "request-1")
    committed = commit_debt_application(
        accepted.state,
        request_id="request-1",
        actual_applied_code=101,
        actual_dac_epoch=2,
        first_consumer_frontier=3,
    )
    assert committed.event is DebtEvent.APPLICATION_COMMITTED
    assert committed.state.pending is None
    assert committed.state.response_pending_request_id == "request-1"
    assert committed.state.committed.total_codes == Fraction(-1, 8)
    assert committed.state.committed.fll_codes == Fraction(-3, 28)
    assert committed.state.committed.pll_codes == Fraction(-1, 56)
    assert not committed.state.actionable

    during_response = evaluate_correction_debt(
        committed.state,
        provenance=_provenance(
            evidence_frontier=4,
            applied_code=101,
            dac_epoch=2,
            phase_frontier=4,
        ),
        decision_id="decision-4",
        request_id="request-2",
        raw_fll_increment_codes=1,
        raw_pll_increment_codes=0,
        limits=LIMITS,
    )
    assert during_response.reason == "response_outstanding"
    assert during_response.state == committed.state

    completed = complete_debt_response(
        committed.state, request_id="request-1", response_frontier=4
    )
    assert completed.event is DebtEvent.RESPONSE_COMPLETED
    assert completed.state.response_pending_request_id is None
    assert completed.state.actionable


@pytest.mark.parametrize("outcome", ["rejected", "expired"])
def test_rejection_or_expiry_discards_pending_and_preserves_committed(
    outcome: str,
) -> None:
    initial = initial_correction_debt(_provenance())
    proposed = _evaluate(initial, frontier=1, fll=Fraction(3, 4)).state
    resolved = resolve_unaccepted_debt_proposal(
        proposed, request_id="request-1", outcome=outcome
    )

    assert resolved.event.value == f"proposal_{outcome}"
    assert resolved.state.pending is None
    assert resolved.state.committed == initial.committed


def test_acceptance_wins_and_cannot_be_rejected_or_expired() -> None:
    proposed = _evaluate(
        initial_correction_debt(_provenance()),
        frontier=1,
        fll=Fraction(3, 4),
    ).state
    accepted = mark_debt_proposal_accepted(proposed, "request-1").state
    invalid = resolve_unaccepted_debt_proposal(
        accepted, request_id="request-1", outcome="expired"
    )

    assert invalid.event is DebtEvent.IDENTITY_FAULT
    assert invalid.state.mode is DebtMode.IDENTITY_FAULT
    assert invalid.state.pending == accepted.pending


def test_full_raw_demand_is_limited_only_by_step_and_range_before_rounding() -> None:
    state = initial_correction_debt(_provenance())
    step_limited = _evaluate(state, frontier=1, fll=10)
    assert step_limited.proposal is not None
    assert step_limited.proposal.candidate_fll_codes == 10
    assert step_limited.proposal.limited_total_codes == 2
    assert step_limited.proposal.integer_request_delta_codes == 2
    assert step_limited.limit_reasons == ("step_backcalculated",)

    cx322_sized = evaluate_correction_debt(
        state,
        provenance=_provenance(evidence_frontier=1, phase_frontier=1),
        decision_id="decision-full-demand",
        request_id="request-full-demand",
        raw_fll_increment_codes=Fraction(-6009, 1000),
        raw_pll_increment_codes=0,
        limits=DebtLimits(
            minimum_code=0,
            maximum_code=65535,
            maximum_step_codes=21,
            maximum_abs_committed_debt_codes=Fraction(1, 2),
        ),
    )
    assert cx322_sized.proposal is not None
    assert cx322_sized.proposal.limited_total_codes == Fraction(-6009, 1000)
    assert cx322_sized.proposal.integer_request_delta_codes == -6
    assert cx322_sized.limit_reasons == ()

    near_endpoint = initial_correction_debt(
        _provenance(applied_code=109)
    )
    ranged = evaluate_correction_debt(
        near_endpoint,
        provenance=_provenance(
            evidence_frontier=1,
            applied_code=109,
            phase_frontier=1,
        ),
        decision_id="decision-range",
        request_id="request-range",
        raw_fll_increment_codes=4,
        raw_pll_increment_codes=0,
        limits=LIMITS,
    )
    assert ranged.proposal is not None
    assert ranged.proposal.limited_total_codes == 1
    assert ranged.proposal.requested_code == 110
    assert "range_backcalculated" in ranged.limit_reasons

    applied = mark_debt_proposal_accepted(
        ranged.state, "request-range"
    ).state
    applied = commit_debt_application(
        applied,
        request_id="request-range",
        actual_applied_code=110,
        actual_dac_epoch=2,
        first_consumer_frontier=2,
    )
    assert applied.state.committed.total_codes == 0


def test_residual_debt_cap_applies_only_at_commit_boundaries() -> None:
    tight_cap = DebtLimits(
        minimum_code=90,
        maximum_code=110,
        maximum_step_codes=2,
        maximum_abs_committed_debt_codes=Fraction(1, 4),
    )
    state = initial_correction_debt(_provenance())
    zero = evaluate_correction_debt(
        state,
        provenance=_provenance(evidence_frontier=1, phase_frontier=1),
        decision_id="decision-zero-cap",
        request_id="request-zero-cap",
        raw_fll_increment_codes=Fraction(2, 5),
        raw_pll_increment_codes=0,
        limits=tight_cap,
    )
    assert zero.event is DebtEvent.DEBT_UPDATED_WITHOUT_REQUEST
    assert zero.state.committed.total_codes == Fraction(1, 4)
    assert zero.limit_reasons == ("committed_residual_debt_capped",)

    proposal = evaluate_correction_debt(
        initial_correction_debt(_provenance()),
        provenance=_provenance(evidence_frontier=1, phase_frontier=1),
        decision_id="decision-application-cap",
        request_id="request-application-cap",
        raw_fll_increment_codes=Fraction(3, 5),
        raw_pll_increment_codes=0,
        limits=tight_cap,
    )
    assert proposal.proposal is not None
    assert proposal.proposal.limited_total_codes == Fraction(3, 5)
    accepted = mark_debt_proposal_accepted(
        proposal.state, "request-application-cap"
    ).state
    applied = commit_debt_application(
        accepted,
        request_id="request-application-cap",
        actual_applied_code=101,
        actual_dac_epoch=2,
        first_consumer_frontier=2,
    )
    assert applied.state.committed.total_codes == Fraction(-1, 4)
    assert applied.limit_reasons == ("committed_residual_debt_capped",)


def test_opposing_components_do_not_leave_hidden_cancellation_debt() -> None:
    state = initial_correction_debt(_provenance())
    transition = _evaluate(
        state,
        frontier=1,
        fll=10,
        pll=Fraction(-48, 5),
    )
    assert transition.event is DebtEvent.DEBT_UPDATED_WITHOUT_REQUEST
    assert transition.state.committed.total_codes == Fraction(2, 5)
    assert transition.state.committed.fll_codes == Fraction(2, 5)
    assert transition.state.committed.pll_codes == 0


def test_hard_endpoint_removes_outward_component_but_retains_inward_component() -> None:
    state = initial_correction_debt(_provenance(applied_code=110))
    transition = evaluate_correction_debt(
        state,
        provenance=_provenance(
            evidence_frontier=1,
            applied_code=110,
            phase_frontier=1,
        ),
        decision_id="decision-endpoint",
        request_id="request-endpoint",
        raw_fll_increment_codes=2,
        raw_pll_increment_codes=Fraction(-3, 4),
        limits=LIMITS,
    )

    assert transition.proposal is not None
    assert transition.proposal.limited_fll_codes == 0
    assert transition.proposal.limited_pll_codes == Fraction(-3, 4)
    assert transition.proposal.integer_request_delta_codes == -1
    assert "upper_endpoint_fll_backcalculated" in transition.limit_reasons

    outward_only = evaluate_correction_debt(
        state,
        provenance=_provenance(
            evidence_frontier=1,
            applied_code=110,
            phase_frontier=1,
        ),
        decision_id="decision-outward",
        request_id="request-outward",
        raw_fll_increment_codes=Fraction(1, 4),
        raw_pll_increment_codes=0,
        limits=LIMITS,
    )
    assert outward_only.event is DebtEvent.DEBT_UPDATED_WITHOUT_REQUEST
    assert outward_only.state.committed.total_codes == 0
    assert outward_only.limit_reasons == ("upper_endpoint_fll_backcalculated",)


def test_suppression_hold_requalification_freeze_and_identity_fault_preserve_debt() -> None:
    state = _evaluate(
        initial_correction_debt(_provenance()),
        frontier=1,
        fll=Fraction(1, 4),
    ).state
    suppressed = suppress_correction_debt(state, "cadence_blocked")
    assert suppressed.state == state

    held = enter_correction_debt_hold(state, "gnss_metadata_hold")
    assert held.state.mode is DebtMode.HOLD
    assert held.state.committed == state.committed
    no_accrual = _evaluate(held.state, frontier=2, fll=1)
    assert no_accrual.reason == "mode:hold:gnss_metadata_hold"
    assert no_accrual.state == held.state

    stale = requalify_correction_debt(
        held.state, fresh_observation=_provenance(evidence_frontier=1, phase_frontier=1)
    )
    assert stale.reason == "requalification_not_fresh"
    resumed = requalify_correction_debt(
        held.state, fresh_observation=_provenance(evidence_frontier=2, phase_frontier=2)
    )
    assert resumed.event is DebtEvent.REQUALIFIED
    assert resumed.state.actionable
    assert resumed.state.committed == state.committed

    frozen = freeze_correction_debt(resumed.state, "finite_authority_exhausted")
    assert frozen.state.mode is DebtMode.FROZEN
    assert frozen.state.committed == state.committed

    contradicted = evaluate_correction_debt(
        resumed.state,
        provenance=_provenance(
            evidence_frontier=3,
            applied_code=101,
            phase_frontier=3,
        ),
        decision_id="decision-bad",
        request_id="request-bad",
        raw_fll_increment_codes=1,
        raw_pll_increment_codes=0,
        limits=LIMITS,
    )
    assert contradicted.event is DebtEvent.IDENTITY_FAULT
    assert contradicted.state.mode is DebtMode.IDENTITY_FAULT
    assert contradicted.state.committed == state.committed
    cannot_downgrade = enter_correction_debt_hold(
        contradicted.state, "metadata_loss_after_fault"
    )
    assert cannot_downgrade.state == contradicted.state
    assert cannot_downgrade.state.mode is DebtMode.IDENTITY_FAULT


def test_hold_during_transaction_retains_owner_resolution_and_response() -> None:
    state = initial_correction_debt(_provenance())
    proposed = _evaluate(state, frontier=1, fll=Fraction(3, 4)).state
    held_pending = enter_correction_debt_hold(proposed, "metadata_lost").state
    assert held_pending.mode is DebtMode.HOLD
    assert held_pending.pending == proposed.pending

    rejected = resolve_unaccepted_debt_proposal(
        held_pending, request_id="request-1", outcome="rejected"
    ).state
    assert rejected.mode is DebtMode.HOLD
    assert rejected.pending is None
    assert rejected.committed == state.committed

    proposed = _evaluate(state, frontier=1, fll=Fraction(3, 4)).state
    accepted = mark_debt_proposal_accepted(proposed, "request-1").state
    held_accepted = enter_correction_debt_hold(accepted, "metadata_lost").state
    applied = commit_debt_application(
        held_accepted,
        request_id="request-1",
        actual_applied_code=101,
        actual_dac_epoch=2,
        first_consumer_frontier=2,
    ).state
    assert applied.mode is DebtMode.HOLD
    assert applied.response_pending_request_id == "request-1"
    with pytest.raises(OutstandingDebtTransitionError):
        requalify_correction_debt(
            applied,
            fresh_observation=_provenance(
                evidence_frontier=3,
                applied_code=101,
                dac_epoch=2,
                phase_frontier=3,
            ),
        )

    completed = complete_debt_response(
        applied, request_id="request-1", response_frontier=3
    ).state
    assert completed.mode is DebtMode.HOLD
    resumed = requalify_correction_debt(
        completed,
        fresh_observation=_provenance(
            evidence_frontier=4,
            applied_code=101,
            dac_epoch=2,
            phase_frontier=4,
        ),
    )
    assert resumed.state.mode is DebtMode.ACTIVE


def test_phase_loss_discards_only_pll_debt_and_requires_transaction_resolution() -> None:
    state = _evaluate(
        initial_correction_debt(_provenance()),
        frontier=1,
        fll=Fraction(1, 4),
        pll=Fraction(1, 8),
    ).state
    fallback = discard_pll_correction_debt(state, "phase_evidence_lost")
    assert fallback.event is DebtEvent.PLL_DEBT_DISCARDED
    assert fallback.state.mode is DebtMode.FLL_FALLBACK
    assert fallback.state.committed.fll_codes == Fraction(1, 4)
    assert fallback.state.committed.pll_codes == 0
    assert fallback.state.committed.provenance.phase_epoch is None

    forbidden_pll = evaluate_correction_debt(
        fallback.state,
        provenance=replace(
            fallback.state.committed.provenance,
            evidence_frontier=2,
            phase_epoch="phase-new",
            phase_frontier=2,
        ),
        decision_id="decision-pll",
        request_id="request-pll",
        raw_fll_increment_codes=0,
        raw_pll_increment_codes=Fraction(1, 4),
        limits=LIMITS,
    )
    assert forbidden_pll.reason == "pll_increment_forbidden_in_fll_fallback"
    assert forbidden_pll.state == fallback.state

    pending = _evaluate(
        initial_correction_debt(_provenance()),
        frontier=1,
        fll=Fraction(3, 4),
    ).state
    with pytest.raises(OutstandingDebtTransitionError):
        discard_pll_correction_debt(pending, "phase_evidence_lost")


def test_phase_epoch_change_requires_explicit_discard_and_session_reset_is_explicit() -> None:
    state = _evaluate(
        initial_correction_debt(_provenance()),
        frontier=1,
        fll=0,
        pll=Fraction(1, 4),
    ).state
    changed_phase = evaluate_correction_debt(
        state,
        provenance=_provenance(
            evidence_frontier=2,
            phase_epoch="phase-b",
            phase_frontier=2,
        ),
        decision_id="decision-phase-b",
        request_id="request-phase-b",
        raw_fll_increment_codes=0,
        raw_pll_increment_codes=Fraction(1, 4),
        limits=LIMITS,
    )
    assert changed_phase.reason == "phase_epoch_changed_requires_pll_discard"
    assert changed_phase.state == state

    reset = reset_correction_debt(
        state,
        provenance=_provenance(
            capture_session="session-b",
            evidence_frontier=0,
            phase_epoch="phase-b",
            phase_frontier=0,
        ),
        reason="capture_session_reset",
    )
    assert reset.event is DebtEvent.DEBT_RESET
    assert reset.state.committed.total_codes == 0
    assert reset.state.committed.provenance.capture_session == "session-b"


def _persistence_identity(
    *,
    dac_epoch: int = 1,
    phase_state_id: str = "phase-a",
    capture_session: str = "session-a",
) -> PersistenceIdentity:
    return PersistenceIdentity(
        capture_session=capture_session,
        continuity_segment="segment-a",
        applied_code=100 + dac_epoch - 1,
        dac_epoch=dac_epoch,
        phase_state_id=phase_state_id,
    )


def _demand_observation(
    opening: int,
    closing: int,
    lower: Fraction,
    upper: Fraction,
    *,
    identity: PersistenceIdentity | None = None,
    qualified: bool = True,
    settled: bool = True,
    cadence_eligible: bool = True,
) -> DemandIntervalObservation:
    return DemandIntervalObservation(
        identity=identity or _persistence_identity(),
        opening_frontier=opening,
        closing_frontier=closing,
        combined_demand=RationalInterval(lower, upper),
        qualified=qualified,
        settled=settled,
        cadence_eligible=cadence_eligible,
    )


def test_same_sign_persistence_uses_fresh_contiguous_nonoverlapping_intervals() -> None:
    state = initial_persistence(3)
    first = advance_persistence(state, _demand_observation(0, 10, 1, 2))
    assert first.state.count == 1
    assert not first.state.satisfied

    overlap = advance_persistence(
        first.state, _demand_observation(5, 15, 1, 2)
    )
    assert overlap.reason == "overlapping_interval"
    assert overlap.state == first.state

    second = advance_persistence(
        first.state, _demand_observation(10, 20, 1, 3)
    )
    third = advance_persistence(
        second.state, _demand_observation(20, 30, Fraction(1, 10), 1)
    )
    assert second.state.count == 2
    assert third.state.count == 3
    assert third.state.satisfied
    assert third.reason == "persistence_satisfied"


@pytest.mark.parametrize(
    ("override", "reason"),
    [
        ({"qualified": False}, "interval_unqualified"),
        ({"settled": False}, "settling_incomplete"),
        ({"cadence_eligible": False}, "cadence_ineligible"),
    ],
)
def test_ineligible_interval_does_not_advance_persistence(
    override: dict[str, bool], reason: str
) -> None:
    state = advance_persistence(
        initial_persistence(3), _demand_observation(0, 10, 1, 2)
    ).state
    suppressed = advance_persistence(
        state, _demand_observation(10, 20, 1, 2, **override)
    )
    assert suppressed.reason == reason
    assert suppressed.state == state


def test_transaction_freeze_cannot_mutate_persistence() -> None:
    state = advance_persistence(
        initial_persistence(3), _demand_observation(0, 10, 1, 2)
    ).state
    frozen = freeze_persistence(state, "request_outstanding")
    attempted = advance_persistence(
        frozen.state, _demand_observation(10, 20, 1, 2)
    )
    assert attempted.reason == "persistence_frozen:request_outstanding"
    assert attempted.state == frozen.state

    resumed = resume_frozen_persistence(
        frozen.state, "authoritative_rejection_confirmed"
    )
    assert resumed.state.mode is PersistenceMode.ACTIVE
    assert resumed.state.count == 1


def test_zero_containing_opposite_sign_and_gap_reset_persistence() -> None:
    state = advance_persistence(
        initial_persistence(3), _demand_observation(0, 10, 1, 2)
    ).state
    state = advance_persistence(
        state, _demand_observation(10, 20, 1, 2)
    ).state

    zero = advance_persistence(state, _demand_observation(20, 30, -1, 1))
    assert zero.reason == "zero_containing_interval_reset"
    assert zero.state.count == 0
    assert zero.state.sign is None

    negative = advance_persistence(
        zero.state, _demand_observation(30, 40, -2, -1)
    )
    positive = advance_persistence(
        negative.state, _demand_observation(40, 50, 1, 2)
    )
    assert positive.reason == "demand_sign_changed_reset"
    assert positive.state.count == 1

    gap = advance_persistence(
        positive.state, _demand_observation(60, 70, 1, 2)
    )
    assert gap.reason == "noncontiguous_interval_reset"
    assert gap.state.count == 1


def test_persistence_freezes_through_hold_and_requires_complete_post_requalification() -> None:
    state = initial_persistence(3)
    state = advance_persistence(
        state, _demand_observation(0, 10, 1, 2)
    ).state
    state = advance_persistence(
        state, _demand_observation(10, 20, 1, 2)
    ).state
    held = hold_persistence(state, "gnss_metadata_hold")
    assert held.state.count == 2
    ignored = advance_persistence(
        held.state, _demand_observation(20, 30, 1, 2)
    )
    assert ignored.reason == "persistence_hold:gnss_metadata_hold"
    assert ignored.state == held.state

    awaiting = requalify_persistence(
        held.state, requalification_frontier=25
    ).state
    assert awaiting.mode is PersistenceMode.AWAITING_POST_REQUALIFICATION_OBSERVATION
    stale_support = advance_persistence(
        awaiting, _demand_observation(20, 30, 1, 2)
    )
    assert stale_support.reason == "observation_not_wholly_post_requalification"
    assert stale_support.state == awaiting

    fresh = advance_persistence(
        awaiting, _demand_observation(30, 40, 1, 2)
    )
    assert fresh.state.mode is PersistenceMode.ACTIVE
    assert fresh.state.count == 3
    assert fresh.state.satisfied


def test_dac_or_phase_epoch_change_resets_persistence_before_current_interval() -> None:
    state = advance_persistence(
        initial_persistence(3), _demand_observation(0, 10, 1, 2)
    ).state
    state = advance_persistence(
        state, _demand_observation(10, 20, 1, 2)
    ).state
    dac_reset = advance_persistence(
        state,
        _demand_observation(
            20, 30, 1, 2, identity=_persistence_identity(dac_epoch=2)
        ),
    )
    assert dac_reset.reason == "identity_epoch_reset"
    assert dac_reset.state.count == 1

    phase_reset = advance_persistence(
        dac_reset.state,
        _demand_observation(
            30,
            40,
            1,
            2,
            identity=_persistence_identity(
                dac_epoch=2, phase_state_id="phase-b"
            ),
        ),
    )
    assert phase_reset.reason == "identity_epoch_reset"
    assert phase_reset.state.count == 1

    session_reset = advance_persistence(
        phase_reset.state,
        _demand_observation(
            0,
            10,
            1,
            2,
            identity=_persistence_identity(
                capture_session="session-b", phase_state_id="phase-c"
            ),
        ),
    )
    assert session_reset.reason == "identity_epoch_reset"
    assert session_reset.state.count == 1

    explicit = reset_persistence(session_reset.state, "capture_session_reset")
    assert explicit.state.count == 0
    assert explicit.state.identity is None
    assert explicit.reason == "capture_session_reset"
