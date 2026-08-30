from __future__ import annotations

import csv
import json
from pathlib import Path

from host.otis_tools import active_hybrid_activation as live_manifest
from host.otis_tools import active_hybrid_monitor as monitor
from host.otis_tools.active_hybrid_bundle import FRESH_SERIAL_AUTO_DETECT
from host.otis_tools.active_hybrid_programme_contract import (
    CX322_D9_D6_72H_PROGRAMME,
)
from host.otis_tools.contracts import CONTRACT_FIELDS


def _write_json(path: Path, value: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _write_csv(path: Path, row: dict[str, str]) -> None:
    _write_csv_rows(path, [row])


def _write_csv_rows(path: Path, rows: list[dict[str, str]]) -> None:
    assert rows
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=tuple(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def _contract_row(contract: str, **values: str) -> dict[str, str]:
    row = {field: "" for field in CONTRACT_FIELDS[contract]}
    unknown = set(values) - set(row)
    assert not unknown
    row.update(values)
    return row


def _fixture(tmp_path: Path, monkeypatch) -> tuple[Path, float]:
    run_dir = tmp_path / "run"
    now = 2_000_000_000.0
    manifest = {
        "run_id": "fixture",
        "bundle": {"bundle_sha256": "b" * 64},
        "activation": {"activation_sha256": "a" * 64},
        "host": {"serial_device": "/dev/fixture"},
    }
    monkeypatch.setattr(
        monitor,
        "validate_frozen_run_manifest",
        lambda path: manifest,
    )
    _write_json(
        run_dir / monitor.CAPTURE_STATE,
        {
            "pid": 321,
            "capture_active": True,
            "serial_open": True,
            "malformed_utf8": 0,
            "parser_errors": 0,
            "reconnect_count": 0,
            "commands_rejected": 0,
            "bytes_written": 100,
            "lines_parsed": 4,
            "commands_sent": 2,
            "emergency_aborts_sent": 0,
        },
    )
    _write_json(
        run_dir / monitor.SUPERVISOR_STATE,
        {
            "terminal": None,
            "latest_hybrid_state": "PHASE_QUALIFY",
            "phase_material_application_count": 1,
            "first_phase_checkpoint_passed": True,
        },
    )
    raw = run_dir / monitor.RAW_SERIAL
    raw.parent.mkdir(parents=True)
    raw.write_text("record\n", encoding="utf-8")
    for path in (run_dir / monitor.CAPTURE_STATE, raw):
        path.touch()
        monkeypatch.setattr(monitor, "_age_s", lambda path, now: 1.0)
    monkeypatch.setattr(monitor, "_serial_owner_pids", lambda device: {321})
    monkeypatch.setattr(monitor, "_pid_alive", lambda pid: True)
    return run_dir, now


def _campaign18_fixture(tmp_path: Path, monkeypatch) -> tuple[Path, float]:
    """Build a physical live-manifest shape and use its production validator."""

    run_dir = tmp_path / "campaign18-run"
    run_dir.mkdir()
    activation_path = tmp_path / "activation.json"
    bundle_path = tmp_path / "bundle.json"
    proposal_path = tmp_path / "proposal.json"
    build_identity = "b" * 64 + ":" + "c" * 64
    bundle = {
        "bundle_sha256": "d" * 64,
        "firmware": {
            "profile_id": CX322_D9_D6_72H_PROGRAMME.profile_id,
            "build_identity": build_identity,
        },
        "policy": {"policy_id": CX322_D9_D6_72H_PROGRAMME.policy_id},
        "host_tools": {},
        "finite_limits": {
            "qualified_origin": "first_complete_fresh_authoritative_600s_estimate",
            "wall_clock_origin": "sole_capture_owner_records_run_identity",
        },
    }
    proposal = {"proposal_sha256": "e" * 64}
    activation = {
        "programme_id": CX322_D9_D6_72H_PROGRAMME.programme_id,
        "activation_sha256": "a" * 64,
        "authority": live_manifest._authority(CX322_D9_D6_72H_PROGRAMME),
        "device": {
            "path": None,
            "selection": FRESH_SERIAL_AUTO_DETECT,
            "baud": 115200,
            "expected_board_serial": None,
        },
    }
    _write_json(activation_path, activation)
    _write_json(bundle_path, bundle)
    _write_json(proposal_path, proposal)
    monkeypatch.setattr(
        live_manifest,
        "validate_activation",
        lambda *args, **kwargs: (activation, bundle, proposal),
    )
    live_manifest.create_run_manifest(
        activation_path=activation_path,
        bundle_path=bundle_path,
        proposal_path=proposal_path,
        run_dir=run_dir,
        output_path=run_dir / "run_manifest.json",
        serial_device="/dev/cu.usbmodem-campaign18",
    )
    # Keep the production run-manifest validator intact.  Only its separately
    # tested frozen-input resolver is isolated to these local fixture inputs.
    monkeypatch.setattr(
        live_manifest,
        "validate_frozen_activation",
        lambda *args, **kwargs: (activation, bundle, proposal),
    )

    now = 2_000_000_000.0
    _write_json(
        run_dir / monitor.CAPTURE_STATE,
        {
            "pid": 321,
            "capture_active": True,
            "serial_open": True,
            "malformed_utf8": 0,
            "parser_errors": 0,
            "reconnect_count": 0,
            "commands_rejected": 0,
            "bytes_written": 100,
            "lines_parsed": 4,
            "commands_sent": 2,
            "emergency_aborts_sent": 0,
        },
    )
    _write_json(
        run_dir / monitor.SUPERVISOR_STATE,
        {
            "terminal": None,
            "latest_hybrid_state": "PHASE_QUALIFY",
            "phase_material_application_count": 1,
            "first_phase_checkpoint_passed": True,
        },
    )
    raw = run_dir / monitor.RAW_SERIAL
    raw.parent.mkdir(parents=True, exist_ok=True)
    raw.write_text("record\n", encoding="utf-8")
    monkeypatch.setattr(monitor, "_age_s", lambda path, now: 1.0)
    monkeypatch.setattr(monitor, "_serial_owner_pids", lambda device: {321})
    monkeypatch.setattr(monitor, "_pid_alive", lambda pid: True)

    transaction = _contract_row(
        "active_transactions_v1",
        record_type="ACT",
        schema_version="1",
        transaction_record_sequence="1",
        event="application",
        run_identity=CX322_D9_D6_72H_PROGRAMME.runtime_run_identity,
        build_identity=build_identity,
        profile_identity=CX322_D9_D6_72H_PROGRAMME.profile_id,
        session_id="7",
        request_sequence="1",
        decision_sequence="11",
        source_first_sequence="100",
        source_last_sequence="700",
        authorization_sequence="3",
        nonce="900",
        accepted_code="43068",
        applied_code="43068",
        application_sequence="1",
        dac_epoch="2",
        reason="application_applied",
    )
    transaction_timing = _contract_row(
        "active_transactions_v2",
        **{
            field: transaction[field]
            for field in monitor.ACTIVE_TRANSACTION_V2_FIELDS
            if field not in monitor._AT2_NON_JOIN_FIELDS
        },
    )
    transaction_timing.update(
        {
            "record_type": "AT2",
            "schema_version": "2",
            "timing_record_sequence": "1",
            "event_timestamp_ticks": "16000000",
            "time_domain": monitor.EXACT_LIFECYCLE_TIME_DOMAIN,
        }
    )
    decision = _contract_row(
        "active_hybrid_decisions_v1",
        record_type="AHY",
        schema_version="1",
        hybrid_record_sequence="1",
        decision_sequence="12",
        run_identity=CX322_D9_D6_72H_PROGRAMME.runtime_run_identity,
        build_identity=build_identity,
        profile_identity=CX322_D9_D6_72H_PROGRAMME.profile_id,
        capture_session="7",
        source_first_sequence="101",
        source_last_sequence="701",
        reason="application_consumed",
    )
    decision_timing = _contract_row(
        "active_hybrid_decisions_v2",
        **{
            field: decision[field]
            for field in monitor.ACTIVE_HYBRID_DECISION_V2_FIELDS
            if field not in monitor._AH2_NON_JOIN_FIELDS
        },
    )
    decision_timing.update(
        {
            "record_type": "AH2",
            "schema_version": "2",
            "timing_record_sequence": "1",
            "decision_timestamp_ticks": "32000000",
            "time_domain": monitor.EXACT_LIFECYCLE_TIME_DOMAIN,
        }
    )
    _write_csv(run_dir / monitor.ACTIVE, transaction)
    _write_csv(run_dir / monitor.ACTIVE_EXACT, transaction_timing)
    _write_csv(run_dir / monitor.HYBRID, decision)
    _write_csv(run_dir / monitor.HYBRID_EXACT, decision_timing)
    return run_dir, now


def test_running_snapshot_reports_owner_and_scientific_progress(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir, now = _fixture(tmp_path, monkeypatch)
    _write_csv(
        run_dir / monitor.HYBRID,
        _contract_row(
            "active_hybrid_decisions_v1",
            decision_sequence="8",
            dac_epoch="2",
            state_after="PHASE_QUALIFY",
            phase_materially_influenced="true",
            requested_delta_codes="4",
        ),
    )

    result = monitor.snapshot(run_dir, now=now)

    assert result["status"] == "running"
    assert result["integrity_faults"] == []
    assert result["capture"]["serial_owner_pids"] == [321]
    assert result["progress"]["phase_material_application_count"] == 1
    assert result["progress"]["active_hybrid_decisions"]["rows"] == 1


def test_progress_latest_fields_are_drawn_from_declared_csv_contracts(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir, now = _fixture(tmp_path, monkeypatch)
    _write_csv(
        run_dir / monitor.ESTIMATES,
        _contract_row(
            "estimates_v2",
            estimate_id="estimate-7",
            estimator_timestamp_ticks="42000000",
            source_dac_ref="dac-2",
            frequency_error_hz="0.00125",
        ),
    )
    _write_csv(
        run_dir / monitor.ACTIVE,
        _contract_row(
            "active_transactions_v1",
            transaction_record_sequence="12",
            event="response",
            request_sequence="3",
            active_state="DISARMED",
            response_class="healthy_detected",
        ),
    )
    _write_csv(
        run_dir / monitor.HYBRID,
        _contract_row(
            "active_hybrid_decisions_v1",
            hybrid_record_sequence="9",
            decision_sequence="8",
            dac_epoch="2",
            state_after="FIRST_PHASE_TRANSACTION",
            phase_materially_influenced="true",
            requested_delta_codes="4",
        ),
    )

    progress = monitor.snapshot(run_dir, now=now)["progress"]

    assert progress["estimates"]["latest"] == {
        "estimate_id": "estimate-7",
        "estimator_timestamp_ticks": "42000000",
        "source_dac_ref": "dac-2",
        "frequency_error_hz": "0.00125",
    }
    assert progress["active_transactions"]["latest"] == {
        "transaction_record_sequence": "12",
        "event": "response",
        "request_sequence": "3",
        "active_state": "DISARMED",
        "response_class": "healthy_detected",
    }
    assert progress["active_hybrid_decisions"]["latest"] == {
        "hybrid_record_sequence": "9",
        "decision_sequence": "8",
        "dac_epoch": "2",
        "state_after": "FIRST_PHASE_TRANSACTION",
        "phase_materially_influenced": "true",
        "requested_delta_codes": "4",
    }


def test_stale_capture_and_wrong_owner_are_faults(tmp_path: Path, monkeypatch) -> None:
    run_dir, now = _fixture(tmp_path, monkeypatch)
    monkeypatch.setattr(monitor, "_age_s", lambda path, now: 30.0)
    monkeypatch.setattr(monitor, "_serial_owner_pids", lambda device: {999})

    result = monitor.snapshot(run_dir, now=now)

    assert result["status"] == "fault"
    assert "capture_state_stale" in result["integrity_faults"]
    assert "raw_evidence_stale" in result["integrity_faults"]
    assert "sole_serial_owner_mismatch" in result["integrity_faults"]


def test_terminal_snapshot_does_not_require_live_owner(tmp_path: Path, monkeypatch) -> None:
    run_dir, now = _fixture(tmp_path, monkeypatch)
    _write_json(
        run_dir / monitor.SUPERVISOR_STATE,
        {"terminal": {"result": "healthy_stop", "reason": "finite"}},
    )
    monkeypatch.setattr(monitor, "_serial_owner_pids", lambda device: set())
    monkeypatch.setattr(monitor, "_age_s", lambda path, now: 60.0)

    result = monitor.snapshot(run_dir, now=now)

    assert result["status"] == "terminal"
    assert "sole_serial_owner_mismatch" not in result["integrity_faults"]
    assert "raw_evidence_stale" not in result["integrity_faults"]


def test_campaign18_physical_manifest_monitor_reports_exact_sidecar_progress_and_faults(
    tmp_path: Path, monkeypatch
) -> None:
    run_dir, now = _campaign18_fixture(tmp_path, monkeypatch)

    running = monitor.snapshot(run_dir, now=now)

    assert running["status"] == "running"
    assert running["integrity_faults"] == []
    exact = running["progress"]["exact_timing_sidecars"]
    assert exact["join_exact_at_observed_frontier"] is True
    assert exact["AT2"]["source_rows"] == 1
    assert exact["AT2"]["sidecar_rows"] == 1
    assert exact["AT2"]["joined_rows"] == 1
    assert exact["AT2"]["join_lag_rows"] == 0
    assert exact["AT2"]["latest"]["event_timestamp_ticks"] == "16000000"
    assert exact["AH2"]["source_rows"] == 1
    assert exact["AH2"]["sidecar_rows"] == 1
    assert exact["AH2"]["joined_rows"] == 1
    assert exact["AH2"]["join_lag_rows"] == 0
    assert exact["AH2"]["latest"]["decision_timestamp_ticks"] == "32000000"

    ah2_bytes = (run_dir / monitor.HYBRID_EXACT).read_bytes()
    (run_dir / monitor.HYBRID_EXACT).unlink()
    missing_sidecar = monitor.snapshot(run_dir, now=now)

    assert missing_sidecar["status"] == "fault"
    assert "exact_timing_sidecar_unavailable" in missing_sidecar[
        "integrity_faults"
    ]
    assert "required retained CSV is missing" in missing_sidecar["progress"][
        "exact_timing_sidecars"
    ]["mismatches"][0]
    (run_dir / monitor.HYBRID_EXACT).write_bytes(ah2_bytes)

    decision_rows = monitor._stable_contract_rows(
        run_dir / monitor.HYBRID, monitor.ACTIVE_HYBRID_DECISION_V1_FIELDS
    )
    second_decision = dict(decision_rows[0])
    second_decision.update(
        {
            "hybrid_record_sequence": "2",
            "decision_sequence": "13",
            "source_first_sequence": "102",
            "source_last_sequence": "702",
            "reason": "next_decision_pending_exact_sidecar",
        }
    )
    _write_csv_rows(run_dir / monitor.HYBRID, [decision_rows[0], second_decision])

    transient_lag = monitor.snapshot(run_dir, now=now)

    assert transient_lag["status"] == "running"
    ah2 = transient_lag["progress"]["exact_timing_sidecars"]["AH2"]
    assert ah2["source_rows"] == 2
    assert ah2["sidecar_rows"] == 1
    assert ah2["joined_rows"] == 1
    assert ah2["join_lag_rows"] == 1
    assert ah2["pending_source_sequences"] == ["2"]

    monkeypatch.setattr(monitor, "_age_s", lambda path, now: 30.0)
    monkeypatch.setattr(monitor, "_serial_owner_pids", lambda device: {999})
    stale = monitor.snapshot(run_dir, now=now)

    assert stale["status"] == "fault"
    assert "capture_state_stale" in stale["integrity_faults"]
    assert "raw_evidence_stale" in stale["integrity_faults"]
    assert "sole_serial_owner_mismatch" in stale["integrity_faults"]
    assert "AH2_sidecar_join_lag_stale" in stale["integrity_faults"]

    monkeypatch.setattr(monitor, "_age_s", lambda path, now: 1.0)
    monkeypatch.setattr(monitor, "_serial_owner_pids", lambda device: {321})
    transaction_timing = monitor._stable_contract_rows(
        run_dir / monitor.ACTIVE_EXACT, monitor.ACTIVE_TRANSACTION_V2_FIELDS
    )[0]
    transaction_timing["accepted_code"] = "43069"
    _write_csv(run_dir / monitor.ACTIVE_EXACT, transaction_timing)

    mismatch = monitor.snapshot(run_dir, now=now)

    assert mismatch["status"] == "fault"
    assert "exact_timing_sidecar_identity_mismatch" in mismatch["integrity_faults"]
    assert mismatch["progress"]["exact_timing_sidecars"]["mismatches"] == [
        "AT2 join mismatch transaction_record_sequence=1:accepted_code"
    ]
