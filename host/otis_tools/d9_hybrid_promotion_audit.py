"""Close Prompt 04 at the exact blocked-promotion boundary without hardware I/O.

The valid Prompt 02 result blocks a combined D9/D6/CX322 candidate.  This tool
therefore verifies the reviewed decision, non-effective Prompt 03 contract,
clean separated-profile builds, retained Prompt 01 PTY rehearsal, and unchanged
CX322 law.  It does not create a combined profile, live-trial proposal, or any
physical authority.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import subprocess
import tempfile
from typing import Any, Mapping

from .active_hybrid_policy import load_policy
from .active_hybrid_programme_contract import CX322_PROGRAMME


ROOT = Path(__file__).resolve().parents[2]
PROGRAMME_DIR = (
    ROOT
    / "docs/60_EXPERIMENTS/OTIS_D9_OUTPUT_AND_ADAPTIVE_STEERING_INTEGRATION_PROGRAMME"
)
TOOL_ID = "otis_d9_hybrid_blocked_promotion_audit_v2"
REPORT_TYPE = "otis_d9_hybrid_blocked_promotion_audit_v2"
TERMINAL = "non_effective_semantics_verified_promotion_blocked_by_d9_gate"
READINESS_CONTRACT = PROGRAMME_DIR / "d9_d6_readiness_contract_v1.json"
PROMPT02_DECISION = PROGRAMME_DIR / "prompt02_controller_decision_v1.json"
PROMPT03_CONTRACT = (
    PROGRAMME_DIR / "cx322_non_effective_operational_semantics_contract_v1.json"
)
FIRMWARE_MATRIX = ROOT / "firmware/arduino/firmware_matrix.json"
REQUIRED_BUILD_PROFILES = (
    "d9_d6_forwarded_output_no_control",
    "d9_d6_frequency_only_lower",
    "cx322_direct_hybrid",
)
EXPECTED_REHEARSAL_INPUT = (
    "82f0582e79855544828b2ad222db51ea66af487168b615b891b06e87eb631614"
)


def _canonical_sha256(value: object) -> str:
    return sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    ).hexdigest()


def _file_binding(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"required exact input is unavailable: {path}")
    return {
        "path": str(path.resolve()),
        "size_bytes": path.stat().st_size,
        "sha256": sha256(path.read_bytes()).hexdigest(),
    }


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def _validate_semantic_hash(value: Mapping[str, Any], *, field: str, label: str) -> None:
    unsigned = {key: item for key, item in value.items() if key != field}
    if value.get(field) != _canonical_sha256(unsigned):
        raise ValueError(f"{label} semantic identity differs")


def _profile(matrix: Mapping[str, Any], profile_id: str) -> Mapping[str, Any]:
    entries = matrix.get("profiles")
    if not isinstance(entries, list):
        raise ValueError("firmware matrix profiles are absent")
    matches = [entry for entry in entries if entry.get("id") == profile_id]
    if len(matches) != 1 or not isinstance(matches[0].get("defines"), Mapping):
        raise ValueError(f"exact firmware profile is absent: {profile_id}")
    return matches[0]


def _git_identity() -> tuple[str, bool, list[str]]:
    revision = subprocess.run(
        ["git", "rev-parse", "HEAD"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    status = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return revision, not status, status


def _validate_build_manifest(
    path: Path, *, profile_id: str, source_revision: str
) -> dict[str, object]:
    manifest = _read_object(path)
    provenance = manifest.get("provenance")
    if not isinstance(provenance, Mapping):
        raise ValueError(f"{profile_id} build provenance is absent")
    configuration = provenance.get("configuration")
    source = provenance.get("source")
    if not isinstance(configuration, Mapping) or not isinstance(source, Mapping):
        raise ValueError(f"{profile_id} build source/configuration is absent")
    if configuration.get("profile_id") != profile_id:
        raise ValueError(f"{profile_id} build selected a different profile")
    if source.get("git_commit") != source_revision or source.get("state") != "clean":
        raise ValueError(f"{profile_id} build is not bound to the clean exact revision")
    artifacts = manifest.get("artifacts")
    if not isinstance(artifacts, list):
        raise ValueError(f"{profile_id} build artifacts are absent")
    artifact_names = {item.get("name") for item in artifacts if isinstance(item, Mapping)}
    if not {
        "otis_nano_rp2040_connect.ino.elf",
        "otis_nano_rp2040_connect.ino.uf2",
    }.issubset(artifact_names):
        raise ValueError(f"{profile_id} build lacks ELF/UF2 binary proof")
    return {
        **_file_binding(path),
        "profile_id": profile_id,
        "configuration_sha256": configuration.get("sha256"),
        "source_sha256": source.get("sha256"),
        "git_commit": source_revision,
        "authority_class": (
            "non_actuating_D9_D6"
            if profile_id == "d9_d6_forwarded_output_no_control"
            else (
                "compile_only_unqualified_frequency_control"
                if profile_id == "d9_d6_frequency_only_lower"
                else "retained_standalone_CX322_not_D9_integrated"
            )
        ),
    }


def audit(
    *,
    build_manifest_paths: Mapping[str, Path],
    retained_rehearsal_path: Path,
    readiness_contract_path: Path = READINESS_CONTRACT,
    prompt02_decision_path: Path = PROMPT02_DECISION,
    prompt03_contract_path: Path = PROMPT03_CONTRACT,
    firmware_matrix_path: Path = FIRMWARE_MATRIX,
    source_identity: tuple[str, bool, list[str]] | None = None,
) -> dict[str, object]:
    """Return the exact completed non-effective blocked-promotion report."""
    source_revision, source_clean, dirty_paths = source_identity or _git_identity()
    if not source_clean:
        raise ValueError(f"Prompt 04 exact source is dirty: {dirty_paths}")

    readiness = _read_object(readiness_contract_path)
    _validate_semantic_hash(
        readiness,
        field="contract_semantic_sha256",
        label="D9/D6 readiness contract",
    )
    if readiness.get("contract_id") != "OTIS_D9_D6_READINESS_CONTRACT_V1":
        raise ValueError("D9/D6 readiness contract identity differs")
    if any(readiness.get("authority", {}).values()):
        raise ValueError("D9/D6 readiness authority boundary differs")

    prompt02 = _read_object(prompt02_decision_path)
    _validate_semantic_hash(
        prompt02,
        field="decision_semantic_sha256",
        label="Prompt 02 decision",
    )
    expected_terminals = {
        "d9_output": "output_function_correct_but_waveform_evidence_incomplete",
        "d6_monitor": "d6_forwarded_clock_monitor_qualified_as_diagnostic_only",
        "d14_d8": "d14_d8_acquisition_healthy",
        "frequency_only_soak": "frequency_only_d9_output_soak_incomplete",
        "controller": "cx322_integration_blocked_by_d9_output_gate",
    }
    if prompt02.get("terminals") != expected_terminals:
        raise ValueError("Prompt 02 controller/output terminals differ")
    if prompt02.get("readiness_contract_semantic_sha256") != readiness.get(
        "contract_semantic_sha256"
    ):
        raise ValueError("Prompt 02 decision and readiness contract differ")
    if any(prompt02.get("authority_and_final_state", {}).get(key) for key in (
        "physical_authority",
        "d9_control_authority",
        "d6_control_authority",
        "hybrid_authority",
        "frequency_only_soak_authority",
        "dac_write_performed",
        "receiver_command_performed",
    )):
        raise ValueError("Prompt 02 decision unexpectedly grants authority")

    prompt03 = _read_object(prompt03_contract_path)
    _validate_semantic_hash(
        prompt03,
        field="contract_semantic_sha256",
        label="Prompt 03 semantics contract",
    )
    if (
        prompt03.get("entry_controller_terminal") != expected_terminals["controller"]
        or prompt03.get("entry_controller_decision_semantic_sha256")
        != prompt02.get("decision_semantic_sha256")
        or prompt03.get("terminal")
        != "operational_semantics_implemented_promotion_blocked_by_d9_gate"
        or any(prompt03.get("authority", {}).values())
    ):
        raise ValueError("Prompt 03 entry, terminal, or authority differs")

    matrix = _read_object(firmware_matrix_path)
    d9_non_actuating = _profile(matrix, "d9_d6_forwarded_output_no_control")
    d9_frequency = _profile(matrix, "d9_d6_frequency_only_lower")
    cx322 = _profile(matrix, CX322_PROGRAMME.profile_id)
    non_actuating_defines = d9_non_actuating["defines"]
    frequency_defines = d9_frequency["defines"]
    cx322_defines = cx322["defines"]
    if (
        non_actuating_defines.get("OTIS_ENABLE_FORWARDED_D9_OUTPUT") != "1"
        or non_actuating_defines.get("OTIS_ENABLE_FORWARDED_D6_MONITOR") != "1"
        or non_actuating_defines.get("OTIS_ENABLE_DAC_AD5693R") != "0"
        or non_actuating_defines.get("OTIS_ENABLE_CX317_BOUNDED_ACTIVE") != "0"
        or non_actuating_defines.get("OTIS_ENABLE_CX322_DIRECT_HYBRID") != "0"
    ):
        raise ValueError("non-actuating D9/D6 profile authority differs")
    if (
        frequency_defines.get("OTIS_ENABLE_FORWARDED_D9_OUTPUT") != "1"
        or frequency_defines.get("OTIS_ENABLE_FORWARDED_D6_MONITOR") != "1"
        or frequency_defines.get("OTIS_ENABLE_DAC_AD5693R") != "1"
        or frequency_defines.get("OTIS_ENABLE_CX317_BOUNDED_ACTIVE") != "1"
        or frequency_defines.get("OTIS_ENABLE_CX322_DIRECT_HYBRID", "0") != "0"
    ):
        raise ValueError("D9/D6 frequency-only compile profile differs")
    if (
        cx322_defines.get("OTIS_ENABLE_CX322_DIRECT_HYBRID") != "1"
        or cx322_defines.get("OTIS_ENABLE_FORWARDED_D9_OUTPUT", "0") != "0"
        or cx322_defines.get("OTIS_ENABLE_FORWARDED_D6_MONITOR", "0") != "0"
    ):
        raise ValueError("standalone CX322/D9 profile separation differs")

    if set(build_manifest_paths) != set(REQUIRED_BUILD_PROFILES):
        raise ValueError("Prompt 04 requires all three exact separated build manifests")
    builds = {
        profile_id: _validate_build_manifest(
            build_manifest_paths[profile_id],
            profile_id=profile_id,
            source_revision=source_revision,
        )
        for profile_id in REQUIRED_BUILD_PROFILES
    }

    rehearsal = _read_object(retained_rehearsal_path)
    if (
        rehearsal.get("status") != "passed"
        or rehearsal.get("input_id") != EXPECTED_REHEARSAL_INPUT
        or rehearsal.get("physical_actions_performed") != 0
        or rehearsal.get("qualification_evidence") is not False
        or rehearsal.get("registration_valid") is not True
    ):
        raise ValueError("retained Prompt 01 PTY rehearsal identity or result differs")

    policy = load_policy(CX322_PROGRAMME.policy_path)
    if policy.policy_id != CX322_PROGRAMME.policy_id:
        raise ValueError("CX322 policy identity differs from its programme")

    return {
        "schema_version": 2,
        "report_type": REPORT_TYPE,
        "tool": TOOL_ID,
        "terminal": TERMINAL,
        "status": "passed_non_effective_blocked_promotion_verification",
        "effective": False,
        "physical_authority": False,
        "trial_proposal_created": False,
        "source": {
            "git_commit": source_revision,
            "state": "clean",
        },
        "verified_scope": [
            "Prompt 02 sealed controller decision identity",
            "Prompt 03 non-effective semantics contract identity",
            "exact separated firmware profiles and binary manifests",
            "unchanged CX322 deterministic policy identity",
            "retained Prompt 01 D9/D6 PTY capture/FIFO/abort/rotation/analyzer/sealer path",
            "D9/D6 and CX322 firmware-profile mutual exclusion",
        ],
        "exact_inputs": {
            "d9_d6_readiness_contract": _file_binding(readiness_contract_path),
            "prompt02_controller_decision": _file_binding(prompt02_decision_path),
            "prompt03_semantics_contract": _file_binding(prompt03_contract_path),
            "firmware_matrix": _file_binding(firmware_matrix_path),
            "cx322_policy": {
                **_file_binding(CX322_PROGRAMME.policy_path),
                "policy_id": policy.policy_id,
                "policy_sha256": policy.policy_sha256,
            },
            "retained_prompt01_rehearsal": {
                **_file_binding(retained_rehearsal_path),
                "input_id": rehearsal["input_id"],
                "seal_sha256": rehearsal.get("seal_sha256"),
            },
        },
        "builds": builds,
        "profile_separation": {
            "non_actuating_d9_d6": "d9_d6_forwarded_output_no_control",
            "compile_only_unqualified_frequency_control": "d9_d6_frequency_only_lower",
            "retained_standalone_cx322": "cx322_direct_hybrid",
            "combined_d9_d6_cx322_profile_exists": False,
        },
        "blocking_evidence": [
            prompt02["blocking_evidence_gap"],
            "D9_waveform_and_qualified_load_gate_not_passed",
        ],
        "not_proved_and_intentionally_uncreated": [
            "integrated_D9_D6_CX322_firmware_binary",
            "Prompt_03_state_fields_in_live_firmware_telemetry",
            "complete_integrated_producer_to_consumer_PTY_topology",
            "physical_Core0_Core1_DAC_or_VCOCXO_behavior",
            "D9_waveform_load_delay_jitter_or_independent_frequency",
            "later_72_hour_trial_authority",
        ],
    }


def _write_exclusive(path: Path, value: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, delete=False
    ) as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
        temporary = Path(handle.name)
    try:
        os.link(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _build_manifest_argument(value: str) -> tuple[str, Path]:
    profile_id, separator, raw_path = value.partition("=")
    if not separator or profile_id not in REQUIRED_BUILD_PROFILES or not raw_path:
        raise argparse.ArgumentTypeError("build manifest must be PROFILE=PATH")
    return profile_id, Path(raw_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--build-manifest",
        action="append",
        type=_build_manifest_argument,
        required=True,
    )
    parser.add_argument("--retained-rehearsal", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    build_manifests = dict(args.build_manifest)
    if len(build_manifests) != len(args.build_manifest):
        parser.error("each required build profile must be provided exactly once")
    try:
        report = audit(
            build_manifest_paths=build_manifests,
            retained_rehearsal_path=args.retained_rehearsal,
        )
        _write_exclusive(args.output, report)
    except (FileExistsError, OSError, TypeError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
    print(json.dumps({"terminal": report["terminal"], "status": report["status"]}))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
