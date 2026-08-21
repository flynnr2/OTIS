"""Exact host replay guard for the CX321 plant-sign qualification lifecycle.

The guard is deliberately independent of the command path.  It accepts the
non-actionable ``PSQ,1`` evidence records, recomputes the integer 1,500-count
decision, and defines the exact response tuple that a later firmware ACK and
natural-controller handoff must echo.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import json
import re
from typing import Any, Iterable, Mapping

from .time_domains import (
    RP2040_TIMER0_MICROS_WRAP_TICKS,
    forward_progress,
)


TOOL_ID = "cx321_plant_sign_evidence_guard_v1"
PLANT_SIGN_QUALIFICATION_CONTRACT = "plant_sign_qualification_v1"
PLANT_SIGN_QUALIFICATION_V1_FIELDS = (
    "record_type", "schema_version", "qualification_record_sequence", "event",
    "event_timestamp_ticks", "run_identity", "build_identity", "profile_identity",
    "capture_session", "policy_sha256", "plant_sign_gate_sha256",
    "identification_estimator_sha256", "identification_estimator_config_sha256",
    "natural_frequency_estimator_sha256", "setup_application_sequence",
    "setup_application_timestamp_ticks", "setup_applied_code", "setup_dac_epoch",
    "state_before", "state_after", "total_count", "signed_error_counts",
    "open_ticks", "close_ticks", "source_first_sequence", "source_last_sequence",
    "accepted_intervals", "dac_epoch", "tight_state", "pre_error_counts",
    "current_code", "request_sequence", "acceptance_sequence",
    "application_sequence", "requested_delta_codes", "requested_code",
    "accepted_code", "applied_code", "application_timestamp_ticks",
    "pre_total_count", "post_total_count", "response_counts",
    "response_source_last_sequence", "sign_pass", "magnitude_pass",
    "exact_evidence_pass", "tight_reentry_pass", "passed",
    "acknowledged_response_record_sequence", "host_replay_exact",
    "replay_attestation_sha256", "global_correction_count",
    "global_cumulative_movement_codes", "global_last_application_timestamp_ticks",
    "natural_chatter_origin_code", "natural_cumulative_movement_codes",
    "natural_direction_count", "attested", "reason", "actionable",
)

EVENTS = ("pre1", "pre2", "request", "application", "response", "response_ack", "handoff")
WINDOW_FIELDS = {
    "total_count", "signed_error_counts", "open_ticks", "close_ticks",
    "source_first_sequence", "source_last_sequence", "accepted_intervals",
    "dac_epoch", "tight_state",
}
REQUEST_FIELDS = {
    "pre_error_counts", "current_code", "request_sequence",
    "requested_delta_codes", "requested_code",
}
APPLICATION_FIELDS = {
    "request_sequence", "acceptance_sequence", "application_sequence",
    "requested_delta_codes", "requested_code", "accepted_code", "applied_code",
    "application_timestamp_ticks", "dac_epoch",
}
RESPONSE_FIELDS = APPLICATION_FIELDS | WINDOW_FIELDS | {
    "pre_total_count", "post_total_count", "response_counts",
    "response_source_last_sequence", "sign_pass", "magnitude_pass",
    "exact_evidence_pass", "tight_reentry_pass", "passed",
}
ACK_FIELDS = APPLICATION_FIELDS | {
    "response_counts", "response_source_last_sequence",
    "acknowledged_response_record_sequence", "host_replay_exact",
    "replay_attestation_sha256",
}
HANDOFF_FIELDS = ACK_FIELDS | {
    "global_correction_count", "global_cumulative_movement_codes",
    "global_last_application_timestamp_ticks", "natural_chatter_origin_code",
    "natural_cumulative_movement_codes", "natural_direction_count", "attested",
}
EVENT_FIELDS = {
    "pre1": WINDOW_FIELDS,
    "pre2": WINDOW_FIELDS,
    "request": REQUEST_FIELDS,
    "application": APPLICATION_FIELDS,
    "response": RESPONSE_FIELDS,
    "response_ack": ACK_FIELDS,
    "handoff": HANDOFF_FIELDS,
}
COMMON_FIELDS = {
    "record_type", "schema_version", "qualification_record_sequence", "event",
    "event_timestamp_ticks", "run_identity", "build_identity", "profile_identity",
    "capture_session", "policy_sha256", "plant_sign_gate_sha256",
    "identification_estimator_sha256", "identification_estimator_config_sha256",
    "natural_frequency_estimator_sha256", "setup_application_sequence",
    "setup_application_timestamp_ticks", "setup_applied_code", "setup_dac_epoch",
    "state_before", "state_after", "reason", "actionable",
}
_DIGEST = re.compile(r"[0-9a-f]{64}")


class PlantSignEvidenceError(ValueError):
    """A PSQ record or cross-record invariant was not exact."""


@dataclass(frozen=True)
class PlantSignReplayContext:
    run_identity: str
    build_identity: str
    profile_identity: str
    policy_sha256: str
    plant_sign_gate_sha256: str
    identification_estimator_sha256: str
    identification_estimator_config_sha256: str
    natural_frequency_estimator_sha256: str
    capture_session: int
    timer_hz: int = 16_000_000
    nominal_frequency_hz: int = 10_000_000
    setup_code: int = 0xA83C


def parse_psq_line(line: str) -> dict[str, str]:
    """Parse one canonical comma-separated PSQ line without CSV coercion."""

    values = line.rstrip("\r\n").split(",")
    if len(values) != len(PLANT_SIGN_QUALIFICATION_V1_FIELDS):
        raise PlantSignEvidenceError(
            f"PSQ field count {len(values)} != {len(PLANT_SIGN_QUALIFICATION_V1_FIELDS)}"
        )
    if any(value != value.strip() for value in values):
        raise PlantSignEvidenceError("PSQ values must not contain surrounding whitespace")
    return dict(zip(PLANT_SIGN_QUALIFICATION_V1_FIELDS, values, strict=True))


def _integer(row: Mapping[str, str], field: str, *, minimum: int | None = None) -> int:
    value = row[field]
    if not re.fullmatch(r"-?(0|[1-9][0-9]*)", value) or value == "-0":
        raise PlantSignEvidenceError(f"{field} is not canonical integer text")
    result = int(value)
    if minimum is not None and result < minimum:
        raise PlantSignEvidenceError(f"{field} must be >= {minimum}")
    return result


def _boolean(row: Mapping[str, str], field: str) -> bool:
    value = row[field]
    if value not in {"true", "false"}:
        raise PlantSignEvidenceError(f"{field} is not canonical Boolean text")
    return value == "true"


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise PlantSignEvidenceError(reason)


def _canonical_rows(records: Iterable[Mapping[str, str] | str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for record in records:
        row = parse_psq_line(record) if isinstance(record, str) else dict(record)
        _require(tuple(row) == PLANT_SIGN_QUALIFICATION_V1_FIELDS, "PSQ fields/order differ")
        rows.append(row)
    return rows


def _attestation_payload(
    rows: list[dict[str, str]], context: PlantSignReplayContext
) -> dict[str, Any]:
    pre2, request, application, response = rows[1], rows[2], rows[3], rows[4]
    return {
        "schema_version": 1,
        "tool": TOOL_ID,
        "run_identity": context.run_identity,
        "build_identity": context.build_identity,
        "profile_identity": context.profile_identity,
        "capture_session": context.capture_session,
        "policy_sha256": context.policy_sha256,
        "plant_sign_gate_sha256": context.plant_sign_gate_sha256,
        "identification_estimator_sha256": context.identification_estimator_sha256,
        "identification_estimator_config_sha256": context.identification_estimator_config_sha256,
        "natural_frequency_estimator_sha256": context.natural_frequency_estimator_sha256,
        "pre_total_count": int(pre2["total_count"]),
        "pre_error_counts": int(request["pre_error_counts"]),
        "request_sequence": int(application["request_sequence"]),
        "acceptance_sequence": int(application["acceptance_sequence"]),
        "application_sequence": int(application["application_sequence"]),
        "requested_delta_codes": int(application["requested_delta_codes"]),
        "requested_code": int(application["requested_code"]),
        "applied_code": int(application["applied_code"]),
        "application_timestamp_ticks": int(application["application_timestamp_ticks"]),
        "dac_epoch": int(application["dac_epoch"]),
        "post_total_count": int(response["post_total_count"]),
        "response_counts": int(response["response_counts"]),
        "response_source_last_sequence": int(response["response_source_last_sequence"]),
        "response_record_sequence": int(response["qualification_record_sequence"]),
        "response_event_timestamp_ticks": int(response["event_timestamp_ticks"]),
        "passed": response["passed"] == "true",
    }


def replay_plant_sign_evidence(
    records: Iterable[Mapping[str, str] | str],
    context: PlantSignReplayContext,
    *,
    require_ack_handoff: bool = False,
    expected_ack_attestation_sha256: str | None = None,
) -> dict[str, Any]:
    """Replay an exact response prefix or the complete ACK/handoff lifecycle."""

    rows = _canonical_rows(records)
    expected_events = EVENTS if require_ack_handoff else EVENTS[:5]
    _require(len(rows) == len(expected_events), "PSQ lifecycle length differs")
    _require(tuple(row["event"] for row in rows) == expected_events, "PSQ event order differs")

    identity = {
        "run_identity": context.run_identity,
        "build_identity": context.build_identity,
        "profile_identity": context.profile_identity,
        "capture_session": str(context.capture_session),
        "policy_sha256": context.policy_sha256,
        "plant_sign_gate_sha256": context.plant_sign_gate_sha256,
        "identification_estimator_sha256": context.identification_estimator_sha256,
        "identification_estimator_config_sha256": context.identification_estimator_config_sha256,
        "natural_frequency_estimator_sha256": context.natural_frequency_estimator_sha256,
    }
    setup_tuple: tuple[str, ...] | None = None
    previous_timestamp = -1
    all_fields = set(PLANT_SIGN_QUALIFICATION_V1_FIELDS)
    for ordinal, row in enumerate(rows, 1):
        _require(row["record_type"] == "PSQ" and row["schema_version"] == "1", "unsupported PSQ identity")
        _require(_integer(row, "qualification_record_sequence", minimum=1) == ordinal, "PSQ record sequence is not contiguous")
        timestamp = _integer(row, "event_timestamp_ticks", minimum=0)
        _require(timestamp >= previous_timestamp, "PSQ event time moved backward")
        previous_timestamp = timestamp
        _require(all(row[field] == value for field, value in identity.items()), "PSQ identity tuple differs")
        for field in identity:
            if field.endswith("sha256"):
                _require(_DIGEST.fullmatch(row[field]) is not None, f"{field} is not SHA-256")
        current_setup = tuple(row[field] for field in (
            "setup_application_sequence", "setup_application_timestamp_ticks",
            "setup_applied_code", "setup_dac_epoch",
        ))
        setup_tuple = current_setup if setup_tuple is None else setup_tuple
        _require(current_setup == setup_tuple, "setup application tuple changed")
        _integer(row, "setup_application_sequence", minimum=1)
        _integer(row, "setup_application_timestamp_ticks", minimum=0)
        _require(_integer(row, "setup_applied_code") == context.setup_code, "setup code differs")
        _integer(row, "setup_dac_epoch", minimum=1)
        _require(row["state_before"] and row["state_after"] and row["reason"], "PSQ state/reason missing")
        _require(not _boolean(row, "actionable"), "PSQ evidence must never be actionable")
        allowed = COMMON_FIELDS | EVENT_FIELDS[row["event"]]
        _require(all(row[field] == "" for field in all_fields - allowed), f"{row['event']} has event-inapplicable fields")
        _require(all(row[field] != "" for field in EVENT_FIELDS[row["event"]]), f"{row['event']} lacks event fields")

    pre1, pre2, request, application, response = rows[:5]
    for row, expected_before, expected_after, expected_reason in (
        (
            pre1,
            "FREQUENCY_ACQUIRE",
            "FREQUENCY_ACQUIRE",
            "first_pre_identification_window_accepted",
        ),
        (
            pre2,
            "FREQUENCY_ACQUIRE",
            "PLANT_SIGN_QUALIFY",
            "identification_request_ready",
        ),
        (
            request,
            "PLANT_SIGN_QUALIFY",
            "PLANT_SIGN_QUALIFY",
            "identification_request_created",
        ),
        (
            application,
            "PLANT_SIGN_QUALIFY",
            "PLANT_SIGN_QUALIFY",
            "identification_applied_response_pending",
        ),
    ):
        _require(
            row["state_before"] == expected_before
            and row["state_after"] == expected_after
            and row["reason"] == expected_reason,
            f"{row['event']} state/reason differs",
        )
    nominal_total = context.nominal_frequency_hz * 1500
    setup_tick = _integer(pre1, "setup_application_timestamp_ticks")
    setup_epoch = _integer(pre1, "setup_dac_epoch")
    for window in (pre1, pre2, response):
        _require(_integer(window, "accepted_intervals") == 1500, "PSQ window is not exactly 1500 intervals")
        first = _integer(window, "source_first_sequence", minimum=1)
        last = _integer(window, "source_last_sequence", minimum=first)
        # Sequence identities name the opening and closing D14 boundaries.
        # Exactly 1,500 adjacent intervals therefore span 1,501 boundaries.
        _require(last - first == 1500, "PSQ support sequence is not exactly 1500 intervals")
        opened = _integer(window, "open_ticks", minimum=0)
        closed = _integer(window, "close_ticks", minimum=opened + 1)
        _require(_integer(window, "event_timestamp_ticks") >= closed, "PSQ window emitted before its close")
        total = _integer(window, "total_count", minimum=1)
        _require(_integer(window, "signed_error_counts") == total - nominal_total, "PSQ signed error is not exact-count arithmetic")
    _require(_integer(pre1, "dac_epoch") == setup_epoch == _integer(pre2, "dac_epoch"), "pre windows do not share setup epoch")
    _require(_integer(pre1, "open_ticks") >= setup_tick + 900 * context.timer_hz, "pre1 opens before setup exclusion deadline")
    _require(_integer(pre1, "close_ticks") >= setup_tick + 2400 * context.timer_hz, "pre1 closes before lower bound")
    _require(_integer(pre2, "close_ticks") >= setup_tick + 3900 * context.timer_hz, "pre2 closes before lower bound")
    _require(_integer(pre2, "source_first_sequence") == _integer(pre1, "source_last_sequence"), "pre windows are not contiguous")
    _require(_integer(pre2, "open_ticks") == _integer(pre1, "close_ticks"), "pre windows do not share their boundary")
    pre_total = _integer(pre2, "total_count")
    pre_error = _integer(pre2, "signed_error_counts")
    _require(_integer(pre1, "total_count") == pre_total, "pre totals are not exactly equal")
    _require(1 <= abs(pre_error) <= 5, "pre error is outside the exact entry band")
    _require(pre2["tight_state"] == "TIGHT_INSIDE", "pre2 decision state is not TIGHT_INSIDE")

    _require(_integer(request, "event_timestamp_ticks") == _integer(pre2, "close_ticks"), "request is not at the pre2 close")
    _require(_integer(request, "pre_error_counts") == pre_error, "request pre-error differs")
    _require(_integer(request, "current_code") == context.setup_code, "request does not start at setup code")
    delta = -21 if pre_error > 0 else 21
    _require(_integer(request, "requested_delta_codes") == delta, "identification delta formula differs")
    _require(_integer(request, "requested_code") == context.setup_code + delta, "identification requested code differs")

    immutable_application_fields = (
        "request_sequence", "acceptance_sequence", "application_sequence",
        "requested_delta_codes", "requested_code", "accepted_code", "applied_code",
        "application_timestamp_ticks", "dac_epoch",
    )
    _require(_integer(application, "request_sequence") == _integer(request, "request_sequence"), "application request sequence differs")
    _require(_integer(application, "requested_delta_codes") == delta, "application delta differs")
    requested_code = context.setup_code + delta
    _require(all(_integer(application, field) == requested_code for field in ("requested_code", "accepted_code", "applied_code")), "application code tuple differs")
    application_tick = _integer(application, "application_timestamp_ticks")
    _require(application_tick >= _integer(request, "event_timestamp_ticks"), "application precedes request")
    _require(_integer(application, "event_timestamp_ticks") == application_tick, "application event tick differs")
    application_epoch = _integer(application, "dac_epoch")
    _require(application_epoch == setup_epoch + 1, "identification DAC epoch differs")

    _require(all(response[field] == application[field] for field in immutable_application_fields), "response application tuple differs")
    _require(_integer(response, "dac_epoch") == application_epoch, "response DAC epoch differs")
    _require(_integer(response, "open_ticks") >= application_tick + 900 * context.timer_hz, "response opens before exclusion deadline")
    _require(_integer(response, "close_ticks") >= application_tick + 2400 * context.timer_hz, "response closes before lower bound")
    _require(_integer(response, "pre_total_count") == pre_total, "response pre total differs")
    post_total = _integer(response, "post_total_count")
    _require(post_total == _integer(response, "total_count"), "response post total differs from window")
    response_counts = post_total - pre_total
    _require(_integer(response, "response_counts") == response_counts, "response count subtraction differs")
    _require(_integer(response, "response_source_last_sequence") == _integer(response, "source_last_sequence"), "response source identity differs")
    sign_pass = response_counts * delta > 0
    magnitude_pass = 3 <= abs(response_counts) <= 14
    exact_evidence_pass = True
    tight_pass = response["tight_state"] == "TIGHT_INSIDE"
    derived_pass = sign_pass and magnitude_pass and exact_evidence_pass and tight_pass
    for field, expected in (
        ("sign_pass", sign_pass), ("magnitude_pass", magnitude_pass),
        ("exact_evidence_pass", exact_evidence_pass),
        ("tight_reentry_pass", tight_pass), ("passed", derived_pass),
    ):
        _require(_boolean(response, field) == expected, f"response {field} differs from exact replay")
    _require(
        response["state_before"] == "PLANT_SIGN_QUALIFY"
        and response["state_after"]
        == (
            "PLANT_SIGN_RESPONSE_ACK_PENDING"
            if derived_pass
            else "FAIL_STATIC"
        )
        and response["reason"]
        == (
            "identification_response_exact_ack_pending"
            if derived_pass
            else "identification_response_failed"
        ),
        "response state/reason differs",
    )

    payload = _attestation_payload(rows, context)
    attestation_sha256 = sha256(json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()
    result = {**payload, "exact_replay": True, "attestation_sha256": attestation_sha256}
    if not require_ack_handoff:
        return result
    _require(derived_pass, "a nonpassing response cannot be acknowledged into handoff")

    ack, handoff = rows[5], rows[6]
    acknowledgement_attestation_sha256 = (
        expected_ack_attestation_sha256 or attestation_sha256
    )
    _require(
        _DIGEST.fullmatch(acknowledgement_attestation_sha256) is not None,
        "expected ACK attestation is not a SHA-256 identity",
    )
    _require(
        ack["state_before"] == "PLANT_SIGN_RESPONSE_ACK_PENDING"
        and ack["state_after"] == "PHASE_QUALIFY"
        and ack["reason"] == "identification_response_acknowledged",
        "response_ack state/reason differs",
    )
    _require(
        handoff["state_before"] == "PHASE_QUALIFY"
        and handoff["state_after"] == "PHASE_QUALIFY"
        and handoff["reason"]
        == "plant_sign_first_natural_consumer_handoff_exact",
        "handoff state/reason differs",
    )
    response_sequence = _integer(response, "qualification_record_sequence")
    for row in (ack, handoff):
        _require(all(row[field] == application[field] for field in immutable_application_fields), f"{row['event']} application tuple differs")
        _require(_integer(row, "response_counts") == response_counts, f"{row['event']} response count differs")
        _require(_integer(row, "response_source_last_sequence") == _integer(response, "response_source_last_sequence"), f"{row['event']} response source differs")
        _require(_integer(row, "acknowledged_response_record_sequence") == response_sequence, f"{row['event']} response record reference differs")
        _require(_boolean(row, "host_replay_exact"), f"{row['event']} lacks exact host replay")
        _require(
            row["replay_attestation_sha256"]
            == acknowledgement_attestation_sha256,
            f"{row['event']} attestation hash differs",
        )
    ack_delay = _integer(ack, "event_timestamp_ticks") - _integer(response, "event_timestamp_ticks")
    _require(0 <= ack_delay <= 30 * context.timer_hz, "response ACK missed the exact 30-second deadline")
    _require(_integer(handoff, "event_timestamp_ticks") >= _integer(ack, "event_timestamp_ticks"), "handoff precedes ACK")
    _require(handoff["state_after"] == "PHASE_QUALIFY", "handoff does not enter PHASE_QUALIFY")
    _require(_integer(handoff, "global_correction_count") == 1, "handoff global correction count differs")
    _require(_integer(handoff, "global_cumulative_movement_codes") == 21, "handoff global movement differs")
    _require(_integer(handoff, "global_last_application_timestamp_ticks") == application_tick, "handoff cadence origin differs")
    _require(_integer(handoff, "natural_chatter_origin_code") == requested_code, "handoff chatter origin differs")
    _require(_integer(handoff, "natural_cumulative_movement_codes") == 0, "identification entered natural movement history")
    _require(_integer(handoff, "natural_direction_count") == 0, "identification entered natural direction history")
    _require(_boolean(handoff, "attested"), "handoff is not attested")
    result.update({
        "ack_exact": True,
        "handoff_exact": True,
        "ack_delay_ticks": ack_delay,
        "ack_attestation_sha256": acknowledgement_attestation_sha256,
    })
    return result


def replay_plant_sign_leading_prefix(
    records: Iterable[Mapping[str, str] | str],
    context: PlantSignReplayContext,
    *,
    expected_ack_attestation_sha256: str | None = None,
) -> dict[str, Any]:
    """Strictly replay a progressing CX321 lifecycle prefix of 1–6 rows."""

    rows = _canonical_rows(records)
    _require(1 <= len(rows) <= 6, "PSQ leading prefix length differs")
    _require(
        tuple(row["event"] for row in rows) == EVENTS[: len(rows)],
        "PSQ leading prefix event order differs",
    )
    identity = {
        "run_identity": context.run_identity,
        "build_identity": context.build_identity,
        "profile_identity": context.profile_identity,
        "capture_session": str(context.capture_session),
        "policy_sha256": context.policy_sha256,
        "plant_sign_gate_sha256": context.plant_sign_gate_sha256,
        "identification_estimator_sha256": context.identification_estimator_sha256,
        "identification_estimator_config_sha256": context.identification_estimator_config_sha256,
        "natural_frequency_estimator_sha256": context.natural_frequency_estimator_sha256,
    }
    all_fields = set(PLANT_SIGN_QUALIFICATION_V1_FIELDS)
    setup_tuple: tuple[str, ...] | None = None
    previous_timestamp = -1
    for ordinal, row in enumerate(rows, 1):
        _require(
            row["record_type"] == "PSQ" and row["schema_version"] == "1",
            "unsupported PSQ identity",
        )
        _require(
            _integer(row, "qualification_record_sequence", minimum=1)
            == ordinal,
            "PSQ record sequence is not contiguous",
        )
        timestamp = _integer(row, "event_timestamp_ticks", minimum=0)
        _require(timestamp >= previous_timestamp, "PSQ event time moved backward")
        previous_timestamp = timestamp
        _require(
            all(row[field] == value for field, value in identity.items()),
            "PSQ identity tuple differs",
        )
        for field in identity:
            if field.endswith("sha256"):
                _require(
                    _DIGEST.fullmatch(row[field]) is not None,
                    f"{field} is not SHA-256",
                )
        current_setup = tuple(
            row[field]
            for field in (
                "setup_application_sequence",
                "setup_application_timestamp_ticks",
                "setup_applied_code",
                "setup_dac_epoch",
            )
        )
        setup_tuple = current_setup if setup_tuple is None else setup_tuple
        _require(current_setup == setup_tuple, "setup application tuple changed")
        _integer(row, "setup_application_sequence", minimum=1)
        _integer(row, "setup_application_timestamp_ticks", minimum=0)
        _require(
            _integer(row, "setup_applied_code") == context.setup_code,
            "setup code differs",
        )
        _integer(row, "setup_dac_epoch", minimum=1)
        _require(
            row["state_before"] and row["state_after"] and row["reason"],
            "PSQ state/reason missing",
        )
        _require(
            not _boolean(row, "actionable"),
            "PSQ evidence must never be actionable",
        )
        allowed = COMMON_FIELDS | EVENT_FIELDS[row["event"]]
        _require(
            all(row[field] == "" for field in all_fields - allowed),
            f"{row['event']} has event-inapplicable fields",
        )
        _require(
            all(row[field] != "" for field in EVENT_FIELDS[row["event"]]),
            f"{row['event']} lacks event fields",
        )

    nominal_total = context.nominal_frequency_hz * 1500

    def validate_window(row: Mapping[str, str]) -> None:
        _require(
            _integer(row, "accepted_intervals") == 1500,
            "PSQ window is not exactly 1500 intervals",
        )
        first = _integer(row, "source_first_sequence", minimum=1)
        last = _integer(row, "source_last_sequence", minimum=first)
        _require(
            last - first == 1500,
            "PSQ support sequence is not exactly 1500 intervals",
        )
        opened = _integer(row, "open_ticks", minimum=0)
        closed = _integer(row, "close_ticks", minimum=opened + 1)
        _require(
            _integer(row, "event_timestamp_ticks") >= closed,
            "PSQ window emitted before its close",
        )
        total = _integer(row, "total_count", minimum=1)
        _require(
            _integer(row, "signed_error_counts") == total - nominal_total,
            "PSQ signed error is not exact-count arithmetic",
        )

    pre1 = rows[0]
    validate_window(pre1)
    setup_tick = _integer(pre1, "setup_application_timestamp_ticks")
    setup_epoch = _integer(pre1, "setup_dac_epoch")
    _require(_integer(pre1, "dac_epoch") == setup_epoch, "pre1 DAC epoch differs")
    _require(
        _integer(pre1, "open_ticks") >= setup_tick + 900 * context.timer_hz,
        "pre1 opens before setup exclusion deadline",
    )
    _require(
        _integer(pre1, "close_ticks") >= setup_tick + 2400 * context.timer_hz,
        "pre1 closes before lower bound",
    )
    _require(
        pre1["state_before"] == "FREQUENCY_ACQUIRE"
        and pre1["state_after"] == "FREQUENCY_ACQUIRE"
        and pre1["reason"] == "first_pre_identification_window_accepted"
        and 1 <= abs(_integer(pre1, "signed_error_counts")) <= 5,
        "pre1 progressing state or entry predicate differs",
    )
    if len(rows) == 1:
        return {
            "exact_replay": True,
            "record_count": 1,
            "events": ["pre1"],
            "right_censored_progressing_prefix": True,
        }

    pre2 = rows[1]
    validate_window(pre2)
    _require(_integer(pre2, "dac_epoch") == setup_epoch, "pre2 DAC epoch differs")
    _require(
        _integer(pre2, "source_first_sequence")
        == _integer(pre1, "source_last_sequence"),
        "pre windows are not contiguous",
    )
    _require(
        _integer(pre2, "open_ticks") == _integer(pre1, "close_ticks"),
        "pre windows do not share their boundary",
    )
    _require(
        _integer(pre2, "close_ticks") >= setup_tick + 3900 * context.timer_hz,
        "pre2 closes before lower bound",
    )
    pre_total = _integer(pre2, "total_count")
    pre_error = _integer(pre2, "signed_error_counts")
    _require(
        pre2["state_before"] == "FREQUENCY_ACQUIRE"
        and pre2["state_after"] == "PLANT_SIGN_QUALIFY"
        and pre2["reason"] == "identification_request_ready",
        "pre2 progressing state/reason differs",
    )
    _require(
        _integer(pre1, "total_count") == pre_total,
        "pre totals are not exactly equal",
    )
    _require(1 <= abs(pre_error) <= 5, "pre error is outside the exact entry band")
    _require(
        pre2["tight_state"] == "TIGHT_INSIDE",
        "pre2 decision state is not TIGHT_INSIDE",
    )
    if len(rows) == 2:
        return {
            "exact_replay": True,
            "record_count": 2,
            "events": list(EVENTS[:2]),
            "right_censored_progressing_prefix": True,
        }

    request = rows[2]
    _require(
        request["state_before"] == "PLANT_SIGN_QUALIFY"
        and request["state_after"] == "PLANT_SIGN_QUALIFY"
        and request["reason"] == "identification_request_created",
        "request state/reason differs",
    )
    _require(
        _integer(request, "event_timestamp_ticks")
        == _integer(pre2, "close_ticks"),
        "request is not at the pre2 close",
    )
    _require(
        _integer(request, "pre_error_counts") == pre_error,
        "request pre-error differs",
    )
    _require(
        _integer(request, "current_code") == context.setup_code,
        "request does not start at setup code",
    )
    request_sequence = _integer(request, "request_sequence", minimum=1)
    delta = -21 if pre_error > 0 else 21
    requested_code = context.setup_code + delta
    _require(
        _integer(request, "requested_delta_codes") == delta,
        "identification delta formula differs",
    )
    _require(
        _integer(request, "requested_code") == requested_code,
        "identification requested code differs",
    )
    if len(rows) == 3:
        return {
            "exact_replay": True,
            "record_count": 3,
            "events": list(EVENTS[:3]),
            "right_censored_progressing_prefix": True,
        }

    application = rows[3]
    _require(
        application["state_before"] == "PLANT_SIGN_QUALIFY"
        and application["state_after"] == "PLANT_SIGN_QUALIFY"
        and application["reason"] == "identification_applied_response_pending",
        "application state/reason differs",
    )
    _require(
        _integer(application, "request_sequence") == request_sequence,
        "application request sequence differs",
    )
    _integer(application, "acceptance_sequence", minimum=1)
    _integer(application, "application_sequence", minimum=1)
    _require(
        _integer(application, "requested_delta_codes") == delta,
        "application delta differs",
    )
    _require(
        all(
            _integer(application, field) == requested_code
            for field in (
                "requested_code",
                "accepted_code",
                "applied_code",
            )
        ),
        "application code tuple differs",
    )
    application_tick = _integer(application, "application_timestamp_ticks")
    _require(
        application_tick >= _integer(request, "event_timestamp_ticks"),
        "application precedes request",
    )
    _require(
        _integer(application, "event_timestamp_ticks") == application_tick,
        "application event tick differs",
    )
    application_epoch = _integer(application, "dac_epoch")
    _require(
        application_epoch == setup_epoch + 1,
        "identification DAC epoch differs",
    )
    if len(rows) == 4:
        return {
            "exact_replay": True,
            "record_count": 4,
            "events": list(EVENTS[:4]),
            "right_censored_progressing_prefix": True,
        }

    response_result = replay_plant_sign_evidence(rows[:5], context)
    _require(
        response_result["passed"] is True,
        "nonpassing response requires the plant-sign scientific terminal",
    )
    if len(rows) == 5:
        return {
            **response_result,
            "record_count": 5,
            "events": list(EVENTS[:5]),
            "right_censored_progressing_prefix": True,
        }

    ack = rows[5]
    response = rows[4]
    immutable_application_fields = (
        "request_sequence",
        "acceptance_sequence",
        "application_sequence",
        "requested_delta_codes",
        "requested_code",
        "accepted_code",
        "applied_code",
        "application_timestamp_ticks",
        "dac_epoch",
    )
    _require(
        ack["state_before"] == "PLANT_SIGN_RESPONSE_ACK_PENDING"
        and ack["state_after"] == "PHASE_QUALIFY"
        and ack["reason"] == "identification_response_acknowledged",
        "response_ack state/reason differs",
    )
    _require(
        all(ack[field] == application[field] for field in immutable_application_fields),
        "response_ack application tuple differs",
    )
    _require(
        _integer(ack, "response_counts")
        == _integer(response, "response_counts"),
        "response_ack response count differs",
    )
    _require(
        _integer(ack, "response_source_last_sequence")
        == _integer(response, "response_source_last_sequence"),
        "response_ack response source differs",
    )
    _require(
        _integer(ack, "acknowledged_response_record_sequence")
        == _integer(response, "qualification_record_sequence"),
        "response_ack response record reference differs",
    )
    _require(_boolean(ack, "host_replay_exact"), "response_ack lacks exact host replay")
    acknowledgement_attestation_sha256 = (
        expected_ack_attestation_sha256
        or str(response_result["attestation_sha256"])
    )
    _require(
        _DIGEST.fullmatch(acknowledgement_attestation_sha256) is not None,
        "expected ACK attestation is not a SHA-256 identity",
    )
    _require(
        ack["replay_attestation_sha256"]
        == acknowledgement_attestation_sha256,
        "response_ack attestation hash differs",
    )
    ack_delay = _integer(ack, "event_timestamp_ticks") - _integer(
        response, "event_timestamp_ticks"
    )
    _require(
        0 <= ack_delay <= 30 * context.timer_hz,
        "response ACK missed the exact 30-second deadline",
    )
    return {
        **response_result,
        "ack_exact": True,
        "ack_attestation_sha256": acknowledgement_attestation_sha256,
        "ack_delay_ticks": ack_delay,
        "record_count": 6,
        "events": list(EVENTS[:6]),
        "right_censored_progressing_prefix": True,
    }


def replay_plant_sign_windows_against_snapshots(
    records: Iterable[Mapping[str, str] | str],
    snapshot_records: Iterable[Mapping[str, str]],
    context: PlantSignReplayContext,
) -> dict[str, Any]:
    """Bind each retained PSQ window to canonical raw SNP evidence."""

    rows = _canonical_rows(records)
    windows = [row for row in rows if row["event"] in {"pre1", "pre2", "response"}]
    _require(bool(windows), "PSQ prefix has no window to bind to snapshots")
    snapshots = [dict(row) for row in snapshot_records]
    expected_backend = "pio_wait_cumulative_snapshot_dma_v1"
    modulus = RP2040_TIMER0_MICROS_WRAP_TICKS
    proofs: list[dict[str, Any]] = []
    for window in windows:
        first = _integer(window, "source_first_sequence", minimum=1)
        last = _integer(window, "source_last_sequence", minimum=first)
        support = [
            row
            for row in snapshots
            if row.get("session") == str(context.capture_session)
            and row.get("snapshot_sequence", "").isdigit()
            and first <= int(row["snapshot_sequence"]) <= last
        ]
        support.sort(key=lambda row: int(row["snapshot_sequence"]))
        expected_sequences = list(range(first, last + 1))
        observed_sequences = [int(row["snapshot_sequence"]) for row in support]
        _require(
            len(support) == 1501 and observed_sequences == expected_sequences,
            f"{window['event']} SNP support is not exactly 1,501 contiguous rows",
        )
        reference_sequences: list[int] = []
        raw_ticks: list[int] = []
        downcounters: list[int] = []
        for row in support:
            _require(
                row.get("record_type") == "SNP"
                and row.get("schema_version") == "1"
                and row.get("status") == "0"
                and row.get("backend") == expected_backend,
                f"{window['event']} SNP identity/status/backend differs",
            )
            try:
                reference_sequence = int(row["reference_sequence"])
                raw_tick = int(row["reference_timestamp_ticks"])
                downcounter = int(row["cumulative_down_counter"])
            except (KeyError, ValueError) as exc:
                raise PlantSignEvidenceError(
                    f"{window['event']} SNP numeric identity is not canonical"
                ) from exc
            _require(
                0 <= reference_sequence <= 0xFFFFFFFF
                and 0 <= raw_tick < modulus
                and 0 <= downcounter <= 0xFFFFFFFF,
                f"{window['event']} SNP value is outside its raw domain",
            )
            reference_sequences.append(reference_sequence)
            raw_ticks.append(raw_tick)
            downcounters.append(downcounter)
        _require(
            all(
                current == previous + 1
                for previous, current in zip(
                    reference_sequences, reference_sequences[1:]
                )
            ),
            f"{window['event']} SNP reference sequence is not contiguous",
        )
        elapsed_ticks = 0
        total_count = 0
        wrap_count = 0
        for index in range(1, len(support)):
            progress = forward_progress(
                raw_ticks[index - 1],
                raw_ticks[index],
                domain="rp2040_timer0",
                allow_equal=False,
            )
            _require(
                progress.valid and progress.distance_ticks is not None,
                f"{window['event']} SNP raw TIMER0 progression differs",
            )
            _require(
                8 * context.timer_hz // 10
                <= progress.distance_ticks
                <= 12 * context.timer_hz // 10,
                f"{window['event']} SNP D14 interval is outside 0.8..1.2 s",
            )
            elapsed_ticks += progress.distance_ticks
            wrap_count += progress.rollover_count
            total_count += (
                downcounters[index - 1] - downcounters[index]
            ) & 0xFFFFFFFF
        open_ticks = _integer(window, "open_ticks", minimum=0)
        close_ticks = _integer(window, "close_ticks", minimum=open_ticks + 1)
        if window["event"] in {"pre1", "response"}:
            if window["event"] == "pre1":
                origin_ticks = _integer(
                    window, "setup_application_timestamp_ticks", minimum=0
                )
            else:
                application = next(
                    (row for row in rows if row["event"] == "application"),
                    None,
                )
                _require(
                    application is not None,
                    "response SNP proof lacks its application origin",
                )
                origin_ticks = _integer(
                    application, "application_timestamp_ticks", minimum=0
                )
            exclusion_deadline = origin_ticks + 900 * context.timer_hz
            projected_open = raw_ticks[0]
            if projected_open < exclusion_deadline:
                projected_open += (
                    (
                        exclusion_deadline
                        - projected_open
                        + modulus
                        - 1
                    )
                    // modulus
                ) * modulus
            _require(
                open_ticks == projected_open,
                f"{window['event']} extended opening is not the first raw "
                "TIMER0 projection at/after its exclusion deadline",
            )
        _require(
            open_ticks % modulus == raw_ticks[0]
            and close_ticks % modulus == raw_ticks[-1],
            f"{window['event']} extended endpoints do not match raw SNP TIMER0",
        )
        _require(
            close_ticks - open_ticks == elapsed_ticks,
            f"{window['event']} extended span differs from raw SNP deltas",
        )
        _require(
            total_count == _integer(window, "total_count"),
            f"{window['event']} total differs from raw SNP downcounters",
        )
        proofs.append(
            {
                "event": window["event"],
                "source_first_sequence": first,
                "source_last_sequence": last,
                "snapshot_count": len(support),
                "reference_first_sequence": reference_sequences[0],
                "reference_last_sequence": reference_sequences[-1],
                "elapsed_ticks": elapsed_ticks,
                "total_count": total_count,
                "raw_timer_wrap_count": wrap_count,
                "exact": True,
            }
        )
    payload = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "capture_session": context.capture_session,
        "snapshot_backend": expected_backend,
        "window_proofs": proofs,
        "exact": True,
    }
    return {
        **payload,
        "proof_sha256": sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest(),
    }


def complete_plant_sign_evidence_chain(
    *,
    psq_replay: Mapping[str, Any],
    snapshot_window_proof: Mapping[str, Any],
    act_response_join: Mapping[str, Any],
) -> dict[str, Any]:
    """Hash the complete evidence chain released by the phase-4 ACK.

    Firmware treats the digest as an opaque host attestation and echoes it in
    ``response_ack`` and ``handoff``.  This payload makes that digest bind the
    exact PSQ arithmetic, retained raw-SNP reconstruction, and matching ACT
    application tuple instead of attesting PSQ arithmetic alone.
    """

    psq_sha256 = psq_replay.get("attestation_sha256")
    snapshot_sha256 = snapshot_window_proof.get("proof_sha256")
    _require(
        isinstance(psq_sha256, str)
        and _DIGEST.fullmatch(psq_sha256) is not None,
        "PSQ replay attestation is not a SHA-256 identity",
    )
    _require(
        snapshot_window_proof.get("exact") is True
        and isinstance(snapshot_sha256, str)
        and _DIGEST.fullmatch(snapshot_sha256) is not None,
        "raw-SNP window proof is not exact and content-addressed",
    )
    snapshot_payload = {
        key: value
        for key, value in snapshot_window_proof.items()
        if key != "proof_sha256"
    }
    _require(
        sha256(
            json.dumps(
                snapshot_payload,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest()
        == snapshot_sha256,
        "raw-SNP window proof content differs from its SHA-256 identity",
    )
    _require(
        act_response_join.get("exact") is True,
        "PSQ/ACT response join is not exact",
    )
    payload = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "purpose": "cx321_phase4_complete_evidence_chain",
        "psq_replay_attestation_sha256": psq_sha256,
        "snapshot_window_proof_sha256": snapshot_sha256,
        "act_response_join": dict(act_response_join),
    }
    return {
        **payload,
        "attestation_sha256": sha256(
            json.dumps(
                payload,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode()
        ).hexdigest(),
    }


def replay_plant_sign_terminal_prefix(
    records: Iterable[Mapping[str, str] | str],
    context: PlantSignReplayContext,
    *,
    terminal_decision: str,
) -> dict[str, Any]:
    """Replay the two legitimate nonpassing CX321 terminal prefixes.

    Identity, framing, window support, and count arithmetic failures raise and
    therefore remain platform/measurement faults.  Only an exact supported
    entry rejection or an exact nonpassing response is a scientific terminal.
    """

    rows = _canonical_rows(records)
    if terminal_decision == "plant_sign_qualification_failed":
        result = replay_plant_sign_evidence(rows, context)
        response = rows[-1]
        _require(result["passed"] is False, "failed terminal has a passing response")
        _require(
            response["state_after"] == "FAIL_STATIC"
            and response["reason"] == "identification_response_failed",
            "failed response terminal state/reason differs",
        )
        failed_predicates = [
            name
            for name in (
                "sign_pass",
                "magnitude_pass",
                "tight_reentry_pass",
            )
            if not _boolean(response, name)
        ]
        _require(bool(failed_predicates), "failed response lacks a scientific predicate")
        return {
            **result,
            "terminal_decision": terminal_decision,
            "scientific_terminal_exact": True,
            "failed_predicates": failed_predicates,
        }

    _require(
        terminal_decision == "plant_sign_qualification_not_exercised",
        "unsupported CX321 plant-sign terminal decision",
    )
    _require(len(rows) in {1, 2}, "not-exercised prefix must contain pre1 or pre1/pre2")
    _require(
        tuple(row["event"] for row in rows) == EVENTS[: len(rows)],
        "not-exercised prefix event order differs",
    )
    identity = {
        "run_identity": context.run_identity,
        "build_identity": context.build_identity,
        "profile_identity": context.profile_identity,
        "capture_session": str(context.capture_session),
        "policy_sha256": context.policy_sha256,
        "plant_sign_gate_sha256": context.plant_sign_gate_sha256,
        "identification_estimator_sha256": context.identification_estimator_sha256,
        "identification_estimator_config_sha256": context.identification_estimator_config_sha256,
        "natural_frequency_estimator_sha256": context.natural_frequency_estimator_sha256,
    }
    nominal_total = context.nominal_frequency_hz * 1500
    previous_timestamp = -1
    setup_tuple: tuple[str, ...] | None = None
    for ordinal, row in enumerate(rows, 1):
        _require(row["record_type"] == "PSQ" and row["schema_version"] == "1", "unsupported PSQ identity")
        _require(_integer(row, "qualification_record_sequence") == ordinal, "PSQ record sequence is not contiguous")
        timestamp = _integer(row, "event_timestamp_ticks", minimum=0)
        _require(timestamp >= previous_timestamp, "PSQ event time moved backward")
        previous_timestamp = timestamp
        _require(all(row[field] == expected for field, expected in identity.items()), "PSQ identity tuple differs")
        for field in identity:
            if field.endswith("sha256"):
                _require(
                    _DIGEST.fullmatch(row[field]) is not None,
                    f"{field} is not SHA-256",
                )
        current_setup = tuple(row[field] for field in (
            "setup_application_sequence", "setup_application_timestamp_ticks",
            "setup_applied_code", "setup_dac_epoch",
        ))
        setup_tuple = current_setup if setup_tuple is None else setup_tuple
        _require(current_setup == setup_tuple, "setup application tuple changed")
        _integer(row, "setup_application_sequence", minimum=1)
        _integer(row, "setup_application_timestamp_ticks", minimum=0)
        _require(_integer(row, "setup_applied_code") == context.setup_code, "setup code differs")
        _integer(row, "setup_dac_epoch", minimum=1)
        _require(_integer(row, "accepted_intervals") == 1500, "PSQ window is not exactly 1500 intervals")
        first = _integer(row, "source_first_sequence", minimum=1)
        last = _integer(row, "source_last_sequence", minimum=first)
        _require(last - first == 1500, "PSQ support sequence is not exactly 1500 intervals")
        opened = _integer(row, "open_ticks", minimum=0)
        closed = _integer(row, "close_ticks", minimum=opened + 1)
        _require(timestamp >= closed, "PSQ window emitted before its close")
        total = _integer(row, "total_count", minimum=1)
        _require(_integer(row, "signed_error_counts") == total - nominal_total, "PSQ signed error is not exact-count arithmetic")
        _require(_integer(row, "dac_epoch") == _integer(row, "setup_dac_epoch"), "pre window DAC epoch differs")
        allowed = COMMON_FIELDS | EVENT_FIELDS[row["event"]]
        _require(all(row[field] == "" for field in set(PLANT_SIGN_QUALIFICATION_V1_FIELDS) - allowed), f"{row['event']} has event-inapplicable fields")
        _require(
            all(row[field] != "" for field in EVENT_FIELDS[row["event"]]),
            f"{row['event']} lacks event fields",
        )
        _require(not _boolean(row, "actionable"), "PSQ evidence must never be actionable")

    pre1 = rows[0]
    _require(pre1["state_before"] == "FREQUENCY_ACQUIRE", "pre1 state_before differs")
    setup_tick = _integer(pre1, "setup_application_timestamp_ticks")
    _require(_integer(pre1, "open_ticks") >= setup_tick + 900 * context.timer_hz, "pre1 opens before setup exclusion deadline")
    _require(_integer(pre1, "close_ticks") >= setup_tick + 2400 * context.timer_hz, "pre1 closes before lower bound")
    if len(rows) == 1:
        _require(
            not 1 <= abs(_integer(pre1, "signed_error_counts")) <= 5,
            "pre1 not-exercised prefix lacks an entry-band rejection",
        )
        _require(
            pre1["state_after"] == "PLANT_SIGN_NOT_EXERCISED"
            and pre1["reason"]
            == "pre_identification_scientific_entry_band_not_satisfied",
            "pre1 not-exercised terminal state/reason differs",
        )
        scientific_predicates = ["pre1_entry_band_not_satisfied"]
    else:
        pre2 = rows[1]
        _require(pre2["state_before"] == "FREQUENCY_ACQUIRE", "pre2 state_before differs")
        _require(1 <= abs(_integer(pre1, "signed_error_counts")) <= 5, "accepted pre1 error is outside entry band")
        _require(
            pre1["state_after"] == "FREQUENCY_ACQUIRE"
            and pre1["reason"] == "first_pre_identification_window_accepted",
            "pre1 accepted state/reason differs",
        )
        _require(_integer(pre2, "source_first_sequence") == _integer(pre1, "source_last_sequence"), "pre windows are not contiguous")
        _require(_integer(pre2, "open_ticks") == _integer(pre1, "close_ticks"), "pre windows do not share their boundary")
        _require(_integer(pre2, "close_ticks") >= setup_tick + 3900 * context.timer_hz, "pre2 closes before lower bound")
        scientific_predicates = []
        if _integer(pre2, "total_count") != _integer(pre1, "total_count"):
            scientific_predicates.append("pre_totals_not_equal")
        if pre2["tight_state"] != "TIGHT_INSIDE":
            scientific_predicates.append("pre2_not_tight_inside")
        if not 1 <= abs(_integer(pre2, "signed_error_counts")) <= 5:
            scientific_predicates.append("pre2_entry_band_not_satisfied")
        _require(bool(scientific_predicates), "pre2 not-exercised prefix lacks a scientific rejection predicate")
        expected_reason = (
            "pre_identification_scientific_entry_band_not_satisfied"
            if "pre2_entry_band_not_satisfied" in scientific_predicates
            else "second_pre_window_not_equal_and_tight"
        )
        _require(
            pre2["state_after"] == "PLANT_SIGN_NOT_EXERCISED"
            and pre2["reason"] == expected_reason,
            "pre2 not-exercised terminal state/reason differs",
        )
    return {
        "schema_version": 1,
        "tool": TOOL_ID,
        "terminal_decision": terminal_decision,
        "scientific_terminal_exact": True,
        "record_count": len(rows),
        "events": [row["event"] for row in rows],
        "scientific_rejection_predicates": scientific_predicates,
    }
