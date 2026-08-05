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
from .cx317_stage7_supervisor import load_stage7_spec
from .run_loader import CAPTURE_IN_PROGRESS_FLAG


CONTROL_CSV = Path("csv/control_previews_v1.csv")
ESTIMATES_CSV = Path("csv/estimates_v2.csv")
SUPERVISOR_STATE = Path("reports/cx317_active_supervisor_state.json")
SUPERVISOR_EVENTS = Path("reports/cx317_active_supervisor_events.jsonl")
OUTPUT = Path("reports/stage7_rehearsal_gate.json")


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
    run_dir: Path, *, build_manifest: Path, uf2: Path
) -> tuple[Path, dict[str, Any]]:
    manifest = json.loads((run_dir / "run_manifest.json").read_text(encoding="utf-8"))
    state = json.loads((run_dir / SUPERVISOR_STATE).read_text(encoding="utf-8"))
    events = _events(run_dir / SUPERVISOR_EVENTS)
    spec, identities = load_stage7_spec("rehearsal", 0xA800)
    build_identity = manifest["firmware"]["build_identity"]

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
        "rehearsal_selected_estimator_observed": len(selected) >= 5,
        "capture_closed_before_gate": not (
            run_dir / CAPTURE_IN_PROGRESS_FLAG
        ).exists(),
    }
    result = {
        "schema_version": 1,
        "tool": "cx317_stage7_rehearsal_analyze_v2",
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
        "final": {
            "active_state": health.get(("cx317_active", "state")),
            "evidence_phase": health.get(("cx317_active", "evidence_phase")),
            "applied_code": health.get(
                ("cx317_active", "confirmed_applied_code")
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
    args = parser.parse_args(argv)
    output, result = analyze(
        args.run_dir,
        build_manifest=args.build_manifest,
        uf2=args.uf2,
    )
    print(output)
    return 0 if result["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
