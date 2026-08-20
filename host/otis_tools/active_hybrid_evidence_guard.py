"""Independent CX320 decision replay required before a response ACKE."""

from __future__ import annotations

import csv
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any

from .active_hybrid_policy import _round_half_away, load_policy
from .contracts import CsvValidationContext, validate_csv


TOOL_ID = "cx320_active_hybrid_response_evidence_guard_v1"


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _close(observed: float, expected: float) -> bool:
    return math.isclose(observed, expected, rel_tol=0, abs_tol=5e-12)


def replay_response_before_acknowledgement(
    *,
    active_hybrid_csv: Path,
    active_transactions_csv: Path,
    response_row: dict[str, str],
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
    transactions = [
        row
        for row in _rows(active_transactions_csv)
        if int(row.get("request_sequence", "0")) == request_sequence
    ]
    events = [row.get("event") for row in transactions]
    if events != ["request_created", "core0_accepted", "application", "response"]:
        raise ValueError("CX320 transaction evidence is incomplete or out of order")
    if transactions[-1] != response_row:
        raise ValueError("CX320 response is not the exact retained terminal transaction row")
    decisions = [
        row
        for row in _rows(active_hybrid_csv)
        if int(row["decision_sequence"]) == decision_sequence
    ]
    if len(decisions) != 1:
        raise ValueError("CX320 response does not identify exactly one AHY decision")
    decision = decisions[0]
    policy = load_policy()
    if decision["active_policy_sha256"] != policy.policy_sha256:
        raise ValueError("CX320 decision policy identity differs")
    if decision["run_identity"] != response_row["run_identity"]:
        raise ValueError("CX320 decision and transaction run identities differ")
    if decision["build_identity"] != response_row["build_identity"]:
        raise ValueError("CX320 decision and transaction build identities differ")
    if decision["profile_identity"] != "cx320_active_hybrid":
        raise ValueError("CX320 decision profile identity differs")

    frequency_error = float(decision["frequency_error_hz"])
    relative_phase = int(decision["relative_phase_cycles"])
    frequency_term = -frequency_error
    phase_authorized = decision["state_before"] in {"PHASE_QUALIFY", "HYBRID_TRACKING"}
    phase_term = (
        max(
            -policy.phase_bias_cap_hz,
            min(policy.phase_bias_cap_hz, -relative_phase / policy.pull_in_time_s),
        )
        if phase_authorized
        else 0.0
    )
    combined = frequency_term + phase_term if phase_authorized else frequency_term
    raw_delta = policy.integrator_gain_codes_per_hz_per_decision * combined
    limited = max(-policy.maximum_step_codes, min(policy.maximum_step_codes, raw_delta))
    replayed_delta = _round_half_away(limited)
    current_code = int(decision["current_applied_code"])
    replayed_code = max(
        policy.minimum_code,
        min(policy.maximum_code, current_code + replayed_delta),
    )
    replayed_delta = replayed_code - current_code
    if phase_authorized and replayed_delta != 0 and replayed_delta * phase_term < 0:
        replayed_delta = 0
        replayed_code = current_code
    counterfactual = 0 if phase_authorized else replayed_delta
    if any(
        decision[name] == "true"
        for name in ("cadence_limited", "count_limited", "cumulative_budget_limited")
    ):
        replayed_delta = 0
        replayed_code = current_code
    expected_material = phase_term != 0.0 and replayed_delta != counterfactual
    exact = (
        _close(float(decision["frequency_term_hz"]), frequency_term)
        and _close(float(decision["phase_term_hz"]), phase_term)
        and _close(float(decision["combined_demand_hz"]), combined)
        and _close(float(decision["raw_combined_delta_codes"]), raw_delta)
        and int(decision["requested_delta_codes"]) == replayed_delta
        and int(decision["requested_code"]) == replayed_code
        and int(decision["counterfactual_frequency_only_delta_codes"]) == counterfactual
        and (decision["phase_materially_influenced"] == "true") == expected_material
    )
    if not exact:
        raise ValueError("CX320 independent host replay differs from the firmware decision")

    application = transactions[2]
    response = transactions[3]
    if (
        int(application["applied_code"]) != replayed_code
        or int(application["dac_epoch"]) <= int(decision["dac_epoch"])
        or int(response["applied_code"]) != replayed_code
        or response["response_class"]
        not in {"healthy_detected", "healthy_indeterminate_near_resolution"}
    ):
        raise ValueError("CX320 applied code, epoch, or response checkpoint differs")

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
        "exact_replay": True,
    }
    result["attestation_sha256"] = sha256(
        json.dumps(result, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    return result
