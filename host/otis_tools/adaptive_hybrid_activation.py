"""Create and validate the sole adaptive-hybrid activation and run manifest."""

from __future__ import annotations

import argparse
from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
from typing import Any

from .adaptive_hybrid_bundle import (
    FRESH_SERIAL_AUTO_DETECT,
    validate_bundle,
    validate_frozen_bundle,
)
from .adaptive_hybrid_contract import (
    ADAPTIVE_HYBRID_PROGRAMME,
    OPERATIONAL_REHEARSAL_REQUIRED_BOUNDARIES,
    OPERATIONAL_REHEARSAL_SEAL_TYPE,
    AdaptiveHybridProgramme,
    BenchAttemptEnvelope,
    envelope_for_purpose,
    integrated_setup_provenance_contract,
    operational_rehearsal_authorization_contract,
    progressive_checkpoint_contract,
    programme_from_mapping,
    validate_bench_attempt_envelope,
)
from .adaptive_hybrid_proposal import (
    validate_frozen_proposal,
)
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
_CURRENT_REPRODUCTION_CAPABILITY_SECRET = object()


@dataclass(frozen=True)
class _ValidatedCurrentReproduction:
    activation_sha256: str
    bundle_sha256: str
    proposal_sha256: str
    build_identity: str
    uf2_sha256: str
    _secret: object = field(repr=False, compare=False)


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


def _setup_provenance_contract(
    programme: AdaptiveHybridProgramme,
    bench_attempt: BenchAttemptEnvelope,
) -> dict[str, Any]:
    provenance = integrated_setup_provenance_contract(programme)
    setup_code = bench_attempt.limits.setup_code
    provenance.update(
        {
            "authorized_setup_code": setup_code,
            "authorized_setup_code_hex": (
                f"0x{setup_code:04X}" if setup_code is not None else None
            ),
            "setup_operation": (
                "prospectively_frozen_authorized_stimulus_not_restoration"
                if setup_code is not None
                else "inhibited_by_bench_attempt_contract"
            ),
            "first_confirmed_state_boundary": (
                "exact_setup_acceptance_application_DAC_epoch_and_first_dependent_consumer"
                if setup_code is not None
                else "not_applicable_no_setup_or_DAC_value_write"
            ),
        }
    )
    return provenance


def _authority(
    programme: AdaptiveHybridProgramme,
    bench_attempt: BenchAttemptEnvelope,
) -> dict[str, Any]:
    envelope = bench_attempt.as_dict()
    limits = envelope["authority"]
    timing = envelope["timing"]
    setup_limit = int(limits["setup_application_limit"])
    automatic_limit = int(limits["automatic_application_limit"])
    return {
        "effective": True,
        "physical_execution": True,
        "firmware_flash_limit": 1,
        "reset_for_entry_only": True,
        "serial_open": True,
        "command_fifo": True,
        "bench_attempt_purpose": bench_attempt.purpose,
        "bench_attempt_envelope_sha256": envelope["envelope_sha256"],
        "setup_stimulus": setup_limit == 1,
        "setup_code": limits["setup_code"],
        "setup_write_limit": setup_limit,
        "control_arm": int(limits["arm_submission_limit"]) > 0,
        "arm_submission_limit": limits["arm_submission_limit"],
        "live_acquisition_limit": 1,
        "maximum_total_automatic_applications": automatic_limit,
        "required_completed_automatic_applications": limits[
            "required_completed_automatic_applications"
        ],
        "maximum_total_physical_control_applications": automatic_limit,
        "total_dac_value_write_limit": limits["total_dac_value_write_limit"],
        "maximum_combined_step_codes": (
            programme.maximum_step_codes if automatic_limit else 0
        ),
        "maximum_cumulative_absolute_movement_codes": (
            programme.authorized_maximum_cumulative_movement_codes
            if automatic_limit
            else 0
        ),
        "minimum_applied_cadence_s": (
            programme.minimum_applied_cadence_s if automatic_limit else None
        ),
        "minimum_code": programme.minimum_code if automatic_limit else None,
        "maximum_code": programme.maximum_code if automatic_limit else None,
        "progress_domain": timing["progress_domain"],
        "qualified_endpoint_contract": timing["endpoint_contract"],
        "automatic_application_admission_deadline_delta": timing[
            "automatic_application_admission_deadline_delta"
        ],
        "correction_response_reserve_delta": timing[
            "correction_response_reserve_delta"
        ],
        "first_dependent_decision_reserve_delta": timing[
            "first_dependent_decision_reserve_delta"
        ],
        "absolute_wall_clock_limit_s": timing["absolute_wall_limit_s"],
        "wall_limit_role": timing["wall_limit_role"],
        "maximum_outstanding_requests": limits["maximum_outstanding_requests"],
        "authority_initially_closed": envelope["causal_state"][
            "authority_closed"
        ]["initial"],
        "automatic_retry": limits["automatic_retry_permitted"],
        "arm_retry": limits["arm_retry_permitted"],
        "automatic_restoration": limits["restore_write_permitted"],
        "live_extension": limits["attempt_extension_permitted"],
        "forced_correction": limits["forced_correction_permitted"],
        "authority_consumed_by_first_physical_terminal": True,
        "setup_provenance": _setup_provenance_contract(
            programme, bench_attempt
        ),
        "host_discrepancy_semantics": envelope["host_discrepancy_semantics"],
    }


def _device_contract(bench_attempt: BenchAttemptEnvelope) -> dict[str, Any]:
    identity = bench_attempt.as_dict()["device_identity"]
    return {
        "path": None,
        "selection": FRESH_SERIAL_AUTO_DETECT,
        "baud": EXPECTED_BAUD,
        **identity,
    }


def _setup_contract(
    programme: AdaptiveHybridProgramme,
    bench_attempt: BenchAttemptEnvelope,
) -> dict[str, Any]:
    setup_code = bench_attempt.limits.setup_code
    setup_limit = bench_attempt.limits.setup_application_limit
    return {
        "authorized": setup_limit == 1,
        "code": setup_code,
        "code_hex": f"0x{setup_code:04X}" if setup_code is not None else None,
        "maximum_applications": setup_limit,
        "same_code_reapplication_opens_new_epoch": setup_limit == 1,
        "exact_consumer_epoch_propagation_required": setup_limit == 1,
        "provenance": _setup_provenance_contract(programme, bench_attempt),
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
    bench_attempt: BenchAttemptEnvelope,
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
        "bench_attempt": bench_attempt.as_dict(),
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
        "device": _device_contract(bench_attempt),
        "firmware": bundle["firmware"],
        "authoritative_inputs": bundle["authoritative_inputs"],
        "policy": bundle["policy"],
        "host_tools": bundle["host_tools"],
        "topology": {
            "serial_owner": "capture_device",
            "serial_owner_count": 1,
            "fifos": FIFO_PATHS,
        },
        "setup": _setup_contract(programme, bench_attempt),
        "authority": _authority(programme, bench_attempt),
    }


def validate_operational_rehearsal(
    path: Path, *, bundle: dict[str, Any], proposal: dict[str, Any],
    require_current_tools: bool = True,
    programme: AdaptiveHybridProgramme | None = None,
) -> dict[str, Any]:
    """Validate and canonically bind one independently sealed rehearsal."""

    report_path = path.resolve()
    initial_report_binding = _binding(report_path)
    report = _read_object(report_path, "adaptive-hybrid rehearsal")
    if report.get("report_kind") == "structural_preflight":
        raise ValueError(
            "structural preflight cannot authorize activation; a genuine process/FIFO/"
            "command/acknowledgement/obstruction/abort/handoff/analyze/seal rehearsal "
            "is required"
        )
    selected = programme or ADAPTIVE_HYBRID_PROGRAMME
    if selected is not ADAPTIVE_HYBRID_PROGRAMME:
        raise ValueError("alternate rehearsal programme descriptors are unsupported")

    # The evidence layer independently recomputes retained package bytes.  The
    # executable producer and mutable index implementation are not validators.
    from . import evidence as evidence_module

    contract = operational_rehearsal_authorization_contract(
        bundle=bundle, proposal=proposal, programme=selected
    )
    expected_fields = {
        "schema_version",
        "tool",
        "tool_binding",
        "report_kind",
        "seal_type",
        "status",
        "created_utc",
        "identity",
        "required_boundaries",
        "boundary_results",
        "required_evidence",
        "host_discrepancy_semantics",
        "claim_boundary",
        "producer_requirement",
        "package",
        "manifest",
        "evidence_snapshot",
        "seal",
        "process_evidence",
        "registration",
        "activation_input_ready",
        "minimal_remaining_extension",
        "report_sha256",
    }
    claimed_report_sha256 = report.get("report_sha256")
    unsigned_report = {
        key: value for key, value in report.items() if key != "report_sha256"
    }
    producer_binding = bundle.get("host_tools", {}).get(
        "adaptive_hybrid_operational_rehearsal"
    )
    frozen_tool_bindings = contract["required_evidence"].get(
        "exact_tool_bindings"
    )
    if (
        set(report) != expected_fields
        or not isinstance(claimed_report_sha256, str)
        or claimed_report_sha256 != _canonical_sha256(unsigned_report)
        or report.get("schema_version") != contract["schema_version"]
        or report.get("tool") != evidence_module.OPERATIONAL_REHEARSAL_TOOL_ID
        or report.get("tool_binding") != producer_binding
        or not _binding_exact(producer_binding)
        or report.get("report_kind") != contract["report_kind"]
        or report.get("seal_type") != contract["seal_type"]
        or report.get("status") != contract["status"]
        or not _explicit_utc(report.get("created_utc"))
        or report.get("identity") != contract["identity"]
        or report.get("required_boundaries") != contract["required_boundaries"]
        or report.get("boundary_results")
        != {boundary: True for boundary in contract["required_boundaries"]}
        or report.get("required_evidence") != contract["required_evidence"]
        or report.get("host_discrepancy_semantics")
        != contract["host_discrepancy_semantics"]
        or report.get("claim_boundary") != contract["claim_boundary"]
        or report.get("producer_requirement") != contract["producer_requirement"]
        or report.get("activation_input_ready") is not True
        or report.get("minimal_remaining_extension") is not None
        or not isinstance(frozen_tool_bindings, dict)
        or not all(_binding_exact(value) for value in frozen_tool_bindings.values())
    ):
        raise ValueError(
            "adaptive-hybrid operational rehearsal report contract differs"
        )
    if require_current_tools:
        current_producer_binding = _binding(
            Path(__file__).with_name("adaptive_hybrid_operational_rehearsal.py")
        )
        if producer_binding != current_producer_binding:
            raise ValueError(
                "adaptive-hybrid operational rehearsal producer binding differs"
            )

    package_report = report.get("package")
    registration = report.get("registration")
    if not isinstance(package_report, dict) or not isinstance(registration, dict):
        raise ValueError("adaptive-hybrid rehearsal package registration is malformed")
    package_path = Path(str(package_report.get("path", ""))).resolve()
    if report_path != package_path.parent / (
        f"{package_path.name}-{evidence_module.OPERATIONAL_REHEARSAL_REPORT_NAME}"
    ):
        raise ValueError("adaptive-hybrid rehearsal report path differs")
    package_before = evidence_module.package_identity(package_path)
    expected_package_report = {
        "path": str(package_path),
        "content_sha256": package_before["content_sha256"],
        "file_count": package_before["file_count"],
        "total_bytes": package_before["total_bytes"],
    }
    if package_report != expected_package_report:
        raise ValueError("adaptive-hybrid rehearsal package identity differs")

    identity = contract["identity"]
    success_reason = "adaptive-hybrid operational rehearsal passed"
    analyzer_identity = str(producer_binding["sha256"])
    package_validation = evidence_module.validate_operational_rehearsal_package(
        package_path,
        source_revision=str(identity["source_revision"]),
        build_identity=str(identity["build_identity"]),
        image_identity=str(identity["image_identity"]),
        result_or_failure_reason=success_reason,
        analyzer_identity=analyzer_identity,
    )
    if (
        set(package_validation)
        != {
            "contract",
            "evidence_snapshot_sha256",
            "seal_path",
            "seal_sha256",
            "seal_status",
            "primary_decision",
        }
        or package_validation.get("contract")
        != "otis_validated_success_package_v1"
    ):
        raise ValueError(
            "adaptive-hybrid rehearsal independent package validation differs"
        )

    expected_paths = {
        "manifest": package_path / "run_manifest.json",
        "evidence_snapshot": package_path / "evidence_manifest.json",
        "seal": package_path / evidence_module.OPERATIONAL_REHEARSAL_SEAL_PATH,
        "process_evidence": (
            package_path / evidence_module.OPERATIONAL_REHEARSAL_PROCESS_EVIDENCE_PATH
        ),
    }
    for field, expected_path in expected_paths.items():
        binding = report.get(field)
        if not isinstance(binding, dict):
            raise ValueError(f"adaptive-hybrid rehearsal {field} binding is malformed")
        expected_binding = _binding(expected_path)
        if any(binding.get(key) != value for key, value in expected_binding.items()):
            raise ValueError(f"adaptive-hybrid rehearsal {field} binding differs")
    private_manifest = _read_object(
        expected_paths["manifest"], "adaptive-hybrid rehearsal manifest"
    )
    private_bundle = private_manifest.get("bundle")
    private_proposal = private_manifest.get("proposal")
    if (
        not isinstance(private_bundle, dict)
        or not isinstance(private_proposal, dict)
        or private_bundle.get("bundle_sha256") != identity["bundle_sha256"]
        or private_proposal.get("proposal_sha256") != identity["proposal_sha256"]
        or private_manifest.get("programme_id") != identity["programme_id"]
        or private_manifest.get("run_identity") != identity["run_identity"]
        or private_manifest.get("image_identity") != identity["image_identity"]
    ):
        raise ValueError("adaptive-hybrid rehearsal manifest identity differs")
    if (
        set(report["manifest"]) != {"path", "sha256", "size_bytes"}
        or set(report["process_evidence"]) != {"path", "sha256", "size_bytes"}
        or set(report["evidence_snapshot"])
        != {"path", "sha256", "size_bytes", "snapshot_digest"}
        or report["evidence_snapshot"].get("snapshot_digest")
        != package_validation.get("evidence_snapshot_sha256")
        or set(report["seal"])
        != {"path", "sha256", "size_bytes", "seal_sha256"}
        or report["seal"].get("seal_sha256")
        != package_validation.get("seal_sha256")
        or package_validation.get("seal_path")
        != evidence_module.OPERATIONAL_REHEARSAL_SEAL_PATH.as_posix()
        or package_validation.get("seal_status") != "passed"
    ):
        raise ValueError("adaptive-hybrid rehearsal sealed evidence binding differs")

    expected_registration = {
        "index_path": str(
            Path(str(registration.get("index_path", ""))).resolve()
        ),
        "content_sha256": package_before["content_sha256"],
        "attempt_classification": "successful_rehearsal",
        "successful_rehearsal_validation_error": None,
    }
    if registration != expected_registration:
        raise ValueError("adaptive-hybrid rehearsal registration report differs")
    raw_index_path = Path(str(registration.get("index_path", ""))).expanduser()
    if raw_index_path.is_symlink():
        raise ValueError("adaptive-hybrid rehearsal evidence index may not be a symlink")
    index = _read_object(
        raw_index_path.resolve(), "adaptive-hybrid rehearsal evidence index"
    )
    if (
        set(index)
        != {"schema_version", "index_id", "created_utc", "updated_utc", "packages"}
        or index.get("schema_version") != evidence_module.EVIDENCE_INDEX_SCHEMA_VERSION
        or index.get("index_id") != evidence_module.EVIDENCE_INDEX_ID
        or not _explicit_utc(index.get("created_utc"))
        or not _explicit_utc(index.get("updated_utc"))
        or not isinstance(index.get("packages"), dict)
    ):
        raise ValueError("adaptive-hybrid rehearsal evidence index differs")
    record = index["packages"].get(package_before["content_sha256"])
    expected_record_fields = {
        "content_sha256",
        "file_count",
        "total_bytes",
        "file_manifest",
        "storage_locations",
        "source_revision",
        "build_identity",
        "image_identity",
        "attempt_classification",
        "result_or_failure_reason",
        "analyzer_identity",
        "package_validation",
        "lifecycle_status",
        "registered_utc",
        "mothball",
    }
    if not isinstance(record, dict):
        raise ValueError("adaptive-hybrid successful rehearsal index entry is absent")
    storage_locations = record.get("storage_locations")
    if (
        set(record) != expected_record_fields
        or record.get("content_sha256") != package_before["content_sha256"]
        or record.get("file_count") != package_before["file_count"]
        or record.get("total_bytes") != package_before["total_bytes"]
        or record.get("file_manifest") != package_before["files"]
        or not isinstance(storage_locations, list)
        or str(package_path) not in storage_locations
        or len(storage_locations) != len(set(storage_locations))
        or record.get("source_revision") != identity["source_revision"]
        or record.get("build_identity") != identity["build_identity"]
        or record.get("image_identity") != identity["image_identity"]
        or record.get("attempt_classification") != "successful_rehearsal"
        or record.get("result_or_failure_reason") != success_reason
        or record.get("analyzer_identity") != analyzer_identity
        or record.get("package_validation") != package_validation
        or record.get("lifecycle_status") != "active"
        or not _explicit_utc(record.get("registered_utc"))
        or record.get("mothball") is not None
    ):
        raise ValueError("adaptive-hybrid successful rehearsal index entry differs")

    package_after = evidence_module.package_identity(package_path)
    final_report_binding = _binding(report_path)
    if package_after != package_before or final_report_binding != initial_report_binding:
        raise ValueError("adaptive-hybrid rehearsal evidence changed during validation")
    return {
        **final_report_binding,
        "report_sha256": claimed_report_sha256,
        "package_content_sha256": str(package_before["content_sha256"]),
        "evidence_snapshot_sha256": str(
            package_validation["evidence_snapshot_sha256"]
        ),
        "seal_sha256": str(package_validation["seal_sha256"]),
    }


def create_activation(
    *, bundle_path: Path, proposal_path: Path, operational_rehearsal_path: Path,
    serial_device: str, operator_instruction_ref: str, output_path: Path,
    bench_attempt_purpose: str,
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
    bench_attempt = envelope_for_purpose(bench_attempt_purpose)
    bundle = validate_bundle(bundle_path, programme)
    proposal = validate_frozen_proposal(proposal_path, programme)
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
        bench_attempt=bench_attempt,
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
    raw_bench_attempt = activation.get("bench_attempt")
    if not isinstance(raw_bench_attempt, dict):
        raise ValueError("activation lacks an exact bench-attempt envelope")
    bench_attempt = validate_bench_attempt_envelope(raw_bench_attempt)
    claimed = activation.get("activation_sha256")
    unsigned = {key: value for key, value in activation.items() if key != "activation_sha256"}
    bundle_binding = activation.get("bundle", {})
    proposal_binding = activation.get("proposal", {})
    selected_bundle_path = (bundle_path or Path(str(bundle_binding.get("path", "")))).resolve()
    selected_proposal_path = (proposal_path or Path(str(proposal_binding.get("path", "")))).resolve()
    bundle = validate_frozen_bundle(selected_bundle_path, selected)
    proposal = validate_frozen_proposal(selected_proposal_path, selected)
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
        bench_attempt=bench_attempt,
        bundle_binding=bundle_binding,
        proposal_binding=proposal_binding,
    )
    if claimed != _canonical_sha256(unsigned) or unsigned != expected_unsigned:
        raise ValueError(
            "activation build, firmware, policy, device, setup, operation, tool, "
            "limit, topology, or authority identity differs"
        )
    canonical_rehearsal_binding = validate_operational_rehearsal(
        Path(str(rehearsal_binding.get("path", ""))),
        bundle=bundle,
        proposal=proposal,
        require_current_tools=False,
        programme=selected,
    )
    if rehearsal_binding != canonical_rehearsal_binding:
        raise ValueError("activation rehearsal binding differs")
    return activation, bundle, proposal


def validate_activation(
    path: Path, *, bundle_path: Path | None = None, proposal_path: Path | None = None,
    programme: AdaptiveHybridProgramme | None = None,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    activation, frozen_bundle, proposal = validate_frozen_activation(
        path, bundle_path=bundle_path, proposal_path=proposal_path, programme=programme
    )
    selected = programme or programme_from_mapping(activation)
    bundle_binding = activation.get("bundle", {})
    selected_bundle_path = (
        bundle_path or Path(str(bundle_binding.get("path", "")))
    ).resolve()
    current_bundle = validate_bundle(selected_bundle_path, selected)
    if current_bundle != frozen_bundle:
        raise ValueError("activation frozen and reproduced bundle identities differ")
    return activation, current_bundle, proposal


def validate_activation_for_physical_entry(
    path: Path,
    *,
    bundle_path: Path | None = None,
    proposal_path: Path | None = None,
    programme: AdaptiveHybridProgramme | None = None,
) -> tuple[
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    _ValidatedCurrentReproduction,
]:
    """Reproduce once and return the private capability required to go live."""

    activation, bundle, proposal = validate_activation(
        path,
        bundle_path=bundle_path,
        proposal_path=proposal_path,
        programme=programme,
    )
    capability = _ValidatedCurrentReproduction(
        activation_sha256=str(activation["activation_sha256"]),
        bundle_sha256=str(bundle["bundle_sha256"]),
        proposal_sha256=str(proposal["proposal_sha256"]),
        build_identity=str(bundle["firmware"]["build_identity"]),
        uf2_sha256=str(bundle["firmware"]["uf2"]["sha256"]),
        _secret=_CURRENT_REPRODUCTION_CAPABILITY_SECRET,
    )
    return activation, bundle, proposal, capability


def _require_current_reproduction_capability(
    capability: _ValidatedCurrentReproduction | None,
    *,
    activation: dict[str, Any],
    bundle: dict[str, Any],
    proposal: dict[str, Any],
) -> None:
    firmware = bundle.get("firmware")
    uf2 = firmware.get("uf2") if isinstance(firmware, dict) else None
    expected = (
        activation.get("activation_sha256"),
        bundle.get("bundle_sha256"),
        proposal.get("proposal_sha256"),
        firmware.get("build_identity") if isinstance(firmware, dict) else None,
        uf2.get("sha256") if isinstance(uf2, dict) else None,
    )
    observed = (
        (
            capability.activation_sha256,
            capability.bundle_sha256,
            capability.proposal_sha256,
            capability.build_identity,
            capability.uf2_sha256,
        )
        if isinstance(capability, _ValidatedCurrentReproduction)
        else None
    )
    if (
        not isinstance(capability, _ValidatedCurrentReproduction)
        or capability._secret is not _CURRENT_REPRODUCTION_CAPABILITY_SECRET
        or observed != expected
    ):
        raise ValueError(
            "live manifest requires the matching current firmware reproduction capability"
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
    programme: AdaptiveHybridProgramme,
    authority: dict[str, Any],
    bench_attempt: BenchAttemptEnvelope,
) -> dict[str, Any]:
    envelope = bench_attempt.as_dict()
    limits = envelope["authority"]
    timing = envelope["timing"]
    automatic_limit = int(limits["automatic_application_limit"])
    return {
        "mode": "adaptive_hybrid_bench_attempt",
        "purpose": bench_attempt.purpose,
        "bench_attempt_envelope_sha256": envelope["envelope_sha256"],
        "profile_id": programme.profile_id,
        "run_identity": programme.runtime_run_identity,
        "authority": authority,
        "external_event_input": _external_event_contract(),
        "setup": {
            **_setup_contract(programme, bench_attempt),
            "physical_applied_code_before_setup": _setup_provenance_contract(
                programme, bench_attempt
            )["physical_applied_code_before_setup"],
        },
        "automatic_control": {
            "authorized": automatic_limit > 0,
            "maximum_total_applications": automatic_limit,
            "maximum_total_automatic_applications": automatic_limit,
            "required_completed_automatic_applications": limits[
                "required_completed_automatic_applications"
            ],
            "arm_submission_limit": limits["arm_submission_limit"],
            "total_dac_value_write_limit": limits[
                "total_dac_value_write_limit"
            ],
            "maximum_step_codes": (
                programme.maximum_step_codes if automatic_limit else 0
            ),
            "maximum_cumulative_movement_codes": (
                programme.authorized_maximum_cumulative_movement_codes
                if automatic_limit
                else 0
            ),
            "minimum_applied_cadence_s": (
                programme.minimum_applied_cadence_s if automatic_limit else None
            ),
            "minimum_code": programme.minimum_code if automatic_limit else None,
            "maximum_code": programme.maximum_code if automatic_limit else None,
            "maximum_outstanding_requests": limits[
                "maximum_outstanding_requests"
            ],
            "automatic_retry": limits["automatic_retry_permitted"],
            "arm_retry": limits["arm_retry_permitted"],
            "automatic_restore": limits["restore_write_permitted"],
            "forced_correction": limits["forced_correction_permitted"],
        },
        "progressive_authority": {
            "causal_state": envelope["causal_state"],
            "terminal_semantics": envelope["terminal_semantics"],
        },
        "qualification": {
            "progress_domain": timing["progress_domain"],
            "qualified_endpoint_contract": timing["endpoint_contract"],
            "automatic_application_admission_deadline_delta": timing[
                "automatic_application_admission_deadline_delta"
            ],
            "correction_response_reserve_delta": timing[
                "correction_response_reserve_delta"
            ],
            "first_dependent_decision_reserve_delta": timing[
                "first_dependent_decision_reserve_delta"
            ],
            "absolute_wall_clock_limit_s": timing["absolute_wall_limit_s"],
            "qualified_origin": (
                "first_fresh_selected_D14_D8_estimate_after_setup_and_settling"
                if bench_attempt.limits.setup_application_limit
                else "first_fresh_selected_D14_D8_estimate_after_firmware_entry"
            ),
            "wall_clock_origin": "run_manifest.started_at_utc",
            "wall_limit_role": timing["wall_limit_role"],
            "no_extension": not limits["attempt_extension_permitted"],
        },
    }


def _host_contract(
    serial_device: str,
    bundle: dict[str, Any],
    bench_attempt: BenchAttemptEnvelope,
) -> dict[str, Any]:
    return {
        "capture_tool": "host.otis_tools.capture_device",
        "supervisor_tool": "host.otis_tools.adaptive_hybrid_supervisor",
        "runner_tool": "host.otis_tools.adaptive_hybrid_run",
        "analyzer_tool": "host.otis_tools.adaptive_hybrid_analyze",
        "serial_device": serial_device,
        "activation_device_selection": FRESH_SERIAL_AUTO_DETECT,
        "baud": EXPECTED_BAUD,
        **bench_attempt.as_dict()["device_identity"],
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
        "reports/adaptive_hybrid_hybrid_firmware_entry_v1.json",
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
        "reports/adaptive_hybrid_hybrid_firmware_entry_v1.json",
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
    _validated_current_reproduction: _ValidatedCurrentReproduction | None = None,
) -> dict[str, Any]:
    programme = ADAPTIVE_HYBRID_PROGRAMME
    run_dir = run_dir.resolve()
    if output_path.resolve() != (run_dir / RUN_MANIFEST_PATH).resolve():
        raise ValueError("live manifest must be run-local run_manifest.json")
    activation, bundle, proposal = validate_frozen_activation(
        activation_path, bundle_path=bundle_path, proposal_path=proposal_path,
        programme=programme,
    )
    _require_current_reproduction_capability(
        _validated_current_reproduction,
        activation=activation,
        bundle=bundle,
        proposal=proposal,
    )
    if not isinstance(serial_device, str) or not serial_device.startswith("/dev/"):
        raise ValueError("run manifest requires the freshly resolved serial device")
    raw_bench_attempt = activation.get("bench_attempt")
    if not isinstance(raw_bench_attempt, dict):
        raise ValueError("activation lacks an exact bench-attempt envelope")
    bench_attempt = validate_bench_attempt_envelope(raw_bench_attempt)
    files = _required_files()
    now = _utc_now()
    section = _run_section(
        programme, activation["authority"], bench_attempt
    )
    actuation_authorized = (
        bench_attempt.limits.setup_application_limit > 0
        or bench_attempt.limits.automatic_application_limit > 0
    )
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
        "bench_attempt": raw_bench_attempt,
        "board": "arduino_nano_rp2040_connect",
        "capture_mode": "pio_wait_cumulative_snapshot_with_independent_gpio_ref",
        "control_mode": bench_attempt.purpose,
        "closed_loop_control": (
            bench_attempt.limits.automatic_application_limit > 0
        ),
        "actionable": actuation_authorized,
        "actuation_authorized": actuation_authorized,
        "qualification_evidence": True,
        "bundle": {**_binding(bundle_path), "bundle_sha256": bundle["bundle_sha256"]},
        "proposal": {**_binding(proposal_path), "proposal_sha256": proposal["proposal_sha256"]},
        "activation": {**_binding(activation_path), "activation_sha256": activation["activation_sha256"]},
        "firmware": bundle["firmware"],
        "authoritative_inputs": bundle["authoritative_inputs"],
        "policy": bundle["policy"],
        "transaction_identities": _transaction_identities(bundle),
        "host": _host_contract(serial_device, bundle, bench_attempt),
        programme.manifest_section: section,
        "domains": [canonical_domain_declaration(name) for name in ("rp2040_monotonic_us32", "rp2040_monotonic_us64", "h1_oscillator_10mhz")],
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
    bundle = validate_frozen_bundle(bundle_path, programme)
    proposal = validate_frozen_proposal(proposal_path, programme)
    activation = _read_object(activation_path, "adaptive-hybrid activation")
    raw_bench_attempt = activation.get("bench_attempt")
    if not isinstance(raw_bench_attempt, dict):
        raise ValueError("run-manifest activation lacks a bench-attempt envelope")
    bench_attempt = validate_bench_attempt_envelope(raw_bench_attempt)
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
        or activation.get("device") != _device_contract(bench_attempt)
        or activation.get("setup") != _setup_contract(programme, bench_attempt)
        or activation.get("authority") != _authority(programme, bench_attempt)
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
    actuation_authorized = (
        bench_attempt.limits.setup_application_limit > 0
        or bench_attempt.limits.automatic_application_limit > 0
    )
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
        "bench_attempt": raw_bench_attempt,
        "board": "arduino_nano_rp2040_connect",
        "capture_mode": "pio_wait_cumulative_snapshot_with_independent_gpio_ref",
        "control_mode": bench_attempt.purpose,
        "closed_loop_control": (
            bench_attempt.limits.automatic_application_limit > 0
        ),
        "actionable": actuation_authorized,
        "actuation_authorized": actuation_authorized,
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
        "host": _host_contract(str(serial_device), bundle, bench_attempt),
        programme.manifest_section: _run_section(
            programme, activation["authority"], bench_attempt
        ),
        "domains": [
            canonical_domain_declaration(name)
            for name in (
                "rp2040_monotonic_us32",
                "rp2040_monotonic_us64",
                "h1_oscillator_10mhz",
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
