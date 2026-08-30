from __future__ import annotations

from copy import deepcopy
import csv
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from host.otis_tools import d9_d6_frequency_only_endurance as endurance
from host.otis_tools.run_loader import load_manifest


ROOT = Path(__file__).resolve().parents[1]


def test_frequency_only_metadata_hold_freezes_and_requalifies_causally() -> None:
    supervisor = object.__new__(endurance.D9D6FrequencyOnlyEnduranceSupervisor)
    supervisor.state = {
        "gnss_metadata_hold_active": False,
        "gnss_metadata_hold_count": 0,
        "gnss_metadata_hold_oracle": None,
        "gnss_metadata_hold_identity": None,
    }
    supervisor.accounting = SimpleNamespace(last_count_sequence=100)
    events: list[tuple[str, dict[str, object]]] = []
    supervisor._save = lambda: None
    supervisor._event = (
        lambda event, **payload: events.append((event, payload))
    )
    health = {
        ("cx317_active", "state"): "GNSS_METADATA_HOLD",
        ("cx317_active", "reason"): "gnss_metadata_unqualified_hold",
        ("cx317_active", "gnss_metadata_hold_active"): "true",
        ("cx317_active", "confirmed_applied_code_known"): "true",
        ("cx317_active", "confirmed_applied_code"): "43068",
        ("cx317_active", "dac_epoch"): "1",
        ("cx317_active", "correction_count"): "0",
        ("cx317_active", "cumulative_movement_codes"): "0",
        ("cx317_active", "session_id"): "7",
        ("cx317_active", "gnss_metadata_hold_entry_sequence"): "30",
        ("cx317_active", "gnss_metadata_hold_transaction_pending"): "false",
    }
    supervisor._update_metadata_hold(health)
    assert supervisor.state["gnss_metadata_hold_active"] is True
    assert supervisor.state["gnss_metadata_hold_count"] == 1

    changed = dict(health)
    changed[("cx317_active", "dac_epoch")] = "2"
    with pytest.raises(ValueError, match="actuation identity changed"):
        supervisor._update_metadata_hold(changed)

    recovered = dict(health)
    recovered.update(
        {
            ("cx317_active", "state"): "DISARMED",
            ("cx317_active", "gnss_metadata_hold_active"): "false",
            ("cx317_active", "reason"): (
                "reference_requalified_fresh_authorization_required"
            ),
            ("cx317_active", "gnss_metadata_requalification_sequence"): "31",
            ("cx317_active", "gnss_metadata_qualification_frontier"): "100",
            ("cx317_active", "d14_d8_observation_sequence"): "101",
        }
    )
    supervisor._update_metadata_hold(recovered)
    assert supervisor.state["gnss_metadata_hold_active"] is False
    assert events[-1][0].endswith("fresh_causal_requalification")


def _build(tmp_path: Path) -> Path:
    matrix = json.loads((ROOT / "firmware/arduino/firmware_matrix.json").read_text())
    defines = next(item["defines"] for item in matrix["profiles"] if item["id"] == "d9_d6_frequency_only_lower")
    path = tmp_path / "build.json"
    uf2 = tmp_path / "firmware.uf2"
    uf2.write_bytes(b"exact-frequency-only-uf2")
    path.write_text(json.dumps({"provenance": {"source": {"git_commit": "a" * 40, "sha256": "b" * 64}, "configuration": {"profile_id": "d9_d6_frequency_only_lower", "fqbn": endurance.EXPECTED_UPLOAD_FQBN, "defines": defines, "sha256": "c" * 64}}, "artifacts": [{"name": uf2.name, "sha256": endurance.sha256(uf2.read_bytes()).hexdigest(), "size_bytes": uf2.stat().st_size}]}), encoding="utf-8")
    return path


def _bundle(tmp_path: Path) -> dict[str, object]:
    return endurance.freeze_bundle(build_manifest_path=_build(tmp_path), source_revision="a" * 40)


def _activation_for_bundle(
    tmp_path: Path, bundle: dict[str, object]
) -> tuple[dict[str, object], dict[str, object], Path]:
    bundle_path = tmp_path / "bundle.json"
    endurance._write_new(bundle_path, bundle)
    preflight_path = tmp_path / "preflight.json"
    endurance._write_new(preflight_path, endurance.no_io_preflight(bundle))
    rehearsal_path = tmp_path / "rehearsal.json"
    endurance._write_new(
        rehearsal_path,
        {
            "schema_version": 1,
            "tool": endurance.TOOL_ID,
            "report_type": "frequency_only_exact_operational_rehearsal_v1",
            "status": "passed",
            "hardware_operations": False,
            "bundle_sha256": bundle["bundle_sha256"],
            "profile_id": bundle["profile_id"],
            "firmware_build_identity": bundle["firmware"]["build_identity"],
            "firmware_build_manifest_sha256": bundle["firmware_build"][
                "sha256"
            ],
            "firmware_flash_authority": endurance._firmware_flash_authority(),
            "mode": "PTY_fixture",
            "production_upload_orchestration_exercised": True,
            "deterministic_upload_and_reenumeration_injected": True,
            "exactly_one_upload_no_retry_enforced": True,
            "global_activation_consumption_replay_blocked": True,
            "pre_upload_fresh_auto_detect_exercised": True,
            "post_upload_fresh_auto_detect_exercised": True,
            "capture_own_auto_detect_command_exercised": True,
            "firmware_policy_identity_replayed_by_live_supervisor": True,
            "actual_frequency_only_exact_counter_arm_exercised": True,
            "priority_abort_delivered": True,
            "abort_delivery_retained_before_capture_close": True,
            "actual_supervisor_exercised": True,
            "complete_response_transactions": 2,
            "one_outstanding_transaction_enforced": True,
            "opportunity_causal_ledger_exercised": True,
            "accelerated_exact_counter_endpoint_reached": True,
            "gnss_metadata_hold_effective_live_supervisor_fault_injection": True,
            "gnss_metadata_hold_confirmed_session_code_epoch_bound": True,
            "gnss_metadata_hold_fresh_causal_requalification_exercised": True,
        },
    )
    activation = endurance.activate_bundle(
        bundle_path=bundle_path,
        preflight_report_path=preflight_path,
        rehearsal_report_path=rehearsal_path,
        operator_authorization_ref="operator_thread_2026-08-28_bench_authority",
    )
    activation_path = tmp_path / "activation.json"
    endurance._write_new(activation_path, activation)
    return bundle, activation, activation_path


def _activation(tmp_path: Path) -> tuple[dict[str, object], dict[str, object], Path]:
    return _activation_for_bundle(tmp_path, _bundle(tmp_path))


def _fixture_firmware_entry(
    *,
    run_dir: Path,
    activation: dict[str, object],
    bundle: dict[str, object],
) -> tuple[str, dict[str, object], dict[str, object]]:
    devices = iter(("/dev/cu.before", "/dev/cu.after"))
    board = {
        "hardware_id": "fixture-board",
        "serial_number": "fixture-board",
        "vid": "0x2341",
        "pid": "0x005E",
        "product": "fixture Nano RP2040",
        "board_name": "Arduino Nano RP2040 Connect",
        "board_fqbn": "rp2040:rp2040:arduino_nano_connect",
    }
    return endurance._execute_activation_authorized_upload(
        run_dir=run_dir,
        activation=activation,
        bundle=bundle,
        fresh_detect=lambda: next(devices),
        identity_reader=lambda device: {**board, "address": device},
        owner_reader=lambda _: set(),
        upload_runner=lambda *args, **kwargs: SimpleNamespace(
            returncode=0, stdout="fixture upload", stderr=""
        ),
        sleep_fn=lambda _: None,
        hardware_operations=True,
    )


def _control_row(
    sequence: int,
    *,
    limited_delta: int = 0,
    reason: str = "inside_deadband",
    eligible: bool = False,
) -> dict[str, str]:
    truth = "true" if eligible else "false"
    return {
        "control_seq": str(sequence),
        "decision_id": f"fixture:{sequence}",
        "decision_timestamp_ticks": str(sequence * endurance.TIMER_HZ),
        "time_domain": "rp2040_timer0",
        "control_state": "ACTIVE",
        "preview_eligibility": "true" if limited_delta else "false",
        "limited_delta_codes": str(limited_delta),
        "preview_available": "true",
        "actuation_authorized": truth,
        "actionable": truth,
        "decision_reason_code": reason,
    }


CONTROL_FIELDS = list(_control_row(1))


def _write_analyzer_fixture(
    run_dir: Path, bundle: dict[str, object], *, interval_count: int = 1200
) -> None:
    (run_dir / "csv").mkdir(parents=True)
    activation_source = run_dir.parent / f"{run_dir.name}-activation-source"
    activation_source.mkdir()
    _, activation, activation_path = _activation_for_bundle(
        activation_source, bundle
    )
    device, board, firmware_entry = _fixture_firmware_entry(
        run_dir=run_dir, activation=activation, bundle=bundle
    )
    endurance.create_live_manifest(
        run_dir=run_dir,
        activation_path=activation_path,
        activation=activation,
        resolved_device=device,
        board_identity=board,
        firmware_entry=firmware_entry,
    )
    endurance._write_new(
        run_dir / endurance.SUPERVISOR_STATE_PATH,
        {
            "terminal": {
                "result": "healthy_stop",
                "reason": "frequency_only_d9_d6_digital_endurance_passed",
            },
            "qualified_duration_s": interval_count,
            "milestones_qualified_s": [],
            "automatic_dac_commands_sent_by_host": 0,
            "phase_or_hybrid_commands_sent_by_host": 0,
            "control_opportunity_count": 1,
            "eligible_control_opportunity_count": 0,
            "pending_control_opportunity_sequences": [],
            "lost_opportunity_dispositions": {"no_demand": 1},
            "gnss_metadata_hold_count": 0,
            "gnss_metadata_hold_active": False,
        },
    )
    transaction_rows = [endurance._rehearsal_transaction_rows(bundle)[0]]
    endurance._write_csv_rows(
        run_dir / endurance.ACTIVE_CSV,
        endurance.ACTIVE_TRANSACTION_V1_FIELDS,
        transaction_rows,
    )
    timing_row = {
        field: "" for field in endurance.ACTIVE_TRANSACTION_V2_FIELDS
    }
    timing_row.update(
        {
            field: transaction_rows[0][field]
            for field in endurance.ACTIVE_TRANSACTION_TIMING_JOIN_FIELDS
        }
    )
    timing_row.update(
        {
            "record_type": "AT2",
            "schema_version": "2",
            "timing_record_sequence": "1",
            "event_timestamp_ticks": "100",
            "time_domain": endurance.EXACT_LIFECYCLE_TIME_DOMAIN,
        }
    )
    endurance._write_csv_rows(
        run_dir / "csv/active_transactions_v2.csv",
        endurance.ACTIVE_TRANSACTION_V2_FIELDS,
        [timing_row],
    )
    health_rows = [
        {
            "component": component,
            "status_key": key,
            "status_value": value,
        }
        for (component, key), value in endurance.EXPECTED_D9_HEALTH.items()
    ]
    health_rows.append(
        {
            "component": "forwarded_clock_output",
            "status_key": "first_valid_ticks",
            "status_value": "100",
        }
    )
    endurance._write_csv_rows(
        run_dir / "csv/health.csv",
        ["component", "status_key", "status_value"],
        health_rows,
    )
    timer0_modulus = (1 << 32) * 16
    raw_rows: list[dict[str, str]] = []
    snapshot_rows: list[dict[str, str]] = []
    count_rows: list[dict[str, str]] = []
    for sequence in range(interval_count + 1):
        ticks = (100 + sequence * endurance.TIMER_HZ) % timer0_modulus
        down_counter = (3_000_000_000 - sequence * 10_000_000) % (1 << 32)
        raw_rows.append(
            {
                "record_type": "REF",
                "schema_version": "1",
                "event_seq": str(sequence + 1),
                "channel_id": "1",
                "edge": "R",
                "timestamp_ticks": str(ticks),
                "capture_domain": "rp2040_timer0",
                "flags": "0",
            }
        )
        snapshot_rows.append(
            {
                "record_type": "SNP",
                "schema_version": "1",
                "session": "7",
                "snapshot_sequence": str(sequence),
                "cumulative_down_counter": str(down_counter),
                "reference_sequence": str(10 + sequence),
                "reference_timestamp_ticks": str(ticks),
                "status": "0",
                "backend": "pio_wait_cumulative_snapshot_dma_v1",
            }
        )
        if sequence:
            count_rows.append(
                {
                    "record_type": "CNT",
                    "schema_version": "1",
                    "count_seq": str(sequence),
                    "channel_id": "2",
                    "gate_open_ticks": str(
                        (100 + (sequence - 1) * endurance.TIMER_HZ)
                        % timer0_modulus
                    ),
                    "gate_close_ticks": str(ticks),
                    "gate_domain": "rp2040_timer0",
                    "counted_edges": "10000000",
                    "source_edge": "R",
                    "source_domain": "h1_cx317_ocxo_10mhz",
                    "flags": "0",
                }
            )
    endurance._write_csv_rows(
        run_dir / "csv/raw_events.csv",
        [
            "record_type",
            "schema_version",
            "event_seq",
            "channel_id",
            "edge",
            "timestamp_ticks",
            "capture_domain",
            "flags",
        ],
        raw_rows,
    )
    endurance._write_csv_rows(
        run_dir / "csv/pps_snapshots.csv",
        [
            "record_type",
            "schema_version",
            "session",
            "snapshot_sequence",
            "cumulative_down_counter",
            "reference_sequence",
            "reference_timestamp_ticks",
            "status",
            "backend",
        ],
        snapshot_rows,
    )
    endurance._write_csv_rows(
        run_dir / "csv/count_observations.csv",
        [
            "record_type",
            "schema_version",
            "count_seq",
            "channel_id",
            "gate_open_ticks",
            "gate_close_ticks",
            "gate_domain",
            "counted_edges",
            "source_edge",
            "source_domain",
            "flags",
        ],
        count_rows,
    )
    endurance._write_csv_rows(
        run_dir / "csv/estimates_v2.csv",
        [
            "estimate_id",
            "estimator_version",
            "source_count_seq",
            "source_reference_first_seq",
            "source_reference_last_seq",
            "accepted_sample_count",
            "observation_validity",
            "reference_validity",
            "reference_continuity",
            "count_validity",
            "count_continuity",
            "diagnostic_health",
            "frequency_error_hz",
        ],
        [
            {
                "estimate_id": "selected-600",
                "estimator_version": "cx317_selected_600s_nonoverlap_v1",
                "source_count_seq": "600",
                "source_reference_first_seq": "10",
                "source_reference_last_seq": "609",
                "accepted_sample_count": "600",
                "observation_validity": "valid",
                "reference_validity": "valid",
                "reference_continuity": "true",
                "count_validity": "valid",
                "count_continuity": "true",
                "diagnostic_health": "healthy",
                "frequency_error_hz": "0.25",
            },
            {
                "estimate_id": "selected-1200",
                "estimator_version": "cx317_selected_600s_nonoverlap_v1",
                "source_count_seq": "1200",
                "source_reference_first_seq": "610",
                "source_reference_last_seq": "1209",
                "accepted_sample_count": "600",
                "observation_validity": "valid",
                "reference_validity": "valid",
                "reference_continuity": "true",
                "count_validity": "valid",
                "count_continuity": "true",
                "diagnostic_health": "healthy",
                "frequency_error_hz": "0.10",
            },
        ],
    )
    manifest_sha256 = endurance.sha256(
        (run_dir / "run_manifest.json").read_bytes()
    ).hexdigest()
    closure = {
        "schema_version": 1,
        "protocol": "otis_capture_segment_rotation_v1",
        "closed_utc": "2026-08-28T00:00:00Z",
        "run": str(run_dir.resolve()),
        "run_manifest_sha256": manifest_sha256,
        "device": device,
        "baud": 115200,
        "owner_pid": 1,
        "transport_generation": 1,
        "closure_mode": "physical_serial_close",
        "logical_segment_closed": True,
        "physical_serial_open": False,
        "serial_reopened": False,
        "next_run": None,
        "request_id": None,
        "serial_owner_check": None,
        "counters": {},
    }
    endurance._write_new(
        run_dir / "reports/capture_segment_closure_v1.json", closure
    )
    endurance._write_new(
        run_dir / "reports/capture_device_state.json",
        {
            "capture_active": False,
            "serial_open": False,
            "logical_segment_closed": True,
            "physical_serial_open": False,
        },
    )
    endurance._record_run_lifecycle(
        run_dir=run_dir,
        terminal_reason="frequency_only_d9_d6_digital_endurance_passed",
        capture_returncode=0,
        expected_device=device,
    )


def test_contract_bundle_and_no_io_preflight_are_frequency_only(tmp_path: Path) -> None:
    contract = endurance.load_contract()
    bundle = _bundle(tmp_path)
    result = endurance.no_io_preflight(bundle)
    assert contract["profile_id"] == "d9_d6_frequency_only_lower"
    assert result["hardware_operations"] is False
    assert result["gnss_uart_policy"] == contract["gnss_uart_policy"]
    assert bundle["gnss_uart_policy"]["maximum_total_attempts"] == 2
    assert bundle["gnss_uart_policy"]["settle_after_peripheral_drain_ms"] == 1200
    assert bundle["gnss_uart_policy"]["autodiscovery_permitted"] is False
    assert "general_waveform_qualification" in result["unresolved_delivered_output_claims"]
    assert contract["envelope"]["maximum_automatic_applications"] == 48
    assert contract["envelope"]["maximum_cumulative_movement_codes"] == 1008
    assert contract["envelope"]["maximum_total_physical_dac_writes"] == 49
    assert contract["envelope"]["automatic_limits_are_nonbinding_cadence_derived_ceilings"] is True
    assert (
        contract["sustained_discipline"][
            "application_admission_close_before_qualified_endpoint_s"
        ]
        == 1500
    )
    assert (
        contract["sustained_discipline"][
            "longer_analysis_horizons_do_not_close_control_admission"
        ]
        is True
    )
    assert (
        contract["gnss_metadata_hold"]["authority"]
        == "effective_firmware_and_live_supervisor_semantics"
    )


def test_candidate_bundle_is_non_effective_until_exact_reports_activate_it(
    tmp_path: Path,
) -> None:
    bundle, activation, activation_path = _activation(tmp_path)

    assert bundle["effective"] is False
    assert bundle["physical_authority"] is False
    assert activation["effective"] is True
    assert activation["physical_authority"] is True
    checked_activation, checked_bundle = endurance.validate_activation(
        endurance._read(activation_path)
    )
    assert checked_activation["candidate_bundle_sha256"] == bundle["bundle_sha256"]
    assert checked_bundle["firmware"]["build_identity"] == bundle["firmware"][
        "build_identity"
    ]
    capture_contract = checked_activation["capture_evidence_contract"]
    assert capture_contract == endurance._exact_capture_contract()
    assert capture_contract["contracts"]["active_transactions_v2"] == 2
    assert capture_contract["contracts"]["active_hybrid_decisions_v2"] == 2
    assert {
        item["name"] for item in capture_contract["domains"]
    } >= {"rp2040_timer0", endurance.EXACT_LIFECYCLE_TIME_DOMAIN}

    tampered_activation = deepcopy(checked_activation)
    tampered_activation["capture_evidence_contract"]["contracts"][
        "active_transactions_v2"
    ] = 1
    unsigned = {
        key: value
        for key, value in tampered_activation.items()
        if key != "activation_sha256"
    }
    tampered_activation["activation_sha256"] = endurance.canonical_sha256(unsigned)
    with pytest.raises(ValueError, match="activation exact bindings differ"):
        endurance.validate_activation(tampered_activation)

    rehearsal_path = Path(str(activation["rehearsal_report"]["path"]))
    rehearsal = endurance._read(rehearsal_path)
    rehearsal["gnss_metadata_hold_confirmed_session_code_epoch_bound"] = False
    endurance._write_replace(rehearsal_path, rehearsal)
    with pytest.raises(ValueError, match="rehearsal report differs"):
        endurance.validate_activation(activation)


def test_bundle_rejects_hybrid_selector(tmp_path: Path) -> None:
    path = _build(tmp_path); value = json.loads(path.read_text()); value["provenance"]["configuration"]["defines"]["OTIS_ENABLE_CX322_DIRECT_HYBRID"] = "1"; path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="zero-hybrid"):
        endurance.freeze_bundle(build_manifest_path=path, source_revision="a" * 40)


def test_bundle_rejects_caller_revision_or_uf2_identity_drift(tmp_path: Path) -> None:
    path = _build(tmp_path)
    with pytest.raises(ValueError, match="source revision"):
        endurance.freeze_bundle(build_manifest_path=path, source_revision="d" * 40)
    value = json.loads(path.read_text())
    (tmp_path / "firmware.uf2").write_bytes(b"different")
    path.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(ValueError, match="UF2"):
        endurance.freeze_bundle(build_manifest_path=path, source_revision="a" * 40)


def test_exact_counter_accounting_milestones_and_terminal() -> None:
    contract = deepcopy(endurance.load_contract())
    contract["envelope"]["qualified_duration_s"] = 4
    contract["envelope"]["milestone_qualified_duration_s"] = 1
    supervisor = endurance.EnduranceSupervisor(contract)
    supervisor.arm(frontier_ticks=100, d9_state="configured_10mhz_forwarded_unqualified", d9_readback_exact=True, d14_d8_healthy=True, outstanding_transaction=False, applied_code=0xA808, dac_epoch=1)
    for number in range(4):
        start = 100 + number * endurance.TIMER_HZ
        supervisor.observe_interval(opening_ticks=start, closing_ticks=start + endurance.TIMER_HZ, measurement_qualified=True, d9_valid=True)
    assert supervisor.milestones == [1, 2, 3, 4]
    assert supervisor.target_reached is True
    assert supervisor.terminal is None


def test_exact_counter_accounting_accepts_uint32_sequence_rollover() -> None:
    supervisor = endurance.EnduranceSupervisor(endurance.load_contract())
    supervisor.arm(
        frontier_ticks=100,
        d9_state="configured_10mhz_forwarded_unqualified",
        d9_readback_exact=True,
        d14_d8_healthy=True,
        outstanding_transaction=False,
        applied_code=0xA808,
        dac_epoch=1,
    )
    supervisor.observe_interval(
        opening_ticks=100,
        closing_ticks=101,
        measurement_qualified=True,
        d9_valid=True,
        count_sequence=(1 << 32) - 1,
    )
    supervisor.observe_interval(
        opening_ticks=101,
        closing_ticks=102,
        measurement_qualified=True,
        d9_valid=True,
        count_sequence=0,
    )

    assert supervisor.terminal is None
    assert supervisor.last_count_sequence == 0


def test_d9_invalidity_and_hybrid_transaction_are_terminals() -> None:
    contract = endurance.load_contract()
    first = endurance.EnduranceSupervisor(contract); first.arm(frontier_ticks=0, d9_state="configured_10mhz_forwarded_unqualified", d9_readback_exact=True, d14_d8_healthy=True, outstanding_transaction=False, applied_code=0xA808, dac_epoch=1); first.observe_interval(opening_ticks=0, closing_ticks=1, measurement_qualified=True, d9_valid=False)
    assert first.terminal == "frequency_only_d9_d6_digital_noninterference_failed"
    second = endurance.EnduranceSupervisor(contract); second.record_fll_transaction(setup_establishment=False, requested_delta_codes=1, application_ticks=0, phase_or_hybrid=True)
    assert second.terminal == "frequency_only_d9_d6_controller_or_transaction_fault"


def test_live_d9_gate_waits_for_complete_configuration_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor = endurance.create_live_supervisor(
        run_dir=tmp_path / "run",
        bundle=_bundle(tmp_path),
    )

    supervisor._check_fail_static_health({})
    assert supervisor.state["terminal"] is None
    assert supervisor.state["d9_exact_readback_established"] is False

    health = dict(endurance.EXPECTED_D9_HEALTH)
    health[("forwarded_clock_output", "first_valid_ticks")] = "100"
    health[("command", "config_snapshot")] = "begin"
    supervisor._check_fail_static_health(health)
    assert supervisor.state["terminal"] is None
    assert supervisor.state["d9_exact_readback_established"] is False

    health[("command", "config_snapshot")] = "end"
    supervisor._check_fail_static_health(health)
    assert supervisor.state["terminal"] is None
    assert supervisor.state["d9_exact_readback_established"] is True

    del health[("forwarded_clock_output", "readback_valid")]
    supervisor._check_fail_static_health(health)
    assert supervisor.state["terminal"]["reason"] == (
        "frequency_only_d9_d6_digital_noninterference_failed"
    )


def test_live_d9_gate_times_out_if_configuration_snapshot_never_completes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor = endurance.create_live_supervisor(
        run_dir=tmp_path / "run",
        bundle=_bundle(tmp_path),
    )
    supervisor._d9_configuration_wait_started_monotonic = 100.0
    monkeypatch.setattr(
        endurance.time,
        "monotonic",
        lambda: 100.0 + endurance.D9_CONFIGURATION_SNAPSHOT_COMPLETION_TIMEOUT_S,
    )
    supervisor._abort = lambda reason: supervisor.state.__setitem__(  # type: ignore[method-assign]
        "terminal", {"result": "aborted", "reason": reason}
    )

    supervisor._check_fail_static_health({})

    assert supervisor.state["terminal"]["reason"] == (
        "frequency_only_d9_d6_digital_noninterference_failed"
    )
    events = [
        json.loads(line)
        for line in supervisor.events_path.read_text(encoding="utf-8").splitlines()
    ]
    assert events[-1]["event"] == (
        "frequency_only_d9_configuration_snapshot_timeout"
    )


def test_live_frequency_only_rejects_post_bootstrap_promotion_attempt(
    tmp_path: Path,
) -> None:
    supervisor = endurance.create_live_supervisor(
        run_dir=tmp_path / "run",
        bundle=_bundle(tmp_path),
    )
    identity = {
        "run_identity": supervisor.spec.run_identity,
        "build_identity": supervisor.expected_build_identity,
        "profile_identity": supervisor.spec.profile,
        **supervisor.identities,
    }
    health = endurance.canonical_prewrite_fixture(
        expected_identity=identity,
        planned_live_stimulus_code=supervisor.spec.start_code,
    )
    health.update(endurance.EXPECTED_D9_HEALTH)
    health[("forwarded_clock_output", "first_valid_ticks")] = "100"
    health[("command", "config_snapshot")] = "end"
    health[
        (
            "gnss_receiver",
            "post_bootstrap_target_baud_command_attempt_count",
        )
    ] = "1"
    supervisor.state["prewrite_contract_ready_utc"] = "2026-08-28T00:00:00Z"

    supervisor._check_fail_static_health(health)

    assert supervisor.state["terminal"]["reason"] == (
        "frequency_only_d9_d6_invalid_due_to_identity_or_evidence_failure"
    )


def test_live_frequency_only_holds_during_bounded_gnss_bootstrap(
    tmp_path: Path,
) -> None:
    supervisor = endurance.create_live_supervisor(
        run_dir=tmp_path / "run",
        bundle=_bundle(tmp_path),
    )
    health = {
        ("gnss_receiver", "operational_bootstrap_state"): "in_progress",
        ("gnss_receiver", "operational_bootstrap_attempt_count"): "1",
        ("gnss_receiver", "target_baud_command_attempt_count"): "1",
    }

    supervisor._check_fail_static_health(health)

    assert supervisor.state["terminal"] is None
    assert supervisor.state["prewrite_contract_ready_utc"] is None


def test_live_run_loop_holds_setup_until_post_config_d9_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from host.otis_tools import frequency_control_supervisor

    run_dir = tmp_path / "run"
    supervisor = endurance.create_live_supervisor(
        run_dir=run_dir,
        bundle=_bundle(tmp_path),
    )
    (run_dir / "capture_in_progress.flag").touch()
    ready = {
        ("cx317_active", "run_identity"): supervisor.spec.run_identity,
        ("cx317_active", "build_identity"): supervisor.expected_build_identity,
        ("cx317_active", "profile_identity"): supervisor.spec.profile,
        ("cx317_active", "session_id"): "4",
        ("cx317_active", "state"): "DISARMED",
        ("cx317_active", "reason"): "initialized_disarmed",
        ("cx317_active", "manual_start_confirmed"): "false",
        ("cx317_active", "snapshot_generation_complete"): "7",
        ("cx317_active", "query_nonce"): str(
            supervisor.state["host_attach_query_nonce"]
        ),
        ("cx317_active", "uptime_s"): "1000",
        ("command", "config_snapshot"): "end",
        ("forwarded_clock_output", "first_valid_ticks"): "100",
        **endurance.EXPECTED_D9_HEALTH,
    }
    for key, value in supervisor.identities.items():
        ready[("cx317_active", key)] = value
    health_rows = iter(({}, ready, ready))
    commands: list[str] = []
    loop_count = 0

    class NoAbort:
        def __init__(self, _path: Path) -> None:
            pass

        def __enter__(self) -> "NoAbort":
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def poll(self) -> bool:
            return False

    def finish_after_setup(
        _health: dict[tuple[str, str], str],
        _now_epoch: float,
        _elapsed_monotonic_s: float,
    ) -> None:
        nonlocal loop_count
        loop_count += 1
        if loop_count == 3:
            supervisor.state["terminal"] = {
                "result": "healthy_stop",
                "reason": "deterministic_test_complete",
            }

    monkeypatch.setattr(frequency_control_supervisor, "AbortFifo", NoAbort)
    monkeypatch.setattr(frequency_control_supervisor.time, "sleep", lambda _: None)
    supervisor._command = commands.append  # type: ignore[method-assign]
    supervisor._check_capture_transport_state = lambda: {}  # type: ignore[method-assign]
    supervisor._renew_lease = lambda: None  # type: ignore[method-assign]
    supervisor._process_transactions = lambda: None  # type: ignore[method-assign]
    supervisor._current_health = lambda: next(health_rows)  # type: ignore[method-assign]
    supervisor._check_setup_transaction_timeout = (  # type: ignore[method-assign]
        lambda _health, _now: None
    )
    supervisor._check_prewrite_contract = (  # type: ignore[method-assign]
        lambda _health, _elapsed: None
    )
    supervisor._prewrite_readiness = (  # type: ignore[method-assign]
        lambda _health: SimpleNamespace(ready=True)
    )
    supervisor._maybe_qualify = lambda _health: None  # type: ignore[method-assign]
    supervisor._maybe_finish = finish_after_setup  # type: ignore[method-assign]

    assert supervisor.run() == 0

    setup_commands = [
        command for command in commands if command.startswith("ACTIVE SETUP ")
    ]
    assert len(setup_commands) == 1
    assert supervisor.state["d9_exact_readback_established"] is True
    snapshot_command = next(
        command for command in commands if command.startswith("ACTIVE SNAPSHOT ")
    )
    assert commands.index(setup_commands[0]) > commands.index(snapshot_command)


def test_pty_rehearsal_uses_real_capture_abort_and_rotation(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    report = endurance.pty_operational_rehearsal(
        bundle=bundle, output_dir=tmp_path / "rehearsal"
    )

    assert report["status"] == "passed"
    assert report["hardware_operations"] is False
    assert report["baud"] == 115200
    assert report["priority_abort_delivered"] is True
    assert report["rotation"]["serial_reopened"] is False
    assert report["application_admission_reserve_s"] == 1500
    assert report["long_analysis_horizon_keeps_control_admission_open"] is True
    assert report["opportunity_causal_ledger_exercised"] is True
    assert report["backlogged_configuration_startup_hold_exercised"] is True
    assert report["no_setup_before_d9_exact_readback_established"] is True
    assert report["setup_authority_false_holds_without_consuming_setup"] is True
    assert report["setup_issued_only_after_fresh_exact_authority_snapshot"] is True
    assert report["firmware_policy_identity_replayed_by_live_supervisor"] is True
    assert report["actual_frequency_only_exact_counter_arm_exercised"] is True

    replayed_rows = list(
        csv.DictReader(
            (
                tmp_path
                / "rehearsal/run/csv/tight_deadband_decisions_v1.csv"
            ).open(encoding="utf-8", newline="")
        )
    )
    assert replayed_rows[0]["policy_sha256"] == (
        endurance.load_no_write_qualification_spec("A")[1][
            "active_policy_sha256"
        ]
    )

    bundle_path = tmp_path / "bundle.json"
    preflight_path = tmp_path / "preflight.json"
    endurance._write_new(bundle_path, bundle)
    endurance._write_new(preflight_path, endurance.no_io_preflight(bundle))
    activation = endurance.activate_bundle(
        bundle_path=bundle_path,
        preflight_report_path=preflight_path,
        rehearsal_report_path=tmp_path / "rehearsal/reports/rehearsal.json",
        operator_authorization_ref="operator_thread_2026-08-28_bench_authority",
    )
    assert activation["effective"] is True


def test_live_manifest_uses_fresh_auto_detect_capture_and_current_epoch(tmp_path: Path) -> None:
    bundle, activation, activation_path = _activation(tmp_path)
    run_dir = tmp_path / "live"
    run_dir.mkdir()
    device, board, firmware_entry = _fixture_firmware_entry(
        run_dir=run_dir, activation=activation, bundle=bundle
    )

    manifest = endurance.create_live_manifest(
        run_dir=run_dir,
        activation_path=activation_path,
        activation=activation,
        resolved_device=device,
        board_identity=board,
        firmware_entry=firmware_entry,
    )
    command = endurance.live_capture_command(
        run_dir=run_dir,
        expected_device=device,
        duration_s=108000 + endurance.CAPTURE_EVIDENCE_DRAIN_MARGIN_S,
    )

    assert manifest["host"]["baud"] == 115200
    assert manifest["host"]["serial_selection"] == "fresh_auto_detect_each_enumeration"
    assert "--auto-detect" in command
    assert command[command.index("--expected-auto-detect-device") + 1] == device
    assert command[command.index("--duration-s") + 1] == "108180"
    assert "--device" not in command
    assert (
        manifest["frequency_only_engineering"]["activation_sha256"]
        == activation["activation_sha256"]
    )
    assert manifest["frequency_only_engineering"]["bundle_sha256"] == bundle[
        "bundle_sha256"
    ]
    expected_capture = endurance._exact_capture_contract()
    assert manifest["domains"] == expected_capture["domains"]
    assert manifest["contracts"] == expected_capture["contracts"]
    assert manifest["files"] == expected_capture["files"]
    assert manifest["firmware"]["fqbn"] == endurance.EXPECTED_UPLOAD_FQBN
    assert manifest["firmware"]["entry_record_sha256"] == firmware_entry[
        "record_sha256"
    ]
    assert manifest["finite_timing"] == {
        "authority_and_wall_terminal_s": 108000,
        "capture_duration_s": 108180,
        "post_terminal_evidence_drain_and_abort_margin_s": 180,
    }
    assert any(
        entry["contract"] == "active_transactions_v2"
        and "optional" not in entry
        for entry in manifest["files"]
    )
    assert any(
        entry["contract"] == "active_hybrid_decisions_v2"
        and entry["optional"] is True
        for entry in manifest["files"]
    )
    assert load_manifest(run_dir).stage == endurance.LIVE_STAGE


def test_single_upload_binds_fqbn_boards_and_hashes_without_retry(
    tmp_path: Path,
) -> None:
    bundle, activation, _ = _activation(tmp_path)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    devices = iter(("/dev/cu.before", "/dev/cu.after"))
    detected: list[str] = []
    uploads: list[list[str]] = []
    board = {
        "hardware_id": "board",
        "serial_number": "board",
        "vid": "0x2341",
        "pid": "0x005E",
        "product": "Nano",
        "board_name": "Nano RP2040",
        "board_fqbn": "rp2040:rp2040:arduino_nano_connect",
    }

    def detect() -> str:
        device = next(devices)
        detected.append(device)
        return device

    def upload(command: list[str], **_: object) -> SimpleNamespace:
        uploads.append(command)
        return SimpleNamespace(returncode=0, stdout="uploaded", stderr="")

    device, observed, record = endurance._execute_activation_authorized_upload(
        run_dir=run_dir,
        activation=activation,
        bundle=bundle,
        fresh_detect=detect,
        identity_reader=lambda current: {**board, "address": current},
        owner_reader=lambda _: set(),
        upload_runner=upload,
        sleep_fn=lambda _: None,
    )

    assert detected == ["/dev/cu.before", "/dev/cu.after"]
    assert len(uploads) == 1
    assert uploads[0][uploads[0].index("--fqbn") + 1] == (
        endurance.EXPECTED_UPLOAD_FQBN
    )
    assert uploads[0][uploads[0].index("--input-file") + 1] == bundle[
        "firmware"
    ]["uf2"]["path"]
    assert device == "/dev/cu.after"
    assert observed["address"] == device
    assert record["firmware_flash_count"] == 1
    assert record["automatic_retry_performed"] is False
    assert record["board_before_sha256"] == endurance.canonical_sha256(
        record["board_before"]
    )
    assert record["board_after_sha256"] == endurance.canonical_sha256(
        record["board_after"]
    )
    with pytest.raises(FileExistsError, match="upload is forbidden"):
        endurance._execute_activation_authorized_upload(
            run_dir=run_dir,
            activation=activation,
            bundle=bundle,
            fresh_detect=lambda: "/dev/cu.unused",
            identity_reader=lambda current: {**board, "address": current},
            owner_reader=lambda _: set(),
            upload_runner=upload,
        )
    assert len(uploads) == 1


def test_activation_upload_reservation_is_global_and_survives_process_death(
    tmp_path: Path,
) -> None:
    bundle, activation, _ = _activation(tmp_path)
    first_run = tmp_path / "first-run"
    second_run = tmp_path / "second-run"
    first_run.mkdir()
    second_run.mkdir()
    board = {
        "hardware_id": "board",
        "serial_number": "board",
        "vid": "0x2341",
        "pid": "0x005E",
        "product": "Nano",
        "board_name": "Nano RP2040",
        "board_fqbn": "rp2040:rp2040:arduino_nano_connect",
    }
    upload_count = 0

    def interrupted_upload(*_: object, **__: object) -> SimpleNamespace:
        nonlocal upload_count
        upload_count += 1
        reservation_path = endurance._activation_upload_attempt_path(activation)
        assert reservation_path.is_file()
        reservation = endurance._read(reservation_path)
        assert reservation["intended_run_dir"] == str(first_run.resolve())
        raise KeyboardInterrupt("simulated process death after upload began")

    with pytest.raises(KeyboardInterrupt, match="simulated process death"):
        endurance._execute_activation_authorized_upload(
            run_dir=first_run,
            activation=activation,
            bundle=bundle,
            fresh_detect=lambda: "/dev/cu.fixture",
            identity_reader=lambda current: {**board, "address": current},
            owner_reader=lambda _: set(),
            upload_runner=interrupted_upload,
        )

    with pytest.raises(FileExistsError, match="activation already has"):
        endurance._execute_activation_authorized_upload(
            run_dir=second_run,
            activation=activation,
            bundle=bundle,
            fresh_detect=lambda: "/dev/cu.must-not-be-used",
            identity_reader=lambda current: {**board, "address": current},
            owner_reader=lambda _: set(),
            upload_runner=interrupted_upload,
        )
    assert upload_count == 1
    assert not (first_run / endurance.FIRMWARE_ENTRY_PATH).exists()
    assert not (second_run / endurance.FIRMWARE_ENTRY_PATH).exists()


def test_run_live_uploads_before_capture_and_keeps_108000s_authority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, activation, activation_path = _activation(tmp_path)
    run_dir = tmp_path / "live-run"
    original_upload = endurance._execute_activation_authorized_upload
    upload_count = 0
    capture_command: list[str] = []
    capture_popen_kwargs: dict[str, object] = {}
    supervisor_duration: list[float] = []

    def upload_once(**kwargs: object):  # type: ignore[no-untyped-def]
        nonlocal upload_count
        upload_count += 1
        devices = iter(("/dev/cu.before", "/dev/cu.after"))
        board = {
            "hardware_id": "fixture-board",
            "serial_number": "fixture-board",
            "vid": "0x2341",
            "pid": "0x005E",
            "product": "fixture Nano RP2040",
            "board_name": "Arduino Nano RP2040 Connect",
            "board_fqbn": "rp2040:rp2040:arduino_nano_connect",
        }
        return original_upload(
            run_dir=kwargs["run_dir"],
            activation=kwargs["activation"],
            bundle=kwargs["bundle"],
            fresh_detect=lambda: next(devices),
            identity_reader=lambda device: {**board, "address": device},
            owner_reader=lambda _: set(),
            upload_runner=lambda *args, **kw: SimpleNamespace(
                returncode=0, stdout="fixture upload", stderr=""
            ),
            sleep_fn=lambda _: None,
            hardware_operations=True,
        )

    class Capture:
        pid = 1234
        returncode: int | None = None

        def poll(self) -> int | None:
            return self.returncode

    capture = Capture()

    class Supervisor:
        def __init__(self) -> None:
            self.state: dict[str, object] = {}

        def run(self) -> int:
            self.state["terminal"] = {
                "result": "healthy_stop",
                "reason": "frequency_only_d9_d6_digital_endurance_passed",
            }
            return 0

        def _event(self, *args: object, **kwargs: object) -> None:
            pass

        def _abort(self, reason: str) -> None:
            raise AssertionError(reason)

        def _save(self) -> None:
            pass

    def create_supervisor(**kwargs: object) -> Supervisor:
        supervisor_duration.append(float(kwargs["duration_s"]))
        return Supervisor()

    def popen(command: list[str], **kwargs: object) -> Capture:
        capture_command.extend(command)
        capture_popen_kwargs.update(kwargs)
        return capture

    def stop_capture(current: Capture) -> None:
        current.returncode = 0
        manifest_sha256 = endurance.sha256(
            (run_dir / "run_manifest.json").read_bytes()
        ).hexdigest()
        endurance._write_new(
            run_dir / "reports/capture_segment_closure_v1.json",
            {
                "run_manifest_sha256": manifest_sha256,
                "device": "/dev/cu.after",
                "baud": 115200,
                "logical_segment_closed": True,
                "physical_serial_open": False,
                "closure_mode": "physical_serial_close",
                "serial_reopened": False,
            },
        )
        endurance._write_new(
            run_dir / "reports/capture_device_state.json",
            {
                "capture_active": False,
                "serial_open": False,
                "logical_segment_closed": True,
                "physical_serial_open": False,
            },
        )

    monkeypatch.setattr(endurance, "_execute_activation_authorized_upload", upload_once)
    monkeypatch.setattr(endurance, "create_live_supervisor", create_supervisor)
    monkeypatch.setattr(endurance.subprocess, "Popen", popen)
    monkeypatch.setattr(endurance, "_wait_for_capture_ready", lambda *args: None)
    monkeypatch.setattr(endurance, "_serial_owner_pids", lambda _: {capture.pid})
    monkeypatch.setattr(endurance, "_stop_capture", stop_capture)

    result = endurance.run_live(activation_path=activation_path, run_dir=run_dir)

    assert original_upload is not endurance._execute_activation_authorized_upload
    assert upload_count == 1
    assert capture_command[capture_command.index("--duration-s") + 1] == "108180"
    assert "--auto-detect" in capture_command
    assert "--device" not in capture_command
    assert capture_popen_kwargs["start_new_session"] is True
    assert supervisor_duration == [108000.0]
    assert result["capture_returncode"] == 0
    assert result["firmware_flash_count"] == 1
    assert result["capture_duration_s"] == 108180
    assert result["authority_and_wall_terminal_s"] == 108000


def test_canonical_qualified_interval_joins_d14_ref_snp_and_d8_cnt(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    run_dir = tmp_path / "run"
    (run_dir / "csv").mkdir(parents=True)
    endurance._write_csv_rows(
        run_dir / endurance.ACTIVE_CSV,
        endurance.ACTIVE_TRANSACTION_V1_FIELDS,
        [endurance._rehearsal_transaction_rows(bundle)[0]],
    )
    endurance._write_csv_rows(
        run_dir / "csv/raw_events.csv",
        ["record_type", "schema_version", "event_seq", "channel_id", "edge", "timestamp_ticks", "capture_domain", "flags"],
        [
            {"record_type": "REF", "schema_version": "1", "event_seq": "1", "channel_id": "1", "edge": "R", "timestamp_ticks": "100", "capture_domain": "rp2040_timer0", "flags": "0"},
            {"record_type": "REF", "schema_version": "1", "event_seq": "2", "channel_id": "1", "edge": "R", "timestamp_ticks": str(100 + endurance.TIMER_HZ), "capture_domain": "rp2040_timer0", "flags": "0"},
        ],
    )
    endurance._write_csv_rows(
        run_dir / "csv/pps_snapshots.csv",
        ["record_type", "schema_version", "session", "snapshot_sequence", "cumulative_down_counter", "reference_sequence", "reference_timestamp_ticks", "status", "backend"],
        [
            {"record_type": "SNP", "schema_version": "1", "session": "7", "snapshot_sequence": "0", "cumulative_down_counter": "20000000", "reference_sequence": "10", "reference_timestamp_ticks": "100", "status": "0", "backend": "pio_wait_cumulative_snapshot_dma_v1"},
            {"record_type": "SNP", "schema_version": "1", "session": "7", "snapshot_sequence": "1", "cumulative_down_counter": "10000000", "reference_sequence": "11", "reference_timestamp_ticks": str(100 + endurance.TIMER_HZ), "status": "0", "backend": "pio_wait_cumulative_snapshot_dma_v1"},
        ],
    )
    endurance._write_csv_rows(
        run_dir / "csv/count_observations.csv",
        ["record_type", "schema_version", "count_seq", "channel_id", "gate_open_ticks", "gate_close_ticks", "gate_domain", "counted_edges", "source_edge", "source_domain", "flags"],
        [{"record_type": "CNT", "schema_version": "1", "count_seq": "1", "channel_id": "2", "gate_open_ticks": "100", "gate_close_ticks": str(100 + endurance.TIMER_HZ), "gate_domain": "rp2040_timer0", "counted_edges": "10000000", "source_edge": "R", "source_domain": "h1_cx317_ocxo_10mhz", "flags": "0"}],
    )
    rows = endurance.canonical_d14_d8_intervals(run_dir)
    assert len(rows) == 1
    assert rows[0]["measurement_qualified"] is True
    assert rows[0]["session"] == 7
    assert rows[0]["dac_epoch"] == 1
    assert rows[0]["applied_code"] == 0xA808
    assert rows[0]["frequency_error_hz"] == pytest.approx(0.0)

    counts = run_dir / "csv/count_observations.csv"
    text = counts.read_text(encoding="utf-8").replace(",0\n", ",1\n")
    counts.write_text(text, encoding="utf-8")
    assert endurance.canonical_d14_d8_intervals(run_dir)[0]["measurement_qualified"] is False


def test_canonical_interval_reads_commit_frontier_before_supporting_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reads: list[str] = []

    def read_rows(path: Path) -> list[dict[str, str]]:
        reads.append(path.name)
        return []

    monkeypatch.setattr(endurance, "_read_csv_rows", read_rows)

    assert endurance.canonical_d14_d8_intervals(tmp_path) == []
    assert reads == [
        endurance.COUNT_OBSERVATIONS_CSV,
        endurance.PPS_SNAPSHOTS_CSV,
        endurance.RAW_EVENTS_CSV,
        endurance.ACTIVE_CSV.name,
    ]


def test_shared_frequency_control_path_uses_a808_setup_then_arm(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    run_dir = tmp_path / "shared"
    (run_dir / "csv").mkdir(parents=True)
    supervisor = endurance.create_live_supervisor(run_dir=run_dir, bundle=bundle)
    commands: list[str] = []
    supervisor._command = commands.append  # type: ignore[method-assign]
    supervisor._prewrite_readiness = lambda _health: SimpleNamespace(ready=True)  # type: ignore[method-assign]
    health = {
        ("cx317_active", "run_identity"): supervisor.spec.run_identity,
        ("cx317_active", "build_identity"): supervisor.expected_build_identity,
        ("cx317_active", "profile_identity"): supervisor.spec.profile,
        ("cx317_active", "session_id"): "4",
        ("cx317_active", "state"): "DISARMED",
        ("cx317_active", "reason"): "initialized_disarmed",
        ("cx317_active", "manual_start_confirmed"): "false",
        ("cx317_active", "snapshot_generation_complete"): "7",
        ("cx317_active", "query_nonce"): str(supervisor.state["host_attach_query_nonce"]),
        ("cx317_active", "uptime_s"): "1000",
    }
    for key, value in supervisor.identities.items():
        health[("cx317_active", key)] = value

    supervisor._maybe_start_or_arm(health)
    assert commands == []

    supervisor.state["d9_exact_readback_established"] = True
    supervisor._maybe_start_or_arm(health)

    assert supervisor.spec.start_code == 0xA808
    assert commands[0].startswith("ACTIVE SETUP 1 7 ")
    assert " 4 0xA808 1 " in commands[0]
    assert (run_dir / "reports/setup_authority_input_v1.json").is_file()


def test_nonbinding_ceiling_alone_does_not_mark_endpoint_incomplete() -> None:
    accounting = endurance.EnduranceSupervisor(endurance.load_contract())
    accounting.record_fll_transaction(
        setup_establishment=True,
        requested_delta_codes=0,
        application_ticks=0,
        phase_or_hybrid=False,
    )
    for ordinal in range(48):
        accounting.record_fll_transaction(
            setup_establishment=False,
            requested_delta_codes=21,
            application_ticks=(ordinal + 1) * 1800 * endurance.TIMER_HZ,
            phase_or_hybrid=False,
            decision_sequence=ordinal + 1,
        )
    assert accounting.automatic_applications == 48
    assert accounting.cumulative_movement_codes == 1008
    assert accounting.authority_ceiling_exhausted is True
    assert accounting.authority_ceiling_decision_sequence == 48
    assert accounting.endpoint_incomplete_reason is None
    assert accounting.terminal is None

    accounting.record_fll_transaction(
        setup_establishment=False,
        requested_delta_codes=1,
        application_ticks=49 * 1800 * endurance.TIMER_HZ,
        phase_or_hybrid=False,
    )
    assert accounting.terminal == "frequency_only_d9_d6_controller_or_transaction_fault"


def test_later_eligible_opportunity_inside_open_admission_marks_ceiling_incomplete(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "ceiling-opportunity"
    supervisor = endurance.create_live_supervisor(
        run_dir=run_dir, bundle=_bundle(tmp_path)
    )
    supervisor.accounting.authority_ceiling_exhausted = True
    supervisor.accounting.authority_ceiling_decision_sequence = 48
    endurance._write_csv_rows(
        run_dir / "csv" / endurance.CONTROL_PREVIEWS_CSV,
        CONTROL_FIELDS,
        [_control_row(49, limited_delta=1, reason="actionable", eligible=False)],
    )

    supervisor._update_lost_opportunities({})

    assert supervisor.state["lost_opportunity_dispositions"] == {
        "authority_ceiling_closed": 1
    }
    assert supervisor.state["eligible_control_opportunity_count"] == 1
    assert supervisor.accounting.endpoint_incomplete_reason == (
        "eligible_opportunity_suppressed_by_authority_ceiling"
    )


def test_ceiling_at_final_admissible_opportunity_does_not_create_incomplete(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "ceiling-at-reserve"
    supervisor = endurance.create_live_supervisor(
        run_dir=run_dir, bundle=_bundle(tmp_path)
    )
    supervisor.accounting.authority_ceiling_exhausted = True
    supervisor.accounting.authority_ceiling_decision_sequence = 48
    supervisor.state["exact_response_admission_closed_utc"] = (
        "2026-08-28T00:00:00Z"
    )
    endurance._write_csv_rows(
        run_dir / "csv" / endurance.CONTROL_PREVIEWS_CSV,
        CONTROL_FIELDS,
        [_control_row(49, limited_delta=1, reason="actionable", eligible=True)],
    )

    supervisor._update_lost_opportunities({})

    assert supervisor.state["lost_opportunity_dispositions"] == {
        "exact_response_admission_closed": 1
    }
    assert supervisor.accounting.endpoint_incomplete_reason is None


def test_control_admission_closes_only_for_exact_1500s_response(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor = endurance.create_live_supervisor(
        run_dir=tmp_path / "admission", bundle=_bundle(tmp_path)
    )
    supervisor.accounting.armed_ticks = 1
    supervisor.state["d9_exact_readback_established"] = True
    calls: list[dict[tuple[str, str], str]] = []
    monkeypatch.setattr(
        endurance.FrequencyControlSupervisor,
        "_maybe_start_or_arm",
        lambda _self, health: calls.append(health),
    )
    target = 86400 * endurance.TIMER_HZ
    health: dict[tuple[str, str], str] = {}

    supervisor.accounting.qualified_ticks = target - 21600 * endurance.TIMER_HZ
    supervisor._maybe_start_or_arm(health)
    assert calls == [health]
    assert supervisor.state.get("exact_response_admission_closed_utc") is None

    supervisor.accounting.qualified_ticks = target - 1500 * endurance.TIMER_HZ
    supervisor._maybe_start_or_arm(health)
    assert calls == [health]
    assert supervisor.state["exact_response_admission_closed_utc"] is not None


def test_actual_supervisor_restores_counter_ledger_and_observes_repeated_responses(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    run_dir = tmp_path / "restart"
    (run_dir / "csv").mkdir(parents=True)
    rows = endurance._rehearsal_transaction_rows(bundle)
    endurance._write_csv_rows(
        run_dir / endurance.ACTIVE_CSV,
        endurance.ACTIVE_TRANSACTION_V1_FIELDS,
        rows,
    )
    endurance._write_csv_rows(
        run_dir / "csv" / endurance.ACTIVE_TRANSACTIONS_V2_CSV,
        endurance.ACTIVE_TRANSACTION_V2_FIELDS,
        endurance._rehearsal_transaction_timing_rows(rows),
    )
    first = endurance.create_live_supervisor(run_dir=run_dir, bundle=bundle)
    first.state["acknowledged_record_sequences"] = list(range(2, len(rows) + 1))
    first.state["observed_manual_record_sequences"] = [1]
    first.accounting.armed_ticks = 100
    first.accounting.qualified_ticks = 123 * endurance.TIMER_HZ
    first.accounting.last_closing_ticks = 100 + 123 * endurance.TIMER_HZ
    first.accounting.last_count_sequence = 123
    first._persist_accounting()
    first._process_transactions()
    assert first.state["response_count"] == 2
    exact_application_ticks = endurance._exact_application_ticks(
        run_dir=run_dir, transactions=rows
    )
    assert first.accounting.last_application_ticks == exact_application_ticks[-1]
    assert first.state["terminal"] is None
    assert first.observational_responses is True

    restarted = endurance.create_live_supervisor(run_dir=run_dir, bundle=bundle)
    assert restarted.accounting.armed_ticks == 100
    assert restarted.accounting.qualified_ticks == 123 * endurance.TIMER_HZ
    assert restarted.accounting.last_count_sequence == 123
    assert restarted.accounting.last_application_ticks == exact_application_ticks[-1]
    assert restarted.state["response_count"] == 2


def test_restart_recovers_counter_checkpoint_if_json_state_lags_ledger(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "ledger-restart"
    supervisor = endurance.create_live_supervisor(
        run_dir=run_dir, bundle=_bundle(tmp_path)
    )
    supervisor.accounting.arm(
        frontier_ticks=100,
        d9_state="configured_10mhz_forwarded_unqualified",
        d9_readback_exact=True,
        d14_d8_healthy=True,
        outstanding_transaction=False,
        applied_code=0xA808,
        dac_epoch=1,
    )
    supervisor.accounting.observe_interval(
        opening_ticks=100,
        closing_ticks=100 + endurance.TIMER_HZ,
        measurement_qualified=True,
        d9_valid=True,
        count_sequence=1,
    )
    checkpoint = endurance._counter_checkpoint(supervisor.accounting)
    checkpoint["processed_count_sequence"] = 1
    ledger = run_dir / endurance.QUALIFIED_INTERVAL_LEDGER_PATH
    ledger.parent.mkdir(parents=True, exist_ok=True)
    ledger.write_text(
        json.dumps(
            {
                "count_sequence": 1,
                "measurement_qualified": True,
                "d9_digital_readback_exact": True,
                "counter_accounting_after": checkpoint,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    stale = endurance._read(run_dir / endurance.SUPERVISOR_STATE_PATH)
    stale.update(
        {
            "armed_ticks": 100,
            "qualified_ticks": 0,
            "elapsed_ticks": 0,
            "last_closing_ticks": None,
            "last_qualified_count_sequence": None,
        }
    )
    endurance._write_replace(run_dir / endurance.SUPERVISOR_STATE_PATH, stale)

    restarted = endurance.create_live_supervisor(
        run_dir=run_dir, bundle=_bundle(tmp_path)
    )

    assert restarted.accounting.qualified_ticks == endurance.TIMER_HZ
    assert restarted.accounting.last_count_sequence == 1
    assert restarted.consumed_count_sequences == {1}


def test_opportunity_ledger_is_restart_safe_and_zero_application_is_accounted(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "opportunities"
    supervisor = endurance.create_live_supervisor(
        run_dir=run_dir, bundle=_bundle(tmp_path)
    )
    endurance._write_csv_rows(
        run_dir / "csv" / endurance.CONTROL_PREVIEWS_CSV,
        CONTROL_FIELDS,
        [
            _control_row(10),
            _control_row(11, reason="decision_cadence_hold"),
            _control_row(12, limited_delta=1, reason="estimate_unavailable"),
        ],
    )

    supervisor._update_lost_opportunities({})

    assert supervisor.state["control_opportunity_count"] == 3
    assert supervisor.state["pending_control_opportunity_sequences"] == []
    assert supervisor.state["lost_opportunity_dispositions"] == {
        "cadence_hold": 1,
        "ineligible_not_authorized": 1,
        "no_demand": 1,
    }
    assert supervisor._opportunity_accounting_complete() == (True, None)

    restarted = endurance.create_live_supervisor(
        run_dir=run_dir, bundle=_bundle(tmp_path)
    )
    restarted._update_lost_opportunities({})
    events, opportunities = endurance._read_opportunity_causal_ledger(
        run_dir / endurance.OPPORTUNITY_CAUSAL_LEDGER_PATH
    )
    assert len(events) == 3
    assert set(opportunities) == {10, 11, 12}


def test_late_exact_application_reclassifies_preview_only_opportunity_once(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "late-application"
    supervisor = endurance.create_live_supervisor(
        run_dir=run_dir, bundle=_bundle(tmp_path)
    )
    endurance._write_csv_rows(
        run_dir / "csv" / endurance.CONTROL_PREVIEWS_CSV,
        CONTROL_FIELDS,
        [_control_row(10, limited_delta=21, reason="actionable")],
    )

    supervisor._update_lost_opportunities({})
    assert supervisor.state["lost_opportunity_dispositions"] == {
        "ineligible_not_authorized": 1
    }

    application = {
        field: "" for field in endurance.ACTIVE_TRANSACTION_V1_FIELDS
    }
    application.update(
        {
            "transaction_record_sequence": "4",
            "event": "application",
            "decision_sequence": "10",
        }
    )
    endurance._write_csv_rows(
        run_dir / endurance.ACTIVE_CSV,
        endurance.ACTIVE_TRANSACTION_V1_FIELDS,
        [application],
    )
    supervisor._update_lost_opportunities({})

    events, opportunities = endurance._read_opportunity_causal_ledger(
        run_dir / endurance.OPPORTUNITY_CAUSAL_LEDGER_PATH
    )
    assert [event["event"] for event in events] == [
        "opportunity_observed",
        "opportunity_reclassified",
    ]
    assert opportunities[10]["eligible_control_opportunity"] is True
    assert opportunities[10]["disposition"] == "applied"
    assert opportunities[10]["resolution_transaction_record_sequence"] == 4

    restarted = endurance.create_live_supervisor(
        run_dir=run_dir, bundle=_bundle(tmp_path)
    )
    restarted._update_lost_opportunities({})
    events_after_restart, _ = endurance._read_opportunity_causal_ledger(
        run_dir / endurance.OPPORTUNITY_CAUSAL_LEDGER_PATH
    )
    assert events_after_restart == events


@pytest.mark.parametrize("sequences", ([1, 3], [1, 1]))
def test_opportunity_ledger_rejects_missing_or_duplicate_control_sequences(
    tmp_path: Path, sequences: list[int]
) -> None:
    run_dir = tmp_path / ("opportunity-sequence-" + "-".join(map(str, sequences)))
    supervisor = endurance.create_live_supervisor(
        run_dir=run_dir, bundle=_bundle(tmp_path)
    )
    endurance._write_csv_rows(
        run_dir / "csv" / endurance.CONTROL_PREVIEWS_CSV,
        CONTROL_FIELDS,
        [_control_row(sequence) for sequence in sequences],
    )

    with pytest.raises(ValueError, match="missing|duplicate"):
        supervisor._update_lost_opportunities({})


def test_zero_application_is_not_valid_when_opportunities_are_absent_or_pending(
    tmp_path: Path,
) -> None:
    run_dir = tmp_path / "opportunity-pending"
    supervisor = endurance.create_live_supervisor(
        run_dir=run_dir, bundle=_bundle(tmp_path)
    )
    assert supervisor._opportunity_accounting_complete() == (
        False,
        "control_opportunity_evidence_absent",
    )
    endurance._write_csv_rows(
        run_dir / "csv" / endurance.CONTROL_PREVIEWS_CSV,
        CONTROL_FIELDS,
        [_control_row(1, limited_delta=1, reason="actionable", eligible=True)],
    )
    supervisor._update_lost_opportunities({})
    assert supervisor._opportunity_accounting_complete() == (
        False,
        "control_opportunity_disposition_incomplete",
    )


@pytest.mark.parametrize(
    "withdrawal_reason",
    (
        "gnss_metadata_private_request_withdrawn",
        "gnss_metadata_core0_rejection_discarded",
    ),
)
def test_gnss_withdrawal_resolves_exact_opportunity_with_lifecycle_evidence(
    tmp_path: Path, withdrawal_reason: str
) -> None:
    run_dir = tmp_path / withdrawal_reason
    supervisor = endurance.create_live_supervisor(
        run_dir=run_dir, bundle=_bundle(tmp_path)
    )
    endurance._write_csv_rows(
        run_dir / "csv" / endurance.CONTROL_PREVIEWS_CSV,
        CONTROL_FIELDS,
        [_control_row(10, limited_delta=1, reason="actionable", eligible=True)],
    )
    transaction = {
        field: "" for field in endurance.ACTIVE_TRANSACTION_V1_FIELDS
    }
    transaction.update(
        {
            "transaction_record_sequence": "3",
            "event": "request_withdrawn",
            "decision_sequence": "10",
            "reason": withdrawal_reason,
        }
    )
    endurance._write_csv_rows(
        run_dir / endurance.ACTIVE_CSV,
        endurance.ACTIVE_TRANSACTION_V1_FIELDS,
        [transaction],
    )

    supervisor._update_lost_opportunities({})

    assert supervisor.state["lost_opportunity_dispositions"] == {
        "gnss_metadata_hold": 1
    }
    _, retained = endurance._read_opportunity_causal_ledger(
        run_dir / endurance.OPPORTUNITY_CAUSAL_LEDGER_PATH
    )
    assert retained[10]["resolution_transaction_record_sequence"] == 3
    assert retained[10]["resolution_reason"] == withdrawal_reason
    assert retained[10]["resolution_evidence"].endswith(withdrawal_reason)


def test_gnss_metadata_hold_oracle_is_measurement_preserving_and_non_effective() -> None:
    fact = endurance.gnss_metadata_hold_oracle_fact(
        capture_session="fixture",
        frontier=600,
        applied_code=0xA808,
        dac_epoch=1,
    )
    assert fact["mode"] == "GNSS_METADATA_HOLD"
    assert fact["measurement_continues"] is True
    assert fact["effective_actuation_permitted"] is False
    assert fact["control_rearm_eligible"] is False
    assert fact["last_confirmed_code"] == 0xA808


def test_analyzer_reconstructs_stationary_frequency_and_drift_metrics(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    run_dir = tmp_path / "analysis"
    _write_analyzer_fixture(run_dir, bundle)

    result = endurance.analyze_run(run_dir)

    assert result["fll_window_fitness"]["qualified_window_count"] == 2
    assert result["d14_relative_frequency_error_hz"]["count"] == 2
    assert result["stationary_dac_epoch_vcocxo_drift"][0]["drift"][
        "sample_count"
    ] == 2
    assert set(result["frequency_horizons_s"]) == {
        "600",
        "1500",
        "3600",
        "7200",
        "21600",
    }
    assert result["chatter"]["application_count"] == 0
    assert result["d6_diagnostic_only"]["control_authority"] is False
    comparison = result["fll_window_fitness"]["candidate_window_comparison"]
    assert comparison["runtime_authority_changed"] is False
    assert set(comparison["candidates"]) == {
        "60",
        "120",
        "300",
        "600",
        "1200",
        "1800",
    }
    assert result["exact_transaction_timing"] == {
        "time_domain": endurance.EXACT_LIFECYCLE_TIME_DOMAIN,
        "ACT1_rows": 1,
        "AT2_rows": 1,
        "one_to_one_exact": True,
        "coarse_seconds_used_as_ticks": False,
        "first_event_timestamp_ticks": 100,
        "last_event_timestamp_ticks": 100,
    }
    assert result["lifecycle_provenance"]["capture_returncode"] == 0
    assert result["lifecycle_provenance"]["capture_duration_s"] == 108180
    assert result["lifecycle_provenance"]["authority_and_wall_terminal_s"] == 108000
    assert result["lifecycle_provenance"]["fqbn"] == (
        endurance.EXPECTED_UPLOAD_FQBN
    )
    assert result["physical_waveform_qualification"] is False


def test_candidate_fll_windows_use_exact_stationary_rational_support() -> None:
    intervals: list[dict[str, object]] = []
    for sequence in range(1, 3601):
        sixty_second_block = (sequence - 1) // 60
        edge_offset = 1 if sixty_second_block % 2 == 0 else -1
        intervals.append(
            {
                "count_sequence": sequence,
                "session": 7,
                "dac_epoch": 4,
                "applied_code": 0xA808,
                "counted_edges": 10_000_000 + edge_offset,
                "duration_ticks": endurance.TIMER_HZ,
                "measurement_qualified": True,
                "settling_complete": True,
            }
        )

    result = endurance._candidate_fll_window_fitness(intervals)
    candidates = result["candidates"]

    first_60 = candidates["60"]["windows"][0]
    assert first_60["summed_counted_edges"] == 60 * 10_000_001
    assert first_60["summed_duration_ticks"] == 60 * endurance.TIMER_HZ
    assert first_60["frequency_error_hz"] == {
        "numerator": 1,
        "denominator": 1,
        "display_value": 1.0,
    }
    assert candidates["600"]["quantization"][
        "worst_case_one_edge_resolution_hz"
    ] == {
        "numerator": 1,
        "denominator": 600,
        "display_value": pytest.approx(1 / 600),
    }
    assert candidates["600"]["latency"]["boxcar_group_delay_s"] == {
        "numerator": 300,
        "denominator": 1,
        "display_value": 300.0,
    }
    assert candidates["60"]["assessment"] == "too_short"
    assert candidates["600"]["assessment"] == "appropriate"
    assert candidates["1200"]["assessment"] == "too_long"
    assert candidates["1800"]["assessment"] == "too_long"
    assert candidates["60"]["drift_support"]
    assert result["observational_only"] is True
    assert result["runtime_authority_changed"] is False


def test_candidate_fll_frequency_uses_d14_not_rp2040_timer_as_reference() -> None:
    intervals = [
        {
            "count_sequence": sequence,
            "session": 7,
            "dac_epoch": 4,
            "applied_code": 0xA808,
            "counted_edges": 9_999_998,
            "duration_ticks": endurance.TIMER_HZ - 80,
            "measurement_qualified": True,
            "settling_complete": True,
        }
        for sequence in range(1, 601)
    ]

    result = endurance._candidate_fll_window_fitness(intervals)
    candidate = result["candidates"]["600"]

    assert candidate["windows"][0]["frequency_error_hz"] == {
        "numerator": -2,
        "denominator": 1,
        "display_value": -2.0,
    }
    assert candidate["windows"][0]["summed_duration_ticks"] == 600 * (
        endurance.TIMER_HZ - 80
    )
    assert candidate["windows"][0]["frequency_reference_domain"] == (
        "D14_reference_intervals"
    )
    assert result["aperture_diagnostic_domain"] == "rp2040_timer0"


def test_candidate_fll_windows_never_straddle_session_code_or_epoch() -> None:
    intervals = [
        {
            "count_sequence": sequence,
            "session": 1 if sequence <= 60 else 2,
            "dac_epoch": 1,
            "applied_code": 0xA808,
            "counted_edges": 10_000_000,
            "duration_ticks": endurance.TIMER_HZ,
            "measurement_qualified": True,
            "settling_complete": True,
        }
        for sequence in range(1, 121)
    ]

    candidates = endurance._candidate_fll_window_fitness(intervals)["candidates"]

    assert candidates["60"]["complete_stationary_window_count"] == 2
    assert candidates["120"]["complete_stationary_window_count"] == 0
    assert candidates["120"]["assessment"] == "insufficient_evidence"


def test_analyzer_refuses_unreconciled_at2_before_seal(tmp_path: Path) -> None:
    bundle = _bundle(tmp_path)
    run_dir = tmp_path / "analysis"
    _write_analyzer_fixture(run_dir, bundle)
    timings = endurance._read_csv_rows(run_dir / "csv/active_transactions_v2.csv")
    timings[0]["reason"] = "different_reason"
    endurance._write_csv_rows(
        run_dir / "csv/active_transactions_v2.csv",
        endurance.ACTIVE_TRANSACTION_V2_FIELDS,
        timings,
    )

    with pytest.raises(ValueError, match="ACT1/AT2 exact timing reconciliation"):
        endurance.analyze_run(run_dir)
    with pytest.raises(ValueError, match="ACT1/AT2 exact timing reconciliation"):
        endurance.seal_and_register(
            run_dir=run_dir,
            index_path=tmp_path / "evidence_index.jsonl",
        )

    assert not (run_dir / endurance.ANALYSIS_PATH).exists()
    assert not (run_dir / endurance.SEAL_PATH).exists()
    assert not (run_dir / "COMPLETE").exists()


def test_exact_at2_cadence_rejects_subminimum_ticks_despite_1800s_act1(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    transactions = endurance._rehearsal_transaction_rows(bundle)
    timings = endurance._rehearsal_transaction_timing_rows(transactions)
    application_timings = [row for row in timings if row["event"] == "application"]
    application_timings[1]["event_timestamp_ticks"] = str(
        int(application_timings[0]["event_timestamp_ticks"])
        + 1800 * endurance.TIMER_HZ
        - 1
    )

    live_dir = tmp_path / "live-cadence"
    endurance._write_csv_rows(
        live_dir / endurance.ACTIVE_CSV,
        endurance.ACTIVE_TRANSACTION_V1_FIELDS,
        transactions,
    )
    endurance._write_csv_rows(
        live_dir / "csv" / endurance.ACTIVE_TRANSACTIONS_V2_CSV,
        endurance.ACTIVE_TRANSACTION_V2_FIELDS,
        timings,
    )
    supervisor = endurance.create_live_supervisor(
        run_dir=live_dir, bundle=bundle
    )
    supervisor.state["acknowledged_record_sequences"] = list(
        range(2, len(transactions) + 1)
    )
    supervisor.state["observed_manual_record_sequences"] = [1]
    supervisor._save()
    with pytest.raises(ValueError, match="exact AT2 application cadence"):
        supervisor._process_transactions()

    analysis_dir = tmp_path / "analysis-cadence"
    _write_analyzer_fixture(analysis_dir, bundle)
    endurance._write_csv_rows(
        analysis_dir / endurance.ACTIVE_CSV,
        endurance.ACTIVE_TRANSACTION_V1_FIELDS,
        transactions,
    )
    endurance._write_csv_rows(
        analysis_dir / "csv" / endurance.ACTIVE_TRANSACTIONS_V2_CSV,
        endurance.ACTIVE_TRANSACTION_V2_FIELDS,
        timings,
    )
    state = endurance._read(analysis_dir / endurance.SUPERVISOR_STATE_PATH)
    state.update(
        {
            "automatic_applications": 2,
            "response_count": 2,
            "control_opportunity_count": 2,
            "eligible_control_opportunity_count": 2,
            "pending_control_opportunity_sequences": [],
            "lost_opportunity_dispositions": {"applied": 2},
        }
    )
    endurance._write_replace(
        analysis_dir / endurance.SUPERVISOR_STATE_PATH, state
    )
    with pytest.raises(ValueError, match="exact AT2 application cadence"):
        endurance.analyze_run(analysis_dir)


def test_analyzer_reports_gnss_lifecycle_opportunity_disposition(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    run_dir = tmp_path / "analysis-gnss-opportunity"
    _write_analyzer_fixture(run_dir, bundle)
    state = endurance._read(run_dir / endurance.SUPERVISOR_STATE_PATH)
    state["eligible_control_opportunity_count"] = 1
    state["lost_opportunity_dispositions"] = {"gnss_metadata_hold": 1}
    endurance._write_replace(run_dir / endurance.SUPERVISOR_STATE_PATH, state)

    result = endurance.analyze_run(run_dir)

    assert result["lost_opportunities"]["dispositions"] == {
        "gnss_metadata_hold": 1
    }
    assert result["lost_opportunities"][
        "every_eligible_opportunity_has_exact_disposition"
    ] is True


def test_analyzer_refuses_manifest_without_exact_timing_inventory(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    run_dir = tmp_path / "analysis"
    _write_analyzer_fixture(run_dir, bundle)
    manifest = endurance._read(run_dir / "run_manifest.json")
    manifest["contracts"]["active_transactions_v2"] = 1
    endurance._write_replace(run_dir / "run_manifest.json", manifest)

    with pytest.raises(ValueError, match="exact capture declaration differs"):
        endurance.analyze_run(run_dir)


def test_analyzer_refuses_manifest_divergence_after_capture_closure(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    run_dir = tmp_path / "analysis"
    _write_analyzer_fixture(run_dir, bundle)
    manifest = endurance._read(run_dir / "run_manifest.json")
    manifest["known_limitations"].append("post-capture mutation")
    endurance._write_replace(run_dir / "run_manifest.json", manifest)

    with pytest.raises(ValueError, match="capture closure differs"):
        endurance.analyze_run(run_dir)


def test_analyzer_refuses_nonzero_capture_return_with_rehashed_lifecycle(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    run_dir = tmp_path / "analysis"
    _write_analyzer_fixture(run_dir, bundle)
    lifecycle = endurance._read(run_dir / endurance.RUN_LIFECYCLE_PATH)
    lifecycle["capture_returncode"] = 1
    lifecycle["status"] = "capture_close_failed"
    unsigned = {
        key: value for key, value in lifecycle.items() if key != "record_sha256"
    }
    lifecycle["record_sha256"] = endurance.canonical_sha256(unsigned)
    endurance._write_replace(run_dir / endurance.RUN_LIFECYCLE_PATH, lifecycle)

    with pytest.raises(ValueError, match="run lifecycle or capture return differs"):
        endurance.seal_and_register(
            run_dir=run_dir, index_path=tmp_path / "evidence_index.jsonl"
        )
    assert not (run_dir / endurance.SEAL_PATH).exists()
    assert not (run_dir / "COMPLETE").exists()


def test_analyzer_revalidates_retained_build_manifest_identity(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    run_dir = tmp_path / "analysis"
    _write_analyzer_fixture(run_dir, bundle)
    retained = endurance._read(run_dir / "inputs/firmware_build_manifest.json")
    retained["provenance"]["configuration"]["profile_id"] = "different"
    endurance._write_replace(
        run_dir / "inputs/firmware_build_manifest.json", retained
    )

    with pytest.raises(ValueError, match="retained firmware build manifest differs"):
        endurance.analyze_run(run_dir)


def test_analyzer_revalidates_immutable_global_upload_attempt(
    tmp_path: Path,
) -> None:
    bundle = _bundle(tmp_path)
    run_dir = tmp_path / "analysis"
    _write_analyzer_fixture(run_dir, bundle)
    retained_path = run_dir / endurance.RETAINED_UPLOAD_ATTEMPT_PATH
    retained = endurance._read(retained_path)
    retained["intended_run_dir"] = str(tmp_path / "different-run")
    unsigned = {
        key: value for key, value in retained.items() if key != "record_sha256"
    }
    retained["record_sha256"] = endurance.canonical_sha256(unsigned)
    endurance._write_replace(retained_path, retained)

    with pytest.raises(
        ValueError, match="retained firmware-upload attempt reservation differs"
    ):
        endurance.analyze_run(run_dir)


def test_response_analysis_right_censors_long_horizons_at_next_application(
    tmp_path: Path,
) -> None:
    transactions = endurance._rehearsal_transaction_rows(_bundle(tmp_path))
    first_application = next(
        row for row in transactions if row["event"] == "application"
    )
    epoch = int(first_application["dac_epoch"])
    code = int(first_application["applied_code"])
    windows = [
        {
            "window_qualified": True,
            "dac_epoch": epoch,
            "applied_code": code,
            "source_count_sequence": 2400,
            "frequency_error_hz": -0.05,
        }
    ]

    result = endurance._response_and_horizon_metrics(transactions, windows)
    first = result["per_application"][0]
    facts = {item["horizon_s"]: item for item in first["horizons"]}
    assert facts[600]["available"] is True
    assert facts[1500]["source"] == "ACT_exact_response_checkpoint"
    assert facts[3600]["available"] is False
    assert facts[21600]["available"] is False
    assert (
        facts[21600]["source"]
        == "right_censored_by_next_application"
    )

    last = result["per_application"][-1]
    last_facts = {item["horizon_s"]: item for item in last["horizons"]}
    assert last_facts[21600]["source"] == "unknown_missing_or_invalid_horizon_evidence"

    last_application_source = int(
        next(
            row["source_last_sequence"]
            for row in transactions
            if row["event"] == "application"
            and int(row["request_sequence"]) == int(last["request_sequence"])
        )
    )
    with_endpoint = endurance._response_and_horizon_metrics(
        transactions,
        windows,
        endpoint_source_sequence=last_application_source + 100,
    )
    endpoint_facts = {
        item["horizon_s"]: item
        for item in with_endpoint["per_application"][-1]["horizons"]
    }
    assert endpoint_facts[3600]["source"] == "right_censored_by_exact_endpoint"
