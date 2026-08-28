"""Pure, permanently non-effective Prompt 03 operational semantics.

The D9 output gate blocked promotion of a combined CX322/D9 profile.  This
module is therefore a deterministic safety/replay oracle only: it contains no
serial, firmware, actuator, controller-arm, or physical-authority path.  The
``effective_actuation_permitted`` result is false for every transition.  The
separate eligibility fields describe what the retained unchanged CX322 law
would be allowed to request in a future, separately authorized integration.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum

from .adaptive_steering_offline import (
    CanonicalControlState,
    RequestReleaseState,
    contain_optional_evidence_fault,
)


CX322_POLICY_ID = "CX322_BOUNDED_HYBRID_FACT_GATHERING_V1"


class OperationalMode(str, Enum):
    ACTIVE = "ACTIVE"
    GNSS_METADATA_HOLD = "GNSS_METADATA_HOLD"
    PHASE_DEGRADED_FLL = "PHASE_DEGRADED_FLL"
    LOW_EFFICIENCY_INHIBIT = "LOW_EFFICIENCY_INHIBIT"
    ACTUATOR_PROVENANCE_FAIL_STATIC = "ACTUATOR_PROVENANCE_FAIL_STATIC"


class TransactionOwner(str, Enum):
    NONE = "none"
    CORE1 = "core1"
    CORE0 = "core0"


class TransactionPhase(str, Enum):
    NONE = "none"
    PRIVATE_UNRELEASED = "private_unreleased"
    RELEASED_PENDING = "released_pending"
    ACCEPTED_APPLICATION_PENDING = "accepted_application_pending"
    RESPONSE_PENDING = "response_pending"


class AppliedPath(str, Enum):
    FLL_ONLY = "FLL_ONLY"
    HYBRID = "HYBRID"


ABSORBING_MODES = {
    OperationalMode.LOW_EFFICIENCY_INHIBIT,
    OperationalMode.ACTUATOR_PROVENANCE_FAIL_STATIC,
}


@dataclass(frozen=True)
class Cx322OperationalState:
    mode: OperationalMode
    capture_session: str
    measurement_frontier: int
    last_confirmed_code: int
    last_confirmed_dac_epoch: int
    metadata_sequence: int
    phase_epoch: str | None
    phase_frontier: int | None
    rearm_inhibit_reason: str
    policy_id: str = CX322_POLICY_ID
    d14_d8_measurement_healthy: bool = True
    gnss_metadata_qualified: bool = True
    metadata_reason: str = "qualified"
    phase_evidence_qualified: bool = True
    d9_output_valid: bool = False
    d9_output_reason: str = "waveform_evidence_incomplete"
    resume_mode_after_metadata_hold: OperationalMode | None = None
    transaction_owner: TransactionOwner = TransactionOwner.NONE
    transaction_phase: TransactionPhase = TransactionPhase.NONE
    pending_request_sequence: int | None = None
    pending_request_nonce: int | None = None
    last_outcome_sequence: int = 0
    last_application_sequence: int = 0
    last_first_consumer_frontier: int = -1
    last_response_frontier: int = -1
    last_completed_request_sequence: int = 0
    last_completed_request_nonce: int = 0
    last_completed_outcome: str = "none"
    phase_loss_pending: bool = False
    retired_phase_epochs: tuple[str, ...] = ()
    fll_episode_ids: tuple[str, ...] = ()
    last_fll_episode_application_sequence: int = 0
    last_fll_episode_exposure_end: int = -1

    def __post_init__(self) -> None:
        if not self.capture_session or self.measurement_frontier < 0:
            raise ValueError("capture session and measurement frontier are required")
        if not (0xA800 <= self.last_confirmed_code <= 0xAB00):
            raise ValueError("last confirmed code is outside the characterized envelope")
        if self.last_confirmed_dac_epoch < 0 or self.metadata_sequence < 0:
            raise ValueError("DAC and metadata identities must be nonnegative")
        if (self.phase_epoch is None) != (self.phase_frontier is None):
            raise ValueError("phase epoch and frontier must be present together")
        if self.phase_frontier is not None and self.phase_frontier < 0:
            raise ValueError("phase frontier must be nonnegative")
        if self.phase_evidence_qualified and self.phase_epoch is None:
            raise ValueError("qualified phase evidence requires an epoch identity")
        if (
            not self.phase_evidence_qualified
            and self.phase_epoch is not None
            and not self.phase_loss_pending
        ):
            raise ValueError(
                "an unqualified retained phase epoch requires a latched transaction"
            )
        if self.transaction_phase is TransactionPhase.NONE:
            if self.transaction_owner is not TransactionOwner.NONE:
                raise ValueError("a clear transaction cannot have an owner")
            if self.pending_request_sequence is not None:
                raise ValueError("a clear transaction cannot retain a request")
            if self.pending_request_nonce is not None:
                raise ValueError("a clear transaction cannot retain a nonce")
        else:
            if self.transaction_owner is TransactionOwner.NONE:
                raise ValueError("an outstanding transaction requires one owner")
            if self.pending_request_sequence is None or self.pending_request_sequence <= 0:
                raise ValueError("an outstanding transaction requires a request sequence")
            if self.pending_request_nonce is None or self.pending_request_nonce <= 0:
                raise ValueError("an outstanding transaction requires a nonce")
        if len(set(self.retired_phase_epochs)) != len(self.retired_phase_epochs):
            raise ValueError("retired phase epochs must be unique")
        if len(set(self.fll_episode_ids)) != len(self.fll_episode_ids):
            raise ValueError("FLL low-efficiency episodes must be unique")
        if self.last_completed_outcome not in {
            "none",
            "rejected",
            "expired",
            "accepted_applied_response_complete",
        }:
            raise ValueError("completed transaction outcome is unknown")
        if self.last_completed_outcome == "none":
            if self.last_completed_request_sequence or self.last_completed_request_nonce:
                raise ValueError("clear completed outcome cannot retain request identity")
        elif not (
            self.last_completed_request_sequence > 0
            and self.last_completed_request_nonce > 0
        ):
            raise ValueError("completed outcome requires request sequence and nonce")


@dataclass(frozen=True)
class MetadataQualification:
    receiver_matches_d14: bool
    qualified: bool
    reason: str
    sequence: int
    qualification_frontier: int
    capture_session: str
    post_qualification_observation_frontier: int
    applied_code: int
    dac_epoch: int


@dataclass(frozen=True)
class AppliedTransaction:
    request_sequence: int
    request_nonce: int
    outcome_sequence: int
    application_sequence: int
    applied_code: int
    dac_epoch: int
    first_consumer_frontier: int


@dataclass(frozen=True)
class LowEfficiencyEpisode:
    episode_id: str
    policy_id: str
    capture_session: str
    application_sequence: int
    first_consumer_frontier: int
    response_frontier: int
    response_window_start: int
    response_window_end: int
    exposure_window_start: int
    exposure_window_end: int
    applied: bool
    response_complete: bool
    exposure_complete: bool
    applied_path: AppliedPath
    frequency_only_integer_request: int
    combined_integer_request: int
    applied_code: int
    dac_epoch: int

    def __post_init__(self) -> None:
        if not self.episode_id or self.application_sequence <= 0:
            raise ValueError("episode identity and application sequence are required")
        if not (
            0 <= self.response_window_start < self.response_window_end
            and 0 <= self.exposure_window_start <= self.exposure_window_end
        ):
            raise ValueError("episode windows must be ordered and nonnegative")
        if self.applied_path is AppliedPath.FLL_ONLY and self.phase_materially_influenced:
            raise ValueError("FLL-only episode cannot carry a phase-material request")

    @property
    def phase_materially_influenced(self) -> bool:
        return self.frequency_only_integer_request != self.combined_integer_request


@dataclass(frozen=True)
class OperationalTransition:
    state: Cx322OperationalState
    action: str
    measurement_continues: bool
    effective_actuation_permitted: bool
    control_rearm_eligible: bool
    phase_request_eligible: bool
    delivered_output_trial_terminal: str | None = None
    local_component_status: tuple[str, str] | None = None


def _eligibility(state: Cx322OperationalState) -> tuple[bool, bool]:
    common = (
        state.mode in {OperationalMode.ACTIVE, OperationalMode.PHASE_DEGRADED_FLL}
        and state.d14_d8_measurement_healthy
        and state.gnss_metadata_qualified
        and state.rearm_inhibit_reason == "none"
        and state.transaction_phase is TransactionPhase.NONE
    )
    phase = common and state.mode is OperationalMode.ACTIVE and state.phase_evidence_qualified
    return common, phase


def _transition(
    state: Cx322OperationalState,
    action: str,
    *,
    delivered_output_trial_terminal: str | None = None,
    local_component_status: tuple[str, str] | None = None,
) -> OperationalTransition:
    control_rearm_eligible, phase_request_eligible = _eligibility(state)
    return OperationalTransition(
        state=state,
        action=action,
        measurement_continues=state.d14_d8_measurement_healthy,
        effective_actuation_permitted=False,
        control_rearm_eligible=control_rearm_eligible,
        phase_request_eligible=phase_request_eligible,
        delivered_output_trial_terminal=delivered_output_trial_terminal,
        local_component_status=local_component_status,
    )


def _fail_static(state: Cx322OperationalState, reason: str) -> OperationalTransition:
    return _transition(
        replace(
            state,
            mode=OperationalMode.ACTUATOR_PROVENANCE_FAIL_STATIC,
            rearm_inhibit_reason=reason,
            resume_mode_after_metadata_hold=None,
        ),
        f"{reason}_fail_static",
    )


def _absorbing(state: Cx322OperationalState, event: str) -> OperationalTransition | None:
    if state.mode not in ABSORBING_MODES:
        return None
    return _transition(state, f"{event}_ignored_absorbing_{state.mode.value.lower()}")


def _hold_state(state: Cx322OperationalState, *, reason: str) -> Cx322OperationalState:
    resume = (
        state.mode
        if state.mode in {OperationalMode.ACTIVE, OperationalMode.PHASE_DEGRADED_FLL}
        else state.resume_mode_after_metadata_hold
    )
    return replace(
        state,
        mode=OperationalMode.GNSS_METADATA_HOLD,
        gnss_metadata_qualified=False,
        metadata_reason=reason,
        rearm_inhibit_reason=reason,
        resume_mode_after_metadata_hold=resume,
    )


def counter_deadline_reached(*, now: int, deadline: int, counter_bits: int) -> bool:
    """Compare an exact modular counter without converting through wall time."""
    if counter_bits not in {16, 32, 64}:
        raise ValueError("deadline counter domain must declare 16, 32, or 64 bits")
    modulus = 1 << counter_bits
    if not (0 <= now < modulus and 0 <= deadline < modulus):
        raise ValueError("deadline values must fit the declared counter domain")
    return ((now - deadline) & (modulus - 1)) < (modulus >> 1)


def metadata_loss(
    state: Cx322OperationalState,
    *,
    request_state: RequestReleaseState,
    request_sequence: int | None = None,
    request_nonce: int | None = None,
    authoritative_outcome: str | None = None,
    outcome_sequence: int | None = None,
    outcome_deadline_expired: bool = False,
    outcome_counter: int | None = None,
    outcome_deadline: int | None = None,
    deadline_counter_bits: int | None = None,
) -> OperationalTransition:
    """Enter metadata hold while preserving exact Core 1/Core 0 ownership."""
    deadline_fields = (outcome_counter, outcome_deadline, deadline_counter_bits)
    if any(value is not None for value in deadline_fields):
        if not all(value is not None for value in deadline_fields):
            raise ValueError("deadline comparison requires counter, deadline, and domain")
        outcome_deadline_expired = counter_deadline_reached(
            now=outcome_counter,
            deadline=outcome_deadline,
            counter_bits=deadline_counter_bits,
        )
    absorbed = _absorbing(state, "metadata_loss")
    if absorbed is not None:
        return absorbed
    if state.transaction_phase is not TransactionPhase.NONE:
        if (
            request_sequence != state.pending_request_sequence
            or request_nonce != state.pending_request_nonce
        ):
            return _fail_static(state, "metadata_loss_pending_request_identity_contradiction")
        expected_state = {
            TransactionPhase.RELEASED_PENDING: RequestReleaseState.RELEASED_PENDING,
            TransactionPhase.ACCEPTED_APPLICATION_PENDING: RequestReleaseState.RELEASE_ACCEPTED,
            TransactionPhase.RESPONSE_PENDING: RequestReleaseState.RESPONSE_PENDING,
        }.get(state.transaction_phase)
        if request_state is not expected_state:
            return _fail_static(state, "metadata_loss_pending_transaction_phase_contradiction")
        if (
            state.transaction_phase is TransactionPhase.RELEASED_PENDING
            and outcome_deadline_expired
            and authoritative_outcome != "accepted"
        ):
            return _fail_static(state, "released_request_outcome_deadline_expired")
        if authoritative_outcome == "accepted":
            if state.transaction_phase is TransactionPhase.RELEASED_PENDING:
                if outcome_sequence is None or outcome_sequence <= state.last_outcome_sequence:
                    return _fail_static(state, "accepted_outcome_sequence_contradictory")
                return _transition(
                    replace(
                        state,
                        transaction_phase=TransactionPhase.ACCEPTED_APPLICATION_PENDING,
                        last_outcome_sequence=outcome_sequence,
                    ),
                    "acceptance_wins_complete_application_first_consumer_and_response",
                )
            if outcome_sequence == state.last_outcome_sequence:
                return _transition(state, "duplicate_accepted_outcome_ignored_exact_identity")
            return _fail_static(state, "duplicate_accepted_outcome_identity_contradiction")
        if authoritative_outcome in {"rejected", "expired"}:
            if state.transaction_phase is not TransactionPhase.RELEASED_PENDING:
                return _fail_static(state, "late_rejection_after_acceptance_contradiction")
            if outcome_sequence is None or outcome_sequence <= state.last_outcome_sequence:
                return _fail_static(state, "released_request_outcome_sequence_contradictory")
            return _transition(
                replace(
                    state,
                    transaction_owner=TransactionOwner.NONE,
                    transaction_phase=TransactionPhase.NONE,
                    pending_request_sequence=None,
                    pending_request_nonce=None,
                    last_outcome_sequence=outcome_sequence,
                    last_completed_request_sequence=request_sequence,
                    last_completed_request_nonce=request_nonce,
                    last_completed_outcome=authoritative_outcome,
                ),
                f"released_request_{authoritative_outcome}_then_remain_metadata_hold",
            )
        if authoritative_outcome is not None:
            return _fail_static(state, "released_request_outcome_contradictory")
        return _transition(state, "metadata_loss_repeated_existing_transaction_preserved")

    hold = _hold_state(state, reason="gnss_metadata_unqualified")
    if request_state is RequestReleaseState.UNUSED_ARM:
        if authoritative_outcome is not None:
            return _fail_static(hold, "unused_arm_has_impossible_outcome")
        return _transition(hold, "unused_arm_consumed_then_enter_metadata_hold")
    if request_state is RequestReleaseState.PRIVATE_UNRELEASED:
        if authoritative_outcome is not None:
            return _fail_static(hold, "private_unreleased_has_impossible_core0_outcome")
        if (
            request_sequence is None
            or request_sequence <= 0
            or request_nonce is None
            or request_nonce <= 0
        ):
            return _fail_static(hold, "private_unreleased_request_identity_missing")
        return _transition(hold, "private_unreleased_withdrawn_then_enter_metadata_hold")
    if request_state in {RequestReleaseState.RELEASE_ACCEPTED, RequestReleaseState.RESPONSE_PENDING}:
        return _fail_static(hold, "direct_transaction_phase_without_retained_identity")
    if request_state is RequestReleaseState.RELEASED_PENDING:
        if (
            request_sequence is None
            or request_sequence <= 0
            or request_nonce is None
            or request_nonce <= 0
        ):
            return _fail_static(hold, "released_request_identity_missing")
        if authoritative_outcome not in {None, "accepted", "rejected", "expired"}:
            return _fail_static(hold, "released_request_outcome_contradictory")
        # An authoritative acceptance wins a coincident local deadline check.
        if outcome_deadline_expired and authoritative_outcome != "accepted":
            return _fail_static(hold, "released_request_outcome_deadline_expired")
        if authoritative_outcome in {"rejected", "expired"}:
            if outcome_sequence is None or outcome_sequence <= state.last_outcome_sequence:
                return _fail_static(hold, "released_request_outcome_sequence_contradictory")
            return _transition(
                replace(
                    hold,
                    last_outcome_sequence=outcome_sequence,
                    last_completed_request_sequence=request_sequence,
                    last_completed_request_nonce=request_nonce,
                    last_completed_outcome=authoritative_outcome,
                ),
                f"released_request_{authoritative_outcome}_then_enter_metadata_hold",
            )
        phase = TransactionPhase.RELEASED_PENDING
        if authoritative_outcome == "accepted":
            if outcome_sequence is None or outcome_sequence <= state.last_outcome_sequence:
                return _fail_static(hold, "accepted_outcome_sequence_contradictory")
            phase = TransactionPhase.ACCEPTED_APPLICATION_PENDING
        return _transition(
            replace(
                hold,
                transaction_owner=TransactionOwner.CORE0,
                transaction_phase=phase,
                pending_request_sequence=request_sequence,
                pending_request_nonce=request_nonce,
                last_outcome_sequence=(
                    outcome_sequence
                    if authoritative_outcome == "accepted" and outcome_sequence is not None
                    else state.last_outcome_sequence
                ),
            ),
            (
                "acceptance_wins_complete_application_first_consumer_and_response"
                if authoritative_outcome == "accepted"
                else "released_request_core0_owned_await_authoritative_outcome"
            ),
        )
    if request_state is RequestReleaseState.OUTCOME_RESOLVED:
        return _transition(hold, "resolved_outcome_enter_metadata_hold")
    return _fail_static(hold, "request_release_state_fail_static_or_unknown")


def accept_released_request(
    state: Cx322OperationalState,
    *,
    request_sequence: int,
    request_nonce: int,
    outcome_sequence: int,
) -> OperationalTransition:
    absorbed = _absorbing(state, "request_acceptance")
    if absorbed is not None:
        return absorbed
    if state.transaction_phase is not TransactionPhase.RELEASED_PENDING:
        return _fail_static(state, "acceptance_without_released_pending_request")
    if (
        request_sequence != state.pending_request_sequence
        or request_nonce != state.pending_request_nonce
    ):
        return _fail_static(state, "acceptance_request_identity_contradiction")
    if outcome_sequence <= state.last_outcome_sequence:
        return _fail_static(state, "acceptance_outcome_sequence_contradiction")
    return _transition(
        replace(
            state,
            transaction_phase=TransactionPhase.ACCEPTED_APPLICATION_PENDING,
            last_outcome_sequence=outcome_sequence,
        ),
        "released_request_accepted_core0_outcome_owner",
    )


def complete_accepted_application(
    state: Cx322OperationalState, application: AppliedTransaction
) -> OperationalTransition:
    absorbed = _absorbing(state, "application_completion")
    if absorbed is not None:
        return absorbed
    if state.transaction_phase is not TransactionPhase.ACCEPTED_APPLICATION_PENDING:
        return _fail_static(state, "application_without_accepted_request")
    if (
        application.request_sequence != state.pending_request_sequence
        or application.request_nonce != state.pending_request_nonce
    ):
        return _fail_static(state, "application_request_identity_contradiction")
    if application.outcome_sequence != state.last_outcome_sequence:
        return _fail_static(state, "application_outcome_identity_contradiction")
    if not (0xA800 <= application.applied_code <= 0xAB00):
        return _fail_static(state, "application_code_outside_characterized_envelope")
    if (
        application.application_sequence <= state.last_application_sequence
        or application.dac_epoch <= state.last_confirmed_dac_epoch
        or application.first_consumer_frontier <= state.measurement_frontier
    ):
        return _fail_static(state, "application_or_first_consumer_order_contradiction")
    return _transition(
        replace(
            state,
            measurement_frontier=application.first_consumer_frontier,
            last_confirmed_code=application.applied_code,
            last_confirmed_dac_epoch=application.dac_epoch,
            last_application_sequence=application.application_sequence,
            last_first_consumer_frontier=application.first_consumer_frontier,
            transaction_phase=TransactionPhase.RESPONSE_PENDING,
        ),
        "accepted_application_and_first_consumer_confirmed_response_pending",
    )


def _apply_phase_degradation(state: Cx322OperationalState) -> Cx322OperationalState:
    retired = state.retired_phase_epochs
    if state.phase_epoch is not None and state.phase_epoch not in retired:
        retired = (*retired, state.phase_epoch)
    if state.mode is OperationalMode.GNSS_METADATA_HOLD:
        mode = state.mode
        resume = OperationalMode.PHASE_DEGRADED_FLL
        inhibit = state.rearm_inhibit_reason
    else:
        mode = OperationalMode.PHASE_DEGRADED_FLL
        resume = None
        inhibit = "none"
    return replace(
        state,
        mode=mode,
        resume_mode_after_metadata_hold=resume,
        phase_evidence_qualified=False,
        phase_epoch=None,
        phase_frontier=None,
        phase_loss_pending=False,
        retired_phase_epochs=retired,
        rearm_inhibit_reason=inhibit,
    )


def complete_metadata_response_then_hold(
    state: Cx322OperationalState,
    *,
    request_sequence: int,
    request_nonce: int,
    response_frontier: int,
) -> OperationalTransition:
    absorbed = _absorbing(state, "response_completion")
    if absorbed is not None:
        return absorbed
    if state.transaction_phase is not TransactionPhase.RESPONSE_PENDING:
        return _fail_static(state, "response_without_pending_application")
    if (
        request_sequence != state.pending_request_sequence
        or request_nonce != state.pending_request_nonce
    ):
        return _fail_static(state, "response_request_identity_contradiction")
    if response_frontier <= state.measurement_frontier:
        return _fail_static(state, "response_frontier_not_causally_later")
    resolved = replace(
        state,
        measurement_frontier=response_frontier,
        last_response_frontier=response_frontier,
        transaction_owner=TransactionOwner.NONE,
        transaction_phase=TransactionPhase.NONE,
        pending_request_sequence=None,
        pending_request_nonce=None,
        last_completed_request_sequence=request_sequence,
        last_completed_request_nonce=request_nonce,
        last_completed_outcome="accepted_applied_response_complete",
    )
    if resolved.phase_loss_pending:
        return _transition(
            _apply_phase_degradation(resolved),
            "response_completed_then_metadata_hold_with_phase_degraded_fll",
        )
    return _transition(resolved, "response_completed_then_remain_metadata_hold")


def requalify_metadata_hold(
    state: Cx322OperationalState, observation: MetadataQualification
) -> OperationalTransition:
    absorbed = _absorbing(state, "metadata_requalification")
    if absorbed is not None:
        return absorbed
    if state.mode is not OperationalMode.GNSS_METADATA_HOLD:
        raise ValueError("only GNSS metadata hold may be requalified")
    if state.transaction_phase is not TransactionPhase.NONE:
        return _transition(state, "metadata_fresh_but_transaction_resolution_pending")
    if not observation.receiver_matches_d14 or not observation.qualified:
        return _transition(state, "metadata_not_qualified_remain_hold")
    if observation.sequence <= state.metadata_sequence:
        return _transition(state, "metadata_sequence_not_fresh_remain_hold")
    if observation.qualification_frontier < state.measurement_frontier:
        return _transition(state, "metadata_qualification_snapshot_behind_remain_hold")
    if observation.post_qualification_observation_frontier <= observation.qualification_frontier:
        return _transition(state, "post_metadata_observation_not_causally_later_remain_hold")
    if observation.capture_session != state.capture_session:
        return _fail_static(state, "post_metadata_requalification_session_contradiction")
    if observation.dac_epoch < state.last_confirmed_dac_epoch:
        return _transition(state, "post_metadata_applied_identity_snapshot_behind_remain_hold")
    if (
        observation.dac_epoch != state.last_confirmed_dac_epoch
        or observation.applied_code != state.last_confirmed_code
    ):
        return _fail_static(state, "post_metadata_requalification_identity_contradiction")
    resumed = state.resume_mode_after_metadata_hold or OperationalMode.ACTIVE
    return _transition(
        replace(
            state,
            mode=resumed,
            metadata_sequence=observation.sequence,
            measurement_frontier=observation.post_qualification_observation_frontier,
            gnss_metadata_qualified=True,
            metadata_reason=observation.reason,
            rearm_inhibit_reason="none",
            resume_mode_after_metadata_hold=None,
        ),
        "fresh_metadata_and_causally_later_d14_d8_observation_requalified",
    )


def degrade_phase_to_fll(state: Cx322OperationalState) -> OperationalTransition:
    """Latch phase loss through a transaction; introduce no correction debt."""
    absorbed = _absorbing(state, "phase_loss")
    if absorbed is not None:
        return absorbed
    if state.transaction_phase is not TransactionPhase.NONE:
        return _transition(
            replace(
                state,
                phase_evidence_qualified=False,
                phase_loss_pending=True,
                rearm_inhibit_reason="phase_loss_pending_transaction_resolution",
            ),
            "phase_loss_latched_until_transaction_first_consumer_and_response",
        )
    return _transition(
        _apply_phase_degradation(state),
        "not_applicable_no_committed_pll_debt",
    )


def requalify_new_phase_epoch(
    state: Cx322OperationalState, *, phase_epoch: str, phase_frontier: int
) -> OperationalTransition:
    absorbed = _absorbing(state, "phase_requalification")
    if absorbed is not None:
        return absorbed
    if state.mode is not OperationalMode.PHASE_DEGRADED_FLL:
        raise ValueError("only phase-degraded FLL may accept a new phase epoch")
    if (
        not phase_epoch
        or phase_epoch in state.retired_phase_epochs
        or phase_frontier <= state.measurement_frontier
    ):
        return _transition(state, "new_phase_epoch_not_new_or_causally_later")
    return _transition(
        replace(
            state,
            mode=OperationalMode.ACTIVE,
            phase_evidence_qualified=True,
            phase_epoch=phase_epoch,
            phase_frontier=phase_frontier,
            measurement_frontier=phase_frontier,
            rearm_inhibit_reason="none",
        ),
        "new_phase_epoch_qualified_without_numeric_rejoin",
    )


def record_completed_low_efficiency(
    state: Cx322OperationalState, episode: LowEfficiencyEpisode
) -> OperationalTransition:
    """Count only applied, identity-bound, independent FLL-only episodes."""
    absorbed = _absorbing(state, "low_efficiency")
    if absorbed is not None:
        return absorbed
    identity_exact = (
        episode.policy_id == state.policy_id
        and episode.capture_session == state.capture_session
        and episode.applied_code == state.last_confirmed_code
        and episode.dac_epoch == state.last_confirmed_dac_epoch
        and episode.application_sequence == state.last_application_sequence
        and episode.first_consumer_frontier == state.last_first_consumer_frontier
        and episode.response_frontier == state.last_response_frontier
    )
    if not identity_exact:
        return _fail_static(state, "low_efficiency_episode_identity_contradiction")
    if not (episode.applied and episode.response_complete and episode.exposure_complete):
        return _transition(state, "low_efficiency_episode_incomplete_not_counted")
    if episode.applied_path is AppliedPath.HYBRID:
        if not episode.phase_materially_influenced:
            return _transition(state, "hybrid_episode_not_fll_only_not_counted")
        return _transition(
            _apply_phase_degradation(state),
            "phase_material_low_efficiency_discard_cached_pll_and_fallback_to_fll",
        )
    if (
        episode.episode_id in state.fll_episode_ids
        or episode.application_sequence <= state.last_fll_episode_application_sequence
        or episode.exposure_window_start <= state.last_fll_episode_exposure_end
        or not (
            episode.response_window_start
            <= episode.response_frontier
            <= episode.response_window_end
        )
        or episode.exposure_window_start > episode.response_window_start
        or episode.response_window_end > episode.exposure_window_end
    ):
        return _transition(state, "fll_low_efficiency_episode_duplicate_or_overlapping_not_counted")
    episode_ids = (*state.fll_episode_ids, episode.episode_id)
    if len(episode_ids) >= 2:
        return _transition(
            replace(
                state,
                mode=OperationalMode.LOW_EFFICIENCY_INHIBIT,
                fll_episode_ids=episode_ids,
                last_fll_episode_application_sequence=episode.application_sequence,
                last_fll_episode_exposure_end=episode.exposure_window_end,
                rearm_inhibit_reason="two_independent_fll_only_low_efficiency_episodes",
                resume_mode_after_metadata_hold=None,
            ),
            "second_independent_fll_only_low_efficiency_static_inhibit",
        )
    return _transition(
        replace(
            state,
            fll_episode_ids=episode_ids,
            last_fll_episode_application_sequence=episode.application_sequence,
            last_fll_episode_exposure_end=episode.exposure_window_end,
        ),
        "first_fll_only_low_efficiency_episode_local_degradation",
    )


def record_d9_output_status(
    state: Cx322OperationalState, *, valid: bool, reason: str
) -> OperationalTransition:
    """Update delivered-output status without changing D14/D8 controller truth."""
    updated = replace(state, d9_output_valid=valid, d9_output_reason=reason)
    terminal = None if valid else "delivered_output_trial_stopped_d9_invalid"
    return _transition(
        updated,
        "d9_output_status_updated_without_measurement_or_control_authority",
        delivered_output_trial_terminal=terminal,
        local_component_status=("d9", reason),
    )


def contain_local_optional_fault(
    state: Cx322OperationalState, *, component: str, fault: str
) -> OperationalTransition:
    """Prove D6, D10, and shadow failures cannot mutate canonical authority."""
    contain_optional_evidence_fault(
        CanonicalControlState(
            canonical_state_digest=f"{state.capture_session}:{state.measurement_frontier}",
            d14_d8_measurement_healthy=state.d14_d8_measurement_healthy,
            control_authority_state=state.mode.value,
        ),
        component=component,
        fault=fault,
    )
    return _transition(
        state,
        f"{component}_local_fault:{fault}",
        local_component_status=(component, fault),
    )
