from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from host.otis_tools.cx317_active_campaign import (
    ActiveCampaignSupervisor,
    load_campaign_spec,
    validate_transaction_row,
)
from host.otis_tools.contracts import ACTIVE_TRANSACTION_V1_FIELDS
from host.otis_tools.serial_commands import CommandFifo


def _row() -> dict[str, str]:
    spec, identities = load_campaign_spec("A")
    return {
        "event": "request_accepted",
        "run_identity": spec.run_identity,
        "build_identity": "b" * 64 + ":" + "c" * 64,
        "profile_identity": spec.profile,
        **identities,
        "actionable": "false",
        "current_applied_code": str(spec.start_code),
        "requested_delta_codes": "-21",
        "requested_code": str(spec.start_code - 21),
        "accepted_code": str(spec.start_code - 21),
        "correction_ordinal": "1",
        "cumulative_after_codes": "21",
        "applied_code": "0",
        "i2c_ok": "false",
        "clamped": "false",
        "ambiguous": "false",
        "estimator_history_reset": "false",
        "application_sequence": "0",
        "correction_count": "0",
        "cumulative_movement_codes": "0",
    }


def test_campaign_spec_freezes_both_envelopes() -> None:
    campaign_a, _ = load_campaign_spec("A")
    campaign_b, _ = load_campaign_spec("B")
    assert (campaign_a.start_code, campaign_a.correction_limit, campaign_a.cumulative_limit) == (
        0xA950,
        16,
        336,
    )
    assert (campaign_b.start_code, campaign_b.correction_limit, campaign_b.cumulative_limit) == (
        0xA800,
        8,
        168,
    )


def test_prewrite_request_capsule_validates_before_release() -> None:
    row = _row()
    spec, identities = load_campaign_spec("A")
    validate_transaction_row(row, spec, identities, row["build_identity"])


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("actionable", "true"),
        ("requested_delta_codes", "-22"),
        ("accepted_code", str(0xA950 - 20)),
        ("cumulative_after_codes", "337"),
        ("active_policy_sha256", "0" * 64),
    ],
)
def test_prewrite_release_fails_closed_on_identity_or_budget_change(
    field: str, value: str
) -> None:
    row = _row()
    row[field] = value
    spec, identities = load_campaign_spec("A")
    with pytest.raises(ValueError):
        validate_transaction_row(row, spec, identities, row["build_identity"])


def test_supervisor_fsyncs_capsule_then_submits_exact_phase_one_ack(
    tmp_path: Path,
) -> None:
    spec, identities = load_campaign_spec("A")
    build_identity = "b" * 64 + ":" + "c" * 64
    values = {field: "" for field in ACTIVE_TRANSACTION_V1_FIELDS}
    values.update(
        {
            "record_type": "ACT",
            "schema_version": "1",
            "transaction_record_sequence": "1",
            "event": "request_accepted",
            "run_identity": spec.run_identity,
            "build_identity": build_identity,
            "profile_identity": spec.profile,
            **identities,
            "session_id": "7",
            "authorization_sequence": "1",
            "nonce": "9",
            "request_sequence": "1",
            "decision_sequence": "4",
            "source_first_sequence": "100",
            "source_last_sequence": "699",
            "decision_timestamp_s": "2400",
            "current_applied_code": str(spec.start_code),
            "requested_delta_codes": "-21",
            "requested_code": str(spec.start_code - 21),
            "correction_ordinal": "1",
            "cumulative_after_codes": "21",
            "pre_error_hz": "0.02",
            "accepted_code": str(spec.start_code - 21),
            "accepted_timestamp_s": "2400",
            "applied_code": "0",
            "application_sequence": "0",
            "application_timestamp_s": "0",
            "i2c_ok": "false",
            "clamped": "false",
            "ambiguous": "false",
            "dac_epoch": "0",
            "estimator_history_reset": "false",
            "correction_count": "0",
            "cumulative_movement_codes": "0",
            "post_error_hz": "0",
            "observed_response_hz": "0",
            "cumulative_response_hz": "0",
            "consecutive_indeterminate": "0",
            "active_state": "ACCEPTED_AWAITING_APPLICATION",
            "response_class": "unavailable",
            "reason": "request_consumed_actionable_cleared",
            "actionable": "false",
            "evidence_state": "request_pending",
        }
    )
    active_csv = tmp_path / "run" / "csv" / "active_transactions_v1.csv"
    active_csv.parent.mkdir(parents=True)
    manual = dict(values)
    manual.update(
        {
            "transaction_record_sequence": "1",
            "event": "manual_start",
            "authorization_sequence": "0",
            "nonce": "0",
            "request_sequence": "0",
            "decision_sequence": "0",
            "source_first_sequence": "0",
            "source_last_sequence": "0",
            "current_applied_code": str(spec.start_code),
            "requested_delta_codes": "0",
            "requested_code": str(spec.start_code),
            "correction_ordinal": "0",
            "cumulative_after_codes": "0",
            "pre_error_hz": "0",
            "accepted_code": str(spec.start_code),
            "applied_code": str(spec.start_code),
            "i2c_ok": "true",
            "active_state": "DISARMED",
            "reason": "manual_start_established",
            "evidence_state": "evidence_clear",
        }
    )
    values["transaction_record_sequence"] = "2"
    with active_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=ACTIVE_TRANSACTION_V1_FIELDS)
        writer.writeheader()
        writer.writerow(manual)
        writer.writerow(values)

    command_fifo = tmp_path / "commands.fifo"
    supervisor = ActiveCampaignSupervisor(
        run_dir=tmp_path / "run",
        command_fifo=command_fifo,
        abort_fifo=tmp_path / "abort.fifo",
        spec=spec,
        identities=identities,
        expected_build_identity=build_identity,
        allow_manual_start=False,
        allow_arm=False,
        duration_s=None,
    )
    with CommandFifo(command_fifo) as reader:
        supervisor._process_transactions()
        assert reader.poll() == ["ACTIVE EVIDENCE 1 1"]
    capsule = tmp_path / "run" / "reports" / "step_001" / "record_000002_request_accepted.json"
    assert capsule.exists()
    assert json.loads(capsule.read_text(encoding="utf-8")) == values
