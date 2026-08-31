from __future__ import annotations

import csv
from pathlib import Path

from host.otis_tools.capture_serial import CsvRecordSplitter, RECORD_CONTRACTS
from host.otis_tools.contracts import (
    ACTIVE_HYBRID_MAINTENANCE_V1_FIELDS,
    CsvValidationContext,
    validate_csv,
)


SHA256 = "a" * 64
ROOT = Path(__file__).resolve().parents[1]


def _row(sequence: int, event: str = "decision") -> dict[str, str]:
    row = {field: "0" for field in ACTIVE_HYBRID_MAINTENANCE_V1_FIELDS}
    row.update(
        {
            "record_type": "AHM",
            "schema_version": "1",
            "maintenance_record_sequence": str(sequence),
            "event": event,
            "event_timestamp_ticks": str(1_000_000 * sequence),
            "time_domain": "rp2040_timer0_extended",
            "run_identity": "cx323_d9_d6_72h_adaptive_hybrid:1",
            "build_identity": f"{SHA256}:{SHA256}",
            "profile_identity": "cx323_d9_d6_72h_adaptive_hybrid",
            "policy_id": "CX323_PHASE_PRIORITY_PERSISTENT_MAINTENANCE_V1",
            "active_policy_sha256": SHA256,
            "capture_session": "7",
            "source_first_sequence": "1200",
            "source_last_sequence": "1800",
            "frequency_estimator_sha256": SHA256,
            "phase_epoch": "3",
            "phase_observation_sequence": "1800",
            "phase_valid": "true",
            "current_applied_code": "43085",
            "current_dac_epoch": "13",
            "hybrid_record_sequence": str(sequence),
            "hybrid_timing_record_sequence": str(sequence),
            "decision_sequence": str(sequence),
            "transaction_record_sequence": "0",
            "transaction_timing_record_sequence": "0",
            "transaction_event": "none",
            "request_sequence": "0",
            "application_sequence": "0",
            "actual_applied_code": "0",
            "actual_dac_epoch": "0",
            "downstream_epoch_exact": "false",
            "maintenance_state_before": "READY",
            "maintenance_state_after": "PERSISTENCE_HOLD",
            "frontier_relation": "contiguous",
            "interval_sign": "1",
            "persistence_count_before": "0",
            "persistence_count_after": "1",
            "raw_fll_demand_picocodes": "5000000000000",
            "raw_pll_demand_picocodes": "475213574925",
            "candidate_total_demand_picocodes": "5475213574925",
            "safe_cap_codes": "6",
            "requested_delta_codes": "0",
            "requested_code": "43085",
            "committed_fll_debt_before_picocodes": "250000000000",
            "committed_pll_debt_before_picocodes": "100000000000",
            "committed_fll_debt_after_picocodes": "250000000000",
            "committed_pll_debt_after_picocodes": "100000000000",
            "request_pending_before": "false",
            "request_pending_after": "false",
            "response_pending_before": "false",
            "response_pending_after": "false",
            "metadata_hold_before": "false",
            "metadata_hold_after": "false",
            "requalification_window_count_before": "0",
            "requalification_window_count_after": "0",
            "evidence_burst_sequence": str(sequence),
            "evidence_burst_record_ordinal": "3",
            "evidence_burst_record_count": "3",
            "reason": "persistence_first_interval_hold",
            "actionable": "false",
        }
    )
    return row


def _transaction_row(
    sequence: int, event: str, transaction_event: str
) -> dict[str, str]:
    row = _row(sequence, event)
    row.update(
        {
            "transaction_record_sequence": str(100 + sequence),
            "transaction_timing_record_sequence": str(200 + sequence),
            "transaction_event": transaction_event,
            "request_sequence": "9",
            "requested_delta_codes": "5",
            "requested_code": "43090",
            "evidence_burst_record_ordinal": "3",
            "evidence_burst_record_count": "3",
        }
    )
    return row


def _write(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=ACTIVE_HYBRID_MAINTENANCE_V1_FIELDS
        )
        writer.writeheader()
        writer.writerows(rows)


def _context() -> CsvValidationContext:
    return CsvValidationContext(
        "active_hybrid_maintenance_v1",
        frozenset(),
        frozenset({"rp2040_timer0_extended"}),
    )


def test_complete_ahm_lifecycle_validates_and_preserves_exact_joins(
    tmp_path: Path,
) -> None:
    activation = _row(1, "policy_activation")
    activation.update(
        {
            "source_first_sequence": "0",
            "source_last_sequence": "0",
            "hybrid_record_sequence": "0",
            "hybrid_timing_record_sequence": "0",
            "decision_sequence": "0",
            "maintenance_state_before": "POLICY_INACTIVE",
            "maintenance_state_after": "READY",
            "frontier_relation": "not_applicable",
            "persistence_count_after": "0",
            "committed_fll_debt_after_picocodes": "0",
            "committed_pll_debt_after_picocodes": "0",
            "evidence_burst_record_ordinal": "1",
            "evidence_burst_record_count": "1",
            "reason": "new_policy_activation",
        }
    )

    hold = _row(2)

    request = _row(3)
    request.update(
        {
            "transaction_record_sequence": "103",
            "transaction_timing_record_sequence": "203",
            "transaction_event": "request_created",
            "request_sequence": "9",
            "maintenance_state_before": "PERSISTENCE_HOLD",
            "maintenance_state_after": "REQUEST_PENDING",
            "persistence_count_before": "1",
            "persistence_count_after": "2",
            "requested_delta_codes": "5",
            "requested_code": "43090",
            "request_pending_after": "true",
            "evidence_burst_record_ordinal": "5",
            "evidence_burst_record_count": "5",
            "reason": "maintenance_request_ready",
        }
    )

    rejected = _transaction_row(
        4, "request_rejected_or_expired", "request_withdrawn"
    )
    rejected.update(
        {
            "maintenance_state_before": "REQUEST_PENDING",
            "maintenance_state_after": "PERSISTENCE_HOLD",
            "request_pending_before": "true",
            "reason": "request_expired",
        }
    )

    application = _transaction_row(
        5, "application_first_consumer", "application"
    )
    application.update(
        {
            "application_sequence": "4",
            "actual_applied_code": "43090",
            "actual_dac_epoch": "14",
            "downstream_epoch_exact": "true",
            "maintenance_state_before": "REQUEST_PENDING",
            "maintenance_state_after": "RESPONSE_PENDING",
            "request_pending_before": "true",
            "response_pending_after": "true",
            "persistence_count_before": "2",
            "persistence_count_after": "0",
            "committed_fll_debt_after_picocodes": "307504602373",
            "committed_pll_debt_after_picocodes": "34167178042",
            "reason": "exact_application_and_first_consumer",
        }
    )

    response = _transaction_row(6, "response_complete", "response")
    response.update(
        {
            "maintenance_state_before": "RESPONSE_PENDING",
            "maintenance_state_after": "READY",
            "response_pending_before": "true",
            "committed_fll_debt_before_picocodes": "307504602373",
            "committed_pll_debt_before_picocodes": "34167178042",
            "committed_fll_debt_after_picocodes": "307504602373",
            "committed_pll_debt_after_picocodes": "34167178042",
            "reason": "fresh_exact_response_complete",
        }
    )

    metadata_hold = _row(7, "gnss_metadata_hold_enter")
    metadata_hold.update(
        {
            "maintenance_state_after": "METADATA_HOLD",
            "frontier_relation": "not_applicable",
            "metadata_hold_after": "true",
            "persistence_count_after": "0",
            "evidence_burst_record_ordinal": "1",
            "evidence_burst_record_count": "1",
            "reason": "recoverable_gnss_metadata_anomaly",
        }
    )
    metadata_requalified = _row(8, "gnss_metadata_requalified")
    metadata_requalified.update(
        {
            "maintenance_state_before": "METADATA_HOLD",
            "maintenance_state_after": "METADATA_HOLD",
            "frontier_relation": "not_applicable",
            "metadata_hold_before": "true",
            "metadata_hold_after": "true",
            "evidence_burst_record_ordinal": "1",
            "evidence_burst_record_count": "1",
            "reason": "fresh_same_receiver_metadata",
        }
    )

    first_post_requalification_window = _row(9)
    first_post_requalification_window.update(
        {
            "maintenance_state_before": "METADATA_HOLD",
            "maintenance_state_after": "METADATA_HOLD",
            "metadata_hold_before": "true",
            "metadata_hold_after": "true",
            "requalification_window_count_before": "0",
            "requalification_window_count_after": "1",
            "reason": "post_requalification_first_window_hold",
        }
    )
    second_post_requalification_window = _row(10)
    second_post_requalification_window.update(
        {
            "maintenance_state_before": "METADATA_HOLD",
            "maintenance_state_after": "PERSISTENCE_HOLD",
            "metadata_hold_before": "true",
            "metadata_hold_after": "false",
            "requalification_window_count_before": "1",
            "requalification_window_count_after": "2",
            "reason": "post_requalification_second_window_complete",
        }
    )

    fail_static = _row(11, "fail_static")
    fail_static.update(
        {
            "maintenance_state_before": "REQUEST_PENDING",
            "maintenance_state_after": "FAIL_STATIC",
            "frontier_relation": "not_applicable",
            "transaction_event": "application_fault",
            "transaction_record_sequence": "111",
            "transaction_timing_record_sequence": "211",
            "request_sequence": "9",
            "evidence_burst_record_ordinal": "3",
            "evidence_burst_record_count": "3",
            "reason": "unknown_application_or_dac_epoch",
        }
    )

    path = tmp_path / "active_hybrid_maintenance_v1.csv"
    _write(
        path,
        [
            activation,
            hold,
            request,
            rejected,
            application,
            response,
            metadata_hold,
            metadata_requalified,
            first_post_requalification_window,
            second_post_requalification_window,
            fail_static,
        ],
    )

    result = validate_csv(path, _context())
    assert result.row_count == 11
    assert result.errors == ()


def test_ahm_rejects_partial_join_early_debt_commit_and_partial_burst(
    tmp_path: Path,
) -> None:
    row = _transaction_row(
        1, "request_rejected_or_expired", "request_withdrawn"
    )
    row.update(
        {
            "hybrid_timing_record_sequence": "0",
            "request_pending_before": "true",
            "committed_fll_debt_after_picocodes": "250000000001",
            "evidence_burst_record_count": "2",
        }
    )
    path = tmp_path / "invalid_ahm.csv"
    _write(path, [row])

    errors = " ".join(validate_csv(path, _context()).errors)
    assert "requires non-zero hybrid_timing_record_sequence" in errors
    assert "must preserve both committed debt tags" in errors
    assert "burst must contain ACT, AT2, and AHM" in errors


def test_ahm_rejects_application_without_exact_first_consumer(
    tmp_path: Path,
) -> None:
    row = _transaction_row(1, "application_first_consumer", "application")
    row.update(
        {
            "application_sequence": "4",
            "actual_applied_code": "43090",
            "actual_dac_epoch": "14",
            "maintenance_state_before": "REQUEST_PENDING",
            "maintenance_state_after": "RESPONSE_PENDING",
            "request_pending_before": "true",
            "response_pending_after": "true",
            "downstream_epoch_exact": "false",
        }
    )
    path = tmp_path / "invalid_application_ahm.csv"
    _write(path, [row])

    errors = " ".join(validate_csv(path, _context()).errors)
    assert "exact request-to-response-pending propagation transition" in errors


def test_capture_splitter_registers_exact_ahm_wire_contract(tmp_path: Path) -> None:
    assert RECORD_CONTRACTS["AHM"] == "active_hybrid_maintenance_v1"
    path = tmp_path / "active_hybrid_maintenance_v1.csv"
    row = _row(1)
    with CsvRecordSplitter({"active_hybrid_maintenance_v1": path}) as splitter:
        line = ",".join(
            row[field] for field in ACTIVE_HYBRID_MAINTENANCE_V1_FIELDS
        )
        assert splitter.process_line(line) == "active_hybrid_maintenance_v1"

    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == ",".join(ACTIVE_HYBRID_MAINTENANCE_V1_FIELDS)
    assert lines[1].startswith("AHM,1,")


def test_normative_ahm_document_freezes_the_executable_field_order() -> None:
    contract = (
        ROOT
        / "docs/50_SOFTWARE/CX323_ACTIVE_HYBRID_MAINTENANCE_EVIDENCE_CONTRACT.md"
    ).read_text(encoding="utf-8")
    ordered_schema = contract.split("```text\n", 1)[1].split("\n```", 1)[0]

    assert ordered_schema.split(",") == ACTIVE_HYBRID_MAINTENANCE_V1_FIELDS
