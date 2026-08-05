from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from host.otis_tools.cx317_stage7_analyze import (
    _historical_shadow_replays,
    _latest_health_rows,
    _series_metrics,
    _transactions,
)
from host.otis_tools.contracts import ACTIVE_TRANSACTION_V1_FIELDS
from host.otis_tools.cx317_stage7_manifest import create_stage7_manifest
from host.otis_tools.cx317_stage7_part_b_matrix import derive_part_b_matrix
from host.otis_tools.cx317_stage7_shadow import CONTRACT_SHA256
from host.otis_tools.cx317_stage7_shadow_monitor import (
    AUTHORITATIVE,
    SHADOW,
    refresh,
)
from host.otis_tools.cx317_stage7_supervisor import (
    PART_A_QUALIFIED_TIMEOUT_S,
    PART_B_CLEARANCE_GRACE_S,
    PART_B_DURATION_S,
    STAGE7_QUALIFICATION_TIMEOUT_S,
    Stage7Supervisor,
    _next_selected_interval_is_cadence_eligible,
    load_stage7_spec,
)
from host.otis_tools.run_loader import CAPTURE_IN_PROGRESS_FLAG
from tools.firmware_matrix import source_input_hash


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def test_stage7_specs_freeze_part_a_and_endurance_budgets() -> None:
    part_a, identities_a = load_stage7_spec("part_a", 0xA800)
    part_b, identities_b = load_stage7_spec("part_b", 0xA815)

    assert part_a.profile == "cx317_dual_core_active_part_a"
    assert part_a.run_identity == "cx317_stage7_part_a:3170003"
    assert (part_a.correction_limit, part_a.cumulative_limit) == (4, 84)
    assert part_b.profile == "cx317_dual_core_active_endurance_part_b"
    assert part_b.run_identity == "cx317_stage7_part_b:3170004"
    assert part_b.start_code == 0xA815
    assert (part_b.correction_limit, part_b.cumulative_limit) == (32, 672)
    assert identities_a == identities_b
    assert STAGE7_QUALIFICATION_TIMEOUT_S == 5400
    assert PART_A_QUALIFIED_TIMEOUT_S == 14400
    assert PART_B_DURATION_S == 86400
    assert PART_B_CLEARANCE_GRACE_S == 3600


def test_shadow_monitor_preserves_context_and_exactly_replays(tmp_path: Path) -> None:
    run = tmp_path / "run"
    (run / "csv").mkdir(parents=True)
    (run / "reports").mkdir()
    (run / CAPTURE_IN_PROGRESS_FLAG).write_text("test\n", encoding="utf-8")
    (run / "csv/estimates_v2.csv").write_text(
        "record_type,estimator_version,config_hash,observation_validity,"
        "reference_validity,count_validity,diagnostic_health,preview_eligibility,"
        "frequency_error_hz,estimate_id,estimate_seq,estimator_timestamp_ticks,"
        "source_reference_first_seq,source_reference_last_seq\n"
        "EST,cx317_selected_600s_nonoverlap_v1,"
        "5a53b229cabb5a2cf34fa24eb2ffbaae4900bb802be8d17661539399247fcd6c,"
        "valid,valid,valid,healthy,true,-0.005000000820,"
        "est:cx317:selected600:000001,1,9600000000,1,600\n",
        encoding="utf-8",
    )
    (run / "csv/active_transactions_v1.csv").write_text("event\n", encoding="utf-8")
    (run / "csv/environment.csv").write_text(
        "env_seq,temperature_c,relative_humidity_pct,pressure_pa\n"
        "600,30.5,42.0,\n",
        encoding="utf-8",
    )
    (run / "csv/health.csv").write_text(
        "record_type,component,status_key,status_value\n"
        "STS,gnss_receiver,control_eligible,true\n"
        "STS,dual_core,service_to_timing_depth,0\n"
        "STS,dual_core,service_to_timing_high_water,2\n"
        "STS,dual_core,observation_depth,0\n"
        "STS,dual_core,observation_high_water,3\n"
        "STS,dual_core,critical_depth,0\n"
        "STS,dual_core,critical_high_water,2\n"
        "STS,dual_core,evidence_depth,0\n"
        "STS,dual_core,evidence_high_water,1\n"
        "STS,dual_core,telemetry_depth,0\n"
        "STS,dual_core,telemetry_high_water,4\n"
        "STS,dual_core,telemetry_dropped,0\n",
        encoding="utf-8",
    )
    (run / "reports/cx317_active_supervisor_state.json").write_text(
        json.dumps(
            {
                "stage7_part": "part_b",
                "part_b_service_burst_index": None,
            }
        ),
        encoding="utf-8",
    )

    assert refresh(run, part="part_b", start_code=0xA82A) == (1, 5)
    assert refresh(run, part="part_b", start_code=0xA82A) == (1, 5)
    authoritative = _rows(run / AUTHORITATIVE)
    shadow = _rows(run / SHADOW)
    assert len(authoritative) == 1
    assert authoritative[0]["actual_applied_code"] == str(0xA82A)
    assert authoritative[0]["authoritative_deadband_state"] == "inside"
    assert authoritative[0]["gnss_qualification"] == "qualified"
    assert authoritative[0]["shadow_contract_sha256"] == CONTRACT_SHA256
    assert authoritative[0]["preserved_while_capture_active"] == "true"
    assert len(shadow) == 5
    assert {row["estimate_id"] for row in shadow} == {
        "est:cx317:selected600:000001"
    }
    assert all(row["actionable"] == "false" for row in shadow)
    assert all(row["actuation_authorized"] == "false" for row in shadow)
    assert all(row["authorization_consumed"] == "false" for row in shadow)


def test_stage7_supervisor_declares_four_host_evidence_releases() -> None:
    source = Path(
        "host/otis_tools/cx317_stage7_supervisor.py"
    ).read_text(encoding="utf-8")
    assert '"request_created": 1' in source
    assert '"core0_accepted": 2' in source
    assert '"application": 3' in source
    assert '"response": 4' in source
    assert "PART_A_SERVICE_LOAD_QUERIES = 60" in source
    assert "PART_B_DURATION_S = 24 * 60 * 60" in source
    assert "STAGE7_QUALIFICATION_TIMEOUT_S = 90 * 60" in source
    assert "PART_A_QUALIFIED_TIMEOUT_S = 4 * 60 * 60" in source
    assert "PART_B_CLEARANCE_GRACE_S = 60 * 60" in source
    assert 'self.state["response_count"] >= 1' in source
    assert '"part_a_post_service_eligible_control_seq"' in source
    assert "inside_deadband" not in source[source.index("def _process_transactions") : source.index("def _maybe_qualify")]


def test_stage7_manifest_binds_clean_part_a_artifact(tmp_path: Path) -> None:
    build = {
        "provenance": {
            "source": {
                "git_commit": "1" * 40,
                "sha256": "2" * 64,
                "state": "clean",
            },
            "configuration": {
                "profile_id": "cx317_dual_core_active_part_a",
                "sha256": "3" * 64,
                "defines": {
                    "OTIS_CX317_ACTIVE_START_CODE": "0xA800u",
                    "OTIS_CX317_ACTIVE_CORRECTION_LIMIT": "4u",
                    "OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES": "84u",
                    "OTIS_ENABLE_DUAL_CORE_PARTITION": "1",
                    "OTIS_ENABLE_CX317_BOUNDED_ACTIVE": "1",
                    "OTIS_GNSS_UART_TX_ENABLED": "0",
                },
            },
        },
        "artifacts": [
            {
                "name": "otis_nano_rp2040_connect.ino.uf2",
                "sha256": "4" * 64,
                "size_bytes": 123456,
            }
        ],
    }
    build_manifest = tmp_path / "firmware_build_manifest.json"
    build_manifest.write_text(
        json.dumps(build, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    run = tmp_path / "stage7_part_a"
    manifest_path = create_stage7_manifest(
        part="part_a",
        start_code=0xA800,
        run_dir=run,
        build_manifest_path=build_manifest,
        serial_device="/dev/cu.test",
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["stage"] == "CX317_DUAL_CORE_ACTIVE_PART_A"
    assert manifest["firmware"]["profile_id"] == "cx317_dual_core_active_part_a"
    assert manifest["active_campaign"]["authoritative_deadband_hz"] == (
        0.006249995628992717
    )
    assert manifest["active_campaign"]["qualification_timeout_s"] == 5400
    assert manifest["active_campaign"]["duration_after_qualification_s"] == 14400
    assert manifest["active_campaign"]["post_duration_clearance_grace_s"] == 0
    assert manifest["active_campaign"]["maximum_wall_clock_s"] == 19800
    assert manifest["shadow_contract"]["sha256"] == CONTRACT_SHA256
    assert manifest["host"]["shadow_has_serial_or_command_authority"] is False
    assert set(manifest["evidence_artifacts"]) == {
        "reports/cx317_active_supervisor_state.json",
        "reports/cx317_active_supervisor_events.jsonl",
        "reports/stage7_authoritative_observations_v1.csv",
        "reports/stage7_shadow_decisions_v1.csv",
        "reports/stage7_exit_gate.json",
    }


def test_part_b_manifest_requires_exact_passed_a1_a2_handoff(
    tmp_path: Path,
) -> None:
    start_code = 0xA815
    build = {
        "provenance": {
            "source": {
                "git_commit": "1" * 40,
                "sha256": "2" * 64,
                "state": "clean",
            },
            "configuration": {
                "profile_id": "cx317_dual_core_active_endurance_part_b",
                "sha256": "3" * 64,
                "defines": {
                    "OTIS_CX317_ACTIVE_START_CODE": f"0x{start_code:04X}u",
                    "OTIS_CX317_ACTIVE_CORRECTION_LIMIT": "32u",
                    "OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES": "672u",
                    "OTIS_ENABLE_DUAL_CORE_PARTITION": "1",
                    "OTIS_ENABLE_CX317_BOUNDED_ACTIVE": "1",
                    "OTIS_GNSS_UART_TX_ENABLED": "0",
                },
            },
        },
        "artifacts": [
            {
                "name": "otis_nano_rp2040_connect.ino.uf2",
                "sha256": "4" * 64,
                "size_bytes": 123456,
            }
        ],
    }
    a1 = tmp_path / "part_a1_gate.json"
    a1.write_text(
        json.dumps(
            {
                "status": "pass",
                "test": "part_a_fixed_code_stability",
                "applicable": True,
                "criteria": {"every_frozen_criterion": True},
            }
        ),
        encoding="utf-8",
    )
    a2 = tmp_path / "part_a2_gate.json"
    a2.write_text(
        json.dumps(
            {
                "status": "pass",
                "part": "part_a",
                "transactions": {
                    "application_count": 1,
                    "all_response_classifications_replay_exactly": True,
                    "final_code": start_code,
                },
            }
        ),
        encoding="utf-8",
    )
    derived_matrix, derived_start = derive_part_b_matrix(
        part_a2_gate_path=a2,
        output_path=tmp_path / "stage7_part_b_matrix.json",
    )
    assert derived_start == start_code
    build["provenance"]["source"]["sha256"] = source_input_hash(
        matrix_path=derived_matrix
    )
    build_manifest = tmp_path / "firmware_build_manifest.json"
    build_manifest.write_text(json.dumps(build), encoding="utf-8")

    manifest_path = create_stage7_manifest(
        part="part_b",
        start_code=start_code,
        run_dir=tmp_path / "part_b",
        build_manifest_path=build_manifest,
        serial_device="/dev/cu.test",
        part_a1_gate_path=a1,
        part_a2_gate_path=a2,
        part_b_matrix_path=derived_matrix,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert set(manifest["prerequisite_gates"]) == {
        "part_a1_fixed_code_stability",
        "part_a2_cross_core_transaction",
    }
    assert manifest["prerequisite_gates"][
        "part_a1_fixed_code_stability"
    ]["document"]["test"] == "part_a_fixed_code_stability"
    assert manifest["prerequisite_gates"][
        "part_a2_cross_core_transaction"
    ]["document"]["transactions"]["final_code"] == start_code

    changed = json.loads(a2.read_text(encoding="utf-8"))
    changed["transactions"]["final_code"] = start_code + 1
    a2.write_text(json.dumps(changed), encoding="utf-8")
    with pytest.raises(ValueError, match="Part B start"):
        create_stage7_manifest(
            part="part_b",
            start_code=start_code,
            run_dir=tmp_path / "part_b_bad",
            build_manifest_path=build_manifest,
            serial_device="/dev/cu.test",
            part_a1_gate_path=a1,
            part_a2_gate_path=a2,
            part_b_matrix_path=derived_matrix,
        )


def test_stage7_time_series_metrics_do_not_assume_independence() -> None:
    rows = [
        {"frequency_error_hz": str(value), "timestamp_s": str(index * 600)}
        for index, value in enumerate(
            (-0.005, -0.004, -0.003, 0.007, 0.006, 0.005), 1
        )
    ]
    metrics = _series_metrics(rows)
    assert metrics["count"] == 6
    assert metrics["newey_west_lag"] == 3
    assert metrics["successive_estimates_assumed_independent"] is False
    assert 0 < metrics["effective_sample_size_initial_positive_acf"] <= 6
    assert metrics["authoritative_boundary_crossings"] == 2


def test_stage7_analyzer_uses_run_manifest_validation_sets() -> None:
    source = Path("host/otis_tools/cx317_stage7_analyze.py").read_text(
        encoding="utf-8"
    )
    assert "manifest.known_channels" in source
    assert "manifest.known_domains" in source
    assert '"rp2040_timer0" in manifest.known_domains' in source
    assert "manifest.channels" not in source
    assert "manifest.domains" not in source


def test_stage7_analyzer_reduces_loaded_health_rows() -> None:
    latest = _latest_health_rows(
        [
            {
                "record_type": "STS",
                "component": "dual_core",
                "status_key": "telemetry_dropped",
                "status_value": "0",
            },
            {
                "record_type": "STS",
                "component": "dual_core",
                "status_key": "telemetry_dropped",
                "status_value": "7",
            },
        ]
    )
    assert latest[("dual_core", "telemetry_dropped")] == "7"


def _exact_stage7_transaction_rows() -> tuple[
    list[dict[str, str]], object, dict[str, str], str
]:
    spec, identities = load_stage7_spec("part_a", 0xA800)
    build_identity = "a" * 64 + ":" + "b" * 64
    base = {field: "" for field in ACTIVE_TRANSACTION_V1_FIELDS}
    base.update(
        {
            "record_type": "ACT",
            "schema_version": "1",
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
            "pre_error_hz": "-0.010000000",
            "accepted_code": "0",
            "accepted_timestamp_s": "0",
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
            "response_class": "unavailable",
            "actionable": "false",
        }
    )
    manual = dict(base)
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
            "requested_delta_codes": "0",
            "requested_code": str(spec.start_code),
            "correction_ordinal": "0",
            "cumulative_after_codes": "0",
            "pre_error_hz": "0",
            "accepted_code": str(spec.start_code),
            "accepted_timestamp_s": "1",
            "applied_code": str(spec.start_code),
            "application_timestamp_s": "1",
            "i2c_ok": "true",
            "active_state": "DISARMED",
            "reason": "manual_start_established",
            "evidence_state": "evidence_clear",
        }
    )
    created = dict(base)
    created.update(
        {
            "transaction_record_sequence": "2",
            "event": "request_created",
            "active_state": "REQUEST_PENDING",
            "reason": "request_created",
            "evidence_state": "request_pending",
        }
    )
    accepted = dict(created)
    accepted.update(
        {
            "transaction_record_sequence": "3",
            "event": "core0_accepted",
            "accepted_code": str(spec.start_code + 21),
            "accepted_timestamp_s": "2400",
            "active_state": "ACCEPTED_AWAITING_APPLICATION",
            "reason": "request_consumed_actionable_cleared",
            "evidence_state": "acceptance_pending",
        }
    )
    application = dict(accepted)
    application.update(
        {
            "transaction_record_sequence": "4",
            "event": "application",
            "applied_code": str(spec.start_code + 21),
            "application_sequence": "1",
            "application_timestamp_s": "2401",
            "i2c_ok": "true",
            "dac_epoch": "1",
            "estimator_history_reset": "true",
            "correction_count": "1",
            "cumulative_movement_codes": "21",
            "active_state": "AWAITING_RESPONSE",
            "reason": "application_preserved",
            "evidence_state": "application_pending",
        }
    )
    response = dict(application)
    response.update(
        {
            "transaction_record_sequence": "5",
            "event": "response",
            "post_error_hz": "-0.003000000",
            "observed_response_hz": "0.007000000",
            "cumulative_response_hz": "0.007000000",
            "active_state": "DISARMED",
            "response_class": "inside_deadband",
            "reason": "post_error_inside_frozen_deadband",
            "evidence_state": "response_pending",
        }
    )
    return [manual, created, accepted, application, response], spec, identities, build_identity


def test_stage7_exact_four_phase_history_and_response_replay() -> None:
    rows, spec, identities, build_identity = _exact_stage7_transaction_rows()
    check, evidence = _transactions(rows, spec, identities, build_identity)
    assert check.passed
    assert evidence["application_count"] == 1
    assert evidence["final_code"] == 0xA815
    assert evidence["all_response_classifications_replay_exactly"] is True


def test_stage7_rejects_cross_phase_request_field_mutation() -> None:
    rows, spec, identities, build_identity = _exact_stage7_transaction_rows()
    rows[3]["nonce"] = "10"
    with pytest.raises(ValueError, match="immutable fields changed"):
        _transactions(rows, spec, identities, build_identity)


def _supervisor(
    tmp_path: Path, *, part: str = "part_a", start_code: int = 0xA800
) -> Stage7Supervisor:
    run = tmp_path / "run"
    (run / "csv").mkdir(parents=True)
    spec, identities = load_stage7_spec(part, start_code)
    return Stage7Supervisor(
        part=part,
        run_dir=run,
        command_fifo=tmp_path / "command.fifo",
        abort_fifo=tmp_path / "abort.fifo",
        spec=spec,
        identities=identities,
        expected_build_identity="a" * 64 + ":" + "b" * 64,
        allow_manual_start=True,
        allow_arm=True,
        duration_s=None,
    )


def test_part_a_waits_for_eligible_decision_after_service_interval(
    tmp_path: Path,
) -> None:
    supervisor = _supervisor(tmp_path)
    supervisor.state.update(
        {
            "qualification_started_utc": "1970-01-01T00:00:00Z",
            "response_count": 1,
            "part_a_service_load_complete": True,
            "part_a_service_load_completed_control_seq": 10,
            "part_a_post_service_eligible_control_seq": None,
            "arm_pending": False,
        }
    )
    controls = supervisor.run_dir / "csv/control_previews_v1.csv"
    controls.write_text(
        "control_seq,preview_available,model_applicability,diagnostic_health,"
        "limited_delta_codes\n"
        "10,true,applicable,healthy,0\n",
        encoding="utf-8",
    )
    health = {
        ("cx317_active", "state"): "DISARMED",
        ("cx317_active", "evidence_phase"): "evidence_clear",
    }
    supervisor._maybe_finish(health, 0.0)
    assert supervisor.state["terminal"] is None

    with controls.open("a", encoding="utf-8") as handle:
        handle.write("11,true,applicable,healthy,0\n")
    supervisor._maybe_finish(health, 0.0)
    assert supervisor.state["terminal"]["result"] == "healthy_stop"
    assert supervisor.state["part_a_post_service_eligible_control_seq"] == 11


def test_stage7_qualification_and_part_a_have_finite_fail_static_deadlines(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor = _supervisor(tmp_path)
    aborts: list[str] = []
    monkeypatch.setattr(supervisor, "_abort", aborts.append)
    supervisor.state.update(
        {
            "supervisor_started_utc": "1970-01-01T00:00:00Z",
            "qualification_started_utc": None,
        }
    )
    supervisor._maybe_finish({}, float(STAGE7_QUALIFICATION_TIMEOUT_S))
    assert aborts == ["stage7_qualification_timeout"]

    aborts.clear()
    supervisor.state.update(
        {
            "qualification_started_utc": "1970-01-01T00:00:00Z",
            "response_count": 0,
        }
    )
    supervisor._maybe_finish({}, float(PART_A_QUALIFIED_TIMEOUT_S))
    assert aborts == ["part_a_qualified_duration_expired"]


def test_part_b_stable_no_write_run_stops_successfully_at_24h(
    tmp_path: Path,
) -> None:
    supervisor = _supervisor(tmp_path, part="part_b", start_code=0xA82A)
    supervisor.state.update(
        {
            "qualification_started_utc": "1970-01-01T00:00:00Z",
            "arm_pending": False,
            "duration_elapsed": False,
            "part_b_service_bursts_complete": [0, 1, 2, 3],
        }
    )
    health = {
        ("cx317_active", "state"): "DISARMED",
        ("cx317_active", "evidence_phase"): "evidence_clear",
    }
    supervisor._maybe_finish(health, float(PART_B_DURATION_S))
    assert supervisor.state["duration_elapsed"] is True
    assert supervisor.state["terminal"]["result"] == "healthy_stop"
    assert supervisor.state["terminal"]["reason"] == "24h_after_qualification_complete"


def test_part_b_cannot_wait_indefinitely_for_post_duration_clearance(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor = _supervisor(tmp_path, part="part_b", start_code=0xA82A)
    aborts: list[str] = []
    monkeypatch.setattr(supervisor, "_abort", aborts.append)
    supervisor.state.update(
        {
            "qualification_started_utc": "1970-01-01T00:00:00Z",
            "arm_pending": True,
            "duration_elapsed": False,
            "part_b_service_bursts_complete": [0, 1, 2, 3],
        }
    )
    health = {
        ("cx317_active", "state"): "AWAITING_RESPONSE",
        ("cx317_active", "evidence_phase"): "application_preserved",
    }
    supervisor._maybe_finish(health, float(PART_B_DURATION_S))
    assert supervisor.state["duration_elapsed"] is True
    assert aborts == []
    supervisor._maybe_finish(
        health, float(PART_B_DURATION_S + PART_B_CLEARANCE_GRACE_S)
    )
    assert aborts == ["part_b_clearance_grace_expired"]


def test_part_b_cannot_pass_without_all_required_service_bursts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor = _supervisor(tmp_path, part="part_b", start_code=0xA82A)
    aborts: list[str] = []
    monkeypatch.setattr(supervisor, "_abort", aborts.append)
    supervisor.state.update(
        {
            "qualification_started_utc": "1970-01-01T00:00:00Z",
            "arm_pending": False,
            "duration_elapsed": False,
            "part_b_service_bursts_complete": [0, 1, 2],
        }
    )
    health = {
        ("cx317_active", "state"): "DISARMED",
        ("cx317_active", "evidence_phase"): "evidence_clear",
    }
    supervisor._maybe_finish(health, float(PART_B_DURATION_S))
    assert aborts == ["part_b_required_service_bursts_incomplete"]


def test_stage7_supervisor_stops_on_partition_or_transport_loss(
    tmp_path: Path,
) -> None:
    supervisor = _supervisor(tmp_path)
    with pytest.raises(ValueError, match="partition fault"):
        supervisor._check_fail_static_health(
            {("dual_core", "partition_fault"): "evidence_queue_exhausted"}
        )
    with pytest.raises(ValueError, match="telemetry_dropped"):
        supervisor._check_fail_static_health(
            {
                ("dual_core", "partition_fault"): "none",
                ("dual_core", "telemetry_dropped"): "1",
            }
        )


def test_stage7_arms_only_for_the_next_cadence_eligible_interval(
    tmp_path: Path,
) -> None:
    controls = tmp_path / "control_previews_v1.csv"
    estimates = tmp_path / "estimates_v2.csv"
    header = (
        "decision_timestamp_ticks,preview_available,decision_reason_code,"
        "est_input_ref\n"
    )
    controls.write_text(header, encoding="utf-8")
    estimates.write_text(
        "estimate_id,source_count_seq\n"
        "est:0,1799\n"
        "est:1,2399\n"
        "est:2,2999\n"
        "est:3,3599\n",
        encoding="utf-8",
    )
    assert not _next_selected_interval_is_cadence_eligible(
        controls, estimates
    )

    with controls.open("a", encoding="utf-8") as handle:
        handle.write("28827892112,false,fresh_estimator_support,est:0\n")
    assert _next_selected_interval_is_cadence_eligible(controls, estimates)

    with controls.open("a", encoding="utf-8") as handle:
        handle.write("38427843600,true,inside_evidence_deadband,est:1\n")
    assert not _next_selected_interval_is_cadence_eligible(
        controls, estimates
    )

    with controls.open("a", encoding="utf-8") as handle:
        handle.write("48027796864,false,decision_cadence_hold,est:2\n")
    assert not _next_selected_interval_is_cadence_eligible(
        controls, estimates
    )

    with controls.open("a", encoding="utf-8") as handle:
        handle.write("57627748416,false,decision_cadence_hold,est:3\n")
    assert _next_selected_interval_is_cadence_eligible(controls, estimates)


def test_stage7_does_not_rearm_from_stale_high_progress_after_control(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    supervisor = _supervisor(tmp_path)
    controls = supervisor.run_dir / "csv/control_previews_v1.csv"
    estimates = supervisor.run_dir / "csv/estimates_v2.csv"
    controls.write_text(
        "decision_timestamp_ticks,preview_available,decision_reason_code,"
        "est_input_ref,decision_id,limited_delta_codes\n"
        "38427843600,true,inside_evidence_deadband,est:1,ctl:1,0\n"
        "48027796864,false,decision_cadence_hold,est:2,ctl:2,\n"
        "57627748416,false,decision_cadence_hold,est:3,ctl:3,\n",
        encoding="utf-8",
    )
    estimates.write_text(
        "estimate_id,source_count_seq\n"
        "est:1,2399\n"
        "est:2,2999\n"
        "est:3,3599\n",
        encoding="utf-8",
    )
    supervisor.state.update(
        {
            "arm_pending": False,
            "duration_elapsed": False,
            "manual_start_sent": True,
            "authorization_sequence": 1,
        }
    )
    commands: list[str] = []
    monkeypatch.setattr(supervisor, "_identity_ready", lambda health: True)
    monkeypatch.setattr(supervisor, "_command", commands.append)

    health = {
        ("cx317_active", "state"): "DISARMED",
        ("cx317_active", "manual_start_confirmed"): "true",
        ("cx317_active", "correction_count"): "0",
        ("cx317_active", "arm_eligible"): "true",
        ("cx317_active", "evidence_phase"): "evidence_clear",
        ("cx317_active", "selected_interval_count"): "598",
        ("cx317_active", "uptime_s"): "3600",
    }

    # This is the exact V5 race: CTL3 is new but ACTIVE? still reports the
    # previous estimator epoch's high-water progress.  It must not arm.
    supervisor._maybe_start_or_arm(health)
    assert commands == []
    assert supervisor.state["authorization_sequence"] == 1

    # Observe the reset for the epoch after CTL3, then arm only once genuine
    # progress reaches the frozen threshold near CTL4.
    health[("cx317_active", "selected_interval_count")] = "0"
    supervisor._maybe_start_or_arm(health)
    assert commands == []
    health[("cx317_active", "selected_interval_count")] = "519"
    supervisor._maybe_start_or_arm(health)
    assert commands == []
    health[("cx317_active", "selected_interval_count")] = "520"
    health[("cx317_active", "uptime_s")] = "4120"
    supervisor._maybe_start_or_arm(health)
    assert len(commands) == 1
    assert commands[0].startswith("ACTIVE ARM 2 ")
    assert supervisor.state["arm_pending"] is True


def test_frozen_shadow_exactly_replays_sealed_campaign_a_and_b() -> None:
    check, replays = _historical_shadow_replays()
    assert check.passed
    assert set(replays) == {"campaign_a_v3", "campaign_b"}
    assert replays["campaign_a_v3"][
        "v2_baseline_exact_application_replay"
    ]
    assert replays["campaign_b"][
        "v2_baseline_exact_application_replay"
    ]
    for replay in replays.values():
        assert replay["authoritative_stage_exit_passed"]
        assert replay["v2_baseline_within_original_campaign_budget"]
        assert replay["every_counterfactual_decision_has_reason"]
        baseline = replay["candidate_metrics"]["v2_symmetric_baseline"]
        assert baseline["newey_west_lag"] == min(
            3, baseline["observations"] - 1
        )
        assert baseline["successive_estimates_assumed_independent"] is False
