from __future__ import annotations

import csv
import shutil
import subprocess
from pathlib import Path

import pytest

from host.otis_tools.contracts import CsvValidationContext, validate_csv


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


@pytest.fixture(scope="session")
def format_harness(tmp_path_factory: pytest.TempPathFactory) -> Path:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    executable = tmp_path_factory.mktemp("cx318_format") / "format_harness"
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(ROOT / "tests/cpp/cx318_preview_format_harness.cpp"),
            str(FIRMWARE / "otis_cx318_preview_format.cpp"),
            str(FIRMWARE / "otis_decimal_format.cpp"),
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
    ("selector", "contract"),
    [
        ("rph", "relative_phase_observations_v1"),
        ("phe", "phase_estimator_outputs_v1"),
        ("hpr", "hybrid_preview_decisions_v1"),
    ],
)
def test_core0_formatted_stage4_records_validate(
    format_harness: Path,
    tmp_path: Path,
    selector: str,
    contract: str,
) -> None:
    result = subprocess.run(
        [str(format_harness), selector],
        check=True,
        text=True,
        capture_output=True,
        cwd=ROOT,
    )
    path = tmp_path / f"{selector}.csv"
    path.write_text(result.stdout, encoding="utf-8")
    validation = validate_csv(
        path,
        CsvValidationContext(
            contract=contract,
            known_channels=frozenset(),
            known_domains=frozenset({"rp2040_timer0"}),
        ),
    )
    assert validation.ok, validation.errors


def test_phe_retains_only_the_authoritative_nonoverlap_frequency_with_age(
    format_harness: Path,
    tmp_path: Path,
) -> None:
    result = subprocess.run(
        [str(format_harness), "phe_retained"],
        check=True,
        text=True,
        capture_output=True,
        cwd=ROOT,
    )
    path = tmp_path / "phe_retained.csv"
    path.write_text(result.stdout, encoding="utf-8")
    validation = validate_csv(
        path,
        CsvValidationContext(
            contract="phase_estimator_outputs_v1",
            known_channels=frozenset(),
            known_domains=frozenset(),
        ),
    )
    assert validation.ok, validation.errors
    row = next(csv.DictReader(path.open(encoding="utf-8")))
    assert row["estimated_frequency_error_hz"] == "0.001666666666667"
    assert row["estimate_age_s"] == "17.000000000000000"
    assert row["reason_codes"] == "selected_600_interval_frequency_retained"


def test_core1_stage4_producer_has_no_formatter_or_authority_surface() -> None:
    source = (FIRMWARE / "otis_cx318_preview_live.cpp").read_text(
        encoding="utf-8"
    )
    header = (FIRMWARE / "otis_cx318_preview_live.h").read_text(
        encoding="utf-8"
    )
    assert "snprintf" not in source
    assert "otis_transport" not in source
    assert "otis_dac_ad5693r" not in source + header
    assert "otis_cx317_active" not in source + header
    assert "OtisCrossCoreActuator" not in source + header
    assert "authorization" not in source + header
    assert "actionable" not in source + header


def test_stage4_sketch_compiles_out_dac_write_dispatch() -> None:
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    dispatch = sketch[
        sketch.index("} else if (command.kind == OtisSerialCommandKind::DacQuery)") :
        sketch.index("} else if (command.kind == OtisSerialCommandKind::Fc0Query)")
    ]
    guarded = dispatch[
        dispatch.index("#if OTIS_ENABLE_CX318_STAGE4_PREVIEW") :
        dispatch.index("#else", dispatch.index("#if OTIS_ENABLE_CX318_STAGE4_PREVIEW"))
    ]

    for command_kind in ("DacMid", "DacZero", "DacSet"):
        assert f"OtisSerialCommandKind::{command_kind}" in guarded
    assert "rejected_write_surface_compiled_out" in guarded
    assert "handle_dac_set" not in guarded


def test_stage4_transport_finishes_a_record_group_before_other_core0_output() -> None:
    sketch = (FIRMWARE / "otis_nano_rp2040_connect.ino").read_text(
        encoding="utf-8"
    )
    loop = sketch[sketch.index("void loop()") :]
    busy_block = loop[
        loop.index("if (otis_phase4_observe_preview_transport_busy()") :
        loop.index("service_dual_core_outputs();")
    ]

    assert "otis_cx318_preview_transport_busy()" in busy_block
    assert "otis_cx318_preview_transport_service();" in busy_block
    assert "return;" in busy_block


def test_stage4_cross_core_status_is_published_atomically() -> None:
    source = (FIRMWARE / "otis_cx318_preview_live.cpp").read_text(
        encoding="utf-8"
    )

    assert "atomic_store_release(&initialized, false)" in source
    assert "atomic_store_release(&initialized, true)" in source
    assert "atomic_load_acquire(&initialized)" in source
    assert "__atomic_add_fetch(&published_records" in source


def test_core1_live_producer_publishes_pointer_free_numerical_records(
    tmp_path: Path,
) -> None:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    executable = tmp_path / "cx318_live"
    definitions = [
        "OTIS_ENABLE_CX318_STAGE4_PREVIEW=1",
        "OTIS_CX318_STAGE4_STATIC_CODE=0xA950u",
        "OTIS_ENABLE_DUAL_CORE_PARTITION=1",
        "OTIS_SW1_BRINGUP_MODE=OTIS_SW1_MODE_H1_OCXO_OBSERVE",
        "OTIS_CAPTURE_BACKEND=OTIS_CAPTURE_BACKEND_IRQ",
        "OTIS_TCXO_COUNTER_BACKEND=OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO",
        "OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED=1",
        "OTIS_ENABLE_PPS_DUAL_OBSERVER=1",
        "OTIS_ENABLE_GNSS_RECEIVER=1",
        "OTIS_GNSS_UART_TX_ENABLED=0",
        "OTIS_ENABLE_ENV_SENSORS=1",
        "OTIS_ENABLE_DAC_AD5693R=0",
        "OTIS_ENABLE_H1_DAC_SWEEP=0",
    ]
    subprocess.run(
        [
            compiler,
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            *(f"-D{value}" for value in definitions),
            str(ROOT / "tests/cpp/cx318_preview_live_harness.cpp"),
            str(FIRMWARE / "otis_cx318_preview_live.cpp"),
            str(FIRMWARE / "otis_cx318_selected_preview_engine.cpp"),
            str(FIRMWARE / "otis_dual_core_partition.cpp"),
            "-I",
            str(FIRMWARE),
            "-o",
            str(executable),
        ],
        check=True,
        cwd=ROOT,
    )
    subprocess.run([str(executable)], check=True, cwd=ROOT)
