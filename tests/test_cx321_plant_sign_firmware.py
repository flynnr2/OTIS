from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

from host.otis_tools.capture_serial import CsvRecordSplitter
from host.otis_tools.contracts import CsvValidationContext, validate_csv
from host.otis_tools.cx321_plant_sign_evidence_guard import (
    PLANT_SIGN_QUALIFICATION_V1_FIELDS,
    PlantSignReplayContext,
    replay_plant_sign_evidence,
)


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"


def _compiler() -> str:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    return compiler


def test_cx321_exact_plant_sign_and_natural_handoff(tmp_path: Path) -> None:
    executable = tmp_path / "cx321_plant_sign"
    subprocess.run(
        [
            _compiler(),
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(ROOT / "tests/cpp/cx321_plant_sign_harness.cpp"),
            str(FIRMWARE / "otis_cx321_plant_sign.cpp"),
            str(FIRMWARE / "otis_active_hybrid_policy_engine.cpp"),
            "-I",
            str(FIRMWARE),
            "-o",
            str(executable),
        ],
        check=True,
        cwd=ROOT,
    )
    completed = subprocess.run(
        [str(executable)], check=True, text=True, capture_output=True, cwd=ROOT
    )
    assert completed.stdout.strip() == "cx321_plant_sign_harness_passed"


def test_cx321_uses_exact_integer_response_not_float_classifier() -> None:
    source = (FIRMWARE / "otis_cx321_plant_sign.cpp").read_text(encoding="utf-8")
    assert "post - pre" in source
    assert "magnitude >= 3u && magnitude <= 14u" in source
    assert "classify_response" not in source
    assert "OTIS_CX321_SETTLING_EXCLUSION_TICKS" in source


def test_cx321_identification_rebases_only_natural_transaction_history(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "cx321_transaction_rebase"
    subprocess.run(
        [
            _compiler(),
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(ROOT / "tests/cpp/cx321_transaction_rebase_harness.cpp"),
            str(FIRMWARE / "otis_cx317_active_transaction.cpp"),
            "-I",
            str(FIRMWARE),
            "-o",
            str(executable),
        ],
        check=True,
        cwd=ROOT,
    )
    completed = subprocess.run(
        [str(executable)], check=True, text=True, capture_output=True, cwd=ROOT
    )
    assert completed.stdout.strip() == "cx321_transaction_rebase_harness_passed"


def test_compiled_psq_formatter_capture_and_exact_replay(tmp_path: Path) -> None:
    executable = tmp_path / "cx321_plant_sign_format"
    subprocess.run(
        [
            _compiler(),
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(ROOT / "tests/cpp/cx321_plant_sign_format_harness.cpp"),
            str(FIRMWARE / "otis_cx321_plant_sign_format.cpp"),
            "-I",
            str(FIRMWARE),
            "-o",
            str(executable),
        ],
        check=True,
        cwd=ROOT,
    )
    first = subprocess.run(
        [str(executable)], check=True, text=True, capture_output=True, cwd=ROOT
    ).stdout.splitlines()
    assert first[0].split(",") == list(PLANT_SIGN_QUALIFICATION_V1_FIELDS)
    context = PlantSignReplayContext(
        run_identity="cx321:test",
        build_identity=f"{'1':0>64}:{'2':0>64}",
        profile_identity="cx321_bounded_active_hybrid_plant_sign_v2",
        policy_sha256=f"{'1':0>64}",
        plant_sign_gate_sha256=f"{'2':0>64}",
        identification_estimator_sha256=f"{'3':0>64}",
        identification_estimator_config_sha256=f"{'4':0>64}",
        natural_frequency_estimator_sha256=f"{'5':0>64}",
        capture_session=41,
    )
    attestation = replay_plant_sign_evidence(first[1:6], context)[
        "attestation_sha256"
    ]
    emitted = subprocess.run(
        [str(executable), attestation],
        check=True,
        text=True,
        capture_output=True,
        cwd=ROOT,
    ).stdout.splitlines()
    rows = emitted[1:]
    replay = replay_plant_sign_evidence(rows, context, require_ack_handoff=True)
    assert replay["ack_exact"] and replay["handoff_exact"]

    target = tmp_path / "plant_sign_qualification_v1.csv"
    parser_errors: list[str] = []
    with CsvRecordSplitter(
        {"plant_sign_qualification_v1": target},
        on_parser_error=parser_errors.append,
    ) as splitter:
        assert [splitter.process_line(row) for row in rows] == [
            "plant_sign_qualification_v1"
        ] * 7
    assert parser_errors == []
    validation = validate_csv(
        target,
        CsvValidationContext(
            "plant_sign_qualification_v1",
            frozenset(),
            frozenset({"rp2040_timer0_extended"}),
        ),
    )
    assert validation.ok, validation.errors


def test_stateful_live_timer_extension_across_real_lifecycle(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "cx321_live_extension"
    subprocess.run(
        [
            _compiler(),
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(ROOT / "tests/cpp/cx321_live_extension_harness.cpp"),
            str(FIRMWARE / "otis_timer0_extension.cpp"),
            str(FIRMWARE / "otis_cx321_plant_sign.cpp"),
            str(FIRMWARE / "otis_cx321_plant_sign_format.cpp"),
            str(FIRMWARE / "otis_active_hybrid_policy_engine.cpp"),
            "-I",
            str(FIRMWARE),
            "-o",
            str(executable),
        ],
        check=True,
        cwd=ROOT,
    )
    completed = subprocess.run(
        [str(executable)], check=True, text=True, capture_output=True, cwd=ROOT
    )
    assert completed.stdout.strip() == "cx321_live_extension_harness_passed"
