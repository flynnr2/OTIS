"""Activate and manifest the exact CX319 G2 Leg A physical workflow.

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

from .cx319_g1_bundle import PROGRAMME_ID
from .cx319_g2_bundle import (
    HOST_TOOL_PATHS,
    _binding,
    validate_frozen_proposal,
)
from .cx319_g2_contract import (
    CONTRACT_ID,
    MAXIMUM_CODE,
    MAXIMUM_CORRECTIONS,
    MAXIMUM_CUMULATIVE_CODES,
    MAXIMUM_QUALIFIED_DURATION_S,
    MAXIMUM_STEP_CODES,
    MINIMUM_CADENCE_S,
    MINIMUM_CODE,
    QUALIFICATION_DEADLINE_S,
    SETUP_CODE,
    canonical_sha256,
)
from .cx319_g2_runtime_contract import (
    FRESH_RESTART_MAXIMUM_UPTIME_S,
    RUNTIME_CONTRACT_ID,
    TELEMETRY_BASELINE_STABLE_OBSERVATIONS,
)
from .programme_status import (
    CX319_G2_LIVE_LEG,
    ProgrammeExecutionBlocked,
    require_programme_operation_allowed,
)
from .run_paths import default_csv_files


TOOL_ID = "cx319_g2_live_activation_v1"
ACTIVATION_ID = "cx319_g2_leg_a_live_activation_v1"
LIVE_STAGE = "CX319_G2_LEG_A_FREQUENCY_ONLY_LIVE"
RUN_MANIFEST_SCHEMA_VERSION = 1
RUN_ACTIVATION_PATH = Path("cx319_g2_live_activation_v1.json")
RUN_PROPOSAL_PATH = Path("cx319_g2_leg_a_proposal_bundle_v1.json")
LIVE_SEAL_PATH = Path("reports/cx319_g2_live_leg_seal_v1.json")
OPERATIONAL_REHEARSAL_TOOL = "cx319_g2_accelerated_operational_rehearsal_v1"
OPERATIONAL_REHEARSAL_SEAL = (
    "cx319_g2_accelerated_operational_rehearsal_seal_v1"
)


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


def validate_operational_rehearsal(path: Path, proposal: dict[str, Any]) -> dict[str, Any]:
    path = path.resolve()
    result = _read(path, "G2 operational rehearsal result")
    seal_path = Path(str(result.get("seal", ""))).resolve()
    seal = _read(seal_path, "G2 operational rehearsal seal")
    unsigned_seal = {key: value for key, value in seal.items() if key != "seal_sha256"}
    if (
        result.get("schema_version") != 1
        or result.get("tool") != OPERATIONAL_REHEARSAL_TOOL
        or result.get("status") != "passed"
        or result.get("proposal_bundle_sha256") != proposal["bundle_sha256"]
        or any(result.get("hardware_operations", {}).get(key) != 0 for key in (
            "serial_opens",
            "firmware_flashes",
            "dac_writes",
            "control_arms",
        ))
        or seal.get("seal_type") != OPERATIONAL_REHEARSAL_SEAL
        or seal.get("status") != "passed"
        or seal.get("proposal_bundle_sha256") != proposal["bundle_sha256"]
        or seal.get("seal_sha256") != canonical_sha256(unsigned_seal)
    ):
        raise ValueError("G2 operational rehearsal is not an exact no-I/O pass")
    analysis_path = Path(str(result.get("analysis", ""))).resolve()
    if (
        not analysis_path.is_file()
        or seal.get("analysis_file_sha256") != _sha256_file(analysis_path)
    ):
        raise ValueError("G2 operational rehearsal analysis binding differs")
    return {
        "path": str(path),
        "sha256": _sha256_file(path),
        "artifact_content_sha256": result["artifact_content_sha256"],
        "seal_path": str(seal_path),
        "seal_sha256": seal["seal_sha256"],
        "seal_file_sha256": _sha256_file(seal_path),
    }


def _validate_current_operational_inputs(proposal: dict[str, Any]) -> None:
    if proposal.get("host_tools") != {
        name: _binding(path) for name, path in HOST_TOOL_PATHS.items()
    }:
        raise ValueError("G2 proposal host-tool bindings differ from current bytes")
    for section in ("firmware", "policy"):
        value = proposal.get(section, {})
        if not isinstance(value, dict):
            raise ValueError(f"G2 proposal {section} binding is malformed")
    if not _git_clean():
        raise ValueError("G2 live activation requires a clean repository")


def create_activation(
    *,
    proposal_path: Path,
    operational_rehearsal_path: Path,
    serial_device: str,
    operator_instruction_ref: str,
    output_path: Path,
) -> dict[str, Any]:
    require_programme_operation_allowed(PROGRAMME_ID, CX319_G2_LIVE_LEG)
    if not serial_device.startswith("/dev/"):
        raise ValueError("G2 activation requires an explicit /dev serial path")
    if not operator_instruction_ref.strip():
        raise ValueError("G2 activation requires an operator-instruction reference")
    proposal_path = proposal_path.resolve()
    proposal = validate_frozen_proposal(proposal_path)
    _validate_current_operational_inputs(proposal)
    rehearsal = validate_operational_rehearsal(
        operational_rehearsal_path, proposal
    )
    unsigned: dict[str, Any] = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "activation_id": ACTIVATION_ID,
        "created_utc": _utc_now(),
        "programme_id": PROGRAMME_ID,
        "operation": CX319_G2_LIVE_LEG,
        "gate": "G2",
        "leg": "A",
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
            "firmware_flash": False,
            "fresh_restart_maximum_prewrite_uptime_s": (
                FRESH_RESTART_MAXIMUM_UPTIME_S
            ),
            "ordinary_telemetry_attach_baseline_stable_observations": (
                TELEMETRY_BASELINE_STABLE_OBSERVATIONS
            ),
            "post_attach_ordinary_telemetry_increment_allowed": False,
            "evidence_capture_preview_partition_and_control_gates_absolute": True,
            "serial_open": True,
            "setup_stimulus": True,
            "setup_code": SETUP_CODE,
            "setup_write_limit": 1,
            "control_arm": True,
            "automatic_correction": True,
            "automatic_correction_limit": MAXIMUM_CORRECTIONS,
            "dac_value_write": True,
            "maximum_automatic_step_codes": MAXIMUM_STEP_CODES,
            "maximum_cumulative_codes": MAXIMUM_CUMULATIVE_CODES,
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
    value = _read(path, "G2 live activation")
    unsigned = {key: item for key, item in value.items() if key != "activation_sha256"}
    authority = value.get("authority", {})
    if (
        value.get("schema_version") != 1
        or value.get("tool") != TOOL_ID
        or value.get("activation_id") != ACTIVATION_ID
        or value.get("programme_id") != PROGRAMME_ID
        or value.get("operation") != CX319_G2_LIVE_LEG
        or value.get("gate") != "G2"
        or value.get("leg") != "A"
        or value.get("status") != "effective_exact_leg_authority"
        or value.get("activation_sha256") != canonical_sha256(unsigned)
        or not isinstance(authority, dict)
        or authority.get("effective") is not True
        or authority.get("firmware_flash") is not False
        or authority.get("fresh_restart_maximum_prewrite_uptime_s")
        != FRESH_RESTART_MAXIMUM_UPTIME_S
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
        or authority.get("setup_code") != SETUP_CODE
        or authority.get("setup_write_limit") != 1
        or authority.get("automatic_correction_limit") != MAXIMUM_CORRECTIONS
        or authority.get("maximum_automatic_step_codes") != MAXIMUM_STEP_CODES
        or authority.get("maximum_cumulative_codes") != MAXIMUM_CUMULATIVE_CODES
        or authority.get("minimum_code") != MINIMUM_CODE
        or authority.get("maximum_code") != MAXIMUM_CODE
        or authority.get("phase_or_hybrid_actionable") is not False
        or authority.get("automatic_retry") is not False
        or authority.get("automatic_restore") is not False
    ):
        raise ValueError("G2 live activation identity, digest, or authority differs")
    proposal_binding = value.get("proposal", {})
    bound_proposal_path = Path(str(proposal_binding.get("path", ""))).resolve()
    proposal_path = (
        proposal_path.resolve() if proposal_path is not None else bound_proposal_path
    )
    proposal = validate_frozen_proposal(proposal_path)
    if (
        proposal_binding.get("sha256") != _sha256_file(proposal_path)
        or proposal_binding.get("bundle_sha256") != proposal["bundle_sha256"]
    ):
        raise ValueError("G2 activation proposal binding differs")
    return value, proposal


def validate_activation(
    path: Path, *, proposal_path: Path | None = None
) -> tuple[dict[str, Any], dict[str, Any]]:
    require_programme_operation_allowed(PROGRAMME_ID, CX319_G2_LIVE_LEG)
    value, proposal = validate_frozen_activation(
        path, proposal_path=proposal_path
    )
    _validate_current_operational_inputs(proposal)
    rehearsal = validate_operational_rehearsal(
        Path(value["operational_rehearsal"]["path"]), proposal
    )
    if value.get("operational_rehearsal") != rehearsal:
        raise ValueError("G2 activation rehearsal binding differs")
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
) -> dict[str, Any]:
    activation, proposal = validate_activation(
        activation_path, proposal_path=proposal_path
    )
    run_dir = run_dir.resolve()
    files = _required_files()
    authority = activation["authority"]
    envelope = proposal["intended_live_envelope"]
    manifest: dict[str, Any] = {
        "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        "template": False,
        "run_id": run_dir.name,
        "created_utc": _utc_now(),
        "started_at_utc": _utc_now(),
        "stage": LIVE_STAGE,
        "h_phase": "H1",
        "board": "arduino_nano_rp2040_connect",
        "capture_mode": "pio_wait_cumulative_snapshot_with_independent_gpio_ref",
        "control_mode": "cx319_g2_leg_a_frequency_only_live",
        "closed_loop_control": True,
        "actionable": True,
        "actuation_authorized": True,
        "qualification_evidence": True,
        "firmware": proposal["firmware"],
        "policy": proposal["policy"],
        "g1_pass": proposal["g1_pass"],
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
            "supervisor_tool": "host.otis_tools.cx319_g2_supervisor",
            "runner_tool": "host.otis_tools.cx319_g2_run",
            "analyzer_tool": "host.otis_tools.cx319_g2_live_analyze",
            "serial_device": activation["device"]["path"],
            "baud": 115200,
            "sole_serial_owner": True,
            "independent_abort_fifo_required": True,
            "tool_bindings": proposal["host_tools"],
        },
        "cx319": {
            "gate": "G2",
            "leg": "A",
            "mode": "frequency_only_live",
            "profile_id": proposal["leg_spec"]["profile_id"],
            "run_binding_tag": proposal["leg_spec"]["run_binding_tag"],
            "run_identity": proposal["leg_spec"]["run_identity"],
            "runtime_contract_id": RUNTIME_CONTRACT_ID,
            "outcome_contract_id": CONTRACT_ID,
            "planned_live_stimulus": {
                "code": SETUP_CODE,
                "code_hex": "0xA808",
                "maximum_writes": 1,
                "authorized": True,
            },
            "automatic_frequency_control": {
                "authorized": True,
                "required_direction": "positive",
                "maximum_corrections": MAXIMUM_CORRECTIONS,
                "maximum_step_codes": MAXIMUM_STEP_CODES,
                "maximum_cumulative_movement_codes": MAXIMUM_CUMULATIVE_CODES,
                "minimum_applied_correction_cadence_s": MINIMUM_CADENCE_S,
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
                "maximum_qualified_duration_s": MAXIMUM_QUALIFIED_DURATION_S,
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
            "reports/capture_segment_closure_v1.json",
            "reports/cx317_active_supervisor_state.json",
            "reports/cx317_active_supervisor_events.jsonl",
            str(RUN_ACTIVATION_PATH),
            str(RUN_PROPOSAL_PATH),
        ],
        "evidence_artifacts": [
            "reports/capture_device_state.json",
            "reports/capture_segment_closure_v1.json",
            "reports/cx317_active_supervisor_state.json",
            "reports/cx317_active_supervisor_events.jsonl",
            "reports/cx319_g2_capture_launcher.log",
            "reports/cx319_g2_supervisor.log",
            str(RUN_ACTIVATION_PATH),
            str(RUN_PROPOSAL_PATH),
            "COMPLETE",
        ],
        "known_limitations": [
            "G2 grants frequency-only authority for one finite lower-side leg.",
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
    manifest = _read(path, "G2 live run manifest")
    if (
        manifest.get("schema_version") != RUN_MANIFEST_SCHEMA_VERSION
        or manifest.get("stage") != LIVE_STAGE
        or manifest.get("closed_loop_control") is not True
        or manifest.get("actionable") is not True
        or manifest.get("actuation_authorized") is not True
        or manifest.get("qualification_evidence") is not True
    ):
        raise ValueError("G2 live manifest identity or authority differs")
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
        or manifest.get("g1_pass") != proposal["g1_pass"]
        or manifest.get("proposal", {}).get("bundle_sha256")
        != proposal["bundle_sha256"]
        or manifest.get("host", {}).get("tool_bindings")
        != proposal["host_tools"]
        or manifest.get("host", {}).get("serial_device")
        != activation["device"]["path"]
        or manifest.get("cx319", {}).get("authority") != activation["authority"]
    ):
        raise ValueError("G2 live manifest differs from activation or proposal")
    exact = manifest.get("cx319", {})
    if (
        exact.get("gate") != "G2"
        or exact.get("leg") != "A"
        or exact.get("runtime_contract_id") != RUNTIME_CONTRACT_ID
        or exact.get("outcome_contract_id") != CONTRACT_ID
        or exact.get("planned_live_stimulus", {}).get("code") != SETUP_CODE
        or exact.get("automatic_frequency_control", {}).get("required_direction")
        != "positive"
        or exact.get("automatic_frequency_control", {}).get("maximum_corrections")
        != MAXIMUM_CORRECTIONS
        or exact.get("automatic_frequency_control", {}).get("maximum_step_codes")
        != MAXIMUM_STEP_CODES
        or exact.get("automatic_frequency_control", {}).get(
            "maximum_cumulative_movement_codes"
        )
        != MAXIMUM_CUMULATIVE_CODES
        or exact.get("qualification", {}).get("deadline_s")
        != QUALIFICATION_DEADLINE_S
        or exact.get("qualification", {}).get("maximum_qualified_duration_s")
        != MAXIMUM_QUALIFIED_DURATION_S
        or any(exact.get("phase_and_hybrid", {}).get(key) is not False for key in (
            "actionable",
            "actuation_authorized",
            "authorization_consumed",
            "frequency_controller_input",
        ))
    ):
        raise ValueError("G2 live manifest bounds or zero-authority surface differs")
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
