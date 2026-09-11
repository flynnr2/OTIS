"""Content-addressed index for OTIS raw evidence stored outside Git.

The index records package identity and lifecycle metadata. It deliberately has
no delete operation: future raw-package deletion requires a separate reviewed
operator-authorized procedure after OTIS reaches a declared mature milestone.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
from hashlib import sha256
import json
from math import isfinite
import os
from pathlib import Path
import re
import subprocess
import tempfile
from typing import Any

from . import evidence as evidence_module
from .evidence import (
    EVIDENCE_INDEX_ID,
    EVIDENCE_INDEX_SCHEMA_VERSION,
    package_identity,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_INDEX = (
    Path.home() / ".local" / "share" / "otis" / "evidence_index_v1.json"
)
INDEX_ID = EVIDENCE_INDEX_ID
SCHEMA_VERSION = EVIDENCE_INDEX_SCHEMA_VERSION
ATTEMPT_CLASSIFICATIONS = {
    "successful_rehearsal",
    "failed_rehearsal",
    "successful_qualification",
    "failed_qualification",
    "completed_campaign",
    "interrupted_campaign",
    "diagnostic",
    "historical",
}
SUCCESS_CLASSIFICATIONS = frozenset(
    {
        "successful_rehearsal",
        "successful_qualification",
        "completed_campaign",
    }
)
EVIDENCE_INTEGRITY_VALUES = frozenset({"passed", "review_required"})
SCIENTIFIC_OUTCOME_VALUES = frozenset(
    {
        "qualified_complete",
        "bounded_nonpass",
        "interrupted_incomplete",
        "diagnostic_complete",
        "undetermined",
    }
)
CURRENT_SEAL_TYPE = "adaptive_hybrid_physical_seal_v1"
CURRENT_ANALYZER_ID = "adaptive_hybrid_analyze_v1"
CURRENT_SEAL_PATH = Path("reports/adaptive_hybrid_physical_seal_v1.json")
CURRENT_SUPERVISOR_STATE_PATH = Path(
    "reports/adaptive_hybrid_supervisor_state.json"
)
HOST_REVIEW_RESOLUTION_PATH = Path(
    "reports/adaptive_hybrid_hybrid_host_review_resolution_v1.json"
)
ANALYSIS_SUPERSESSION_KIND = "adaptive_hybrid_analysis_supersession_v1"
ANALYSIS_SUPERSESSION_REPORT = Path(
    "adaptive_hybrid_analysis_supersession_v1.json"
)
ANALYSIS_SUPERSESSION_SEAL = Path(
    "adaptive_hybrid_physical_seal_superseding_v1.json"
)
ANALYSIS_SUPERSESSION_JOURNAL = Path("original_finalization_journal.json")
REGISTRATION_SUPERSESSION_KIND = "append_only_package_finalization_v1"
ANALYSIS_SUPERSESSION_TOOL_MODULES = frozenset(
    {
        "acquisition_frontier",
        "active_status_contract",
        "active_status_live_state",
        "adaptive_hybrid_activation",
        "adaptive_hybrid_analyze",
        "adaptive_hybrid_bundle",
        "adaptive_hybrid_contract",
        "adaptive_hybrid_evidence",
        "adaptive_hybrid_policy",
        "adaptive_hybrid_proposal",
        "adaptive_hybrid_replay",
        "adaptive_hybrid_supersede",
        "adaptive_hybrid_transactions",
        "authoritative_inputs",
        "contracts",
        "evidence",
        "evidence_finalization",
        "evidence_index",
        "firmware_binary",
        "firmware_host_contract",
        "raw_measurement_replay",
        "run_loader",
        "run_paths",
        "time_domains",
    }
)
LOWER_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
CURRENT_SEAL_FIELDS = frozenset(
    {
        "schema_version",
        "seal_type",
        "tool",
        "tool_sha256",
        "created_utc",
        "run_id",
        "run_identity",
        "build_identity",
        "image_identity",
        "programme_id",
        "policy_id",
        "status",
        "evidence_integrity",
        "scientific_outcome",
        "primary_decision",
        "terminal_result",
        "terminal_reason",
        "host_review_resolution",
        "checks",
        "csv_validation",
        "exact_lifecycle_records",
        "maintenance_replay",
        "measurement_replay",
        "response_replay",
        "transaction_capsule_sha256",
        "evidence_snapshot",
        "source_sha256",
        "D10_semantics",
        "host_discrepancy_authority",
        "limitations",
        "seal_sha256",
    }
)
CURRENT_PHYSICAL_SEAL_CHECKS = frozenset(
    {
        "manifest_current",
        "csv_contracts_exact",
        "evidence_snapshot_exact",
        "exact_lifecycle_records",
        "transactions_exact",
        "maintenance_replay_exact",
        "D14_D8_measurement_replay_exact",
        "decision_measurement_sources_exact",
        "response_replay_exact",
        "transaction_capsules_exact",
        "D10_optional_event_isolated",
        "inhibited_zero_write_authority_exact",
        "host_review_resolution_exact",
        "supervisor_terminal_exact",
        "scientific_outcome_determined",
    }
)


def campaign_attempt_classification(
    *, evidence_integrity: str, scientific_outcome: str
) -> str:
    """Map an explicit integrity/outcome pair to campaign index stewardship."""

    if (
        not isinstance(evidence_integrity, str)
        or evidence_integrity not in EVIDENCE_INTEGRITY_VALUES
    ):
        raise ValueError("unknown campaign evidence integrity")
    if (
        not isinstance(scientific_outcome, str)
        or scientific_outcome not in SCIENTIFIC_OUTCOME_VALUES
    ):
        raise ValueError("unknown campaign scientific outcome")
    if evidence_integrity == "review_required":
        if scientific_outcome != "undetermined":
            raise ValueError(
                "review-required evidence cannot assert a scientific outcome"
            )
        return "diagnostic"
    if scientific_outcome in {"qualified_complete", "bounded_nonpass"}:
        return "completed_campaign"
    if scientific_outcome == "interrupted_incomplete":
        return "interrupted_campaign"
    if scientific_outcome == "diagnostic_complete":
        return "diagnostic"
    raise ValueError("passed evidence must have a determined scientific outcome")


def _campaign_metadata_matches_classification(
    *,
    attempt_classification: object,
    evidence_integrity: str,
    scientific_outcome: str,
) -> bool:
    if attempt_classification == "successful_qualification":
        return (
            evidence_integrity == "passed"
            and scientific_outcome == "qualified_complete"
        )
    try:
        expected = campaign_attempt_classification(
            evidence_integrity=evidence_integrity,
            scientific_outcome=scientific_outcome,
        )
    except ValueError:
        return False
    return attempt_classification == expected


def _resolved_completion_terminal(
    *,
    location: Path,
    completion: dict[str, Any],
    seal: dict[str, Any],
    original_analyzer_sha256: object,
    analyzer_identity: str,
) -> tuple[dict[str, Any], bool]:
    """Return the original terminal or one exact no-I/O supersession."""

    original_terminal = completion.get("terminal")
    seal_resolution = seal.get("host_review_resolution")
    if isinstance(original_terminal, dict):
        if seal_resolution is not None:
            raise ValueError(
                "successful evidence registration has a contradictory review resolution"
            )
        return original_terminal, False
    if original_terminal is not None or completion.get("orchestration_error") is not None:
        raise ValueError("successful evidence registration completion marker differs")
    if not isinstance(seal_resolution, dict) or set(seal_resolution) != {
        "path",
        "resolution_sha256",
        "source_sha256",
    }:
        raise ValueError("successful evidence registration lacks an exact review resolution")
    if seal_resolution.get("path") != HOST_REVIEW_RESOLUTION_PATH.as_posix():
        raise ValueError("successful evidence registration review resolution path differs")
    resolution = _read_object(
        location / HOST_REVIEW_RESOLUTION_PATH,
        "host-review resolution",
    )
    unsigned = {
        key: value for key, value in resolution.items() if key != "resolution_sha256"
    }
    if (
        resolution.get("schema_version") != 1
        or resolution.get("report_type")
        != "adaptive_hybrid_hybrid_host_review_resolution_v1"
        or resolution.get("resolution")
        != "deterministic_host_endpoint_mismatch_superseded"
        or resolution.get("original_hold_preserved") is not True
        or resolution.get("physical_rerun") is not False
        or resolution.get("device_or_actuator_io") is not False
        or resolution.get("new_authority") is not False
        or resolution.get("absent_artifacts")
        != ["reports/adaptive_hybrid_setup_authority_v1.json"]
        or (location / "reports/adaptive_hybrid_setup_authority_v1.json").exists()
        or resolution.get("resolution_sha256") != _canonical_sha256(unsigned)
        or seal_resolution.get("resolution_sha256")
        != resolution.get("resolution_sha256")
        or seal_resolution.get("source_sha256") != resolution.get("source_sha256")
    ):
        raise ValueError("successful evidence registration review resolution differs")
    original_tools = resolution.get("original_tool_sha256")
    review_tools = resolution.get("review_tool_sha256")
    terminal = resolution.get("terminal")
    if (
        not isinstance(original_tools, dict)
        or original_tools.get("adaptive_hybrid_analyze")
        != original_analyzer_sha256
        or not isinstance(review_tools, dict)
        or review_tools.get("adaptive_hybrid_analyze") != analyzer_identity
        or not isinstance(terminal, dict)
        or terminal.get("result") != "healthy_stop"
        or terminal.get("last_confirmed_code") is not None
    ):
        raise ValueError("successful evidence registration review tool or terminal differs")
    return terminal, True


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_sha256(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
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
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"{label} is unreadable: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must contain a JSON object")
    return value


def source_registration_projection(record: dict[str, Any]) -> dict[str, Any]:
    """Exclude mutable storage and lifecycle stewardship from provenance."""

    fields = (
        "content_sha256",
        "file_count",
        "total_bytes",
        "file_manifest",
        "source_revision",
        "build_identity",
        "image_identity",
        "attempt_classification",
        "result_or_failure_reason",
        "analyzer_identity",
        "package_validation",
    )
    return {key: record[key] for key in fields if key in record}


def _matching_source_location(
    *, source: dict[str, Any], record: dict[str, Any]
) -> tuple[Path, dict[str, Any]]:
    expected = source.get("content_sha256")
    candidates = [source.get("path"), *record.get("storage_locations", [])]
    seen: set[str] = set()
    for raw in candidates:
        if not isinstance(raw, str) or raw in seen:
            continue
        seen.add(raw)
        path = Path(raw).expanduser().resolve()
        if not path.is_dir():
            continue
        identity = package_identity(path)
        if identity.get("content_sha256") == expected:
            return path, identity
    raise ValueError("analysis supersession source package is unavailable")


def validate_completed_diagnostic_journal(
    journal: dict[str, Any],
    *,
    source: dict[str, Any],
    original_seal: dict[str, Any],
    source_manifest: dict[str, Any],
) -> None:
    phase_names = (
        "capture_closed",
        "completion",
        "snapshot",
        "analysis",
        "seal",
        "registration",
    )
    phases = journal.get("phases")
    registration = journal.get("registration")
    if (
        journal.get("contract") != "otis_evidence_finalization_v1"
        or tuple(journal.get("phase_order", ())) != phase_names
        or not _explicit_utc(journal.get("created_utc"))
        or not _explicit_utc(journal.get("updated_utc"))
        or journal.get("expected_content_sha256") != source.get("content_sha256")
        or journal.get("required_seal") != CURRENT_SEAL_PATH.as_posix()
        or not isinstance(journal.get("run_dir"), str)
        or not Path(journal["run_dir"]).is_absolute()
        or journal.get("run_dir") != source.get("path")
        or not isinstance(journal.get("index_path"), str)
        or not Path(journal["index_path"]).is_absolute()
        or not isinstance(phases, dict)
        or set(phases) != set(phase_names)
        or not isinstance(registration, dict)
        or not isinstance(journal.get("secondary_failures"), list)
    ):
        raise ValueError("analysis supersession finalization journal contract differs")
    assert isinstance(phases, dict)
    phase_details: dict[str, dict[str, Any]] = {}
    for name in phase_names:
        phase = phases.get(name)
        if (
            not isinstance(phase, dict)
            or set(phase) != {"completed_utc", "details"}
            or not _explicit_utc(phase.get("completed_utc"))
            or not isinstance(phase.get("details"), dict)
        ):
            raise ValueError(
                "analysis supersession finalization journal phase differs"
            )
        phase_details[name] = phase["details"]
    firmware = source_manifest.get("firmware", {})
    completion = phase_details["completion"]
    terminal = completion.get("terminal")
    analysis = phase_details["analysis"]
    seal = phase_details["seal"]
    capture = phase_details["capture_closed"]
    snapshot = phase_details["snapshot"]
    registered = phase_details["registration"]
    if (
        registration.get("attempt_classification") != "diagnostic"
        or registration.get("analyzer_identity")
        != original_seal.get("tool_sha256")
        or registration.get("source_revision") != firmware.get("source_revision")
        or registration.get("build_identity") != firmware.get("build_identity")
        or registration.get("image_identity") != source_manifest.get("image_identity")
        or registration.get("result_or_failure_reason")
        != "ADAPTIVE_HYBRID offline finalization recovery: operator_review_required"
        or capture.get("capture_exit") != 0
        or capture.get("capture_alive_at_entry") is not True
        or capture.get("automatic_abort_or_teardown") is not False
        or capture.get("host_review_required") is not True
        or not isinstance(terminal, dict)
        or terminal.get("result") != "healthy_stop"
        or terminal.get("reason") != "inhibited_zero_write_complete"
        or terminal.get("last_confirmed_code") is not None
        or completion.get("orchestration_error") != ""
        or Path(str(completion.get("review_resolution", ""))).name
        != HOST_REVIEW_RESOLUTION_PATH.name
        or Path(str(snapshot.get("path", ""))).name != "evidence_manifest.json"
        or analysis.get("status") != "review_required"
        or analysis.get("primary_decision") != "operator_review_required"
        or analysis.get("tool_sha256") != original_seal.get("tool_sha256")
        or analysis.get("exact_lifecycle_records", {}).get("exact") is not True
        or Path(str(seal.get("path", ""))).name != CURRENT_SEAL_PATH.name
        or seal.get("seal_sha256") != original_seal.get("seal_sha256")
        or registered.get("content_sha256") != source.get("content_sha256")
    ):
        raise ValueError("analysis supersession finalization journal binding differs")


def _current_supersession_tool_sha256() -> dict[str, str]:
    module_root = Path(__file__).resolve().parent
    return {
        name: _sha256_file(module_root / f"{name}.py")
        for name in sorted(ANALYSIS_SUPERSESSION_TOOL_MODULES)
    }


def _current_clean_revision() -> dict[str, str]:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain", "--untracked-files=normal"],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    if status:
        raise ValueError("analysis supersession registration requires clean source")
    return {"revision": revision, "source_state": "clean"}


def _maintenance_supersession_exact(
    original: object, corrected: object
) -> bool:
    if not isinstance(original, dict) or not isinstance(corrected, dict):
        return False
    shared_fields = {
        "policy_id",
        "policy_sha256",
        "decision_count",
        "phase_nonzero_decision_count",
        "phase_material_decision_count",
        "unmatched_request_decision_sequences",
        "completed_response_decision_sequences",
        "all_response_checkpoints_passed",
        "comparisons",
    }
    return (
        original.get("exact") is False
        and corrected.get("exact") is True
        and corrected.get("applicability") == "not_applicable"
        and corrected.get("reason")
        == "inhibited_zero_write_frozen_authority_forbids_controller_records"
        and corrected.get("replay_mode")
        == "not_applicable_no_controller_authority"
        and corrected.get("controller_state_authority") == "none"
        and all(original.get(field) == corrected.get(field) for field in shared_fields)
        and corrected.get("decision_count") == 0
        and corrected.get("phase_nonzero_decision_count") == 0
        and corrected.get("phase_material_decision_count") == 0
        and corrected.get("unmatched_request_decision_sequences") == []
        and corrected.get("completed_response_decision_sequences") == []
        and corrected.get("all_response_checkpoints_passed") is True
        and corrected.get("comparisons") == []
    )


def _measurement_supersession_exact(
    original: object, corrected: object
) -> bool:
    if not isinstance(original, dict) or not isinstance(corrected, dict):
        return False
    original_comparisons = original.get("comparisons")
    corrected_comparisons = corrected.get("comparisons")
    if not isinstance(original_comparisons, list) or not isinstance(
        corrected_comparisons, list
    ):
        return False
    selected_count = corrected.get("selected_count")
    if (
        not isinstance(selected_count, int)
        or selected_count <= 0
        or original.get("selected_count") != selected_count
        or len(original_comparisons) != selected_count
        or len(corrected_comparisons) != selected_count
        or corrected.get("calculation_domain")
        != "firmware_ieee754_binary64_then_fixed_12_decimal"
        or original.get("estimate_sequence_exact")
        != corrected.get("estimate_sequence_exact")
        or original.get("selected_nonoverlap")
        != corrected.get("selected_nonoverlap")
        or original.get("D10") != corrected.get("D10")
        or original.get("D14") != corrected.get("D14")
    ):
        return False
    originals = {
        row.get("estimate_id"): row
        for row in original_comparisons
        if isinstance(row, dict) and isinstance(row.get("estimate_id"), str)
    }
    if len(originals) != selected_count:
        return False
    corrected_failures = 0
    original_failures = 0
    for row in corrected_comparisons:
        if not isinstance(row, dict):
            return False
        prior = originals.get(row.get("estimate_id"))
        if not isinstance(prior, dict):
            return False
        if (
            row.get("total_counted_edges") != prior.get("total_counted_edges")
            or row.get("pass") is not True
        ):
            return False
        for field in (
            "absolute_frequency_difference_hz",
            "absolute_error_difference_hz",
        ):
            difference = row.get(field)
            if (
                not isinstance(difference, (int, float))
                or isinstance(difference, bool)
                or not isfinite(difference)
                or difference < 0
                or difference > 5e-13
            ):
                corrected_failures += 1
        original_failures += prior.get("pass") is not True
    return corrected_failures == 0 and original_failures > 0


def _validated_analysis_supersession_artifact(
    location: Path,
    index: dict[str, Any],
    *,
    require_current_tools: bool = False,
) -> dict[str, str]:
    """Validate an offline addendum and its unchanged diagnostic source."""

    report_path = location / ANALYSIS_SUPERSESSION_REPORT
    corrected_path = location / ANALYSIS_SUPERSESSION_SEAL
    report = _read_object(report_path, "analysis supersession report")
    expected_fields = {
        "schema_version",
        "report_type",
        "created_utc",
        "supersession_reason",
        "review_authority",
        "acceptance_criterion_unchanged",
        "actionable",
        "actuation_authorized",
        "physical_rerun",
        "device_or_actuator_io",
        "hardware_interaction",
        "new_control_or_terminal_authority",
        "current_host_source",
        "source_package",
        "original_index_registration",
        "original_finalization_journal",
        "original_seal",
        "corrected_seal",
        "decision_tool_sha256",
        "decision_toolset_sha256",
        "supersession_sha256",
    }
    unsigned = {
        key: value for key, value in report.items() if key != "supersession_sha256"
    }
    if (
        set(report) != expected_fields
        or report.get("schema_version") != 1
        or report.get("report_type") != ANALYSIS_SUPERSESSION_KIND
        or report.get("supersession_reason")
        != (
            "deterministic_offline_consumer_contract_correction:"
            "firmware_binary64_measurement_projection_and_inhibited_zero_write_"
            "maintenance_applicability"
        )
        or report.get("review_authority")
        != "operator_authorized_deterministic_offline_repair"
        or not _explicit_utc(report.get("created_utc"))
        or report.get("acceptance_criterion_unchanged") is not True
        or report.get("actionable") is not False
        or report.get("actuation_authorized") is not False
        or report.get("physical_rerun") is not False
        or report.get("device_or_actuator_io") is not False
        or report.get("hardware_interaction") is not False
        or report.get("new_control_or_terminal_authority") is not False
        or report.get("supersession_sha256") != _canonical_sha256(unsigned)
    ):
        raise ValueError("analysis supersession report contract differs")

    source = report.get("source_package")
    current_host_source = report.get("current_host_source")
    original_index = report.get("original_index_registration")
    original_binding = report.get("original_seal")
    corrected_binding = report.get("corrected_seal")
    journal_binding = report.get("original_finalization_journal")
    tool_hashes = report.get("decision_tool_sha256")
    if not all(
        isinstance(value, dict)
        for value in (
            source,
            current_host_source,
            original_index,
            original_binding,
            corrected_binding,
            journal_binding,
            tool_hashes,
        )
    ):
        raise ValueError("analysis supersession bindings are malformed")
    assert isinstance(source, dict)
    assert isinstance(current_host_source, dict)
    assert isinstance(original_index, dict)
    assert isinstance(original_binding, dict)
    assert isinstance(corrected_binding, dict)
    assert isinstance(journal_binding, dict)
    assert isinstance(tool_hashes, dict)
    if (
        set(source)
        != {
            "path",
            "content_sha256",
            "file_count",
            "total_bytes",
            "firmware_source_revision",
            "source_sha256",
        }
        or set(current_host_source) != {"revision", "source_state"}
        or set(original_index)
        != {
            "index_id",
            "immutable_record_sha256",
            "attempt_classification",
            "analyzer_identity",
        }
        or set(original_binding)
        != {
            "path",
            "file_sha256",
            "seal_sha256",
            "status",
            "primary_decision",
            "tool",
            "tool_sha256",
            "failed_checks",
        }
        or set(corrected_binding)
        != {
            "path",
            "file_sha256",
            "seal_sha256",
            "status",
            "primary_decision",
            "tool",
            "tool_sha256",
        }
        or set(journal_binding)
        != {
            "path",
            "source_path_at_supersession",
            "file_sha256",
            "primary_failure",
            "secondary_failures",
        }
        or set(tool_hashes) != ANALYSIS_SUPERSESSION_TOOL_MODULES
        or any(
            not isinstance(value, str) or not LOWER_HEX_64.fullmatch(value)
            for value in tool_hashes.values()
        )
        or not isinstance(report.get("decision_toolset_sha256"), str)
        or not LOWER_HEX_64.fullmatch(report["decision_toolset_sha256"])
    ):
        raise ValueError("analysis supersession identity fields differ")
    if require_current_tools and (
        tool_hashes != _current_supersession_tool_sha256()
        or current_host_source != _current_clean_revision()
    ):
        raise ValueError("analysis supersession current tool identity differs")
    source_content = source.get("content_sha256")
    source_record = index.get("packages", {}).get(source_content)
    if not isinstance(source_record, dict):
        raise ValueError("analysis supersession source registration is unavailable")
    source_path, source_before = _matching_source_location(
        source=source, record=source_record
    )
    source_manifest = _read_object(source_path / "run_manifest.json", "source manifest")
    from .adaptive_hybrid_activation import validate_frozen_run_manifest
    from .evidence import validate_evidence_snapshot
    from .run_loader import load_manifest

    validated_manifest = validate_frozen_run_manifest(
        source_path / "run_manifest.json"
    )
    if validated_manifest != source_manifest:
        raise ValueError("analysis supersession source manifest differs")
    loaded_manifest = load_manifest(source_path)
    snapshot_failures, snapshot_warnings = validate_evidence_snapshot(
        source_path, loaded_manifest
    )
    if snapshot_failures or snapshot_warnings:
        raise ValueError("analysis supersession source snapshot is not exact")
    source_snapshot_path = source_path / "evidence_manifest.json"
    source_snapshot_sha256 = _sha256_file(source_snapshot_path)
    expected_source_sha256 = {
        str(item["path"]): _sha256_file(source_path / str(item["path"]))
        for item in loaded_manifest.files
        if (source_path / str(item.get("path", ""))).is_file()
    }
    immutable_registration = source_registration_projection(source_record)
    if (
        not isinstance(source_content, str)
        or not LOWER_HEX_64.fullmatch(source_content)
        or source_before.get("content_sha256") != source_content
        or source.get("file_count") != source_before.get("file_count")
        or source.get("total_bytes") != source_before.get("total_bytes")
        or source.get("firmware_source_revision")
        != source_manifest.get("firmware", {}).get("source_revision")
        or not isinstance(current_host_source.get("revision"), str)
        or not re.fullmatch(r"[0-9a-f]{40}", current_host_source["revision"])
        or current_host_source.get("source_state") != "clean"
        or source_record.get("attempt_classification") != "diagnostic"
        or not _standard_index_record_exact(
            source_record,
            content_sha256=source_content,
            identity=source_before,
        )
        or source_record.get("source_revision")
        != source_manifest.get("firmware", {}).get("source_revision")
        or source_record.get("build_identity")
        != source_manifest.get("firmware", {}).get("build_identity")
        or source_record.get("image_identity")
        != source_manifest.get("image_identity")
        or source_record.get("result_or_failure_reason")
        != "ADAPTIVE_HYBRID offline finalization recovery: operator_review_required"
        or original_index.get("index_id") != INDEX_ID
        or original_index.get("immutable_record_sha256")
        != _canonical_sha256(immutable_registration)
        or original_index.get("attempt_classification") != "diagnostic"
        or original_index.get("analyzer_identity")
        != source_record.get("analyzer_identity")
    ):
        raise ValueError("analysis supersession source registration differs")

    original_path = source_path / str(original_binding.get("path", ""))
    original = _read_object(original_path, "original diagnostic seal")
    original_unsigned = {
        key: value for key, value in original.items() if key != "seal_sha256"
    }
    corrected = _read_object(corrected_path, "corrected analyzer seal")
    corrected_unsigned = {
        key: value for key, value in corrected.items() if key != "seal_sha256"
    }
    corrected_checks = corrected.get("checks")
    original_checks = original.get("checks")
    actual_failed_checks = (
        sorted(key for key, value in original_checks.items() if value is not True)
        if isinstance(original_checks, dict)
        else []
    )
    original_snapshot = original.get("evidence_snapshot")
    corrected_snapshot = corrected.get("evidence_snapshot")
    original_d10 = original.get("D10_semantics")
    corrected_d10 = corrected.get("D10_semantics")
    original_discrepancy = original.get("host_discrepancy_authority")
    corrected_discrepancy = corrected.get("host_discrepancy_authority")
    firmware = source_manifest.get("firmware", {})
    policy = source_manifest.get("policy", {})
    if (
        set(original) != CURRENT_SEAL_FIELDS
        or set(corrected) != CURRENT_SEAL_FIELDS
        or original.get("schema_version") != 1
        or corrected.get("schema_version") != 1
        or original.get("seal_type") != CURRENT_SEAL_TYPE
        or corrected.get("seal_type") != CURRENT_SEAL_TYPE
        or original.get("tool") != CURRENT_ANALYZER_ID
        or corrected.get("tool") != CURRENT_ANALYZER_ID
        or not isinstance(original.get("tool_sha256"), str)
        or not LOWER_HEX_64.fullmatch(original["tool_sha256"])
        or not isinstance(corrected.get("tool_sha256"), str)
        or not LOWER_HEX_64.fullmatch(corrected["tool_sha256"])
        or set(original_checks or {}) != CURRENT_PHYSICAL_SEAL_CHECKS
        or set(corrected_checks or {}) != CURRENT_PHYSICAL_SEAL_CHECKS
        or original_binding.get("path") != CURRENT_SEAL_PATH.as_posix()
        or original_binding.get("file_sha256") != _sha256_file(original_path)
        or original_binding.get("seal_sha256") != original.get("seal_sha256")
        or original.get("seal_sha256") != _canonical_sha256(original_unsigned)
        or original.get("status") != "review_required"
        or original.get("primary_decision") != "operator_review_required"
        or original_binding.get("failed_checks")
        != ["D14_D8_measurement_replay_exact", "maintenance_replay_exact"]
        or actual_failed_checks != original_binding.get("failed_checks")
        or original_binding.get("status") != original.get("status")
        or original_binding.get("primary_decision")
        != original.get("primary_decision")
        or original_binding.get("tool") != original.get("tool")
        or original_binding.get("tool_sha256") != original.get("tool_sha256")
        or source_record.get("analyzer_identity") != original.get("tool_sha256")
        or corrected_binding.get("path") != ANALYSIS_SUPERSESSION_SEAL.as_posix()
        or corrected_binding.get("file_sha256") != _sha256_file(corrected_path)
        or corrected_binding.get("seal_sha256") != corrected.get("seal_sha256")
        or corrected.get("seal_sha256") != _canonical_sha256(corrected_unsigned)
        or corrected.get("status") != "passed"
        or corrected.get("primary_decision") != "inhibited_zero_write_complete"
        or corrected.get("terminal_result") != "healthy_stop"
        or corrected.get("terminal_reason") != "inhibited_zero_write_complete"
        or not isinstance(corrected_checks, dict)
        or not corrected_checks
        or not all(value is True for value in corrected_checks.values())
        or corrected_binding.get("tool_sha256") != corrected.get("tool_sha256")
        or corrected_binding.get("status") != corrected.get("status")
        or corrected_binding.get("primary_decision")
        != corrected.get("primary_decision")
        or corrected_binding.get("tool") != corrected.get("tool")
        or tool_hashes.get("adaptive_hybrid_analyze")
        != corrected.get("tool_sha256")
        or report.get("decision_toolset_sha256") != _canonical_sha256(tool_hashes)
        or original.get("host_review_resolution")
        != corrected.get("host_review_resolution")
        or not _maintenance_supersession_exact(
            original.get("maintenance_replay"),
            corrected.get("maintenance_replay"),
        )
        or not _measurement_supersession_exact(
            original.get("measurement_replay"),
            corrected.get("measurement_replay"),
        )
        or original.get("csv_validation") != corrected.get("csv_validation")
        or original.get("exact_lifecycle_records")
        != corrected.get("exact_lifecycle_records")
        or original.get("response_replay") != corrected.get("response_replay")
        or original.get("transaction_capsule_sha256")
        != corrected.get("transaction_capsule_sha256")
        or original.get("limitations") != corrected.get("limitations")
        or original.get("source_sha256") != source.get("source_sha256")
        or corrected.get("source_sha256") != source.get("source_sha256")
        or source.get("source_sha256") != expected_source_sha256
        or original.get("run_id") != source_manifest.get("run_id")
        or corrected.get("run_id") != original.get("run_id")
        or original.get("run_identity") != source_manifest.get("run_identity")
        or corrected.get("run_identity") != original.get("run_identity")
        or original.get("build_identity") != firmware.get("build_identity")
        or corrected.get("build_identity") != original.get("build_identity")
        or original.get("image_identity") != source_manifest.get("image_identity")
        or corrected.get("image_identity") != original.get("image_identity")
        or original.get("programme_id") != source_manifest.get("programme_id")
        or corrected.get("programme_id") != original.get("programme_id")
        or original.get("policy_id") != policy.get("policy_id")
        or corrected.get("policy_id") != original.get("policy_id")
        or not isinstance(original_snapshot, dict)
        or not isinstance(corrected_snapshot, dict)
        or original_snapshot.get("path") != "evidence_manifest.json"
        or corrected_snapshot.get("path") != "evidence_manifest.json"
        or original_snapshot.get("sha256") != source_snapshot_sha256
        or corrected_snapshot.get("sha256") != source_snapshot_sha256
        or original_snapshot.get("failures") != []
        or corrected_snapshot.get("failures") != []
        or original_snapshot.get("warnings") != []
        or corrected_snapshot.get("warnings") != []
        or not isinstance(original_d10, dict)
        or not isinstance(corrected_d10, dict)
        or original_d10 != corrected_d10
        or original_d10.get("pin") != "D10"
        or original_d10.get("authority") != "evidence_only"
        or original_d10.get(
            "absence_noise_invalidity_or_overflow_cannot_change_control_or_terminal"
        )
        is not True
        or not isinstance(original_discrepancy, dict)
        or not isinstance(corrected_discrepancy, dict)
        or original_discrepancy.get("review_required") is not True
        or corrected_discrepancy.get("review_required") is not False
        or any(
            discrepancy.get(field) is not False
            for discrepancy in (original_discrepancy, corrected_discrepancy)
            for field in (
                "new_setup",
                "new_arm",
                "automatic_abort",
                "automatic_teardown",
                "failed_campaign",
            )
        )
        or any(
            discrepancy.get("raw_evidence_preserved") is not True
            for discrepancy in (original_discrepancy, corrected_discrepancy)
        )
    ):
        raise ValueError("analysis supersession seal binding differs")

    completion = _read_object(source_path / "COMPLETE", "source completion marker")
    analyzer_binding = (
        source_manifest.get("host", {})
        .get("tool_bindings", {})
        .get("adaptive_hybrid_analyze", {})
    )
    resolved_terminal, resolved_review = _resolved_completion_terminal(
        location=source_path,
        completion=completion,
        seal=original,
        original_analyzer_sha256=analyzer_binding.get("sha256"),
        analyzer_identity=str(original["tool_sha256"]),
    )
    if (
        resolved_review is not True
        or resolved_terminal.get("result") != corrected.get("terminal_result")
        or resolved_terminal.get("reason") != corrected.get("terminal_reason")
    ):
        raise ValueError("analysis supersession resolved terminal differs")

    if journal_binding.get("path") != ANALYSIS_SUPERSESSION_JOURNAL.as_posix():
        raise ValueError("analysis supersession finalization path differs")
    journal_path = location / ANALYSIS_SUPERSESSION_JOURNAL
    journal = _read_object(journal_path, "source finalization journal")
    retained_run = Path(str(journal.get("run_dir", "")))
    expected_source_journal = (
        retained_run.parent
        / ".otis-finalization"
        / f"{retained_run.name}.json"
    )
    if (
        journal_binding.get("file_sha256") != _sha256_file(journal_path)
        or journal_binding.get("source_path_at_supersession")
        != str(expected_source_journal)
        or journal_binding.get("primary_failure") != journal.get("primary_failure")
        or journal_binding.get("secondary_failures")
        != journal.get("secondary_failures")
        or journal.get("expected_content_sha256") != source_content
        or journal.get("phases", {}).get("registration") is None
    ):
        raise ValueError("analysis supersession finalization binding differs")
    validate_completed_diagnostic_journal(
        journal,
        source=source,
        original_seal=original,
        source_manifest=source_manifest,
    )
    journal_registration = journal.get("registration", {})
    if any(
        source_record.get(field) != journal_registration.get(field)
        for field in (
            "source_revision",
            "build_identity",
            "image_identity",
            "attempt_classification",
            "result_or_failure_reason",
            "analyzer_identity",
        )
    ):
        raise ValueError("analysis supersession source and journal metadata differ")
    if require_current_tools:
        from .adaptive_hybrid_analyze import analyze

        with tempfile.TemporaryDirectory(
            prefix="otis-analysis-supersession-validation."
        ) as temporary_directory:
            _, replayed = analyze(
                source_path,
                output_path=Path(temporary_directory) / "seal.json",
                prior_review_seal_path=original_path,
            )
        deterministic_fields = CURRENT_SEAL_FIELDS - {
            "created_utc",
            "seal_sha256",
        }
        if {
            key: corrected[key] for key in deterministic_fields
        } != {key: replayed[key] for key in deterministic_fields}:
            raise ValueError(
                "analysis supersession corrected seal does not match current replay"
            )
    if package_identity(source_path) != source_before:
        raise ValueError("analysis supersession source changed during validation")
    addendum_identity = package_identity(location)
    if addendum_identity.get("file_count") != 3:
        raise ValueError("analysis supersession addendum contains unexpected files")
    return {
        "contract": ANALYSIS_SUPERSESSION_KIND,
        "source_content_sha256": source_content,
        "original_seal_sha256": str(original["seal_sha256"]),
        "corrected_seal_sha256": str(corrected["seal_sha256"]),
        "corrected_analyzer_identity": str(corrected["tool_sha256"]),
        "primary_decision": str(corrected["primary_decision"]),
        "supersession_sha256": str(report["supersession_sha256"]),
    }


def _validated_current_campaign_package(
    location: Path,
    *,
    source_revision: str,
    build_identity: str,
    image_identity: str,
    attempt_classification: str,
    result_or_failure_reason: str,
    analyzer_identity: str,
) -> dict[str, str]:
    """Validate one current package that claims passing evidence integrity."""

    if not location.is_dir():
        raise ValueError(
            "successful evidence registration requires a completed package directory"
        )
    if attempt_classification == "successful_rehearsal":
        return evidence_module.validate_operational_rehearsal_package(
            location,
            source_revision=source_revision,
            build_identity=build_identity,
            image_identity=image_identity,
            result_or_failure_reason=result_or_failure_reason,
            analyzer_identity=analyzer_identity,
        )
    required = {
        "completion marker": location / "COMPLETE",
        "run manifest": location / "run_manifest.json",
        "evidence snapshot": location / "evidence_manifest.json",
        "analyzer seal": location / CURRENT_SEAL_PATH,
        "supervisor state": location / CURRENT_SUPERVISOR_STATE_PATH,
    }
    missing = [label for label, path in required.items() if not path.is_file()]
    if missing:
        raise ValueError(
            "successful evidence registration requires " + ", ".join(missing)
        )

    # Imports remain local so raw, interrupted, failed, diagnostic, and historical
    # inventory registration does not acquire the current live-programme graph.
    from .adaptive_hybrid_activation import validate_frozen_run_manifest
    from .adaptive_hybrid_contract import programme_from_mapping
    from .evidence import validate_evidence_snapshot
    from .run_loader import load_manifest

    try:
        manifest_value = validate_frozen_run_manifest(required["run manifest"])
        manifest = load_manifest(location)
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            f"successful evidence registration requires an exact current run manifest: {exc}"
        ) from exc
    programme = programme_from_mapping(manifest_value)
    if programme.physical_seal_path != CURRENT_SEAL_PATH:
        raise ValueError("successful evidence registration seal path differs")

    completion = _read_object(required["completion marker"], "completion marker")
    if (
        completion.get("completion")
        != "adaptive_hybrid_finite_physical_campaign"
        or completion.get("terminal") is not None
        and not isinstance(completion.get("terminal"), dict)
    ):
        raise ValueError("successful evidence registration completion marker differs")

    snapshot = _read_object(required["evidence snapshot"], "evidence snapshot")
    failures, warnings = validate_evidence_snapshot(location, manifest)
    if failures or warnings or snapshot.get("run_state") != "complete":
        detail = "; ".join([*failures, *warnings]) or "run_state is not complete"
        raise ValueError(
            "successful evidence registration requires an exact complete evidence "
            f"snapshot: {detail}"
        )

    seal = _read_object(required["analyzer seal"], "analyzer seal")
    if set(seal) != CURRENT_SEAL_FIELDS:
        raise ValueError("successful evidence registration analyzer seal fields differ")
    claimed_seal_sha256 = seal.get("seal_sha256")
    unsigned_seal = {
        key: value for key, value in seal.items() if key != "seal_sha256"
    }
    checks = seal.get("checks")
    snapshot_result = seal.get("evidence_snapshot")
    if (
        seal.get("schema_version") != 1
        or seal.get("seal_type") != CURRENT_SEAL_TYPE
        or seal.get("tool") != CURRENT_ANALYZER_ID
        or not isinstance(claimed_seal_sha256, str)
        or not LOWER_HEX_64.fullmatch(claimed_seal_sha256)
        or claimed_seal_sha256 != _canonical_sha256(unsigned_seal)
        or seal.get("status") != "passed"
        or seal.get("evidence_integrity") != "passed"
        or not isinstance(seal.get("scientific_outcome"), str)
        or seal.get("scientific_outcome") not in SCIENTIFIC_OUTCOME_VALUES
        or not isinstance(checks, dict)
        or not checks
        or not all(value is True for value in checks.values())
        or not isinstance(snapshot_result, dict)
        or snapshot_result.get("path") != "evidence_manifest.json"
        or snapshot_result.get("failures") != []
        or snapshot_result.get("warnings") != []
    ):
        raise ValueError(
            "successful evidence registration requires an exact passing analyzer seal"
        )

    firmware = manifest_value.get("firmware", {})
    policy = manifest_value.get("policy", {})
    host = manifest_value.get("host", {})
    tool_bindings = host.get("tool_bindings", {}) if isinstance(host, dict) else {}
    analyzer_binding = (
        tool_bindings.get("adaptive_hybrid_analyze", {})
        if isinstance(tool_bindings, dict)
        else {}
    )
    terminal, resolved_review = _resolved_completion_terminal(
        location=location,
        completion=completion,
        seal=seal,
        original_analyzer_sha256=analyzer_binding.get("sha256"),
        analyzer_identity=analyzer_identity,
    )
    from .adaptive_hybrid_analyze import classify_scientific_outcome

    supervisor_state = _read_object(required["supervisor state"], "supervisor state")
    derived_scientific_outcome = classify_scientific_outcome(
        terminal,
        programme,
        bench_attempt=manifest_value.get("bench_attempt"),
        qualified_d14_accepted_apertures=supervisor_state.get(
            "qualified_d14_accepted_apertures"
        ),
    )
    if (
        derived_scientific_outcome == "undetermined"
        or seal.get("scientific_outcome") != derived_scientific_outcome
    ):
        raise ValueError(
            "successful evidence registration scientific outcome differs from "
            "the frozen endpoint evidence"
        )
    campaign_classification = campaign_attempt_classification(
        evidence_integrity=str(seal["evidence_integrity"]),
        scientific_outcome=derived_scientific_outcome,
    )
    if attempt_classification in {
        "completed_campaign",
        "interrupted_campaign",
        "diagnostic",
    } and campaign_classification != attempt_classification:
        raise ValueError(
            "campaign registration classification differs from the scientific outcome"
        )
    expected = {
        "run_id": manifest.run_id,
        "run_identity": manifest_value.get("run_identity"),
        "build_identity": build_identity,
        "image_identity": image_identity,
        "programme_id": manifest_value.get("programme_id"),
        "policy_id": policy.get("policy_id") if isinstance(policy, dict) else None,
        "tool_sha256": analyzer_identity,
        "terminal_result": terminal.get("result"),
        "terminal_reason": terminal.get("reason"),
    }
    mismatched = sorted(
        field for field, expected_value in expected.items()
        if seal.get(field) != expected_value
    )
    if mismatched:
        raise ValueError(
            "successful evidence registration metadata differs from analyzer seal: "
            + ", ".join(mismatched)
        )
    if (
        not isinstance(firmware, dict)
        or firmware.get("source_revision") != source_revision
        or firmware.get("build_identity") != build_identity
        or manifest_value.get("image_identity") != image_identity
        or (
            not resolved_review
            and analyzer_binding.get("sha256") != analyzer_identity
        )
        or not isinstance(seal.get("primary_decision"), str)
        or seal["primary_decision"] not in result_or_failure_reason
    ):
        raise ValueError(
            "successful evidence registration metadata differs from the completed package"
        )
    if (
        attempt_classification == "successful_qualification"
        and (
            derived_scientific_outcome != "qualified_complete"
        )
    ):
        raise ValueError(
            "successful qualification registration requires the qualified endpoint"
        )
    sealed_sources = seal.get("source_sha256")
    expected_sources = {
        str(item["path"]): _sha256_file(location / str(item["path"]))
        for item in manifest.files
        if (location / str(item.get("path", ""))).is_file()
    }
    if sealed_sources != expected_sources:
        raise ValueError(
            "successful evidence registration analyzer source identities differ"
        )

    return {
        "contract": "otis_validated_success_package_v1",
        "evidence_snapshot_sha256": str(snapshot["snapshot_digest"]),
        "seal_path": CURRENT_SEAL_PATH.as_posix(),
        "seal_sha256": claimed_seal_sha256,
        "seal_status": str(seal["status"]),
        "evidence_integrity": str(seal["evidence_integrity"]),
        "scientific_outcome": str(seal["scientific_outcome"]),
        "primary_decision": str(seal["primary_decision"]),
    }


def _assert_index_outside_repo(index_path: Path) -> Path:
    resolved = index_path.expanduser().resolve()
    try:
        resolved.relative_to(REPO_ROOT.resolve())
    except ValueError:
        return resolved
    raise ValueError("evidence index must be stored outside the Git repository")


def validate_index_location(index_path: Path) -> Path:
    """Validate and resolve an index location without creating any files."""

    return _assert_index_outside_repo(index_path)


def _empty_index(now: str | None = None) -> dict[str, Any]:
    timestamp = now or _utc_now()
    return {
        "schema_version": SCHEMA_VERSION,
        "index_id": INDEX_ID,
        "created_utc": timestamp,
        "updated_utc": timestamp,
        "packages": {},
    }


def _lock_path(index_path: Path) -> Path:
    return index_path.with_name(f".{index_path.name}.lock")


@contextmanager
def _index_lock(index_path: Path, *, exclusive: bool):  # type: ignore[no-untyped-def]
    path = _assert_index_outside_repo(index_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(_lock_path(path), os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(
            descriptor,
            fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH,
        )
        yield path
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _load_index_unlocked(path: Path) -> dict[str, Any]:
    if not path.exists():
        return _empty_index()
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported evidence index schema_version")
    if data.get("index_id") != INDEX_ID:
        raise ValueError("unexpected evidence index identity")
    if not isinstance(data.get("packages"), dict):
        raise ValueError("evidence index packages must be an object")
    return data


def _save_index_unlocked(path: Path, index: dict[str, Any]) -> None:
    index["updated_utc"] = _utc_now()
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        json.dump(index, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    try:
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)


def load_index(index_path: Path) -> dict[str, Any]:
    with _index_lock(index_path, exclusive=False) as path:
        return _load_index_unlocked(path)


def save_index(index_path: Path, index: dict[str, Any]) -> None:
    with _index_lock(index_path, exclusive=True) as path:
        _save_index_unlocked(path, index)


def register_package(
    *,
    index_path: Path,
    package_path: Path,
    source_revision: str,
    build_identity: str,
    image_identity: str,
    attempt_classification: str,
    result_or_failure_reason: str,
    analyzer_identity: str,
    expected_content_sha256: str | None = None,
    evidence_integrity: str | None = None,
    scientific_outcome: str | None = None,
) -> dict[str, Any]:
    required = {
        "source_revision": source_revision,
        "build_identity": build_identity,
        "image_identity": image_identity,
        "result_or_failure_reason": result_or_failure_reason,
        "analyzer_identity": analyzer_identity,
    }
    missing = sorted(name for name, value in required.items() if not value.strip())
    if missing:
        raise ValueError(f"empty required evidence metadata: {', '.join(missing)}")
    if (
        not isinstance(attempt_classification, str)
        or attempt_classification not in ATTEMPT_CLASSIFICATIONS
    ):
        raise ValueError(
            "attempt_classification must be one of: "
            + ", ".join(sorted(ATTEMPT_CLASSIFICATIONS))
        )
    if (evidence_integrity is None) != (scientific_outcome is None):
        raise ValueError(
            "campaign evidence integrity and scientific outcome must be supplied together"
        )
    if evidence_integrity is not None and scientific_outcome is not None:
        if not _campaign_metadata_matches_classification(
            attempt_classification=attempt_classification,
            evidence_integrity=evidence_integrity,
            scientific_outcome=scientific_outcome,
        ):
            raise ValueError(
                "attempt classification contradicts campaign integrity and outcome"
            )
    if expected_content_sha256 is not None and not LOWER_HEX_64.fullmatch(
        expected_content_sha256
    ):
        raise ValueError("expected evidence content identity must be lowercase SHA-256")

    location = package_path.expanduser().resolve()
    identity = package_identity(location)
    content_sha256 = identity["content_sha256"]
    if (
        expected_content_sha256 is not None
        and content_sha256 != expected_content_sha256
    ):
        raise ValueError("evidence package differs from expected content identity")
    package_validation = None
    if attempt_classification in SUCCESS_CLASSIFICATIONS or evidence_integrity == "passed":
        package_validation = _validated_current_campaign_package(
            location,
            source_revision=source_revision,
            build_identity=build_identity,
            image_identity=image_identity,
            attempt_classification=attempt_classification,
            result_or_failure_reason=result_or_failure_reason,
            analyzer_identity=analyzer_identity,
        )
        if package_identity(location) != identity:
            raise ValueError("evidence package changed during success validation")
        if "scientific_outcome" in package_validation:
            validated_integrity = str(package_validation["evidence_integrity"])
            validated_outcome = str(package_validation["scientific_outcome"])
            if evidence_integrity is not None and (
                evidence_integrity != validated_integrity
                or scientific_outcome != validated_outcome
            ):
                raise ValueError(
                    "registration integrity or outcome differs from validated package"
                )
            evidence_integrity = validated_integrity
            scientific_outcome = validated_outcome
    immutable_metadata: dict[str, Any] = {
        "source_revision": source_revision,
        "build_identity": build_identity,
        "image_identity": image_identity,
        "attempt_classification": attempt_classification,
        "result_or_failure_reason": result_or_failure_reason,
        "analyzer_identity": analyzer_identity,
    }
    if package_validation is not None:
        immutable_metadata["package_validation"] = package_validation
    if evidence_integrity is not None and scientific_outcome is not None:
        immutable_metadata["evidence_integrity"] = evidence_integrity
        immutable_metadata["scientific_outcome"] = scientific_outcome
    with _index_lock(index_path, exclusive=True) as locked_path:
        index = _load_index_unlocked(locked_path)
        existing = index["packages"].get(content_sha256)
        if existing is not None:
            for key, value in immutable_metadata.items():
                if existing.get(key) != value:
                    raise ValueError(
                        "content identity already registered with different "
                        f"{key}"
                    )
            locations = existing["storage_locations"]
            if str(location) not in locations:
                locations.append(str(location))
                _save_index_unlocked(locked_path, index)
            return existing

        now = _utc_now()
        record = {
            "content_sha256": content_sha256,
            "file_count": identity["file_count"],
            "total_bytes": identity["total_bytes"],
            "file_manifest": identity["files"],
            "storage_locations": [str(location)],
            **immutable_metadata,
            "lifecycle_status": "active",
            "registered_utc": now,
            "mothball": None,
        }
        index["packages"][content_sha256] = record
        _save_index_unlocked(locked_path, index)
        return record


def register_analysis_supersession(
    *, index_path: Path, addendum_path: Path
) -> dict[str, Any]:
    """Register one immutable offline-analysis addendum beside its source."""

    location = addendum_path.expanduser().resolve()
    identity = package_identity(location)
    with _index_lock(index_path, exclusive=True) as locked_path:
        index = _load_index_unlocked(locked_path)
        existing = index["packages"].get(identity["content_sha256"])
        if existing is not None:
            validation = _validated_analysis_supersession_artifact(
                location, index, require_current_tools=False
            )
            if package_identity(location) != identity:
                raise ValueError("analysis supersession changed during validation")
            if (
                existing.get("artifact_kind") != ANALYSIS_SUPERSESSION_KIND
                or existing.get("supersession_validation") != validation
                or not _supersession_index_record_exact(
                    existing,
                    content_sha256=identity["content_sha256"],
                    identity=identity,
                    validation=validation,
                )
            ):
                raise ValueError(
                    "analysis supersession content is registered with different metadata"
                )
            locations = existing.get("storage_locations", [])
            if str(location) not in locations:
                locations.append(str(location))
                _save_index_unlocked(locked_path, index)
            return existing
        validation = _validated_analysis_supersession_artifact(
            location, index, require_current_tools=True
        )
        if package_identity(location) != identity:
            raise ValueError("analysis supersession changed during validation")
        for record in index["packages"].values():
            if record.get("artifact_kind") == ANALYSIS_SUPERSESSION_KIND:
                retained = record.get("supersession_validation")
                if not isinstance(retained, dict) or any(
                    record.get(field) != retained.get(field)
                    for field in (
                        "source_content_sha256",
                        "original_seal_sha256",
                        "corrected_seal_sha256",
                        "corrected_analyzer_identity",
                    )
                ):
                    raise ValueError("existing analysis supersession index record differs")
                if (
                    retained.get("source_content_sha256")
                    == validation["source_content_sha256"]
                    and retained.get("original_seal_sha256")
                    == validation["original_seal_sha256"]
                ):
                    raise ValueError(
                        "a conflicting analysis supersession already exists for this seal"
                    )
            elif "attempt_classification" not in record:
                raise ValueError("evidence index contains an unknown record kind")
        now = _utc_now()
        record = {
            "content_sha256": identity["content_sha256"],
            "file_count": identity["file_count"],
            "total_bytes": identity["total_bytes"],
            "file_manifest": identity["files"],
            "storage_locations": [str(location)],
            "artifact_kind": ANALYSIS_SUPERSESSION_KIND,
            "source_content_sha256": validation["source_content_sha256"],
            "original_seal_sha256": validation["original_seal_sha256"],
            "corrected_seal_sha256": validation["corrected_seal_sha256"],
            "corrected_analyzer_identity": validation[
                "corrected_analyzer_identity"
            ],
            "supersession_validation": validation,
            "lifecycle_status": "active",
            "registered_utc": now,
            "mothball": None,
        }
        index["packages"][identity["content_sha256"]] = record
        _save_index_unlocked(locked_path, index)
        return record


def _standard_index_record_exact(
    record: dict[str, Any], *, content_sha256: str, identity: dict[str, Any]
) -> bool:
    fields = {
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
        "lifecycle_status",
        "registered_utc",
        "mothball",
    }
    if "package_validation" in record:
        fields.add("package_validation")
    has_campaign_outcome = (
        "evidence_integrity" in record or "scientific_outcome" in record
    )
    if has_campaign_outcome:
        fields.update({"evidence_integrity", "scientific_outcome"})
    return (
        set(record) == fields
        and record.get("content_sha256") == content_sha256
        and record.get("file_count") == identity.get("file_count")
        and record.get("total_bytes") == identity.get("total_bytes")
        and record.get("file_manifest") == identity.get("files")
        and isinstance(record.get("attempt_classification"), str)
        and record.get("attempt_classification") in ATTEMPT_CLASSIFICATIONS
        and (
            not has_campaign_outcome
            or (
                isinstance(record.get("evidence_integrity"), str)
                and record.get("evidence_integrity") in EVIDENCE_INTEGRITY_VALUES
                and isinstance(record.get("scientific_outcome"), str)
                and record.get("scientific_outcome") in SCIENTIFIC_OUTCOME_VALUES
                and _campaign_metadata_matches_classification(
                    attempt_classification=record.get("attempt_classification"),
                    evidence_integrity=str(record["evidence_integrity"]),
                    scientific_outcome=str(record["scientific_outcome"]),
                )
            )
        )
        and record.get("lifecycle_status") in {"active", "mothballed"}
        and _explicit_utc(record.get("registered_utc"))
    )


def _recorded_package_identity(record: dict[str, Any]) -> dict[str, Any] | None:
    """Reconstruct a package identity from an immutable index manifest."""

    entries = record.get("file_manifest")
    if not isinstance(entries, list):
        return None
    normalized: list[dict[str, Any]] = []
    paths: list[str] = []
    total_bytes = 0
    tree_digest = sha256()
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "relative_path",
            "size_bytes",
            "sha256",
        }:
            return None
        relative_path = entry.get("relative_path")
        size_bytes = entry.get("size_bytes")
        digest = entry.get("sha256")
        if (
            not isinstance(relative_path, str)
            or not relative_path
            or relative_path.startswith("/")
            or "\\" in relative_path
            or ".." in Path(relative_path).parts
            or not isinstance(size_bytes, int)
            or isinstance(size_bytes, bool)
            or size_bytes < 0
            or not isinstance(digest, str)
            or not LOWER_HEX_64.fullmatch(digest)
        ):
            return None
        paths.append(relative_path)
        normalized.append(dict(entry))
        total_bytes += size_bytes
        encoded = json.dumps(
            entry, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        tree_digest.update(len(encoded).to_bytes(8, "big"))
        tree_digest.update(encoded)
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        return None
    if not entries:
        tree_digest.update(b"OTIS_EMPTY_EVIDENCE_DIRECTORY_V1")
    identity = {
        "content_sha256": tree_digest.hexdigest(),
        "file_count": len(normalized),
        "total_bytes": total_bytes,
        "files": normalized,
    }
    if (
        record.get("content_sha256") != identity["content_sha256"]
        or record.get("file_count") != identity["file_count"]
        or record.get("total_bytes") != identity["total_bytes"]
    ):
        return None
    return identity


def _matching_standard_record_identity(
    record: dict[str, Any], *, content_sha256: str
) -> dict[str, Any] | None:
    for raw_location in record.get("storage_locations", []):
        if not isinstance(raw_location, str):
            continue
        location = Path(raw_location).expanduser()
        if not location.exists():
            continue
        identity = package_identity(location)
        if (
            identity.get("content_sha256") == content_sha256
            and _standard_index_record_exact(
                record,
                content_sha256=content_sha256,
                identity=identity,
            )
        ):
            return identity
    return None


def _registration_supersession_exact(
    record: dict[str, Any],
    *,
    content_sha256: str,
    index: dict[str, Any],
) -> tuple[bool, str | None]:
    """Validate one retained identity superseded by append-only finalization."""

    fields = {
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
        "lifecycle_status",
        "registered_utc",
        "mothball",
        "registration_supersession",
    }
    if "package_validation" in record:
        fields.add("package_validation")
    has_campaign_outcome = (
        "evidence_integrity" in record or "scientific_outcome" in record
    )
    if has_campaign_outcome:
        fields.update({"evidence_integrity", "scientific_outcome"})
    disposition = record.get("registration_supersession")
    predecessor_identity = _recorded_package_identity(record)
    if (
        set(record) != fields
        or predecessor_identity is None
        or predecessor_identity.get("content_sha256") != content_sha256
        or record.get("lifecycle_status") != "superseded_registration"
        or record.get("mothball") is not None
        or not _explicit_utc(record.get("registered_utc"))
        or not isinstance(record.get("attempt_classification"), str)
        or record.get("attempt_classification") not in ATTEMPT_CLASSIFICATIONS
        or has_campaign_outcome
        and (
            not isinstance(record.get("evidence_integrity"), str)
            or record.get("evidence_integrity") not in EVIDENCE_INTEGRITY_VALUES
            or not isinstance(record.get("scientific_outcome"), str)
            or record.get("scientific_outcome") not in SCIENTIFIC_OUTCOME_VALUES
            or not _campaign_metadata_matches_classification(
                attempt_classification=record.get("attempt_classification"),
                evidence_integrity=str(record.get("evidence_integrity")),
                scientific_outcome=str(record.get("scientific_outcome")),
            )
        )
        or any(
            not isinstance(record.get(field), str) or not record[field].strip()
            for field in (
                "source_revision",
                "build_identity",
                "image_identity",
                "result_or_failure_reason",
                "analyzer_identity",
            )
        )
        or not isinstance(record.get("storage_locations"), list)
        or not record["storage_locations"]
        or any(
            not isinstance(location, str) or not Path(location).is_absolute()
            for location in record["storage_locations"]
        )
        or len(record["storage_locations"]) != len(set(record["storage_locations"]))
        or not isinstance(disposition, dict)
        or set(disposition)
        != {
            "schema_version",
            "disposition",
            "recorded_utc",
            "successor_content_sha256",
            "predecessor_registered_utc",
            "successor_registered_utc",
            "in_place_storage_locations",
            "preserved_file_count",
            "added_relative_paths",
            "all_predecessor_files_retained_unchanged",
            "evidence_preserved",
            "data_deleted",
            "reason",
        }
        or disposition.get("schema_version") != 1
        or disposition.get("disposition") != REGISTRATION_SUPERSESSION_KIND
        or not _explicit_utc(disposition.get("recorded_utc"))
        or disposition.get("predecessor_registered_utc")
        != record.get("registered_utc")
        or disposition.get("preserved_file_count")
        != predecessor_identity.get("file_count")
        or disposition.get("all_predecessor_files_retained_unchanged") is not True
        or disposition.get("evidence_preserved") is not True
        or disposition.get("data_deleted") is not False
        or not isinstance(disposition.get("reason"), str)
        or not disposition["reason"].strip()
    ):
        return False, None
    successor_sha256 = disposition.get("successor_content_sha256")
    successor = index.get("packages", {}).get(successor_sha256)
    if (
        not isinstance(successor_sha256, str)
        or not LOWER_HEX_64.fullmatch(successor_sha256)
        or successor_sha256 == content_sha256
        or not isinstance(successor, dict)
        or successor.get("artifact_kind") is not None
        or successor.get("lifecycle_status") == "superseded_registration"
        or disposition.get("successor_registered_utc")
        != successor.get("registered_utc")
    ):
        return False, None
    successor_identity = _matching_standard_record_identity(
        successor, content_sha256=successor_sha256
    )
    if successor_identity is None:
        return False, None
    shared_provenance = ("source_revision", "build_identity", "image_identity")
    predecessor_entries = {
        item["relative_path"]: item for item in predecessor_identity["files"]
    }
    successor_entries = {
        item["relative_path"]: item for item in successor_identity["files"]
    }
    added_paths = sorted(set(successor_entries) - set(predecessor_entries))
    overlap = sorted(
        set(record.get("storage_locations", []))
        & set(successor.get("storage_locations", []))
    )
    in_place_locations = disposition.get("in_place_storage_locations")
    exact_in_place_locations = []
    if isinstance(in_place_locations, list):
        for raw_location in in_place_locations:
            if not isinstance(raw_location, str) or raw_location not in overlap:
                continue
            location = Path(raw_location).expanduser()
            if (
                location.exists()
                and package_identity(location).get("content_sha256")
                == successor_sha256
            ):
                exact_in_place_locations.append(raw_location)
    if (
        any(record.get(field) != successor.get(field) for field in shared_provenance)
        or not predecessor_entries
        or not added_paths
        or any(
            successor_entries.get(path) != entry
            for path, entry in predecessor_entries.items()
        )
        or disposition.get("added_relative_paths") != added_paths
        or not isinstance(in_place_locations, list)
        or not in_place_locations
        or in_place_locations != sorted(set(in_place_locations))
        or exact_in_place_locations != in_place_locations
    ):
        return False, None
    return True, successor_sha256


def supersede_append_only_registration(
    *,
    index_path: Path,
    predecessor_content_sha256: str,
    successor_content_sha256: str,
    reason: str,
    confirm_all_predecessor_files_retained: bool,
) -> dict[str, Any]:
    """Retain an in-place pre-finalization identity and bind its successor."""

    if not confirm_all_predecessor_files_retained:
        raise ValueError(
            "registration supersession requires confirmation that all predecessor "
            "files are retained unchanged"
        )
    if not reason.strip():
        raise ValueError("registration supersession reason must be non-empty")
    if (
        not LOWER_HEX_64.fullmatch(predecessor_content_sha256)
        or not LOWER_HEX_64.fullmatch(successor_content_sha256)
        or predecessor_content_sha256 == successor_content_sha256
    ):
        raise ValueError("registration supersession identities differ")
    with _index_lock(index_path, exclusive=True) as locked_path:
        index = _load_index_unlocked(locked_path)
        predecessor = index["packages"].get(predecessor_content_sha256)
        successor = index["packages"].get(successor_content_sha256)
        if not isinstance(predecessor, dict) or not isinstance(successor, dict):
            raise ValueError("registration supersession package is unavailable")
        if predecessor.get("lifecycle_status") == "superseded_registration":
            exact, retained_successor = _registration_supersession_exact(
                predecessor,
                content_sha256=predecessor_content_sha256,
                index=index,
            )
            disposition = predecessor.get("registration_supersession", {})
            if (
                not exact
                or retained_successor != successor_content_sha256
                or disposition.get("reason") != reason
            ):
                raise ValueError("existing registration supersession differs")
            return predecessor
        recorded_identity = _recorded_package_identity(predecessor)
        if (
            recorded_identity is None
            or predecessor.get("lifecycle_status") != "active"
            or predecessor.get("mothball") is not None
            or not _standard_index_record_exact(
                predecessor,
                content_sha256=predecessor_content_sha256,
                identity=recorded_identity,
            )
        ):
            raise ValueError("predecessor registration is not an exact active record")
        successor_identity = _matching_standard_record_identity(
            successor, content_sha256=successor_content_sha256
        )
        if successor_identity is None:
            raise ValueError("successor registration has no exact retained package")
        overlap = sorted(
            set(predecessor.get("storage_locations", []))
            & set(successor.get("storage_locations", []))
        )
        exact_in_place_locations = []
        for raw_location in overlap:
            location = Path(raw_location).expanduser()
            if (
                location.exists()
                and package_identity(location).get("content_sha256")
                == successor_content_sha256
            ):
                exact_in_place_locations.append(raw_location)
        predecessor_entries = {
            item["relative_path"]: item for item in recorded_identity["files"]
        }
        successor_entries = {
            item["relative_path"]: item for item in successor_identity["files"]
        }
        added_paths = sorted(set(successor_entries) - set(predecessor_entries))
        if (
            not exact_in_place_locations
            or not added_paths
            or any(
                successor_entries.get(path) != entry
                for path, entry in predecessor_entries.items()
            )
            or any(
                predecessor.get(field) != successor.get(field)
                for field in ("source_revision", "build_identity", "image_identity")
            )
            or predecessor.get("registered_utc", "")
            >= successor.get("registered_utc", "")
        ):
            raise ValueError(
                "successor is not an exact append-only evolution at the same location"
            )
        predecessor["lifecycle_status"] = "superseded_registration"
        predecessor["registration_supersession"] = {
            "schema_version": 1,
            "disposition": REGISTRATION_SUPERSESSION_KIND,
            "recorded_utc": _utc_now(),
            "successor_content_sha256": successor_content_sha256,
            "predecessor_registered_utc": predecessor["registered_utc"],
            "successor_registered_utc": successor["registered_utc"],
            "in_place_storage_locations": exact_in_place_locations,
            "preserved_file_count": recorded_identity["file_count"],
            "added_relative_paths": added_paths,
            "all_predecessor_files_retained_unchanged": True,
            "evidence_preserved": True,
            "data_deleted": False,
            "reason": reason,
        }
        exact, retained_successor = _registration_supersession_exact(
            predecessor,
            content_sha256=predecessor_content_sha256,
            index=index,
        )
        if not exact or retained_successor != successor_content_sha256:
            raise ValueError("registration supersession failed exact validation")
        _save_index_unlocked(locked_path, index)
        return predecessor


def _supersession_index_record_exact(
    record: dict[str, Any],
    *,
    content_sha256: str,
    identity: dict[str, Any],
    validation: dict[str, str],
) -> bool:
    fields = {
        "content_sha256",
        "file_count",
        "total_bytes",
        "file_manifest",
        "storage_locations",
        "artifact_kind",
        "source_content_sha256",
        "original_seal_sha256",
        "corrected_seal_sha256",
        "corrected_analyzer_identity",
        "supersession_validation",
        "lifecycle_status",
        "registered_utc",
        "mothball",
    }
    return (
        set(record) == fields
        and record.get("content_sha256") == content_sha256
        and record.get("file_count") == identity.get("file_count")
        and record.get("total_bytes") == identity.get("total_bytes")
        and record.get("file_manifest") == identity.get("files")
        and record.get("artifact_kind") == ANALYSIS_SUPERSESSION_KIND
        and record.get("source_content_sha256")
        == validation.get("source_content_sha256")
        and record.get("original_seal_sha256")
        == validation.get("original_seal_sha256")
        and record.get("corrected_seal_sha256")
        == validation.get("corrected_seal_sha256")
        and record.get("corrected_analyzer_identity")
        == validation.get("corrected_analyzer_identity")
        and record.get("supersession_validation") == validation
        and record.get("lifecycle_status") in {"active", "mothballed"}
        and _explicit_utc(record.get("registered_utc"))
    )


def validate_index(index_path: Path) -> dict[str, Any]:
    index = load_index(index_path)
    results: list[dict[str, Any]] = []
    valid = True
    for content_sha256, record in sorted(index["packages"].items()):
        location_results = []
        any_matching_location = False
        if record.get("lifecycle_status") == "superseded_registration":
            exact, successor_sha256 = _registration_supersession_exact(
                record,
                content_sha256=content_sha256,
                index=index,
            )
            unexpected_location = False
            for raw_location in record.get("storage_locations", []):
                location = Path(raw_location)
                if not location.exists():
                    location_results.append(
                        {"location": raw_location, "status": "missing"}
                    )
                    continue
                identity = package_identity(location)
                observed = identity["content_sha256"]
                if observed == content_sha256:
                    status = "retained_predecessor"
                elif observed == successor_sha256:
                    status = "superseded_by_append_only_successor"
                else:
                    status = "mismatch"
                    unexpected_location = True
                location_results.append(
                    {
                        "location": raw_location,
                        "status": status,
                        "observed_content_sha256": observed,
                    }
                )
            package_valid = exact and not unexpected_location
            valid &= package_valid
            results.append(
                {
                    "content_sha256": content_sha256,
                    "valid": package_valid,
                    "successor_content_sha256": successor_sha256,
                    "locations": location_results,
                }
            )
            continue
        for raw_location in record.get("storage_locations", []):
            location = Path(raw_location)
            if not location.exists():
                location_results.append(
                    {"location": raw_location, "status": "missing"}
                )
                continue
            identity = package_identity(location)
            observed = identity["content_sha256"]
            status = "match" if observed == content_sha256 else "mismatch"
            if status == "match" and record.get("artifact_kind") == (
                ANALYSIS_SUPERSESSION_KIND
            ):
                try:
                    validation = _validated_analysis_supersession_artifact(
                        location, index
                    )
                    if not _supersession_index_record_exact(
                        record,
                        content_sha256=content_sha256,
                        identity=identity,
                        validation=validation,
                    ):
                        status = "mismatch"
                except (OSError, KeyError, TypeError, ValueError):
                    status = "mismatch"
            elif status == "match" and not _standard_index_record_exact(
                record,
                content_sha256=content_sha256,
                identity=identity,
            ):
                status = "mismatch"
            any_matching_location |= status == "match"
            location_results.append(
                {
                    "location": raw_location,
                    "status": status,
                    "observed_content_sha256": observed,
                }
            )
        package_valid = any_matching_location
        valid &= package_valid
        results.append(
            {
                "content_sha256": content_sha256,
                "valid": package_valid,
                "locations": location_results,
            }
        )
    return {
        "index_id": INDEX_ID,
        "valid": valid,
        "package_count": len(results),
        "packages": results,
    }


def mothball_package(
    *,
    index_path: Path,
    content_sha256: str,
    reviewed_summary_path: Path,
    reason: str,
    confirm_no_active_dependency: bool,
) -> dict[str, Any]:
    if not confirm_no_active_dependency:
        raise ValueError("mothball requires confirmation of no active dependency")
    if not reason.strip():
        raise ValueError("mothball reason must be non-empty")
    summary = reviewed_summary_path.expanduser().resolve()
    if not summary.is_file():
        raise ValueError(f"reviewed summary does not exist: {summary}")
    with _index_lock(index_path, exclusive=True) as locked_path:
        index = _load_index_unlocked(locked_path)
        try:
            record = index["packages"][content_sha256]
        except KeyError as exc:
            raise ValueError("unknown evidence content identity") from exc
        if record.get("lifecycle_status") == "superseded_registration":
            raise ValueError(
                "append-only registration supersession cannot be mothballed "
                "without a combined lifecycle contract"
            )
        record["lifecycle_status"] = "mothballed"
        record["mothball"] = {
            "mothballed_utc": _utc_now(),
            "reason": reason,
            "no_active_dependency_confirmed": True,
            "reviewed_summary_path": str(summary),
            "reviewed_summary_sha256": _sha256_file(summary),
        }
        _save_index_unlocked(locked_path, index)
        return record


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    commands = parser.add_subparsers(dest="command", required=True)

    register = commands.add_parser("register")
    register.add_argument("package", type=Path)
    register.add_argument("--source-revision", required=True)
    register.add_argument("--build-identity", required=True)
    register.add_argument("--image-identity", required=True)
    register.add_argument(
        "--attempt-classification",
        required=True,
        choices=sorted(ATTEMPT_CLASSIFICATIONS),
    )
    register.add_argument("--result-or-failure-reason", required=True)
    register.add_argument("--analyzer-identity", required=True)
    register.add_argument(
        "--evidence-integrity", choices=sorted(EVIDENCE_INTEGRITY_VALUES)
    )
    register.add_argument(
        "--scientific-outcome", choices=sorted(SCIENTIFIC_OUTCOME_VALUES)
    )

    commands.add_parser("validate")
    commands.add_parser("list")

    mothball = commands.add_parser("mothball")
    mothball.add_argument("content_sha256")
    mothball.add_argument("--reviewed-summary", type=Path, required=True)
    mothball.add_argument("--reason", required=True)
    mothball.add_argument(
        "--confirm-no-active-dependency", action="store_true", required=True
    )
    supersede = commands.add_parser("supersede-append-only-registration")
    supersede.add_argument("predecessor_content_sha256")
    supersede.add_argument("successor_content_sha256")
    supersede.add_argument("--reason", required=True)
    supersede.add_argument(
        "--confirm-all-predecessor-files-retained",
        action="store_true",
        required=True,
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "register":
        result = register_package(
            index_path=args.index,
            package_path=args.package,
            source_revision=args.source_revision,
            build_identity=args.build_identity,
            image_identity=args.image_identity,
            attempt_classification=args.attempt_classification,
            result_or_failure_reason=args.result_or_failure_reason,
            analyzer_identity=args.analyzer_identity,
            evidence_integrity=args.evidence_integrity,
            scientific_outcome=args.scientific_outcome,
        )
    elif args.command == "validate":
        result = validate_index(args.index)
    elif args.command == "list":
        result = load_index(args.index)
    elif args.command == "mothball":
        result = mothball_package(
            index_path=args.index,
            content_sha256=args.content_sha256,
            reviewed_summary_path=args.reviewed_summary,
            reason=args.reason,
            confirm_no_active_dependency=args.confirm_no_active_dependency,
        )
    else:
        result = supersede_append_only_registration(
            index_path=args.index,
            predecessor_content_sha256=args.predecessor_content_sha256,
            successor_content_sha256=args.successor_content_sha256,
            reason=args.reason,
            confirm_all_predecessor_files_retained=(
                args.confirm_all_predecessor_files_retained
            ),
        )
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("valid", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
