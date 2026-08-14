"""Replay and seal one finite physical bounded tight-deadband run.

The analyzer is read-only with respect to the instrument.  It validates the
retained manifest and activation, replays measurement, controller,
tight-deadband, transaction and response evidence, and emits one immutable
pass, bounded-nonpass, or integrity-failure seal.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .active_status_contract import (
    complete_active_status_snapshots,
    latest_complete_health,
)
from .contracts import CsvValidationContext, validate_csv
from .active_transactions import (
    ACTIVE_CSV,
    HEALTH_CSV,
    _read_csv,
    validate_transaction_history,
)
from .control_evidence_replay import (
    _capsules_exact,
    _commands_exact,
    _controller_replay,
    _measurement_replay,
    _response_replay,
)
from .campaign_finalization import (
    CAPTURE_STATE,
    SUPERVISOR_EVENTS,
    SUPERVISOR_STATE,
    _authority_false,
    _capture_closure,
    _contract_path,
    _host_markers,
)
from .frequency_control_supervisor import (
    CONTROL_CSV,
    DAC_CSV,
    ENVIRONMENT_CSV,
    HPR_CSV,
    PHE_CSV,
    RPH_CSV,
    TDB_CSV,
    healthy_required_direction_applications,
)
from .tight_deadband_policy import replay_tight_deadband
from .no_write_qualification_supervisor import load_no_write_qualification_spec
from .bounded_tight_deadband_outcome_contract import (
    MAXIMUM_CORRECTIONS,
    MAXIMUM_CUMULATIVE_CODES,
    MAXIMUM_STEP_CODES,
    MINIMUM_CADENCE_S,
    canonical_sha256,
)
from .bounded_tight_deadband_activation import validate_frozen_run_manifest
from .bounded_tight_deadband_leg import LOWER, leg_for_manifest
from .bounded_tight_deadband_prewrite_contract import (
    RUNTIME_CONTRACT_ID,
    evaluate_health_integrity,
    evaluate_telemetry_drop_history,
)
from .evidence import EVIDENCE_MANIFEST, validate_evidence_snapshot
from .run_loader import CAPTURE_IN_PROGRESS_FLAG, COMPLETE_MARKER, load_manifest
from .setup_authority_contract import (
    SETUP_AUTHORITY_PATH,
    replay_setup_authority_input,
)


TOOL_ID = "cx319_g2_live_analyze_v1"
SEAL_TYPE = "cx319_g2_live_leg_seal_v1"


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _atomic_new_json(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite CX319 live seal: {path}")
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


def _contiguous(rows: list[dict[str, str]], field: str) -> bool:
    if not rows:
        return False
    observed = [int(row[field]) for row in rows]
    return observed == list(range(observed[0], observed[-1] + 1))


def _classify_outcome(
    *,
    common_pass: bool,
    pass_checks_exact: bool,
    terminal_bounded_nonpass: bool,
    terminal_abort_delivery_escape: bool,
) -> tuple[str, str]:
    if common_pass and pass_checks_exact:
        return "passed", "none"
    if common_pass and terminal_bounded_nonpass:
        return (
            "bounded_nonpass",
            "finite_endpoint_without_required_direction_transaction",
        )
    if terminal_abort_delivery_escape:
        return (
            "failed",
            "terminal_abort_delivery_race_after_scientific_bounded_nonpass",
        )
    return "failed", "integrity_or_live_stop_rule_failure"


def _nonce_bound_attach_history(
    rows: list[dict[str, str]], *, query_nonce: int, generation: int
) -> dict[str, Any]:
    snapshots, newest_started = complete_active_status_snapshots(rows)
    matching = [
        item
        for item in snapshots
        if item.get("query_nonce") == str(query_nonce)
    ]
    generations = [
        int(item["snapshot_generation_complete"]) for item in matching
    ]
    exact = bool(generations) and generations[0] == generation
    return {
        "exact": exact,
        "query_nonce": query_nonce,
        "frozen_generation": generation,
        "matching_generations": generations,
        "newest_started_generation": newest_started,
        "reason": (
            "nonce_bound_post_attachment_snapshot"
            if exact
            else "frozen nonce/generation is absent from complete snapshots"
        ),
    }


def _setup_phase_history(
    rows: list[dict[str, str]], request: dict[str, object]
) -> dict[str, Any]:
    observed: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for row in rows:
        if row.get("record_type") != "STS" or row.get("component") != (
            "cx317_setup"
        ):
            continue
        key = row.get("status_key", "")
        if key == "phase":
            if current is not None:
                observed.append(current)
            current = {"phase": row.get("status_value", "")}
        elif current is not None:
            current[key] = row.get("status_value", "")
    if current is not None:
        observed.append(current)
    expected_fields = {
        "authorization_sequence": str(request["authorization_sequence"]),
        "status_generation": str(request["status_generation"]),
        "query_nonce": str(request["query_nonce"]),
    }
    exact_phases = {
        item.get("phase")
        for item in observed
        if all(item.get(key) == value for key, value in expected_fields.items())
    }
    required = {
        "firmware_received",
        "core1_authorized",
        "core0_accepted",
        "core1_execution_released",
        "applied",
    }
    return {
        "exact": required <= exact_phases,
        "required_phases": sorted(required),
        "correlated_phases": sorted(item for item in exact_phases if item),
    }


def analyze(
    run_dir: Path,
    *,
    output_path: Path | None = None,
    supersedes_seal: Path | None = None,
) -> tuple[Path, dict[str, Any]]:
    run_dir = run_dir.resolve()
    if (run_dir / CAPTURE_IN_PROGRESS_FLAG).exists():
        raise ValueError("CX319 live capture is still active")
    if not (run_dir / COMPLETE_MARKER).is_file():
        raise ValueError("CX319 live run is not marked complete")
    manifest_value = validate_frozen_run_manifest(run_dir / "run_manifest.json")
    selected = leg_for_manifest(manifest_value)
    if manifest_value.get("stage") != selected.stage:
        raise ValueError(f"run is not a {selected.gate} live manifest")
    manifest = load_manifest(run_dir)
    spec, identities, leg = load_no_write_qualification_spec(selected.leg)
    build_identity = (
        manifest_value["firmware"]["source_sha256"]
        + ":"
        + manifest_value["firmware"]["configuration_sha256"]
    )
    expected_identity = {
        "run_identity": spec.run_identity,
        "build_identity": build_identity,
        "profile_identity": spec.profile,
        **identities,
    }

    validations: dict[str, dict[str, Any]] = {}
    for contract in manifest_value["contracts"]:
        result = validate_csv(
            _contract_path(manifest, contract),
            CsvValidationContext(
                contract=contract,
                known_channels=manifest.known_channels,
                known_domains=manifest.known_domains,
                tight_deadband_policy_sha256=manifest_value["policy"]["sha256"],
            ),
        )
        validations[contract] = {
            "ok": result.ok,
            "rows": result.row_count,
            "errors": result.errors,
        }

    active_rows = _read_csv(run_dir / ACTIVE_CSV)
    dac_rows = _read_csv(run_dir / DAC_CSV)
    applications = [row for row in active_rows if row.get("event") == "application"]
    responses = [row for row in active_rows if row.get("event") == "response"]
    manual = [row for row in active_rows if row.get("event") == "manual_start"]
    transaction_history_exact = True
    transaction_error = ""
    try:
        validate_transaction_history(
            active_rows, spec, identities, build_identity, dual_core=True
        )
    except (KeyError, TypeError, ValueError) as exc:
        transaction_history_exact = False
        transaction_error = str(exc)

    response_exact, response_replay = _response_replay(
        active_rows, spec.minimum_code, spec.maximum_code
    )
    measurement_exact, measurement_replay, estimates_by_id = _measurement_replay(
        manifest, manifest_value
    )

    supervisor_state = json.loads(
        (run_dir / SUPERVISOR_STATE).read_text(encoding="utf-8")
    )
    supervisor_events = [
        json.loads(line)
        for line in (run_dir / SUPERVISOR_EVENTS)
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    capture_state = json.loads(
        (run_dir / CAPTURE_STATE).read_text(encoding="utf-8")
    )
    markers = _host_markers(run_dir / "raw/serial.log")
    capsule_exact, capsule_hashes = _capsules_exact(
        run_dir, active_rows, supervisor_events, supervisor_state
    )

    tdb_rows = _read_csv(run_dir / TDB_CSV)
    tdb_replay = replay_tight_deadband(
        run_dir / TDB_CSV,
        policy_sha256=manifest_value["policy"]["sha256"],
    )
    tight_entries = [
        row
        for row in tdb_rows
        if row.get("transition") == "true"
        and row.get("state_after") == "TIGHT_INSIDE"
    ]
    healthy_required = healthy_required_direction_applications(
        active_rows, leg.required_direction
    )
    movements = [abs(int(row["requested_delta_codes"])) for row in applications]
    application_times = [int(row["application_timestamp_s"]) for row in applications]
    cadence_exact = all(
        later - earlier >= MINIMUM_CADENCE_S
        for earlier, later in zip(application_times, application_times[1:])
    )
    epochs_exact = (
        len(manual) == 1
        and len(responses) == len(applications)
        and int(manual[0].get("dac_epoch", "-1")) == 1
        and [int(row["dac_epoch"]) for row in applications]
        == list(range(2, len(applications) + 2))
        and all(
            int(response["dac_epoch"]) == int(application["dac_epoch"])
            for application, response in zip(applications, responses, strict=True)
        )
    )
    dac_exact = (
        len(dac_rows) == len(applications) + 1
        and bool(dac_rows)
        and dac_rows[0].get("event") == "manual_apply"
        and int(dac_rows[0]["dac_code_requested"]) == selected.setup_code
        and int(dac_rows[0]["dac_code_applied"]) == selected.setup_code
        and int(dac_rows[0]["dac_code_clamped"]) == 0
        and int(dac_rows[0]["flags"]) == 0
        and all(
            row.get("event") == "active_apply"
            and int(row["dac_code_requested"]) == int(application["requested_code"])
            and int(row["dac_code_applied"]) == int(application["applied_code"])
            and int(row["dac_code_clamped"]) == 0
            and int(row["flags"]) == 0
            for row, application in zip(dac_rows[1:], applications, strict=True)
        )
    )

    control_rows = _read_csv(run_dir / CONTROL_CSV)
    controller_exact, controller_replay = _controller_replay(
        control_rows,
        estimates_by_id,
        tdb_rows,
        dac_rows,
        applications,
        stage5_policy_sha256=manifest_value["policy"]["sha256"],
        policy_id=manifest_value["policy"]["policy_id"],
    )
    final_epoch = len(applications) + 1
    rph_rows = _read_csv(run_dir / RPH_CSV)
    phe_rows = _read_csv(run_dir / PHE_CSV)
    hpr_rows = _read_csv(run_dir / HPR_CSV)
    preview_continuity = (
        _contiguous(control_rows, "control_seq")
        and _contiguous(rph_rows, "observation_sequence")
        and _contiguous(phe_rows, "observation_sequence")
        and _contiguous(hpr_rows, "preview_sequence")
        and _contiguous(tdb_rows, "decision_sequence")
        and int(rph_rows[-1]["dac_epoch"]) == final_epoch
        and int(hpr_rows[-1]["dac_epoch"]) == final_epoch
        and int(tdb_rows[-1]["dac_epoch"]) == final_epoch
    )
    current_tight = (
        bool(tdb_rows)
        and tdb_rows[-1].get("state_after") == "TIGHT_INSIDE"
        and int(tdb_rows[-1]["dac_epoch"]) == final_epoch
        and tdb_rows[-1].get("frequency_controller_eligible") == "false"
    )
    preview_paths = (CONTROL_CSV, RPH_CSV, PHE_CSV, HPR_CSV, TDB_CSV)
    previews_present = all(_read_csv(run_dir / relative) for relative in preview_paths)
    zero_authority = all(
        _authority_false(run_dir / relative) for relative in preview_paths
    )
    health_rows = _read_csv(run_dir / HEALTH_CSV)
    query_nonce = int(supervisor_state["host_attach_query_nonce"])
    attach_generation = int(supervisor_state["host_attach_snapshot_generation"])
    health = latest_complete_health(
        run_dir / HEALTH_CSV, required_query_nonce=query_nonce
    )
    telemetry_drop_baseline = int(
        supervisor_state["telemetry_drop_baseline"]
    )
    telemetry_drop_baseline_status_seq = int(
        supervisor_state["telemetry_drop_baseline_status_seq"]
    )
    health_integrity = evaluate_health_integrity(
        health, telemetry_drop_baseline=telemetry_drop_baseline
    )
    telemetry_drop_history = evaluate_telemetry_drop_history(
        _read_csv(run_dir / HEALTH_CSV),
        frozen_baseline=telemetry_drop_baseline,
        frozen_status_seq=telemetry_drop_baseline_status_seq,
    )
    host_attach_history = _nonce_bound_attach_history(
        health_rows,
        query_nonce=query_nonce,
        generation=attach_generation,
    )
    setup_authority_path = run_dir / SETUP_AUTHORITY_PATH
    setup_authority_error = ""
    try:
        setup_authority = replay_setup_authority_input(
            setup_authority_path,
            expected_identity=expected_identity,
            planned_live_stimulus_code=selected.setup_code,
        )
    except (KeyError, OSError, TypeError, ValueError) as exc:
        setup_authority = None
        setup_authority_error = str(exc)
    setup_phases = (
        _setup_phase_history(health_rows, setup_authority.request)
        if setup_authority is not None
        else {"exact": False, "error": setup_authority_error}
    )
    sources = {
        row.get("source", "").lower()
        for row in _read_csv(run_dir / ENVIRONMENT_CSV)
    }
    evidence_failures, evidence_warnings = validate_evidence_snapshot(
        run_dir, manifest
    )
    evidence_path = run_dir / EVIDENCE_MANIFEST
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    terminal = supervisor_state.get("terminal", {})
    terminal_pass = (
        terminal.get("result") == "healthy_stop"
        and terminal.get("reason")
        == "required_direction_and_two_estimate_tight_entry"
    )
    terminal_bounded_nonpass = (
        terminal.get("result") == "aborted"
        and terminal.get("reason")
        in {
            "stage5_qualification_deadline_expired",
            "stage5_finite_qualified_endpoint_nonpass",
        }
    )
    allowed_emergency_aborts = 1 if terminal_bounded_nonpass else 0
    terminal_abort_submissions = len(
        [
            item
            for item in supervisor_events
            if item.get("event") == "emergency_device_abort_submitted"
        ]
    )
    terminal_abort_sends = int(capture_state.get("emergency_aborts_sent", 0))
    terminal_abort_delivery = {
        "required": terminal_bounded_nonpass,
        "supervisor_submission_count": terminal_abort_submissions,
        "capture_send_count": terminal_abort_sends,
        "exact": (
            terminal_abort_submissions == allowed_emergency_aborts
            and terminal_abort_sends == allowed_emergency_aborts
        ),
    }
    capture_closure = _capture_closure(
        run_dir,
        capture_state,
        markers,
        allowed_emergency_aborts=allowed_emergency_aborts,
    )
    flash_record: dict[str, Any] | None = None
    flash_exact = not selected.firmware_flash
    if selected.flash_record_filename is not None:
        flash_path = run_dir / selected.flash_record_filename
        try:
            flash_record = json.loads(flash_path.read_text(encoding="utf-8"))
            flash_unsigned = {
                key: value
                for key, value in flash_record.items()
                if key != "record_sha256"
            }
            flash_exact = (
                flash_record.get("status") == "passed"
                and flash_record.get("gate") == selected.gate
                and flash_record.get("leg") == selected.leg
                and flash_record.get("firmware_flash_count") == 1
                and flash_record.get("expected_board_serial") == "503533748A919118"
                and flash_record.get("board_identity_confirmed_before") is True
                and flash_record.get("board_identity_confirmed_after") is True
                and flash_record.get("usb_reenumerated") is True
                and flash_record.get("uf2_sha256")
                == manifest_value["firmware"]["uf2"]["sha256"]
                and flash_record.get("build_manifest_sha256")
                == manifest_value["firmware"]["build_manifest"]["sha256"]
                and flash_record.get("record_sha256")
                == canonical_sha256(flash_unsigned)
            )
        except (OSError, TypeError, ValueError, json.JSONDecodeError):
            flash_exact = False

    common_checks = {
        "manifest_exact_leg_activation_prerequisite_firmware_and_policy": True,
        "passing_accelerated_operational_rehearsal_bound": bool(
            manifest_value["activation"]["activation_sha256"]
            and manifest_value["proposal"]["bundle_sha256"]
        ),
        "firmware_entry_matches_exact_leg_authority": flash_exact,
        "prewrite_runtime_contract_exact_before_setup": (
            supervisor_state.get("prewrite_contract_ready_utc") is not None
            and supervisor_state.get("setup_confirmed_utc") is not None
            and supervisor_state.get("prewrite_contract_ready_utc")
            <= supervisor_state.get("setup_confirmed_utc")
            and setup_authority is not None
            and setup_authority.exact
            and setup_authority.readiness.contract_id == RUNTIME_CONTRACT_ID
            and setup_phases["exact"] is True
        ),
        "all_declared_contracts_validate": all(
            item["ok"] for item in validations.values()
        ),
        "zero_association_loss_decisions": validations.get(
            "association_loss_decisions_v1", {}
        ).get("rows")
        == 0,
        "capture_closed_cleanly_with_one_owner": capture_closure["ok"],
        "command_stream_matches_supervisor_exactly": _commands_exact(
            markers,
            supervisor_events,
            capture_state,
            setup_code=selected.setup_code,
            allowed_emergency_aborts=allowed_emergency_aborts,
        ),
        "transaction_history_exact": transaction_history_exact,
        "durable_transaction_capsules_and_phase_acknowledgements_exact": capsule_exact,
        "response_classifier_replay_exact": response_exact,
        "raw_measurement_and_estimator_replay_exact": measurement_exact,
        "frequency_controller_replay_and_application_binding_exact": controller_exact,
        "single_exact_setup_and_dac_epochs": epochs_exact and dac_exact,
        "automatic_limits_range_and_cadence_exact": (
            len(applications) <= MAXIMUM_CORRECTIONS
            and all(0 < movement <= MAXIMUM_STEP_CODES for movement in movements)
            and sum(movements) <= MAXIMUM_CUMULATIVE_CODES
            and cadence_exact
            and all(
                spec.minimum_code <= int(row["applied_code"]) <= spec.maximum_code
                for row in applications
            )
        ),
        "tight_deadband_policy_exact": tdb_replay.exact and bool(tdb_rows),
        "phase_hybrid_tdb_continuous_and_zero_authority": (
            previews_present and preview_continuity and zero_authority
        ),
        "both_environment_streams_present": {"sht4x", "bmp280"} <= sources,
        "live_health_has_no_post_attach_telemetry_increment_or_fault": (
            health_integrity.clean
            and telemetry_drop_history["exact"] is True
            and host_attach_history["exact"] is True
        ),
        "sealed_evidence_snapshot_valid": (
            evidence.get("run_state") == "complete"
            and not evidence_failures
            and not evidence_warnings
        ),
    }
    pass_checks = {
        "terminal_reason_is_exact_pass": terminal_pass,
        "healthy_required_direction_automatic_transaction_demonstrated": bool(
            healthy_required
        ),
        "two_estimate_tight_entry_transition_demonstrated": (
            bool(tight_entries) and current_tight
        ),
        "terminal_disarmed_and_evidence_clear": (
            health.get(("cx317_active", "state")) == "DISARMED"
            and health.get(("cx317_active", "evidence_phase")) == "evidence_clear"
            and health.get(("cx317_active", "fail_static")) == "false"
            and supervisor_state.get("arm_pending") is False
            and len(responses) >= 1
        ),
    }
    common_pass = all(value is True for value in common_checks.values())
    scientific_evidence_exact = all(
        value is True
        for name, value in common_checks.items()
        if name
        not in {
            "capture_closed_cleanly_with_one_owner",
            "command_stream_matches_supervisor_exactly",
        }
    )
    stimulus_nonactionable = (
        terminal_bounded_nonpass
        and scientific_evidence_exact
        and bool(tight_entries)
        and current_tight
        and not applications
        and not responses
    )
    terminal_abort_delivery_escape = (
        stimulus_nonactionable
        and terminal_abort_submissions == 1
        and terminal_abort_sends == 0
        and common_checks["capture_closed_cleanly_with_one_owner"] is False
        and common_checks["command_stream_matches_supervisor_exactly"] is False
    )
    status, failure_class = _classify_outcome(
        common_pass=common_pass,
        pass_checks_exact=all(pass_checks.values()),
        terminal_bounded_nonpass=terminal_bounded_nonpass,
        terminal_abort_delivery_escape=terminal_abort_delivery_escape,
    )
    scientific_outcome = (
        "stimulus_nonactionable_stable_tight_hold"
        if stimulus_nonactionable
        else "required_direction_qualification_passed"
        if status == "passed"
        else "not_established"
    )
    checks = {**common_checks, **pass_checks}

    source_paths = {
        "run_manifest.json",
        "raw/serial.log",
        str(CAPTURE_STATE),
        "reports/capture_segment_closure_v1.json",
        str(SUPERVISOR_STATE),
        str(SUPERVISOR_EVENTS),
        str(SETUP_AUTHORITY_PATH),
        str(EVIDENCE_MANIFEST),
        str(COMPLETE_MARKER),
        *(str(item["path"]) for item in manifest.files),
        *(str(item) for item in manifest_value.get("evidence_artifacts", [])),
        *capsule_hashes,
    }
    source_hashes = {
        relative: _sha256_file(run_dir / relative)
        for relative in sorted(source_paths)
    }
    unsigned: dict[str, Any] = {
        "schema_version": 1,
        "seal_type": f"{selected.prefix}_live_leg_seal_v1",
        "tool": f"{selected.prefix}_live_analyze_v1",
        "tool_sha256": _sha256_file(Path(__file__)),
        "programme_id": "cx319_stabilized_tight_deadband",
        "gate": selected.gate,
        "leg": selected.leg,
        "status": status,
        "failure_class": failure_class,
        "scientific_outcome": scientific_outcome,
        "terminal_abort_delivery": terminal_abort_delivery,
        "profile_id": spec.profile,
        "required_direction": selected.required_direction,
        "proposal_bundle_sha256": manifest_value["proposal"]["bundle_sha256"],
        "activation_sha256": manifest_value["activation"]["activation_sha256"],
        "prerequisite_evidence_sha256": (
            manifest_value["g1_pass"]["evidence_content_sha256"]
            if selected.prerequisite_key == "g1_pass"
            else manifest_value["g2_pass"]["acquisition_content_sha256"]
        ),
        "policy_sha256": manifest_value["policy"]["sha256"],
        "build_manifest_sha256": manifest_value["firmware"]["build_manifest"][
            "sha256"
        ],
        "uf2_sha256": manifest_value["firmware"]["uf2"]["sha256"],
        "run": {
            "path": str(run_dir),
            "manifest_sha256": _sha256_file(run_dir / "run_manifest.json"),
        },
        "capture_closure": capture_closure,
        "firmware_flash_record": flash_record,
        "evidence_snapshot": {
            "path": str(evidence_path),
            "sha256": _sha256_file(evidence_path),
            "snapshot_digest": evidence.get("snapshot_digest"),
        },
        "terminal": terminal,
        "runtime_health_integrity": {
            "clean": health_integrity.clean,
            "missing": health_integrity.missing,
            "mismatches": health_integrity.mismatches,
            "telemetry_drop_history": telemetry_drop_history,
            "host_attach_history": host_attach_history,
        },
        "setup_authority_replay": {
            "exact": setup_authority is not None and setup_authority.exact,
            "errors": (
                list(setup_authority.errors)
                if setup_authority is not None
                else [setup_authority_error]
            ),
            "phase_history": setup_phases,
        },
        "checks": checks,
        "contract_validation": validations,
        "transactions": {
            "history_error": transaction_error,
            "application_count": len(applications),
            "response_count": len(responses),
            "path_codes": sum(movements),
            "healthy_required_direction_count": len(healthy_required),
            "dac_epochs": [int(row["dac_epoch"]) for row in applications],
            "capsules_sha256": capsule_hashes,
            "response_replay": response_replay,
        },
        "hardware_operations": {
            "serial_opens": 1,
            "firmware_flashes": int(selected.firmware_flash),
            "dac_writes": len(dac_rows),
            "control_arms": len(
                [
                    item
                    for item in supervisor_events
                    if item.get("event") == "command_submitted"
                    and str(item.get("command", "")).startswith("ACTIVE ARM ")
                ]
            ),
        },
        "measurement_replay": measurement_replay,
        "controller_replay": controller_replay,
        "tight_deadband_policy": tdb_replay.as_dict(),
        "tight_entry_transition_count": len(tight_entries),
        "source_artifacts_sha256": source_hashes,
        "claims_boundary": (
            f"One finite bounded {selected.gate} "
            f"{'lower' if selected.leg == 'A' else 'upper'}-side frequency-only leg; "
            "phase and hybrid preview remained zero-authority."
        ),
    }
    if supersedes_seal is not None:
        superseded = supersedes_seal.resolve()
        superseded_value = json.loads(superseded.read_text(encoding="utf-8"))
        unsigned["analysis_supersession"] = {
            "reason": "deterministic_offline_analyzer_repair",
            "superseded_seal_path": str(superseded),
            "superseded_seal_file_sha256": _sha256_file(superseded),
            "superseded_seal_sha256": superseded_value.get("seal_sha256"),
            "superseded_status": superseded_value.get("status"),
            "superseded_tool_sha256": superseded_value.get("tool_sha256"),
            "raw_acquisition_unchanged": True,
            "physical_rerun": False,
        }
    result = {**unsigned, "seal_sha256": canonical_sha256(unsigned)}
    output = (
        output_path.resolve()
        if output_path is not None
        else run_dir / selected.live_seal_filename
    )
    _atomic_new_json(output, result)
    return output, result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--supersedes-seal", type=Path)
    args = parser.parse_args(argv)
    try:
        output, result = analyze(
            args.run_dir,
            output_path=args.output,
            supersedes_seal=args.supersedes_seal,
        )
    except (
        FileExistsError,
        FileNotFoundError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        raise SystemExit(str(exc)) from exc
    print(json.dumps({"status": result["status"], "output": str(output)}, sort_keys=True))
    return 0 if result["status"] in {"passed", "bounded_nonpass"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
