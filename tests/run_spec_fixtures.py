from __future__ import annotations

import json
from hashlib import sha256
from pathlib import Path

from host.otis_tools import firmware_artifact, run_spec
from host.otis_tools.firmware_artifact import ValidatedFirmwareArtifact
from tools import build_firmware


def canonical_sha256(value: object) -> str:
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()


def synthetic_firmware_document(tmp_path: Path) -> dict:
    input_unsigned = {
        "schema_version": 1,
        "contract": build_firmware.FIRMWARE_INPUT_CONTRACT,
        "entries": [
            {"path": "firmware/source.cpp", "sha256": "1" * 64, "size_bytes": 12}
        ],
    }
    inputs = {**input_unsigned, "set_sha256": canonical_sha256(input_unsigned)}
    configuration_unsigned = {
        "schema_version": 2,
        "image_id": build_firmware.IMAGE_ID,
        "firmware_version": build_firmware.FIRMWARE_VERSION,
        "fqbn": "rp2040:rp2040:arduino_nano_connect:freq=133",
        "config_source_sha256": "2" * 64,
        "profile_bindings": {},
        "contract_bindings": {},
        "forwarded_clock_contract": {},
    }
    configuration = {
        **configuration_unsigned,
        "sha256": canonical_sha256(configuration_unsigned),
    }
    source = {
        "firmware_audit_revision": "3" * 40,
        "state": "clean",
        "sha256": inputs["set_sha256"],
    }
    target = {
        "fqbn": configuration["fqbn"],
        "board_id": "synthetic",
        "board_name": "synthetic",
    }
    toolchain = {"compiler_identity": "synthetic", "installed_sha256": "4" * 64}
    invocation_payload = {
        "builder_id": "otis_fixed_firmware_builder_v1",
        "builder_version": build_firmware.BUILDER_VERSION,
        "build_session_id": "0123456789abcdef",
        "source": source,
        "firmware_inputs": inputs,
        "configuration_sha256": configuration["sha256"],
        "target": target,
        "toolchain": toolchain,
        "arduino_cli_version": "1.4.1",
    }
    provenance = {
        "schema_version": 2,
        "source": source,
        "firmware_inputs": inputs,
        "configuration": configuration,
        "target": target,
        "toolchain": toolchain,
        "invocation": {
            "builder_id": "otis_fixed_firmware_builder_v1",
            "arduino_cli_version": "1.4.1",
            "build_session_id": "0123456789abcdef",
            "id": canonical_sha256(invocation_payload),
        },
    }
    binding = lambda name, digit: {
        "path": str(tmp_path / name),
        "sha256": digit * 64,
        "size_bytes": 128,
    }
    unsigned = {
        "schema_version": 1,
        "contract": firmware_artifact.CONTRACT,
        "image_id": build_firmware.IMAGE_ID,
        "build_manifest": binding("firmware_build_manifest.json", "5"),
        "source_revision": source["firmware_audit_revision"],
        "source_state": "clean",
        "source_sha256": source["sha256"],
        "firmware_inputs": inputs,
        "configuration_sha256": configuration["sha256"],
        "build_identity": f"{source['sha256']}:{configuration['sha256']}",
        "uf2": binding("otis.uf2", "6"),
        "generated_header": binding("otis_build_manifest.generated.h", "7"),
        "fqbn": target["fqbn"],
        "target": target,
        "toolchain": toolchain,
        "binary_contract": {
            "contract": "otis_adaptive_hybrid_firmware_binary_v1",
            "status": "verified",
        },
        "independent_binary_verification": {
            "contract": "otis_host_verified_adaptive_hybrid_uf2_v2",
            "status": "verified",
        },
        "resource_budget": {
            "contract": "otis_firmware_resource_budget_v1",
            "status": "within_budget",
        },
        "build_session_id": invocation_payload["build_session_id"],
        "provenance": provenance,
    }
    return {
        **unsigned,
        "firmware_artifact_sha256": firmware_artifact.firmware_artifact_identity_sha256(
            unsigned
        ),
    }


def build_synthetic_spec(
    monkeypatch, tmp_path: Path, *, purpose: str
) -> run_spec.ValidatedRunSpec:
    document = synthetic_firmware_document(tmp_path)
    artifact = ValidatedFirmwareArtifact(
        document, Path(document["build_manifest"]["path"])
    )
    monkeypatch.setattr(run_spec, "load_firmware_artifact", lambda _path: artifact)
    return run_spec.build_run_spec(
        firmware_manifest_path=tmp_path / "ignored.json",
        purpose=purpose,
        output_path=tmp_path / run_spec.RUN_SPEC_FILENAME,
        created_utc="2026-09-12T10:00:00Z",
    )
