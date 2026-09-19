from __future__ import annotations

import csv
import io
from pathlib import Path
import shutil
import subprocess

import pytest

from host.otis_tools.firmware_host_contract import (
    RECORD_TYPE_TO_CONTRACT,
    validate_record_wire_values,
)


FIRMWARE = Path("firmware/arduino/otis_nano_rp2040_connect")


def _compiler() -> str:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is not available")
    return compiler


@pytest.fixture(scope="module")
def framing_harness(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("serial_framing") / "serial_framing"
    subprocess.run(
        [
            _compiler(),
            "-std=c++17",
            f"-I{FIRMWARE}",
            str(Path("tests/cpp/serial_command_framing_harness.cpp")),
            str(FIRMWARE / "otis_serial_command.cpp"),
            "-o",
            str(output),
        ],
        check=True,
    )
    return output


def _events(harness: Path, payload: bytes) -> list[str]:
    completed = subprocess.run(
        [str(harness)],
        input=payload,
        stdout=subprocess.PIPE,
        check=True,
    )
    return completed.stdout.decode("ascii").splitlines()


def test_firmware_services_collection_validation_parsing_then_execution() -> None:
    source = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    service = source[
        source.index("void service_serial_commands(bool output_allowed = true)") :
    ]
    collection = service[service.index("uint8_t byte_budget = 32u;") :]
    assert collection.index("otis_serial_frame_collect(") < collection.index(
        "otis_serial_frame_validate("
    )
    assert collection.index("otis_serial_frame_validate(") < collection.index(
        "otis_serial_command_parse("
    )
    assert collection.index("otis_serial_command_parse(") < collection.index(
        "execute_serial_command("
    )
    assert '"unknown", "rejected_unknown"' in source


def test_exact_limit_line_is_accepted(framing_harness: Path) -> None:
    payload = (b" " * 187) + b"HELP\n"
    assert len(payload) - 1 == 191
    assert _events(framing_harness, payload) == ["EXEC_HELP"]


def test_one_byte_overflow_discards_prefix_and_suffix(framing_harness: Path) -> None:
    payload = (b" " * 188) + b"HELP DAC SET 0x8000\n"
    assert _events(framing_harness, payload) == ["DIAG_REJECTED_TOO_LONG"]


@pytest.mark.parametrize("suffix", [b"DAC SET 0x8000", b"ACTIVE ABORT"])
def test_very_long_line_never_executes_command_suffix(
    framing_harness: Path, suffix: bytes
) -> None:
    payload = (b"X" * 10_000) + suffix + b"\n"
    assert _events(framing_harness, payload) == ["DIAG_REJECTED_TOO_LONG"]


def test_cr_lf_and_crlf_are_supported_delimiters(framing_harness: Path) -> None:
    assert _events(framing_harness, b"HELP\rHELP\nHELP\r\n") == [
        "EXEC_HELP",
        "EXEC_HELP",
        "EXEC_HELP",
    ]


def test_dual_core_fixture_commands_have_closed_firmware_vocabulary(
    framing_harness: Path,
) -> None:
    assert _events(
        framing_harness,
        b"DUALCORE?\nDUALCORE INVALIDATE_GNSS\nDUALCORE RECOVER\n"
        b"DUALCORE ARBITRARY\n",
    ) == [
        "EXEC_OTHER",
        "DIAG_REJECTED_UNKNOWN",
        "DIAG_REJECTED_UNKNOWN",
        "DIAG_REJECTED_UNKNOWN",
    ]


def test_commas_and_quotes_are_not_echoed_in_diagnostic(
    framing_harness: Path,
) -> None:
    payload = b'unknown,value\"with quote\n'
    assert _events(framing_harness, payload) == ["DIAG_REJECTED_UNKNOWN"]


def test_repeated_overflow_emits_one_diagnostic_per_physical_line(
    framing_harness: Path,
) -> None:
    payload = (b"A" * 200) + b"\n" + (b"B" * 200) + b"\r\n"
    assert _events(framing_harness, payload) == [
        "DIAG_REJECTED_TOO_LONG",
        "DIAG_REJECTED_TOO_LONG",
    ]


def test_valid_command_recovers_after_rejected_line(framing_harness: Path) -> None:
    payload = (b"A" * 200) + b"\r\nHELP\n"
    assert _events(framing_harness, payload) == [
        "DIAG_REJECTED_TOO_LONG",
        "EXEC_HELP",
    ]


def test_no_command_executes_from_any_part_of_rejected_line(
    framing_harness: Path,
) -> None:
    payload = b"DAC SET 0x8000 " + (b"P" * 200) + b" ACTIVE ABORT\n"
    assert _events(framing_harness, payload) == ["DIAG_REJECTED_TOO_LONG"]


def test_invalid_control_byte_is_rejected_before_parsing(
    framing_harness: Path,
) -> None:
    assert _events(framing_harness, b"HELP\x00ACTIVE ABORT\n") == [
        "DIAG_REJECTED_INVALID_CHARACTER"
    ]


@pytest.fixture()
def csv_emission_harness(tmp_path: Path) -> Path:
    binary = tmp_path / "csv_emission"
    subprocess.run(
        [
            _compiler(),
            "-std=c++17",
            f"-I{FIRMWARE}",
            str(Path("tests/cpp/csv_emission_harness.cpp")),
            str(FIRMWARE / "otis_emit.cpp"),
            "-o",
            str(binary),
        ],
        check=True,
    )
    return binary


def test_textual_csv_fields_are_percent_encoded_and_single_line(
    csv_emission_harness: Path,
) -> None:
    emitted = subprocess.check_output([str(csv_emission_harness)])
    assert emitted.count(b"\r\n") == 1
    text = emitted.decode("ascii")
    row = next(csv.reader(io.StringIO(text)))
    assert row == [
        "STS",
        "1",
        "7",
        "9",
        "domain",
        "command",
        "unknown",
        "bad%2C%22line%0D%0A%25tail",
        "WARN",
        "0",
    ]
    assert validate_record_wire_values("health_v1", row) == ()


def test_production_raw_emitters_cross_the_host_at_storage_boundaries(
    csv_emission_harness: Path,
) -> None:
    emitted = subprocess.check_output([str(csv_emission_harness), "boundaries"])
    assert emitted.decode("ascii").count("\r\n") == 13
    rows = list(csv.reader(io.StringIO(emitted.decode("ascii"))))
    assert len(rows) == 13
    contracts = [RECORD_TYPE_TO_CONTRACT[row[0]] for row in rows]
    assert contracts.count("raw_events_v1") == 2
    assert contracts.count("count_observations_v1") == 2
    assert contracts.count("health_v1") == 1
    assert contracts.count("dac_steps_v1") == 2
    assert contracts.count("environment_v1") == 2
    assert contracts.count("pps_snapshots_v2") == 2
    assert contracts.count("forwarded_monitor_snapshots_v1") == 2
    assert all(
        validate_record_wire_values(contract, row) == ()
        for contract, row in zip(contracts, rows, strict=True)
    )
