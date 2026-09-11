from __future__ import annotations

from hashlib import sha256
from pathlib import Path, PurePosixPath
import argparse
import csv
from datetime import datetime
import json
import os
import re
from typing import Any, Iterable

from .acquisition_frontier import FRONTIER_PATH, FRONTIER_POLICY, FRONTIER_STATE_PATH
from .adaptive_hybrid_bundle import validate_frozen_bundle
from .adaptive_hybrid_contract import (
    ADAPTIVE_HYBRID_PROGRAMME,
    OPERATIONAL_REHEARSAL_SEAL_TYPE,
    programme_from_mapping,
)
from .adaptive_hybrid_proposal import validate_frozen_proposal
from .authoritative_inputs import (
    transaction_identities_from_bundle,
    validate_authoritative_inputs,
)
from .contracts import CONTRACT_SCHEMA_VERSIONS
from .run_loader import (
    CAPTURE_IN_PROGRESS_FLAG,
    COMPLETE_MARKER,
    CURRENT_EVIDENCE_EPOCH,
    RunManifest,
    load_manifest,
)
from .time_domains import canonical_domain_declaration, validate_domain_declarations


EVIDENCE_MANIFEST = "evidence_manifest.json"
EVIDENCE_SCHEMA_VERSION = 1
DIGEST_ALGORITHM = "sha256"
EVIDENCE_INDEX_ID = "otis_evidence_index_v1"
EVIDENCE_INDEX_SCHEMA_VERSION = 1
FIRMWARE_PROVENANCE_STATUS_FIELDS = {
    ("protocol", "contract_id"): "firmware_host_contract_id",
    ("protocol", "contract_sha256"): "firmware_host_contract_sha256",
    ("firmware", "git_commit"): "git_commit",
    ("firmware", "source_state"): "source_state",
    ("firmware", "source_hash"): "source_sha256",
    ("firmware", "config_hash"): "config_sha256",
    ("system", "board"): "board",
    ("system", "board_name"): "board_name",
    ("system", "fqbn"): "fqbn",
    ("system", "arduino_core_provider"): "core_provider",
    ("system", "arduino_core_version"): "core_version",
    ("system", "arduino_core_installed_hash"): "core_installed_sha256",
    ("build", "image_id"): "image_id",
    ("build", "toolchain"): "toolchain",
    ("build", "compiler"): "compiler",
    ("build", "toolchain_installed_hash"): "toolchain_installed_sha256",
    ("build", "arduino_cli_version"): "arduino_cli_version",
    ("build", "invocation_id"): "invocation_id",
}
FIRMWARE_PROVENANCE_SENTINEL = ("build", "provenance_format")
FIRMWARE_PROVENANCE_FORMAT = "otis_fixed_firmware_build_v1"
LOWER_HEX_40 = re.compile(r"^[0-9a-f]{40}$")
LOWER_HEX_64 = re.compile(r"^[0-9a-f]{64}$")

OPERATIONAL_REHEARSAL_TOOL_ID = "adaptive_hybrid_operational_rehearsal_v1"
OPERATIONAL_REHEARSAL_REPORT_KIND = "operational_path_rehearsal"
OPERATIONAL_REHEARSAL_ANALYZER_ID = (
    "adaptive_hybrid_operational_rehearsal_analyze_v1"
)
OPERATIONAL_REHEARSAL_MODE = (
    "adaptive_hybrid_deterministic_process_topology_rehearsal_pty_v1"
)
OPERATIONAL_REHEARSAL_SCENARIO = (
    "adaptive_hybrid_two_transaction_metadata_hold_abort_rotation_v1"
)
OPERATIONAL_REHEARSAL_STAGE = "OTIS_ADAPTIVE_HYBRID_OPERATIONAL_REHEARSAL_PTY"
OPERATIONAL_REHEARSAL_REPORT_NAME = (
    "adaptive_hybrid_operational_rehearsal_v1.json"
)
OPERATIONAL_REHEARSAL_SEAL_PATH = Path(
    "reports/adaptive_hybrid_operational_rehearsal_seal_v1.json"
)
OPERATIONAL_REHEARSAL_PROCESS_EVIDENCE_PATH = Path(
    "reports/adaptive_hybrid_operational_process_evidence_v1.json"
)
OPERATIONAL_REHEARSAL_MONITOR_SAMPLES_PATH = Path(
    "reports/adaptive_hybrid_monitor_samples_v1.jsonl"
)
OPERATIONAL_REHEARSAL_TRANSITION_DIR = Path("segments/transition")
OPERATIONAL_REHEARSAL_TRANSITION_MANIFEST_PATH = (
    OPERATIONAL_REHEARSAL_TRANSITION_DIR / "run_manifest.json"
)
OPERATIONAL_REHEARSAL_TRANSITION_CLOSURE_PATH = (
    OPERATIONAL_REHEARSAL_TRANSITION_DIR
    / "reports/capture_segment_closure_v1.json"
)
OPERATIONAL_REHEARSAL_TRANSITION_CAPTURE_STATE_PATH = (
    OPERATIONAL_REHEARSAL_TRANSITION_DIR / "reports/capture_device_state.json"
)
OPERATIONAL_REHEARSAL_TRANSITION_RAW_PATH = (
    OPERATIONAL_REHEARSAL_TRANSITION_DIR / "raw/serial.log"
)
OPERATIONAL_REHEARSAL_TRANSITION_HEALTH_PATH = (
    OPERATIONAL_REHEARSAL_TRANSITION_DIR / "csv/health.csv"
)
OPERATIONAL_REHEARSAL_COMPLETION_TYPE = "adaptive_hybrid_operational_rehearsal"
POST_SNAPSHOT_ARTIFACTS = frozenset(
    {
        "reports/adaptive_hybrid_physical_seal_v1.json",
        OPERATIONAL_REHEARSAL_SEAL_PATH.as_posix(),
    }
)
OPERATIONAL_REHEARSAL_SEAL_FIELDS = frozenset(
    {
        "schema_version",
        "seal_type",
        "tool",
        "tool_sha256",
        "created_utc",
        "run_id",
        "report_kind",
        "programme_id",
        "run_identity",
        "image_identity",
        "build_identity",
        "bundle_sha256",
        "policy_sha256",
        "status",
        "primary_decision",
        "checks",
        "csv_validation",
        "maintenance_replay",
        "shared_current_analyzer_consumers",
        "evidence_snapshot",
        "source_sha256",
        "process_evidence_sha256",
        "D10_diagnostic",
        "D10_semantics",
        "claim_boundary",
        "seal_sha256",
    }
)
OPERATIONAL_REHEARSAL_CHECKS = frozenset(
    {
        "private_nonphysical_manifest_exact",
        "process_command_transcript_matches_raw",
        "supervisor_commands_match_capture_prefix",
        "actual_capture_process_bound_to_closure",
        "setup_command_bound_to_retained_authority",
        "two_arm_envelopes_bound_to_supervisor_events",
        "progressive_evidence_phases_exact",
        "periodic_lease_and_snapshot_boundaries",
        "stale_command_timeout_rejected",
        "first_dependent_checkpoint_before_second_arm",
        "setup_first_consumer_exact",
        "metadata_hold_requalified_without_actuation",
        "two_transactions_replayed",
        "shared_current_analyzer_consumers_exact",
        "normal_fifo_revoked_after_obstruction",
        "priority_abort_preceded_source_close",
        "same_owner_rotation_then_physical_close",
        "read_only_monitor_observed_lifecycle",
        "supervisor_terminal_is_operator_abort",
        "host_events_durable",
    }
)


class EvidenceError(ValueError):
    pass


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value


def _canonical_sha256(value: object) -> str:
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def _explicit_utc(value: object) -> bool:
    if not isinstance(value, str) or not value.endswith("Z"):
        return False
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is not None
    except ValueError:
        return False


def _digest_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _binding(path: Path) -> dict[str, Any]:
    source = path.resolve()
    if not source.is_file():
        raise ValueError(f"bound artifact is unavailable: {source}")
    return {
        "path": str(source),
        "sha256": _digest_file(source),
        "size_bytes": source.stat().st_size,
    }


def _binding_exact(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    source = Path(str(value.get("path", ""))).resolve()
    return (
        source.is_file()
        and value.get("path") == str(source)
        and value.get("size_bytes") == source.stat().st_size
        and value.get("sha256", value.get("file_sha256"))
        == _digest_file(source)
    )


def _package_files(path: Path) -> Iterable[tuple[str, Path]]:
    if path.is_file():
        yield path.name, path
        return
    if not path.is_dir():
        raise ValueError(f"evidence package does not exist: {path}")
    for candidate in sorted(path.rglob("*")):
        if candidate.is_symlink():
            raise ValueError(f"evidence package contains a symlink: {candidate}")
        if candidate.is_file():
            yield candidate.relative_to(path).as_posix(), candidate


def package_identity(path: Path) -> dict[str, Any]:
    """Return a stable identity for one file or a recursively hashed tree."""

    requested = path.expanduser()
    if requested.is_symlink():
        raise ValueError(f"evidence package may not be a symlink: {requested}")
    source = requested.resolve()
    entries: list[dict[str, Any]] = []
    tree_digest = sha256()
    total_bytes = 0
    for relative_path, candidate in _package_files(source):
        size = candidate.stat().st_size
        entry = {
            "relative_path": relative_path,
            "size_bytes": size,
            "sha256": _digest_file(candidate),
        }
        entries.append(entry)
        encoded = json.dumps(
            entry, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        tree_digest.update(len(encoded).to_bytes(8, "big"))
        tree_digest.update(encoded)
        total_bytes += size
    if source.is_dir() and not entries:
        tree_digest.update(b"OTIS_EMPTY_EVIDENCE_DIRECTORY_V1")
    return {
        "content_sha256": tree_digest.hexdigest(),
        "file_count": len(entries),
        "total_bytes": total_bytes,
        "files": entries,
    }


def _operational_rehearsal_files() -> list[dict[str, Any]]:
    return [
        {
            "path": "csv/external_events.csv",
            "contract": "raw_events_v1",
            "record_type": "EVT",
            "optional": True,
        },
        {
            "path": "csv/reference_events.csv",
            "contract": "raw_events_v1",
            "record_type": "REF",
            "optional": True,
        },
        {"path": "csv/count_observations.csv", "contract": "count_observations_v1", "optional": True},
        {"path": "csv/pps_snapshots.csv", "contract": "pps_snapshots_v1", "optional": True},
        {"path": "csv/accepted_pps_spans_v1.csv", "contract": "accepted_pps_spans_v1", "optional": True},
        {"path": "csv/relative_phase_observations_v2.csv", "contract": "relative_phase_observations_v2", "optional": True},
        {"path": "csv/phase_estimator_outputs_v2.csv", "contract": "phase_estimator_outputs_v2", "optional": True},
        {"path": "csv/health.csv", "contract": "health_v1"},
        {"path": "csv/dac_steps.csv", "contract": "dac_steps_v1", "optional": True},
        {"path": "csv/estimates_v3.csv", "contract": "estimates_v3", "optional": True},
        {"path": "csv/control_previews_v1.csv", "contract": "control_previews_v1", "optional": True},
        {"path": "csv/active_transactions_v3.csv", "contract": "active_transactions_v3"},
        {"path": "csv/active_hybrid_decisions_v3.csv", "contract": "active_hybrid_decisions_v3"},
        {"path": "csv/active_hybrid_maintenance_v2.csv", "contract": "active_hybrid_maintenance_v2"},
    ]


def _operational_rehearsal_channels() -> list[dict[str, Any]]:
    return [
        {
            "channel_id": 0,
            "pin": "D10",
            "role": "external_event",
            "record_type": "EVT",
            "authority": "evidence_only",
            "control_authority": False,
            "terminal_authority": False,
        },
        {
            "channel_id": 1,
            "pin": "D14",
            "role": "authoritative_pps_reference",
            "record_type": "REF",
        },
        {
            "channel_id": 2,
            "pin": "D8",
            "role": "oscillator_count",
            "record_type": "CNT",
        },
        {
            "channel_id": 3,
            "pin": "D6",
            "role": "forwarded_D9_monitor_diagnostic_only",
            "record_type": "MNS",
            "control_authority": False,
            "terminal_authority": False,
        },
    ]


def _operational_rehearsal_artifacts() -> list[str]:
    return [
        "raw/serial.log",
        "reports/capture_device_state.json",
        "reports/adaptive_hybrid_supervisor_state.json",
        "reports/adaptive_hybrid_supervisor_events.jsonl",
        "reports/adaptive_hybrid_session_v1.json",
        "reports/adaptive_hybrid_supervisor_ready_v1.json",
        "reports/adaptive_hybrid_monitor_state_v1.json",
        "reports/capture_segment_closure_v1.json",
        OPERATIONAL_REHEARSAL_PROCESS_EVIDENCE_PATH.as_posix(),
        OPERATIONAL_REHEARSAL_MONITOR_SAMPLES_PATH.as_posix(),
        FRONTIER_PATH,
        FRONTIER_STATE_PATH,
        OPERATIONAL_REHEARSAL_TRANSITION_MANIFEST_PATH.as_posix(),
        OPERATIONAL_REHEARSAL_TRANSITION_CLOSURE_PATH.as_posix(),
        OPERATIONAL_REHEARSAL_TRANSITION_CAPTURE_STATE_PATH.as_posix(),
        OPERATIONAL_REHEARSAL_TRANSITION_RAW_PATH.as_posix(),
        OPERATIONAL_REHEARSAL_TRANSITION_HEALTH_PATH.as_posix(),
    ]


def _canonical_pty_path(value: object) -> bool:
    if not isinstance(value, str):
        return False
    canonical = os.path.realpath(value)
    return value == canonical and bool(
        re.fullmatch(r"/dev/pts/[0-9]+", canonical)
        or re.fullmatch(r"/dev/ttys[0-9]+", canonical)
    )


def _validate_operational_rehearsal_manifest(
    path: Path,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    """Validate the private no-authority manifest without importing its runner."""

    manifest_path = path.resolve()
    value = _read_object(manifest_path, "rehearsal run manifest")
    programme = programme_from_mapping(value)
    bundle_binding = value.get("bundle")
    proposal_binding = value.get("proposal")
    if not isinstance(bundle_binding, dict) or not isinstance(proposal_binding, dict):
        raise ValueError("rehearsal manifest bundle/proposal bindings are malformed")
    bundle_path = Path(str(bundle_binding.get("path", ""))).resolve()
    proposal_path = Path(str(proposal_binding.get("path", ""))).resolve()
    bundle = validate_frozen_bundle(bundle_path, programme)
    proposal = validate_frozen_proposal(proposal_path, programme)
    files = _operational_rehearsal_files()
    contracts = {
        entry["contract"]: CONTRACT_SCHEMA_VERSIONS[entry["contract"]]
        for entry in files
    }
    frozen_inputs = validate_authoritative_inputs(bundle["authoritative_inputs"])
    acceptance_path = "data_contracts/reference_acceptance_policy_v1.json"
    expected_reference_acceptance = {
        "path": acceptance_path,
        "policy_id": frozen_inputs.document(acceptance_path
        )["policy_id"],
        "policy_sha256": frozen_inputs.binding(acceptance_path
        )["sha256"],
    }
    artifacts = _operational_rehearsal_artifacts()
    host = value.get("host")
    section = value.get(programme.manifest_section)
    if not isinstance(host, dict) or not isinstance(section, dict):
        raise ValueError("rehearsal manifest host/programme section is malformed")
    expected_host = {
        "version": OPERATIONAL_REHEARSAL_TOOL_ID,
        "source_revision": str(bundle["firmware"]["source_revision"]),
        "serial_device": host.get("serial_device"),
        "baud": 115200,
        "sole_serial_owner": True,
        "serial_owner_count": 1,
        "tool_bindings": bundle["host_tools"],
        "fifos": {
            "normal_command": "control/normal_commands.fifo",
            "emergency_abort": "control/emergency_abort.fifo",
            "host_abort": "control/host_abort.fifo",
        },
    }
    expected_section = {
        "profile_id": programme.profile_id,
        "run_identity": programme.runtime_run_identity,
        "setup": {"code": programme.setup_code, "applications": 1},
        "automatic_control": {
            "maximum_total_applications": programme.maximum_physical_applications,
            "maximum_step_codes": programme.maximum_step_codes,
            "maximum_cumulative_movement_codes": programme.maximum_cumulative_movement_codes,
            "minimum_applied_cadence_s": programme.minimum_applied_cadence_s,
            "minimum_code": programme.minimum_code,
            "maximum_code": programme.maximum_code,
            "automatic_retry": False,
            "automatic_restore": False,
        },
        "qualification": {
            "qualified_duration_s": programme.qualified_duration_s,
            "qualified_endpoint_contract": "qualified_D14_D8_aperture_count_v2",
            "qualified_d14_aperture_count": programme.qualified_d14_aperture_count,
            "correction_response_reserve_d14_apertures": programme.correction_response_reserve_d14_apertures,
            "absolute_wall_clock_limit_s": programme.absolute_wall_limit_s,
            "no_extension": True,
        },
        "D10": {
            "role": "optional_external_event_evidence",
            "enters_D14_D8_validity_control_or_terminal": False,
        },
    }
    expected_top_level = {
        "schema_version", "template", "run_id", "created_utc", "started_at_utc",
        "evidence_epoch", "stage", "mode", "scenario", "programme_id",
        "run_identity", "image_identity", "board", "capture_mode",
        "qualification_evidence", "physical_actions_performed", "actionable",
        "actuation_authorized", "authority_effective", "closed_loop_control",
        "bundle", "proposal", "activation", "firmware", "authoritative_inputs",
        "policy", "host", programme.manifest_section, "domains", "channels",
        "contracts", "files", "expected_artifacts", "evidence_artifacts",
        "acquisition_frontier", "reference_acceptance", "transaction_identities",
        "manifest_sha256",
    }
    unsigned = {key: item for key, item in value.items() if key != "manifest_sha256"}
    expected_bundle_binding = {
        **_binding(bundle_path),
        "bundle_sha256": bundle["bundle_sha256"],
    }
    expected_proposal_binding = {
        **_binding(proposal_path),
        "proposal_sha256": proposal["proposal_sha256"],
    }
    exact = (
        set(value) == expected_top_level
        and manifest_path == manifest_path.parent / "run_manifest.json"
        and value.get("run_id") == manifest_path.parent.name
        and _explicit_utc(value.get("created_utc"))
        and _explicit_utc(value.get("started_at_utc"))
        and value.get("manifest_sha256") == _canonical_sha256(unsigned)
        and value.get("schema_version") == 1
        and value.get("template") is False
        and value.get("evidence_epoch") == CURRENT_EVIDENCE_EPOCH
        and value.get("stage") == OPERATIONAL_REHEARSAL_STAGE
        and value.get("mode") == OPERATIONAL_REHEARSAL_MODE
        and value.get("scenario") == OPERATIONAL_REHEARSAL_SCENARIO
        and value.get("programme_id") == programme.programme_id
        and value.get("image_identity") == programme.profile_id
        and value.get("run_identity") == programme.runtime_run_identity
        and value.get("qualification_evidence") is False
        and value.get("physical_actions_performed") == 0
        and value.get("actionable") is False
        and value.get("actuation_authorized") is False
        and value.get("authority_effective") is False
        and value.get("closed_loop_control") is False
        and value.get("board") == "deterministic_pty_no_physical_hardware"
        and value.get("capture_mode") == "real_capture_device_process_over_pty"
        and value.get("acquisition_frontier") == FRONTIER_POLICY
        and value.get("reference_acceptance") == expected_reference_acceptance
        and value.get("transaction_identities") == transaction_identities_from_bundle(bundle)
        and _canonical_pty_path(host.get("serial_device"))
        and host == expected_host
        and bundle_binding == expected_bundle_binding
        and proposal_binding == expected_proposal_binding
        and value.get("activation")
        == {"activation_sha256": "0" * 64, "status": "rehearsal_no_physical_authority"}
        and value.get("firmware") == bundle.get("firmware")
        and value.get("authoritative_inputs") == bundle.get("authoritative_inputs")
        and value.get("policy") == bundle.get("policy")
        and proposal.get("exact_bundle", {}).get("bundle_sha256") == bundle.get("bundle_sha256")
        and section == expected_section
        and value.get("domains")
        == [
            canonical_domain_declaration("rp2040_monotonic_us32"),
            canonical_domain_declaration("rp2040_monotonic_us64"),
            canonical_domain_declaration("h1_oscillator_10mhz"),
        ]
        and value.get("channels") == _operational_rehearsal_channels()
        and value.get("files") == files
        and value.get("contracts") == contracts
        and value.get("expected_artifacts") == artifacts
        and value.get("evidence_artifacts") == artifacts
    )
    if not exact:
        raise ValueError("rehearsal manifest identity or nonphysical boundary differs")
    if not _binding_exact(bundle_binding) or not _binding_exact(proposal_binding):
        raise ValueError("rehearsal manifest bundle/proposal bytes differ")
    tool_bindings = bundle.get("host_tools")
    if not isinstance(tool_bindings, dict) or not all(
        _binding_exact(item) for item in tool_bindings.values()
    ):
        raise ValueError("rehearsal manifest current host-tool closure differs")
    if not frozen_inputs.matches(value.get("authoritative_inputs")):
        raise ValueError("rehearsal manifest authoritative inputs differ from bundle")
    domain_errors = validate_domain_declarations(value.get("domains"), require_complete=True)
    if domain_errors:
        raise ValueError("rehearsal manifest time domains differ: " + "; ".join(domain_errors))
    return value, bundle, proposal


def _safe_relative_path(value: object) -> str:
    if not isinstance(value, str) or not value:
        raise EvidenceError("artifact path must be a non-empty string")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or value != path.as_posix():
        raise EvidenceError(f"artifact path is not a normalized run-relative path: {value!r}")
    return value


def _artifact_path(run_dir: Path, rel_path: str) -> Path:
    path = run_dir / rel_path
    current = run_dir
    for part in PurePosixPath(rel_path).parts:
        current = current / part
        if current.is_symlink():
            raise EvidenceError(f"artifact path traverses a symbolic link: {rel_path}")
    return path


def _snapshot_payload(snapshot: dict) -> dict:
    payload = {
        "schema_version": snapshot["schema_version"],
        "run_id": snapshot["run_id"],
        "run_state": snapshot["run_state"],
        "digest_algorithm": snapshot["digest_algorithm"],
        "artifacts": snapshot["artifacts"],
    }
    if "firmware_build_provenance" in snapshot:
        payload["firmware_build_provenance"] = snapshot[
            "firmware_build_provenance"
        ]
    return payload


def _snapshot_digest(snapshot: dict) -> str:
    canonical = json.dumps(
        _snapshot_payload(snapshot),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(canonical).hexdigest()


def _artifact_sources(run_dir: Path, manifest) -> dict[str, dict[str, object]]:
    sources: dict[str, dict[str, object]] = {
        manifest.path.relative_to(run_dir).as_posix(): {"role": "run_manifest"}
    }

    raw_dir = run_dir / "raw"
    if raw_dir.is_dir():
        for path in sorted(raw_dir.rglob("*")):
            if path.is_file():
                sources[path.relative_to(run_dir).as_posix()] = {"role": "raw_evidence"}
    for superseded_name in ("serial_raw.log", "raw_serial.log"):
        if _artifact_path(run_dir, superseded_name).is_file():
            raise EvidenceError(
                f"superseded root evidence file {superseded_name!r} is unsupported; "
                "use the package's recorded Git revision or an archival checkout"
            )

    for entry in manifest.files:
        rel_path = _safe_relative_path(entry.get("path"))
        path = _artifact_path(run_dir, rel_path)
        if not path.is_file():
            if entry.get("optional"):
                continue
            raise EvidenceError(f"required declared artifact is missing: {rel_path}")
        metadata: dict[str, object] = {"role": "declared_artifact"}
        if entry.get("contract"):
            metadata["contract"] = str(entry["contract"])
        sources[rel_path] = metadata

    evidence_artifacts = manifest.data.get("evidence_artifacts", [])
    if not isinstance(evidence_artifacts, list):
        raise EvidenceError("manifest evidence_artifacts must be a list")
    for entry in evidence_artifacts:
        rel_path = _safe_relative_path(entry)
        path = _artifact_path(run_dir, rel_path)
        if not path.is_file():
            raise EvidenceError(
                f"required declared evidence artifact is missing: {rel_path}"
            )
        sources[rel_path] = {"role": "declared_artifact"}

    completion = _artifact_path(run_dir, COMPLETE_MARKER)
    if completion.is_file():
        sources.setdefault(COMPLETE_MARKER, {"role": "completion_marker"})
    for root_name in ("reports", "carrier"):
        root = run_dir / root_name
        if root.is_symlink():
            raise EvidenceError(
                f"retained evidence tree traverses a symbolic link: {root_name}"
            )
        if not root.is_dir():
            continue
        for path in sorted(root.rglob("*")):
            relative = path.relative_to(run_dir).as_posix()
            if path.is_symlink():
                raise EvidenceError(
                    f"retained evidence path traverses a symbolic link: {relative}"
                )
            if path.is_file() and relative not in POST_SNAPSHOT_ARTIFACTS:
                sources.setdefault(relative, {"role": "retained_evidence"})
    return sources


def _requires_generated_firmware_provenance(manifest) -> bool:
    firmware = manifest.data.get("firmware", {})
    return (
        isinstance(firmware, dict)
        and firmware.get("build_provenance_required") is True
    )


def _firmware_build_provenance(run_dir: Path, manifest) -> dict[str, str] | None:
    banners: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    for entry in manifest.files:
        if entry.get("contract") != "health_v1":
            continue
        current = None
        rel_path = _safe_relative_path(entry.get("path"))
        path = _artifact_path(run_dir, rel_path)
        if not path.is_file():
            if entry.get("optional"):
                continue
            raise EvidenceError(
                f"cannot extract firmware provenance from missing {rel_path}"
            )
        try:
            with path.open("r", newline="", encoding="utf-8") as handle:
                reader = csv.DictReader(handle)
                for row in reader:
                    field = (row.get("component", ""), row.get("status_key", ""))
                    if field == FIRMWARE_PROVENANCE_SENTINEL:
                        value = row.get("status_value", "")
                        if value != FIRMWARE_PROVENANCE_FORMAT:
                            raise EvidenceError(
                                "unsupported emitted firmware provenance format: "
                                f"{value!r}"
                            )
                        if current is not None:
                            banners.append(current)
                        current = {"provenance_format": value}
                        continue
                    if current is None:
                        continue
                    output_key = FIRMWARE_PROVENANCE_STATUS_FIELDS.get(
                        field
                    )
                    if output_key is None:
                        continue
                    value = row.get("status_value", "")
                    previous = current.get(output_key)
                    if previous is not None and previous != value:
                        raise EvidenceError(
                            "conflicting emitted firmware provenance for "
                            f"{output_key}: {previous!r} != {value!r}"
                        )
                    current[output_key] = value
        except (OSError, csv.Error) as exc:
            raise EvidenceError(
                f"cannot extract firmware provenance from {rel_path}: {exc}"
            ) from exc
        if current is not None:
            banners.append(current)
        current = None
    if not banners:
        if _requires_generated_firmware_provenance(manifest):
            raise EvidenceError(
                "complete generated firmware build provenance is required "
                "but its sentinel banner is missing"
            )
        return None
    required = {
        "provenance_format",
        *FIRMWARE_PROVENANCE_STATUS_FIELDS.values(),
    }
    normalized: list[dict[str, str]] = []
    for index, values in enumerate(banners, start=1):
        missing = sorted(required - set(values))
        if missing:
            raise EvidenceError(
                f"emitted firmware build provenance banner {index} is "
                "incomplete; missing " + ", ".join(missing)
            )
        if not LOWER_HEX_40.fullmatch(values["git_commit"]):
            raise EvidenceError(
                "emitted firmware git_commit is not exact lowercase Git SHA-1"
            )
        for field in (
            "source_sha256",
            "config_sha256",
            "core_installed_sha256",
            "toolchain_installed_sha256",
            "invocation_id",
            "firmware_host_contract_sha256",
        ):
            if not LOWER_HEX_64.fullmatch(values[field]):
                raise EvidenceError(
                    f"emitted firmware {field} is not lowercase SHA-256"
                )
        if values["source_state"] not in {"clean", "dirty"}:
            raise EvidenceError(
                "emitted firmware source_state must be clean or dirty"
            )
        for field in required - {
            "git_commit",
            "config_sha256",
            "invocation_id",
            "source_sha256",
            "source_state",
            "firmware_host_contract_sha256",
        }:
            if not values[field]:
                raise EvidenceError(
                    f"emitted firmware {field} must be non-empty"
                )
        normalized.append(dict(sorted(values.items())))
    first = normalized[0]
    for index, values in enumerate(normalized[1:], start=2):
        if values != first:
            raise EvidenceError(
                f"conflicting emitted firmware provenance in banner {index}"
            )
    return first


def create_evidence_snapshot(
    run_dir: Path,
    allow_incomplete: bool = False,
    *,
    manifest: RunManifest | None = None,
) -> Path:
    run_dir = run_dir.resolve()
    if (run_dir / CAPTURE_IN_PROGRESS_FLAG).exists():
        raise EvidenceError("capture is in progress; refusing to snapshot mutable evidence")
    if not allow_incomplete and not (run_dir / COMPLETE_MARKER).exists():
        raise EvidenceError(
            f"{COMPLETE_MARKER} marker is missing; pass --allow-incomplete "
            "only for an intentional partial-run snapshot"
        )

    destination = run_dir / EVIDENCE_MANIFEST
    if destination.exists():
        raise FileExistsError(f"evidence snapshot already exists: {destination}")
    premature = sorted(
        relative
        for relative in POST_SNAPSHOT_ARTIFACTS
        if (run_dir / relative).exists()
    )
    if premature:
        raise EvidenceError(
            "post-snapshot analyzer artifact already exists: "
            + ", ".join(premature)
        )

    selected_manifest = manifest or load_manifest(run_dir)
    if (
        selected_manifest.root.resolve() != run_dir
        or selected_manifest.path.resolve() != run_dir / "run_manifest.json"
    ):
        raise EvidenceError("evidence snapshot manifest is not bound to the run directory")
    if selected_manifest.is_template:
        raise EvidenceError("template directories cannot be sealed as run evidence")
    artifacts = []
    for rel_path, metadata in sorted(
        _artifact_sources(run_dir, selected_manifest).items()
    ):
        path = _artifact_path(run_dir, rel_path)
        artifacts.append(
            {
                "path": rel_path,
                **metadata,
                "size_bytes": path.stat().st_size,
                "sha256": _digest_file(path),
            }
        )

    snapshot = {
        "schema_version": EVIDENCE_SCHEMA_VERSION,
        "run_id": selected_manifest.run_id,
        "run_state": "complete" if (run_dir / COMPLETE_MARKER).exists() else "partial",
        "digest_algorithm": DIGEST_ALGORITHM,
        "artifacts": artifacts,
    }
    firmware_build_provenance = _firmware_build_provenance(
        run_dir, selected_manifest
    )
    if firmware_build_provenance is not None:
        snapshot["firmware_build_provenance"] = firmware_build_provenance
    snapshot["snapshot_digest"] = _snapshot_digest(snapshot)
    encoded = (json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    with destination.open("xb") as handle:
        handle.write(encoded)
        handle.flush()
        os.fsync(handle.fileno())
    return destination


def validate_evidence_snapshot(run_dir: Path, manifest) -> tuple[list[str], list[str]]:
    path = run_dir / EVIDENCE_MANIFEST
    if not path.exists():
        if manifest.is_template:
            return [], []
        return [f"{EVIDENCE_MANIFEST}: immutable evidence snapshot is required"], []

    failures: list[str] = []
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return [f"{EVIDENCE_MANIFEST}: cannot read snapshot: {exc}"], []
    if not isinstance(snapshot, dict):
        return [f"{EVIDENCE_MANIFEST}: root must be an object"], []
    if snapshot.get("schema_version") != EVIDENCE_SCHEMA_VERSION:
        failures.append(f"{EVIDENCE_MANIFEST}: unsupported schema_version {snapshot.get('schema_version')!r}")
    if snapshot.get("run_id") != manifest.run_id:
        failures.append(f"{EVIDENCE_MANIFEST}: run_id does not match run manifest")
    if snapshot.get("run_state") not in {"complete", "partial"}:
        failures.append(f"{EVIDENCE_MANIFEST}: run_state must be 'complete' or 'partial'")
    if snapshot.get("digest_algorithm") != DIGEST_ALGORITHM:
        failures.append(f"{EVIDENCE_MANIFEST}: digest_algorithm must be {DIGEST_ALGORITHM!r}")

    artifacts = snapshot.get("artifacts")
    if not isinstance(artifacts, list) or not artifacts:
        return failures + [f"{EVIDENCE_MANIFEST}: artifacts must be a non-empty array"], []
    allowed_snapshot_keys = {
        "schema_version",
        "run_id",
        "run_state",
        "digest_algorithm",
        "artifacts",
        "firmware_build_provenance",
        "snapshot_digest",
    }
    extra_snapshot_keys = set(snapshot) - allowed_snapshot_keys
    if extra_snapshot_keys:
        failures.append(f"{EVIDENCE_MANIFEST}: unsupported fields {sorted(extra_snapshot_keys)}")
    required_snapshot_keys = ("schema_version", "run_id", "run_state", "digest_algorithm", "artifacts")
    if all(key in snapshot for key in required_snapshot_keys):
        if snapshot.get("snapshot_digest") != _snapshot_digest(snapshot):
            failures.append(f"{EVIDENCE_MANIFEST}: snapshot_digest does not match canonical snapshot content")

    try:
        emitted_provenance = _firmware_build_provenance(run_dir, manifest)
    except EvidenceError as exc:
        failures.append(str(exc))
    else:
        sealed_provenance = snapshot.get("firmware_build_provenance")
        if emitted_provenance != sealed_provenance:
            failures.append(
                f"{EVIDENCE_MANIFEST}: firmware_build_provenance does not "
                "match the emitted health evidence"
            )

    seen: set[str] = set()
    listed: set[str] = set()
    previous = ""
    for index, artifact in enumerate(artifacts):
        if not isinstance(artifact, dict):
            failures.append(f"{EVIDENCE_MANIFEST}: artifact {index} must be an object")
            continue
        allowed_artifact_keys = {"path", "role", "contract", "size_bytes", "sha256"}
        required_artifact_keys = {"path", "role", "size_bytes", "sha256"}
        extra_artifact_keys = set(artifact) - allowed_artifact_keys
        missing_artifact_keys = required_artifact_keys - set(artifact)
        if extra_artifact_keys:
            failures.append(
                f"{EVIDENCE_MANIFEST}: artifact {index} has unsupported fields {sorted(extra_artifact_keys)}"
            )
        if missing_artifact_keys:
            failures.append(
                f"{EVIDENCE_MANIFEST}: artifact {index} is missing fields {sorted(missing_artifact_keys)}"
            )
        if artifact.get("role") not in {
            "run_manifest",
            "raw_evidence",
            "declared_artifact",
            "completion_marker",
            "retained_evidence",
        }:
            failures.append(f"{EVIDENCE_MANIFEST}: artifact {index} has an unsupported evidence role")
        if "contract" in artifact and (
            not isinstance(artifact["contract"], str) or not artifact["contract"]
        ):
            failures.append(f"{EVIDENCE_MANIFEST}: artifact {index} contract must be a non-empty string")
        try:
            rel_path = _safe_relative_path(artifact.get("path"))
        except EvidenceError as exc:
            failures.append(f"{EVIDENCE_MANIFEST}: artifact {index}: {exc}")
            continue
        if rel_path == EVIDENCE_MANIFEST:
            failures.append(f"{EVIDENCE_MANIFEST}: snapshot must not include itself")
        if rel_path in seen:
            failures.append(f"{EVIDENCE_MANIFEST}: duplicate artifact path {rel_path!r}")
        if previous and rel_path < previous:
            failures.append(f"{EVIDENCE_MANIFEST}: artifacts are not sorted by path")
        seen.add(rel_path)
        listed.add(rel_path)
        previous = rel_path
        try:
            artifact_path = _artifact_path(run_dir, rel_path)
        except EvidenceError as exc:
            failures.append(str(exc))
            continue
        if not artifact_path.is_file():
            failures.append(f"{rel_path}: snapshotted artifact is missing or is not a regular file")
            continue
        size = artifact_path.stat().st_size
        if not isinstance(artifact.get("size_bytes"), int) or artifact["size_bytes"] < 0:
            failures.append(f"{rel_path}: snapshot size_bytes is malformed")
        elif artifact["size_bytes"] != size:
            failures.append(f"{rel_path}: size differs from evidence snapshot")
        expected_digest = artifact.get("sha256")
        if (
            not isinstance(expected_digest, str)
            or len(expected_digest) != 64
            or any(character not in "0123456789abcdef" for character in expected_digest)
        ):
            failures.append(f"{rel_path}: snapshot SHA-256 is malformed")
        elif _digest_file(artifact_path) != expected_digest:
            failures.append(f"{rel_path}: SHA-256 differs from evidence snapshot")

    try:
        required = _artifact_sources(run_dir, manifest)
    except EvidenceError as exc:
        failures.append(str(exc))
    else:
        required_paths = set(required)
        for rel_path in sorted(required_paths - listed):
            failures.append(f"{rel_path}: evidence-bearing artifact is not covered by {EVIDENCE_MANIFEST}")
        for rel_path in sorted(listed - required_paths):
            failures.append(f"{rel_path}: snapshotted artifact is outside the defined evidence scope")
        artifact_by_path = {
            artifact.get("path"): artifact
            for artifact in artifacts
            if isinstance(artifact, dict) and isinstance(artifact.get("path"), str)
        }
        for rel_path in sorted(required_paths & listed):
            artifact = artifact_by_path.get(rel_path, {})
            expected = required[rel_path]
            if artifact.get("role") != expected["role"]:
                failures.append(f"{rel_path}: evidence role does not match snapshot scope")
            if artifact.get("contract") != expected.get("contract"):
                failures.append(f"{rel_path}: evidence contract does not match run manifest")
    return failures, []


def validate_operational_rehearsal_package(
    location: Path,
    *,
    source_revision: str,
    build_identity: str,
    image_identity: str,
    result_or_failure_reason: str,
    analyzer_identity: str,
) -> dict[str, str]:
    """Independently validate one immutable successful rehearsal package."""

    requested = location.expanduser()
    run_dir = requested.resolve()
    if requested.is_symlink() or not run_dir.is_dir():
        raise ValueError("successful rehearsal requires a non-symlink package directory")
    identity_before = package_identity(requested)
    required = {
        "manifest": run_dir / "run_manifest.json",
        "completion": run_dir / COMPLETE_MARKER,
        "snapshot": run_dir / EVIDENCE_MANIFEST,
        "seal": run_dir / OPERATIONAL_REHEARSAL_SEAL_PATH,
        "process evidence": run_dir / OPERATIONAL_REHEARSAL_PROCESS_EVIDENCE_PATH,
        "transition manifest": run_dir / OPERATIONAL_REHEARSAL_TRANSITION_MANIFEST_PATH,
        "transition closure": run_dir / OPERATIONAL_REHEARSAL_TRANSITION_CLOSURE_PATH,
    }
    missing = sorted(label for label, path in required.items() if not path.is_file())
    if missing or (run_dir / CAPTURE_IN_PROGRESS_FLAG).exists():
        detail = ", ".join(missing) if missing else "capture is still active"
        raise ValueError(f"successful rehearsal package is incomplete: {detail}")

    manifest_value, bundle, _proposal = _validate_operational_rehearsal_manifest(
        required["manifest"]
    )
    manifest = RunManifest(run_dir, required["manifest"], manifest_value)
    producer_binding = bundle.get("host_tools", {}).get(
        "adaptive_hybrid_operational_rehearsal"
    )
    if (
        source_revision != bundle.get("firmware", {}).get("source_revision")
        or build_identity != bundle.get("firmware", {}).get("build_identity")
        or image_identity != ADAPTIVE_HYBRID_PROGRAMME.profile_id
        or result_or_failure_reason
        != "adaptive-hybrid operational rehearsal passed"
        or not isinstance(producer_binding, dict)
        or not _binding_exact(producer_binding)
        or producer_binding.get("sha256") != analyzer_identity
    ):
        raise ValueError("successful rehearsal registration metadata differs")

    completion = _read_object(required["completion"], "rehearsal completion")
    terminal = completion.get("terminal")
    if (
        set(completion)
        != {
            "schema_version",
            "completion",
            "completed_utc",
            "run_id",
            "terminal",
            "physical_actions_performed",
            "claim_boundary",
        }
        or completion.get("schema_version") != 1
        or completion.get("completion") != OPERATIONAL_REHEARSAL_COMPLETION_TYPE
        or not _explicit_utc(completion.get("completed_utc"))
        or completion.get("run_id") != run_dir.name
        or completion.get("physical_actions_performed") != 0
        or completion.get("claim_boundary")
        != "deterministic_host_operational_path_only"
        or not isinstance(terminal, dict)
        or set(terminal)
        != {
            "result",
            "reason",
            "utc",
            "primary_decision",
            "last_confirmed_code",
        }
        or terminal.get("result") != "aborted"
        or terminal.get("reason") != "independent_host_abort_fifo"
        or terminal.get("primary_decision") != "adaptive_hybrid_operator_abort"
        or terminal.get("last_confirmed_code")
        != ADAPTIVE_HYBRID_PROGRAMME.setup_code
        or not _explicit_utc(terminal.get("utc"))
    ):
        raise ValueError("successful rehearsal completion boundary differs")

    snapshot = _read_object(required["snapshot"], "rehearsal snapshot")
    snapshot_failures, snapshot_warnings = validate_evidence_snapshot(
        run_dir, manifest
    )
    if (
        snapshot_failures
        or snapshot_warnings
        or snapshot.get("run_id") != run_dir.name
        or snapshot.get("run_state") != "complete"
        or snapshot.get("digest_algorithm") != "sha256"
        or not isinstance(snapshot.get("artifacts"), list)
    ):
        detail = "; ".join([*snapshot_failures, *snapshot_warnings])
        raise ValueError(
            "successful rehearsal requires an exact complete snapshot"
            + (f": {detail}" if detail else "")
        )

    seal = _read_object(required["seal"], "rehearsal seal")
    claimed_seal_sha256 = seal.get("seal_sha256")
    unsigned_seal = {
        key: value for key, value in seal.items() if key != "seal_sha256"
    }
    checks = seal.get("checks")
    shared = seal.get("shared_current_analyzer_consumers")
    snapshot_result = seal.get("evidence_snapshot")
    maintenance_replay = seal.get("maintenance_replay")
    expected_identity = {
        "run_id": run_dir.name,
        "report_kind": OPERATIONAL_REHEARSAL_REPORT_KIND,
        "programme_id": ADAPTIVE_HYBRID_PROGRAMME.programme_id,
        "run_identity": ADAPTIVE_HYBRID_PROGRAMME.runtime_run_identity,
        "image_identity": ADAPTIVE_HYBRID_PROGRAMME.profile_id,
        "build_identity": build_identity,
        "bundle_sha256": bundle["bundle_sha256"],
        "policy_sha256": bundle["policy"]["policy_sha256"],
    }
    mismatched_identity = sorted(
        key for key, expected in expected_identity.items() if seal.get(key) != expected
    )
    expected_consumer_scope = {
        "csv_contract_validation": "exercised",
        "D10_optional_event_csv": "fail_local",
        "lifecycle_validation": "exercised",
        "transaction_and_maintenance_replay": "exercised",
        "response_replay": "exercised",
        "transaction_capsule_validation": "exercised",
        "evidence_snapshot_and_source_immutability": "exercised",
        "physical_D14_D8_measurement_replay": "unexercised",
        "physical_terminal_scientific_decision": "unexercised",
        "physical_seal_construction": "unexercised",
    }
    exact_shared_checks = (
        isinstance(shared, dict)
        and isinstance(shared.get("checks"), dict)
        and bool(shared["checks"])
        and all(value is True for value in shared["checks"].values())
    )
    if (
        set(seal) != OPERATIONAL_REHEARSAL_SEAL_FIELDS
        or seal.get("schema_version") != 1
        or seal.get("seal_type") != OPERATIONAL_REHEARSAL_SEAL_TYPE
        or seal.get("tool") != OPERATIONAL_REHEARSAL_ANALYZER_ID
        or seal.get("tool_sha256") != analyzer_identity
        or not _explicit_utc(seal.get("created_utc"))
        or seal.get("status") != "passed"
        or seal.get("primary_decision")
        != "adaptive_hybrid_operational_rehearsal_passed"
        or mismatched_identity
        or not isinstance(claimed_seal_sha256, str)
        or LOWER_HEX_64.fullmatch(claimed_seal_sha256) is None
        or claimed_seal_sha256 != _canonical_sha256(unsigned_seal)
        or not isinstance(checks, dict)
        or set(checks) != OPERATIONAL_REHEARSAL_CHECKS
        or not all(value is True for value in checks.values())
        or not isinstance(shared, dict)
        or shared.get("exact") is not True
        or shared.get("consumer_scope") != expected_consumer_scope
        or not exact_shared_checks
        or not isinstance(maintenance_replay, dict)
        or maintenance_replay.get("exact") is not True
        or not isinstance(snapshot_result, dict)
        or snapshot_result
        != {
            "path": EVIDENCE_MANIFEST,
            "snapshot_digest": snapshot.get("snapshot_digest"),
            "failures": [],
            "warnings": [],
        }
        or seal.get("process_evidence_sha256")
        != _digest_file(required["process evidence"])
        or seal.get("D10_semantics")
        != {
            "manifest_channel": _operational_rehearsal_channels()[0],
            "control_consumer": None,
            "terminal_consumer": None,
            "absence_noise_or_invalidity_fail_local": True,
        }
        or seal.get("claim_boundary")
        != {
            "activation_input_only": True,
            "physical_plant_qualification": False,
            "USB_CDC_or_firmware_execution_proven": False,
            "physical_actions_performed": 0,
        }
    ):
        detail = ", ".join(mismatched_identity)
        raise ValueError(
            "successful rehearsal requires an exact passing seal"
            + (f"; identity differs: {detail}" if detail else "")
        )

    snapshot_sources = {
        str(item["path"]): str(item["sha256"])
        for item in snapshot["artifacts"]
        if isinstance(item, dict) and "path" in item and "sha256" in item
    }
    current_sources = {
        path: _digest_file(run_dir / path) for path in snapshot_sources
    }
    if seal.get("source_sha256") != snapshot_sources or current_sources != snapshot_sources:
        raise ValueError("successful rehearsal sealed source identities differ")
    if package_identity(run_dir) != identity_before:
        raise ValueError("successful rehearsal package changed during validation")
    return {
        "contract": "otis_validated_success_package_v1",
        "evidence_snapshot_sha256": str(snapshot["snapshot_digest"]),
        "seal_path": OPERATIONAL_REHEARSAL_SEAL_PATH.as_posix(),
        "seal_sha256": claimed_seal_sha256,
        "seal_status": "passed",
        "primary_decision": "adaptive_hybrid_operational_rehearsal_passed",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Create an immutable SHA-256 evidence snapshot for an OTIS run.")
    parser.add_argument("run_dir", type=Path)
    parser.add_argument(
        "--allow-incomplete",
        action="store_true",
        help="Snapshot a run without a COMPLETE marker; the partial status remains explicit.",
    )
    args = parser.parse_args()
    try:
        path = create_evidence_snapshot(args.run_dir, args.allow_incomplete)
    except (EvidenceError, FileExistsError, FileNotFoundError, json.JSONDecodeError) as exc:
        raise SystemExit(str(exc)) from exc
    print(path)


if __name__ == "__main__":
    main()
