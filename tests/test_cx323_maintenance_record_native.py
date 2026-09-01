from __future__ import annotations

import csv
import io
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from host.otis_tools.contracts import (
    ACTIVE_HYBRID_MAINTENANCE_V1_FIELDS,
    CsvValidationContext,
    validate_csv,
)


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"
HARNESS = ROOT / "tests/cpp/cx323_maintenance_record_harness.cpp"
BUILDER = FIRMWARE / "otis_cx323_maintenance_record.cpp"
FORMATTER = FIRMWARE / "otis_cx323_maintenance_format.cpp"
CONTROLLER = FIRMWARE / "otis_cx323_phase_priority_maintenance.cpp"
WIDE = FIRMWARE / "otis_cx323_wide.cpp"


def _host_compiler() -> str:
    compiler = shutil.which("c++") or shutil.which("g++") or shutil.which("clang++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    return compiler


@pytest.fixture(scope="module")
def maintenance_record_harness(tmp_path_factory: pytest.TempPathFactory) -> Path:
    executable = tmp_path_factory.mktemp("cx323_maintenance_record") / "harness"
    subprocess.run(
        [
            _host_compiler(),
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(HARNESS),
            str(BUILDER),
            str(FORMATTER),
            str(CONTROLLER),
            str(WIDE),
            "-I",
            str(FIRMWARE),
            "-o",
            str(executable),
        ],
        cwd=ROOT,
        check=True,
    )
    return executable


def test_native_builder_emits_host_valid_exact_lifecycle(
    maintenance_record_harness: Path, tmp_path: Path
) -> None:
    completed = subprocess.run(
        [str(maintenance_record_harness), "lifecycle"],
        cwd=ROOT,
        check=True,
        capture_output=True,
    )
    assert completed.stdout.endswith(b"\r\n")
    rows = list(csv.reader(io.StringIO(completed.stdout.decode("ascii"))))
    assert rows[0] == ACTIVE_HYBRID_MAINTENANCE_V1_FIELDS
    assert all(len(row) == 61 for row in rows[1:])
    records = [
        dict(zip(ACTIVE_HYBRID_MAINTENANCE_V1_FIELDS, row, strict=True))
        for row in rows[1:]
    ]
    assert [record["event"] for record in records] == [
        "policy_activation",
        "decision",
        "decision",
        "application_first_consumer",
        "response_complete",
        "gnss_metadata_hold_enter",
        "gnss_metadata_requalified",
        "decision",
        "decision",
        "request_rejected_or_expired",
        "fail_static",
    ]
    assert records[0]["maintenance_state_before"] == "POLICY_INACTIVE"
    assert records[1]["frontier_relation"] == "first"
    assert records[2]["frontier_relation"] == "contiguous"
    assert records[2]["transaction_event"] == "request_created"
    assert records[2]["candidate_total_demand_picocodes"] == str(
        int(records[2]["raw_fll_demand_picocodes"])
        + int(records[2]["raw_pll_demand_picocodes"])
        + int(records[2]["committed_fll_debt_before_picocodes"])
        + int(records[2]["committed_pll_debt_before_picocodes"])
    )
    assert records[3]["downstream_epoch_exact"] == "true"
    assert records[3]["actual_applied_code"] == records[3]["requested_code"]
    assert records[3]["maintenance_state_after"] == "RESPONSE_PENDING"
    assert records[4]["response_pending_before"] == "true"
    assert records[4]["response_pending_after"] == "false"

    # Async metadata evidence retains the complete last AHY/AH2 identity while
    # reporting the current confirmed code and no fictitious new demand.
    assert records[5]["hybrid_record_sequence"] == records[2][
        "hybrid_record_sequence"
    ]
    assert records[5]["current_applied_code"] == records[3][
        "actual_applied_code"
    ]
    assert records[5]["requested_delta_codes"] == "0"
    assert records[5]["raw_fll_demand_picocodes"] == "0"
    assert records[6]["metadata_hold_before"] == "true"
    assert records[6]["metadata_hold_after"] == "true"
    assert records[6]["requalification_window_count_after"] == "0"
    assert records[6]["source_last_sequence"] == "1201"
    assert records[6]["requalification_d14_d8_observation_sequence"] == "1501"
    assert all(
        record["requalification_d14_d8_observation_sequence"] == "0"
        for index, record in enumerate(records)
        if index != 6
    )
    assert records[7]["requalification_window_count_before"] == "0"
    assert records[7]["requalification_window_count_after"] == "1"
    assert records[7]["metadata_hold_after"] == "true"
    assert records[8]["requalification_window_count_before"] == "1"
    assert records[8]["requalification_window_count_after"] == "2"
    assert records[8]["metadata_hold_after"] == "false"
    assert records[8]["transaction_event"] == "request_created"
    assert records[9]["transaction_event"] == "request_withdrawn"
    assert records[10]["transaction_event"] == "application_fault"
    assert records[10]["maintenance_state_after"] == "FAIL_STATIC"

    csv_path = tmp_path / "active_hybrid_maintenance_v1.csv"
    csv_path.write_bytes(completed.stdout)
    result = validate_csv(
        csv_path,
        CsvValidationContext(
            "active_hybrid_maintenance_v1",
            frozenset(),
            frozenset({"rp2040_timer0_extended"}),
        ),
    )
    assert result.row_count == 11
    assert result.errors == ()


def test_native_builder_rejects_partial_contradictory_overflow_and_wrong_events(
    maintenance_record_harness: Path,
) -> None:
    completed = subprocess.run(
        [str(maintenance_record_harness), "selftest"],
        cwd=ROOT,
        check=True,
        text=True,
        capture_output=True,
    )
    assert completed.stdout == "selftest_ok\n"


def _arm_compiler() -> Path | None:
    direct = shutil.which("arm-none-eabi-g++")
    if direct is not None:
        return Path(direct)
    matrix = json.loads((ROOT / "firmware/arduino/firmware_matrix.json").read_text())
    toolchain = matrix["toolchain"]
    relative = Path(
        "packages",
        toolchain["packager"],
        "tools",
        toolchain["name"],
        toolchain["version"],
        "bin",
        toolchain["compiler"],
    )
    candidates = (
        Path.home() / "Library/Arduino15" / relative,
        Path.home() / ".arduino15" / relative,
    )
    return next((candidate for candidate in candidates if candidate.is_file()), None)


def test_builder_compiles_for_frozen_cortex_m0plus_toolchain(tmp_path: Path) -> None:
    compiler = _arm_compiler()
    if compiler is None:
        pytest.skip("frozen arm-none-eabi-g++ toolchain is unavailable")
    output = tmp_path / "otis_cx323_maintenance_record.o"
    subprocess.run(
        [
            str(compiler),
            "-std=gnu++17",
            "-mcpu=cortex-m0plus",
            "-mthumb",
            "-fno-exceptions",
            "-fno-rtti",
            "-Wall",
            "-Wextra",
            "-Werror",
            "-I",
            str(FIRMWARE),
            "-c",
            str(BUILDER),
            "-o",
            str(output),
        ],
        cwd=ROOT,
        check=True,
    )
    assert output.stat().st_size > 0
