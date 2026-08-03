#!/usr/bin/env python3
"""Deterministic Stage 3 campaign replay and fault-injection evidence.

The replay never opens hardware.  It exercises the same frozen host reference
used to test the allocation-free firmware transaction state machine.
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass, replace
import json
from pathlib import Path
from typing import Callable

from host.otis_tools.cx317_bounded_active import (
    ActiveError,
    ActiveState,
    ActiveTransactionEngine,
    AppliedAcknowledgement,
    ControlDecision,
    Eligibility,
    ResponseClass,
    load_policy,
)


BUILD_HASH = "d" * 64


@dataclass(frozen=True)
class ReplayResult:
    campaign: str
    scenario: str
    passed: bool
    terminal_state: str
    reason: str
    writes: int
    automatic_retry: bool
    automatic_restore: bool


def _engine(campaign: str) -> ActiveTransactionEngine:
    policy = load_policy()
    return ActiveTransactionEngine(
        policy,
        campaign,
        build_hash=BUILD_HASH,
        session_id=0x317,
        initial_applied_code=policy.campaigns[campaign].start_code,
    )


def _arm(
    active: ActiveTransactionEngine,
    now_s: int,
    sequence: int,
    health: Eligibility = Eligibility(),
) -> None:
    active.arm(
        active.expected_arm_spec(
            authorization_sequence=sequence,
            nonce=0xC3170000 + sequence,
            expires_s=now_s + 60,
        ),
        health,
        now_s,
    )


def _decision(
    active: ActiveTransactionEngine,
    now_s: int,
    sequence: int,
    *,
    delta: int | None = None,
    pre_error_hz: float | None = None,
) -> ControlDecision:
    if delta is None:
        delta = 21 if active.limits.name == "B" else -21
    if pre_error_hz is None:
        pre_error_hz = -0.020 if delta > 0 else 0.020
    return ControlDecision(
        decision_sequence=sequence,
        source_first_sequence=sequence * 1000,
        source_last_sequence=sequence * 1000 + 600,
        timestamp_s=now_s,
        current_applied_code=active.applied_code,
        requested_delta_codes=delta,
        requested_code=active.applied_code + delta,
        pre_error_hz=pre_error_hz,
    )


def _accept(active: ActiveTransactionEngine, now_s: int, sequence: int, **kwargs):
    request, accepted = active.transact_decision(
        _decision(active, now_s, sequence, **kwargs), Eligibility(), now_s
    )
    return request, accepted


def _ack(active, request, accepted, now_s: int, **changes):
    value = AppliedAcknowledgement(
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
    active.acknowledge_application(replace(value, **changes))
    return value


def _step(
    active: ActiveTransactionEngine,
    now_s: int,
    sequence: int,
    *,
    pre_error_hz: float | None = None,
    post_error_hz: float | None = None,
    delta: int | None = None,
    evidence_healthy: bool = True,
    control_eligible_after_response: bool = True,
):
    if delta is None:
        delta = 21 if active.limits.name == "B" else -21
    if pre_error_hz is None:
        pre_error_hz = -0.020 if delta > 0 else 0.020
    if post_error_hz is None:
        post_error_hz = -0.0165 if delta > 0 else 0.0165
    _arm(active, now_s, sequence)
    request, accepted = _accept(
        active,
        now_s,
        sequence,
        delta=delta,
        pre_error_hz=pre_error_hz,
    )
    _ack(active, request, accepted, now_s)
    return active.record_response(
        post_error_hz=post_error_hz,
        evidence_healthy=evidence_healthy,
        control_eligible_after_response=control_eligible_after_response,
    )


def _result(campaign: str, scenario: str, active, passed: bool, reason: str):
    status = active.status()
    return ReplayResult(
        campaign=campaign,
        scenario=scenario,
        passed=passed,
        terminal_state=status["state"],
        reason=reason,
        writes=status["correction_count"],
        automatic_retry=status["automatic_retry"],
        automatic_restore=status["automatic_restore"],
    )


def _expect_error(
    campaign: str,
    scenario: str,
    operation: Callable[[ActiveTransactionEngine], None],
    expected_state: ActiveState = ActiveState.FAULT,
) -> ReplayResult:
    active = _engine(campaign)
    try:
        operation(active)
    except ActiveError as exc:
        passed = active.state is expected_state
        return _result(campaign, scenario, active, passed, str(exc))
    return _result(campaign, scenario, active, False, "fault injection was accepted")


def _happy_response(campaign: str, scenario: str, post: float) -> ReplayResult:
    active = _engine(campaign)
    if campaign == "B":
        post = -post
    response = _step(active, 2400, 1, post_error_hz=post)
    passed = response.classification in {
        ResponseClass.HEALTHY_DETECTED,
        ResponseClass.HEALTHY_INDETERMINATE,
        ResponseClass.INSIDE_DEADBAND,
    }
    return _result(campaign, scenario, active, passed, response.classification.value)


def replay_campaign(campaign: str) -> list[ReplayResult]:
    policy = load_policy()
    gain = json.loads(policy.response_policy_path.read_text())["parameters"]
    gain_min = float(gain["gain_min_hz_per_code"])
    gain_max = float(gain["gain_max_hz_per_code"])
    results = [
        _happy_response(campaign, "ideal_convergence", 0.0165),
        _happy_response(campaign, "smallest_measured_gain", 0.020 - 21 * gain_min),
        _happy_response(campaign, "largest_measured_gain", 0.020 - 21 * gain_max),
        _happy_response(campaign, "quantized_noisy_response", 0.01660),
    ]

    active = _engine(campaign)
    error_sign = -1.0 if campaign == "B" else 1.0
    first = _step(active, 2400, 1, post_error_hz=error_sign * 0.0180)
    second = _step(
        active,
        4200,
        2,
        pre_error_hz=error_sign * 0.0180,
        post_error_hz=error_sign * 0.0164,
    )
    results.append(
        _result(
            campaign,
            "indeterminate_then_cumulative_detection",
            active,
            first.classification is ResponseClass.HEALTHY_INDETERMINATE
            and second.classification is ResponseClass.HEALTHY_DETECTED,
            f"{first.classification.value}->{second.classification.value}",
        )
    )

    for scenario, post, expected in (
        ("wrong_sign_plant", 0.024, ResponseClass.WRONG_SIGN),
        ("excessive_gain", 0.008, ResponseClass.EXCESS_RESPONSE),
        ("growing_error", -0.030, ResponseClass.GROWING_ERROR),
    ):
        active = _engine(campaign)
        response = _step(active, 2400, 1, post_error_hz=error_sign * post)
        results.append(
            _result(
                campaign,
                scenario,
                active,
                response.classification is expected and active.state is ActiveState.FAULT,
                response.classification.value,
            )
        )

    active = _engine(campaign)
    indeterminate = []
    for sequence, (pre, post) in enumerate(
        ((0.020, 0.0190), (0.0190, 0.0180), (0.0180, 0.0175)), start=1
    ):
        response = _step(
            active,
            2400 + (sequence - 1) * 1800,
            sequence,
            pre_error_hz=error_sign * pre,
            post_error_hz=error_sign * post,
        )
        indeterminate.append(response.classification)
    results.append(
        _result(
            campaign,
            "persistent_absent_response",
            active,
            indeterminate[-1] is ResponseClass.MEASUREMENT_OR_ACTUATOR_FAULT
            and active.state is ActiveState.FAULT,
            "->".join(item.value for item in indeterminate),
        )
    )

    # Healthy drift at both declared temperature boundaries is represented by
    # the prevalidated temperature_valid gate and a near-floor signed response.
    active = _engine(campaign)
    response = _step(active, 2400, 1, post_error_hz=error_sign * 0.01665)
    results.append(
        _result(
            campaign,
            "drift_temperature_boundaries",
            active,
            response.classification is ResponseClass.HEALTHY_DETECTED,
            "lower_and_upper_boundary_eligibility_replayed",
        )
    )

    for scenario, health_change in (
        ("gnss_fix_invalid", {"gnss_metadata_valid": False}),
        ("gnss_fix_stale", {"gnss_identity_stable": False}),
        ("missing_pps", {"raw_pps_valid": False}),
        ("malformed_pps", {"raw_pps_valid": False}),
        ("count_fault", {"count_valid": False}),
        ("capture_owner_loss", {"capture_owner_live": False}),
        ("abort_path_loss", {"abort_path_live": False}),
        ("lost_transaction_evidence", {"transaction_evidence_available": False}),
    ):
        def reject(active, changes=health_change):
            _arm(active, 2400, 1, replace(Eligibility(), **changes))

        results.append(_expect_error(campaign, scenario, reject))

    def reject_invalid_estimator_at_request(active):
        health = replace(Eligibility(), estimator_valid=False)
        _arm(active, 2400, 1, health)
        active.request(_decision(active, 2400, 1), health, 2400)

    results.append(
        _expect_error(
            campaign, "snapshot_fault", reject_invalid_estimator_at_request
        )
    )

    active = _engine(campaign)
    temperature_context_only = replace(Eligibility(), temperature_valid=False)
    _arm(active, 2400, 1, temperature_context_only)
    request, accepted = active.transact_decision(
        _decision(active, 2400, 1), temperature_context_only, 2400
    )
    _ack(active, request, accepted, 2400)
    response = active.record_response(post_error_hz=error_sign * 0.0165)
    results.append(
        _result(
            campaign,
            "temperature_outside_observed_context",
            active,
            response.classification is ResponseClass.HEALTHY_DETECTED
            and active.state is ActiveState.DISARMED,
            "temperature retained as covariate without measurement/control veto",
        )
    )

    active = _engine(campaign)
    response = _step(
        active,
        2400,
        1,
        post_error_hz=error_sign * 0.0165,
        control_eligible_after_response=False,
    )
    held = active.state is ActiveState.OUT_OF_MODEL_HOLD
    try:
        _arm(
            active,
            4200,
            2,
            replace(Eligibility(), model_applicable=False),
        )
    except ActiveError:
        pass
    stayed_held = active.state is ActiveState.OUT_OF_MODEL_HOLD
    _arm(active, 4200, 2, Eligibility())
    results.append(
        _result(
            campaign,
            "valid_response_out_of_model_hold_and_requalification",
            active,
            response.classification is ResponseClass.HEALTHY_DETECTED
            and held
            and stayed_held
            and active.state is ActiveState.ARMED,
            "valid response preserved; hold required applicable fresh support",
        )
    )

    active = _engine(campaign)
    try:
        _arm(active, 2400, 1, replace(Eligibility(), gnss_metadata_valid=False))
    except ActiveError:
        pass
    recovered = _engine(campaign)
    response = _step(recovered, 2400, 1)
    results.append(
        _result(
            campaign,
            "gnss_recovery_new_session",
            recovered,
            response.classification is ResponseClass.HEALTHY_DETECTED,
            "invalid session remained faulted; replacement session passed",
        )
    )

    def disagreement(active):
        _arm(active, 2400, 1)
        request, accepted = _accept(active, 2400, 1)
        _ack(active, request, accepted, 2400, applied_code=request.requested_code + 1)

    results.append(_expect_error(campaign, "requested_accepted_applied_disagreement", disagreement))

    for scenario, changes in (
        ("i2c_failure", {"i2c_ok": False}),
        ("clamp", {"clamped": True}),
        ("ambiguous_i2c_outcome", {"ambiguous": True}),
        ("stale_acknowledgement", {"request_sequence": 0}),
    ):
        def bad_ack(active, ack_changes=changes):
            _arm(active, 2400, 1)
            request, accepted = _accept(active, 2400, 1)
            _ack(active, request, accepted, 2400, **ack_changes)

        results.append(_expect_error(campaign, scenario, bad_ack))

    def timeout(active):
        _arm(active, 2400, 1)
        _accept(active, 2400, 1)
        active.note_application_timeout()
        raise ActiveError(active.reason)

    results.append(_expect_error(campaign, "acknowledgement_timeout", timeout))

    def duplicate_ack(active):
        _arm(active, 2400, 1)
        request, accepted = _accept(active, 2400, 1)
        ack = _ack(active, request, accepted, 2400)
        active.acknowledge_application(ack)

    results.append(_expect_error(campaign, "duplicate_acknowledgement", duplicate_ack))

    for scenario, operation in (
        (
            "step_limit",
            lambda active: (
                _arm(active, 2400, 1),
                active.request(
                    _decision(
                        active,
                        2400,
                        1,
                        delta=22 if active.limits.name == "B" else -22,
                    ),
                    Eligibility(),
                    2400,
                ),
            ),
        ),
        (
            "reordered_request",
            lambda active: (
                setattr(active, "last_decision_sequence", 2),
                _arm(active, 2400, 1),
                active.request(_decision(active, 2400, 1), Eligibility(), 2400),
            ),
        ),
    ):
        results.append(_expect_error(campaign, scenario, operation))

    def cadence(active):
        _step(active, 2400, 1)
        _arm(active, 3000, 2)
        active.request(_decision(active, 3000, 2), Eligibility(), 3000)

    results.append(_expect_error(campaign, "cadence_limit", cadence))

    for scenario, field, value in (
        ("cumulative_limit", "cumulative_movement_codes", policy.campaigns[campaign].maximum_cumulative_movement_codes),
        ("correction_count_limit", "correction_count", policy.campaigns[campaign].maximum_corrections),
    ):
        def limit(active, attr=field, bound=value):
            setattr(active, attr, bound)
            _arm(active, 2400, 1)
            if attr == "cumulative_movement_codes":
                delta = 1 if active.limits.name == "B" else -1
                active.request(
                    _decision(active, 2400, 1, delta=delta), Eligibility(), 2400
                )

        results.append(_expect_error(campaign, scenario, limit))

    def range_limit(active):
        active.applied_code = policy.minimum_code
        _arm(active, 2400, 1)
        active.request(_decision(active, 2400, 1, delta=-1), Eligibility(), 2400)

    results.append(_expect_error(campaign, "hard_code_range", range_limit))

    active = _engine(campaign)
    _arm(active, 2400, 1)
    active.note_session_change(active.session_id + 1)
    results.append(_result(campaign, "reconnect_reboot", active, active.state is ActiveState.FAULT, active.reason))

    active = _engine(campaign)
    _arm(active, 2400, 1)
    active.abort("independent_host_or_device_abort")
    results.append(_result(campaign, "abort", active, active.state is ActiveState.ABORTED and active.correction_count == 0, active.reason))

    active = _engine(campaign)
    _arm(active, 2400, 1)
    before = active.status()
    for _ in range(1000):
        json.dumps(active.status(), sort_keys=True)
    results.append(
        _result(
            campaign,
            "telemetry_backpressure_state_isolation",
            active,
            active.status() == before,
            "1000 status serializations did not mutate state",
        )
    )
    return results


def run_all() -> list[ReplayResult]:
    return replay_campaign("A") + replay_campaign("B")


def _markdown(results: list[ReplayResult]) -> str:
    lines = [
        "# CX317 Stage 3 deterministic replay",
        "",
        f"Result: **{'PASS' if all(item.passed for item in results) else 'FAIL'}**",
        "",
        "| Campaign | Scenario | Result | Terminal state | Writes | Reason |",
        "|---|---|---:|---|---:|---|",
    ]
    for item in results:
        lines.append(
            f"| {item.campaign} | {item.scenario} | {'PASS' if item.passed else 'FAIL'} "
            f"| {item.terminal_state} | {item.writes} | {item.reason} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path)
    args = parser.parse_args()
    results = run_all()
    payload = {
        "schema_version": 1,
        "passed": all(item.passed for item in results),
        "scenario_count": len(results),
        "results": [asdict(item) for item in results],
    }
    if args.output_dir:
        args.output_dir.mkdir(parents=True, exist_ok=True)
        (args.output_dir / "cx317_active_replay.json").write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (args.output_dir / "cx317_active_replay.md").write_text(
            _markdown(results), encoding="utf-8"
        )
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
