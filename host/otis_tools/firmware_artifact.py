"""Immutable firmware artifact validation and explicit reproduction.

Loading an artifact is a pure retained-byte operation.  Compilation and current
checkout inspection exist only in :func:`reproduce_firmware`.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from tools import build_firmware

from . import firmware_binary

CONTRACT = "otis_firmware_artifact_v1"
REPRODUCTION_CONTRACT = "otis_firmware_reproduction_receipt_v1"
_HEX16 = re.compile(r"^[0-9a-f]{16}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_EXPECTED_ARTIFACT_SUFFIXES = frozenset({".bin", ".elf", ".h", ".map", ".uf2"})


def _canonical_bytes(value: object) -> bytes:
    try:
        return json.dumps(
            value,
            ensure_ascii=True,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii")
    except (TypeError, ValueError) as error:
        raise ValueError("firmware artifact is not canonical JSON") from error


def _canonical_sha256(value: object) -> str:
    return sha256(_canonical_bytes(value)).hexdigest()


def firmware_artifact_identity_sha256(value: dict[str, Any]) -> str:
    """Hash artifact content identities while retaining paths as opaque provenance."""

    payload = {
        key: item for key, item in value.items() if key != "firmware_artifact_sha256"
    }
    # The retained build manifest binding is an audit locator.  Its bytes include
    # non-authoritative repository context, while every firmware-bearing field
    # from that manifest is independently embedded below.
    payload["build_manifest"] = {"role": "historical_build_record"}
    for name in ("uf2", "generated_header"):
        binding = payload.get(name)
        if isinstance(binding, dict):
            payload[name] = {
                "sha256": binding.get("sha256"),
                "size_bytes": binding.get("size_bytes"),
            }
    return _canonical_sha256(payload)


def _file_binding(path: Path) -> dict[str, Any]:
    source = path.expanduser()
    if source.is_symlink():
        raise ValueError(f"firmware artifact is not a regular file: {source}")
    path = source.resolve(strict=True)
    if not path.is_file():
        raise ValueError(f"firmware artifact is not a regular file: {source}")
    data = path.read_bytes()
    return {
        "path": str(path),
        "sha256": sha256(data).hexdigest(),
        "size_bytes": len(data),
    }


def _object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ValueError(f"firmware build manifest is unreadable: {path}") from error
    if not isinstance(value, dict):
        raise TypeError("firmware build manifest root must be an object")
    return value


def _validate_input_set(value: object) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != {
        "schema_version",
        "contract",
        "entries",
        "set_sha256",
    }:
        raise ValueError("firmware input set is malformed")
    unsigned = {key: item for key, item in value.items() if key != "set_sha256"}
    entries = value.get("entries")
    if (
        value.get("schema_version") != 1
        or value.get("contract") != build_firmware.FIRMWARE_INPUT_CONTRACT
        or value.get("set_sha256") != _canonical_sha256(unsigned)
        or not isinstance(entries, list)
        or not entries
    ):
        raise ValueError("firmware input-set identity differs")
    paths: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "path",
            "sha256",
            "size_bytes",
        }:
            raise ValueError("firmware input binding is malformed")
        relative = entry.get("path")
        relative_path = Path(str(relative))
        if (
            not isinstance(relative, str)
            or relative_path.is_absolute()
            or not relative_path.parts
            or any(part in {"", ".", ".."} for part in relative_path.parts)
            or not _HEX64.fullmatch(str(entry.get("sha256", "")))
            or not isinstance(entry.get("size_bytes"), int)
            or isinstance(entry.get("size_bytes"), bool)
            or entry["size_bytes"] < 0
        ):
            raise ValueError("firmware input binding is unsafe or malformed")
        paths.append(relative)
    if paths != sorted(set(paths)):
        raise ValueError("firmware input bindings are duplicated or not ordered")
    return json.loads(_canonical_bytes(value))


def _validate_provenance(value: object) -> dict[str, Any]:
    if (
        not isinstance(value, dict)
        or set(value)
        != {
            "schema_version",
            "source",
            "firmware_inputs",
            "configuration",
            "target",
            "toolchain",
            "invocation",
        }
        or value.get("schema_version") != 2
    ):
        raise ValueError("firmware provenance is malformed")
    source = value.get("source")
    configuration = value.get("configuration")
    target = value.get("target")
    toolchain = value.get("toolchain")
    invocation = value.get("invocation")
    if not all(
        isinstance(item, dict)
        for item in (source, configuration, target, toolchain, invocation)
    ):
        raise ValueError("firmware provenance components are malformed")
    inputs = _validate_input_set(value.get("firmware_inputs"))
    if (
        set(source) != {"firmware_audit_revision", "state", "sha256"}
        or not _HEX40.fullmatch(str(source.get("firmware_audit_revision", "")))
        or source.get("state") != "clean"
        or source.get("sha256") != inputs["set_sha256"]
    ):
        raise ValueError("firmware source identity differs")
    config_unsigned = {
        key: item for key, item in configuration.items() if key != "sha256"
    }
    if (
        configuration.get("schema_version") != 2
        or configuration.get("image_id") != build_firmware.IMAGE_ID
        or configuration.get("firmware_version") != build_firmware.FIRMWARE_VERSION
        or configuration.get("sha256") != _canonical_sha256(config_unsigned)
        or "schema_bindings" in configuration
    ):
        raise ValueError("firmware configuration identity differs")
    if not isinstance(target.get("fqbn"), str) or not isinstance(
        toolchain.get("compiler_identity"), str
    ):
        raise TypeError("firmware target or toolchain identity is incomplete")
    session = invocation.get("build_session_id")
    payload = {
        "builder_id": invocation.get("builder_id"),
        "builder_version": build_firmware.BUILDER_VERSION,
        "build_session_id": session,
        "source": source,
        "firmware_inputs": inputs,
        "configuration_sha256": configuration["sha256"],
        "target": target,
        "toolchain": toolchain,
        "arduino_cli_version": invocation.get("arduino_cli_version"),
    }
    if (
        invocation.get("builder_id") != "otis_fixed_firmware_builder_v1"
        or not _HEX16.fullmatch(str(session or ""))
        or invocation.get("id") != _canonical_sha256(payload)
    ):
        raise ValueError("firmware invocation identity differs")
    return json.loads(_canonical_bytes(value))


def _artifact_paths(manifest_path: Path, manifest: dict[str, Any]) -> dict[str, Path]:
    raw = manifest.get("artifacts")
    if (
        not isinstance(raw, list)
        or not raw
        or any(not isinstance(item, dict) for item in raw)
    ):
        raise ValueError("firmware artifact inventory is malformed")
    result: dict[str, Path] = {}
    suffixes: set[str] = set()
    for item in raw:
        if set(item) != {"name", "sha256", "size_bytes"}:
            raise ValueError("firmware artifact binding is malformed")
        name = item.get("name")
        if not isinstance(name, str) or Path(name).name != name or name in result:
            raise ValueError("firmware artifact name is unsafe or duplicated")
        if not _HEX64.fullmatch(str(item.get("sha256", ""))) or not isinstance(
            item.get("size_bytes"), int
        ):
            raise ValueError("firmware artifact identity is malformed")
        path = manifest_path.parent / name
        binding = _file_binding(path)
        if (
            binding["sha256"] != item["sha256"]
            or binding["size_bytes"] != item["size_bytes"]
        ):
            raise ValueError(f"firmware artifact bytes differ: {name}")
        result[name] = path.resolve()
        suffixes.add(path.suffix)
    if suffixes != _EXPECTED_ARTIFACT_SUFFIXES or len(result) != len(
        _EXPECTED_ARTIFACT_SUFFIXES
    ):
        raise ValueError(
            "firmware build must retain exactly one artifact of each required type"
        )
    return result


def _validated_document(manifest_path: Path) -> dict[str, Any]:
    source = manifest_path.expanduser()
    if source.is_symlink():
        raise ValueError("firmware build manifest must be a regular file")
    manifest_path = source.resolve(strict=True)
    if not manifest_path.is_file():
        raise ValueError("firmware build manifest must be a regular file")
    manifest = _object(manifest_path)
    if (
        set(manifest)
        != {
            "schema_version",
            "capabilities",
            "provenance",
            "repository_context",
            "resource_budget",
            "binary_contract",
            "artifacts",
        }
        or manifest.get("schema_version") != 1
    ):
        raise ValueError("firmware build manifest shape differs")
    provenance = _validate_provenance(manifest.get("provenance"))
    repository_context = manifest.get("repository_context")
    if (
        not isinstance(repository_context, dict)
        or repository_context.get("firmware_identity_authority") is not False
    ):
        raise ValueError("firmware repository context claims identity authority")
    resource = manifest.get("resource_budget")
    if (
        not isinstance(resource, dict)
        or resource.get("contract") != "otis_firmware_resource_budget_v1"
        or resource.get("status") != "within_budget"
    ):
        raise ValueError("firmware resource budget is not verified")
    binary = manifest.get("binary_contract")
    if (
        not isinstance(binary, dict)
        or binary.get("contract") != "otis_adaptive_hybrid_firmware_binary_v1"
        or binary.get("status") != "verified"
    ):
        raise ValueError("firmware binary contract is not verified")
    paths = _artifact_paths(manifest_path, manifest)
    uf2_paths = [path for path in paths.values() if path.suffix == ".uf2"]
    header_paths = [
        path
        for path in paths.values()
        if path.name == build_firmware.GENERATED_HEADER_NAME
    ]
    if len(uf2_paths) != 1 or len(header_paths) != 1:
        raise ValueError("firmware build omits its UF2 or generated provenance header")
    expected_header = build_firmware.provenance_header(provenance).encode("utf-8")
    if header_paths[0].read_bytes() != expected_header:
        raise ValueError("generated firmware provenance header differs")
    independent = firmware_binary.verify_uf2(
        uf2_paths[0],
        firmware_inputs=provenance["firmware_inputs"],
        provenance=provenance,
    )
    if binary != firmware_binary.binary_contract_from_verification(independent):
        raise ValueError(
            "firmware binary report differs from independent UF2 verification"
        )
    source = provenance["source"]
    configuration = provenance["configuration"]
    artifact_unsigned = {
        "schema_version": 1,
        "contract": CONTRACT,
        "image_id": configuration["image_id"],
        "build_manifest": _file_binding(manifest_path),
        "source_revision": source["firmware_audit_revision"],
        "source_state": source["state"],
        "source_sha256": source["sha256"],
        "firmware_inputs": provenance["firmware_inputs"],
        "configuration_sha256": configuration["sha256"],
        "build_identity": f"{source['sha256']}:{configuration['sha256']}",
        "uf2": _file_binding(uf2_paths[0]),
        "generated_header": _file_binding(header_paths[0]),
        "fqbn": provenance["target"]["fqbn"],
        "target": provenance["target"],
        "toolchain": provenance["toolchain"],
        "binary_contract": binary,
        "independent_binary_verification": independent,
        "resource_budget": resource,
        "build_session_id": provenance["invocation"]["build_session_id"],
        "provenance": provenance,
    }
    return {
        **artifact_unsigned,
        "firmware_artifact_sha256": firmware_artifact_identity_sha256(
            artifact_unsigned
        ),
    }


@dataclass(frozen=True, slots=True, init=False)
class ValidatedFirmwareArtifact:
    _encoded: str
    path: Path
    firmware_artifact_sha256: str

    def __init__(self, document: dict[str, Any], path: Path) -> None:
        encoded = _canonical_bytes(document).decode("ascii")
        object.__setattr__(self, "_encoded", encoded)
        object.__setattr__(self, "path", path.resolve())
        object.__setattr__(
            self, "firmware_artifact_sha256", document["firmware_artifact_sha256"]
        )

    def document(self) -> dict[str, Any]:
        return json.loads(self._encoded)

    @property
    def sha256(self) -> str:
        return self.firmware_artifact_sha256

    @property
    def build_identity(self) -> str:
        return str(self.document()["build_identity"])

    @property
    def binary_binding(self) -> dict[str, Any]:
        return dict(self.document()["uf2"])

    @property
    def firmware_inputs(self) -> dict[str, Any]:
        return dict(self.document()["firmware_inputs"])


def validate_frozen_firmware_artifact(value: object) -> ValidatedFirmwareArtifact:
    """Validate a self-contained recorded artifact without opening its old paths."""

    if not isinstance(value, dict):
        raise TypeError("frozen firmware artifact is malformed")
    expected_keys = {
        "schema_version",
        "contract",
        "image_id",
        "build_manifest",
        "source_revision",
        "source_state",
        "source_sha256",
        "firmware_inputs",
        "configuration_sha256",
        "build_identity",
        "uf2",
        "generated_header",
        "fqbn",
        "target",
        "toolchain",
        "binary_contract",
        "independent_binary_verification",
        "resource_budget",
        "build_session_id",
        "provenance",
        "firmware_artifact_sha256",
    }
    if (
        set(value) != expected_keys
        or value.get("schema_version") != 1
        or value.get("contract") != CONTRACT
    ):
        raise ValueError("frozen firmware artifact shape differs")
    if value.get("firmware_artifact_sha256") != firmware_artifact_identity_sha256(
        value
    ):
        raise ValueError("frozen firmware artifact identity differs")
    provenance = _validate_provenance(value.get("provenance"))
    source = provenance["source"]
    configuration = provenance["configuration"]
    if (
        value.get("image_id") != configuration["image_id"]
        or value.get("source_revision") != source["firmware_audit_revision"]
        or value.get("source_state") != source["state"]
        or value.get("source_sha256") != source["sha256"]
        or value.get("firmware_inputs") != provenance["firmware_inputs"]
        or value.get("configuration_sha256") != configuration["sha256"]
        or value.get("build_identity")
        != f"{source['sha256']}:{configuration['sha256']}"
        or value.get("fqbn") != provenance["target"]["fqbn"]
        or value.get("target") != provenance["target"]
        or value.get("toolchain") != provenance["toolchain"]
        or value.get("build_session_id") != provenance["invocation"]["build_session_id"]
    ):
        raise ValueError("frozen firmware artifact fields contradict provenance")
    binary = value.get("binary_contract")
    independent = value.get("independent_binary_verification")
    resource = value.get("resource_budget")
    if (
        not isinstance(binary, dict)
        or binary.get("contract") != "otis_adaptive_hybrid_firmware_binary_v1"
        or binary.get("status") != "verified"
        or not isinstance(independent, dict)
        or independent.get("contract") != "otis_host_verified_adaptive_hybrid_uf2_v2"
        or independent.get("status") != "verified"
        or not isinstance(resource, dict)
        or resource.get("contract") != "otis_firmware_resource_budget_v1"
        or resource.get("status") != "within_budget"
    ):
        raise ValueError("frozen firmware verification reports differ")
    for name in ("build_manifest", "uf2", "generated_header"):
        binding = value.get(name)
        if (
            not isinstance(binding, dict)
            or set(binding) != {"path", "sha256", "size_bytes"}
            or not isinstance(binding.get("path"), str)
            or not _HEX64.fullmatch(str(binding.get("sha256", "")))
            or not isinstance(binding.get("size_bytes"), int)
            or isinstance(binding.get("size_bytes"), bool)
            or binding["size_bytes"] <= 0
        ):
            raise ValueError(f"frozen firmware {name} binding is malformed")
    return ValidatedFirmwareArtifact(
        json.loads(_canonical_bytes(value)), Path(str(value["build_manifest"]["path"]))
    )


def load_firmware_artifact(build_manifest_path: Path) -> ValidatedFirmwareArtifact:
    document = _validated_document(build_manifest_path)
    return validate_frozen_firmware_artifact(document)


def reproduce_firmware(
    artifact: ValidatedFirmwareArtifact,
    *,
    output_dir: Path,
    arduino_cli: str = "arduino-cli",
) -> dict[str, Any]:
    """Explicitly rebuild one artifact from matching current firmware inputs."""

    retained = artifact.document()
    current_manifest = build_firmware.load_manifest()
    current = build_firmware.capture_source_state(current_manifest)
    provenance = retained["provenance"]
    if (
        current["source_state"] != "clean"
        or current["source_sha256"] != retained["source_sha256"]
        or current["firmware_audit_revision"] != retained["source_revision"]
        or current["config_sha256"] != retained["configuration_sha256"]
        or current["firmware_inputs"] != retained["firmware_inputs"]
    ):
        raise ValueError("current firmware inputs differ from the retained artifact")
    result = build_firmware.build_firmware(
        current_manifest,
        output_dir.resolve(),
        arduino_cli=arduino_cli,
        build_session_id=retained["build_session_id"],
    )
    reproduced_manifest_path = Path(str(result["build_manifest"]))
    reproduced = load_firmware_artifact(reproduced_manifest_path)
    reproduced_document = reproduced.document()
    if reproduced_document["provenance"] != provenance:
        raise ValueError("reproduced firmware provenance differs")
    if reproduced_document["uf2"]["sha256"] != retained["uf2"]["sha256"]:
        raise ValueError("reproduced firmware binary differs")
    unsigned = {
        "schema_version": 1,
        "contract": REPRODUCTION_CONTRACT,
        "status": "verified",
        "firmware_artifact_sha256": artifact.sha256,
        "firmware_input_set_sha256": retained["firmware_inputs"]["set_sha256"],
        "configuration_sha256": retained["configuration_sha256"],
        "build_session_id": retained["build_session_id"],
        "uf2_sha256": retained["uf2"]["sha256"],
        "reproduced_build_manifest": reproduced_document["build_manifest"],
        "reproduced_uf2": reproduced_document["uf2"],
    }
    return {**unsigned, "receipt_sha256": _canonical_sha256(unsigned)}
