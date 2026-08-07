from __future__ import annotations

import csv
from datetime import datetime, timezone
import json
from pathlib import Path

import pytest

from host.otis_tools.cx317_stage7_analyze import (
    _controller_parity,
    _dual_core_queue_health,
    _historical_shadow_replays,
    _latest_health_rows,
    _series_metrics,
    _transactions,
    _transactions_for_analysis,
)
from host.otis_tools.cx317_i_only_preview_replay import (
    IOnlyPreviewEngine,
    Observation,
    load_post_campaign_policy,
)
from host.otis_tools.cx317_stage6_dual_core_analyze import _estimator_parity
from host.otis_tools.contracts import (
    ACTIVE_TRANSACTION_V1_FIELDS,
    CONTROL_PREVIEW_V1_FIELDS,
    ESTIMATE_V2_FIELDS,
    HEALTH_FIELDS,
)
from host.otis_tools.cx317_stage7_rehearsal_analyze import (
    analyze as analyze_rehearsal,
)
from host.otis_tools.cx317_stage7_manifest import create_stage7_manifest
from host.otis_tools.cx317_stage7_gate_validation import (
    PART_A_COMPOSITE_TEST,
    part_a2_progression_gate_valid,
)
from host.otis_tools.cx317_stage7_part_b_matrix import derive_part_b_matrix
from host.otis_tools.cx317_stage7_part_b_rehearsal import (
    rehearse as rehearse_part_b,
)
from host.otis_tools.cx317_stage7_shadow import CONTRACT_SHA256
from host.otis_tools.cx317_stage7_shadow_monitor import (
    AUTHORITATIVE,
    SHADOW,
    refresh,
)
from host.otis_tools.cx317_stage7_supervisor import (
    REHEARSAL_DECISION_CADENCE_S,
    REHEARSAL_QUALIFICATION_TIMEOUT_S,
    REHEARSAL_SELECTED_INTERVAL_S,
    PART_A_QUALIFIED_TIMEOUT_S,
    PART_B_CLEARANCE_GRACE_S,
    PART_B_DURATION_S,
    STAGE7_QUALIFICATION_TIMEOUT_S,
    Stage7Supervisor,
    _next_selected_interval_is_cadence_eligible,
    load_stage7_spec,
    part_b_timeline_preflight,
    rehearsal_timeline_preflight,
    stage7_timing,
)
from host.otis_tools.evidence import create_evidence_snapshot
from host.otis_tools.run_loader import CAPTURE_IN_PROGRESS_FLAG
from host.otis_tools.serial_commands import parse_serial_command
from tools.firmware_matrix import source_input_hash


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _sealed_hil_rehearsal_gate(tmp_path: Path) -> Path:
    from hashlib import sha256

    transport_gate = _sealed_transport_rehearsal_gate(tmp_path)
    transport_run = transport_gate.parent.parent
    transport_manifest = transport_run / "run_manifest.json"
    transport_snapshot = transport_run / "evidence_manifest.json"
    transport_document = json.loads(
        transport_gate.read_text(encoding="utf-8")
    )
    transport_binding = {
        "path": str(transport_gate),
        "sha256": sha256(transport_gate.read_bytes()).hexdigest(),
        "run_manifest": {
            "path": str(transport_manifest),
            "sha256": sha256(transport_manifest.read_bytes()).hexdigest(),
        },
        "evidence_snapshot": {
            "path": str(transport_snapshot),
            "sha256": sha256(transport_snapshot.read_bytes()).hexdigest(),
            "snapshot_digest": json.loads(
                transport_snapshot.read_text(encoding="utf-8")
            )["snapshot_digest"],
        },
        "bindings": transport_document["bindings"],
    }
    run = (tmp_path / "sealed_hil_rehearsal").resolve()
    reports = run / "reports"
    csv_dir = run / "csv"
    reports.mkdir(parents=True)
    csv_dir.mkdir()
    (csv_dir / "test.csv").write_text("value\npassed\n", encoding="utf-8")
    gate = reports / "stage7_rehearsal_gate.json"
    gate.write_text(
        json.dumps(
            {
                "status": "pass",
                "tool": "cx317_stage7_rehearsal_analyze_v3",
                "diagnostic_only": True,
                "qualification_evidence": False,
                "stage7_progression_authority": False,
                "run_dir": str(run),
                "criteria": {
                    "active_contract_valid": True,
                    "both_responses_completed_without_fault_class": True,
                    "capture_closed_before_gate": True,
                    "exact_clean_build_and_uf2": True,
                    "exact_two_complete_consecutive_transactions": True,
                    "final_device_disarmed_evidence_clear": True,
                    "host_priority_transport_exact_and_clean": True,
                    "later_cadence_eligible_decision_observed": True,
                    "partition_capture_and_transport_remained_clean": True,
                    "priority_transport_fault_rehearsal_passed": True,
                    "sixty_query_service_load_completed": True,
                    "supervisor_healthy_stop": True,
                },
                "event_faults": [],
                "active_contract_errors": [],
                "priority_transport_fault_rehearsal": transport_binding,
                "final": {
                    "active_state": "DISARMED",
                    "evidence_phase": "evidence_clear",
                },
            }
        ),
        encoding="utf-8",
    )
    (run / "run_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": run.name,
                "stage": "CX317_STAGE7_DIAGNOSTIC_REHEARSAL",
                "diagnostic_only": True,
                "qualification_evidence": False,
                "stage7_progression_authority": False,
                "host": {
                    "sole_serial_owner": True,
                    "independent_abort_fifo_required": True,
                    "priority_abort_command_fifo_required": True,
                    "capture_command_write_timeout_s": 1.0,
                    "capture_console_log_file_required": True,
                    "normal_command_batch_limit": 1,
                    "normal_command_max_age_s": 2.0,
                    "normal_command_envelope": "OTISQ1_MONOTONIC_NS",
                    "supervisor_tool": "host.otis_tools.cx317_stage7_supervisor",
                },
                "active_campaign": {"part": "rehearsal"},
                "firmware": {"source_state": "clean"},
                "files": [
                    {"path": "csv/test.csv", "contract": "test_v1"}
                ],
                "evidence_artifacts": [
                    "reports/stage7_rehearsal_gate.json"
                ],
            }
        ),
        encoding="utf-8",
    )
    (run / "COMPLETE").write_text("complete\n", encoding="utf-8")
    create_evidence_snapshot(run)
    return gate


def _sealed_transport_rehearsal_gate(tmp_path: Path) -> Path:
    from hashlib import sha256

    run = (tmp_path / "sealed_transport_rehearsal").resolve()
    reports = run / "reports"
    csv_dir = run / "csv"
    reports.mkdir(parents=True)
    csv_dir.mkdir()
    (csv_dir / "test.csv").write_text("value\npassed\n", encoding="utf-8")
    tool_dir = Path("host/otis_tools")
    bindings = {
        "capture_tool_sha256": sha256(
            (tool_dir / "capture_device.py").read_bytes()
        ).hexdigest(),
        "supervisor_sha256": sha256(
            (tool_dir / "cx317_stage7_supervisor.py").read_bytes()
        ).hexdigest(),
        "serial_commands_sha256": sha256(
            (tool_dir / "serial_commands.py").read_bytes()
        ).hexdigest(),
        "injection_tool_sha256": sha256(
            (
                tool_dir / "cx317_stage7_transport_fault_inject.py"
            ).read_bytes()
        ).hexdigest(),
        "analyzer_tool_sha256": sha256(
            (
                tool_dir / "cx317_stage7_transport_rehearsal_analyze.py"
            ).read_bytes()
        ).hexdigest(),
    }
    gate = reports / "stage7_rehearsal_gate.json"
    gate.write_text(
        json.dumps(
            {
                "status": "pass",
                "tool": "cx317_stage7_transport_rehearsal_analyze_v1",
                "diagnostic_only": True,
                "qualification_evidence": False,
                "stage7_progression_authority": False,
                "run_dir": str(run),
                "criteria": {"exact_transport_fault_rehearsal": True},
                "bindings": bindings,
            }
        ),
        encoding="utf-8",
    )
    (run / "run_manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "run_id": run.name,
                "stage": "CX317_STAGE7_TRANSPORT_FAULT_REHEARSAL",
                "diagnostic_only": True,
                "qualification_evidence": False,
                "stage7_progression_authority": False,
                "files": [
                    {"path": "csv/test.csv", "contract": "test_v1"}
                ],
                "evidence_artifacts": [
                    "reports/stage7_rehearsal_gate.json"
                ],
            }
        ),
        encoding="utf-8",
    )
    (run / "COMPLETE").touch()
    create_evidence_snapshot(run)
    return gate


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


def test_zero_correction_endurance_still_requires_manual_start_queue_traffic() -> None:
    latest = {
        ("dual_core", "partition_fault"): "none",
        ("dual_core", "fail_static"): "false",
        ("cx317_active", "fail_static"): "false",
        ("dual_core", "telemetry_dropped"): "0",
        ("dual_core", "observation_high_water"): "3",
        ("dual_core", "critical_high_water"): "1",
        ("dual_core", "evidence_high_water"): "1",
    }

    assert _dual_core_queue_health(latest)

    latest[("dual_core", "critical_high_water")] = "0"
    assert not _dual_core_queue_health(latest)

    latest[("dual_core", "critical_high_water")] = "1"
    latest[("dual_core", "telemetry_dropped")] = "1"
    assert not _dual_core_queue_health(latest)


def test_composite_part_a_gate_preserves_failed_source_and_repair_scope() -> None:
    gate = {
        "status": "pass",
        "part": "part_a",
        "test": PART_A_COMPOSITE_TEST,
        "qualification_evidence": True,
        "stage7_progression_authority": True,
        "criteria": {"all_bound_evidence_passed": True},
        "transactions": {
            "application_count": 1,
            "all_response_classifications_replay_exactly": True,
            "final_code": 0xA815,
        },
        "source_a2_disposition": {
            "source_exit_status": "fail",
            "source_run_state": "partial",
            "source_run_relabelled_as_pass": False,
        },
        "repair_rehearsal": {
            "status": "pass",
            "diagnostic_only": True,
            "qualification_evidence": False,
            "evidence_snapshot_valid": True,
        },
    }

    assert part_a2_progression_gate_valid(gate)
    gate["source_a2_disposition"]["source_run_relabelled_as_pass"] = True
    assert not part_a2_progression_gate_valid(gate)
    gate["source_a2_disposition"]["source_run_relabelled_as_pass"] = False
    gate["repair_rehearsal"]["qualification_evidence"] = True
    assert not part_a2_progression_gate_valid(gate)


def test_stage7_rehearsal_is_distinct_finite_and_nonqualifying() -> None:
    spec, identities = load_stage7_spec("rehearsal", 0xA800)
    timing = stage7_timing("rehearsal")

    assert spec.profile == "cx317_dual_core_active_rehearsal"
    assert spec.run_identity == "cx317_stage7_rehearsal:3170005"
    assert spec.correction_limit == 2
    assert spec.cumulative_limit == 42
    assert timing.selected_interval_s == REHEARSAL_SELECTED_INTERVAL_S == 120
    assert timing.decision_cadence_s == REHEARSAL_DECISION_CADENCE_S == 240
    assert timing.qualification_timeout_s == REHEARSAL_QUALIFICATION_TIMEOUT_S == 420
    assert timing.qualified_timeout_s == 1200
    assert identities["estimator_sha256"] != load_stage7_spec(
        "part_a", 0xA800
    )[1]["estimator_sha256"]
    assert identities["active_policy_sha256"] == identities[
        "numerical_policy_sha256"
    ]
    preflight = rehearsal_timeline_preflight()
    assert all(preflight["checks"].values())
    assert preflight["derived_s"] == {
        "lower_layer_ready": 63,
        "first_arm_window": 165,
        "first_actionable_decision": 180,
        "response_ready_after_application": 180,
        "conservative_post_application_completion": 1020,
    }


def test_stage7_rehearsal_preflight_rejects_inherited_qualification_inhibit() -> None:
    policy = json.loads(
        Path("profiles/discipline/cx317_stage7_rehearsal_v1.json").read_text(
            encoding="utf-8"
        )
    )
    policy["timing_s"]["pps_backend_startup_inhibit"] = 600
    preflight = rehearsal_timeline_preflight(policy)

    assert preflight["checks"]["policy_timers_exact"] is False
    assert preflight["checks"][
        "arm_window_precedes_first_actionable_decision"
    ] is False


def test_stage7_part_b_preflight_proves_every_long_clock_fits() -> None:
    preflight = part_b_timeline_preflight()

    assert all(preflight["checks"].values())
    assert preflight["derived_s"] == {
        "lower_layer_ready": 603,
        "earliest_qualification": 2400,
        "service_burst_starts": [3600, 25200, 46800, 68400],
        "final_service_burst_complete": 68460,
        "qualified_duration": 86400,
        "response_ready_after_application": 1500,
        "conservative_boundary_transaction_clear": 1620,
        "clearance_grace": 3600,
        "maximum_wall_clock": 95400,
    }


def test_stage7_part_b_preflight_rejects_insufficient_clearance_policy() -> None:
    policy = json.loads(
        Path("profiles/discipline/cx317_bounded_active_v2.json").read_text(
            encoding="utf-8"
        )
    )
    policy["parameters"]["full_history_reset_s"] = 3600
    preflight = part_b_timeline_preflight(policy)

    assert preflight["checks"]["policy_timers_exact"] is False
    assert preflight["checks"][
        "clearance_covers_boundary_transaction_response"
    ] is False


def test_stage7_part_b_accelerated_control_rehearsal_passes() -> None:
    report = rehearse_part_b()

    assert report["status"] == "pass"
    assert report["qualification_evidence"] is False
    assert report["hardware_actuation"] is False
    assert report["serial_or_fifo_authority"] is False
    assert all(report["timeline_preflight"]["checks"].values())
    assert all(report["cases"].values())


def test_stage7_rehearsal_manifest_cannot_claim_qualification(
    tmp_path: Path,
) -> None:
    defines = {
        "OTIS_CX317_ACTIVE_START_CODE": "0xA800u",
        "OTIS_CX317_ACTIVE_CORRECTION_LIMIT": "2u",
        "OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES": "42u",
        "OTIS_ENABLE_DUAL_CORE_PARTITION": "1",
        "OTIS_ENABLE_CX317_BOUNDED_ACTIVE": "1",
        "OTIS_GNSS_UART_TX_ENABLED": "0",
        "OTIS_CX317_SELECTED_SPAN_INTERVALS_CONFIG": "120u",
        "OTIS_FC0_STARTUP_INHIBIT_MS": "60000u",
        "OTIS_FC0_CONTROL_READY_CLEAN_WINDOWS": "3u",
        "OTIS_CX317_STARTUP_WARMUP_S": "60u",
        "OTIS_CX317_SETTLING_EXCLUSION_S": "60u",
        "OTIS_CX317_FULL_HISTORY_RESET_S": "180u",
        "OTIS_CX317_RECOVERY_FRESH_SUPPORT_S": "120u",
        "OTIS_CX317_DECISION_CADENCE_S": "240u",
        "OTIS_CX317_MINIMUM_APPLIED_CADENCE_S": "240u",
    }
    build = {
        "provenance": {
            "source": {
                "git_commit": "1" * 40,
                "sha256": "2" * 64,
                "state": "clean",
            },
            "configuration": {
                "profile_id": "cx317_dual_core_active_rehearsal",
                "sha256": "3" * 64,
                "defines": defines,
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
    build_manifest.write_text(json.dumps(build), encoding="utf-8")
    path = create_stage7_manifest(
        part="rehearsal",
        start_code=0xA800,
        run_dir=tmp_path / "rehearsal",
        build_manifest_path=build_manifest,
        serial_device="/dev/cu.test",
    )
    manifest = json.loads(path.read_text(encoding="utf-8"))

    assert manifest["diagnostic_only"] is True
    assert manifest["qualification_evidence"] is False
    assert manifest["stage7_progression_authority"] is False
    assert manifest["shadow_contract"]["enabled"] is False
    assert manifest["active_campaign"]["correction_limit"] == 2
    assert manifest["active_campaign"]["cumulative_limit_codes"] == 42
    assert manifest["active_campaign"]["maximum_wall_clock_s"] == 1620
    assert all(
        manifest["active_campaign"]["cross_layer_timeline_preflight"][
            "checks"
        ].values()
    )
    assert manifest["policy"]["path"] == (
        "profiles/discipline/cx317_stage7_rehearsal_v1.json"
    )
    assert "reports/stage7_rehearsal_gate.json" in manifest[
        "expected_artifacts"
    ]
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
        # A later mutable display snapshot must not overwrite the exact
        # qualification carried by the selected estimator source boundary.
        "STS,gnss_receiver,control_eligible,false\n"
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
    assert 'required_responses = 2 if self.part == "rehearsal" else 1' in source
    assert '"part_a_post_service_eligible_control_seq"' in source
    assert parse_serial_command("ACTIVE EVIDENCE 1 4").normalized == (
        "ACTIVE EVIDENCE 1 4"
    )
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
    assert manifest["host"]["priority_abort_command_fifo_required"] is True
    assert manifest["host"]["capture_command_write_timeout_s"] == 1.0
    assert manifest["host"]["capture_console_log_file_required"] is True
    assert manifest["host"]["normal_command_batch_limit"] == 1
    assert manifest["host"]["normal_command_max_age_s"] == 2.0
    assert manifest["host"]["normal_command_envelope"] == (
        "OTISQ1_MONOTONIC_NS"
    )
    assert set(manifest["evidence_artifacts"]) == {
        "reports/capture_device_state.json",
        "reports/capture_device.log",
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
    rehearsal = tmp_path / "part_b_rehearsal_gate.json"
    rehearsal.write_text(
        json.dumps(rehearse_part_b()),
        encoding="utf-8",
    )
    hil_rehearsal = _sealed_hil_rehearsal_gate(tmp_path)
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
        part_b_rehearsal_gate_path=rehearsal,
        part_b_hil_rehearsal_gate_path=hil_rehearsal,
        part_b_matrix_path=derived_matrix,
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert set(manifest["prerequisite_gates"]) == {
        "part_a1_fixed_code_stability",
        "part_a2_cross_core_transaction",
        "part_b_accelerated_control_rehearsal",
        "part_b_post_repair_hil_rehearsal",
    }
    assert manifest["prerequisite_gates"][
        "part_a1_fixed_code_stability"
    ]["document"]["test"] == "part_a_fixed_code_stability"
    assert manifest["prerequisite_gates"][
        "part_a2_cross_core_transaction"
    ]["document"]["transactions"]["final_code"] == start_code
    assert manifest["prerequisite_gates"][
        "part_b_accelerated_control_rehearsal"
    ]["document"]["status"] == "pass"
    assert manifest["prerequisite_gates"][
        "part_b_post_repair_hil_rehearsal"
    ]["document"]["status"] == "pass"
    assert all(
        manifest["active_campaign"]["cross_layer_timeline_preflight"][
            "checks"
        ].values()
    )

    changed_rehearsal = json.loads(rehearsal.read_text(encoding="utf-8"))
    changed_rehearsal["cases"]["duration_boundary_inhibits_new_arm"] = False
    rehearsal.write_text(json.dumps(changed_rehearsal), encoding="utf-8")
    with pytest.raises(ValueError, match="accelerated rehearsal"):
        create_stage7_manifest(
            part="part_b",
            start_code=start_code,
            run_dir=tmp_path / "part_b_bad_rehearsal",
            build_manifest_path=build_manifest,
            serial_device="/dev/cu.test",
            part_a1_gate_path=a1,
            part_a2_gate_path=a2,
            part_b_rehearsal_gate_path=rehearsal,
            part_b_hil_rehearsal_gate_path=hil_rehearsal,
            part_b_matrix_path=derived_matrix,
        )
    rehearsal.write_text(json.dumps(rehearse_part_b()), encoding="utf-8")

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
            part_b_rehearsal_gate_path=rehearsal,
            part_b_hil_rehearsal_gate_path=hil_rehearsal,
            part_b_matrix_path=derived_matrix,
        )
    changed["transactions"]["final_code"] = start_code
    a2.write_text(json.dumps(changed), encoding="utf-8")

    changed_hil = json.loads(hil_rehearsal.read_text(encoding="utf-8"))
    changed_hil["criteria"]["supervisor_healthy_stop"] = False
    hil_rehearsal.write_text(json.dumps(changed_hil), encoding="utf-8")
    with pytest.raises(ValueError, match="HIL rehearsal"):
        create_stage7_manifest(
            part="part_b",
            start_code=start_code,
            run_dir=tmp_path / "part_b_bad_hil_rehearsal",
            build_manifest_path=build_manifest,
            serial_device="/dev/cu.test",
            part_a1_gate_path=a1,
            part_a2_gate_path=a2,
            part_b_rehearsal_gate_path=rehearsal,
            part_b_hil_rehearsal_gate_path=hil_rehearsal,
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


def test_stage7_a2_estimator_replay_accepts_its_three_required_outputs() -> None:
    estimator_hash = "e" * 64
    counts: dict[int, dict[str, str]] = {}
    estimates: list[dict[str, str]] = []
    for estimate_sequence in range(3):
        first = estimate_sequence * 600
        last = first + 600
        for source_sequence in range(first + 1, last + 1):
            counts[source_sequence] = {"counted_edges": "10000000"}
        estimates.append(
            {
                "estimate_seq": str(estimate_sequence),
                "estimate_id": f"estimate-{estimate_sequence}",
                "estimator_version": "cx317_selected_600s_nonoverlap_v1",
                "source_reference_first_seq": str(first),
                "source_reference_last_seq": str(last),
                "frequency_estimate_hz": "10000000.000000000000",
                "frequency_error_hz": "0.000000000000",
                "config_hash": estimator_hash,
                "observation_validity": "valid",
                "reference_validity": "valid",
                "count_validity": "valid",
                "diagnostic_health": "healthy",
            }
        )

    stage6_check, _ = _estimator_parity(estimates, counts, estimator_hash)
    stage7_a2_check, _ = _estimator_parity(
        estimates, counts, estimator_hash, minimum_selected=3
    )

    assert not stage6_check.passed
    assert stage7_a2_check.passed


def test_stage7_controller_replay_uses_actual_application_epoch() -> None:
    policy = load_post_campaign_policy()
    generator = IOnlyPreviewEngine(policy)
    estimates = [
        {"estimate_id": "selected-1", "frequency_error_hz": "-0.010000000000"},
        {"estimate_id": "selected-2", "frequency_error_hz": "-0.006666665897"},
        {"estimate_id": "selected-3", "frequency_error_hz": "-0.006666665897"},
    ]
    observations = (
        (1800, None, 0xA800, "missing"),
        (2400, -0.010000000000, 0xA800, "selected-1"),
        (3900, -0.006666665897, 0xA815, "selected-2"),
        (4500, -0.006666665897, 0xA815, "selected-3"),
    )
    mapped = {
        "WARMUP_INHIBIT": "WARMUP_INHIBIT",
        "QUALIFYING": "QUALIFYING",
        "SETTLING_INHIBIT": "SETTLE_PREVIEW",
        "TRACKING": "LOCKED_PREVIEW",
    }
    controls: list[dict[str, str]] = []
    for sequence, (timestamp_s, error, code, estimate_id) in enumerate(
        observations
    ):
        if sequence == 2:
            generator.note_dac_epoch(2403)
        previous = generator.state
        result = generator.process(
            Observation(timestamp_s, error, code)
        )
        preview = bool(result["preview_available"])
        raw_delta = result["raw_delta_codes"]
        controls.append(
            {
                "control_seq": str(sequence),
                "decision_timestamp_ticks": str(timestamp_s * 16_000_000),
                "est_input_ref": estimate_id,
                "current_dac_code": str(code),
                "frequency_error_hz": (
                    "" if error is None else f"{error:.12f}"
                ),
                "raw_delta_codes": (
                    "" if raw_delta is None else f"{float(raw_delta):.12f}"
                ),
                "limited_delta_codes": (
                    "" if result["limited_delta_codes"] is None
                    else str(result["limited_delta_codes"])
                ),
                "proposed_dac_code": (
                    "" if result["proposed_code"] is None
                    else str(result["proposed_code"])
                ),
                "policy_version": policy.policy_id,
                "config_hash": policy.config_hash,
                "plant_model_hash": policy.plant_model_hash,
                "control_state": mapped[str(result["state"])],
                "previous_control_state": mapped[previous],
                "decision_reason_code": str(result["reason"]),
                "model_applicability": "applicable",
                "preview_available": "true" if preview else "false",
                "preview_only": "true",
                "actuation_authorized": "false",
                "actionable": "false",
                "step_limited": (
                    "true" if result["step_limited"] else "false"
                ),
                "range_clamped": (
                    "true" if result["range_clamped"] else "false"
                ),
            }
        )

    without_epoch, _ = _controller_parity(controls, estimates)
    with_epoch, replay = _controller_parity(
        controls,
        estimates,
        [{"application_timestamp_s": "2403"}],
    )

    assert not without_epoch.passed
    assert with_epoch.passed
    assert all(item["pass"] for item in replay["comparisons"])


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


def _exact_stage7_transaction_rows(
    part: str = "part_a",
) -> tuple[
    list[dict[str, str]], object, dict[str, str], str
]:
    spec, identities = load_stage7_spec(part, 0xA800)
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


def _write_rows(
    path: Path, fields: list[str], rows: list[dict[str, str]]
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _append_second_stage7_transaction(
    rows: list[dict[str, str]], start_code: int
) -> None:
    """Append an exact clean follow-on transaction to a validated first one."""
    second_code = start_code + 42
    created = dict(rows[1])
    created.update(
        {
            "transaction_record_sequence": "6",
            "authorization_sequence": "2",
            "nonce": "10",
            "request_sequence": "2",
            "decision_sequence": "5",
            "source_first_sequence": "700",
            "source_last_sequence": "1299",
            "decision_timestamp_s": "4800",
            "current_applied_code": str(start_code + 21),
            "requested_delta_codes": "21",
            "requested_code": str(second_code),
            "correction_ordinal": "2",
            "cumulative_after_codes": "42",
            "pre_error_hz": "-0.008333333",
            "accepted_code": "0",
            "accepted_timestamp_s": "0",
            "applied_code": "0",
            "application_sequence": "0",
            "application_timestamp_s": "0",
            "i2c_ok": "false",
            "dac_epoch": "1",
            "estimator_history_reset": "false",
            "correction_count": "1",
            "cumulative_movement_codes": "21",
            "post_error_hz": "0",
            "observed_response_hz": "0",
            "cumulative_response_hz": "0",
            "consecutive_indeterminate": "0",
            "response_class": "unavailable",
            "active_state": "REQUEST_PENDING",
            "reason": "request_created",
            "evidence_state": "request_pending",
        }
    )
    accepted = dict(created)
    accepted.update(
        {
            "transaction_record_sequence": "7",
            "event": "core0_accepted",
            "accepted_code": str(second_code),
            "accepted_timestamp_s": "4800",
            "active_state": "ACCEPTED_AWAITING_APPLICATION",
            "reason": "request_consumed_actionable_cleared",
            "evidence_state": "acceptance_pending",
        }
    )
    application = dict(accepted)
    application.update(
        {
            "transaction_record_sequence": "8",
            "event": "application",
            "applied_code": str(second_code),
            "application_sequence": "2",
            "application_timestamp_s": "4801",
            "i2c_ok": "true",
            "dac_epoch": "2",
            "estimator_history_reset": "true",
            "correction_count": "2",
            "cumulative_movement_codes": "42",
            "active_state": "AWAITING_RESPONSE",
            "reason": "application_preserved",
            "evidence_state": "application_pending",
        }
    )
    response = dict(application)
    response.update(
        {
            "transaction_record_sequence": "9",
            "event": "response",
            "post_error_hz": "-0.006000000",
            "observed_response_hz": "0.002333333",
            "cumulative_response_hz": "0.004000000",
            "active_state": "DISARMED",
            "response_class": "inside_deadband",
            "reason": "post_error_inside_frozen_deadband",
            "evidence_state": "response_pending",
        }
    )
    rows.extend((created, accepted, application, response))


def test_stage7_rehearsal_analyzer_requires_complete_clear_sequence(
    tmp_path: Path,
) -> None:
    run = tmp_path / "rehearsal"
    uf2 = tmp_path / "candidate.uf2"
    uf2.write_bytes(b"rehearsal-uf2")
    from hashlib import sha256

    uf2_sha = sha256(uf2.read_bytes()).hexdigest()
    source_sha = "a" * 64
    config_sha = "b" * 64
    defines = {
        "OTIS_CX317_ACTIVE_START_CODE": "0xA800u",
        "OTIS_CX317_ACTIVE_CORRECTION_LIMIT": "2u",
        "OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES": "42u",
        "OTIS_ENABLE_DUAL_CORE_PARTITION": "1",
        "OTIS_ENABLE_CX317_BOUNDED_ACTIVE": "1",
        "OTIS_GNSS_UART_TX_ENABLED": "0",
        "OTIS_CX317_SELECTED_SPAN_INTERVALS_CONFIG": "120u",
        "OTIS_FC0_STARTUP_INHIBIT_MS": "60000u",
        "OTIS_FC0_CONTROL_READY_CLEAN_WINDOWS": "3u",
        "OTIS_CX317_STARTUP_WARMUP_S": "60u",
        "OTIS_CX317_SETTLING_EXCLUSION_S": "60u",
        "OTIS_CX317_FULL_HISTORY_RESET_S": "180u",
        "OTIS_CX317_RECOVERY_FRESH_SUPPORT_S": "120u",
        "OTIS_CX317_DECISION_CADENCE_S": "240u",
        "OTIS_CX317_MINIMUM_APPLIED_CADENCE_S": "240u",
    }
    build = {
        "provenance": {
            "source": {
                "git_commit": "1" * 40,
                "sha256": source_sha,
                "state": "clean",
            },
            "configuration": {
                "profile_id": "cx317_dual_core_active_rehearsal",
                "sha256": config_sha,
                "defines": defines,
            },
        },
        "artifacts": [
            {
                "name": "candidate.uf2",
                "sha256": uf2_sha,
                "size_bytes": uf2.stat().st_size,
            }
        ],
    }
    build_manifest = tmp_path / "firmware_build_manifest.json"
    build_manifest.write_text(json.dumps(build), encoding="utf-8")
    create_stage7_manifest(
        part="rehearsal",
        start_code=0xA800,
        run_dir=run,
        build_manifest_path=build_manifest,
        serial_device="/dev/cu.test",
    )
    rows, _, _, _ = _exact_stage7_transaction_rows("rehearsal")
    _append_second_stage7_transaction(rows, 0xA800)
    for row in rows:
        row["build_identity"] = f"{source_sha}:{config_sha}"
    _write_rows(
        run / "csv/active_transactions_v1.csv",
        ACTIVE_TRANSACTION_V1_FIELDS,
        rows,
    )

    health_values = {
        ("cx317_active", "state"): "DISARMED",
        ("cx317_active", "evidence_phase"): "evidence_clear",
        ("cx317_active", "confirmed_applied_code"): str(0xA82A),
        ("cx317_active", "correction_count"): "2",
        ("cx317_active", "fail_static"): "false",
        ("dual_core", "partition_fault"): "none",
        ("dual_core", "fail_static"): "false",
        ("dual_core", "telemetry_dropped"): "0",
        ("capture", "dropped_count"): "0",
        ("capture", "pps_count_boundary_dropped_count"): "0",
    }
    health_rows = []
    for value, sequence in (("true", 1), ("false", 2)):
        row = {field: "" for field in HEALTH_FIELDS}
        row.update(
            {
                "record_type": "STS",
                "schema_version": "1",
                "status_seq": str(sequence),
                "timestamp_ticks": str(sequence),
                "status_domain": "rp2040_timer0",
                "component": "pps_gate",
                "status_key": "startup_inhibit_active",
                "status_value": value,
                "severity": "WARN" if value == "true" else "INFO",
                "flags": "0",
            }
        )
        health_rows.append(row)
    for key, value, sequence in (
        ("control_eligible", "true", 3),
    ):
        row = {field: "" for field in HEALTH_FIELDS}
        row.update(
            {
                "record_type": "STS",
                "schema_version": "1",
                "status_seq": str(sequence),
                "timestamp_ticks": str(sequence),
                "status_domain": "rp2040_timer0",
                "component": "pps_gate",
                "status_key": key,
                "status_value": value,
                "severity": "INFO",
                "flags": "0",
            }
        )
        health_rows.append(row)
    for sequence, ((component, key), value) in enumerate(
        health_values.items(), 4
    ):
        row = {field: "" for field in HEALTH_FIELDS}
        row.update(
            {
                "record_type": "STS",
                "schema_version": "1",
                "status_seq": str(sequence),
                "timestamp_ticks": str(sequence),
                "status_domain": "rp2040_timer0",
                "component": component,
                "status_key": key,
                "status_value": value,
                "severity": "INFO",
                "flags": "0",
            }
        )
        health_rows.append(row)
    _write_rows(run / "csv/health.csv", HEALTH_FIELDS, health_rows)

    control = {field: "" for field in CONTROL_PREVIEW_V1_FIELDS}
    control.update(
        {
            "record_type": "CTL",
            "schema_version": "1",
            "control_seq": "6",
            "preview_available": "true",
        }
    )
    _write_rows(
        run / "csv/control_previews_v1.csv",
        CONTROL_PREVIEW_V1_FIELDS,
        [control],
    )
    estimates = []
    for sequence in range(5):
        row = {field: "" for field in ESTIMATE_V2_FIELDS}
        row.update(
            {
                "record_type": "EST",
                "schema_version": "2",
                "estimate_seq": str(sequence),
                "estimator_version": (
                    "cx317_rehearsal_selected_120s_nonoverlap_v1"
                ),
            }
        )
        estimates.append(row)
    _write_rows(run / "csv/estimates_v2.csv", ESTIMATE_V2_FIELDS, estimates)

    state = {
        "terminal": {"result": "healthy_stop"},
        "response_count": 2,
        "part_a_service_load_sent": 60,
        "part_a_service_load_complete": True,
        "part_a_post_service_eligible_control_seq": 6,
    }
    state_path = run / "reports/cx317_active_supervisor_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(state), encoding="utf-8")
    (run / "reports/cx317_active_supervisor_events.jsonl").write_text(
        "", encoding="utf-8"
    )
    (run / "reports/capture_device.log").write_text(
        "file-backed capture log\n", encoding="utf-8"
    )
    (run / "reports/capture_device_state.json").write_text(
        json.dumps(
            {
                "capture_active": False,
                "serial_open": False,
                "normal_command_batch_limit": 1,
                "normal_command_max_age_s": 2.0,
                "write_timeout_s": 1.0,
                "malformed_utf8": 0,
                "parser_errors": 0,
                "reconnect_count": 0,
                "commands_rejected": 0,
                "emergency_aborts_sent": 0,
            }
        ),
        encoding="utf-8",
    )
    raw_dir = run / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / "serial.log").write_text(
        '\n'.join(
            [
                '# OTIS_HOST {"batch_limit":1,"event":"command_ingress_opened",'
                '"normal_command_max_age_s":2.0,"path":"normal.fifo"}',
                '# OTIS_HOST {"event":"emergency_command_ingress_opened",'
                '"path":"emergency.fifo"}',
                '# OTIS_HOST {"commands_rejected":0,"emergency_aborts_sent":0,'
                '"event":"capture_stopped","malformed_utf8":0,'
                '"parser_errors":0,"reconnect_count":0}',
            ]
        )
        + '\n',
        encoding="utf-8",
    )

    output, result = analyze_rehearsal(
        run,
        build_manifest=build_manifest,
        uf2=uf2,
        transport_rehearsal_gate=_sealed_transport_rehearsal_gate(
            tmp_path
        ),
    )
    assert result["status"] == "pass"
    assert all(result["criteria"].values())
    assert json.loads(output.read_text(encoding="utf-8"))[
        "qualification_evidence"
    ] is False


def test_stage7_exact_four_phase_history_and_response_replay() -> None:
    rows, spec, identities, build_identity = _exact_stage7_transaction_rows()
    check, evidence = _transactions(rows, spec, identities, build_identity)
    assert check.passed
    assert evidence["application_count"] == 1
    assert evidence["final_code"] == 0xA815
    assert evidence["all_response_classifications_replay_exactly"] is True


def test_stage7_incomplete_response_preserves_physical_application() -> None:
    rows, spec, identities, build_identity = _exact_stage7_transaction_rows()
    check, evidence = _transactions(
        rows[:-1], spec, identities, build_identity
    )

    assert not check.passed
    assert evidence["application_count"] == 1
    assert evidence["complete_request_group_count"] == 0
    assert evidence["request_group_count"] == 1
    assert evidence["path_codes"] == 21
    assert evidence["net_movement_codes"] == 21
    assert evidence["final_code"] == 0xA815
    assert evidence["all_response_classifications_replay_exactly"] is False


def test_stage7_rejects_cross_phase_request_field_mutation() -> None:
    rows, spec, identities, build_identity = _exact_stage7_transaction_rows()
    rows[3]["nonce"] = "10"
    with pytest.raises(ValueError, match="immutable fields changed"):
        _transactions(rows, spec, identities, build_identity)


def test_stage7_analysis_preserves_valid_prefix_before_malformed_request() -> None:
    rows, spec, identities, build_identity = _exact_stage7_transaction_rows()
    malformed = dict(rows[1])
    malformed.update(
        {
            "transaction_record_sequence": "6",
            "authorization_sequence": "2",
            "request_sequence": "2",
            "accepted_code": str(0xA815),
        }
    )

    check, evidence = _transactions_for_analysis(
        rows + [malformed], spec, identities, build_identity
    )

    assert not check.passed
    assert evidence["validated_prefix_record_count"] == 5
    assert evidence["first_invalid_record_sequence"] == 6
    assert evidence["application_count"] == 1
    assert evidence["complete_request_group_count"] == 1
    assert evidence["request_group_count"] == 2
    assert evidence["path_codes"] == 21
    assert evidence["final_code"] == 0xA815
    assert "non-zero accepted code" in evidence["transaction_validation_error"]


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


def test_stage7_supervisor_rejects_stale_or_faulted_capture_transport(
    tmp_path: Path,
) -> None:
    supervisor = _supervisor(tmp_path)
    state_path = supervisor.run_dir / "reports/capture_device_state.json"
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state = {
        "updated_utc": datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
        "capture_active": True,
        "serial_open": True,
        "command_fifo_configured": True,
        "emergency_command_fifo_configured": True,
        "normal_command_batch_limit": 1,
        "normal_command_max_age_s": 2.0,
        "write_timeout_s": 1.0,
        "malformed_utf8": 0,
        "parser_errors": 0,
        "reconnect_count": 0,
        "commands_rejected": 0,
        "emergency_aborts_sent": 0,
    }
    state_path.write_text(json.dumps(state), encoding="utf-8")

    supervisor._check_capture_transport_state()

    state["commands_rejected"] = 1
    state_path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(ValueError, match="commands_rejected"):
        supervisor._check_capture_transport_state()

    state["commands_rejected"] = 0
    state["updated_utc"] = "1970-01-01T00:00:00Z"
    state_path.write_text(json.dumps(state), encoding="utf-8")
    with pytest.raises(ValueError, match="state is stale"):
        supervisor._check_capture_transport_state()


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


def test_part_a_service_completion_inhibits_rearm_for_nonzero_terminal_preview(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor = _supervisor(tmp_path)
    supervisor.state.update(
        {
            "manual_start_sent": True,
            "response_count": 1,
            "part_a_service_load_complete": True,
            "part_a_service_load_completed_control_seq": 2,
            "part_a_post_service_eligible_control_seq": None,
            "arm_pending": False,
        }
    )
    controls = supervisor.run_dir / "csv/control_previews_v1.csv"
    controls.write_text(
        "control_seq,preview_available,model_applicability,diagnostic_health,"
        "limited_delta_codes\n"
        "3,true,applicable,healthy,19\n",
        encoding="utf-8",
    )
    commands: list[str] = []
    monkeypatch.setattr(supervisor, "_identity_ready", lambda health: True)
    monkeypatch.setattr(supervisor, "_command", commands.append)
    health = {
        ("cx317_active", "state"): "DISARMED",
        ("cx317_active", "manual_start_confirmed"): "true",
        ("cx317_active", "correction_count"): "1",
        ("cx317_active", "arm_eligible"): "true",
        ("cx317_active", "evidence_phase"): "evidence_clear",
        ("cx317_active", "selected_interval_count"): "599",
        ("cx317_active", "uptime_s"): "4500",
    }

    supervisor._maybe_start_or_arm(health)

    assert commands == []
    assert supervisor.state["authorization_sequence"] == 0


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


def test_part_b_rehearsal_traverses_all_four_service_bursts(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor = _supervisor(tmp_path, part="part_b", start_code=0xA82A)
    supervisor.state["qualification_started_utc"] = "1970-01-01T00:00:00Z"
    commands: list[str] = []
    wall = 3599.0
    monkeypatch.setattr(supervisor, "_command", commands.append)
    monkeypatch.setattr(
        "host.otis_tools.cx317_stage7_supervisor.time.time",
        lambda: wall,
    )
    monotonic = 1.0
    supervisor._service_load(monotonic)
    assert commands == []

    for burst_index, burst_start in enumerate((3600, 25200, 46800, 68400)):
        wall = float(burst_start)
        for _ in range(60):
            supervisor._service_load(monotonic)
            monotonic += 1.01
        supervisor._service_load(monotonic)
        monotonic += 1.01
        assert supervisor.state["part_b_service_bursts_complete"] == list(
            range(burst_index + 1)
        )

    assert commands == ["CONFIG?"] * 240
    assert supervisor.state["part_b_service_burst_index"] is None
    assert supervisor.state["part_b_service_burst_sent"] == 0


def test_part_b_service_burst_and_one_shot_authorization_never_overlap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor = _supervisor(tmp_path, part="part_b", start_code=0xA82A)
    supervisor.state["qualification_started_utc"] = "1970-01-01T00:00:00Z"
    commands: list[str] = []
    monkeypatch.setattr(supervisor, "_command", commands.append)
    monkeypatch.setattr(
        "host.otis_tools.cx317_stage7_supervisor.time.time",
        lambda: 3600.0,
    )

    supervisor.state["arm_pending"] = True
    supervisor._service_load(1.0)
    assert commands == []
    assert supervisor.state["part_b_service_burst_index"] is None

    supervisor.state["arm_pending"] = False
    supervisor._service_load(1.0)
    assert commands == ["CONFIG?"]
    assert supervisor.state["part_b_service_burst_index"] == 0

    controls = supervisor.run_dir / "csv/control_previews_v1.csv"
    controls.write_text(
        "control_seq,preview_available,decision_timestamp_ticks,"
        "limited_delta_codes\n"
        "10,true,16000000000,19\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(supervisor, "_identity_ready", lambda health: True)
    health = {
        ("cx317_active", "state"): "DISARMED",
        ("cx317_active", "manual_start_confirmed"): "true",
        ("cx317_active", "correction_count"): "0",
        ("cx317_active", "arm_eligible"): "true",
        ("cx317_active", "evidence_phase"): "evidence_clear",
        ("cx317_active", "selected_interval_count"): "599",
        ("cx317_active", "uptime_s"): "4200",
    }
    supervisor._maybe_start_or_arm(health)
    assert commands == ["CONFIG?"]

    supervisor.state["part_b_service_burst_sent"] = 60
    supervisor._service_load(2.01)
    assert supervisor.state["part_b_service_burst_index"] is None
    assert supervisor.state["part_b_arm_resume_after_control_seq"] == 10

    supervisor._maybe_start_or_arm(health)
    assert commands == ["CONFIG?"]

    with controls.open("a", encoding="utf-8") as handle:
        handle.write("11,true,25600000000,19\n")
    supervisor._maybe_start_or_arm(health)
    assert commands == ["CONFIG?"]
    assert supervisor.state["part_b_arm_resume_after_control_seq"] is None


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


def test_part_b_boundary_transaction_can_clear_inside_grace(
    tmp_path: Path,
) -> None:
    supervisor = _supervisor(tmp_path, part="part_b", start_code=0xA82A)
    supervisor.state.update(
        {
            "qualification_started_utc": "1970-01-01T00:00:00Z",
            "arm_pending": True,
            "duration_elapsed": False,
            "part_b_service_bursts_complete": [0, 1, 2, 3],
        }
    )
    outstanding = {
        ("cx317_active", "state"): "AWAITING_RESPONSE",
        ("cx317_active", "evidence_phase"): "application_preserved",
    }
    supervisor._maybe_finish(outstanding, float(PART_B_DURATION_S))
    assert supervisor.state["duration_elapsed"] is True
    assert supervisor.state["terminal"] is None

    supervisor.state["arm_pending"] = False
    clear = {
        ("cx317_active", "state"): "DISARMED",
        ("cx317_active", "evidence_phase"): "evidence_clear",
    }
    supervisor._maybe_finish(clear, float(PART_B_DURATION_S + 1500))
    assert supervisor.state["terminal"]["result"] == "healthy_stop"
    assert supervisor.state["terminal"]["reason"] == (
        "24h_after_qualification_complete"
    )


def test_part_b_duration_boundary_inhibits_every_new_arm(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor = _supervisor(tmp_path, part="part_b", start_code=0xA82A)
    supervisor.state.update(
        {
            "manual_start_sent": True,
            "arm_pending": False,
            "duration_elapsed": True,
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
        ("cx317_active", "selected_interval_count"): "599",
        ("cx317_active", "uptime_s"): "88800",
    }

    supervisor._maybe_start_or_arm(health)

    assert commands == []
    assert supervisor.state["authorization_sequence"] == 0


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


def test_stage7_cadence_prediction_rejects_the_failed_part_b_boundary(
    tmp_path: Path,
) -> None:
    controls = tmp_path / "control_previews_v1.csv"
    estimates = tmp_path / "estimates_v2.csv"
    # Reproduce the RP2040 timer phase that made three nominal 600 s spans
    # only 1799 integer uptime seconds.  PPS source sequences had advanced by
    # 1803 and therefore falsely predicted an eligible decision in the stopped
    # Part B run.
    modulus = (1 << 32) * 16
    spacing = 9_599_940_352
    eligible_ticks = 763_248_107_312
    unwrapped = [
        eligible_ticks - (75 - index) * spacing for index in range(78)
    ]
    lines = [
        "control_seq,preview_available,decision_timestamp_ticks,"
        "decision_reason_code\n"
    ]
    for index, ticks in enumerate(unwrapped):
        preview = "true" if index == 75 else "false"
        reason = (
            "inside_evidence_deadband"
            if index == 75
            else "decision_cadence_hold"
        )
        lines.append(f"{index},{preview},{ticks % modulus},{reason}\n")
    controls.write_text("".join(lines), encoding="utf-8")
    estimates.write_text("estimate_id,source_count_seq\n", encoding="utf-8")

    assert not _next_selected_interval_is_cadence_eligible(
        controls, estimates
    )


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
