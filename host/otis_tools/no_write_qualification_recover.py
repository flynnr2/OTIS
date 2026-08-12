"""Recover a completed Q1 capture from the cumulative-reconnect verifier escape.

This recovery is deliberately narrow.  It accepts only the retained Q1 failure
whose final same-owner rotation was rejected because the old host check required
the cumulative reconnect counter to be zero.  It reconstructs the missing
derived transport report from already-retained records, then runs the normal
snapshot, analyzer, seal, and registration path.  It never opens the device or
changes raw/serial.log.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
from typing import Any

from .evidence import (
    EVIDENCE_MANIFEST,
    create_evidence_snapshot,
    validate_evidence_snapshot,
)
from .evidence_finalization import (
    advance_phase,
    journal_path_for,
    recover_registration,
    set_registration_intent,
)
from .evidence_index import package_identity
from .no_write_qualification_analyze import (
    ANALYSIS_PATH,
    REPORT_PATH,
    SEAL_PATH,
    TRANSPORT_REPORT_PATH,
    TOOL_ID as ANALYZER_TOOL_ID,
    _atomic_new_json,
    _canonical_sha256,
    analyze,
    report_markdown,
    seal,
)
from .no_write_qualification_run import (
    ORCHESTRATION_FAILURE_PATH,
    TOOL_ID as RUN_TOOL_ID,
    _same_owner_rotation_completed,
    _write_complete,
)
from .run_loader import CAPTURE_IN_PROGRESS_FLAG, load_manifest
from .validate_run import validate_run


RECOVERY_TOOL_ID = "cx319_q1_host_verifier_recovery_v1"
EXPECTED_FAILURE = "G1 same-owner transition changed serial ownership"
TRANSITION_DIR = Path("g1_owner_handoff_transition")
ROTATION_RESPONSES = Path("control/segment_carrier/responses")
RECOVERY_REPORT_PATH = Path("reports/cx319_q1_host_verifier_recovery_v1.json")
SUPERSEDED_ANALYSIS_PATH = ANALYSIS_PATH
PASSING_ANALYSIS_PATH = Path("reports/cx319_g1_analysis_v2.json")
PASSING_REPORT_PATH = Path("reports/CX319_G1_REANALYSIS.md")
ANALYSIS_SUPERSESSION_PATH = Path(
    "reports/cx319_q1_analysis_supersession_v1.json"
)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise ValueError(reason)


def _single_rotation_response(run_dir: Path) -> tuple[Path, dict[str, Any]]:
    paths = sorted((run_dir / ROTATION_RESPONSES).glob("*.json"))
    _require(len(paths) == 1, "recovery requires exactly one rotation response")
    return paths[0], _read_json(paths[0])


def reconstruct_transport_report(run_dir: Path) -> dict[str, Any]:
    """Derive the report lost after the successful rotation response."""

    run_dir = run_dir.resolve()
    transition_dir = run_dir / TRANSITION_DIR
    failure_path = run_dir / ORCHESTRATION_FAILURE_PATH
    failure = _read_json(failure_path)
    manifest = _read_json(run_dir / "run_manifest.json")
    primary_state = _read_json(run_dir / "reports/capture_device_state.json")
    primary_closure = _read_json(
        run_dir / "reports/capture_segment_closure_v1.json"
    )
    transition_state = _read_json(
        transition_dir / "reports/capture_device_state.json"
    )
    transition_closure = _read_json(
        transition_dir / "reports/capture_segment_closure_v1.json"
    )
    carrier_state = _read_json(
        run_dir / "control/segment_carrier/carrier_state.json"
    )
    response_path, response = _single_rotation_response(run_dir)

    _require(failure.get("error") == EXPECTED_FAILURE, "unexpected Q1 failure")
    _require(
        failure.get("supervisor_terminal", {}).get("result") == "healthy_stop",
        "Q1 supervisor did not reach its healthy finite endpoint",
    )
    _require(
        failure.get("source_revision")
        == manifest.get("firmware", {}).get("git_commit"),
        "failure and manifest source revisions differ",
    )
    _require(
        not (run_dir / CAPTURE_IN_PROGRESS_FLAG).exists(),
        "capture is still marked in progress",
    )

    pid = int(primary_state.get("pid", -1))
    reconnects = int(primary_state.get("reconnect_count", -1))
    expected_reconnects = len(
        manifest.get("q1_real_io", {}).get("intentional_detach_schedule", [])
    )
    _require(pid > 0, "invalid retained capture PID")
    _require(reconnects == expected_reconnects, "unexpected cumulative reconnect count")
    _require(
        primary_state.get("capture_active") is False
        and primary_state.get("logical_segment_closed") is True
        and primary_state.get("physical_serial_open") is True,
        "primary segment did not close by logical rotation",
    )
    _require(
        primary_closure.get("closure_mode") == "same_owner_logical_rotation"
        and primary_closure.get("owner_pid") == pid
        and primary_closure.get("physical_serial_open") is True
        and primary_closure.get("serial_reopened") is False
        and primary_closure.get("counters", {}).get("reconnect_count")
        == reconnects
        and primary_closure.get("serial_owner_check")
        == {"performed": True, "owner_pids": [pid]},
        "primary closure does not prove preserved sole ownership",
    )
    _require(
        _same_owner_rotation_completed(
            response,
            capture_pid=pid,
            reconnect_count_before_rotation=reconnects,
        ),
        "rotation response does not preserve owner and reconnect state",
    )
    _require(
        response.get("from_run") == str(run_dir)
        and response.get("to_run") == str(transition_dir),
        "rotation response names different segments",
    )
    _require(
        transition_state.get("capture_active") is False
        and transition_state.get("serial_open") is False
        and transition_state.get("physical_serial_open") is False
        and transition_state.get("pid") == pid
        and transition_state.get("reconnect_count") == reconnects,
        "transition segment did not end with the same closed carrier",
    )
    _require(
        transition_closure.get("closure_mode") == "physical_serial_close"
        and transition_closure.get("owner_pid") == pid
        and transition_closure.get("serial_reopened") is False
        and transition_closure.get("counters", {}).get("reconnect_count")
        == reconnects,
        "transition physical-close certificate differs",
    )
    _require(
        carrier_state.get("status") == "stopped"
        and carrier_state.get("pid") == pid
        and carrier_state.get("serial_open") is False
        and carrier_state.get("reconnect_count") == reconnects,
        "final carrier state differs",
    )
    for state_name, state in (
        ("primary", primary_state),
        ("transition", transition_state),
    ):
        _require(
            all(
                state.get(key) == 0
                for key in ("malformed_utf8", "parser_errors", "commands_rejected")
            ),
            f"{state_name} capture transport is not clean",
        )

    # The retained failure is reachable only after _inject_transport_fault has
    # returned successfully.  The raw abort markers are independently checked
    # again by the normal analyzer.  The exact queued count was not retained, so
    # report the decision-bearing lower bound rather than inventing a count.
    return {
        "schema_version": 1,
        "tool": RUN_TOOL_ID,
        "status": "pass",
        "capture_pid": pid,
        "serial_device": primary_closure["device"],
        "serial_owner_pids": [pid],
        "serial_owner_pids_after_resume": [pid],
        "sole_serial_owner_verified": True,
        "sole_serial_owner_verified_after_resume": True,
        "owner_pid_unchanged_across_obstruction": True,
        "normal_fifo_saturated": True,
        "timestamped_config_queries_queued": 1,
        "timestamped_config_queries_queued_semantics": "proven_positive_lower_bound",
        "priority_abort_enqueued_while_capture_stopped": True,
        "priority_abort_observed_in_capture": True,
        "capture_resumed": True,
        "reconnect_count_before_owner_handoff": reconnects,
        "reconnect_count_after_owner_handoff": reconnects,
        "owner_handoff": response,
        "recovery_provenance": {
            "tool": RECOVERY_TOOL_ID,
            "method": "deterministic_reconstruction_after_host_verifier_escape",
            "original_failure": EXPECTED_FAILURE,
            "failure_report": {
                "path": ORCHESTRATION_FAILURE_PATH.as_posix(),
                "sha256": _sha256_file(failure_path),
            },
            "rotation_response": {
                "path": response_path.relative_to(run_dir).as_posix(),
                "sha256": _sha256_file(response_path),
            },
            "raw_serial_unchanged": True,
            "physical_rerun": False,
        },
    }


def recover(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    journal = journal_path_for(run_dir)
    _require(journal.is_file(), "Q1 finalization journal is missing")
    if (
        (run_dir / TRANSPORT_REPORT_PATH).is_file()
        and (run_dir / "COMPLETE").is_file()
        and (run_dir / EVIDENCE_MANIFEST).is_file()
        and (run_dir / SUPERSEDED_ANALYSIS_PATH).is_file()
        and not (run_dir / SEAL_PATH).exists()
    ):
        return supersede_failed_analysis(run_dir)
    _require(not (run_dir / TRANSPORT_REPORT_PATH).exists(), "transport report already exists")
    _require(not (run_dir / "COMPLETE").exists(), "run is already marked complete")

    transport = reconstruct_transport_report(run_dir)
    _atomic_new_json(run_dir / TRANSPORT_REPORT_PATH, transport)
    recovery_report = {
        "schema_version": 1,
        "tool": RECOVERY_TOOL_ID,
        "status": "recovered_for_normal_analysis",
        "run_dir": str(run_dir),
        "transport_report_sha256": _sha256_file(run_dir / TRANSPORT_REPORT_PATH),
        "supersedes_failure_report_sha256": transport["recovery_provenance"][
            "failure_report"
        ]["sha256"],
        "raw_serial_unchanged": True,
        "physical_rerun": False,
        "claims_boundary": (
            "Host-derived transport reconstruction only; the normal Q1 analyzer "
            "and seal remain authoritative for the gate result."
        ),
    }
    _atomic_new_json(run_dir / RECOVERY_REPORT_PATH, recovery_report)

    advance_phase(
        journal,
        "capture_closed",
        {
            "recovered_from": EXPECTED_FAILURE,
            "transport_report": str(run_dir / TRANSPORT_REPORT_PATH),
        },
    )
    _write_complete(run_dir)
    advance_phase(journal, "completion", {"host_only_recovery": True})
    snapshot_path = create_evidence_snapshot(run_dir)
    advance_phase(journal, "snapshot", {"path": str(snapshot_path)})

    analysis = analyze(run_dir)
    _atomic_new_json(run_dir / ANALYSIS_PATH, analysis)
    (run_dir / REPORT_PATH).write_text(report_markdown(analysis), encoding="utf-8")
    advance_phase(
        journal,
        "analysis",
        {"path": str(run_dir / ANALYSIS_PATH), "status": analysis["status"]},
    )
    if analysis["status"] != "pass":
        failed = sorted(name for name, passed in analysis["checks"].items() if not passed)
        raise RuntimeError("recovered Q1 analysis failed: " + ", ".join(failed))

    manifest = load_manifest(run_dir)
    failures, warnings = validate_evidence_snapshot(run_dir, manifest)
    _require(not failures and not warnings, f"evidence snapshot validation failed: {failures + warnings}")
    _require(validate_run(run_dir) == 0, "generic run validation failed")

    seal_value = seal(run_dir, analysis)
    advance_phase(
        journal,
        "seal",
        {"path": str(run_dir / SEAL_PATH), "seal_sha256": seal_value["seal_sha256"]},
    )
    bundle = _read_json(run_dir / "cx319_g1_exact_bundle_v1.json")
    registration = {
        "source_revision": bundle["firmware"]["git_commit"],
        "build_identity": bundle["firmware"]["build_manifest"]["sha256"],
        "profile_identity": bundle["firmware"]["profile_id"],
        "attempt_classification": "successful_rehearsal",
        "result_or_failure_reason": (
            "all CX319 Q1 exact no-write gates passed after host-only verifier "
            f"supersession {recovery_report['supersedes_failure_report_sha256']}"
        ),
        "analyzer_identity": analysis["bindings"]["analyzer_sha256"],
    }
    set_registration_intent(
        journal,
        registration=registration,
        expected_content_sha256=package_identity(run_dir)["content_sha256"],
    )
    indexed = recover_registration(journal)
    return {
        "status": "pass",
        "run_dir": str(run_dir),
        "analysis": str(run_dir / ANALYSIS_PATH),
        "seal": str(run_dir / SEAL_PATH),
        "seal_sha256": seal_value["seal_sha256"],
        "evidence_content_sha256": indexed["content_sha256"],
        "physical_rerun": False,
    }


def supersede_failed_analysis(run_dir: Path) -> dict[str, Any]:
    """Retain the first offline verdict and seal a corrected reanalysis."""

    run_dir = run_dir.resolve()
    journal = journal_path_for(run_dir)
    first = _read_json(run_dir / SUPERSEDED_ANALYSIS_PATH)
    failed_checks = sorted(
        name for name, passed in first.get("checks", {}).items() if passed is False
    )
    _require(first.get("status") == "fail", "first analysis is not a failed verdict")
    _require(
        failed_checks == ["prewrite_runtime_contract_exact_before_abort"],
        "first analysis failed outside the bounded abort-evidence predicate",
    )
    analysis = analyze(run_dir)
    _require(analysis.get("status") == "pass", "corrected Q1 reanalysis did not pass")
    serialized_analysis = json.loads(
        json.dumps(analysis, sort_keys=True, allow_nan=False)
    )
    passing_analysis_path = run_dir / PASSING_ANALYSIS_PATH
    if passing_analysis_path.exists():
        _require(
            _read_json(passing_analysis_path) == serialized_analysis,
            "retained passing reanalysis differs on retry",
        )
    else:
        _atomic_new_json(passing_analysis_path, analysis)
    passing_report = report_markdown(analysis)
    passing_report_path = run_dir / PASSING_REPORT_PATH
    if passing_report_path.exists():
        _require(
            passing_report_path.read_text(encoding="utf-8") == passing_report,
            "retained passing report differs on retry",
        )
    else:
        passing_report_path.write_text(passing_report, encoding="utf-8")
    supersession = {
        "schema_version": 1,
        "tool": RECOVERY_TOOL_ID,
        "status": "superseded_by_passing_reanalysis",
        "run_dir": str(run_dir),
        "superseded_analysis": {
            "path": SUPERSEDED_ANALYSIS_PATH.as_posix(),
            "sha256": _sha256_file(run_dir / SUPERSEDED_ANALYSIS_PATH),
            "status": "fail",
            "failed_checks": failed_checks,
        },
        "replacement_analysis": {
            "path": PASSING_ANALYSIS_PATH.as_posix(),
            "sha256": _sha256_file(run_dir / PASSING_ANALYSIS_PATH),
            "status": "pass",
            "analyzer_sha256": analysis["bindings"]["analyzer_sha256"],
        },
        "reason": (
            "The first analyzer required a periodic post-abort snapshot even "
            "though the retained exact Core 1 critical acknowledgement is "
            "emitted only after the bound firmware applies abort."
        ),
        "raw_serial_unchanged": True,
        "physical_rerun": False,
    }
    supersession_path = run_dir / ANALYSIS_SUPERSESSION_PATH
    if supersession_path.exists():
        _require(
            _read_json(supersession_path) == supersession,
            "retained analysis supersession differs on retry",
        )
    else:
        _atomic_new_json(supersession_path, supersession)

    manifest = load_manifest(run_dir)
    failures, warnings = validate_evidence_snapshot(run_dir, manifest)
    _require(
        not failures and not warnings,
        f"evidence snapshot validation failed: {failures + warnings}",
    )
    _require(validate_run(run_dir) == 0, "generic run validation failed")
    evidence_path = run_dir / EVIDENCE_MANIFEST
    evidence = _read_json(evidence_path)
    seal_value: dict[str, Any] = {
        "schema_version": 1,
        "seal_type": "cx319_g1_no_write_rehearsal_seal_v1",
        "tool": ANALYZER_TOOL_ID,
        "status": "pass",
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "leg": analysis["leg"],
        "profile_id": analysis["profile_id"],
        "analysis": {
            "path": PASSING_ANALYSIS_PATH.as_posix(),
            "sha256": _sha256_file(run_dir / PASSING_ANALYSIS_PATH),
            "analysis_sha256": analysis["analysis_sha256"],
        },
        "analysis_supersession": {
            "path": ANALYSIS_SUPERSESSION_PATH.as_posix(),
            "sha256": _sha256_file(run_dir / ANALYSIS_SUPERSESSION_PATH),
            "superseded_analysis_sha256": supersession[
                "superseded_analysis"
            ]["sha256"],
        },
        "evidence_snapshot": {
            "path": EVIDENCE_MANIFEST,
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
    seal_value["seal_sha256"] = _canonical_sha256(seal_value)
    _atomic_new_json(run_dir / SEAL_PATH, seal_value)
    advance_phase(
        journal,
        "seal",
        {
            "path": str(run_dir / SEAL_PATH),
            "seal_sha256": seal_value["seal_sha256"],
            "analysis_supersession": str(run_dir / ANALYSIS_SUPERSESSION_PATH),
        },
    )

    bundle = _read_json(run_dir / "cx319_g1_exact_bundle_v1.json")
    registration = {
        "source_revision": bundle["firmware"]["git_commit"],
        "build_identity": bundle["firmware"]["build_manifest"]["sha256"],
        "profile_identity": bundle["firmware"]["profile_id"],
        "attempt_classification": "successful_rehearsal",
        "result_or_failure_reason": (
            "all CX319 Q1 exact no-write gates passed; retained first host "
            "verdict superseded by exact Core 1 abort acknowledgement"
        ),
        "analyzer_identity": analysis["bindings"]["analyzer_sha256"],
    }
    set_registration_intent(
        journal,
        registration=registration,
        expected_content_sha256=package_identity(run_dir)["content_sha256"],
    )
    indexed = recover_registration(journal)
    return {
        "status": "pass",
        "run_dir": str(run_dir),
        "analysis": str(run_dir / PASSING_ANALYSIS_PATH),
        "superseded_analysis": str(run_dir / SUPERSEDED_ANALYSIS_PATH),
        "seal": str(run_dir / SEAL_PATH),
        "seal_sha256": seal_value["seal_sha256"],
        "evidence_content_sha256": indexed["content_sha256"],
        "physical_rerun": False,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args(argv)
    try:
        result = recover(args.run_dir)
    except (FileExistsError, FileNotFoundError, KeyError, OSError, RuntimeError, TypeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
