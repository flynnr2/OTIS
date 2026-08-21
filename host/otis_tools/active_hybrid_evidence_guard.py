"""Independent CX320 decision replay required before a response ACKE."""

from __future__ import annotations

import csv
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any

from .active_hybrid_policy import ActiveHybridController, HybridObservation, load_policy
from .contracts import CsvValidationContext, validate_csv


TOOL_ID = "cx320_active_hybrid_response_evidence_guard_v1"
FROZEN_AHY_FRACTIONAL_DECIMAL_PLACES = 12
FROZEN_ACT_FREQUENCY_DECIMAL_PLACES = 9
FROZEN_AHY_HALF_SERIALIZATION_QUANTUM = (
    0.5 * 10**-FROZEN_AHY_FRACTIONAL_DECIMAL_PLACES
)
FROZEN_ACT_FREQUENCY_HALF_SERIALIZATION_QUANTUM = (
    0.5 * 10**-FROZEN_ACT_FREQUENCY_DECIMAL_PLACES
)


class ResponseCheckpointRejected(ValueError):
    """The evidence replayed exactly but failed a frozen response predicate."""


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


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
    controller = ActiveHybridController(
        policy, setup_application_s=setup_application_s
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
                timestamp_s=int(row["decision_timestamp_s"]),
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
                    and response["response_class"]
                    in {
                        "healthy_detected",
                        "healthy_indeterminate_near_resolution",
                        "inside_deadband",
                    }
                )
                response_checkpoint_passed = (
                    response_exact and predicted_sign_observed
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
            if replayed.requested_delta_codes != 0:
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


def replay_response_before_acknowledgement(
    *,
    active_hybrid_csv: Path,
    active_transactions_csv: Path,
    response_row: dict[str, str],
    policy_path: Path | None = None,
    expected_profile_identity: str = "cx320_active_hybrid",
    expected_active_policy_sha256: str | None = None,
    plant_sign_csv: Path | None = None,
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
    replay = replay_active_hybrid_history(
        all_decisions,
        all_transactions,
        policy_path=policy_path,
        expected_run_identity=decision["run_identity"],
        expected_build_identity=decision["build_identity"],
        expected_profile_identity=decision["profile_identity"],
        expected_active_policy_sha256=active_policy_sha256,
        plant_sign_handoff=plant_sign_handoff,
    )
    if not replay["exact"]:
        raise ValueError("CX320 independent host replay differs from the firmware decision")

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
    if (
        int(application["applied_code"]) != replayed_code
        or int(application["dac_epoch"]) <= int(decision["dac_epoch"])
        or int(response["applied_code"]) != replayed_code
        or response["response_class"]
        not in {
            "healthy_detected",
            "healthy_indeterminate_near_resolution",
            "inside_deadband",
        }
    ):
        raise ValueError("CX320 applied code, epoch, or response evidence differs")
    if not predicted_sign_observed:
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
        "exact_replay": True,
    }
    result["attestation_sha256"] = sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return result
