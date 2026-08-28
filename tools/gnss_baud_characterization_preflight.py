#!/usr/bin/env python3
"""Structural no-I/O preflight for the GNSS baud characterization firmware."""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import tempfile
from typing import Any

try:
    from tools.firmware_matrix import (
        DEFAULT_MATRIX,
        GENERATED_HEADER_NAME,
        GNSS_BAUD_CONTINUATION_CONTRACT as GNSS_BAUD_CHARACTERIZATION_CONTRACT,
        GNSS_BAUD_CONTINUATION_CONTRACT_SHA256 as GNSS_BAUD_CHARACTERIZATION_CONTRACT_SHA256,
        GNSS_BAUD_CHARACTERIZATION_PACKETS,
        GNSS_BAUD_CONTINUATION_PROFILE_ID as GNSS_BAUD_CHARACTERIZATION_PROFILE_ID,
        GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_DEFINE,
        GNSS_BAUD_CHARACTERIZATION_STARTUP_HINT_BAUD,
        GNSS_BAUD_CHARACTERIZATION_STARTUP_HINT_DEFINE,
        GNSS_BAUD_RESUME_CONTRACT,
        GNSS_BAUD_RESUME_CONTRACT_SHA256,
        GNSS_BAUD_RESUME_PROFILE_ID,
        MatrixError,
        REPO_ROOT,
        SKETCH,
        _gnss_baud_continuation_contract as _gnss_baud_contract,
        _gnss_baud_resume_contract,
        _gnss_binary_contract,
        configuration_hash,
        load_matrix,
        source_input_hash,
    )
except ModuleNotFoundError:
    from firmware_matrix import (  # type: ignore[no-redef]
        DEFAULT_MATRIX,
        GENERATED_HEADER_NAME,
        GNSS_BAUD_CONTINUATION_CONTRACT as GNSS_BAUD_CHARACTERIZATION_CONTRACT,
        GNSS_BAUD_CONTINUATION_CONTRACT_SHA256 as GNSS_BAUD_CHARACTERIZATION_CONTRACT_SHA256,
        GNSS_BAUD_CHARACTERIZATION_PACKETS,
        GNSS_BAUD_CONTINUATION_PROFILE_ID as GNSS_BAUD_CHARACTERIZATION_PROFILE_ID,
        GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_DEFINE,
        GNSS_BAUD_CHARACTERIZATION_STARTUP_HINT_BAUD,
        GNSS_BAUD_CHARACTERIZATION_STARTUP_HINT_DEFINE,
        GNSS_BAUD_RESUME_CONTRACT,
        GNSS_BAUD_RESUME_CONTRACT_SHA256,
        GNSS_BAUD_RESUME_PROFILE_ID,
        MatrixError,
        REPO_ROOT,
        SKETCH,
        _gnss_baud_continuation_contract as _gnss_baud_contract,
        _gnss_baud_resume_contract,
        _gnss_binary_contract,
        configuration_hash,
        load_matrix,
        source_input_hash,
    )


TOOL_ID = "otis_gnss_baud_characterization_profile_preflight_v1"
EXPECTED_ARTIFACT_SUFFIXES = {".bin", ".elf", ".h", ".map", ".uf2"}


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _atomic_json(path: Path, value: object) -> None:
    path = path.resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        json.dump(value, handle, indent=2, sort_keys=True, allow_nan=False)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _source_guard(sketch_dir: Path = SKETCH) -> dict[str, Any]:
    receiver = (sketch_dir / "otis_gnss_receiver.cpp").read_text(encoding="utf-8")
    serial_command = (sketch_dir / "otis_serial_command.cpp").read_text(
        encoding="utf-8"
    )
    config = (sketch_dir / "otis_config.h").read_text(encoding="utf-8")
    board = (sketch_dir / "otis_board.h").read_text(encoding="utf-8")
    sketch = (sketch_dir / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    uart_ring_header = (sketch_dir / "otis_gnss_uart_rx.h").read_text(
        encoding="utf-8"
    )
    uart_ring_source = (sketch_dir / "otis_gnss_uart_rx.cpp").read_text(
        encoding="utf-8"
    )
    packet_pattern = re.compile(
        r'"(\$PMTK251,[0-9]+\*[0-9A-F]{2}\\r\\n)"'
    )
    source_packets = {
        value.replace("\\r", "\r").replace("\\n", "\n").encode("ascii")
        for value in packet_pattern.findall(receiver)
    }
    if source_packets != GNSS_BAUD_CHARACTERIZATION_PACKETS:
        raise ValueError("firmware source does not contain exactly five PMTK251 packets")
    if receiver.count("uart_get_hw(uart0)->dr =") != 1:
        raise ValueError("GNSS source must retain one bounded UART0 write primitive")
    for forbidden in (
        "uart_putc",
        "uart_puts",
        "uart_write_blocking",
        "Serial1.write",
        "Serial1.print",
        '"GNSS RAW ',
        '"GNSS WRITE ',
        '"UART WRITE ',
    ):
        if forbidden in receiver or forbidden in serial_command or forbidden in sketch:
            raise ValueError(f"generic GNSS/UART write surface is present: {forbidden}")
    required_config_guards = (
        "OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION",
        "OTIS_BUILD_EXPECTED_OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION",
        GNSS_BAUD_CHARACTERIZATION_STARTUP_HINT_DEFINE,
        f"OTIS_BUILD_EXPECTED_{GNSS_BAUD_CHARACTERIZATION_STARTUP_HINT_DEFINE}",
        GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_DEFINE,
        f"OTIS_BUILD_EXPECTED_{GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_DEFINE}",
        "GNSS baud characterization requires",
    )
    if any(value not in config for value in required_config_guards):
        raise ValueError("characterization compile/profile guards are incomplete")
    if (
        "OTIS_GNSS_COMMAND_RESPONSE_TIMEOUT_MS" not in config
        or "link->policy.response_timeout_ms" not in receiver
    ):
        raise ValueError("startup identity response-window binding is incomplete")
    if (
        'strncmp(command, "GNSS BAUD ",' not in serial_command
        or 'strncmp(command, "GNSS STATUS ",' not in serial_command
        or "OtisSerialCommandKind::GnssOther" not in serial_command
    ):
        raise ValueError("bounded GNSS characterization command parser is incomplete")
    required_sketch_surface = (
        "OtisSerialCommandKind::GnssBaud",
        "OtisSerialCommandKind::GnssStatus",
        "OtisSerialCommandKind::GnssOther",
        "otis_gnss_receiver_request_baud_transition",
        "otis_gnss_receiver_begin_status_challenge",
        "otis_gnss_receiver_complete_status_challenge",
        "otis_gnss_receiver_finish_status_snapshot",
        '"snapshot", "begin"',
        '"snapshot", "end"',
        '"snapshot_generation"',
        '"request_seq"',
        '"metadata_frontier"',
        '"extended_counter_ticks"',
        '"phase_window_ring_high_water"',
        '"target_command_transmit_complete"',
        '"target_identity_confirmed"',
        '"target_output_confirmed"',
    )
    if any(marker not in sketch for marker in required_sketch_surface):
        raise ValueError("live GNSS command/coherent telemetry surface is incomplete")
    required_ring_surface = (
        "kOtisGnssUartRxRingCapacity = 1024u",
        "kOtisGnssUartRxConsumerByteBudget = 128u",
        "kOtisGnssUartRxConsumerTickBudget = 4000u",
        "phase_window_maximum_interrupt_residence_ticks",
        "last_consumer_service_gap_ticks",
    )
    if any(marker not in uart_ring_header for marker in required_ring_surface):
        raise ValueError("interrupt-backed GNSS UART ring contract is incomplete")
    if (
        "otis_gnss_uart_rx_ring_push_from_isr" not in uart_ring_source
        or "uart_get_hw(uart0)->dr =" not in receiver
        or "while ((hardware->fr & UART_UARTFR_RXFE_BITS) == 0u)" not in receiver
    ):
        raise ValueError("GNSS ISR drain-to-ring path is incomplete")
    if (
        "OTIS_PIN_PPS_REFERENCE = D14" not in board
        or "OTIS_PIN_OSC_OBSERVATION = D8" not in board
    ):
        raise ValueError("D14/D8 authoritative topology mapping differs")
    return {
        "status": "verified",
        "pmtk251_packet_count": len(source_packets),
        "bounded_uart0_write_primitives": 1,
        "generic_receiver_byte_surface": "absent",
        "characterization_commands": ["GNSS BAUD", "GNSS STATUS"],
        "coherent_status_surface": "begin_end_with_platform_and_uart_counters",
        "startup_identity_response_timeout_source": (
            "frozen_contract_checked_exact_profile_define"
        ),
        "startup_discovery_hint_source": (
            "sealed_observed_serial_baud_checked_exact_profile_define"
        ),
        "uart_rx_ring": "interrupt_backed_1024_entries",
        "topology": {"reference_authority": "D14", "oscillator_input": "D8"},
    }


def _artifact_bindings(
    manifest_path: Path, manifest: dict[str, Any]
) -> tuple[dict[str, dict[str, Any]], Path]:
    artifacts_dir = manifest_path.parent.resolve()
    entries = manifest.get("artifacts")
    if not isinstance(entries, list):
        raise ValueError("firmware build manifest artifacts must be an array")
    by_suffix: dict[str, dict[str, Any]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError("firmware artifact binding must be an object")
        name = str(entry.get("name", ""))
        suffix = Path(name).suffix
        if suffix in by_suffix or suffix not in EXPECTED_ARTIFACT_SUFFIXES:
            raise ValueError("firmware artifact suffix set differs")
        path = artifacts_dir / name
        if (
            path.parent.resolve() != artifacts_dir
            or path.is_symlink()
            or not path.is_file()
            or path.stat().st_size != entry.get("size_bytes")
            or _sha256_file(path) != entry.get("sha256")
        ):
            raise ValueError(f"firmware artifact identity differs: {name}")
        by_suffix[suffix] = dict(entry)
    if set(by_suffix) != EXPECTED_ARTIFACT_SUFFIXES:
        raise ValueError("firmware artifact set is incomplete")
    if by_suffix[".h"]["name"] != GENERATED_HEADER_NAME:
        raise ValueError("generated build profile header artifact is misnamed")
    return by_suffix, artifacts_dir


def create_preflight(
    *, build_manifest_path: Path, output_path: Path | None = None
) -> dict[str, Any]:
    """Validate one exact built profile without opening or changing hardware."""
    matrix = load_matrix(DEFAULT_MATRIX)
    manifest_path = build_manifest_path.resolve()
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read firmware build manifest: {exc}") from exc
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise ValueError("firmware build manifest identity differs")
    provenance = manifest.get("provenance", {})
    configuration = provenance.get("configuration", {})
    profile_id = str(configuration.get("profile_id", ""))
    if profile_id == GNSS_BAUD_RESUME_PROFILE_ID:
        contract = _gnss_baud_resume_contract()
        contract_path = GNSS_BAUD_RESUME_CONTRACT
        contract_sha256 = GNSS_BAUD_RESUME_CONTRACT_SHA256
    elif profile_id == GNSS_BAUD_CHARACTERIZATION_PROFILE_ID:
        contract = _gnss_baud_contract()
        contract_path = GNSS_BAUD_CHARACTERIZATION_CONTRACT
        contract_sha256 = GNSS_BAUD_CHARACTERIZATION_CONTRACT_SHA256
    else:
        raise ValueError("unsupported GNSS characterization preflight profile")
    profile = next(item for item in matrix["profiles"] if item["id"] == profile_id)
    source = provenance.get("source", {})
    invocation = provenance.get("invocation", {})
    if (
        configuration.get("profile_id") != profile_id
        or configuration.get("defines") != profile["defines"]
        or configuration.get("sha256") != configuration_hash(matrix, profile)
        or source.get("sha256") != source_input_hash()
        or not isinstance(invocation.get("id"), str)
        or len(invocation["id"]) != 64
    ):
        raise ValueError("firmware build provenance differs from current exact profile")
    by_suffix, artifacts_dir = _artifact_bindings(manifest_path, manifest)
    resource_budget = manifest.get("resource_budget", {})
    if (
        resource_budget.get("status") != "within_budget"
        or resource_budget.get("budget") != matrix["resource_budgets"]
    ):
        raise ValueError("firmware build memory budget is absent or failed")
    observed = resource_budget.get("observed", {})
    if (
        int(observed.get("static_dynamic_memory_used_bytes", -1))
        > matrix["resource_budgets"]["static_dynamic_memory_max_bytes"]
        or int(observed.get("runtime_memory_available_bytes", -1))
        < matrix["resource_budgets"]["runtime_memory_reserve_min_bytes"]
    ):
        raise ValueError("firmware build memory observations exceed the frozen bound")
    binary_contract = _gnss_binary_contract(profile, artifacts_dir)
    if manifest.get("gnss_binary_contract") != binary_contract:
        raise ValueError("firmware build binary contract report differs")
    header = (artifacts_dir / GENERATED_HEADER_NAME).read_text(encoding="utf-8")
    startup_discovery = contract["startup_discovery"]
    startup_hint_baud = int(startup_discovery["hint_baud"])
    expected_hint_define = (
        f"#define {GNSS_BAUD_CHARACTERIZATION_STARTUP_HINT_DEFINE} "
        f"{startup_hint_baud}u"
    )
    expected_retain_define = (
        f"#define {GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_DEFINE} 1"
    )
    if (
        f'#define OTIS_BUILD_PROFILE_ID "{profile_id}"'
        not in header
        or "#define OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION 1" not in header
        or "#define OTIS_ENABLE_DAC_AD5693R 0" not in header
        or expected_hint_define not in header
        or expected_retain_define not in header
    ):
        raise ValueError(
            "generated profile header does not bind the no-DAC profile and "
            "startup discovery hint"
        )
    source_guard = _source_guard()
    checks = {
        "frozen_contract_identity": True,
        "exact_profile_and_current_source_identity": True,
        "no_dac_or_control_authority": True,
        "generated_profile_header_retained": True,
        "startup_discovery_hint_bound_to_sealed_observed_baud": True,
        "five_packet_binary_contract": True,
        "D14_D8_topology_source_and_binary": True,
        "memory_budget_within_bound": True,
        "all_artifact_hashes_and_sizes": True,
        "physical_authority_false": contract["authority"]["physical_authority"]
        is False,
    }
    result = {
        "schema_version": 1,
        "tool": TOOL_ID,
        "status": "passed" if all(checks.values()) else "failed",
        "programme_id": contract["programme_id"],
        "profile_id": profile_id,
        "contract": {
            "path": str(contract_path.relative_to(REPO_ROOT)),
            "sha256": contract_sha256,
        },
        "build_manifest": {
            "path": str(manifest_path),
            "sha256": _sha256_file(manifest_path),
        },
        "configuration_sha256": configuration["sha256"],
        "source_sha256": source["sha256"],
        "invocation_id": invocation["id"],
        "startup_discovery": startup_discovery,
        "artifacts": [by_suffix[key] for key in sorted(by_suffix)],
        "resource_budget": resource_budget,
        "binary_contract": binary_contract,
        "source_guard": source_guard,
        "checks": checks,
        "hardware_operations": {
            "serial_devices_opened": 0,
            "bytes_transmitted": 0,
            "firmware_flashes": 0,
            "board_resets": 0,
            "dac_writes": 0,
            "receiver_baud_changes": 0,
        },
    }
    if result["status"] != "passed":
        raise ValueError("GNSS baud characterization profile preflight failed")
    if output_path is not None:
        _atomic_json(output_path, result)
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-manifest", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        result = create_preflight(
            build_manifest_path=args.build_manifest, output_path=args.output
        )
    except (MatrixError, ValueError) as exc:
        parser.error(str(exc))
    print(
        f"GNSS baud characterization profile preflight {result['status']}: "
        f"{args.output.resolve()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
