"""Run the accelerated no-I/O CX319 G2 host operational path.

The actual G2 supervisor state machine emits the setup, arm, and four durable
evidence acknowledgements against deterministic firmware records.  Long plant
timers are compressed into explicit timestamps.  The resulting transcript is
processed by the actual accelerated analyzer, sealed, and packaged for a dry
registration check.  No serial device or hardware command path is opened.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .contracts import CONTRACT_FIELDS
from .cx319_g1_bundle import POLICY_PATH
from .cx319_g2_analyze import analyze
from .cx319_g2_bundle import _sha256_file, validate_proposal
from .cx319_g2_contract import canonical_sha256, normal_command_allowed
from .cx319_g2_runtime_contract import canonical_prewrite_fixture
from .cx319_g2_supervisor import create_supervisor
from .evidence_index import package_identity, register_package, validate_index


TOOL_ID = "cx319_g2_accelerated_operational_rehearsal_v1"


def _atomic_new(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite rehearsal artifact: {path}")
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


def _write_csv(path: Path, fieldnames: list[str], rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _tdb_row(
    *,
    sequence: int,
    estimate: int,
    epoch: int,
    error: int,
    state_before: str,
    state_after: str,
    entry_counter: int,
    eligible: bool,
    reason: str,
) -> dict[str, str]:
    return {
        "record_type": "TDB",
        "schema_version": "1",
        "decision_sequence": str(sequence),
        "estimate_id": f"est:cx317:selected600:{estimate:06d}",
        "decision_timestamp_ticks": str((2400 + sequence * 600) * 16_000_000),
        "time_domain": "rp2040_timer0",
        "capture_session": "1",
        "dac_epoch": str(epoch),
        "integer_edge_error_counts": str(error),
        "absolute_edge_error_counts": str(abs(error)),
        "state_before": state_before,
        "state_after": state_after,
        "entry_counter": str(entry_counter),
        "release_counter": "0",
        "transition": "true",
        "frequency_controller_eligible": str(eligible).lower(),
        "requalified": "false",
        "requalification_reason": "",
        "historical_v2_inside": str(abs(error) <= 3).lower(),
        "symmetric_two_count_inside": str(abs(error) <= 2).lower(),
        "policy_id": "CX318_STAGE5_TIGHT_HYSTERETIC_COUNTS_V1",
        "policy_sha256": _sha256_file(POLICY_PATH),
        "actionable": "false",
        "actuation_authorized": "false",
        "authorization_consumed": "false",
        "reason_codes": reason,
    }


def _write_arm_fixture(run_dir: Path) -> None:
    _write_csv(
        run_dir / "csv/tight_deadband_decisions_v1.csv",
        CONTRACT_FIELDS["tight_deadband_decisions_v1"],
        [
            _tdb_row(
                sequence=0,
                estimate=3,
                epoch=1,
                error=-4,
                state_before="REQUALIFY_OUTSIDE",
                state_after="OUTSIDE",
                entry_counter=0,
                eligible=True,
                reason="outside_loose_evidence",
            )
        ],
    )
    (run_dir / "csv/control_previews_v1.csv").write_text(
        "decision_timestamp_ticks,preview_available,decision_reason_code,"
        "est_input_ref,decision_id,limited_delta_codes,control_state\n"
        "38427843600,true,preview_available_observe_only,"
        "est:cx317:selected600:000001,ctl:1,21,LOCKED_PREVIEW\n"
        "48027796864,false,decision_cadence_hold,"
        "est:cx317:selected600:000002,ctl:2,,LOCKED_PREVIEW\n"
        "57627748416,false,decision_cadence_hold,"
        "est:cx317:selected600:000003,ctl:3,,LOCKED_PREVIEW\n",
        encoding="utf-8",
    )


def _transaction_rows(supervisor, build_identity: str) -> list[dict[str, str]]:  # type: ignore[no-untyped-def]
    common_identity = {
        "record_type": "ACT",
        "schema_version": "1",
        "run_identity": supervisor.spec.run_identity,
        "build_identity": build_identity,
        "profile_identity": supervisor.spec.profile,
        "session_id": "1",
        **supervisor.identities,
        "actionable": "false",
    }
    manual = {
        **common_identity,
        "transaction_record_sequence": "1",
        "event": "manual_start",
        "authorization_sequence": "0",
        "nonce": "0",
        "request_sequence": "0",
        "decision_sequence": "0",
        "source_first_sequence": "0",
        "source_last_sequence": "0",
        "decision_timestamp_s": "100",
        "current_applied_code": str(0xA808),
        "requested_delta_codes": "0",
        "requested_code": str(0xA808),
        "correction_ordinal": "0",
        "cumulative_after_codes": "0",
        "pre_error_hz": "0.000000000",
        "accepted_code": str(0xA808),
        "accepted_timestamp_s": "100",
        "applied_code": str(0xA808),
        "application_sequence": "0",
        "application_timestamp_s": "100",
        "i2c_ok": "true",
        "clamped": "false",
        "ambiguous": "false",
        "dac_epoch": "1",
        "estimator_history_reset": "true",
        "correction_count": "0",
        "cumulative_movement_codes": "0",
        "post_error_hz": "0.000000000",
        "observed_response_hz": "0.000000000",
        "cumulative_response_hz": "0.000000000",
        "consecutive_indeterminate": "0",
        "active_state": "DISARMED",
        "response_class": "unavailable",
        "reason": "manual_start_established",
        "evidence_state": "evidence_clear",
    }
    request_common = {
        **common_identity,
        "authorization_sequence": "1",
        "nonce": "123456789",
        "request_sequence": "1",
        "decision_sequence": "4",
        "source_first_sequence": "3601",
        "source_last_sequence": "4200",
        "decision_timestamp_s": "4200",
        "current_applied_code": str(0xA808),
        "requested_delta_codes": "21",
        "requested_code": str(0xA81D),
        "correction_ordinal": "1",
        "cumulative_after_codes": "21",
        "pre_error_hz": "-0.007245000",
        "dac_epoch": "1",
    }
    phases = [
        {
            "event": "request_created",
            "accepted_code": "0",
            "accepted_timestamp_s": "0",
            "applied_code": "0",
            "application_sequence": "0",
            "application_timestamp_s": "0",
            "i2c_ok": "false",
            "clamped": "false",
            "ambiguous": "false",
            "estimator_history_reset": "false",
            "correction_count": "0",
            "cumulative_movement_codes": "0",
            "post_error_hz": "0.000000000",
            "observed_response_hz": "0.000000000",
            "cumulative_response_hz": "0.000000000",
            "consecutive_indeterminate": "0",
            "active_state": "REQUEST_PENDING",
            "response_class": "unavailable",
            "reason": "one_actionable_request_created",
            "evidence_state": "request_pending",
        },
        {
            "event": "core0_accepted",
            "accepted_code": str(0xA81D),
            "accepted_timestamp_s": "4201",
            "applied_code": "0",
            "application_sequence": "0",
            "application_timestamp_s": "0",
            "i2c_ok": "false",
            "clamped": "false",
            "ambiguous": "false",
            "estimator_history_reset": "false",
            "correction_count": "0",
            "cumulative_movement_codes": "0",
            "post_error_hz": "0.000000000",
            "observed_response_hz": "0.000000000",
            "cumulative_response_hz": "0.000000000",
            "consecutive_indeterminate": "0",
            "active_state": "ACCEPTED_AWAITING_APPLICATION",
            "response_class": "unavailable",
            "reason": "request_consumed_actionable_cleared",
            "evidence_state": "acceptance_pending",
        },
        {
            "event": "application",
            "accepted_code": str(0xA81D),
            "accepted_timestamp_s": "4201",
            "applied_code": str(0xA81D),
            "application_sequence": "1",
            "application_timestamp_s": "4202",
            "i2c_ok": "true",
            "clamped": "false",
            "ambiguous": "false",
            "dac_epoch": "2",
            "estimator_history_reset": "true",
            "correction_count": "1",
            "cumulative_movement_codes": "21",
            "post_error_hz": "0.000000000",
            "observed_response_hz": "0.000000000",
            "cumulative_response_hz": "0.000000000",
            "consecutive_indeterminate": "0",
            "active_state": "AWAITING_RESPONSE",
            "response_class": "unavailable",
            "reason": "applied_history_reset_response_required",
            "evidence_state": "application_pending",
        },
        {
            "event": "response",
            "accepted_code": str(0xA81D),
            "accepted_timestamp_s": "4201",
            "applied_code": str(0xA81D),
            "application_sequence": "1",
            "application_timestamp_s": "4202",
            "i2c_ok": "true",
            "clamped": "false",
            "ambiguous": "false",
            "dac_epoch": "2",
            "estimator_history_reset": "true",
            "correction_count": "1",
            "cumulative_movement_codes": "21",
            "post_error_hz": "-0.002000000",
            "observed_response_hz": "0.005245000",
            "cumulative_response_hz": "0.005245000",
            "consecutive_indeterminate": "0",
            "active_state": "DISARMED",
            "response_class": "healthy_detected",
            "reason": "response_detected_with_commanded_sign",
            "evidence_state": "response_pending",
        },
    ]
    rows = [manual]
    for sequence, phase in enumerate(phases, start=2):
        rows.append(
            {
                **request_common,
                **phase,
                "transaction_record_sequence": str(sequence),
            }
        )
    return rows


def _write_tight_entry(run_dir: Path) -> None:
    rows = [
        _tdb_row(
            sequence=0,
            estimate=10,
            epoch=2,
            error=2,
            state_before="REQUALIFY_OUTSIDE",
            state_after="OUTSIDE",
            entry_counter=1,
            eligible=False,
            reason="tight_entry_pending",
        ),
        _tdb_row(
            sequence=1,
            estimate=11,
            epoch=2,
            error=-2,
            state_before="OUTSIDE",
            state_after="TIGHT_INSIDE",
            entry_counter=0,
            eligible=False,
            reason="tight_entry_confirmed",
        ),
    ]
    _write_csv(
        run_dir / "csv/tight_deadband_decisions_v1.csv",
        CONTRACT_FIELDS["tight_deadband_decisions_v1"],
        rows,
    )


def run(*, proposal_path: Path, output_dir: Path) -> dict[str, Any]:
    proposal = validate_proposal(proposal_path)
    output_dir = output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(f"G2 rehearsal output must be empty: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    artifacts = output_dir / "artifacts"
    artifacts.mkdir()

    build_identity = (
        proposal["firmware"]["source_sha256"]
        + ":"
        + proposal["firmware"]["configuration_sha256"]
    )
    with tempfile.TemporaryDirectory(prefix="cx319-g2-rehearsal-") as raw_temp:
        run_dir = Path(raw_temp) / "run"
        (run_dir / "csv").mkdir(parents=True)
        supervisor = create_supervisor(
            run_dir=run_dir,
            command_fifo=run_dir / "normal.fifo",
            emergency_command_fifo=run_dir / "emergency.fifo",
            abort_fifo=run_dir / "abort.fifo",
            expected_build_identity=build_identity,
        )
        commands: list[dict[str, Any]] = []

        def record(command: str) -> None:
            if not normal_command_allowed(command):
                raise ValueError(f"accelerated supervisor emitted {command!r}")
            commands.append(
                {"path": "normal", "command": command, "acknowledged": True}
            )

        supervisor._command = record  # type: ignore[method-assign]
        for command in ("CONFIG?", "DAC?", "ACTIVE LEASE 1", "ACTIVE?"):
            supervisor._command(command)

        expected_identity = {
            "run_identity": supervisor.spec.run_identity,
            "build_identity": build_identity,
            "profile_identity": supervisor.spec.profile,
            **supervisor.identities,
        }
        health = canonical_prewrite_fixture(
            expected_identity=expected_identity,
            planned_live_stimulus_code=supervisor.spec.start_code,
        )
        supervisor._maybe_start_or_arm(health)
        _write_arm_fixture(run_dir)
        health.update(
            {
                ("cx317_active", "manual_start_confirmed"): "true",
                ("cx317_active", "arm_eligible"): "true",
                ("cx317_active", "confirmed_applied_code_known"): "true",
                ("cx317_active", "confirmed_applied_code"): "0xA808",
                ("cx317_active", "dac_epoch"): "1",
                ("cx317_active", "selected_interval_count"): "0",
                ("cx317_active", "uptime_s"): "3600",
            }
        )
        supervisor._maybe_start_or_arm(health)
        health[("cx317_active", "selected_interval_count")] = "520"
        health[("cx317_active", "uptime_s")] = "4120"
        supervisor._maybe_start_or_arm(health)

        transaction_rows = _transaction_rows(supervisor, build_identity)
        _write_csv(
            run_dir / "csv/active_transactions_v1.csv",
            CONTRACT_FIELDS["active_transactions_v1"],
            transaction_rows,
        )
        supervisor._process_transactions()
        _write_tight_entry(run_dir)
        final_health = dict(health)
        final_health.update(
            {
                ("cx317_active", "state"): "DISARMED",
                ("cx317_active", "evidence_phase"): "evidence_clear",
                ("cx317_active", "correction_count"): "1",
                ("cx317_active", "cumulative_movement_codes"): "21",
                ("cx317_active", "dac_epoch"): "2",
                ("cx317_active", "arm_eligible"): "false",
            }
        )
        supervisor._maybe_finish(final_health, 1_800_020_000.0, 7200.0)
        terminal = supervisor.state["terminal"]

    commands.append(
        {"path": "emergency", "command": "ACTIVE ABORT", "acknowledged": True}
    )
    transcript = {
        "schema_version": 1,
        "contract_id": "cx319_g2_leg_a_outcome_contract_v1",
        "programme_id": "cx319_stabilized_tight_deadband",
        "gate": "G2",
        "leg": "A",
        "mode": "accelerated_offline_no_io",
        "proposal_bundle_sha256": proposal["bundle_sha256"],
        "authority": {"effective": False},
        "hardware_operations": {
            "serial_opens": 0,
            "firmware_flashes": 0,
            "dac_writes": 0,
            "control_arms": 0,
        },
        "commands": commands,
        "setup": {
            "requested_code": 0xA808,
            "applied_code": 0xA808,
            "dac_epoch": 1,
            "acknowledged": True,
        },
        "automatic_transactions": [
            {
                "request_sequence": 1,
                "events": [
                    "request_created",
                    "core0_accepted",
                    "application",
                    "response",
                ],
                "delta_codes": 21,
                "applied_code": 0xA81D,
                "application_timestamp_s": 4202,
                "response_class": "healthy_detected",
                "result": "healthy_completed",
            }
        ],
        "tight_entry": {
            "consecutive_estimates": 2,
            "integer_edge_error_counts": [2, -2],
            "terminal_state": "TIGHT_INSIDE",
            "current_dac_epoch": 2,
        },
        "limits": proposal["intended_live_envelope"] | {
            "maximum_automatic_corrections": proposal["intended_live_envelope"][
                "automatic_corrections"
            ]
        },
        "phase_and_hybrid": {
            "actionable": False,
            "actuation_authorized": False,
            "authorization_consumed": False,
            "frequency_controller_input": False,
        },
        "transport_fault": {
            "normal_path_saturated": True,
            "priority_abort_observed": True,
            "sole_owner": True,
            "serial_reopened": False,
            "basis": "passing G1 physical transport report plus unchanged platform path",
        },
        "closure": {
            "same_owner_rotation": True,
            "analyzer_ran": True,
            "seal_created": True,
            "registration_rehearsed": True,
        },
        "supervisor_terminal": terminal,
    }
    # Present the outcome contract's exact public limit names only.
    envelope = transcript["limits"]
    transcript["limits"] = {
        "maximum_automatic_corrections": envelope["maximum_automatic_corrections"],
        "maximum_step_codes": envelope["maximum_step_codes"],
        "maximum_cumulative_codes": envelope["maximum_cumulative_codes"],
        "minimum_applied_cadence_s": envelope["minimum_applied_cadence_s"],
        "settling_exclusion_s": envelope["settling_exclusion_s"],
        "fresh_support_s": envelope["fresh_support_s"],
        "qualification_deadline_s": envelope["qualification_deadline_s"],
        "maximum_qualified_duration_s": envelope["maximum_qualified_duration_s"],
    }
    transcript_path = artifacts / "cx319_g2_operational_transcript_v1.json"
    _atomic_new(transcript_path, transcript)
    analysis_path = artifacts / "cx319_g2_analysis_v1.json"
    analysis = analyze(
        proposal_path=proposal_path,
        transcript_path=transcript_path,
        output_path=analysis_path,
    )
    seal_unsigned = {
        "schema_version": 1,
        "seal_type": "cx319_g2_accelerated_operational_rehearsal_seal_v1",
        "tool": TOOL_ID,
        "status": analysis["status"],
        "proposal_bundle_sha256": proposal["bundle_sha256"],
        "transcript_sha256": _sha256_file(transcript_path),
        "analysis_sha256": analysis["analysis_sha256"],
        "analysis_file_sha256": _sha256_file(analysis_path),
        "hardware_operations": transcript["hardware_operations"],
        "claims_boundary": analysis["claims_boundary"],
    }
    seal = {**seal_unsigned, "seal_sha256": canonical_sha256(seal_unsigned)}
    seal_path = artifacts / "cx319_g2_operational_rehearsal_seal_v1.json"
    _atomic_new(seal_path, seal)
    package = package_identity(artifacts)
    with tempfile.TemporaryDirectory(
        prefix="cx319-g2-registration-rehearsal-"
    ) as registration_temp:
        registration_root = Path(registration_temp)
        temporary_index = registration_root / "evidence_index_v1.json"
        exercised: list[dict[str, str]] = []
        for classification in ("completed_campaign", "interrupted_campaign"):
            fixture = registration_root / classification
            fixture.mkdir()
            (fixture / "classification.txt").write_text(
                classification + "\n", encoding="utf-8"
            )
            record = register_package(
                index_path=temporary_index,
                package_path=fixture,
                source_revision=proposal["source_revision"],
                build_identity=proposal["firmware"]["build_manifest"]["sha256"],
                profile_identity=proposal["leg_spec"]["profile_id"],
                attempt_classification=classification,
                result_or_failure_reason=(
                    "CX319 G2 accelerated registration-path rehearsal"
                ),
                analyzer_identity=_sha256_file(Path(__file__)),
            )
            exercised.append(
                {
                    "attempt_classification": classification,
                    "content_sha256": record["content_sha256"],
                }
            )
        registration_validation = validate_index(temporary_index)
    registration = {
        "schema_version": 1,
        "mode": "actual_temporary_external_index_registration",
        "status": (
            "passed"
            if analysis["status"] == "passed"
            and registration_validation["valid"] is True
            and registration_validation["package_count"] == 2
            else "failed"
        ),
        "package_content_sha256": package["content_sha256"],
        "file_count": package["file_count"],
        "attempt_classifications_exercised": exercised,
        "temporary_index_validation": registration_validation,
        "persistent_external_index_mutated": False,
    }
    _atomic_new(output_dir / "cx319_g2_registration_rehearsal_v1.json", registration)
    result = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "status": registration["status"],
        "proposal_bundle_sha256": proposal["bundle_sha256"],
        "analysis": str(analysis_path),
        "seal": str(seal_path),
        "registration": str(
            output_dir / "cx319_g2_registration_rehearsal_v1.json"
        ),
        "artifact_content_sha256": package["content_sha256"],
        "hardware_operations": transcript["hardware_operations"],
        "claims_boundary": analysis["claims_boundary"],
    }
    _atomic_new(output_dir / "cx319_g2_operational_rehearsal_v1.json", result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--proposal", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    result = run(proposal_path=args.proposal, output_dir=args.output_dir)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
