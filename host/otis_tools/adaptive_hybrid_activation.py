"""Create and validate the sole adaptive-hybrid activation and run manifest."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any

from .adaptive_hybrid_bundle import FRESH_SERIAL_AUTO_DETECT, validate_bundle
from .adaptive_hybrid_contract import (
    ADAPTIVE_HYBRID_PROGRAMME,
    AdaptiveHybridProgramme,
    integrated_setup_provenance_contract,
    progressive_checkpoint_contract,
    programme_from_mapping,
)
from .adaptive_hybrid_proposal import validate_proposal
from .authoritative_inputs import (
    ROOT_PROFILE,
    authoritative_binding,
    authoritative_document,
    validate_authoritative_inputs,
)
from .run_paths import adaptive_hybrid_csv_files
from .time_domains import canonical_domain_declaration, validate_domain_declarations


TOOL_ID = "adaptive_hybrid_activation_v1"
ACTIVATION_ID = ADAPTIVE_HYBRID_PROGRAMME.activation_id
PROGRAMME_ID = ADAPTIVE_HYBRID_PROGRAMME.programme_id
OPERATION = ADAPTIVE_HYBRID_PROGRAMME.operation
LIVE_STAGE = ADAPTIVE_HYBRID_PROGRAMME.live_stage
RUNTIME_RUN_IDENTITY = ADAPTIVE_HYBRID_PROGRAMME.runtime_run_identity
EXPECTED_BOARD_SERIAL = "503533748A919118"
EXPECTED_BAUD = 115200
RUN_ACTIVATION_PATH = ADAPTIVE_HYBRID_PROGRAMME.run_activation_path
RUN_PROPOSAL_PATH = ADAPTIVE_HYBRID_PROGRAMME.run_proposal_path
RUN_BUNDLE_PATH = ADAPTIVE_HYBRID_PROGRAMME.run_bundle_path
RUN_MANIFEST_PATH = Path("run_manifest.json")
FIFO_PATHS = {
    "normal_command": "control/normal_commands.fifo",
    "emergency_abort": "control/emergency_abort.fifo",
    "host_abort": "control/host_abort.fifo",
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _canonical_sha256(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _explicit_utc(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _read_object(path: Path, label: str) -> dict[str, Any]:
    value = json.loads(path.resolve().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{label} root must be an object")
    return value


def _binding(path: Path) -> dict[str, Any]:
    source = path.resolve()
    if not source.is_file():
        raise ValueError(f"bound artifact is unavailable: {source}")
    return {"path": str(source), "sha256": _sha256_file(source), "size_bytes": source.stat().st_size}


def _binding_exact(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    path = Path(str(value.get("path", ""))).resolve()
    digest = value.get("sha256", value.get("file_sha256"))
    return path.is_file() and path.stat().st_size == value.get("size_bytes") and _sha256_file(path) == digest


def _binding_matches_path(value: object, path: Path) -> bool:
    if not isinstance(value, dict) or not path.is_file():
        return False
    return (
        path.stat().st_size == value.get("size_bytes")
        and _sha256_file(path) == value.get("sha256")
    )


def _semantic_hash_exact(binding: object, field: str) -> bool:
    if not _binding_exact(binding) or not isinstance(binding, dict):
        return False
    value = _read_object(Path(str(binding["path"])), field)
    claimed = value.get(field)
    unsigned = {key: item for key, item in value.items() if key != field}
    return isinstance(claimed, str) and claimed == binding.get(field) == _canonical_sha256(unsigned)


def _atomic_new_json(path: Path, value: dict[str, Any]) -> None:
    destination = path.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n").encode()
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o444)
    try:
        if os.write(descriptor, payload) != len(payload):
            raise OSError(f"short immutable artifact write: {destination}")
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _authority(programme: AdaptiveHybridProgramme) -> dict[str, Any]:
    return {
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
        "maximum_total_automatic_applications": programme.maximum_applications,
        "maximum_total_physical_control_applications": programme.maximum_physical_applications,
        **progressive_checkpoint_contract(programme),
        "maximum_combined_step_codes": programme.maximum_step_codes,
        "maximum_cumulative_absolute_movement_codes": programme.maximum_cumulative_movement_codes,
        "minimum_applied_cadence_s": programme.minimum_applied_cadence_s,
        "minimum_code": programme.minimum_code,
        "maximum_code": programme.maximum_code,
        "qualified_duration_s": programme.qualified_duration_s,
        "absolute_wall_clock_limit_s": programme.absolute_wall_limit_s,
        "maximum_outstanding_requests": 1,
        "automatic_retry": False,
        "automatic_restoration": False,
        "live_extension": False,
        "authority_consumed_by_first_physical_terminal": True,
        "setup_provenance": integrated_setup_provenance_contract(programme),
    }


def _device_contract() -> dict[str, Any]:
    return {
        "path": None,
        "selection": FRESH_SERIAL_AUTO_DETECT,
        "baud": EXPECTED_BAUD,
        "expected_board_serial": None,
    }


def _setup_contract(programme: AdaptiveHybridProgramme) -> dict[str, Any]:
    return {
        "code": programme.setup_code,
        "code_hex": f"0x{programme.setup_code:04X}",
        "maximum_applications": 1,
        "same_code_reapplication_opens_new_epoch": True,
        "exact_consumer_epoch_propagation_required": True,
        "provenance": integrated_setup_provenance_contract(programme),
    }


def _activation_unsigned(
    *,
    bundle_path: Path,
    proposal_path: Path,
    operational_rehearsal: dict[str, Any],
    bundle: dict[str, Any],
    proposal: dict[str, Any],
    operator_instruction_ref: str,
    attempt_reason: str,
    created_utc: str,
    programme: AdaptiveHybridProgramme,
    bundle_binding: dict[str, Any] | None = None,
    proposal_binding: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "tool": TOOL_ID,
        "tool_binding": _binding(Path(__file__)),
        "activation_id": programme.activation_id,
        "created_utc": created_utc,
        "programme_id": programme.programme_id,
        "operation": programme.operation,
        "status": "effective_exact_bundle_authority",
        "operator_instruction_ref": operator_instruction_ref,
        "run_identity": programme.runtime_run_identity,
        "image_identity": programme.profile_id,
        "bundle": {
            **(bundle_binding or _binding(bundle_path)),
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "proposal": {
            **(proposal_binding or _binding(proposal_path)),
            "proposal_sha256": proposal["proposal_sha256"],
        },
        "operational_rehearsal": operational_rehearsal,
        "attempt": {
            "ordinal": 1,
            "reason": attempt_reason,
            "automatic_retry": False,
        },
        "device": _device_contract(),
        "firmware": bundle["firmware"],
        "authoritative_inputs": bundle["authoritative_inputs"],
        "policy": bundle["policy"],
        "host_tools": bundle["host_tools"],
        "topology": {
            "serial_owner": "capture_device",
            "serial_owner_count": 1,
            "fifos": FIFO_PATHS,
        },
        "setup": _setup_contract(programme),
        "authority": _authority(programme),
    }


def validate_operational_rehearsal(
    path: Path, *, bundle: dict[str, Any], proposal: dict[str, Any],
    require_current_tools: bool = True,
    programme: AdaptiveHybridProgramme | None = None,
) -> dict[str, Any]:
    del bundle, proposal, require_current_tools, programme
    report = _read_object(path, "adaptive-hybrid rehearsal")
    if report.get("report_kind") == "structural_preflight":
        raise ValueError(
            "structural preflight cannot authorize activation; a genuine process/FIFO/"
            "command/acknowledgement/obstruction/abort/handoff/analyze/seal rehearsal "
            "is required"
        )
    raise ValueError(
        "activation is fail-closed: no genuine adaptive-hybrid operational-path "
        "rehearsal producer is implemented"
    )


def create_activation(
    *, bundle_path: Path, proposal_path: Path, operational_rehearsal_path: Path,
    serial_device: str, operator_instruction_ref: str, output_path: Path,
    attempt_ordinal: int = 1, attempt_reason: str = "initial frozen adaptive-hybrid entry",
    programme: AdaptiveHybridProgramme = ADAPTIVE_HYBRID_PROGRAMME,
) -> dict[str, Any]:
    if programme is not ADAPTIVE_HYBRID_PROGRAMME:
        raise ValueError("alternate programme descriptors are unsupported")
    if serial_device not in {"auto-detect", "--auto-detect"}:
        raise ValueError("activation requires fresh serial auto-detection")
    if attempt_ordinal != 1:
        raise ValueError("activation authorizes one fresh attempt only")
    if not operator_instruction_ref.strip() or not attempt_reason.strip():
        raise ValueError("activation requires operator and attempt reasons")
    bundle = validate_bundle(bundle_path, programme)
    proposal = validate_proposal(proposal_path, programme)
    rehearsal = validate_operational_rehearsal(
        operational_rehearsal_path, bundle=bundle, proposal=proposal, programme=programme
    )
    unsigned = _activation_unsigned(
        bundle_path=bundle_path,
        proposal_path=proposal_path,
        operational_rehearsal=rehearsal,
        bundle=bundle,
        proposal=proposal,
        operator_instruction_ref=operator_instruction_ref.strip(),
        attempt_reason=attempt_reason.strip(),
        created_utc=_utc_now(),
        programme=programme,
    )
    activation = {**unsigned, "activation_sha256": _canonical_sha256(unsigned)}
    _atomic_new_json(output_path, activation)
    return activation


def validate_frozen_activation(
    path: Path, *, bundle_path: Path | None = None, proposal_path: Path | None = None,
    programme: AdaptiveHybridProgramme | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    activation = _read_object(path, "adaptive-hybrid activation")
    selected = programme or programme_from_mapping(activation)
    claimed = activation.get("activation_sha256")
    unsigned = {key: value for key, value in activation.items() if key != "activation_sha256"}
    bundle_binding = activation.get("bundle", {})
    proposal_binding = activation.get("proposal", {})
    selected_bundle_path = (bundle_path or Path(str(bundle_binding.get("path", "")))).resolve()
    selected_proposal_path = (proposal_path or Path(str(proposal_binding.get("path", "")))).resolve()
    bundle = validate_bundle(selected_bundle_path, selected)
    proposal = validate_proposal(selected_proposal_path, selected)
    rehearsal_binding = activation.get("operational_rehearsal", {})
    attempt = activation.get("attempt", {})
    operator_ref = activation.get("operator_instruction_ref")
    created_utc = activation.get("created_utc")
    attempt_reason = attempt.get("reason") if isinstance(attempt, dict) else None
    if (
        not isinstance(operator_ref, str)
        or not operator_ref.strip()
        or operator_ref != operator_ref.strip()
        or not isinstance(attempt_reason, str)
        or not attempt_reason.strip()
        or attempt_reason != attempt_reason.strip()
        or not _explicit_utc(created_utc)
        or not _binding_exact(rehearsal_binding)
        or not _binding_matches_path(bundle_binding, selected_bundle_path)
        or not _binding_matches_path(proposal_binding, selected_proposal_path)
    ):
        raise ValueError("activation identity, topology, or authority differs")
    expected_unsigned = _activation_unsigned(
        bundle_path=Path(str(bundle_binding.get("path", ""))).resolve(),
        proposal_path=Path(str(proposal_binding.get("path", ""))).resolve(),
        operational_rehearsal=rehearsal_binding,
        bundle=bundle,
        proposal=proposal,
        operator_instruction_ref=operator_ref,
        attempt_reason=attempt_reason,
        created_utc=created_utc,
        programme=selected,
        bundle_binding=bundle_binding,
        proposal_binding=proposal_binding,
    )
    if claimed != _canonical_sha256(unsigned) or unsigned != expected_unsigned:
        raise ValueError(
            "activation build, firmware, policy, device, setup, operation, tool, "
            "limit, topology, or authority identity differs"
        )
    validate_operational_rehearsal(
        Path(str(rehearsal_binding.get("path", ""))),
        bundle=bundle,
        proposal=proposal,
        require_current_tools=False,
        programme=selected,
    )
    return activation, bundle, proposal


def validate_activation(
    path: Path, *, bundle_path: Path | None = None, proposal_path: Path | None = None,
    programme: AdaptiveHybridProgramme | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    return validate_frozen_activation(
        path, bundle_path=bundle_path, proposal_path=proposal_path, programme=programme
    )


def _transaction_identities(bundle: dict[str, Any]) -> dict[str, str]:
    frozen_inputs = bundle.get("authoritative_inputs")
    validate_authoritative_inputs(frozen_inputs)
    policy = authoritative_document(frozen_inputs, ROOT_PROFILE)
    bindings = policy.get("bindings", {})
    if not isinstance(bindings, dict):
        raise ValueError("adaptive-hybrid policy bindings are unavailable")

    def digest(name: str) -> str:
        relative = bindings.get(name)
        if not isinstance(relative, str):
            raise ValueError(f"policy binding {name!r} is unavailable")
        return str(authoritative_binding(frozen_inputs, relative)["sha256"])

    return {
        "estimator_sha256": digest("frequency_estimator"),
        "model_sha256": digest("plant_model"),
        "active_policy_sha256": str(bundle["policy"]["policy_sha256"]),
        "response_policy_sha256": digest("response_classification"),
        "numerical_policy_sha256": str(bundle["policy"]["policy_sha256"]),
    }


def _required_files() -> list[dict[str, Any]]:
    required = {
        "raw_events_v1", "count_observations_v1", "pps_snapshots_v1",
        "estimates_v2",
        "active_transactions_v2", "active_hybrid_decisions_v2",
        "active_hybrid_maintenance_v1", "relative_phase_observations_v1",
        "phase_estimator_outputs_v1",
    }
    files = [dict(item) for item in adaptive_hybrid_csv_files()]
    for item in files:
        if item["contract"] in required and item.get("record_type") != "EVT":
            item.pop("optional", None)
    return files


def _external_event_contract() -> dict[str, Any]:
    return {
        "pin": "D10",
        "channel_id": 0,
        "record_type": "EVT",
        "role": "external_event",
        "optional": True,
        "authority": "evidence_only",
        "control_eligible": False,
        "terminal_eligible": False,
    }


def _run_section(
    programme: AdaptiveHybridProgramme, authority: dict[str, Any]
) -> dict[str, Any]:
    return {
        "mode": "adaptive_hybrid_live",
        "profile_id": programme.profile_id,
        "run_identity": programme.runtime_run_identity,
        "authority": authority,
        "external_event_input": _external_event_contract(),
        "setup": {
            **_setup_contract(programme),
            "physical_applied_code_before_setup": integrated_setup_provenance_contract(
                programme
            )["physical_applied_code_before_setup"],
        },
        "automatic_control": {
            "authorized": True,
            "maximum_total_applications": programme.maximum_physical_applications,
            "maximum_total_automatic_applications": programme.maximum_applications,
            "maximum_step_codes": programme.maximum_step_codes,
            "maximum_cumulative_movement_codes": programme.maximum_cumulative_movement_codes,
            "minimum_applied_cadence_s": programme.minimum_applied_cadence_s,
            "minimum_code": programme.minimum_code,
            "maximum_code": programme.maximum_code,
            "maximum_outstanding_requests": 1,
            "automatic_retry": False,
            "automatic_restore": False,
        },
        "progressive_authority": progressive_checkpoint_contract(programme),
        "qualification": {
            "qualified_duration_s": programme.qualified_duration_s,
            "qualified_endpoint_contract": "qualified_D14_D8_aperture_count_v2",
            "qualified_d14_aperture_count": programme.qualified_d14_aperture_count,
            "correction_response_reserve_d14_apertures": (
                programme.correction_response_reserve_d14_apertures
            ),
            "absolute_wall_clock_limit_s": programme.absolute_wall_limit_s,
            "qualified_origin": (
                "first_fresh_selected_D14_D8_estimate_after_setup_and_settling"
            ),
            "wall_clock_origin": "run_manifest.started_at_utc",
            "no_extension": True,
        },
    }


def _host_contract(serial_device: str, bundle: dict[str, Any]) -> dict[str, Any]:
    return {
        "capture_tool": "host.otis_tools.capture_device",
        "supervisor_tool": "host.otis_tools.adaptive_hybrid_supervisor",
        "runner_tool": "host.otis_tools.adaptive_hybrid_run",
        "analyzer_tool": "host.otis_tools.adaptive_hybrid_analyze",
        "serial_device": serial_device,
        "activation_device_selection": FRESH_SERIAL_AUTO_DETECT,
        "baud": EXPECTED_BAUD,
        "expected_board_serial": None,
        "sole_serial_owner": True,
        "serial_owner_count": 1,
        "fifos": FIFO_PATHS,
        "tool_bindings": bundle["host_tools"],
    }


def _channels() -> list[dict[str, Any]]:
    return [
        {
            "channel_id": 0,
            "pin": "D10",
            "role": "external_event",
            "record_type": "EVT",
            "record_family": "raw_events_v1",
            "authority": "evidence_only",
            "control_authority": False,
            "terminal_authority": False,
        },
        {
            "channel_id": 1,
            "pin": "D14",
            "role": "authoritative_pps_reference",
            "record_type": "REF",
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
            "pin": "D6",
            "role": "diagnostic_forwarded_d9_clock_monitor_zero_authority",
            "record_family": "forwarded_monitor_snapshots_v1",
            "authority": "diagnostic_only",
            "control_authority": False,
            "terminal_authority": False,
        },
    ]


def _contract_versions(files: list[dict[str, Any]]) -> dict[str, int]:
    version_two = {
        "estimates_v2",
        "active_transactions_v2",
        "active_hybrid_decisions_v2",
    }
    return {
        item["contract"]: 2 if item["contract"] in version_two else 1
        for item in files
    }


def _expected_artifacts(
    files: list[dict[str, Any]], programme: AdaptiveHybridProgramme
) -> list[str]:
    return [
        *[item["path"] for item in files if not item.get("optional")],
        "raw/serial.log",
        "reports/capture_device_state.json",
        "reports/adaptive_hybrid_supervisor_state.json",
        "reports/adaptive_hybrid_supervisor_events.jsonl",
        "reports/capture_segment_closure_v1.json",
        str(programme.run_activation_path),
        str(programme.run_proposal_path),
        str(programme.run_bundle_path),
        "COMPLETE",
    ]


def _evidence_artifacts(programme: AdaptiveHybridProgramme) -> list[str]:
    return [
        "reports/capture_device_state.json",
        "reports/adaptive_hybrid_supervisor_state.json",
        "reports/adaptive_hybrid_supervisor_events.jsonl",
        "reports/capture_segment_closure_v1.json",
        str(programme.run_activation_path),
        str(programme.run_proposal_path),
        str(programme.run_bundle_path),
        "COMPLETE",
    ]


def _known_limitations() -> list[str]:
    return [
        "D14 is the sole PPS/reference input and D8 is the sole oscillator/count input.",
        "D10 external-event evidence never enters timing, control, actuation, or the run terminal.",
        "D9 and D6 are diagnostic-only and fail locally.",
    ]


def create_run_manifest(
    *, activation_path: Path, bundle_path: Path, proposal_path: Path,
    run_dir: Path, output_path: Path, serial_device: str | None = None,
) -> dict[str, Any]:
    programme = ADAPTIVE_HYBRID_PROGRAMME
    run_dir = run_dir.resolve()
    if output_path.resolve() != (run_dir / RUN_MANIFEST_PATH).resolve():
        raise ValueError("live manifest must be run-local run_manifest.json")
    activation, bundle, proposal = validate_activation(
        activation_path, bundle_path=bundle_path, proposal_path=proposal_path,
        programme=programme,
    )
    if not isinstance(serial_device, str) or not serial_device.startswith("/dev/"):
        raise ValueError("run manifest requires the freshly resolved serial device")
    files = _required_files()
    now = _utc_now()
    section = _run_section(programme, activation["authority"])
    manifest: dict[str, Any] = {
        "schema_version": 1,
        "evidence_epoch": programme.evidence_epoch,
        "template": False,
        "run_id": run_dir.name,
        "created_utc": now,
        "started_at_utc": now,
        "stage": programme.live_stage,
        "programme_id": programme.programme_id,
        "run_identity": programme.runtime_run_identity,
        "image_identity": programme.profile_id,
        "board": "arduino_nano_rp2040_connect",
        "capture_mode": "pio_wait_cumulative_snapshot_with_independent_gpio_ref",
        "control_mode": "adaptive_hybrid_regulation",
        "closed_loop_control": True,
        "actionable": True,
        "actuation_authorized": True,
        "qualification_evidence": True,
        "bundle": {**_binding(bundle_path), "bundle_sha256": bundle["bundle_sha256"]},
        "proposal": {**_binding(proposal_path), "proposal_sha256": proposal["proposal_sha256"]},
        "activation": {**_binding(activation_path), "activation_sha256": activation["activation_sha256"]},
        "firmware": bundle["firmware"],
        "authoritative_inputs": bundle["authoritative_inputs"],
        "policy": bundle["policy"],
        "transaction_identities": _transaction_identities(bundle),
        "host": _host_contract(serial_device, bundle),
        programme.manifest_section: section,
        "domains": [canonical_domain_declaration(name) for name in ("rp2040_monotonic_us32", "rp2040_monotonic_us64", "h1_adaptive_hybrid_ocxo_10mhz")],
        "channels": _channels(),
        "contracts": _contract_versions(files),
        "files": files,
        "expected_artifacts": _expected_artifacts(files, programme),
        "evidence_artifacts": _evidence_artifacts(programme),
        "known_limitations": _known_limitations(),
    }
    manifest["manifest_sha256"] = _canonical_sha256(manifest)
    _atomic_new_json(output_path, manifest)
    return manifest


def validate_frozen_run_manifest(path: Path) -> dict[str, Any]:
    manifest = _read_object(path, "adaptive-hybrid run manifest")
    programme = programme_from_mapping(manifest)
    claimed = manifest.get("manifest_sha256")
    unsigned = {key: value for key, value in manifest.items() if key != "manifest_sha256"}
    activation_binding = manifest.get("activation")
    bundle_binding = manifest.get("bundle")
    proposal_binding = manifest.get("proposal")
    if (
        claimed != _canonical_sha256(unsigned)
        or path.resolve() != (path.parent / RUN_MANIFEST_PATH).resolve()
        or not _semantic_hash_exact(activation_binding, "activation_sha256")
        or not _semantic_hash_exact(bundle_binding, "bundle_sha256")
        or not _semantic_hash_exact(proposal_binding, "proposal_sha256")
        or Path(str(activation_binding["path"])).resolve() != (path.parent / programme.run_activation_path).resolve()
        or Path(str(bundle_binding["path"])).resolve() != (path.parent / programme.run_bundle_path).resolve()
        or Path(str(proposal_binding["path"])).resolve() != (path.parent / programme.run_proposal_path).resolve()
    ):
        raise ValueError("run-manifest identity, topology, or authority differs")

    bundle_path = Path(str(bundle_binding["path"])).resolve()
    proposal_path = Path(str(proposal_binding["path"])).resolve()
    activation_path = Path(str(activation_binding["path"])).resolve()
    bundle = validate_bundle(bundle_path, programme)
    proposal = validate_proposal(proposal_path, programme)
    activation = _read_object(activation_path, "adaptive-hybrid activation")
    activation_unsigned = {
        key: value for key, value in activation.items() if key != "activation_sha256"
    }
    if (
        activation.get("activation_sha256") != _canonical_sha256(activation_unsigned)
        or activation.get("firmware") != bundle["firmware"]
        or activation.get("authoritative_inputs") != bundle["authoritative_inputs"]
        or activation.get("policy") != bundle["policy"]
        or activation.get("host_tools") != bundle["host_tools"]
        or activation.get("operation") != programme.operation
        or activation.get("device") != _device_contract()
        or activation.get("setup") != _setup_contract(programme)
        or activation.get("authority") != _authority(programme)
        or proposal.get("build_identity") != bundle["firmware"]["build_identity"]
        or proposal.get("policy_sha256") != bundle["policy"]["policy_sha256"]
    ):
        raise ValueError("run-manifest activation, bundle, or proposal identity differs")

    created_utc = manifest.get("created_utc")
    started_at_utc = manifest.get("started_at_utc")
    host = manifest.get("host")
    serial_device = host.get("serial_device") if isinstance(host, dict) else None
    if (
        not _explicit_utc(created_utc)
        or not _explicit_utc(started_at_utc)
        or not isinstance(serial_device, str)
        or not serial_device.startswith("/dev/")
    ):
        raise ValueError("run-manifest creation or serial identity differs")
    files = _required_files()
    expected_unsigned: dict[str, Any] = {
        "schema_version": 1,
        "evidence_epoch": programme.evidence_epoch,
        "template": False,
        "run_id": path.parent.name,
        "created_utc": created_utc,
        "started_at_utc": started_at_utc,
        "stage": programme.live_stage,
        "programme_id": programme.programme_id,
        "run_identity": programme.runtime_run_identity,
        "image_identity": programme.profile_id,
        "board": "arduino_nano_rp2040_connect",
        "capture_mode": "pio_wait_cumulative_snapshot_with_independent_gpio_ref",
        "control_mode": "adaptive_hybrid_regulation",
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
        "authoritative_inputs": bundle["authoritative_inputs"],
        "policy": bundle["policy"],
        "transaction_identities": _transaction_identities(bundle),
        "host": _host_contract(str(serial_device), bundle),
        programme.manifest_section: _run_section(programme, activation["authority"]),
        "domains": [
            canonical_domain_declaration(name)
            for name in (
                "rp2040_monotonic_us32",
                "rp2040_monotonic_us64",
                "h1_adaptive_hybrid_ocxo_10mhz",
            )
        ],
        "channels": _channels(),
        "contracts": _contract_versions(files),
        "files": files,
        "expected_artifacts": _expected_artifacts(files, programme),
        "evidence_artifacts": _evidence_artifacts(programme),
        "known_limitations": _known_limitations(),
    }
    if unsigned != expected_unsigned:
        raise ValueError(
            "run-manifest firmware, policy, transaction, tool, setup, limit, "
            "topology, file, or authority contract differs"
        )
    errors = validate_domain_declarations(manifest.get("domains"))
    if errors:
        raise ValueError("run-manifest time domains differ: " + "; ".join(errors))
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
    parser.add_argument("--validate-activation", type=Path)
    parser.add_argument("--validate-manifest", type=Path)
    args = parser.parse_args(argv)
    if args.validate_activation:
        value = validate_activation(args.validate_activation)[0]
    elif args.validate_manifest:
        value = validate_run_manifest(args.validate_manifest)
    else:
        parser.error("select one validation operation")
    print(json.dumps(value, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
