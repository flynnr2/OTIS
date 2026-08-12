"""Freeze and validate an exact no-write qualification bundle.

This module is offline-safe. It validates build provenance and emits immutable
JSON, but it never opens serial, flashes firmware, creates FIFOs, sends a
command, or touches the DAC.
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

from tools.firmware_matrix import configuration_hash, load_matrix, source_input_hash

from .no_write_prewrite_readiness_contract import (
    ACTIVE_STATUS_KEYS,
    INHERITED_PREVIEW_BASELINE_PROVENANCE,
    RAW_PPS_QUALIFICATION_DEADLINE_S,
    RUNTIME_CONTRACT_ID,
)
from .programme_status import (
    NO_WRITE_BENCH_REHEARSAL,
    OFFLINE_PREPARATION,
    require_programme_operation_allowed,
)
from .run_paths import default_csv_files


REPO_ROOT = Path(__file__).resolve().parents[2]
PROGRAMME_ID = "cx319_stabilized_tight_deadband"
NO_WRITE_BENCH_OPERATION = NO_WRITE_BENCH_REHEARSAL
POLICY_PATH = REPO_ROOT / "profiles/discipline/cx319_stabilized_tight_deadband_v1.json"
AUTHORITY_PATH = (
    REPO_ROOT / "profiles/qualification/cx319_g1_no_write_bench_authority_v1.json"
)
MATRIX_PATH = REPO_ROOT / "firmware/arduino/firmware_matrix.json"
TOOL_ID = "cx319_g1_bundle_v1"
BUNDLE_ID = "cx319_g1_exact_no_write_rehearsal_bundle_v1"
BUNDLE_SCHEMA_VERSION = 1
RUN_MANIFEST_SCHEMA_VERSION = 1
REHEARSAL_STAGE = "CX319_G1_EXACT_NO_WRITE_REHEARSAL"
REHEARSAL_DURATION_S = 2700
SELECTED_ESTIMATE_SPAN_S = 600
Q1_INTENTIONAL_DETACH_SCHEDULE = (
    (2.0, 0.250),
    (5.0, 0.750),
    (9.0, 1.250),
)
RUN_BUNDLE_PATH = Path("cx319_g1_exact_bundle_v1.json")
TRANSITION_RUN_DIR = Path("g1_owner_handoff_transition")
NORMAL_COMMAND_ALLOWLIST = (
    "CONFIG?",
    "DAC?",
    "FC0?",
    "ACTIVE?",
    "ACTIVE SNAPSHOT <nonzero_uint32>",
    "ACTIVE LEASE <nonzero_uint32>",
)
FORBIDDEN_COMMAND_PREFIXES = (
    "DAC SET ",
    "DAC MID",
    "DAC ZERO",
    "ACTIVE ARM ",
    "ACTIVE EVIDENCE ",
    "DUALCORE ",
    "SWEEP ",
    "PPSGEN ",
)
EMERGENCY_COMMAND = "ACTIVE ABORT"
LEG_IDENTITIES = {
    "A": ("cx319_tight_lower", 3195001, 0xA808, "positive"),
    "B": ("cx319_tight_upper", 3195002, 0xA848, "negative"),
}

HOST_TOOL_PATHS = {
    "bundle": Path(__file__),
    "rehearsal": Path(__file__).with_name("no_write_qualification_run.py"),
    "supervisor": Path(__file__).with_name("no_write_qualification_supervisor.py"),
    "analyzer": Path(__file__).with_name("no_write_qualification_analyze.py"),
    "runtime_contract": Path(__file__).with_name("no_write_prewrite_readiness_contract.py"),
    "host_attach_contract": Path(__file__).with_name(
        "host_attach_health_contract.py"
    ),
    "capture": Path(__file__).with_name("capture_device.py"),
    "active_status_live_state": Path(__file__).with_name(
        "active_status_live_state.py"
    ),
    "serial_commands": Path(__file__).with_name("serial_commands.py"),
    "abort_path": Path(__file__).with_name("cx317_abort_path.py"),
    "segment_rotation": Path(__file__).with_name("capture_segment_rotation.py"),
    "evidence_snapshot": Path(__file__).with_name("evidence.py"),
    "evidence_index": Path(__file__).with_name("evidence_index.py"),
    "run_validation": Path(__file__).with_name("validate_run.py"),
    "offline_preflight": Path(__file__).with_name("no_write_qualification_preflight.py"),
}
FROZEN_V1_HOST_TOOL_NAMES = frozenset(
    {
        "abort_path",
        "analyzer",
        "bundle",
        "capture",
        "evidence_index",
        "evidence_snapshot",
        "offline_preflight",
        "rehearsal",
        "run_validation",
        "runtime_contract",
        "segment_rotation",
        "serial_commands",
        "supervisor",
    }
)
FROZEN_V2_HOST_TOOL_NAMES = frozenset(
    {
        *FROZEN_V1_HOST_TOOL_NAMES,
        "host_attach_contract",
    }
)
CURRENT_HOST_TOOL_NAMES = frozenset(HOST_TOOL_PATHS)


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


def _canonical_sha256(value: object) -> str:
    return sha256(
        json.dumps(
            value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode("utf-8")
    ).hexdigest()


def normal_command_allowed(command: str) -> bool:
    if command in {"CONFIG?", "DAC?", "FC0?", "ACTIVE?"}:
        return True
    for prefix in ("ACTIVE SNAPSHOT ", "ACTIVE LEASE "):
        if command.startswith(prefix):
            sequence = command[len(prefix) :]
            return sequence.isdigit() and 0 < int(sequence) <= 0xFFFFFFFF
    return False


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
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


def _binding(path: Path) -> dict[str, Any]:
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f"bundle input is unavailable: {path}")
    return {
        "path": str(path),
        "sha256": _sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _binding_current(binding: object) -> bool:
    if not isinstance(binding, dict):
        return False
    path_value = binding.get("path")
    if not isinstance(path_value, str):
        return False
    path = Path(path_value)
    return (
        path.is_file()
        and binding.get("sha256") == _sha256_file(path)
        and binding.get("size_bytes") == path.stat().st_size
    )


def _git_identity() -> tuple[str, str]:
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=REPO_ROOT,
        check=True,
        text=True,
        capture_output=True,
    ).stdout
    return commit, "dirty" if status else "clean"


def _git_is_ancestor(ancestor: str, descendant: str) -> bool:
    completed = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=REPO_ROOT,
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.returncode == 0


def _load_policy() -> dict[str, Any]:
    policy = _read_object(POLICY_PATH, "CX319 policy")
    if (
        policy.get("schema_version") != 1
        or policy.get("policy_id")
        != "CX319_STABILIZED_TIGHT_DEADBAND_FREQUENCY_ONLY_V1"
    ):
        raise ValueError("unexpected CX319 policy identity")
    bindings = policy.get("bindings")
    if not isinstance(bindings, dict) or not bindings:
        raise ValueError("CX319 policy bindings are unavailable")
    for name, binding in bindings.items():
        if not isinstance(binding, dict):
            raise ValueError(f"CX319 policy binding is malformed: {name}")
        path = REPO_ROOT / str(binding.get("path", ""))
        if not path.is_file() or binding.get("sha256") != _sha256_file(path):
            raise ValueError(f"CX319 policy binding is stale: {name}")
    return policy


def _load_authority() -> dict[str, Any]:
    authority = _read_object(AUTHORITY_PATH, "CX319 G1 authority overlay")
    if (
        authority.get("schema_version") != 1
        or authority.get("authority_id")
        != "CX319_Q1_Q3_SEQUENCE_AUTHORITY_V1"
        or authority.get("programme_id") != PROGRAMME_ID
        or authority.get("operation") != NO_WRITE_BENCH_OPERATION
        or authority.get("gate") != "G1"
    ):
        raise ValueError("unexpected CX319 G1 authority overlay identity")
    bindings = authority.get("bindings")
    if not isinstance(bindings, dict) or not bindings:
        raise ValueError("CX319 G1 authority bindings are unavailable")
    for name, binding in bindings.items():
        if not isinstance(binding, dict):
            raise ValueError(f"CX319 G1 authority binding is malformed: {name}")
        path = REPO_ROOT / str(binding.get("path", ""))
        if not path.is_file() or binding.get("sha256") != _sha256_file(path):
            raise ValueError(f"CX319 G1 authority binding is stale: {name}")
    authority_model = authority.get("authority_model", {})
    counters = authority.get("physical_write_counters", {})
    if (
        authority_model.get("control_policy_grants_operational_authority")
        is not False
        or authority_model.get("programme_status_contract_id")
        != "otis_programme_status_v2"
        or authority_model.get("programme_status_operation_required_at_execution")
        != NO_WRITE_BENCH_OPERATION
        or authority_model.get("passing_rehearsal_grants_live_authority") is not False
        or not isinstance(counters, dict)
        or not counters
        or any(value != 0 for value in counters.values())
        or set(authority.get("forbidden_operations", []))
        != {
            "dac_write",
            "control_arm",
            "setup_stimulus",
            "automatic_correction",
            "rehearsal_to_live_promotion",
            "live_actuation",
            "phase_or_hybrid_actuation",
        }
    ):
        raise ValueError("CX319 G1 authority overlay exposes write/live authority")
    return authority


def _frozen_leg_spec(leg: str) -> dict[str, Any]:
    if leg not in LEG_IDENTITIES:
        raise ValueError("CX319 leg must be A or B")
    expected = LEG_IDENTITIES[leg]
    return {
        "leg": leg,
        "profile_id": expected[0],
        "run_binding_tag": expected[1],
        "run_identity": f"{expected[0]}:{expected[1]}",
        "planned_live_setup_code": expected[2],
        "planned_live_setup_code_hex": f"0x{expected[2]:04X}",
        "required_automatic_direction": expected[3],
    }


def leg_spec(leg: str) -> dict[str, Any]:
    policy = _load_policy()
    frozen = _frozen_leg_spec(leg)
    value = policy["legs"][leg]
    observed = (
        value.get("firmware_profile"),
        value.get("run_binding_tag"),
        value.get("exact_setup_code"),
        value.get("required_automatic_direction"),
    )
    expected = LEG_IDENTITIES[leg]
    if observed != expected:
        raise ValueError(f"CX319 leg {leg} identity differs from policy")
    return frozen


def validate_build(
    *,
    leg: str,
    build_manifest_path: Path,
    uf2_path: Path,
    allow_clean_ancestor_source: bool = False,
) -> dict[str, Any]:
    spec = leg_spec(leg)
    matrix = load_matrix(MATRIX_PATH)
    profiles = {
        profile["id"]: profile for profile in matrix["profiles"]
    }
    profile = profiles.get(spec["profile_id"])
    if not isinstance(profile, dict) or profile.get("expect") != "pass":
        raise ValueError("CX319 exact supported firmware profile is unavailable")
    if set(profile.get("verification_tiers", [])) != {
        "standard_campaign",
        "release",
        "bench",
    }:
        raise ValueError("CX319 exact profile lacks current verification tiers")

    build_manifest_path = build_manifest_path.resolve()
    uf2_path = uf2_path.resolve()
    build = _read_object(build_manifest_path, "CX319 firmware build manifest")
    provenance = build.get("provenance")
    if not isinstance(provenance, dict):
        raise ValueError("CX319 build provenance is unavailable")
    source = provenance.get("source")
    configuration = provenance.get("configuration")
    if not isinstance(source, dict) or not isinstance(configuration, dict):
        raise ValueError("CX319 build source/configuration provenance is malformed")
    current_commit, current_state = _git_identity()
    if current_state != "clean":
        raise ValueError("G1 exact bundle requires a clean repository source state")
    source_commit = source.get("git_commit")
    source_revision_allowed = source_commit == current_commit or (
        allow_clean_ancestor_source
        and isinstance(source_commit, str)
        and len(source_commit) == 40
        and _git_is_ancestor(source_commit, current_commit)
    )
    if (
        source.get("state") != "clean"
        or not source_revision_allowed
        or source.get("sha256") != source_input_hash(matrix_path=MATRIX_PATH)
    ):
        raise ValueError("CX319 build does not bind the current clean source")
    if (
        configuration.get("profile_id") != spec["profile_id"]
        or configuration.get("defines") != profile["defines"]
        or configuration.get("fqbn") != matrix["target"]["fqbn"]
        or configuration.get("sha256") != configuration_hash(matrix, profile)
    ):
        raise ValueError("CX319 build configuration differs from the exact profile")
    artifacts = build.get("artifacts")
    if not isinstance(artifacts, list) or not uf2_path.is_file():
        raise ValueError("CX319 UF2 artifact inventory is unavailable")
    matches = [
        item
        for item in artifacts
        if isinstance(item, dict) and item.get("name") == uf2_path.name
    ]
    if len(matches) != 1:
        raise ValueError("CX319 build does not bind exactly one supplied UF2")
    artifact = matches[0]
    if (
        artifact.get("sha256") != _sha256_file(uf2_path)
        or artifact.get("size_bytes") != uf2_path.stat().st_size
    ):
        raise ValueError("CX319 supplied UF2 differs from its build manifest")
    budget = build.get("resource_budget")
    if (
        not isinstance(budget, dict)
        or budget.get("contract") != "otis_firmware_resource_budget_v1"
        or budget.get("status") != "within_budget"
    ):
        raise ValueError("CX319 firmware build is outside the resource budget")
    return {
        "profile_id": spec["profile_id"],
        "build_manifest": _binding(build_manifest_path),
        "uf2": _binding(uf2_path),
        "git_commit": source_commit,
        "source_state": "clean",
        "source_sha256": source["sha256"],
        "configuration_sha256": configuration["sha256"],
        "build_invocation_id": provenance["invocation"]["id"],
        "fqbn": configuration["fqbn"],
        "resource_budget": budget,
        "build_provenance_required": True,
    }


def validate_confirmed_installed_firmware(
    *,
    firmware: dict[str, Any],
    flash_record_path: Path,
) -> dict[str, Any]:
    """Bind a prior successful exact flash to byte-identical firmware."""

    flash_record_path = flash_record_path.resolve()
    flash = _read_object(flash_record_path, "confirmed G1 flash record")
    source_bundle_path = flash_record_path.parent.parent / RUN_BUNDLE_PATH
    source_bundle = validate_frozen_bundle(source_bundle_path)
    source_firmware = source_bundle["firmware"]
    if (
        flash.get("status") != "pass"
        or flash.get("operation") != "exact_cx319_g1_firmware_flash"
        or flash.get("attempt_count") != 1
        or flash.get("board_before") != flash.get("board_after")
        or flash.get("board_after", {}).get("serial_number")
        != "503533748A919118"
        or flash.get("profile_id") != source_firmware.get("profile_id")
        or flash.get("build_manifest_sha256")
        != source_firmware.get("build_manifest", {}).get("sha256")
        or flash.get("uf2_sha256")
        != source_firmware.get("uf2", {}).get("sha256")
        or flash.get("bundle_sha256") != source_bundle.get("bundle_sha256")
        or flash.get("dac_value_write_attempts") != 0
        or flash.get("setup_stimulus_attempts") != 0
        or flash.get("control_arm_attempts") != 0
    ):
        raise ValueError("source flash is not one confirmed exact G1 upload")
    for key in ("profile_id", "source_sha256", "configuration_sha256"):
        if firmware.get(key) != source_firmware.get(key):
            raise ValueError(
                f"current firmware {key} differs from confirmed installed firmware"
            )
    if firmware.get("uf2", {}).get("sha256") != flash.get("uf2_sha256"):
        raise ValueError("current UF2 bytes differ from confirmed installed firmware")
    return {
        "mode": "reuse_confirmed_installed_firmware",
        "firmware_flashes_allowed": 0,
        "source_flash_record": _binding(flash_record_path),
        "source_bundle": _binding(source_bundle_path),
        "source_bundle_sha256": source_bundle["bundle_sha256"],
        "source_build_manifest_sha256": flash["build_manifest_sha256"],
        "installed_uf2_sha256": flash["uf2_sha256"],
        "installed_board": flash["board_after"],
    }


def _host_bindings() -> dict[str, dict[str, Any]]:
    return {name: _binding(path) for name, path in HOST_TOOL_PATHS.items()}


def create_bundle(
    *,
    leg: str,
    build_manifest_path: Path,
    uf2_path: Path,
    serial_device: str,
    output_path: Path,
    confirmed_flash_record_path: Path | None = None,
) -> dict[str, Any]:
    require_programme_operation_allowed(PROGRAMME_ID, OFFLINE_PREPARATION)
    if not serial_device.startswith("/dev/"):
        raise ValueError("G1 bundle requires an explicit /dev serial path")
    spec = leg_spec(leg)
    firmware = validate_build(
        leg=leg,
        build_manifest_path=build_manifest_path,
        uf2_path=uf2_path,
        allow_clean_ancestor_source=(confirmed_flash_record_path is not None),
    )
    host_source_revision, host_source_state = _git_identity()
    if host_source_state != "clean":
        raise ValueError("G1 exact bundle requires a clean host source state")
    firmware_entry = (
        {
            "mode": "single_exact_flash",
            "firmware_flashes_allowed": 1,
        }
        if confirmed_flash_record_path is None
        else validate_confirmed_installed_firmware(
            firmware=firmware,
            flash_record_path=confirmed_flash_record_path,
        )
    )
    policy = _load_policy()
    authority_overlay = _load_authority()
    payload: dict[str, Any] = {
        "schema_version": BUNDLE_SCHEMA_VERSION,
        "tool": TOOL_ID,
        "bundle_id": BUNDLE_ID,
        "created_utc": _utc_now(),
        "programme_id": PROGRAMME_ID,
        "host_source_revision": host_source_revision,
        "gate": "G1",
        "leg": spec,
        "firmware": firmware,
        "firmware_entry": firmware_entry,
        "policy": {
            "path": str(POLICY_PATH),
            "sha256": _sha256_file(POLICY_PATH),
            "policy_id": policy["policy_id"],
            "bindings": policy["bindings"],
        },
        "operator_authority": {
            "path": str(AUTHORITY_PATH),
            "sha256": _sha256_file(AUTHORITY_PATH),
            "authority_id": authority_overlay["authority_id"],
            "bindings": authority_overlay["bindings"],
        },
        "host_tools": _host_bindings(),
        "device": {
            "path": serial_device,
            "expected_board_serial": "503533748A919118",
            "baud": 115200,
            "single_continuously_draining_owner": True,
        },
        "rehearsal": {
            "minimum_capture_duration_s": REHEARSAL_DURATION_S,
            "minimum_selected_estimate_span_s": SELECTED_ESTIMATE_SPAN_S,
            "minimum_fresh_selected_estimates": 1,
            "setup_writes": 0,
            "automatic_writes": 0,
            "dac_value_writes": 0,
            "control_arms": 0,
            "rehearsal_to_live_promotion": False,
            "same_profile_and_uf2_required_for_later_live_proposal": True,
        },
        "commands": {
            "normal_allowlist": list(NORMAL_COMMAND_ALLOWLIST),
            "emergency_allowlist": [EMERGENCY_COMMAND],
            "forbidden_prefixes": list(FORBIDDEN_COMMAND_PREFIXES),
            "write_timeout_s": 1.0,
            "normal_command_max_age_s": 2.0,
            "normal_command_batch_limit": 1,
        },
        "transport_fault": {
            "normal_path_obstruction": "SIGSTOP sole capture owner then saturate normal FIFO",
            "independent_priority_abort": EMERGENCY_COMMAND,
            "capture_resume_required": True,
            "same_owner_after_resume_required": True,
        },
        "q1_real_io": {
            "intentional_detach_schedule": [
                {"after_first_open_s": after_s, "detached_s": detached_s}
                for after_s, detached_s in Q1_INTENTIONAL_DETACH_SCHEDULE
            ],
            "lease_expiry_observation_s": 31,
            "qualification_boundary_s": RAW_PPS_QUALIFICATION_DEADLINE_S,
            "dac_value_writes": 0,
        },
        "rotation": {
            "protocol": "otis_same_owner_logical_segment_rotation_v1",
            "serial_reopen_allowed": False,
            "owner_pid_change_allowed": False,
            "transition_spool_actuation_authorized": False,
        },
        "analysis_and_seal": {
            "all_declared_contracts_validate": True,
            "tight_deadband_replay_exact": True,
            "phase_hybrid_and_tight_authority_zero": True,
            "actual_analyzer_and_seal_required": True,
            "external_evidence_registration_required": True,
        },
        "runtime_contract": {
            "id": RUNTIME_CONTRACT_ID,
            "active_status_keys": list(ACTIVE_STATUS_KEYS),
            "inherited_preview_baseline_code": "0xA828",
            "inherited_preview_baseline_provenance": (
                INHERITED_PREVIEW_BASELINE_PROVENANCE
            ),
            "physical_applied_code_before_live_stimulus": "unknown",
            "missing_status_is_failure": True,
            "attachment_mode": "arbitrary_running_instrument",
            "firmware_uptime_limit_s": None,
            "device_snapshot": "nonce_bound_complete_generation",
            "evidence_session_boundary": (
                "separate_nonce_bound_immutable_cumulative_baseline"
            ),
            "gnss_pps_qualification_deadline_s": (
                RAW_PPS_QUALIFICATION_DEADLINE_S
            ),
        },
        "authority": {
            "programme_operation_required": NO_WRITE_BENCH_OPERATION,
            "flash_exact_firmware": (
                firmware_entry["mode"] == "single_exact_flash"
            ),
            "reuse_confirmed_installed_firmware": (
                firmware_entry["mode"]
                == "reuse_confirmed_installed_firmware"
            ),
            "serial_capture": True,
            "read_only_queries_and_leases": True,
            "priority_abort": True,
            "dac_value_write": False,
            "setup_stimulus": False,
            "control_arm": False,
            "automatic_correction": False,
            "live_leg": False,
            "phase_or_hybrid_actionable": False,
        },
        "stop_conditions": [
            "unexpected serial owner or reconnect",
            "any forbidden command request",
            "any DAC or active transaction row",
            "any non-zero preview authority field",
            "runtime identity, status snapshot, queue, memory or diagnostic gate failure",
            "normal FIFO does not saturate during bounded obstruction",
            "priority abort is not observed before stale normal work",
            "same-owner rotation changes owner or reopens serial",
            "2700 second endpoint lacks one fresh authoritative 600 second estimate",
        ],
    }
    payload["bundle_sha256"] = _canonical_sha256(payload)
    _atomic_new_json(output_path, payload)
    return payload


def _binding_well_formed(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    digest = value.get("sha256")
    return (
        isinstance(value.get("path"), str)
        and bool(value["path"])
        and isinstance(digest, str)
        and len(digest) == 64
        and all(character in "0123456789abcdef" for character in digest)
        and isinstance(value.get("size_bytes"), int)
        and value["size_bytes"] >= 0
    )


def validate_frozen_bundle(path: Path) -> dict[str, Any]:
    """Validate an immutable run bundle without consulting current inputs."""

    path = path.resolve()
    bundle = _read_object(path, "CX319 G1 bundle")
    claimed = bundle.get("bundle_sha256")
    unsigned = {key: value for key, value in bundle.items() if key != "bundle_sha256"}
    if (
        bundle.get("schema_version") != BUNDLE_SCHEMA_VERSION
        or bundle.get("tool") != TOOL_ID
        or bundle.get("bundle_id") != BUNDLE_ID
        or bundle.get("programme_id") != PROGRAMME_ID
        or bundle.get("gate") != "G1"
        or claimed != _canonical_sha256(unsigned)
    ):
        raise ValueError("CX319 G1 bundle identity or digest is invalid")
    leg = bundle.get("leg", {}).get("leg")
    if bundle.get("leg") != _frozen_leg_spec(str(leg)):
        raise ValueError("CX319 G1 bundle leg identity is invalid")
    firmware = bundle.get("firmware")
    if (
        not isinstance(firmware, dict)
        or firmware.get("profile_id") != bundle["leg"]["profile_id"]
        or firmware.get("source_state") != "clean"
        or not _binding_well_formed(firmware.get("build_manifest"))
        or not _binding_well_formed(firmware.get("uf2"))
    ):
        raise ValueError("CX319 G1 firmware binding is unavailable")
    firmware_entry = bundle.get("firmware_entry")
    if firmware_entry is None:
        firmware_entry = {
            "mode": "single_exact_flash",
            "firmware_flashes_allowed": 1,
        }
    if not isinstance(firmware_entry, dict) or firmware_entry.get("mode") not in {
        "single_exact_flash",
        "reuse_confirmed_installed_firmware",
    }:
        raise ValueError("CX319 G1 firmware entry mode is invalid")
    policy = bundle.get("policy", {})
    operator_authority = bundle.get("operator_authority", {})
    if (
        not isinstance(policy, dict)
        or policy.get("policy_id")
        != "CX319_STABILIZED_TIGHT_DEADBAND_FREQUENCY_ONLY_V1"
        or not isinstance(policy.get("sha256"), str)
        or len(policy["sha256"]) != 64
        or not isinstance(operator_authority, dict)
        or operator_authority.get("authority_id")
        != "CX319_Q1_Q3_SEQUENCE_AUTHORITY_V1"
    ):
        raise ValueError("CX319 G1 frozen policy or authority identity is invalid")
    tools = bundle.get("host_tools")
    runtime_contract_id = bundle.get("runtime_contract", {}).get("id")
    expected_tool_names = {
        "cx319_g1_prewrite_runtime_contract_v1": FROZEN_V1_HOST_TOOL_NAMES,
        "cx319_g1_prewrite_runtime_contract_v2": FROZEN_V2_HOST_TOOL_NAMES,
        "cx319_g1_prewrite_runtime_contract_v3": CURRENT_HOST_TOOL_NAMES,
        RUNTIME_CONTRACT_ID: CURRENT_HOST_TOOL_NAMES,
    }.get(runtime_contract_id)
    if (
        not isinstance(tools, dict)
        or expected_tool_names is None
        or set(tools) != expected_tool_names
        or not all(_binding_well_formed(item) for item in tools.values())
    ):
        raise ValueError("CX319 G1 frozen host tool binding is incomplete")
    authority = bundle.get("authority", {})
    rehearsal = bundle.get("rehearsal", {})
    commands = bundle.get("commands", {})
    runtime_contract = bundle.get("runtime_contract", {})
    q1_real_io = bundle.get("q1_real_io", {})
    if (
        authority.get("programme_operation_required") != NO_WRITE_BENCH_OPERATION
        or any(
            authority.get(key) is not False
            for key in (
                "dac_value_write",
                "setup_stimulus",
                "control_arm",
                "automatic_correction",
                "live_leg",
                "phase_or_hybrid_actionable",
            )
        )
        or rehearsal.get("minimum_capture_duration_s") != REHEARSAL_DURATION_S
        or authority.get("flash_exact_firmware")
        != (firmware_entry["mode"] == "single_exact_flash")
        or authority.get("reuse_confirmed_installed_firmware", False)
        != (firmware_entry["mode"] == "reuse_confirmed_installed_firmware")
        or firmware_entry.get("firmware_flashes_allowed")
        != (1 if firmware_entry["mode"] == "single_exact_flash" else 0)
        or any(
            rehearsal.get(key) != 0
            for key in (
                "setup_writes",
                "automatic_writes",
                "dac_value_writes",
                "control_arms",
            )
        )
        or tuple(commands.get("normal_allowlist", [])) != NORMAL_COMMAND_ALLOWLIST
        or commands.get("emergency_allowlist") != [EMERGENCY_COMMAND]
        or tuple(commands.get("forbidden_prefixes", []))
        != FORBIDDEN_COMMAND_PREFIXES
        or q1_real_io
        != {
            "intentional_detach_schedule": [
                {"after_first_open_s": after_s, "detached_s": detached_s}
                for after_s, detached_s in Q1_INTENTIONAL_DETACH_SCHEDULE
            ],
            "lease_expiry_observation_s": 31,
            "qualification_boundary_s": RAW_PPS_QUALIFICATION_DEADLINE_S,
            "dac_value_writes": 0,
        }
        or (
            runtime_contract_id == RUNTIME_CONTRACT_ID
            and (
                runtime_contract.get("attachment_mode")
                != "arbitrary_running_instrument"
                or runtime_contract.get("firmware_uptime_limit_s") is not None
                or runtime_contract.get("device_snapshot")
                != "nonce_bound_complete_generation"
                or runtime_contract.get("evidence_session_boundary")
                != "separate_nonce_bound_immutable_cumulative_baseline"
                or runtime_contract.get("gnss_pps_qualification_deadline_s")
                != RAW_PPS_QUALIFICATION_DEADLINE_S
            )
        )
    ):
        raise ValueError("CX319 G1 bundle exposes write/live authority")
    return bundle


def validate_bundle(path: Path) -> dict[str, Any]:
    """Validate a bundle for current G1 entry against the clean worktree."""

    bundle = validate_frozen_bundle(path)
    leg = str(bundle["leg"]["leg"])
    firmware = bundle["firmware"]
    if bundle["leg"] != leg_spec(leg):
        raise ValueError("CX319 G1 bundle leg identity is stale")
    firmware_entry = bundle.get(
        "firmware_entry",
        {"mode": "single_exact_flash", "firmware_flashes_allowed": 1},
    )
    current = validate_build(
        leg=leg,
        build_manifest_path=Path(firmware["build_manifest"]["path"]),
        uf2_path=Path(firmware["uf2"]["path"]),
        allow_clean_ancestor_source=(
            firmware_entry.get("mode")
            == "reuse_confirmed_installed_firmware"
        ),
    )
    if firmware != current:
        raise ValueError("CX319 G1 firmware binding differs from current exact inputs")
    current_host_revision, current_host_state = _git_identity()
    if (
        current_host_state != "clean"
        or bundle.get("host_source_revision") != current_host_revision
    ):
        raise ValueError("CX319 G1 bundle host source binding is stale")
    if firmware_entry.get("mode") == "reuse_confirmed_installed_firmware":
        source_flash = firmware_entry.get("source_flash_record", {})
        if not isinstance(source_flash, dict):
            raise ValueError("confirmed installed firmware source is unavailable")
        current_entry = validate_confirmed_installed_firmware(
            firmware=firmware,
            flash_record_path=Path(str(source_flash.get("path", ""))),
        )
        if firmware_entry != current_entry:
            raise ValueError("confirmed installed firmware binding is stale")
    if bundle.get("policy", {}).get("sha256") != _sha256_file(POLICY_PATH):
        raise ValueError("CX319 G1 bundle policy binding is stale")
    authority_overlay = _load_authority()
    if bundle.get("operator_authority") != {
        "path": str(AUTHORITY_PATH),
        "sha256": _sha256_file(AUTHORITY_PATH),
        "authority_id": authority_overlay["authority_id"],
        "bindings": authority_overlay["bindings"],
    }:
        raise ValueError("CX319 G1 bundle authority binding is stale")
    if (
        set(bundle["host_tools"]) != set(HOST_TOOL_PATHS)
        or not all(
            _binding_current(item) for item in bundle["host_tools"].values()
        )
    ):
        raise ValueError("CX319 G1 host tool binding is stale or incomplete")
    return bundle


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
    bundle_path: Path,
    run_dir: Path,
    output_path: Path,
    q1_real_io: bool = False,
) -> dict[str, Any]:
    bundle = validate_bundle(bundle_path)
    run_dir = run_dir.resolve()
    files = _required_files()
    spec = bundle["leg"]
    transition_evidence = [
        (TRANSITION_RUN_DIR / "run_manifest.json").as_posix(),
        (TRANSITION_RUN_DIR / "raw/serial.log").as_posix(),
        (
            TRANSITION_RUN_DIR / "reports/capture_device_state.json"
        ).as_posix(),
        (
            TRANSITION_RUN_DIR / "reports/capture_segment_closure_v1.json"
        ).as_posix(),
        *[
            (TRANSITION_RUN_DIR / str(entry["path"])).as_posix()
            for entry in files
            if not entry.get("optional")
        ],
    ]
    manifest = {
        "schema_version": RUN_MANIFEST_SCHEMA_VERSION,
        "template": False,
        "run_id": run_dir.name,
        "created_utc": _utc_now(),
        "started_at_utc": _utc_now(),
        "stage": REHEARSAL_STAGE,
        "h_phase": "H1",
        "board": "arduino_nano_rp2040_connect",
        "capture_mode": "pio_wait_cumulative_snapshot_with_independent_gpio_ref",
        "control_mode": "cx319_exact_profile_no_write_rehearsal",
        "closed_loop_control": False,
        "actionable": False,
        "actuation_authorized": False,
        "qualification_evidence": False,
        "firmware": bundle["firmware"],
        "policy": bundle["policy"],
        "operator_authority": bundle["operator_authority"],
        "bundle": {
            "path": str(bundle_path.resolve()),
            "sha256": _sha256_file(bundle_path.resolve()),
            "bundle_sha256": bundle["bundle_sha256"],
        },
        "host": {
            "capture_tool": "host.otis_tools.capture_device",
            "supervisor_tool": "host.otis_tools.no_write_qualification_supervisor",
            "serial_device": bundle["device"]["path"],
            "baud": 115200,
            "sole_serial_owner": True,
            "independent_abort_fifo_required": True,
            "same_owner_segment_rotation_required": True,
            "tool_bindings": bundle["host_tools"],
        },
        "cx319": {
            "gate": "G1",
            "mode": "no_write_rehearsal",
            **spec,
            "runtime_contract": bundle["runtime_contract"],
            "rehearsal": bundle["rehearsal"],
            "authority": bundle["authority"],
            "commands": bundle["commands"],
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
            entry["contract"]: (
                2 if entry["contract"] == "estimates_v2" else 1
            )
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
            "reports/cx319_g1_transport_rehearsal_v1.json",
            "reports/cx319_g1_flash_v1.json",
            "reports/cx319_g1_analysis_v1.json",
            "reports/CX319_G1_REHEARSAL.md",
            "reports/cx319_g1_capture_launcher.log",
            "reports/cx319_g1_supervisor.log",
            RUN_BUNDLE_PATH.as_posix(),
            *(
                [
                    "reports/cx319_q1_real_io_prelude_v1.json",
                    "reports/cx319_q1_evidence_session_baseline_v1.json",
                ]
                if q1_real_io
                else []
            ),
            *transition_evidence,
        ],
        "evidence_artifacts": [
            "reports/capture_device_state.json",
            "reports/cx317_active_status_live_state_v1.json",
            "reports/capture_segment_closure_v1.json",
            "reports/cx317_active_supervisor_state.json",
            "reports/cx317_active_supervisor_events.jsonl",
            "reports/cx319_g1_transport_rehearsal_v1.json",
            "reports/cx319_g1_flash_v1.json",
            "reports/cx319_g1_capture_launcher.log",
            "reports/cx319_g1_supervisor.log",
            RUN_BUNDLE_PATH.as_posix(),
            *(
                [
                    "reports/cx319_q1_real_io_prelude_v1.json",
                    "reports/cx319_q1_evidence_session_baseline_v1.json",
                ]
                if q1_real_io
                else []
            ),
            *transition_evidence,
        ],
        "known_limitations": [
            "G1 is a no-write operational rehearsal, not frequency-control evidence.",
            "The historical A828 context is not current physical DAC confirmation.",
            "Relative phase remains arbitrary-epoch and phase/hybrid outputs have zero authority.",
        ],
    }
    if q1_real_io:
        manifest["q1_real_io"] = bundle["q1_real_io"]
    _atomic_new_json(output_path, manifest)
    return manifest


def validate_run_manifest(path: Path) -> dict[str, Any]:
    manifest = _read_object(path.resolve(), "CX319 G1 run manifest")
    if (
        manifest.get("schema_version") != RUN_MANIFEST_SCHEMA_VERSION
        or manifest.get("stage") != REHEARSAL_STAGE
        or manifest.get("closed_loop_control") is not False
        or manifest.get("actionable") is not False
        or manifest.get("actuation_authorized") is not False
        or manifest.get("qualification_evidence") is not False
    ):
        raise ValueError("CX319 G1 run manifest identity or authority is invalid")
    bundle_binding = manifest.get("bundle")
    if not isinstance(bundle_binding, dict):
        raise ValueError("CX319 G1 run manifest lacks a bundle binding")
    bundle_path = Path(str(bundle_binding.get("path", "")))
    bundle = validate_frozen_bundle(bundle_path)
    if (
        bundle_binding.get("sha256") != _sha256_file(bundle_path)
        or bundle_binding.get("bundle_sha256") != bundle["bundle_sha256"]
        or manifest.get("firmware") != bundle["firmware"]
        or manifest.get("policy") != bundle["policy"]
        or manifest.get("operator_authority") != bundle["operator_authority"]
        or manifest.get("cx319", {}).get("leg") != bundle["leg"]["leg"]
        or manifest.get("cx319", {}).get("authority") != bundle["authority"]
        or manifest.get("cx319", {}).get("commands") != bundle["commands"]
        or (
            "q1_real_io" in manifest
            and manifest.get("q1_real_io") != bundle.get("q1_real_io")
        )
    ):
        raise ValueError("CX319 G1 run manifest differs from its exact bundle")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--leg", choices=("A", "B"), required=True)
    create.add_argument("--build-manifest", type=Path, required=True)
    create.add_argument("--uf2", type=Path, required=True)
    create.add_argument("--serial-device", required=True)
    create.add_argument("--confirmed-flash-record", type=Path)
    create.add_argument("--output", type=Path, required=True)
    validate = subparsers.add_parser("validate")
    validate.add_argument("bundle", type=Path)
    args = parser.parse_args(argv)
    try:
        if args.command == "create":
            result = create_bundle(
                leg=args.leg,
                build_manifest_path=args.build_manifest,
                uf2_path=args.uf2,
                serial_device=args.serial_device,
                output_path=args.output,
                confirmed_flash_record_path=args.confirmed_flash_record,
            )
        else:
            result = validate_bundle(args.bundle)
    except (
        FileExistsError,
        FileNotFoundError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
        subprocess.SubprocessError,
    ) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
