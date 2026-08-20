from __future__ import annotations

from pathlib import Path

import pytest

from host.otis_tools.active_hybrid_evidence_guard import (
    replay_response_before_acknowledgement,
)
from host.otis_tools.active_hybrid_policy import ActiveHybridController, load_policy
from host.otis_tools.active_hybrid_rehearsal import (
    _ahy_row,
    _modeled_transaction,
    _observation,
    _scenario_abort_failure,
    _scenario_clean_degradation,
    _scenario_shared_fault,
    _transaction_rows,
    _write_csv,
)
from host.otis_tools.active_hybrid_supervisor import (
    ActiveHybridSupervisor,
    SupervisorContractError,
)
from host.otis_tools.contracts import (
    ACTIVE_HYBRID_DECISION_V1_FIELDS,
    CONTRACT_FIELDS,
    CsvValidationContext,
    validate_csv,
)


def _bundle() -> dict[str, object]:
    policy = load_policy()
    return {
        "run_identity": "cx320_active_hybrid:3200001",
        "bundle_sha256": "b" * 64,
        "policy": {"policy_sha256": policy.policy_sha256},
        "firmware": {"build_identity": "a" * 64 + ":" + "c" * 64},
        "setup": {
            "consumer_epoch_propagation_required": [
                "frequency_estimator",
                "phase_estimator",
                "controller",
                "preview_replay",
                "recorder",
                "response_classifier",
            ]
        },
    }


def test_accelerated_path_exercises_material_checkpoint_and_shared_budget(
    tmp_path: Path,
) -> None:
    primary, ahy_rows, transaction_rows = _modeled_transaction(_bundle())
    assert primary["frequency_only_application_count"] == 1
    assert primary["phase_nonzero_application_count"] == 2
    assert primary["phase_material_application_count"] == 2
    assert primary["correction_count"] == 3
    assert primary["cumulative_movement_codes"] == 28
    assert primary["later_authority_released"] is True
    assert primary["request_outstanding"] is False
    assert primary["response_outstanding"] is False

    ahy_path = tmp_path / "active_hybrid_decisions_v1.csv"
    act_path = tmp_path / "active_transactions_v1.csv"
    _write_csv(ahy_path, ACTIVE_HYBRID_DECISION_V1_FIELDS, ahy_rows)
    _write_csv(act_path, CONTRACT_FIELDS["active_transactions_v1"], transaction_rows)
    assert validate_csv(
        ahy_path,
        CsvValidationContext("active_hybrid_decisions_v1", frozenset(), frozenset()),
    ).ok
    assert validate_csv(
        act_path,
        CsvValidationContext("active_transactions_v1", frozenset(), frozenset()),
    ).ok

    material = next(row for row in ahy_rows if row["phase_materially_influenced"] == "true")
    response = next(
        row
        for row in transaction_rows
        if row["event"] == "response"
        and row["decision_sequence"] == material["decision_sequence"]
    )
    attestation = replay_response_before_acknowledgement(
        active_hybrid_csv=ahy_path,
        active_transactions_csv=act_path,
        response_row=response,
    )
    assert attestation["exact_replay"] is True
    assert attestation["phase_materially_influenced"] is True
    assert attestation["response_class"] == "inside_deadband"
    assert attestation["predicted_sign_observed"] is True


def test_phase_degradation_and_transport_faults_are_distinct() -> None:
    bundle = _bundle()
    degradation = _scenario_clean_degradation(bundle)
    shared_fault = _scenario_shared_fault(bundle)
    abort_failure = _scenario_abort_failure(bundle)
    assert degradation["state"] == "PHASE_DEGRADED_FREQUENCY_ONLY"
    assert degradation["request_outstanding"] is False
    assert shared_fault["terminal_reason"] == "transport_obstruction_shared_fault"
    assert shared_fault["abort_submitted"] is True
    assert shared_fault["abort_delivered"] is True
    assert abort_failure["terminal_reason"] == "failed_priority_abort_delivery"
    assert abort_failure["abort_delivered"] is False
    assert abort_failure["capture_close_rejected_before_delivery"] is True


def test_owner_cannot_close_before_abort_delivery() -> None:
    supervisor = ActiveHybridSupervisor(
        run_identity="run",
        bundle_sha256="b" * 64,
        policy_sha256="p" * 64,
        build_identity="s" * 64 + ":" + "c" * 64,
    )
    supervisor.establish_capture(owner="owner")
    supervisor.fail_static("injected")
    supervisor.submit_priority_abort()
    with pytest.raises(SupervisorContractError, match="before priority abort delivery"):
        supervisor.close_capture(owner="owner", logical_rotation=True)


def test_response_guard_rejects_changed_firmware_delta(tmp_path: Path) -> None:
    _, ahy_rows, transaction_rows = _modeled_transaction(_bundle())
    material = next(row for row in ahy_rows if row["phase_materially_influenced"] == "true")
    material["requested_delta_codes"] = str(int(material["requested_delta_codes"]) - 1)
    material["requested_code"] = str(
        int(material["current_applied_code"]) + int(material["requested_delta_codes"])
    )
    ahy_path = tmp_path / "active_hybrid_decisions_v1.csv"
    act_path = tmp_path / "active_transactions_v1.csv"
    _write_csv(ahy_path, ACTIVE_HYBRID_DECISION_V1_FIELDS, ahy_rows)
    _write_csv(act_path, CONTRACT_FIELDS["active_transactions_v1"], transaction_rows)
    response = next(
        row
        for row in transaction_rows
        if row["event"] == "response"
        and row["decision_sequence"] == material["decision_sequence"]
    )
    with pytest.raises(ValueError, match="independent host replay differs"):
        replay_response_before_acknowledgement(
            active_hybrid_csv=ahy_path,
            active_transactions_csv=act_path,
            response_row=response,
        )


def test_response_guard_replays_nonzero_frequency_only_counterfactual(
    tmp_path: Path,
) -> None:
    policy = load_policy()
    controller = ActiveHybridController(policy)
    first = controller.decide(
        _observation(
            controller,
            timestamp_s=1800,
            sequence=1800,
            frequency_error_hz=0.0,
            counts=0,
            tight_state="TIGHT_INSIDE",
            relative_phase_cycles=-24,
        )
    )
    decision = controller.decide(
        _observation(
            controller,
            timestamp_s=3600,
            sequence=3600,
            frequency_error_hz=-0.001,
            counts=-1,
            tight_state="TIGHT_INSIDE",
            relative_phase_cycles=-24,
        )
    )
    run_identity = "cx320_active_hybrid:3200001"
    build_identity = "a" * 64 + ":" + "c" * 64
    ahy_rows = [
        _ahy_row(
            first,
            record_sequence=1,
            run_identity=run_identity,
            build_identity=build_identity,
            policy_sha256=policy.policy_sha256,
            response_policy_sha256=policy.response_policy_sha256,
        ),
        _ahy_row(
            decision,
            record_sequence=2,
            run_identity=run_identity,
            build_identity=build_identity,
            policy_sha256=policy.policy_sha256,
            response_policy_sha256=policy.response_policy_sha256,
        )
    ]
    transaction_rows = _transaction_rows(
        decision,
        record_sequence=1,
        request_sequence=1,
        application_sequence=1,
        dac_epoch=2,
        cumulative_movement=abs(decision.requested_delta_codes),
        run_identity=run_identity,
        build_identity=build_identity,
        policy_sha256=policy.policy_sha256,
        estimator_sha256=policy.frequency_estimator_sha256,
        model_sha256=policy.plant_model_sha256,
        response_policy_sha256=policy.response_policy_sha256,
    )
    controller.note_application(
        decision,
        applied_code=int(transaction_rows[2]["applied_code"]),
        dac_epoch=int(transaction_rows[2]["dac_epoch"]),
        downstream_consumers_exact=True,
    )
    response_timestamp = int(transaction_rows[2]["application_timestamp_s"]) + (
        policy.settling_exclusion_s + policy.fresh_support_s
    )
    response_decision = controller.decide(
        _observation(
            controller,
            timestamp_s=response_timestamp,
            sequence=response_timestamp,
            frequency_error_hz=float(transaction_rows[-1]["post_error_hz"]),
            counts=round(float(transaction_rows[-1]["post_error_hz"]) * 600),
            tight_state="TIGHT_INSIDE",
            relative_phase_cycles=-24,
            outstanding_response=True,
        )
    )
    response_ahy = _ahy_row(
        response_decision,
        record_sequence=3,
        run_identity=run_identity,
        build_identity=build_identity,
        policy_sha256=policy.policy_sha256,
        response_policy_sha256=policy.response_policy_sha256,
    )
    response_ahy.update(
        {
            "authority_state": "AWAITING_RESPONSE",
            "request_sequence": "1",
            "acceptance_sequence": "1",
            "application_sequence": "1",
        }
    )
    ahy_rows.append(response_ahy)
    ahy_path = tmp_path / "active_hybrid_decisions_v1.csv"
    act_path = tmp_path / "active_transactions_v1.csv"
    _write_csv(ahy_path, ACTIVE_HYBRID_DECISION_V1_FIELDS, ahy_rows)
    _write_csv(act_path, CONTRACT_FIELDS["active_transactions_v1"], transaction_rows)
    response = transaction_rows[-1]

    attestation = replay_response_before_acknowledgement(
        active_hybrid_csv=ahy_path,
        active_transactions_csv=act_path,
        response_row=response,
    )
    assert attestation["counterfactual_frequency_only_delta_codes"] == 3
    assert attestation["requested_delta_codes"] == 6

    ahy_rows[1]["counterfactual_frequency_only_delta_codes"] = "0"
    ahy_path.unlink()
    _write_csv(ahy_path, ACTIVE_HYBRID_DECISION_V1_FIELDS, ahy_rows)
    with pytest.raises(ValueError, match="independent host replay differs"):
        replay_response_before_acknowledgement(
            active_hybrid_csv=ahy_path,
            active_transactions_csv=act_path,
            response_row=response,
        )


def test_response_guard_replays_tight_loss_as_frequency_only(
    tmp_path: Path,
) -> None:
    policy = load_policy()
    controller = ActiveHybridController(policy)
    first = controller.decide(
        _observation(
            controller,
            timestamp_s=1800,
            sequence=1800,
            frequency_error_hz=0.0,
            counts=0,
            tight_state="TIGHT_INSIDE",
            relative_phase_cycles=720,
        )
    )
    decision = controller.decide(
        _observation(
            controller,
            timestamp_s=3600,
            sequence=3600,
            frequency_error_hz=0.01,
            counts=6,
            tight_state="OUTSIDE",
            relative_phase_cycles=720,
        )
    )
    assert (decision.state_before, decision.state_after) == (
        "PHASE_QUALIFY",
        "FREQUENCY_ACQUIRE",
    )
    assert decision.phase_term_hz == 0.0
    assert decision.requested_delta_codes == -21

    run_identity = "cx320_active_hybrid:3200001"
    build_identity = "a" * 64 + ":" + "c" * 64
    rows = [
        _ahy_row(
            item,
            record_sequence=index,
            run_identity=run_identity,
            build_identity=build_identity,
            policy_sha256=policy.policy_sha256,
            response_policy_sha256=policy.response_policy_sha256,
        )
        for index, item in enumerate((first, decision), start=1)
    ]
    transactions = _transaction_rows(
        decision,
        record_sequence=1,
        request_sequence=1,
        application_sequence=1,
        dac_epoch=2,
        cumulative_movement=21,
        run_identity=run_identity,
        build_identity=build_identity,
        policy_sha256=policy.policy_sha256,
        estimator_sha256=policy.frequency_estimator_sha256,
        model_sha256=policy.plant_model_sha256,
        response_policy_sha256=policy.response_policy_sha256,
    )
    controller.note_application(
        decision,
        applied_code=int(transactions[2]["applied_code"]),
        dac_epoch=2,
        downstream_consumers_exact=True,
    )
    response_timestamp = int(transactions[2]["application_timestamp_s"]) + (
        policy.settling_exclusion_s + policy.fresh_support_s
    )
    response_decision = controller.decide(
        _observation(
            controller,
            timestamp_s=response_timestamp,
            sequence=response_timestamp,
            frequency_error_hz=float(transactions[-1]["post_error_hz"]),
            counts=round(float(transactions[-1]["post_error_hz"]) * 600),
            tight_state="OUTSIDE",
            relative_phase_cycles=720,
            outstanding_response=True,
        )
    )
    response_ahy = _ahy_row(
        response_decision,
        record_sequence=3,
        run_identity=run_identity,
        build_identity=build_identity,
        policy_sha256=policy.policy_sha256,
        response_policy_sha256=policy.response_policy_sha256,
    )
    response_ahy.update(
        {
            "authority_state": "AWAITING_RESPONSE",
            "request_sequence": "1",
            "acceptance_sequence": "1",
            "application_sequence": "1",
        }
    )
    rows.append(response_ahy)
    ahy_path = tmp_path / "active_hybrid_decisions_v1.csv"
    act_path = tmp_path / "active_transactions_v1.csv"
    _write_csv(ahy_path, ACTIVE_HYBRID_DECISION_V1_FIELDS, rows)
    _write_csv(act_path, CONTRACT_FIELDS["active_transactions_v1"], transactions)

    attestation = replay_response_before_acknowledgement(
        active_hybrid_csv=ahy_path,
        active_transactions_csv=act_path,
        response_row=transactions[-1],
    )
    assert attestation["exact_replay"] is True
    assert attestation["phase_materially_influenced"] is False
    assert attestation["requested_delta_codes"] == -21


def test_inside_deadband_checkpoint_still_requires_observed_command_sign(
    tmp_path: Path,
) -> None:
    _, rows, transactions = _modeled_transaction(_bundle())
    material = next(row for row in rows if row["phase_materially_influenced"] == "true")
    response = next(
        row
        for row in transactions
        if row["event"] == "response"
        and row["decision_sequence"] == material["decision_sequence"]
    )
    assert response["response_class"] == "inside_deadband"
    response["observed_response_hz"] = "0.000000000000"
    ahy_path = tmp_path / "active_hybrid_decisions_v1.csv"
    act_path = tmp_path / "active_transactions_v1.csv"
    _write_csv(ahy_path, ACTIVE_HYBRID_DECISION_V1_FIELDS, rows)
    _write_csv(act_path, CONTRACT_FIELDS["active_transactions_v1"], transactions)

    with pytest.raises(ValueError, match="independent host replay differs"):
        replay_response_before_acknowledgement(
            active_hybrid_csv=ahy_path,
            active_transactions_csv=act_path,
            response_row=response,
        )
