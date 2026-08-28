"""Create and validate the exact GNSS baud-envelope candidate and activation.

Candidate creation is structural and performs no hardware operation.  A live
orchestrator must successfully call :func:`load_and_validate` before it opens a
serial device, flashes firmware, or submits a receiver command.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import re
import subprocess
import sys
from typing import Any, Iterable, Mapping

from .gnss_baud_envelope_supervisor import (
    PROGRAMME_ID,
    canonical_sha256,
    load_contract,
)
from .evidence_index import DEFAULT_INDEX, validate_index_location
from .run_loader import (
    GNSS_BAUD_CONTINUATION_EVIDENCE_EPOCH,
    GNSS_BAUD_CONTINUATION_PROFILE_ID,
    GNSS_BAUD_CONTINUATION_STAGE,
    GNSS_BAUD_RESUME_EVIDENCE_EPOCH,
    GNSS_BAUD_RESUME_PROFILE_ID,
    GNSS_BAUD_RESUME_STAGE,
    GNSS_BAUD_ENVELOPE_EVIDENCE_EPOCH,
    GNSS_BAUD_ENVELOPE_PROFILE_ID,
    GNSS_BAUD_ENVELOPE_STAGE,
)
from .run_paths import default_csv_files


ROOT = Path(__file__).resolve().parents[2]
BUNDLE_TYPE = "otis_gnss_baud_envelope_candidate_bundle_v1"
ACTIVATION_TYPE = "otis_gnss_baud_envelope_live_activation_v1"
TOOL_ID = "otis_gnss_baud_envelope_bundle_v1"
ORIGINAL_CONTRACT_SHA256 = (
    "08308e05ecc4b169a46ace1eb339b93a778abe04070278fcc3c47519666b0550"
)
CONTINUATION_CONTRACT_SHA256 = (
    "7f029d106b684ac96623c5d3be28f3ebc6b69a3cd38e2641561ed04a2d204a22"
)
RESUME_CONTRACT_SHA256 = (
    "a91b095fb155292e979a84424c22141f88285ba6db065ffba7c167d9179c67c9"
)
# Retained export for callers that specifically consume the continuation bundle.
EXPECTED_CONTRACT_SHA256 = CONTINUATION_CONTRACT_SHA256
EXPECTED_FIRMWARE_VERSION = "OTIS_GNSS_BAUD_ENVELOPE_CHARACTERIZATION_V1"
EXPECTED_GNSS_RELEASE = "AXN_5.1.6_3333_18041700"
EXPECTED_GNSS_CONFIGURATION = "0101100000000000000000"
EXPECTED_USB_SERIAL = "503533748A919118"
STARTUP_DISCOVERY_HINT_DEFINE = "OTIS_GNSS_DISCOVERY_STARTUP_BAUD_HINT"
STARTUP_DISCOVERY_HINT_BAUD = 57600
OPENING_TARGET_AND_RECOVERY_ANCHOR_BAUD = 9600
STARTUP_DISCOVERY_ATTEMPT_BAUDS = (57600, 9600, 19200, 38400, 57600, 115200)
STARTUP_DISCOVERY_FALLBACK_SCAN_BAUDS = (9600, 19200, 38400, 57600, 115200)
STARTUP_DISCOVERY_TELEMETRY_KEYS = (
    "startup_hint_attempted",
    "startup_hint_baud",
    "startup_hint_identity_outcome",
    "startup_fallback_entered",
    "initial_discovery_identity_baud",
    "initial_discovery_outcome",
    "pmtk605_peripheral_complete_count",
    "pmtk605_last_peripheral_complete_ticks",
    "pmtk605_last_peripheral_complete_ticks_available",
    "pmtk605_last_peripheral_complete_ticks_domain",
)
CONTINUATION_START_LOGICAL_SEGMENT_DEFINE = (
    "OTIS_GNSS_BAUD_CHARACTERIZATION_CONTINUATION_START_LOGICAL_SEGMENT"
)
CONTINUATION_START_LOGICAL_SEGMENT = 6
CONTINUATION_HISTORICAL_SEGMENTS = ("S01", "S02", "S03", "S04", "S05")
CONTINUATION_LIVE_SEGMENTS = ("S06", "S07", "S08", "S09", "S10", "S11")
CONTINUATION_ATTACHMENT_TELEMETRY_KEYS = (
    "continuation_mode",
    "continuation_start_logical_segment",
    "continuation_local_segment_ordinal",
    "continuation_logical_segment",
    "continuation_attachment_baud",
    "continuation_attachment_outcome",
)
LIVE_RUN_ROOT = (
    ROOT / "runs" / "otis_gnss_baud_envelope_characterization_v1"
)
LIVE_RUN_ID = re.compile(r"^live_[0-9]{8}T[0-9]{6}Z$")
EVIDENCE_ARTIFACTS = (
    "reports/activated_candidate_bundle_v1.json",
    "reports/activated_live_activation_v1.json",
    "reports/activated_contract_v1.json",
    "reports/activated_firmware_build_manifest_v1.json",
    "reports/activated_profile_preflight_v1.json",
    "reports/activated_operational_check_v1.json",
    "reports/activated_run_manifest_template_v1.json",
    "reports/gnss_baud_envelope_firmware_flash_v1.json",
    "reports/gnss_baud_envelope_capture_process.log",
    "reports/capture_device_state.json",
    "reports/capture_segment_closure_v1.json",
    "reports/gnss_baud_envelope_supervisor_events_v1.jsonl",
    "reports/gnss_baud_envelope_supervisor_state_v1.json",
    "reports/gnss_baud_envelope_monitor_events_v1.jsonl",
    "reports/gnss_baud_envelope_attachment_terminal_v1.json",
    "reports/gnss_baud_envelope_abort_delivery_v1.json",
    "reports/gnss_baud_envelope_analysis_v1.json",
    "reports/gnss_baud_envelope_seal_v1.json",
    "reports/gnss_baud_envelope_live_result_v1.json",
    "COMPLETE",
)

REQUIRED_HOST_TOOL_PATHS = (
    "host/otis_tools/gnss_baud_envelope_bundle.py",
    "host/otis_tools/gnss_baud_envelope_live.py",
    "host/otis_tools/gnss_baud_envelope_capture_adapter.py",
    "host/otis_tools/gnss_baud_envelope_run.py",
    "host/otis_tools/gnss_baud_envelope_supervisor.py",
    "host/otis_tools/gnss_baud_envelope_monitor.py",
    "host/otis_tools/gnss_baud_envelope_analyze.py",
    "host/otis_tools/gnss_baud_envelope_operational_check.py",
    "host/otis_tools/capture_device.py",
    "host/otis_tools/capture_runtime_checks.py",
    "host/otis_tools/capture_segment_rotation.py",
    "host/otis_tools/campaign_finalization.py",
    "host/otis_tools/evidence.py",
    "host/otis_tools/evidence_index.py",
    "host/otis_tools/run_loader.py",
    "host/otis_tools/serial_commands.py",
    "tools/firmware_matrix.py",
    "tools/gnss_baud_characterization_preflight.py",
)

ORIGINAL_CANDIDATE_KEYS = frozenset(
    {
        "schema_version",
        "bundle_type",
        "bundle_id",
        "tool",
        "programme_id",
        "created_at_utc",
        "effective",
        "physical_authority",
        "contract",
        "firmware",
        "source_state",
        "source_files",
        "host_tools",
        "preflight",
        "operational_check",
        "expected_device",
        "capture",
        "command_table_sha256",
        "schedule",
        "stop_conditions",
        "final_state",
        "run_manifest_template",
        "run_manifest_template_sha256",
        "environment",
        "registration_index_path",
        "authority",
    }
)
CONTINUATION_CANDIDATE_KEYS = ORIGINAL_CANDIDATE_KEYS | {
    "startup_discovery",
    "continuation",
}
CANDIDATE_KEYS = CONTINUATION_CANDIDATE_KEYS
ORIGINAL_ACTIVATION_KEYS = frozenset(
    {
        "schema_version",
        "activation_type",
        "activation_id",
        "bundle_id",
        "bundle_sha256",
        "effective",
        "physical_authority",
        "activated_at_utc",
        "operator",
        "authority_source",
        "run_id",
        "run_dir",
        "device",
        "expected_device_identity",
        "wall_deadline_utc",
        "abort_deadline_ms",
        "flash_limit",
        "live_run_limit",
        "dac_writes_permitted",
        "control_arm_permitted",
        "registration_index_path",
    }
)
CONTINUATION_ACTIVATION_KEYS = ORIGINAL_ACTIVATION_KEYS | {
    "startup_discovery",
    "continuation",
    "schedule",
}
ACTIVATION_KEYS = CONTINUATION_ACTIVATION_KEYS


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} root must be an object")
    return value


def _binding(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    if resolved.is_symlink() or not resolved.is_file():
        raise ValueError(f"required exact file is absent or a symlink: {resolved}")
    return {
        "path": str(resolved),
        "size_bytes": resolved.stat().st_size,
        "sha256": _sha256_file(resolved),
    }


def _validate_binding(value: Mapping[str, Any], label: str) -> Path:
    if set(value) != {"path", "size_bytes", "sha256"}:
        raise ValueError(f"{label} binding shape differs")
    path = Path(str(value["path"])).resolve()
    if (
        path.is_symlink()
        or not path.is_file()
        or path.stat().st_size != int(value["size_bytes"])
        or _sha256_file(path) != value["sha256"]
    ):
        raise ValueError(f"{label} identity differs: {path}")
    return path


def _startup_discovery(contract: Mapping[str, Any]) -> dict[str, Any]:
    value = contract.get("startup_discovery")
    if not isinstance(value, Mapping):
        raise ValueError("startup discovery contract is absent")
    if contract.get("contract_id") == (
        "otis_gnss_baud_envelope_characterization_resume_v1"
    ):
        if (
            value.get("opening_target_baud") != 9600
            or value.get("recovery_anchor_baud") != 9600
            or value.get("hint_baud") != 115200
            or value.get("startup_attempt_bauds")
            != [115200, 9600, 19200, 38400, 57600, 115200]
            or value.get("fallback_scan_bauds")
            != list(STARTUP_DISCOVERY_FALLBACK_SCAN_BAUDS)
            or value.get("recovery_scan_bauds")
            != list(STARTUP_DISCOVERY_FALLBACK_SCAN_BAUDS)
            or value.get("pmtk251_before_fresh_identity_permitted") is not False
            or value.get("required_causal_telemetry")
            != list(STARTUP_DISCOVERY_TELEMETRY_KEYS)
        ):
            raise ValueError("resume startup discovery contract differs")
        return dict(value)
    sealed = value.get("sealed_prior_physical_state")
    subsequent = value.get("subsequent_observed_serial_baud_evidence")
    if (
        value.get("opening_target_baud")
        != OPENING_TARGET_AND_RECOVERY_ANCHOR_BAUD
        or value.get("recovery_anchor_baud")
        != OPENING_TARGET_AND_RECOVERY_ANCHOR_BAUD
        or value.get("hint_baud") != STARTUP_DISCOVERY_HINT_BAUD
        or value.get("hint_generated_define") != STARTUP_DISCOVERY_HINT_DEFINE
        or value.get("retain_generated_define")
        != "OTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD"
        or value.get("hint_authority")
        != "scan_order_only_not_confirmed_baud_epoch_or_transition_authority"
        or value.get("startup_attempt_bauds")
        != list(STARTUP_DISCOVERY_ATTEMPT_BAUDS)
        or value.get("fallback_scan_bauds")
        != list(STARTUP_DISCOVERY_FALLBACK_SCAN_BAUDS)
        or value.get("startup_attempt_count")
        != len(STARTUP_DISCOVERY_ATTEMPT_BAUDS)
        or value.get("recovery_scan_unchanged") is not True
        or value.get("first_hint_permitted_transmit")
        != "PMTK605_identity_query_only"
        or value.get("pmtk251_before_fresh_identity_permitted") is not False
        or value.get("basis_classification") != "observed_serial_baud"
        or value.get("causal_telemetry_component") != "gnss_receiver"
        or value.get("pmtk605_peripheral_complete_counter_domain")
        != "rp2040_timer0_extended"
        or value.get("required_causal_telemetry")
        != list(STARTUP_DISCOVERY_TELEMETRY_KEYS)
        or not isinstance(sealed, Mapping)
        or sealed.get("run_id") != "live_20260826T223754Z"
        or sealed.get("observed_serial_baud") != STARTUP_DISCOVERY_HINT_BAUD
        or sealed.get("terminal_reported_last_confirmed_baud")
        != STARTUP_DISCOVERY_HINT_BAUD
        or sealed.get("seal_sha256")
        != "fe3da719d3ddc94ce79437622b6b8b9c545ffbcb9bdfec650da06658ce6606bc"
        or sealed.get("snapshot_digest")
        != "c577b7baef11707bed1256c2f1025d50c3026439a6737af99f8ceac045fc03fc"
        or not isinstance(subsequent, Mapping)
        or subsequent.get("run_id") != "live_20260827T014904Z"
        or subsequent.get("observed_serial_baud")
        != STARTUP_DISCOVERY_HINT_BAUD
        or subsequent.get("health_csv_sha256")
        != "a0ae39a38a1015abba6177f22d7dcf413457ece058f93e9bc2b578c2a50b7adc"
    ):
        raise ValueError("startup discovery hint/provenance contract differs")
    return dict(value)


def _continuation_contract(contract: Mapping[str, Any]) -> dict[str, Any]:
    value = contract.get("continuation")
    prefix = contract.get("prefix_validation")
    analysis = contract.get("composite_analysis")
    mapping = value.get("local_to_logical_segment_map", []) if isinstance(value, Mapping) else []
    if contract.get("contract_id") == (
        "otis_gnss_baud_envelope_characterization_resume_v1"
    ):
        expected_resume_mapping = [
            {"local_request_sequence": 1, "local_segment_id": "S01", "logical_segment_id": "S10"},
            {"local_request_sequence": 2, "local_segment_id": "S02", "logical_segment_id": "S11"},
        ]
        if (
            not isinstance(value, Mapping)
            or value.get("local_request_sequences") != [1, 2]
            or mapping != expected_resume_mapping
            or value.get("preferred_attachment_baud") != 115200
            or value.get("attachment_deadline_ms") != 120000
            or not isinstance(prefix, Mapping)
            or prefix.get("source_run_id") != "live_20260827T092556Z"
            or prefix.get("supervisor_events_sha256")
            != "9125fca098454ba379c14126d8b17e22b28db8b2649cb38781a09c32df2fef19"
            or contract.get("schedule", {}).get("total_confirmed_online_seconds")
            != 24600
        ):
            raise ValueError("resume provenance/scope contract differs")
        return dict(value)
    expected_mapping = [
        {
            "local_request_sequence": index,
            "local_segment_id": f"S{index:02d}",
            "logical_segment_id": f"S{index + 5:02d}",
        }
        for index in range(1, 7)
    ]
    schedule_segments = contract.get("schedule", {}).get("segments", [])
    if (
        contract.get("contract_id")
        != "otis_gnss_baud_envelope_characterization_continuation_v1"
        or contract.get("evidence_unit") != "composite_multi_artifact_evidence"
        or not isinstance(value, Mapping)
        or value.get("local_request_sequences") != [1, 2, 3, 4, 5, 6]
        or mapping != expected_mapping
        or [
            {
                "local_request_sequence": item.get("request_seq"),
                "local_segment_id": item.get("id"),
                "logical_segment_id": item.get("logical_segment_id"),
            }
            for item in schedule_segments
        ] != expected_mapping
        or value.get("reject_logical_segment_ids_from_live_command_surface")
        != ["S01", "S02", "S03", "S04", "S05"]
        or value.get("preferred_attachment_baud") != STARTUP_DISCOVERY_HINT_BAUD
        or value.get("attachment_deadline_ms") != 120000
        or not isinstance(prefix, Mapping)
        or prefix.get("source_run_id") != "live_20260826T223754Z"
        or prefix.get("original_contract_file_sha256")
        != "a03d06f0b55097314194973e2d0ef1d16b0e5c52e4fb8a4d31f23c91c7193e11"
        or prefix.get("original_contract_canonical_sha256")
        != "e43cc21f5d8c0dfba0366f06604ca816d417bf25542776fb45bec91d1a1bbf5d"
        or prefix.get("supervisor_events_sha256")
        != "b8dca60881836e99fc704bdc65c78b4fe5ea861ceea2c9a0b9661ff3a557161b"
        or prefix.get("s06_bridge_transition_confirmed_event_sequence") != 27
        or prefix.get("s06_ordinary_entry_completed_event_sequence") != 29
        or not isinstance(analysis, Mapping)
        or analysis.get("terminal")
        != "composite_multi_artifact_characterization_complete"
        or analysis.get("ordinary_programme_completion_terminal_permitted") is not False
        or analysis.get("capture_and_firmware_gap_between_prefix_and_continuation")
        is not True
        or analysis.get("counter_delta_rule")
        != "subtract_only_within_one_source_run_artifact_contract_and_counter_baseline"
        or analysis.get("row_source_fields")
        != [
            "source_run_id",
            "source_artifact_sha256",
            "source_contract_sha256",
            "source_firmware_sha256",
            "source_counter_baseline_id",
        ]
        or analysis.get("firmware_compatibility_rule")
        != "stratify_by_firmware_identity_unless_explicit_compatibility_proof_passes"
        or analysis.get("historical_global_terminal_preserved")
        != "programme_invalid_due_to_platform_or_evidence_failure"
        or analysis.get("historical_global_per_baud_classes_imported") is not False
    ):
        raise ValueError("continuation provenance/scope contract differs")
    return dict(value)

def _validate_historical_continuation_source(
    contract: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate reusable gates only against their retained original inputs."""
    _continuation_contract(contract)
    prefix = contract["prefix_validation"]
    if contract.get("contract_id") == (
        "otis_gnss_baud_envelope_characterization_resume_v1"
    ):
        run_dir = (ROOT / str(prefix["source_run_path"])).resolve()
        if run_dir != (LIVE_RUN_ROOT / str(prefix["source_run_id"])).resolve():
            raise ValueError("resume source run path differs")
        exact_artifacts = {
            "reports/activated_contract_v1.json": "activated_contract_sha256",
            "reports/activated_firmware_build_manifest_v1.json": "activated_firmware_build_manifest_sha256",
            "reports/gnss_baud_envelope_supervisor_events_v1.jsonl": "supervisor_events_sha256",
            "reports/gnss_baud_envelope_supervisor_state_v1.json": "supervisor_state_sha256",
            "reports/capture_segment_closure_v1.json": "capture_segment_closure_sha256",
            "reports/gnss_baud_envelope_abort_delivery_v1.json": "abort_delivery_sha256",
        }
        for relative, key in exact_artifacts.items():
            if _sha256_file(run_dir / relative) != prefix[key]:
                raise ValueError(f"resume source artifact identity differs: {relative}")
        events = [
            json.loads(line)
            for line in (run_dir / "reports/gnss_baud_envelope_supervisor_events_v1.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        ]
        terminal = events[-1]
        reused = [str(value) for value in prefix["reuse_completed_logical_phases"]]
        completed = [
            f"{event.get('logical_segment_id')}.{event.get('phase_id')}"
            for event in events
            if event.get("event") == "phase_completed"
        ]
        if (
            [int(event.get("event_sequence", -1)) for event in events]
            != list(range(1, len(events) + 1))
            or terminal.get("event_sequence") != prefix["failed_terminal_event_sequence"]
            or terminal.get("terminal") != prefix["failed_terminal"]
            or terminal.get("reason") != prefix["failed_reason"]
            or completed != reused
        ):
            raise ValueError("resume source terminal/completed phase prefix differs")
        return {
            "status": "validated_against_original_manifest_and_contract",
            "source_run_id": prefix["source_run_id"],
            "source_contract_sha256": prefix["activated_contract_sha256"],
            "source_artifact_sha256": prefix["supervisor_events_sha256"],
            "reused_logical_phases": reused,
            "interrupted_s10_soak_duration_credited": False,
            "historical_terminal_reused_as_programme_success": False,
            "counter_deltas_cross_source_artifacts": False,
        }
    source = {
        **prefix,
        "run_id": prefix["source_run_id"],
        "run_path": prefix["source_run_path"],
        "snapshot_digest": contract["startup_discovery"][
            "sealed_prior_physical_state"
        ]["snapshot_digest"],
        "original_contract_semantic_sha256": prefix[
            "original_contract_canonical_sha256"
        ],
        "s06_transition_confirmed_event_sequence": prefix[
            "s06_bridge_transition_confirmed_event_sequence"
        ],
    }
    run_dir = (ROOT / str(source["run_path"])).resolve()
    expected_run_dir = (
        LIVE_RUN_ROOT / str(source["run_id"])
    ).resolve()
    if run_dir != expected_run_dir or run_dir.is_symlink() or not run_dir.is_dir():
        raise ValueError("historical continuation source run path differs")
    evidence_manifest_path = run_dir / "evidence_manifest.json"
    if _sha256_file(evidence_manifest_path) != source["evidence_manifest_sha256"]:
        raise ValueError("historical evidence manifest identity differs")
    evidence_manifest = _read_object(evidence_manifest_path, "historical evidence manifest")
    if (
        evidence_manifest.get("run_id") != source["run_id"]
        or evidence_manifest.get("run_state") != "complete"
        or evidence_manifest.get("snapshot_digest") != source["snapshot_digest"]
    ):
        raise ValueError("historical evidence manifest semantics differ")
    manifest_entries = {
        str(entry.get("path")): entry
        for entry in evidence_manifest.get("artifacts", [])
        if isinstance(entry, Mapping)
    }
    expected_artifacts = {
        "run_manifest.json": source["run_manifest_sha256"],
        "reports/activated_contract_v1.json": source[
            "original_contract_file_sha256"
        ],
        "reports/activated_firmware_build_manifest_v1.json": source[
            "firmware_build_manifest_sha256"
        ],
        "reports/gnss_baud_envelope_supervisor_events_v1.jsonl": source[
            "supervisor_events_sha256"
        ],
        "reports/gnss_baud_envelope_supervisor_state_v1.json": source[
            "supervisor_state_sha256"
        ],
        "reports/gnss_baud_envelope_analysis_v1.json": source["analysis_sha256"],
    }
    for relative, expected_sha256 in expected_artifacts.items():
        entry = manifest_entries.get(relative)
        path = run_dir / relative
        if (
            not isinstance(entry, Mapping)
            or entry.get("sha256") != expected_sha256
            or _sha256_file(path) != expected_sha256
            or path.stat().st_size != entry.get("size_bytes")
        ):
            raise ValueError(f"historical artifact identity differs: {relative}")

    original_contract = _read_object(
        run_dir / "reports/activated_contract_v1.json", "historical contract"
    )
    if canonical_sha256(original_contract) != source["original_contract_semantic_sha256"]:
        raise ValueError("historical contract semantic identity differs")
    original_segments = {
        str(item.get("id")): item
        for item in original_contract.get("schedule", {}).get("segments", [])
        if isinstance(item, Mapping)
    }
    run_manifest = _read_object(run_dir / "run_manifest.json", "historical run manifest")
    if (
        run_manifest.get("run_id") != source["run_id"]
        or run_manifest.get("gnss_baud_envelope", {}).get("contract", {}).get(
            "sha256"
        ) != source["original_contract_file_sha256"]
        or run_manifest.get("firmware", {}).get("source_tree_identity")
        != source["firmware_source_sha256"]
        or run_manifest.get("firmware", {}).get("binary_sha256")
        != source["firmware_uf2_sha256"]
    ):
        raise ValueError("historical run manifest provenance differs")
    build_manifest = _read_object(
        run_dir / "reports/activated_firmware_build_manifest_v1.json",
        "historical firmware build manifest",
    )
    uf2_entries = [
        entry
        for entry in build_manifest.get("artifacts", [])
        if isinstance(entry, Mapping) and str(entry.get("name", "")).endswith(".uf2")
    ]
    if (
        build_manifest.get("provenance", {}).get("source", {}).get("sha256")
        != source["firmware_source_sha256"]
        or build_manifest.get("provenance", {}).get("configuration", {}).get(
            "sha256"
        ) != source["firmware_configuration_sha256"]
        or len(uf2_entries) != 1
        or uf2_entries[0].get("sha256") != source["firmware_uf2_sha256"]
    ):
        raise ValueError("historical firmware provenance differs")

    events_path = run_dir / "reports/gnss_baud_envelope_supervisor_events_v1.jsonl"
    events = [json.loads(line) for line in events_path.read_text(encoding="utf-8").splitlines()]
    sequences = [int(event.get("event_sequence", -1)) for event in events]
    if sequences != list(range(1, len(events) + 1)):
        raise ValueError("historical supervisor event sequence is not exact")
    if any(
        event.get("run_id") != source["run_id"]
        or event.get("contract_sha256")
        != source["original_contract_semantic_sha256"]
        for event in events
    ):
        raise ValueError("historical event provenance differs")
    by_sequence = {int(event["event_sequence"]): event for event in events}
    fault_delta_keys = {
        "bytes_dropped_before_retention",
        "hardware_overrun_count",
        "hardware_framing_count",
        "hardware_parity_count",
        "hardware_break_count",
        "overflow_count",
        "link_checksum_failure_count",
        "metadata_checksum_failure_count",
        "parser_drop_count",
        "truncated_count",
        "oversize_count",
        "metadata_hold_count",
        "capture_dropped_count",
        "pps_count_boundary_dropped_count",
        "shared_queue_corruption_count",
        "telemetry_dropped_count",
        "dual_core_partition_fault_count",
    }

    def validate_phase(event: Mapping[str, Any], segment: Mapping[str, Any], phase: Mapping[str, Any]) -> Mapping[str, Any]:
        required_ticks = int(phase["duration_s"]) * 16_000_000
        deltas = event.get("counter_deltas")
        metrics = event.get("metrics")
        started = by_sequence.get(int(event.get("event_sequence", -1)) - 1, {})
        if (
            event.get("event") != "phase_completed"
            or event.get("segment_id") != segment["id"]
            or event.get("phase_id") != phase["id"]
            or event.get("phase_kind") != phase["class"]
            or int(event.get("required_duration_s", -1)) != int(phase["duration_s"])
            or int(event.get("elapsed_ticks", -1)) < required_ticks
            or not isinstance(deltas, Mapping)
            or any(int(deltas.get(key, -1)) != 0 for key in fault_delta_keys)
            or not isinstance(metrics, Mapping)
            or metrics.get("identity_exact") is not True
            or metrics.get("configuration_exact") is not True
            or metrics.get("uart_isr_drain_complete_observed") is not True
            or started.get("event") != "phase_started"
            or started.get("segment_id") != segment["id"]
            or started.get("phase_id") != phase["id"]
            or started.get("baud") != event.get("baud")
            or started.get("baud_epoch") != event.get("baud_epoch")
            or started.get("online_start_ticks") != event.get("online_start_ticks")
        ):
            raise ValueError(
                f"historical phase completion gate differs: {segment['id']}.{phase['id']}"
            )
        return started

    segment_sources: list[dict[str, Any]] = []
    segment_gate_sources: list[dict[str, Any]] = []
    gate_sequences = source["completed_segment_gate_event_sequences"]
    for request_sequence, segment_id in enumerate(CONTINUATION_HISTORICAL_SEGMENTS, start=1):
        segment = original_segments.get(segment_id)
        gate = by_sequence.get(int(gate_sequences[segment_id]), {})
        confirmed = next(
            (
                event
                for event in events
                if event.get("event") == "transition_confirmed"
                and event.get("segment_id") == segment_id
            ),
            {},
        )
        if (
            not isinstance(segment, Mapping)
            or int(segment.get("request_seq", -1)) != request_sequence
            or confirmed.get("request_sequence") != request_sequence
            or confirmed.get("confirmed_baud") != segment.get("target_baud")
            or confirmed.get("identity_confirmed") is not True
            or confirmed.get("configuration_confirmed") is not True
            or confirmed.get("first_dependent_snapshot_bound") is not True
            or gate.get("event") != "segment_completed"
            or gate.get("segment_id") != segment_id
            or gate.get("baud") != segment.get("target_baud")
            or gate.get("confirmed_online_duration_s")
            != segment.get("confirmed_online_s")
        ):
            raise ValueError(f"historical segment gate differs: {segment_id}")
        phases = segment.get("phases", [])
        completed = [
            event
            for event in events
            if event.get("event") == "phase_completed"
            and event.get("segment_id") == segment_id
        ]
        if len(completed) != len(phases):
            raise ValueError(f"historical phase set differs: {segment_id}")
        for phase, event in zip(phases, completed, strict=True):
            started = validate_phase(event, segment, phase)
            segment_sources.append(
                {
                    "segment_id": segment_id,
                    "phase_id": phase["id"],
                    "source_run_id": source["run_id"],
                    "source_contract_sha256": source[
                        "original_contract_file_sha256"
                    ],
                    "source_firmware_sha256": source["firmware_uf2_sha256"],
                    "source_artifact_sha256": source["supervisor_events_sha256"],
                    "source_counter_baseline_id": (
                        f"{source['run_id']}:supervisor_events:"
                        f"{started['event_sequence']}->{event['event_sequence']}"
                    ),
                    "phase_started_event_sequence": started["event_sequence"],
                    "phase_completed_event_sequence": event["event_sequence"],
                }
            )
        segment_gate_sources.append(
            {
                "segment_id": segment_id,
                "source_run_id": source["run_id"],
                "source_artifact_sha256": source["supervisor_events_sha256"],
                "source_contract_sha256": source["original_contract_file_sha256"],
                "source_firmware_sha256": source["firmware_uf2_sha256"],
                "source_counter_baseline_id": (
                    f"{source['run_id']}:segment:{segment_id}:"
                    f"transition->{gate['event_sequence']}"
                ),
                "segment_completed_event_sequence": gate["event_sequence"],
            }
        )
    s06 = original_segments["S06"]
    transition = by_sequence.get(int(source["s06_transition_confirmed_event_sequence"]), {})
    phase = s06["phases"][0]
    phase_event = by_sequence.get(
        int(source["s06_ordinary_entry_completed_event_sequence"]), {}
    )
    if (
        transition.get("event") != "transition_confirmed"
        or transition.get("segment_id") != "S06"
        or transition.get("request_sequence") != 6
        or transition.get("confirmed_baud") != 57600
        or transition.get("identity_confirmed") is not True
        or transition.get("configuration_confirmed") is not True
        or transition.get("first_dependent_snapshot_bound") is not True
    ):
        raise ValueError("historical S06 transition gate differs")
    phase_started = validate_phase(phase_event, s06, phase)
    segment_sources.append(
        {
            "segment_id": "S06",
            "phase_id": "ordinary_entry",
            "source_run_id": source["run_id"],
            "source_contract_sha256": source["original_contract_file_sha256"],
            "source_firmware_sha256": source["firmware_uf2_sha256"],
            "source_artifact_sha256": source["supervisor_events_sha256"],
            "source_counter_baseline_id": (
                f"{source['run_id']}:supervisor_events:"
                f"{phase_started['event_sequence']}->{phase_event['event_sequence']}"
            ),
            "phase_started_event_sequence": phase_started["event_sequence"],
            "transition_confirmed_event_sequence": transition["event_sequence"],
            "phase_completed_event_sequence": phase_event["event_sequence"],
        }
    )
    state = _read_object(
        run_dir / "reports/gnss_baud_envelope_supervisor_state_v1.json",
        "historical supervisor state",
    )
    if [item.get("segment_id") for item in state.get("completed_segments", [])] != list(
        CONTINUATION_HISTORICAL_SEGMENTS
    ):
        raise ValueError("historical supervisor completed-segment ledger differs")
    return {
        "status": "validated_against_original_manifest_and_contract",
        "source_run_id": source["run_id"],
        "source_evidence_manifest_sha256": source["evidence_manifest_sha256"],
        "source_snapshot_digest": source["snapshot_digest"],
        "source_contract_sha256": source["original_contract_file_sha256"],
        "source_contract_semantic_sha256": source[
            "original_contract_semantic_sha256"
        ],
        "source_firmware_sha256": source["firmware_uf2_sha256"],
        "reused_phase_sources": segment_sources,
        "reused_completed_segment_sources": segment_gate_sources,
        "counter_deltas_cross_source_artifacts": False,
        "firmware_identity_stratification_required": True,
        "historical_terminal_reused_as_programme_success": False,
    }


def _continuation_bundle_binding(contract: Mapping[str, Any]) -> dict[str, Any]:
    continuation = _continuation_contract(contract)
    prefix_report = _validate_historical_continuation_source(contract)
    prefix = contract["prefix_validation"]
    attachment = {
        "preferred_baud": continuation["preferred_attachment_baud"],
        "allowed_bauds": list(continuation["attachment_baud_allowlist"]),
        "deadline_ms": continuation["attachment_deadline_ms"],
        "deadline_terminal": continuation["attachment_deadline_terminal"],
        "initial_confirmed_baud": contract["transition_policy"][
            "initial_confirmed_baud"
        ],
        "initial_baud_epoch": contract["transition_policy"]["initial_baud_epoch"],
        "programme_command_before_fresh_attachment_permitted": False,
        "hint_hit_request1_semantics": continuation[
            "hint_hit_request1_semantics"
        ],
        "hint_miss_request1_semantics": continuation[
            "hint_miss_request1_semantics"
        ],
        "no_identity_semantics": continuation["no_identity_semantics"],
    }
    if (
        attachment["initial_confirmed_baud"]
        != "fresh_attachment_baud_from_allowlist"
        or attachment["allowed_bauds"]
        != list(STARTUP_DISCOVERY_FALLBACK_SCAN_BAUDS)
        or attachment["deadline_ms"] != 120000
    ):
        raise ValueError("continuation dynamic attachment contract differs")
    return {
        "evidence_unit": contract["evidence_unit"],
        "prefix_validation": prefix_report,
        "prefix_source_hashes": {
            key: value
            for key, value in prefix.items()
            if key.endswith("_sha256") or key == "snapshot_digest"
        },
        "local_request_sequences": list(continuation["local_request_sequences"]),
        "local_to_logical_segment_map": [
            dict(item) for item in continuation["local_to_logical_segment_map"]
        ],
        "reject_logical_segment_ids_from_live_command_surface": list(
            continuation["reject_logical_segment_ids_from_live_command_surface"]
        ),
        "attachment": attachment,
        "total_confirmed_online_seconds": int(
            contract["schedule"]["total_confirmed_online_seconds"]
        ),
        "composite_terminal": contract["composite_analysis"]["terminal"],
        "ordinary_programme_completion_terminal_permitted": contract[
            "composite_analysis"
        ]["ordinary_programme_completion_terminal_permitted"],
    }


def _write_exclusive_json(path: Path, value: object) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    descriptor = os.open(path, flags, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def _git(args: Iterable[str]) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    return result.stdout.rstrip("\n")


def _source_state() -> dict[str, Any]:
    status = _git(["status", "--porcelain=v1", "--untracked-files=all"])
    diff = subprocess.run(
        ["git", "diff", "--binary", "--no-ext-diff"],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout
    return {
        "git_commit": _git(["rev-parse", "HEAD"]),
        "git_branch": _git(["branch", "--show-current"]),
        "dirty": bool(status),
        "status_porcelain": status.splitlines(),
        "status_sha256": sha256(status.encode("utf-8")).hexdigest(),
        "tracked_diff_sha256": sha256(diff).hexdigest(),
    }


def _source_bindings(
    profile_id: str = GNSS_BAUD_CONTINUATION_PROFILE_ID,
) -> list[dict[str, Any]]:
    sketch = ROOT / "firmware/arduino/otis_nano_rp2040_connect"
    paths = sorted(
        path
        for path in sketch.iterdir()
        if path.is_file() and path.suffix in {".h", ".cpp", ".ino", ".pio"}
    )
    paths.append(ROOT / "firmware/arduino/firmware_matrix.json")
    paths.append(
        ROOT / "profiles/qualification/otis_gnss_baud_envelope_characterization_v1.json"
    )
    if profile_id == GNSS_BAUD_CONTINUATION_PROFILE_ID:
        paths.append(
            ROOT
            / "profiles/qualification/otis_gnss_baud_envelope_characterization_continuation_v1.json"
        )
    elif profile_id == GNSS_BAUD_RESUME_PROFILE_ID:
        paths.extend(
            [
                ROOT
                / "profiles/qualification/otis_gnss_baud_envelope_characterization_continuation_v1.json",
                ROOT
                / "profiles/qualification/otis_gnss_baud_envelope_characterization_resume_v1.json",
            ]
        )
    elif profile_id != GNSS_BAUD_ENVELOPE_PROFILE_ID:
        _profile_spec(profile_id)
    return [_binding(path) for path in paths]


def _host_paths() -> list[Path]:
    """Freeze the complete in-repository Python runtime used by the campaign.

    Several capture and finalization modules load helpers lazily. Binding the
    package rather than a hand-maintained import subset prevents an otherwise
    exact candidate from silently acquiring an unbound transitive dependency.
    The two repository-level build/preflight tools remain explicit.
    """

    package_paths = sorted((ROOT / "host/otis_tools").glob("*.py"))
    extra_paths = [
        ROOT / "tools/firmware_matrix.py",
        ROOT / "tools/gnss_baud_characterization_preflight.py",
    ]
    paths = sorted({path.resolve() for path in [*package_paths, *extra_paths]})
    required = {
        str((ROOT / relative).resolve())
        for relative in REQUIRED_HOST_TOOL_PATHS
    }
    absent = sorted(required - {str(path) for path in paths})
    if absent:
        raise ValueError(
            "required campaign host tools are absent: " + ", ".join(absent)
        )
    return paths


def _host_bindings() -> list[dict[str, Any]]:
    return [_binding(path) for path in _host_paths()]


def _artifact_bindings(
    manifest_path: Path, manifest: Mapping[str, Any]
) -> list[dict[str, Any]]:
    entries = manifest.get("artifacts")
    if not isinstance(entries, list):
        raise ValueError("firmware build manifest has no artifact array")
    result: list[dict[str, Any]] = []
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ValueError("firmware artifact entry is not an object")
        path = manifest_path.parent / str(entry.get("name", ""))
        bound = _binding(path)
        if (
            bound["size_bytes"] != entry.get("size_bytes")
            or bound["sha256"] != entry.get("sha256")
        ):
            raise ValueError(f"firmware artifact differs from manifest: {path.name}")
        result.append(bound)
    suffixes = {Path(item["path"]).suffix for item in result}
    if suffixes != {".bin", ".elf", ".h", ".map", ".uf2"}:
        raise ValueError(f"firmware artifact suffix set differs: {sorted(suffixes)}")
    return sorted(result, key=lambda item: item["path"])


def _profile_spec(profile_id: str) -> dict[str, Any]:
    if profile_id == GNSS_BAUD_ENVELOPE_PROFILE_ID:
        return {
            "profile_id": profile_id,
            "contract_path": ROOT
            / "profiles/qualification/otis_gnss_baud_envelope_characterization_v1.json",
            "contract_sha256": ORIGINAL_CONTRACT_SHA256,
            "stage": GNSS_BAUD_ENVELOPE_STAGE,
            "evidence_epoch": GNSS_BAUD_ENVELOPE_EVIDENCE_EPOCH,
            "continuation": False,
        }
    if profile_id == GNSS_BAUD_CONTINUATION_PROFILE_ID:
        return {
            "profile_id": profile_id,
            "contract_path": ROOT
            / "profiles/qualification/otis_gnss_baud_envelope_characterization_continuation_v1.json",
            "contract_sha256": CONTINUATION_CONTRACT_SHA256,
            "stage": GNSS_BAUD_CONTINUATION_STAGE,
            "evidence_epoch": GNSS_BAUD_CONTINUATION_EVIDENCE_EPOCH,
            "continuation": True,
        }
    if profile_id == GNSS_BAUD_RESUME_PROFILE_ID:
        return {
            "profile_id": profile_id,
            "contract_path": ROOT
            / "profiles/qualification/otis_gnss_baud_envelope_characterization_resume_v1.json",
            "contract_sha256": RESUME_CONTRACT_SHA256,
            "stage": GNSS_BAUD_RESUME_STAGE,
            "evidence_epoch": GNSS_BAUD_RESUME_EVIDENCE_EPOCH,
            "continuation": True,
        }
    raise ValueError(f"unsupported GNSS baud-envelope profile: {profile_id}")


def _load_profile_contract(
    contract_path: Path, profile_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    spec = _profile_spec(profile_id)
    resolved = contract_path.resolve()
    if (
        resolved != Path(spec["contract_path"]).resolve()
        or _sha256_file(resolved) != spec["contract_sha256"]
    ):
        raise ValueError("candidate contract file identity differs for explicit profile")
    if spec["continuation"]:
        contract = _read_object(resolved, "continuation contract")
        _continuation_contract(contract)
    else:
        contract = load_contract(resolved)
    if contract.get("firmware_profile", {}).get("profile_id") != profile_id:
        raise ValueError("contract firmware profile differs from explicit profile")
    return contract, spec


def _profile_from_manifest(
    manifest: Mapping[str, Any], profile_id: str
) -> tuple[dict[str, Any], dict[str, Any]]:
    from tools.firmware_matrix import (
        configuration_hash,
        configuration_payload,
        load_matrix,
        source_input_hash,
    )

    provenance = manifest.get("provenance")
    if not isinstance(provenance, Mapping):
        raise ValueError("build provenance is absent")
    configuration = provenance.get("configuration")
    source = provenance.get("source")
    if not isinstance(configuration, Mapping) or not isinstance(source, Mapping):
        raise ValueError("build source/configuration provenance is absent")
    if configuration.get("profile_id") != profile_id:
        raise ValueError("build profile is not the exact GNSS characterization profile")
    defines = configuration.get("defines")
    if not isinstance(defines, Mapping):
        raise ValueError("build compile-time configuration is absent")
    matrix = load_matrix()
    profile = next(
        item for item in matrix["profiles"] if item["id"] == profile_id
    )
    expected_configuration = configuration_payload(matrix, profile)
    expected_configuration["sha256"] = configuration_hash(matrix, profile)
    if (
        dict(configuration) != expected_configuration
        or source.get("sha256") != source_input_hash()
        or not re.fullmatch(r"[0-9a-f]{40}", str(source.get("git_commit", "")))
    ):
        raise ValueError("build provenance differs from current exact profile/source")
    required_zero = (
        "OTIS_ENABLE_DAC_AD5693R",
        "OTIS_ENABLE_H1_DAC_SWEEP",
        "OTIS_ENABLE_CX317_BOUNDED_ACTIVE",
        "OTIS_ENABLE_CX318_STAGE4_PREMISE_SETUP",
        "OTIS_ENABLE_CX320_ACTIVE_HYBRID",
        "OTIS_ENABLE_CX321_ACTIVE_HYBRID",
        "OTIS_ENABLE_CX322_DIRECT_HYBRID",
        "OTIS_ENABLE_SUSTAINED_HYBRID_REGULATION",
    )
    if any(str(defines.get(name, "0")) != "0" for name in required_zero):
        raise ValueError("characterization build contains DAC/control authority")
    if str(defines.get("OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION")) != "1":
        raise ValueError("characterization transition selector is absent")
    if str(defines.get("OTIS_GNSS_UART_BAUD")) != "9600u":
        raise ValueError("characterization opening baud differs")
    startup_selectors = {
        STARTUP_DISCOVERY_HINT_DEFINE:
            defines.get(STARTUP_DISCOVERY_HINT_DEFINE),
        "OTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD":
            defines.get(
                "OTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD"
            ),
    }
    if profile_id in {GNSS_BAUD_CONTINUATION_PROFILE_ID, GNSS_BAUD_RESUME_PROFILE_ID}:
        expected_hint = int(
            _read_object(
                Path(_profile_spec(profile_id)["contract_path"]), "profile contract"
            )["startup_discovery"]["hint_baud"]
        )
        if startup_selectors != {
            STARTUP_DISCOVERY_HINT_DEFINE: f"{expected_hint}u",
            "OTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD": "1",
        }:
            raise ValueError("continuation startup discovery selectors differ")
    elif any(value is not None for value in startup_selectors.values()):
        raise ValueError("original build unexpectedly carries continuation selectors")
    return dict(configuration), dict(source)


def _validated_binary_contract(
    build_manifest: Mapping[str, Any],
    profile_id: str = GNSS_BAUD_CONTINUATION_PROFILE_ID,
) -> dict[str, Any]:
    binary_contract = build_manifest.get("gnss_binary_contract")
    spec = _profile_spec(profile_id)
    contract, _ = _load_profile_contract(Path(spec["contract_path"]), profile_id)
    continuation = bool(spec["continuation"])
    expected_startup_discovery = None
    expected_continuation = None
    if continuation:
        startup_discovery = _startup_discovery(contract)
        hint_baud = int(startup_discovery["hint_baud"])
        expected_startup_discovery = {
            "opening_target_baud": OPENING_TARGET_AND_RECOVERY_ANCHOR_BAUD,
            "recovery_anchor_baud": OPENING_TARGET_AND_RECOVERY_ANCHOR_BAUD,
            "hint_baud": hint_baud,
            "hint_define": STARTUP_DISCOVERY_HINT_DEFINE,
            "hint_define_value": f"{hint_baud}u",
            "retain_define": (
                "OTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD"
            ),
            "retain_define_value": "1",
            "provenance": startup_discovery,
        }
        expected_continuation = {
            "profile_id": profile_id,
            "retain_discovered_startup_baud": True,
            "provenance": contract["continuation"],
        }
    if (
        not isinstance(binary_contract, Mapping)
        or binary_contract.get("status") != "verified"
        or binary_contract.get("campaign_contract", {}).get("sha256")
        != spec["contract_sha256"]
        or binary_contract.get("startup_discovery")
        != expected_startup_discovery
        or binary_contract.get("continuation") != expected_continuation
    ):
        raise ValueError("build manifest lacks the exact GNSS binary contract")
    return dict(binary_contract)


def _environment() -> dict[str, Any]:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "freeze", "--all"],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    frozen = result.stdout.strip().splitlines()
    return {
        "python_executable": str(Path(sys.executable).resolve()),
        "python_version": sys.version,
        "pip_freeze": frozen,
        "pip_freeze_sha256": canonical_sha256(frozen),
        "host_platform": platform.platform(),
        "host_machine": platform.machine(),
        "host_python_implementation": platform.python_implementation(),
    }


def _run_manifest_template(
    *,
    contract_binding: Mapping[str, Any],
    firmware: Mapping[str, Any],
    profile_id: str,
    startup_discovery: Mapping[str, Any] | None = None,
    continuation: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    spec = _profile_spec(profile_id)
    files = default_csv_files()
    contracts = {
        str(entry["contract"]): int(str(entry["contract"]).rsplit("_v", 1)[1])
        for entry in files
    }
    programme = {
        "programme_id": PROGRAMME_ID,
        "profile_id": profile_id,
        "contract": dict(contract_binding),
        "physical_evidence": True,
    }
    if spec["continuation"]:
        if not isinstance(startup_discovery, Mapping) or not isinstance(
            continuation, Mapping
        ):
            raise ValueError("continuation run template lacks continuation bindings")
        programme["startup_discovery"] = dict(startup_discovery)
        programme["continuation"] = dict(continuation)
    return {
        "schema_version": 1,
        "template": True,
        "run_id": "<ACTIVATION_RUN_ID>",
        "stage": spec["stage"],
        "compatibility_floor": spec["evidence_epoch"],
        "board": "arduino_nano_rp2040_connect",
        "capture_mode": "continuous_physical_gnss_baud_envelope",
        "actionable": True,
        "actuation_authorized": False,
        "gnss_baud_envelope": programme,
        "firmware": {
            "name": "otis_nano_rp2040_connect",
            "version": EXPECTED_FIRMWARE_VERSION,
            "profile_id": profile_id,
            "source_revision": firmware["source_revision"],
            "source_tree_identity": firmware["source_tree_identity"],
            "binary_sha256": firmware["binary_sha256"],
            "build_provenance_required": True,
        },
        "host": {
            "serial_device": "<ACTIVATION_DEVICE>",
            "sole_serial_owner": True,
            "status_interval_s": 1,
            "normal_command_ingress": "timestamped_bounded_fifo",
            "priority_abort_ingress": "independent_fifo",
        },
        "domains": [
            {"name": "rp2040_timer0", "nominal_hz": 16000000},
            {"name": "rp2040_timer0_extended", "nominal_hz": 16000000},
            {"name": "host_monotonic_ns", "nominal_hz": 1000000000},
        ],
        "channels": [
            {"channel_id": 1, "role": "authoritative_d14_pps_reference"},
            {"channel_id": 2, "role": "authoritative_d8_count"},
        ],
        "contracts": contracts,
        "files": files,
        "expected_artifacts": [
            *(entry["path"] for entry in files if not entry.get("optional")),
            "raw/serial.log",
            *EVIDENCE_ARTIFACTS,
        ],
        "evidence_artifacts": list(EVIDENCE_ARTIFACTS),
        "authority": {
            "non_actuating": True,
            "dac_writes_permitted": 0,
            "control_arm_permitted": False,
            "d10_authority": False,
        },
    }


def create_candidate(
    *,
    contract_path: Path,
    build_manifest_path: Path,
    preflight_path: Path,
    operational_check_path: Path,
    output_path: Path,
    profile_id: str = GNSS_BAUD_ENVELOPE_PROFILE_ID,
    expected_usb_serial: str = EXPECTED_USB_SERIAL,
) -> dict[str, Any]:
    contract_path = contract_path.resolve()
    contract, spec = _load_profile_contract(contract_path, profile_id)
    transition_policy = contract["transition_policy"]
    startup_discovery = _startup_discovery(contract) if spec["continuation"] else None
    continuation = (
        _continuation_bundle_binding(contract) if spec["continuation"] else None
    )
    if transition_policy.get("initial_baud_epoch") != 1:
        raise ValueError("initial GNSS baud/epoch contract differs")
    if not spec["continuation"] and (
        transition_policy.get("initial_confirmed_baud") != 9600
        or contract.get("firmware_profile", {}).get("initial_baud") != 9600
    ):
        raise ValueError("original initial GNSS baud contract differs")

    build_manifest_path = build_manifest_path.resolve()
    build_manifest = _read_object(build_manifest_path, "build manifest")
    configuration, source = _profile_from_manifest(build_manifest, profile_id)
    binary_contract = _validated_binary_contract(build_manifest, profile_id)
    artifacts = _artifact_bindings(build_manifest_path, build_manifest)
    uf2 = next(item for item in artifacts if Path(item["path"]).suffix == ".uf2")

    preflight = _read_object(preflight_path.resolve(), "profile preflight")
    if (
        preflight.get("status") != "passed"
        or preflight.get("profile_id") != profile_id
        or preflight.get("contract", {}).get("sha256") != spec["contract_sha256"]
        or preflight.get("build_manifest", {}).get("sha256")
        != _sha256_file(build_manifest_path)
        or not all(preflight.get("checks", {}).values())
        or any(preflight.get("hardware_operations", {}).values())
    ):
        raise ValueError("profile preflight is not an exact no-I/O pass")

    operational = _read_object(
        operational_check_path.resolve(), "accelerated operational check"
    )
    expected_operational_terminal = (
        "multi_baud_characterization_continuation_complete"
        if spec["continuation"]
        else "multi_baud_characterization_complete"
    )
    if (
        operational.get("status") != "passed"
        or operational.get("programme_id") != PROGRAMME_ID
        or operational.get("contract_file_sha256") != spec["contract_sha256"]
        or any(operational.get("hardware_operations", {}).values())
        or operational.get("terminal", {}).get("terminal")
        != expected_operational_terminal
    ):
        raise ValueError("accelerated operational check is not an exact no-I/O pass")

    contract_binding = _binding(contract_path)
    firmware = {
        "profile_id": profile_id,
        "firmware_version": EXPECTED_FIRMWARE_VERSION,
        "source_revision": str(source.get("git_commit", "")),
        "source_tree_identity": str(source.get("sha256", "")),
        "build_profile": str(configuration["profile_id"]),
        "compile_time_configuration": dict(configuration),
        "build_manifest": _binding(build_manifest_path),
        "artifacts": artifacts,
        "binary_path": uf2["path"],
        "binary_sha256": uf2["sha256"],
        "binary_contract": dict(binary_contract),
    }
    template = _run_manifest_template(
        contract_binding=contract_binding,
        firmware=firmware,
        profile_id=profile_id,
        startup_discovery=startup_discovery,
        continuation=continuation,
    )
    payload: dict[str, Any] = {
        "schema_version": 1,
        "bundle_type": BUNDLE_TYPE,
        "tool": TOOL_ID,
        "programme_id": PROGRAMME_ID,
        "created_at_utc": _iso(_utc_now()),
        "effective": False,
        "physical_authority": False,
        "contract": contract_binding,
        "firmware": firmware,
        "source_state": _source_state(),
        "source_files": _source_bindings(profile_id),
        "host_tools": _host_bindings(),
        "preflight": _binding(preflight_path),
        "operational_check": _binding(operational_check_path),
        "expected_device": {
            "usb_serial": expected_usb_serial,
            "port_identity": f"usb_serial:{expected_usb_serial}",
            "firmware_profile_id": profile_id,
            "firmware_version": EXPECTED_FIRMWARE_VERSION,
            "gnss_identity": EXPECTED_GNSS_RELEASE,
            "gnss_configuration": EXPECTED_GNSS_CONFIGURATION,
            "initial_confirmed_baud": transition_policy["initial_confirmed_baud"],
            "initial_baud_epoch": 1,
        },
        "capture": {
            "status_interval_s": 1,
            "normal_fifo": "control/normal_commands.fifo",
            "priority_fifo": "control/emergency_abort.fifo",
            "stop_fifo": "control/programme_stop.fifo",
            "evidence_stale_after_ms": 5000,
            "minimum_free_bytes": 5 * 1024 * 1024 * 1024,
        },
        "command_table_sha256": contract["command_table"]["sha256"],
        "schedule": {
            "sha256": canonical_sha256(contract["schedule"]),
            "total_confirmed_online_seconds": int(
                contract["schedule"]["total_confirmed_online_seconds"]
            ),
            "segment_count": len(contract["schedule"]["segments"]),
            "maximum_transition_and_recovery_seconds": (
                len(contract["schedule"]["segments"])
                * int(transition_policy["serial_link_unrecoverable_deadline_ms"])
                // 1000
            ),
        },
        "stop_conditions": list(contract["programme_stop_conditions"]),
        "final_state": dict(contract["final_state"]),
        "run_manifest_template": template,
        "run_manifest_template_sha256": canonical_sha256(template),
        "environment": _environment(),
        "registration_index_path": str(validate_index_location(DEFAULT_INDEX)),
        "authority": {
            "activation_required": True,
            "flash_limit": 1,
            "live_run_limit": 1,
            "automatic_retry_runs": 0,
            "dac_writes_permitted": 0,
            "control_arm_permitted": False,
        },
    }
    if spec["continuation"]:
        payload["startup_discovery"] = startup_discovery
        payload["continuation"] = continuation
        payload["expected_device"].update(
            {
                "initial_confirmed_baud_allowlist": list(
                    continuation["attachment"]["allowed_bauds"]
                ),
                "attachment_deadline_ms": continuation["attachment"]["deadline_ms"],
                "programme_command_before_fresh_attachment_permitted": False,
                "opening_target_baud": OPENING_TARGET_AND_RECOVERY_ANCHOR_BAUD,
                "recovery_anchor_baud": OPENING_TARGET_AND_RECOVERY_ANCHOR_BAUD,
                "startup_discovery_hint_baud": int(startup_discovery["hint_baud"]),
            }
        )
    candidate = {**payload, "bundle_id": canonical_sha256(payload)}
    validate_candidate(candidate)
    _write_exclusive_json(output_path, candidate)
    return candidate


def _validate_candidate_original_legacy(
    candidate: Mapping[str, Any],
) -> dict[str, Any]:
    if set(candidate) != CANDIDATE_KEYS:
        raise ValueError("candidate bundle field set differs")
    if (
        candidate.get("schema_version") != 1
        or candidate.get("bundle_type") != BUNDLE_TYPE
        or candidate.get("tool") != TOOL_ID
        or candidate.get("programme_id") != PROGRAMME_ID
        or candidate.get("effective") is not False
        or candidate.get("physical_authority") is not False
    ):
        raise ValueError("candidate bundle identity or authority differs")
    unsigned = {key: value for key, value in candidate.items() if key != "bundle_id"}
    if candidate.get("bundle_id") != canonical_sha256(unsigned):
        raise ValueError("candidate bundle semantic identity differs")
    contract_path = _validate_binding(candidate["contract"], "contract")
    if _sha256_file(contract_path) != EXPECTED_CONTRACT_SHA256:
        raise ValueError("candidate contract identity differs")
    contract = load_contract(contract_path)
    startup_discovery = _startup_discovery(contract)
    if candidate.get("startup_discovery") != startup_discovery:
        raise ValueError("candidate startup discovery provenance differs")
    if candidate["source_files"] != _source_bindings():
        raise ValueError("candidate source-file set differs")
    for index, binding in enumerate(candidate["source_files"]):
        _validate_binding(binding, f"source file {index}")
    bound_host_paths = []
    for index, binding in enumerate(candidate["host_tools"]):
        bound_host_paths.append(
            _validate_binding(binding, f"host tool {index}")
        )
    if bound_host_paths != _host_paths():
        raise ValueError("candidate host-tool path set differs")
    firmware = candidate["firmware"]
    if (
        firmware.get("profile_id") != GNSS_BAUD_ENVELOPE_PROFILE_ID
        or firmware.get("firmware_version") != EXPECTED_FIRMWARE_VERSION
        or firmware.get("binary_sha256")
        != _sha256_file(Path(firmware.get("binary_path", "")))
    ):
        raise ValueError("candidate firmware identity differs")
    build_manifest_path = _validate_binding(
        firmware["build_manifest"], "build manifest"
    )
    build_manifest = _read_object(build_manifest_path, "build manifest")
    configuration, source = _profile_from_manifest(build_manifest)
    binary_contract = _validated_binary_contract(build_manifest)
    expected_artifacts = _artifact_bindings(build_manifest_path, build_manifest)
    expected_preflight_artifacts = sorted(
        (dict(entry) for entry in build_manifest["artifacts"]),
        key=lambda entry: Path(str(entry["name"])).suffix,
    )
    expected_uf2 = next(
        item for item in expected_artifacts if Path(item["path"]).suffix == ".uf2"
    )
    if (
        firmware.get("source_revision") != str(source.get("git_commit", ""))
        or firmware.get("source_tree_identity") != str(source.get("sha256", ""))
        or firmware.get("build_profile") != str(configuration["profile_id"])
        or firmware.get("compile_time_configuration") != configuration
        or firmware.get("artifacts") != expected_artifacts
        or firmware.get("binary_path") != expected_uf2["path"]
        or firmware.get("binary_sha256") != expected_uf2["sha256"]
        or firmware.get("binary_contract") != build_manifest.get(
            "gnss_binary_contract"
        )
    ):
        raise ValueError("candidate firmware does not match its build manifest")
    for index, binding in enumerate(firmware["artifacts"]):
        _validate_binding(binding, f"firmware artifact {index}")
    preflight_path = _validate_binding(candidate["preflight"], "preflight")
    preflight = _read_object(preflight_path, "profile preflight")
    preflight_checks = preflight.get("checks")
    preflight_hardware = preflight.get("hardware_operations")
    expected_preflight_checks = {
        "frozen_contract_identity",
        "exact_profile_and_current_source_identity",
        "no_dac_or_control_authority",
        "generated_profile_header_retained",
        "startup_discovery_hint_bound_to_sealed_observed_baud",
        "five_packet_binary_contract",
        "D14_D8_topology_source_and_binary",
        "memory_budget_within_bound",
        "all_artifact_hashes_and_sizes",
        "physical_authority_false",
    }
    expected_preflight_hardware = {
        "serial_devices_opened": 0,
        "bytes_transmitted": 0,
        "firmware_flashes": 0,
        "board_resets": 0,
        "dac_writes": 0,
        "receiver_baud_changes": 0,
    }
    if (
        preflight.get("schema_version") != 1
        or preflight.get("tool")
        != "otis_gnss_baud_characterization_profile_preflight_v1"
        or preflight.get("status") != "passed"
        or preflight.get("programme_id") != PROGRAMME_ID
        or preflight.get("profile_id") != GNSS_BAUD_ENVELOPE_PROFILE_ID
        or preflight.get("contract", {}).get("sha256")
        != EXPECTED_CONTRACT_SHA256
        or preflight.get("build_manifest", {}).get("sha256")
        != _sha256_file(build_manifest_path)
        or not isinstance(preflight_checks, Mapping)
        or set(preflight_checks) != expected_preflight_checks
        or not all(preflight_checks.values())
        or preflight_hardware != expected_preflight_hardware
        or preflight.get("configuration_sha256") != configuration["sha256"]
        or preflight.get("source_sha256") != source["sha256"]
        or preflight.get("binary_contract") != binary_contract
        or preflight.get("artifacts") != expected_preflight_artifacts
        or preflight.get("startup_discovery") != startup_discovery
    ):
        raise ValueError("candidate preflight semantics differ")
    operational_path = _validate_binding(
        candidate["operational_check"], "operational check"
    )
    operational = _read_object(operational_path, "operational check")
    operational_hardware = operational.get("hardware_operations")
    mutations = operational.get("analyzer_mutation_regressions")
    obstruction = operational.get("transport_obstruction")
    rotation = operational.get("atomic_rotation")
    recovery = operational.get("recovery_branches")
    expected_mutations = (
        {"continuation_source_and_schedule_binding"}
        if spec["continuation"]
        else {
            "invalid_final_state",
            "negative_transition_milestone",
            "peak_cadence_and_tail_identity",
            "phase_order_or_transition_binding",
        }
    )
    expected_terminal = (
        "multi_baud_characterization_continuation_complete"
        if spec["continuation"]
        else "multi_baud_characterization_complete"
    )
    expected_rate_local_fault_continued = (
        False if profile_id == GNSS_BAUD_RESUME_PROFILE_ID else True
    )
    terminal = operational.get("terminal")
    if (
        operational.get("schema_version") != 1
        or operational.get("tool")
        != "otis_gnss_baud_envelope_accelerated_operational_check_v1"
        or operational.get("status") != "passed"
        or operational.get("programme_id") != PROGRAMME_ID
        or operational.get("contract_file_sha256") != EXPECTED_CONTRACT_SHA256
        or operational_hardware
        != {
            "physical_serial_opens": 0,
            "firmware_flashes": 0,
            "board_resets": 0,
            "receiver_writes": 0,
            "dac_writes": 0,
        }
        or not isinstance(mutations, Mapping)
        or set(mutations) != expected_mutations
        or not all(mutations.values())
        or not isinstance(obstruction, Mapping)
        or obstruction.get("priority_abort_observed_in_capture") is not True
        or obstruction.get("sole_serial_owner_verified") is not True
        or obstruction.get("sole_serial_owner_verified_after_resume") is not True
        or obstruction.get("owner_pid_unchanged_across_obstruction") is not True
        or obstruction.get("capture_resumed") is not True
        or not isinstance(rotation, Mapping)
        or rotation.get("status") != "completed"
        or rotation.get("serial_reopened") is not False
        or not isinstance(recovery, Mapping)
        or recovery.get("recovery_at_other_baud") is not True
        or recovery.get("five_rate_unrecoverable_terminal", {}).get("terminal")
        != "serial_link_unrecoverable"
        or recovery.get("d14_d8_noninterference_terminal", {}).get("reason")
        != "d14_d8_capture_loss"
        or recovery.get("idempotent_duplicate_result") is not True
        or operational.get("temporary_registration_valid") is not True
        or operational.get("rate_local_fault_continued")
        is not expected_rate_local_fault_continued
        or not isinstance(terminal, Mapping)
        or terminal.get("terminal")
        != "multi_baud_characterization_complete"
        or terminal.get("last_confirmed_baud") != 9600
        or terminal.get("final_identity_confirmed") is not True
        or terminal.get("final_configuration_confirmed") is not True
        or terminal.get("final_metadata_requalified") is not True
    ):
        raise ValueError("candidate operational-check semantics differ")
    expected = candidate["expected_device"]
    if (
        expected.get("firmware_profile_id") != GNSS_BAUD_ENVELOPE_PROFILE_ID
        or expected.get("firmware_version") != EXPECTED_FIRMWARE_VERSION
        or expected.get("initial_confirmed_baud")
        != contract["transition_policy"]["initial_confirmed_baud"]
        or expected.get("initial_baud_epoch")
        != contract["transition_policy"]["initial_baud_epoch"]
        or expected.get("opening_target_baud")
        != startup_discovery["opening_target_baud"]
        or expected.get("recovery_anchor_baud")
        != startup_discovery["recovery_anchor_baud"]
        or expected.get("startup_discovery_hint_baud")
        != startup_discovery["hint_baud"]
        or expected.get("gnss_identity") != EXPECTED_GNSS_RELEASE
        or expected.get("gnss_configuration") != EXPECTED_GNSS_CONFIGURATION
        or expected.get("port_identity")
        != f"usb_serial:{expected.get('usb_serial')}"
    ):
        raise ValueError("candidate expected-device identity differs")
    if candidate.get("command_table_sha256") != contract["command_table"]["sha256"]:
        raise ValueError("candidate command table identity differs")
    expected_schedule = {
        "sha256": canonical_sha256(contract["schedule"]),
        "total_confirmed_online_seconds": int(
            contract["schedule"]["total_confirmed_online_seconds"]
        ),
        "segment_count": len(contract["schedule"]["segments"]),
        "maximum_transition_and_recovery_seconds": (
            len(contract["schedule"]["segments"])
            * int(
                contract["transition_policy"][
                    "serial_link_unrecoverable_deadline_ms"
                ]
            )
            // 1000
        ),
    }
    if candidate.get("schedule") != expected_schedule:
        raise ValueError("candidate schedule binding differs from contract")
    if candidate.get("stop_conditions") != list(
        contract["programme_stop_conditions"]
    ):
        raise ValueError("candidate stop conditions differ from contract")
    if candidate.get("final_state") != dict(contract["final_state"]):
        raise ValueError("candidate final state differs from contract")
    if candidate.get("capture") != {
        "status_interval_s": 1,
        "normal_fifo": "control/normal_commands.fifo",
        "priority_fifo": "control/emergency_abort.fifo",
        "stop_fifo": "control/programme_stop.fifo",
        "evidence_stale_after_ms": 5000,
        "minimum_free_bytes": 5 * 1024 * 1024 * 1024,
    }:
        raise ValueError("candidate capture contract differs")
    template = candidate["run_manifest_template"]
    if candidate.get("run_manifest_template_sha256") != canonical_sha256(template):
        raise ValueError("run-manifest template identity differs")
    if (
        template != _run_manifest_template(
            contract_binding=candidate["contract"],
            firmware=firmware,
            startup_discovery=startup_discovery,
        )
        or
        template.get("stage") != GNSS_BAUD_ENVELOPE_STAGE
        or template.get("compatibility_floor")
        != GNSS_BAUD_ENVELOPE_EVIDENCE_EPOCH
        or template.get("actuation_authorized") is not False
        or template.get("files") != default_csv_files()
        or template.get("expected_artifacts")
        != [
            *(
                entry["path"]
                for entry in default_csv_files()
                if not entry.get("optional")
            ),
            "raw/serial.log",
            *EVIDENCE_ARTIFACTS,
        ]
        or template.get("evidence_artifacts") != list(EVIDENCE_ARTIFACTS)
        or template.get("contracts")
        != {
            str(entry["contract"]): int(
                str(entry["contract"]).rsplit("_v", 1)[1]
            )
            for entry in default_csv_files()
        }
    ):
        raise ValueError("run-manifest template semantics differ")
    if candidate.get("environment") != _environment():
        raise ValueError("candidate host dependency environment changed")
    authority = candidate["authority"]
    if authority != {
        "activation_required": True,
        "flash_limit": 1,
        "live_run_limit": 1,
        "automatic_retry_runs": 0,
        "dac_writes_permitted": 0,
        "control_arm_permitted": False,
    }:
        raise ValueError("candidate authority envelope differs")
    registration_index = validate_index_location(
        Path(str(candidate["registration_index_path"]))
    )
    if registration_index != validate_index_location(DEFAULT_INDEX):
        raise ValueError("candidate evidence-index location differs")
    return dict(candidate)


def _validate_candidate_dual(candidate: Mapping[str, Any]) -> dict[str, Any]:
    firmware = candidate.get("firmware")
    if not isinstance(firmware, Mapping):
        raise ValueError("candidate firmware binding is absent")
    profile_id = str(firmware.get("profile_id", ""))
    spec = _profile_spec(profile_id)
    expected_keys = (
        CONTINUATION_CANDIDATE_KEYS
        if spec["continuation"]
        else ORIGINAL_CANDIDATE_KEYS
    )
    if set(candidate) != expected_keys:
        raise ValueError("candidate bundle field set differs")
    if (
        candidate.get("schema_version") != 1
        or candidate.get("bundle_type") != BUNDLE_TYPE
        or candidate.get("tool") != TOOL_ID
        or candidate.get("programme_id") != PROGRAMME_ID
        or candidate.get("effective") is not False
        or candidate.get("physical_authority") is not False
    ):
        raise ValueError("candidate bundle identity or authority differs")
    unsigned = {key: value for key, value in candidate.items() if key != "bundle_id"}
    if candidate.get("bundle_id") != canonical_sha256(unsigned):
        raise ValueError("candidate bundle semantic identity differs")

    contract_path = _validate_binding(candidate["contract"], "contract")
    contract, _ = _load_profile_contract(contract_path, profile_id)
    startup_discovery = None
    continuation = None
    if spec["continuation"]:
        startup_discovery = _startup_discovery(contract)
        continuation = _continuation_bundle_binding(contract)
        if (
            candidate.get("startup_discovery") != startup_discovery
            or candidate.get("continuation") != continuation
        ):
            raise ValueError("candidate continuation provenance differs")

    if candidate.get("source_files") != _source_bindings(profile_id):
        raise ValueError("candidate source-file set differs")
    for index, binding in enumerate(candidate["source_files"]):
        _validate_binding(binding, f"source file {index}")
    bound_host_paths = [
        _validate_binding(binding, f"host tool {index}")
        for index, binding in enumerate(candidate["host_tools"])
    ]
    if bound_host_paths != _host_paths():
        raise ValueError("candidate host-tool path set differs")

    if (
        firmware.get("firmware_version") != EXPECTED_FIRMWARE_VERSION
        or firmware.get("binary_sha256")
        != _sha256_file(Path(str(firmware.get("binary_path", ""))))
    ):
        raise ValueError("candidate firmware identity differs")
    build_manifest_path = _validate_binding(
        firmware["build_manifest"], "build manifest"
    )
    build_manifest = _read_object(build_manifest_path, "build manifest")
    configuration, source = _profile_from_manifest(build_manifest, profile_id)
    binary_contract = _validated_binary_contract(build_manifest, profile_id)
    expected_artifacts = _artifact_bindings(build_manifest_path, build_manifest)
    expected_uf2 = next(
        item for item in expected_artifacts if Path(item["path"]).suffix == ".uf2"
    )
    if (
        firmware.get("source_revision") != str(source.get("git_commit", ""))
        or firmware.get("source_tree_identity") != str(source.get("sha256", ""))
        or firmware.get("build_profile") != profile_id
        or firmware.get("compile_time_configuration") != configuration
        or firmware.get("artifacts") != expected_artifacts
        or firmware.get("binary_path") != expected_uf2["path"]
        or firmware.get("binary_sha256") != expected_uf2["sha256"]
        or firmware.get("binary_contract") != binary_contract
    ):
        raise ValueError("candidate firmware does not match its exact build manifest")
    for index, binding in enumerate(firmware["artifacts"]):
        _validate_binding(binding, f"firmware artifact {index}")

    preflight_path = _validate_binding(candidate["preflight"], "preflight")
    preflight = _read_object(preflight_path, "profile preflight")
    expected_checks = {
        "frozen_contract_identity",
        "exact_profile_and_current_source_identity",
        "no_dac_or_control_authority",
        "generated_profile_header_retained",
        "five_packet_binary_contract",
        "D14_D8_topology_source_and_binary",
        "memory_budget_within_bound",
        "all_artifact_hashes_and_sizes",
        "physical_authority_false",
    }
    if spec["continuation"]:
        expected_checks.add("startup_discovery_hint_bound_to_sealed_observed_baud")
    expected_preflight_artifacts = sorted(
        (dict(entry) for entry in build_manifest["artifacts"]),
        key=lambda entry: Path(str(entry["name"])).suffix,
    )
    expected_hardware = {
        "serial_devices_opened": 0,
        "bytes_transmitted": 0,
        "firmware_flashes": 0,
        "board_resets": 0,
        "dac_writes": 0,
        "receiver_baud_changes": 0,
    }
    checks = preflight.get("checks")
    if (
        preflight.get("schema_version") != 1
        or preflight.get("tool")
        != "otis_gnss_baud_characterization_profile_preflight_v1"
        or preflight.get("status") != "passed"
        or preflight.get("programme_id") != PROGRAMME_ID
        or preflight.get("profile_id") != profile_id
        or preflight.get("contract", {}).get("sha256")
        != spec["contract_sha256"]
        or preflight.get("build_manifest", {}).get("sha256")
        != _sha256_file(build_manifest_path)
        or not isinstance(checks, Mapping)
        or set(checks) != expected_checks
        or not all(checks.values())
        or preflight.get("hardware_operations") != expected_hardware
        or preflight.get("configuration_sha256") != configuration["sha256"]
        or preflight.get("source_sha256") != source["sha256"]
        or preflight.get("binary_contract") != binary_contract
        or preflight.get("artifacts") != expected_preflight_artifacts
        or (
            spec["continuation"]
            and preflight.get("startup_discovery") != startup_discovery
        )
        or (
            not spec["continuation"] and "startup_discovery" in preflight
        )
    ):
        raise ValueError("candidate preflight semantics differ")

    operational_path = _validate_binding(
        candidate["operational_check"], "operational check"
    )
    operational = _read_object(operational_path, "operational check")
    terminal = operational.get("terminal", {})
    mutations = operational.get("analyzer_mutation_regressions")
    obstruction = operational.get("transport_obstruction")
    rotation = operational.get("atomic_rotation")
    recovery = operational.get("recovery_branches")
    expected_mutations = (
        {"continuation_source_and_schedule_binding"}
        if spec["continuation"]
        else {
            "invalid_final_state",
            "negative_transition_milestone",
            "peak_cadence_and_tail_identity",
            "phase_order_or_transition_binding",
        }
    )
    expected_terminal = (
        "multi_baud_characterization_continuation_complete"
        if spec["continuation"]
        else "multi_baud_characterization_complete"
    )
    expected_rate_local_fault_continued = (
        False if profile_id == GNSS_BAUD_RESUME_PROFILE_ID else True
    )
    if (
        operational.get("schema_version") != 1
        or operational.get("tool")
        != "otis_gnss_baud_envelope_accelerated_operational_check_v1"
        or operational.get("status") != "passed"
        or operational.get("programme_id") != PROGRAMME_ID
        or operational.get("contract_file_sha256") != spec["contract_sha256"]
        or operational.get("hardware_operations")
        != {
            "physical_serial_opens": 0,
            "firmware_flashes": 0,
            "board_resets": 0,
            "receiver_writes": 0,
            "dac_writes": 0,
        }
        or not isinstance(mutations, Mapping)
        or set(mutations) != expected_mutations
        or not all(mutations.values())
        or not isinstance(obstruction, Mapping)
        or obstruction.get("priority_abort_observed_in_capture") is not True
        or obstruction.get("sole_serial_owner_verified") is not True
        or obstruction.get("sole_serial_owner_verified_after_resume") is not True
        or obstruction.get("owner_pid_unchanged_across_obstruction") is not True
        or obstruction.get("capture_resumed") is not True
        or not isinstance(rotation, Mapping)
        or rotation.get("status") != "completed"
        or rotation.get("serial_reopened") is not False
        or not isinstance(recovery, Mapping)
        or recovery.get("recovery_at_other_baud") is not True
        or recovery.get("five_rate_unrecoverable_terminal", {}).get("terminal")
        != "serial_link_unrecoverable"
        or recovery.get("d14_d8_noninterference_terminal", {}).get("reason")
        != "d14_d8_capture_loss"
        or recovery.get("idempotent_duplicate_result") is not True
        or operational.get("temporary_registration_valid") is not True
        or operational.get("rate_local_fault_continued")
        is not expected_rate_local_fault_continued
        or terminal.get("terminal") != expected_terminal
        or terminal.get("last_confirmed_baud") != 9600
        or terminal.get("final_identity_confirmed") is not True
        or terminal.get("final_configuration_confirmed") is not True
        or terminal.get("final_metadata_requalified") is not True
    ):
        raise ValueError("candidate operational-check semantics differ")

    expected_device = {
        "usb_serial": candidate["expected_device"].get("usb_serial"),
        "port_identity": (
            f"usb_serial:{candidate['expected_device'].get('usb_serial')}"
        ),
        "firmware_profile_id": profile_id,
        "firmware_version": EXPECTED_FIRMWARE_VERSION,
        "gnss_identity": EXPECTED_GNSS_RELEASE,
        "gnss_configuration": EXPECTED_GNSS_CONFIGURATION,
        "initial_confirmed_baud": contract["transition_policy"][
            "initial_confirmed_baud"
        ],
        "initial_baud_epoch": contract["transition_policy"]["initial_baud_epoch"],
    }
    if spec["continuation"]:
        expected_device.update(
            {
                "initial_confirmed_baud_allowlist": continuation["attachment"][
                    "allowed_bauds"
                ],
                "attachment_deadline_ms": continuation["attachment"]["deadline_ms"],
                "programme_command_before_fresh_attachment_permitted": False,
                "opening_target_baud": startup_discovery["opening_target_baud"],
                "recovery_anchor_baud": startup_discovery["recovery_anchor_baud"],
                "startup_discovery_hint_baud": startup_discovery["hint_baud"],
            }
        )
    if candidate.get("expected_device") != expected_device:
        raise ValueError("candidate expected-device identity differs")

    expected_schedule = {
        "sha256": canonical_sha256(contract["schedule"]),
        "total_confirmed_online_seconds": int(
            contract["schedule"]["total_confirmed_online_seconds"]
        ),
        "segment_count": len(contract["schedule"]["segments"]),
        "maximum_transition_and_recovery_seconds": (
            len(contract["schedule"]["segments"])
            * int(contract["transition_policy"]["serial_link_unrecoverable_deadline_ms"])
            // 1000
        ),
    }
    if (
        candidate.get("command_table_sha256")
        != contract["command_table"]["sha256"]
        or candidate.get("schedule") != expected_schedule
        or candidate.get("stop_conditions")
        != list(contract["programme_stop_conditions"])
        or candidate.get("final_state") != dict(contract["final_state"])
    ):
        raise ValueError("candidate contract-derived programme binding differs")
    if candidate.get("capture") != {
        "status_interval_s": 1,
        "normal_fifo": "control/normal_commands.fifo",
        "priority_fifo": "control/emergency_abort.fifo",
        "stop_fifo": "control/programme_stop.fifo",
        "evidence_stale_after_ms": 5000,
        "minimum_free_bytes": 5 * 1024 * 1024 * 1024,
    }:
        raise ValueError("candidate capture contract differs")
    template = _run_manifest_template(
        contract_binding=candidate["contract"],
        firmware=firmware,
        profile_id=profile_id,
        startup_discovery=startup_discovery,
        continuation=continuation,
    )
    if (
        candidate.get("run_manifest_template") != template
        or candidate.get("run_manifest_template_sha256")
        != canonical_sha256(template)
    ):
        raise ValueError("run-manifest template semantics differ")
    if candidate.get("environment") != _environment():
        raise ValueError("candidate host dependency environment changed")
    if candidate.get("authority") != {
        "activation_required": True,
        "flash_limit": 1,
        "live_run_limit": 1,
        "automatic_retry_runs": 0,
        "dac_writes_permitted": 0,
        "control_arm_permitted": False,
    }:
        raise ValueError("candidate authority envelope differs")
    if validate_index_location(
        Path(str(candidate["registration_index_path"]))
    ) != validate_index_location(DEFAULT_INDEX):
        raise ValueError("candidate evidence-index location differs")
    return dict(candidate)


# The dual validator supersedes the original-profile-only implementation above.
validate_candidate = _validate_candidate_dual


def create_activation(
    *,
    candidate_path: Path,
    output_path: Path,
    operator: str,
    authority_source: str,
    run_id: str,
    run_dir: Path,
    device: Path,
    wall_hours: float = 15.0,
) -> dict[str, Any]:
    candidate_path = candidate_path.resolve()
    candidate = validate_candidate(_read_object(candidate_path, "candidate bundle"))
    profile_id = str(candidate["firmware"]["profile_id"])
    spec = _profile_spec(profile_id)
    if not operator.strip() or not authority_source.strip():
        raise ValueError("activation requires operator and authority source")
    if not LIVE_RUN_ID.fullmatch(run_id):
        raise ValueError("live run id must be live_YYYYMMDDTHHMMSSZ")
    resolved_run = run_dir.resolve()
    if resolved_run != (LIVE_RUN_ROOT / run_id).resolve():
        raise ValueError("activation run directory is outside the exact live root")
    if resolved_run.exists():
        raise FileExistsError("activation run directory already exists")
    resolved_device = device.resolve()
    if resolved_device.parent != Path("/dev") or not resolved_device.name.startswith("cu."):
        raise ValueError("activation device must be one explicit /dev/cu.* path")
    if wall_hours < 12.5 or wall_hours > 24.0:
        raise ValueError("activation wall horizon must be in 12.5..24 hours")
    now = _utc_now()
    payload: dict[str, Any] = {
        "schema_version": 1,
        "activation_type": ACTIVATION_TYPE,
        "bundle_id": candidate["bundle_id"],
        "bundle_sha256": _sha256_file(candidate_path),
        "effective": True,
        "physical_authority": True,
        "activated_at_utc": _iso(now),
        "operator": operator.strip(),
        "authority_source": authority_source.strip(),
        "run_id": run_id,
        "run_dir": str(resolved_run),
        "device": str(resolved_device),
        "expected_device_identity": candidate["expected_device"]["usb_serial"],
        "wall_deadline_utc": _iso(now + timedelta(hours=wall_hours)),
        "abort_deadline_ms": 2000,
        "flash_limit": 1,
        "live_run_limit": 1,
        "dac_writes_permitted": 0,
        "control_arm_permitted": False,
        "registration_index_path": candidate["registration_index_path"],
    }
    if spec["continuation"]:
        payload.update(
            {
                "startup_discovery": candidate["startup_discovery"],
                "continuation": candidate["continuation"],
                "schedule": candidate["schedule"],
            }
        )
    activation = {**payload, "activation_id": canonical_sha256(payload)}
    validate_activation(candidate_path, candidate, activation)
    _write_exclusive_json(output_path, activation)
    return activation


def validate_activation(
    candidate_path: Path,
    candidate: Mapping[str, Any],
    activation: Mapping[str, Any],
) -> dict[str, Any]:
    firmware = candidate.get("firmware")
    if not isinstance(firmware, Mapping):
        raise ValueError("candidate firmware binding is absent")
    spec = _profile_spec(str(firmware.get("profile_id", "")))
    expected_keys = (
        CONTINUATION_ACTIVATION_KEYS
        if spec["continuation"]
        else ORIGINAL_ACTIVATION_KEYS
    )
    if set(activation) != expected_keys:
        raise ValueError("activation field set differs")
    unsigned = {
        key: value for key, value in activation.items() if key != "activation_id"
    }
    if activation.get("activation_id") != canonical_sha256(unsigned):
        raise ValueError("activation semantic identity differs")
    if (
        activation.get("schema_version") != 1
        or activation.get("activation_type") != ACTIVATION_TYPE
        or activation.get("bundle_id") != candidate.get("bundle_id")
        or activation.get("bundle_sha256") != _sha256_file(candidate_path)
        or activation.get("effective") is not True
        or activation.get("physical_authority") is not True
        or activation.get("expected_device_identity")
        != candidate["expected_device"]["usb_serial"]
        or activation.get("flash_limit") != 1
        or activation.get("live_run_limit") != 1
        or activation.get("dac_writes_permitted") != 0
        or activation.get("control_arm_permitted") is not False
        or activation.get("abort_deadline_ms") != 2000
        or activation.get("registration_index_path")
        != candidate.get("registration_index_path")
        or not isinstance(activation.get("operator"), str)
        or not str(activation.get("operator", "")).strip()
        or activation.get("operator") != str(activation.get("operator")).strip()
        or not isinstance(activation.get("authority_source"), str)
        or not str(activation.get("authority_source", "")).strip()
        or activation.get("authority_source")
        != str(activation.get("authority_source")).strip()
    ):
        raise ValueError("activation authority or bundle binding differs")
    if spec["continuation"] and (
        activation.get("startup_discovery") != candidate.get("startup_discovery")
        or activation.get("continuation") != candidate.get("continuation")
        or activation.get("schedule") != candidate.get("schedule")
        or activation.get("startup_discovery", {}).get("hint_baud")
        != candidate.get("startup_discovery", {}).get("hint_baud")
        or activation.get("continuation", {}).get("attachment", {}).get(
            "initial_confirmed_baud"
        ) != "fresh_attachment_baud_from_allowlist"
        or activation.get("continuation", {}).get("attachment", {}).get(
            "allowed_bauds"
        ) != list(STARTUP_DISCOVERY_FALLBACK_SCAN_BAUDS)
        or activation.get("schedule", {}).get("total_confirmed_online_seconds")
        != candidate.get("schedule", {}).get("total_confirmed_online_seconds")
    ):
        raise ValueError("activation continuation binding differs")
    validate_index_location(Path(str(activation["registration_index_path"])))
    run_id = str(activation.get("run_id", ""))
    run_dir = Path(str(activation.get("run_dir", ""))).resolve()
    if (
        not LIVE_RUN_ID.fullmatch(run_id)
        or run_dir != (LIVE_RUN_ROOT / run_id).resolve()
    ):
        raise ValueError("activation run identity differs")
    device = Path(str(activation.get("device", ""))).resolve()
    if device.parent != Path("/dev") or not device.name.startswith("cu."):
        raise ValueError("activation device identity differs")
    try:
        activated_at = datetime.fromisoformat(
            str(activation["activated_at_utc"]).replace("Z", "+00:00")
        )
        deadline = datetime.fromisoformat(
            str(activation["wall_deadline_utc"]).replace("Z", "+00:00")
        )
    except (KeyError, ValueError) as exc:
        raise ValueError("activation UTC horizon is malformed") from exc
    if (
        activated_at.tzinfo is None
        or deadline.tzinfo is None
        or activated_at.utcoffset() != timedelta(0)
        or deadline.utcoffset() != timedelta(0)
    ):
        raise ValueError("activation horizon must use explicit UTC")
    horizon = deadline - activated_at
    if horizon < timedelta(hours=12.5) or horizon > timedelta(hours=24):
        raise ValueError("activation wall horizon differs from frozen bounds")
    now = _utc_now()
    if activated_at > now:
        raise ValueError("activation timestamp is in the future")
    if deadline <= now:
        raise ValueError("activation wall deadline has expired")
    return dict(activation)


def load_and_validate(
    candidate_path: Path, activation_path: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    candidate_path = candidate_path.resolve()
    candidate = validate_candidate(_read_object(candidate_path, "candidate bundle"))
    activation = _read_object(activation_path.resolve(), "live activation")
    return candidate, validate_activation(candidate_path, candidate, activation)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    candidate = commands.add_parser("create-candidate")
    candidate.add_argument(
        "--profile",
        choices=(
            GNSS_BAUD_ENVELOPE_PROFILE_ID,
            GNSS_BAUD_CONTINUATION_PROFILE_ID,
            GNSS_BAUD_RESUME_PROFILE_ID,
        ),
        default=GNSS_BAUD_ENVELOPE_PROFILE_ID,
    )
    candidate.add_argument("--contract", required=True, type=Path)
    candidate.add_argument("--build-manifest", required=True, type=Path)
    candidate.add_argument("--preflight", required=True, type=Path)
    candidate.add_argument("--operational-check", required=True, type=Path)
    candidate.add_argument("--output", required=True, type=Path)
    candidate.add_argument("--expected-usb-serial", default=EXPECTED_USB_SERIAL)
    activation = commands.add_parser("create-activation")
    activation.add_argument("--candidate", required=True, type=Path)
    activation.add_argument("--output", required=True, type=Path)
    activation.add_argument("--operator", required=True)
    activation.add_argument("--authority-source", required=True)
    activation.add_argument("--run-id", required=True)
    activation.add_argument("--run-dir", required=True, type=Path)
    activation.add_argument("--device", required=True, type=Path)
    activation.add_argument("--wall-hours", type=float, default=15.0)
    validate = commands.add_parser("validate")
    validate.add_argument("--candidate", required=True, type=Path)
    validate.add_argument("--activation", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.command == "create-candidate":
        value = create_candidate(
            contract_path=args.contract,
            build_manifest_path=args.build_manifest,
            preflight_path=args.preflight,
            operational_check_path=args.operational_check,
            output_path=args.output,
            profile_id=args.profile,
            expected_usb_serial=args.expected_usb_serial,
        )
    elif args.command == "create-activation":
        value = create_activation(
            candidate_path=args.candidate,
            output_path=args.output,
            operator=args.operator,
            authority_source=args.authority_source,
            run_id=args.run_id,
            run_dir=args.run_dir,
            device=args.device,
            wall_hours=args.wall_hours,
        )
    else:
        value = {
            "status": "passed",
            "bundle_id": load_and_validate(args.candidate, args.activation)[0][
                "bundle_id"
            ],
        }
    print(json.dumps(value, indent=2, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
