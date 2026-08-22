"""Analyze a CX320 rehearsal or future physical evidence package."""

from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .contracts import CsvValidationContext, validate_csv
from .active_hybrid_programme_contract import programme_from_mapping


TOOL_ID = "cx320_active_hybrid_analyzer_v1"
TERMINAL_DECISIONS = {
    "bounded_active_hybrid_control_passed",
    "phase_influence_not_exercised",
    "first_phase_transaction_passed_sustained_result_incomplete",
    "phase_channel_degraded_frequency_control_retained",
    "hybrid_response_wrong_or_frequency_not_reacquired",
    "hybrid_policy_chatter_or_budget_nonpass",
    "frequency_performance_materially_degraded",
    "right_censored_incomplete",
    "measurement_authority_or_platform_fault",
    "operator_abort",
}


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: dict[str, Any]) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _event_positions(events: list[dict[str, Any]], required: list[str]) -> list[int]:
    positions: list[int] = []
    cursor = -1
    for name in required:
        matches = [
            index
            for index, event in enumerate(events)
            if index > cursor and event.get("event") == name
        ]
        if not matches:
            raise ValueError(f"rehearsal event ordering lacks {name}")
        cursor = matches[0]
        positions.append(cursor)
    return positions


def _validate_scenario(
    scenario: dict[str, Any], *, expected_terminal_reason: str | None = None
) -> None:
    events = scenario.get("events")
    if not isinstance(events, list) or not events:
        raise ValueError("rehearsal scenario lacks events")
    for expected, event in enumerate(events, start=1):
        if event.get("sequence") != expected:
            raise ValueError("rehearsal event sequence is not contiguous")
    if expected_terminal_reason is not None and scenario.get("terminal_reason") != expected_terminal_reason:
        raise ValueError("rehearsal terminal reason differs")


def analyze(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    manifest = _read_object(run_dir / "run_manifest.json")
    programme = programme_from_mapping(manifest)
    trace = _read_object(run_dir / "reports/operational_trace_v1.json")
    if manifest.get("programme_id") != programme.programme_id:
        raise ValueError("unexpected active-hybrid programme identity")
    if manifest.get("mode") != "accelerated_no_io_operational_rehearsal":
        raise ValueError("analyzer expected a no-I/O operational rehearsal")
    if manifest.get("qualification_evidence") is not False:
        raise ValueError("offline rehearsal must not be qualification evidence")
    if manifest.get("physical_actions_performed") != 0:
        raise ValueError("offline rehearsal claims a physical action")
    if manifest.get("authority_effective") is not False:
        raise ValueError("offline rehearsal authority must be non-effective")
    if trace.get("bundle_sha256") != manifest.get("bundle_sha256"):
        raise ValueError("trace and run manifest bundle identities differ")

    decision_path = run_dir / "csv/active_hybrid_decisions_v1.csv"
    validation = validate_csv(
        decision_path,
        CsvValidationContext(
            "active_hybrid_decisions_v1", frozenset(), frozenset()
        ),
    )
    if not validation.ok:
        raise ValueError("active-hybrid decision contract failed: " + "; ".join(validation.errors))
    with decision_path.open(newline="", encoding="utf-8") as handle:
        decisions = list(csv.DictReader(handle))
    material = [row for row in decisions if row["phase_materially_influenced"] == "true"]
    nonzero = [row for row in decisions if float(row["phase_term_hz"]) != 0.0]

    primary = trace.get("modeled_phase_transaction")
    clean_degradation = trace.get("clean_phase_degradation")
    shared_fault = trace.get("shared_fail_static_transport_obstruction")
    abort_failure = trace.get("abort_delivery_failure")
    if not all(
        isinstance(item, dict)
        for item in (primary, clean_degradation, shared_fault, abort_failure)
    ):
        raise ValueError("operational rehearsal lacks required scenario branches")
    _validate_scenario(primary)
    _validate_scenario(clean_degradation)
    _validate_scenario(
        shared_fault, expected_terminal_reason="transport_obstruction_shared_fault"
    )
    _validate_scenario(
        abort_failure, expected_terminal_reason="failed_priority_abort_delivery"
    )
    observational_responses = trace.get("observational_response_classification")
    if programme.response_checkpoint_observational:
        if not isinstance(observational_responses, dict) or (
            observational_responses.get("applicable") is not True
        ):
            raise ValueError(
                "CX322 rehearsal lacks observational response scenarios"
            )
        classes = observational_responses.get("classes")
        expected_classes = {
            "healthy_indeterminate_near_resolution",
            "wrong_sign",
            "growing_error",
            "excess_response",
        }
        if not isinstance(classes, dict) or set(classes) != expected_classes:
            raise ValueError("CX322 rehearsal response-class coverage differs")
        if any(
            not isinstance(item, dict)
            or item.get("state") == "FAIL_STATIC"
            or item.get("later_authority_released") is not True
            or item.get("terminal_reason") is not None
            for item in classes.values()
        ):
            raise ValueError(
                "CX322 admissible response became terminal or blocked later authority"
            )
        if observational_responses.get("invalid_measurement_fails_static") is not True:
            raise ValueError("CX322 invalid measurement did not remain fail-static")

    primary_events = primary["events"]
    _event_positions(
        primary_events,
        [
            "capture_owner_established",
            "exact_identity_confirmed",
            "setup_propagated",
            "progressive_authority_armed",
            "request_created",
            "application_propagated",
            "response_replayed_before_acknowledgement",
            "request_created",
            "application_propagated",
        ],
    )
    if primary.get("later_authority_released") is not True:
        raise ValueError("conditional later authority was not released by the first checkpoint")
    if primary.get("request_outstanding") or primary.get("response_outstanding"):
        raise ValueError("modeled terminal retained transaction authority")
    if primary.get("correction_count", 99) > 4 or primary.get("cumulative_movement_codes", 99) > 84:
        raise ValueError("modeled transaction exceeded global authority budget")

    degradation_events = clean_degradation["events"]
    _event_positions(
        degradation_events,
        [
            "setup_propagated",
            "progressive_authority_armed",
            "phase_authority_revoked_clean_boundary",
        ],
    )
    if clean_degradation.get("state") != "PHASE_DEGRADED_FREQUENCY_ONLY":
        raise ValueError("clean phase invalidity did not retain frequency-only state")

    fault_events = shared_fault["events"]
    obstruction, fail_static, submitted, delivered, closed = _event_positions(
        fault_events,
        [
            "transport_obstruction_detected",
            "fail_static_entered",
            "priority_abort_submitted",
            "priority_abort_delivered",
            "capture_closed",
        ],
    )
    if not obstruction < fail_static < submitted < delivered < closed:
        raise ValueError("abort delivery or capture closure ordering differs")
    close_event = fault_events[closed]
    if close_event.get("ownerless_interval") is not False or close_event.get("owner_count") != 1:
        raise ValueError("rehearsal did not preserve sole serial ownership")
    if close_event.get("logical_rotation") is not True:
        raise ValueError("rehearsal did not exercise logical evidence rotation")
    if abort_failure.get("capture_close_rejected_before_delivery") is not True:
        raise ValueError("failed abort delivery did not hold the sole owner open")

    checks = {
        "active_decision_contract": True,
        "setup_propagated_through_first_consumer": True,
        "one_modeled_phase_material_transaction": len(material) >= 1,
        "first_checkpoint_gates_later_authority": primary.get("later_authority_released") is True,
        "phase_only_degradation_retains_frequency_state": True,
        "shared_fault_is_fail_static": True,
        "priority_abort_submission_and_delivery_distinct": submitted < delivered,
        "failed_abort_delivery_holds_owner_open": True,
        "sole_serial_owner_and_logical_rotation": True,
        "observational_response_classes_are_nonterminal": (
            not programme.response_checkpoint_observational
            or isinstance(observational_responses, dict)
        ),
        "no_physical_io": True,
    }
    if not all(checks.values()):
        raise ValueError(f"active-hybrid rehearsal checks failed: {checks}")

    report: dict[str, Any] = {
        "schema_version": 1,
        "report_type": f"{programme.key}_active_hybrid_operational_rehearsal_analysis_v1",
        "tool": TOOL_ID,
        "tool_sha256": _sha256_file(Path(__file__)),
        "created_utc": datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z"),
        "status": "passed",
        "qualification_evidence": False,
        "physical_actions_performed": 0,
        "run_identity": manifest["run_identity"],
        "bundle_sha256": manifest["bundle_sha256"],
        "policy_sha256": manifest["policy_sha256"],
        "build_identity": manifest["build_identity"],
        "decision_record_count": len(decisions),
        "phase_nonzero_decision_count": len(nonzero),
        "phase_material_decision_count": len(material),
        "checks": checks,
        "scenario_terminal_classifications": (
            {
                "modeled_phase_transaction": "bounded_direct_hybrid_evidence_acquired",
                "clean_phase_degradation": "right_censored_incomplete",
                "shared_fail_static_transport_obstruction": "measurement_authority_or_platform_fault",
                "abort_delivery_failure": "measurement_authority_or_platform_fault",
            }
            if programme.response_checkpoint_observational
            else {
                "modeled_phase_transaction": "first_phase_transaction_passed_sustained_result_incomplete",
                "clean_phase_degradation": "phase_channel_degraded_frequency_control_retained",
                "shared_fail_static_transport_obstruction": "measurement_authority_or_platform_fault",
                "abort_delivery_failure": "measurement_authority_or_platform_fault",
            }
        ),
        "limitations": [
            "Accelerated deterministic observations exercise host and policy state transitions but do not reproduce the physical plant.",
            "Serialized AHY records are non-actionable evidence; no command FIFO or serial device was opened.",
        ],
    }
    if any(value not in programme.terminal_decisions for value in report["scenario_terminal_classifications"].values()):
        raise ValueError("rehearsal used an undeclared terminal classification")
    report["analysis_sha256"] = _canonical_sha256(report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = analyze(args.run_dir)
    rendered = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output is not None:
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
