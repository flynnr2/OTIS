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
import subprocess
import tempfile
from typing import Any

from .active_hybrid_bundle import REQUIRED_FALSE_AUTHORITY, validate_bundle
from .active_hybrid_proposal import validate_proposal
from .evidence_index import package_identity
from .run_paths import default_csv_files


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
    "setup_propagation",
    "progressive_checkpoint",
    "conditional_release",
    "response_classification",
    "phase_only_degradation",
    "shared_fail_static_fault",
    "transport_obstruction",
    "terminal_abort_delivery_before_capture_close",
    "logical_evidence_rotation",
    "analysis_seal_registration",
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


def _validate_frozen_inputs(
    *, bundle_path: Path, proposal_path: Path
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
        or bundle.get("programme_id") != PROGRAMME_ID
        or bundle.get("run_identity") != RUNTIME_RUN_IDENTITY
        or bundle.get("status") != "frozen_non_effective_physical_proposal_input"
        or proposal.get("programme_id") != PROGRAMME_ID
        or proposal.get("run_identity") != RUNTIME_RUN_IDENTITY
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


def validate_operational_rehearsal(
    path: Path,
    *,
    bundle: dict[str, Any],
    proposal: dict[str, Any],
    require_current_tools: bool = True,
) -> dict[str, Any]:
    path = path.resolve()
    report = _read_object(path, "CX320 live-topology rehearsal")
    claimed = report.get("rehearsal_sha256")
    unsigned = {
        key: item for key, item in report.items() if key != "rehearsal_sha256"
    }
    coverage = report.get("coverage")
    tool_bindings = report.get("tool_bindings")
    if (
        report.get("schema_version") != 1
        or report.get("report_type") != REHEARSAL_REPORT_TYPE
        or report.get("status") != "passed"
        or report.get("bundle_sha256") != bundle.get("bundle_sha256")
        or report.get("proposal_sha256") != proposal.get("proposal_sha256")
        or report.get("physical_actions_performed") != 0
        or report.get("qualification_evidence") is not False
        or claimed != _canonical_sha256(unsigned)
        or not isinstance(coverage, dict)
        or set(coverage) != set(REHEARSAL_COVERAGE)
        or any(coverage.get(name) is not True for name in REHEARSAL_COVERAGE)
        or tool_bindings != bundle.get("host_tools")
    ):
        raise ValueError("CX320 live-topology rehearsal receipt differs or is incomplete")
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
        "report_type": REHEARSAL_REPORT_TYPE,
        "rehearsal_sha256": claimed,
    }


def _authority() -> dict[str, Any]:
    return {
        "effective": True,
        "physical_execution": True,
        "firmware_flash_limit": 1,
        "reset_for_entry_or_bounded_recovery": True,
        "serial_open": True,
        "command_fifo": True,
        "setup_stimulus": True,
        "setup_code": SETUP_CODE,
        "setup_write_limit": 1,
        "control_arm": True,
        "live_acquisition_limit": 1,
        "maximum_total_automatic_applications": 4,
        "first_phase_material_applications_before_checkpoint": 1,
        "minimum_phase_material_applications_for_pass": 2,
        "maximum_combined_step_codes": 21,
        "maximum_cumulative_absolute_movement_codes": 84,
        "minimum_applied_cadence_s": 1800,
        "minimum_code": 0xA800,
        "maximum_code": 0xAB00,
        "qualified_duration_s": 43_200,
        "absolute_wall_clock_limit_s": 57_600,
        "maximum_outstanding_requests": 1,
        "automatic_retry": False,
        "automatic_restoration": False,
        "live_extension": False,
        "authority_consumed_by_first_physical_terminal": True,
    }


def _attempt_descriptor(
    *,
    ordinal: int,
    reason: str,
    predecessor_terminal_path: Path | None,
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
        if (
            not (run_dir / "COMPLETE").is_file()
            or seal.get("status") != "failed"
            or seal.get("primary_decision")
            != "measurement_authority_or_platform_fault"
            or seal.get("acquisition_gate", {}).get("passed") is not False
            or seal.get("offline_finalization_gate", {}).get(
                "replayable_without_physical_repeat"
            )
            is not False
        ):
            raise ValueError(
                "CX320 predecessor does not establish a failed physical gate "
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
) -> dict[str, Any]:
    if not serial_device.startswith("/dev/"):
        raise ValueError("CX320 activation requires an explicit /dev serial path")
    if not operator_instruction_ref.strip():
        raise ValueError("CX320 activation requires an operator-instruction reference")
    bundle = validate_bundle(bundle_path)
    proposal = validate_proposal(proposal_path)
    frozen_bundle, frozen_proposal = _validate_frozen_inputs(
        bundle_path=bundle_path, proposal_path=proposal_path
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
    )
    unsigned: dict[str, Any] = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "tool_binding": _binding(Path(__file__)),
        "activation_id": ACTIVATION_ID,
        "created_utc": _utc_now(),
        "programme_id": PROGRAMME_ID,
        "operation": OPERATION,
        "status": "effective_exact_bundle_authority",
        "operator_instruction_ref": operator_instruction_ref.strip(),
        "run_identity": RUNTIME_RUN_IDENTITY,
        "profile_identity": PROFILE_IDENTITY,
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
        ),
        "operational_rehearsal": rehearsal,
        "device": {
            "path": serial_device,
            "baud": EXPECTED_BAUD,
            "expected_board_serial": EXPECTED_BOARD_SERIAL,
        },
        "firmware": bundle["firmware"],
        "policy": bundle["policy"],
        "host_tools": bundle["host_tools"],
        "topology": {
            "serial_owner": "capture_device",
            "serial_owner_count": 1,
            "fifos": FIFO_PATHS,
        },
        "setup": {
            "code": SETUP_CODE,
            "code_hex": SETUP_CODE_HEX,
            "maximum_applications": 1,
            "same_code_reapplication_opens_new_epoch": True,
            "exact_consumer_epoch_propagation_required": True,
        },
        "authority": _authority(),
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
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    path = path.resolve()
    activation = _read_object(path, "CX320 live activation")
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
        bundle_path=bundle_path, proposal_path=proposal_path
    )
    host_tools = bundle.get("host_tools")
    if not isinstance(host_tools, dict):
        raise ValueError("CX320 activation host-tool binding is malformed")
    fifos = topology.get("fifos", {})
    if (
        activation.get("schema_version") != 1
        or activation.get("tool") != TOOL_ID
        or activation.get("activation_id") != ACTIVATION_ID
        or activation.get("programme_id") != PROGRAMME_ID
        or activation.get("operation") != OPERATION
        or activation.get("status") != "effective_exact_bundle_authority"
        or activation.get("run_identity") != RUNTIME_RUN_IDENTITY
        or activation.get("profile_identity") != PROFILE_IDENTITY
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
        or activation.get("device")
        != {
            "path": device.get("path"),
            "baud": EXPECTED_BAUD,
            "expected_board_serial": EXPECTED_BOARD_SERIAL,
        }
        or not str(device.get("path", "")).startswith("/dev/")
        or topology.get("serial_owner") != "capture_device"
        or topology.get("serial_owner_count") != 1
        or fifos != FIFO_PATHS
        or len(set(fifos.values())) != 3
        or activation.get("setup")
        != {
            "code": SETUP_CODE,
            "code_hex": SETUP_CODE_HEX,
            "maximum_applications": 1,
            "same_code_reapplication_opens_new_epoch": True,
            "exact_consumer_epoch_propagation_required": True,
        }
        or activation.get("authority") != _authority()
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
    )
    if rehearsal_binding != observed_rehearsal:
        raise ValueError("CX320 activation rehearsal binding differs")
    return activation, bundle, proposal


def validate_activation(
    path: Path,
    *,
    bundle_path: Path | None = None,
    proposal_path: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    activation, frozen_bundle, frozen_proposal = validate_frozen_activation(
        path, bundle_path=bundle_path, proposal_path=proposal_path
    )
    current_bundle = validate_bundle(
        (bundle_path or Path(activation["bundle"]["path"])).resolve()
    )
    current_proposal = validate_proposal(
        (proposal_path or Path(activation["proposal"]["path"])).resolve()
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
    )
    return activation, current_bundle, current_proposal


def _required_files() -> list[dict[str, Any]]:
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
    files: list[dict[str, Any]] = [dict(entry) for entry in default_csv_files()]
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
    activation, bundle, proposal = validate_activation(
        activation_path,
        bundle_path=bundle_path,
        proposal_path=proposal_path,
    )
    actual_device = serial_device or str(activation["device"]["path"])
    if not actual_device.startswith("/dev/"):
        raise ValueError("CX320 live manifest requires an explicit serial device")
    files = _required_files()
    authority = activation["authority"]
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "compatibility_floor": "CX320_EVIDENCE_EPOCH_1",
        "template": False,
        "run_id": run_dir.name,
        "created_utc": _utc_now(),
        "started_at_utc": _utc_now(),
        "stage": LIVE_STAGE,
        "programme_id": PROGRAMME_ID,
        "run_identity": RUNTIME_RUN_IDENTITY,
        "profile_identity": PROFILE_IDENTITY,
        "board": "arduino_nano_rp2040_connect",
        "capture_mode": "pio_wait_cumulative_snapshot_with_independent_gpio_ref",
        "control_mode": "bounded_active_hybrid_phase_frequency",
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
            "baud": EXPECTED_BAUD,
            "expected_board_serial": EXPECTED_BOARD_SERIAL,
            "sole_serial_owner": True,
            "serial_owner_count": 1,
            "fifos": FIFO_PATHS,
            "tool_bindings": bundle["host_tools"],
        },
        "cx320": {
            "mode": "active_hybrid_live",
            "profile_id": PROFILE_IDENTITY,
            "run_identity": RUNTIME_RUN_IDENTITY,
            "authority": authority,
            "setup": {
                "code": SETUP_CODE,
                "code_hex": SETUP_CODE_HEX,
                "maximum_applications": 1,
                "physical_applied_code_before_setup": "unknown",
                "same_code_reapplication_opens_new_epoch": True,
                "exact_consumer_epoch_propagation_required": True,
            },
            "automatic_control": {
                "authorized": True,
                "maximum_total_applications": 4,
                "maximum_step_codes": 21,
                "maximum_cumulative_movement_codes": 84,
                "minimum_applied_cadence_s": 1800,
                "minimum_code": 0xA800,
                "maximum_code": 0xAB00,
                "maximum_outstanding_requests": 1,
                "automatic_retry": False,
                "automatic_restore": False,
            },
            "progressive_authority": {
                "first_phase_material_applications_before_checkpoint": 1,
                "minimum_phase_material_applications_for_pass": 2,
                "first_response_acknowledgement_requires_durable_AHY_and_ACT": True,
                "first_response_acknowledgement_requires_exact_host_replay": True,
                "later_authority_requires_healthy_response_and_tight_reacquisition": True,
            },
            "qualification": {
                "qualified_duration_s": 43_200,
                "absolute_wall_clock_limit_s": 57_600,
                "qualified_origin": bundle["finite_limits"]["qualified_origin"],
                "wall_clock_origin": bundle["finite_limits"]["wall_clock_origin"],
                "no_extension": True,
            },
        },
        "domains": [
            {"name": "rp2040_timer0", "nominal_hz": 16_000_000},
            {"name": "h1_cx317_ocxo_10mhz", "nominal_hz": 10_000_000},
        ],
        "channels": [
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
                "pin": "D10",
                "role": "independent_external_event_not_control_authority",
                "record_family": "raw_events_v1",
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
            "reports/cx317_active_supervisor_state.json",
            "reports/cx317_active_supervisor_events.jsonl",
            "reports/capture_segment_closure_v1.json",
            str(RUN_ACTIVATION_PATH),
            str(RUN_PROPOSAL_PATH),
            str(RUN_BUNDLE_PATH),
            "COMPLETE",
        ],
        "evidence_artifacts": [
            "reports/capture_device_state.json",
            "reports/cx317_active_supervisor_state.json",
            "reports/cx317_active_supervisor_events.jsonl",
            "reports/capture_segment_closure_v1.json",
            "reports/cx320_active_hybrid_capture.log",
            "reports/cx320_active_hybrid_supervisor.log",
            str(RUN_ACTIVATION_PATH),
            str(RUN_PROPOSAL_PATH),
            str(RUN_BUNDLE_PATH),
            "COMPLETE",
        ],
        "known_limitations": [
            "D14 is the sole PPS/reference input and D8 the sole oscillator/count input.",
            "D10 is an independent event input and never enters timing or control authority.",
            (
                "The result does not establish UTC, absolute phase, calibrated "
                "delay, traceable frequency accuracy, or holdover."
            ),
        ],
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
    )
    host = manifest.get("host", {})
    cx320 = manifest.get("cx320", {})
    if not isinstance(host, dict) or not isinstance(cx320, dict):
        raise ValueError("CX320 live run manifest host or programme section is malformed")
    control = cx320.get("automatic_control", {})
    progressive = cx320.get("progressive_authority", {})
    qualification = cx320.get("qualification", {})
    if (
        path != (run_dir / RUN_MANIFEST_PATH)
        or manifest.get("schema_version") != 1
        or manifest.get("compatibility_floor") != "CX320_EVIDENCE_EPOCH_1"
        or manifest.get("template") is not False
        or manifest.get("stage") != LIVE_STAGE
        or manifest.get("programme_id") != PROGRAMME_ID
        or manifest.get("run_identity") != RUNTIME_RUN_IDENTITY
        or manifest.get("profile_identity") != PROFILE_IDENTITY
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
        or not str(host.get("serial_device", "")).startswith("/dev/")
        or host.get("baud") != EXPECTED_BAUD
        or host.get("expected_board_serial") != EXPECTED_BOARD_SERIAL
        or host.get("sole_serial_owner") is not True
        or host.get("serial_owner_count") != 1
        or host.get("fifos") != FIFO_PATHS
        or len(set(host.get("fifos", {}).values())) != 3
        or cx320.get("authority") != activation["authority"]
        or cx320.get("run_identity") != RUNTIME_RUN_IDENTITY
        or cx320.get("setup", {}).get("code") != SETUP_CODE
        or cx320.get("setup", {}).get("maximum_applications") != 1
        or control
        != {
            "authorized": True,
            "maximum_total_applications": 4,
            "maximum_step_codes": 21,
            "maximum_cumulative_movement_codes": 84,
            "minimum_applied_cadence_s": 1800,
            "minimum_code": 0xA800,
            "maximum_code": 0xAB00,
            "maximum_outstanding_requests": 1,
            "automatic_retry": False,
            "automatic_restore": False,
        }
        or progressive
        != {
            "first_phase_material_applications_before_checkpoint": 1,
            "minimum_phase_material_applications_for_pass": 2,
            "first_response_acknowledgement_requires_durable_AHY_and_ACT": True,
            "first_response_acknowledgement_requires_exact_host_replay": True,
            "later_authority_requires_healthy_response_and_tight_reacquisition": True,
        }
        or qualification.get("qualified_duration_s") != 43_200
        or qualification.get("absolute_wall_clock_limit_s") != 57_600
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
    if not required_contracts <= set(manifest.get("contracts", {})):
        raise ValueError("CX320 live manifest lacks decision-bearing contracts")
    return manifest


def validate_run_manifest(path: Path) -> dict[str, Any]:
    manifest = validate_frozen_run_manifest(path)
    validate_activation(
        Path(manifest["activation"]["path"]),
        bundle_path=Path(manifest["bundle"]["path"]),
        proposal_path=Path(manifest["proposal"]["path"]),
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    activate = commands.add_parser("activate")
    activate.add_argument("--bundle", type=Path, required=True)
    activate.add_argument("--proposal", type=Path, required=True)
    activate.add_argument("--operational-rehearsal", type=Path, required=True)
    activate.add_argument("--serial-device", required=True)
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
            result: Any = create_activation(
                bundle_path=args.bundle,
                proposal_path=args.proposal,
                operational_rehearsal_path=args.operational_rehearsal,
                serial_device=args.serial_device,
                operator_instruction_ref=args.operator_instruction_ref,
                output_path=args.output,
                attempt_ordinal=args.attempt_ordinal,
                attempt_reason=args.attempt_reason,
                predecessor_terminal_path=args.predecessor_terminal,
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
