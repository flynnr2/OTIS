#!/usr/bin/env python3
"""Build the one production OTIS Arduino firmware image with exact provenance."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from hashlib import sha256
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from host.otis_tools import firmware_binary
from host.otis_tools.firmware_host_contract import (
    binding as firmware_host_contract_binding,
)
from host.otis_tools.firmware_host_contract import (
    verify_generated_cpp_header,
)
from tools.generate_reference_acceptance_policy import (
    HEADER as ACCEPTANCE_POLICY_HEADER,
)
from tools.generate_reference_acceptance_policy import (
    POLICY as ACCEPTANCE_POLICY_PATH,
)
from tools.generate_reference_acceptance_policy import (
    render_header as render_acceptance_policy_header,
)

DEFAULT_MANIFEST = REPO_ROOT / "firmware" / "arduino" / "firmware_build_manifest.json"
SKETCH = REPO_ROOT / "firmware" / "arduino" / "otis_nano_rp2040_connect"
BUILDER_PATH = Path(__file__).resolve()
CONFIG_HEADER = SKETCH / "otis_config.h"
GENERATED_HEADER_NAME = "otis_build_manifest.generated.h"
IMAGE_ID = "adaptive_hybrid_regulation"
FIRMWARE_VERSION = "OTIS_ADAPTIVE_HYBRID_REGULATION_V1"
BUILDER_VERSION = 1
PROVENANCE_FORMAT = "otis_fixed_firmware_build_v2"
EXPECTED_ARTIFACT_SUFFIXES = (".bin", ".elf", ".h", ".map", ".uf2")
FIRMWARE_SOURCE_SUFFIXES = (
    ".S",
    ".c",
    ".cc",
    ".cpp",
    ".cxx",
    ".h",
    ".hh",
    ".hpp",
    ".hxx",
    ".ino",
    ".pio",
    ".s",
)
INSTALLATION_NOISE_NAMES = {".DS_Store", "installed.json"}
HEX40_PATTERN = re.compile(r"^[0-9a-f]{40}$")
HEX64_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SESSION_ID_PATTERN = re.compile(r"^[0-9a-f]{16}$")
PROGRAM_USAGE_PATTERN = re.compile(
    r"Sketch uses (\d+) bytes .* Maximum is (\d+) bytes\."
)
DYNAMIC_MEMORY_USAGE_PATTERN = re.compile(
    r"Global variables use (\d+) bytes .* leaving (\d+) bytes for local "
    r"variables\. Maximum is (\d+) bytes\."
)
GNSS_BAUD_PACKET_PATTERN = re.compile(rb"\$PMTK251,[0-9]+\*[0-9A-F]{2}\r\n")
EXPECTED_GNSS_PACKET = b"$PMTK251,115200*1F\r\n"
REQUIRED_IMAGE_MARKERS = {
    "firmware_version": FIRMWARE_VERSION.encode("ascii"),
    "image_id": IMAGE_ID.encode("ascii"),
    "d14_reference": b"D14",
    "d8_count_input": b"D8_GPIO20_GPIN0",
    "d9_forwarded_output": b"D9_GPIO21_GPOUT0",
    "d6_fail_local_monitor": b"d6_gpio18_diagnostic_input",
    "d6_snapshot_topology": b"d6_d14_cumulative_snapshot",
    "gnss_metadata_hold": b"metadata_hold",
    "frequency_estimator": b"OTIS_PPS_GATED_FREQUENCY_ESTIMATOR_V1",
    "phase_estimator": b"OTIS_RELATIVE_PHASE_ESTIMATOR_V1",
    "phase_raw_method": b"D14_ACCEPTED_SPAN_RELATIVE_PHASE_ACCUMULATOR_V1",
    "active_status_contract": b"adaptive_hybrid_active_status_snapshot_v2",
    "external_event_not_implemented": b"not_implemented",
}
FORBIDDEN_IMAGE_MARKERS = {
    "qualified_forwarded_waveform_claim": b"qualified_10mhz_forwarded",
    "runtime_forwarded_source_selection": (b"runtime_forwarded_clock_source_selection"),
    "nonzero_fractional_divider": b"fractional_divider_nonzero",
}
EXPECTED_PROFILE_BINDINGS = {
    "adaptive_policy": "profiles/discipline/adaptive_hybrid_regulation_v1.json",
    "frequency_estimator": (
        "profiles/estimators/pps_gated_frequency_estimator_v1.json"
    ),
    "phase_estimator": "profiles/estimators/relative_phase_estimator_v1.json",
    "plant_model": "profiles/plant_models/pps_gated_oscillator_plant_v1.json",
    "response_policy": "profiles/discipline/response_classification_v1.json",
}
EXPECTED_SCHEMA_BINDINGS = {
    "adaptive_policy": "schemas/adaptive_hybrid_regulation_v1.schema.json",
    "response_policy": "schemas/response_classification_v1.schema.json",
    "frequency_estimator": "schemas/pps_gated_frequency_estimator_v1.schema.json",
    "phase_estimator": "schemas/relative_phase_estimator_v1.schema.json",
    "plant_model": "schemas/plant_model_v1.schema.json",
    "setup_authority": "schemas/adaptive_hybrid_setup_authority_v1.schema.json",
    "run_evidence": "schemas/run_evidence_v1.schema.json",
}
EXPECTED_CONTRACT_BINDINGS = {
    "firmware_host": "data_contracts/otis_firmware_host_contract_v1.json",
    "reference_acceptance": "data_contracts/reference_acceptance_policy_v1.json",
}
FIRMWARE_HOST_BINDING_HELPER = (
    REPO_ROOT / "host" / "otis_tools" / "firmware_host_contract.py"
)
FIRMWARE_BINARY_HELPER = REPO_ROOT / "host" / "otis_tools" / "firmware_binary.py"
PROFILE_BINDING_MACROS = {
    "adaptive_policy": "OTIS_BUILD_ADAPTIVE_POLICY_SHA256",
    "frequency_estimator": "OTIS_BUILD_FREQUENCY_ESTIMATOR_SHA256",
    "phase_estimator": "OTIS_BUILD_PHASE_ESTIMATOR_SHA256",
    "plant_model": "OTIS_BUILD_PLANT_MODEL_SHA256",
    "response_policy": "OTIS_BUILD_RESPONSE_POLICY_SHA256",
}
ROOT_PROFILE = "profiles/discipline/adaptive_hybrid_regulation_v1.json"
FIRMWARE_INPUT_CONTRACT = "otis_firmware_input_set_v1"
PROFILE_SCHEMA_BINDINGS = {
    ROOT_PROFILE: "schemas/adaptive_hybrid_regulation_v1.schema.json",
    "profiles/discipline/response_classification_v1.json": (
        "schemas/response_classification_v1.schema.json"
    ),
    "profiles/estimators/pps_gated_frequency_estimator_v1.json": (
        "schemas/pps_gated_frequency_estimator_v1.schema.json"
    ),
    "profiles/estimators/relative_phase_estimator_v1.json": (
        "schemas/relative_phase_estimator_v1.schema.json"
    ),
    "profiles/plant_models/pps_gated_oscillator_plant_v1.json": (
        "schemas/plant_model_v1.schema.json"
    ),
}
EXPECTED_FORWARDED_CLOCK_CONTRACT = {
    "schema_version": 1,
    "contract_id": "OTIS_D9_FORWARDED_CLOCK_CONTRACT_V1",
    "state": "configured_10mhz_forwarded_unqualified",
    "source": "D8_GPIO20_GPIN0",
    "destination": "D9_GPIO21_GPOUT0",
    "source_gpio": 20,
    "destination_gpio": 21,
    "applied_auxsrc": 1,
    "integer_divider": 1,
    "fractional_divider": 0,
    "inversion": False,
    "drive_strength_ma": 2,
    "slew_rate": "slow",
    "nominal_frequency_hz": 10_000_000,
    "control_authority": False,
}


class BuildError(RuntimeError):
    pass


def _build_session_id_argument(value: str) -> str:
    if not SESSION_ID_PATTERN.fullmatch(value):
        raise argparse.ArgumentTypeError(
            "build session id must be 16 lowercase hexadecimal digits"
        )
    return value


def _run(
    arguments: list[str],
    *,
    cwd: Path = REPO_ROOT,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(
            arguments,
            cwd=cwd,
            check=check,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise BuildError(f"required executable is unavailable: {arguments[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise BuildError(f"command failed ({' '.join(arguments)}): {detail}") from exc


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("ascii")


def _sha256_json(value: object) -> str:
    return sha256(_canonical_bytes(value)).hexdigest()


def _bound_repository_file(relative: str) -> Path:
    relative_path = Path(relative)
    if (
        relative_path.is_absolute()
        or not relative_path.parts
        or any(part in {"", ".", ".."} for part in relative_path.parts)
    ):
        raise BuildError(
            f"repository file binding is not a safe relative path: {relative!r}"
        )
    path = REPO_ROOT / relative_path
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise BuildError(f"repository file binding is unavailable: {relative}") from exc
    if not resolved.is_relative_to(REPO_ROOT.resolve()) or resolved != path.absolute():
        raise BuildError(
            f"repository file binding traverses a symbolic link: {relative}"
        )
    if not resolved.is_file():
        raise BuildError(f"repository file binding is not a regular file: {relative}")
    return resolved


def profile_binding_report(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    declared = manifest.get("profile_bindings")
    if declared != EXPECTED_PROFILE_BINDINGS:
        raise BuildError(
            "fixed manifest profile bindings differ from the five current profiles"
        )
    report: dict[str, dict[str, Any]] = {}
    profile_values: dict[str, dict[str, Any]] = {}
    for name, relative in EXPECTED_PROFILE_BINDINGS.items():
        path = _bound_repository_file(relative)
        data = path.read_bytes()
        try:
            value = json.loads(data)
        except json.JSONDecodeError as exc:
            raise BuildError(f"bound profile is not valid JSON: {relative}") from exc
        if not isinstance(value, dict):
            raise BuildError(f"bound profile root is not an object: {relative}")
        report[name] = {
            "path": relative,
            "size_bytes": len(data),
            "sha256": sha256(data).hexdigest(),
        }
        if name == "phase_estimator":
            profile_id = value.get("profile_id")
            if not isinstance(profile_id, str) or not profile_id:
                raise BuildError(f"bound profile has no profile_id: {relative}")
            report[name]["profile_id"] = profile_id
        profile_values[name] = value

    expected_root_bindings = {
        "response_classification": EXPECTED_PROFILE_BINDINGS["response_policy"],
        "frequency_estimator": EXPECTED_PROFILE_BINDINGS["frequency_estimator"],
        "phase_estimator": EXPECTED_PROFILE_BINDINGS["phase_estimator"],
        "plant_model": EXPECTED_PROFILE_BINDINGS["plant_model"],
    }
    if profile_values["adaptive_policy"].get("bindings") != expected_root_bindings:
        raise BuildError(
            "adaptive policy does not bind the exact current profile closure"
        )

    phase_selection = profile_values["phase_estimator"].get("selection")
    if not isinstance(phase_selection, dict):
        raise BuildError("phase estimator selection must be an object")
    phase_raw_method = phase_selection.get("raw_phase_method")
    if not isinstance(phase_raw_method, str) or not phase_raw_method:
        raise BuildError("phase estimator selection has no raw_phase_method")
    report["phase_estimator"]["raw_phase_method"] = phase_raw_method

    return report


def _profile_references(value: object) -> set[str]:
    references: set[str] = set()

    def walk(child: object) -> None:
        if isinstance(child, dict):
            for item in child.values():
                walk(item)
        elif isinstance(child, list):
            for item in child:
                walk(item)
        elif (
            isinstance(child, str)
            and child.startswith("profiles/")
            and child.endswith(".json")
        ):
            references.add(child)

    walk(value)
    return references


def _authoritative_entry(relative: str) -> tuple[dict[str, Any], dict[str, Any]]:
    path = _bound_repository_file(relative)
    data = path.read_bytes()
    try:
        value = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BuildError(f"authoritative input is not valid JSON: {relative}") from exc
    if not isinstance(value, dict):
        raise BuildError(f"authoritative input root is not an object: {relative}")
    return (
        {
            "path": relative,
            "sha256": sha256(data).hexdigest(),
            "size_bytes": len(data),
            "content": data.decode("utf-8"),
        },
        value,
    )


def schema_binding_report(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    declared = manifest.get("schema_bindings")
    if declared != EXPECTED_SCHEMA_BINDINGS:
        raise BuildError(
            "fixed manifest schema bindings differ from the current schemas"
        )
    report: dict[str, dict[str, Any]] = {}
    for name, relative in EXPECTED_SCHEMA_BINDINGS.items():
        path = _bound_repository_file(relative)
        data = path.read_bytes()
        try:
            value = json.loads(data)
        except json.JSONDecodeError as exc:
            raise BuildError(f"bound schema is not valid JSON: {relative}") from exc
        if not isinstance(value, dict):
            raise BuildError(f"bound schema root is not an object: {relative}")
        report[name] = {
            "path": relative,
            "size_bytes": len(data),
            "sha256": sha256(data).hexdigest(),
        }
    return report


def contract_binding_report(manifest: dict[str, Any]) -> dict[str, dict[str, Any]]:
    declared = manifest.get("contract_bindings")
    if declared != EXPECTED_CONTRACT_BINDINGS:
        raise BuildError(
            "fixed manifest contract bindings differ from the current protocol"
        )
    verify_generated_cpp_header()
    current = firmware_host_contract_binding()
    if current["path"] != EXPECTED_CONTRACT_BINDINGS["firmware_host"]:
        raise BuildError("firmware/host contract path differs")
    if ACCEPTANCE_POLICY_HEADER.read_text() != render_acceptance_policy_header():
        raise BuildError(
            "reference acceptance firmware policy differs from frozen JSON"
        )
    policy_bytes = ACCEPTANCE_POLICY_PATH.read_bytes()
    return {
        "firmware_host": current,
        "reference_acceptance": {
            "path": EXPECTED_CONTRACT_BINDINGS["reference_acceptance"],
            "sha256": sha256(policy_bytes).hexdigest(),
            "size_bytes": len(policy_bytes),
        },
    }


def load_manifest() -> dict[str, Any]:
    path = DEFAULT_MANIFEST
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise BuildError(f"cannot read firmware build manifest: {path}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise BuildError("firmware build manifest schema_version must be 1")
    if manifest.get("builder_id") != "otis_fixed_firmware_builder_v1":
        raise BuildError("firmware build manifest builder_id differs")
    image = manifest.get("image")
    if not isinstance(image, dict):
        raise BuildError("firmware build manifest image must be an object")
    if image.get("id") != IMAGE_ID:
        raise BuildError(f"fixed firmware image id must be {IMAGE_ID!r}")
    if image.get("firmware_version") != FIRMWARE_VERSION:
        raise BuildError(f"fixed firmware version must be {FIRMWARE_VERSION!r}")
    expected_external_event = {
        "pin": "D10",
        "channel": "CH0",
        "status": "not_implemented",
        "isolation_claimed": False,
        "control_authority": False,
        "terminal_authority": False,
    }
    capabilities = manifest.get("capabilities")
    if (
        not isinstance(capabilities, dict)
        or capabilities.get("external_event_capture") != expected_external_event
    ):
        raise BuildError(
            "fixed manifest must preserve D10/CH0 while explicitly denying "
            "an implemented or isolated external-event backend"
        )
    profile_binding_report(manifest)
    if manifest.get("schema_bindings") != EXPECTED_SCHEMA_BINDINGS:
        raise BuildError("fixed manifest schema declarations differ")
    contract_binding_report(manifest)
    if manifest.get("forwarded_clock_contract") != EXPECTED_FORWARDED_CLOCK_CONTRACT:
        raise BuildError("fixed manifest forwarded-clock contract differs")
    for section in ("target", "toolchain", "resource_budget"):
        if not isinstance(manifest.get(section), dict):
            raise BuildError(f"firmware build manifest {section} must be an object")
    target = manifest["target"]
    toolchain = manifest["toolchain"]
    for section, name in (
        (target, "core_archive_sha256"),
        (target, "core_installed_sha256"),
        (toolchain, "installed_sha256"),
    ):
        if not HEX64_PATTERN.fullmatch(str(section.get(name, ""))):
            raise BuildError(f"{name} must be a lowercase SHA-256")
    budget = manifest["resource_budget"]
    required_budget = {
        "dynamic_memory_total_bytes",
        "static_dynamic_memory_max_bytes",
        "runtime_memory_reserve_min_bytes",
    }
    if set(budget) != required_budget or any(
        not isinstance(budget[name], int) or budget[name] <= 0
        for name in required_budget
    ):
        raise BuildError("fixed firmware resource budget is malformed")
    if (
        budget["static_dynamic_memory_max_bytes"]
        + budget["runtime_memory_reserve_min_bytes"]
        != budget["dynamic_memory_total_bytes"]
    ):
        raise BuildError("static RAM budget and runtime reserve must equal total RAM")
    return manifest


def installed_tree_hash(root: Path) -> str:
    root = root.resolve()
    if not root.is_dir():
        raise BuildError(f"installed package path is not a directory: {root}")
    paths = sorted(
        (
            path
            for path in root.rglob("*")
            if (path.is_file() or path.is_symlink())
            and path.name not in INSTALLATION_NOISE_NAMES
            and "__pycache__" not in path.relative_to(root).parts
            and path.suffix not in {".pyc", ".pyo"}
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    if not paths:
        raise BuildError(f"installed package path contains no files: {root}")
    digest = sha256()
    for path in paths:
        relative = path.relative_to(root).as_posix().encode("utf-8")
        if path.is_symlink():
            kind = b"L"
            data = os.readlink(path).encode("utf-8")
        else:
            kind = b"F"
            data = path.read_bytes()
        digest.update(kind)
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def _require_installed_hash(label: str, root: Path, expected: str) -> str:
    actual = installed_tree_hash(root)
    if actual != expected:
        raise BuildError(
            f"{label} installed-byte SHA-256 mismatch: "
            f"expected {expected}, found {actual}"
        )
    return actual


def _build_properties(board_details: dict[str, Any]) -> dict[str, str]:
    properties: dict[str, str] = {}
    for item in board_details.get("build_properties", []):
        if isinstance(item, str) and "=" in item:
            key, value = item.split("=", 1)
            properties[key] = value
    return properties


def verify_environment(
    manifest: dict[str, Any], *, arduino_cli: str = "arduino-cli"
) -> dict[str, str]:
    cli = json.loads(_run([arduino_cli, "version", "--format", "json"]).stdout)
    expected_cli = str(manifest["arduino_cli_version"])
    actual_cli = str(cli.get("VersionString", ""))
    if actual_cli != expected_cli:
        raise BuildError(
            f"Arduino CLI version mismatch: expected {expected_cli}, found {actual_cli}"
        )
    target = manifest["target"]
    details = json.loads(
        _run(
            [
                arduino_cli,
                "board",
                "details",
                "--fqbn",
                str(target["fqbn"]),
                "--format",
                "json",
            ]
        ).stdout
    )
    fqbn_parts = str(target["fqbn"]).split(":", 3)
    checks = {
        "FQBN": (":".join(fqbn_parts[:3]), details.get("fqbn")),
        "core provider": (
            target["core_provider"],
            details.get("package", {}).get("name"),
        ),
        "core architecture": (
            target["core_architecture"],
            details.get("platform", {}).get("architecture"),
        ),
        "core version": (target["core_version"], details.get("version")),
        "core archive checksum": (
            f"SHA-256:{target['core_archive_sha256']}",
            details.get("platform", {}).get("checksum"),
        ),
    }
    for label, (expected, actual) in checks.items():
        if actual != expected:
            raise BuildError(
                f"{label} mismatch: expected {expected!r}, found {actual!r}"
            )
    if len(fqbn_parts) == 4:
        selected_options = {
            str(option.get("option")): str(value.get("value"))
            for option in details.get("config_options", [])
            for value in option.get("values", [])
            if value.get("selected") is True
        }
        for assignment in fqbn_parts[3].split(","):
            option, expected_value = assignment.split("=", 1)
            if selected_options.get(option) != expected_value:
                raise BuildError(
                    f"FQBN option {option!r} mismatch: expected "
                    f"{expected_value!r}, found {selected_options.get(option)!r}"
                )
    if not details.get("properties_id") or not details.get("name"):
        raise BuildError("board details do not expose generated board identity")
    toolchain = manifest["toolchain"]
    dependency = next(
        (
            item
            for item in details.get("tools_dependencies", [])
            if item.get("packager") == toolchain["packager"]
            and item.get("name") == toolchain["name"]
        ),
        None,
    )
    if dependency is None or dependency.get("version") != toolchain["version"]:
        raise BuildError("pinned compiler toolchain is absent or has the wrong version")
    properties = _build_properties(details)
    platform_root = properties.get("runtime.platform.path")
    toolchain_name = str(toolchain["name"])
    tool_root = properties.get(f"runtime.tools.{toolchain_name}.path")
    compiler_prefix = properties.get("build.toolchain")
    if not platform_root or not tool_root or not compiler_prefix:
        raise BuildError("board details omit installed compiler or core paths")
    if properties.get("build.toolchainpkg") != toolchain_name:
        raise BuildError("board selects a different compiler package")
    core_hash = _require_installed_hash(
        "Arduino core", Path(platform_root), str(target["core_installed_sha256"])
    )
    toolchain_hash = _require_installed_hash(
        "compiler toolchain", Path(tool_root), str(toolchain["installed_sha256"])
    )
    compiler_path = Path(tool_root) / "bin" / str(toolchain["compiler"])
    if str(toolchain["compiler"]) != f"{compiler_prefix}-g++":
        raise BuildError("board compiler executable differs from the manifest")
    compiler_line = _run([str(compiler_path), "--version"]).stdout.splitlines()[0]
    if not compiler_line.endswith(f" {toolchain['compiler_version']}"):
        raise BuildError("compiler version differs from the manifest")
    return {
        "arduino_cli_version": actual_cli,
        "board_id": str(details["properties_id"]),
        "board_name": str(details["name"]),
        "core_installed_sha256": core_hash,
        "toolchain_installed_sha256": toolchain_hash,
        "core_path": str(Path(platform_root).resolve()),
        "toolchain_path": str(Path(tool_root).resolve()),
        "compiler_identity": (
            f"{toolchain_name}@{toolchain['version']}/"
            f"{toolchain['compiler']}@{toolchain['compiler_version']}"
        ),
    }


def _git_identity(
    repo_root: Path = REPO_ROOT,
    *,
    pathspecs: tuple[str, ...] | None = None,
) -> tuple[str, str]:
    commit = _run(["git", "rev-parse", "HEAD"], cwd=repo_root).stdout.strip()
    if not HEX40_PATTERN.fullmatch(commit):
        raise BuildError(f"Git returned a malformed commit identity: {commit!r}")
    status_arguments = ["git", "status", "--porcelain=v1", "--untracked-files=all"]
    if pathspecs is not None:
        if not pathspecs:
            raise BuildError("firmware operational source path set is empty")
        status_arguments.extend(["--", *pathspecs])
    status = _run(
        status_arguments,
        cwd=repo_root,
    ).stdout
    return commit, "dirty" if status else "clean"


def source_input_paths(
    manifest: dict[str, Any],
    *,
    sketch: Path = SKETCH,
    builder_path: Path = BUILDER_PATH,
) -> tuple[Path, ...]:
    """Return only repository bytes that can change the compiled image."""

    del manifest  # The fixed manifest path itself is part of the byte closure.
    semantic_paths = {
        *(_bound_repository_file(path) for path in EXPECTED_PROFILE_BINDINGS.values()),
        *(_bound_repository_file(path) for path in EXPECTED_CONTRACT_BINDINGS.values()),
    }
    return tuple(
        sorted(
            {
                path.resolve()
                for path in sketch.rglob("*")
                if path.is_file()
                and path.name != GENERATED_HEADER_NAME
                and path.suffix in FIRMWARE_SOURCE_SUFFIXES
            }
            | {
                DEFAULT_MANIFEST.resolve(),
                builder_path.resolve(),
                FIRMWARE_HOST_BINDING_HELPER.resolve(),
                FIRMWARE_BINARY_HELPER.resolve(),
                (REPO_ROOT / "tools/generate_reference_acceptance_policy.py").resolve(),
                *semantic_paths,
            },
            key=lambda path: path.relative_to(REPO_ROOT).as_posix(),
        )
    )


def operational_source_pathspecs(
    manifest: dict[str, Any] | None = None,
) -> tuple[str, ...]:
    """Return the exact Git paths whose bytes define the firmware image."""

    selected = manifest or load_manifest()
    return tuple(
        path.relative_to(REPO_ROOT).as_posix() for path in source_input_paths(selected)
    )


def _input_binding(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "path": path.relative_to(REPO_ROOT).as_posix(),
        "sha256": sha256(data).hexdigest(),
        "size_bytes": len(data),
    }


def firmware_input_report(
    manifest: dict[str, Any],
    *,
    sketch: Path = SKETCH,
    builder_path: Path = BUILDER_PATH,
) -> dict[str, Any]:
    """Bind the exact path and byte inventory that can affect compilation."""

    entries = [
        _input_binding(path)
        for path in source_input_paths(
            manifest, sketch=sketch, builder_path=builder_path
        )
    ]
    unsigned = {
        "schema_version": 1,
        "contract": FIRMWARE_INPUT_CONTRACT,
        "entries": entries,
    }
    return {**unsigned, "set_sha256": _sha256_json(unsigned)}


def source_input_hash(
    manifest: dict[str, Any],
    *,
    sketch: Path = SKETCH,
    builder_path: Path = BUILDER_PATH,
) -> str:
    """Return the canonical identity of the exact firmware input inventory."""

    return str(
        firmware_input_report(manifest, sketch=sketch, builder_path=builder_path)[
            "set_sha256"
        ]
    )


def _configuration_payload(
    manifest: dict[str, Any],
    config_source_sha256: str,
    profile_bindings: dict[str, dict[str, Any]],
    contract_bindings: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    return {
        "schema_version": 2,
        "image_id": manifest["image"]["id"],
        "firmware_version": manifest["image"]["firmware_version"],
        "fqbn": manifest["target"]["fqbn"],
        "config_source_sha256": config_source_sha256,
        "profile_bindings": profile_bindings,
        "contract_bindings": contract_bindings,
        "forwarded_clock_contract": manifest["forwarded_clock_contract"],
    }


def _git_firmware_audit_revision(
    pathspecs: tuple[str, ...], *, repo_root: Path = REPO_ROOT
) -> str:
    """Return the latest commit that changed any firmware input path."""

    if not pathspecs:
        raise BuildError("firmware source path set is empty")
    revision = _run(
        ["git", "log", "-1", "--format=%H", "--", *pathspecs],
        cwd=repo_root,
    ).stdout.strip()
    if not HEX40_PATTERN.fullmatch(revision):
        raise BuildError("firmware input history has no exact audit revision")
    return revision


def capture_source_state(manifest: dict[str, Any]) -> dict[str, Any]:
    """Capture firmware-only identity, independent of unrelated host HEAD."""

    config_source_sha256 = sha256(CONFIG_HEADER.read_bytes()).hexdigest()
    profiles = profile_binding_report(manifest)
    contracts = contract_binding_report(manifest)
    inputs = firmware_input_report(manifest)
    pathspecs = operational_source_pathspecs(manifest)
    _, source_state = _git_identity(pathspecs=pathspecs)
    configuration = _configuration_payload(
        manifest, config_source_sha256, profiles, contracts
    )
    return {
        "firmware_audit_revision": _git_firmware_audit_revision(pathspecs),
        "source_state": source_state,
        "source_sha256": inputs["set_sha256"],
        "firmware_inputs": inputs,
        "config_source_sha256": config_source_sha256,
        "config_sha256": _sha256_json(configuration),
        "profile_bindings": profiles,
        "contract_bindings": contracts,
    }


def repository_context_report() -> dict[str, Any]:
    """Record repository state without granting it firmware identity authority."""

    git_commit, working_tree_state = _git_identity()
    return {
        "git_commit": git_commit,
        "working_tree_state": working_tree_state,
        "firmware_identity_authority": False,
    }


def _assert_source_unchanged(expected: dict[str, Any], actual: dict[str, Any]) -> None:
    changed = sorted(key for key in expected if expected[key] != actual.get(key))
    if changed:
        raise BuildError(
            "firmware build input changed during compilation: " + ", ".join(changed)
        )


def _verify_installed_environment(environment: dict[str, str]) -> None:
    _require_installed_hash(
        "Arduino core",
        Path(environment["core_path"]),
        environment["core_installed_sha256"],
    )
    _require_installed_hash(
        "compiler toolchain",
        Path(environment["toolchain_path"]),
        environment["toolchain_installed_sha256"],
    )


def build_provenance(
    manifest: dict[str, Any],
    environment: dict[str, str],
    source: dict[str, Any],
    build_session_id: str,
) -> dict[str, Any]:
    if not SESSION_ID_PATTERN.fullmatch(build_session_id):
        raise BuildError("build session id must be 16 lowercase hexadecimal digits")
    configuration = _configuration_payload(
        manifest,
        source["config_source_sha256"],
        source["profile_bindings"],
        source["contract_bindings"],
    )
    source_identity = {
        "firmware_audit_revision": source["firmware_audit_revision"],
        "state": source["source_state"],
        "sha256": source["source_sha256"],
    }
    target_identity = {
        **manifest["target"],
        "board_id": environment["board_id"],
        "board_name": environment["board_name"],
    }
    toolchain_identity = {
        **manifest["toolchain"],
        "compiler_identity": environment["compiler_identity"],
    }
    invocation_payload = {
        "builder_id": manifest["builder_id"],
        "builder_version": BUILDER_VERSION,
        "build_session_id": build_session_id,
        "source": source_identity,
        "firmware_inputs": source["firmware_inputs"],
        "configuration_sha256": source["config_sha256"],
        "target": target_identity,
        "toolchain": toolchain_identity,
        "arduino_cli_version": environment["arduino_cli_version"],
    }
    return {
        "schema_version": 2,
        "source": source_identity,
        "firmware_inputs": source["firmware_inputs"],
        "configuration": {**configuration, "sha256": source["config_sha256"]},
        "target": target_identity,
        "toolchain": toolchain_identity,
        "invocation": {
            "builder_id": manifest["builder_id"],
            "arduino_cli_version": environment["arduino_cli_version"],
            "build_session_id": build_session_id,
            "id": _sha256_json(invocation_payload),
        },
    }


def generated_provenance_values(provenance: dict[str, Any]) -> dict[str, str]:
    """Use the independent v2 provenance projection shared with UF2 audit."""

    return firmware_binary.expected_provenance_values(provenance)


def provenance_header(provenance: dict[str, Any]) -> str:
    config = provenance["configuration"]
    invocation = provenance["invocation"]
    generated = generated_provenance_values(provenance)
    lines = [
        "// Generated into a one-use temporary sketch.",
        "#ifndef OTIS_BUILD_SESSION_ID",
        '#error "OTIS builder session flag is required."',
        "#endif",
        f"#if OTIS_BUILD_SESSION_ID != 0x{invocation['build_session_id']}ULL",
        '#error "OTIS builder session flag does not match this manifest."',
        "#endif",
        "#undef OTIS_BUILD_SESSION_ID",
        "",
    ]
    lines.extend(
        [
            "#ifdef OTIS_BUILD_MANIFEST_GENERATED",
            '#error "OTIS build manifest was externally defined or included twice."',
            "#endif",
            "#define OTIS_BUILD_MANIFEST_GENERATED 1",
            "",
        ]
    )
    for name, value in sorted(generated.items()):
        lines.extend(
            [
                f"#ifdef {name}",
                f'#error "{name} was externally pre-defined."',
                "#endif",
                f"#define {name} {json.dumps(str(value), ensure_ascii=True)}",
            ]
        )
    frequency_tag = config["profile_bindings"]["frequency_estimator"]["sha256"][:16]
    lines.extend(
        [
            "#ifdef OTIS_BUILD_FREQUENCY_ESTIMATOR_TAG_U64",
            '#error "OTIS_BUILD_FREQUENCY_ESTIMATOR_TAG_U64 was externally pre-defined."',
            "#endif",
            f"#define OTIS_BUILD_FREQUENCY_ESTIMATOR_TAG_U64 0x{frequency_tag}ULL",
        ]
    )
    lines.append("")
    return "\n".join(lines)


def _path_has_symlink_component(path: Path) -> bool:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _validate_output_dir(path: Path) -> None:
    if _path_has_symlink_component(path):
        raise BuildError(f"firmware output path traverses a symbolic link: {path}")
    if path.exists() and not path.is_dir():
        raise BuildError(f"firmware output path is not a directory: {path}")


def _reject_descendant_symlinks(path: Path) -> None:
    if not path.exists():
        return
    for root, directory_names, file_names in os.walk(path, followlinks=False):
        root_path = Path(root)
        for name in [*directory_names, *file_names]:
            candidate = root_path / name
            if candidate.is_symlink():
                raise BuildError(
                    f"firmware output contains a symbolic link: {candidate}"
                )


def _artifact_hashes(artifacts_dir: Path) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for suffix in EXPECTED_ARTIFACT_SUFFIXES:
        matches = sorted(
            path
            for path in artifacts_dir.iterdir()
            if path.is_file() and path.suffix == suffix
        )
        if len(matches) != 1:
            raise BuildError(
                f"successful build must produce exactly one {suffix} artifact; "
                f"found {len(matches)}"
            )
        path = matches[0]
        artifacts.append(
            {
                "name": path.name,
                "size_bytes": path.stat().st_size,
                "sha256": sha256(path.read_bytes()).hexdigest(),
            }
        )
    return sorted(artifacts, key=lambda item: item["name"])


def _resource_usage(build_output: str) -> dict[str, int]:
    program_match = PROGRAM_USAGE_PATTERN.search(build_output)
    memory_match = DYNAMIC_MEMORY_USAGE_PATTERN.search(build_output)
    if program_match is None or memory_match is None:
        raise BuildError("firmware build omitted its resource usage report")
    usage = {
        "program_storage_used_bytes": int(program_match.group(1)),
        "program_storage_total_bytes": int(program_match.group(2)),
        "static_dynamic_memory_used_bytes": int(memory_match.group(1)),
        "runtime_memory_available_bytes": int(memory_match.group(2)),
        "dynamic_memory_total_bytes": int(memory_match.group(3)),
    }
    if (
        usage["static_dynamic_memory_used_bytes"]
        + usage["runtime_memory_available_bytes"]
        != usage["dynamic_memory_total_bytes"]
    ):
        raise BuildError("firmware resource usage report is inconsistent")
    return usage


def _resource_report(manifest: dict[str, Any], usage: dict[str, int]) -> dict[str, Any]:
    budget = manifest["resource_budget"]
    if usage["dynamic_memory_total_bytes"] != budget["dynamic_memory_total_bytes"]:
        raise BuildError("firmware build reported an unexpected RAM total")
    if (
        usage["static_dynamic_memory_used_bytes"]
        > budget["static_dynamic_memory_max_bytes"]
    ):
        raise BuildError("static dynamic-memory maximum exceeded")
    if (
        usage["runtime_memory_available_bytes"]
        < budget["runtime_memory_reserve_min_bytes"]
    ):
        raise BuildError("runtime memory reserve is below minimum")
    return {
        "contract": "otis_firmware_resource_budget_v1",
        "status": "within_budget",
        "budget": dict(budget),
        "observed": usage,
    }


def _binary_report(artifacts_dir: Path, provenance: dict[str, Any]) -> dict[str, Any]:
    uf2_paths = sorted(artifacts_dir.glob("*.uf2"))
    if len(uf2_paths) != 1:
        raise BuildError("binary audit requires exactly one flashable UF2")
    try:
        verification = firmware_binary.verify_uf2(
            uf2_paths[0],
            firmware_inputs=provenance["firmware_inputs"],
            provenance=provenance,
        )
        return firmware_binary.binary_contract_from_verification(verification)
    except ValueError as error:
        raise BuildError(str(error)) from error


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def build_firmware(
    manifest: dict[str, Any],
    output_dir: Path,
    *,
    arduino_cli: str,
    build_session_id: str | None = None,
) -> dict[str, Any]:
    if build_session_id is not None and not SESSION_ID_PATTERN.fullmatch(
        build_session_id
    ):
        raise BuildError("build session id must be 16 lowercase hexadecimal digits")
    _validate_output_dir(output_dir)
    build_dir = output_dir / "build"
    artifacts_dir = output_dir / "artifacts"
    for path in (build_dir, artifacts_dir):
        _validate_output_dir(path)
        path.mkdir(parents=True, exist_ok=True)
        _reject_descendant_symlinks(path)
    for path in artifacts_dir.iterdir():
        if path.is_file() and not path.is_symlink():
            path.unlink()
    environment = verify_environment(manifest, arduino_cli=arduino_cli)
    source = capture_source_state(manifest)
    provenance = build_provenance(
        manifest,
        environment,
        source,
        build_session_id if build_session_id is not None else secrets.token_hex(8),
    )
    generated_header_text = provenance_header(provenance)
    with tempfile.TemporaryDirectory(
        prefix="temporary_sketch_", dir=output_dir
    ) as root:
        temporary_sketch = Path(root) / SKETCH.name
        shutil.copytree(SKETCH, temporary_sketch)
        (temporary_sketch / GENERATED_HEADER_NAME).write_text(
            generated_header_text, encoding="utf-8"
        )
        command = [
            arduino_cli,
            "compile",
            "--clean",
            "--fqbn",
            str(manifest["target"]["fqbn"]),
            "--build-path",
            str(build_dir),
            "--output-dir",
            str(artifacts_dir),
            "--build-property",
            (
                "compiler.cpp.extra_flags="
                f"-DOTIS_BUILD_SESSION_ID=0x{provenance['invocation']['build_session_id']}ULL"
            ),
            str(temporary_sketch),
        ]
        result = _run(command, check=False)
        combined = result.stdout + result.stderr
        (output_dir / "build.log").write_text(combined, encoding="utf-8")
        _assert_source_unchanged(source, capture_source_state(manifest))
    if result.returncode != 0:
        raise BuildError(
            f"fixed firmware compile failed; see {(output_dir / 'build.log').resolve()}"
        )
    _verify_installed_environment(environment)
    (artifacts_dir / GENERATED_HEADER_NAME).write_text(
        generated_header_text, encoding="utf-8"
    )
    resource = _resource_report(manifest, _resource_usage(combined))
    binary = _binary_report(artifacts_dir, provenance)
    artifacts = _artifact_hashes(artifacts_dir)
    build_manifest_path = artifacts_dir / "firmware_build_manifest.json"
    _write_json(
        build_manifest_path,
        {
            "schema_version": 1,
            "capabilities": manifest["capabilities"],
            "provenance": provenance,
            "repository_context": repository_context_report(),
            "resource_budget": resource,
            "binary_contract": binary,
            "artifacts": artifacts,
        },
    )
    return {
        "image_id": IMAGE_ID,
        "outcome": "pass",
        "verified": True,
        "config_sha256": provenance["configuration"]["sha256"],
        "invocation_id": provenance["invocation"]["id"],
        "build_log": str((output_dir / "build.log").resolve()),
        "build_manifest": str(build_manifest_path.resolve()),
        "resource_usage": resource["observed"],
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compile the fixed OTIS adaptive-hybrid firmware image."
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "build" / "firmware",
        help="Ignored build/artifact directory.",
    )
    parser.add_argument(
        "--check-environment",
        action="store_true",
        help="Verify the pinned CLI/core/toolchain without compiling.",
    )
    parser.add_argument(
        "--build-session-id",
        type=_build_session_id_argument,
        help=(
            "Use this exact 16-character lowercase hexadecimal build session "
            "identity; omitted builds generate a random identity."
        ),
    )
    parser.add_argument("--arduino-cli", default="arduino-cli")
    args = parser.parse_args(argv)
    try:
        manifest = load_manifest()
        if args.check_environment:
            print(
                json.dumps(
                    verify_environment(manifest, arduino_cli=args.arduino_cli),
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        print(f"[build] {IMAGE_ID}", flush=True)
        result = build_firmware(
            manifest,
            args.output_dir.absolute(),
            arduino_cli=args.arduino_cli,
            build_session_id=args.build_session_id,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0
    except (BuildError, json.JSONDecodeError, OSError, ValueError) as exc:
        print(f"firmware build error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
