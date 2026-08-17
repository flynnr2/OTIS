"""Activate and manifest an exact bounded tight-deadband physical workflow.

The proposal and accelerated rehearsal remain non-authorizing evidence.  This
module can create a narrow activation only after the programme status exposes
``g2_live_leg``.  It performs no serial, firmware, DAC, or control operation.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any

from .no_write_qualification_bundle import PROGRAMME_ID
from .bounded_tight_deadband_bundle import (
    HOST_TOOL_PATHS,
    _binding,
)
from .bounded_tight_deadband_proposal import validate_frozen_proposal
from .bounded_tight_deadband_leg import (
    LOWER,
    RANGE_LOWER,
    RANGE_UPPER,
    RANGE_UPPER_COMPLETION,
    UPPER,
    leg_for,
    leg_for_manifest,
    leg_for_proposal,
)
from .bounded_tight_deadband_outcome_contract import (
    CONTRACT_ID,
    MAXIMUM_CODE,
    MINIMUM_CODE,
    QUALIFICATION_DEADLINE_S,
    canonical_sha256,
)
from .bounded_tight_deadband_prewrite_contract import (
    FRESH_HOST_ATTACH_MAXIMUM_UPTIME_S,
    RAW_PPS_QUALIFICATION_DEADLINE_S,
    RUNTIME_CONTRACT_ID,
    TELEMETRY_BASELINE_STABLE_OBSERVATIONS,
)
from .programme_status import ProgrammeExecutionBlocked, require_programme_operation_allowed
from .run_paths import default_csv_files


TOOL_ID = "cx319_g2_live_activation_v1"
ACTIVATION_ID = "cx319_g2_leg_a_live_activation_v1"
LIVE_STAGE = "CX319_G2_LEG_A_FREQUENCY_ONLY_LIVE"
RUN_MANIFEST_SCHEMA_VERSION = 1
RUN_ACTIVATION_PATH = LOWER.activation_filename
RUN_PROPOSAL_PATH = LOWER.proposal_filename
LIVE_SEAL_PATH = LOWER.live_seal_filename
OPERATIONAL_REHEARSAL_TOOL = LOWER.rehearsal_tool
LEGACY_OPERATIONAL_REHEARSAL_TOOL = (
    "cx319_g2_accelerated_operational_rehearsal_v1"
)
OPERATIONAL_REHEARSAL_SEAL = LOWER.rehearsal_seal_type


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


def _read(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _atomic_new_json(path: Path, value: dict[str, Any]) -> None:
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
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=Path(__file__).resolve().parents[2],
        check=True,
        text=True,
        capture_output=True,
    )
    return not result.stdout


def _sequence_index_exact(value: dict[str, Any], selected) -> bool:  # type: ignore[no-untyped-def]
    sequence_index = value.get("sequence_index")
    if selected.programme_id == PROGRAMME_ID:
        return sequence_index is None
    if selected.leg == "C":
        return sequence_index == 4
    return sequence_index in ({1, 3} if selected.leg == "L" else {2})


def validate_operational_rehearsal(path: Path, proposal: dict[str, Any]) -> dict[str, Any]:
    selected = leg_for_proposal(proposal)
    path = path.resolve()
    result = _read(path, f"{selected.gate} operational rehearsal result")
    seal_path = Path(str(result.get("seal", ""))).resolve()
    seal = _read(seal_path, f"{selected.gate} operational rehearsal seal")
    unsigned_seal = {key: value for key, value in seal.items() if key != "seal_sha256"}
    if (
        result.get("schema_version") != 1
        or result.get("tool")
        not in {selected.rehearsal_tool, LEGACY_OPERATIONAL_REHEARSAL_TOOL}
        or result.get("status") != "passed"
        or result.get("proposal_bundle_sha256") != proposal["bundle_sha256"]
        or result.get("sequence_index") != proposal.get("sequence_index")
        or any(result.get("hardware_operations", {}).get(key) != 0 for key in (
            "serial_opens",
            "firmware_flashes",
            "dac_writes",
            "control_arms",
        ))
        or seal.get("seal_type") != selected.rehearsal_seal_type
        or seal.get("status") != "passed"
        or seal.get("proposal_bundle_sha256") != proposal["bundle_sha256"]
        or seal.get("sequence_index") != proposal.get("sequence_index")
        or seal.get("seal_sha256") != canonical_sha256(unsigned_seal)
    ):
        raise ValueError(f"{selected.gate} operational rehearsal is not an exact no-I/O pass")
    analysis_path = Path(str(result.get("analysis", ""))).resolve()
    if (
        not analysis_path.is_file()
        or seal.get("analysis_file_sha256") != _sha256_file(analysis_path)
    ):
        raise ValueError(f"{selected.gate} operational rehearsal analysis binding differs")
    return {
        "path": str(path),
        "sha256": _sha256_file(path),
        "artifact_content_sha256": result["artifact_content_sha256"],
        "seal_path": str(seal_path),
        "seal_sha256": seal["seal_sha256"],
        "seal_file_sha256": _sha256_file(seal_path),
    }


def _validate_current_operational_inputs(proposal: dict[str, Any]) -> None:
    host_tool_paths = HOST_TOOL_PATHS
    if proposal.get("programme_id") != PROGRAMME_ID:
        from .conditional_part_b_bundle import HOST_TOOL_PATHS as conditional_paths

        host_tool_paths = conditional_paths
    if proposal.get("host_tools") != {
        name: _binding(path) for name, path in host_tool_paths.items()
    }:
        raise ValueError("CX319 proposal host-tool bindings differ from current bytes")
    for section in ("firmware", "policy"):
        value = proposal.get(section, {})
        if not isinstance(value, dict):
            raise ValueError(f"G2 proposal {section} binding is malformed")
    if not _git_clean():
        raise ValueError("CX319 live activation requires a clean repository")


def create_activation(
    *,
    proposal_path: Path,
    operational_rehearsal_path: Path,
    serial_device: str,
    operator_instruction_ref: str,
    output_path: Path,
    leg_name: str = "A",
) -> dict[str, Any]:
    requested = {
        "A": LOWER,
        "B": UPPER,
        "L": RANGE_LOWER,
        "U": RANGE_UPPER,
        "C": RANGE_UPPER_COMPLETION,
    }.get(leg_name)
    if requested is None:
        raise ValueError(f"unsupported CX319 activation leg: {leg_name!r}")
    if requested.programme_id == PROGRAMME_ID:
        require_programme_operation_allowed(PROGRAMME_ID, requested.operation)
    if not serial_device.startswith("/dev/"):
        raise ValueError(f"{requested.gate} activation requires an explicit /dev serial path")
    if not operator_instruction_ref.strip():
        raise ValueError(f"{requested.gate} activation requires an operator-instruction reference")
    proposal_path = proposal_path.resolve()
    proposal = validate_frozen_proposal(proposal_path)
    selected = leg_for_proposal(proposal)
    if selected != requested:
        raise ValueError("requested activation leg differs from the proposal")
    _validate_current_operational_inputs(proposal)
    rehearsal = validate_operational_rehearsal(
        operational_rehearsal_path, proposal
    )
    unsigned: dict[str, Any] = {
        "schema_version": 1,
        "tool": selected.activation_tool,
        "activation_id": selected.activation_id,
        "created_utc": _utc_now(),
        "programme_id": selected.programme_id,
        "operation": selected.operation,
        "gate": selected.gate,
        "leg": selected.leg,
        "sequence_index": proposal.get("sequence_index"),
        "status": "effective_exact_leg_authority",
        "operator_instruction_ref": operator_instruction_ref.strip(),
        "proposal": {
            "path": str(proposal_path),
            "sha256": _sha256_file(proposal_path),
            "bundle_sha256": proposal["bundle_sha256"],
        },
        "operational_rehearsal": rehearsal,
        "device": {
            "path": serial_device,
            "baud": 115200,
            "expected_board_serial": "503533748A919118",
        },
        "authority": {
            "effective": True,
            "physical_execution": True,
            "firmware_flash": selected.firmware_flash,
            "fresh_host_attach_maximum_uptime_s": (
                FRESH_HOST_ATTACH_MAXIMUM_UPTIME_S
            ),
            "gnss_pps_qualification_deadline_s": (
                RAW_PPS_QUALIFICATION_DEADLINE_S
            ),
            "ordinary_telemetry_attach_baseline_stable_observations": (
                TELEMETRY_BASELINE_STABLE_OBSERVATIONS
            ),
            "post_attach_ordinary_telemetry_increment_allowed": False,
            "evidence_capture_preview_partition_and_control_gates_absolute": True,
            "serial_open": True,
            "setup_stimulus": True,
            "setup_code": selected.setup_code,
            "setup_write_limit": 1,
            "control_arm": True,
            "automatic_correction": True,
            "automatic_correction_limit": selected.correction_limit,
            "dac_value_write": True,
            "maximum_automatic_step_codes": selected.maximum_step_codes,
            "maximum_cumulative_codes": selected.cumulative_limit_codes,
            "minimum_code": MINIMUM_CODE,
            "maximum_code": MAXIMUM_CODE,
            "phase_or_hybrid_actionable": False,
            "automatic_retry": False,
            "automatic_restore": False,
        },
        "stop_conditions": [
            "prewrite runtime contract mismatch",
            "wrong setup acknowledgement or DAC epoch",
            "transaction, range, step, cadence or budget fault",
            "wrong-sign or unhealthy response",
            "preview authority contamination",
            "serial owner loss, reconnect, parser error or malformed record",
            "qualification deadline or finite qualified endpoint",
        ],
    }
    value = {**unsigned, "activation_sha256": canonical_sha256(unsigned)}
    _atomic_new_json(output_path.resolve(), value)
    return value


def validate_frozen_activation(
    path: Path, *, proposal_path: Path | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    path = path.resolve()
    value = _read(path, "CX319 live activation")
    selected = leg_for(value.get("gate"), value.get("leg"))
    unsigned = {key: item for key, item in value.items() if key != "activation_sha256"}
    authority = value.get("authority", {})
    if (
        value.get("schema_version") != 1
        or value.get("tool") != selected.activation_tool
        or value.get("activation_id") != selected.activation_id
        or value.get("programme_id") != selected.programme_id
        or value.get("operation") != selected.operation
        or not _sequence_index_exact(value, selected)
        or value.get("status") != "effective_exact_leg_authority"
        or value.get("activation_sha256") != canonical_sha256(unsigned)
        or not isinstance(authority, dict)
        or authority.get("effective") is not True
        or authority.get("firmware_flash") is not selected.firmware_flash
        or authority.get("fresh_host_attach_maximum_uptime_s")
        != FRESH_HOST_ATTACH_MAXIMUM_UPTIME_S
        or authority.get("gnss_pps_qualification_deadline_s")
        != RAW_PPS_QUALIFICATION_DEADLINE_S
        or authority.get(
            "ordinary_telemetry_attach_baseline_stable_observations"
        )
        != TELEMETRY_BASELINE_STABLE_OBSERVATIONS
        or authority.get("post_attach_ordinary_telemetry_increment_allowed")
        is not False
        or authority.get(
            "evidence_capture_preview_partition_and_control_gates_absolute"
        )
        is not True
        or authority.get("setup_code") != selected.setup_code
        or authority.get("setup_write_limit") != 1
        or authority.get("automatic_correction_limit") != selected.correction_limit
        or authority.get("maximum_automatic_step_codes") != selected.maximum_step_codes
        or authority.get("maximum_cumulative_codes") != selected.cumulative_limit_codes
        or authority.get("minimum_code") != MINIMUM_CODE
        or authority.get("maximum_code") != MAXIMUM_CODE
        or authority.get("phase_or_hybrid_actionable") is not False
        or authority.get("automatic_retry") is not False
        or authority.get("automatic_restore") is not False
    ):
        raise ValueError(f"{selected.gate} live activation identity, digest, or authority differs")
    proposal_binding = value.get("proposal", {})
    bound_proposal_path = Path(str(proposal_binding.get("path", ""))).resolve()
    proposal_path = (
        proposal_path.resolve() if proposal_path is not None else bound_proposal_path
    )
    proposal = validate_frozen_proposal(proposal_path)
    if (
        proposal_binding.get("sha256") != _sha256_file(proposal_path)
        or proposal_binding.get("bundle_sha256") != proposal["bundle_sha256"]
        or value.get("sequence_index") != proposal.get("sequence_index")
    ):
        raise ValueError("CX319 activation proposal binding differs")
    return value, proposal


def validate_activation(
    path: Path, *, proposal_path: Path | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    value, proposal = validate_frozen_activation(
        path, proposal_path=proposal_path
    )
    selected = leg_for_proposal(proposal)
    if selected.programme_id == PROGRAMME_ID:
        require_programme_operation_allowed(PROGRAMME_ID, selected.operation)
    _validate_current_operational_inputs(proposal)
    rehearsal = validate_operational_rehearsal(
        Path(value["operational_rehearsal"]["path"]), proposal
    )
    if value.get("operational_rehearsal") != rehearsal:
        raise ValueError("CX319 activation rehearsal binding differs")
    return value, proposal


def _required_files() -> list[dict[str, Any]]:
    required = {
        "pps_snapshots_v1",
        "dac_steps_v1",
        "environment_v1",
        "estimates_v2",
        "control_previews_v1",
        "active_transactions_v1",
        "relative_phase_observations_v1",
        "phase_estimator_outputs_v1",
        "hybrid_preview_decisions_v1",
        "tight_deadband_decisions_v1",
    }
    files = default_csv_files()
    for entry in files:
        if entry["contract"] in required:
            entry.pop("optional", None)
    return files


def create_run_manifest(
    *,
    activation_path: Path,
    proposal_path: Path,
    run_dir: Path,
    output_path: Path,
    serial_device: str | None = None,
) -> dict[str, Any]:
    activation, proposal = validate_activation(
        activation_path, proposal_path=proposal_path
    )
    selected = leg_for_proposal(proposal)
    run_dir = run_dir.resolve()
    files = _required_files()
    authority = activation["authority"]
    actual_serial_device = serial_device or activation["device"]["path"]
    if not isinstance(actual_serial_device, str) or not actual_serial_device.startswith("/dev/"):
        raise ValueError("CX319 live manifest requires an explicit serial device")
    envelope = proposal["intended_live_envelope"]
    manifest: dict[str, Any] = {
        "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        "compatibility_floor": "CX319_EVIDENCE_EPOCH_1",
        "template": False,
        "run_id": run_dir.name,
        "created_utc": _utc_now(),
        "started_at_utc": _utc_now(),
        "stage": selected.stage,
        "board": "arduino_nano_rp2040_connect",
        "capture_mode": "pio_wait_cumulative_snapshot_with_independent_gpio_ref",
        "control_mode": selected.control_mode,
        "closed_loop_control": True,
        "actionable": True,
        "actuation_authorized": True,
        "qualification_evidence": True,
        "programme_id": selected.programme_id,
        "sequence_index": proposal.get("sequence_index"),
        "sequence_count": proposal.get("sequence_count"),
        "firmware": proposal["firmware"],
        "policy": proposal["policy"],
        "observational_hybrid_preview": proposal.get("observational_hybrid_preview"),
        selected.prerequisite_key: proposal[selected.prerequisite_key],
        "predecessor_leg": proposal.get("predecessor_leg"),
        "proposal": {
            "path": str(proposal_path.resolve()),
            "sha256": activation["proposal"]["sha256"],
            "bundle_sha256": proposal["bundle_sha256"],
        },
        "activation": {
            "path": str(activation_path.resolve()),
            "sha256": _sha256_file(activation_path.resolve()),
            "activation_sha256": activation["activation_sha256"],
        },
        "host": {
            "capture_tool": "host.otis_tools.capture_device",
            "supervisor_tool": "host.otis_tools.bounded_tight_deadband_supervisor",
            "runner_tool": "host.otis_tools.bounded_tight_deadband_run",
            "analyzer_tool": "host.otis_tools.bounded_tight_deadband_live_analyze",
            "serial_device": actual_serial_device,
            "activation_serial_device": activation["device"]["path"],
            "baud": 115200,
            "sole_serial_owner": True,
            "independent_abort_fifo_required": True,
            "tool_bindings": proposal["host_tools"],
        },
        "cx319": {
            "gate": selected.gate,
            "leg": selected.leg,
            "sequence_index": proposal.get("sequence_index"),
            "mode": "frequency_only_live",
            "profile_id": proposal["leg_spec"]["profile_id"],
            "run_binding_tag": proposal["leg_spec"]["run_binding_tag"],
            "run_identity": proposal["leg_spec"]["run_identity"],
            "runtime_contract_id": RUNTIME_CONTRACT_ID,
            "outcome_contract_id": selected.outcome_contract_id,
            "planned_live_stimulus": {
                "code": selected.setup_code,
                "code_hex": selected.setup_code_hex,
                "maximum_writes": 1,
                "authorized": True,
            },
            "automatic_frequency_control": {
                "authorized": True,
                "required_direction": selected.required_direction,
                "maximum_corrections": selected.correction_limit,
                "maximum_step_codes": selected.maximum_step_codes,
                "maximum_cumulative_movement_codes": selected.cumulative_limit_codes,
                "minimum_applied_correction_cadence_s": selected.minimum_cadence_s,
                "minimum_code": MINIMUM_CODE,
                "maximum_code": MAXIMUM_CODE,
                "settling_exclusion_s": envelope["settling_exclusion_s"],
                "fresh_support_after_settling_s": envelope["fresh_support_s"],
                "one_request_outstanding": True,
                "automatic_retry": False,
                "automatic_restore": False,
            },
            "qualification": {
                "deadline_s": QUALIFICATION_DEADLINE_S,
                "maximum_qualified_duration_s": selected.maximum_qualified_duration_s,
                "no_extension_after_finite_endpoint": True,
            },
            "phase_and_hybrid": {
                "actionable": False,
                "actuation_authorized": False,
                "authorization_consumed": False,
                "frequency_controller_input": False,
            },
            "authority": authority,
        },
        "domains": [
            {"name": "rp2040_timer0", "nominal_hz": 16_000_000},
            {"name": "h1_cx317_ocxo_10mhz", "nominal_hz": 10_000_000},
        ],
        "channels": [
            {
                "channel_id": 1,
                "role": "authoritative_pps_reference",
                "record_family": "raw_events_v1",
            },
            {
                "channel_id": 2,
                "role": "pps_gated_oscillator_count",
                "record_family": "count_observations_v1",
            },
        ],
        "contracts": {
            entry["contract"]: 2 if entry["contract"] == "estimates_v2" else 1
            for entry in files
        },
        "files": files,
        "expected_artifacts": [
            *[entry["path"] for entry in files if not entry.get("optional")],
            "raw/serial.log",
            "reports/capture_device_state.json",
            "reports/cx317_active_status_live_state_v1.json",
            "reports/capture_segment_closure_v1.json",
            "reports/cx317_active_supervisor_state.json",
            "reports/cx317_active_supervisor_events.jsonl",
            str(selected.activation_filename),
            str(selected.proposal_filename),
            *(
                [str(selected.flash_record_filename)]
                if selected.flash_record_filename is not None
                else []
            ),
        ],
        "evidence_artifacts": [
            "reports/capture_device_state.json",
            "reports/cx317_active_status_live_state_v1.json",
            "reports/capture_segment_closure_v1.json",
            "reports/cx317_active_supervisor_state.json",
            "reports/cx317_active_supervisor_events.jsonl",
            f"reports/{selected.prefix}_capture_launcher.log",
            f"reports/{selected.prefix}_supervisor.log",
            str(selected.activation_filename),
            str(selected.proposal_filename),
            *(
                [str(selected.flash_record_filename)]
                if selected.flash_record_filename is not None
                else []
            ),
            "COMPLETE",
        ],
        "known_limitations": [
            f"{selected.gate} grants frequency-only authority for one finite "
            f"{'lower' if selected.required_sign > 0 else 'upper'}-side leg.",
            "Phase and hybrid preview remain zero-authority.",
            "The result does not establish traceable absolute frequency, UTC, calibrated phase, or holdover.",
        ],
    }
    _atomic_new_json(output_path.resolve(), manifest)
    return manifest


def _validate_run_manifest(
    path: Path, *, require_current_authority: bool
) -> dict[str, Any]:
    path = path.resolve()
    manifest = _read(path, "CX319 live run manifest")
    selected = leg_for_manifest(manifest)
    if (
        manifest.get("schema_version") != RUN_MANIFEST_SCHEMA_VERSION
        or manifest.get("stage") != selected.stage
        or manifest.get("closed_loop_control") is not True
        or manifest.get("actionable") is not True
        or manifest.get("actuation_authorized") is not True
        or manifest.get("qualification_evidence") is not True
        or manifest.get("programme_id") != selected.programme_id
        or not _sequence_index_exact(manifest, selected)
    ):
        raise ValueError(f"{selected.gate} live manifest identity or authority differs")
    activation_binding = manifest.get("activation", {})
    activation_path = Path(str(activation_binding.get("path", ""))).resolve()
    proposal_path = Path(str(manifest.get("proposal", {}).get("path", "")))
    validator = validate_activation if require_current_authority else validate_frozen_activation
    activation, proposal = validator(
        activation_path, proposal_path=proposal_path
    )
    if (
        activation_binding.get("sha256") != _sha256_file(activation_path)
        or activation_binding.get("activation_sha256")
        != activation["activation_sha256"]
        or manifest.get("firmware") != proposal["firmware"]
        or manifest.get("policy") != proposal["policy"]
        or manifest.get("observational_hybrid_preview")
        != proposal.get("observational_hybrid_preview")
        or manifest.get(selected.prerequisite_key)
        != proposal[selected.prerequisite_key]
        or manifest.get("predecessor_leg") != proposal.get("predecessor_leg")
        or manifest.get("proposal", {}).get("bundle_sha256")
        != proposal["bundle_sha256"]
        or manifest.get("sequence_index") != proposal.get("sequence_index")
        or manifest.get("sequence_count") != proposal.get("sequence_count")
        or manifest.get("host", {}).get("tool_bindings")
        != proposal["host_tools"]
        or manifest.get("host", {}).get(
            "activation_serial_device",
            manifest.get("host", {}).get("serial_device"),
        )
        != activation["device"]["path"]
        or not str(manifest.get("host", {}).get("serial_device", "")).startswith("/dev/")
        or (
            not selected.firmware_flash
            and manifest.get("host", {}).get("serial_device")
            != activation["device"]["path"]
        )
        or manifest.get("cx319", {}).get("authority") != activation["authority"]
    ):
        raise ValueError("G2 live manifest differs from activation or proposal")
    exact = manifest.get("cx319", {})
    if (
        exact.get("gate") != selected.gate
        or exact.get("leg") != selected.leg
        or exact.get("sequence_index") != proposal.get("sequence_index")
        or exact.get("runtime_contract_id") != RUNTIME_CONTRACT_ID
        or exact.get("outcome_contract_id") != selected.outcome_contract_id
        or exact.get("planned_live_stimulus", {}).get("code") != selected.setup_code
        or exact.get("automatic_frequency_control", {}).get("required_direction")
        != selected.required_direction
        or exact.get("automatic_frequency_control", {}).get("maximum_corrections")
        != selected.correction_limit
        or exact.get("automatic_frequency_control", {}).get("maximum_step_codes")
        != selected.maximum_step_codes
        or exact.get("automatic_frequency_control", {}).get(
            "maximum_cumulative_movement_codes"
        )
        != selected.cumulative_limit_codes
        or exact.get("qualification", {}).get("deadline_s")
        != QUALIFICATION_DEADLINE_S
        or exact.get("qualification", {}).get("maximum_qualified_duration_s")
        != selected.maximum_qualified_duration_s
        or any(exact.get("phase_and_hybrid", {}).get(key) is not False for key in (
            "actionable",
            "actuation_authorized",
            "authorization_consumed",
            "frequency_controller_input",
        ))
    ):
        raise ValueError(f"{selected.gate} live manifest bounds or zero-authority surface differs")
    return manifest


def validate_run_manifest(path: Path) -> dict[str, Any]:
    """Validate a manifest immediately before physical execution."""

    return _validate_run_manifest(path, require_current_authority=True)


def validate_frozen_run_manifest(path: Path) -> dict[str, Any]:
    """Validate retained run evidence without consulting current authority."""

    return _validate_run_manifest(path, require_current_authority=False)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    activate = commands.add_parser("activate")
    activate.add_argument("--proposal", type=Path, required=True)
    activate.add_argument("--operational-rehearsal", type=Path, required=True)
    activate.add_argument("--serial-device", required=True)
    activate.add_argument("--operator-instruction-ref", required=True)
    activate.add_argument("--leg", choices=("A", "B", "L", "U", "C"), default="A")
    activate.add_argument("--output", type=Path, required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("activation", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "activate":
            value = create_activation(
                proposal_path=args.proposal,
                operational_rehearsal_path=args.operational_rehearsal,
                serial_device=args.serial_device,
                operator_instruction_ref=args.operator_instruction_ref,
                output_path=args.output,
                leg_name=args.leg,
            )
        else:
            value, _ = validate_activation(args.activation)
    except (
        FileExistsError,
        FileNotFoundError,
        KeyError,
        OSError,
        ProgrammeExecutionBlocked,
        TypeError,
        ValueError,
        json.JSONDecodeError,
        subprocess.SubprocessError,
    ) as exc:
        parser.error(str(exc))
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
