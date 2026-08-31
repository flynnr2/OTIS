"""Independent CX320 decision replay required before a response ACKE."""

from __future__ import annotations

import csv
from dataclasses import replace
from hashlib import sha256
import json
import math
from pathlib import Path
import time
from typing import Any

from .active_hybrid_policy import (
    ActiveHybridController,
    CX323Decision,
    CX323Observation,
    CX323PhasePriorityController,
    CX323Policy,
    HybridObservation,
    load_cx323_policy,
    load_policy,
)
from .contracts import CsvValidationContext, validate_csv
from .time_domains import time_domain, unwrap_domain_ticks


TOOL_ID = "cx320_active_hybrid_response_evidence_guard_v1"
FROZEN_AHY_FRACTIONAL_DECIMAL_PLACES = 12
FROZEN_ACT_FREQUENCY_DECIMAL_PLACES = 9
FROZEN_AHY_HALF_SERIALIZATION_QUANTUM = (
    0.5 * 10**-FROZEN_AHY_FRACTIONAL_DECIMAL_PLACES
)
CX323_MAINTENANCE_VISIBILITY_TIMEOUT_S = 2.0
CX323_MAINTENANCE_VISIBILITY_POLL_S = 0.02
FROZEN_ACT_FREQUENCY_HALF_SERIALIZATION_QUANTUM = (
    0.5 * 10**-FROZEN_ACT_FREQUENCY_DECIMAL_PLACES
)


class ResponseCheckpointRejected(ValueError):
    """The evidence replayed exactly but failed a frozen response predicate."""


class IndependentReplayMismatch(ValueError):
    """Host replay disagrees with retained firmware evidence."""


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _exact_decision_timestamps_s(
    decisions: list[dict[str, str]],
    estimates: list[dict[str, str]] | None,
    *,
    estimator_id: str,
) -> dict[int, float]:
    """Join each AHY source boundary to its exact estimator timer coordinate."""

    if estimates is None:
        return {}
    selected: dict[int, list[dict[str, str]]] = {}
    for row in estimates:
        if (
            row.get("estimator_version") == estimator_id
            and row.get("observation_validity") == "valid"
            and row.get("reference_validity") == "valid"
            and row.get("count_validity") == "valid"
        ):
            selected.setdefault(int(row["source_count_seq"]), []).append(row)
    matched: list[dict[str, str]] = []
    sequences: list[int] = []
    for decision in decisions:
        decision_sequence = int(decision["decision_sequence"])
        candidates = selected.get(int(decision["source_last_sequence"]), [])
        if len(candidates) != 1:
            raise ValueError(
                "CX320 AHY decision lacks one exact selected-estimate timestamp"
            )
        matched.append(candidates[0])
        sequences.append(decision_sequence)
    domains = {row.get("time_domain", "") for row in matched}
    if len(domains) != 1:
        raise ValueError("CX320 exact decision timestamps cross clock domains")
    domain = next(iter(domains))
    ticks, _ = unwrap_domain_ticks(
        [int(row["estimator_timestamp_ticks"]) for row in matched],
        domain=domain,
    )
    hz = time_domain(domain).nominal_hz
    return {
        decision_sequence: tick / hz
        for decision_sequence, tick in zip(sequences, ticks)
    }


def _close(observed: float, expected: float) -> bool:
    return math.isclose(observed, expected, rel_tol=0, abs_tol=5e-12)


def _raw_code_close(
    observed: float, expected: float, *, gain_codes_per_hz: float
) -> bool:
    # AHY serializes both the frequency input used by independent replay and
    # the firmware raw-code result to 12 fractional decimal places.  Bound the
    # former's half-quantum after conversion to codes, then add the latter's
    # half-quantum in its native code unit.
    tolerance_codes = FROZEN_AHY_HALF_SERIALIZATION_QUANTUM * (
        abs(gain_codes_per_hz) + 1.0
    )
    return math.isclose(observed, expected, rel_tol=0, abs_tol=tolerance_codes)


def _ahy_act_frequency_close(observed: float, expected: float) -> bool:
    """Compare the same frequency serialized by AHY and ACT contracts."""

    return math.isclose(
        observed,
        expected,
        rel_tol=0,
        abs_tol=(
            FROZEN_AHY_HALF_SERIALIZATION_QUANTUM
            + FROZEN_ACT_FREQUENCY_HALF_SERIALIZATION_QUANTUM
        ),
    )


def _bool(row: dict[str, str], name: str) -> bool:
    value = row[name]
    if value not in {"true", "false"}:
        raise ValueError(f"CX320 {name} is not canonical Boolean text")
    return value == "true"


def _cx321_natural_replay_handoff(
    plant_sign_records: list[dict[str, str]],
    transactions: list[dict[str, str]],
) -> dict[str, Any]:
    """Recover the one exact CX321 natural-controller replay seed."""

    handoffs = [row for row in plant_sign_records if row.get("event") == "handoff"]
    if len(handoffs) != 1:
        raise ValueError("CX321 natural replay requires one exact PSQ handoff")
    handoff = handoffs[0]
    if (
        handoff.get("attested") != "true"
        or handoff.get("global_correction_count") != "1"
        or handoff.get("global_cumulative_movement_codes") != "21"
        or handoff.get("natural_cumulative_movement_codes") != "0"
        or handoff.get("natural_direction_count") != "0"
    ):
        raise ValueError("CX321 PSQ handoff does not preserve exact natural seed")
    request_sequence = int(handoff["request_sequence"])
    applications = [
        row
        for row in transactions
        if row.get("event") == "application"
        and int(row.get("request_sequence", "0")) == request_sequence
        and row.get("applied_code") == handoff.get("applied_code")
        and row.get("dac_epoch") == handoff.get("dac_epoch")
    ]
    if len(applications) != 1:
        raise ValueError("CX321 PSQ handoff lacks one exact ACT application")
    application = applications[0]
    timer_hz = 16_000_000
    handoff_ticks = int(handoff["event_timestamp_ticks"])
    qualification_started_s = (handoff_ticks + timer_hz - 1) // timer_hz
    return {
        "applied_code": int(handoff["applied_code"]),
        "dac_epoch": int(handoff["dac_epoch"]),
        "application_s": int(application["application_timestamp_s"]),
        "qualification_started_s": qualification_started_s,
        "attestation_id": handoff["replay_attestation_sha256"],
        "identification_request_sequence": request_sequence,
    }


def replay_active_hybrid_history(
    decisions: list[dict[str, str]],
    transactions: list[dict[str, str]],
    *,
    policy_path: Path | None = None,
    expected_run_identity: str,
    expected_build_identity: str,
    expected_profile_identity: str,
    expected_active_policy_sha256: str | None = None,
    plant_sign_handoff: dict[str, Any] | None = None,
    estimate_rows: list[dict[str, str]] | None = None,
    maximum_applications: int | None = None,
    maximum_cumulative_movement_codes: int | None = None,
    phase_checkpoint_required: bool = True,
) -> dict[str, Any]:
    """Replay the real request/application/response chronology exactly.

    Firmware emits the response-horizon AHY row while the application and
    response are still outstanding, then records the ACT response, and only
    clears the policy checkpoint after the host's durable phase-4 evidence
    acknowledgement.  Replaying a completed transaction immediately after its
    request row invents an ordering that cannot occur on the device.
    """

    policy = load_policy() if policy_path is None else load_policy(policy_path)
    active_policy_sha256 = (
        expected_active_policy_sha256 or policy.policy_sha256
    )
    manual = [row for row in transactions if row.get("event") == "manual_start"]
    setup_application_s = (
        int(manual[0]["application_timestamp_s"]) if len(manual) == 1 else None
    )
    authorized_maximum_applications = (
        policy.maximum_applications
        if maximum_applications is None
        else maximum_applications
    )
    authorized_maximum_cumulative_movement_codes = (
        policy.maximum_cumulative_movement_codes
        if maximum_cumulative_movement_codes is None
        else maximum_cumulative_movement_codes
    )
    if (
        authorized_maximum_applications < 0
        or authorized_maximum_cumulative_movement_codes < 0
    ):
        raise ValueError("active-hybrid authority budgets must be non-negative")
    # The retained policy identity describes the request law, while a live
    # campaign may compile a larger finite authority envelope around that law.
    # Replay the explicit larger envelope in the controller itself; otherwise
    # controller.decide() silently falls back to the generic four-application
    # policy and diverges after the fourth live application.  A smaller caller
    # limit remains an external authority-suppression check below.
    replay_policy = replace(
        policy,
        maximum_applications=max(
            policy.maximum_applications, authorized_maximum_applications
        ),
        maximum_cumulative_movement_codes=max(
            policy.maximum_cumulative_movement_codes,
            authorized_maximum_cumulative_movement_codes,
        ),
    )
    controller = ActiveHybridController(
        replay_policy, setup_application_s=setup_application_s
    )
    exact_timestamps_s = _exact_decision_timestamps_s(
        decisions, estimate_rows, estimator_id=policy.frequency_estimator_id
    )
    identification_request_sequence: int | None = None
    if plant_sign_handoff is not None:
        controller.rebase_after_plant_sign(
            applied_code=int(plant_sign_handoff["applied_code"]),
            dac_epoch=int(plant_sign_handoff["dac_epoch"]),
            application_s=int(plant_sign_handoff["application_s"]),
            qualification_started_s=int(
                plant_sign_handoff["qualification_started_s"]
            ),
            attestation_id=str(plant_sign_handoff["attestation_id"]),
        )
        identification_request_sequence = int(
            plant_sign_handoff["identification_request_sequence"]
        )
    mappings: dict[str, dict[int, dict[str, str]]] = {
        "request_created": {},
        "application": {},
        "response": {},
    }
    mapping_exact = True
    for row in transactions:
        if (
            identification_request_sequence is not None
            and int(row.get("request_sequence", "0"))
            == identification_request_sequence
        ):
            continue
        target = mappings.get(row.get("event", ""))
        if target is None:
            continue
        try:
            sequence = int(row["decision_sequence"])
        except (KeyError, TypeError, ValueError):
            mapping_exact = False
            continue
        if sequence in target:
            mapping_exact = False
        target[sequence] = row

    comparisons: list[dict[str, Any]] = []
    exact = mapping_exact
    prior_record_sequence = 0
    seen_decisions: set[int] = set()
    outstanding_decision_sequence: int | None = None
    completed_response_decisions: set[int] = set()
    all_response_checkpoints_passed = True
    for row in decisions:
        try:
            record_sequence = int(row["hybrid_record_sequence"])
            decision_sequence = int(row["decision_sequence"])
            identity_exact = (
                row["run_identity"] == expected_run_identity
                and row["build_identity"] == expected_build_identity
                and row["profile_identity"] == expected_profile_identity
                and row["active_policy_sha256"] == active_policy_sha256
                and row["frequency_estimator_sha256"]
                == policy.frequency_estimator_sha256
                and row["phase_estimator_sha256"]
                == policy.phase_estimator_sha256
                and row["response_policy_sha256"]
                == policy.response_policy_sha256
            )
            response_horizon = (
                controller.transaction_outstanding
                and row.get("authority_state") == "AWAITING_RESPONSE"
            )
            observation = HybridObservation(
                timestamp_s=exact_timestamps_s.get(
                    decision_sequence, int(row["decision_timestamp_s"])
                ),
                capture_session=int(row["capture_session"]),
                source_first_sequence=int(row["source_first_sequence"]),
                source_last_sequence=int(row["source_last_sequence"]),
                dac_epoch=int(row["dac_epoch"]),
                applied_code=int(row["current_applied_code"]),
                frequency_error_hz=float(row["frequency_error_hz"]),
                accumulated_edge_error_counts=int(
                    row["accumulated_edge_error_counts"]
                ),
                tight_state=row["tight_state"],
                phase_epoch=int(row["phase_epoch"]),
                phase_observation_sequence=int(row["phase_observation_sequence"]),
                relative_phase_cycles=int(row["relative_phase_cycles"]),
                phase_dac_epoch=int(row["phase_dac_epoch"]),
                phase_applied_code=int(row["phase_applied_code"]),
                phase_continuous=_bool(row, "phase_continuous"),
                phase_current=_bool(row, "phase_current"),
                phase_step_detected=_bool(row, "phase_step_detected"),
                identity_exact=identity_exact,
                common_health_clean=True,
                phase_consumers_exact=(
                    _bool(row, "phase_recorder_published")
                    and _bool(row, "downstream_epoch_exact")
                ),
                outstanding_request=controller.transaction_outstanding,
                outstanding_response=response_horizon,
            )
            replayed = controller.decide(observation)
            numerical_exact = (
                row["state_before"] == replayed.state_before
                and row["state_after"] == replayed.state_after
                and row["reason"] == replayed.reason
                and _close(float(row["frequency_term_hz"]), replayed.frequency_term_hz)
                and _close(float(row["phase_term_hz"]), replayed.phase_term_hz)
                and _close(
                    float(row["combined_demand_hz"]), replayed.combined_demand_hz
                )
                and _raw_code_close(
                    float(row["raw_combined_delta_codes"]),
                    replayed.raw_combined_delta_codes,
                    gain_codes_per_hz=(
                        policy.integrator_gain_codes_per_hz_per_decision
                    ),
                )
                and int(row["requested_delta_codes"])
                == replayed.requested_delta_codes
                and int(row["requested_code"]) == replayed.requested_code
                and int(row["counterfactual_frequency_only_delta_codes"])
                == replayed.counterfactual_frequency_only_delta_codes
                and _bool(row, "phase_materially_influenced")
                == replayed.phase_materially_influenced
                and _bool(row, "step_limited") == replayed.step_limited
                and _bool(row, "range_clamped") == replayed.range_clamped
                and _bool(row, "cadence_limited") == replayed.cadence_limited
                and _bool(row, "count_limited") == replayed.count_limited
                and _bool(row, "cumulative_budget_limited")
                == replayed.cumulative_budget_limited
                and int(row["correction_count_before"])
                == replayed.correction_count_before
                and int(row["cumulative_movement_before_codes"])
                == replayed.cumulative_movement_before_codes
            )
            sequence_exact = (
                record_sequence == prior_record_sequence + 1
                and decision_sequence not in seen_decisions
            )
            request = mappings["request_created"].get(decision_sequence)
            carried_completed_transaction_exact = False
            authority_budget_closed = (
                replayed.correction_count_before
                >= authorized_maximum_applications
                or (
                    replayed.cumulative_movement_before_codes
                    + abs(replayed.requested_delta_codes)
                    > authorized_maximum_cumulative_movement_codes
                )
            )
            authority_budget_suppression_candidate = (
                replayed.requested_delta_codes != 0
                and request is None
                and not controller.transaction_outstanding
                and row.get("authority_state") == "DISARMED"
                and row.get("actionable") == "false"
                and authority_budget_closed
            )
            if authority_budget_suppression_candidate:
                completed_before = [
                    prior_decision
                    for prior_decision in mappings["response"]
                    if prior_decision < decision_sequence
                    and prior_decision in mappings["request_created"]
                    and prior_decision in mappings["application"]
                ]
                if completed_before:
                    carried_decision = max(completed_before)
                    carried_request = mappings["request_created"][carried_decision]
                    carried_application = mappings["application"][carried_decision]
                    carried_response = mappings["response"][carried_decision]
                    carried_completed_transaction_exact = (
                        int(row.get("request_sequence", "0"))
                        == int(carried_request["request_sequence"])
                        and int(row.get("acceptance_sequence", "0"))
                        == int(carried_request["request_sequence"])
                        and int(row.get("application_sequence", "0"))
                        == int(carried_application["application_sequence"])
                        and int(row.get("actual_applied_code", "-1"))
                        == int(carried_application["applied_code"])
                        and int(row.get("actual_dac_epoch", "-1"))
                        == int(carried_application["dac_epoch"])
                        and row.get("response_class")
                        == carried_response["response_class"]
                    )
            authority_budget_suppressed = (
                authority_budget_suppression_candidate
                and carried_completed_transaction_exact
            )
            transaction_exact = (
                (replayed.requested_delta_codes == 0 and request is None)
                or (
                    replayed.requested_delta_codes != 0
                    and not controller.transaction_outstanding
                    and request is not None
                    and int(request["requested_delta_codes"])
                    == replayed.requested_delta_codes
                    and int(request["requested_code"]) == replayed.requested_code
                )
                or authority_budget_suppressed
            )
            response_exact = True
            predicted_sign_observed: bool | None = None
            response_checkpoint_passed: bool | None = None
            if response_horizon:
                if outstanding_decision_sequence is None:
                    raise ValueError("response horizon lacks an outstanding decision")
                application = mappings["application"].get(
                    outstanding_decision_sequence
                )
                response = mappings["response"].get(outstanding_decision_sequence)
                if application is None or response is None:
                    raise ValueError("response horizon lacks complete ACT evidence")
                requested_delta = int(response["requested_delta_codes"])
                predicted_sign_observed = (
                    float(response["observed_response_hz"]) * requested_delta > 0.0
                )
                admissible_response_classes = (
                    {
                        "healthy_detected",
                        "healthy_indeterminate_near_resolution",
                        "inside_deadband",
                        "limit_reached",
                        "wrong_sign",
                        "excess_response",
                        "growing_error",
                    }
                    if policy.response_checkpoint_observational
                    else {
                        "healthy_detected",
                        "healthy_indeterminate_near_resolution",
                        "inside_deadband",
                    }
                )
                response_exact = (
                    int(row["request_sequence"])
                    == int(response["request_sequence"])
                    and int(row["application_sequence"])
                    == int(application["application_sequence"])
                    and row["response_class"] == "unavailable"
                    and int(row["current_applied_code"])
                    == int(application["applied_code"])
                    and int(row["dac_epoch"]) == int(application["dac_epoch"])
                    and _ahy_act_frequency_close(
                        float(row["frequency_error_hz"]),
                        float(response["post_error_hz"]),
                    )
                    and int(row["decision_timestamp_s"])
                    - int(application["application_timestamp_s"])
                    >= policy.settling_exclusion_s + policy.fresh_support_s
                    and response["response_class"] in admissible_response_classes
                )
                response_checkpoint_passed = (
                    response_exact
                    and (
                        policy.response_checkpoint_observational
                        or not phase_checkpoint_required
                        or predicted_sign_observed
                    )
                )
                all_response_checkpoints_passed &= response_checkpoint_passed
                controller.note_response(
                    classification=response["response_class"],
                    predicted_sign_observed=predicted_sign_observed,
                    exact_replay=response_exact,
                    support_fresh=True,
                    applied_epoch_exact=(
                        int(response["applied_code"])
                        == int(application["applied_code"])
                        and int(response["dac_epoch"])
                        == int(application["dac_epoch"])
                    ),
                )
                completed_response_decisions.add(outstanding_decision_sequence)
                outstanding_decision_sequence = None

            row_exact = (
                identity_exact
                and numerical_exact
                and sequence_exact
                and transaction_exact
                and response_exact
            )
            comparisons.append(
                {
                    "decision_sequence": decision_sequence,
                    "requested_delta_codes": replayed.requested_delta_codes,
                    "requested_code": replayed.requested_code,
                    "counterfactual_frequency_only_delta_codes": (
                        replayed.counterfactual_frequency_only_delta_codes
                    ),
                    "phase_materially_influenced": (
                        replayed.phase_materially_influenced
                    ),
                    "response_horizon": response_horizon,
                    "identity_exact": identity_exact,
                    "numerical_exact": numerical_exact,
                    "sequence_exact": sequence_exact,
                    "transaction_binding_exact": transaction_exact,
                    "authority_budget_suppressed": authority_budget_suppressed,
                    "carried_completed_transaction_exact": (
                        carried_completed_transaction_exact
                    ),
                    "response_evidence_exact": response_exact,
                    "response_checkpoint_exact": response_exact,
                    "predicted_sign_observed": predicted_sign_observed,
                    "response_checkpoint_passed": response_checkpoint_passed,
                    "exact": row_exact,
                }
            )
            exact &= row_exact
            prior_record_sequence = record_sequence
            seen_decisions.add(decision_sequence)
            if replayed.requested_delta_codes != 0 and not authority_budget_suppressed:
                application = mappings["application"].get(decision_sequence)
                if application is None:
                    raise ValueError("nonzero AHY decision lacks ACT application")
                controller.note_application(
                    replayed,
                    applied_code=int(application["applied_code"]),
                    dac_epoch=int(application["dac_epoch"]),
                    downstream_consumers_exact=True,
                )
                outstanding_decision_sequence = decision_sequence
        except (KeyError, TypeError, ValueError) as exc:
            exact = False
            comparisons.append(
                {
                    "decision_sequence": row.get("decision_sequence"),
                    "exact": False,
                    "error": str(exc),
                }
            )

    unmatched_requests = sorted(set(mappings["request_created"]) - seen_decisions)
    completed_transactions = set(mappings["response"])
    exact &= (
        not unmatched_requests
        and bool(decisions)
        and completed_response_decisions == completed_transactions
        and not controller.transaction_outstanding
        and outstanding_decision_sequence is None
    )
    phase_nonzero_count = 0
    for row in decisions:
        try:
            phase_nonzero_count += float(row["phase_term_hz"]) != 0.0
        except (KeyError, TypeError, ValueError):
            exact = False
    return {
        "exact": exact,
        "decision_count": len(decisions),
        "phase_nonzero_decision_count": phase_nonzero_count,
        "phase_material_decision_count": sum(
            row.get("phase_materially_influenced") == "true" for row in decisions
        ),
        "unmatched_request_decision_sequences": unmatched_requests,
        "completed_response_decision_sequences": sorted(
            completed_response_decisions
        ),
        "all_response_checkpoints_passed": all_response_checkpoints_passed,
        "comparisons": comparisons,
    }


def _cx323_bool(row: dict[str, str], field: str) -> bool:
    value = row[field]
    if value not in {"true", "false"}:
        raise ValueError(f"CX323 AHM {field} is not canonical Boolean text")
    return value == "true"


def _cx323_state(controller: CX323PhasePriorityController) -> str:
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


def _cx323_snapshot_exact(
    row: dict[str, str],
    controller: CX323PhasePriorityController,
    *,
    suffix: str,
) -> bool:
    return (
        row[f"maintenance_state_{suffix}"] == _cx323_state(controller)
        and int(row[f"committed_fll_debt_{suffix}_picocodes"])
        == controller.debt.fll_picocodes
        and int(row[f"committed_pll_debt_{suffix}_picocodes"])
        == controller.debt.pll_picocodes
        and _cx323_bool(row, f"request_pending_{suffix}")
        == controller.request_pending
        and _cx323_bool(row, f"response_pending_{suffix}")
        == controller.response_pending
        and _cx323_bool(row, f"metadata_hold_{suffix}")
        == controller.metadata_hold
        and int(row[f"persistence_count_{suffix}"])
        == controller.persistence_count
        and int(row[f"requalification_window_count_{suffix}"])
        == controller.requalification_window_count
    )


def replay_cx323_maintenance_history(
    decisions: list[dict[str, str]],
    transactions: list[dict[str, str]],
    maintenance_rows: list[dict[str, str]],
    *,
    policy_path: Path,
    expected_run_identity: str,
    expected_build_identity: str,
    expected_profile_identity: str,
    expected_active_policy_sha256: str | None = None,
) -> dict[str, Any]:
    """Replay CX323 through its own oracle and authoritative AHM chronology.

    AHY remains the controller-content observation and ACT remains the actuator
    lifecycle, but neither serializes the persistent-window or tagged-debt
    state introduced by CX323.  AHM is therefore the state authority and the
    exact join that lets the independent Python oracle replay each decision and
    transaction boundary without routing the successor policy through the
    historical CX320/CX322 controller.
    """

    policy = load_cx323_policy(policy_path)
    active_policy_sha256 = expected_active_policy_sha256 or policy.policy_sha256
    if active_policy_sha256 != policy.policy_sha256:
        raise ValueError("CX323 replay policy identity differs from frozen profile")
    policy_document = json.loads(policy_path.read_text(encoding="utf-8"))
    estimator_sha256 = str(
        policy_document["bindings"]["frequency_estimator"]["sha256"]
    )
    decision_by_sequence: dict[int, dict[str, str]] = {}
    for row in decisions:
        sequence = int(row["decision_sequence"])
        if sequence <= 0 or sequence in decision_by_sequence:
            raise ValueError("CX323 AHY decision sequence is not unique and positive")
        decision_by_sequence[sequence] = row
    transaction_by_record: dict[int, dict[str, str]] = {}
    for row in transactions:
        record = int(row["transaction_record_sequence"])
        if record <= 0 or record in transaction_by_record:
            raise ValueError("CX323 ACT record sequence is not unique and positive")
        transaction_by_record[record] = row

    controller: CX323PhasePriorityController | None = None
    replayed_decisions: dict[int, CX323Decision] = {}
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
                and maintenance["profile_identity"] == expected_profile_identity
                and maintenance["policy_id"] == policy.policy_id
                and maintenance["active_policy_sha256"] == active_policy_sha256
                and maintenance["frequency_estimator_sha256"]
                == estimator_sha256
            )
            sequence_exact = record == previous_maintenance_record + 1
            if event == "policy_activation":
                if controller is not None or record != 1:
                    raise ValueError("CX323 policy activation is not the first AHM row")
                controller = CX323PhasePriorityController(
                    policy,
                    setup_applied_code=int(maintenance["current_applied_code"]),
                    setup_dac_epoch=int(maintenance["current_dac_epoch"]),
                )
                numerical_exact = (
                    maintenance["maintenance_state_before"] == "POLICY_INACTIVE"
                    and controller.applied_code == policy.setup_code
                    and controller.dac_epoch == 1
                    and _cx323_snapshot_exact(
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
                    raise ValueError("CX323 AHM event precedes policy activation")
                before_exact = _cx323_snapshot_exact(
                    maintenance, controller, suffix="before"
                )
                transaction_exact = True
                if event == "decision":
                    decision_sequence = int(maintenance["decision_sequence"])
                    source = decision_by_sequence.get(decision_sequence)
                    if source is None or decision_sequence in seen_decisions:
                        raise ValueError(
                            "CX323 AHM decision lacks one unique AHY source"
                        )
                    source_exact = (
                        int(source["hybrid_record_sequence"])
                        == int(maintenance["hybrid_record_sequence"])
                        and source["run_identity"] == expected_run_identity
                        and source["build_identity"] == expected_build_identity
                        and source["profile_identity"]
                        == expected_profile_identity
                        and source["active_policy_sha256"]
                        == active_policy_sha256
                        and int(source["capture_session"])
                        == int(maintenance["capture_session"])
                        and int(source["source_first_sequence"])
                        == int(maintenance["source_first_sequence"])
                        and int(source["source_last_sequence"])
                        == int(maintenance["source_last_sequence"])
                        and int(source["current_applied_code"])
                        == controller.applied_code
                        and int(source["dac_epoch"]) == controller.dac_epoch
                    )
                    reason = maintenance["reason"]
                    observation = CX323Observation(
                        timestamp_s=int(source["decision_timestamp_s"]),
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
                        phase_valid=_cx323_bool(maintenance, "phase_valid"),
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
                        + int(
                            maintenance[
                                "committed_fll_debt_before_picocodes"
                            ]
                        )
                        + int(
                            maintenance[
                                "committed_pll_debt_before_picocodes"
                            ]
                        )
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
                        and _cx323_snapshot_exact(
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
                            "CX323 transaction lifecycle lacks its originating decision"
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
                            first_consumer_exact=_cx323_bool(
                                maintenance, "downstream_epoch_exact"
                            ),
                        )
                    else:
                        controller.complete_response(fresh_exact=True)
                        completed_response_decisions.add(decision_sequence)
                    numerical_exact = before_exact and _cx323_snapshot_exact(
                        maintenance, controller, suffix="after"
                    )
                elif event == "gnss_metadata_hold_enter":
                    controller.enter_metadata_hold()
                    numerical_exact = before_exact and _cx323_snapshot_exact(
                        maintenance, controller, suffix="after"
                    )
                elif event == "gnss_metadata_requalified":
                    frontier = int(maintenance["source_last_sequence"])
                    if frontier <= 0:
                        raise ValueError(
                            "CX323 GNSS requalification lacks its causal D14/D8 frontier"
                        )
                    controller.requalify_metadata(frontier)
                    numerical_exact = before_exact and _cx323_snapshot_exact(
                        maintenance, controller, suffix="after"
                    )
                elif event == "fail_static":
                    controller._fail_static(maintenance["reason"])
                    numerical_exact = before_exact and _cx323_snapshot_exact(
                        maintenance, controller, suffix="after"
                    )
                else:
                    raise ValueError(f"unknown CX323 AHM event: {event}")

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
        "replay_mode": "cx323_phase_priority_oracle_with_AHM_v1",
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


def _await_cx323_maintenance_response(
    path: Path,
    *,
    response_row: dict[str, str],
) -> list[dict[str, str]]:
    """Bound the ACT-before-AHM splitter visibility interval for one burst."""

    deadline = time.monotonic() + CX323_MAINTENANCE_VISIBILITY_TIMEOUT_S
    while True:
        rows = _rows(path) if path.is_file() else []
        if any(
            row.get("event") == "response_complete"
            and row.get("transaction_record_sequence")
            == response_row.get("transaction_record_sequence")
            and row.get("request_sequence") == response_row.get("request_sequence")
            and row.get("decision_sequence") == response_row.get("decision_sequence")
            for row in rows
        ):
            return rows
        if time.monotonic() >= deadline:
            raise ValueError(
                "CX323 response AHM was not visible before phase-4 acknowledgement"
            )
        time.sleep(CX323_MAINTENANCE_VISIBILITY_POLL_S)


def replay_response_before_acknowledgement(
    *,
    active_hybrid_csv: Path,
    active_transactions_csv: Path,
    response_row: dict[str, str],
    policy_path: Path | None = None,
    expected_profile_identity: str = "cx320_active_hybrid",
    expected_active_policy_sha256: str | None = None,
    plant_sign_csv: Path | None = None,
    estimates_csv: Path | None = None,
    maintenance_csv: Path | None = None,
    maximum_applications: int | None = None,
    maximum_cumulative_movement_codes: int | None = None,
    phase_checkpoint_required: bool = True,
) -> dict[str, Any]:
    validation = validate_csv(
        active_hybrid_csv,
        CsvValidationContext("active_hybrid_decisions_v1", frozenset(), frozenset()),
    )
    if not validation.ok:
        raise ValueError("CX320 AHY evidence differs: " + "; ".join(validation.errors))
    if response_row.get("event") != "response":
        raise ValueError("CX320 response guard requires the ACT response record")
    request_sequence = int(response_row["request_sequence"])
    decision_sequence = int(response_row["decision_sequence"])
    all_transactions = _rows(active_transactions_csv)
    transactions = [
        row
        for row in all_transactions
        if int(row.get("request_sequence", "0")) == request_sequence
    ]
    events = [row.get("event") for row in transactions]
    if events != ["request_created", "core0_accepted", "application", "response"]:
        raise ValueError("CX320 transaction evidence is incomplete or out of order")
    if transactions[-1] != response_row:
        raise ValueError("CX320 response is not the exact retained terminal transaction row")
    all_decisions = _rows(active_hybrid_csv)
    decisions = [
        row for row in all_decisions if int(row["decision_sequence"]) == decision_sequence
    ]
    if len(decisions) != 1:
        raise ValueError("CX320 response does not identify exactly one AHY decision")
    decision = decisions[0]
    policy = load_policy() if policy_path is None else load_policy(policy_path)
    active_policy_sha256 = expected_active_policy_sha256 or policy.policy_sha256
    plant_sign_handoff = (
        None
        if plant_sign_csv is None
        else _cx321_natural_replay_handoff(
            _rows(plant_sign_csv), all_transactions
        )
    )
    if decision["active_policy_sha256"] != active_policy_sha256:
        raise ValueError("CX320 decision policy identity differs")
    if decision["run_identity"] != response_row["run_identity"]:
        raise ValueError("CX320 decision and transaction run identities differ")
    if decision["build_identity"] != response_row["build_identity"]:
        raise ValueError("CX320 decision and transaction build identities differ")
    if decision["profile_identity"] != expected_profile_identity:
        raise ValueError("CX320 decision profile identity differs")
    if isinstance(policy, CX323Policy):
        if maintenance_csv is None:
            raise ValueError("CX323 response replay requires retained AHM evidence")
        if policy_path is None:
            raise ValueError("CX323 response replay requires its frozen policy path")
        maintenance_rows = _await_cx323_maintenance_response(
            maintenance_csv, response_row=response_row
        )
        maintenance_validation = validate_csv(
            maintenance_csv,
            CsvValidationContext(
                "active_hybrid_maintenance_v1",
                frozenset(),
                frozenset({"rp2040_timer0_extended"}),
            ),
        )
        if not maintenance_validation.ok:
            raise ValueError(
                "CX323 AHM evidence differs: "
                + "; ".join(maintenance_validation.errors)
            )
        replay = replay_cx323_maintenance_history(
            all_decisions,
            all_transactions,
            maintenance_rows,
            policy_path=policy_path,
            expected_run_identity=decision["run_identity"],
            expected_build_identity=decision["build_identity"],
            expected_profile_identity=decision["profile_identity"],
            expected_active_policy_sha256=active_policy_sha256,
        )
        if not replay["exact"]:
            raise IndependentReplayMismatch(
                "CX323 independent host replay differs from AHM/firmware evidence"
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
            raise ValueError("CX323 request decision is absent from exact AHM replay")
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
            raise ValueError("CX323 applied code, epoch, or response evidence differs")
        predicted_sign_observed = (
            float(response["observed_response_hz"]) * requested_delta > 0.0
        )
        result: dict[str, Any] = {
            "schema_version": 1,
            "attestation_type": (
                "cx323_response_replayed_before_acknowledgement_v1"
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
    replay = replay_active_hybrid_history(
        all_decisions,
        all_transactions,
        policy_path=policy_path,
        expected_run_identity=decision["run_identity"],
        expected_build_identity=decision["build_identity"],
        expected_profile_identity=decision["profile_identity"],
        expected_active_policy_sha256=active_policy_sha256,
        plant_sign_handoff=plant_sign_handoff,
        estimate_rows=(None if estimates_csv is None else _rows(estimates_csv)),
        maximum_applications=maximum_applications,
        maximum_cumulative_movement_codes=maximum_cumulative_movement_codes,
        phase_checkpoint_required=phase_checkpoint_required,
    )
    if not replay["exact"]:
        raise IndependentReplayMismatch(
            "CX320 independent host replay differs from the firmware decision"
        )

    application = transactions[2]
    response = transactions[3]
    comparison = next(
        (
            item
            for item in replay["comparisons"]
            if int(item.get("decision_sequence", -1)) == decision_sequence
        ),
        None,
    )
    if comparison is None or not comparison.get("exact"):
        raise ValueError("CX320 request decision is absent from exact host replay")
    replayed_delta = int(comparison["requested_delta_codes"])
    replayed_code = int(comparison["requested_code"])
    counterfactual = int(comparison["counterfactual_frequency_only_delta_codes"])
    expected_material = bool(comparison["phase_materially_influenced"])
    predicted_sign_observed = (
        float(response["observed_response_hz"])
        * int(response["requested_delta_codes"])
        > 0.0
    )
    admissible_response_classes = (
        {
            "healthy_detected",
            "healthy_indeterminate_near_resolution",
            "inside_deadband",
            "limit_reached",
            "wrong_sign",
            "excess_response",
            "growing_error",
        }
        if policy.response_checkpoint_observational
        else {
            "healthy_detected",
            "healthy_indeterminate_near_resolution",
            "inside_deadband",
        }
    )
    if (
        int(application["applied_code"]) != replayed_code
        or int(application["dac_epoch"]) <= int(decision["dac_epoch"])
        or int(response["applied_code"]) != replayed_code
        or response["response_class"] not in admissible_response_classes
    ):
        raise ValueError("CX320 applied code, epoch, or response evidence differs")
    if (
        not predicted_sign_observed
        and phase_checkpoint_required
        and not policy.response_checkpoint_observational
    ):
        raise ResponseCheckpointRejected(
            "CX320 frozen response-sign checkpoint did not pass"
        )

    result: dict[str, Any] = {
        "schema_version": 1,
        "attestation_type": "cx320_response_replayed_before_acknowledgement_v1",
        "tool": TOOL_ID,
        "tool_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
        "request_sequence": request_sequence,
        "decision_sequence": decision_sequence,
        "transaction_record_sequence": int(response["transaction_record_sequence"]),
        "run_identity": decision["run_identity"],
        "build_identity": decision["build_identity"],
        "policy_sha256": decision["active_policy_sha256"],
        "requested_delta_codes": replayed_delta,
        "requested_code": replayed_code,
        "counterfactual_frequency_only_delta_codes": counterfactual,
        "phase_materially_influenced": expected_material,
        "applied_code": int(application["applied_code"]),
        "dac_epoch": int(application["dac_epoch"]),
        "response_class": response["response_class"],
        "predicted_sign_observed": predicted_sign_observed,
        "response_checkpoint_mode": (
            "observational_non_terminal"
            if policy.response_checkpoint_observational
            or not phase_checkpoint_required
            else "admission_gate"
        ),
        "exact_replay": True,
    }
    result["attestation_sha256"] = sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return result
