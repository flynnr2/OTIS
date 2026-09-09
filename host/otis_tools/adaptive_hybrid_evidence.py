"""Independent replay of adaptive-hybrid decisions and maintenance state."""

from __future__ import annotations

import csv
from hashlib import sha256
import json
from pathlib import Path
import time
from typing import Any

from .adaptive_hybrid_policy import (
    AdaptiveHybridDecision,
    AdaptiveHybridObservation,
    AdaptiveHybridPhasePriorityController,
    AdaptiveHybridPolicy,
)
from .contracts import CsvValidationContext, validate_csv

TOOL_ID = "adaptive_hybrid_response_evidence_guard_v1"
MAINTENANCE_VISIBILITY_TIMEOUT_S = 2.0
MAINTENANCE_VISIBILITY_POLL_S = 0.02


class ResponseCheckpointRejected(ValueError):
    """The evidence replayed exactly but failed a frozen predicate."""


class IndependentReplayMismatch(ValueError):
    """Independent replay disagrees with retained firmware evidence."""


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))

def _adaptive_hybrid_bool(row: dict[str, str], field: str) -> bool:
    value = row[field]
    if value not in {"true", "false"}:
        raise ValueError(f"AdaptiveHybrid AHM {field} is not canonical Boolean text")
    return value == "true"


def _adaptive_hybrid_state(controller: AdaptiveHybridPhasePriorityController) -> str:
    if controller.fail_static_reason is not None:
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


def _adaptive_hybrid_snapshot_exact(
    row: dict[str, str],
    controller: AdaptiveHybridPhasePriorityController,
    *,
    suffix: str,
) -> bool:
    return (
        row[f"maintenance_state_{suffix}"] == _adaptive_hybrid_state(controller)
        and int(row[f"committed_fll_debt_{suffix}_picocodes"])
        == controller.debt.fll_picocodes
        and int(row[f"committed_pll_debt_{suffix}_picocodes"])
        == controller.debt.pll_picocodes
        and _adaptive_hybrid_bool(row, f"request_pending_{suffix}")
        == controller.request_pending
        and _adaptive_hybrid_bool(row, f"response_pending_{suffix}")
        == controller.response_pending
        and _adaptive_hybrid_bool(row, f"metadata_hold_{suffix}")
        == controller.metadata_hold
        and int(row[f"persistence_count_{suffix}"])
        == controller.persistence_count
        and int(row[f"requalification_window_count_{suffix}"])
        == controller.requalification_window_count
    )


def replay_adaptive_hybrid_maintenance_history(
    decisions: list[dict[str, str]],
    transactions: list[dict[str, str]],
    maintenance_rows: list[dict[str, str]],
    *,
    expected_run_identity: str,
    expected_build_identity: str,
    expected_image_identity: str,
    policy: AdaptiveHybridPolicy,
    policy_document: dict[str, Any],
    estimator_sha256: str,
    expected_active_policy_sha256: str | None = None,
) -> dict[str, Any]:
    """Replay AdaptiveHybrid through its own oracle and authoritative AHM chronology.

    AHY is the controller-content observation and ACT is the actuator
    lifecycle, but neither serializes the persistent-window or tagged-debt
    state introduced by AdaptiveHybrid.  AHM is therefore the state authority and the
    exact join that lets the independent Python oracle replay each decision and
    transaction boundary by replaying only the active policy.
    """

    active_policy_sha256 = expected_active_policy_sha256 or policy.policy_sha256
    if active_policy_sha256 != policy.policy_sha256:
        raise ValueError("AdaptiveHybrid replay policy identity differs from frozen profile")
    if not isinstance(policy_document, dict):
        raise ValueError("AdaptiveHybrid replay policy document is malformed")
    if not isinstance(estimator_sha256, str) or len(estimator_sha256) != 64:
        raise ValueError("AdaptiveHybrid replay estimator identity is malformed")
    decision_by_sequence: dict[int, dict[str, str]] = {}
    for row in decisions:
        sequence = int(row["decision_sequence"])
        if sequence <= 0 or sequence in decision_by_sequence:
            raise ValueError("AdaptiveHybrid AHY decision sequence is not unique and positive")
        decision_by_sequence[sequence] = row
    transaction_by_record: dict[int, dict[str, str]] = {}
    for row in transactions:
        record = int(row["transaction_record_sequence"])
        if record <= 0 or record in transaction_by_record:
            raise ValueError("AdaptiveHybrid ACT record sequence is not unique and positive")
        transaction_by_record[record] = row

    controller: AdaptiveHybridPhasePriorityController | None = None
    replayed_decisions: dict[int, AdaptiveHybridDecision] = {}
    seen_decisions: set[int] = set()
    seen_transaction_records: set[int] = set()
    completed_response_decisions: set[int] = set()
    comparisons: list[dict[str, Any]] = []
    exact = True
    previous_maintenance_record = 0

    for maintenance in maintenance_rows:
        comparison: dict[str, Any] = {
            "maintenance_record_sequence": maintenance.get(
                "maintenance_record_sequence"
            ),
            "event": maintenance.get("event"),
        }
        try:
            record = int(maintenance["maintenance_record_sequence"])
            event = maintenance["event"]
            identity_exact = (
                maintenance["run_identity"] == expected_run_identity
                and maintenance["build_identity"] == expected_build_identity
                and maintenance["image_identity"] == expected_image_identity
                and maintenance["policy_id"] == policy.policy_id
                and maintenance["active_policy_sha256"] == active_policy_sha256
                and maintenance["frequency_estimator_sha256"]
                == estimator_sha256
            )
            sequence_exact = record == previous_maintenance_record + 1
            if event == "policy_activation":
                if controller is not None or record != 1:
                    raise ValueError("AdaptiveHybrid policy activation is not the first AHM row")
                controller = AdaptiveHybridPhasePriorityController(
                    policy,
                    setup_applied_code=int(maintenance["current_applied_code"]),
                    setup_dac_epoch=int(maintenance["current_dac_epoch"]),
                )
                numerical_exact = (
                    maintenance["maintenance_state_before"] == "POLICY_INACTIVE"
                    and controller.applied_code == policy.setup_code
                    and controller.dac_epoch == 1
                    and _adaptive_hybrid_snapshot_exact(
                        maintenance, controller, suffix="after"
                    )
                )
                transaction_exact = (
                    maintenance.get("transaction_event") == "none"
                    and int(maintenance.get("transaction_record_sequence", "0"))
                    == 0
                )
            else:
                if controller is None:
                    raise ValueError("AdaptiveHybrid AHM event precedes policy activation")
                before_exact = _adaptive_hybrid_snapshot_exact(
                    maintenance, controller, suffix="before"
                )
                transaction_exact = True
                if event == "decision":
                    decision_sequence = int(maintenance["decision_sequence"])
                    source = decision_by_sequence.get(decision_sequence)
                    if source is None or decision_sequence in seen_decisions:
                        raise ValueError(
                            "AdaptiveHybrid AHM decision lacks one unique AHY source"
                        )
                    source_exact = (
                        int(source["hybrid_record_sequence"])
                        == int(maintenance["hybrid_record_sequence"])
                        and source["run_identity"] == expected_run_identity
                        and source["build_identity"] == expected_build_identity
                        and source["image_identity"]
                        == expected_image_identity
                        and source["active_policy_sha256"]
                        == active_policy_sha256
                        and int(source["capture_session"])
                        == int(maintenance["capture_session"])
                        and int(source["source_first_sequence"])
                        == int(maintenance["source_first_sequence"])
                        and int(source["source_last_sequence"])
                        == int(maintenance["source_last_sequence"])
                        and int(source["decision_timestamp_ticks"])
                        == int(maintenance["event_timestamp_ticks"])
                        and int(source["current_applied_code"])
                        == controller.applied_code
                        and int(source["dac_epoch"]) == controller.dac_epoch
                    )
                    reason = maintenance["reason"]
                    observation = AdaptiveHybridObservation(
                        timestamp_s=int(source["decision_timestamp_s"]),
                        timestamp_ticks=int(maintenance["event_timestamp_ticks"]),
                        capture_session=int(source["capture_session"]),
                        source_first_sequence=int(source["source_first_sequence"]),
                        source_last_sequence=int(source["source_last_sequence"]),
                        dac_epoch=int(source["dac_epoch"]),
                        applied_code=int(source["current_applied_code"]),
                        accumulated_edge_error_counts=int(
                            source["accumulated_edge_error_counts"]
                        ),
                        tight_state=source["tight_state"],
                        phase_epoch=int(source["phase_epoch"]),
                        relative_phase_cycles=int(source["relative_phase_cycles"]),
                        frequency_estimator_id=policy.frequency_estimator_id,
                        phase_valid=_adaptive_hybrid_bool(maintenance, "phase_valid"),
                        authority_valid=(
                            reason != "reference_invalidity_or_authority_hold"
                        ),
                        settled=reason != "settling_hold",
                        cadence_eligible=(
                            source.get("cadence_limited", "false") != "true"
                        ),
                        metadata_qualified=(
                            not controller.metadata_hold
                            or controller.metadata_requalified
                        ),
                    )
                    replayed = controller.decide(observation)
                    candidate_total = (
                        replayed.raw_combined_picocodes
                        + replayed.committed_debt_picocodes
                    )
                    numerical_exact = (
                        before_exact
                        and source_exact
                        and replayed.decision_sequence == decision_sequence
                        and replayed.reason == reason == source["reason"]
                        and replayed.requested_delta_codes
                        == int(maintenance["requested_delta_codes"])
                        == int(source["requested_delta_codes"])
                        and replayed.requested_code
                        == int(maintenance["requested_code"])
                        == int(source["requested_code"])
                        and replayed.safe_cap_codes
                        == int(maintenance["safe_cap_codes"])
                        and replayed.raw_fll_picocodes
                        == int(maintenance["raw_fll_demand_picocodes"])
                        and replayed.raw_pll_picocodes
                        == int(maintenance["raw_pll_demand_picocodes"])
                        and candidate_total
                        == int(maintenance["candidate_total_demand_picocodes"])
                        and _adaptive_hybrid_snapshot_exact(
                            maintenance, controller, suffix="after"
                        )
                    )
                    transaction_record = int(
                        maintenance["transaction_record_sequence"]
                    )
                    if replayed.requested_delta_codes:
                        transaction = transaction_by_record.get(transaction_record)
                        transaction_exact = (
                            transaction is not None
                            and maintenance["transaction_event"]
                            == "request_created"
                            and transaction.get("event") == "request_created"
                            and int(transaction["decision_sequence"])
                            == decision_sequence
                            and int(transaction["request_sequence"])
                            == int(maintenance["request_sequence"])
                            and int(transaction["event_timestamp_ticks"])
                            == int(maintenance["event_timestamp_ticks"])
                        )
                        if transaction is not None:
                            seen_transaction_records.add(transaction_record)
                    else:
                        transaction_exact = (
                            transaction_record == 0
                            and maintenance["transaction_event"] == "none"
                        )
                    replayed_decisions[decision_sequence] = replayed
                    seen_decisions.add(decision_sequence)
                elif event in {
                    "request_rejected_or_expired",
                    "application_first_consumer",
                    "response_complete",
                }:
                    decision_sequence = int(maintenance["decision_sequence"])
                    replayed = replayed_decisions.get(decision_sequence)
                    if replayed is None:
                        raise ValueError(
                            "AdaptiveHybrid transaction lifecycle lacks its originating decision"
                        )
                    transaction_record = int(
                        maintenance["transaction_record_sequence"]
                    )
                    transaction = transaction_by_record.get(transaction_record)
                    expected_transaction_event = {
                        "request_rejected_or_expired": "request_withdrawn",
                        "application_first_consumer": "application",
                        "response_complete": "response",
                    }[event]
                    transaction_exact = (
                        transaction is not None
                        and transaction.get("event") == expected_transaction_event
                        and maintenance["transaction_event"]
                        == expected_transaction_event
                        and int(transaction["decision_sequence"])
                        == decision_sequence
                        and int(transaction["request_sequence"])
                        == int(maintenance["request_sequence"])
                        and int(transaction["event_timestamp_ticks"])
                        == int(maintenance["event_timestamp_ticks"])
                    )
                    if transaction is not None:
                        seen_transaction_records.add(transaction_record)
                    if event == "request_rejected_or_expired":
                        controller.reject_or_expire_request()
                    elif event == "application_first_consumer":
                        controller.confirm_application(
                            replayed,
                            applied_code=int(maintenance["actual_applied_code"]),
                            dac_epoch=int(maintenance["actual_dac_epoch"]),
                            first_consumer_exact=_adaptive_hybrid_bool(
                                maintenance, "downstream_epoch_exact"
                            ),
                        )
                    else:
                        controller.complete_response(fresh_exact=True)
                        completed_response_decisions.add(decision_sequence)
                    numerical_exact = before_exact and _adaptive_hybrid_snapshot_exact(
                        maintenance, controller, suffix="after"
                    )
                elif event == "gnss_metadata_hold_enter":
                    controller.enter_metadata_hold()
                    numerical_exact = before_exact and _adaptive_hybrid_snapshot_exact(
                        maintenance, controller, suffix="after"
                    )
                elif event == "gnss_metadata_requalified":
                    frontier = int(
                        maintenance[
                            "requalification_d14_d8_observation_sequence"
                        ]
                    )
                    if frontier <= 0:
                        raise ValueError(
                            "AdaptiveHybrid GNSS requalification lacks its causal D14/D8 frontier"
                        )
                    controller.requalify_metadata(frontier)
                    numerical_exact = before_exact and _adaptive_hybrid_snapshot_exact(
                        maintenance, controller, suffix="after"
                    )
                elif event == "fail_static":
                    controller._fail_static(maintenance["reason"])
                    numerical_exact = before_exact and _adaptive_hybrid_snapshot_exact(
                        maintenance, controller, suffix="after"
                    )
                else:
                    raise ValueError(f"unknown AdaptiveHybrid AHM event: {event}")

            row_exact = (
                identity_exact
                and sequence_exact
                and numerical_exact
                and transaction_exact
            )
            comparison.update(
                {
                    "identity_exact": identity_exact,
                    "sequence_exact": sequence_exact,
                    "numerical_exact": numerical_exact,
                    "transaction_binding_exact": transaction_exact,
                    "exact": row_exact,
                }
            )
            exact &= row_exact
            previous_maintenance_record = record
        except (KeyError, RuntimeError, TypeError, ValueError) as exc:
            exact = False
            comparison.update({"exact": False, "error": str(exc)})
        comparisons.append(comparison)

    required_transaction_records = {
        record
        for record, row in transaction_by_record.items()
        if row.get("event")
        in {"request_created", "request_withdrawn", "application", "response"}
    }
    exact &= (
        controller is not None
        and bool(decisions)
        and seen_decisions == set(decision_by_sequence)
        and seen_transaction_records == required_transaction_records
        and not controller.request_pending
        and not controller.response_pending
    )
    phase_nonzero_count = 0
    for row in decisions:
        try:
            phase_nonzero_count += int(row["relative_phase_cycles"]) != 0
        except (KeyError, TypeError, ValueError):
            exact = False
    return {
        "exact": bool(exact),
        "replay_mode": "adaptive_hybrid_phase_priority_oracle_with_AHM_v1",
        "controller_state_authority": "active_hybrid_maintenance_v1",
        "policy_id": policy.policy_id,
        "policy_sha256": policy.policy_sha256,
        "decision_count": len(decisions),
        "phase_nonzero_decision_count": phase_nonzero_count,
        "phase_material_decision_count": sum(
            row.get("phase_materially_influenced") == "true" for row in decisions
        ),
        "unmatched_request_decision_sequences": sorted(
            set(decision_by_sequence) - seen_decisions
        ),
        "completed_response_decision_sequences": sorted(
            completed_response_decisions
        ),
        "all_response_checkpoints_passed": True,
        "comparisons": comparisons,
    }


def _await_adaptive_hybrid_maintenance_response(
    path: Path,
    *,
    response_row: dict[str, str],
) -> list[dict[str, str]]:
    """Bound the ACT-before-AHM splitter visibility interval for one burst."""

    deadline = time.monotonic() + MAINTENANCE_VISIBILITY_TIMEOUT_S
    while True:
        rows = _rows(path) if path.is_file() else []
        for index, row in enumerate(rows):
            if (
                row.get("event") == "response_complete"
                and row.get("transaction_record_sequence")
                == response_row.get("transaction_record_sequence")
                and row.get("request_sequence")
                == response_row.get("request_sequence")
                and row.get("decision_sequence")
                == response_row.get("decision_sequence")
            ):
                # Reconstruct the exact causal prefix that existed before this
                # response was acknowledged.  Later evidence must not change a
                # previously completed checkpoint's verdict.
                return rows[: index + 1]
        if time.monotonic() >= deadline:
            raise ValueError(
                "AdaptiveHybrid response AHM was not visible before phase-4 acknowledgement"
            )
        time.sleep(MAINTENANCE_VISIBILITY_POLL_S)


def replay_response_before_acknowledgement(
    *,
    active_hybrid_csv: Path,
    active_transactions_csv: Path,
    response_row: dict[str, str],
    frozen_policy: AdaptiveHybridPolicy,
    frozen_policy_document: dict[str, Any],
    frozen_estimator_sha256: str,
    expected_image_identity: str = "adaptive_hybrid_regulation",
    expected_active_policy_sha256: str | None = None,
    estimates_csv: Path | None = None,
    maintenance_csv: Path | None = None,
    maximum_applications: int | None = None,
    maximum_cumulative_movement_codes: int | None = None,
    phase_checkpoint_required: bool = True,
) -> dict[str, Any]:
    validation = validate_csv(
        active_hybrid_csv,
        CsvValidationContext(
            "active_hybrid_decisions_v2",
            frozenset(),
            frozenset({"rp2040_monotonic_us64"}),
        ),
    )
    if not validation.ok:
        raise ValueError("adaptive-hybrid AHY evidence differs: " + "; ".join(validation.errors))
    if response_row.get("event") != "response":
        raise ValueError("response guard requires the ACT response record")
    request_sequence = int(response_row["request_sequence"])
    decision_sequence = int(response_row["decision_sequence"])
    all_transactions = _rows(active_transactions_csv)
    transactions = [
        row
        for row in all_transactions
        if int(row.get("request_sequence", "0")) == request_sequence
    ]
    events = [row.get("event") for row in transactions]
    if events != ["request_created", "request_accepted", "application", "response"]:
        raise ValueError("transaction evidence is incomplete or out of order")
    if transactions[-1] != response_row:
        raise ValueError("response is not the exact retained terminal transaction row")
    all_decisions = _rows(active_hybrid_csv)
    decisions = [
        row for row in all_decisions if int(row["decision_sequence"]) == decision_sequence
    ]
    if len(decisions) != 1:
        raise ValueError("response does not identify exactly one AHY decision")
    decision = decisions[0]
    policy = frozen_policy
    active_policy_sha256 = expected_active_policy_sha256 or policy.policy_sha256
    if decision["active_policy_sha256"] != active_policy_sha256:
        raise ValueError("decision policy identity differs")
    if decision["run_identity"] != response_row["run_identity"]:
        raise ValueError("decision and transaction run identities differ")
    if decision["build_identity"] != response_row["build_identity"]:
        raise ValueError("decision and transaction build identities differ")
    if decision["image_identity"] != expected_image_identity:
        raise ValueError("decision profile identity differs")
    if isinstance(policy, AdaptiveHybridPolicy):
        if maintenance_csv is None:
            raise ValueError("AdaptiveHybrid response replay requires retained AHM evidence")
        maintenance_rows = _await_adaptive_hybrid_maintenance_response(
            maintenance_csv, response_row=response_row
        )
        maintenance_validation = validate_csv(
            maintenance_csv,
            CsvValidationContext(
                "active_hybrid_maintenance_v1",
                frozenset(),
                frozenset({"rp2040_monotonic_us64"}),
            ),
        )
        if not maintenance_validation.ok:
            raise ValueError(
                "AdaptiveHybrid AHM evidence differs: "
                + "; ".join(maintenance_validation.errors)
            )
        causal_decision_sequences = {
            int(item["decision_sequence"])
            for item in maintenance_rows
            if int(item.get("decision_sequence", "0")) > 0
        }
        replay = replay_adaptive_hybrid_maintenance_history(
            [
                row
                for row in all_decisions
                if int(row["decision_sequence"]) in causal_decision_sequences
            ],
            [
                row
                for row in all_transactions
                if int(row["transaction_record_sequence"])
                <= int(response_row["transaction_record_sequence"])
            ],
            maintenance_rows,
            policy=policy,
            policy_document=frozen_policy_document,
            estimator_sha256=frozen_estimator_sha256,
            expected_run_identity=decision["run_identity"],
            expected_build_identity=decision["build_identity"],
            expected_image_identity=decision["image_identity"],
            expected_active_policy_sha256=active_policy_sha256,
        )
        if not replay["exact"]:
            raise IndependentReplayMismatch(
                "AdaptiveHybrid independent host replay differs from AHM/firmware evidence"
            )
        application = transactions[2]
        response = transactions[3]
        comparison = next(
            (
                item
                for item in replay["comparisons"]
                if item.get("event") == "decision"
                and int(item.get("maintenance_record_sequence", -1)) > 0
                and item.get("exact")
                and any(
                    row.get("event") == "decision"
                    and row.get("maintenance_record_sequence")
                    == item.get("maintenance_record_sequence")
                    and int(row.get("decision_sequence", "0"))
                    == decision_sequence
                    for row in maintenance_rows
                )
            ),
            None,
        )
        if comparison is None:
            raise ValueError("AdaptiveHybrid request decision is absent from exact AHM replay")
        requested_code = int(decision["requested_code"])
        requested_delta = int(decision["requested_delta_codes"])
        if (
            int(application["applied_code"]) != requested_code
            or int(application["dac_epoch"]) <= int(decision["dac_epoch"])
            or int(response["applied_code"]) != requested_code
            or int(response["dac_epoch"]) != int(application["dac_epoch"])
            or response["response_class"]
            not in {
                "healthy_detected",
                "healthy_indeterminate_near_resolution",
                "inside_deadband",
                "limit_reached",
                "wrong_sign",
                "excess_response",
                "growing_error",
            }
        ):
            raise ValueError("AdaptiveHybrid applied code, epoch, or response evidence differs")
        predicted_sign_observed = (
            float(response["observed_response_hz"]) * requested_delta > 0.0
        )
        result: dict[str, Any] = {
            "schema_version": 1,
            "attestation_type": (
                "adaptive_hybrid_response_replayed_before_acknowledgement_v1"
            ),
            "tool": TOOL_ID,
            "tool_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
            "request_sequence": request_sequence,
            "decision_sequence": decision_sequence,
            "transaction_record_sequence": int(
                response["transaction_record_sequence"]
            ),
            "run_identity": decision["run_identity"],
            "build_identity": decision["build_identity"],
            "policy_sha256": decision["active_policy_sha256"],
            "requested_delta_codes": requested_delta,
            "requested_code": requested_code,
            "applied_code": int(application["applied_code"]),
            "dac_epoch": int(application["dac_epoch"]),
            "response_class": response["response_class"],
            "predicted_sign_observed": predicted_sign_observed,
            "response_checkpoint_mode": "observational_non_terminal",
            "controller_state_authority": "active_hybrid_maintenance_v1",
            "exact_replay": True,
        }
        result["attestation_sha256"] = sha256(
            json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        return result
