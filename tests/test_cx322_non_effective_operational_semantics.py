from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path

from host.otis_tools.adaptive_steering_offline import RequestReleaseState
from host.otis_tools.cx322_non_effective_operational_semantics import (
    AppliedPath,
    AppliedTransaction,
    Cx322OperationalState,
    LowEfficiencyEpisode,
    MetadataQualification,
    OperationalMode,
    TransactionOwner,
    TransactionPhase,
    accept_released_request,
    complete_accepted_application,
    complete_metadata_response_then_hold,
    contain_local_optional_fault,
    counter_deadline_reached,
    degrade_phase_to_fll,
    metadata_loss,
    record_completed_low_efficiency,
    record_d9_output_status,
    requalify_metadata_hold,
    requalify_new_phase_epoch,
)


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / (
    "docs/60_EXPERIMENTS/OTIS_D9_OUTPUT_AND_ADAPTIVE_STEERING_"
    "INTEGRATION_PROGRAMME/cx322_non_effective_operational_semantics_contract_v1.json"
)


def _state(**changes: object) -> Cx322OperationalState:
    value = Cx322OperationalState(
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
    return replace(value, **changes)


def _qualification(
    *,
    sequence: int = 21,
    qualification_frontier: int = 101,
    observation_frontier: int = 102,
    capture_session: str = "session-7",
    applied_code: int = 0xA83C,
    dac_epoch: int = 4,
) -> MetadataQualification:
    return MetadataQualification(
        receiver_matches_d14=True,
        qualified=True,
        reason="same_receiver_metadata_qualified",
        sequence=sequence,
        qualification_frontier=qualification_frontier,
        capture_session=capture_session,
        post_qualification_observation_frontier=observation_frontier,
        applied_code=applied_code,
        dac_epoch=dac_epoch,
    )


def _episode(
    episode_id: str,
    application_sequence: int,
    start: int,
    end: int,
    *,
    path: AppliedPath = AppliedPath.FLL_ONLY,
    fll_request: int = 2,
    combined_request: int = 2,
    applied: bool = True,
) -> LowEfficiencyEpisode:
    return LowEfficiencyEpisode(
        episode_id=episode_id,
        policy_id="CX322_BOUNDED_HYBRID_FACT_GATHERING_V1",
        capture_session="session-7",
        application_sequence=application_sequence,
        first_consumer_frontier=start - 1,
        response_frontier=start + 1,
        response_window_start=start,
        response_window_end=end - 1,
        exposure_window_start=start,
        exposure_window_end=end,
        applied=applied,
        response_complete=True,
        exposure_complete=True,
        applied_path=path,
        frequency_only_integer_request=fll_request,
        combined_integer_request=combined_request,
        applied_code=0xA83C,
        dac_epoch=4,
    )


def _assert_non_effective(*transitions: object) -> None:
    for transition in transitions:
        assert transition.effective_actuation_permitted is False


def test_contract_is_semantically_bound_and_permanently_non_effective() -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    unsigned = {
        key: value for key, value in contract.items() if key != "contract_semantic_sha256"
    }
    assert contract["contract_semantic_sha256"] == sha256(
        json.dumps(
            unsigned, sort_keys=True, separators=(",", ":"), ensure_ascii=False
        ).encode()
    ).hexdigest()
    assert contract["entry_controller_terminal"] == (
        "cx322_integration_blocked_by_d9_output_gate"
    )
    assert contract["terminal"] == (
        "operational_semantics_implemented_promotion_blocked_by_d9_gate"
    )
    assert not any(contract["authority"].values())
    assert contract["unchanged_cx322_request_law"]["correction_debt_change"] == "none"
    bindings = (
        (
            contract["unchanged_cx322_request_law"]["policy_path"],
            contract["unchanged_cx322_request_law"]["policy_sha256"],
        ),
        (
            contract["unchanged_cx322_request_law"]["host_policy_path"],
            contract["unchanged_cx322_request_law"]["host_policy_sha256"],
        ),
        (
            contract["unchanged_cx322_request_law"]["firmware_policy_source_path"],
            contract["unchanged_cx322_request_law"]["firmware_policy_source_sha256"],
        ),
        (
            contract["unchanged_cx322_request_law"]["firmware_policy_header_path"],
            contract["unchanged_cx322_request_law"]["firmware_policy_header_sha256"],
        ),
        (
            contract["existing_transaction_path"]["source_path"],
            contract["existing_transaction_path"]["source_sha256"],
        ),
        (
            contract["existing_transaction_path"]["header_path"],
            contract["existing_transaction_path"]["header_sha256"],
        ),
        (
            contract["existing_transaction_path"]["non_effective_oracle_path"],
            contract["existing_transaction_path"]["non_effective_oracle_sha256"],
        ),
        (
            contract["existing_transaction_path"]["offline_reference_path"],
            contract["existing_transaction_path"]["offline_reference_sha256"],
        ),
        (contract["native_fixture"]["path"], contract["native_fixture"]["sha256"]),
        (
            contract["native_fixture"]["pytest_path"],
            contract["native_fixture"]["pytest_sha256"],
        ),
    )
    for relative_path, expected_sha256 in bindings:
        assert sha256((ROOT / relative_path).read_bytes()).hexdigest() == expected_sha256


def test_metadata_loss_covers_private_and_exact_core0_acceptance_path() -> None:
    private = metadata_loss(
        _state(
            last_application_sequence=1,
            last_first_consumer_frontier=109,
            last_response_frontier=111,
        ),
        request_state=RequestReleaseState.PRIVATE_UNRELEASED,
        request_sequence=7,
        request_nonce=7007,
    )
    assert private.state.mode is OperationalMode.GNSS_METADATA_HOLD
    assert private.state.transaction_phase is TransactionPhase.NONE
    assert private.action == "private_unreleased_withdrawn_then_enter_metadata_hold"

    released = metadata_loss(
        _state(),
        request_state=RequestReleaseState.RELEASED_PENDING,
        request_sequence=8,
        request_nonce=8008,
    )
    assert released.state.mode is OperationalMode.GNSS_METADATA_HOLD
    assert released.state.transaction_owner is TransactionOwner.CORE0
    assert released.state.transaction_phase is TransactionPhase.RELEASED_PENDING
    accepted = accept_released_request(
        released.state, request_sequence=8, request_nonce=8008, outcome_sequence=31
    )
    applied = complete_accepted_application(
        accepted.state,
        AppliedTransaction(
            request_sequence=8,
            request_nonce=8008,
            outcome_sequence=31,
            application_sequence=5,
            applied_code=0xA840,
            dac_epoch=5,
            first_consumer_frontier=101,
        ),
    )
    assert applied.state.last_confirmed_code == 0xA840
    assert applied.state.last_confirmed_dac_epoch == 5
    assert applied.state.transaction_phase is TransactionPhase.RESPONSE_PENDING
    response = complete_metadata_response_then_hold(
        applied.state, request_sequence=8, request_nonce=8008, response_frontier=102
    )
    assert response.state.mode is OperationalMode.GNSS_METADATA_HOLD
    assert response.state.transaction_owner is TransactionOwner.NONE
    assert response.state.transaction_phase is TransactionPhase.NONE
    assert response.state.last_response_frontier == 102
    assert response.state.last_completed_request_sequence == 8
    assert response.state.last_completed_request_nonce == 8008
    assert response.state.last_completed_outcome == "accepted_applied_response_complete"
    _assert_non_effective(private, released, accepted, applied, response)


def test_acceptance_wins_deadline_race_but_silence_and_contradiction_fail_static() -> None:
    accepted = metadata_loss(
        _state(),
        request_state=RequestReleaseState.RELEASED_PENDING,
        request_sequence=9,
        request_nonce=9009,
        authoritative_outcome="accepted",
        outcome_sequence=40,
        outcome_deadline_expired=True,
    )
    assert accepted.state.transaction_phase is TransactionPhase.ACCEPTED_APPLICATION_PENDING
    assert accepted.state.mode is OperationalMode.GNSS_METADATA_HOLD

    silent = metadata_loss(
        _state(),
        request_state=RequestReleaseState.RELEASED_PENDING,
        request_sequence=9,
        request_nonce=9009,
        outcome_deadline_expired=True,
    )
    assert silent.state.mode is OperationalMode.ACTUATOR_PROVENANCE_FAIL_STATIC
    impossible = metadata_loss(
        _state(),
        request_state=RequestReleaseState.PRIVATE_UNRELEASED,
        request_sequence=9,
        request_nonce=9009,
        authoritative_outcome="accepted",
    )
    assert impossible.state.mode is OperationalMode.ACTUATOR_PROVENANCE_FAIL_STATIC
    _assert_non_effective(accepted, silent, impossible)


def test_repeated_outcomes_nonce_and_direct_phase_entry_are_exact() -> None:
    released = metadata_loss(
        _state(),
        request_state=RequestReleaseState.RELEASED_PENDING,
        request_sequence=13,
        request_nonce=1313,
    )
    accepted = metadata_loss(
        released.state,
        request_state=RequestReleaseState.RELEASED_PENDING,
        request_sequence=13,
        request_nonce=1313,
        authoritative_outcome="accepted",
        outcome_sequence=60,
    )
    assert accepted.state.transaction_phase is TransactionPhase.ACCEPTED_APPLICATION_PENDING
    duplicate = metadata_loss(
        accepted.state,
        request_state=RequestReleaseState.RELEASE_ACCEPTED,
        request_sequence=13,
        request_nonce=1313,
        authoritative_outcome="accepted",
        outcome_sequence=60,
    )
    assert duplicate.state is accepted.state
    late_rejection = metadata_loss(
        accepted.state,
        request_state=RequestReleaseState.RELEASE_ACCEPTED,
        request_sequence=13,
        request_nonce=1313,
        authoritative_outcome="rejected",
        outcome_sequence=61,
    )
    wrong_nonce = metadata_loss(
        released.state,
        request_state=RequestReleaseState.RELEASED_PENDING,
        request_sequence=13,
        request_nonce=9999,
    )
    direct_accepted = metadata_loss(
        _state(),
        request_state=RequestReleaseState.RELEASE_ACCEPTED,
        request_sequence=13,
        request_nonce=1313,
    )
    direct_response = metadata_loss(
        _state(),
        request_state=RequestReleaseState.RESPONSE_PENDING,
        request_sequence=13,
        request_nonce=1313,
    )
    rejected = metadata_loss(
        _state(),
        request_state=RequestReleaseState.RELEASED_PENDING,
        request_sequence=14,
        request_nonce=1414,
        authoritative_outcome="rejected",
        outcome_sequence=62,
    )
    assert rejected.state.last_completed_request_sequence == 14
    assert rejected.state.last_completed_request_nonce == 1414
    assert rejected.state.last_completed_outcome == "rejected"
    for contradictory in (
        late_rejection,
        wrong_nonce,
        direct_accepted,
        direct_response,
    ):
        assert contradictory.state.mode is OperationalMode.ACTUATOR_PROVENANCE_FAIL_STATIC
    _assert_non_effective(
        released,
        accepted,
        duplicate,
        late_rejection,
        wrong_nonce,
        direct_accepted,
        direct_response,
    )


def test_outcome_deadline_is_wrap_safe_in_its_declared_counter_domain() -> None:
    assert not counter_deadline_reached(
        now=0xFFFF_FFFE, deadline=2, counter_bits=32
    )
    assert counter_deadline_reached(now=2, deadline=2, counter_bits=32)
    assert counter_deadline_reached(now=3, deadline=2, counter_bits=32)
    before_wrap = metadata_loss(
        _state(),
        request_state=RequestReleaseState.RELEASED_PENDING,
        request_sequence=12,
        request_nonce=1212,
        outcome_counter=0xFFFF_FFFE,
        outcome_deadline=2,
        deadline_counter_bits=32,
    )
    expired_after_wrap = metadata_loss(
        _state(),
        request_state=RequestReleaseState.RELEASED_PENDING,
        request_sequence=12,
        request_nonce=1212,
        outcome_counter=3,
        outcome_deadline=2,
        deadline_counter_bits=32,
    )
    assert before_wrap.state.transaction_phase is TransactionPhase.RELEASED_PENDING
    assert expired_after_wrap.state.mode is OperationalMode.ACTUATOR_PROVENANCE_FAIL_STATIC
    _assert_non_effective(before_wrap, expired_after_wrap)


def test_metadata_requalification_separates_lag_from_contradiction_and_causality() -> None:
    held = metadata_loss(
        _state(), request_state=RequestReleaseState.UNUSED_ARM
    ).state
    stale_metadata = requalify_metadata_hold(
        held, _qualification(sequence=20, qualification_frontier=100, observation_frontier=101)
    )
    stale_observation = requalify_metadata_hold(
        held, _qualification(qualification_frontier=101, observation_frontier=101)
    )
    behind_identity = requalify_metadata_hold(
        held, _qualification(dac_epoch=3, qualification_frontier=101, observation_frontier=102)
    )
    contradiction = requalify_metadata_hold(
        held,
        _qualification(
            applied_code=0xA841,
            dac_epoch=4,
            qualification_frontier=101,
            observation_frontier=102,
        ),
    )
    recovered = requalify_metadata_hold(held, _qualification())
    assert stale_metadata.state.mode is OperationalMode.GNSS_METADATA_HOLD
    assert stale_observation.state.mode is OperationalMode.GNSS_METADATA_HOLD
    assert behind_identity.state.mode is OperationalMode.GNSS_METADATA_HOLD
    assert contradiction.state.mode is OperationalMode.ACTUATOR_PROVENANCE_FAIL_STATIC
    assert recovered.state.mode is OperationalMode.ACTIVE
    assert recovered.control_rearm_eligible
    _assert_non_effective(
        stale_metadata, stale_observation, behind_identity, contradiction, recovered
    )


def test_phase_loss_latches_through_first_consumer_response_and_requires_new_epoch() -> None:
    pending = metadata_loss(
        _state(),
        request_state=RequestReleaseState.RELEASED_PENDING,
        request_sequence=10,
        request_nonce=1010,
        authoritative_outcome="accepted",
        outcome_sequence=50,
    )
    lost = degrade_phase_to_fll(pending.state)
    assert lost.state.phase_loss_pending
    assert not lost.control_rearm_eligible
    applied = complete_accepted_application(
        lost.state,
        AppliedTransaction(10, 1010, 50, 6, 0xA83B, 5, 101),
    )
    resolved = complete_metadata_response_then_hold(
        applied.state, request_sequence=10, request_nonce=1010, response_frontier=102
    )
    assert resolved.state.mode is OperationalMode.GNSS_METADATA_HOLD
    assert resolved.state.resume_mode_after_metadata_hold is OperationalMode.PHASE_DEGRADED_FLL
    assert "phase-7" in resolved.state.retired_phase_epochs
    metadata_requalified = requalify_metadata_hold(
        resolved.state,
        _qualification(
            qualification_frontier=103,
            observation_frontier=104,
            applied_code=0xA83B,
            dac_epoch=5,
        ),
    )
    assert metadata_requalified.state.mode is OperationalMode.PHASE_DEGRADED_FLL
    assert metadata_requalified.control_rearm_eligible
    assert not metadata_requalified.phase_request_eligible
    reused = requalify_new_phase_epoch(
        metadata_requalified.state, phase_epoch="phase-7", phase_frontier=105
    )
    assert reused.state.mode is OperationalMode.PHASE_DEGRADED_FLL
    fresh = requalify_new_phase_epoch(
        metadata_requalified.state, phase_epoch="phase-8", phase_frontier=105
    )
    assert fresh.state.mode is OperationalMode.ACTIVE
    assert fresh.action == "new_phase_epoch_qualified_without_numeric_rejoin"
    _assert_non_effective(lost, applied, resolved, metadata_requalified, reused, fresh)


def test_no_tagged_correction_debt_and_phase_material_fallback_is_explicit() -> None:
    degraded = degrade_phase_to_fll(_state())
    assert degraded.action == "not_applicable_no_committed_pll_debt"
    assert degraded.state.mode is OperationalMode.PHASE_DEGRADED_FLL
    assert degraded.control_rearm_eligible
    assert not degraded.phase_request_eligible

    phase_material = record_completed_low_efficiency(
        _state(
            last_application_sequence=1,
            last_first_consumer_frontier=109,
            last_response_frontier=111,
        ),
        _episode(
            "hybrid-1",
            1,
            110,
            120,
            path=AppliedPath.HYBRID,
            fll_request=0,
            combined_request=2,
        ),
    )
    assert phase_material.state.mode is OperationalMode.PHASE_DEGRADED_FLL
    assert phase_material.state.phase_epoch is None
    assert phase_material.action.startswith("phase_material_low_efficiency")
    _assert_non_effective(degraded, phase_material)


def test_only_two_explicit_independent_fll_only_episodes_static_inhibit() -> None:
    retained_first = _state(
        last_application_sequence=1,
        last_first_consumer_frontier=109,
        last_response_frontier=111,
    )
    hybrid_equal = record_completed_low_efficiency(
        retained_first,
        _episode("hybrid-equal", 1, 110, 120, path=AppliedPath.HYBRID),
    )
    assert hybrid_equal.state.fll_episode_ids == ()
    incomplete = record_completed_low_efficiency(
        retained_first,
        replace(_episode("fll-1", 1, 110, 120), response_complete=False),
    )
    assert incomplete.state.fll_episode_ids == ()
    first = record_completed_low_efficiency(
        retained_first, _episode("fll-1", 1, 110, 120)
    )
    retained_second = replace(
        first.state,
        last_application_sequence=2,
        last_first_consumer_frontier=118,
        last_response_frontier=120,
    )
    overlap = record_completed_low_efficiency(
        retained_second, _episode("fll-overlap", 2, 119, 130)
    )
    assert overlap.state is retained_second
    retained_second_valid = replace(
        retained_second,
        last_first_consumer_frontier=120,
        last_response_frontier=122,
    )
    second = record_completed_low_efficiency(
        retained_second_valid, _episode("fll-2", 2, 121, 131)
    )
    assert second.state.mode is OperationalMode.LOW_EFFICIENCY_INHIBIT
    assert not second.control_rearm_eligible
    _assert_non_effective(hybrid_equal, incomplete, first, overlap, second)


def test_fail_static_and_low_efficiency_inhibit_are_absorbing() -> None:
    failed = metadata_loss(
        _state(),
        request_state=RequestReleaseState.RELEASED_PENDING,
        request_sequence=11,
        request_nonce=1111,
        outcome_deadline_expired=True,
    ).state
    assert metadata_loss(
        failed, request_state=RequestReleaseState.UNUSED_ARM
    ).state is failed
    assert degrade_phase_to_fll(failed).state is failed

    retained_first = _state(
        last_application_sequence=1,
        last_first_consumer_frontier=109,
        last_response_frontier=111,
    )
    first = record_completed_low_efficiency(
        retained_first, _episode("fll-1", 1, 110, 120)
    ).state
    retained_second = replace(
        first,
        last_application_sequence=2,
        last_first_consumer_frontier=120,
        last_response_frontier=122,
    )
    inhibited = record_completed_low_efficiency(
        retained_second, _episode("fll-2", 2, 121, 131)
    ).state
    metadata = metadata_loss(
        inhibited, request_state=RequestReleaseState.UNUSED_ARM
    )
    phase = degrade_phase_to_fll(inhibited)
    accepted = accept_released_request(
        inhibited, request_sequence=1, request_nonce=1, outcome_sequence=1
    )
    applied = complete_accepted_application(
        inhibited, AppliedTransaction(1, 1, 1, 1, 0xA83C, 4, 101)
    )
    response = complete_metadata_response_then_hold(
        inhibited,
        request_sequence=1,
        request_nonce=1,
        response_frontier=101,
    )
    assert metadata.state is inhibited
    assert phase.state is inhibited
    assert accepted.state is inhibited
    assert applied.state is inhibited
    assert response.state is inhibited
    _assert_non_effective(metadata, phase, accepted, applied, response)


def test_d9_and_all_optional_faults_remain_local_to_healthy_d14_d8() -> None:
    initial = _state()
    d9 = record_d9_output_status(initial, valid=False, reason="readback_invalid")
    assert d9.state.d14_d8_measurement_healthy
    assert d9.state.mode is OperationalMode.ACTIVE
    assert d9.delivered_output_trial_terminal == "delivered_output_trial_stopped_d9_invalid"
    cases = {
        "d6": ("absent", "stalled", "corrupt", "overflow", "queue_failure"),
        "d10": ("absent", "noise", "invalid", "overflow", "queue_failure"),
        "shadow": (
            "input_drop",
            "output_drop",
            "stale",
            "killed",
            "stalled",
            "delayed",
            "corrupt",
            "rejected",
            "model_infeasible",
        ),
    }
    transitions = [d9]
    for component, faults in cases.items():
        for fault in faults:
            local = contain_local_optional_fault(initial, component=component, fault=fault)
            assert local.state is initial
            assert local.state.d14_d8_measurement_healthy
            transitions.append(local)
    _assert_non_effective(*transitions)
