"""Analyze and seal an exact no-write qualification rehearsal."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .active_status_contract import (
    evaluate_solicited_attach_snapshot_history,
    latest_complete_health,
)
from .board_identity import EXPECTED_SERIAL
from .contracts import CsvValidationContext, validate_csv
from .cx317_active_campaign import ACTIVE_CSV, HEALTH_CSV, _read_csv
from .tight_deadband_rehearsal_analyze import (
    CAPTURE_STATE,
    SUPERVISOR_EVENTS,
    SUPERVISOR_STATE,
    _authority_false,
    _capture_closure,
    _capture_duration,
    _contract_path,
    _host_markers,
)
from .tight_deadband_supervisor import (
    CONTROL_CSV,
    DAC_CSV,
    ENVIRONMENT_CSV,
    ESTIMATES_CSV,
    HPR_CSV,
    PHE_CSV,
    RPH_CSV,
    TDB_CSV,
)
from .tight_deadband_replay import replay_tight_deadband_chain
from .no_write_qualification_bundle import (
    EMERGENCY_COMMAND,
    FORBIDDEN_COMMAND_PREFIXES,
    REHEARSAL_DURATION_S,
    TRANSITION_RUN_DIR,
    normal_command_allowed,
    validate_run_manifest,
)
from .no_write_qualification_supervisor import load_no_write_qualification_spec
from .no_write_prewrite_readiness_contract import (
    RUNTIME_CONTRACT_ID,
    environment_streams_ready,
    evaluate_prewrite_readiness,
    evaluate_telemetry_drop_history,
)
from .evidence import EVIDENCE_MANIFEST
from .run_loader import CAPTURE_IN_PROGRESS_FLAG, COMPLETE_MARKER, load_manifest


TOOL_ID = "cx319_g1_analyze_v1"
ANALYSIS_TYPE = "cx319_g1_exact_no_write_rehearsal_analysis_v1"
SEAL_TYPE = "cx319_g1_no_write_rehearsal_seal_v1"
ANALYSIS_PATH = Path("reports/cx319_g1_analysis_v1.json")
REPORT_PATH = Path("reports/CX319_G1_REHEARSAL.md")
SEAL_PATH = Path("reports/cx319_g1_rehearsal_seal_v1.json")
FLASH_RECORD_PATH = Path("reports/cx319_g1_flash_v1.json")
TRANSPORT_REPORT_PATH = Path("reports/cx319_g1_transport_rehearsal_v1.json")


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _atomic_new_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite immutable result: {path}")
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _command_allowed(command: str) -> bool:
    return command == EMERGENCY_COMMAND or normal_command_allowed(command)


def _authority_false_or_absent(path: Path) -> bool:
    rows = _read_csv(path)
    return not rows or _authority_false(path)


def _post_abort_health_exact(
    primary: dict[tuple[str, str], str],
    transition: dict[tuple[str, str], str],
    rows: list[dict[str, str]] | None = None,
) -> bool:
    pre_abort_exact = (
        primary.get(("cx317_active", "state")) == "DISARMED"
        and primary.get(("cx317_active", "fail_static")) == "false"
    )
    periodic_snapshot_exact = (
        transition.get(("cx317_active", "state")) == "ABORTED"
        and transition.get(("cx317_active", "reason"))
        == "device_abort_command_via_core0"
        and transition.get(("cx317_active", "fail_static")) == "true"
    )
    critical_ack_exact = False
    if rows:
        for queued, accepted in zip(rows, rows[1:]):
            try:
                consecutive = int(accepted["status_seq"]) == int(
                    queued["status_seq"]
                ) + 1
            except (KeyError, TypeError, ValueError):
                consecutive = False
            if (
                consecutive
                and queued.get("component") == "cx317_active"
                and queued.get("status_key") == "abort"
                and queued.get("status_value") == "queued_to_core1"
                and accepted.get("component") == "cx317_active"
                and accepted.get("status_key") == "critical_record"
                and accepted.get("status_value") == "abort_accepted_on_core1"
            ):
                critical_ack_exact = True
                break
    return pre_abort_exact and (periodic_snapshot_exact or critical_ack_exact)


def _priority_abort_ordered(markers: list[dict[str, Any]]) -> bool:
    events = [str(item.get("event")) for item in markers]
    try:
        latch = events.index("emergency_abort_latched")
        revoke = events.index("normal_command_ingress_revoked", latch + 1)
        accepted = next(
            index
            for index, item in enumerate(markers[revoke + 1 :], revoke + 1)
            if item.get("event") == "host_command_accepted"
            and item.get("command") == EMERGENCY_COMMAND
        )
        sent = next(
            index
            for index, item in enumerate(markers[accepted + 1 :], accepted + 1)
            if item.get("event") == "host_command_sent"
            and item.get("command") == EMERGENCY_COMMAND
        )
        completed = events.index("emergency_abort_sent", sent + 1)
    except (StopIteration, ValueError):
        return False
    ordered = [latch, revoke, accepted, sent, completed]
    return ordered == sorted(ordered)


def analyze(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    if (run_dir / CAPTURE_IN_PROGRESS_FLAG).exists():
        raise ValueError("CX319 G1 capture is still active")
    manifest_value = validate_run_manifest(run_dir / "run_manifest.json")
    q1_real_io = manifest_value.get("q1_real_io")
    expected_reconnects = (
        len(q1_real_io.get("intentional_detach_schedule", []))
        if isinstance(q1_real_io, dict)
        else 0
    )
    manifest = load_manifest(run_dir)
    transition_dir = run_dir / TRANSITION_RUN_DIR
    transition_manifest = load_manifest(transition_dir)
    leg_name = manifest_value["cx319"]["leg"]
    spec, identities, _ = load_no_write_qualification_spec(leg_name)

    validations: dict[str, dict[str, Any]] = {}
    for segment, segment_manifest in (
        ("primary", manifest),
        ("transition", transition_manifest),
    ):
        for contract in manifest_value["contracts"]:
            path = _contract_path(segment_manifest, contract)
            result = validate_csv(
                path,
                CsvValidationContext(
                    contract=contract,
                    known_channels=segment_manifest.known_channels,
                    known_domains=segment_manifest.known_domains,
                    allow_rp2040_timer0_wrap=True,
                    tight_deadband_policy_sha256=manifest_value["policy"][
                        "sha256"
                    ],
                ),
            )
            validations[f"{segment}:{contract}"] = {
                "ok": result.ok,
                "rows": result.row_count,
                "errors": result.errors,
            }

    active_rows = _read_csv(run_dir / ACTIVE_CSV)
    dac_rows = _read_csv(run_dir / DAC_CSV)
    transition_active_rows = _read_csv(transition_dir / ACTIVE_CSV)
    transition_dac_rows = _read_csv(transition_dir / DAC_CSV)
    estimates = [
        row
        for row in _read_csv(run_dir / ESTIMATES_CSV)
        if row.get("estimator_version")
        == "cx317_selected_600s_nonoverlap_v1"
    ]
    tdb_replay = replay_tight_deadband_chain(
        [run_dir / TDB_CSV, transition_dir / TDB_CSV],
        policy_sha256=manifest_value["policy"]["sha256"],
    )
    health_rows = _read_csv(run_dir / HEALTH_CSV)
    health = latest_complete_health(run_dir / HEALTH_CSV)
    transition_health_rows = _read_csv(transition_dir / HEALTH_CSV)
    transition_health = latest_complete_health(
        transition_dir / HEALTH_CSV
    )
    expected_build = (
        manifest_value["firmware"]["source_sha256"]
        + ":"
        + manifest_value["firmware"]["configuration_sha256"]
    )
    identity = {
        "run_identity": spec.run_identity,
        "build_identity": expected_build,
        "profile_identity": spec.profile,
        **identities,
    }
    supervisor_state = json.loads((run_dir / SUPERVISOR_STATE).read_text())
    telemetry_drop_baseline = int(
        supervisor_state["telemetry_drop_baseline"]
    )
    telemetry_drop_baseline_status_seq = int(
        supervisor_state["telemetry_drop_baseline_status_seq"]
    )
    readiness = evaluate_prewrite_readiness(
        health,
        expected_identity=identity,
        planned_live_stimulus_code=spec.start_code,
        active_row_count=len(active_rows),
        dac_row_count=len(dac_rows),
        telemetry_drop_baseline=telemetry_drop_baseline,
    )
    telemetry_drop_history = evaluate_telemetry_drop_history(
        [*health_rows, *transition_health_rows],
        frozen_baseline=telemetry_drop_baseline,
        frozen_status_seq=telemetry_drop_baseline_status_seq,
    )
    host_attach_history = evaluate_solicited_attach_snapshot_history(
        [*health_rows, *transition_health_rows],
        query_nonce=int(supervisor_state["host_attach_query_nonce"]),
        frozen_uptime_s=int(supervisor_state["host_attach_uptime_s"]),
        frozen_generation=int(
            supervisor_state["host_attach_snapshot_generation"]
        ),
        maximum_uptime_s=None,
    )
    markers = _host_markers(run_dir / "raw/serial.log")
    duration_s = _capture_duration(markers)
    capture_state = json.loads((run_dir / CAPTURE_STATE).read_text())
    capture_closure = _capture_closure(
        run_dir,
        capture_state,
        markers,
        allowed_emergency_aborts=1,
        allowed_reconnects=expected_reconnects,
    )
    supervisor_events = [
        json.loads(line)
        for line in (run_dir / SUPERVISOR_EVENTS)
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    transport = json.loads((run_dir / TRANSPORT_REPORT_PATH).read_text())
    q1_prelude = (
        json.loads((run_dir / "reports/cx319_q1_real_io_prelude_v1.json").read_text())
        if expected_reconnects
        else None
    )
    q1_evidence_baseline = (
        json.loads(
            (run_dir / "reports/cx319_q1_evidence_session_baseline_v1.json")
            .read_text()
        )
        if expected_reconnects
        else None
    )
    evidence_boundary_history: dict[str, object] = {"exact": True}
    evidence_session_counter_deltas: dict[str, int] = {}
    evidence_session_transport_counter_deltas: dict[str, int] = {}
    if isinstance(q1_evidence_baseline, dict):
        evidence_boundary_history = evaluate_solicited_attach_snapshot_history(
            [*health_rows, *transition_health_rows],
            query_nonce=int(q1_evidence_baseline["query_nonce"]),
            frozen_uptime_s=int(q1_evidence_baseline["firmware_uptime_s"]),
            frozen_generation=int(q1_evidence_baseline["snapshot_generation"]),
            maximum_uptime_s=None,
        )
        for key, baseline_value in q1_evidence_baseline.get(
            "cumulative_counters", {}
        ).items():
            evidence_session_counter_deltas[str(key)] = (
                int(health.get(("cx317_active", str(key)), "0"))
                - int(baseline_value)
            )
        for key, baseline_value in q1_evidence_baseline.get(
            "cumulative_transport_counters", {}
        ).items():
            evidence_session_transport_counter_deltas[str(key)] = (
                int(health.get(("dual_core", str(key)), "0"))
                - int(baseline_value)
            )
    flash = json.loads((run_dir / FLASH_RECORD_PATH).read_text())
    run_bundle = json.loads(
        Path(manifest_value["bundle"]["path"]).read_text(encoding="utf-8")
    )
    firmware_entry = run_bundle.get(
        "firmware_entry",
        {"mode": "single_exact_flash", "firmware_flashes_allowed": 1},
    )
    firmware_entry_ready_ns = flash.get("restart_reappeared_monotonic_ns")
    if firmware_entry_ready_ns is None:
        firmware_entry_ready_ns = flash.get("upload_completed_monotonic_ns")
    carrier_ready_ns = flash.get("carrier_ready_monotonic_ns")
    identity_started_ns = flash.get("post_reset_identity_started_monotonic_ns")
    deferred_identity_ordered = (
        expected_reconnects == 0
        or flash.get("attachment_mode") == "running_instrument"
        or (
            flash.get("post_reset_identity_order")
            == "carrier_then_board_enumeration"
            and isinstance(firmware_entry_ready_ns, int)
            and isinstance(carrier_ready_ns, int)
            and isinstance(identity_started_ns, int)
            and firmware_entry_ready_ns < carrier_ready_ns <= identity_started_ns
        )
    )
    single_flash_exact = (
        firmware_entry.get("mode") == "single_exact_flash"
        and flash.get("operation") == "exact_cx319_g1_firmware_flash"
        and flash.get("status") == "pass"
        and flash.get("attempt_count") == 1
        and flash.get("board_before") == flash.get("board_after")
        and flash.get("board_after", {}).get("serial_number")
        == EXPECTED_SERIAL
        and deferred_identity_ordered
    )
    confirmed_reuse_exact = (
        firmware_entry.get("mode") == "reuse_confirmed_installed_firmware"
        and firmware_entry.get("firmware_flashes_allowed") == 0
        and flash.get("operation")
        == "confirmed_installed_cx319_g1_running_attach"
        and flash.get("status") == "pass"
        and flash.get("attempt_count") == 0
        and flash.get("firmware_flashes") == 0
        and flash.get("board_before") == flash.get("board_after")
        and flash.get("board_after") == flash.get("installed_board")
        and flash.get("board_after", {}).get("serial_number")
        == EXPECTED_SERIAL
        and flash.get("source_flash_record")
        == firmware_entry.get("source_flash_record")
        and flash.get("source_bundle") == firmware_entry.get("source_bundle")
        and flash.get("source_bundle_sha256")
        == firmware_entry.get("source_bundle_sha256")
        and flash.get("source_build_manifest_sha256")
        == firmware_entry.get("source_build_manifest_sha256")
        and flash.get("installed_uf2_sha256")
        == firmware_entry.get("installed_uf2_sha256")
        and flash.get("uf2_sha256") == manifest_value["firmware"]["uf2"]["sha256"]
        and deferred_identity_ordered
    )
    transition_state = json.loads(
        (transition_dir / "reports/capture_device_state.json").read_text()
    )
    transition_closure = json.loads(
        (transition_dir / "reports/capture_segment_closure_v1.json").read_text()
    )
    transition_markers = _host_markers(transition_dir / "raw/serial.log")
    commands_sent = [
        str(item.get("command"))
        for item in markers
        if item.get("event") == "host_command_sent"
    ]
    sources = {
        row.get("source", "").lower()
        for segment_dir in (run_dir, transition_dir)
        for row in _read_csv(segment_dir / ENVIRONMENT_CSV)
    }
    fatal_rows = [
        row
        for row in [*health_rows, *transition_health_rows]
        if row.get("severity") == "FATAL"
    ]
    snapshot_capacity = int(
        health.get(("pps_gate", "snapshot_ring_capacity"), "0")
    )
    snapshot_high_water = int(
        health.get(("pps_gate", "snapshot_backlog_high_water"), "999999")
    )
    terminal = supervisor_state.get("terminal")
    events = [str(item.get("event")) for item in supervisor_events]
    command_allowlist_exact = (
        commands_sent
        and all(_command_allowed(command) for command in commands_sent)
        and not any(
            command.startswith(prefix)
            for command in commands_sent
            for prefix in FORBIDDEN_COMMAND_PREFIXES
        )
        and commands_sent.count(EMERGENCY_COMMAND) == 1
        and _priority_abort_ordered(markers)
        and all(
            any(
                command == required
                or (
                    required == "ACTIVE LEASE"
                    and command.startswith("ACTIVE LEASE ")
                )
                or (
                    required == "ACTIVE SNAPSHOT"
                    and command.startswith("ACTIVE SNAPSHOT ")
                )
                for command in commands_sent
            )
            for required in (
                "CONFIG?",
                "DAC?",
                "FC0?",
                "ACTIVE SNAPSHOT",
                "ACTIVE LEASE",
            )
        )
    )
    checks = {
        "manifest_bundle_profile_build_and_policy_exact": True,
        "exact_firmware_entry_same_board": (
            (single_flash_exact or confirmed_reuse_exact)
            and (
                expected_reconnects == 0
                or single_flash_exact
                or flash.get("attachment_mode") == "running_instrument"
            )
            and flash.get("dac_value_write_attempts") == 0
            and flash.get("setup_stimulus_attempts") == 0
            and flash.get("control_arm_attempts") == 0
        ),
        "all_declared_contracts_validate": all(
            item["ok"] for item in validations.values()
        ),
        "finite_capture_at_least_2700s": duration_s >= REHEARSAL_DURATION_S,
        "capture_closed_by_same_owner_rotation": (
            capture_closure.get("ok") is True
            and capture_closure.get("mode") == "same_owner_logical_rotation"
        ),
        "one_owner_obstruction_and_priority_abort": (
            transport.get("status") == "pass"
            and transport.get("sole_serial_owner_verified") is True
            and transport.get("sole_serial_owner_verified_after_resume") is True
            and transport.get("owner_pid_unchanged_across_obstruction") is True
            and transport.get("normal_fifo_saturated") is True
            and transport.get("priority_abort_observed_in_capture") is True
            and transport.get("owner_handoff", {}).get("status") == "completed"
            and transport.get("owner_handoff", {}).get("serial_reopened") is False
            and transport.get("owner_handoff", {}).get("pid")
            == transport.get("capture_pid")
            and transition_state.get("capture_active") is False
            and transition_state.get("serial_open") is False
            and transition_state.get("physical_serial_open") is False
            and transition_state.get("reconnect_count") == expected_reconnects
            and transition_state.get("pid") == transport.get("capture_pid")
            and transition_closure.get("closure_mode")
            == "physical_serial_close"
            and transition_closure.get("owner_pid")
            == transport.get("capture_pid")
            and transition_closure.get("serial_reopened") is False
            and not any(
                item.get("event") == "host_command_sent"
                for item in transition_markers
            )
        ),
        "normal_commands_exact_no_write_allowlist": command_allowlist_exact,
        "q1_real_io_prelude_exact": (
            expected_reconnects == 0
            or (
                isinstance(q1_prelude, dict)
                and q1_prelude.get("status") == "pass"
                and q1_prelude.get("attachment_mode")
                == "running_instrument"
                and q1_prelude.get("boot_record_required") is False
                and q1_prelude.get("firmware_uptime_limit_s") is None
                and q1_prelude.get("device_snapshot", {}).get(
                    "setup_partition_healthy"
                )
                == "true"
                and isinstance(q1_evidence_baseline, dict)
                and q1_evidence_baseline.get("status") == "acknowledged"
                and evidence_boundary_history.get("exact") is True
                and all(
                    evidence_session_counter_deltas.get(key) == 0
                    for key in (
                        "evidence_request_sequence",
                        "correction_count",
                        "cumulative_movement_codes",
                        "dac_epoch",
                    )
                )
                and evidence_session_counter_deltas.get(
                    "selected_interval_count", -1
                ) >= 0
                and evidence_session_transport_counter_deltas.get(
                    "pre_carrier_records_discarded"
                ) == 0
                and evidence_session_transport_counter_deltas.get(
                    "periodic_service_deferred"
                ) == 0
                and q1_prelude.get("intentional_detach_count")
                == expected_reconnects
                and q1_prelude.get(
                    "all_detach_gaps_below_transport_horizon"
                )
                is True
                and q1_prelude.get("serial_exclusive_requested") is True
                and q1_prelude.get("competing_open_rejected") is True
                and q1_prelude.get("sole_owner_after_probe") is True
                and q1_prelude.get("lease_live_snapshot", {}).get(
                    "capture_lease_live"
                )
                == "true"
                and q1_prelude.get("lease_expired_snapshot", {}).get(
                    "capture_lease_live"
                )
                == "false"
                and q1_prelude.get("lease_expired_snapshot", {}).get(
                    "setup_partition_healthy"
                )
                == "true"
                and supervisor_state.get("q1_boundary_burst_sent") is True
            )
        ),
        "supervisor_exact_no_write_terminal": (
            supervisor_state.get("programme_id")
            == "cx319_stabilized_tight_deadband"
            and supervisor_state.get("cx319_gate") == "G1"
            and supervisor_state.get("cx319_mode") == "no_write_rehearsal"
            and supervisor_state.get("cx319_leg") == leg_name
            and supervisor_state.get("manual_start_sent") is False
            and int(supervisor_state.get("authorization_sequence", -1)) == 0
            and isinstance(terminal, dict)
            and terminal.get("result") == "healthy_stop"
            and "cx319_g1_supervisor_fault" not in events
            and "cx319_exact_setup_requested" not in events
            and "cx319_one_decision_armed" not in events
        ),
        "prewrite_runtime_contract_exact_before_abort": (
            supervisor_state.get("prewrite_contract_ready_utc") is not None
            and supervisor_state.get("latest_prewrite_readiness", {}).get("ready")
            is True
            and supervisor_state.get("latest_prewrite_readiness", {}).get(
                "contract_id"
            )
            == RUNTIME_CONTRACT_ID
            and readiness.contract_id == RUNTIME_CONTRACT_ID
            and readiness.ready
            and telemetry_drop_history["exact"] is True
            and host_attach_history["exact"] is True
            and _post_abort_health_exact(
                health,
                transition_health,
                [*health_rows, *transition_health_rows],
            )
        ),
        "selected_600s_estimate_present": len(estimates) >= 1,
        "tight_deadband_replay_exact": (
            tdb_replay.exact and tdb_replay.row_count >= 1
        ),
        "phase_hybrid_and_tight_zero_authority": all(
            _authority_false(run_dir / relative)
            for relative in (CONTROL_CSV, RPH_CSV, PHE_CSV, HPR_CSV, TDB_CSV)
        )
        and all(
            _authority_false_or_absent(transition_dir / relative)
            for relative in (CONTROL_CSV, RPH_CSV, PHE_CSV, HPR_CSV, TDB_CSV)
        ),
        "both_environment_streams_present": environment_streams_ready(sources),
        "zero_dac_and_active_transactions": (
            not dac_rows
            and not active_rows
            and not transition_dac_rows
            and not transition_active_rows
        ),
        "capture_transport_and_diagnostics_clean": (
            all(
                capture_state.get(key) == 0
                for key in (
                    "malformed_utf8",
                    "parser_errors",
                    "commands_rejected",
                )
            )
            and capture_state.get("reconnect_count") == expected_reconnects
            and capture_state.get("intentional_detach_count")
            == expected_reconnects
            and capture_state.get("emergency_aborts_sent") == 1
            and all(
                transition_state.get(key) == 0
                for key in (
                    "malformed_utf8",
                    "parser_errors",
                    "commands_rejected",
                    "commands_sent",
                    "emergency_aborts_sent",
                )
            )
            and transition_state.get("reconnect_count") == expected_reconnects
            and not fatal_rows
            and health.get(("resource_registry", "valid")) == "true"
            and health.get(("resource_registry", "complete")) == "true"
            and health.get(("resource_registry", "conflict_count")) == "0"
            and health.get(("resource_registry", "binding_failure_count")) == "0"
            and health.get(("memory_budget", "valid")) == "true"
            and snapshot_capacity > 0
            and 0 < snapshot_high_water < snapshot_capacity
        ),
    }
    result: dict[str, Any] = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "analysis_type": ANALYSIS_TYPE,
        "status": "pass" if all(checks.values()) else "fail",
        "run_dir": str(run_dir),
        "leg": leg_name,
        "profile_id": spec.profile,
        "checks": checks,
        "observed": {
            "capture_duration_s": duration_s,
            "selected_600s_estimates": len(estimates),
            "tight_deadband_rows": tdb_replay.row_count,
            "dac_rows": len(dac_rows) + len(transition_dac_rows),
            "active_rows": len(active_rows) + len(transition_active_rows),
            "segment_rows": {
                "primary": {
                    "dac": len(dac_rows),
                    "active": len(active_rows),
                },
                "transition": {
                    "dac": len(transition_dac_rows),
                    "active": len(transition_active_rows),
                },
            },
            "commands_sent": commands_sent,
            "snapshot_backlog_high_water": snapshot_high_water,
            "snapshot_ring_capacity": snapshot_capacity,
            "fatal_rows": len(fatal_rows),
            "expected_intentional_reconnects": expected_reconnects,
            "post_abort_state": transition_health.get(
                ("cx317_active", "state")
            ),
            "post_abort_reason": transition_health.get(
                ("cx317_active", "reason")
            ),
            "post_abort_fail_static": transition_health.get(
                ("cx317_active", "fail_static")
            ),
        },
        "runtime_contract": supervisor_state.get("latest_prewrite_readiness"),
        "telemetry_drop_history": telemetry_drop_history,
        "host_attach_history": host_attach_history,
        "evidence_boundary_history": evidence_boundary_history,
        "evidence_session_counter_deltas": evidence_session_counter_deltas,
        "evidence_session_transport_counter_deltas": (
            evidence_session_transport_counter_deltas
        ),
        "capture_closure": capture_closure,
        "contract_validation": validations,
        "tight_deadband_replay": tdb_replay.as_dict(),
        "bindings": {
            "manifest_sha256": _sha256_file(run_dir / "run_manifest.json"),
            "bundle_sha256": manifest_value["bundle"]["bundle_sha256"],
            "build_manifest_sha256": manifest_value["firmware"][
                "build_manifest"
            ]["sha256"],
            "uf2_sha256": manifest_value["firmware"]["uf2"]["sha256"],
            "policy_sha256": manifest_value["policy"]["sha256"],
            "flash_record_sha256": _sha256_file(run_dir / FLASH_RECORD_PATH),
            "firmware_entry_mode": firmware_entry["mode"],
            "transport_report_sha256": _sha256_file(
                run_dir / TRANSPORT_REPORT_PATH
            ),
            "analyzer_sha256": _sha256_file(Path(__file__)),
        },
        "claims_boundary": (
            "G1 no-write operational evidence only; not frequency-control, "
            "calibration, absolute phase, UTC, lock or holdover evidence"
        ),
    }
    result["analysis_sha256"] = _canonical_sha256(result)
    return result


def report_markdown(result: dict[str, Any]) -> str:
    lines = [
        "# CX319 G1 Exact No-Write Rehearsal",
        "",
        f"Status: **{result['status'].upper()}**",
        "",
        "This is exact-profile no-write operational evidence. It does not",
        "authorize or demonstrate a setup stimulus or automatic correction.",
        "",
        "## Gates",
        "",
        *[
            f"- {'PASS' if passed else 'FAIL'} — `{name}`"
            for name, passed in result["checks"].items()
        ],
        "",
        "## Claims boundary",
        "",
        result["claims_boundary"] + ".",
        "",
    ]
    return "\n".join(lines)


def seal(run_dir: Path, analysis: dict[str, Any]) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    if analysis.get("status") != "pass":
        raise ValueError("cannot create a passing G1 seal from failed analysis")
    if not (run_dir / COMPLETE_MARKER).is_file():
        raise ValueError("G1 run is not marked complete")
    evidence_path = run_dir / EVIDENCE_MANIFEST
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    payload: dict[str, Any] = {
        "schema_version": 1,
        "seal_type": SEAL_TYPE,
        "tool": TOOL_ID,
        "status": "pass",
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "leg": analysis["leg"],
        "profile_id": analysis["profile_id"],
        "analysis": {
            "path": ANALYSIS_PATH.as_posix(),
            "sha256": _sha256_file(run_dir / ANALYSIS_PATH),
            "analysis_sha256": analysis["analysis_sha256"],
        },
        "evidence_snapshot": {
            "path": str(EVIDENCE_MANIFEST),
            "sha256": _sha256_file(evidence_path),
            "snapshot_digest": evidence["snapshot_digest"],
            "run_state": evidence["run_state"],
        },
        "bundle_sha256": analysis["bindings"]["bundle_sha256"],
        "uf2_sha256": analysis["bindings"]["uf2_sha256"],
        "setup_writes": 0,
        "dac_value_writes": 0,
        "automatic_writes": 0,
        "control_arms": 0,
        "actuation_authorized": False,
        "qualification_evidence": False,
    }
    payload["seal_sha256"] = _canonical_sha256(payload)
    _atomic_new_json(run_dir / SEAL_PATH, payload)
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args(argv)
    try:
        result = analyze(args.run_dir)
    except (
        FileExistsError,
        FileNotFoundError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        parser.error(str(exc))
    _atomic_new_json(args.run_dir / ANALYSIS_PATH, result)
    (args.run_dir / REPORT_PATH).write_text(
        report_markdown(result), encoding="utf-8"
    )
    print(json.dumps({"status": result["status"]}, sort_keys=True))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
