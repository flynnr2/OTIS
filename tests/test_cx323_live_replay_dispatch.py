from __future__ import annotations

import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from host.otis_tools import active_hybrid_evidence_guard as evidence_guard
from host.otis_tools.active_hybrid_evidence_guard import (
    replay_cx323_maintenance_history,
)
from host.otis_tools.active_hybrid_policy import (
    CX323Observation,
    CX323PhasePriorityController,
    load_cx323_policy,
)
from host.otis_tools.active_hybrid_programme_contract import (
    CX323_D9_D6_72H_PROGRAMME,
)


def _state(controller: CX323PhasePriorityController) -> str:
    if controller.fail_static_reason:
        return "FAIL_STATIC"
    if controller.metadata_hold:
        return "METADATA_HOLD"
    if controller.response_pending:
        return "RESPONSE_PENDING"
    if controller.request_pending:
        return "REQUEST_PENDING"
    if controller.persistence_count:
        return "PERSISTENCE_HOLD"
    return "READY"


def _snapshot(controller: CX323PhasePriorityController, suffix: str) -> dict[str, str]:
    return {
        f"maintenance_state_{suffix}": _state(controller),
        f"committed_fll_debt_{suffix}_picocodes": str(
            controller.debt.fll_picocodes
        ),
        f"committed_pll_debt_{suffix}_picocodes": str(
            controller.debt.pll_picocodes
        ),
        f"request_pending_{suffix}": str(controller.request_pending).lower(),
        f"response_pending_{suffix}": str(controller.response_pending).lower(),
        f"metadata_hold_{suffix}": str(controller.metadata_hold).lower(),
        f"persistence_count_{suffix}": str(controller.persistence_count),
        f"requalification_window_count_{suffix}": str(
            controller.requalification_window_count
        ),
    }


def _exact_cx323_lifecycle() -> tuple[
    list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]
]:
    programme = CX323_D9_D6_72H_PROGRAMME
    policy = load_cx323_policy(programme.policy_path)
    policy_document = json.loads(programme.policy_path.read_text(encoding="utf-8"))
    estimator_sha256 = policy_document["bindings"]["frequency_estimator"]["sha256"]
    build_identity = "a" * 64 + ":" + "b" * 64
    identity = {
        "run_identity": programme.runtime_run_identity,
        "build_identity": build_identity,
        "profile_identity": programme.profile_id,
    }
    controller = CX323PhasePriorityController(policy)
    maintenance: list[dict[str, str]] = []
    decisions: list[dict[str, str]] = []
    transactions: list[dict[str, str]] = []

    def base(event: str, before: dict[str, str], after: dict[str, str]) -> dict[str, str]:
        sequence = len(maintenance) + 1
        return {
            "maintenance_record_sequence": str(sequence),
            "event": event,
            "policy_id": policy.policy_id,
            "active_policy_sha256": policy.policy_sha256,
            "frequency_estimator_sha256": estimator_sha256,
            "current_applied_code": str(controller.applied_code),
            "current_dac_epoch": str(controller.dac_epoch),
            "capture_session": "1",
            "source_first_sequence": "0",
            "source_last_sequence": "0",
            "phase_epoch": "1",
            "phase_valid": "true",
            "hybrid_record_sequence": "0",
            "decision_sequence": "0",
            "transaction_record_sequence": "0",
            "transaction_event": "none",
            "request_sequence": "0",
            "actual_applied_code": "0",
            "actual_dac_epoch": "0",
            "downstream_epoch_exact": "false",
            "requested_delta_codes": "0",
            "requested_code": str(controller.applied_code),
            "safe_cap_codes": "0",
            "raw_fll_demand_picocodes": "0",
            "raw_pll_demand_picocodes": "0",
            "candidate_total_demand_picocodes": "0",
            "reason": event,
            **identity,
            **before,
            **after,
        }

    inactive = {
        "maintenance_state_before": "POLICY_INACTIVE",
        "committed_fll_debt_before_picocodes": "0",
        "committed_pll_debt_before_picocodes": "0",
        "request_pending_before": "false",
        "response_pending_before": "false",
        "metadata_hold_before": "false",
        "persistence_count_before": "0",
        "requalification_window_count_before": "0",
    }
    maintenance.append(base("policy_activation", inactive, _snapshot(controller, "after")))

    def decide(
        *, timestamp: int, opening: int, closing: int, counts: int, tight: str
    ) -> tuple[CX323Observation, object]:
        before = _snapshot(controller, "before")
        observation = CX323Observation(
            timestamp_s=timestamp,
            capture_session=1,
            source_first_sequence=opening,
            source_last_sequence=closing,
            dac_epoch=controller.dac_epoch,
            applied_code=controller.applied_code,
            accumulated_edge_error_counts=counts,
            tight_state=tight,
            phase_epoch=1,
            relative_phase_cycles=0,
        )
        decision = controller.decide(observation)
        hybrid_record = len(decisions) + 1
        ahy = {
            "hybrid_record_sequence": str(hybrid_record),
            "decision_sequence": str(decision.decision_sequence),
            "decision_timestamp_s": str(timestamp),
            "capture_session": "1",
            "source_first_sequence": str(opening),
            "source_last_sequence": str(closing),
            "current_applied_code": str(observation.applied_code),
            "dac_epoch": str(observation.dac_epoch),
            "accumulated_edge_error_counts": str(counts),
            "tight_state": tight,
            "phase_epoch": "1",
            "relative_phase_cycles": "0",
            "requested_delta_codes": str(decision.requested_delta_codes),
            "requested_code": str(decision.requested_code),
            "phase_materially_influenced": "false",
            "reason": decision.reason,
            "active_policy_sha256": policy.policy_sha256,
            **identity,
        }
        decisions.append(ahy)
        row = base("decision", before, _snapshot(controller, "after"))
        row.update(
            {
                "hybrid_record_sequence": str(hybrid_record),
                "decision_sequence": str(decision.decision_sequence),
                "source_first_sequence": str(opening),
                "source_last_sequence": str(closing),
                "current_applied_code": str(observation.applied_code),
                "current_dac_epoch": str(observation.dac_epoch),
                "requested_delta_codes": str(decision.requested_delta_codes),
                "requested_code": str(decision.requested_code),
                "safe_cap_codes": str(decision.safe_cap_codes),
                "raw_fll_demand_picocodes": str(decision.raw_fll_picocodes),
                "raw_pll_demand_picocodes": str(decision.raw_pll_picocodes),
                "candidate_total_demand_picocodes": str(
                    decision.raw_combined_picocodes
                    + int(before["committed_fll_debt_before_picocodes"])
                    + int(before["committed_pll_debt_before_picocodes"])
                ),
                "reason": decision.reason,
            }
        )
        return observation, decision, row

    observation, request, request_ahm = decide(
        timestamp=0, opening=1, closing=601, counts=2, tight="OUTSIDE"
    )
    transactions.append(
        {
            "transaction_record_sequence": "1",
            "event": "request_created",
            "decision_sequence": str(request.decision_sequence),
            "request_sequence": "1",
        }
    )
    request_ahm.update(
        {
            "transaction_record_sequence": "1",
            "transaction_event": "request_created",
            "request_sequence": "1",
        }
    )
    maintenance.append(request_ahm)

    transactions.append(
        {
            "transaction_record_sequence": "2",
            "event": "core0_accepted",
            "decision_sequence": str(request.decision_sequence),
            "request_sequence": "1",
        }
    )
    before = _snapshot(controller, "before")
    controller.confirm_application(
        request,
        applied_code=request.requested_code,
        dac_epoch=2,
        first_consumer_exact=True,
    )
    transactions.append(
        {
            "transaction_record_sequence": "3",
            "event": "application",
            "decision_sequence": str(request.decision_sequence),
            "request_sequence": "1",
            "applied_code": str(request.requested_code),
            "dac_epoch": "2",
        }
    )
    application = base(
        "application_first_consumer", before, _snapshot(controller, "after")
    )
    application.update(
        {
            "hybrid_record_sequence": "1",
            "decision_sequence": str(request.decision_sequence),
            "source_first_sequence": str(observation.source_first_sequence),
            "source_last_sequence": str(observation.source_last_sequence),
            "transaction_record_sequence": "3",
            "transaction_event": "application",
            "request_sequence": "1",
            "actual_applied_code": str(request.requested_code),
            "actual_dac_epoch": "2",
            "downstream_epoch_exact": "true",
            "requested_delta_codes": str(request.requested_delta_codes),
            "requested_code": str(request.requested_code),
            "safe_cap_codes": str(request.safe_cap_codes),
            "raw_fll_demand_picocodes": str(request.raw_fll_picocodes),
            "raw_pll_demand_picocodes": str(request.raw_pll_picocodes),
            "candidate_total_demand_picocodes": str(request.raw_combined_picocodes),
        }
    )
    maintenance.append(application)

    before = _snapshot(controller, "before")
    controller.complete_response(fresh_exact=True)
    transactions.append(
        {
            "transaction_record_sequence": "4",
            "event": "response",
            "decision_sequence": str(request.decision_sequence),
            "request_sequence": "1",
            "applied_code": str(request.requested_code),
            "dac_epoch": "2",
            "requested_delta_codes": str(request.requested_delta_codes),
            "observed_response_hz": "0.001",
            "response_class": "healthy_detected",
        }
    )
    response = base("response_complete", before, _snapshot(controller, "after"))
    response.update(
        {
            "hybrid_record_sequence": "1",
            "decision_sequence": str(request.decision_sequence),
            "source_first_sequence": str(observation.source_first_sequence),
            "source_last_sequence": str(observation.source_last_sequence),
            "transaction_record_sequence": "4",
            "transaction_event": "response",
            "request_sequence": "1",
            "actual_applied_code": str(request.requested_code),
            "actual_dac_epoch": "2",
            "downstream_epoch_exact": "true",
            "requested_delta_codes": str(request.requested_delta_codes),
            "requested_code": str(request.requested_code),
            "safe_cap_codes": str(request.safe_cap_codes),
            "raw_fll_demand_picocodes": str(request.raw_fll_picocodes),
            "raw_pll_demand_picocodes": str(request.raw_pll_picocodes),
            "candidate_total_demand_picocodes": str(request.raw_combined_picocodes),
        }
    )
    maintenance.append(response)

    second_observation, second_request, second_request_ahm = decide(
        timestamp=1800,
        opening=601,
        closing=1201,
        counts=-2,
        tight="OUTSIDE",
    )
    transactions.append(
        {
            "transaction_record_sequence": "5",
            "event": "request_created",
            "decision_sequence": str(second_request.decision_sequence),
            "request_sequence": "2",
        }
    )
    second_request_ahm.update(
        {
            "transaction_record_sequence": "5",
            "transaction_event": "request_created",
            "request_sequence": "2",
        }
    )
    maintenance.append(second_request_ahm)

    before = _snapshot(controller, "before")
    controller.reject_or_expire_request()
    transactions.append(
        {
            "transaction_record_sequence": "6",
            "event": "request_withdrawn",
            "decision_sequence": str(second_request.decision_sequence),
            "request_sequence": "2",
        }
    )
    rejected = base(
        "request_rejected_or_expired", before, _snapshot(controller, "after")
    )
    rejected.update(
        {
            "hybrid_record_sequence": "2",
            "decision_sequence": str(second_request.decision_sequence),
            "source_first_sequence": str(second_observation.source_first_sequence),
            "source_last_sequence": str(second_observation.source_last_sequence),
            "transaction_record_sequence": "6",
            "transaction_event": "request_withdrawn",
            "request_sequence": "2",
            "requested_delta_codes": str(second_request.requested_delta_codes),
            "requested_code": str(second_request.requested_code),
            "safe_cap_codes": str(second_request.safe_cap_codes),
            "raw_fll_demand_picocodes": str(second_request.raw_fll_picocodes),
            "raw_pll_demand_picocodes": str(second_request.raw_pll_picocodes),
            "candidate_total_demand_picocodes": str(
                second_request.raw_combined_picocodes
            ),
        }
    )
    maintenance.append(rejected)

    before = _snapshot(controller, "before")
    controller.enter_metadata_hold()
    hold = base("gnss_metadata_hold_enter", before, _snapshot(controller, "after"))
    hold.update({"source_last_sequence": "601", "reason": "recoverable_gnss_metadata_hold"})
    maintenance.append(hold)

    before = _snapshot(controller, "before")
    controller.requalify_metadata(1201)
    requalified = base(
        "gnss_metadata_requalified", before, _snapshot(controller, "after")
    )
    requalified.update({"source_last_sequence": "1201", "reason": "fresh_gnss_metadata"})
    maintenance.append(requalified)

    for timestamp, opening, closing in ((2400, 1201, 1801), (3000, 1801, 2401)):
        _observation, _decision, row = decide(
            timestamp=timestamp,
            opening=opening,
            closing=closing,
            counts=0,
            tight="TIGHT_INSIDE",
        )
        maintenance.append(row)

    for transaction in transactions:
        transaction.update(identity)

    return decisions, transactions, maintenance


def test_cx323_ahm_oracle_replays_rejection_and_two_window_gnss_requalification() -> None:
    decisions, transactions, maintenance = _exact_cx323_lifecycle()
    programme = CX323_D9_D6_72H_PROGRAMME

    replay = replay_cx323_maintenance_history(
        decisions,
        transactions,
        maintenance,
        policy_path=programme.policy_path,
        expected_run_identity=programme.runtime_run_identity,
        expected_build_identity="a" * 64 + ":" + "b" * 64,
        expected_profile_identity=programme.profile_id,
    )

    assert replay["exact"] is True
    assert replay["replay_mode"] == "cx323_phase_priority_oracle_with_AHM_v1"
    assert [row["event"] for row in maintenance] == [
        "policy_activation",
        "decision",
        "application_first_consumer",
        "response_complete",
        "decision",
        "request_rejected_or_expired",
        "gnss_metadata_hold_enter",
        "gnss_metadata_requalified",
        "decision",
        "decision",
    ]
    assert maintenance[-2]["metadata_hold_after"] == "true"
    assert maintenance[-2]["requalification_window_count_after"] == "1"
    assert maintenance[-1]["metadata_hold_after"] == "false"
    assert maintenance[-1]["requalification_window_count_after"] == "2"


def _write_rows(path: Path, rows: list[dict[str, str]]) -> None:
    fields = list(dict.fromkeys(key for row in rows for key in row))
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def test_cx323_phase4_response_attestation_waits_for_and_replays_ahm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    decisions, transactions, maintenance = _exact_cx323_lifecycle()
    programme = CX323_D9_D6_72H_PROGRAMME
    ahy_path = tmp_path / "active_hybrid_decisions_v1.csv"
    act_path = tmp_path / "active_transactions_v1.csv"
    ahm_path = tmp_path / "active_hybrid_maintenance_v1.csv"
    _write_rows(ahy_path, decisions)
    _write_rows(act_path, transactions)
    _write_rows(ahm_path, maintenance)
    monkeypatch.setattr(
        evidence_guard,
        "validate_csv",
        lambda *_args, **_kwargs: SimpleNamespace(ok=True, errors=()),
    )
    response = next(
        row
        for row in transactions
        if row["event"] == "response" and row["request_sequence"] == "1"
    )

    attestation = evidence_guard.replay_response_before_acknowledgement(
        active_hybrid_csv=ahy_path,
        active_transactions_csv=act_path,
        response_row=response,
        policy_path=programme.policy_path,
        expected_profile_identity=programme.profile_id,
        expected_active_policy_sha256=load_cx323_policy().policy_sha256,
        maintenance_csv=ahm_path,
        maximum_applications=programme.maximum_applications,
        maximum_cumulative_movement_codes=(
            programme.maximum_cumulative_movement_codes
        ),
    )

    assert attestation["attestation_type"] == (
        "cx323_response_replayed_before_acknowledgement_v1"
    )
    assert attestation["controller_state_authority"] == (
        "active_hybrid_maintenance_v1"
    )
    assert attestation["response_checkpoint_mode"] == (
        "observational_non_terminal"
    )
    assert attestation["exact_replay"] is True
