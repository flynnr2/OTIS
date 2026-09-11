from __future__ import annotations

import csv
import io
from pathlib import Path
import shutil
import subprocess

import pytest

from host.otis_tools.contracts import (
    ACTIVE_HYBRID_MAINTENANCE_V2_FIELDS,
    CsvValidationContext,
    validate_csv,
)
from host.otis_tools.firmware_host_contract import validate_record_wire_values


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"
SIGNED_128_MAX_TEXT = "170141183460469231731687303715884105727"


@pytest.fixture(scope="module")
def maintenance_formatter(tmp_path_factory: pytest.TempPathFactory) -> Path:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    executable = tmp_path_factory.mktemp("adaptive_hybrid_maintenance_format") / "harness"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(ROOT / "tests/cpp/adaptive_hybrid_maintenance_format_harness.cpp"),
            str(FIRMWARE / "otis_adaptive_hybrid_maintenance_format.cpp"),
            str(FIRMWARE / "otis_adaptive_hybrid_wide.cpp"),
            "-I",
            str(FIRMWARE),
            "-o",
            str(executable),
        ],
        check=True,
        cwd=ROOT,
    )
    return executable


def test_native_formatter_emits_exact_header_and_host_valid_lifecycle(
    maintenance_formatter: Path, tmp_path: Path
) -> None:
    completed = subprocess.run(
        [str(maintenance_formatter), "lifecycle"],
        check=True,
        capture_output=True,
    )
    assert completed.stdout.endswith(b"\r\n")
    decoded = completed.stdout.decode("ascii")
    rows = list(csv.reader(io.StringIO(decoded)))
    assert rows[0] == ACTIVE_HYBRID_MAINTENANCE_V2_FIELDS
    assert len(rows[0]) == len(ACTIVE_HYBRID_MAINTENANCE_V2_FIELDS) == 60
    assert all(
        len(row) == len(ACTIVE_HYBRID_MAINTENANCE_V2_FIELDS)
        for row in rows[1:]
    )
    assert all(
        validate_record_wire_values("active_hybrid_maintenance_v2", row) == ()
        for row in rows[1:]
    )

    records = [
        dict(zip(ACTIVE_HYBRID_MAINTENANCE_V2_FIELDS, row, strict=True))
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
        "fail_static",
    ]
    assert records[1]["raw_fll_demand_picocodes"] == f"-{SIGNED_128_MAX_TEXT}"
    assert records[1]["raw_pll_demand_picocodes"] == SIGNED_128_MAX_TEXT
    assert {record["phase_valid"] for record in records} == {"true"}
    assert {record["actionable"] for record in records} == {"false"}
    assert records[6]["requalification_accepted_boundary_ordinal"] == "2400"
    assert all(
        record["requalification_accepted_boundary_ordinal"] == "0"
        for index, record in enumerate(records)
        if index != 6
    )

    csv_path = tmp_path / "active_hybrid_maintenance_v2.csv"
    csv_path.write_bytes(completed.stdout)
    result = validate_csv(
        csv_path,
        CsvValidationContext(
            "active_hybrid_maintenance_v2",
            frozenset(),
            frozenset({"rp2040_monotonic_us64"}),
        ),
    )
    assert result.row_count == 10
    assert result.errors == ()


def test_native_formatter_rejects_truncation_nulls_invalid_enums_and_bounds(
    maintenance_formatter: Path,
) -> None:
    completed = subprocess.run(
        [str(maintenance_formatter), "selftest"],
        check=True,
        text=True,
        capture_output=True,
    )
    assert completed.stdout == "selftest_ok\n"
