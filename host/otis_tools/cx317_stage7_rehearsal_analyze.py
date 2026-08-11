"""Analyze the diagnostic-only Stage 7 hardware-in-loop rehearsal gate."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import argparse
import csv
import json
from typing import Any

from .contracts import CsvValidationContext, validate_csv
from .cx317_active_campaign import (
    ACTIVE_CSV,
    HEALTH_CSV,
    _latest_health,
    _read_csv,
    validate_transaction_history,
)
from .cx317_bounded_active_supervisor import load_cx317_bounded_active_spec
from .evidence import EVIDENCE_MANIFEST, validate_evidence_snapshot
from .run_loader import (
    CAPTURE_IN_PROGRESS_FLAG,
    COMPLETE_MARKER,
    load_manifest,
)


CONTROL_CSV = Path("csv/control_previews_v1.csv")
ESTIMATES_CSV = Path("csv/estimates_v2.csv")
SUPERVISOR_STATE = Path("reports/cx317_active_supervisor_state.json")
SUPERVISOR_EVENTS = Path("reports/cx317_active_supervisor_events.jsonl")
OUTPUT = Path("reports/stage7_rehearsal_gate.json")
HOST_MARKER_PREFIX = "# OTIS_HOST "
CAPTURE_TOOL = Path(__file__).with_name("capture_device.py")
SUPERVISOR_TOOL = Path(__file__).with_name("cx317_bounded_active_supervisor.py")
SERIAL_COMMANDS_TOOL = Path(__file__).with_name("serial_commands.py")
TRANSPORT_INJECTION_TOOL = Path(__file__).with_name(
    "cx317_stage7_transport_fault_inject.py"
)
TRANSPORT_ANALYZER_TOOL = Path(__file__).with_name(
    "cx317_stage7_transport_rehearsal_analyze.py"
)


def _sha256(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _events(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _host_markers(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    markers: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if line.startswith(HOST_MARKER_PREFIX):
                markers.append(json.loads(line[len(HOST_MARKER_PREFIX) :]))
    return markers


def _transport_rehearsal_binding(gate_path: Path) -> dict[str, Any]:
    gate_path = gate_path.resolve()
    if (
        gate_path.name != "stage7_rehearsal_gate.json"
        or gate_path.parent.name != "reports"
    ):
        raise ValueError("transport rehearsal gate path is not canonical")
    run_dir = gate_path.parent.parent
    if (run_dir / CAPTURE_IN_PROGRESS_FLAG).exists():
        raise ValueError("transport rehearsal capture is still active")
    if not (run_dir / COMPLETE_MARKER).is_file():
        raise ValueError("transport rehearsal is not marked complete")
    manifest = load_manifest(run_dir)
    gate = json.loads(gate_path.read_text(encoding="utf-8"))
    snapshot_path = run_dir / EVIDENCE_MANIFEST
    snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))
    bindings = gate.get("bindings", {})
    criteria = gate.get("criteria", {})
    failures, warnings = validate_evidence_snapshot(run_dir, manifest)
    valid = (
        manifest.data.get("stage")
        == "CX317_STAGE7_TRANSPORT_FAULT_REHEARSAL"
        and manifest.data.get("diagnostic_only") is True
        and manifest.data.get("qualification_evidence") is False
        and manifest.data.get("stage7_progression_authority") is False
        and gate.get("status") == "pass"
        and gate.get("tool")
        == "cx317_stage7_transport_rehearsal_analyze_v1"
        and gate.get("run_dir") == str(run_dir)
        and bool(criteria)
        and all(value is True for value in criteria.values())
        and bindings.get("capture_tool_sha256") == _sha256(CAPTURE_TOOL)
        and bindings.get("supervisor_sha256") == _sha256(SUPERVISOR_TOOL)
        and bindings.get("serial_commands_sha256")
        == _sha256(SERIAL_COMMANDS_TOOL)
        and bindings.get("injection_tool_sha256")
        == _sha256(TRANSPORT_INJECTION_TOOL)
        and bindings.get("analyzer_tool_sha256")
        == _sha256(TRANSPORT_ANALYZER_TOOL)
        and snapshot.get("run_state") == "complete"
        and not failures
        and not warnings
    )
    if not valid:
        raise ValueError("transport rehearsal is not an exact sealed pass")
    return {
        "path": str(gate_path),
        "sha256": _sha256(gate_path),
        "run_manifest": {
            "path": str(manifest.path.resolve()),
            "sha256": _sha256(manifest.path),
        },
        "evidence_snapshot": {
            "path": str(snapshot_path.resolve()),
            "sha256": _sha256(snapshot_path),
            "snapshot_digest": snapshot["snapshot_digest"],
        },
        "bindings": bindings,
    }


def _selected_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open("r", newline="", encoding="utf-8") as handle:
        return [
            row
            for row in csv.DictReader(handle)
            if row.get("estimator_version")
            == "cx317_rehearsal_selected_120s_nonoverlap_v1"
        ]


def analyze(
    run_dir: Path,
    *,
    build_manifest: Path,
    uf2: Path,
    transport_rehearsal_gate: Path,
) -> tuple[Path, dict[str, Any]]:
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    state = json.loads((run_dir / SUPERVISOR_STATE).read_text(encoding="utf-8"))
    events = _events(run_dir / SUPERVISOR_EVENTS)
    spec, identities = load_cx317_bounded_active_spec("rehearsal", 0xA800)
    build_identity = manifest["firmware"]["build_identity"]
    transport_binding = _transport_rehearsal_binding(
        transport_rehearsal_gate
    )

    act_path = run_dir / ACTIVE_CSV
    validation = validate_csv(
        act_path,
        CsvValidationContext(
            "active_transactions_v1", frozenset(), frozenset()
        ),
    )
    act_rows = _read_csv(act_path)
    history_error: str | None = None
    try:
        validate_transaction_history(
            act_rows,
            spec,
            identities,
            build_identity,
            dual_core=True,
        )
    except ValueError as exc:
        history_error = str(exc)

    event_names = [row.get("event") for row in act_rows]
    expected_events = ["manual_start"] + [
        event
        for _ in range(2)
        for event in (
            "request_created",
            "core0_accepted",
            "application",
            "response",
        )
    ]
    applications = [
        row for row in act_rows if row.get("event") == "application"
    ]
    responses = [row for row in act_rows if row.get("event") == "response"]
    requests = [
        row for row in act_rows if row.get("event") == "request_created"
    ]
    first_application = applications[0] if applications else {}
    second_application = applications[1] if len(applications) > 1 else {}
    health = _latest_health(run_dir / HEALTH_CSV)
    health_rows = _read_csv(run_dir / HEALTH_CSV)
    pps_startup_values = [
        row.get("status_value")
        for row in health_rows
        if row.get("component") == "pps_gate"
        and row.get("status_key") == "startup_inhibit_active"
    ]
    selected = _selected_rows(run_dir / ESTIMATES_CSV)
    controls = _read_csv(run_dir / CONTROL_CSV)
    post_service_seq = state.get("part_a_post_service_eligible_control_seq")
    event_faults = [
        item
        for item in events
        if item.get("event") in {
            "stage7_supervisor_fault",
            "device_abort_submission_failed",
        }
        or item.get("command") == "ACTIVE ABORT"
    ]
    submitted_commands = [
        item.get("command")
        for item in events
        if item.get("event") == "command_submitted"
    ]
    acknowledged_commands = [
        item.get("command")
        for item in events
        if item.get("event") == "command_acknowledged"
    ]
    host_markers = _host_markers(run_dir / "raw/serial.log")
    capture_stopped = [
        row for row in host_markers if row.get("event") == "capture_stopped"
    ]
    normal_ingress = [
        row
        for row in host_markers
        if row.get("event") == "command_ingress_opened"
    ]
    emergency_ingress = [
        row
        for row in host_markers
        if row.get("event") == "emergency_command_ingress_opened"
    ]
    capture_transport_state = json.loads(
        (run_dir / "reports/capture_device_state.json").read_text(
            encoding="utf-8"
        )
    )
    host_contract = manifest.get("host", {})

    build = json.loads(build_manifest.read_text(encoding="utf-8"))
    build_artifact = next(
        item
        for item in build["artifacts"]
        if item["name"].endswith(".uf2")
    )
    criteria = {
        "diagnostic_identity_cannot_claim_qualification": (
            manifest.get("diagnostic_only") is True
            and manifest.get("qualification_evidence") is False
            and manifest.get("stage7_progression_authority") is False
            and manifest["firmware"]["profile_id"] == spec.profile
            and manifest["active_campaign"]["run_identity"]
            == spec.run_identity
        ),
        "priority_transport_fault_rehearsal_passed": bool(
            transport_binding
        ),
        "exact_clean_build_and_uf2": (
            build["provenance"]["source"]["state"] == "clean"
            and manifest["firmware"]["source_state"] == "clean"
            and manifest["firmware"]["build_manifest_sha256"]
            == _sha256(build_manifest)
            and build_artifact["sha256"] == _sha256(uf2)
            and manifest["firmware"]["uf2_sha256"] == _sha256(uf2)
        ),
        "active_contract_valid": not validation.errors and history_error is None,
        "pps_backend_startup_inhibit_completed": (
            "true" in pps_startup_values
            and "false" in pps_startup_values
            and health.get(("pps_gate", "startup_inhibit_active")) == "false"
            and health.get(("pps_gate", "control_eligible")) == "true"
        ),
        "exact_two_complete_consecutive_transactions": (
            event_names == expected_events
        ),
        "exact_first_a800_to_a815_application": (
            first_application.get("current_applied_code") == str(0xA800)
            and first_application.get("requested_delta_codes") == "21"
            and first_application.get("applied_code") == str(0xA815)
            and first_application.get("i2c_ok") == "true"
            and first_application.get("ambiguous") == "false"
            and first_application.get("clamped") == "false"
        ),
        "second_request_clears_prior_acceptance_and_application": (
            len(requests) == 2
            and requests[1].get("accepted_code") == "0"
            and requests[1].get("accepted_timestamp_s") == "0"
            and requests[1].get("applied_code") == "0"
            and requests[1].get("application_sequence") == "0"
            and requests[1].get("application_timestamp_s") == "0"
        ),
        "second_application_is_single_bounded_follow_on": (
            len(applications) == 2
            and second_application.get("current_applied_code")
            == str(0xA815)
            and 0
            < abs(int(second_application.get("requested_delta_codes", "0")))
            <= 21
            and second_application.get("requested_code")
            == second_application.get("applied_code")
            and second_application.get("i2c_ok") == "true"
            and second_application.get("ambiguous") == "false"
            and second_application.get("clamped") == "false"
        ),
        "both_responses_completed_without_fault_class": (
            len(responses) == 2
            and all(
                response.get("response_class")
                in {
                    "healthy_detected",
                    "healthy_indeterminate_near_resolution",
                    "inside_deadband",
                    "limit_reached",
                }
                and response.get("active_state") == "DISARMED"
                for response in responses
            )
        ),
        "sixty_query_service_load_completed": (
            state.get("part_a_service_load_sent") == 60
            and state.get("part_a_service_load_complete") is True
        ),
        "later_cadence_eligible_decision_observed": (
            isinstance(post_service_seq, int)
            and any(
                int(row.get("control_seq", "-1")) == post_service_seq
                and row.get("preview_available") == "true"
                for row in controls
            )
        ),
        "supervisor_healthy_stop": (
            state.get("terminal", {}).get("result") == "healthy_stop"
            and state.get("response_count") == 2
            and not event_faults
        ),
        "final_device_disarmed_evidence_clear": (
            health.get(("cx317_active", "state")) == "DISARMED"
            and health.get(("cx317_active", "evidence_phase"))
            == "evidence_clear"
            and health.get(("cx317_active", "confirmed_applied_code_known"))
            == "true"
            and health.get(("cx317_active", "confirmed_applied_code"))
            == second_application.get("applied_code")
            and health.get(("cx317_active", "correction_count")) == "2"
        ),
        "partition_capture_and_transport_remained_clean": (
            health.get(("dual_core", "partition_fault")) in {None, "none"}
            and health.get(("dual_core", "fail_static")) in {None, "false"}
            and health.get(("cx317_active", "fail_static")) == "false"
            and health.get(("capture", "dropped_count")) in {None, "0"}
            and health.get(("capture", "pps_count_boundary_dropped_count"))
            in {None, "0"}
            and health.get(("dual_core", "telemetry_dropped")) in {None, "0"}
        ),
        "host_priority_transport_exact_and_clean": (
            bool(submitted_commands)
            and submitted_commands == acknowledged_commands
            and host_contract.get(
                "manual_start_before_first_control_required"
            )
            is True
            and host_contract.get("faulted_control_never_armed") is True
            and len(capture_stopped) == 1
            and len(normal_ingress) == 1
            and len(emergency_ingress) == 1
            and normal_ingress[0].get("batch_limit") == 1
            and normal_ingress[0].get("normal_command_max_age_s") == 2.0
            and normal_ingress[0].get("path")
            != emergency_ingress[0].get("path")
            and all(
                int(capture_stopped[0].get(key, -1)) == 0
                for key in (
                    "malformed_utf8",
                    "parser_errors",
                    "reconnect_count",
                    "commands_rejected",
                    "emergency_aborts_sent",
                )
            )
            and (run_dir / "reports/capture_device.log").is_file()
            and capture_transport_state.get("capture_active") is False
            and capture_transport_state.get("serial_open") is False
            and capture_transport_state.get("state_heartbeat_interval_s")
            == 5.0
            and capture_transport_state.get("normal_command_batch_limit")
            == 1
            and capture_transport_state.get("normal_command_max_age_s")
            == 2.0
            and capture_transport_state.get("write_timeout_s") == 1.0
            and all(
                int(capture_transport_state.get(key, -1)) == 0
                for key in (
                    "malformed_utf8",
                    "parser_errors",
                    "reconnect_count",
                    "commands_rejected",
                    "emergency_aborts_sent",
                )
            )
        ),
        "rehearsal_selected_estimator_observed": len(selected) >= 5,
        "capture_closed_before_gate": not (
            run_dir / CAPTURE_IN_PROGRESS_FLAG
        ).exists(),
    }
    result = {
        "schema_version": 1,
        "tool": "cx317_stage7_rehearsal_analyze_v3",
        "status": "pass" if all(criteria.values()) else "fail",
        "diagnostic_only": True,
        "qualification_evidence": False,
        "stage7_progression_authority": False,
        "run_dir": str(run_dir.resolve()),
        "criteria": criteria,
        "transaction_events": event_names,
        "response_classes": [row.get("response_class") for row in responses],
        "selected_estimate_count": len(selected),
        "active_contract_errors": validation.errors,
        "transaction_history_error": history_error,
        "event_faults": event_faults,
        "priority_transport_fault_rehearsal": transport_binding,
        "final": {
            "active_state": health.get(("cx317_active", "state")),
            "evidence_phase": health.get(("cx317_active", "evidence_phase")),
            "applied_code": health.get(
                ("cx317_active", "confirmed_applied_code")
            ),
            "applied_code_known": health.get(
                ("cx317_active", "confirmed_applied_code_known")
            ),
        },
    }
    output = run_dir / OUTPUT
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return output, result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--build-manifest", type=Path, required=True)
    parser.add_argument("--uf2", type=Path, required=True)
    parser.add_argument(
        "--transport-rehearsal-gate", type=Path, required=True
    )
    args = parser.parse_args(argv)
    output, result = analyze(
        args.run_dir,
        build_manifest=args.build_manifest,
        uf2=args.uf2,
        transport_rehearsal_gate=args.transport_rehearsal_gate,
    )
    print(output)
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
