"""Independent host inspection of the flashable OTIS UF2 image."""

from __future__ import annotations

import json
import re
import struct
from hashlib import sha256
from pathlib import Path
from typing import Any

UF2_MAGIC_START_0 = 0x0A324655
UF2_MAGIC_START_1 = 0x9E5D5157
UF2_MAGIC_END = 0x0AB16F30
UF2_BLOCK_BYTES = 512
UF2_DATA_OFFSET = 32
UF2_MAX_PAYLOAD_BYTES = 476
UF2_NOT_MAIN_FLASH = 0x00000001
GNSS_BAUD_PACKET_PATTERN = re.compile(rb"\$PMTK251,[0-9]+\*[0-9A-F]{2}\r\n")
EXPECTED_GNSS_PACKET = b"$PMTK251,115200*1F\r\n"
REQUIRED_MARKERS = {
    "firmware_version": b"OTIS_ADAPTIVE_HYBRID_REGULATION_V1",
    "image_id": b"adaptive_hybrid_regulation",
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
FORBIDDEN_MARKERS = {
    "qualified_forwarded_waveform_claim": b"qualified_10mhz_forwarded",
    "runtime_forwarded_source_selection": b"runtime_forwarded_clock_source_selection",
    "nonzero_fractional_divider": b"fractional_divider_nonzero",
}
PROVENANCE_FORMAT = "otis_fixed_firmware_build_v2"
BUILDER_VERSION = 1


def _canonical_sha256(value: object) -> str:
    return sha256(
        json.dumps(
            value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
        ).encode("ascii")
    ).hexdigest()


def expected_provenance_values(provenance: object) -> dict[str, str]:
    """Independently reconstruct every v2 generated firmware identity."""

    if not isinstance(provenance, dict) or provenance.get("schema_version") != 2:
        raise ValueError("firmware UF2 provenance is malformed")
    source = provenance.get("source")
    firmware_inputs = provenance.get("firmware_inputs")
    config = provenance.get("configuration")
    target = provenance.get("target")
    toolchain = provenance.get("toolchain")
    invocation = provenance.get("invocation")
    if not all(
        isinstance(value, dict)
        for value in (source, firmware_inputs, config, target, toolchain, invocation)
    ):
        raise ValueError("firmware UF2 provenance components are malformed")
    input_unsigned = {
        key: value for key, value in firmware_inputs.items() if key != "set_sha256"
    }
    if (
        firmware_inputs.get("contract") != "otis_firmware_input_set_v1"
        or firmware_inputs.get("set_sha256") != _canonical_sha256(input_unsigned)
        or source.get("sha256") != firmware_inputs.get("set_sha256")
    ):
        raise ValueError("firmware UF2 input-set identity is not independently exact")
    config_unsigned = {key: value for key, value in config.items() if key != "sha256"}
    config_sha256 = config.get("sha256")
    if config.get("schema_version") != 2 or config_sha256 != _canonical_sha256(
        config_unsigned
    ):
        raise ValueError("firmware configuration identity is not independently exact")
    invocation_payload = {
        "builder_id": invocation.get("builder_id"),
        "builder_version": BUILDER_VERSION,
        "build_session_id": invocation.get("build_session_id"),
        "source": source,
        "firmware_inputs": firmware_inputs,
        "configuration_sha256": config_sha256,
        "target": target,
        "toolchain": toolchain,
        "arduino_cli_version": invocation.get("arduino_cli_version"),
    }
    if invocation.get("id") != _canonical_sha256(invocation_payload):
        raise ValueError("firmware invocation identity is not independently exact")
    try:
        profile_bindings = config["profile_bindings"]
        phase_binding = profile_bindings["phase_estimator"]
        generated: dict[str, object] = {
            "OTIS_BUILD_PROVENANCE_FORMAT": PROVENANCE_FORMAT,
            # Existing firmware field names remain stable; the v2 format defines
            # this value as the latest commit affecting firmware input bytes.
            "OTIS_BUILD_GIT_COMMIT": source["firmware_audit_revision"],
            "OTIS_BUILD_SOURCE_STATE": source["state"],
            "OTIS_BUILD_SOURCE_SHA256": source["sha256"],
            "OTIS_BUILD_CONFIG_SHA256": config_sha256,
            "OTIS_BUILD_IMAGE_ID": config["image_id"],
            "OTIS_BUILD_FQBN": target["fqbn"],
            "OTIS_BUILD_BOARD_ID": target["board_id"],
            "OTIS_BUILD_BOARD_NAME": target["board_name"],
            "OTIS_BUILD_CORE_PROVIDER": target["core_provider"],
            "OTIS_BUILD_CORE_VERSION": target["core_version"],
            "OTIS_BUILD_CORE_INSTALLED_SHA256": target["core_installed_sha256"],
            "OTIS_BUILD_TOOLCHAIN": f"{toolchain['name']}@{toolchain['version']}",
            "OTIS_BUILD_COMPILER": toolchain["compiler_identity"],
            "OTIS_BUILD_TOOLCHAIN_INSTALLED_SHA256": toolchain["installed_sha256"],
            "OTIS_BUILD_ARDUINO_CLI_VERSION": invocation["arduino_cli_version"],
            "OTIS_BUILD_INVOCATION_ID": invocation["id"],
            "OTIS_BUILD_FIRMWARE_HOST_CONTRACT_ID": config["contract_bindings"][
                "firmware_host"
            ]["contract_id"],
            "OTIS_BUILD_FIRMWARE_HOST_CONTRACT_SHA256": config["contract_bindings"][
                "firmware_host"
            ]["sha256"],
            "OTIS_BUILD_FORWARDED_CLOCK_CONTRACT_ID": config[
                "forwarded_clock_contract"
            ]["contract_id"],
            "OTIS_BUILD_FORWARDED_CLOCK_CONTRACT_SHA256": _canonical_sha256(
                config["forwarded_clock_contract"]
            ),
            "OTIS_BUILD_PHASE_ESTIMATOR_ID": phase_binding["profile_id"],
            "OTIS_BUILD_PHASE_RAW_METHOD_ID": phase_binding["raw_phase_method"],
            "OTIS_BUILD_SOURCE_IDENTITY_SHA256": _canonical_sha256(source),
            "OTIS_BUILD_TARGET_IDENTITY_SHA256": _canonical_sha256(target),
            "OTIS_BUILD_TOOLCHAIN_IDENTITY_SHA256": _canonical_sha256(toolchain),
            # The established wire key now names the firmware-only input set;
            # PROVENANCE_FORMAT v2 prevents interpretation as the retired global set.
            "OTIS_BUILD_AUTHORITATIVE_INPUT_SET_SHA256": firmware_inputs["set_sha256"],
            "OTIS_BUILD_PROVENANCE_SHA256": _canonical_sha256(provenance),
        }
        macro_by_binding = {
            "adaptive_policy": "OTIS_BUILD_ADAPTIVE_POLICY_SHA256",
            "frequency_estimator": "OTIS_BUILD_FREQUENCY_ESTIMATOR_SHA256",
            "phase_estimator": "OTIS_BUILD_PHASE_ESTIMATOR_SHA256",
            "plant_model": "OTIS_BUILD_PLANT_MODEL_SHA256",
            "response_policy": "OTIS_BUILD_RESPONSE_POLICY_SHA256",
        }
        for binding_name, macro_name in macro_by_binding.items():
            generated[macro_name] = profile_bindings[binding_name]["sha256"]
    except (KeyError, TypeError) as error:
        raise ValueError("firmware UF2 provenance value is unavailable") from error
    string_values = {name: str(value) for name, value in generated.items()}
    string_values["OTIS_BUILD_GENERATED_HEADER_IDENTITY_SHA256"] = _canonical_sha256(
        string_values
    )
    return string_values


def _uf2_payload(path: Path) -> tuple[bytes, int]:
    image = path.read_bytes()
    if not image or len(image) % UF2_BLOCK_BYTES:
        raise ValueError("firmware UF2 block framing is invalid")
    blocks: dict[int, tuple[int, bytes]] = {}
    declared_count: int | None = None
    address_ranges: list[tuple[int, int]] = []
    for offset in range(0, len(image), UF2_BLOCK_BYTES):
        block = image[offset : offset + UF2_BLOCK_BYTES]
        magic0, magic1, flags, target, payload_size, number, count = struct.unpack_from(
            "<7I", block, 0
        )
        end_magic = struct.unpack_from("<I", block, 508)[0]
        if (
            magic0 != UF2_MAGIC_START_0
            or magic1 != UF2_MAGIC_START_1
            or end_magic != UF2_MAGIC_END
            or not 0 < payload_size <= UF2_MAX_PAYLOAD_BYTES
            or flags & UF2_NOT_MAIN_FLASH
        ):
            raise ValueError("firmware UF2 block header is invalid")
        if declared_count is None:
            declared_count = count
        if count != declared_count or number >= count or number in blocks:
            raise ValueError("firmware UF2 block sequence is invalid")
        payload = block[UF2_DATA_OFFSET : UF2_DATA_OFFSET + payload_size]
        blocks[number] = (target, payload)
        address_ranges.append((target, target + payload_size))
    if declared_count != len(blocks) or set(blocks) != set(range(len(blocks))):
        raise ValueError("firmware UF2 block set is incomplete")
    for (_, prior_end), (next_start, _) in zip(
        sorted(address_ranges), sorted(address_ranges)[1:]
    ):
        if next_start < prior_end:
            raise ValueError("firmware UF2 payload addresses overlap")
    payload = b"".join(item[1] for item in sorted(blocks.values()))
    return payload, len(blocks)


def verify_uf2(
    path: Path,
    *,
    firmware_inputs: dict[str, Any],
    provenance: dict[str, Any],
) -> dict[str, Any]:
    """Inspect actual UF2 payload bytes independently of builder assertions."""

    payload, block_count = _uf2_payload(path)
    required = {name: marker in payload for name, marker in REQUIRED_MARKERS.items()}
    missing = sorted(name for name, present in required.items() if not present)
    if missing:
        raise ValueError(
            "firmware UF2 omits independently required markers: " + ", ".join(missing)
        )
    forbidden = {name: marker in payload for name, marker in FORBIDDEN_MARKERS.items()}
    present = sorted(name for name, found in forbidden.items() if found)
    if present:
        raise ValueError(
            "firmware UF2 contains independently forbidden markers: "
            + ", ".join(present)
        )
    profiles = (
        firmware_inputs.get("entries") if isinstance(firmware_inputs, dict) else None
    )
    if not isinstance(profiles, list):
        raise TypeError("firmware UF2 input identity is unavailable")
    profile_hashes = {
        str(binding["path"]): str(binding["sha256"]).encode("ascii") in payload
        for binding in profiles
        if isinstance(binding, dict)
        and isinstance(binding.get("path"), str)
        and str(binding["path"]).startswith("profiles/")
        and isinstance(binding.get("sha256"), str)
    }
    if not profile_hashes or not all(profile_hashes.values()):
        raise ValueError("firmware UF2 omits frozen profile identities")
    exact_provenance = {
        name.removeprefix("OTIS_BUILD_").lower(): value.encode("ascii") in payload
        for name, value in expected_provenance_values(provenance).items()
    }
    missing_provenance = sorted(
        name for name, present in exact_provenance.items() if not present
    )
    if missing_provenance:
        raise ValueError(
            "firmware UF2 omits exact build provenance markers: "
            + ", ".join(missing_provenance)
        )
    packets = set(GNSS_BAUD_PACKET_PATTERN.findall(payload))
    if packets != {EXPECTED_GNSS_PACKET}:
        raise ValueError("firmware UF2 GNSS PMTK251 packet set differs")
    return {
        "contract": "otis_host_verified_adaptive_hybrid_uf2_v2",
        "status": "verified",
        "block_count": block_count,
        "required_markers": required,
        "forbidden_markers_present": forbidden,
        "profile_sha256_markers": profile_hashes,
        "exact_provenance_markers": exact_provenance,
        "gnss_pmtk251_packets": [EXPECTED_GNSS_PACKET.decode("ascii")],
    }


def binary_contract_from_verification(verification: dict[str, Any]) -> dict[str, Any]:
    if (
        verification.get("contract") != "otis_host_verified_adaptive_hybrid_uf2_v2"
        or verification.get("status") != "verified"
    ):
        raise ValueError("firmware verification report is malformed")
    return {
        "contract": "otis_adaptive_hybrid_firmware_binary_v1",
        "status": "verified",
        "required_markers": verification["required_markers"],
        "exact_provenance_markers": verification["exact_provenance_markers"],
        "forbidden_markers_present": verification["forbidden_markers_present"],
        "gnss_pmtk251_packets": verification["gnss_pmtk251_packets"],
        "authority": {
            "reference": "D14",
            "oscillator_count": "D8_GPIO20_GPIN0",
            "d9_control_authority": False,
            "d6_control_authority": False,
            "d10_control_authority": False,
        },
    }
