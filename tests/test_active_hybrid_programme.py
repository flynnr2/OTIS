from __future__ import annotations

from pathlib import Path

import pytest

from host.otis_tools.active_hybrid_evidence_guard import (
    replay_response_before_acknowledgement,
)
from host.otis_tools.active_hybrid_policy import load_policy
from host.otis_tools.active_hybrid_rehearsal import (
    _modeled_transaction,
    _scenario_abort_failure,
    _scenario_clean_degradation,
    _scenario_shared_fault,
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
        "run_identity": "cx320_active_hybrid_12h_v1:3200001",
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
