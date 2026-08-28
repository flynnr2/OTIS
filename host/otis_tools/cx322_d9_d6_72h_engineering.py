"""Sustained 72-qualified-hour CX322/D9/D6 engineering programme.

The module freezes the distinct non-challenge programme, reduces a canonical
hash-chained record stream for supervisor/monitor/analyzer use, and rehearses
the host capture and finalization path without touching hardware.  It cannot
authorize a live run or promote D9 waveform claims.
"""

from __future__ import annotations

import argparse
from collections import Counter
from bisect import bisect_right
import csv
from dataclasses import dataclass, field
from fractions import Fraction
from hashlib import sha256
import io
import json
import os
from pathlib import Path
import pty
import re
import secrets
import select
import signal
import stat
import subprocess
import sys
import time
from typing import Any, Mapping

from .active_control_supervisor import RP2040_TIMER0_TICKS_PER_SECOND
from .capture_segment_rotation import prepare_transition, request_rotation
from .contracts import (
    ACTIVE_HYBRID_DECISION_V1_FIELDS,
    ACTIVE_HYBRID_DECISION_V2_FIELDS,
    ACTIVE_TRANSACTION_V1_FIELDS,
    ACTIVE_TRANSACTION_V2_FIELDS,
    CONTRACT_FIELDS,
    CONTRACT_RECORD_TYPES,
    CONTRACT_SCHEMA_VERSIONS,
    SEQUENCE_FIELDS,
)
from .evidence_finalization import (
    advance_phase,
    begin_finalization,
    recover_registration,
    set_registration_intent,
)
from .evidence_index import DEFAULT_INDEX, package_identity
from .active_hybrid_live_supervisor import (
    FORWARDED_OUTPUT_INTEGRATION_EXPECTED_HEALTH,
    FORWARDED_MONITOR_OBSERVABILITY_KEYS,
)
from .active_status_contract import ACTIVE_STATUS_CONTRACT_KEYS
from .run_paths import default_csv_files, exact_active_timing_csv_files
from .serial_commands import (
    send_command_to_fifo,
    send_timestamped_command_to_fifo,
)
from .time_domains import RP2040_TIMER0_MICROS_WRAP_TICKS, forward_progress


ROOT = Path(__file__).resolve().parents[2]
PROGRAMME_DIR = (
    ROOT
    / "docs/60_EXPERIMENTS/"
    "OTIS_D9_OUTPUT_AND_ADAPTIVE_STEERING_INTEGRATION_PROGRAMME"
)
CONTRACT_PATH = (
    PROGRAMME_DIR / "cx322_d9_d6_72h_integrated_engineering_contract_v1.json"
)
PARENT_CONTRACT_PATH = (
    PROGRAMME_DIR / "cx322_d9_d6_integration_engineering_contract_v1.json"
)
MATRIX_PATH = ROOT / "firmware/arduino/firmware_matrix.json"
POLICY_PATH = ROOT / "profiles/discipline/cx322_bounded_hybrid_fact_gathering_v1.json"
TOOL_ID = "otis_cx322_d9_d6_72h_integrated_engineering_v1"
BUNDLE_TYPE = "otis_cx322_d9_d6_72h_integrated_engineering_bundle_v1"
RECORD_CONTRACT = "otis_cx322_d9_d6_72h_record_v1"
CAPABILITY = "cx322-d9-d6-72h-integrated-engineering-rehearsal"
PTY_CAPTURE_SUBCOMMAND = "_bounded-nonphysical-pty-capture"
PTY_DEVICE_ENV = "OTIS_CX322_D9_D6_72H_PTY_DEVICE"
PTY_RUN_DIR_ENV = "OTIS_CX322_D9_D6_72H_PTY_RUN_DIR"
PTY_TOKEN_ENV = "OTIS_CX322_D9_D6_72H_PTY_TOKEN"
LIVE_ACTIVATION_TYPE = "otis_cx322_d9_d6_72h_live_activation_v1"
LIVE_ADAPTER_STATE_TYPE = "otis_cx322_d9_d6_72h_live_adapter_state_v1"
LIVE_ADAPTER_REPORT_TYPE = "otis_cx322_d9_d6_72h_live_adapter_report_v1"
EXACT_LIFECYCLE_TIME_DOMAIN = "rp2040_timer0_extended"
CAMPAIGN18_PROGRAMME_ID = "OTIS_CX322_D9_D6_72H_INTEGRATED_ENGINEERING_V1"
CAMPAIGN18_RUN_IDENTITY = "cx322_d9_d6_72h_sustained_engineering:1"

# The shared capture contracts carry exact AT2/AH2 counter sidecars.  The
# retained adapter still refuses to reinterpret ACT/AHY v1 seconds as ticks.
_GNSS_HOLD_STATUS_KEYS = frozenset(
    {
        "gnss_metadata_hold_active",
        "gnss_metadata_hold_transaction_pending",
        "gnss_metadata_hold_entry_sequence",
        "gnss_metadata_requalification_sequence",
        "gnss_metadata_qualification_frontier",
        "d14_d8_observation_sequence",
    }
)

_INSPECTION_SOURCES = {
    "active_transactions_v1": "csv/active_transactions_v1.csv",
    "active_hybrid_decisions_v1": "csv/active_hybrid_decisions_v1.csv",
    "raw_events_v1": "csv/raw_events.csv",
    "count_observations_v1": "csv/count_observations.csv",
    "pps_snapshots_v1": "csv/pps_snapshots.csv",
    "forwarded_monitor_snapshots_v1": "csv/forwarded_monitor_snapshots.csv",
    "health_v1": "csv/health.csv",
    "reference_observations_v1": "csv/reference_observations_v1.csv",
    "relative_phase_observations_v1": "csv/relative_phase_observations_v1.csv",
    "phase_estimator_outputs_v1": "csv/phase_estimator_outputs_v1.csv",
}

_LIVE_SOURCE_DECLARATIONS = (
    {
        "role": "exact_active_transaction_lifecycle",
        "path": "csv/active_transactions_v2.csv",
        "contract": "active_transactions_v2",
        "record_type": "AT2",
        "schema_version": 2,
        "fields": ACTIVE_TRANSACTION_V2_FIELDS,
        "exact_tick_field": "event_timestamp_ticks",
        "time_domain_field": "time_domain",
        "joins_to": "active_transactions_v1",
        "join_fields": [
            "transaction_record_sequence",
            "event",
            "run_identity",
            "build_identity",
            "profile_identity",
            "session_id",
            "request_sequence",
            "decision_sequence",
            "source_first_sequence",
            "source_last_sequence",
            "authorization_sequence",
            "nonce",
            "accepted_code",
            "applied_code",
            "application_sequence",
            "dac_epoch",
            "reason",
        ],
    },
    {
        "role": "exact_active_hybrid_decision",
        "path": "csv/active_hybrid_decisions_v2.csv",
        "contract": "active_hybrid_decisions_v2",
        "record_type": "AH2",
        "schema_version": 2,
        "fields": ACTIVE_HYBRID_DECISION_V2_FIELDS,
        "exact_tick_field": "decision_timestamp_ticks",
        "time_domain_field": "time_domain",
        "joins_to": "active_hybrid_decisions_v1",
        "join_fields": [
            "hybrid_record_sequence",
            "decision_sequence",
            "run_identity",
            "build_identity",
            "profile_identity",
            "capture_session",
            "source_first_sequence",
            "source_last_sequence",
            "reason",
        ],
    },
)


def canonical_sha256(value: object) -> str:
    return sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _semantic_identity(value: Mapping[str, Any], field: str) -> str:
    unsigned = {key: item for key, item in value.items() if key != field}
    return canonical_sha256(unsigned)


def file_binding(path: Path) -> dict[str, object]:
    resolved = path.resolve()
    if path.is_symlink() or not resolved.is_file():
        raise ValueError(f"exact bound file absent or symbolic: {path}")
    payload = resolved.read_bytes()
    return {
        "path": str(resolved),
        "size_bytes": len(payload),
        "sha256": sha256(payload).hexdigest(),
    }


def _validate_binding(binding: Mapping[str, Any], *, label: str) -> Path:
    path = Path(str(binding.get("path", "")))
    expected = file_binding(path)
    if dict(binding) != expected:
        raise ValueError(f"{label} bound-file identity differs")
    return path


def _profiles() -> dict[str, dict[str, Any]]:
    matrix = _read_json(MATRIX_PATH)
    profiles = matrix.get("profiles")
    if not isinstance(profiles, list):
        raise ValueError("firmware profile matrix differs")
    return {str(item["id"]): item for item in profiles}


def _intended_profile_defines(contract: Mapping[str, Any]) -> dict[str, str]:
    firmware = contract["firmware"]
    profiles = _profiles()
    base = profiles.get(str(firmware["base_profile_id"]))
    if base is None:
        raise ValueError("required CX322 D9/D6 base profile is absent")
    expected = {
        **base["defines"],
        **firmware["required_define_delta"],
    }
    required = {
        "OTIS_GNSS_UART_BAUD": "115200u",
        "OTIS_ENABLE_CX320_ACTIVE_HYBRID": "1",
        "OTIS_ENABLE_CX322_DIRECT_HYBRID": "1",
        "OTIS_ENABLE_FORWARDED_D9_OUTPUT": "1",
        "OTIS_ENABLE_FORWARDED_D6_MONITOR": "1",
        "OTIS_ENABLE_D9_D6_READINESS_PROFILE": "0",
        "OTIS_CX317_ACTIVE_CAMPAIGN": (
            "OTIS_CX317_ACTIVE_CAMPAIGN_D9_D6_72H_SUSTAINED_HYBRID"
        ),
        "OTIS_CX317_ACTIVE_START_CODE": "0xA83Cu",
        "OTIS_CX317_ACTIVE_CORRECTION_LIMIT": "144u",
        "OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES": "3024u",
        "OTIS_ACTIVE_HYBRID_MAX_AUTOMATIC_APPLICATIONS": "144u",
        "OTIS_ACTIVE_HYBRID_MAX_CUMULATIVE_MOVEMENT_CODES": "3024u",
        "OTIS_CX317_MINIMUM_APPLIED_CADENCE_S": "1800u",
    }
    if any(expected.get(key) != value for key, value in required.items()):
        raise ValueError("CX322 D9/D6 firmware authority selectors differ")
    return expected


def _profile_matrix_integrated(contract: Mapping[str, Any]) -> bool:
    firmware = contract["firmware"]
    profile = _profiles().get(str(firmware["profile_id"]))
    expected = _intended_profile_defines(contract)
    if profile is None:
        if firmware.get("profile_matrix_status") != (
            "pending_new_profile_and_firmware_guards_required_before_physical_"
            "activation"
        ):
            raise ValueError("required 72h firmware profile is absent")
        return False
    if profile.get("defines") != expected:
        raise ValueError("72h profile is not exact base plus authority delta")
    if firmware.get("profile_matrix_status") != (
        "implemented_and_compile_time_guards_verified"
    ):
        raise ValueError("72h integrated profile status differs")
    return True


def _validate_parent(contract: Mapping[str, Any]) -> dict[str, Any]:
    parent = _read_json(PARENT_CONTRACT_PATH)
    parent_identity = _semantic_identity(parent, "contract_semantic_sha256")
    if parent.get("contract_semantic_sha256") != parent_identity:
        raise ValueError("parent engineering contract semantic identity differs")
    expected = contract["semantic_parent"]
    if (
        parent.get("contract_id") != expected["contract_id"]
        or parent_identity != expected["contract_semantic_sha256"]
        or PARENT_CONTRACT_PATH.name != expected["contract_file"]
    ):
        raise ValueError("72h contract parent binding differs")
    return parent


def load_contract(path: Path = CONTRACT_PATH) -> dict[str, Any]:
    contract = _read_json(path)
    if contract.get("contract_semantic_sha256") != _semantic_identity(
        contract, "contract_semantic_sha256"
    ):
        raise ValueError("72h engineering contract semantic identity differs")
    if contract.get("contract_id") != (
        "OTIS_CX322_D9_D6_72H_INTEGRATED_ENGINEERING_CONTRACT_V1"
    ):
        raise ValueError("72h engineering contract id differs")
    _validate_parent(contract)
    _profile_matrix_integrated(contract)

    firmware = contract["firmware"]
    if (
        firmware["profile_id"] != "cx322_d9_d6_72h_sustained_engineering"
        or firmware["base_profile_id"]
        != "cx322_d9_d6_integration_engineering"
        or firmware["required_define_delta"]
        != {
            "OTIS_CX317_ACTIVE_CAMPAIGN": (
                "OTIS_CX317_ACTIVE_CAMPAIGN_D9_D6_72H_SUSTAINED_HYBRID"
            ),
            "OTIS_CX317_ACTIVE_CORRECTION_LIMIT": "144u",
            "OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES": "3024u",
            "OTIS_ACTIVE_HYBRID_MAX_AUTOMATIC_APPLICATIONS": "144u",
            "OTIS_ACTIVE_HYBRID_MAX_CUMULATIVE_MOVEMENT_CODES": "3024u",
        }
        or firmware["cx322_request_law_changed"] is not False
        or firmware["generic_sustained_regulation_mode"] is not False
        or firmware["deliberate_reversal_challenge_enabled"] is not False
    ):
        raise ValueError("72h distinct non-challenge firmware intent differs")

    timing = contract["time"]
    if timing != {
        "source_counter_domain": "rp2040_timer0",
        "counter_domain": "rp2040_timer0_extended",
        "nominal_counter_hz": RP2040_TIMER0_TICKS_PER_SECOND,
        "qualified_duration_s": 259_200,
        "qualification_deadline_s": 5_400,
        "absolute_wall_limit_s": 280_800,
        "milestone_interval_qualified_s": 21_600,
        "milestones_qualified_s": [21_600 * number for number in range(1, 13)],
        "qualification_origin": (
            "first_complete_fresh_selected_600_estimate_after_exact_setup_code_"
            "epoch_establishment_and_common_D14_D8_health"
        ),
    }:
        raise ValueError("72h exact counter-domain duration differs")
    if contract["serial"] != {
        "baud": 115200,
        "selection": (
            "capture_device_--auto-detect_fresh_for_every_capture_and_"
            "reenumeration"
        ),
        "required_candidate_count": 1,
        "stored_device_path_permitted": False,
        "stored_board_serial_permitted": False,
        "sole_serial_owner_required": True,
        "independent_abort_delivery_required": True,
    }:
        raise ValueError("72h serial auto-detection/baud contract differs")
    envelope = contract["controller_envelope"]
    expected_envelope = {
        "automatic_application_limit": 144,
        "automatic_application_limit_derivation": (
            "259200_qualified_seconds_divided_by_1800_seconds_per_application"
        ),
        "automatic_cumulative_movement_limit_codes": 3024,
        "automatic_cumulative_movement_limit_derivation": (
            "144_applications_multiplied_by_21_codes_per_application"
        ),
        "automatic_step_limit_codes": 21,
        "total_dac_write_limit_including_setup": 145,
        "authority_ceilings_are_nonbinding_not_targets": True,
        "minimum_automatic_application_count": 0,
        "minimum_application_cadence_s": 1800,
        "maximum_outstanding_transactions": 1,
        "dac_min_code": 0xA800,
        "dac_min_code_hex": "0xA800",
        "dac_max_code": 0xAB00,
        "dac_max_code_hex": "0xAB00",
        "deliberate_reversal_challenge_permitted": False,
        "automatic_retry_permitted": False,
        "restoration_write_permitted": False,
        "close_new_application_admission_before_endpoint_s": 1500,
    }
    if envelope != expected_envelope:
        raise ValueError("72h controller/application envelope differs")
    cadence_s = int(envelope["minimum_application_cadence_s"])
    application_limit = int(envelope["automatic_application_limit"])
    step_limit = int(envelope["automatic_step_limit_codes"])
    if (
        int(timing["qualified_duration_s"]) % cadence_s != 0
        or application_limit != int(timing["qualified_duration_s"]) // cadence_s
        or int(envelope["automatic_cumulative_movement_limit_codes"])
        != application_limit * step_limit
        or int(envelope["total_dac_write_limit_including_setup"])
        != int(contract["starting_dac"]["setup_write_limit"])
        + application_limit
        or application_limit > 0xFFFF
        or int(envelope["automatic_cumulative_movement_limit_codes"])
        > 0xFFFF
    ):
        raise ValueError("72h cadence-derived authority arithmetic differs")
    replay = contract["record_replay"]
    if (
        replay["record_contract"] != RECORD_CONTRACT
        or replay["hash_chain_required"] is not True
        or replay["counter_domain_exact_through_replay"] is not True
        or replay["single_reducer_required_for_supervisor_monitor_and_analyzer"]
        is not True
        or replay["transaction_lifecycle"]
        != [
            "control_opportunity",
            "automatic_request",
            "automatic_acceptance",
            "automatic_application",
            "first_dependent_consumer",
            "automatic_response",
        ]
    ):
        raise ValueError("72h canonical record/replay contract differs")
    start = contract["starting_dac"]
    if (
        start["setup_code"] != 0xA83C
        or start["setup_write_limit"] != 1
        or start["setup_counts_as_automatic_application"] is not False
        or start["required_established_epoch"] != 1
        or start["retry_permitted"] is not False
        or start["restoration_permitted"] is not False
    ):
        raise ValueError("72h setup-establishment boundary differs")
    if contract["timing_truth"] != {
        "reference_input": "D14",
        "oscillator_and_control_input": "D8",
        "D14_D8_continuity_required": True,
        "D10_authority_changed": False,
    }:
        raise ValueError("D14/D8 timing-truth boundary differs")
    d9 = contract["d9"]
    if (
        d9["required_state"] != "configured_10mhz_forwarded_unqualified"
        or d9["source"] != "D8_GPIO20_GPIN0"
        or d9["destination"] != "D9_GPIO21_GPOUT0"
        or d9["integer_divider"] != 1
        or d9["fractional_divider"] != 0
        or d9["readback_exact_required"] is not True
        or d9["measurement_authority"] is not False
        or d9["control_authority"] is not False
    ):
        raise ValueError("D9 digital configuration/readback boundary differs")
    d6 = contract["d6"]
    if (
        d6["allowed_statuses"] != ["present", "local_degraded"]
        or d6["measurement_authority"] is not False
        or d6["control_authority"] is not False
    ):
        raise ValueError("D6 zero-authority boundary differs")
    claim = contract["claim_boundary"]
    if (
        claim["programme_class"] != "engineering_non_promotional"
        or claim["waveform_evidence_status"] != "unresolved_oscilloscope_deferred"
        or claim["prompt02_waveform_gate_satisfied"] is not False
        or claim["prompt02_promotion_permitted"] is not False
    ):
        raise ValueError("waveform/non-promotional claim boundary differs")
    physical = contract["physical_execution"]
    if (
        physical["authorized_by_this_contract_alone"] is not False
        or physical["separate_exact_bundle_activation_required"] is not True
        or physical[
            "host_programme_record_replay_and_finalization_rehearsal_status"
        ]
        != "implemented"
    ):
        raise ValueError("72h host/physical authority boundary differs")
    return contract


def _configuration(build_manifest: Mapping[str, Any]) -> Mapping[str, Any]:
    provenance = build_manifest.get("provenance")
    if isinstance(provenance, Mapping) and isinstance(
        provenance.get("configuration"), Mapping
    ):
        return provenance["configuration"]
    configuration = build_manifest.get("configuration")
    if isinstance(configuration, Mapping):
        return configuration
    raise ValueError("build manifest lacks exact configuration")


def _validate_build_manifest(
    path: Path, contract: Mapping[str, Any]
) -> dict[str, Any]:
    build = _read_json(path)
    configuration = _configuration(build)
    expected_defines = _intended_profile_defines(contract)
    if (
        configuration.get("profile_id") != contract["firmware"]["profile_id"]
        or configuration.get("defines") != expected_defines
    ):
        raise ValueError("build is not the exact CX322 D9/D6 engineering profile")
    return build


def freeze_bundle(
    *,
    build_manifest_path: Path,
    source_revision: str,
    contract_path: Path = CONTRACT_PATH,
) -> dict[str, object]:
    """Freeze the exact no-authority input bundle; this performs no I/O."""

    if not re.fullmatch(r"[0-9a-f]{40}", source_revision):
        raise ValueError("source revision must be one exact lowercase Git SHA-1")
    contract = load_contract(contract_path)
    _validate_build_manifest(build_manifest_path, contract)
    bindings = {
        "contract": file_binding(contract_path),
        "parent_engineering_contract": file_binding(PARENT_CONTRACT_PATH),
        "firmware_matrix": file_binding(MATRIX_PATH),
        "cx322_policy": file_binding(POLICY_PATH),
        "firmware_build_manifest": file_binding(build_manifest_path),
        "programme_tool": file_binding(Path(__file__)),
        "capture_tool": file_binding(ROOT / "host/otis_tools/capture_device.py"),
        "rotation_tool": file_binding(
            ROOT / "host/otis_tools/capture_segment_rotation.py"
        ),
        "command_tool": file_binding(ROOT / "host/otis_tools/serial_commands.py"),
    }
    unsigned: dict[str, object] = {
        "schema_version": 1,
        "bundle_type": BUNDLE_TYPE,
        "tool": TOOL_ID,
        "effective": False,
        "physical_authority": False,
        "source_revision": source_revision,
        "programme_id": contract["contract_id"],
        "contract_semantic_sha256": contract["contract_semantic_sha256"],
        "profile_id": contract["firmware"]["profile_id"],
        "firmware_profile_matrix_integrated": _profile_matrix_integrated(contract),
        "serial": contract["serial"],
        "time": contract["time"],
        "starting_dac": contract["starting_dac"],
        "controller_envelope": contract["controller_envelope"],
        "timing_truth": contract["timing_truth"],
        "d9": contract["d9"],
        "d6": contract["d6"],
        "record_replay": contract["record_replay"],
        "terminals": contract["terminals"],
        "claim_boundary": contract["claim_boundary"],
        "bindings": bindings,
        "remaining_live_components": ["separate_exact_physical_activation"],
    }
    return {**unsigned, "bundle_sha256": canonical_sha256(unsigned)}


def validate_bundle(bundle: Mapping[str, Any]) -> dict[str, Any]:
    value = dict(bundle)
    unsigned = {key: item for key, item in value.items() if key != "bundle_sha256"}
    if value.get("bundle_sha256") != canonical_sha256(unsigned):
        raise ValueError("72h bundle semantic identity differs")
    if (
        value.get("bundle_type") != BUNDLE_TYPE
        or value.get("effective") is not False
        or value.get("physical_authority") is not False
    ):
        raise ValueError("72h bundle type or physical-authority boundary differs")
    bindings = value.get("bindings")
    if not isinstance(bindings, Mapping):
        raise ValueError("72h bundle bindings absent")
    for label in (
        "contract",
        "parent_engineering_contract",
        "firmware_matrix",
        "cx322_policy",
        "firmware_build_manifest",
        "programme_tool",
        "capture_tool",
        "rotation_tool",
        "command_tool",
    ):
        if not isinstance(bindings.get(label), Mapping):
            raise ValueError(f"{label} binding absent")
        _validate_binding(bindings[label], label=label)
    contract_path = Path(str(bindings["contract"]["path"]))
    contract = load_contract(contract_path)
    _validate_build_manifest(
        Path(str(bindings["firmware_build_manifest"]["path"])), contract
    )
    copied = (
        "serial",
        "time",
        "starting_dac",
        "controller_envelope",
        "timing_truth",
        "d9",
        "d6",
        "record_replay",
        "terminals",
        "claim_boundary",
    )
    if (
        value.get("contract_semantic_sha256")
        != contract["contract_semantic_sha256"]
        or value.get("programme_id") != contract["contract_id"]
        or value.get("profile_id") != contract["firmware"]["profile_id"]
        or value.get("firmware_profile_matrix_integrated")
        != _profile_matrix_integrated(contract)
        or any(value.get(key) != contract[key] for key in copied)
    ):
        raise ValueError("72h bundle contract projection differs")
    return value


def draft_live_activation(
    *,
    bundle: Mapping[str, Any],
    run_directory: Path,
    run_identity: str,
) -> dict[str, object]:
    """Create an explicitly ineffective no-I/O live-adapter activation draft."""

    checked = validate_bundle(bundle)
    if run_identity != CAMPAIGN18_RUN_IDENTITY:
        raise ValueError("live activation requires the exact campaign18 run identity")
    unsigned: dict[str, object] = {
        "schema_version": 1,
        "activation_type": LIVE_ACTIVATION_TYPE,
        "tool": TOOL_ID,
        "effective": False,
        "physical_authority": False,
        "bundle_sha256": checked["bundle_sha256"],
        "programme_id": checked["programme_id"],
        "profile_id": checked["profile_id"],
        "source_revision": checked["source_revision"],
        "run_identity": run_identity,
        "run_directory": str(run_directory.resolve()),
        "serial": checked["serial"],
        "controller_envelope": checked["controller_envelope"],
        "adapter_authority": {
            "retained_evidence_reader": True,
            "scientific_report_writer": True,
            "canonical_reducer_writer": False,
            "serial_owner": False,
            "command_writer": False,
            "acknowledgement_sender": False,
            "controller": False,
            "actuator_authority": False,
        },
        "exact_lifecycle_time_domain": EXACT_LIFECYCLE_TIME_DOMAIN,
        "required_live_sources": [dict(item) for item in _LIVE_SOURCE_DECLARATIONS],
        "inspection_sources": dict(_INSPECTION_SOURCES),
    }
    return {
        **unsigned,
        "activation_sha256": canonical_sha256(unsigned),
    }


def _live_activation_blockers(bundle: Mapping[str, Any]) -> list[str]:
    blockers: list[str] = []
    if not bool(bundle["firmware_profile_matrix_integrated"]):
        blockers.append("firmware_profile_matrix_and_guards_not_integrated")
    registered = {
        item["contract"]: item for item in exact_active_timing_csv_files()
    }
    expected_contracts = (
        (
            "active_transactions_v2",
            ACTIVE_TRANSACTION_V2_FIELDS,
            "AT2",
            "csv/active_transactions_v2.csv",
        ),
        (
            "active_hybrid_decisions_v2",
            ACTIVE_HYBRID_DECISION_V2_FIELDS,
            "AH2",
            "csv/active_hybrid_decisions_v2.csv",
        ),
    )
    for contract_id, fields, record_type, path in expected_contracts:
        if CONTRACT_FIELDS.get(contract_id) != fields:
            blockers.append(f"{contract_id}_exact_fields_not_registered")
        if CONTRACT_RECORD_TYPES.get(contract_id) != {record_type}:
            blockers.append(f"{contract_id}_record_type_not_registered")
        if CONTRACT_SCHEMA_VERSIONS.get(contract_id) != 2:
            blockers.append(f"{contract_id}_schema_version_not_registered")
        if registered.get(contract_id, {}).get("path") != path:
            blockers.append(f"{contract_id}_capture_path_not_registered")
    active_keys = ACTIVE_STATUS_CONTRACT_KEYS.get(
        "cx317_active_status_snapshot_v1", ()
    )
    if not _GNSS_HOLD_STATUS_KEYS.issubset(active_keys):
        blockers.append("gnss_hold_causal_status_contract_not_registered")
    if bundle["time"]["counter_domain"] != EXACT_LIFECYCLE_TIME_DOMAIN:
        blockers.append("canonical_reducer_extended_counter_domain_not_bound")
    return blockers


def validate_live_activation(
    *,
    bundle: Mapping[str, Any],
    activation: Mapping[str, Any],
) -> dict[str, object]:
    """Validate exact activation identity and readiness without device I/O."""

    checked_bundle = validate_bundle(bundle)
    value = dict(activation)
    unsigned = {
        key: item for key, item in value.items() if key != "activation_sha256"
    }
    if value.get("activation_sha256") != canonical_sha256(unsigned):
        raise ValueError("72h live activation semantic identity differs")
    expected_authority = {
        "retained_evidence_reader": True,
        "scientific_report_writer": True,
        "canonical_reducer_writer": False,
        "serial_owner": False,
        "command_writer": False,
        "acknowledgement_sender": False,
        "controller": False,
        "actuator_authority": False,
    }
    exact_projection = {
        "schema_version": 1,
        "activation_type": LIVE_ACTIVATION_TYPE,
        "tool": TOOL_ID,
        "bundle_sha256": checked_bundle["bundle_sha256"],
        "programme_id": checked_bundle["programme_id"],
        "profile_id": checked_bundle["profile_id"],
        "source_revision": checked_bundle["source_revision"],
        "serial": checked_bundle["serial"],
        "controller_envelope": checked_bundle["controller_envelope"],
        "adapter_authority": expected_authority,
        "exact_lifecycle_time_domain": EXACT_LIFECYCLE_TIME_DOMAIN,
        "required_live_sources": [dict(item) for item in _LIVE_SOURCE_DECLARATIONS],
        "inspection_sources": dict(_INSPECTION_SOURCES),
    }
    if any(value.get(key) != expected for key, expected in exact_projection.items()):
        raise ValueError("72h live activation bundle or authority projection differs")
    run_directory = Path(str(value.get("run_directory", "")))
    if not run_directory.is_absolute():
        raise ValueError("72h live activation run directory must be absolute")
    run_identity = value.get("run_identity")
    if run_identity != CAMPAIGN18_RUN_IDENTITY:
        raise ValueError("72h live activation run identity differs")
    if not isinstance(value.get("effective"), bool) or not isinstance(
        value.get("physical_authority"), bool
    ):
        raise ValueError("72h live activation authority flags are not Boolean")
    blockers = _live_activation_blockers(checked_bundle)
    prerequisites_ready = not blockers
    if (value["effective"] or value["physical_authority"]) and not prerequisites_ready:
        raise ValueError(
            "72h live activation claims authority while hard blockers remain: "
            + ", ".join(blockers)
        )
    if bool(value["effective"]) != bool(value["physical_authority"]):
        raise ValueError("72h live activation effective/authority flags differ")
    active_binding = value.get("active_hybrid_activation")
    if value["effective"]:
        if not isinstance(active_binding, Mapping):
            raise ValueError("effective 72h adapter lacks active-hybrid activation")
        _validate_binding(active_binding, label="active-hybrid activation")
    elif active_binding is not None:
        raise ValueError("ineffective 72h adapter carries physical activation")
    return {
        "status": "ready" if prerequisites_ready else "blocked",
        "hardware_operations": False,
        "activation_sha256": value["activation_sha256"],
        "bundle_sha256": checked_bundle["bundle_sha256"],
        "prerequisites_ready": prerequisites_ready,
        "physical_activation_ready": bool(
            prerequisites_ready
            and value["effective"]
            and value["physical_authority"]
        ),
        "effective": value["effective"],
        "physical_authority": value["physical_authority"],
        "hard_blockers": blockers,
        "run_identity": run_identity,
        "run_directory": str(run_directory),
        "adapter_authority": expected_authority,
    }


def _validate_campaign18_active_activation(
    *, bundle: Mapping[str, Any], active_hybrid_activation_path: Path
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Validate the physical activation and cross-bind both campaign bundles."""

    from .active_hybrid_activation import validate_frozen_activation
    from .active_hybrid_programme_contract import CX322_D9_D6_72H_PROGRAMME

    checked = validate_bundle(bundle)
    active_activation, active_bundle, _proposal = validate_frozen_activation(
        active_hybrid_activation_path.resolve(),
        programme=CX322_D9_D6_72H_PROGRAMME,
    )
    firmware = active_bundle.get("firmware")
    finite_limits = active_bundle.get("finite_limits")
    authority = active_activation.get("authority")
    device = active_activation.get("device")
    if not all(
        isinstance(value, Mapping)
        for value in (firmware, finite_limits, authority, device)
    ):
        raise ValueError("campaign18 active activation projection is malformed")
    build_binding = checked["bindings"]["firmware_build_manifest"]
    expected_limits = {
        "qualified_duration_s": checked["time"]["qualified_duration_s"],
        "absolute_wall_clock_limit_s": checked["time"]["absolute_wall_limit_s"],
        "maximum_total_automatic_applications": checked["controller_envelope"][
            "automatic_application_limit"
        ],
        "maximum_total_physical_control_applications": checked[
            "controller_envelope"
        ]["automatic_application_limit"],
        "maximum_cumulative_absolute_movement_codes": checked[
            "controller_envelope"
        ]["automatic_cumulative_movement_limit_codes"],
        "maximum_combined_step_codes": checked["controller_envelope"][
            "automatic_step_limit_codes"
        ],
        "minimum_applied_cadence_s": checked["controller_envelope"][
            "minimum_application_cadence_s"
        ],
    }
    if (
        active_activation.get("programme_id") != CAMPAIGN18_PROGRAMME_ID
        or active_activation.get("run_identity") != CAMPAIGN18_RUN_IDENTITY
        or active_activation.get("profile_identity") != checked["profile_id"]
        or device.get("path") is not None
        or device.get("selection")
        != "capture_device_--auto-detect_fresh_for_every_capture_and_reenumeration"
        or device.get("baud") != 115200
        or device.get("expected_board_serial") is not None
        or firmware.get("profile_id") != checked["profile_id"]
        or firmware.get("source_revision") != checked["source_revision"]
        or firmware.get("build_manifest", {}).get("sha256")
        != build_binding["sha256"]
        or firmware.get("defines") != _intended_profile_defines(load_contract())
        or any(
            finite_limits.get(key) != value
            for key, value in expected_limits.items()
        )
        or authority.get("effective") is not True
        or authority.get("physical_execution") is not True
        or authority.get("firmware_flash_limit") != 1
        or authority.get("setup_write_limit") != 1
        or authority.get("maximum_total_automatic_applications") != 144
        or authority.get("maximum_total_physical_control_applications") != 144
        or authority.get("maximum_cumulative_absolute_movement_codes") != 3024
        or authority.get("maximum_deliberate_challenges") != 0
        or authority.get("automatic_retry") is not False
        or authority.get("automatic_restoration") is not False
        or authority.get("live_extension") is not False
    ):
        raise ValueError(
            "campaign18 physical activation differs from the exact 72h bundle"
        )
    return active_activation, active_bundle


def bind_effective_live_activation(
    *,
    bundle: Mapping[str, Any],
    draft: Mapping[str, Any],
    active_hybrid_activation_path: Path,
) -> dict[str, object]:
    """Bind the read-only adapter to one already-authorized physical campaign."""

    checked_draft = validate_live_activation(bundle=bundle, activation=draft)
    if checked_draft["effective"] or checked_draft["physical_authority"]:
        raise ValueError("campaign18 adapter activation draft is already effective")
    if checked_draft["hard_blockers"]:
        raise ValueError(
            "campaign18 adapter prerequisites remain blocked: "
            + ", ".join(checked_draft["hard_blockers"])
        )
    _validate_campaign18_active_activation(
        bundle=bundle,
        active_hybrid_activation_path=active_hybrid_activation_path,
    )
    unsigned = {
        key: value
        for key, value in dict(draft).items()
        if key != "activation_sha256"
    }
    unsigned.update(
        {
            "effective": True,
            "physical_authority": True,
            "active_hybrid_activation": file_binding(
                active_hybrid_activation_path.resolve()
            ),
        }
    )
    effective = {**unsigned, "activation_sha256": canonical_sha256(unsigned)}
    validate_campaign18_entrypoint(
        bundle=bundle,
        adapter_activation=effective,
        active_hybrid_activation_path=active_hybrid_activation_path,
    )
    return effective


def validate_campaign18_entrypoint(
    *,
    bundle: Mapping[str, Any],
    adapter_activation: Mapping[str, Any],
    active_hybrid_activation_path: Path,
) -> dict[str, object]:
    """No-I/O validation for the exact Campaign 18 physical entrypoint."""

    adapter = validate_live_activation(
        bundle=bundle, activation=adapter_activation
    )
    if not adapter["physical_activation_ready"]:
        raise ValueError("campaign18 adapter lacks effective physical activation")
    expected_binding = file_binding(active_hybrid_activation_path.resolve())
    if adapter_activation.get("active_hybrid_activation") != expected_binding:
        raise ValueError("campaign18 adapter binds a different physical activation")
    active_activation, active_bundle = _validate_campaign18_active_activation(
        bundle=bundle,
        active_hybrid_activation_path=active_hybrid_activation_path,
    )
    return {
        "status": "ready",
        "hardware_operations": False,
        "programme_id": CAMPAIGN18_PROGRAMME_ID,
        "run_identity": CAMPAIGN18_RUN_IDENTITY,
        "profile_identity": active_activation["profile_identity"],
        "bundle_sha256": bundle["bundle_sha256"],
        "active_hybrid_bundle_sha256": active_bundle["bundle_sha256"],
        "active_hybrid_activation_sha256": active_activation[
            "activation_sha256"
        ],
        "build_identity": active_activation["firmware"]["build_identity"],
        "adapter_activation_sha256": adapter_activation["activation_sha256"],
        "serial_selection": active_activation["device"]["selection"],
        "baud": active_activation["device"]["baud"],
        "physical_runner": "host.otis_tools.active_hybrid_run",
        "serial_owner": "host.otis_tools.capture_device",
        "supervisor": "host.otis_tools.active_hybrid_live_supervisor",
        "retained_adapter_runs_after_finalization": True,
    }


def run_campaign18_qualification(
    *,
    bundle_path: Path,
    adapter_activation_path: Path,
    active_hybrid_activation_path: Path,
    run_dir: Path,
    adapter_output_dir: Path,
    evidence_index_path: Path,
    arduino_cli: str = "arduino-cli",
) -> dict[str, object]:
    """Run Campaign 18 through the shared physical path, then inspect evidence."""

    from .active_hybrid_programme_contract import CX322_D9_D6_72H_PROGRAMME
    from .active_hybrid_run import (
        _activation_attempt_reservation_path,
        run_active_hybrid_qualification,
    )

    bundle = _read_json(bundle_path.resolve())
    adapter_activation = _read_json(adapter_activation_path.resolve())
    active_hybrid_activation = _read_json(
        active_hybrid_activation_path.resolve()
    )
    entry = validate_campaign18_entrypoint(
        bundle=bundle,
        adapter_activation=adapter_activation,
        active_hybrid_activation_path=active_hybrid_activation_path,
    )
    run_dir = run_dir.resolve()
    if Path(str(adapter_activation["run_directory"])).resolve() != run_dir:
        raise ValueError("campaign18 adapter run directory differs from runner")
    adapter_output_dir = adapter_output_dir.resolve()
    if adapter_output_dir == run_dir or adapter_output_dir.is_relative_to(run_dir):
        raise ValueError(
            "campaign18 adapter outputs must remain outside sealed run evidence"
        )
    physical = run_active_hybrid_qualification(
        activation_path=active_hybrid_activation_path.resolve(),
        run_dir=run_dir,
        evidence_index_path=evidence_index_path,
        arduino_cli=arduino_cli,
    )
    if Path(str(physical.get("run_dir", ""))).resolve() != run_dir:
        raise RuntimeError("campaign18 physical runner returned a different run")
    evidence_before = package_identity(run_dir)["content_sha256"]
    if physical.get("evidence_content_sha256") != evidence_before:
        raise RuntimeError("campaign18 finalized evidence identity differs")
    if physical.get("primary_decision") not in (
        CX322_D9_D6_72H_PROGRAMME.terminal_decisions
    ):
        raise RuntimeError(
            "campaign18 shared analyzer returned a non-Campaign18 terminal"
        )
    reservation_path = _activation_attempt_reservation_path(
        active_hybrid_activation
    )
    expected_reservation = {
        "path": str(reservation_path),
        "sha256": sha256(reservation_path.read_bytes()).hexdigest(),
    }
    if (
        physical.get("firmware_flashes") != 1
        or physical.get("activation_sha256")
        != entry["active_hybrid_activation_sha256"]
        or physical.get("bundle_sha256")
        != entry["active_hybrid_bundle_sha256"]
        or physical.get("build_identity") != entry["build_identity"]
        or physical.get("activation_attempt_reservation")
        != expected_reservation
    ):
        raise RuntimeError(
            "campaign18 shared runner flash, activation, bundle, build, or "
            "global reservation identity differs"
        )
    adapter_output_dir.mkdir(parents=True, exist_ok=False)
    report = RetainedEvidence72hAdapter(
        bundle=bundle,
        activation=adapter_activation,
        state_path=adapter_output_dir / "adapter_state_v1.json",
        report_path=adapter_output_dir / "adapter_report_v1.json",
    ).poll()
    evidence_after = package_identity(run_dir)["content_sha256"]
    if evidence_after != evidence_before:
        raise RuntimeError("campaign18 read-only adapter changed sealed evidence")
    if report["hard_blockers"]:
        raise RuntimeError(
            "campaign18 retained adapter found blocking evidence defects: "
            + ", ".join(report["hard_blockers"])
        )
    return {
        "status": physical["status"],
        "primary_decision": physical["primary_decision"],
        "entrypoint": entry,
        "physical": physical,
        "retained_adapter": {
            "status": report["status"],
            "report": file_binding(adapter_output_dir / "adapter_report_v1.json"),
            "state": file_binding(adapter_output_dir / "adapter_state_v1.json"),
            "sealed_evidence_unchanged": True,
            "scientific_metrics_status": report["scientific_metrics"]["status"],
        },
        "evidence_content_sha256": evidence_after,
    }


def campaign18_operational_rehearsal(
    *, active_bundle_path: Path, proposal_path: Path, output_dir: Path
) -> dict[str, object]:
    """Run and validate the shared activation-bearing Campaign 18 rehearsal."""

    from .active_hybrid_activation import validate_operational_rehearsal
    from .active_hybrid_bundle import validate_bundle as validate_active_bundle
    from .active_hybrid_live_rehearsal import run as run_shared_rehearsal
    from .active_hybrid_programme_contract import CX322_D9_D6_72H_PROGRAMME
    from .active_hybrid_proposal import validate_proposal

    active_bundle_path = active_bundle_path.resolve()
    proposal_path = proposal_path.resolve()
    output_dir = output_dir.resolve()
    bundle = validate_active_bundle(
        active_bundle_path, CX322_D9_D6_72H_PROGRAMME
    )
    proposal = validate_proposal(proposal_path, CX322_D9_D6_72H_PROGRAMME)
    report = run_shared_rehearsal(
        bundle_path=active_bundle_path,
        proposal_path=proposal_path,
        output_dir=output_dir,
    )
    report_path = (
        output_dir / f"{CX322_D9_D6_72H_PROGRAMME.rehearsal_report_type}.json"
    )
    activation_binding = validate_operational_rehearsal(
        report_path,
        bundle=bundle,
        proposal=proposal,
        require_current_tools=True,
        programme=CX322_D9_D6_72H_PROGRAMME,
    )
    transaction = report["real_process_topology"][
        "cx322_real_transaction_path"
    ]
    return {
        "status": "passed",
        "hardware_operations": False,
        "qualification_evidence": False,
        "activation_bindable": True,
        "programme_id": CX322_D9_D6_72H_PROGRAMME.programme_id,
        "profile_id": CX322_D9_D6_72H_PROGRAMME.profile_id,
        "rehearsal": activation_binding,
        "shared_process_topology": {
            "capture": "host.otis_tools.capture_device",
            "supervisor": "host.otis_tools.active_hybrid_live_supervisor",
            "analyzer": "host.otis_tools.active_hybrid_live_analyze",
            "finalizer_and_registration": True,
            "exact_AT2_AH2_required": True,
            "repeated_request_sequences": transaction[
                "request_sequences_consumed"
            ],
            "GNSS_hold_and_causal_requalification": transaction[
                "gnss_hold_and_causal_requalification"
            ],
        },
    }


def _atomic_write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    with temporary.open("w", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _stable_csv_payload(path: Path) -> bytes:
    payload = path.read_bytes()
    if not payload:
        return b""
    newline = payload.rfind(b"\n")
    return b"" if newline < 0 else payload[: newline + 1]


def _read_exact_retained_csv(
    *, path: Path, contract_id: str, previous: Mapping[str, Any] | None
) -> tuple[list[dict[str, str]], dict[str, object]]:
    payload = _stable_csv_payload(path)
    if previous is not None:
        consumed = int(previous["consumed_size_bytes"])
        if len(payload) < consumed:
            raise ValueError(f"retained source truncated after consumption: {path}")
        if sha256(payload[:consumed]).hexdigest() != previous["prefix_sha256"]:
            raise ValueError(f"retained source prefix changed after consumption: {path}")
    try:
        text_payload = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ValueError(f"retained source is not UTF-8: {path}") from exc
    reader = csv.DictReader(io.StringIO(text_payload, newline=""))
    expected_fields = CONTRACT_FIELDS[contract_id]
    if reader.fieldnames != expected_fields:
        raise ValueError(
            f"{contract_id} header mismatch: expected {expected_fields}, "
            f"got {reader.fieldnames}"
        )
    rows = list(reader)
    previous_sequence: int | None = None
    for number, row in enumerate(rows, start=1):
        if None in row or any(row.get(field) is None for field in expected_fields):
            raise ValueError(f"{contract_id} row {number} is malformed")
        if row["record_type"] not in CONTRACT_RECORD_TYPES[contract_id]:
            raise ValueError(f"{contract_id} row {number} record type differs")
        if row["schema_version"] != str(CONTRACT_SCHEMA_VERSIONS[contract_id]):
            raise ValueError(f"{contract_id} row {number} schema differs")
        sequence_field = SEQUENCE_FIELDS[contract_id]
        try:
            sequence = int(row[sequence_field], 10)
        except ValueError as exc:
            raise ValueError(
                f"{contract_id} row {number} sequence is not an integer"
            ) from exc
        if previous_sequence is not None and sequence <= previous_sequence:
            raise ValueError(f"{contract_id} retained ordering differs")
        previous_sequence = sequence
    return rows, {
        "consumed_size_bytes": len(payload),
        "prefix_sha256": sha256(payload).hexdigest(),
        "row_count": len(rows),
    }


def _read_exact_sidecar_csv(
    *,
    path: Path,
    fields: list[str],
    record_type: str,
    sequence_field: str,
    previous: Mapping[str, Any] | None,
) -> tuple[list[dict[str, str]], dict[str, object]]:
    payload = _stable_csv_payload(path)
    if previous is not None:
        consumed = int(previous["consumed_size_bytes"])
        if len(payload) < consumed:
            raise ValueError(f"retained sidecar truncated after consumption: {path}")
        if sha256(payload[:consumed]).hexdigest() != previous["prefix_sha256"]:
            raise ValueError(
                f"retained sidecar prefix changed after consumption: {path}"
            )
    reader = csv.DictReader(io.StringIO(payload.decode("utf-8"), newline=""))
    if reader.fieldnames != fields:
        raise ValueError(
            f"retained exact-timing sidecar header differs: {path}"
        )
    rows = list(reader)
    last_sequence = 0
    last_ticks: int | None = None
    for number, row in enumerate(rows, start=1):
        try:
            sequence = int(row[sequence_field])
            timestamp_field = (
                "event_timestamp_ticks"
                if record_type == "AT2"
                else "decision_timestamp_ticks"
            )
            timestamp = int(row[timestamp_field])
        except (KeyError, ValueError) as exc:
            raise ValueError(
                f"retained exact-timing sidecar row {number} is malformed"
            ) from exc
        if (
            row["record_type"] != record_type
            or row["schema_version"] != "2"
            or row["time_domain"] != EXACT_LIFECYCLE_TIME_DOMAIN
            or sequence <= last_sequence
            or (last_ticks is not None and timestamp < last_ticks)
        ):
            raise ValueError(
                f"retained exact-timing sidecar row {number} identity differs"
            )
        last_sequence = sequence
        last_ticks = timestamp
    return rows, {
        "consumed_size_bytes": len(payload),
        "prefix_sha256": sha256(payload).hexdigest(),
        "row_count": len(rows),
    }


def _sidecar_join_inspection(
    *,
    transactions: list[dict[str, str]],
    decisions: list[dict[str, str]],
    transaction_timings: list[dict[str, str]],
    decision_timings: list[dict[str, str]],
) -> dict[str, object]:
    declarations = {
        item["contract"]: item for item in _LIVE_SOURCE_DECLARATIONS
    }
    mismatches: list[str] = []
    transaction_by_sequence = {
        row["transaction_record_sequence"]: row for row in transactions
    }
    seen_transactions: set[str] = set()
    transaction_decl = declarations["active_transactions_v2"]
    for timing in transaction_timings:
        sequence = timing["transaction_record_sequence"]
        source = transaction_by_sequence.get(sequence)
        if source is None:
            mismatches.append(f"AT2 orphan transaction_record_sequence={sequence}")
            continue
        seen_transactions.add(sequence)
        if any(
            timing[field] != source[field]
            for field in transaction_decl["join_fields"]
        ):
            mismatches.append(f"AT2 join mismatch transaction_record_sequence={sequence}")
    missing_transactions = sorted(
        set(transaction_by_sequence) - seen_transactions, key=int
    )
    if missing_transactions:
        mismatches.append(
            "AT2 missing transaction_record_sequence="
            + ",".join(missing_transactions)
        )

    decision_by_sequence = {
        row["hybrid_record_sequence"]: row for row in decisions
    }
    seen_decisions: set[str] = set()
    decision_decl = declarations["active_hybrid_decisions_v2"]
    for timing in decision_timings:
        sequence = timing["hybrid_record_sequence"]
        source = decision_by_sequence.get(sequence)
        if source is None:
            mismatches.append(f"AH2 orphan hybrid_record_sequence={sequence}")
            continue
        seen_decisions.add(sequence)
        if any(
            timing[field] != source[field]
            for field in decision_decl["join_fields"]
        ):
            mismatches.append(f"AH2 join mismatch hybrid_record_sequence={sequence}")
    missing_decisions = sorted(set(decision_by_sequence) - seen_decisions, key=int)
    if missing_decisions:
        mismatches.append(
            "AH2 missing hybrid_record_sequence=" + ",".join(missing_decisions)
        )
    return {
        "exact": bool(
            transactions
            and decisions
            and transaction_timings
            and decision_timings
            and not mismatches
        ),
        "AT2_rows": len(transaction_timings),
        "AH2_rows": len(decision_timings),
        "mismatches": mismatches,
        "coarse_seconds_used_as_ticks": False,
    }


def _fraction_value(value: Fraction) -> dict[str, int]:
    return {"numerator": value.numerator, "denominator": value.denominator}


def _fraction_summary(values: list[Fraction]) -> dict[str, object]:
    if not values:
        return {"sample_count": 0}
    return {
        "sample_count": len(values),
        "minimum": _fraction_value(min(values)),
        "maximum": _fraction_value(max(values)),
        "mean": _fraction_value(sum(values, Fraction()) / len(values)),
    }


def _fraction_distribution(values: list[Fraction]) -> dict[str, object]:
    summary = _fraction_summary(values)
    if not values:
        return summary
    mean = sum(values, Fraction()) / len(values)
    variance = sum((value - mean) ** 2 for value in values) / len(values)
    return {**summary, "population_variance": _fraction_value(variance)}


def _d14_relative_frequency_samples(
    raw_rows: list[dict[str, str]],
    count_rows: list[dict[str, str]],
) -> tuple[list[dict[str, Any]], list[int]]:
    reference_ticks = {
        int(row["timestamp_ticks"])
        for row in raw_rows
        if row["record_type"] == "REF"
        and row["channel_id"] == "1"
        and int(row["flags"], 0) == 0
    }
    samples: list[dict[str, Any]] = []
    invalid: list[int] = []
    previous_raw_close: int | None = None
    previous_extended_close: int | None = None
    for row in count_rows:
        if row["channel_id"] != "2":
            continue
        sequence = int(row["count_seq"])
        raw_opening = int(row["gate_open_ticks"])
        raw_closing = int(row["gate_close_ticks"])
        progress = forward_progress(
            raw_opening,
            raw_closing,
            domain=row["gate_domain"],
            allow_equal=False,
        )
        duration = progress.distance_ticks
        if (
            int(row["flags"], 0) != 0
            or not progress.valid
            or duration is None
            or raw_opening not in reference_ticks
            or raw_closing not in reference_ticks
        ):
            invalid.append(sequence)
            continue
        if previous_raw_close is None:
            extended_closing = (
                raw_closing
                + progress.rollover_count * RP2040_TIMER0_MICROS_WRAP_TICKS
            )
        else:
            between = forward_progress(
                previous_raw_close,
                raw_closing,
                domain=row["gate_domain"],
                allow_equal=False,
            )
            if (
                not between.valid
                or between.distance_ticks is None
                or previous_extended_close is None
            ):
                invalid.append(sequence)
                continue
            extended_closing = previous_extended_close + between.distance_ticks
        extended_opening = extended_closing - duration
        previous_raw_close = raw_closing
        previous_extended_close = extended_closing
        counted = int(row["counted_edges"])
        error_nanohz = Fraction(
            (
                counted * RP2040_TIMER0_TICKS_PER_SECOND
                - 10_000_000 * duration
            )
            * 1_000_000_000,
            duration,
        )
        samples.append(
            {
                "count_sequence": sequence,
                "raw_opening_ticks": raw_opening,
                "raw_closing_ticks": raw_closing,
                "opening_ticks": extended_opening,
                "closing_ticks": extended_closing,
                "duration_ticks": duration,
                "counted_edges": counted,
                "frequency_error_nanohz": error_nanohz,
            }
        )
    return samples, invalid


def _exact_lifecycle_timelines(
    transactions: list[dict[str, str]],
    transaction_timings: list[dict[str, str]],
) -> tuple[list[dict[str, int]], list[dict[str, int]]]:
    source = {
        row["transaction_record_sequence"]: row for row in transactions
    }
    setup: list[dict[str, int]] = []
    applications: list[dict[str, int]] = []
    for timing in transaction_timings:
        row = source.get(timing["transaction_record_sequence"])
        if row is None or timing["event"] != row["event"]:
            continue
        event = row["event"]
        if event not in {"manual_start", "application"}:
            continue
        value = {
            "ticks": int(timing["event_timestamp_ticks"]),
            "applied_code": int(row["applied_code"]),
            "dac_epoch": int(row["dac_epoch"]),
            "application_sequence": int(row["application_sequence"]),
            "request_sequence": int(row["request_sequence"]),
            "requested_delta_codes": int(row["requested_delta_codes"]),
        }
        (setup if event == "manual_start" else applications).append(value)
    setup.sort(key=lambda item: item["ticks"])
    applications.sort(key=lambda item: item["ticks"])
    return setup, applications


def _stationary_epoch_metrics(
    samples: list[dict[str, Any]],
    transitions: list[dict[str, int]],
) -> dict[str, object]:
    epochs: dict[tuple[int, int], list[dict[str, Any]]] = {}
    excluded_crossing = 0
    for sample in samples:
        opening = int(sample["opening_ticks"])
        closing = int(sample["closing_ticks"])
        crossing = [
            item for item in transitions if opening < item["ticks"] < closing
        ]
        if crossing:
            excluded_crossing += 1
            continue
        preceding = [item for item in transitions if item["ticks"] <= opening]
        if not preceding:
            continue
        identity = preceding[-1]
        epochs.setdefault(
            (identity["dac_epoch"], identity["applied_code"]), []
        ).append(sample)
    output: list[dict[str, object]] = []
    for (epoch, code), values in sorted(epochs.items()):
        errors = [item["frequency_error_nanohz"] for item in values]
        drift: Fraction | None = None
        if len(values) >= 2:
            x_values = [int(item["closing_ticks"]) for item in values]
            count = len(values)
            denominator = count * sum(x * x for x in x_values) - sum(
                x_values
            ) ** 2
            if denominator > 0:
                slope_nanohz_per_tick = Fraction(
                    count
                    * sum(
                        Fraction(x) * error
                        for x, error in zip(x_values, errors, strict=True)
                    )
                    - Fraction(sum(x_values)) * sum(errors, Fraction()),
                    denominator,
                )
                drift = (
                    slope_nanohz_per_tick
                    * 3600
                    * RP2040_TIMER0_TICKS_PER_SECOND
                )
        output.append(
            {
                "dac_epoch": epoch,
                "applied_code": code,
                "frequency_error_nanohz": _fraction_summary(errors),
                "stationary_drift_nanohz_per_hour": (
                    None if drift is None else _fraction_value(drift)
                ),
                "first_closing_ticks": values[0]["closing_ticks"],
                "last_closing_ticks": values[-1]["closing_ticks"],
            }
        )
    return {
        "epoch_count": len(output),
        "epochs": output,
        "intervals_excluded_for_application_crossing": excluded_crossing,
    }


def _candidate_window_fitness(
    *,
    samples: list[dict[str, Any]],
    transitions: list[dict[str, int]],
    decisions: list[dict[str, str]],
    decision_timings: list[dict[str, str]],
) -> dict[str, object]:
    """Compare fixed offline windows without changing live controller authority."""

    candidate_windows_s = (60, 300, 600, 900, 1800)
    epochs: dict[tuple[int, int], list[dict[str, Any]]] = {}
    ordered_transitions = sorted(transitions, key=lambda item: item["ticks"])
    transition_index = -1
    for sample in sorted(samples, key=lambda item: item["closing_ticks"]):
        opening = int(sample["opening_ticks"])
        closing = int(sample["closing_ticks"])
        while (
            transition_index + 1 < len(ordered_transitions)
            and ordered_transitions[transition_index + 1]["ticks"] <= opening
        ):
            transition_index += 1
        if transition_index < 0:
            continue
        if (
            transition_index + 1 < len(ordered_transitions)
            and ordered_transitions[transition_index + 1]["ticks"] < closing
        ):
            continue
        identity = ordered_transitions[transition_index]
        epochs.setdefault(
            (identity["dac_epoch"], identity["applied_code"]), []
        ).append(sample)

    decision_source = {
        row["hybrid_record_sequence"]: row for row in decisions
    }
    return _candidate_window_fitness_from_epochs(
        candidate_windows_s=candidate_windows_s,
        epochs=epochs,
        decision_source=decision_source,
        decision_timings=decision_timings,
    )


def _phase_pull_in_candidate_fitness(
    *,
    phase_observations: list[dict[str, str]],
    phase_estimates: list[dict[str, str]],
    decisions: list[dict[str, str]],
    transactions: list[dict[str, str]],
    transaction_timings: list[dict[str, str]],
) -> dict[str, object]:
    """Assess pull-in choices on the realized phase trajectory only."""

    pull_in_candidates_s = (3_600, 10_800, 21_600, 43_200)
    cap_hz = Fraction(1, 600)
    raw_by_ref = {
        f"RPH:{row.get('phase_epoch')}:{row.get('observation_sequence')}": row
        for row in phase_observations
    }
    joined: list[dict[str, int | Fraction]] = []
    join_mismatches: list[str] = []
    for estimate in phase_estimates:
        source_ref = estimate.get("source_relative_phase_observation", "")
        raw = raw_by_ref.get(source_ref)
        if raw is None:
            join_mismatches.append(source_ref or "missing_source_reference")
            continue
        if (
            raw.get("qualification_state") != "qualified"
            or estimate.get("qualification_state") != "qualified"
            or raw.get("discontinuity_reason") not in {"", "none"}
        ):
            continue
        try:
            joined.append(
                {
                    "phase_epoch": int(raw["phase_epoch"]),
                    "observation_sequence": int(raw["observation_sequence"]),
                    "closing_reference_sequence": int(
                        raw["closing_reference_sequence"]
                    ),
                    "filtered_relative_phase_cycles": Fraction(
                        estimate["filtered_relative_phase_cycles"]
                    ),
                }
            )
        except (KeyError, ValueError, ZeroDivisionError):
            join_mismatches.append(source_ref or "malformed_source_reference")
    joined.sort(
        key=lambda item: (
            int(item["phase_epoch"]),
            int(item["observation_sequence"]),
        )
    )
    candidates: list[dict[str, object]] = []
    deployed_terms: list[Fraction] = []
    for pull_in_s in pull_in_candidates_s:
        unclamped = [
            -Fraction(item["filtered_relative_phase_cycles"], pull_in_s)
            for item in joined
        ]
        clamped = [max(-cap_hz, min(cap_hz, value)) for value in unclamped]
        cap_count = sum(abs(value) >= cap_hz for value in unclamped)
        if pull_in_s == 21_600:
            deployed_terms = clamped
        candidates.append(
            {
                "pull_in_time_s": pull_in_s,
                "observation_count": len(clamped),
                "absolute_phase_bias_cap_hz": _fraction_value(cap_hz),
                "unclamped_phase_bias_hz": _fraction_summary(unclamped),
                "clamped_phase_bias_hz": _fraction_summary(clamped),
                "cap_residence_count": cap_count,
                "cap_residence_fraction": _fraction_value(
                    Fraction(cap_count, len(clamped)) if clamped else Fraction()
                ),
                "closed_loop_outcome_replayed": False,
            }
        )

    epochs: dict[int, list[dict[str, int | Fraction]]] = {}
    for item in joined:
        epochs.setdefault(int(item["phase_epoch"]), []).append(item)
    epoch_behavior: list[dict[str, object]] = []
    total_crossings = 0
    total_reversals = 0
    for epoch, values in sorted(epochs.items()):
        phases = [Fraction(item["filtered_relative_phase_cycles"]) for item in values]
        crossings = sum(
            1
            for left, right in zip(phases, phases[1:])
            if left != 0 and right != 0 and (left > 0) != (right > 0)
        )
        slopes = [right - left for left, right in zip(phases, phases[1:])]
        nonzero_slope_signs = [1 if value > 0 else -1 for value in slopes if value]
        reversals = sum(
            left != right
            for left, right in zip(
                nonzero_slope_signs, nonzero_slope_signs[1:]
            )
        )
        total_crossings += crossings
        total_reversals += reversals
        epoch_behavior.append(
            {
                "phase_epoch": epoch,
                "observation_count": len(phases),
                "opening_abs_phase_cycles": _fraction_value(abs(phases[0])),
                "closing_abs_phase_cycles": _fraction_value(abs(phases[-1])),
                "net_abs_phase_reduction_cycles": _fraction_value(
                    abs(phases[0]) - abs(phases[-1])
                ),
                "zero_crossing_overshoot_count": crossings,
                "phase_direction_reversal_count": reversals,
            }
        )

    timed_transaction_sequences = {
        row["transaction_record_sequence"] for row in transaction_timings
    }
    applied_decision_sequences = {
        row["decision_sequence"]
        for row in transactions
        if row.get("event") == "application"
        and row.get("transaction_record_sequence")
        in timed_transaction_sequences
        and row.get("i2c_ok") == "true"
    }
    phase_by_identity = {
        (int(item["phase_epoch"]), int(item["observation_sequence"])): item
        for item in joined
    }
    effects: list[dict[str, object]] = []
    for decision in decisions:
        if (
            decision.get("decision_sequence") not in applied_decision_sequences
            or decision.get("phase_materially_influenced") != "true"
        ):
            continue
        try:
            identity = (
                int(decision["phase_epoch"]),
                int(decision["phase_observation_sequence"]),
            )
            source = phase_by_identity[identity]
        except (KeyError, ValueError):
            continue
        source_abs = abs(Fraction(source["filtered_relative_phase_cycles"]))
        later = [
            item
            for item in epochs[identity[0]]
            if int(item["observation_sequence"]) > identity[1]
            and abs(Fraction(item["filtered_relative_phase_cycles"])) < source_abs
        ]
        first = later[0] if later else None
        effects.append(
            {
                "decision_sequence": int(decision["decision_sequence"]),
                "phase_epoch": identity[0],
                "source_phase_observation_sequence": identity[1],
                "opening_abs_phase_cycles": _fraction_value(source_abs),
                "time_to_first_abs_phase_reduction_D14_intervals": (
                    None
                    if first is None
                    else int(first["closing_reference_sequence"])
                    - int(source["closing_reference_sequence"])
                ),
                "effect_observed": first is not None,
            }
        )
    deployed_cap_count = sum(abs(value) >= cap_hz for value in deployed_terms)
    return {
        "status": (
            "observational_exact_join"
            if joined and not join_mismatches
            else "unavailable_or_partial"
        ),
        "candidate_pull_in_times_s": list(pull_in_candidates_s),
        "candidate_comparison": candidates,
        "deployed_pull_in_time_s": 21_600,
        "deployed_21600_behavior": {
            "cap_residence_count": deployed_cap_count,
            "cap_residence_fraction": _fraction_value(
                Fraction(deployed_cap_count, len(deployed_terms))
                if deployed_terms
                else Fraction()
            ),
            "phase_epochs": epoch_behavior,
            "zero_crossing_overshoot_count": total_crossings,
            "phase_direction_reversal_count": total_reversals,
            "application_time_to_effect": effects,
            "time_to_effect_domain": "qualified_contiguous_D14_intervals",
        },
        "phase_estimator_join_mismatches": sorted(join_mismatches),
        "live_tuning_or_authority_changed": False,
        "limitations": [
            "candidate terms are evaluated on the single realized deployed phase trajectory; alternative actuation and resulting closed-loop trajectories are not identifiable",
            "the retained selected phase-estimator output supports phase-bias, cap-residence, realized phase-error reduction, overshoot, reversal, and D14-interval time-to-effect observations, not causal ranking of pull-in candidates",
            "time-to-effect remains in contiguous authoritative D14 intervals because retained RPH/PHE records do not carry exact RP2040 timestamps",
        ],
    }


def _candidate_window_fitness_from_epochs(
    *,
    candidate_windows_s: tuple[int, ...],
    epochs: dict[tuple[int, int], list[dict[str, Any]]],
    decision_source: dict[str, dict[str, str]],
    decision_timings: list[dict[str, str]],
) -> dict[str, object]:
    decision_points: list[tuple[int, Fraction]] = []
    for timing in decision_timings:
        row = decision_source.get(timing["hybrid_record_sequence"])
        if row is None:
            continue
        try:
            decision_points.append(
                (
                    int(timing["decision_timestamp_ticks"]),
                    Fraction(row["phase_term_hz"]) * 1_000_000_000,
                )
            )
        except (KeyError, ValueError, ZeroDivisionError):
            continue
    decision_points.sort()

    candidates: list[dict[str, object]] = []
    for window_s in candidate_windows_s:
        target_ticks = window_s * RP2040_TIMER0_TICKS_PER_SECOND
        all_means: list[Fraction] = []
        all_residuals: list[Fraction] = []
        all_drifts: list[Fraction] = []
        phase_ratios: list[Fraction] = []
        phase_terms: list[Fraction] = []
        per_epoch: list[dict[str, object]] = []
        for (epoch, code), epoch_samples in sorted(epochs.items()):
            start = 0
            support = 0
            weighted = Fraction()
            previous_close: int | None = None
            window_points: list[tuple[int, Fraction]] = []
            epoch_means: list[Fraction] = []
            epoch_residuals: list[Fraction] = []
            epoch_drifts: list[Fraction] = []
            for end, sample in enumerate(epoch_samples):
                opening = int(sample["opening_ticks"])
                closing = int(sample["closing_ticks"])
                duration = int(sample["duration_ticks"])
                if previous_close is not None and opening != previous_close:
                    start = end
                    support = 0
                    weighted = Fraction()
                previous_close = closing
                support += duration
                weighted += sample["frequency_error_nanohz"] * duration
                while support > target_ticks and start <= end:
                    removed = epoch_samples[start]
                    removed_duration = int(removed["duration_ticks"])
                    support -= removed_duration
                    weighted -= (
                        removed["frequency_error_nanohz"] * removed_duration
                    )
                    start += 1
                if support != target_ticks:
                    continue
                mean = weighted / target_ticks
                residual = abs(mean - sample["frequency_error_nanohz"])
                epoch_means.append(mean)
                epoch_residuals.append(residual)
                window_points.append((closing, mean))
                if len(window_points) >= 2:
                    prior_close, prior_mean = window_points[-2]
                    delta_ticks = closing - prior_close
                    if delta_ticks > 0:
                        epoch_drifts.append(
                            (mean - prior_mean)
                            * 3600
                            * RP2040_TIMER0_TICKS_PER_SECOND
                            / delta_ticks
                        )
            closes = [item[0] for item in window_points]
            if closes:
                epoch_open = int(epoch_samples[0]["opening_ticks"])
                epoch_close = int(epoch_samples[-1]["closing_ticks"])
                for decision_ticks, phase_term in decision_points:
                    if not epoch_open <= decision_ticks <= epoch_close:
                        continue
                    index = bisect_right(closes, decision_ticks) - 1
                    if index < 0:
                        continue
                    frequency_mean = window_points[index][1]
                    phase_terms.append(phase_term)
                    if frequency_mean != 0:
                        phase_ratios.append(abs(phase_term / frequency_mean))
            all_means.extend(epoch_means)
            all_residuals.extend(epoch_residuals)
            all_drifts.extend(epoch_drifts)
            per_epoch.append(
                {
                    "dac_epoch": epoch,
                    "applied_code": code,
                    "window_estimate_count": len(epoch_means),
                    "frequency_error_nanohz": _fraction_distribution(
                        epoch_means
                    ),
                }
            )
        candidates.append(
            {
                "window_s": window_s,
                "support_ticks": target_ticks,
                "nominal_group_delay_ticks": target_ticks // 2,
                "window_estimate_count": len(all_means),
                "frequency_error_nanohz": _fraction_distribution(all_means),
                "noise_population_variance_nanohz_squared": (
                    _fraction_distribution(all_means).get(
                        "population_variance"
                    )
                ),
                "end_sample_tracking_residual_abs_nanohz": _fraction_summary(
                    all_residuals
                ),
                "successive_window_drift_nanohz_per_hour": _fraction_summary(
                    all_drifts
                ),
                "deployed_PLL_phase_term_nanohz_at_aligned_decisions": (
                    _fraction_summary(phase_terms)
                ),
                "absolute_deployed_phase_to_candidate_frequency_ratio": (
                    _fraction_summary(phase_ratios)
                ),
                "per_stationary_DAC_epoch": per_epoch,
            }
        )
    return {
        "status": "derived_offline_non_authoritative",
        "candidate_windows_s": list(candidate_windows_s),
        "deployed_frequency_window_s": 600,
        "candidates": candidates,
        "stationary_DAC_epoch_split_required": True,
        "live_tuning_or_authority_changed": False,
        "limitations": [
            "candidate FLL windows are observational aggregates of retained D14/D8 intervals, not replayed firmware decisions",
            "counterfactual PLL estimator windows are not identifiable because only the deployed phase filter outputs and terms were retained",
            "phase-pull fields align deployed PLL terms to each candidate frequency window and do not claim an alternative PLL law",
            "candidate windows without exact contiguous support inside one stationary DAC epoch remain unavailable rather than interpolated",
            "actuation-dependent closed-loop outcomes cannot be causally ranked from this one realized trajectory",
        ],
    }


def _controller_attribution(
    decisions: list[dict[str, str]],
    decision_timings: list[dict[str, str]],
    transactions: list[dict[str, str]],
    transaction_timings: list[dict[str, str]],
) -> dict[str, object]:
    source = {row["hybrid_record_sequence"]: row for row in decisions}
    timed_transaction_sequences = {
        row["transaction_record_sequence"] for row in transaction_timings
    }
    applied_decisions = {
        row["decision_sequence"]
        for row in transactions
        if row["event"] == "application"
        and row["transaction_record_sequence"] in timed_transaction_sequences
        and row.get("i2c_ok") == "true"
        and int(row.get("applied_code", "0")) != 0
    }
    samples: list[dict[str, object]] = []
    dispositions: Counter[str] = Counter()
    for timing in decision_timings:
        row = source.get(timing["hybrid_record_sequence"])
        if row is None:
            continue
        try:
            requested = int(row["requested_delta_codes"])
            frequency_only = int(row["counterfactual_frequency_only_delta_codes"])
            materially_influenced = _truth_text(row["phase_materially_influenced"])
            sample = {
                "hybrid_record_sequence": int(row["hybrid_record_sequence"]),
                "decision_sequence": int(row["decision_sequence"]),
                "decision_timestamp_ticks": int(timing["decision_timestamp_ticks"]),
                "frequency_term_hz": _fraction_value(
                    Fraction(row["frequency_term_hz"])
                ),
                "phase_term_hz": _fraction_value(Fraction(row["phase_term_hz"])),
                "combined_demand_hz": _fraction_value(
                    Fraction(row["combined_demand_hz"])
                ),
                "requested_delta_codes": requested,
                "counterfactual_frequency_only_delta_codes": frequency_only,
                "phase_materially_influenced": materially_influenced,
                "phase_delta_contribution_codes": requested - frequency_only,
                "reason": row["reason"],
                "exact_ACT_application_join": (
                    row["decision_sequence"] in applied_decisions
                ),
            }
        except (KeyError, ValueError, ZeroDivisionError) as exc:
            raise ValueError(
                "AHY retained controller-attribution fields are malformed"
            ) from exc
        samples.append(sample)
        if row["decision_sequence"] in applied_decisions:
            dispositions["APPLICATION_REQUESTED_APPLIED"] += 1
        elif "gnss" in row["reason"].lower() or "metadata" in row["reason"].lower():
            dispositions["GNSS_METADATA_HOLD"] += 1
        elif row["range_clamped"] == "true":
            dispositions["RANGE_BOUND_HOLD"] += 1
        elif row["cadence_limited"] == "true":
            dispositions["POLICY_HOLD"] += 1
        elif row["count_limited"] == "true" or row["cumulative_budget_limited"] == "true":
            dispositions["POLICY_HOLD"] += 1
        else:
            dispositions["NO_CORRECTION_REQUESTED"] += 1
    return {
        "decision_count": len(samples),
        "samples": samples,
        "phase_material_decision_count": sum(
            bool(item["phase_materially_influenced"]) for item in samples
        ),
        "frequency_only_counterfactual_difference_count": sum(
            item["requested_delta_codes"]
            != item["counterfactual_frequency_only_delta_codes"]
            for item in samples
        ),
        "opportunity_dispositions": dict(sorted(dispositions.items())),
        "lost_opportunity_count": sum(
            count
            for disposition, count in dispositions.items()
            if disposition != "APPLICATION_REQUESTED_APPLIED"
        ),
        "application_disposition_requires_exact_ACT_application_join": True,
    }


def _response_and_chatter_metrics(
    samples: list[dict[str, Any]],
    applications: list[dict[str, int]],
    *,
    qualification_endpoint_ticks: int | None,
) -> tuple[dict[str, object], dict[str, object], dict[str, object]]:
    horizons_s = (600, 1500, 3600, 7200, 21_600)
    samples_by_close = {int(row["closing_ticks"]): row for row in samples}
    last_evidence_ticks = max(samples_by_close, default=0)
    horizon_rows: list[dict[str, object]] = []
    gains: list[Fraction] = []
    overshoot_count = 0
    application_deltas = [item["requested_delta_codes"] for item in applications]
    for index, application in enumerate(applications):
        application_ticks = application["ticks"]
        next_application_ticks = (
            applications[index + 1]["ticks"]
            if index + 1 < len(applications)
            else None
        )
        preceding = [
            sample for sample in samples if sample["closing_ticks"] <= application_ticks
        ]
        pre = preceding[-1] if preceding else None
        for horizon_s in horizons_s:
            target = application_ticks + horizon_s * RP2040_TIMER0_TICKS_PER_SECOND
            if next_application_ticks is not None and next_application_ticks <= target:
                status = "right_censored_by_next_application"
                post = None
            elif (
                qualification_endpoint_ticks is not None
                and target > qualification_endpoint_ticks
            ):
                status = "right_censored_by_qualified_endpoint"
                post = None
            elif target > last_evidence_ticks:
                status = "pending_beyond_retained_frontier"
                post = None
            else:
                post = samples_by_close.get(target)
                status = "observed_exact" if post is not None else "exact_boundary_absent"
            row: dict[str, object] = {
                "application_sequence": application["application_sequence"],
                "application_ticks": application_ticks,
                "horizon_s": horizon_s,
                "target_ticks": target,
                "status": status,
                "next_application_ticks": next_application_ticks,
                "retained_endpoint_ticks": last_evidence_ticks,
                "qualified_endpoint_ticks": qualification_endpoint_ticks,
            }
            if pre is not None and post is not None:
                pre_error = pre["frequency_error_nanohz"]
                post_error = post["frequency_error_nanohz"]
                response = post_error - pre_error
                row.update(
                    {
                        "pre_frequency_error_nanohz": _fraction_value(pre_error),
                        "post_frequency_error_nanohz": _fraction_value(post_error),
                        "observed_response_nanohz": _fraction_value(response),
                    }
                )
                if application["requested_delta_codes"] != 0:
                    gain = response / application["requested_delta_codes"]
                    gains.append(gain)
                    row["gain_nanohz_per_code"] = _fraction_value(gain)
            horizon_rows.append(row)
        if pre is not None:
            ending = next_application_ticks or last_evidence_ticks
            interval_errors = [
                sample["frequency_error_nanohz"]
                for sample in samples
                if application_ticks < sample["closing_ticks"] <= ending
            ]
            pre_error = pre["frequency_error_nanohz"]
            if pre_error and any(error * pre_error < 0 for error in interval_errors):
                overshoot_count += 1
    direction_reversals = sum(
        1
        for left, right in zip(application_deltas, application_deltas[1:])
        if left and right and (left > 0) != (right > 0)
    )
    application_separations = [
        right["ticks"] - left["ticks"]
        for left, right in zip(applications, applications[1:])
    ]
    return (
        {
            "horizons_s": list(horizons_s),
            "records": horizon_rows,
            "status_counts": dict(
                sorted(Counter(row["status"] for row in horizon_rows).items())
            ),
        },
        {
            "gain_nanohz_per_code": _fraction_summary(gains),
            "application_overshoot_count": overshoot_count,
        },
        {
            "application_count": len(applications),
            "direction_reversal_count": direction_reversals,
            "application_separation_ticks": (
                {"sample_count": 0}
                if not application_separations
                else {
                    "sample_count": len(application_separations),
                    "minimum": min(application_separations),
                    "maximum": max(application_separations),
                }
            ),
            "minimum_cadence_violation_count": sum(
                separation
                < 1800 * RP2040_TIMER0_TICKS_PER_SECOND
                for separation in application_separations
            ),
        },
    )


def _qualification_boundary_ticks(
    *,
    decisions: list[dict[str, str]],
    decision_timings: list[dict[str, str]],
    samples: list[dict[str, Any]],
) -> tuple[int | None, int | None]:
    decision_by_sequence = {
        row["hybrid_record_sequence"]: row for row in decisions
    }
    candidates: list[int] = []
    for timing in decision_timings:
        row = decision_by_sequence.get(timing["hybrid_record_sequence"])
        if row is None:
            continue
        try:
            source_span = (
                int(row["source_last_sequence"])
                - int(row["source_first_sequence"])
                + 1
            )
        except ValueError:
            continue
        if source_span == 600 and row["phase_recorder_published"] == "true":
            candidates.append(int(timing["decision_timestamp_ticks"]))
    if not candidates:
        return None, None
    origin = min(candidates)
    remaining = 259_200 * RP2040_TIMER0_TICKS_PER_SECOND
    for sample in sorted(samples, key=lambda item: item["closing_ticks"]):
        opening = max(int(sample["opening_ticks"]), origin)
        closing = int(sample["closing_ticks"])
        if closing <= opening:
            continue
        interval = closing - opening
        if interval >= remaining:
            return origin, opening + remaining
        remaining -= interval
    return origin, None


def derive_retained_scientific_metrics(
    *,
    rows: Mapping[str, list[dict[str, str]]],
    transaction_timings: list[dict[str, str]],
    decision_timings: list[dict[str, str]],
) -> dict[str, object]:
    """Derive campaign metrics solely from retained exact joined records."""

    frequency_samples, invalid_counts = _d14_relative_frequency_samples(
        rows["raw_events_v1"], rows["count_observations_v1"]
    )
    frequency_errors = [
        item["frequency_error_nanohz"] for item in frequency_samples
    ]
    sidecar_join = _sidecar_join_inspection(
        transactions=rows["active_transactions_v1"],
        decisions=rows["active_hybrid_decisions_v1"],
        transaction_timings=transaction_timings,
        decision_timings=decision_timings,
    )
    producer_field_blockers: list[str] = []
    if rows["active_transactions_v1"] and not transaction_timings:
        producer_field_blockers.append(
            "active_transactions_v2.event_timestamp_ticks"
        )
    if rows["active_hybrid_decisions_v1"] and not decision_timings:
        producer_field_blockers.append(
            "active_hybrid_decisions_v2.decision_timestamp_ticks"
        )
    setup, applications = _exact_lifecycle_timelines(
        rows["active_transactions_v1"], transaction_timings
    )
    if transaction_timings and not setup:
        producer_field_blockers.append(
            "active_transactions_v2.manual_start.event_timestamp_ticks"
        )
    transitions = [*setup, *applications]
    transitions.sort(key=lambda item: item["ticks"])
    stationary = _stationary_epoch_metrics(frequency_samples, transitions)
    candidate_windows = _candidate_window_fitness(
        samples=frequency_samples,
        transitions=transitions,
        decisions=rows["active_hybrid_decisions_v1"],
        decision_timings=decision_timings,
    )
    phase_pull_in_candidates = _phase_pull_in_candidate_fitness(
        phase_observations=rows.get("relative_phase_observations_v1", []),
        phase_estimates=rows.get("phase_estimator_outputs_v1", []),
        decisions=rows["active_hybrid_decisions_v1"],
        transactions=rows["active_transactions_v1"],
        transaction_timings=transaction_timings,
    )
    if decision_timings:
        attribution = _controller_attribution(
            rows["active_hybrid_decisions_v1"],
            decision_timings,
            rows["active_transactions_v1"],
            transaction_timings,
        )
    else:
        attribution = {
            "decision_count": 0,
            "samples": [],
            "phase_material_decision_count": 0,
            "frequency_only_counterfactual_difference_count": 0,
            "opportunity_dispositions": {},
            "lost_opportunity_count": 0,
            "application_disposition_requires_exact_ACT_application_join": True,
        }
    qualification_origin_ticks, qualification_endpoint_ticks = (
        _qualification_boundary_ticks(
            decisions=rows["active_hybrid_decisions_v1"],
            decision_timings=decision_timings,
            samples=frequency_samples,
        )
    )
    response, gain_overshoot, chatter = _response_and_chatter_metrics(
        frequency_samples,
        applications,
        qualification_endpoint_ticks=qualification_endpoint_ticks,
    )
    durations = [item["duration_ticks"] for item in frequency_samples]
    estimator_spans = [
        int(row["source_last_sequence"]) - int(row["source_first_sequence"]) + 1
        for row in rows["active_hybrid_decisions_v1"]
    ]
    return {
        "status": (
            "exact"
            if sidecar_join["exact"] and not producer_field_blockers
            else "partial_blocked"
        ),
        "hard_producer_field_blockers": producer_field_blockers,
        "sidecar_join": sidecar_join,
        "D14_relative_frequency_distribution_nanohz": _fraction_summary(
            frequency_errors
        ),
        "stationary_DAC_epoch_drift": stationary,
        "response_horizons": response,
        "qualification_boundaries": {
            "origin_ticks": qualification_origin_ticks,
            "endpoint_ticks": qualification_endpoint_ticks,
            "origin_derivation": (
                "first_exact_AH2_decision_with_600_interval_AHY_source_and_"
                "published_phase_observation"
            ),
            "endpoint_derivation": (
                "259200_exact_qualified_D14_D8_ticks_after_origin"
            ),
        },
        "FLL_PLL_phase_and_counterfactual_attribution": attribution,
        "gain_and_overshoot": gain_overshoot,
        "chatter": chatter,
        "lost_opportunities": {
            "count": attribution["lost_opportunity_count"],
            "dispositions": attribution["opportunity_dispositions"],
            "derived_per_decision": bool(decision_timings),
        },
        "measurement_window_fitness": {
            "valid_D14_D8_interval_count": len(frequency_samples),
            "invalid_D14_D8_count_sequences": invalid_counts,
            "valid_fraction": _fraction_value(
                Fraction(
                    len(frequency_samples),
                    len(frequency_samples) + len(invalid_counts),
                )
                if frequency_samples or invalid_counts
                else Fraction()
            ),
            "duration_ticks": (
                {"sample_count": 0}
                if not durations
                else {
                    "sample_count": len(durations),
                    "minimum": min(durations),
                    "maximum": max(durations),
                }
            ),
            "estimator_source_interval_span": (
                {"sample_count": 0}
                if not estimator_spans
                else {
                    "sample_count": len(estimator_spans),
                    "minimum": min(estimator_spans),
                    "maximum": max(estimator_spans),
                }
            ),
            "candidate_window_comparison": candidate_windows,
            "PLL_pull_in_candidate_comparison": phase_pull_in_candidates,
        },
        "caller_supplied_metric_summaries_used": False,
        "coarse_seconds_projected_to_ticks": False,
    }


def _manifest_paths(run_directory: Path) -> dict[str, str]:
    manifest = _read_json(run_directory / "run_manifest.json")
    entries = manifest.get("files")
    if not isinstance(entries, list):
        raise ValueError("retained run manifest lacks files")
    paths: dict[str, str] = {}
    root = run_directory.resolve()
    for entry in entries:
        if not isinstance(entry, Mapping):
            raise ValueError("retained run manifest file entry differs")
        contract_id = str(entry.get("contract", ""))
        relative = str(entry.get("path", ""))
        if contract_id in paths:
            raise ValueError(f"duplicate retained contract path: {contract_id}")
        resolved = (root / relative).resolve()
        if not resolved.is_relative_to(root):
            raise ValueError("retained contract path escapes run directory")
        paths[contract_id] = relative
    return paths


def _truth_text(value: str) -> bool:
    if value not in {"true", "false"}:
        raise ValueError(f"expected exact Boolean text, got {value!r}")
    return value == "true"


def _structural_lifecycles(
    transactions: list[dict[str, str]],
    decisions: list[dict[str, str]],
) -> dict[str, object]:
    grouped: dict[tuple[str, str], list[dict[str, str]]] = {}
    for row in transactions:
        if row["event"] == "manual_start":
            continue
        key = (row["session_id"], row["request_sequence"])
        grouped.setdefault(key, []).append(row)
    complete: list[dict[str, object]] = []
    incomplete: list[dict[str, object]] = []
    expected_events = [
        "request_created",
        "request_accepted",
        "application",
        "response",
    ]
    for key, rows in sorted(grouped.items(), key=lambda item: int(item[0][1])):
        events = [row["event"] for row in rows]
        present = [event for event in expected_events if event in events]
        ordered = [events.index(event) for event in present] == sorted(
            events.index(event) for event in present
        )
        identity_fields = (
            "run_identity",
            "build_identity",
            "profile_identity",
            "session_id",
            "nonce",
            "request_sequence",
            "decision_sequence",
            "source_first_sequence",
            "source_last_sequence",
        )
        identity_exact = all(
            len({row[field] for row in rows}) == 1 for field in identity_fields
        )
        application = next(
            (row for row in rows if row["event"] == "application"), None
        )
        response = next((row for row in rows if row["event"] == "response"), None)
        consumers = [
            row
            for row in decisions
            if row["capture_session"] == key[0]
            and row["request_sequence"] == key[1]
            and application is not None
            and row["application_sequence"] == application["application_sequence"]
            and row["actual_applied_code"] == application["applied_code"]
            and row["actual_dac_epoch"] == application["dac_epoch"]
            and row["downstream_epoch_exact"] == "true"
            and response is not None
            and row["response_class"] == response["response_class"]
        ]
        lifecycle = {
            "session_id": int(key[0]),
            "request_sequence": int(key[1]),
            "events": events,
            "identity_exact": identity_exact,
            "first_dependent_consumer_exact": len(consumers) >= 1,
            "decision_sequence": (
                None if not rows else int(rows[0]["decision_sequence"])
            ),
            "application_sequence": (
                None if application is None else int(application["application_sequence"])
            ),
            "dac_epoch": None if application is None else int(application["dac_epoch"]),
            "applied_code": (
                None if application is None else int(application["applied_code"])
            ),
        }
        applied_complete = (
            events == expected_events
            and ordered
            and identity_exact
            and len(consumers) >= 1
        )
        withdrawn_complete = (
            events == ["request_created", "request_withdrawn"]
            and identity_exact
        )
        lifecycle["disposition"] = (
            "APPLICATION_REQUESTED_APPLIED"
            if applied_complete
            else "REQUEST_WITHDRAWN"
            if withdrawn_complete
            else "INCOMPLETE"
        )
        is_complete = applied_complete or withdrawn_complete
        (complete if is_complete else incomplete).append(lifecycle)
    return {
        "complete_count": len(complete),
        "incomplete_count": len(incomplete),
        "complete": complete,
        "incomplete": incomplete,
        "exact_ticks_available": False,
        "canonical_lifecycle_records_emitted": 0,
    }


def _complete_active_snapshots(
    health_rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    snapshots: list[dict[str, str]] = []
    pending: dict[str, str] | None = None
    generation: str | None = None
    for row in health_rows:
        if row["component"] != "cx317_active":
            continue
        key = row["status_key"]
        value = row["status_value"]
        if key == "snapshot_generation_begin":
            pending = {}
            generation = value
        elif pending is not None and key == "snapshot_generation_complete":
            if value == generation:
                snapshots.append(dict(pending))
            pending = None
            generation = None
        elif pending is not None:
            pending[key] = value
    return snapshots


def _gnss_hold_inspection(
    health_rows: list[dict[str, str]],
    reference_rows: list[dict[str, str]],
) -> dict[str, object]:
    snapshots = _complete_active_snapshots(health_rows)
    hold_entries: list[dict[str, int]] = []
    requalifications: list[dict[str, int]] = []
    retained: dict[str, int] | None = None
    contradictions: list[str] = []
    for snapshot in snapshots:
        if not _GNSS_HOLD_STATUS_KEYS.issubset(snapshot):
            continue
        try:
            active = _truth_text(snapshot["gnss_metadata_hold_active"])
            if active and retained is None:
                retained = {
                    "entry_sequence": int(
                        snapshot["gnss_metadata_hold_entry_sequence"]
                    ),
                    "session_id": int(snapshot["session_id"]),
                    "applied_code": int(snapshot["confirmed_applied_code"], 0),
                    "dac_epoch": int(snapshot["dac_epoch"]),
                }
                hold_entries.append(dict(retained))
            elif active and retained is not None:
                if (
                    int(snapshot["session_id"]) != retained["session_id"]
                    or int(snapshot["confirmed_applied_code"], 0)
                    != retained["applied_code"]
                    or int(snapshot["dac_epoch"]) != retained["dac_epoch"]
                ):
                    contradictions.append("actuation identity changed during GNSS hold")
            elif not active and retained is not None:
                metadata_sequence = int(
                    snapshot["gnss_metadata_requalification_sequence"]
                )
                frontier = int(snapshot["gnss_metadata_qualification_frontier"])
                observation = int(snapshot["d14_d8_observation_sequence"])
                exact = (
                    metadata_sequence > retained["entry_sequence"]
                    and observation > frontier
                    and int(snapshot["session_id"]) == retained["session_id"]
                    and int(snapshot["confirmed_applied_code"], 0)
                    == retained["applied_code"]
                    and int(snapshot["dac_epoch"]) == retained["dac_epoch"]
                    and snapshot.get("state") == "DISARMED"
                )
                if not exact:
                    contradictions.append(
                        "GNSS hold cleared without fresh causal requalification"
                    )
                else:
                    requalifications.append(
                        {
                            "metadata_sequence": metadata_sequence,
                            "qualification_frontier": frontier,
                            "post_qualification_observation_sequence": observation,
                            "session_id": retained["session_id"],
                            "applied_code": retained["applied_code"],
                            "dac_epoch": retained["dac_epoch"],
                        }
                    )
                retained = None
        except (KeyError, ValueError) as exc:
            contradictions.append(f"malformed GNSS hold snapshot: {exc}")
    freshness = Counter(row["metadata_freshness"] for row in reference_rows)
    stale_ticks = [
        int(row["observation_timestamp_ticks"])
        for row in reference_rows
        if row["metadata_freshness"] == "stale"
    ]
    fresh_ticks = [
        int(row["observation_timestamp_ticks"])
        for row in reference_rows
        if row["metadata_freshness"] == "current"
    ]
    fresh_after_stale = bool(
        stale_ticks and fresh_ticks and max(fresh_ticks) > max(stale_ticks)
    )
    if hold_entries and requalifications and not fresh_after_stale:
        contradictions.append(
            "GNSS hold requalification lacks later fresh retained metadata"
        )
    return {
        "complete_active_snapshot_count": len(snapshots),
        "hold_entry_count": len(hold_entries),
        "requalification_count": len(requalifications),
        "hold_entries": hold_entries,
        "requalifications": requalifications,
        "active_at_frontier": retained is not None,
        "metadata_freshness_counts": dict(sorted(freshness.items())),
        "fresh_metadata_after_stale_observed": fresh_after_stale,
        "contradictions": contradictions,
        "control_only": True,
        "D14_D8_measurement_continues": True,
    }


def _timing_and_forwarded_inspection(
    rows: Mapping[str, list[dict[str, str]]],
) -> dict[str, object]:
    references = [
        row
        for row in rows["raw_events_v1"]
        if row["record_type"] == "REF" and row["channel_id"] == "1"
    ]
    counts = [
        row for row in rows["count_observations_v1"] if row["channel_id"] == "2"
    ]
    reference_ticks = {int(row["timestamp_ticks"]) for row in references}
    invalid_counts: list[int] = []
    for row in counts:
        progress = forward_progress(
            int(row["gate_open_ticks"]),
            int(row["gate_close_ticks"]),
            domain=row["gate_domain"],
            allow_equal=False,
        )
        if (
            int(row["flags"], 0) != 0
            or int(row["gate_close_ticks"]) not in reference_ticks
            or not progress.valid
        ):
            invalid_counts.append(int(row["count_seq"]))
    d14_d8_exact = bool(references and counts and not invalid_counts)

    health = {
        (row["component"], row["status_key"]): row["status_value"]
        for row in rows["health_v1"]
    }
    d9_missing: list[str] = []
    d9_mismatches: list[str] = []
    for key, expected in FORWARDED_OUTPUT_INTEGRATION_EXPECTED_HEALTH.items():
        observed = health.get(key)
        label = f"{key[0]}.{key[1]}"
        if observed is None:
            d9_missing.append(label)
        elif observed != expected:
            d9_mismatches.append(f"{label}={observed!r}, expected {expected!r}")
    first_valid = health.get(("forwarded_clock_output", "first_valid_ticks"))
    try:
        if first_valid is None or int(first_valid) <= 0:
            raise ValueError
    except ValueError:
        if first_valid is None:
            d9_missing.append("forwarded_clock_output.first_valid_ticks")
        else:
            d9_mismatches.append(
                "forwarded_clock_output.first_valid_ticks must be positive"
            )

    monitors = rows["forwarded_monitor_snapshots_v1"]
    d6_health_missing = [
        f"{component}.{key}"
        for component, key in FORWARDED_MONITOR_OBSERVABILITY_KEYS
        if (component, key) not in health
    ]
    bad_monitors = [
        int(row["snapshot_sequence"])
        for row in monitors
        if row["channel_id"] != "3" or int(row["status"], 0) != 0
    ]
    local_degraded = bool(d6_health_missing or bad_monitors or not monitors)
    terminal = None
    if references and counts and invalid_counts:
        terminal = "authoritative_capture_fault"
    elif d9_mismatches:
        terminal = "d9_digital_fault"
    return {
        "D14": {
            "read": bool(references),
            "reference_rows": len(references),
            "exact_hardware_ticks_preserved": True,
        },
        "D8": {
            "read": bool(counts),
            "count_rows": len(counts),
            "exact_gate_ticks_preserved": True,
        },
        "D14_D8": {
            "healthy_and_aligned": d14_d8_exact,
            "invalid_count_sequences": invalid_counts,
            "terminal_authority": True,
        },
        "D9": {
            "configuration_and_readback_exact": not d9_missing
            and not d9_mismatches,
            "missing": d9_missing,
            "mismatches": d9_mismatches,
            "waveform_claim": False,
            "terminal_authority": True,
        },
        "D6": {
            "monitor_rows": len(monitors),
            "local_degraded": local_degraded,
            "bad_snapshot_sequences": bad_monitors,
            "missing_health": d6_health_missing,
            "control_authority": False,
            "terminal_authority": False,
        },
        "terminal_classification": terminal,
    }


def _retained_campaign18_endpoint(
    *,
    run_directory: Path,
    structural_lifecycles: Mapping[str, Any],
    health_rows: list[dict[str, str]],
) -> dict[str, object]:
    blockers: list[str] = []
    state_path = run_directory / "reports/cx317_active_supervisor_state.json"
    if not state_path.is_file():
        return {
            "exact": False,
            "hard_blockers": ["campaign18_supervisor_terminal_state_absent"],
        }
    state = _read_json(state_path)
    terminal = state.get("terminal")
    try:
        origin = int(state["qualified_origin_extended_timestamp_ticks"])
        frontier = int(state["qualified_frontier_extended_ticks"])
        endpoint = int(state["qualified_endpoint_extended_timestamp_ticks"])
    except (KeyError, TypeError, ValueError):
        origin = 0
        frontier = 0
        endpoint = 0
        blockers.append("campaign18_exact_qualified_endpoint_ticks_absent")
    target = 259_200 * RP2040_TIMER0_TICKS_PER_SECOND
    elapsed = frontier - origin
    if elapsed < target:
        blockers.append("campaign18_qualified_endpoint_short_or_right_censored")
    if endpoint - origin != target:
        blockers.append("campaign18_qualified_endpoint_not_exact")
    if frontier < endpoint:
        blockers.append("campaign18_frontier_precedes_exact_endpoint")
    if not isinstance(terminal, Mapping) or (
        terminal.get("result") != "healthy_stop"
        or terminal.get("reason")
        != "cx322_d9_d6_72h_72h_qualified_endpoint_complete"
        or terminal.get("preliminary_decision")
        != "pending_offline_scientific_analysis"
    ):
        blockers.append("campaign18_qualified_terminal_absent_or_contradictory")
    if state.get("arm_pending") is not False:
        blockers.append("campaign18_terminal_arm_or_request_pending")
    if state.get("host_verification_hold") is not None:
        blockers.append("campaign18_terminal_host_verification_hold_pending")
    if int(structural_lifecycles.get("incomplete_count", -1)) != 0:
        blockers.append("campaign18_terminal_transaction_incomplete")
    snapshots = _complete_active_snapshots(health_rows)
    final_snapshot = snapshots[-1] if snapshots else {}
    if (
        final_snapshot.get("state") != "DISARMED"
        or final_snapshot.get("evidence_pending") != "false"
        or final_snapshot.get("evidence_phase") != "evidence_clear"
        or final_snapshot.get("evidence_request_sequence") != "0"
        or final_snapshot.get("gnss_metadata_hold_transaction_pending") != "false"
    ):
        blockers.append("campaign18_terminal_snapshot_not_quiescent")
    return {
        "exact": not blockers,
        "qualified_origin_extended_timestamp_ticks": origin,
        "qualified_frontier_extended_timestamp_ticks": frontier,
        "qualified_endpoint_extended_timestamp_ticks": endpoint,
        "qualified_elapsed_ticks": elapsed,
        "required_qualified_ticks": target,
        "terminal": dict(terminal) if isinstance(terminal, Mapping) else None,
        "final_snapshot_state": final_snapshot.get("state"),
        "hard_blockers": blockers,
    }


@dataclass
class RetainedEvidence72hAdapter:
    """Restart-safe read-only scientific adapter over retained evidence.

    It deliberately has no serial, command, ACK, controller, actuator, or
    canonical-stream surface. Exact lifecycle times come only from joined
    AT2/AH2 sidecars; ACT/AHY display seconds are never projected to ticks.
    """

    bundle: Mapping[str, Any]
    activation: Mapping[str, Any]
    state_path: Path | None = None
    report_path: Path | None = None

    def __post_init__(self) -> None:
        self.validation = validate_live_activation(
            bundle=self.bundle, activation=self.activation
        )
        self.run_directory = Path(str(self.activation["run_directory"])).resolve()
        default_output = self.run_directory.parent / (
            f"{self.run_directory.name}_cx322_d9_d6_72h_analysis"
        )
        self.state_path = self.state_path or (default_output / "adapter_state_v1.json")
        self.report_path = self.report_path or (default_output / "adapter_report_v1.json")
        for path in (self.state_path, self.report_path):
            resolved = path.resolve()
            if resolved == self.run_directory or resolved.is_relative_to(
                self.run_directory
            ):
                raise ValueError(
                    "72h read-only adapter outputs must remain outside retained evidence"
                )

    def _load_state(self) -> dict[str, Any]:
        if not self.state_path.exists():
            unsigned: dict[str, Any] = {
                "schema_version": 1,
                "state_type": LIVE_ADAPTER_STATE_TYPE,
                "bundle_sha256": self.bundle["bundle_sha256"],
                "activation_sha256": self.activation["activation_sha256"],
                "run_identity": self.activation["run_identity"],
                "run_directory": str(self.run_directory),
                "poll_count": 0,
                "sources": {},
                "canonical_record_count": 0,
            }
            return {**unsigned, "state_sha256": canonical_sha256(unsigned)}
        state = _read_json(self.state_path)
        unsigned = {
            key: item for key, item in state.items() if key != "state_sha256"
        }
        if state.get("state_sha256") != canonical_sha256(unsigned):
            raise ValueError("72h live adapter state identity differs")
        expected = {
            "state_type": LIVE_ADAPTER_STATE_TYPE,
            "bundle_sha256": self.bundle["bundle_sha256"],
            "activation_sha256": self.activation["activation_sha256"],
            "run_identity": self.activation["run_identity"],
            "run_directory": str(self.run_directory),
        }
        if any(state.get(key) != value for key, value in expected.items()):
            raise ValueError("72h live adapter restart binding differs")
        if int(state.get("canonical_record_count", -1)) != 0:
            raise ValueError("blocked inspection state claims canonical records")
        return state

    def poll(self) -> dict[str, object]:
        manifest_paths = _manifest_paths(self.run_directory)
        state = self._load_state()
        source_state = state.get("sources")
        if not isinstance(source_state, dict):
            raise ValueError("72h live adapter source state differs")
        rows: dict[str, list[dict[str, str]]] = {}
        new_rows: dict[str, int] = {}
        next_sources: dict[str, dict[str, object]] = {}
        source_blockers: list[str] = []
        for contract_id, relative_path in _INSPECTION_SOURCES.items():
            if manifest_paths.get(contract_id) != relative_path:
                source_blockers.append(f"{contract_id}_exact_manifest_path_absent")
                rows[contract_id] = []
                continue
            path = self.run_directory / relative_path
            if not path.is_file():
                source_blockers.append(f"{contract_id}_retained_file_absent")
                rows[contract_id] = []
                continue
            previous = source_state.get(contract_id)
            parsed, cursor = _read_exact_retained_csv(
                path=path,
                contract_id=contract_id,
                previous=previous if isinstance(previous, Mapping) else None,
            )
            previous_count = (
                int(previous["row_count"])
                if isinstance(previous, Mapping)
                else 0
            )
            if len(parsed) < previous_count:
                raise ValueError(f"retained source row count moved backward: {path}")
            rows[contract_id] = parsed
            new_rows[contract_id] = len(parsed) - previous_count
            next_sources[contract_id] = cursor

        exact_sidecars: dict[str, list[dict[str, str]]] = {}
        for declaration in _LIVE_SOURCE_DECLARATIONS:
            contract_id = str(declaration["contract"])
            relative_path = str(declaration["path"])
            if manifest_paths.get(contract_id) != relative_path:
                source_blockers.append(f"{contract_id}_exact_manifest_path_absent")
                exact_sidecars[contract_id] = []
                continue
            path = self.run_directory / relative_path
            if not path.is_file():
                source_blockers.append(f"{contract_id}_retained_file_absent")
                exact_sidecars[contract_id] = []
                continue
            previous = source_state.get(contract_id)
            parsed, cursor = _read_exact_sidecar_csv(
                path=path,
                fields=list(declaration["fields"]),
                record_type=str(declaration["record_type"]),
                sequence_field="timing_record_sequence",
                previous=previous if isinstance(previous, Mapping) else None,
            )
            previous_count = (
                int(previous["row_count"])
                if isinstance(previous, Mapping)
                else 0
            )
            exact_sidecars[contract_id] = parsed
            new_rows[contract_id] = len(parsed) - previous_count
            next_sources[contract_id] = cursor

        lifecycle = _structural_lifecycles(
            rows["active_transactions_v1"],
            rows["active_hybrid_decisions_v1"],
        )
        sidecar_join = _sidecar_join_inspection(
            transactions=rows["active_transactions_v1"],
            decisions=rows["active_hybrid_decisions_v1"],
            transaction_timings=exact_sidecars["active_transactions_v2"],
            decision_timings=exact_sidecars["active_hybrid_decisions_v2"],
        )
        if sidecar_join["mismatches"]:
            source_blockers.append("exact_timing_sidecar_join_incomplete_or_mismatched")
        scientific_metrics = derive_retained_scientific_metrics(
            rows=rows,
            transaction_timings=exact_sidecars["active_transactions_v2"],
            decision_timings=exact_sidecars["active_hybrid_decisions_v2"],
        )
        source_blockers.extend(scientific_metrics["hard_producer_field_blockers"])
        timing = _timing_and_forwarded_inspection(rows)
        if not timing["D14_D8"]["healthy_and_aligned"]:
            source_blockers.append("D14_D8_retained_authority_not_healthy")
        if not timing["D9"]["configuration_and_readback_exact"]:
            source_blockers.append("D9_configuration_or_readback_not_exact")
        gnss = _gnss_hold_inspection(
            rows["health_v1"], rows["reference_observations_v1"]
        )
        if gnss["contradictions"]:
            source_blockers.append("gnss_hold_causal_identity_contradiction")
        endpoint = _retained_campaign18_endpoint(
            run_directory=self.run_directory,
            structural_lifecycles=lifecycle,
            health_rows=rows["health_v1"],
        )
        source_blockers.extend(endpoint["hard_blockers"])
        all_blockers = list(
            dict.fromkeys([*self.validation["hard_blockers"], *source_blockers])
        )
        report: dict[str, object] = {
            "schema_version": 1,
            "report_type": LIVE_ADAPTER_REPORT_TYPE,
            "tool": TOOL_ID,
            "status": (
                "complete_read_only" if not all_blockers else "blocked_inspection_only"
            ),
            "bundle_sha256": self.bundle["bundle_sha256"],
            "activation_sha256": self.activation["activation_sha256"],
            "run_identity": self.activation["run_identity"],
            "poll_number": int(state["poll_count"]) + 1,
            "hard_blockers": all_blockers,
            "source_row_counts": {
                contract_id: len(value) for contract_id, value in sorted(rows.items())
            },
            "new_rows": dict(sorted(new_rows.items())),
            "structural_lifecycles": lifecycle,
            "exact_timing_sidecar_join": sidecar_join,
            "scientific_metrics": scientific_metrics,
            "timing_and_forwarded_evidence": timing,
            "gnss_metadata": gnss,
            "qualified_endpoint": endpoint,
            "canonical_record_count": 0,
            "canonical_records_appended": 0,
            "coarse_seconds_projected_to_ticks": False,
            "adapter_authority": self.validation["adapter_authority"],
            "admission_reserve_s": self.bundle["controller_envelope"][
                "close_new_application_admission_before_endpoint_s"
            ],
            "promotion_permitted": False,
        }
        report["report_sha256"] = canonical_sha256(report)
        next_unsigned = {
            key: item
            for key, item in state.items()
            if key != "state_sha256"
        }
        next_unsigned.update(
            {
                "poll_count": int(state["poll_count"]) + 1,
                "sources": next_sources,
                "canonical_record_count": 0,
                "last_report_sha256": report["report_sha256"],
            }
        )
        next_state = {
            **next_unsigned,
            "state_sha256": canonical_sha256(next_unsigned),
        }
        _atomic_write_json(self.state_path, next_state)
        _atomic_write_json(self.report_path, report)
        return report


@dataclass(frozen=True)
class Engineering72hProgrammeAdapter:
    """Host-facing programme descriptor without 24h challenge semantics."""

    programme_id: str
    profile_id: str
    qualified_duration_s: int
    absolute_wall_limit_s: int
    milestone_interval_s: int
    maximum_applications: int
    maximum_physical_writes: int
    maximum_cumulative_movement_codes: int
    maximum_step_codes: int
    minimum_applied_cadence_s: int
    response_reserve_s: int
    minimum_code: int
    maximum_code: int
    maximum_outstanding_transactions: int
    generic_sustained_regulation_mode: bool = False
    sustained_authority_programme: bool = True
    deliberate_reversal_challenge: bool = False

    def as_dict(self) -> dict[str, object]:
        return {
            name: getattr(self, name)
            for name in self.__dataclass_fields__
        }


def programme_adapter(
    contract: Mapping[str, Any] | None = None,
) -> Engineering72hProgrammeAdapter:
    value = load_contract() if contract is None else contract
    envelope = value["controller_envelope"]
    firmware = value.get("firmware")
    profile_id = (
        firmware["profile_id"]
        if isinstance(firmware, Mapping)
        else value["profile_id"]
    )
    return Engineering72hProgrammeAdapter(
        programme_id=str(
            value["contract_id"]
            if "contract_id" in value
            else value["programme_id"]
        ),
        profile_id=str(profile_id),
        qualified_duration_s=int(value["time"]["qualified_duration_s"]),
        absolute_wall_limit_s=int(value["time"]["absolute_wall_limit_s"]),
        milestone_interval_s=int(value["time"]["milestone_interval_qualified_s"]),
        maximum_applications=int(envelope["automatic_application_limit"]),
        maximum_physical_writes=int(
            envelope["total_dac_write_limit_including_setup"]
        ),
        maximum_cumulative_movement_codes=int(
            envelope["automatic_cumulative_movement_limit_codes"]
        ),
        maximum_step_codes=int(envelope["automatic_step_limit_codes"]),
        minimum_applied_cadence_s=int(
            envelope["minimum_application_cadence_s"]
        ),
        response_reserve_s=int(
            envelope["close_new_application_admission_before_endpoint_s"]
        ),
        minimum_code=int(envelope["dac_min_code"]),
        maximum_code=int(envelope["dac_max_code"]),
        maximum_outstanding_transactions=int(
            envelope["maximum_outstanding_transactions"]
        ),
    )


def _record_sha256(record: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {key: value for key, value in record.items() if key != "record_sha256"}
    )


def _metric_summary(values: list[int]) -> dict[str, object]:
    if not values:
        return {"sample_count": 0}
    total = sum(values)
    return {
        "sample_count": len(values),
        "minimum": min(values),
        "maximum": max(values),
        "maximum_absolute": max(abs(value) for value in values),
        "sum": total,
        "mean_exact": {"numerator": total, "denominator": len(values)},
    }


_PERFORMANCE_FIELDS = frozenset(
    {
        "frequency_error_nanohz",
        "phase_error_ns",
        "drift_nanohz_per_hour",
        "window_support_ticks",
    }
)
_RESPONSE_FIELDS = frozenset(
    {
        "response_latency_ticks",
        "settling_exclusion_ticks",
        "fresh_support_ticks",
        "pre_frequency_error_nanohz",
        "post_frequency_error_nanohz",
        "response_counts",
    }
)


@dataclass
class Engineering72hSupervisor:
    """Canonical exact-counter reducer used by all 72h host consumers."""

    contract: Mapping[str, Any]
    run_start_ticks: int
    _seed_run_record: bool = field(default=True, repr=False)
    setup_establishments: int = 0
    setup_application_ticks: int | None = None
    setup_code: int | None = None
    current_code: int | None = None
    current_epoch: int = 0
    armed_ticks: int | None = None
    last_observation_ticks: int | None = None
    qualified_ticks: int = 0
    unqualified_ticks: int = 0
    automatic_applications: int = 0
    automatic_requests: int = 0
    requested_movement_codes: int = 0
    cumulative_movement_codes: int = 0
    last_application_ticks: int | None = None
    milestones: list[int] = field(default_factory=list)
    d6_local_degraded_intervals: int = 0
    d6_local_degraded_ticks: int = 0
    gnss_metadata_hold_intervals: int = 0
    gnss_metadata_hold_ticks: int = 0
    terminal: str | None = None
    pending_opportunity: dict[str, Any] | None = None
    pending_transaction: dict[str, Any] | None = None
    opportunity_dispositions: Counter[str] = field(default_factory=Counter)
    performance_metrics: dict[str, list[int]] = field(default_factory=dict)
    response_metrics: dict[str, list[int]] = field(default_factory=dict)
    response_classifications: Counter[str] = field(default_factory=Counter)
    application_deltas: list[int] = field(default_factory=list)
    code_transitions: list[tuple[int, int]] = field(default_factory=list)
    confirmed_codes: set[int] = field(default_factory=set)
    qualified_code_residence_ticks: Counter[int] = field(default_factory=Counter)
    records: list[dict[str, Any]] = field(default_factory=list)
    last_opportunity_ticks: int | None = None

    def __post_init__(self) -> None:
        if self.run_start_ticks < 0:
            raise ValueError("run start ticks must be nonnegative")
        if self._seed_run_record:
            self._append_event("run_started", run_start_ticks=self.run_start_ticks)

    @property
    def timer_hz(self) -> int:
        return int(self.contract["time"]["nominal_counter_hz"])

    @property
    def target_ticks(self) -> int:
        return int(self.contract["time"]["qualified_duration_s"]) * self.timer_hz

    @property
    def outstanding_transactions(self) -> int:
        return int(self.pending_transaction is not None)

    def _stop(self, terminal_key: str) -> None:
        if self.terminal is None:
            self.terminal = str(self.contract["terminals"][terminal_key])

    def _append_event(self, event: str, **fields: Any) -> dict[str, Any]:
        record: dict[str, Any] = {
            "schema_version": 1,
            "record_contract": RECORD_CONTRACT,
            "record_sequence": len(self.records) + 1,
            "previous_record_sha256": (
                None if not self.records else self.records[-1]["record_sha256"]
            ),
            "counter_domain": self.contract["time"]["counter_domain"],
            "event": event,
            **fields,
        }
        record["record_sha256"] = _record_sha256(record)
        self.apply_canonical_record(record)
        return record

    def apply_canonical_record(self, record: Mapping[str, Any]) -> None:
        value = dict(record)
        expected_sequence = len(self.records) + 1
        expected_previous = (
            None if not self.records else self.records[-1]["record_sha256"]
        )
        if (
            value.get("schema_version") != 1
            or value.get("record_contract") != RECORD_CONTRACT
            or value.get("record_sequence") != expected_sequence
            or value.get("previous_record_sha256") != expected_previous
            or value.get("counter_domain") != self.contract["time"]["counter_domain"]
            or value.get("record_sha256") != _record_sha256(value)
        ):
            raise ValueError("72h canonical record identity or ordering differs")
        if expected_sequence == 1:
            if (
                value.get("event") != "run_started"
                or value.get("run_start_ticks") != self.run_start_ticks
            ):
                raise ValueError("72h record stream lacks exact run origin")
        self.records.append(value)
        if expected_sequence > 1:
            self._reduce(value)

    @classmethod
    def replay(
        cls, contract: Mapping[str, Any], records: list[Mapping[str, Any]]
    ) -> "Engineering72hSupervisor":
        if not records or records[0].get("event") != "run_started":
            raise ValueError("72h canonical record stream is empty or unanchored")
        supervisor = cls(
            contract,
            int(records[0]["run_start_ticks"]),
            _seed_run_record=False,
        )
        for record in records:
            supervisor.apply_canonical_record(record)
        return supervisor

    def _reduce(self, record: Mapping[str, Any]) -> None:
        event = str(record.get("event"))
        handlers = {
            "setup_established": self._reduce_setup,
            "qualification_armed": self._reduce_arm,
            "control_opportunity": self._reduce_opportunity,
            "automatic_request": self._reduce_request,
            "automatic_acceptance": self._reduce_acceptance,
            "automatic_application": self._reduce_application,
            "first_dependent_consumer": self._reduce_consumer,
            "automatic_response": self._reduce_response,
            "observation_interval": self._reduce_observation,
            "operator_abort": self._reduce_abort,
        }
        handler = handlers.get(event)
        if handler is None:
            raise ValueError(f"unknown 72h canonical event: {event}")
        handler(record)

    def _reduce_setup(self, record: Mapping[str, Any]) -> None:
        start = self.contract["starting_dac"]
        invalid = (
            self.terminal is not None
            or self.armed_ticks is not None
            or self.setup_establishments != 0
            or int(record["application_ticks"]) < self.run_start_ticks
            or bool(record["pre_setup_physical_code_readable"])
            or bool(record["dac_query_claimed_physical_readback"])
            or int(record["applied_code"]) != int(start["setup_code"])
            or int(record["applied_epoch"])
            != int(start["required_established_epoch"])
            or not bool(record["acknowledgement_exact"])
            or not bool(record["first_dependent_consumer_exact"])
        )
        if invalid:
            self._stop("controller_or_transaction_fault")
            return
        self.setup_establishments = 1
        self.setup_application_ticks = int(record["application_ticks"])
        self.setup_code = int(record["applied_code"])
        self.current_code = self.setup_code
        self.confirmed_codes.add(self.setup_code)
        self.current_epoch = int(record["applied_epoch"])
        self.code_transitions.append(
            (int(record["application_ticks"]), self.setup_code)
        )

    def _reduce_arm(self, record: Mapping[str, Any]) -> None:
        frontier_ticks = int(record["frontier_ticks"])
        deadline = int(self.contract["time"]["qualification_deadline_s"])
        if frontier_ticks - self.run_start_ticks > deadline * self.timer_hz:
            self._stop("right_censored_incomplete")
            return
        serial = self.contract["serial"]
        d9 = self.contract["d9"]
        if (
            self.terminal is not None
            or self.armed_ticks is not None
            or not bool(record["fresh_auto_detect"])
            or int(record["candidate_count"]) != int(serial["required_candidate_count"])
            or int(record["baud"]) != int(serial["baud"])
            or not bool(record["sole_serial_owner"])
            or not bool(record["independent_abort_ready"])
            or self.setup_establishments != 1
            or self.current_code != int(self.contract["starting_dac"]["setup_code"])
            or self.current_epoch
            != int(self.contract["starting_dac"]["required_established_epoch"])
            or not bool(record["gnss_metadata_fresh_same_receiver"])
            or record["d6_status"] not in self.contract["d6"]["allowed_statuses"]
            or not bool(record["no_outstanding_transaction"])
        ):
            self._stop("identity_or_evidence_fault")
            return
        if not bool(record["d14_d8_healthy"]):
            self._stop("authoritative_capture_fault")
            return
        if (
            record["d9_state"] != d9["required_state"]
            or not bool(record["d9_identity_exact"])
            or not bool(record["d9_readback_exact"])
        ):
            self._stop("d9_digital_fault")
            return
        self.armed_ticks = frontier_ticks
        self.last_observation_ticks = frontier_ticks

    def _remaining_qualified_ticks(self) -> int:
        return self.target_ticks - self.qualified_ticks

    def _reduce_opportunity(self, record: Mapping[str, Any]) -> None:
        envelope = self.contract["controller_envelope"]
        disposition = str(record["disposition"])
        allowed_lost = set(self.contract["record_replay"]["lost_opportunity_dispositions"])
        allowed = allowed_lost | {"APPLICATION_REQUESTED"}
        ticks = int(record["frontier_ticks"])
        if (
            self.terminal is not None
            or self.armed_ticks is None
            or ticks < self.armed_ticks
            or (self.last_opportunity_ticks is not None and ticks <= self.last_opportunity_ticks)
            or disposition not in allowed
            or self.pending_opportunity is not None
        ):
            self._stop("controller_or_transaction_fault")
            return
        remaining = self._remaining_qualified_ticks()
        reserve = int(envelope["close_new_application_admission_before_endpoint_s"]) * self.timer_hz
        if disposition == "APPLICATION_REQUESTED":
            invalid_request = (
                self.pending_transaction is not None
                or remaining <= reserve
                or self.automatic_applications
                >= int(envelope["automatic_application_limit"])
                or self.cumulative_movement_codes
                >= int(envelope["automatic_cumulative_movement_limit_codes"])
            )
            if invalid_request:
                self._stop("controller_or_transaction_fault")
                return
            self.pending_opportunity = {
                "opportunity_id": str(record["opportunity_id"]),
                "frontier_ticks": ticks,
            }
        elif disposition == "ENDPOINT_ADMISSION_CLOSED" and remaining > reserve:
            self._stop("controller_or_transaction_fault")
            return
        self.last_opportunity_ticks = ticks
        self.opportunity_dispositions[disposition] += 1

    def _reduce_request(self, record: Mapping[str, Any]) -> None:
        opportunity = self.pending_opportunity
        request_ticks = int(record["request_ticks"])
        if (
            self.terminal is not None
            or opportunity is None
            or self.pending_transaction is not None
            or str(record["opportunity_id"]) != opportunity["opportunity_id"]
            or request_ticks < int(opportunity["frontier_ticks"])
            or int(record["outstanding_transactions_before_request"]) != 0
            or int(record["requested_from_code"]) != self.current_code
            or int(record["requested_code"]) == self.current_code
        ):
            self._stop("controller_or_transaction_fault")
            return
        self.pending_opportunity = None
        self.automatic_requests += 1
        self.requested_movement_codes += abs(
            int(record["requested_code"]) - int(record["requested_from_code"])
        )
        self.pending_transaction = {
            "transaction_id": str(record["transaction_id"]),
            "opportunity_id": str(record["opportunity_id"]),
            "session_id": str(record["session_id"]),
            "request_sequence": int(record["request_sequence"]),
            "evidence_sequence": int(record["evidence_sequence"]),
            "requested_from_code": int(record["requested_from_code"]),
            "requested_code": int(record["requested_code"]),
            "request_ticks": request_ticks,
            "phase": "requested",
        }

    def _transaction_matches(self, record: Mapping[str, Any], phase: str) -> bool:
        transaction = self.pending_transaction
        return bool(
            transaction is not None
            and transaction["phase"] == phase
            and str(record["transaction_id"]) == transaction["transaction_id"]
            and str(record["session_id"]) == transaction["session_id"]
            and int(record["request_sequence"]) == transaction["request_sequence"]
            and int(record["evidence_sequence"]) == transaction["evidence_sequence"]
        )

    def _reduce_acceptance(self, record: Mapping[str, Any]) -> None:
        if (
            self.terminal is not None
            or not self._transaction_matches(record, "requested")
            or int(record["acceptance_ticks"])
            < int(self.pending_transaction["request_ticks"])
            or not bool(record["acknowledgement_exact"])
        ):
            self._stop("controller_or_transaction_fault")
            return
        self.pending_transaction["acceptance_ticks"] = int(record["acceptance_ticks"])
        self.pending_transaction["phase"] = "accepted"

    def _reduce_application(self, record: Mapping[str, Any]) -> None:
        envelope = self.contract["controller_envelope"]
        transaction = self.pending_transaction
        if transaction is None:
            self._stop("controller_or_transaction_fault")
            return
        application_ticks = int(record["application_ticks"])
        applied_code = int(record["applied_code"])
        delta = applied_code - int(transaction["requested_from_code"])
        preceding_ticks = (
            self.last_application_ticks
            if self.last_application_ticks is not None
            else self.setup_application_ticks
        )
        invalid = (
            self.terminal is not None
            or not self._transaction_matches(record, "accepted")
            or int(record["requested_code"]) != transaction["requested_code"]
            or applied_code != transaction["requested_code"]
            or preceding_ticks is None
            or application_ticks < int(transaction["acceptance_ticks"])
            or application_ticks - preceding_ticks
            < int(envelope["minimum_application_cadence_s"]) * self.timer_hz
            or not 1 <= abs(delta) <= int(envelope["automatic_step_limit_codes"])
            or not int(envelope["dac_min_code"])
            <= applied_code
            <= int(envelope["dac_max_code"])
            or int(record["applied_epoch"]) != self.current_epoch + 1
        )
        next_applications = self.automatic_applications + 1
        next_movement = self.cumulative_movement_codes + abs(delta)
        if invalid or (
            next_applications > int(envelope["automatic_application_limit"])
            or next_movement
            > int(envelope["automatic_cumulative_movement_limit_codes"])
            or self.setup_establishments + next_applications
            > int(envelope["total_dac_write_limit_including_setup"])
        ):
            self._stop("controller_or_transaction_fault")
            return
        self.automatic_applications = next_applications
        self.cumulative_movement_codes = next_movement
        self.last_application_ticks = application_ticks
        self.current_code = applied_code
        self.confirmed_codes.add(applied_code)
        self.current_epoch = int(record["applied_epoch"])
        self.application_deltas.append(delta)
        self.code_transitions.append((application_ticks, applied_code))
        transaction["application_ticks"] = application_ticks
        transaction["applied_code"] = applied_code
        transaction["applied_epoch"] = self.current_epoch
        transaction["phase"] = "applied"

    def _reduce_consumer(self, record: Mapping[str, Any]) -> None:
        transaction = self.pending_transaction
        if (
            self.terminal is not None
            or transaction is None
            or not self._transaction_matches(record, "applied")
            or int(record["consumer_ticks"]) < int(transaction["application_ticks"])
            or int(record["applied_code"]) != transaction["applied_code"]
            or int(record["applied_epoch"]) != transaction["applied_epoch"]
            or not bool(record["first_dependent_consumer_exact"])
        ):
            self._stop("controller_or_transaction_fault")
            return
        transaction["consumer_ticks"] = int(record["consumer_ticks"])
        transaction["phase"] = "consumed"

    def _record_metrics(
        self,
        destination: dict[str, list[int]],
        metrics: Mapping[str, Any],
        allowed: frozenset[str],
    ) -> bool:
        if set(metrics) - allowed:
            return False
        for name, value in metrics.items():
            if isinstance(value, bool) or not isinstance(value, int):
                return False
            if name.endswith("ticks") and value < 0:
                return False
        for name, value in metrics.items():
            destination.setdefault(name, []).append(value)
        return True

    def _reduce_response(self, record: Mapping[str, Any]) -> None:
        transaction = self.pending_transaction
        metrics = record.get("metrics", {})
        if not isinstance(metrics, Mapping):
            metrics = {"invalid": 0}
        response_ticks = int(record["response_ticks"])
        latency = metrics.get("response_latency_ticks")
        latency_exact = bool(
            transaction is not None
            and "application_ticks" in transaction
            and (
                latency is None
                or latency
                == response_ticks - int(transaction["application_ticks"])
            )
        )
        if (
            self.terminal is not None
            or transaction is None
            or not self._transaction_matches(record, "consumed")
            or response_ticks < int(transaction["consumer_ticks"])
            or not bool(record["response_complete"])
            or not str(record["classification"])
            or not latency_exact
            or not self._record_metrics(self.response_metrics, metrics, _RESPONSE_FIELDS)
        ):
            self._stop("controller_or_transaction_fault")
            return
        self.response_classifications[str(record["classification"])] += 1
        self.pending_transaction = None

    def _reduce_observation(self, record: Mapping[str, Any]) -> None:
        if self.terminal is not None:
            return
        opening_ticks = int(record["opening_ticks"])
        closing_ticks = int(record["closing_ticks"])
        d6_status = str(record["d6_status"])
        gnss_state = str(record["gnss_metadata_state"])
        metrics = record.get("performance", {})
        if not isinstance(metrics, Mapping):
            metrics = {"invalid": 0}
        window_support = metrics.get("window_support_ticks")
        if (
            self.armed_ticks is None
            or self.last_observation_ticks is None
            or opening_ticks != self.last_observation_ticks
            or closing_ticks <= opening_ticks
            or d6_status not in self.contract["d6"]["allowed_statuses"]
            or gnss_state not in {"fresh_same_receiver", "GNSS_METADATA_HOLD"}
            or (
                window_support is not None
                and window_support != closing_ticks - opening_ticks
            )
            or not self._record_metrics(
                self.performance_metrics, metrics, _PERFORMANCE_FIELDS
            )
        ):
            self._stop("identity_or_evidence_fault")
            return
        if closing_ticks - self.run_start_ticks > (
            int(self.contract["time"]["absolute_wall_limit_s"]) * self.timer_hz
        ):
            self._stop("right_censored_incomplete")
            return
        if not bool(record["d14_d8_healthy"]):
            self._stop("authoritative_capture_fault")
            return
        if not bool(record["d9_configuration_and_readback_exact"]):
            self._stop("d9_digital_fault")
            return
        interval_ticks = closing_ticks - opening_ticks
        self.last_observation_ticks = closing_ticks
        if d6_status == "local_degraded":
            self.d6_local_degraded_intervals += 1
            self.d6_local_degraded_ticks += interval_ticks
        if gnss_state == "GNSS_METADATA_HOLD":
            self.gnss_metadata_hold_intervals += 1
            self.gnss_metadata_hold_ticks += interval_ticks
        if not bool(record["measurement_qualified"]):
            self.unqualified_ticks += interval_ticks
            return
        credited_ticks = min(interval_ticks, self._remaining_qualified_ticks())
        self.qualified_ticks += credited_ticks
        if self.current_code is None:
            self._stop("identity_or_evidence_fault")
            return
        qualified_close = opening_ticks + credited_ticks
        transitions = [
            (ticks, code)
            for ticks, code in self.code_transitions
            if opening_ticks < ticks < qualified_close
        ]
        opening_codes = [
            (ticks, code)
            for ticks, code in self.code_transitions
            if ticks <= opening_ticks
        ]
        if not opening_codes:
            self._stop("identity_or_evidence_fault")
            return
        residence_code = opening_codes[-1][1]
        residence_open = opening_ticks
        for transition_ticks, transition_code in transitions:
            self.qualified_code_residence_ticks[residence_code] += (
                transition_ticks - residence_open
            )
            residence_open = transition_ticks
            residence_code = transition_code
        self.qualified_code_residence_ticks[residence_code] += (
            qualified_close - residence_open
        )
        for milestone in self.contract["time"]["milestones_qualified_s"]:
            if (
                self.qualified_ticks >= int(milestone) * self.timer_hz
                and int(milestone) not in self.milestones
            ):
                self.milestones.append(int(milestone))
        if self.qualified_ticks == self.target_ticks:
            if (
                self.pending_opportunity is not None
                or self.pending_transaction is not None
                or not self.opportunity_dispositions
            ):
                self._stop("controller_or_transaction_fault")
            else:
                self._stop("qualified_complete")

    def _reduce_abort(self, record: Mapping[str, Any]) -> None:
        key = (
            "pre_setup_no_write_abort"
            if self.setup_establishments == 0 and self.automatic_applications == 0
            else "operator_abort"
        )
        self._stop(key)

    def record_setup_establishment(self, **fields: Any) -> None:
        self._append_event("setup_established", **fields)

    def arm(self, **fields: Any) -> None:
        if self.terminal is not None or self.armed_ticks is not None:
            raise ValueError("72h programme cannot be armed in the current state")
        self._append_event("qualification_armed", **fields)
        if self.armed_ticks is None:
            if self.terminal == self.contract["terminals"]["right_censored_incomplete"]:
                raise ValueError("72h qualification deadline expired before arming")
            raise ValueError("72h entry identity or authority gate differs")

    def record_control_opportunity(
        self, *, opportunity_id: str, frontier_ticks: int, disposition: str
    ) -> None:
        self._append_event(
            "control_opportunity",
            opportunity_id=opportunity_id,
            frontier_ticks=frontier_ticks,
            disposition=disposition,
        )

    def record_automatic_request(self, **fields: Any) -> None:
        self._append_event("automatic_request", **fields)

    def record_automatic_acceptance(self, **fields: Any) -> None:
        self._append_event("automatic_acceptance", **fields)

    def record_application_applied(self, **fields: Any) -> None:
        self._append_event("automatic_application", **fields)

    def record_first_dependent_consumer(self, **fields: Any) -> None:
        self._append_event("first_dependent_consumer", **fields)

    def record_automatic_response(self, **fields: Any) -> None:
        self._append_event("automatic_response", **fields)

    def record_automatic_application(
        self,
        *,
        requested_from_code: int,
        applied_code: int,
        applied_epoch: int,
        application_ticks: int,
        outstanding_transactions_before_request: int,
        acknowledgement_exact: bool,
        first_dependent_consumer_exact: bool,
        response_complete: bool,
    ) -> None:
        """Compatibility helper that still emits the complete lifecycle."""

        ordinal = self.automatic_applications + 1
        opportunity_id = f"compat-opportunity-{ordinal}"
        transaction_id = f"compat-transaction-{ordinal}"
        session_id = "compat-session"
        request_sequence = ordinal
        evidence_sequence = len(self.records) + 1
        self.record_control_opportunity(
            opportunity_id=opportunity_id,
            frontier_ticks=application_ticks,
            disposition="APPLICATION_REQUESTED",
        )
        if self.terminal is not None:
            return
        self.record_automatic_request(
            transaction_id=transaction_id,
            opportunity_id=opportunity_id,
            session_id=session_id,
            request_sequence=request_sequence,
            evidence_sequence=evidence_sequence,
            request_ticks=application_ticks,
            requested_from_code=requested_from_code,
            requested_code=applied_code,
            outstanding_transactions_before_request=(
                outstanding_transactions_before_request
            ),
        )
        if self.terminal is not None:
            return
        self.record_automatic_acceptance(
            transaction_id=transaction_id,
            session_id=session_id,
            request_sequence=request_sequence,
            evidence_sequence=evidence_sequence,
            acceptance_ticks=application_ticks,
            acknowledgement_exact=acknowledgement_exact,
        )
        if self.terminal is not None:
            return
        self.record_application_applied(
            transaction_id=transaction_id,
            session_id=session_id,
            request_sequence=request_sequence,
            evidence_sequence=evidence_sequence,
            application_ticks=application_ticks,
            requested_code=applied_code,
            applied_code=applied_code,
            applied_epoch=applied_epoch,
        )
        if self.terminal is not None:
            return
        self.record_first_dependent_consumer(
            transaction_id=transaction_id,
            session_id=session_id,
            request_sequence=request_sequence,
            evidence_sequence=evidence_sequence,
            consumer_ticks=application_ticks,
            applied_code=applied_code,
            applied_epoch=applied_epoch,
            first_dependent_consumer_exact=first_dependent_consumer_exact,
        )
        if self.terminal is not None:
            return
        self.record_automatic_response(
            transaction_id=transaction_id,
            session_id=session_id,
            request_sequence=request_sequence,
            evidence_sequence=evidence_sequence,
            response_ticks=application_ticks,
            response_complete=response_complete,
            classification="compatibility_complete",
            metrics={"response_latency_ticks": 0},
        )

    def observe_interval(
        self,
        *,
        opening_ticks: int,
        closing_ticks: int,
        measurement_qualified: bool,
        d14_d8_healthy: bool,
        d9_configuration_and_readback_exact: bool,
        d6_status: str,
        gnss_metadata_state: str = "fresh_same_receiver",
        performance: Mapping[str, int] | None = None,
    ) -> None:
        self._append_event(
            "observation_interval",
            opening_ticks=opening_ticks,
            closing_ticks=closing_ticks,
            measurement_qualified=measurement_qualified,
            d14_d8_healthy=d14_d8_healthy,
            d9_configuration_and_readback_exact=(
                d9_configuration_and_readback_exact
            ),
            d6_status=d6_status,
            gnss_metadata_state=gnss_metadata_state,
            performance=dict(performance or {}),
        )

    def operator_abort(self) -> None:
        self._append_event("operator_abort")

    def persist_record_log(self, path: Path) -> dict[str, object]:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as handle:
            for record in self.records:
                handle.write(json.dumps(record, sort_keys=True, allow_nan=False))
                handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        return {
            "path": str(path.resolve()),
            "record_count": len(self.records),
            "last_record_sha256": self.records[-1]["record_sha256"],
            "file_sha256": sha256(path.read_bytes()).hexdigest(),
        }

    def summary(self) -> dict[str, object]:
        reversal_count = sum(
            1
            for preceding, following in zip(
                self.application_deltas, self.application_deltas[1:]
            )
            if (preceding > 0) != (following > 0)
        )
        envelope = self.contract["controller_envelope"]
        lower_code = int(envelope["dac_min_code"])
        upper_code = int(envelope["dac_max_code"])
        lower_residence = self.qualified_code_residence_ticks[lower_code]
        upper_residence = self.qualified_code_residence_ticks[upper_code]
        return {
            "terminal": self.terminal,
            "programme": programme_adapter(self.contract).as_dict(),
            "setup_establishments": self.setup_establishments,
            "automatic_applications": self.automatic_applications,
            "automatic_requests": self.automatic_requests,
            "total_dac_writes": self.setup_establishments
            + self.automatic_applications,
            "cumulative_automatic_movement_codes": self.cumulative_movement_codes,
            "requested_automatic_movement_codes": self.requested_movement_codes,
            "net_automatic_movement_codes": (
                None
                if self.current_code is None or self.setup_code is None
                else self.current_code - self.setup_code
            ),
            "automatic_reversal_count": reversal_count,
            "qualified_range_residence": {
                "minimum_code_ticks": lower_residence,
                "maximum_code_ticks": upper_residence,
                "interior_code_ticks": (
                    self.qualified_ticks - lower_residence - upper_residence
                ),
                "by_code_ticks": {
                    f"0x{code:04X}": ticks
                    for code, ticks in sorted(
                        self.qualified_code_residence_ticks.items()
                    )
                },
                "confirmed_codes_visited": [
                    f"0x{code:04X}" for code in sorted(self.confirmed_codes)
                ],
            },
            "authority_ceiling_reached": (
                self.automatic_applications
                == int(envelope["automatic_application_limit"])
                or self.cumulative_movement_codes
                == int(envelope["automatic_cumulative_movement_limit_codes"])
            ),
            "authority_ceiling_is_not_success_or_activity_target": True,
            "qualified_ticks": self.qualified_ticks,
            "qualified_seconds": self.qualified_ticks // self.timer_hz,
            "unqualified_ticks": self.unqualified_ticks,
            "milestones_qualified_s": list(self.milestones),
            "endpoint_quiescent": (
                self.pending_opportunity is None
                and self.pending_transaction is None
            ),
            "outstanding_transactions": self.outstanding_transactions,
            "opportunity_count": sum(self.opportunity_dispositions.values()),
            "opportunity_dispositions": dict(
                sorted(self.opportunity_dispositions.items())
            ),
            "lost_opportunity_count": sum(
                count
                for disposition, count in self.opportunity_dispositions.items()
                if disposition != "APPLICATION_REQUESTED"
            ),
            "gnss_metadata_hold": {
                "interval_count": self.gnss_metadata_hold_intervals,
                "ticks": self.gnss_metadata_hold_ticks,
                "seconds": self.gnss_metadata_hold_ticks // self.timer_hz,
                "semantics": self.contract["record_replay"][
                    "gnss_metadata_hold_semantics"
                ],
                "run_or_measurement_failure": False,
                "new_control_authority": False,
            },
            "d6_local_degradation": {
                "interval_count": self.d6_local_degraded_intervals,
                "ticks": self.d6_local_degraded_ticks,
                "seconds": self.d6_local_degraded_ticks // self.timer_hz,
                "affected_D14_D8_or_control": False,
            },
            "performance_metrics": {
                name: _metric_summary(values)
                for name, values in sorted(self.performance_metrics.items())
            },
            "response_metrics": {
                "classifications": dict(sorted(self.response_classifications.items())),
                "values": {
                    name: _metric_summary(values)
                    for name, values in sorted(self.response_metrics.items())
                },
            },
            "last_confirmed_code": self.current_code,
            "last_confirmed_epoch": self.current_epoch,
            "record_count": len(self.records),
            "last_record_sha256": self.records[-1]["record_sha256"],
        }


def load_record_log(path: Path) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            if not line.strip():
                raise ValueError(f"blank canonical record at line {line_number}")
            value = json.loads(line)
            if not isinstance(value, dict):
                raise ValueError(f"non-object canonical record at line {line_number}")
            records.append(value)
    return records


def replay_record_log(
    *, contract: Mapping[str, Any], record_log_path: Path
) -> Engineering72hSupervisor:
    return Engineering72hSupervisor.replay(contract, load_record_log(record_log_path))


def monitor_record_log(
    *, contract: Mapping[str, Any], record_log_path: Path
) -> dict[str, object]:
    summary = replay_record_log(
        contract=contract, record_log_path=record_log_path
    ).summary()
    return {
        "consumer": "72h_unattended_transition_monitor",
        "terminal": summary["terminal"],
        "qualified_ticks": summary["qualified_ticks"],
        "milestones_qualified_s": summary["milestones_qualified_s"],
        "outstanding_transactions": summary["outstanding_transactions"],
        "opportunity_dispositions": summary["opportunity_dispositions"],
        "gnss_metadata_hold": summary["gnss_metadata_hold"],
        "d6_local_degradation": summary["d6_local_degradation"],
        "last_record_sha256": summary["last_record_sha256"],
    }


def analyze_record_log(
    *, contract: Mapping[str, Any], record_log_path: Path
) -> dict[str, object]:
    summary = replay_record_log(
        contract=contract, record_log_path=record_log_path
    ).summary()
    return {
        "consumer": "72h_scientific_analyzer",
        "record_contract": RECORD_CONTRACT,
        "summary": summary,
        "claim_boundary": contract["claim_boundary"],
        "waveform_promotion_permitted": False,
    }


def no_io_preflight(bundle: Mapping[str, Any]) -> dict[str, object]:
    checked = validate_bundle(bundle)
    return {
        "tool": TOOL_ID,
        "status": "passed",
        "hardware_operations": False,
        "bundle_sha256": checked["bundle_sha256"],
        "profile_id": checked["profile_id"],
        "firmware_profile_matrix_integrated": checked[
            "firmware_profile_matrix_integrated"
        ],
        "physical_activation_ready": False,
        "programme": programme_adapter(checked).as_dict(),
        "serial_selection": checked["serial"]["selection"],
        "baud": checked["serial"]["baud"],
        "qualified_duration_s": checked["time"]["qualified_duration_s"],
        "milestones_qualified_s": checked["time"]["milestones_qualified_s"],
        "terminals": checked["terminals"],
        "waveform_evidence_status": checked["claim_boundary"][
            "waveform_evidence_status"
        ],
        "promotion_permitted": False,
        "remaining_live_components": checked["remaining_live_components"],
    }


def _write_new_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")


def _wait_for(path: Path, *, timeout_s: float = 10.0) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if path.exists():
            return
        time.sleep(0.025)
    raise TimeoutError(f"timed out waiting for {path}")


def _read_until(master: int, expected: bytes, *, timeout_s: float = 5.0) -> bytes:
    deadline = time.monotonic() + timeout_s
    observed = b""
    while time.monotonic() < deadline:
        readable, _, _ = select.select([master], [], [], 0.05)
        if readable:
            observed += os.read(master, 4096)
            if expected in observed:
                return observed
    raise TimeoutError(f"PTY did not receive {expected!r}; observed={observed!r}")


def _status(sequence: int, component: str, key: str, value: str) -> bytes:
    return (
        f"STS,1,{sequence},{sequence * RP2040_TIMER0_TICKS_PER_SECOND},"
        "rp2040_timer0,"
        f"{component},{key},{value},INFO,0\r\n"
    ).encode("ascii")


def _bounded_pty_capture_process(argv: list[str]) -> int:
    """Run capture with one explicit nonphysical PTY owner-check seam.

    A PTY necessarily remains open in this parent rehearsal process so it can
    act as the deterministic firmware fixture.  That makes lsof correctly see
    two owners.  The child may bypass only that rotation-time lsof assertion,
    and only when a fresh secret capability, exact device, exact run directory,
    non-actuating rehearsal manifest, and character-device boundary all match.
    The production CaptureDeviceRunner implementation remains unchanged.
    """

    from . import capture_device

    expected_device = os.environ.pop(PTY_DEVICE_ENV, "")
    expected_run_dir = os.environ.pop(PTY_RUN_DIR_ENV, "")
    token = os.environ.pop(PTY_TOKEN_ENV, "")
    if (
        not expected_device
        or not expected_run_dir
        or not re.fullmatch(r"[0-9a-f]{64}", token)
    ):
        raise ValueError("bounded PTY capture seam lacks exact process authority")
    expected_capability = f"{CAPABILITY}:{token}"
    expected_run = Path(expected_run_dir).resolve()
    original = capture_device.CaptureDeviceRunner._verify_sole_serial_owner

    def fixture_owner_check(
        runner: capture_device.CaptureDeviceRunner,
    ) -> dict[str, object]:
        device = Path(runner.config.device)
        manifest_path = runner.current_run_dir / "run_manifest.json"
        try:
            manifest = _read_json(manifest_path)
            is_character_device = stat.S_ISCHR(device.stat().st_mode)
        except (OSError, ValueError, json.JSONDecodeError):
            manifest = {}
            is_character_device = False
        exact_fixture = (
            runner.config.device == expected_device
            and runner.current_run_dir == expected_run
            and runner.config.segment_capability == expected_capability
            and is_character_device
            and manifest.get("stage")
            == "CX322_D9_D6_72H_INTEGRATED_ENGINEERING_REHEARSAL"
            and manifest.get("actionable") is False
            and manifest.get("actuation_authorized") is False
        )
        if not exact_fixture:
            return original(runner)
        return {
            "performed": False,
            "reason": "bounded_explicit_nonphysical_PTY_fixture_owner_seam",
            "owner_pids": [os.getpid()],
            "production_lsof_check_unchanged": True,
            "fixture_capability_sha256": sha256(
                expected_capability.encode("utf-8")
            ).hexdigest(),
        }

    capture_device.CaptureDeviceRunner._verify_sole_serial_owner = (
        fixture_owner_check
    )
    original_argv = sys.argv
    sys.argv = ["host.otis_tools.capture_device", *argv]
    try:
        capture_device.main()
        return 0
    finally:
        sys.argv = original_argv
        capture_device.CaptureDeviceRunner._verify_sole_serial_owner = original


def _run_accelerated_counter_rehearsal(
    contract: Mapping[str, Any], *, run_start_ticks: int = 0
) -> Engineering72hSupervisor:
    hz = int(contract["time"]["nominal_counter_hz"])
    supervisor = Engineering72hSupervisor(contract, run_start_ticks)
    setup_ticks = run_start_ticks + 100
    supervisor.record_setup_establishment(
        applied_code=0xA83C,
        applied_epoch=1,
        application_ticks=setup_ticks,
        pre_setup_physical_code_readable=False,
        dac_query_claimed_physical_readback=False,
        acknowledgement_exact=True,
        first_dependent_consumer_exact=True,
    )
    # The first automatic application is eligible at the qualified origin only
    # because the setup application is already one exact cadence old.
    frontier = setup_ticks + 1800 * hz
    supervisor.arm(
        frontier_ticks=frontier,
        fresh_auto_detect=True,
        candidate_count=1,
        baud=115200,
        sole_serial_owner=True,
        independent_abort_ready=True,
        d9_state="configured_10mhz_forwarded_unqualified",
        d9_identity_exact=True,
        d9_readback_exact=True,
        d14_d8_healthy=True,
        gnss_metadata_fresh_same_receiver=True,
        d6_status="present",
        no_outstanding_transaction=True,
    )
    code = 0xA83C
    epoch = 1
    opening = frontier
    for number in range(1, 145):
        delta = 21 if number % 2 else -21
        next_code = code + delta
        application_ticks = frontier + (number - 1) * 1800 * hz + 2
        opportunity_id = f"opportunity-{number}"
        transaction_id = f"transaction-{number}"
        session_id = "accelerated-72h-session"
        supervisor.record_control_opportunity(
            opportunity_id=opportunity_id,
            frontier_ticks=application_ticks - 2,
            disposition="APPLICATION_REQUESTED",
        )
        supervisor.record_automatic_request(
            transaction_id=transaction_id,
            opportunity_id=opportunity_id,
            session_id=session_id,
            request_sequence=number,
            evidence_sequence=number * 10,
            request_ticks=application_ticks - 2,
            requested_from_code=code,
            requested_code=next_code,
            outstanding_transactions_before_request=0,
        )
        supervisor.record_automatic_acceptance(
            transaction_id=transaction_id,
            session_id=session_id,
            request_sequence=number,
            evidence_sequence=number * 10,
            acceptance_ticks=application_ticks - 1,
            acknowledgement_exact=True,
        )
        supervisor.record_application_applied(
            transaction_id=transaction_id,
            session_id=session_id,
            request_sequence=number,
            evidence_sequence=number * 10,
            application_ticks=application_ticks,
            requested_code=next_code,
            applied_code=next_code,
            applied_epoch=epoch + 1,
        )
        supervisor.record_first_dependent_consumer(
            transaction_id=transaction_id,
            session_id=session_id,
            request_sequence=number,
            evidence_sequence=number * 10,
            consumer_ticks=application_ticks + 1,
            applied_code=next_code,
            applied_epoch=epoch + 1,
            first_dependent_consumer_exact=True,
        )
        response_fields = {
            "transaction_id": transaction_id,
            "session_id": session_id,
            "request_sequence": number,
            "evidence_sequence": number * 10,
            "response_ticks": application_ticks + 1500 * hz,
            "response_complete": True,
            "classification": (
                "inside_deadband" if number % 3 else "healthy_indeterminate"
            ),
            "metrics": {
                "response_latency_ticks": 1500 * hz,
                "settling_exclusion_ticks": 900 * hz,
                "fresh_support_ticks": 600 * hz,
                "pre_frequency_error_nanohz": delta * 1_000_000,
                "post_frequency_error_nanohz": delta * 100_000,
                "response_counts": delta,
            },
        }
        if number != 144:
            supervisor.record_automatic_response(**response_fields)
        code = next_code
        epoch += 1

        closing = frontier + number * 1800 * hz
        if number == 144:
            closing = int(response_fields["response_ticks"])
        supervisor.observe_interval(
            opening_ticks=opening,
            closing_ticks=closing,
            measurement_qualified=True,
            d14_d8_healthy=True,
            d9_configuration_and_readback_exact=True,
            d6_status="local_degraded" if number == 60 else "present",
            gnss_metadata_state=(
                "GNSS_METADATA_HOLD" if number == 50 else "fresh_same_receiver"
            ),
            performance={
                "frequency_error_nanohz": delta * 100_000,
                "phase_error_ns": number - 72,
                "drift_nanohz_per_hour": number - 72,
                "window_support_ticks": closing - opening,
            },
        )
        if number == 144:
            supervisor.record_automatic_response(**response_fields)
        if number == 50:
            supervisor.record_control_opportunity(
                opportunity_id="metadata-hold-opportunity",
                frontier_ticks=closing - 1,
                disposition="GNSS_METADATA_HOLD",
            )
        opening = closing

    # At exactly the frozen 1500-second response reserve the programme records
    # a lost opportunity and remains passive to the exact qualified endpoint.
    supervisor.record_control_opportunity(
        opportunity_id="endpoint-admission-closed",
        frontier_ticks=opening,
        disposition="ENDPOINT_ADMISSION_CLOSED",
    )
    supervisor.observe_interval(
        opening_ticks=opening,
        closing_ticks=opening + supervisor.target_ticks - supervisor.qualified_ticks,
        measurement_qualified=True,
        d14_d8_healthy=True,
        d9_configuration_and_readback_exact=True,
        d6_status="present",
        performance={
            "frequency_error_nanohz": 0,
            "phase_error_ns": 0,
            "drift_nanohz_per_hour": 0,
            "window_support_ticks": supervisor.target_ticks
            - supervisor.qualified_ticks,
        },
    )
    return supervisor


def pty_operational_rehearsal(
    *, bundle: Mapping[str, Any], output_dir: Path
) -> dict[str, object]:
    """Exercise production capture/FIFOs/rotation with accelerated evidence.

    The PTY supplies a deterministic firmware transcript.  It proves host
    command, capture, abort, and counter-contract behavior only, never a
    physical RP2040, D9 waveform, D6 loopback, or DAC response.
    """

    checked = validate_bundle(bundle)
    contract = load_contract(Path(str(checked["bindings"]["contract"]["path"])))
    output_dir.mkdir(parents=True, exist_ok=False)
    run_dir = output_dir / "run"
    run_dir.mkdir()
    transition_dir = output_dir / "transition"
    carrier_dir = output_dir / "carrier"
    master, slave = pty.openpty()
    device = os.ttyname(slave)
    os.close(slave)
    files = default_csv_files()
    _write_new_json(
        run_dir / "run_manifest.json",
        {
            "schema_version": 1,
            "template": False,
            "run_id": "cx322_d9_d6_72h_engineering_pty",
            "stage": "CX322_D9_D6_72H_INTEGRATED_ENGINEERING_REHEARSAL",
            "profile_id": checked["profile_id"],
            "bundle_sha256": checked["bundle_sha256"],
            "actionable": False,
            "actuation_authorized": False,
            "host": {
                "serial_device": device,
                "baud": 115200,
                "sole_serial_owner": True,
                "capture_tool": "host.otis_tools.capture_device",
            },
            "domains": [
                {
                    "name": "rp2040_timer0",
                    "nominal_hz": RP2040_TIMER0_TICKS_PER_SECOND,
                }
            ],
            "channels": [
                {"channel_id": 1, "role": "authoritative_d14_reference"},
                {"channel_id": 2, "role": "authoritative_d8_count"},
                {
                    "channel_id": 3,
                    "role": "diagnostic_d6_forwarded_d9_monitor",
                    "zero_authority": True,
                },
            ],
            "contracts": {entry["contract"]: 1 for entry in files},
            "files": files,
            "evidence_artifacts": [],
        },
    )
    normal = run_dir / "control/normal_commands.fifo"
    emergency = run_dir / "control/emergency_abort.fifo"
    fixture_token = secrets.token_hex(32)
    fixture_capability = f"{CAPABILITY}:{fixture_token}"
    capture_environment = dict(os.environ)
    capture_environment.update(
        {
            PTY_DEVICE_ENV: device,
            PTY_RUN_DIR_ENV: str(run_dir.resolve()),
            PTY_TOKEN_ENV: fixture_token,
        }
    )
    capture = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "host.otis_tools.cx322_d9_d6_72h_engineering",
            PTY_CAPTURE_SUBCOMMAND,
            "--device",
            device,
            "--baud",
            "115200",
            "--run-dir",
            str(run_dir),
            "--duration-s",
            "30",
            "--command-fifo",
            str(normal),
            "--emergency-command-fifo",
            str(emergency),
            "--normal-command-max-age-s",
            "2",
            "--segment-control-dir",
            str(carrier_dir),
            "--segment-capability",
            fixture_capability,
        ],
        cwd=ROOT,
        env=capture_environment,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    output = ""
    commands: list[str] = []
    configuration_sha256 = "a" * 64
    setup = (
        "ACTIVE SETUP 1 1 1 1000 1 0xA83C 1 " + configuration_sha256
    )
    expected_commands = [
        "CONFIG?",
        "DUALCORE?",
        "DAC?",
        "ACTIVE?",
        setup,
        "ACTIVE ARM 1 2 2000",
    ]
    try:
        _wait_for(normal)
        for command in expected_commands:
            send_timestamped_command_to_fifo(normal, command)
            _read_until(master, (command + "\n").encode("ascii"))
            commands.append(command)
        transcript = b"".join(
            (
                _status(1, "build", "profile_id", checked["profile_id"]),
                _status(2, "serial", "baud", "115200"),
                _status(
                    3,
                    "forwarded_clock_output",
                    "state",
                    "configured_10mhz_forwarded_unqualified",
                ),
                _status(4, "forwarded_clock_output", "readback_valid", "true"),
                _status(5, "d14_reference", "state", "healthy"),
                _status(6, "d8_capture", "state", "healthy"),
                _status(7, "forwarded_clock_monitor", "state", "local_degraded"),
                _status(8, "d14_reference", "state", "healthy"),
                _status(9, "d8_capture", "state", "healthy"),
                _status(10, "cx317_setup", "applied_code", str(0xA83C)),
                _status(11, "cx317_setup", "dac_epoch", "1"),
                _status(12, "cx317_setup", "first_consumer_exact", "true"),
            )
        )
        os.write(master, transcript)
        send_command_to_fifo(emergency, "ACTIVE ABORT")
        _read_until(master, b"ACTIVE ABORT\n")
        commands.append("ACTIVE ABORT")
        time.sleep(0.1)
        prepare_transition(run_dir / "run_manifest.json", transition_dir)
        rotation = request_rotation(
            control_dir=carrier_dir,
            capability=fixture_capability,
            to_run=transition_dir,
            mode="transition",
            operation_id="cx322-d9-d6-72h-engineering-pty",
        )
    finally:
        if capture.poll() is None:
            capture.send_signal(signal.SIGINT)
        try:
            output, _ = capture.communicate(timeout=10)
        finally:
            os.close(master)
    if capture.returncode != 0:
        raise RuntimeError(f"capture rehearsal failed: {output[-1200:]}")
    rotation_owner_check = _read_json(
        run_dir / "reports/capture_segment_closure_v1.json"
    )["serial_owner_check"]
    if rotation_owner_check != {
        "performed": False,
        "reason": "bounded_explicit_nonphysical_PTY_fixture_owner_seam",
        "owner_pids": [capture.pid],
        "production_lsof_check_unchanged": True,
        "fixture_capability_sha256": sha256(
            fixture_capability.encode("utf-8")
        ).hexdigest(),
    }:
        raise RuntimeError("PTY owner-check seam escaped its exact boundary")

    supervisor = _run_accelerated_counter_rehearsal(contract)
    summary = supervisor.summary()
    if summary["terminal"] != contract["terminals"]["qualified_complete"]:
        raise RuntimeError("accelerated 72h counter rehearsal did not complete")

    evidence_dir = output_dir / "accelerated-evidence"
    reports_dir = evidence_dir / "reports"
    reports_dir.mkdir(parents=True)
    record_binding = supervisor.persist_record_log(
        evidence_dir / "cx322_d9_d6_72h_records_v1.jsonl"
    )
    replayed = replay_record_log(
        contract=contract,
        record_log_path=Path(str(record_binding["path"])),
    )
    monitor = monitor_record_log(
        contract=contract,
        record_log_path=Path(str(record_binding["path"])),
    )
    analysis = analyze_record_log(
        contract=contract,
        record_log_path=Path(str(record_binding["path"])),
    )
    if replayed.summary() != summary:
        raise RuntimeError("persisted 72h replay differs from supervisor reducer")
    _write_new_json(reports_dir / "analysis.json", analysis)
    _write_new_json(
        reports_dir / "seal.json",
        {
            "record_log_file_sha256": record_binding["file_sha256"],
            "last_record_sha256": record_binding["last_record_sha256"],
            "terminal": summary["terminal"],
            "promotion_permitted": False,
        },
    )
    _write_new_json(
        evidence_dir / "evidence_manifest.json",
        {
            "contract": contract["contract_id"],
            "bundle_sha256": checked["bundle_sha256"],
            "record_contract": RECORD_CONTRACT,
            "record_count": record_binding["record_count"],
            "analyzer": TOOL_ID,
        },
    )
    (evidence_dir / "COMPLETE").write_text("complete\n", encoding="utf-8")
    registration_metadata = {
        "source_revision": str(checked["source_revision"]),
        "build_identity": str(
            checked["bindings"]["firmware_build_manifest"]["sha256"]
        ),
        "profile_identity": str(checked["profile_id"]),
        "attempt_classification": "successful_rehearsal",
        "result_or_failure_reason": "canonical 72h host rehearsal passed",
        "analyzer_identity": TOOL_ID,
    }
    journal = begin_finalization(
        run_dir=evidence_dir,
        index_path=output_dir / "evidence-index.json",
        registration=registration_metadata,
        required_seal=Path("reports/seal.json"),
    )
    for phase, details in (
        ("capture_closed", {"mode": "PTY_fixture"}),
        ("completion", {"terminal": summary["terminal"]}),
        ("snapshot", {"last_record_sha256": summary["last_record_sha256"]}),
        ("analysis", {"consumer": analysis["consumer"]}),
        ("seal", {"path": "reports/seal.json"}),
    ):
        advance_phase(journal, phase, details)
    evidence_identity = package_identity(evidence_dir)["content_sha256"]
    set_registration_intent(
        journal,
        registration=registration_metadata,
        expected_content_sha256=evidence_identity,
    )
    registration = recover_registration(journal)
    report: dict[str, object] = {
        "tool": TOOL_ID,
        "status": "passed",
        "hardware_operations": False,
        "mode": "PTY_fixture_with_accelerated_rp2040_timer0_evidence",
        "bundle_sha256": checked["bundle_sha256"],
        "profile_id": checked["profile_id"],
        "firmware_profile_matrix_integrated": checked[
            "firmware_profile_matrix_integrated"
        ],
        "baud": 115200,
        "serial_selection": "PTY_fixture_not_auto_detect",
        "commands_observed_in_order": commands,
        "priority_abort_delivered": True,
        "rotation": rotation,
        "rotation_owner_check": rotation_owner_check,
        "accelerated_counter_result": summary,
        "canonical_record_log": record_binding,
        "monitor_replay": monitor,
        "analyzer_replay": analysis,
        "finalization_rehearsal": {
            "status": "passed",
            "journal": str(journal),
            "content_sha256": registration["content_sha256"],
            "registered": True,
        },
        "terminal_derived_from_contract": summary["terminal"],
        "d6_local_degradation_did_not_change_terminal": True,
        "waveform_evidence_status": checked["claim_boundary"][
            "waveform_evidence_status"
        ],
        "promotion_permitted": False,
        "activation_bindable": False,
        "rehearsal_class": "local_component_non_authorizing",
        "real_boundaries_exercised": [
            "production_capture_device_process",
            "normal_timestamped_command_fifo",
            "independent_priority_abort_fifo",
            "single_capture_process_retained_serial_handle_across_rotation",
            "same_owner_logical_rotation",
            "contract_validator",
            "exact_integer_counter_duration_and_milestones",
            "setup_plus_144_automatic_application_accounting",
            "repeated_request_acceptance_application_consumer_response_lifecycle",
            "GNSS_METADATA_HOLD_and_D6_locality_replay",
            "canonical_hash_chained_persisted_record_replay",
            "shared_supervisor_monitor_analyzer_reducer",
            "immutable_finalization_seal_and_registration_journal",
        ],
        "not_proved": [
            "fresh_USB_auto_detect",
            "production_lsof_sole_serial_owner_check",
            "firmware_binary_runtime_identity",
            "physical_D14_D8_capture",
            "physical_D9_forwarding_waveform_frequency_or_load",
            "physical_D6_loopback",
            "physical_DAC_setup_application_or_oscillator_response",
            "firmware_144_application_and_3024_code_profile_guards",
            "authorized_live_capture_to_canonical_record_adapter",
            "shared_activation_bearing_capture_supervisor_analyzer_launcher",
            "mandatory_exact_AT2_AH2_production_sidecars",
            "72h_unattended_physical_duration",
        ],
    }
    _write_new_json(output_dir / "reports/rehearsal.json", report)
    return report


def main(argv: list[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if arguments[:1] == [PTY_CAPTURE_SUBCOMMAND]:
        return _bounded_pty_capture_process(arguments[1:])
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    freeze = commands.add_parser("freeze")
    freeze.add_argument("--build-manifest", type=Path, required=True)
    freeze.add_argument("--source-revision", required=True)
    freeze.add_argument("--output", type=Path, required=True)
    preflight = commands.add_parser("preflight")
    preflight.add_argument("--bundle", type=Path, required=True)
    activation_draft = commands.add_parser("activation-draft")
    activation_draft.add_argument("--bundle", type=Path, required=True)
    activation_draft.add_argument("--run-dir", type=Path, required=True)
    activation_draft.add_argument("--run-identity", required=True)
    activation_draft.add_argument("--output", type=Path, required=True)
    activation_preflight = commands.add_parser("activation-preflight")
    activation_preflight.add_argument("--bundle", type=Path, required=True)
    activation_preflight.add_argument("--activation", type=Path, required=True)
    activation_bind = commands.add_parser("activation-bind")
    activation_bind.add_argument("--bundle", type=Path, required=True)
    activation_bind.add_argument("--draft", type=Path, required=True)
    activation_bind.add_argument(
        "--active-hybrid-activation", type=Path, required=True
    )
    activation_bind.add_argument("--output", type=Path, required=True)
    inspect_retained = commands.add_parser("inspect-retained")
    inspect_retained.add_argument("--bundle", type=Path, required=True)
    inspect_retained.add_argument("--activation", type=Path, required=True)
    rehearse = commands.add_parser("rehearse")
    rehearse.add_argument("--bundle", type=Path, required=True)
    rehearse.add_argument("--output-dir", type=Path, required=True)
    shared_rehearse = commands.add_parser("rehearse-campaign18")
    shared_rehearse.add_argument("--active-bundle", type=Path, required=True)
    shared_rehearse.add_argument("--proposal", type=Path, required=True)
    shared_rehearse.add_argument("--output-dir", type=Path, required=True)
    execute = commands.add_parser("run-campaign18")
    execute.add_argument("--bundle", type=Path, required=True)
    execute.add_argument("--adapter-activation", type=Path, required=True)
    execute.add_argument(
        "--active-hybrid-activation", type=Path, required=True
    )
    execute.add_argument("--run-dir", type=Path, required=True)
    execute.add_argument("--adapter-output-dir", type=Path, required=True)
    execute.add_argument("--evidence-index", type=Path, default=DEFAULT_INDEX)
    execute.add_argument("--arduino-cli", default="arduino-cli")
    args = parser.parse_args(arguments)
    if args.command == "freeze":
        result = freeze_bundle(
            build_manifest_path=args.build_manifest,
            source_revision=args.source_revision,
        )
        _write_new_json(args.output, result)
    elif args.command == "preflight":
        result = no_io_preflight(_read_json(args.bundle))
    elif args.command == "activation-draft":
        result = draft_live_activation(
            bundle=_read_json(args.bundle),
            run_directory=args.run_dir,
            run_identity=args.run_identity,
        )
        _write_new_json(args.output, result)
    elif args.command == "activation-preflight":
        result = validate_live_activation(
            bundle=_read_json(args.bundle),
            activation=_read_json(args.activation),
        )
    elif args.command == "activation-bind":
        result = bind_effective_live_activation(
            bundle=_read_json(args.bundle),
            draft=_read_json(args.draft),
            active_hybrid_activation_path=args.active_hybrid_activation,
        )
        _write_new_json(args.output, result)
    elif args.command == "inspect-retained":
        result = RetainedEvidence72hAdapter(
            bundle=_read_json(args.bundle),
            activation=_read_json(args.activation),
        ).poll()
    elif args.command == "rehearse":
        result = pty_operational_rehearsal(
            bundle=_read_json(args.bundle), output_dir=args.output_dir
        )
    elif args.command == "rehearse-campaign18":
        result = campaign18_operational_rehearsal(
            active_bundle_path=args.active_bundle,
            proposal_path=args.proposal,
            output_dir=args.output_dir,
        )
    else:
        result = run_campaign18_qualification(
            bundle_path=args.bundle,
            adapter_activation_path=args.adapter_activation,
            active_hybrid_activation_path=args.active_hybrid_activation,
            run_dir=args.run_dir,
            adapter_output_dir=args.adapter_output_dir,
            evidence_index_path=args.evidence_index,
            arduino_cli=args.arduino_cli,
        )
    print(json.dumps(result, sort_keys=True, allow_nan=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
