from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path

import pytest

from tools import gnss_baud_characterization_preflight as preflight
from tools.firmware_matrix import (
    DEFAULT_MATRIX,
    GENERATED_HEADER_NAME,
    GNSS_BAUD_CHARACTERIZATION_BINARY_MARKERS,
    GNSS_BAUD_CHARACTERIZATION_PACKETS,
    GNSS_BAUD_CONTINUATION_CONTRACT_SHA256,
    GNSS_BAUD_CONTINUATION_PROFILE_ID,
    _gnss_binary_contract,
    configuration_hash,
    load_matrix,
    source_input_hash,
)

GNSS_BAUD_CHARACTERIZATION_CONTRACT_SHA256 = (
    GNSS_BAUD_CONTINUATION_CONTRACT_SHA256
)
GNSS_BAUD_CHARACTERIZATION_PROFILE_ID = GNSS_BAUD_CONTINUATION_PROFILE_ID


def _artifact(path: Path) -> dict[str, object]:
    return {
        "name": path.name,
        "size_bytes": path.stat().st_size,
        "sha256": sha256(path.read_bytes()).hexdigest(),
    }


def _synthetic_build(tmp_path: Path) -> Path:
    matrix = load_matrix(DEFAULT_MATRIX)
    profile = next(
        item
        for item in matrix["profiles"]
        if item["id"] == GNSS_BAUD_CHARACTERIZATION_PROFILE_ID
    )
    binary_image = (
        b"synthetic BIN D14 D8_GPIO20_GPIN0\x00"
        + b"\x00".join(sorted(GNSS_BAUD_CHARACTERIZATION_PACKETS))
        + b"\x00"
        + b"\x00".join(GNSS_BAUD_CHARACTERIZATION_BINARY_MARKERS.values())
    )
    elf = tmp_path / "candidate.elf"
    elf.write_bytes(b"synthetic ELF with debug metadata")
    binary = tmp_path / "candidate.bin"
    binary.write_bytes(binary_image)
    map_file = tmp_path / "candidate.map"
    map_file.write_bytes(b"synthetic map")
    uf2 = tmp_path / "candidate.uf2"
    uf2.write_bytes(b"synthetic uf2")
    header = tmp_path / GENERATED_HEADER_NAME
    header.write_text(
        '#define OTIS_BUILD_PROFILE_ID "'
        + GNSS_BAUD_CHARACTERIZATION_PROFILE_ID
        + '"\n#define OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION 1\n'
        + "#define OTIS_ENABLE_DAC_AD5693R 0\n"
        + "#define OTIS_GNSS_DISCOVERY_STARTUP_BAUD_HINT 57600u\n"
        + "#define OTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD 1\n",
        encoding="utf-8",
    )
    manifest = {
        "schema_version": 1,
        "provenance": {
            "source": {
                "git_commit": "1" * 40,
                "state": "synthetic",
                "sha256": source_input_hash(),
            },
            "configuration": {
                "profile_id": GNSS_BAUD_CHARACTERIZATION_PROFILE_ID,
                "defines": profile["defines"],
                "sha256": configuration_hash(matrix, profile),
            },
            "invocation": {"id": "2" * 64},
        },
        "resource_budget": {
            "contract": "otis_firmware_resource_budget_v1",
            "status": "within_budget",
            "budget": matrix["resource_budgets"],
            "observed": {
                "static_dynamic_memory_used_bytes": 140000,
                "runtime_memory_available_bytes": 122144,
                "dynamic_memory_total_bytes": 262144,
            },
        },
        "gnss_binary_contract": _gnss_binary_contract(profile, tmp_path),
        "artifacts": [
            _artifact(path)
            for path in (binary, elf, header, map_file, uf2)
        ],
    }
    path = tmp_path / "firmware_build_manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return path


def _synthetic_source(tmp_path: Path) -> Path:
    (tmp_path / "otis_gnss_receiver.cpp").write_text(
        "\n".join(
            [
                f'constexpr char packet[] = "{packet.decode("ascii").replace(chr(13), "\\r").replace(chr(10), "\\n")}";'
                for packet in sorted(GNSS_BAUD_CHARACTERIZATION_PACKETS)
            ]
            + [
                "uart_get_hw(uart0)->dr = byte;",
                "while ((hardware->fr & UART_UARTFR_RXFE_BITS) == 0u) {}",
                "link->policy.response_timeout_ms;",
            ]
        ),
        encoding="utf-8",
    )
    (tmp_path / "otis_serial_command.cpp").write_text(
        'strncmp(command, "GNSS BAUD ", 11);\n'
        'strncmp(command, "GNSS STATUS ", 12);\n'
        "OtisSerialCommandKind::GnssOther;\n",
        encoding="utf-8",
    )
    (tmp_path / "otis_config.h").write_text(
        "OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION\n"
        "OTIS_BUILD_EXPECTED_OTIS_ENABLE_GNSS_BAUD_CHARACTERIZATION\n"
        "OTIS_GNSS_DISCOVERY_STARTUP_BAUD_HINT\n"
        "OTIS_BUILD_EXPECTED_OTIS_GNSS_DISCOVERY_STARTUP_BAUD_HINT\n"
        "OTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD\n"
        "OTIS_BUILD_EXPECTED_OTIS_GNSS_BAUD_CHARACTERIZATION_RETAIN_DISCOVERED_STARTUP_BAUD\n"
        "OTIS_GNSS_COMMAND_RESPONSE_TIMEOUT_MS\n"
        "GNSS baud characterization requires\n",
        encoding="utf-8",
    )
    (tmp_path / "otis_board.h").write_text(
        "OTIS_PIN_PPS_REFERENCE = D14;\nOTIS_PIN_OSC_OBSERVATION = D8;\n",
        encoding="utf-8",
    )
    (tmp_path / "otis_nano_rp2040_connect.ino").write_text(
        "\n".join(
            (
                "OtisSerialCommandKind::GnssBaud",
                "OtisSerialCommandKind::GnssStatus",
                "OtisSerialCommandKind::GnssOther",
                "otis_gnss_receiver_request_baud_transition",
                "otis_gnss_receiver_begin_status_challenge",
                "otis_gnss_receiver_complete_status_challenge",
                "otis_gnss_receiver_finish_status_snapshot",
                'emit_status(component, \"snapshot\", \"begin\");',
                'emit_status(component, \"snapshot\", \"end\");',
                '"snapshot_generation"',
                '"request_seq"',
                '"metadata_frontier"',
                '"extended_counter_ticks"',
                '"phase_window_ring_high_water"',
                '"target_command_transmit_complete"',
                '"target_identity_confirmed"',
                '"target_output_confirmed"',
            )
        ),
        encoding="utf-8",
    )
    (tmp_path / "otis_gnss_uart_rx.h").write_text(
        "\n".join(
            (
                "kOtisGnssUartRxRingCapacity = 1024u",
                "kOtisGnssUartRxConsumerByteBudget = 128u",
                "kOtisGnssUartRxConsumerTickBudget = 4000u",
                "phase_window_maximum_interrupt_residence_ticks",
                "last_consumer_service_gap_ticks",
            )
        ),
        encoding="utf-8",
    )
    (tmp_path / "otis_gnss_uart_rx.cpp").write_text(
        "otis_gnss_uart_rx_ring_push_from_isr\n", encoding="utf-8"
    )
    return tmp_path


def test_source_guard_proves_fixed_packets_bounded_commands_and_topology(
    tmp_path: Path,
) -> None:
    source = _synthetic_source(tmp_path)

    result = preflight._source_guard(source)

    assert result["status"] == "verified"
    assert result["pmtk251_packet_count"] == 5
    assert result["bounded_uart0_write_primitives"] == 1
    assert result["generic_receiver_byte_surface"] == "absent"
    assert result["topology"] == {
        "reference_authority": "D14",
        "oscillator_input": "D8",
    }

    serial_command = source / "otis_serial_command.cpp"
    serial_command.write_text(
        serial_command.read_text(encoding="utf-8") + '"GNSS RAW payload"\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="generic GNSS/UART write surface"):
        preflight._source_guard(source)


def test_profile_preflight_binds_exact_build_without_hardware(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _synthetic_build(tmp_path)
    monkeypatch.setattr(
        preflight,
        "_source_guard",
        lambda: {"status": "verified", "fixture": True},
    )
    output = tmp_path / "preflight.json"

    result = preflight.create_preflight(
        build_manifest_path=manifest, output_path=output
    )

    assert result["status"] == "passed"
    assert result["profile_id"] == GNSS_BAUD_CHARACTERIZATION_PROFILE_ID
    assert result["contract"]["sha256"] == (
        GNSS_BAUD_CHARACTERIZATION_CONTRACT_SHA256
    )
    assert all(result["checks"].values())
    assert set(result["hardware_operations"].values()) == {0}
    assert json.loads(output.read_text(encoding="utf-8")) == result


def test_profile_preflight_rejects_artifact_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _synthetic_build(tmp_path)
    monkeypatch.setattr(
        preflight,
        "_source_guard",
        lambda: {"status": "verified", "fixture": True},
    )
    (tmp_path / "candidate.uf2").write_bytes(b"tampered")

    with pytest.raises(ValueError, match="artifact identity differs"):
        preflight.create_preflight(build_manifest_path=manifest)


def test_profile_preflight_rejects_failed_memory_bound(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest = _synthetic_build(tmp_path)
    value = json.loads(manifest.read_text(encoding="utf-8"))
    value["resource_budget"]["status"] = "failed"
    manifest.write_text(json.dumps(value), encoding="utf-8")
    monkeypatch.setattr(
        preflight,
        "_source_guard",
        lambda: {"status": "verified", "fixture": True},
    )

    with pytest.raises(ValueError, match="memory budget"):
        preflight.create_preflight(build_manifest_path=manifest)
