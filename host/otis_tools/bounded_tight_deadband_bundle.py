"""Create and validate a non-authorizing bounded-control proposal bundle."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import tempfile
from typing import Any

from .no_write_qualification_analyze import _canonical_sha256
from .no_write_qualification_bundle import (
    POLICY_PATH,
    PROGRAMME_ID,
    _git_identity,
    validate_frozen_bundle,
    validate_run_manifest,
)
from .bounded_tight_deadband_outcome_contract import (
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
from .bounded_tight_deadband_prewrite_contract import (
    FRESH_HOST_ATTACH_MAXIMUM_UPTIME_S,
    RAW_PPS_QUALIFICATION_DEADLINE_S,
    TELEMETRY_BASELINE_STABLE_OBSERVATIONS,
)
from .no_write_prewrite_readiness_contract import (
    RUNTIME_CONTRACT_ID as NO_WRITE_RUNTIME_CONTRACT_ID,
)
from .evidence_index import package_identity
from .programme_status import (
    OFFLINE_PREPARATION,
    load_programme_status,
    require_programme_operation_allowed,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
TOOL_ID = "cx319_g2_proposal_bundle_v1"
BUNDLE_ID = "cx319_g2_leg_a_proposal_bundle_v1"
NO_WRITE_ANALYSIS = Path("reports/cx319_g1_analysis_v1.json")
NO_WRITE_SEAL = Path("reports/cx319_g1_rehearsal_seal_v1.json")
HOST_TOOL_PATHS = {
    "bundle": Path(__file__),
    "capture": Path(__file__).with_name("capture_device.py"),
    "serial_commands": Path(__file__).with_name("serial_commands.py"),
    "abort_path": Path(__file__).with_name("cx317_abort_path.py"),
    "segment_rotation": Path(__file__).with_name("capture_segment_rotation.py"),
    "supervisor": Path(__file__).with_name("bounded_tight_deadband_supervisor.py"),
    "runtime_contract": Path(__file__).with_name(
        "bounded_tight_deadband_prewrite_contract.py"
    ),
    "host_attach_contract": Path(__file__).with_name(
        "host_attach_health_contract.py"
    ),
    "outcome_contract": Path(__file__).with_name("bounded_tight_deadband_outcome_contract.py"),
    "preflight": Path(__file__).with_name("bounded_tight_deadband_preflight.py"),
    "operational_rehearsal": Path(__file__).with_name(
        "bounded_tight_deadband_operational_rehearsal.py"
    ),
    "analyzer": Path(__file__).with_name("bounded_tight_deadband_rehearsal_analyze.py"),
    "live_activation": Path(__file__).with_name("bounded_tight_deadband_activation.py"),
    "live_runner": Path(__file__).with_name("bounded_tight_deadband_run.py"),
    "live_analyzer": Path(__file__).with_name("bounded_tight_deadband_live_analyze.py"),
    "evidence_snapshot": Path(__file__).with_name("evidence.py"),
    "evidence_index": Path(__file__).with_name("evidence_index.py"),
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


def _read(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read {label}: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _binding(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    if not resolved.is_file():
        raise ValueError(f"bound host tool is unavailable: {resolved}")
    return {
        "path": str(resolved),
        "sha256": _sha256_file(resolved),
        "size_bytes": resolved.stat().st_size,
    }


def _atomic_new(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f"refusing to overwrite G2 proposal: {path}")
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


def validate_no_write_qualification_pass(run_dir: Path) -> dict[str, Any]:
    run_dir = run_dir.resolve()
    manifest = validate_run_manifest(run_dir / "run_manifest.json")
    if manifest.get("cx319", {}).get("leg") != "A":
        raise ValueError("G2 requires a passed G1 Leg A source")
    if (
        manifest.get("cx319", {}).get("runtime_contract", {}).get("id")
        != NO_WRITE_RUNTIME_CONTRACT_ID
    ):
        raise ValueError("G2 requires the current GNSS-bearing G1 contract")
    analysis_path = run_dir / NO_WRITE_ANALYSIS
    seal_path = run_dir / NO_WRITE_SEAL
    analysis = _read(analysis_path, "G1 analysis")
    seal = _read(seal_path, "G1 seal")
    unsigned_seal = {key: value for key, value in seal.items() if key != "seal_sha256"}
    if (
        analysis.get("status") != "pass"
        or not isinstance(analysis.get("checks"), dict)
        or not analysis["checks"]
        or not all(value is True for value in analysis["checks"].values())
        or seal.get("status") != "pass"
        or seal.get("leg") != "A"
        or seal.get("profile_id") != "cx319_tight_lower"
        or seal.get("bundle_sha256") != manifest["bundle"]["bundle_sha256"]
        or seal.get("seal_sha256") != _canonical_sha256(unsigned_seal)
        or seal.get("analysis", {}).get("sha256") != _sha256_file(analysis_path)
        or seal.get("dac_value_writes") != 0
        or seal.get("control_arms") != 0
    ):
        raise ValueError("G1 source is not a canonical no-write pass")
    status = load_programme_status()["programmes"][PROGRAMME_ID]
    completed = status.get("completed_g1_evidence", {})
    content = package_identity(run_dir)["content_sha256"]
    if (
        completed.get("run_id") != run_dir.name
        or completed.get("bundle_sha256") != seal["bundle_sha256"]
        or completed.get("seal_sha256") != seal["seal_sha256"]
        or completed.get("evidence_content_sha256") != content
    ):
        raise ValueError("G1 programme status or registered content binding differs")
    frozen_bundle_path = Path(manifest["bundle"]["path"])
    frozen_bundle = validate_frozen_bundle(frozen_bundle_path)
    return {
        "run_id": run_dir.name,
        "run_dir": str(run_dir),
        "run_manifest_sha256": _sha256_file(run_dir / "run_manifest.json"),
        "analysis_sha256": analysis["analysis_sha256"],
        "analysis_file_sha256": _sha256_file(analysis_path),
        "seal_sha256": seal["seal_sha256"],
        "seal_file_sha256": _sha256_file(seal_path),
        "evidence_content_sha256": content,
        "bundle_sha256": seal["bundle_sha256"],
        "firmware": frozen_bundle["firmware"],
        "policy": frozen_bundle["policy"],
    }


def create_proposal(
    *, no_write_run_dir: Path, output_path: Path
) -> dict[str, Any]:
    require_programme_operation_allowed(PROGRAMME_ID, OFFLINE_PREPARATION)
    commit, state = _git_identity()
    if state != "clean":
        raise ValueError("G2 proposal bundle requires a clean repository")
    g1 = validate_no_write_qualification_pass(no_write_run_dir)
    if g1["policy"]["sha256"] != _sha256_file(POLICY_PATH):
        raise ValueError("G1 policy differs from the current G2 policy")
    host_tools = {name: _binding(path) for name, path in HOST_TOOL_PATHS.items()}
    unsigned: dict[str, Any] = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "bundle_id": BUNDLE_ID,
        "created_utc": _utc_now(),
        "source_revision": commit,
        "source_state": state,
        "programme_id": PROGRAMME_ID,
        "gate": "G2",
        "leg": "A",
        "status": "proposed_not_authorized",
        "authority": {
            "effective": False,
            "physical_execution": False,
            "firmware_flash": False,
            "serial_open": False,
            "setup_stimulus": False,
            "control_arm": False,
            "automatic_correction": False,
            "dac_value_write": False,
            "phase_or_hybrid_actionable": False,
            "required_future_operation": "g2_live_leg",
            "explicit_operator_transition_required": True,
        },
        "g1_pass": g1,
        "firmware": g1["firmware"],
        "policy": g1["policy"],
        "host_tools": host_tools,
        "leg_spec": {
            "profile_id": "cx319_tight_lower",
            "run_binding_tag": 3195001,
            "run_identity": "cx319_tight_lower:3195001",
            "setup_code": SETUP_CODE,
            "setup_code_hex": "0xA808",
            "required_automatic_direction": "positive",
        },
        "intended_live_envelope": {
            "setup_writes": 1,
            "automatic_corrections": MAXIMUM_CORRECTIONS,
            "maximum_step_codes": MAXIMUM_STEP_CODES,
            "maximum_cumulative_codes": MAXIMUM_CUMULATIVE_CODES,
            "minimum_code": MINIMUM_CODE,
            "maximum_code": MAXIMUM_CODE,
            "minimum_applied_cadence_s": MINIMUM_CADENCE_S,
            "settling_exclusion_s": 900,
            "fresh_support_s": 600,
            "qualification_deadline_s": QUALIFICATION_DEADLINE_S,
            "maximum_qualified_duration_s": MAXIMUM_QUALIFIED_DURATION_S,
            "one_request_outstanding": True,
            "automatic_retry": False,
            "automatic_restore": False,
        },
        "command_envelope": {
            "normal_exact": [
                "CONFIG?",
                "DAC?",
                "FC0?",
                "ACTIVE SNAPSHOT <post_attach_nonce>",
                "ACTIVE LEASE <nonzero_uint32>",
                "ACTIVE SETUP <authorization> <generation> <nonce> <expiry> <session> 0xA808 1 <configuration_sha256> exactly once",
                "ACTIVE ARM <sequence> <nonce> <expiry>",
                "ACTIVE EVIDENCE <request_sequence> <phase_1_to_4>",
            ],
            "emergency_exact": ["ACTIVE ABORT"],
            "normal_batch_limit": 1,
            "normal_command_max_age_s": 2.0,
            "write_timeout_s": 1.0,
        },
        "readiness_gates": {
            "structural_preflight_required": True,
            "accelerated_operational_path_rehearsal_required": True,
            "fresh_host_attach_maximum_uptime_s": (
                FRESH_HOST_ATTACH_MAXIMUM_UPTIME_S
            ),
            "gnss_pps_qualification_deadline_s": (
                RAW_PPS_QUALIFICATION_DEADLINE_S
            ),
            "continuous_drain_from_host_attachment_through_physical_close": True,
            "ordinary_telemetry_attach_baseline_stable_observations": (
                TELEMETRY_BASELINE_STABLE_OBSERVATIONS
            ),
            "post_attach_ordinary_telemetry_increment_forbidden": True,
            "evidence_capture_preview_partition_and_control_gates_absolute": True,
            "gnss_service_precedes_serial_transport_early_return": True,
            "gnss_prewrite_identity_epoch": 1,
            "gnss_identity_and_control_eligibility_required_before_setup": True,
            "physical_qualification_requires_separate_authority": True,
            "analyzer_seal_and_registration_required": True,
            "physical_runner_and_live_analyzer_bound": True,
        },
    }
    value = {**unsigned, "bundle_sha256": canonical_sha256(unsigned)}
    _atomic_new(output_path.resolve(), value)
    return value


def validate_frozen_proposal(path: Path) -> dict[str, Any]:
    path = path.resolve()
    value = _read(path, "G2 proposal bundle")
    claimed = value.get("bundle_sha256")
    unsigned = {key: item for key, item in value.items() if key != "bundle_sha256"}
    if (
        value.get("schema_version") != 1
        or value.get("tool") != TOOL_ID
        or value.get("bundle_id") != BUNDLE_ID
        or value.get("status") != "proposed_not_authorized"
        or value.get("authority", {}).get("effective") is not False
        or claimed != canonical_sha256(unsigned)
    ):
        raise ValueError("G2 proposal identity, authority, or digest differs")
    return value


def validate_proposal(path: Path) -> dict[str, Any]:
    value = validate_frozen_proposal(path)
    _, state = _git_identity()
    if state != "clean":
        raise ValueError("G2 proposal validation requires a clean source state")
    if value.get("host_tools") != {
        name: _binding(tool_path) for name, tool_path in HOST_TOOL_PATHS.items()
    }:
        raise ValueError("G2 proposal host tool binding is stale")
    observed_g1 = validate_no_write_qualification_pass(Path(value["g1_pass"]["run_dir"]))
    if value.get("g1_pass") != observed_g1:
        raise ValueError("G2 proposal G1 binding is stale")
    if value.get("firmware") != observed_g1["firmware"]:
        raise ValueError("G2 proposal firmware differs from G1")
    if value.get("policy") != observed_g1["policy"]:
        raise ValueError("G2 proposal policy differs from G1")
    return value


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    create = commands.add_parser("create")
    create.add_argument("--no-write-run-dir", type=Path, required=True)
    create.add_argument("--output", type=Path, required=True)
    validate = commands.add_parser("validate")
    validate.add_argument("proposal", type=Path)
    args = parser.parse_args(argv)
    if args.command == "create":
        result = create_proposal(
            no_write_run_dir=args.no_write_run_dir, output_path=args.output
        )
    else:
        result = validate_proposal(args.proposal)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
