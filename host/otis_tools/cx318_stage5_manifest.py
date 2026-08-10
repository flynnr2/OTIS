"""Create and validate fail-closed CX318 Stage 5 leg manifests.

The frozen Stage 5 policy is the sole source for the two leg profiles and
their limits.  This tool only creates a manifest; it does not open a serial
device, send a command, or write a DAC.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .run_paths import default_csv_files
from .run_loader import CAPTURE_IN_PROGRESS_FLAG, COMPLETE_MARKER
from .cx318_stage5_runtime_contract import (
    ACTIVE_STATUS_KEYS,
    INHERITED_PREVIEW_BASELINE_PROVENANCE,
    RUNTIME_CONTRACT_ID,
)
from tools.firmware_matrix import configuration_hash, load_matrix


REPO_ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = REPO_ROOT / "profiles/discipline/cx318_stage5_tight_active_v1.json"
FIRMWARE_MATRIX_PATH = REPO_ROOT / "firmware/arduino/firmware_matrix.json"
HOST_TOOL_PATHS = {
    "capture": Path(__file__).with_name("capture_device.py"),
    "supervisor": Path(__file__).with_name("cx318_stage5_supervisor.py"),
    "serial_commands": Path(__file__).with_name("serial_commands.py"),
    "abort_path": Path(__file__).with_name("cx317_abort_path.py"),
    "tight_replay": Path(__file__).with_name("cx318_stage5_tight_replay.py"),
    "rehearsal_analyzer": Path(__file__).with_name(
        "cx318_stage5_rehearsal_analyze.py"
    ),
    "live_analyzer": Path(__file__).with_name("cx318_stage5_live_analyze.py"),
    "bidirectional_gate": Path(__file__).with_name(
        "cx318_stage5_bidirectional_gate.py"
    ),
    "segment_rotation": Path(__file__).with_name("cx318_capture_segment.py"),
    "promotion": Path(__file__).with_name("cx318_stage5_promote.py"),
    "runtime_contract": Path(__file__).with_name(
        "cx318_stage5_runtime_contract.py"
    ),
    "preflight": Path(__file__).with_name("cx318_stage5_preflight.py"),
}

MANIFEST_SCHEMA_VERSION = 2
REHEARSAL_STAGE = "CX318_STAGE5_TIGHT_ACTIVE_REHEARSAL"
LIVE_STAGE = "CX318_STAGE5_TIGHT_ACTIVE_LIVE"
STAGE4_BINDING_TYPE = "cx318_stage4_post_capture_external_binding_v1"
REHEARSAL_SEAL_TYPE = "cx318_stage5_rehearsal_no_write_seal_v1"
LIVE_LEG_SEAL_TYPE = "cx318_stage5_live_leg_seal_v1"


def _utc_now() -> str:
    return (
        datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    )


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_digest(value: dict[str, Any]) -> str:
    return sha256(
        json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode("utf-8")
    ).hexdigest()


def _read_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object: {path}")
    return value


def _is_sha256(value: Any) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(char in "0123456789abcdef" for char in value)


def _binding(path: Path, *, label: str) -> dict[str, str]:
    path = path.resolve()
    if not path.is_file():
        raise ValueError(f"{label} is not a file: {path}")
    return {"path": str(path), "sha256": _sha256_file(path)}


def _require_sealed_run_state(run_root: Path, *, label: str) -> None:
    """Reassert mutable terminal conditions when a historical seal is reused."""

    if not (run_root / COMPLETE_MARKER).is_file():
        raise ValueError(f"{label} COMPLETE marker is unavailable")
    if (run_root / CAPTURE_IN_PROGRESS_FLAG).exists():
        raise ValueError(f"{label} has been reopened after sealing")
    state = _read_object(
        run_root / "reports/capture_device_state.json", f"{label} capture state"
    )
    if (
        state.get("capture_active") is not False
        or state.get("logical_segment_closed") is not True
    ):
        raise ValueError(f"{label} is not an immutable closed capture segment")


def _host_tool_bindings() -> dict[str, dict[str, str]]:
    return {
        name: _binding(path, label=f"Stage 5 host tool {name}")
        for name, path in HOST_TOOL_PATHS.items()
    }


def _policy() -> dict[str, Any]:
    policy = _read_object(POLICY_PATH, "Stage 5 policy")
    if (
        policy.get("policy_id") != "CX318_STAGE5_TIGHT_ACTIVE_FREQUENCY_ONLY_V1"
        or policy.get("status") != "frozen_before_stage5_hardware_or_write"
    ):
        raise ValueError("unexpected frozen Stage 5 policy identity")
    bindings = policy.get("bindings")
    if not isinstance(bindings, dict):
        raise ValueError("Stage 5 policy has no binding map")
    required = {
        "master_prompt",
        "stage5_prompt",
        "selected_frequency_estimator",
        "inherited_frequency_controller_numerics",
        "plant_model",
        "response_policy",
        "selected_relative_phase_estimator",
        "selected_hybrid_preview",
    }
    if not required <= set(bindings):
        raise ValueError("Stage 5 policy binding map is incomplete")
    for name, item in bindings.items():
        if not isinstance(item, dict) or not isinstance(item.get("path"), str) or not _is_sha256(item.get("sha256")):
            raise ValueError(f"Stage 5 policy binding is malformed: {name}")
        target = REPO_ROOT / item["path"]
        if not target.is_file() or _sha256_file(target) != item["sha256"]:
            raise ValueError(f"Stage 5 policy binding is stale: {name}")
    return policy


def _leg(policy: dict[str, Any], leg: str) -> dict[str, Any]:
    if leg not in {"A", "B"}:
        raise ValueError("leg must be A or B")
    legs = policy.get("legs")
    value = legs.get(leg) if isinstance(legs, dict) else None
    if not isinstance(value, dict):
        raise ValueError(f"Stage 5 policy has no leg {leg}")
    expected = (
        ("A", "cx318_stage5_tight_lower", 0xA808, "positive"),
        ("B", "cx318_stage5_tight_upper", 0xA848, "negative"),
    )
    exact = next(item for item in expected if item[0] == leg)
    if (
        value.get("firmware_profile"), value.get("exact_setup_code"), value.get("required_automatic_direction"),
        value.get("maximum_automatic_corrections"), value.get("maximum_cumulative_automatic_movement_codes"),
    ) != (exact[1], exact[2], exact[3], 4, 84):
        raise ValueError(f"Stage 5 policy leg {leg} is not exact")
    return value


def _matrix_profile(profile_id: str) -> dict[str, Any]:
    matrix = _read_object(FIRMWARE_MATRIX_PATH, "firmware matrix")
    profiles = matrix.get("profiles")
    matches = [item for item in profiles if isinstance(item, dict) and item.get("id") == profile_id] if isinstance(profiles, list) else []
    if len(matches) != 1 or not isinstance(matches[0].get("defines"), dict):
        raise ValueError(f"firmware matrix lacks exact Stage 5 profile {profile_id}")
    return matches[0]


def _validate_build(build_manifest_path: Path, uf2_path: Path, profile_id: str) -> dict[str, Any]:
    build_manifest_path = build_manifest_path.resolve()
    uf2_path = uf2_path.resolve()
    build = _read_object(build_manifest_path, "firmware build manifest")
    try:
        provenance = build["provenance"]
        source = provenance["source"]
        configuration = provenance["configuration"]
        artifacts = build["artifacts"]
    except KeyError as exc:
        raise ValueError("firmware build manifest lacks required provenance") from exc
    if (
        not isinstance(source, dict)
        or source.get("state") != "clean"
        or not _is_sha256(source.get("sha256"))
    ):
        raise ValueError("Stage 5 requires a clean-source firmware artifact")
    if not isinstance(configuration, dict) or configuration.get("profile_id") != profile_id:
        raise ValueError("firmware build profile does not match the requested Stage 5 leg")
    matrix_profile = _matrix_profile(profile_id)
    if configuration.get("defines") != matrix_profile["defines"]:
        raise ValueError("firmware build defines differ from the exact Stage 5 profile; accelerated or relaxed limits are forbidden")
    matrix = load_matrix(FIRMWARE_MATRIX_PATH)
    expected_configuration_sha256 = configuration_hash(matrix, matrix_profile)
    if configuration.get("sha256") != expected_configuration_sha256:
        raise ValueError(
            "firmware build configuration hash differs from the exact current "
            "Stage 5 matrix/configuration input"
        )
    if not uf2_path.is_file():
        raise ValueError(f"UF2 is not a file: {uf2_path}")
    if not isinstance(artifacts, list):
        raise ValueError("firmware build manifest artifact inventory is malformed")
    matches = [item for item in artifacts if isinstance(item, dict) and item.get("name") == uf2_path.name]
    if len(matches) != 1:
        raise ValueError("firmware build manifest does not bind exactly one supplied UF2")
    artifact = matches[0]
    if artifact.get("sha256") != _sha256_file(uf2_path) or artifact.get("size_bytes") != uf2_path.stat().st_size:
        raise ValueError("supplied UF2 differs from the firmware build manifest")
    return {
        "path": str(build_manifest_path),
        "sha256": _sha256_file(build_manifest_path),
        "profile_id": profile_id,
        "configuration_sha256": configuration["sha256"],
        "source_sha256": source.get("sha256"),
        "source_state": source["state"],
        "uf2": {"path": str(uf2_path), "sha256": artifact["sha256"], "size_bytes": artifact["size_bytes"]},
    }


def _validate_stage4_seal(path: Path) -> dict[str, Any]:
    path = path.resolve()
    seal = _read_object(path, "Stage 4 seal")
    claimed = seal.get("binding_sha256")
    unsigned = {key: value for key, value in seal.items() if key != "binding_sha256"}
    run = seal.get("run")
    analysis = seal.get("live_analysis")
    snapshot = seal.get("evidence_snapshot")
    if (
        seal.get("binding_type") != STAGE4_BINDING_TYPE
        or not _is_sha256(claimed)
        or claimed != _canonical_digest(unsigned)
        or not isinstance(run, dict)
        or not isinstance(analysis, dict)
        or not isinstance(snapshot, dict)
        or analysis.get("status") != "passed"
        or not _is_sha256(run.get("manifest_sha256"))
        or not _is_sha256(snapshot.get("sha256"))
        or not _is_sha256(snapshot.get("snapshot_digest"))
    ):
        raise ValueError("Stage 4 seal is not a valid sealed pass artifact")
    return {**_binding(path, label="Stage 4 seal"), "binding_sha256": claimed}


def _validate_rehearsal_seal(path: Path, *, leg: str, firmware: dict[str, Any]) -> dict[str, Any]:
    path = path.resolve()
    seal = _read_object(path, "Stage 5 rehearsal seal")
    claimed = seal.get("seal_sha256")
    unsigned = {key: value for key, value in seal.items() if key != "seal_sha256"}
    rehearsal = seal.get("rehearsal")
    checks = seal.get("checks")
    run = seal.get("run")
    evidence = seal.get("evidence_snapshot")
    source_hashes = seal.get("source_artifacts_sha256")
    exact = (
        seal.get("seal_type") == REHEARSAL_SEAL_TYPE
        and seal.get("tool") == "cx318_stage5_rehearsal_analyze_v1"
        and seal.get("status") == "passed"
        and seal.get("leg") == leg
        and seal.get("profile_id") == firmware["profile_id"]
        and isinstance(rehearsal, dict)
        and rehearsal.get("capture_duration_s", -1) >= 2700
        and rehearsal.get("selected_600s_estimates", 0) >= 1
        and rehearsal.get("setup_writes") == 0
        and rehearsal.get("dac_writes") == 0
        and rehearsal.get("automatic_writes") == 0
        and rehearsal.get("accelerated_or_relaxed_limits") is False
        and seal.get("build_manifest_sha256") == firmware["sha256"]
        and seal.get("uf2_sha256") == firmware["uf2"]["sha256"]
        and isinstance(checks, dict)
        and bool(checks)
        and all(value is True for value in checks.values())
        and isinstance(run, dict)
        and _is_sha256(run.get("manifest_sha256"))
        and isinstance(evidence, dict)
        and _is_sha256(evidence.get("sha256"))
        and _is_sha256(evidence.get("snapshot_digest"))
        and isinstance(source_hashes, dict)
        and bool(source_hashes)
        and all(
            isinstance(relative, str)
            and relative
            and _is_sha256(digest)
            for relative, digest in source_hashes.items()
        )
        and _is_sha256(claimed)
        and claimed == _canonical_digest(unsigned)
    )
    if not exact:
        raise ValueError("Stage 5 live requires a passed exact-profile 2700-second no-write rehearsal seal")

    # A valid seal binds the historical bytes; live-manifest creation also
    # proves those bytes still exist unchanged.  Otherwise a preserved seal
    # could be paired with a subsequently modified rehearsal directory.
    rehearsal_root_value = run.get("path")
    if not isinstance(rehearsal_root_value, str):
        raise ValueError("Stage 5 rehearsal seal lacks its source run path")
    rehearsal_root = Path(rehearsal_root_value).resolve()
    if not rehearsal_root.is_dir():
        raise ValueError("Stage 5 rehearsal source run is unavailable")
    _require_sealed_run_state(rehearsal_root, label="Stage 5 rehearsal")
    for relative, expected_sha256 in source_hashes.items():
        relative_path = Path(relative)
        source_path = (rehearsal_root / relative_path).resolve()
        try:
            source_path.relative_to(rehearsal_root)
        except ValueError:
            raise ValueError(
                "Stage 5 rehearsal seal source path escapes its run directory"
            ) from None
        if relative_path.is_absolute() or not source_path.is_file():
            raise ValueError("Stage 5 rehearsal seal source artifact is unavailable")
        if _sha256_file(source_path) != expected_sha256:
            raise ValueError("Stage 5 rehearsal source artifact changed after sealing")
    manifest_source = rehearsal_root / "run_manifest.json"
    if (
        not manifest_source.is_file()
        or _sha256_file(manifest_source) != run["manifest_sha256"]
    ):
        raise ValueError("Stage 5 rehearsal manifest changed after sealing")
    evidence_path_value = evidence.get("path")
    if not isinstance(evidence_path_value, str):
        raise ValueError("Stage 5 rehearsal seal lacks its evidence path")
    evidence_path = Path(evidence_path_value).resolve()
    try:
        evidence_path.relative_to(rehearsal_root)
    except ValueError:
        raise ValueError(
            "Stage 5 rehearsal evidence path escapes its run directory"
        ) from None
    if not evidence_path.is_file() or _sha256_file(evidence_path) != evidence["sha256"]:
        raise ValueError("Stage 5 rehearsal evidence snapshot changed after sealing")
    return {**_binding(path, label="Stage 5 rehearsal seal"), "seal_sha256": claimed}


def _validate_live_leg_seal(path: Path, *, expected_leg: str) -> dict[str, Any]:
    path = path.resolve()
    seal = _read_object(path, "Stage 5 live leg seal")
    claimed = seal.get("seal_sha256")
    unsigned = {key: value for key, value in seal.items() if key != "seal_sha256"}
    run = seal.get("run")
    source_hashes = seal.get("source_artifacts_sha256")
    transition_source = seal.get("transition_source")
    policy = _policy()
    leg_policy = _leg(policy, expected_leg)
    exact = (
        seal.get("seal_type") == LIVE_LEG_SEAL_TYPE
        and seal.get("tool") == "cx318_stage5_live_analyze_v1"
        and seal.get("tool_sha256") == _sha256_file(HOST_TOOL_PATHS["live_analyzer"])
        and seal.get("status") == "passed"
        and seal.get("failure_class") == "none"
        and seal.get("leg") == expected_leg
        and seal.get("profile_id") == leg_policy["firmware_profile"]
        and seal.get("policy_sha256") == _sha256_file(POLICY_PATH)
        and isinstance(seal.get("checks"), dict)
        and bool(seal["checks"])
        and all(value is True for value in seal["checks"].values())
        and isinstance(run, dict)
        and isinstance(run.get("path"), str)
        and _is_sha256(run.get("manifest_sha256"))
        and isinstance(source_hashes, dict)
        and bool(source_hashes)
        and all(
            isinstance(relative, str) and relative and _is_sha256(digest)
            for relative, digest in source_hashes.items()
        )
        and isinstance(transition_source, dict)
        and isinstance(transition_source.get("root"), str)
        and type(transition_source.get("owner_pid")) is int
        and type(transition_source.get("transport_generation")) is int
        and _is_sha256(transition_source.get("manifest_sha256"))
        and isinstance(transition_source.get("checks"), dict)
        and bool(transition_source["checks"])
        and all(value is True for value in transition_source["checks"].values())
        and isinstance(transition_source.get("source_artifacts_sha256"), dict)
        and bool(transition_source["source_artifacts_sha256"])
        and all(
            isinstance(relative, str) and relative and _is_sha256(digest)
            for relative, digest in transition_source[
                "source_artifacts_sha256"
            ].items()
        )
        and _is_sha256(claimed)
        and claimed == _canonical_digest(unsigned)
    )
    if not exact:
        raise ValueError(f"Stage 5 leg {expected_leg} seal is not a canonical passed seal")
    run_root = Path(run["path"]).resolve()
    if not run_root.is_dir():
        raise ValueError("Stage 5 live leg source run is unavailable")
    _require_sealed_run_state(run_root, label=f"Stage 5 leg {expected_leg}")
    for relative, expected_sha256 in source_hashes.items():
        relative_path = Path(relative)
        source_path = (run_root / relative_path).resolve()
        try:
            source_path.relative_to(run_root)
        except ValueError:
            raise ValueError("Stage 5 live seal source path escapes its run directory") from None
        if relative_path.is_absolute() or not source_path.is_file():
            raise ValueError("Stage 5 live seal source artifact is unavailable")
        if _sha256_file(source_path) != expected_sha256:
            raise ValueError("Stage 5 live source artifact changed after sealing")
    manifest_path = run_root / "run_manifest.json"
    if not manifest_path.is_file() or _sha256_file(manifest_path) != run["manifest_sha256"]:
        raise ValueError("Stage 5 live manifest changed after sealing")
    transition_root = Path(transition_source["root"]).resolve()
    if not transition_root.is_dir():
        raise ValueError("Stage 5 transition source is unavailable")
    for relative, expected_sha256 in transition_source[
        "source_artifacts_sha256"
    ].items():
        relative_path = Path(relative)
        source_path = (transition_root / relative_path).resolve()
        try:
            source_path.relative_to(transition_root)
        except ValueError:
            raise ValueError(
                "Stage 5 transition seal source path escapes its run directory"
            ) from None
        if relative_path.is_absolute() or not source_path.is_file():
            raise ValueError("Stage 5 transition source artifact is unavailable")
        if _sha256_file(source_path) != expected_sha256:
            raise ValueError("Stage 5 transition source artifact changed after sealing")
    if (
        transition_source["source_artifacts_sha256"].get("run_manifest.json")
        != transition_source["manifest_sha256"]
    ):
        raise ValueError("Stage 5 transition manifest binding differs")
    manifest = validate_manifest(manifest_path)
    if (
        manifest.get("stage") != LIVE_STAGE
        or manifest.get("stage5", {}).get("leg") != expected_leg
        or manifest.get("firmware", {}).get("sha256")
        != seal.get("build_manifest_sha256")
        or manifest.get("firmware", {}).get("uf2", {}).get("sha256")
        != seal.get("uf2_sha256")
        or manifest.get("stage4_seal", {}).get("binding_sha256")
        != seal.get("stage4_binding_sha256")
        or manifest.get("stage5", {}).get("rehearsal_seal", {}).get(
            "seal_sha256"
        )
        != seal.get("rehearsal_seal_sha256")
        or seal.get("required_direction")
        != leg_policy["required_automatic_direction"]
    ):
        raise ValueError("Stage 5 live seal differs from its source manifest")
    return {**_binding(path, label=f"Stage 5 leg {expected_leg} seal"), "seal_sha256": claimed}


def _required_files() -> list[dict[str, Any]]:
    required = {
        "pps_snapshots_v1", "dac_steps_v1", "environment_v1", "estimates_v2", "control_previews_v1", "active_transactions_v1",
        "relative_phase_observations_v1", "phase_estimator_outputs_v1", "hybrid_preview_decisions_v1",
        "tight_deadband_decisions_v1",
    }
    files = default_csv_files()
    for entry in files:
        if entry["contract"] in required:
            entry.pop("optional", None)
    return files


def _assert_clean_run_dir(run_dir: Path) -> None:
    if run_dir.exists() and (not run_dir.is_dir() or any(run_dir.iterdir())):
        raise FileExistsError(f"Stage 5 run directory must be new or empty: {run_dir}")


def _write_json_new_atomic(path: Path, value: dict[str, Any]) -> None:
    """Publish JSON atomically without replacing any existing evidence."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False) as handle:
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    try:
        os.link(temporary, path)
    except FileExistsError:
        raise FileExistsError(f"refusing to overwrite existing manifest: {path}") from None
    finally:
        temporary.unlink(missing_ok=True)


def create_manifest(
    *, mode: str, leg: str, run_dir: Path, build_manifest_path: Path, uf2_path: Path,
    stage4_seal_path: Path, serial_device: str, rehearsal_seal_path: Path | None = None,
    leg_a_seal_path: Path | None = None, baud: int = 115200,
) -> Path:
    """Create one exact Stage 5 rehearsal or live manifest.

    Live creation requires an explicit seal made by the Stage 5 rehearsal
    analysis/sealing step.  The seal format is deliberately small and is
    validated here so its file and internal digest are both bound.
    """
    if mode not in {"rehearsal", "live"}:
        raise ValueError("mode must be rehearsal or live")
    if not serial_device:
        raise ValueError("serial_device is required")
    if baud != 115200:
        raise ValueError("Stage 5 baud must be exactly 115200")
    run_dir = run_dir.resolve()
    _assert_clean_run_dir(run_dir)
    policy = _policy()
    leg_policy = _leg(policy, leg)
    firmware = _validate_build(build_manifest_path, uf2_path, leg_policy["firmware_profile"])
    stage4_seal = _validate_stage4_seal(stage4_seal_path)
    rehearsal_seal = None
    leg_a_seal = None
    if mode == "live":
        if rehearsal_seal_path is None:
            raise ValueError("live Stage 5 manifest requires --rehearsal-seal")
        rehearsal_seal = _validate_rehearsal_seal(rehearsal_seal_path, leg=leg, firmware=firmware)
    elif rehearsal_seal_path is not None:
        raise ValueError("a rehearsal manifest cannot bind a rehearsal seal")
    if mode == "live" and leg == "B":
        if leg_a_seal_path is None:
            raise ValueError("live Stage 5 leg B requires --leg-a-seal")
        leg_a_seal = _validate_live_leg_seal(leg_a_seal_path, expected_leg="A")
    elif leg_a_seal_path is not None:
        raise ValueError("only live Stage 5 leg B may bind a leg A seal")

    controller = policy["frequency_controller"]
    finite = policy["finite_runtime"]
    rehearsal = policy["same_profile_rehearsal"]
    files = _required_files()
    now = _utc_now()
    no_write = mode == "rehearsal"
    stage5 = {
        "mode": mode,
        "leg": leg,
        "firmware_profile": leg_policy["firmware_profile"],
        "run_binding_tag": leg_policy["run_binding_tag"],
        "runtime_contract": {
            "id": RUNTIME_CONTRACT_ID,
            "active_status_keys": list(ACTIVE_STATUS_KEYS),
            "missing_status_is_failure": True,
            "startup_grace_s": 30,
        },
        "inherited_preview_baseline": {
            "code": rehearsal["reconfirmed_pre_setup_code"],
            "code_hex": rehearsal["reconfirmed_pre_setup_code_hex"],
            "dac_epoch": 0,
            "provenance": INHERITED_PREVIEW_BASELINE_PROVENANCE,
            "physical_dac_confirmation": False,
        },
        "planned_live_stimulus": {
            "code": leg_policy["exact_setup_code"], "code_hex": leg_policy["exact_setup_code_hex"],
            "maximum_writes": 0 if no_write else 1, "authorized": not no_write,
        },
        "automatic_frequency_control": {
            "authorized": not no_write, "required_direction": leg_policy["required_automatic_direction"],
            "maximum_corrections": 0 if no_write else leg_policy["maximum_automatic_corrections"],
            "maximum_cumulative_movement_codes": 0 if no_write else leg_policy["maximum_cumulative_automatic_movement_codes"],
            "maximum_step_codes": controller["maximum_automatic_step_codes"],
            "minimum_applied_correction_cadence_s": controller["minimum_applied_correction_cadence_s"],
            "settling_exclusion_s": controller["settling_exclusion_s"],
            "fresh_support_after_settling_s": controller["fresh_support_after_settling_s"],
        },
        "qualification": {
            "deadline_s": finite["qualification_deadline_s"],
            "maximum_qualified_duration_s": finite["maximum_qualified_duration_s"],
            "no_extension_after_finite_endpoint": finite["no_extension_after_finite_endpoint"],
        },
        "phase_and_hybrid": dict(policy["phase_and_hybrid_authority"]),
    }
    if no_write:
        stage5["rehearsal"] = {
            "same_build_profile_and_limits_required": True,
            "accelerated_or_relaxed_profile_forbidden": True,
            "minimum_capture_duration_s": rehearsal["minimum_capture_duration_s"],
            "minimum_selected_600s_estimates": rehearsal["minimum_selected_600s_estimates"],
            "setup_writes_forbidden": True,
            "dac_writes_forbidden": True,
            "automatic_writes_forbidden": True,
        }
    else:
        stage5["rehearsal_seal"] = rehearsal_seal
        if leg_a_seal is not None:
            stage5["leg_a_seal"] = leg_a_seal

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "template": False,
        "run_id": run_dir.name,
        "created_utc": now,
        "started_at_utc": now,
        "stage": REHEARSAL_STAGE if no_write else LIVE_STAGE,
        "board": "arduino_nano_rp2040_connect",
        "actionable": not no_write,
        "actuation_authorized": not no_write,
        "firmware": firmware,
        "policy": {"path": str(POLICY_PATH), "sha256": _sha256_file(POLICY_PATH), "bindings": policy["bindings"]},
        "stage4_seal": stage4_seal,
        "host": {
            "capture_tool": "host.otis_tools.capture_device", "supervisor_tool": "host.otis_tools.cx318_stage5_supervisor",
            "serial_device": serial_device, "baud": baud, "sole_serial_owner": True,
            "independent_abort_fifo_required": True,
            "same_owner_segment_rotation_required": True,
            "segment_rotation_protocol": "otis_same_owner_logical_segment_rotation_v1",
            "tool_bindings": _host_tool_bindings(),
        },
        "stage5": stage5,
        "domains": [{"name": "rp2040_timer0", "nominal_hz": 16_000_000}, {"name": "h0_tcxo_16mhz", "nominal_hz": 10_000_000}],
        "channels": [{"channel_id": 1, "role": "authoritative_pps_reference", "record_family": "raw_events_v1"}, {"channel_id": 2, "role": "pps_gated_oscillator_count", "record_family": "count_observations_v1"}],
        "contracts": {entry["contract"]: 2 if entry["contract"] == "estimates_v2" else 1 for entry in files},
        "files": files,
        "expected_artifacts": [
            *[entry["path"] for entry in files if not entry.get("optional")],
            "raw/serial.log",
            "reports/capture_device_state.json",
            "reports/capture_segment_closure_v1.json",
            "reports/cx317_active_supervisor_state.json",
            "reports/cx317_active_supervisor_events.jsonl",
        ],
    }
    path = run_dir / "run_manifest.json"
    _write_json_new_atomic(path, manifest)
    return path


def validate_manifest(path: Path) -> dict[str, Any]:
    """Validate a created manifest and all currently readable external bindings."""
    path = path.resolve()
    manifest = _read_object(path, "Stage 5 manifest")
    mode_by_stage = {REHEARSAL_STAGE: "rehearsal", LIVE_STAGE: "live"}
    mode = mode_by_stage.get(manifest.get("stage"))
    stage5 = manifest.get("stage5")
    if manifest.get("schema_version") != MANIFEST_SCHEMA_VERSION or not isinstance(stage5, dict) or mode != stage5.get("mode"):
        raise ValueError("unsupported or malformed Stage 5 manifest")
    policy = _policy()
    leg = stage5.get("leg")
    leg_policy = _leg(policy, leg)
    firmware_value = manifest.get("firmware")
    if not isinstance(firmware_value, dict):
        raise ValueError("Stage 5 manifest lacks firmware binding")
    uf2_binding = firmware_value.get("uf2")
    if (
        not isinstance(firmware_value.get("path"), str)
        or not isinstance(uf2_binding, dict)
        or not isinstance(uf2_binding.get("path"), str)
    ):
        raise ValueError("Stage 5 manifest firmware paths are malformed")
    expected_firmware = _validate_build(
        Path(firmware_value["path"]), Path(uf2_binding["path"]), leg_policy["firmware_profile"]
    )
    if firmware_value != expected_firmware:
        raise ValueError("Stage 5 manifest firmware binding is stale or differs from its exact build")
    policy_value = manifest.get("policy")
    expected_policy = {"path": str(POLICY_PATH), "sha256": _sha256_file(POLICY_PATH), "bindings": policy["bindings"]}
    if policy_value != expected_policy:
        raise ValueError("Stage 5 manifest policy binding is stale")
    host = manifest.get("host")
    if (
        not isinstance(host, dict)
        or host.get("capture_tool") != "host.otis_tools.capture_device"
        or host.get("supervisor_tool")
        != "host.otis_tools.cx318_stage5_supervisor"
        or host.get("sole_serial_owner") is not True
        or host.get("independent_abort_fifo_required") is not True
        or host.get("same_owner_segment_rotation_required") is not True
        or host.get("segment_rotation_protocol")
        != "otis_same_owner_logical_segment_rotation_v1"
        or host.get("tool_bindings") != _host_tool_bindings()
    ):
        raise ValueError("Stage 5 manifest host tool binding is stale")
    stage4 = manifest.get("stage4_seal")
    if not isinstance(stage4, dict) or stage4 != _validate_stage4_seal(Path(stage4.get("path", ""))):
        raise ValueError("Stage 5 manifest Stage 4 seal binding is stale")
    setup = stage5.get("planned_live_stimulus", {})
    automatic = stage5.get("automatic_frequency_control", {})
    controller = policy["frequency_controller"]
    finite = policy["finite_runtime"]
    pre_setup = stage5.get("inherited_preview_baseline", {})
    runtime_contract = stage5.get("runtime_contract", {})
    if (
        stage5.get("firmware_profile") != leg_policy["firmware_profile"]
        or pre_setup
        != {
            "code": 0xA828,
            "code_hex": "0xA828",
            "dac_epoch": 0,
            "provenance": INHERITED_PREVIEW_BASELINE_PROVENANCE,
            "physical_dac_confirmation": False,
        }
        or runtime_contract
        != {
            "id": RUNTIME_CONTRACT_ID,
            "active_status_keys": list(ACTIVE_STATUS_KEYS),
            "missing_status_is_failure": True,
            "startup_grace_s": 30,
        }
        or setup.get("code") != leg_policy["exact_setup_code"]
        or setup.get("code_hex") != leg_policy["exact_setup_code_hex"]
        or automatic.get("required_direction") != leg_policy["required_automatic_direction"]
        or automatic.get("maximum_step_codes") != 21
        or automatic.get("minimum_applied_correction_cadence_s") != 1800
        or automatic.get("settling_exclusion_s") != 900
        or automatic.get("fresh_support_after_settling_s") != 600
        or stage5.get("qualification", {}).get("deadline_s") != 5400
        or stage5.get("qualification", {}).get("maximum_qualified_duration_s") != 14400
        or stage5.get("phase_and_hybrid")
        != policy["phase_and_hybrid_authority"]
        or controller["maximum_automatic_step_codes"] != 21
        or finite["qualification_deadline_s"] != 5400
        or finite["maximum_qualified_duration_s"] != 14400
    ):
        raise ValueError("Stage 5 manifest limit or timing is not exact")
    if mode == "rehearsal":
        if (
            setup.get("authorized") is not False or setup.get("maximum_writes") != 0
            or automatic.get("authorized") is not False or automatic.get("maximum_corrections") != 0
            or automatic.get("maximum_cumulative_movement_codes") != 0
            or not isinstance(stage5.get("rehearsal"), dict)
            or stage5["rehearsal"].get("minimum_capture_duration_s") != 2700
            or stage5["rehearsal"].get("setup_writes_forbidden") is not True
            or stage5["rehearsal"].get("dac_writes_forbidden") is not True
            or stage5["rehearsal"].get("automatic_writes_forbidden") is not True
            or stage5["rehearsal"].get("accelerated_or_relaxed_profile_forbidden") is not True
        ):
            raise ValueError("Stage 5 rehearsal has write authority or an accelerated duration")
    else:
        if (
            setup.get("authorized") is not True or setup.get("maximum_writes") != 1
            or automatic.get("authorized") is not True
            or automatic.get("maximum_corrections") != 4
            or automatic.get("maximum_cumulative_movement_codes") != 84
        ):
            raise ValueError("Stage 5 live authority is not exact")
        rehearsal_seal = stage5.get("rehearsal_seal")
        if not isinstance(rehearsal_seal, dict) or not isinstance(rehearsal_seal.get("path"), str):
            raise ValueError("Stage 5 rehearsal seal binding is malformed")
        if rehearsal_seal != _validate_rehearsal_seal(
            Path(rehearsal_seal["path"]), leg=leg, firmware=expected_firmware
        ):
            raise ValueError("Stage 5 rehearsal seal binding is stale")
        leg_a_seal = stage5.get("leg_a_seal")
        if leg == "B":
            if not isinstance(leg_a_seal, dict) or not isinstance(leg_a_seal.get("path"), str):
                raise ValueError("Stage 5 leg B lacks its required passed leg A seal")
            if leg_a_seal != _validate_live_leg_seal(
                Path(leg_a_seal["path"]), expected_leg="A"
            ):
                raise ValueError("Stage 5 leg B leg A seal binding is stale")
        elif leg_a_seal is not None:
            raise ValueError("Stage 5 leg A must not carry a prior-leg seal")
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create", help="create a new exact manifest")
    create.add_argument("--mode", choices=("rehearsal", "live"), required=True)
    create.add_argument("--leg", choices=("A", "B"), required=True)
    create.add_argument("--run-dir", type=Path, required=True)
    create.add_argument("--build-manifest", type=Path, required=True)
    create.add_argument("--uf2", type=Path, required=True)
    create.add_argument("--stage4-seal", type=Path, required=True)
    create.add_argument("--rehearsal-seal", type=Path)
    create.add_argument("--leg-a-seal", type=Path)
    create.add_argument("--serial-device", required=True)
    create.add_argument("--baud", type=int, default=115200)
    validate = commands.add_parser("validate", help="validate an existing manifest and bindings")
    validate.add_argument("manifest", type=Path)
    args = parser.parse_args(argv)
    if args.command == "validate":
        validate_manifest(args.manifest)
        print(args.manifest.resolve())
    else:
        print(create_manifest(
            mode=args.mode, leg=args.leg, run_dir=args.run_dir, build_manifest_path=args.build_manifest,
            uf2_path=args.uf2, stage4_seal_path=args.stage4_seal, rehearsal_seal_path=args.rehearsal_seal,
            leg_a_seal_path=args.leg_a_seal,
            serial_device=args.serial_device, baud=args.baud,
        ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
