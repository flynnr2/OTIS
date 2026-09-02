"""Create and validate CX320 live authority and run-manifest artifacts.

This module is deliberately no-I/O.  It never discovers a board, opens a
serial device, creates a command FIFO, uploads firmware, applies setup, or arms
control.  Its effective activation is a separate immutable artifact derived
from the operator-authorized, non-effective proposal.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any

from .active_hybrid_programme_contract import (
    ActiveHybridProgramme,
    CX323_REHEARSAL_COVERAGE,
    CX323_D9_D6_72H_PROGRAMME,
    CX320_PROGRAMME,
    CX322_D9_D6_72H_PROGRAMME,
    integrated_setup_provenance_contract,
    progressive_checkpoint_contract,
    programme_from_mapping,
)

from .active_hybrid_bundle import (
    FRESH_SERIAL_AUTO_DETECT,
    REQUIRED_FALSE_AUTHORITY,
    validate_bundle,
)
from .active_hybrid_proposal import validate_proposal
from .evidence_index import package_identity
from .run_paths import (
    cx323_active_timing_csv_files,
    cx321_csv_files,
    default_csv_files,
    exact_active_timing_csv_files,
)
from .time_domains import (
    canonical_domain_declaration,
    validate_domain_declarations,
)


TOOL_ID = "cx320_active_hybrid_live_activation_v1"
ACTIVATION_ID = "cx320_active_hybrid_12h_live_activation_v1"
PROGRAMME_ID = "CX320_BOUNDED_ACTIVE_HYBRID_PHASE_FREQUENCY_V1"
OPERATION = "cx320_stage5_bounded_active_hybrid_live"
LIVE_STAGE = "CX320_BOUNDED_ACTIVE_HYBRID_PHASE_FREQUENCY_LIVE"
RUNTIME_RUN_IDENTITY = "cx320_active_hybrid:3200001"
PROFILE_IDENTITY = "cx320_active_hybrid"
EXPECTED_BOARD_SERIAL = "503533748A919118"
EXPECTED_BAUD = 115200
DEFAULT_ATTEMPT_REASON = (
    "initial Stage 5 physical entry after bounded pre-entry materiality and "
    "live-path remediation"
)
SETUP_CODE = 0xA83C
SETUP_CODE_HEX = "0xA83C"
RUN_ACTIVATION_PATH = Path("cx320_active_hybrid_live_activation_v1.json")
RUN_PROPOSAL_PATH = Path("cx320_active_hybrid_authority_proposal_v1.json")
RUN_BUNDLE_PATH = Path("cx320_active_hybrid_exact_bundle_v1.json")
RUN_MANIFEST_PATH = Path("run_manifest.json")
REHEARSAL_REPORT_TYPE = "cx320_active_hybrid_live_topology_rehearsal_v1"
REHEARSAL_COVERAGE = (
    "capture_device_real_process",
    "pty_serial_carrier",
    "sole_serial_owner",
    "normal_command_fifo",
    "emergency_abort_fifo",
    "host_abort_fifo",
    "live_supervisor_process",
    "first_active_hybrid_wire_record",
    "active_hybrid_status_handoff",
    "setup_authority_qualification_deadline",
    "qualified_device_time_boundaries",
    "setup_propagation",
    "progressive_checkpoint",
    "conditional_release",
    "response_classification",
    "phase_only_degradation",
    "shared_fail_static_fault",
    "transport_obstruction",
    "terminal_abort_delivery_before_capture_close",
    "post_abort_complete_active_snapshot",
    "logical_evidence_rotation",
    "analysis_seal_registration",
)
SUSTAINED_REHEARSAL_COVERAGE = (
    "complete_multi_transaction_identity_sequence",
    "repeated_natural_transaction",
    "deliberate_challenge_transaction",
    "opposite_direction_recovery_transaction",
    "first_post_recovery_consumer",
    "separate_automatic_physical_challenge_accounting",
    "mandatory_sustained_status_snapshot_identity",
)
INTEGRATED_REHEARSAL_COVERAGE = (
    "integrated_unarmed_concurrency_observation_boundary",
    "integrated_setup_provenance_boundary",
)
CAMPAIGN18_REHEARSAL_COVERAGE = (
    "campaign18_exact_AT2_AH2_capture",
    "campaign18_repeated_natural_transaction",
    "campaign18_GNSS_hold_causal_requalification",
    "campaign18_exact_72h_endpoint_clock",
    "campaign18_authoritative_capture_fault_terminal",
)
FIFO_PATHS = {
    "normal_command": "control/normal_commands.fifo",
    "emergency_abort": "control/emergency_abort.fifo",
    "host_abort": "control/host_abort.fifo",
}


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_sha256(value: dict[str, Any]) -> str:
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _binding(path: Path) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f"bound file is unavailable: {path}")
    return {
        "path": str(path),
        "sha256": _sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _binding_matches(binding: object, path: Path) -> bool:
    if not isinstance(binding, dict):
        return False
    path = path.resolve()
    return (
        binding.get("path") == str(path)
        and _binding_content_matches(binding, path)
    )


def _binding_content_matches(binding: object, path: Path) -> bool:
    if not isinstance(binding, dict):
        return False
    path = path.resolve()
    return (
        path.is_file()
        and binding.get("sha256") == _sha256_file(path)
        and binding.get("size_bytes") == path.stat().st_size
    )


def _atomic_new_json(path: Path, value: dict[str, Any]) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite immutable artifact: {path}")
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


def _git_clean() -> bool:
    completed = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=Path(__file__).resolve().parents[2],
        check=True,
        text=True,
        capture_output=True,
    )
    return not completed.stdout


def _semantic_object(path: Path, digest_field: str, label: str) -> dict[str, Any]:
    value = _read_object(path, label)
    claimed = value.get(digest_field)
    unsigned = {key: item for key, item in value.items() if key != digest_field}
    if claimed != _canonical_sha256(unsigned):
        raise ValueError(f"{label} semantic identity differs")
    return value


def _bundle_binds_this_tool(bundle: dict[str, Any]) -> bool:
    current = _binding(Path(__file__))
    tools = bundle.get("host_tools")
    return isinstance(tools, dict) and any(
        item == current for item in tools.values()
    )


def _validate_current_bundle(
    path: Path, programme: ActiveHybridProgramme
) -> dict[str, Any]:
    # Preserve the established CX320 call surface for tests and retained
    # operational integrations that replace the one-argument validator.
    return (
        validate_bundle(path)
        if programme is CX320_PROGRAMME
        else validate_bundle(path, programme)
    )


def _validate_frozen_inputs(
    *,
    bundle_path: Path,
    proposal_path: Path,
    programme: ActiveHybridProgramme = CX320_PROGRAMME,
) -> tuple[dict[str, Any], dict[str, Any]]:
    bundle_path = bundle_path.resolve()
    proposal_path = proposal_path.resolve()
    bundle = _semantic_object(bundle_path, "bundle_sha256", "CX320 bundle")
    proposal = _semantic_object(
        proposal_path, "proposal_sha256", "CX320 authority proposal"
    )
    exact_bundle = proposal.get("exact_bundle", {})
    proposal_authority = proposal.get("authority", {})
    bundle_authority = bundle.get("authority", {})
    host_tools = bundle.get("host_tools")
    if (
        not isinstance(exact_bundle, dict)
        or not isinstance(host_tools, dict)
        or bundle.get("programme_id") != programme.programme_id
        or bundle.get("run_identity") != programme.runtime_run_identity
        or bundle.get("status") != "frozen_non_effective_physical_proposal_input"
        or proposal.get("programme_id") != programme.programme_id
        or proposal.get("run_identity") != programme.runtime_run_identity
        or proposal.get("status")
        != "non_effective_awaiting_separate_operator_decision"
        or not isinstance(proposal_authority, dict)
        or not isinstance(bundle_authority, dict)
        or any(
            proposal_authority.get(name) is not False
            for name in REQUIRED_FALSE_AUTHORITY
        )
        or any(
            bundle_authority.get(name) is not False
            for name in REQUIRED_FALSE_AUTHORITY
        )
        or exact_bundle.get("file_sha256") != _sha256_file(bundle_path)
        or exact_bundle.get("bundle_sha256") != bundle.get("bundle_sha256")
        or proposal.get("policy_sha256")
        != bundle.get("policy", {}).get("policy_sha256")
        or proposal.get("build_identity")
        != bundle.get("firmware", {}).get("build_identity")
    ):
        raise ValueError("CX320 frozen bundle/proposal identity or authority differs")
    return bundle, proposal


def _cx323_aperture_rehearsal_exact(
    clock: object, programme: ActiveHybridProgramme
) -> bool:
    """Validate the accelerated V2 D14/D8 aperture boundary evidence."""

    if not isinstance(clock, dict):
        return False
    target = programme.qualified_d14_aperture_count
    reserve = programme.correction_response_reserve_d14_apertures
    if target is None or reserve is None:
        return False
    admission_close = target - reserve
    accepted_origin = clock.get("accepted_window_count_origin")
    reference_origin = clock.get("boundary_reference_sequence_origin")
    observations = clock.get("boundary_observations")
    if (
        type(accepted_origin) is not int
        or type(reference_origin) is not int
        or not 0 <= accepted_origin < 1 << 32
        or not 0 <= reference_origin < 1 << 32
        or not isinstance(observations, dict)
        or clock.get("time_domain")
        != "qualified_D14_D8_aperture_count_v2"
        or clock.get("supporting_local_ordering_domain") != "rp2040_timer0"
        or clock.get("qualified_endpoint_d14_d8_apertures") != target
        or clock.get("correction_response_reserve_d14_apertures") != reserve
        or clock.get("correction_admission_close_d14_d8_apertures")
        != admission_close
        or clock.get("admission_open_before_exact_aperture_boundary") is not True
        or clock.get("admission_closed_at_exact_aperture_boundary") is not True
        or clock.get("endpoint_open_before_exact_aperture_boundary") is not True
        or clock.get("endpoint_closed_at_exact_aperture_boundary") is not True
        or clock.get(
            "rp2040_timer0_held_constant_across_aperture_boundaries"
        )
        is not True
        or clock.get("forward_host_utc_step_did_not_close_early") is not True
        or clock.get("backward_host_utc_step_did_not_delay_endpoint") is not True
    ):
        return False

    expected = {
        "admission_open": (admission_close - 1, False, False),
        "admission_closed": (admission_close, True, False),
        "endpoint_open": (target - 1, True, False),
        "endpoint_closed": (target, True, True),
    }
    timer0_ticks: int | None = None
    for name, (progress, response_closed, terminal_reached) in expected.items():
        item = observations.get(name)
        if not isinstance(item, dict):
            return False
        accepted_now = item.get("accepted_window_count")
        reference_now = item.get("boundary_reference_sequence")
        observed_timer0_ticks = item.get("rp2040_timer0_ticks")
        if (
            type(accepted_now) is not int
            or type(reference_now) is not int
            or type(observed_timer0_ticks) is not int
            or item.get("qualified_d14_d8_apertures") != progress
            or ((accepted_now - accepted_origin) & 0xFFFFFFFF) != progress
            or ((reference_now - reference_origin) & 0xFFFFFFFF) != progress
            or item.get("response_horizon_closed") is not response_closed
            or item.get("terminal_reached") is not terminal_reached
        ):
            return False
        if timer0_ticks is None:
            timer0_ticks = observed_timer0_ticks
        elif observed_timer0_ticks != timer0_ticks:
            return False
    return True


def validate_operational_rehearsal(
    path: Path,
    *,
    bundle: dict[str, Any],
    proposal: dict[str, Any],
    require_current_tools: bool = True,
    programme: ActiveHybridProgramme | None = None,
) -> dict[str, Any]:
    path = path.resolve()
    report = _read_object(path, "CX320 live-topology rehearsal")
    programme = programme or programme_from_mapping(bundle)
    claimed = report.get("rehearsal_sha256")
    unsigned = {
        key: item for key, item in report.items() if key != "rehearsal_sha256"
    }
    coverage = report.get("coverage")
    tool_bindings = report.get("tool_bindings")
    expected_coverage = set(REHEARSAL_COVERAGE)
    if programme.sustained_status_contract:
        expected_coverage.add("mandatory_sustained_status_snapshot_identity")
    if programme.sustained_regulation:
        expected_coverage.update(SUSTAINED_REHEARSAL_COVERAGE)
    if programme.engineering_unarmed_observation_s > 0:
        expected_coverage.add("integrated_unarmed_concurrency_observation_boundary")
    if programme.forwarded_output_integration:
        expected_coverage.add("integrated_setup_provenance_boundary")
    if programme.persistent_maintenance_policy:
        expected_coverage.update(CX323_REHEARSAL_COVERAGE)
    elif programme.integrated_long_run:
        expected_coverage.update(CAMPAIGN18_REHEARSAL_COVERAGE)
    if (
        report.get("schema_version") != 1
        or report.get("report_type") != programme.rehearsal_report_type
        or report.get("status") != "passed"
        or report.get("bundle_sha256") != bundle.get("bundle_sha256")
        or report.get("proposal_sha256") != proposal.get("proposal_sha256")
        or report.get("physical_actions_performed") != 0
        or report.get("qualification_evidence") is not False
        or claimed != _canonical_sha256(unsigned)
        or not isinstance(coverage, dict)
        or set(coverage) != expected_coverage
        or any(coverage.get(name) is not True for name in expected_coverage)
        or tool_bindings != bundle.get("host_tools")
        or (
            programme.forwarded_output_integration
            and report.get("setup_provenance_contract")
            != integrated_setup_provenance_contract(programme)
        )
    ):
        raise ValueError("CX320 live-topology rehearsal receipt differs or is incomplete")
    if programme.identification_required:
        ordering = report.get("cx321_identification_ordering", {})
        if not isinstance(ordering, dict) or not all(
            ordering.get(key) is True
            for key in (
                "no_early_or_stale_identification_arm",
                "one_exact_pre2_identification_arm",
                "phase4_waited_for_matching_psq_after_act_split",
            )
        ):
            raise ValueError("CX321 rehearsal lacks exact identification ordering")
        topology = report.get("real_process_topology", {})
        transaction = (
            topology.get("cx321_real_transaction_path", {})
            if isinstance(topology, dict)
            else {}
        )
        phases = transaction.get("evidence_phase_commands", [])
        extended = transaction.get("extended_phase4_command")
        digest = transaction.get("complete_evidence_chain_sha256")
        extended_fields = extended.split() if isinstance(extended, str) else []
        natural = transaction.get("first_natural_decision", {})
        natural_phases = transaction.get("natural_evidence_phase_commands", [])
        if (
            not isinstance(transaction, dict)
            or transaction.get("canonical_psq_field_count") != 60
            or transaction.get("canonical_snp_rows_captured") != 4502
            or transaction.get("canonical_act_field_count") != 47
            or not isinstance(phases, list)
            or len(phases) != 4
            or phases[:3]
            != [
                "ACTIVE EVIDENCE 1 1",
                "ACTIVE EVIDENCE 1 2",
                "ACTIVE EVIDENCE 1 3",
            ]
            or phases[3] != extended
            or len(extended_fields) != 10
            or extended_fields[:4] != ["ACTIVE", "EVIDENCE", "1", "4"]
            or extended_fields[4:9] != ["5", "-5", "1", "2", "6302"]
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or extended_fields[-1:] != [digest]
            or transaction.get("raw_timer_rollover_between_application_and_response")
            is not True
            or transaction.get("firmware_consumption_confirmed") is not True
            or transaction.get("response_ack_handoff_exact") is not True
            or transaction.get("act_response_join", {}).get("exact") is not True
            or not isinstance(transaction.get("raw_snapshot_proof_sha256"), str)
            or not isinstance(natural, dict)
            or natural.get("request_sequence") != 2
            or natural.get("global_correction_count_before") != 1
            or natural.get("global_cumulative_movement_before_codes") != 21
            or natural.get("natural_cumulative_movement_codes") != 0
            or natural.get("natural_direction_count") != 0
            or natural.get("plant_sign_handoff_first_consumer") is not True
            or natural.get("phase_materially_influenced") is not True
            or transaction.get("natural_ahy_rows_captured") != 2
            or not isinstance(natural_phases, list)
            or natural_phases
            != [
                "ACTIVE EVIDENCE 2 1",
                "ACTIVE EVIDENCE 2 2",
                "ACTIVE EVIDENCE 2 3",
                "ACTIVE EVIDENCE 2 4",
            ]
            or transaction.get(
                "natural_response_firmware_consumption_confirmed"
            )
            is not True
        ):
            raise ValueError(
                "CX321 rehearsal lacks the exact real-process plant-sign "
                "transaction path"
            )
    if programme.integrated_long_run:
        topology = report.get("real_process_topology", {})
        transaction = (
            topology.get("integrated_long_run_real_transaction_path", {})
            or topology.get("cx322_real_transaction_path", {})
            if isinstance(topology, dict)
            else {}
        )
        clock = report.get("accelerated_qualified_device_clock", {})
        manifest_path = path.parent / "process_topology/run/run_manifest.json"
        manifest = _read_object(
            manifest_path, "integrated long-run rehearsal manifest"
        )
        files = manifest.get("files", [])
        required_exact = {
            "active_transactions_v2": "csv/active_transactions_v2.csv",
            "active_hybrid_decisions_v2": "csv/active_hybrid_decisions_v2.csv",
        }
        if programme.persistent_maintenance_policy:
            required_exact["active_hybrid_maintenance_v1"] = (
                "csv/active_hybrid_maintenance_v1.csv"
            )
        exact_files = {
            item.get("contract"): item
            for item in files
            if isinstance(item, dict)
            and item.get("contract") in required_exact
        }
        domains = manifest.get("domains", [])
        domain_errors = validate_domain_declarations(
            domains,
            require_complete=(
                require_current_tools
                and programme.key == CX323_D9_D6_72H_PROGRAMME.key
            ),
        )
        qualified_boundary_exact = (
            _cx323_aperture_rehearsal_exact(clock, programme)
            if programme.qualified_d14_aperture_count is not None
            else (
                isinstance(clock, dict)
                and clock.get("correction_admission_close_elapsed_s") == 257_700
                and clock.get("qualified_endpoint_elapsed_s") == 259_200
                and clock.get("admission_open_at_floor_before_exact_boundary")
                is True
                and clock.get("admission_closed_at_exact_boundary") is True
                and clock.get("forward_host_utc_step_did_not_close_early") is True
                and clock.get("backward_host_utc_step_did_not_delay_endpoint")
                is True
            )
        )
        if (
            not isinstance(transaction, dict)
            or transaction.get("complete_multi_transaction_sequence") is not True
            or transaction.get("request_sequences_consumed") != [1, 2]
            or transaction.get("gnss_hold_and_causal_requalification") is not True
            or transaction.get(
                "gnss_bootstrap_in_progress_observed_by_supervisor"
            )
            is not True
            or transaction.get("first_post_requalification_consumer_exact")
            is not True
            or not isinstance(
                transaction.get(
                    "first_post_recovery_consumer_decision_sequence"
                ),
                int,
            )
            or not qualified_boundary_exact
            or manifest.get("programme_id") != programme.programme_id
            or manifest.get("profile_identity") != programme.profile_id
            or set(exact_files) != set(required_exact)
            or any(
                exact_files[name].get("path") != expected_path
                or exact_files[name].get("optional") is not None
                for name, expected_path in required_exact.items()
            )
            or manifest.get("contracts", {}).get("active_transactions_v2") != 2
            or manifest.get("contracts", {}).get("active_hybrid_decisions_v2") != 2
            or domain_errors
            or not any(
                isinstance(item, dict)
                and item.get("name") == "rp2040_timer0_extended"
                and item.get("nominal_hz") == 16_000_000
                for item in domains
            )
        ):
            raise ValueError(
                "Campaign 18 rehearsal lacks the activation-bearing exact "
                "transaction, GNSS, or qualified-clock path"
            )
    if require_current_tools:
        if not isinstance(tool_bindings, dict):
            raise ValueError("CX320 rehearsal tool bindings are unavailable")
        for name, item in tool_bindings.items():
            if not isinstance(item, dict):
                raise ValueError(f"CX320 rehearsal tool binding is malformed: {name}")
            bound_path = Path(str(item.get("path", "")))
            if not bound_path.is_file() or not _binding_matches(item, bound_path):
                raise ValueError(f"CX320 rehearsal tool binding differs: {name}")
    return {
        **_binding(path),
        "report_type": programme.rehearsal_report_type,
        "rehearsal_sha256": claimed,
    }


def _authority(
    programme: ActiveHybridProgramme = CX320_PROGRAMME,
) -> dict[str, Any]:
    value: dict[str, Any] = {
        "effective": True,
        "physical_execution": True,
        "firmware_flash_limit": 1,
        "reset_for_entry_or_bounded_recovery": True,
        "serial_open": True,
        "command_fifo": True,
        "setup_stimulus": True,
        "setup_code": programme.setup_code,
        "setup_write_limit": 1,
        "control_arm": True,
        "live_acquisition_limit": 1,
        "maximum_total_automatic_applications": (
            programme.authorized_maximum_applications
        ),
        "maximum_total_physical_control_applications": (
            programme.authorized_maximum_physical_applications
        ),
        "maximum_deliberate_challenges": programme.maximum_deliberate_challenges,
        **progressive_checkpoint_contract(programme),
        "maximum_combined_step_codes": programme.maximum_step_codes,
        "maximum_cumulative_absolute_movement_codes": (
            programme.authorized_maximum_cumulative_movement_codes
        ),
        "minimum_applied_cadence_s": programme.minimum_applied_cadence_s,
        "minimum_code": programme.minimum_code,
        "maximum_code": programme.maximum_code,
        "qualified_duration_s": programme.qualified_duration_s,
        "absolute_wall_clock_limit_s": programme.authorized_absolute_wall_limit_s,
        "maximum_outstanding_requests": 1,
        "automatic_retry": False,
        "automatic_restoration": False,
        "live_extension": False,
        "authority_consumed_by_first_physical_terminal": True,
    }
    if programme.forwarded_output_integration:
        value["setup_provenance"] = integrated_setup_provenance_contract(
            programme
        )
    return value


def _attempt_descriptor(
    *,
    ordinal: int,
    reason: str,
    predecessor_terminal_path: Path | None,
    programme: ActiveHybridProgramme = CX320_PROGRAMME,
) -> dict[str, Any]:
    if type(ordinal) is not int or ordinal < 1:
        raise ValueError("CX320 attempt ordinal must be a positive integer")
    reason = reason.strip()
    if not reason:
        raise ValueError("CX320 attempt requires a concrete reason")
    if ordinal == 1:
        if predecessor_terminal_path is not None:
            raise ValueError("initial CX320 attempt cannot name a predecessor terminal")
        predecessor: dict[str, Any] | None = None
    else:
        if predecessor_terminal_path is None:
            raise ValueError("later CX320 attempt requires a predecessor terminal")
        predecessor_terminal_path = predecessor_terminal_path.resolve()
        seal = _semantic_object(
            predecessor_terminal_path,
            "seal_sha256",
            "CX320 predecessor physical terminal seal",
        )
        run_dir = predecessor_terminal_path.parents[1]
        terminal = seal.get("terminal", {})
        supervisor_terminal = (
            terminal.get("supervisor_terminal", {})
            if isinstance(terminal, dict)
            else {}
        )
        acquisition_gate = seal.get("acquisition_gate", {})
        offline_finalization_gate = seal.get("offline_finalization_gate", {})
        scientific_checks = seal.get("scientific_acceptance_checks", {})
        if not scientific_checks and isinstance(
            seal.get("descriptive_prior_comparisons"), dict
        ):
            scientific_checks = seal["descriptive_prior_comparisons"]
        endpoint_complete_check = (
            scientific_checks.get("qualified_endpoint_complete")
            if isinstance(scientific_checks, dict)
            else None
        )
        if endpoint_complete_check is None and isinstance(
            scientific_checks, dict
        ):
            endpoint_complete_check = scientific_checks.get(
                "qualified_12h_endpoint_complete"
            )
        operator_abort_decisions = {"operator_abort"}
        operator_abort_decisions.update(
            decision
            for decision in programme.terminal_decisions
            if decision.endswith("_operator_abort")
        )
        campaign18_legacy_live_health_handoff = (
            isinstance(supervisor_terminal, dict)
            and isinstance(supervisor_terminal.get("reason"), str)
            and re.fullmatch(
                r"cx322_d9_d6_72h_live_supervisor_fault:"
                r"active live-health handoff is invalid: new snapshot "
                r"generation began before the prior generation [1-9][0-9]* "
                r"completed",
                supervisor_terminal["reason"],
            )
            is not None
        )
        failed_physical_gate = (
            seal.get("status") == "failed"
            and seal.get("primary_decision")
            == "measurement_authority_or_platform_fault"
            and acquisition_gate.get("passed") is False
            and offline_finalization_gate.get(
                "replayable_without_physical_repeat"
            )
            is False
        )
        failed_post_acquisition_gate = (
            seal.get("status") == "failed"
            and seal.get("primary_decision")
            == "measurement_authority_or_platform_fault"
            and acquisition_gate.get("passed") is True
            and isinstance(terminal, dict)
            and terminal.get("endpoint_complete") is False
            and terminal.get("static_terminal_exact") is True
            and terminal.get("abort_submission_count") == 1
            and terminal.get("abort_delivery_count") == 1
            and isinstance(supervisor_terminal, dict)
            and supervisor_terminal.get("result") == "aborted"
        )
        campaign18_capture_terminal = (
            programme is CX322_D9_D6_72H_PROGRAMME
            and seal.get("status") == "failed"
            and acquisition_gate.get("passed") is True
            and isinstance(terminal, dict)
            and terminal.get("endpoint_complete") is False
            and terminal.get("static_terminal_exact") is True
            and terminal.get("abort_submission_count") == 1
            and terminal.get("abort_delivery_count") == 1
            and endpoint_complete_check is False
            and isinstance(supervisor_terminal, dict)
            and supervisor_terminal.get("result") == "aborted"
            and (
                seal.get("primary_decision")
                == "cx322_d9_d6_72h_D14_D8_authority_or_capture_fault"
                or (
                    seal.get("primary_decision")
                    == "cx322_d9_d6_72h_identity_or_evidence_fault"
                    and supervisor_terminal.get("primary_decision")
                    == "measurement_authority_or_platform_fault"
                    and (
                        supervisor_terminal.get("reason")
                        == (
                            "cx322_d9_d6_72h_live_supervisor_fault:"
                            "live active_fail_static asserted"
                        )
                        or campaign18_legacy_live_health_handoff
                    )
                )
            )
        )
        cx323_firmware_fail_static_terminal = (
            programme is CX323_D9_D6_72H_PROGRAMME
            and seal.get("status") == "failed"
            and seal.get("primary_decision")
            == "cx323_d9_d6_72h_identity_or_evidence_fault"
            and acquisition_gate.get("passed") is False
            and offline_finalization_gate.get(
                "replayable_without_physical_repeat"
            )
            is False
            and isinstance(terminal, dict)
            and terminal.get("endpoint_complete") is False
            and terminal.get("abort_submission_count") == 1
            and terminal.get("abort_delivery_count") == 1
            and isinstance(supervisor_terminal, dict)
            and supervisor_terminal.get("result") == "aborted"
            and supervisor_terminal.get("primary_decision")
            == "cx323_d9_d6_72h_identity_or_evidence_fault"
            and supervisor_terminal.get("reason")
            == (
                "cx323_d9_d6_72h_live_supervisor_fault:"
                "live active_fail_static asserted"
            )
            and isinstance(terminal.get("static_code"), int)
            and programme.minimum_code
            <= terminal["static_code"]
            <= programme.maximum_code
            and supervisor_terminal.get("last_confirmed_code")
            == terminal["static_code"]
        )
        # Campaign19 Attempt 7 reached the first request frontier before the
        # original host inspected the already-retained firmware partition
        # fault.  Its sealed terminal therefore carries the old
        # acknowledgement-observation diagnosis instead of the later exact
        # ``live active_fail_static asserted`` reason.  Accept only that
        # complete, immutable legacy shape as evidence of an incomplete gate;
        # this authorizes a new identified attempt without reclassifying the
        # predecessor as a successful acquisition.
        cx323_legacy_ack_observation_terminal = (
            programme is CX323_D9_D6_72H_PROGRAMME
            and seal.get("status") == "failed"
            and seal.get("primary_decision")
            == "cx323_d9_d6_72h_identity_or_evidence_fault"
            and acquisition_gate.get("passed") is False
            and offline_finalization_gate.get(
                "replayable_without_physical_repeat"
            )
            is False
            and seal.get("evidence_snapshot_validation")
            == {"failures": [], "warnings": []}
            and isinstance(terminal, dict)
            and terminal.get("endpoint_complete") is False
            and terminal.get("latest_hybrid_state")
            == "FIRST_PHASE_TRANSACTION"
            and terminal.get("static_terminal_exact") is False
            and terminal.get("abort_submission_count") == 1
            and terminal.get("abort_delivery_count") == 1
            and isinstance(terminal.get("static_code"), int)
            and programme.minimum_code
            <= terminal["static_code"]
            <= programme.maximum_code
            and isinstance(supervisor_terminal, dict)
            and supervisor_terminal.get("result") == "aborted"
            and supervisor_terminal.get("primary_decision")
            == "cx323_d9_d6_72h_identity_or_evidence_fault"
            and supervisor_terminal.get("reason")
            == (
                "cx323_d9_d6_72h_live_supervisor_fault:"
                "active-hybrid evidence acknowledgement reached the host "
                "serial write boundary but firmware consumption is unconfirmed"
            )
            and supervisor_terminal.get("last_confirmed_code")
            == terminal["static_code"]
            and isinstance(seal.get("source_artifacts_sha256"), dict)
            and all(
                isinstance(seal["source_artifacts_sha256"].get(path), str)
                and len(seal["source_artifacts_sha256"][path]) == 64
                for path in (
                    "COMPLETE",
                    "csv/health.csv",
                    "raw/serial.log",
                    "reports/cx317_active_supervisor_events.jsonl",
                    "reports/cx317_active_supervisor_state.json",
                )
            )
        )
        # Campaign19 Attempt 8 completed its first exact application and
        # response, but the CX323 status getter subsequently overwrote the
        # correct CX323 counters/checkpoint with zero-valued legacy-engine
        # fields.  The live supervisor correctly rejected the resulting
        # impossible ``HYBRID_TRACKING`` snapshot.  Accept only the sealed
        # shape whose independent transaction and maintenance replay proves
        # that exact response checkpoint; this admits a new identified
        # attempt without reclassifying the interrupted acquisition.
        application_counts = seal.get("application_counts_and_budgets", {})
        timing_join = seal.get("integrated_exact_timing_sidecar_join", {})
        active_replay = seal.get("active_hybrid_replay", {})
        acquisition_checks = acquisition_gate.get("checks", {})
        cx323_status_serialization_terminal = (
            programme is CX323_D9_D6_72H_PROGRAMME
            and seal.get("status") == "failed"
            and seal.get("primary_decision")
            == "cx323_d9_d6_72h_identity_or_evidence_fault"
            and acquisition_gate.get("passed") is True
            and offline_finalization_gate.get(
                "replayable_without_physical_repeat"
            )
            is True
            and seal.get("evidence_snapshot_validation")
            == {"failures": [], "warnings": []}
            and isinstance(terminal, dict)
            and terminal.get("endpoint_complete") is False
            and terminal.get("latest_hybrid_state") == "HYBRID_TRACKING"
            and terminal.get("static_terminal_exact") is True
            and terminal.get("abort_submission_count") == 1
            and terminal.get("abort_delivery_count") == 1
            and isinstance(terminal.get("static_code"), int)
            and programme.minimum_code
            <= terminal["static_code"]
            <= programme.maximum_code
            and isinstance(supervisor_terminal, dict)
            and supervisor_terminal.get("result") == "aborted"
            and supervisor_terminal.get("primary_decision")
            == "cx323_d9_d6_72h_identity_or_evidence_fault"
            and supervisor_terminal.get("reason")
            == (
                "cx323_d9_d6_72h_live_supervisor_fault:"
                "CX320 HYBRID_TRACKING lacks the first checkpoint"
            )
            and supervisor_terminal.get("last_confirmed_code")
            == terminal["static_code"]
            and isinstance(application_counts, dict)
            and application_counts.get("exact") is True
            and application_counts.get("automatic_application_count") == 1
            and application_counts.get("physical_control_application_count")
            == 1
            and application_counts.get("phase_material_application_count") == 1
            and application_counts.get("first_phase_checkpoint_passed") is True
            and application_counts.get(
                "first_phase_observation_checkpoint_exact"
            )
            is True
            and application_counts.get("all_response_checkpoints_passed")
            is True
            and isinstance(timing_join, dict)
            and timing_join.get("exact") is True
            and timing_join.get("mismatches") == []
            and isinstance(active_replay, dict)
            and active_replay.get("all_response_checkpoints_passed") is True
            and isinstance(seal.get("source_artifacts_sha256"), dict)
            and all(
                isinstance(seal["source_artifacts_sha256"].get(path), str)
                and len(seal["source_artifacts_sha256"][path]) == 64
                for path in (
                    "COMPLETE",
                    "csv/active_hybrid_maintenance_v1.csv",
                    "csv/active_transactions_v2.csv",
                    "csv/health.csv",
                    "raw/serial.log",
                    "reports/cx317_active_supervisor_events.jsonl",
                    "reports/cx317_active_supervisor_state.json",
                )
            )
        )
        # Campaign19 Attempt 10 completed and durably released its first exact
        # response checkpoint, then correctly cleared the firmware's current-
        # transaction checkpoint when its second application began.  The host
        # mistook that transient level for the already-latched authority gate
        # and aborted.  Accept only the sealed two-application shape that
        # proves the first causal release and the bounded static abort.  This
        # admits a new identified attempt without reclassifying the incomplete
        # acquisition or weakening any scientific acceptance criterion.
        cx323_latched_checkpoint_semantic_contract_terminal = (
            programme is CX323_D9_D6_72H_PROGRAMME
            and seal.get("status") == "failed"
            and seal.get("primary_decision")
            == "cx323_d9_d6_72h_identity_or_evidence_fault"
            and acquisition_gate.get("passed") is False
            and offline_finalization_gate.get(
                "replayable_without_physical_repeat"
            )
            is False
            and seal.get("evidence_snapshot_validation")
            == {"failures": [], "warnings": []}
            and isinstance(acquisition_checks, dict)
            and acquisition_checks.get("command_stream_exact") is True
            and acquisition_checks.get(
                "response_identity_through_first_dependent_decision_exact"
            )
            is True
            and acquisition_checks.get(
                "abort_submission_delivery_and_close_order_exact"
            )
            is True
            and isinstance(terminal, dict)
            and terminal.get("endpoint_complete") is False
            and terminal.get("latest_hybrid_state")
            == "FIRST_PHASE_TRANSACTION"
            and terminal.get("static_terminal_exact") is False
            and terminal.get("abort_submission_count") == 1
            and terminal.get("abort_delivery_count") == 1
            and isinstance(terminal.get("static_code"), int)
            and programme.minimum_code
            <= terminal["static_code"]
            <= programme.maximum_code
            and isinstance(supervisor_terminal, dict)
            and supervisor_terminal.get("result") == "aborted"
            and supervisor_terminal.get("primary_decision")
            == "cx323_d9_d6_72h_identity_or_evidence_fault"
            and supervisor_terminal.get("reason")
            == (
                "cx323_d9_d6_72h_live_supervisor_fault:"
                "CX320 later material authority preceded its checkpoint"
            )
            and supervisor_terminal.get("last_confirmed_code")
            == terminal["static_code"]
            and isinstance(application_counts, dict)
            and application_counts.get("exact") is False
            and application_counts.get("setup_count") == 1
            and application_counts.get("automatic_application_count") == 2
            and application_counts.get("physical_control_application_count")
            == 2
            and application_counts.get("phase_material_application_count") == 2
            and application_counts.get("cumulative_movement_codes") == 2
            and application_counts.get("first_phase_checkpoint_passed") is True
            and application_counts.get(
                "first_phase_observation_checkpoint_exact"
            )
            is True
            and application_counts.get(
                "later_authority_gated_by_first_checkpoint"
            )
            is True
            and application_counts.get("all_response_checkpoints_passed")
            is True
            and application_counts.get("dac_application_exact") is True
            and application_counts.get(
                "budgets_range_step_cadence_and_clamp_exact"
            )
            is True
            and isinstance(timing_join, dict)
            and timing_join.get("exact") is True
            and timing_join.get("mismatches") == []
            and isinstance(active_replay, dict)
            and active_replay.get("exact") is False
            and active_replay.get("phase_material_decision_count") == 2
            and active_replay.get("all_response_checkpoints_passed") is True
            and active_replay.get("unmatched_request_decision_sequences") == []
            and isinstance(seal.get("source_artifacts_sha256"), dict)
            and all(
                isinstance(seal["source_artifacts_sha256"].get(path), str)
                and len(seal["source_artifacts_sha256"][path]) == 64
                for path in (
                    "COMPLETE",
                    "csv/active_hybrid_decisions_v2.csv",
                    "csv/active_hybrid_maintenance_v1.csv",
                    "csv/active_transactions_v2.csv",
                    "csv/health.csv",
                    "raw/serial.log",
                    "reports/cx317_active_supervisor_events.jsonl",
                    "reports/cx317_active_supervisor_state.json",
                )
            )
        )
        bounded_operator_abort = (
            seal.get("status") == "bounded_nonpass"
            and seal.get("primary_decision") in operator_abort_decisions
            and isinstance(terminal, dict)
            and terminal.get("abort_submission_count") == 1
            and terminal.get("abort_delivery_count") == 1
            and isinstance(supervisor_terminal, dict)
            and supervisor_terminal.get("result") == "aborted"
            and supervisor_terminal.get("reason")
            == "independent_host_abort_fifo"
            and terminal.get("endpoint_complete") is False
            and endpoint_complete_check is False
        )
        bounded_pre_setup_provenance = (
            seal.get("status") == "bounded_nonpass"
            and seal.get("primary_decision")
            == "pre_setup_provenance_unresolved"
            and acquisition_gate.get("passed") is True
            and isinstance(terminal, dict)
            and terminal.get("endpoint_complete") is False
            and terminal.get("abort_submission_count") == 1
            and terminal.get("abort_delivery_count") == 1
            and isinstance(supervisor_terminal, dict)
            and supervisor_terminal.get("result") == "aborted"
            and seal.get("pre_setup_provenance_terminal", {}).get("exact")
            is True
        )
        if (
            not (run_dir / "COMPLETE").is_file()
            or not (
                failed_physical_gate
                or failed_post_acquisition_gate
                or campaign18_capture_terminal
                or cx323_firmware_fail_static_terminal
                or cx323_legacy_ack_observation_terminal
                or cx323_status_serialization_terminal
                or cx323_latched_checkpoint_semantic_contract_terminal
                or bounded_operator_abort
                or bounded_pre_setup_provenance
            )
        ):
            raise ValueError(
                "CX320 predecessor does not establish an incomplete physical gate "
                "requiring a new identified attempt"
            )
        predecessor = {
            **_binding(predecessor_terminal_path),
            "seal_sha256": seal["seal_sha256"],
            "run_id": seal["run_id"],
            "bundle_sha256": seal["bundle_sha256"],
            "build_identity": seal["build_identity"],
            "primary_decision": seal["primary_decision"],
            "evidence_content_sha256": package_identity(run_dir)[
                "content_sha256"
            ],
        }
    return {
        "ordinal": ordinal,
        "reason": reason,
        "predecessor_physical_terminal": predecessor,
        "automatic_retry": False,
    }


def create_activation(
    *,
    bundle_path: Path,
    proposal_path: Path,
    operational_rehearsal_path: Path,
    serial_device: str,
    operator_instruction_ref: str,
    output_path: Path,
    attempt_ordinal: int = 1,
    attempt_reason: str = DEFAULT_ATTEMPT_REASON,
    predecessor_terminal_path: Path | None = None,
    programme: ActiveHybridProgramme = CX320_PROGRAMME,
) -> dict[str, Any]:
    if programme.fresh_serial_auto_detect:
        if serial_device not in {"auto-detect", "--auto-detect"}:
            raise ValueError(
                "integrated activation requires fresh --auto-detect selection"
            )
        device_contract: dict[str, Any] = {
            "path": None,
            "selection": FRESH_SERIAL_AUTO_DETECT,
            "baud": EXPECTED_BAUD,
            "expected_board_serial": None,
        }
    else:
        if not serial_device.startswith("/dev/"):
            raise ValueError(
                "CX320 activation requires an explicit /dev serial path"
            )
        device_contract = {
            "path": serial_device,
            "baud": EXPECTED_BAUD,
            "expected_board_serial": EXPECTED_BOARD_SERIAL,
        }
    if not operator_instruction_ref.strip():
        raise ValueError("CX320 activation requires an operator-instruction reference")
    bundle = _validate_current_bundle(bundle_path, programme)
    proposal = (
        validate_proposal(proposal_path)
        if programme is CX320_PROGRAMME
        else validate_proposal(proposal_path, programme)
    )
    frozen_bundle, frozen_proposal = _validate_frozen_inputs(
        bundle_path=bundle_path,
        proposal_path=proposal_path,
        programme=programme,
    )
    if bundle != frozen_bundle or proposal != frozen_proposal:
        raise ValueError("CX320 current and frozen input validation differs")
    if not _bundle_binds_this_tool(bundle):
        raise ValueError("CX320 bundle does not bind the activation/manifest tool")
    if not _git_clean():
        raise ValueError("CX320 live activation requires a clean repository")
    rehearsal = validate_operational_rehearsal(
        operational_rehearsal_path,
        bundle=bundle,
        proposal=proposal,
        require_current_tools=True,
        programme=programme,
    )
    unsigned: dict[str, Any] = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "tool_binding": _binding(Path(__file__)),
        "activation_id": programme.activation_id,
        "created_utc": _utc_now(),
        "programme_id": programme.programme_id,
        "operation": programme.operation,
        "status": "effective_exact_bundle_authority",
        "operator_instruction_ref": operator_instruction_ref.strip(),
        "run_identity": programme.runtime_run_identity,
        "profile_identity": programme.profile_id,
        "bundle": {
            **_binding(bundle_path),
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "proposal": {
            **_binding(proposal_path),
            "proposal_sha256": proposal["proposal_sha256"],
        },
        "authority_lineage": proposal.get("lineage"),
        "attempt": _attempt_descriptor(
            ordinal=attempt_ordinal,
            reason=attempt_reason,
            predecessor_terminal_path=predecessor_terminal_path,
            programme=programme,
        ),
        "operational_rehearsal": rehearsal,
        "device": device_contract,
        "firmware": bundle["firmware"],
        "policy": bundle["policy"],
        "host_tools": bundle["host_tools"],
        "topology": {
            "serial_owner": "capture_device",
            "serial_owner_count": 1,
            "fifos": FIFO_PATHS,
        },
        "setup": {
            "code": programme.setup_code,
            "code_hex": f"0x{programme.setup_code:04X}",
            "maximum_applications": 1,
            "same_code_reapplication_opens_new_epoch": True,
            "exact_consumer_epoch_propagation_required": True,
            **(
                {
                    "provenance": integrated_setup_provenance_contract(
                        programme
                    )
                }
                if programme.forwarded_output_integration
                else {}
            ),
        },
        "authority": _authority(programme),
    }
    activation = {
        **unsigned,
        "activation_sha256": _canonical_sha256(unsigned),
    }
    _atomic_new_json(output_path, activation)
    return activation


def validate_frozen_activation(
    path: Path,
    *,
    bundle_path: Path | None = None,
    proposal_path: Path | None = None,
    programme: ActiveHybridProgramme | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    path = path.resolve()
    activation = _read_object(path, "CX320 live activation")
    programme = programme or programme_from_mapping(activation)
    claimed = activation.get("activation_sha256")
    unsigned = {
        key: item for key, item in activation.items() if key != "activation_sha256"
    }
    bundle_binding = activation.get("bundle", {})
    proposal_binding = activation.get("proposal", {})
    topology = activation.get("topology")
    device = activation.get("device")
    if (
        not isinstance(bundle_binding, dict)
        or not isinstance(proposal_binding, dict)
        or not isinstance(topology, dict)
        or not isinstance(device, dict)
    ):
        raise ValueError("CX320 activation bundle or proposal binding is malformed")
    bound_bundle_path = Path(str(bundle_binding.get("path", ""))).resolve()
    bound_proposal_path = Path(str(proposal_binding.get("path", ""))).resolve()
    bundle_overridden = bundle_path is not None
    proposal_overridden = proposal_path is not None
    bundle_path = (bundle_path or bound_bundle_path).resolve()
    proposal_path = (proposal_path or bound_proposal_path).resolve()
    bundle, proposal = _validate_frozen_inputs(
        bundle_path=bundle_path,
        proposal_path=proposal_path,
        programme=programme,
    )
    host_tools = bundle.get("host_tools")
    if not isinstance(host_tools, dict):
        raise ValueError("CX320 activation host-tool binding is malformed")
    fifos = topology.get("fifos", {})
    expected_device = (
        {
            "path": None,
            "selection": FRESH_SERIAL_AUTO_DETECT,
            "baud": EXPECTED_BAUD,
            "expected_board_serial": None,
        }
        if programme.fresh_serial_auto_detect
        else {
            "path": device.get("path"),
            "baud": EXPECTED_BAUD,
            "expected_board_serial": EXPECTED_BOARD_SERIAL,
        }
    )
    if (
        activation.get("schema_version") != 1
        or activation.get("tool") != TOOL_ID
        or activation.get("activation_id") != programme.activation_id
        or activation.get("programme_id") != programme.programme_id
        or activation.get("operation") != programme.operation
        or activation.get("status") != "effective_exact_bundle_authority"
        or activation.get("run_identity") != programme.runtime_run_identity
        or activation.get("profile_identity") != programme.profile_id
        or claimed != _canonical_sha256(unsigned)
        or not _binding_content_matches(bundle_binding, bundle_path)
        or (not bundle_overridden and bundle_binding.get("path") != str(bundle_path))
        or bundle_binding.get("bundle_sha256") != bundle["bundle_sha256"]
        or not _binding_content_matches(proposal_binding, proposal_path)
        or (
            not proposal_overridden
            and proposal_binding.get("path") != str(proposal_path)
        )
        or proposal_binding.get("proposal_sha256") != proposal["proposal_sha256"]
        or activation.get("authority_lineage") != proposal.get("lineage")
        or activation.get("firmware") != bundle.get("firmware")
        or activation.get("policy") != bundle.get("policy")
        or activation.get("host_tools") != host_tools
        or activation.get("tool_binding") not in list(host_tools.values())
        or activation.get("device") != expected_device
        or (
            not programme.fresh_serial_auto_detect
            and not str(device.get("path", "")).startswith("/dev/")
        )
        or topology.get("serial_owner") != "capture_device"
        or topology.get("serial_owner_count") != 1
        or fifos != FIFO_PATHS
        or len(set(fifos.values())) != 3
        or activation.get("setup")
        != {
            "code": programme.setup_code,
            "code_hex": f"0x{programme.setup_code:04X}",
            "maximum_applications": 1,
            "same_code_reapplication_opens_new_epoch": True,
            "exact_consumer_epoch_propagation_required": True,
            **(
                {
                    "provenance": integrated_setup_provenance_contract(
                        programme
                    )
                }
                if programme.forwarded_output_integration
                else {}
            ),
        }
        or activation.get("authority") != _authority(programme)
    ):
        raise ValueError("CX320 activation identity, topology, or authority differs")
    attempt = activation.get("attempt")
    if not isinstance(attempt, dict):
        raise ValueError("CX320 activation attempt identity is malformed")
    predecessor = attempt.get("predecessor_physical_terminal")
    predecessor_path = (
        Path(str(predecessor.get("path", "")))
        if isinstance(predecessor, dict)
        else None
    )
    expected_attempt = _attempt_descriptor(
        ordinal=attempt.get("ordinal"),
        reason=str(attempt.get("reason", "")),
        predecessor_terminal_path=predecessor_path,
        programme=programme,
    )
    if attempt != expected_attempt:
        raise ValueError("CX320 activation attempt lineage differs")
    rehearsal_binding = activation.get("operational_rehearsal", {})
    rehearsal_path = Path(str(rehearsal_binding.get("path", ""))).resolve()
    observed_rehearsal = validate_operational_rehearsal(
        rehearsal_path,
        bundle=bundle,
        proposal=proposal,
        require_current_tools=False,
        programme=programme,
    )
    if rehearsal_binding != observed_rehearsal:
        raise ValueError("CX320 activation rehearsal binding differs")
    return activation, bundle, proposal


def validate_activation(
    path: Path,
    *,
    bundle_path: Path | None = None,
    proposal_path: Path | None = None,
    programme: ActiveHybridProgramme | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    activation, frozen_bundle, frozen_proposal = validate_frozen_activation(
        path,
        bundle_path=bundle_path,
        proposal_path=proposal_path,
        programme=programme,
    )
    programme = programme or programme_from_mapping(activation)
    current_bundle = _validate_current_bundle(
        (bundle_path or Path(activation["bundle"]["path"])).resolve(), programme
    )
    current_proposal_path = (
        proposal_path or Path(activation["proposal"]["path"])
    ).resolve()
    current_proposal = (
        validate_proposal(current_proposal_path)
        if programme is CX320_PROGRAMME
        else validate_proposal(current_proposal_path, programme)
    )
    if current_bundle != frozen_bundle or current_proposal != frozen_proposal:
        raise ValueError("CX320 current activation inputs differ from retained inputs")
    if not _binding_matches(activation.get("tool_binding"), Path(__file__)):
        raise ValueError("CX320 activation tool identity differs")
    if not _bundle_binds_this_tool(current_bundle):
        raise ValueError("CX320 current bundle no longer binds activation tool")
    if not _git_clean():
        raise ValueError("CX320 live execution requires a clean repository")
    validate_operational_rehearsal(
        Path(activation["operational_rehearsal"]["path"]),
        bundle=current_bundle,
        proposal=current_proposal,
        require_current_tools=True,
        programme=programme,
    )
    return activation, current_bundle, current_proposal


def _required_files(
    programme: ActiveHybridProgramme = CX320_PROGRAMME,
) -> list[dict[str, Any]]:
    required = {
        "pps_snapshots_v1",
        "reference_observations_v1",
        "diagnostics_v1",
        "estimates_v2",
        "control_previews_v1",
        "active_transactions_v1",
        "active_hybrid_decisions_v1",
        "relative_phase_observations_v1",
        "phase_estimator_outputs_v1",
        "hybrid_preview_decisions_v1",
        "tight_deadband_decisions_v1",
    }
    if programme.persistent_maintenance_policy:
        source = cx323_active_timing_csv_files()
        required.update(
            {
                "active_transactions_v2",
                "active_hybrid_decisions_v2",
                programme.maintenance_record_contract,
            }
        )
    elif programme.integrated_long_run:
        source = exact_active_timing_csv_files()
        required.update(
            {"active_transactions_v2", "active_hybrid_decisions_v2"}
        )
    elif programme.identification_required:
        source = cx321_csv_files()
    else:
        source = default_csv_files()
    files: list[dict[str, Any]] = [dict(entry) for entry in source]
    if programme.identification_required:
        required.add("plant_sign_qualification_v1")
    for entry in files:
        if entry["contract"] in required:
            entry.pop("optional", None)
    return files


def create_run_manifest(
    *,
    activation_path: Path,
    bundle_path: Path,
    proposal_path: Path,
    run_dir: Path,
    output_path: Path,
    serial_device: str | None = None,
) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    output_path = output_path.resolve()
    if output_path != (run_dir / RUN_MANIFEST_PATH).resolve():
        raise ValueError("CX320 live manifest must be run-local run_manifest.json")
    activation_value = _read_object(activation_path, "active-hybrid activation")
    programme = programme_from_mapping(activation_value)
    activation, bundle, proposal = validate_activation(
        activation_path,
        bundle_path=bundle_path,
        proposal_path=proposal_path,
        programme=programme,
    )
    actual_device = serial_device or str(activation["device"]["path"])
    if not actual_device.startswith("/dev/"):
        raise ValueError(
            "CX320 live manifest requires the freshly resolved serial device"
        )
    files = _required_files(programme)
    authority = activation["authority"]
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "compatibility_floor": programme.compatibility_floor,
        "template": False,
        "run_id": run_dir.name,
        "created_utc": _utc_now(),
        "started_at_utc": _utc_now(),
        "stage": programme.live_stage,
        "programme_id": programme.programme_id,
        "run_identity": programme.runtime_run_identity,
        "profile_identity": programme.profile_id,
        "board": "arduino_nano_rp2040_connect",
        "capture_mode": "pio_wait_cumulative_snapshot_with_independent_gpio_ref",
        "control_mode": (
            "bounded_active_hybrid_plant_sign_phase_frequency"
            if programme.identification_required
            else "bounded_active_hybrid_phase_frequency"
        ),
        "closed_loop_control": True,
        "actionable": True,
        "actuation_authorized": True,
        "qualification_evidence": True,
        "bundle": {
            **_binding(bundle_path),
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "proposal": {
            **_binding(proposal_path),
            "proposal_sha256": proposal["proposal_sha256"],
        },
        "activation": {
            **_binding(activation_path),
            "activation_sha256": activation["activation_sha256"],
        },
        "firmware": bundle["firmware"],
        "policy": bundle["policy"],
        "host": {
            "capture_tool": "host.otis_tools.capture_device",
            "supervisor_tool": "host.otis_tools.active_hybrid_live_supervisor",
            "runner_tool": "host.otis_tools.active_hybrid_run",
            "analyzer_tool": "host.otis_tools.active_hybrid_live_analyze",
            "serial_device": actual_device,
            "activation_serial_device": activation["device"]["path"],
            **(
                {
                    "activation_device_selection": activation["device"][
                        "selection"
                    ]
                }
                if programme.fresh_serial_auto_detect
                else {}
            ),
            "baud": EXPECTED_BAUD,
            "expected_board_serial": activation["device"][
                "expected_board_serial"
            ],
            "sole_serial_owner": True,
            "serial_owner_count": 1,
            "fifos": FIFO_PATHS,
            "tool_bindings": bundle["host_tools"],
        },
        programme.manifest_section: {
            "mode": "active_hybrid_live",
            "profile_id": programme.profile_id,
            "run_identity": programme.runtime_run_identity,
            "authority": authority,
            "setup": {
                "code": programme.setup_code,
                "code_hex": f"0x{programme.setup_code:04X}",
                "maximum_applications": 1,
                "physical_applied_code_before_setup": (
                    integrated_setup_provenance_contract(programme)[
                        "physical_applied_code_before_setup"
                    ]
                    if programme.forwarded_output_integration
                    else "unknown"
                ),
                "same_code_reapplication_opens_new_epoch": True,
                "exact_consumer_epoch_propagation_required": True,
                **(
                    {
                        "provenance": integrated_setup_provenance_contract(
                            programme
                        )
                    }
                    if programme.forwarded_output_integration
                    else {}
                ),
            },
            "automatic_control": {
                "authorized": True,
                "maximum_total_applications": (
                    programme.authorized_maximum_physical_applications
                ),
                **(
                    {
                        "maximum_total_automatic_applications": (
                            programme.authorized_maximum_applications
                        ),
                        "maximum_deliberate_challenges": programme.maximum_deliberate_challenges,
                    }
                    if programme.sustained_regulation
                    else {}
                ),
                "maximum_step_codes": programme.maximum_step_codes,
                "maximum_cumulative_movement_codes": (
                    programme.authorized_maximum_cumulative_movement_codes
                ),
                "minimum_applied_cadence_s": programme.minimum_applied_cadence_s,
                "minimum_code": programme.minimum_code,
                "maximum_code": programme.maximum_code,
                "maximum_outstanding_requests": 1,
                "automatic_retry": False,
                "automatic_restore": False,
            },
            "progressive_authority": {
                **progressive_checkpoint_contract(programme),
            },
            "qualification": {
                "qualified_duration_s": programme.qualified_duration_s,
                **(
                    {
                        "qualified_endpoint_contract": "qualified_D14_D8_aperture_count_v2",
                        "qualified_d14_aperture_count": programme.qualified_d14_aperture_count,
                        "correction_response_reserve_d14_apertures": programme.correction_response_reserve_d14_apertures,
                    }
                    if programme.qualified_d14_aperture_count is not None
                    else {}
                ),
                "absolute_wall_clock_limit_s": (
                    programme.authorized_absolute_wall_limit_s
                ),
                "qualified_origin": bundle["finite_limits"]["qualified_origin"],
                "wall_clock_origin": bundle["finite_limits"]["wall_clock_origin"],
                "no_extension": True,
            },
        },
        "domains": [
            canonical_domain_declaration("rp2040_timer0"),
            canonical_domain_declaration("h1_cx317_ocxo_10mhz"),
        ],
        "channels": [
            *(
                [
                    {
                        "channel_id": 0,
                        "pin": "D10",
                        "role": (
                            "independent_external_event_not_control_authority"
                        ),
                        "record_family": "raw_events_v1",
                    }
                ]
                if programme.forwarded_output_integration
                else []
            ),
            {
                "channel_id": 1,
                "pin": "D14",
                "role": "authoritative_pps_reference",
                "record_family": "raw_events_v1",
            },
            {
                "channel_id": 2,
                "pin": "D8",
                "role": "pps_gated_oscillator_count",
                "record_family": "count_observations_v1",
            },
            {
                "channel_id": 3,
                "pin": "D6" if programme.forwarded_output_integration else "D10",
                "role": (
                    "diagnostic_forwarded_d9_clock_monitor_zero_authority"
                    if programme.forwarded_output_integration
                    else "independent_external_event_not_control_authority"
                ),
                "record_family": (
                    "forwarded_monitor_snapshots_v1"
                    if programme.forwarded_output_integration
                    else "raw_events_v1"
                ),
            },
        ],
        "contracts": {
            entry["contract"]: (
                2
                if entry["contract"]
                in {
                    "estimates_v2",
                    "active_transactions_v2",
                    "active_hybrid_decisions_v2",
                }
                else 1
            )
            for entry in files
        },
        "files": files,
        "expected_artifacts": [
            *[entry["path"] for entry in files if not entry.get("optional")],
            "raw/serial.log",
            "reports/capture_device_state.json",
            "reports/cx317_active_supervisor_state.json",
            "reports/cx317_active_supervisor_events.jsonl",
            "reports/capture_segment_closure_v1.json",
            str(programme.run_activation_path),
            str(programme.run_proposal_path),
            str(programme.run_bundle_path),
            "COMPLETE",
        ],
        "evidence_artifacts": [
            "reports/capture_device_state.json",
            "reports/cx317_active_supervisor_state.json",
            "reports/cx317_active_supervisor_events.jsonl",
            "reports/capture_segment_closure_v1.json",
            f"reports/{programme.key}_active_hybrid_capture.log",
            f"reports/{programme.key}_active_hybrid_supervisor.log",
            str(programme.run_activation_path),
            str(programme.run_proposal_path),
            str(programme.run_bundle_path),
            "COMPLETE",
        ],
        "known_limitations": [
            "D14 is the sole PPS/reference input and D8 the sole oscillator/count input.",
            "D10 is an independent event input and never enters timing or control authority.",
            *(
                [
                    "D9 digital source/divider/GPIO/readback evidence is not waveform, load, jitter, or independently referenced frequency qualification.",
                    "D6 is diagnostic-only; absence or local faults do not enter D14/D8 validity or steering authority.",
                ]
                if programme.forwarded_output_integration
                else []
            ),
            (
                "The result does not establish UTC, absolute phase, calibrated "
                "delay, traceable frequency accuracy, or holdover."
            ),
        ],
    }
    if (
        programme.identification_required
        or programme.integrated_long_run
    ):
        manifest["domains"].append(
            canonical_domain_declaration("rp2040_timer0_extended")
        )
    if programme.identification_required:
        manifest["programme_policy"] = bundle["programme_policy"]
        manifest["identification"] = bundle["identification"]
        manifest[programme.manifest_section]["plant_sign_identification"] = {
            "required": True,
            "contract": "plant_sign_qualification_v1",
            "programme_policy": bundle["programme_policy"],
        }
    manifest["manifest_sha256"] = _canonical_sha256(manifest)
    _atomic_new_json(output_path, manifest)
    return manifest


def validate_frozen_run_manifest(path: Path) -> dict[str, Any]:
    path = path.resolve()
    manifest = _read_object(path, "CX320 live run manifest")
    claimed = manifest.get("manifest_sha256")
    unsigned = {
        key: item for key, item in manifest.items() if key != "manifest_sha256"
    }
    if claimed != _canonical_sha256(unsigned):
        raise ValueError("CX320 run-manifest semantic identity differs")
    programme = programme_from_mapping(manifest)
    run_dir = path.parent.resolve()
    activation_binding = manifest.get("activation", {})
    bundle_binding = manifest.get("bundle", {})
    proposal_binding = manifest.get("proposal", {})
    activation_path = Path(str(activation_binding.get("path", ""))).resolve()
    bundle_path = Path(str(bundle_binding.get("path", ""))).resolve()
    proposal_path = Path(str(proposal_binding.get("path", ""))).resolve()
    activation, bundle, proposal = validate_frozen_activation(
        activation_path,
        bundle_path=bundle_path,
        proposal_path=proposal_path,
        programme=programme,
    )
    host = manifest.get("host", {})
    section = manifest.get(programme.manifest_section, {})
    if not isinstance(host, dict) or not isinstance(section, dict):
        raise ValueError("CX320 live run manifest host or programme section is malformed")
    control = section.get("automatic_control", {})
    progressive = section.get("progressive_authority", {})
    qualification = section.get("qualification", {})
    if (
        path != (run_dir / RUN_MANIFEST_PATH)
        or manifest.get("schema_version") != 1
        or manifest.get("compatibility_floor") != programme.compatibility_floor
        or manifest.get("template") is not False
        or manifest.get("stage") != programme.live_stage
        or manifest.get("programme_id") != programme.programme_id
        or manifest.get("run_identity") != programme.runtime_run_identity
        or manifest.get("profile_identity") != programme.profile_id
        or manifest.get("closed_loop_control") is not True
        or manifest.get("actionable") is not True
        or manifest.get("actuation_authorized") is not True
        or manifest.get("qualification_evidence") is not True
        or not _binding_matches(activation_binding, activation_path)
        or activation_binding.get("activation_sha256")
        != activation["activation_sha256"]
        or not _binding_matches(bundle_binding, bundle_path)
        or bundle_binding.get("bundle_sha256") != bundle["bundle_sha256"]
        or not _binding_matches(proposal_binding, proposal_path)
        or proposal_binding.get("proposal_sha256") != proposal["proposal_sha256"]
        or manifest.get("firmware") != bundle["firmware"]
        or manifest.get("policy") != bundle["policy"]
        or host.get("tool_bindings") != bundle["host_tools"]
        or host.get("activation_serial_device") != activation["device"]["path"]
        or (
            programme.fresh_serial_auto_detect
            and host.get("activation_device_selection")
            != activation["device"]["selection"]
        )
        or not str(host.get("serial_device", "")).startswith("/dev/")
        or host.get("baud") != EXPECTED_BAUD
        or host.get("expected_board_serial")
        != activation["device"]["expected_board_serial"]
        or host.get("sole_serial_owner") is not True
        or host.get("serial_owner_count") != 1
        or host.get("fifos") != FIFO_PATHS
        or len(set(host.get("fifos", {}).values())) != 3
        or section.get("authority") != activation["authority"]
        or section.get("run_identity") != programme.runtime_run_identity
        or section.get("setup")
        != {
            "code": programme.setup_code,
            "code_hex": f"0x{programme.setup_code:04X}",
            "maximum_applications": 1,
            "physical_applied_code_before_setup": (
                integrated_setup_provenance_contract(programme)[
                    "physical_applied_code_before_setup"
                ]
                if programme.forwarded_output_integration
                else "unknown"
            ),
            "same_code_reapplication_opens_new_epoch": True,
            "exact_consumer_epoch_propagation_required": True,
            **(
                {
                    "provenance": integrated_setup_provenance_contract(
                        programme
                    )
                }
                if programme.forwarded_output_integration
                else {}
            ),
        }
        or control
        != {
            "authorized": True,
            "maximum_total_applications": (
                programme.authorized_maximum_physical_applications
            ),
            **(
                {
                    "maximum_total_automatic_applications": (
                        programme.authorized_maximum_applications
                    ),
                    "maximum_deliberate_challenges": programme.maximum_deliberate_challenges,
                }
                if programme.sustained_regulation
                else {}
            ),
            "maximum_step_codes": programme.maximum_step_codes,
            "maximum_cumulative_movement_codes": (
                programme.authorized_maximum_cumulative_movement_codes
            ),
            "minimum_applied_cadence_s": programme.minimum_applied_cadence_s,
            "minimum_code": programme.minimum_code,
            "maximum_code": programme.maximum_code,
            "maximum_outstanding_requests": 1,
            "automatic_retry": False,
            "automatic_restore": False,
        }
        or progressive
        != progressive_checkpoint_contract(programme)
        or qualification.get("qualified_duration_s")
        != programme.qualified_duration_s
        or (
            programme.qualified_d14_aperture_count is not None
            and (
                qualification.get("qualified_endpoint_contract")
                != "qualified_D14_D8_aperture_count_v2"
                or qualification.get("qualified_d14_aperture_count")
                != programme.qualified_d14_aperture_count
                or qualification.get("correction_response_reserve_d14_apertures")
                != programme.correction_response_reserve_d14_apertures
            )
        )
        or qualification.get("absolute_wall_clock_limit_s")
        != programme.authorized_absolute_wall_limit_s
        or qualification.get("no_extension") is not True
    ):
        raise ValueError("CX320 live run manifest identity, topology, or bounds differ")
    required_contracts = {
        "active_transactions_v1",
        "active_hybrid_decisions_v1",
        "relative_phase_observations_v1",
        "phase_estimator_outputs_v1",
        "estimates_v2",
    }
    if programme.identification_required:
        required_contracts.add("plant_sign_qualification_v1")
        identification = section.get("plant_sign_identification", {})
        if (
            not isinstance(identification, dict)
            or identification.get("required") is not True
            or identification.get("contract")
            != "plant_sign_qualification_v1"
            or identification.get("programme_policy")
            != manifest.get("programme_policy")
            or manifest.get("programme_policy") != bundle.get("programme_policy")
            or manifest.get("identification") != bundle.get("identification")
        ):
            raise ValueError("CX321 plant-sign manifest binding differs")
    if not required_contracts <= set(manifest.get("contracts", {})):
        raise ValueError("CX320 live manifest lacks decision-bearing contracts")
    domain_errors = validate_domain_declarations(
        manifest.get("domains"),
    )
    if domain_errors:
        raise ValueError(
            "CX320 live manifest time-domain declaration differs: "
            + "; ".join(domain_errors)
        )
    return manifest


def validate_run_manifest(path: Path) -> dict[str, Any]:
    manifest = validate_frozen_run_manifest(path)
    programme = programme_from_mapping(manifest)
    domain_errors = validate_domain_declarations(
        manifest.get("domains"),
        require_complete=(programme.key == CX323_D9_D6_72H_PROGRAMME.key),
    )
    if domain_errors:
        raise ValueError(
            "CX320 current live manifest time-domain declaration differs: "
            + "; ".join(domain_errors)
        )
    validate_activation(
        Path(manifest["activation"]["path"]),
        bundle_path=Path(manifest["bundle"]["path"]),
        proposal_path=Path(manifest["proposal"]["path"]),
        programme=programme,
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    activate = commands.add_parser("activate")
    activate.add_argument("--bundle", type=Path, required=True)
    activate.add_argument("--proposal", type=Path, required=True)
    activate.add_argument("--operational-rehearsal", type=Path, required=True)
    device = activate.add_mutually_exclusive_group(required=True)
    device.add_argument("--serial-device")
    device.add_argument("--auto-detect", action="store_true")
    activate.add_argument("--operator-instruction-ref", required=True)
    activate.add_argument("--attempt-ordinal", type=int, default=1)
    activate.add_argument("--attempt-reason", default=DEFAULT_ATTEMPT_REASON)
    activate.add_argument("--predecessor-terminal", type=Path)
    activate.add_argument("--output", type=Path, required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("activation", type=Path)
    validate.add_argument("--bundle", type=Path)
    validate.add_argument("--proposal", type=Path)
    validate.add_argument("--frozen", action="store_true")
    manifest = commands.add_parser("manifest")
    manifest.add_argument("--activation", type=Path, required=True)
    manifest.add_argument("--bundle", type=Path, required=True)
    manifest.add_argument("--proposal", type=Path, required=True)
    manifest.add_argument("--run-dir", type=Path, required=True)
    manifest.add_argument("--output", type=Path, required=True)
    manifest.add_argument("--serial-device")
    validate_manifest = commands.add_parser("validate-manifest")
    validate_manifest.add_argument("manifest", type=Path)
    validate_manifest.add_argument("--frozen", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "activate":
            programme = programme_from_mapping(
                _read_object(args.bundle, "active-hybrid activation bundle")
            )
            result: Any = create_activation(
                bundle_path=args.bundle,
                proposal_path=args.proposal,
                operational_rehearsal_path=args.operational_rehearsal,
                serial_device=(
                    "--auto-detect" if args.auto_detect else args.serial_device
                ),
                operator_instruction_ref=args.operator_instruction_ref,
                output_path=args.output,
                attempt_ordinal=args.attempt_ordinal,
                attempt_reason=args.attempt_reason,
                predecessor_terminal_path=args.predecessor_terminal,
                programme=programme,
            )
        elif args.command == "validate":
            validator = validate_frozen_activation if args.frozen else validate_activation
            result = validator(
                args.activation,
                bundle_path=args.bundle,
                proposal_path=args.proposal,
            )[0]
        elif args.command == "manifest":
            result = create_run_manifest(
                activation_path=args.activation,
                bundle_path=args.bundle,
                proposal_path=args.proposal,
                run_dir=args.run_dir,
                output_path=args.output,
                serial_device=args.serial_device,
            )
        else:
            validator = (
                validate_frozen_run_manifest
                if args.frozen
                else validate_run_manifest
            )
            result = validator(args.manifest)
    except (
        FileExistsError,
        FileNotFoundError,
        KeyError,
        OSError,
        RuntimeError,
        subprocess.SubprocessError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
