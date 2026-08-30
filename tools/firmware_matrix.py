#!/usr/bin/env python3
"""Build the intentional OTIS Arduino firmware matrix with exact provenance."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MATRIX = REPO_ROOT / "firmware" / "arduino" / "firmware_matrix.json"
SKETCH = REPO_ROOT / "firmware" / "arduino" / "otis_nano_rp2040_connect"
CONFIG_HEADER = SKETCH / "otis_config.h"
BUILDER_VERSION = 3
PROFILE_ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9_]*$")
DEFINE_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]*$")
DEFINE_VALUE_PATTERN = re.compile(r"^[A-Za-z0-9_()+.,:+*/<>=!-]+$")
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
FORBIDDEN_PROFILE_DEFINES = {
    "OTIS_FIRMWARE_CONFIG_ID",
    "OTIS_FIRMWARE_GIT_COMMIT",
}
PROFILE_SELECTOR_NAMES = {
    "OTIS_SW1_BRINGUP_MODE",
    "OTIS_CAPTURE_BACKEND",
    "OTIS_TCXO_COUNTER_BACKEND",
    "OTIS_ENABLE_PSEUDO_PPS_GENERATOR",
    "OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED",
    "OTIS_PPS_GATE_MIN_INTERVAL_US",
    "OTIS_PPS_GATE_MAX_INTERVAL_US",
    "OTIS_ENABLE_OBSERVE_ONLY_DISCIPLINE_PREVIEW",
    "OTIS_ENABLE_DAC_AD5693R",
    "OTIS_ENABLE_H1_DAC_SWEEP",
    "OTIS_ENABLE_ENV_SENSORS",
}
OPTIONAL_PROFILE_SELECTOR_NAMES = {
    "OTIS_PPS_GATE_STATUS_PERIOD_MS",
    "OTIS_DAC_MIN_CODE",
    "OTIS_DAC_MAX_CODE",
    "OTIS_ENABLE_CX317_I_ONLY_PREVIEW",
    "OTIS_ENABLE_CX318_STAGE4_PREVIEW",
    "OTIS_ENABLE_CX318_STAGE5_PREVIEW",
    "OTIS_INTEGER_COUNT_DEADBAND_INITIAL_CODE",
    "OTIS_INTEGER_COUNT_DEADBAND_INITIAL_DAC_EPOCH",
    "OTIS_ENABLE_STABILIZED_TIGHT_DEADBAND_PREVIEW",
    "OTIS_ENABLE_CX320_ACTIVE_HYBRID",
    "OTIS_ENABLE_CX321_ACTIVE_HYBRID",
    "OTIS_ENABLE_CX322_DIRECT_HYBRID",
    "OTIS_ENABLE_SUSTAINED_HYBRID_REGULATION",
    "OTIS_ACTIVE_HYBRID_MAX_AUTOMATIC_APPLICATIONS",
    "OTIS_ACTIVE_HYBRID_MAX_CUMULATIVE_MOVEMENT_CODES",
    "OTIS_ACTIVE_HYBRID_ENABLE_REVERSAL_CHALLENGE",
    "OTIS_SELECTED_HYBRID_EXTERNAL_DAC_EPOCH_RESEED",
    "OTIS_ENABLE_CX319_RANGE_MAP_PREVIEW",
    "OTIS_CX319_RANGE_MAP_INITIAL_CODE",
    "OTIS_CX318_STAGE4_STATIC_CODE",
    "OTIS_CX318_STAGE4_DAC_EPOCH",
    "OTIS_ENABLE_CX318_STAGE4_PREMISE_SETUP",
    "OTIS_CX318_STAGE4_PREMISE_SETUP_CODE",
    "OTIS_ENABLE_DUAL_CORE_PARTITION",
    "OTIS_ENABLE_GNSS_RECEIVER",
    "OTIS_GNSS_UART_TX_ENABLED",
    "OTIS_GNSS_UART_BAUD",
    "OTIS_GNSS_OPERATIONAL_CONFIG_BLIND_PROMOTION",
    "OTIS_GNSS_OPERATIONAL_PROMOTION_SETTLE_MS",
    "OTIS_GNSS_DISCOVERY_STARTUP_BAUD_HINT",
    "OTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD",
    "OTIS_GNSS_BAUD_CHARACTERIZATION_RESUME",
    "OTIS_GNSS_COMMAND_RESPONSE_TIMEOUT_MS",
    "OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION",
    "OTIS_ENABLE_CX317_BOUNDED_ACTIVE",
    "OTIS_ENABLE_Q2_TRANSACTION_REHEARSAL",
    "OTIS_ENABLE_D9_D6_READINESS_PROFILE",
    "OTIS_ENABLE_FORWARDED_D9_OUTPUT",
    "OTIS_ENABLE_FORWARDED_D6_MONITOR",
    "OTIS_CX317_ACTIVE_CAMPAIGN",
    "OTIS_CX317_ACTIVE_START_CODE",
    "OTIS_CX317_ACTIVE_CORRECTION_LIMIT",
    "OTIS_CX317_ACTIVE_CUMULATIVE_LIMIT_CODES",
    "OTIS_CX317_SELECTED_SPAN_INTERVALS_CONFIG",
    "OTIS_CX317_STARTUP_WARMUP_S",
    "OTIS_CX317_SETTLING_EXCLUSION_S",
    "OTIS_CX317_FULL_HISTORY_RESET_S",
    "OTIS_CX317_RECOVERY_FRESH_SUPPORT_S",
    "OTIS_CX317_DECISION_CADENCE_S",
    "OTIS_CX317_MINIMUM_APPLIED_CADENCE_S",
    "OTIS_FC0_STARTUP_INHIBIT_MS",
    "OTIS_FC0_CONTROL_READY_CLEAN_WINDOWS",
}
GNSS_BAUD_CHARACTERIZATION_PROFILE_ID = (
    "otis_gnss_baud_envelope_characterization_v1"
)
GNSS_BAUD_CONTINUATION_PROFILE_ID = (
    "otis_gnss_baud_envelope_characterization_continuation_v1"
)
GNSS_BAUD_RESUME_PROFILE_ID = "otis_gnss_baud_envelope_characterization_resume_v1"
GNSS_BAUD_CHARACTERIZATION_STARTUP_HINT_DEFINE = (
    "OTIS_GNSS_DISCOVERY_STARTUP_BAUD_HINT"
)
GNSS_BAUD_CHARACTERIZATION_STARTUP_HINT_BAUD = 57600
GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_DEFINE = (
    "OTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD"
)
GNSS_BAUD_CHARACTERIZATION_STARTUP_ATTEMPTS = (
    57600,
    9600,
    19200,
    38400,
    57600,
    115200,
)
GNSS_BAUD_CHARACTERIZATION_FALLBACK_SCAN = (9600, 19200, 38400, 57600, 115200)
GNSS_BAUD_CHARACTERIZATION_STARTUP_TELEMETRY = (
    "startup_hint_attempted",
    "startup_hint_baud",
    "startup_hint_identity_outcome",
    "startup_fallback_entered",
    "initial_discovery_identity_baud",
    "initial_discovery_outcome",
    "pmtk605_peripheral_complete_count",
    "pmtk605_last_peripheral_complete_ticks",
    "pmtk605_last_peripheral_complete_ticks_available",
    "pmtk605_last_peripheral_complete_ticks_domain",
)
GNSS_BAUD_CHARACTERIZATION_CONTRACT = (
    REPO_ROOT
    / "profiles"
    / "qualification"
    / "otis_gnss_baud_envelope_characterization_v1.json"
)
GNSS_BAUD_CHARACTERIZATION_CONTRACT_SHA256 = (
    "08308e05ecc4b169a46ace1eb339b93a778abe04070278fcc3c47519666b0550"
)
GNSS_BAUD_CONTINUATION_CONTRACT = (
    REPO_ROOT
    / "profiles"
    / "qualification"
    / "otis_gnss_baud_envelope_characterization_continuation_v1.json"
)
GNSS_BAUD_CONTINUATION_CONTRACT_SHA256 = (
    "7f029d106b684ac96623c5d3be28f3ebc6b69a3cd38e2641561ed04a2d204a22"
)
GNSS_BAUD_RESUME_CONTRACT = (
    REPO_ROOT
    / "profiles"
    / "qualification"
    / "otis_gnss_baud_envelope_characterization_resume_v1.json"
)
GNSS_BAUD_RESUME_CONTRACT_SHA256 = (
    "a91b095fb155292e979a84424c22141f88285ba6db065ffba7c167d9179c67c9"
)
GNSS_BAUD_CHARACTERIZATION_PACKETS = {
    b"$PMTK251,9600*17\r\n",
    b"$PMTK251,19200*22\r\n",
    b"$PMTK251,38400*27\r\n",
    b"$PMTK251,57600*2C\r\n",
    b"$PMTK251,115200*1F\r\n",
}
GNSS_BAUD_CHARACTERIZATION_BINARY_MARKERS = {
    "programme_id": b"OTIS_GNSS_BAUD_ENVELOPE_CHARACTERIZATION_V1",
    "baud_handler": b"baud_request_disposition",
    "status_handler": b"status_request_disposition",
    "coherent_snapshot": b"snapshot_generation",
    "metadata_frontier": b"metadata_frontier",
    "extended_counter": b"extended_counter_ticks",
    "phase_window": b"phase_window_ring_high_water",
    "isr_policy": b"uart0_rx_drain_to_empty_entry_exit_timer_only",
}
GNSS_BAUD_PACKET_PATTERN = re.compile(
    rb"\$PMTK251,[0-9]+\*[0-9A-F]{2}\r\n"
)
D9_D6_READINESS_CONTRACT = (
    REPO_ROOT
    / "docs"
    / "60_EXPERIMENTS"
    / "OTIS_D9_OUTPUT_AND_ADAPTIVE_STEERING_INTEGRATION_PROGRAMME"
    / "d9_d6_readiness_contract_v1.json"
)
D9_D6_READINESS_CONTRACT_ID = "OTIS_D9_D6_READINESS_CONTRACT_V1"
D9_D6_READINESS_CONTRACT_SEMANTIC_SHA256 = (
    "a6a08d14a03a87b5e0308880c64799baf2e7afecc23cad22d1532f297960de4d"
)
# These are deliberately emitted status/provenance strings, rather than source
# symbols or ELF layout details.  The binary audit therefore proves the
# customer-visible, fixed configuration surface of the selected build.
D9_D6_BINARY_MARKERS = {
    "contract_id": D9_D6_READINESS_CONTRACT_ID.encode("ascii"),
    "contract_semantic_sha256": D9_D6_READINESS_CONTRACT_SEMANTIC_SHA256.encode(
        "ascii"
    ),
    "unqualified_configured_state": b"configured_10mhz_forwarded_unqualified",
    "source_d8_gpin0": b"D8_GPIO20_GPIN0",
    "destination_d9_gpout0": b"D9_GPIO21_GPOUT0",
    "readback": b"readback_valid",
    "integer_divider": b"integer_divider",
    "fractional_divider": b"fractional_divider",
}
D6_MONITOR_BINARY_MARKERS = {
    "raw_snapshot_record": b"MNS",
    "component": b"forwarded_clock_monitor",
    "d6_gpio18_resource": b"d6_gpio18_diagnostic_input",
    "d6_d14_snapshot_topology": b"d6_d14_cumulative_snapshot",
    "monitor_channel": b"channel_id",
    "cpu_snapshot_backend": b"pio_wait_cumulative_snapshot_cpu_v1",
}
# A qualified output or a non-zero / runtime-selected divider must never be
# represented by a readiness binary.  These are names reserved for future
# deliberate implementations, so a newly introduced semantic surface cannot
# silently evade this proof.
D9_D6_FORBIDDEN_BINARY_MARKERS = {
    "qualified_waveform_claim": b"qualified_10mhz_forwarded",
    "runtime_source_selection": b"runtime_forwarded_clock_source_selection",
    "nonzero_fractional_divider": b"fractional_divider_nonzero",
}
D9_D6_ZERO_AUTHORITY_SELECTORS = (
    "OTIS_ENABLE_DAC_AD5693R",
    "OTIS_ENABLE_H1_DAC_SWEEP",
    "OTIS_ENABLE_CX317_BOUNDED_ACTIVE",
    "OTIS_ENABLE_CX318_STAGE4_PREMISE_SETUP",
    "OTIS_ENABLE_CX320_ACTIVE_HYBRID",
    "OTIS_ENABLE_CX321_ACTIVE_HYBRID",
    "OTIS_ENABLE_CX322_DIRECT_HYBRID",
    "OTIS_ENABLE_SUSTAINED_HYBRID_REGULATION",
)
GENERATED_HEADER_NAME = "otis_build_profile.generated.h"
PROVENANCE_FORMAT = "otis_generated_build_v1"
EXPECTED_ARTIFACT_SUFFIXES = (".bin", ".elf", ".h", ".map", ".uf2")
INSTALLATION_NOISE_NAMES = {".DS_Store", "installed.json"}
LIFECYCLE_CLASSES = {
    "keep_active",
    "keep_compile_only",
}
VERIFICATION_TIERS = {"fast", "campaign", "release", "bench"}


class MatrixError(RuntimeError):
    pass


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
        raise MatrixError(f"required executable is unavailable: {arguments[0]}") from exc
    except subprocess.CalledProcessError as exc:
        detail = (exc.stderr or exc.stdout or "").strip()
        raise MatrixError(
            f"command failed ({' '.join(arguments)}): {detail}"
        ) from exc


def _canonical_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256_json(value: object) -> str:
    return sha256(_canonical_bytes(value)).hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MatrixError(f"cannot read matrix {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise MatrixError("firmware matrix root must be an object")
    return value


def _gnss_baud_contract() -> dict[str, Any]:
    contract = _load_json(GNSS_BAUD_CHARACTERIZATION_CONTRACT)
    actual_sha256 = sha256(GNSS_BAUD_CHARACTERIZATION_CONTRACT.read_bytes()).hexdigest()
    firmware_profile = contract.get("firmware_profile", {})
    authority = contract.get("authority", {})
    topology = contract.get("topology", {})
    transition_policy = contract.get("transition_policy", {})
    packets = contract.get("command_table", {}).get("packets", [])
    packet_bytes = {str(item["wire"]).encode("ascii") for item in packets}
    ordered = [
        str(item["wire"]).encode("ascii")
        for item in sorted(packets, key=lambda item: int(item["baud"]))
    ]
    if (
        actual_sha256 != GNSS_BAUD_CHARACTERIZATION_CONTRACT_SHA256
        or contract.get("programme_id")
        != "OTIS_GNSS_BAUD_ENVELOPE_CHARACTERIZATION_V1"
        or firmware_profile.get("profile_id")
        != GNSS_BAUD_CHARACTERIZATION_PROFILE_ID
        or authority.get("physical_authority") is not False
        or authority.get("dac_writes_permitted") != 0
        or topology.get("reference_authority") != "D14"
        or topology.get("oscillator_count_input") != "D8"
        or transition_policy.get("initial_confirmed_baud") != 9600
        or transition_policy.get("initial_baud_epoch") != 1
        or packet_bytes != GNSS_BAUD_CHARACTERIZATION_PACKETS
        or sha256(b"".join(ordered)).hexdigest()
        != contract.get("command_table", {}).get("sha256")
    ):
        raise MatrixError(
            "frozen GNSS baud characterization contract/profile binding differs"
        )
    return contract


def _gnss_baud_continuation_contract() -> dict[str, Any]:
    contract = _load_json(GNSS_BAUD_CONTINUATION_CONTRACT)
    actual_sha256 = sha256(GNSS_BAUD_CONTINUATION_CONTRACT.read_bytes()).hexdigest()
    startup = contract.get("startup_discovery", {})
    continuation = contract.get("continuation", {})
    prefix = contract.get("prefix_validation", {})
    schedule = contract.get("schedule", {})
    mapping = continuation.get("local_to_logical_segment_map", [])
    if (
        actual_sha256 != GNSS_BAUD_CONTINUATION_CONTRACT_SHA256
        or contract.get("contract_id")
        != "otis_gnss_baud_envelope_characterization_continuation_v1"
        or contract.get("firmware_profile", {}).get("profile_id")
        != GNSS_BAUD_CONTINUATION_PROFILE_ID
        or contract.get("authority", {}).get("physical_authority") is not False
        or startup.get("hint_baud") != 57600
        or startup.get("startup_attempt_bauds")
        != list(GNSS_BAUD_CHARACTERIZATION_STARTUP_ATTEMPTS)
        or startup.get("fallback_scan_bauds")
        != list(GNSS_BAUD_CHARACTERIZATION_FALLBACK_SCAN)
        or startup.get("recovery_scan_bauds")
        != list(GNSS_BAUD_CHARACTERIZATION_FALLBACK_SCAN)
        or startup.get("required_causal_telemetry")
        != list(GNSS_BAUD_CHARACTERIZATION_STARTUP_TELEMETRY)
        or prefix.get("source_run_id") != "live_20260826T223754Z"
        or prefix.get("original_contract_file_sha256")
        != "a03d06f0b55097314194973e2d0ef1d16b0e5c52e4fb8a4d31f23c91c7193e11"
        or prefix.get("original_contract_canonical_sha256")
        != "e43cc21f5d8c0dfba0366f06604ca816d417bf25542776fb45bec91d1a1bbf5d"
        or prefix.get("supervisor_events_sha256")
        != "b8dca60881836e99fc704bdc65c78b4fe5ea861ceea2c9a0b9661ff3a557161b"
        or [item.get("logical_segment_id") for item in mapping]
        != ["S06", "S07", "S08", "S09", "S10", "S11"]
        or continuation.get("local_request_sequences") != [1, 2, 3, 4, 5, 6]
        or continuation.get("attachment_deadline_ms") != 120000
        or schedule.get("total_confirmed_online_seconds") != 35700
        or contract.get("composite_analysis", {}).get("terminal")
        != "composite_multi_artifact_characterization_complete"
    ):
        raise MatrixError("frozen GNSS continuation contract/profile binding differs")
    return contract


def _gnss_baud_resume_contract() -> dict[str, Any]:
    contract = _load_json(GNSS_BAUD_RESUME_CONTRACT)
    startup = contract.get("startup_discovery", {})
    continuation = contract.get("continuation", {})
    prefix = contract.get("prefix_validation", {})
    schedule = contract.get("schedule", {})
    mapping = continuation.get("local_to_logical_segment_map", [])
    if (
        sha256(GNSS_BAUD_RESUME_CONTRACT.read_bytes()).hexdigest()
        != GNSS_BAUD_RESUME_CONTRACT_SHA256
        or contract.get("contract_id")
        != "otis_gnss_baud_envelope_characterization_resume_v1"
        or contract.get("firmware_profile", {}).get("profile_id")
        != GNSS_BAUD_RESUME_PROFILE_ID
        or contract.get("authority", {}).get("physical_authority") is not False
        or startup.get("hint_baud") != 115200
        or startup.get("fallback_scan_bauds")
        != list(GNSS_BAUD_CHARACTERIZATION_FALLBACK_SCAN)
        or startup.get("recovery_scan_bauds")
        != list(GNSS_BAUD_CHARACTERIZATION_FALLBACK_SCAN)
        or startup.get("required_causal_telemetry")
        != list(GNSS_BAUD_CHARACTERIZATION_STARTUP_TELEMETRY)
        or prefix.get("source_run_id") != "live_20260827T092556Z"
        or prefix.get("supervisor_events_sha256")
        != "9125fca098454ba379c14126d8b17e22b28db8b2649cb38781a09c32df2fef19"
        or [item.get("logical_segment_id") for item in mapping] != ["S10", "S11"]
        or continuation.get("local_request_sequences") != [1, 2]
        or continuation.get("attachment_deadline_ms") != 120000
        or schedule.get("total_confirmed_online_seconds") != 24600
    ):
        raise MatrixError("frozen GNSS resume contract/profile binding differs")
    return contract

def load_matrix(path: Path = DEFAULT_MATRIX) -> dict[str, Any]:
    matrix = _load_json(path)
    if matrix.get("schema_version") != 1:
        raise MatrixError("firmware matrix schema_version must be 1")
    if matrix.get("builder_id") != "otis_firmware_matrix_v1":
        raise MatrixError("firmware matrix builder_id is unsupported")

    target = matrix.get("target")
    toolchain = matrix.get("toolchain")
    resource_budgets = matrix.get("resource_budgets")
    profiles = matrix.get("profiles")
    if (
        not isinstance(target, dict)
        or not isinstance(toolchain, dict)
        or not isinstance(resource_budgets, dict)
    ):
        raise MatrixError(
            "firmware matrix target, toolchain, and resource_budgets must be objects"
        )
    if not isinstance(profiles, list) or not profiles:
        raise MatrixError("firmware matrix profiles must be a non-empty array")

    required_target = {
        "fqbn",
        "core_provider",
        "core_architecture",
        "core_version",
        "core_archive_sha256",
        "core_installed_sha256",
    }
    required_toolchain = {
        "packager",
        "name",
        "version",
        "compiler",
        "compiler_version",
        "installed_sha256",
    }
    if required_target - set(target):
        raise MatrixError(
            f"firmware matrix target is missing {sorted(required_target - set(target))}"
        )
    if required_toolchain - set(toolchain):
        raise MatrixError(
            "firmware matrix toolchain is missing "
            f"{sorted(required_toolchain - set(toolchain))}"
        )
    if not HEX64_PATTERN.fullmatch(str(target["core_archive_sha256"])):
        raise MatrixError("target core_archive_sha256 must be lowercase SHA-256")
    if not HEX64_PATTERN.fullmatch(str(target["core_installed_sha256"])):
        raise MatrixError("target core_installed_sha256 must be lowercase SHA-256")
    if not HEX64_PATTERN.fullmatch(str(toolchain["installed_sha256"])):
        raise MatrixError("toolchain installed_sha256 must be lowercase SHA-256")

    required_budgets = {
        "dynamic_memory_total_bytes",
        "static_dynamic_memory_max_bytes",
        "runtime_memory_reserve_min_bytes",
    }
    if required_budgets - set(resource_budgets):
        raise MatrixError(
            "firmware matrix resource_budgets is missing "
            f"{sorted(required_budgets - set(resource_budgets))}"
        )
    if any(
        not isinstance(resource_budgets[key], int) or resource_budgets[key] <= 0
        for key in required_budgets
    ):
        raise MatrixError("firmware resource budgets must be positive integers")
    if (
        resource_budgets["static_dynamic_memory_max_bytes"]
        + resource_budgets["runtime_memory_reserve_min_bytes"]
        != resource_budgets["dynamic_memory_total_bytes"]
    ):
        raise MatrixError(
            "static dynamic-memory budget plus runtime reserve must equal total RAM"
        )

    seen: set[str] = set()
    pass_count = 0
    fail_count = 0
    for profile in profiles:
        if not isinstance(profile, dict):
            raise MatrixError("each firmware profile must be an object")
        profile_id = profile.get("id")
        if not isinstance(profile_id, str) or not PROFILE_ID_PATTERN.fullmatch(
            profile_id
        ):
            raise MatrixError(f"invalid firmware profile id: {profile_id!r}")
        if profile_id in seen:
            raise MatrixError(f"duplicate firmware profile id: {profile_id}")
        seen.add(profile_id)
        expectation = profile.get("expect")
        if expectation == "pass":
            pass_count += 1
            if "expected_error" in profile:
                raise MatrixError(
                    f"supported profile {profile_id} must not name expected_error"
                )
        elif expectation == "fail":
            fail_count += 1
            if not isinstance(profile.get("expected_error"), str) or not profile[
                "expected_error"
            ]:
                raise MatrixError(
                    f"invalid profile {profile_id} must name expected_error"
                )
        else:
            raise MatrixError(
                f"profile {profile_id} expect must be 'pass' or 'fail'"
            )
        lifecycle = profile.get("lifecycle")
        if lifecycle not in LIFECYCLE_CLASSES:
            raise MatrixError(
                f"profile {profile_id} has invalid lifecycle {lifecycle!r}"
            )
        verification_tiers = profile.get("verification_tiers")
        if (
            not isinstance(verification_tiers, list)
            or any(not isinstance(item, str) for item in verification_tiers)
            or len(set(verification_tiers)) != len(verification_tiers)
            or set(verification_tiers) - VERIFICATION_TIERS
        ):
            raise MatrixError(
                f"profile {profile_id} has invalid verification_tiers"
            )
        if lifecycle == "keep_active" and expectation != "pass":
            raise MatrixError(
                f"active profile {profile_id} must be expected to pass"
            )
        if lifecycle == "keep_compile_only" and expectation != "fail":
            raise MatrixError(
                f"compile-only profile {profile_id} must be an expected-fail "
                "structural guard"
            )
        if expectation == "fail" and set(verification_tiers) - {"release"}:
            raise MatrixError(
                f"expected-fail profile {profile_id} may run only at Release"
            )
        defines = profile.get("defines")
        if not isinstance(defines, dict) or not defines:
            raise MatrixError(f"profile {profile_id} defines must be an object")
        for name, value in defines.items():
            if (
                not isinstance(name, str)
                or not DEFINE_NAME_PATTERN.fullmatch(name)
                or name.startswith("OTIS_BUILD_")
                or name in FORBIDDEN_PROFILE_DEFINES
            ):
                raise MatrixError(
                    f"profile {profile_id} may not define generated identity {name!r}"
                )
            if (
                not isinstance(value, str)
                or not value
                or not DEFINE_VALUE_PATTERN.fullmatch(value)
            ):
                raise MatrixError(
                    f"profile {profile_id} has unsafe define value for {name}: {value!r}"
                )
        unknown_selectors = set(defines) - (
            PROFILE_SELECTOR_NAMES | OPTIONAL_PROFILE_SELECTOR_NAMES
        )
        missing_selectors = PROFILE_SELECTOR_NAMES - set(defines)
        if unknown_selectors or missing_selectors:
            raise MatrixError(
                f"profile {profile_id} selector set mismatch: "
                f"missing {sorted(missing_selectors)}, "
                f"unsupported {sorted(unknown_selectors)}"
            )
        if (
            expectation == "pass"
            and defines.get("OTIS_ENABLE_CX317_BOUNDED_ACTIVE", "0") == "1"
            and profile_id
            not in {
                "cx319_tight_lower",
                "cx319_tight_upper",
                "cx319_range_part_b_lower",
                "cx319_range_part_b_upper",
                "cx319_range_part_b_upper_completion",
                "cx320_active_hybrid",
                "cx321_active_hybrid",
                "cx322_direct_hybrid",
                "cx322_d9_d6_integration_engineering",
                "cx322_d9_d6_72h_sustained_engineering",
                "otis_sustained_hybrid_regulation_v1",
                "d9_d6_frequency_only_lower",
            }
        ):
            raise MatrixError(
                "bounded controller-to-DAC reachability is restricted to "
                "the current bounded-active profiles"
            )
        characterization_enabled = defines.get(
            "OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION", "0"
        )
        if characterization_enabled not in {"0", "1"}:
            raise MatrixError(
                "OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION must be 0 or 1"
            )
        if profile_id in {
            "cx322_direct_hybrid",
            "cx322_d9_d6_integration_engineering",
            "cx322_d9_d6_72h_sustained_engineering",
            "d9_d6_frequency_only_lower",
        } and (
            defines.get("OTIS_GNSS_OPERATIONAL_CONFIG_BLIND_PROMOTION") != "1"
            or defines.get("OTIS_GNSS_OPERATIONAL_PROMOTION_SETTLE_MS")
            != "1200u"
        ):
            raise MatrixError(
                "D9/D6 operational profiles require the exact finite "
                "configuration-blind GNSS promotion contract"
            )
        if (
            characterization_enabled == "1"
            and profile_id
            not in {
                GNSS_BAUD_CHARACTERIZATION_PROFILE_ID,
                GNSS_BAUD_CONTINUATION_PROFILE_ID,
                GNSS_BAUD_RESUME_PROFILE_ID,
            }
        ):
            raise MatrixError(
                "GNSS baud characterization is restricted to its exact profile"
            )
        if profile_id in {
            GNSS_BAUD_CHARACTERIZATION_PROFILE_ID,
            GNSS_BAUD_CONTINUATION_PROFILE_ID,
            GNSS_BAUD_RESUME_PROFILE_ID,
        }:
            continuation_profile = profile_id in {
                GNSS_BAUD_CONTINUATION_PROFILE_ID,
                GNSS_BAUD_RESUME_PROFILE_ID,
            }
            characterization_contract = (
                (
                    _gnss_baud_resume_contract()
                    if profile_id == GNSS_BAUD_RESUME_PROFILE_ID
                    else _gnss_baud_continuation_contract()
                )
                if continuation_profile
                else _gnss_baud_contract()
            )
            startup_identity_response_timeout_ms = int(
                characterization_contract["transition_policy"][
                    "startup_identity_response_timeout_ms"
                ]
            )
            required_characterization_defines = {
                "OTIS_SW1_BRINGUP_MODE": "OTIS_SW1_MODE_H1_OCXO_OBSERVE",
                "OTIS_CAPTURE_BACKEND": "OTIS_CAPTURE_BACKEND_IRQ",
                "OTIS_TCXO_COUNTER_BACKEND": (
                    "OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO"
                ),
                "OTIS_ENABLE_PSEUDO_PPS_GENERATOR": "0",
                "OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED": "1",
                "OTIS_PPS_GATE_STATUS_PERIOD_MS": "1000u",
                "OTIS_ENABLE_GNSS_RECEIVER": "1",
                "OTIS_GNSS_UART_TX_ENABLED": "1",
                "OTIS_GNSS_UART_BAUD": "9600u",
                "OTIS_GNSS_COMMAND_RESPONSE_TIMEOUT_MS": (
                    f"{startup_identity_response_timeout_ms}u"
                ),
                "OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION": "1",
                "OTIS_ENABLE_DUAL_CORE_PARTITION": "1",
                "OTIS_ENABLE_DAC_AD5693R": "0",
                "OTIS_ENABLE_H1_DAC_SWEEP": "0",
                "OTIS_ENABLE_CX317_BOUNDED_ACTIVE": "0",
                "OTIS_ENABLE_CX318_STAGE4_PREMISE_SETUP": "0",
                "OTIS_ENABLE_CX320_ACTIVE_HYBRID": "0",
                "OTIS_ENABLE_CX321_ACTIVE_HYBRID": "0",
                "OTIS_ENABLE_CX322_DIRECT_HYBRID": "0",
                "OTIS_ENABLE_SUSTAINED_HYBRID_REGULATION": "0",
            }
            if continuation_profile:
                required_characterization_defines.update(
                    {
                        GNSS_BAUD_CHARACTERIZATION_STARTUP_HINT_DEFINE: (
                            f"{int(characterization_contract['startup_discovery']['hint_baud'])}u"
                        ),
                        GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_DEFINE: "1",
                    }
                )
            elif any(
                name in defines
                for name in (
                    GNSS_BAUD_CHARACTERIZATION_STARTUP_HINT_DEFINE,
                    GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_DEFINE,
                )
            ):
                raise MatrixError(
                    "original GNSS characterization profile cannot carry "
                    "continuation startup selectors"
                )
            mismatches = {
                name: (defines.get(name), expected_value)
                for name, expected_value in required_characterization_defines.items()
                if defines.get(name) != expected_value
            }
            if mismatches:
                raise MatrixError(
                    "GNSS baud characterization profile authority or topology "
                    f"differs: {mismatches}"
                )
    if pass_count == 0 or fail_count == 0:
        raise MatrixError(
            "firmware matrix must contain supported and expected-fail profiles"
        )
    return matrix


def configuration_payload(
    matrix: dict[str, Any],
    profile: dict[str, Any],
    *,
    config_source_sha256: str | None = None,
) -> dict[str, Any]:
    config_source_sha256 = (
        config_source_sha256
        if config_source_sha256 is not None
        else sha256(CONFIG_HEADER.read_bytes()).hexdigest()
    )
    if not HEX64_PATTERN.fullmatch(config_source_sha256):
        raise MatrixError("config_source_sha256 must be lowercase SHA-256")
    return {
        "schema_version": 1,
        "fqbn": matrix["target"]["fqbn"],
        "profile_id": profile["id"],
        "defines": dict(sorted(profile["defines"].items())),
        "config_source_sha256": config_source_sha256,
    }


def configuration_hash(
    matrix: dict[str, Any],
    profile: dict[str, Any],
    *,
    config_path: Path = CONFIG_HEADER,
) -> str:
    return _sha256_json(
        configuration_payload(
            matrix,
            profile,
            config_source_sha256=sha256(config_path.read_bytes()).hexdigest(),
        )
    )


def _git_identity(repo_root: Path = REPO_ROOT) -> tuple[str, str]:
    commit = _run(["git", "rev-parse", "HEAD"], cwd=repo_root).stdout.strip()
    if not HEX40_PATTERN.fullmatch(commit):
        raise MatrixError(f"Git returned a malformed commit identity: {commit!r}")
    status = _run(
        ["git", "status", "--porcelain=v1", "--untracked-files=all"],
        cwd=repo_root,
    ).stdout
    return commit, "dirty" if status else "clean"


def source_input_hash(
    *,
    sketch: Path = SKETCH,
    matrix_path: Path = DEFAULT_MATRIX,
    builder_path: Path = Path(__file__).resolve(),
) -> str:
    def source_name(path: Path) -> str:
        resolved = path.resolve()
        try:
            return resolved.relative_to(REPO_ROOT).as_posix()
        except ValueError:
            return resolved.as_posix()

    paths = sorted(
        [
            path
            for path in sketch.rglob("*")
            if path.is_file() and path.name != GENERATED_HEADER_NAME
        ]
        + [matrix_path.resolve(), builder_path.resolve()],
        key=source_name,
    )
    digest = sha256()
    for path in paths:
        relative = source_name(path).encode("utf-8")
        data = path.read_bytes()
        digest.update(len(relative).to_bytes(8, "big"))
        digest.update(relative)
        digest.update(len(data).to_bytes(8, "big"))
        digest.update(data)
    return digest.hexdigest()


def installed_tree_hash(root: Path) -> str:
    """Hash functional installed bytes independently of local runtime noise."""
    root = root.resolve()
    if not root.is_dir():
        raise MatrixError(f"installed package path is not a directory: {root}")

    def is_functional_package_path(path: Path) -> bool:
        relative = path.relative_to(root)
        return (
            path.name not in INSTALLATION_NOISE_NAMES
            and "__pycache__" not in relative.parts
            and path.suffix not in {".pyc", ".pyo"}
        )

    paths = sorted(
        (
            path
            for path in root.rglob("*")
            if (path.is_file() or path.is_symlink())
            and is_functional_package_path(path)
        ),
        key=lambda path: path.relative_to(root).as_posix(),
    )
    if not paths:
        raise MatrixError(f"installed package path contains no files: {root}")
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
        raise MatrixError(
            f"{label} installed-byte SHA-256 mismatch: "
            f"expected {expected}, found {actual}"
        )
    return actual


def _build_properties(board_details: dict[str, Any]) -> dict[str, str]:
    properties: dict[str, str] = {}
    for item in board_details.get("build_properties", []):
        if not isinstance(item, str) or "=" not in item:
            continue
        key, value = item.split("=", 1)
        properties[key] = value
    return properties


def verify_environment(
    matrix: dict[str, Any],
    *,
    arduino_cli: str = "arduino-cli",
) -> dict[str, str]:
    cli = json.loads(
        _run([arduino_cli, "version", "--format", "json"]).stdout
    )
    expected_cli = str(matrix["arduino_cli_version"])
    actual_cli = str(cli.get("VersionString", ""))
    if actual_cli != expected_cli:
        raise MatrixError(
            f"Arduino CLI version mismatch: expected {expected_cli}, found {actual_cli}"
        )

    target = matrix["target"]
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
    expected_fqbn = str(target["fqbn"])
    fqbn_parts = expected_fqbn.split(":", 3)
    expected_board_fqbn = ":".join(fqbn_parts[:3])
    checks = {
        "FQBN": (expected_board_fqbn, details.get("fqbn")),
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
            raise MatrixError(
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
            if "=" not in assignment:
                raise MatrixError(f"invalid FQBN option {assignment!r}")
            option, expected_value = assignment.split("=", 1)
            actual_value = selected_options.get(option)
            if actual_value != expected_value:
                raise MatrixError(
                    f"FQBN option {option!r} mismatch: expected "
                    f"{expected_value!r}, found {actual_value!r}"
                )
    if not details.get("properties_id") or not details.get("name"):
        raise MatrixError("board details do not expose generated board identity")

    toolchain = matrix["toolchain"]
    dependency = next(
        (
            item
            for item in details.get("tools_dependencies", [])
            if item.get("packager") == toolchain["packager"]
            and item.get("name") == toolchain["name"]
        ),
        None,
    )
    if dependency is None:
        raise MatrixError("pinned compiler toolchain is absent from board dependencies")
    if dependency.get("version") != toolchain["version"]:
        raise MatrixError(
            "compiler toolchain version mismatch: expected "
            f"{toolchain['version']}, found {dependency.get('version')}"
        )

    properties = _build_properties(details)
    platform_root_value = properties.get("runtime.platform.path")
    if not platform_root_value:
        raise MatrixError("board details do not expose the installed platform path")
    core_installed_sha256 = _require_installed_hash(
        "Arduino core",
        Path(platform_root_value),
        str(target["core_installed_sha256"]),
    )
    toolchain_name = str(toolchain["name"])
    path_key = f"runtime.tools.{toolchain_name}.path"
    tool_root = properties.get(path_key)
    compiler_prefix = properties.get("build.toolchain")
    compiler_package = properties.get("build.toolchainpkg")
    if not tool_root or not compiler_prefix:
        raise MatrixError("board details do not expose the selected compiler path")
    if compiler_package != toolchain_name:
        raise MatrixError(
            f"board selects compiler package {compiler_package!r}, "
            f"not {toolchain_name!r}"
        )
    toolchain_installed_sha256 = _require_installed_hash(
        "compiler toolchain",
        Path(tool_root),
        str(toolchain["installed_sha256"]),
    )
    compiler_path = Path(tool_root) / "bin" / str(toolchain["compiler"])
    if str(toolchain["compiler"]) != f"{compiler_prefix}-g++":
        raise MatrixError(
            "compiler executable mismatch: board selects "
            f"{compiler_prefix!r}, matrix names {toolchain['compiler']!r}"
        )
    compiler_line = _run([str(compiler_path), "--version"]).stdout.splitlines()[0]
    expected_fragment = f" {toolchain['compiler_version']}"
    if not compiler_line.endswith(expected_fragment):
        raise MatrixError(
            "compiler version mismatch: expected "
            f"{toolchain['compiler_version']!r}, found {compiler_line!r}"
        )

    return {
        "arduino_cli_version": actual_cli,
        "board_id": str(details.get("properties_id", "")),
        "board_name": str(details.get("name", "")),
        "core_installed_sha256": core_installed_sha256,
        "toolchain_installed_sha256": toolchain_installed_sha256,
        "core_path": str(Path(platform_root_value).resolve()),
        "toolchain_path": str(Path(tool_root).resolve()),
        "compiler_identity": (
            f"{toolchain_name}@{toolchain['version']}/"
            f"{toolchain['compiler']}@{toolchain['compiler_version']}"
        ),
        "compiler_path": str(compiler_path),
    }


def build_provenance(
    matrix: dict[str, Any],
    profile: dict[str, Any],
    environment: dict[str, str],
    *,
    git_commit: str,
    source_state: str,
    source_sha256: str,
    build_session_id: str,
    config_source_sha256: str | None = None,
) -> dict[str, Any]:
    if not HEX64_PATTERN.fullmatch(source_sha256):
        raise MatrixError("source_sha256 must be lowercase SHA-256")
    if not SESSION_ID_PATTERN.fullmatch(build_session_id):
        raise MatrixError("build_session_id must be 16 lowercase hexadecimal digits")
    config = configuration_payload(
        matrix,
        profile,
        config_source_sha256=config_source_sha256,
    )
    config_sha256 = _sha256_json(config)
    invocation_payload = {
        "builder_id": matrix["builder_id"],
        "builder_version": BUILDER_VERSION,
        "build_session_id": build_session_id,
        "git_commit": git_commit,
        "source_state": source_state,
        "source_sha256": source_sha256,
        "config_sha256": config_sha256,
        "arduino_cli_version": environment["arduino_cli_version"],
        "core_provider": matrix["target"]["core_provider"],
        "core_version": matrix["target"]["core_version"],
        "core_installed_sha256": environment["core_installed_sha256"],
        "board_id": environment["board_id"],
        "toolchain": (
            f"{matrix['toolchain']['name']}@{matrix['toolchain']['version']}"
        ),
        "toolchain_installed_sha256": environment[
            "toolchain_installed_sha256"
        ],
        "compiler": environment["compiler_identity"],
    }
    return {
        "schema_version": 1,
        "source": {
            "git_commit": git_commit,
            "state": source_state,
            "sha256": source_sha256,
        },
        "configuration": {
            **config,
            "sha256": config_sha256,
        },
        "target": {
            **matrix["target"],
            "board_id": environment["board_id"],
            "board_name": environment["board_name"],
            "core_installed_sha256": environment["core_installed_sha256"],
        },
        "toolchain": {
            **matrix["toolchain"],
            "compiler_identity": environment["compiler_identity"],
            "installed_sha256": environment["toolchain_installed_sha256"],
        },
        "invocation": {
            "builder_id": matrix["builder_id"],
            "arduino_cli_version": environment["arduino_cli_version"],
            "build_session_id": build_session_id,
            "id": _sha256_json(invocation_payload),
        },
    }


def provenance_header(
    provenance: dict[str, Any],
    *,
    ide_compatible: bool = False,
) -> str:
    source = provenance["source"]
    config = provenance["configuration"]
    target = provenance["target"]
    toolchain = provenance["toolchain"]
    invocation = provenance["invocation"]
    generated = {
        "OTIS_BUILD_PROVENANCE_FORMAT": PROVENANCE_FORMAT,
        "OTIS_BUILD_GIT_COMMIT": source["git_commit"],
        "OTIS_BUILD_SOURCE_STATE": source["state"],
        "OTIS_BUILD_SOURCE_SHA256": source["sha256"],
        "OTIS_BUILD_CONFIG_SHA256": config["sha256"],
        "OTIS_BUILD_PROFILE_ID": config["profile_id"],
        "OTIS_BUILD_FQBN": target["fqbn"],
        "OTIS_BUILD_BOARD_ID": target["board_id"],
        "OTIS_BUILD_BOARD_NAME": target["board_name"],
        "OTIS_BUILD_CORE_PROVIDER": target["core_provider"],
        "OTIS_BUILD_CORE_VERSION": target["core_version"],
        "OTIS_BUILD_CORE_INSTALLED_SHA256": target["core_installed_sha256"],
        "OTIS_BUILD_TOOLCHAIN": (
            f"{toolchain['name']}@{toolchain['version']}"
        ),
        "OTIS_BUILD_COMPILER": toolchain["compiler_identity"],
        "OTIS_BUILD_TOOLCHAIN_INSTALLED_SHA256": toolchain[
            "installed_sha256"
        ],
        "OTIS_BUILD_ARDUINO_CLI_VERSION": invocation[
            "arduino_cli_version"
        ],
        "OTIS_BUILD_INVOCATION_ID": invocation["id"],
    }
    if ide_compatible:
        lines = [
            "// Generated for direct Arduino IDE compilation by:",
            "// python3 tools/firmware_matrix.py --prepare-ide --profile "
            f"{config['profile_id']}",
            "// Regenerate after changing source, profile, or toolchain. "
            "Do not hand-edit or commit.",
            "#ifdef OTIS_BUILD_IDE_PROFILE_GENERATED",
            '#error "OTIS_BUILD_IDE_PROFILE_GENERATED was externally pre-defined."',
            "#endif",
            "#define OTIS_BUILD_IDE_PROFILE_GENERATED 1",
            "",
        ]
    else:
        lines = [
            "// Generated into a one-use temporary sketch by tools/firmware_matrix.py.",
            "// Do not reuse, hand-edit, or commit.",
            "#ifndef OTIS_BUILD_SESSION_ID",
            '#error "OTIS builder session flag is required; raw/stale-header builds are forbidden."',
            "#endif",
            "#ifdef OTIS_BUILD_EXPECTED_SESSION_ID",
            '#error "OTIS_BUILD_EXPECTED_SESSION_ID was externally pre-defined."',
            "#endif",
            f"#define OTIS_BUILD_EXPECTED_SESSION_ID 0x{invocation['build_session_id']}ULL",
            "#if OTIS_BUILD_SESSION_ID != OTIS_BUILD_EXPECTED_SESSION_ID",
            '#error "OTIS builder session flag does not match this generated profile."',
            "#endif",
            "#undef OTIS_BUILD_SESSION_ID",
            "#undef OTIS_BUILD_EXPECTED_SESSION_ID",
            "",
        ]
    lines.extend(
        [
            "#ifdef OTIS_BUILD_PROFILE_GENERATED",
            '#error "OTIS generated build profile was externally pre-defined or included twice."',
            "#endif",
            "#define OTIS_BUILD_PROFILE_GENERATED 1",
            "",
        ]
    )
    for name, value in sorted(generated.items()):
        encoded = json.dumps(str(value), ensure_ascii=True)
        lines.extend(
            [
                f"#ifdef {name}",
                f'#error "{name} was externally pre-defined."',
                "#endif",
            ]
        )
        lines.append(f"#define {name} {encoded}")
    for name, value in sorted(config["defines"].items()):
        expected_name = f"OTIS_BUILD_EXPECTED_{name}"
        lines.extend(
            [
                f"#ifdef {expected_name}",
                f'#error "{expected_name} was externally pre-defined."',
                "#endif",
                f"#define {expected_name} {value}",
                f"#ifdef {name}",
                f'#error "{name} was externally pre-defined."',
                "#endif",
                f"#define {name} {value}",
            ]
        )
    lines.append("")
    return "\n".join(lines)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, ensure_ascii=True, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _capture_source_state(
    matrix: dict[str, Any],
    profile: dict[str, Any],
    *,
    repo_root: Path = REPO_ROOT,
    sketch: Path = SKETCH,
    config_path: Path = CONFIG_HEADER,
    matrix_path: Path = DEFAULT_MATRIX,
    builder_path: Path = Path(__file__).resolve(),
) -> dict[str, str]:
    git_commit, source_state = _git_identity(repo_root)
    config_source_sha256 = sha256(config_path.read_bytes()).hexdigest()
    return {
        "git_commit": git_commit,
        "source_state": source_state,
        "source_sha256": source_input_hash(
            sketch=sketch,
            matrix_path=matrix_path,
            builder_path=builder_path,
        ),
        "config_source_sha256": config_source_sha256,
        "config_sha256": _sha256_json(
            configuration_payload(
                matrix,
                profile,
                config_source_sha256=config_source_sha256,
            )
        ),
    }


def _assert_source_unchanged(
    expected: dict[str, str],
    actual: dict[str, str],
) -> None:
    changed = sorted(
        key for key in expected if expected.get(key) != actual.get(key)
    )
    if changed:
        raise MatrixError(
            "repository/build input changed during compilation: "
            + ", ".join(changed)
        )


def _matrix_source_identity(source_snapshot: dict[str, str]) -> dict[str, str]:
    return {
        key: source_snapshot[key]
        for key in (
            "git_commit",
            "source_state",
            "source_sha256",
            "config_source_sha256",
        )
    }


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


def _path_has_symlink_component(path: Path) -> bool:
    absolute = path.absolute()
    current = Path(absolute.anchor)
    for part in absolute.parts[1:]:
        current = current / part
        if current.is_symlink():
            return True
    return False


def _validate_profile_output_paths(paths: tuple[Path, ...]) -> None:
    for path in paths:
        if _path_has_symlink_component(path):
            raise MatrixError(
                f"firmware output path traverses a symbolic link: {path}"
            )
        if path.exists() and not path.is_dir():
            raise MatrixError(f"firmware output path is not a directory: {path}")


def _reject_descendant_symlinks(path: Path) -> None:
    if not path.exists():
        return
    for root, directory_names, file_names in os.walk(path, followlinks=False):
        root_path = Path(root)
        for name in [*directory_names, *file_names]:
            candidate = root_path / name
            if candidate.is_symlink():
                raise MatrixError(
                    "firmware output directory contains a symbolic link: "
                    f"{candidate}"
                )


def _discard_artifacts(path: Path) -> None:
    if not path.exists() or _path_has_symlink_component(path):
        return
    for artifact in path.iterdir():
        if artifact.is_file() and not artifact.is_symlink():
            artifact.unlink()


def _discard_matrix_artifacts(
    output_dir: Path,
    profile_ids: list[str],
) -> None:
    for profile_id in profile_ids:
        _discard_artifacts(output_dir / profile_id / "artifacts")


def _artifact_hashes(artifacts_dir: Path) -> list[dict[str, Any]]:
    artifacts: list[dict[str, Any]] = []
    for suffix in EXPECTED_ARTIFACT_SUFFIXES:
        matches = sorted(
            path for path in artifacts_dir.iterdir()
            if path.is_file() and path.suffix == suffix
        )
        if len(matches) != 1:
            raise MatrixError(
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


def _d9_d6_readiness_contract() -> dict[str, Any]:
    """Load and bind the frozen D9/D6 readiness semantics.

    This is intentionally an offline build-time binding.  It asserts neither
    electrical propagation nor waveform quality; those claims remain outside
    an ELF's evidence boundary.
    """
    contract = _load_json(D9_D6_READINESS_CONTRACT)
    unsigned = {
        key: value
        for key, value in contract.items()
        if key != "contract_semantic_sha256"
    }
    actual_semantic_sha256 = _sha256_json(unsigned)
    if (
        contract.get("contract_id") != D9_D6_READINESS_CONTRACT_ID
        or contract.get("contract_semantic_sha256")
        != D9_D6_READINESS_CONTRACT_SEMANTIC_SHA256
        or actual_semantic_sha256 != D9_D6_READINESS_CONTRACT_SEMANTIC_SHA256
    ):
        raise MatrixError("frozen D9/D6 readiness contract identity differs")
    if (
        contract.get("d9_output", {}).get("source")
        != "GPIO20/CLOCK_GPIN0/clksrc_gpin0"
        or contract.get("d9_output", {}).get("destination")
        != "D9/GPIO21/CLOCK_GPOUT0"
        or contract.get("d9_output", {}).get("divider")
        != {"integer": 1, "fractional": 0}
        or contract.get("d6_monitor", {}).get("gpio") != "D6/GPIO18"
        or contract.get("d6_monitor", {}).get("authority")
        != "must_not_affect_D14_D8_validity_estimation_control_abort_or_terminal"
    ):
        raise MatrixError("frozen D9/D6 readiness contract topology differs")
    return contract


def _single_flashable_image(artifacts_dir: Path, *, audit: str) -> bytes:
    binary_paths = sorted(
        path for path in artifacts_dir.iterdir()
        if path.is_file() and path.suffix == ".bin"
    )
    if len(binary_paths) != 1:
        raise MatrixError(
            f"{audit} binary audit requires exactly one emitted flashable BIN; "
            f"found {len(binary_paths)}"
        )
    return binary_paths[0].read_bytes()


def _d9_d6_binary_contract(
    profile: dict[str, Any], artifacts_dir: Path
) -> dict[str, Any]:
    """Verify the fixed D8->D9 and optional D6 flashable image surface."""
    image = _single_flashable_image(artifacts_dir, audit="D9/D6")
    defines = profile["defines"]
    output_selected = defines.get("OTIS_ENABLE_FORWARDED_D9_OUTPUT", "0") == "1"
    monitor_selected = defines.get("OTIS_ENABLE_FORWARDED_D6_MONITOR", "0") == "1"
    selector_values = {
        name: defines.get(name, "0") for name in D9_D6_ZERO_AUTHORITY_SELECTORS
    }
    zero_authority = all(value == "0" for value in selector_values.values())
    base = {
        "contract": "otis_d9_d6_readiness_binary_contract_v1",
        "output_selection": "enabled" if output_selected else "disabled",
        "monitor_selection": "enabled" if monitor_selected else "disabled",
        "selectors": {
            "OTIS_ENABLE_D9_D6_READINESS_PROFILE": defines.get(
                "OTIS_ENABLE_D9_D6_READINESS_PROFILE", "0"
            ),
            "OTIS_ENABLE_FORWARDED_D9_OUTPUT": defines.get(
                "OTIS_ENABLE_FORWARDED_D9_OUTPUT", "0"
            ),
            "OTIS_ENABLE_FORWARDED_D6_MONITOR": defines.get(
                "OTIS_ENABLE_FORWARDED_D6_MONITOR", "0"
            ),
            "control_write_selectors": selector_values,
            "all_control_write_selectors_disabled": zero_authority,
            "d9_has_control_authority": False,
            "d6_has_control_authority": False,
        },
    }
    if not output_selected:
        if monitor_selected:
            raise MatrixError("D6 monitor cannot be selected when D9 output is disabled")
        return {
            **base,
            "status": "disabled_profile",
            "topology_contract": None,
            "readiness_contract": None,
            "required_markers": {},
            "forbidden_markers_present": {},
        }

    readiness = _d9_d6_readiness_contract()
    marker_presence = {
        name: marker in image for name, marker in D9_D6_BINARY_MARKERS.items()
    }
    if not all(marker_presence.values()):
        missing = sorted(
            name for name, present in marker_presence.items() if not present
        )
        raise MatrixError(
            "D9 readiness binary omits required fixed-output markers: "
            f"{missing}"
        )
    monitor_markers = {
        name: marker in image for name, marker in D6_MONITOR_BINARY_MARKERS.items()
    }
    if monitor_selected and not all(monitor_markers.values()):
        missing = sorted(
            name for name, present in monitor_markers.items() if not present
        )
        raise MatrixError(
            "D6 readiness binary omits required diagnostic-monitor markers: "
            f"{missing}"
        )
    forbidden_present = {
        name: marker in image
        for name, marker in D9_D6_FORBIDDEN_BINARY_MARKERS.items()
    }
    present = sorted(name for name, value in forbidden_present.items() if value)
    if present:
        raise MatrixError(
            "D9 readiness binary contains forbidden runtime/fractional "
            f"selection markers: {present}"
        )
    contract_binding = {
        "path": str(D9_D6_READINESS_CONTRACT.relative_to(REPO_ROOT)),
        "contract_id": readiness["contract_id"],
        "contract_semantic_sha256": readiness["contract_semantic_sha256"],
    }
    return {
        **base,
        "status": "verified",
        "topology_contract": {
            **contract_binding,
            "binding_scope": (
                "fixed_D8_GPIN0_to_D9_GPOUT0_and_D6_zero_authority_sidecar"
            ),
        },
        "readiness_contract": contract_binding if zero_authority else None,
        "authority_scope": (
            "no_control_readiness"
            if zero_authority
            else "D9_D6_topology_only_controller_authority_is_separate"
        ),
        "required_markers": {
            "d9_output": marker_presence,
            "d6_monitor": monitor_markers if monitor_selected else {},
        },
        "forbidden_markers_present": forbidden_present,
    }


def _gnss_binary_contract(
    profile: dict[str, Any], artifacts_dir: Path
) -> dict[str, Any]:
    """Verify the flashable image contains only its authorized PMTK251 surface."""
    binary_paths = sorted(
        path for path in artifacts_dir.iterdir()
        if path.is_file() and path.suffix == ".bin"
    )
    if len(binary_paths) != 1:
        raise MatrixError(
            "GNSS binary audit requires exactly one emitted flashable BIN; "
            f"found {len(binary_paths)}"
        )
    # Do not scan the ELF container: non-loadable DWARF can retain the spelling
    # of a compile-time-discarded command and is not part of the device image.
    image = binary_paths[0].read_bytes()
    actual_packets = set(GNSS_BAUD_PACKET_PATTERN.findall(image))
    defines = profile["defines"]
    characterization_enabled = (
        defines.get("OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION", "0") == "1"
    )
    continuation_enabled = profile.get("id") in {
        GNSS_BAUD_CONTINUATION_PROFILE_ID,
        GNSS_BAUD_RESUME_PROFILE_ID,
    }
    if characterization_enabled:
        campaign_contract = (
            (
                _gnss_baud_resume_contract()
                if profile.get("id") == GNSS_BAUD_RESUME_PROFILE_ID
                else _gnss_baud_continuation_contract()
            )
            if continuation_enabled
            else _gnss_baud_contract()
        )
        expected_packets = GNSS_BAUD_CHARACTERIZATION_PACKETS
    elif (
        defines.get("OTIS_ENABLE_GNSS_RECEIVER", "0") == "1"
        and defines.get("OTIS_GNSS_UART_TX_ENABLED", "0") == "1"
    ):
        target_baud = defines.get("OTIS_GNSS_UART_BAUD")
        ordinary_packets = {
            "9600u": b"$PMTK251,9600*17\r\n",
            "115200u": b"$PMTK251,115200*1F\r\n",
        }
        expected_packet = ordinary_packets.get(target_baud)
        if expected_packet is None:
            raise MatrixError(
                "ordinary GNSS profile has no auditable fixed target packet"
            )
        expected_packets = {expected_packet}
    else:
        expected_packets = set()
    if actual_packets != expected_packets:
        render = lambda values: sorted(
            value.decode("ascii").replace("\r", "\\r").replace("\n", "\\n")
            for value in values
        )
        raise MatrixError(
            "emitted GNSS PMTK251 packet set differs: "
            f"expected {render(expected_packets)}, found {render(actual_packets)}"
        )
    topology_markers_present = {
        "D14": b"D14" in image,
        "D8_GPIO20_GPIN0": b"D8_GPIO20_GPIN0" in image,
    }
    if characterization_enabled and not all(topology_markers_present.values()):
        raise MatrixError(
            "GNSS characterization binary omits the D14/D8 topology markers"
        )
    marker_presence = {
        name: marker in image
        for name, marker in GNSS_BAUD_CHARACTERIZATION_BINARY_MARKERS.items()
    }
    if characterization_enabled and not all(marker_presence.values()):
        missing = sorted(name for name, present in marker_presence.items()
                         if not present)
        raise MatrixError(
            "GNSS characterization binary omits required command/status "
            f"markers: {missing}"
        )
    return {
        "contract": "otis_gnss_fixed_packet_binary_contract_v1",
        "status": "verified",
        "characterization_transition_surface": (
            "enabled" if characterization_enabled else "disabled"
        ),
        "pmtk251_packets": sorted(
            packet.decode("ascii") for packet in actual_packets
        ),
        "characterization_markers": marker_presence,
        "dac_and_control_write_authority": {
            "OTIS_ENABLE_DAC_AD5693R": defines["OTIS_ENABLE_DAC_AD5693R"],
            "OTIS_ENABLE_H1_DAC_SWEEP": defines["OTIS_ENABLE_H1_DAC_SWEEP"],
            "OTIS_ENABLE_CX317_BOUNDED_ACTIVE": defines.get(
                "OTIS_ENABLE_CX317_BOUNDED_ACTIVE", "0"
            ),
            "OTIS_ENABLE_CX318_STAGE4_PREMISE_SETUP": defines.get(
                "OTIS_ENABLE_CX318_STAGE4_PREMISE_SETUP", "0"
            ),
            "OTIS_ENABLE_CX320_ACTIVE_HYBRID": defines.get(
                "OTIS_ENABLE_CX320_ACTIVE_HYBRID", "0"
            ),
            "OTIS_ENABLE_CX321_ACTIVE_HYBRID": defines.get(
                "OTIS_ENABLE_CX321_ACTIVE_HYBRID", "0"
            ),
            "OTIS_ENABLE_CX322_DIRECT_HYBRID": defines.get(
                "OTIS_ENABLE_CX322_DIRECT_HYBRID", "0"
            ),
            "OTIS_ENABLE_SUSTAINED_HYBRID_REGULATION": defines.get(
                "OTIS_ENABLE_SUSTAINED_HYBRID_REGULATION", "0"
            ),
        },
        "topology_markers_present": topology_markers_present,
        "campaign_contract": (
            {
                "path": str(
                    (
                        GNSS_BAUD_RESUME_CONTRACT
                        if profile.get("id") == GNSS_BAUD_RESUME_PROFILE_ID
                        else (
                            GNSS_BAUD_CONTINUATION_CONTRACT
                            if continuation_enabled
                            else GNSS_BAUD_CHARACTERIZATION_CONTRACT
                        )
                    ).relative_to(REPO_ROOT)
                ),
                "sha256": (
                    GNSS_BAUD_RESUME_CONTRACT_SHA256
                    if profile.get("id") == GNSS_BAUD_RESUME_PROFILE_ID
                    else (
                        GNSS_BAUD_CONTINUATION_CONTRACT_SHA256
                        if continuation_enabled
                        else GNSS_BAUD_CHARACTERIZATION_CONTRACT_SHA256
                    )
                ),
            }
            if characterization_enabled
            else None
        ),
        "startup_discovery": (
            {
                "opening_target_baud": 9600,
                "recovery_anchor_baud": 9600,
                "hint_baud": int(campaign_contract["startup_discovery"]["hint_baud"]),
                "hint_define": GNSS_BAUD_CHARACTERIZATION_STARTUP_HINT_DEFINE,
                "hint_define_value": defines.get(
                    GNSS_BAUD_CHARACTERIZATION_STARTUP_HINT_DEFINE
                ),
                "retain_define": GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_DEFINE,
                "retain_define_value": defines.get(
                    GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_DEFINE
                ),
                "provenance": campaign_contract["startup_discovery"],
            }
            if continuation_enabled
            else None
        ),
        "continuation": (
            {
                "profile_id": profile["id"],
                "retain_discovered_startup_baud": True,
                "provenance": campaign_contract["continuation"],
            }
            if continuation_enabled
            else None
        ),
    }


def _resource_usage_from_build_output(output: str) -> dict[str, int]:
    program_match = PROGRAM_USAGE_PATTERN.search(output)
    memory_match = DYNAMIC_MEMORY_USAGE_PATTERN.search(output)
    if program_match is None or memory_match is None:
        raise MatrixError(
            "successful firmware build did not emit the required resource usage report"
        )
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
        raise MatrixError("firmware resource usage report is internally inconsistent")
    return usage


def _enforce_resource_budgets(
    matrix: dict[str, Any], usage: dict[str, int]
) -> dict[str, Any]:
    budget = matrix["resource_budgets"]
    if usage["dynamic_memory_total_bytes"] != budget[
        "dynamic_memory_total_bytes"
    ]:
        raise MatrixError(
            "firmware build reported an unexpected dynamic-memory total: "
            f"{usage['dynamic_memory_total_bytes']}"
        )
    failures: list[str] = []
    if usage["static_dynamic_memory_used_bytes"] > budget[
        "static_dynamic_memory_max_bytes"
    ]:
        failures.append("static dynamic-memory maximum exceeded")
    if usage["runtime_memory_available_bytes"] < budget[
        "runtime_memory_reserve_min_bytes"
    ]:
        failures.append("runtime memory reserve is below minimum")
    if failures:
        raise MatrixError("; ".join(failures))
    return {
        "contract": "otis_firmware_resource_budget_v1",
        "status": "within_budget",
        "budget": dict(budget),
        "observed": usage,
    }


def _selected_profiles(
    matrix: dict[str, Any],
    requested: list[str],
    supported_only: bool,
    *,
    verification_tier: str | None = None,
    all_profiles: bool = False,
) -> list[dict[str, Any]]:
    profiles = matrix["profiles"]
    by_id = {profile["id"]: profile for profile in profiles}
    unknown = sorted(set(requested) - set(by_id))
    if unknown:
        raise MatrixError(f"unknown firmware profiles: {unknown}")
    if requested:
        selected = [by_id[item] for item in requested]
    elif all_profiles:
        selected = list(profiles)
    else:
        selected_tier = verification_tier or "release"
        if selected_tier not in VERIFICATION_TIERS:
            raise MatrixError(
                f"unknown verification tier: {selected_tier!r}"
            )
        selected = [
            profile
            for profile in profiles
            if selected_tier in profile["verification_tiers"]
        ]
    if supported_only:
        selected = [profile for profile in selected if profile["expect"] == "pass"]
    if not selected:
        raise MatrixError("no firmware profiles selected")
    return selected


def prepare_ide_profile(
    matrix: dict[str, Any],
    profile: dict[str, Any],
    *,
    arduino_cli: str = "arduino-cli",
    repo_root: Path = REPO_ROOT,
    sketch: Path = SKETCH,
    config_path: Path = CONFIG_HEADER,
    matrix_path: Path = DEFAULT_MATRIX,
    builder_path: Path = Path(__file__).resolve(),
) -> dict[str, Any]:
    """Materialize one validated profile for direct Arduino IDE compilation."""
    if profile["expect"] != "pass":
        raise MatrixError(
            f"cannot prepare expected-fail profile {profile['id']} for the IDE"
        )
    if not sketch.is_dir():
        raise MatrixError(f"Arduino sketch directory is unavailable: {sketch}")
    generated_header = sketch / GENERATED_HEADER_NAME
    if _path_has_symlink_component(generated_header):
        raise MatrixError(
            f"Arduino IDE generated profile path traverses a symbolic link: "
            f"{generated_header}"
        )
    if generated_header.exists() and not generated_header.is_file():
        raise MatrixError(
            f"Arduino IDE generated profile path is not a file: {generated_header}"
        )

    environment = verify_environment(matrix, arduino_cli=arduino_cli)
    source_snapshot = _capture_source_state(
        matrix,
        profile,
        repo_root=repo_root,
        sketch=sketch,
        config_path=config_path,
        matrix_path=matrix_path,
        builder_path=builder_path,
    )
    _verify_installed_environment(environment)
    provenance = build_provenance(
        matrix,
        profile,
        environment,
        git_commit=source_snapshot["git_commit"],
        source_state=source_snapshot["source_state"],
        source_sha256=source_snapshot["source_sha256"],
        build_session_id=secrets.token_hex(8),
        config_source_sha256=source_snapshot["config_source_sha256"],
    )
    previous_header = (
        generated_header.read_bytes() if generated_header.exists() else None
    )
    try:
        generated_header.write_text(
            provenance_header(provenance, ide_compatible=True),
            encoding="utf-8",
        )
        after_generation = _capture_source_state(
            matrix,
            profile,
            repo_root=repo_root,
            sketch=sketch,
            config_path=config_path,
            matrix_path=matrix_path,
            builder_path=builder_path,
        )
        _assert_source_unchanged(source_snapshot, after_generation)
        _verify_installed_environment(environment)
    except (OSError, MatrixError):
        if previous_header is None:
            generated_header.unlink(missing_ok=True)
        else:
            generated_header.write_bytes(previous_header)
        raise
    return {
        "path": str(generated_header.resolve()),
        "profile_id": profile["id"],
        "provenance": provenance,
    }


def _compile_profile(
    matrix: dict[str, Any],
    profile: dict[str, Any],
    provenance: dict[str, Any],
    output_dir: Path,
    arduino_cli: str,
    *,
    environment: dict[str, str],
    source_snapshot: dict[str, str],
    matrix_path: Path = DEFAULT_MATRIX,
) -> dict[str, Any]:
    profile_dir = output_dir / profile["id"]
    build_dir = profile_dir / "build"
    artifacts_dir = profile_dir / "artifacts"
    _validate_profile_output_paths(
        (output_dir, profile_dir, build_dir, artifacts_dir)
    )
    build_dir.mkdir(parents=True, exist_ok=True)
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    _reject_descendant_symlinks(build_dir)
    _reject_descendant_symlinks(artifacts_dir)
    _discard_artifacts(artifacts_dir)
    source_header = SKETCH / GENERATED_HEADER_NAME
    if source_header.is_symlink():
        raise MatrixError(
            f"source generated profile header is a symbolic link: {source_header}"
        )
    if source_header.exists() and not source_header.is_file():
        raise MatrixError(
            f"source generated profile header is not a file: {source_header}"
        )

    temporary_sketch_path: Path | None = None
    with tempfile.TemporaryDirectory(
        prefix="temporary_sketch_", dir=profile_dir
    ) as temporary_root_value:
        temporary_root = Path(temporary_root_value)
        temporary_sketch_path = temporary_root / SKETCH.name
        shutil.copytree(SKETCH, temporary_sketch_path)
        generated_header_text = provenance_header(provenance)
        (temporary_sketch_path / GENERATED_HEADER_NAME).write_text(
            generated_header_text, encoding="utf-8"
        )
        command = [
            arduino_cli,
            "compile",
            "--clean",
            "--fqbn",
            str(matrix["target"]["fqbn"]),
            "--build-path",
            str(build_dir),
            "--output-dir",
            str(artifacts_dir),
            "--build-property",
            "compiler.cpp.extra_flags="
            f"-DOTIS_BUILD_SESSION_ID=0x"
            f"{provenance['invocation']['build_session_id']}ULL",
            str(temporary_sketch_path),
        ]
        result = _run(command, check=False)
        combined = result.stdout + result.stderr
        (profile_dir / "build.log").write_text(combined, encoding="utf-8")

        after_compile = _capture_source_state(
            matrix,
            profile,
            matrix_path=matrix_path,
        )
        try:
            _assert_source_unchanged(source_snapshot, after_compile)
        except MatrixError:
            _discard_artifacts(artifacts_dir)
            raise

    if temporary_sketch_path.exists():
        raise MatrixError("temporary firmware source was not removed after compilation")
    try:
        _reject_descendant_symlinks(build_dir)
        _reject_descendant_symlinks(artifacts_dir)
    except MatrixError:
        _discard_artifacts(artifacts_dir)
        raise
    for copied_header in build_dir.rglob(GENERATED_HEADER_NAME):
        copied_header.unlink()
    if any(build_dir.rglob(GENERATED_HEADER_NAME)):
        raise MatrixError("transient generated profile header was not removed")
    try:
        _verify_installed_environment(environment)
    except MatrixError:
        _discard_artifacts(artifacts_dir)
        raise

    expected = profile["expect"]
    passed = result.returncode == 0
    outcome_matches = passed if expected == "pass" else not passed
    error_matched = True
    if expected == "fail":
        error_matched = profile["expected_error"] in combined
        outcome_matches = outcome_matches and error_matched
    build_manifest_path = artifacts_dir / "firmware_build_manifest.json"
    if passed:
        (artifacts_dir / GENERATED_HEADER_NAME).write_text(
            generated_header_text, encoding="utf-8"
        )
        resource_usage = _resource_usage_from_build_output(combined)
        resource_report = _enforce_resource_budgets(matrix, resource_usage)
        gnss_binary_contract = _gnss_binary_contract(profile, artifacts_dir)
        d9_d6_binary_contract = _d9_d6_binary_contract(profile, artifacts_dir)
        artifacts = _artifact_hashes(artifacts_dir)
        after_hashing = _capture_source_state(
            matrix,
            profile,
            matrix_path=matrix_path,
        )
        try:
            _assert_source_unchanged(source_snapshot, after_hashing)
            _verify_installed_environment(environment)
        except MatrixError:
            _discard_artifacts(artifacts_dir)
            raise
        _write_json(
            build_manifest_path,
            {
                "schema_version": 1,
                "provenance": provenance,
                "resource_budget": resource_report,
                "gnss_binary_contract": gnss_binary_contract,
                "d9_d6_binary_contract": d9_d6_binary_contract,
                "artifacts": artifacts,
            },
        )
    return {
        "profile_id": profile["id"],
        "expect": expected,
        "returncode": result.returncode,
        "outcome": "pass" if passed else "fail",
        "expected_error_matched": error_matched,
        "verified": outcome_matches,
        "config_sha256": provenance["configuration"]["sha256"],
        "invocation_id": provenance["invocation"]["id"],
        "build_log": str((profile_dir / "build.log").resolve()),
        "build_manifest": str(build_manifest_path.resolve()) if passed else None,
    }


def run_matrix(
    matrix: dict[str, Any],
    profiles: list[dict[str, Any]],
    output_dir: Path,
    *,
    arduino_cli: str = "arduino-cli",
    matrix_path: Path = DEFAULT_MATRIX,
) -> list[dict[str, Any]]:
    _validate_profile_output_paths((output_dir,))
    summary_path = output_dir / "matrix_summary.json"
    if summary_path.exists():
        summary_path.unlink()
    environment = verify_environment(matrix, arduino_cli=arduino_cli)
    results: list[dict[str, Any]] = []
    touched_profile_ids: list[str] = []
    matrix_snapshot = _capture_source_state(
        matrix,
        profiles[0],
        matrix_path=matrix_path,
    )
    matrix_identity = _matrix_source_identity(matrix_snapshot)
    try:
        for profile in profiles:
            source_snapshot = _capture_source_state(
                matrix,
                profile,
                matrix_path=matrix_path,
            )
            _assert_source_unchanged(
                matrix_identity,
                _matrix_source_identity(source_snapshot),
            )
            _verify_installed_environment(environment)
            provenance = build_provenance(
                matrix,
                profile,
                environment,
                git_commit=source_snapshot["git_commit"],
                source_state=source_snapshot["source_state"],
                source_sha256=source_snapshot["source_sha256"],
                build_session_id=secrets.token_hex(8),
                config_source_sha256=source_snapshot["config_source_sha256"],
            )
            print(
                f"[{profile['expect']}] {profile['id']} "
                f"config={provenance['configuration']['sha256'][:12]}",
                flush=True,
            )
            profile_id = str(profile["id"])
            profile_dir = output_dir / profile_id
            _validate_profile_output_paths(
                (
                    output_dir,
                    profile_dir,
                    profile_dir / "build",
                    profile_dir / "artifacts",
                )
            )
            touched_profile_ids.append(profile_id)
            result = _compile_profile(
                matrix,
                profile,
                provenance,
                output_dir,
                arduino_cli,
                environment=environment,
                source_snapshot=source_snapshot,
                matrix_path=matrix_path,
            )
            results.append(result)
            print(
                f"  outcome={result['outcome']} verified={result['verified']}",
                flush=True,
            )
        final_snapshot = _capture_source_state(
            matrix,
            profiles[0],
            matrix_path=matrix_path,
        )
        _assert_source_unchanged(
            matrix_identity,
            _matrix_source_identity(final_snapshot),
        )
        _verify_installed_environment(environment)
    except MatrixError:
        _discard_matrix_artifacts(
            output_dir,
            touched_profile_ids,
        )
        if summary_path.exists():
            summary_path.unlink()
        raise
    try:
        matrix_name = str(matrix_path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        matrix_name = str(matrix_path.resolve())
    summary = {
        "schema_version": 1,
        "matrix": matrix_name,
        "git_commit": matrix_identity["git_commit"],
        "source_state": matrix_identity["source_state"],
        "all_verified": all(result["verified"] for result in results),
        "results": results,
    }
    _write_json(summary_path, summary)
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compile the pinned, intentional OTIS Arduino firmware matrix."
    )
    parser.add_argument(
        "--matrix",
        type=Path,
        default=DEFAULT_MATRIX,
        help="Pinned matrix JSON (default: firmware/arduino/firmware_matrix.json).",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=REPO_ROOT / "build" / "firmware_matrix",
        help="Ignored build/artifact directory.",
    )
    parser.add_argument(
        "--profile",
        action="append",
        default=[],
        help="Build one profile id; repeat to select several.",
    )
    parser.add_argument(
        "--supported-only",
        action="store_true",
        help="Skip expected-fail guard profiles.",
    )
    parser.add_argument(
        "--tier",
        choices=sorted(VERIFICATION_TIERS),
        help=(
            "Select profiles assigned to one executable verification tier; "
            "defaults to release when no profile or --all-profiles is named."
        ),
    )
    parser.add_argument(
        "--all-profiles",
        action="store_true",
        help="Include archived profiles for an explicit historical matrix run.",
    )
    parser.add_argument(
        "--check-environment",
        action="store_true",
        help="Verify the pinned CLI/core/toolchain without compiling.",
    )
    parser.add_argument(
        "--prepare-ide",
        action="store_true",
        help=(
            "Generate one supported profile in the source sketch for direct "
            "Arduino IDE compilation (requires exactly one --profile)."
        ),
    )
    parser.add_argument(
        "--list",
        action="store_true",
        help="List the intentional matrix without inspecting the toolchain.",
    )
    parser.add_argument(
        "--arduino-cli",
        default="arduino-cli",
        help="Arduino CLI executable (version remains pinned).",
    )
    args = parser.parse_args(argv)

    try:
        matrix = load_matrix(args.matrix.resolve())
        if args.prepare_ide and (args.list or args.check_environment):
            raise MatrixError(
                "--prepare-ide cannot be combined with --list or "
                "--check-environment"
            )
        if args.prepare_ide and len(args.profile) != 1:
            raise MatrixError(
                "--prepare-ide requires exactly one explicit --profile"
            )
        if args.all_profiles and (args.profile or args.tier):
            raise MatrixError(
                "--all-profiles cannot be combined with --profile or --tier"
            )
        selected = _selected_profiles(
            matrix,
            list(args.profile),
            args.supported_only,
            verification_tier=args.tier,
            all_profiles=args.all_profiles,
        )
        if args.list:
            for profile in selected:
                print(
                    f"{profile['id']}\t{profile['expect']}\t"
                    f"{profile['lifecycle']}\t"
                    f"{','.join(profile['verification_tiers'])}\t"
                    f"{profile.get('purpose', '')}"
                )
            return 0
        if args.check_environment:
            environment = verify_environment(
                matrix, arduino_cli=args.arduino_cli
            )
            print(json.dumps(environment, indent=2, sort_keys=True))
            return 0
        if args.prepare_ide:
            prepared = prepare_ide_profile(
                matrix,
                selected[0],
                arduino_cli=args.arduino_cli,
                matrix_path=args.matrix.resolve(),
            )
            provenance = prepared["provenance"]
            print(
                f"Prepared Arduino IDE profile {prepared['profile_id']} at "
                f"{prepared['path']}"
            )
            print(
                "Regenerate before compiling after any source, profile, or "
                "toolchain change."
            )
            print(
                f"source={provenance['source']['sha256']} "
                f"config={provenance['configuration']['sha256']}"
            )
            return 0
        results = run_matrix(
            matrix,
            selected,
            args.output_dir.absolute(),
            arduino_cli=args.arduino_cli,
            matrix_path=args.matrix.resolve(),
        )
    except (MatrixError, json.JSONDecodeError) as exc:
        print(f"firmware matrix error: {exc}", file=sys.stderr)
        return 2
    return 0 if all(result["verified"] for result in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
