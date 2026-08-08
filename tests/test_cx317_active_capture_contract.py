from __future__ import annotations

import csv
from pathlib import Path

from host.otis_tools.capture_serial import CsvRecordSplitter
from host.otis_tools.contracts import (
    ACTIVE_TRANSACTION_V1_FIELDS,
    CsvValidationContext,
    validate_csv,
)


def _row(sequence: int, event: str, evidence_state: str) -> dict[str, str]:
    digest = "a" * 64
    values = {field: "" for field in ACTIVE_TRANSACTION_V1_FIELDS}
    values.update(
        {
            "record_type": "ACT",
            "schema_version": "1",
            "transaction_record_sequence": str(sequence),
            "event": event,
            "run_identity": "cx317_bounded_campaign_a:3170001",
            "build_identity": f"{digest}:{digest}",
            "profile_identity": "cx317_bounded_active_campaign_a",
            "session_id": "9",
            "authorization_sequence": "4",
            "nonce": "12345",
            "request_sequence": "1",
            "decision_sequence": "81",
            "source_first_sequence": "100",
            "source_last_sequence": "699",
            "decision_timestamp_s": "2400",
            "current_applied_code": "43344",
            "requested_delta_codes": "-21",
            "requested_code": "43323",
            "correction_ordinal": "1",
            "cumulative_after_codes": "21",
            "pre_error_hz": "0.020000000",
            "accepted_code": "43323",
            "accepted_timestamp_s": "2400",
            "applied_code": "43323" if event != "request_accepted" else "0",
            "application_sequence": "1" if event != "request_accepted" else "0",
            "application_timestamp_s": "2401" if event != "request_accepted" else "0",
            "i2c_ok": "true" if event != "request_accepted" else "false",
            "clamped": "false",
            "ambiguous": "false",
            "dac_epoch": "1" if event != "request_accepted" else "0",
            "estimator_history_reset": "true" if event != "request_accepted" else "false",
            "correction_count": "1" if event != "request_accepted" else "0",
            "cumulative_movement_codes": "21" if event != "request_accepted" else "0",
            "post_error_hz": "0.0165" if event == "response" else "0.0",
            "observed_response_hz": "-0.0035" if event == "response" else "0.0",
            "cumulative_response_hz": "-0.0035" if event == "response" else "0.0",
            "consecutive_indeterminate": "0",
            "active_state": (
                "ACCEPTED_AWAITING_APPLICATION"
                if event == "request_accepted"
                else "AWAITING_RESPONSE" if event == "application" else "DISARMED"
            ),
            "response_class": "healthy_detected" if event == "response" else "unavailable",
            "reason": "fixture",
            "estimator_sha256": digest,
            "model_sha256": digest,
            "active_policy_sha256": digest,
            "response_policy_sha256": digest,
            "numerical_policy_sha256": digest,
            "actionable": "false",
            "evidence_state": evidence_state,
        }
    )
    return values


def test_act_records_are_split_and_validate_as_durable_three_phase_evidence(
    tmp_path: Path,
) -> None:
    path = tmp_path / "active_transactions_v1.csv"
    rows = (
        _row(1, "request_accepted", "request_pending"),
        _row(2, "application", "application_pending"),
        _row(3, "response", "response_pending"),
    )
    with CsvRecordSplitter({"active_transactions_v1": path}) as splitter:
        for row in rows:
            line = ",".join(row[field] for field in ACTIVE_TRANSACTION_V1_FIELDS)
            assert splitter.process_line(line) == "active_transactions_v1"

    result = validate_csv(
        path,
        CsvValidationContext("active_transactions_v1", frozenset(), frozenset()),
    )
    assert result.row_count == 3
    assert result.errors == ()


def test_act_contract_rejects_actionable_or_wrong_evidence_phase(tmp_path: Path) -> None:
    path = tmp_path / "active_transactions_v1.csv"
    row = _row(1, "request_accepted", "application_pending")
    row["actionable"] = "true"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ACTIVE_TRANSACTION_V1_FIELDS)
        writer.writeheader()
        writer.writerow(row)

    result = validate_csv(
        path,
        CsvValidationContext("active_transactions_v1", frozenset(), frozenset()),
    )
    assert any("must never be actionable" in error for error in result.errors)
    assert any("requires evidence_state=request_pending" in error for error in result.errors)


def test_request_created_is_non_actionable_durable_evidence(
    tmp_path: Path,
) -> None:
    path = tmp_path / "active_transactions_v1.csv"
    row = _row(1, "request_created", "request_pending")
    row.update(
        {
            "accepted_code": "0",
            "accepted_timestamp_s": "0",
            "applied_code": "0",
            "application_sequence": "0",
            "application_timestamp_s": "0",
            "i2c_ok": "false",
            "dac_epoch": "0",
            "estimator_history_reset": "false",
            "correction_count": "0",
            "cumulative_movement_codes": "0",
            "active_state": "REQUEST_PENDING",
            "actionable": "false",
        }
    )
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ACTIVE_TRANSACTION_V1_FIELDS)
        writer.writeheader()
        writer.writerow(row)

    result = validate_csv(
        path,
        CsvValidationContext(
            "active_transactions_v1", frozenset(), frozenset()
        ),
    )
    assert result.row_count == 1
    assert result.errors == ()


def test_act_contract_accepts_durable_out_of_model_hold_response(
    tmp_path: Path,
) -> None:
    path = tmp_path / "active_transactions_v1.csv"
    row = _row(4, "response", "response_pending")
    row["active_state"] = "OUT_OF_MODEL_HOLD"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ACTIVE_TRANSACTION_V1_FIELDS)
        writer.writeheader()
        writer.writerow(row)

    result = validate_csv(
        path,
        CsvValidationContext("active_transactions_v1", frozenset(), frozenset()),
    )
    assert result.row_count == 1
    assert result.errors == ()
