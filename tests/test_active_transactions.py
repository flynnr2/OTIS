from __future__ import annotations

import csv
from dataclasses import replace
import json
import os
from pathlib import Path
import threading
import time

import pytest

from host.otis_tools.active_transactions import (
    ActiveTransactionSupervisor,
    _await_cx321_plant_sign_response,
    _cx321_response_is_plant_sign_identification,
    _join_cx321_psq_response_to_act,
    validate_transaction_row,
)
from host.otis_tools.no_write_qualification_supervisor import (
    load_no_write_qualification_spec,
)
from host.otis_tools.contracts import ACTIVE_TRANSACTION_V1_FIELDS
from host.otis_tools.serial_commands import CommandFifo


def _row() -> dict[str, str]:
    spec, identities, _ = load_no_write_qualification_spec("A")
    return {
        "event": "request_accepted",
        "run_identity": spec.run_identity,
        "build_identity": "b" * 64 + ":" + "c" * 64,
        "profile_identity": spec.profile,
        **identities,
        "actionable": "false",
        "current_applied_code": str(spec.start_code),
        "requested_delta_codes": "21",
        "requested_code": str(spec.start_code + 21),
        "accepted_code": str(spec.start_code + 21),
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


def test_current_specs_freeze_both_cx319_envelopes() -> None:
    campaign_a, _, _ = load_no_write_qualification_spec("A")
    campaign_b, _, _ = load_no_write_qualification_spec("B")
    assert (campaign_a.start_code, campaign_a.correction_limit, campaign_a.cumulative_limit) == (
        0xA808,
        4,
        84,
    )
    assert (campaign_b.start_code, campaign_b.correction_limit, campaign_b.cumulative_limit) == (
        0xA848,
        4,
        84,
    )


def test_prewrite_request_capsule_validates_before_release() -> None:
    row = _row()
    spec, identities, _ = load_no_write_qualification_spec("A")
    validate_transaction_row(row, spec, identities, row["build_identity"])


def test_cx321_phase4_waits_for_matching_psq_split_record(
    tmp_path: Path,
) -> None:
    row = {
        "correction_ordinal": "1",
        "requested_delta_codes": "-21",
        "cumulative_after_codes": "21",
    }
    assert _cx321_response_is_plant_sign_identification(row) is True
    path = tmp_path / "plant_sign_qualification_v1.csv"
    path.write_text("event,request_sequence\n", encoding="utf-8")

    def append_response() -> None:
        time.sleep(0.05)
        with path.open("a", encoding="utf-8") as handle:
            handle.write("response,7\n")

    writer = threading.Thread(target=append_response)
    writer.start()
    rows, response = _await_cx321_plant_sign_response(
        path, request_sequence=7, timeout_s=0.5
    )
    writer.join()

    assert rows[-1] == response
    assert response == {"event": "response", "request_sequence": "7"}


def test_cx321_first_phase4_never_silently_falls_back_to_natural() -> None:
    with pytest.raises(ValueError, match="frozen plant-sign stimulus"):
        _cx321_response_is_plant_sign_identification(
            {
                "correction_ordinal": "1",
                "requested_delta_codes": "4",
                "cumulative_after_codes": "4",
            }
        )


def _cx321_psq_act_join_rows() -> tuple[dict[str, str], dict[str, str]]:
    psq = {
        "request_sequence": "7",
        "application_sequence": "9",
        "requested_delta_codes": "-21",
        "requested_code": str(0xA827),
        "accepted_code": str(0xA827),
        "applied_code": str(0xA827),
        "dac_epoch": "2",
        "application_timestamp_ticks": str(3902 * 16_000_000 + 17),
    }
    act = {
        "transaction_record_sequence": "44",
        "event": "response",
        "request_sequence": "7",
        "application_sequence": "9",
        "requested_delta_codes": "-21",
        "requested_code": str(0xA827),
        "accepted_code": str(0xA827),
        "applied_code": str(0xA827),
        "dac_epoch": "2",
        "application_timestamp_s": "3902",
    }
    return psq, act


def test_cx321_phase4_ack_joins_psq_to_exact_act_response() -> None:
    psq, act = _cx321_psq_act_join_rows()

    result = _join_cx321_psq_response_to_act(
        psq_response=psq, act_response=act
    )

    assert result["exact"] is True
    assert result["act_transaction_record_sequence"] == 44


@pytest.mark.parametrize(
    "field",
    (
        "request_sequence",
        "application_sequence",
        "requested_delta_codes",
        "requested_code",
        "accepted_code",
        "applied_code",
        "dac_epoch",
    ),
)
def test_cx321_phase4_ack_rejects_each_psq_act_tuple_mismatch(
    field: str,
) -> None:
    psq, act = _cx321_psq_act_join_rows()
    act[field] = str(int(act[field]) + 1)

    with pytest.raises(ValueError, match=field):
        _join_cx321_psq_response_to_act(
            psq_response=psq, act_response=act
        )


def test_cx321_phase4_ack_accepts_legitimate_core0_core1_second_crossing() -> None:
    psq, act = _cx321_psq_act_join_rows()
    psq["application_timestamp_ticks"] = str(3902 * 16_000_000 + 15_999_999)
    act["application_timestamp_s"] = "3903"

    result = _join_cx321_psq_response_to_act(
        psq_response=psq, act_response=act
    )

    assert result["exact"] is True
    assert result["acknowledgement_lag_lower_bound_ticks"] == 1


def test_cx321_phase4_ack_rejects_core0_tick_after_core1_consumption_second() -> None:
    psq, act = _cx321_psq_act_join_rows()
    psq["application_timestamp_ticks"] = str(3903 * 16_000_000)

    with pytest.raises(ValueError, match="follows its ACT Core1"):
        _join_cx321_psq_response_to_act(
            psq_response=psq, act_response=act
        )


def test_cx321_phase4_ack_rejects_cross_core_lag_beyond_actuator_deadline() -> None:
    psq, act = _cx321_psq_act_join_rows()
    act["application_timestamp_s"] = "3933"

    with pytest.raises(ValueError, match="30-second actuator deadline"):
        _join_cx321_psq_response_to_act(
            psq_response=psq, act_response=act
        )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("actionable", "true"),
        ("requested_delta_codes", "22"),
        ("accepted_code", str(0xA808 + 20)),
        ("cumulative_after_codes", "337"),
        ("active_policy_sha256", "0" * 64),
    ],
)
def test_prewrite_release_fails_closed_on_identity_or_budget_change(
    field: str, value: str
) -> None:
    row = _row()
    row[field] = value
    spec, identities, _ = load_no_write_qualification_spec("A")
    with pytest.raises(ValueError):
        validate_transaction_row(row, spec, identities, row["build_identity"])


def test_supervisor_fsyncs_capsule_then_submits_exact_phase_one_ack(
    tmp_path: Path,
) -> None:
    spec, identities, _ = load_no_write_qualification_spec("A")
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
            "requested_delta_codes": "21",
            "requested_code": str(spec.start_code + 21),
            "correction_ordinal": "1",
            "cumulative_after_codes": "21",
            "pre_error_hz": "0.02",
            "accepted_code": str(spec.start_code + 21),
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
    supervisor = ActiveTransactionSupervisor(
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


def test_supervisor_abort_uses_separate_priority_fifo(
    tmp_path: Path,
) -> None:
    spec, identities, _ = load_no_write_qualification_spec("A")
    run_dir = tmp_path / "run"
    normal_fifo_path = tmp_path / "normal.fifo"
    emergency_fifo_path = tmp_path / "emergency.fifo"
    supervisor = ActiveTransactionSupervisor(
        run_dir=run_dir,
        command_fifo=normal_fifo_path,
        emergency_command_fifo=emergency_fifo_path,
        abort_fifo=tmp_path / "abort.fifo",
        spec=spec,
        identities=identities,
        expected_build_identity="b" * 64 + ":" + "c" * 64,
        allow_manual_start=False,
        allow_arm=False,
        duration_s=None,
    )

    with CommandFifo(normal_fifo_path) as normal_reader, CommandFifo(
        emergency_fifo_path
    ) as emergency_reader:
        supervisor._abort("test_fault")
        assert emergency_reader.poll() == ["ACTIVE ABORT"]
        assert normal_reader.poll() == []
    assert supervisor.state["terminal"]["result"] == "aborted"
    events = (run_dir / "reports/cx317_active_supervisor_events.jsonl").read_text(
        encoding="utf-8"
    )
    assert "emergency_device_abort_submitted" in events


def test_cx320_restart_never_confuses_host_write_with_firmware_consumption(
    tmp_path: Path, monkeypatch
) -> None:
    inherited, identities, _ = load_no_write_qualification_spec("A")
    spec = replace(inherited, profile="cx320_active_hybrid")
    run_dir = tmp_path / "run"
    active_csv = run_dir / "csv" / "active_transactions_v1.csv"
    active_csv.parent.mkdir(parents=True)
    active_csv.write_text("fixture\n", encoding="utf-8")
    row = {
        "transaction_record_sequence": "2",
        "request_sequence": "1",
        "event": "request_created",
    }

    def supervisor() -> ActiveTransactionSupervisor:
        return ActiveTransactionSupervisor(
            run_dir=run_dir,
            command_fifo=tmp_path / "commands.fifo",
            abort_fifo=tmp_path / "abort.fifo",
            spec=spec,
            identities=identities,
            expected_build_identity="b" * 64 + ":" + "c" * 64,
            allow_manual_start=False,
            allow_arm=False,
            duration_s=None,
            dual_core_transactions=True,
        )

    first = supervisor()
    submitted: list[str] = []
    monkeypatch.setattr(
        first,
        "_prepare_evidence_acknowledgement",
        lambda _row, _phase: {"pre_submit_snapshot_generation": 7},
    )
    monkeypatch.setattr(first, "_command", submitted.append)
    monkeypatch.setattr(
        first, "_confirm_evidence_acknowledgement", lambda _value: False
    )

    with pytest.raises(ValueError, match="firmware consumption is unconfirmed"):
        first._preserve_and_acknowledge(row, 1)

    assert submitted == ["ACTIVE EVIDENCE 1 1"]
    assert first.state["acknowledged_record_sequences"] == []
    assert first.state["inflight_evidence_acknowledgement"] == {
        "record_sequence": 2,
        "request_sequence": 1,
        "phase": 1,
        "host_write_confirmed": True,
        "pre_submit_snapshot_generation": 7,
    }

    restarted = supervisor()
    monkeypatch.setattr(
        restarted,
        "_command",
        lambda _command: pytest.fail("ambiguous evidence ACK was resent"),
    )
    monkeypatch.setattr(
        restarted, "_confirm_evidence_acknowledgement", lambda _value: True
    )
    restarted._preserve_and_acknowledge(row, 1)

    assert restarted.state["acknowledged_record_sequences"] == [2]
    assert restarted.state["inflight_evidence_acknowledgement"] is None

def test_saturated_normal_fifo_cannot_block_priority_abort(
    tmp_path: Path,
) -> None:
    spec, identities, _ = load_no_write_qualification_spec("A")
    normal_fifo_path = tmp_path / "normal.fifo"
    emergency_fifo_path = tmp_path / "emergency.fifo"
    supervisor = ActiveTransactionSupervisor(
        run_dir=tmp_path / "run",
        command_fifo=normal_fifo_path,
        emergency_command_fifo=emergency_fifo_path,
        abort_fifo=tmp_path / "abort.fifo",
        spec=spec,
        identities=identities,
        expected_build_identity="b" * 64 + ":" + "c" * 64,
        allow_manual_start=False,
        allow_arm=False,
        duration_s=None,
    )

    with CommandFifo(normal_fifo_path), CommandFifo(
        emergency_fifo_path
    ) as emergency_reader:
        writer = os.open(normal_fifo_path, os.O_WRONLY | os.O_NONBLOCK)
        try:
            while True:
                try:
                    os.write(writer, b"CONFIG?\n" * 128)
                except BlockingIOError:
                    break
        finally:
            os.close(writer)

        with pytest.raises(BlockingIOError):
            supervisor._command("CONFIG?")
        supervisor._abort("normal_fifo_saturated")
        assert emergency_reader.poll() == ["ACTIVE ABORT"]

    assert supervisor.state["terminal"]["reason"] == "normal_fifo_saturated"
