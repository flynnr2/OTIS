"""Create and validate the immutable, non-effective Prompt 01 D9/D6 bundle.

This module deliberately has no serial, flashing, or run-directory capability.
It binds the artefacts which a later physical-authority operation must verify
before it opens a device.  The bundle is canonical JSON: its ``bundle_id`` is
the SHA-256 of every other field.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping

from jsonschema import Draft202012Validator


ROOT = Path(__file__).resolve().parents[2]
SCHEMA_PATH = ROOT / "schemas/d9_d6_candidate_bundle_v1.schema.json"
BUNDLE_TYPE = "otis_d9_d6_candidate_bundle_v1"
TOOL_ID = "otis_d9_d6_candidate_bundle_v1"
REHEARSAL_INPUT_TYPE = "otis_d9_d6_rehearsal_input_v1"
TERMINAL_READY = "d9_d6_candidate_bundle_ready_for_physical_authority"
HEX40 = re.compile(r"^[0-9a-f]{40}$")
HEX64 = re.compile(r"^[0-9a-f]{64}$")
# ``provisional_*_pending_d9_gate`` is the immutable, required V2 terminal, so
# generic words such as "pending" cannot identify an unresolved binding.  The
# explicit pre-bundle sentinels and TBD marker can.
PLACEHOLDER = re.compile(r"(?:unbound|placeholder|\\btbd\\b)", re.I)

PROFILE_SELECTORS = {
    "d9_disabled_no_control_baseline": ("0", "0"),
    "d9_forwarded_output_no_control": ("1", "0"),
    "d9_d6_forwarded_output_no_control": ("1", "1"),
}
NO_CONTROL_DEFINES = {
    "OTIS_ENABLE_D9_D6_READINESS_PROFILE": "1",
    "OTIS_ENABLE_DUAL_CORE_PARTITION": "1",
    "OTIS_ENABLE_GNSS_RECEIVER": "0",
    "OTIS_GNSS_UART_TX_ENABLED": "0",
    "OTIS_ENABLE_DAC_AD5693R": "0",
    "OTIS_ENABLE_CX317_BOUNDED_ACTIVE": "0",
    "OTIS_ENABLE_CX320_ACTIVE_HYBRID": "0",
    "OTIS_ENABLE_CX321_ACTIVE_HYBRID": "0",
    "OTIS_ENABLE_CX322_DIRECT_HYBRID": "0",
    "OTIS_ENABLE_SUSTAINED_HYBRID_REGULATION": "0",
}
REQUIRED_KEYS = frozenset(
    {
        "schema_version",
        "bundle_type",
        "tool",
        "bundle_id",
        "effective",
        "physical_authority",
        "terminal",
        "source_state",
        "dependencies",
        "contract",
        "firmware_profiles",
        "host_tools",
        "bench_topology",
        "serial",
        "scope",
        "commands",
        "stop_conditions",
        "evidence_destinations",
        "verification",
        "rehearsal",
        "finalization",
        "authority",
    }
)
REHEARSAL_INPUT_KEYS = frozenset(
    (REQUIRED_KEYS - {"bundle_id", "terminal", "rehearsal"}) | {"input_id"}
)


def canonical_json(value: object) -> bytes:
    """Return the one allowed wire representation, rejecting non-finite JSON."""
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_sha256(value: object) -> str:
    return sha256(canonical_json(value)).hexdigest()


def _load_schema() -> Draft202012Validator:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_binding(path: Path) -> dict[str, object]:
    """Return a non-symlink exact binding suitable for a candidate input."""
    resolved = path.resolve()
    if resolved.is_symlink() or not resolved.is_file():
        raise ValueError(f"cannot bind non-regular file: {resolved}")
    return {
        "path": str(resolved),
        "size_bytes": resolved.stat().st_size,
        "sha256": _sha256_file(resolved),
    }


def _validate_binding(value: Mapping[str, Any], label: str, *, verify_files: bool) -> None:
    if set(value) != {"path", "size_bytes", "sha256"}:
        raise ValueError(f"{label} binding field set differs")
    if not isinstance(value["path"], str) or not value["path"]:
        raise ValueError(f"{label} path is absent")
    if not isinstance(value["size_bytes"], int) or value["size_bytes"] < 1:
        raise ValueError(f"{label} size is invalid")
    if not isinstance(value["sha256"], str) or not HEX64.fullmatch(value["sha256"]):
        raise ValueError(f"{label} SHA-256 is invalid")
    if not verify_files:
        return
    path = Path(value["path"]).resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{label} exact file is absent: {path}")
    if path.stat().st_size != value["size_bytes"] or _sha256_file(path) != value["sha256"]:
        raise ValueError(f"{label} identity differs: {path}")


def _reject_placeholders(value: object, path: str = "bundle") -> None:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if PLACEHOLDER.search(value) or normalized in {
            "unknown", "pending", "n/a", "not_available",
        } or normalized.startswith("unknown_"):
            raise ValueError(f"{path} contains unresolved placeholder: {value!r}")
    if isinstance(value, Mapping):
        for key, item in value.items():
            _reject_placeholders(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_placeholders(item, f"{path}[{index}]")


def _validate_source(value: Mapping[str, Any]) -> None:
    required = {"git_revision", "tree_state", "dirty_paths", "dirty_paths_sha256"}
    if set(value) != required or not HEX40.fullmatch(str(value.get("git_revision"))):
        raise ValueError("source state identity differs")
    if value["tree_state"] not in {"clean", "dirty"} or not isinstance(value["dirty_paths"], list):
        raise ValueError("source state is invalid")
    paths = value["dirty_paths"]
    if paths != sorted(set(paths)) or any(not isinstance(path, str) or not path for path in paths):
        raise ValueError("source dirty paths are not a canonical unique list")
    if value["tree_state"] == "clean" and paths:
        raise ValueError("clean source state cannot have dirty paths")
    if value["tree_state"] == "dirty" and not paths:
        raise ValueError("dirty source state requires exact dirty paths")
    if value["dirty_paths_sha256"] != canonical_sha256(paths):
        raise ValueError("source dirty-path identity differs")


def _validate_dependencies(value: Mapping[str, Any]) -> None:
    required = {"gnss_baud_envelope", "v2_adaptive_study"}
    if set(value) != required:
        raise ValueError("dependency field set differs")
    gnss = value["gnss_baud_envelope"]
    v2 = value["v2_adaptive_study"]
    if not isinstance(gnss, Mapping) or not isinstance(v2, Mapping):
        raise ValueError("dependency identity is invalid")
    if gnss.get("terminal") != "multi_baud_characterization_continuation_complete" or gnss.get("selected_operational_baud") != 115200:
        raise ValueError("GNSS dependency terminal or baud differs")
    if any(not HEX64.fullmatch(str(gnss.get(key, ""))) for key in ("package_sha256", "seal_sha256")):
        raise ValueError("GNSS dependency SHA-256 differs")
    expected_v2 = {
        "contract_sha256": "b7525de381bbd6506978819a46ccdc280993c47aba2d1ab673a9e595b48e325f",
        "derived_manifest_sha256": "705361d252782c911cea63bfca691691c6ab045956942f057f87db31827b4816",
        "report_sha256": "c411e44042162192228b04c4ebd567b90d73ddd77344f9d1d6f494ada863e9e5",
        "tool_bundle_sha256": "fbbcb152880b0079e97eb9b9d216e292aa805ceb829e78996c4e06dee282b1ca",
        "terminal": "provisional_cx322_unchanged_pending_d9_gate",
    }
    if dict(v2) != expected_v2:
        raise ValueError("V2 dependency identity differs")


def _validate_profiles(profiles: list[Mapping[str, Any]], *, verify_files: bool) -> None:
    if len(profiles) != len(PROFILE_SELECTORS):
        raise ValueError("exactly three readiness profile strata are required")
    by_id = {item.get("profile_id"): item for item in profiles}
    if set(by_id) != set(PROFILE_SELECTORS):
        raise ValueError("readiness profile set differs")
    for profile_id, (d9, d6) in PROFILE_SELECTORS.items():
        profile = by_id[profile_id]
        if set(profile) != {"profile_id", "configuration", "toolchain", "build_manifest", "elf", "uf2", "binary_contract"}:
            raise ValueError(f"{profile_id} field set differs")
        configuration = profile["configuration"]
        if not isinstance(configuration, Mapping) or configuration.get("profile_id") != profile_id:
            raise ValueError(f"{profile_id} configuration identity differs")
        defines = configuration.get("defines")
        if not isinstance(defines, Mapping):
            raise ValueError(f"{profile_id} compile definitions are absent")
        expected = {**NO_CONTROL_DEFINES, "OTIS_ENABLE_FORWARDED_D9_OUTPUT": d9, "OTIS_ENABLE_FORWARDED_D6_MONITOR": d6}
        if any(defines.get(key) != setting for key, setting in expected.items()):
            raise ValueError(f"{profile_id} is not exact non-effective D9/D6 topology")
        if defines.get("OTIS_GNSS_UART_BAUD") != "115200u":
            raise ValueError(f"{profile_id} host firmware baud differs")
        for key in ("build_manifest", "elf", "uf2"):
            item = profile[key]
            if not isinstance(item, Mapping):
                raise ValueError(f"{profile_id} {key} binding is invalid")
            _validate_binding(item, f"{profile_id} {key}", verify_files=verify_files)
        toolchain = profile["toolchain"]
        if not isinstance(toolchain, Mapping) or set(toolchain) != {"arduino_cli", "core", "compiler", "installed_sha256"} or not HEX64.fullmatch(str(toolchain.get("installed_sha256", ""))):
            raise ValueError(f"{profile_id} toolchain identity differs")
        contract = profile["binary_contract"]
        expected_binary_status = "disabled_profile" if profile_id == "d9_disabled_no_control_baseline" else "verified"
        if not isinstance(contract, Mapping) or contract.get("status") != expected_binary_status or not HEX64.fullmatch(str(contract.get("sha256", ""))):
            raise ValueError(f"{profile_id} binary-contract result differs")


def _validate_common_payload(value: Mapping[str, Any], *, verify_files: bool) -> None:
    _validate_source(value["source_state"])
    _validate_dependencies(value["dependencies"])
    contract = value["contract"]
    if set(contract) != {"d9_d6_readiness", "readiness_contract"}:
        raise ValueError("readiness contract identity differs")
    readiness = contract["d9_d6_readiness"]
    expected_readiness = {
        "contract_id": "OTIS_D9_D6_READINESS_CONTRACT_V1",
        "contract_semantic_sha256": "a6a08d14a03a87b5e0308880c64799baf2e7afecc23cad22d1532f297960de4d",
        "profile": "d9_d6_forwarded_output_no_control",
        "physical_authority": False,
    }
    if readiness != expected_readiness:
        raise ValueError("d9_d6_readiness manifest binding differs")
    _validate_binding(contract["readiness_contract"], "readiness contract", verify_files=verify_files)
    _validate_profiles(value["firmware_profiles"], verify_files=verify_files)
    tools = value["host_tools"]
    if not isinstance(tools, list) or not tools:
        raise ValueError("host tool bindings are absent")
    for index, binding in enumerate(tools):
        _validate_binding(binding, f"host tool {index}", verify_files=verify_files)
    topology = value["bench_topology"]
    expected_topology = {"d14": "sole_authoritative_pps_input", "d8": "sole_authoritative_oscillator_count_input", "d9": "forwarded_output_only", "d6": "zero_authority_diagnostic_only", "wiring": "D9_to_D6_series_1000_ohms", "load": "high_impedance_only_no_50_ohm"}
    if topology != expected_topology:
        raise ValueError("frozen bench topology differs")
    if value["serial"] != {"firmware_host_baud": 115200, "device_selection": "capture_device_auto_detect_exactly_one_cu_usbmodem"}:
        raise ValueError("serial auto-detect/baud contract differs")
    scope = value["scope"]
    expected_scope = {"waveform_gate_ceiling": "output_function_correct_but_waveform_evidence_incomplete", "waveform_instrument_available": False, "frequency_only_soak_permitted": False, "d6_qualification_only": True}
    if scope != expected_scope:
        raise ValueError("no-instrument scope ceiling differs")
    commands = value["commands"]
    if commands != {"receiver_commands_permitted": False, "dac_writes_permitted": False, "fll_arm_permitted": False, "hybrid_arm_permitted": False, "phase_authority": False}:
        raise ValueError("non-actuating command envelope differs")
    if not isinstance(value["stop_conditions"], list) or not value["stop_conditions"]:
        raise ValueError("stop conditions are absent")
    if not isinstance(value["evidence_destinations"], Mapping) or not value["evidence_destinations"]:
        raise ValueError("evidence destinations are absent")
    for key in ("preflight", "release"):
        outcome = value["verification"].get(key)
        if not isinstance(outcome, Mapping) or outcome.get("status") != "passed":
            raise ValueError(f"{key} verification is not a passed exact result")
        _validate_binding(outcome["report"], f"{key} report", verify_files=verify_files)
    finalization = value["finalization"]
    if finalization != {"capture": "current_platform_capture", "analyzer": "current_platform_analyzer", "sealer": "current_platform_sealer", "registration": "current_evidence_index", "live_run_directory_created": False}:
        raise ValueError("finalization contract differs")
    authority = value["authority"]
    if authority != {"activation_required": True, "physical_authority": False, "independent_abort_required": True, "automatic_retry_runs": 0}:
        raise ValueError("authority contract differs")


def _validate_complete(candidate: Mapping[str, Any], *, verify_files: bool) -> None:
    if set(candidate) != REQUIRED_KEYS:
        raise ValueError("candidate bundle field set differs")
    try:
        _load_schema().validate(candidate)
    except Exception as exc:
        raise ValueError(f"candidate bundle schema invalid: {exc}") from exc
    _reject_placeholders(candidate)
    if candidate["bundle_type"] != BUNDLE_TYPE or candidate["tool"] != TOOL_ID:
        raise ValueError("candidate bundle type differs")
    if candidate["effective"] is not False or candidate["physical_authority"] is not False:
        raise ValueError("candidate must remain non-effective with authority false")
    if candidate["terminal"] != TERMINAL_READY:
        raise ValueError("candidate readiness terminal differs")
    unsigned = {key: value for key, value in candidate.items() if key != "bundle_id"}
    if candidate["bundle_id"] != canonical_sha256(unsigned):
        raise ValueError("candidate bundle semantic identity differs")
    _validate_common_payload(candidate, verify_files=verify_files)
    rehearsal = candidate["rehearsal"]
    if set(rehearsal) != {
        "status", "hardware_operations", "input_bundle", "input_id", "report"
    }:
        raise ValueError("rehearsal result field set differs")
    if rehearsal.get("status") != "passed" or rehearsal.get("hardware_operations") is not False:
        raise ValueError("rehearsal is not an exact no-hardware pass")
    if not HEX64.fullmatch(str(rehearsal.get("input_id", ""))):
        raise ValueError("rehearsal input identity differs")
    _validate_binding(
        rehearsal["input_bundle"], "rehearsal input bundle",
        verify_files=verify_files,
    )
    if verify_files:
        bound_input = json.loads(
            Path(str(rehearsal["input_bundle"]["path"])).read_text(
                encoding="utf-8"
            )
        )
        validated_input = validate_rehearsal_input(
            bound_input, verify_files=verify_files
        )
        if validated_input["input_id"] != rehearsal["input_id"]:
            raise ValueError("rehearsal report binds a different input identity")
    _validate_binding(rehearsal["report"], "rehearsal report", verify_files=verify_files)


def validate_rehearsal_input(
    rehearsal_input: Mapping[str, Any], *, verify_files: bool = True
) -> dict[str, Any]:
    """Validate the immutable exact input consumed before a rehearsal pass exists."""
    if not isinstance(rehearsal_input, Mapping):
        raise ValueError("rehearsal input root must be an object")
    value = dict(rehearsal_input)
    if set(value) != REHEARSAL_INPUT_KEYS:
        raise ValueError("rehearsal input field set differs")
    _reject_placeholders(value)
    if value["bundle_type"] != REHEARSAL_INPUT_TYPE or value["tool"] != TOOL_ID:
        raise ValueError("rehearsal input type differs")
    if value["effective"] is not False or value["physical_authority"] is not False:
        raise ValueError("rehearsal input must remain non-effective with authority false")
    unsigned = {key: item for key, item in value.items() if key != "input_id"}
    if value["input_id"] != canonical_sha256(unsigned):
        raise ValueError("rehearsal input semantic identity differs")
    _validate_common_payload(value, verify_files=verify_files)
    return value


def freeze_rehearsal_input(draft: Mapping[str, Any]) -> dict[str, Any]:
    """Freeze the exact pre-result bundle which the no-hardware path consumes."""
    value = dict(draft)
    value["bundle_type"] = REHEARSAL_INPUT_TYPE
    value["tool"] = TOOL_ID
    value.pop("input_id", None)
    value["input_id"] = canonical_sha256(value)
    return validate_rehearsal_input(value)


def validate_candidate(candidate: Mapping[str, Any], *, verify_files: bool = True) -> dict[str, Any]:
    """Validate a frozen bundle and, by default, every exact file binding."""
    if not isinstance(candidate, Mapping):
        raise ValueError("candidate bundle root must be an object")
    value = dict(candidate)
    _validate_complete(value, verify_files=verify_files)
    return value


def freeze_candidate(draft: Mapping[str, Any]) -> dict[str, Any]:
    """Complete a fully bound draft, derive its identity, then validate it."""
    candidate = dict(draft)
    candidate.pop("bundle_id", None)
    candidate["bundle_id"] = canonical_sha256(candidate)
    return validate_candidate(candidate)


def _read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("candidate JSON root must be an object")
    return value


def _write_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8") as handle:
        handle.write(canonical_json(value).decode("utf-8"))
        handle.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    freeze = subparsers.add_parser("freeze", help="freeze a fully bound draft without any hardware I/O")
    freeze.add_argument("--draft", type=Path, required=True)
    freeze.add_argument("--output", type=Path, required=True)
    check = subparsers.add_parser("validate", help="validate an existing immutable candidate")
    check.add_argument("--bundle", type=Path, required=True)
    check.add_argument("--no-file-check", action="store_true")
    freeze_rehearsal = subparsers.add_parser(
        "freeze-rehearsal", help="freeze the exact pre-result rehearsal input"
    )
    freeze_rehearsal.add_argument("--draft", type=Path, required=True)
    freeze_rehearsal.add_argument("--output", type=Path, required=True)
    check_rehearsal = subparsers.add_parser(
        "validate-rehearsal", help="validate an immutable rehearsal input"
    )
    check_rehearsal.add_argument("--bundle", type=Path, required=True)
    check_rehearsal.add_argument("--no-file-check", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "freeze":
        result = freeze_candidate(_read_json(args.draft))
        _write_exclusive(args.output, result)
        identity = result["bundle_id"]
        terminal = result["terminal"]
    elif args.command == "validate":
        result = validate_candidate(_read_json(args.bundle), verify_files=not args.no_file_check)
        identity = result["bundle_id"]
        terminal = result["terminal"]
    elif args.command == "freeze-rehearsal":
        result = freeze_rehearsal_input(_read_json(args.draft))
        _write_exclusive(args.output, result)
        identity = result["input_id"]
        terminal = "rehearsal_input_frozen_non_effective"
    else:
        result = validate_rehearsal_input(
            _read_json(args.bundle), verify_files=not args.no_file_check
        )
        identity = result["input_id"]
        terminal = "rehearsal_input_valid_non_effective"
    print(json.dumps({"bundle_id": identity, "terminal": terminal}, sort_keys=True))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
