from __future__ import annotations

import csv
from pathlib import Path

from host.otis_tools.active_transactions import validate_transaction_history
from host.otis_tools.contracts import (
    ACTIVE_TRANSACTION_V1_FIELDS,
    CsvValidationContext,
    validate_csv,
)
from host.otis_tools.no_write_qualification_supervisor import (
    load_no_write_qualification_spec,
)


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def test_core0_rejection_bypass_is_exactly_metadata_hold_and_pre_acceptance() -> None:
    live = (FIRMWARE / "otis_cx317_active_live.cpp").read_text(encoding="utf-8")
    start = live.index("bool otis_cx317_active_live_on_cross_core_ack(")
    end = live.index("bool otis_cx317_active_live_manual_start_allowed", start)
    handler = live[start:end]
    special = handler[
        handler.index("const bool exact_metadata_rejection_context") :
        handler.index("const bool guard_acknowledged")
    ]

    for required in (
        "OtisActuatorAckKind::Rejected",
        "OtisActuatorRejectionReason::MetadataHoldCancelledBeforeAcceptance",
        "gnss_metadata_hold_active",
        "gnss_metadata_hold_transaction_pending",
        "OtisCx317ActiveState::RequestPending",
        "evidence_phase == EvidencePhase::None",
        "OtisActuatorGuardState::AwaitingAcceptance",
        "otis_actuator_guard_discard_exact_rejection",
        "otis_cx317_active_discard_released_request_on_metadata_rejection",
        "gnss_metadata_hold_applied_code",
        "gnss_metadata_hold_dac_epoch",
        'queue_frame("request_withdrawn"',
        '"request_withdrawn", rejection_ticks',
        '"gnss_metadata_unqualified_hold"',
    ):
        assert required in special

    cleanup = special.index(
        "otis_cx317_active_discard_released_request_on_metadata_rejection"
    )
    withdrawal = special.index('queue_frame("request_withdrawn"')
    timing_sidecar = special.index('"request_withdrawn", rejection_ticks')
    reference_hold = special.index("otis_cx317_active_reference_hold")
    assert cleanup < withdrawal < timing_sidecar < reference_hold

    # A contradictory tuple deliberately rejoins the established guard path;
    # all Rejected outcomes outside the special context take the legacy path.
    assert "(void)otis_actuator_guard_acknowledge" in special
    assert handler.index("const bool exact_metadata_rejection_context") < handler.index(
        "const bool guard_acknowledged"
    )
    assert "cross_core_actuator_rejected_or_bad_phase" in handler

    core0 = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    producer_start = core0.index("void service_dual_core_actuator_request(")
    producer_end = core0.index("bool publish_dual_core_setup_ack", producer_start)
    producer = core0[producer_start:producer_end]
    for platform_reason in (
        "PlatformFailStatic",
        "GuardStartRejected",
        "GuardAcknowledgementRejected",
        "InvalidExecutionPhase",
        "AcknowledgementDeadlineExpired",
        "ExecutionIdentityMismatch",
    ):
        assert f"OtisActuatorRejectionReason::{platform_reason}" in producer
    assert "MetadataHoldCancelledBeforeAcceptance" not in producer


def test_rejection_cleanup_preserves_code_epoch_and_clears_all_pending_state() -> None:
    transaction = (FIRMWARE / "otis_cx317_active_transaction.cpp").read_text(
        encoding="utf-8"
    )
    start = transaction.index(
        "bool otis_cx317_active_discard_released_request_on_metadata_rejection("
    )
    end = transaction.index(
        "bool otis_cx317_active_acknowledge_application", start
    )
    cleanup = transaction[start:end]

    assert "const uint16_t unchanged_code = transaction->applied_code" in cleanup
    assert "const uint32_t unchanged_epoch = transaction->dac_epoch" in cleanup
    assert "transaction->have_request = false" in cleanup
    assert "transaction->have_acceptance = false" in cleanup
    assert "transaction->have_application = false" in cleanup
    assert "*pending_request = {}" in cleanup
    assert "*pending_request_valid = false" in cleanup
    assert "*metadata_hold_transaction_pending = false" in cleanup
    assert "transaction->state == OtisCx317ActiveState::Disarmed" in cleanup
    assert "transaction->applied_code == unchanged_code" in cleanup
    assert "transaction->dac_epoch == unchanged_epoch" in cleanup
    assert "metadata_hold_cancelled_before_acceptance" in cleanup
    assert "otis_cx317_active_reference_hold" not in cleanup

    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    core0_start = sketch.index("void service_dual_core_actuator_request(")
    core0_end = sketch.index("void service_dual_core_outputs", core0_start)
    core0 = sketch[core0_start:core0_end]
    assert (
        "acknowledgement.applied_code = request.current_applied_code" in core0
    )


def test_disarmed_firmware_withdrawal_validates_under_existing_host_contract(
    tmp_path: Path,
) -> None:
    """Model the exact ACT1 fields serialized between cleanup and hold entry."""

    spec, identities, _ = load_no_write_qualification_spec("A")
    digest = "a" * 64
    build_identity = f"{digest}:{'b' * 64}"
    values = {field: "" for field in ACTIVE_TRANSACTION_V1_FIELDS}
    values.update(
        {
            "record_type": "ACT",
            "schema_version": "1",
            "transaction_record_sequence": "1",
            "event": "manual_start",
            "run_identity": spec.run_identity,
            "build_identity": build_identity,
            "profile_identity": spec.profile,
            **identities,
            "session_id": "9",
            "authorization_sequence": "0",
            "nonce": "0",
            "request_sequence": "0",
            "decision_sequence": "0",
            "source_first_sequence": "0",
            "source_last_sequence": "0",
            "decision_timestamp_s": "0",
            "current_applied_code": str(spec.start_code),
            "requested_delta_codes": "0",
            "requested_code": str(spec.start_code),
            "correction_ordinal": "0",
            "cumulative_after_codes": "0",
            "pre_error_hz": "0.000000000",
            "accepted_code": str(spec.start_code),
            "accepted_timestamp_s": "0",
            "applied_code": str(spec.start_code),
            "application_sequence": "0",
            "application_timestamp_s": "0",
            "i2c_ok": "true",
            "clamped": "false",
            "ambiguous": "false",
            "dac_epoch": "0",
            "estimator_history_reset": "false",
            "correction_count": "0",
            "cumulative_movement_codes": "0",
            "post_error_hz": "0.000000000",
            "observed_response_hz": "0.000000000",
            "cumulative_response_hz": "0.000000000",
            "consecutive_indeterminate": "0",
            "active_state": "DISARMED",
            "response_class": "unavailable",
            "reason": "manual_start_established",
            "actionable": "false",
            "evidence_state": "evidence_clear",
        }
    )
    manual_start = dict(values)

    request_created = dict(values)
    request_created.update(
        {
            "transaction_record_sequence": "2",
            "event": "request_created",
            "authorization_sequence": "1",
            "nonce": "12345",
            "request_sequence": "1",
            "decision_sequence": "81",
            "source_first_sequence": "100",
            "source_last_sequence": "699",
            "decision_timestamp_s": "2400",
            "requested_delta_codes": "7",
            "requested_code": str(spec.start_code + 7),
            "correction_ordinal": "1",
            "cumulative_after_codes": "7",
            "pre_error_hz": "0.020000000",
            "accepted_code": "0",
            "applied_code": "0",
            "i2c_ok": "false",
            "dac_epoch": "4",
            "active_state": "REQUEST_PENDING",
            "reason": "request_created",
            "evidence_state": "request_pending",
        }
    )
    # The cleanup helper preserves the immutable request and exact DAC epoch,
    # clears authority/application fields, and leaves DISARMED for queue_frame.
    request_withdrawn = dict(request_created)
    request_withdrawn.update(
        {
            "transaction_record_sequence": "3",
            "event": "request_withdrawn",
            "active_state": "DISARMED",
            "reason": "gnss_metadata_core0_rejection_discarded",
            "evidence_state": "evidence_clear",
        }
    )
    rows = [manual_start, request_created, request_withdrawn]
    path = tmp_path / "active_transactions_v1.csv"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ACTIVE_TRANSACTION_V1_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    result = validate_csv(
        path,
        CsvValidationContext("active_transactions_v1", frozenset(), frozenset()),
    )
    assert result.row_count == 3
    assert result.errors == ()
    validate_transaction_history(
        rows,
        spec,
        identities,
        build_identity,
        dual_core=True,
    )

    queue_source = (FIRMWARE / "otis_cx317_active_live.cpp").read_text(
        encoding="utf-8"
    )
    queue_start = queue_source.index("bool queue_frame(")
    queue_end = queue_source.index("bool queue_manual_start_frame", queue_start)
    formatter = queue_source[queue_start:queue_end]
    assert "otis_cx317_active_state_name(transaction.state)" in formatter
