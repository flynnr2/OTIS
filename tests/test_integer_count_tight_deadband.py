from __future__ import annotations

import pytest

from host.otis_tools.integer_count_tight_deadband import (
    OUTSIDE,
    POLICY_ID,
    REQUALIFY_OUTSIDE,
    TIGHT_INSIDE,
    TightHystereticDeadband,
)


def _observe(
    policy: TightHystereticDeadband,
    counts: int | None,
    *,
    fresh: bool = True,
    session: int = 1,
    epoch: int = 1,
):
    return policy.observe(
        accumulated_edge_error_counts=counts,
        fresh=fresh,
        session=session,
        dac_epoch=epoch,
    )


def test_requalify_start_and_two_fresh_integer_count_entry() -> None:
    policy = TightHystereticDeadband()
    assert policy.state == REQUALIFY_OUTSIDE

    outside = _observe(policy, 3)
    assert outside.state_before == REQUALIFY_OUTSIDE
    assert outside.state_after == OUTSIDE
    assert outside.reason == "three_count_outside_hold"
    assert outside.frequency_controller_eligible

    first = _observe(policy, -2)
    second = _observe(policy, 2)
    assert first.reason == "tight_entry_pending"
    assert first.entry_pending_count == 1
    assert second.state_after == TIGHT_INSIDE
    assert second.reason == "tight_entry_confirmed"
    assert second.entry_pending_count == 0
    assert not first.frequency_controller_eligible
    assert not second.frequency_controller_eligible
    assert second.policy_id == POLICY_ID
    assert not second.actionable
    assert not second.actuation_authorized
    assert not second.authorization_consumed


def test_three_counts_retains_inside_and_two_four_count_estimates_release() -> None:
    policy = TightHystereticDeadband()
    _observe(policy, 2)
    _observe(policy, 2)

    three = _observe(policy, -3)
    first_release = _observe(policy, 4)
    second_release = _observe(policy, -4)
    assert three.state_after == TIGHT_INSIDE
    assert three.reason == "three_count_inside_hold"
    assert first_release.state_after == TIGHT_INSIDE
    assert first_release.release_pending_count == 1
    assert not first_release.frequency_controller_eligible
    assert second_release.state_after == OUTSIDE
    assert second_release.reason == "loose_release_confirmed"
    assert second_release.release_pending_count == 0
    assert second_release.frequency_controller_eligible


def test_opposite_evidence_and_invalidity_clear_pending_and_requalify() -> None:
    policy = TightHystereticDeadband()
    _observe(policy, 2)
    opposite = _observe(policy, 3)
    invalid = _observe(policy, None, fresh=False)
    fresh_after_invalid = _observe(policy, 2)

    assert opposite.state_after == OUTSIDE
    assert opposite.entry_pending_count == 0
    assert invalid.state_after == REQUALIFY_OUTSIDE
    assert invalid.reason == "invalid_or_stale_requalify"
    assert fresh_after_invalid.state_after == OUTSIDE
    assert fresh_after_invalid.entry_pending_count == 1


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"session": 2}, "session_changed_requalify"),
        ({"epoch": 2}, "dac_epoch_changed_requalify"),
    ],
)
def test_session_or_dac_epoch_change_rearms_then_credits_fresh_boundary(
    change: dict[str, int], reason: str,
) -> None:
    policy = TightHystereticDeadband()
    _observe(policy, 2)
    boundary = _observe(policy, 2, **change)
    second_after_boundary = _observe(policy, 2, **change)

    assert boundary.state_after == OUTSIDE
    assert boundary.reason == "tight_entry_pending"
    assert boundary.requalified
    assert boundary.requalification_reason == reason
    assert boundary.entry_pending_count == 1
    assert second_after_boundary.state_after == TIGHT_INSIDE


def test_rejects_noninteger_count_input() -> None:
    with pytest.raises(ValueError, match="integer count"):
        _observe(TightHystereticDeadband(), 2.0)  # type: ignore[arg-type]


def test_missing_identity_requalifies_without_controller_eligibility() -> None:
    decision = TightHystereticDeadband().observe(
        accumulated_edge_error_counts=4,
        fresh=True,
        session=None,
        dac_epoch=1,
    )
    assert decision.state_after == REQUALIFY_OUTSIDE
    assert decision.reason == "identity_missing_requalify"
    assert not decision.frequency_controller_eligible
