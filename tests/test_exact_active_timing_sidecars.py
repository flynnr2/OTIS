from __future__ import annotations

import csv
from pathlib import Path
import shutil
import subprocess

import pytest

from host.otis_tools.capture_serial import CsvRecordSplitter
from host.otis_tools.contracts import (
    ACTIVE_HYBRID_DECISION_V2_FIELDS,
    ACTIVE_TRANSACTION_V2_FIELDS,
    CsvValidationContext,
    validate_csv,
)
from host.otis_tools.run_paths import (
    cx323_active_timing_csv_files,
    exact_active_timing_csv_files,
)


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"
EXACT_DOMAIN = "rp2040_timer0_extended"


@pytest.fixture(scope="session")
def sidecar_format_harness(tmp_path_factory: pytest.TempPathFactory) -> Path:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    executable = tmp_path_factory.mktemp("active_timing_sidecar") / "format"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(ROOT / "tests/cpp/active_timing_sidecar_format_harness.cpp"),
            str(FIRMWARE / "otis_active_timing_sidecar.cpp"),
            "-I",
            str(FIRMWARE),
            "-o",
            str(executable),
        ],
        check=True,
        cwd=ROOT,
    )
    return executable


@pytest.mark.parametrize(
    ("selector", "contract", "fields"),
    (
        ("at2", "active_transactions_v2", ACTIVE_TRANSACTION_V2_FIELDS),
        ("ah2", "active_hybrid_decisions_v2", ACTIVE_HYBRID_DECISION_V2_FIELDS),
    ),
)
def test_native_sidecar_formatter_matches_and_validates_host_contract(
    sidecar_format_harness: Path,
    tmp_path: Path,
    selector: str,
    contract: str,
    fields: list[str],
) -> None:
    completed = subprocess.run(
        [str(sidecar_format_harness), selector],
        check=True,
        text=True,
        capture_output=True,
        cwd=ROOT,
    )
    path = tmp_path / f"{contract}.csv"
    path.write_text(completed.stdout, encoding="utf-8")
    assert completed.stdout.splitlines()[0].split(",") == fields
    result = validate_csv(
        path,
        CsvValidationContext(
            contract, frozenset(), frozenset({EXACT_DOMAIN})
        ),
    )
    assert result.ok, result.errors


def test_splitter_keeps_v2_sidecars_separate_from_historical_v1(
    sidecar_format_harness: Path, tmp_path: Path
) -> None:
    targets = {
        "active_transactions_v2": tmp_path / "active_transactions_v2.csv",
        "active_hybrid_decisions_v2": tmp_path / "active_hybrid_decisions_v2.csv",
    }
    with CsvRecordSplitter(targets) as splitter:
        for selector, expected in (
            ("at2", "active_transactions_v2"),
            ("ah2", "active_hybrid_decisions_v2"),
        ):
            output = subprocess.run(
                [str(sidecar_format_harness), selector],
                check=True,
                text=True,
                capture_output=True,
                cwd=ROOT,
            ).stdout.splitlines()
            assert splitter.process_line(output[1]) == expected

    assert targets["active_transactions_v2"].read_text().splitlines()[1].startswith(
        "AT2,2,"
    )
    assert targets["active_hybrid_decisions_v2"].read_text().splitlines()[1].startswith(
        "AH2,2,"
    )


def test_exact_sidecar_contract_rejects_coarse_or_unknown_time_domain(
    sidecar_format_harness: Path, tmp_path: Path
) -> None:
    output = subprocess.run(
        [str(sidecar_format_harness), "at2"],
        check=True,
        text=True,
        capture_output=True,
        cwd=ROOT,
    ).stdout
    path = tmp_path / "active_transactions_v2.csv"
    path.write_text(output.replace(EXACT_DOMAIN, "rp2040_timer0"), encoding="utf-8")
    result = validate_csv(
        path,
        CsvValidationContext(
            "active_transactions_v2",
            frozenset(),
            frozenset({"rp2040_timer0", EXACT_DOMAIN}),
        ),
    )
    assert not result.ok
    assert "requires rp2040_timer0_extended" in " ".join(result.errors)


def test_long_run_inventory_adds_v2_without_mutating_v1_paths() -> None:
    inventory = {entry["contract"]: entry for entry in exact_active_timing_csv_files()}
    assert inventory["active_transactions_v1"]["path"] == (
        "csv/active_transactions_v1.csv"
    )
    assert inventory["active_hybrid_decisions_v1"]["path"] == (
        "csv/active_hybrid_decisions_v1.csv"
    )
    assert inventory["active_transactions_v2"]["path"] == (
        "csv/active_transactions_v2.csv"
    )
    assert inventory["active_hybrid_decisions_v2"]["path"] == (
        "csv/active_hybrid_decisions_v2.csv"
    )


def test_cx323_inventory_adds_required_maintenance_evidence_only() -> None:
    campaign18 = {
        entry["contract"] for entry in exact_active_timing_csv_files()
    }
    cx323 = {
        entry["contract"]: entry for entry in cx323_active_timing_csv_files()
    }

    assert "active_hybrid_maintenance_v1" not in campaign18
    assert cx323["active_hybrid_maintenance_v1"] == {
        "path": "csv/active_hybrid_maintenance_v1.csv",
        "contract": "active_hybrid_maintenance_v1",
    }


def test_firmware_sidecars_are_gated_and_cover_exact_lifecycle_boundaries() -> None:
    config = (FIRMWARE / "otis_config.h").read_text(encoding="utf-8")
    live = (FIRMWARE / "otis_cx317_active_live.cpp").read_text(encoding="utf-8")
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )

    assert "OTIS_ENABLE_EXACT_LONG_RUN_TIMING_SIDECARS" in config
    assert "OTIS_CX317_ACTIVE_CAMPAIGN_D9_D6_FREQUENCY_ONLY_ENDURANCE" in config
    assert "OTIS_CX317_ACTIVE_CAMPAIGN_D9_D6_72H_SUSTAINED_HYBRID" in config
    for event in (
        '"manual_start"',
        '"request_created"',
        '"request_withdrawn"',
        '"core0_accepted"',
        '"application"',
        '"response"',
    ):
        assert event in live
    assert "queue_hybrid_timing_sidecar" in live
    assert "core0_acceptance_timestamp_projection_failed" in live
    assert "otis_cx317_active_live_note_manual_start_timing" in sketch
    assert "otis_cx317_active_live_update_health_at_ticks" in sketch
