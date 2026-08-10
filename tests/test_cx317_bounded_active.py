from __future__ import annotations

from dataclasses import replace
import math

import pytest

from host.otis_tools.cx317_bounded_active import (
    ActiveError,
    ActiveState,
    ActiveTransactionEngine,
    AppliedAcknowledgement,
    ControlDecision,
    Eligibility,
    ResponseClass,
    ResponseClassifier,
    load_policy,
)


BUILD_HASH = "b" * 64


def engine(campaign: str = "A") -> ActiveTransactionEngine:
    policy = load_policy()
    return ActiveTransactionEngine(
        policy,
        campaign,
        build_hash=BUILD_HASH,
        session_id=17,
        initial_applied_code=policy.campaigns[campaign].start_code,
    )


def arm(active: ActiveTransactionEngine, now_s: int, sequence: int = 1) -> None:
    spec = active.expected_arm_spec(
        authorization_sequence=sequence,
        nonce=0x12340000 + sequence,
        expires_s=now_s + 60,
    )
    active.arm(spec, Eligibility(), now_s)


def decision(
    active: ActiveTransactionEngine,
    now_s: int,
    *,
    sequence: int = 1,
    delta: int = -21,
    pre_error_hz: float = 0.020,
) -> ControlDecision:
    return ControlDecision(
        decision_sequence=sequence,
        source_first_sequence=1000 + sequence,
        source_last_sequence=1600 + sequence,
        timestamp_s=now_s,
        current_applied_code=active.applied_code,
        requested_delta_codes=delta,
        requested_code=active.applied_code + delta,
        pre_error_hz=pre_error_hz,
    )


def apply(
    active: ActiveTransactionEngine,
    request,
    accepted,
    now_s: int,
    **changes,
) -> None:
    acknowledgement = AppliedAcknowledgement(
        request_sequence=request.request_sequence,
        authorization_sequence=request.authorization_sequence,
        nonce=request.nonce,
        requested_code=request.requested_code,
        accepted_code=accepted.accepted_code,
        applied_code=request.requested_code,
        application_sequence=active.correction_count + 1,
        application_timestamp_s=now_s,
        i2c_ok=True,
    )
    active.acknowledge_application(replace(acknowledgement, **changes))


def successful_step(
    active: ActiveTransactionEngine,
    now_s: int = 2400,
    sequence: int = 1,
    auth_sequence: int = 1,
    post_error_hz: float = 0.0165,
):
    arm(active, now_s, auth_sequence)
    request, accepted = active.transact_decision(
        decision(active, now_s, sequence=sequence), Eligibility(), now_s
    )
    assert request.actionable
    assert not active.pending.request.actionable
    apply(active, request, accepted, now_s)
    response = active.record_response(post_error_hz=post_error_hz)
    return request, accepted, response


def test_policy_locks_master_envelope_and_two_campaigns() -> None:
    policy = load_policy()

    assert policy.maximum_step_codes == 21
    assert policy.minimum_code == 0xA800
    assert policy.maximum_code == 0xAB00
    assert policy.minimum_cadence_s == 1800
    assert policy.settling_exclusion_s == 900
    assert policy.fresh_support_s == 600
    assert policy.full_history_reset_s == 1500
    assert policy.arm_lifetime_s == 120
    assert policy.campaigns["A"].start_code == 0xA950
    assert policy.campaigns["A"].maximum_corrections == 16
    assert policy.campaigns["A"].maximum_cumulative_movement_codes == 336
    assert policy.campaigns["B"].start_code == 0xA800
    assert policy.campaigns["B"].maximum_corrections == 8
    assert policy.campaigns["B"].maximum_cumulative_movement_codes == 168


def test_happy_transaction_consumes_actionability_and_requires_response() -> None:
    active = engine()
    arm(active, 2400)
    request, accepted = active.transact_decision(
        decision(active, 2400), Eligibility(), 2400
    )

    assert request.actionable
    assert not accepted.actionable
    assert active.state is ActiveState.ACCEPTED_AWAITING_APPLICATION
    assert active.status()["actionable"] is False

    apply(active, request, accepted, 2400)
    assert active.state is ActiveState.AWAITING_RESPONSE
    assert active.applied_code == 0xA950 - 21
    assert active.dac_epoch == 1
    assert active.correction_count == 1
    assert active.cumulative_movement_codes == 21

    response = active.record_response(post_error_hz=0.0165)
    assert response.classification is ResponseClass.HEALTHY_DETECTED
    assert active.state is ActiveState.DISARMED
    assert len(active.capsules) == 1
    assert active.capsules[0].request.requested_code == active.applied_code
    assert active.capsules[0].accepted is not None
    assert active.capsules[0].applied is not None
    assert active.capsules[0].response == response


@pytest.mark.parametrize(
    "field",
    [
        field
        for field in Eligibility.__dataclass_fields__
        if field not in {"estimator_valid", "model_applicable", "temperature_valid"}
    ],
)
def test_every_arm_eligibility_gate_blocks_arming(field: str) -> None:
    active = engine()
    health = replace(Eligibility(), **{field: False})
    spec = active.expected_arm_spec(
        authorization_sequence=1, nonce=1, expires_s=2460
    )

    with pytest.raises(ActiveError, match="eligibility"):
        active.arm(spec, health, 2400)
    assert active.state is ActiveState.FAULT
    assert active.applied_code == 0xA950


@pytest.mark.parametrize("field", ["estimator_valid", "model_applicable"])
def test_estimator_and_model_gate_request_but_not_prearm(field: str) -> None:
    active = engine()
    health = replace(Eligibility(), **{field: False})
    spec = active.expected_arm_spec(
        authorization_sequence=1, nonce=1, expires_s=2460
    )
    active.arm(spec, health, 2400)
    assert active.state is ActiveState.ARMED
    with pytest.raises(ActiveError, match="eligibility"):
        active.request(decision(active, 2400), health, 2400)
    assert active.state is ActiveState.FAULT


def test_temperature_is_covariate_not_arm_request_or_response_gate() -> None:
    active = engine()
    health = replace(Eligibility(), temperature_valid=False)
    spec = active.expected_arm_spec(
        authorization_sequence=1, nonce=1, expires_s=2460
    )
    active.arm(spec, health, 2400)
    request, accepted = active.transact_decision(
        decision(active, 2400), health, 2400
    )
    apply(active, request, accepted, 2400)
    response = active.record_response(post_error_hz=0.0165)
    assert response.classification is ResponseClass.HEALTHY_DETECTED
    assert active.state is ActiveState.DISARMED


def test_valid_response_is_preserved_in_out_of_model_hold() -> None:
    active = engine()
    arm(active, 2400)
    request, accepted = active.transact_decision(
        decision(active, 2400), Eligibility(), 2400
    )
    apply(active, request, accepted, 2400)
    response = active.record_response(
        post_error_hz=0.0165,
        measurement_healthy=True,
        control_eligible_after_response=False,
    )
    assert response.classification is ResponseClass.HEALTHY_DETECTED
    assert active.state is ActiveState.OUT_OF_MODEL_HOLD
    assert not active.status()["actionable"]

    next_spec = active.expected_arm_spec(
        authorization_sequence=2, nonce=2, expires_s=4260
    )
    with pytest.raises(ActiveError, match="applicable model"):
        active.arm(
            next_spec,
            replace(Eligibility(), model_applicable=False),
            4200,
        )
    assert active.state is ActiveState.OUT_OF_MODEL_HOLD
    active.arm(next_spec, Eligibility(), 4200)
    assert active.state is ActiveState.ARMED


def test_exact_binding_expiry_duplicate_and_session_change_fail_closed() -> None:
    active = engine()
    valid = active.expected_arm_spec(
        authorization_sequence=1, nonce=1, expires_s=2460
    )
    with pytest.raises(ActiveError, match="binding"):
        active.arm(replace(valid, model_hash="0" * 64), Eligibility(), 2400)

    active = engine()
    with pytest.raises(ActiveError, match="expiry"):
        active.arm(replace(valid, expires_s=3000), Eligibility(), 2400)

    active = engine()
    arm(active, 2400)
    active.note_session_change(18)
    assert active.state is ActiveState.FAULT
    assert not active.status()["armed"]


def test_duplicate_stale_reordered_request_and_zero_delta_do_not_write() -> None:
    active = engine()
    arm(active, 2400)
    active.transact_decision(decision(active, 2400), Eligibility(), 2400)
    with pytest.raises(ActiveError, match="request_without_current_arm"):
        active.request(decision(active, 2400), Eligibility(), 2400)
    assert active.state is ActiveState.FAULT
    assert active.correction_count == 0

    active = engine()
    arm(active, 2400)
    with pytest.raises(ActiveError, match="zero_delta"):
        active.request(decision(active, 2400, delta=0), Eligibility(), 2400)
    assert active.state is ActiveState.DISARMED
    assert active.correction_count == 0


@pytest.mark.parametrize(
    ("change", "reason"),
    [
        ({"requested_code": 0xA950}, "acknowledgement"),
        ({"accepted_code": 0xA950}, "acknowledgement"),
        ({"applied_code": 0xA950}, "acknowledgement"),
        ({"i2c_ok": False}, "acknowledgement"),
        ({"clamped": True}, "acknowledgement"),
        ({"ambiguous": True}, "acknowledgement"),
        ({"application_sequence": 2}, "acknowledgement"),
    ],
)
def test_application_disagreement_failure_timeout_or_ambiguity_latches_fault(
    change: dict, reason: str
) -> None:
    active = engine()
    arm(active, 2400)
    request, accepted = active.transact_decision(
        decision(active, 2400), Eligibility(), 2400
    )

    with pytest.raises(ActiveError, match=reason):
        apply(active, request, accepted, 2400, **change)
    assert active.state is ActiveState.FAULT
    assert active.applied_code == 0xA950
    assert active.correction_count == 0
    assert active.status()["automatic_retry"] is False
    assert active.status()["automatic_restore"] is False


def test_missing_application_acknowledgement_times_out_without_retry() -> None:
    active = engine()
    arm(active, 2400)
    active.transact_decision(decision(active, 2400), Eligibility(), 2400)

    active.note_application_timeout()

    assert active.state is ActiveState.FAULT
    assert active.reason == "application_acknowledgement_timeout"
    assert active.correction_count == 0
    assert not active.status()["actionable"]
    assert not active.status()["automatic_retry"]


def test_step_range_cumulative_count_and_cadence_limits_are_enforced() -> None:
    active = engine()
    arm(active, 2400)
    with pytest.raises(ActiveError, match="step_limit"):
        active.request(decision(active, 2400, delta=-22), Eligibility(), 2400)

    active = engine("B")
    arm(active, 2400)
    with pytest.raises(ActiveError, match="outside_hard_range"):
        active.request(decision(active, 2400, delta=-1), Eligibility(), 2400)

    active = engine()
    successful_step(active)
    arm(active, 3000, 2)
    with pytest.raises(ActiveError, match="cadence"):
        active.request(
            decision(active, 3000, sequence=2), Eligibility(), 3000
        )

    active = engine()
    active.cumulative_movement_codes = 336
    arm(active, 2400)
    with pytest.raises(ActiveError, match="cumulative"):
        active.request(decision(active, 2400, delta=-1), Eligibility(), 2400)

    active = engine()
    active.correction_count = 16
    spec = active.expected_arm_spec(
        authorization_sequence=1, nonce=1, expires_s=2460
    )
    with pytest.raises(ActiveError, match="correction_count"):
        active.arm(spec, Eligibility(), 2400)


def test_abort_is_device_side_latched_and_never_restores() -> None:
    active = engine()
    arm(active, 2400)
    active.abort()

    assert active.state is ActiveState.ABORTED
    assert active.applied_code == 0xA950
    assert not active.status()["armed"]
    assert not active.status()["actionable"]
    assert active.status()["automatic_restore"] is False
    with pytest.raises(ActiveError, match="latched"):
        arm(active, 2500, 2)


def classify(pre: float, post: float, delta: int = -21, **kwargs):
    return ResponseClassifier().classify(
        pre_error_hz=pre,
        post_error_hz=post,
        applied_delta_codes=delta,
        current_code=0xA950 + delta,
        minimum_code=0xA800,
        maximum_code=0xAB00,
        **kwargs,
    )


def test_response_classifier_covers_frozen_classes() -> None:
    assert classify(0.020, 0.0165).classification is ResponseClass.HEALTHY_DETECTED
    assert classify(0.010, 0.0060).classification is ResponseClass.INSIDE_DEADBAND
    assert classify(0.020, 0.019).classification is ResponseClass.HEALTHY_INDETERMINATE
    assert classify(0.020, 0.024).classification is ResponseClass.WRONG_SIGN
    assert classify(0.020, 0.008).classification is ResponseClass.EXCESS_RESPONSE
    assert classify(0.020, 0.030, delta=21).classification is ResponseClass.GROWING_ERROR
    assert classify(0.020, math.nan).classification is ResponseClass.MEASUREMENT_OR_ACTUATOR_FAULT

    limited = ResponseClassifier().classify(
        pre_error_hz=0.020,
        post_error_hz=0.018,
        applied_delta_codes=-1,
        current_code=0xA800,
        minimum_code=0xA800,
        maximum_code=0xAB00,
    )
    assert limited.classification is ResponseClass.LIMIT_REACHED


def test_stage5_response_replay_disables_only_legacy_float_deadband() -> None:
    legacy = ResponseClassifier().classify(
        pre_error_hz=0.001,
        post_error_hz=0.005,
        applied_delta_codes=21,
        current_code=0xA81D,
        minimum_code=0xA800,
        maximum_code=0xAB00,
    )
    stage5 = ResponseClassifier(
        legacy_response_deadband_enabled=False
    ).classify(
        pre_error_hz=0.001,
        post_error_hz=0.005,
        applied_delta_codes=21,
        current_code=0xA81D,
        minimum_code=0xA800,
        maximum_code=0xAB00,
    )
    assert legacy.classification is ResponseClass.INSIDE_DEADBAND
    assert stage5.classification is ResponseClass.HEALTHY_DETECTED
    assert stage5.reason == "response_detected_with_commanded_sign"


def test_cumulative_indeterminate_detection_and_persistent_absence() -> None:
    classifier = ResponseClassifier()
    first = classifier.classify(
        pre_error_hz=0.030,
        post_error_hz=0.029,
        applied_delta_codes=-21,
        current_code=0xA950 - 21,
        minimum_code=0xA800,
        maximum_code=0xAB00,
    )
    second = classifier.classify(
        pre_error_hz=0.029,
        post_error_hz=0.027,
        applied_delta_codes=-21,
        current_code=0xA950 - 42,
        minimum_code=0xA800,
        maximum_code=0xAB00,
    )
    assert first.classification is ResponseClass.HEALTHY_INDETERMINATE
    assert second.classification is ResponseClass.HEALTHY_INDETERMINATE

    classifier = ResponseClassifier()
    results = []
    pre = 0.030
    for index in range(3):
        post = pre - 0.0001
        results.append(
            classifier.classify(
                pre_error_hz=pre,
                post_error_hz=post,
                applied_delta_codes=-21,
                current_code=0xA950 - 21 * (index + 1),
                minimum_code=0xA800,
                maximum_code=0xAB00,
            )
        )
        pre = post
    assert results[-1].classification is ResponseClass.MEASUREMENT_OR_ACTUATOR_FAULT


def test_lost_transaction_evidence_faults_but_droppable_telemetry_is_not_a_gate() -> None:
    active = engine()
    spec = active.expected_arm_spec(
        authorization_sequence=1, nonce=1, expires_s=2460
    )
    with pytest.raises(ActiveError, match="eligibility"):
        active.arm(
            spec,
            replace(Eligibility(), transaction_evidence_available=False),
            2400,
        )

    # Ordinary formatted telemetry backlog is deliberately absent from the
    # eligibility model; non-droppable transaction evidence is the safety gate.
    active = engine()
    arm(active, 2400)
    request = active.request(decision(active, 2400), Eligibility(), 2400)
    assert request.actionable
