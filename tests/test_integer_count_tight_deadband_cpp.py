from __future__ import annotations

import csv
import io
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware/arduino/otis_nano_rp2040_connect"
MODULE = FIRMWARE / "otis_integer_count_tight_deadband.cpp"
HEADER = FIRMWARE / "otis_integer_count_tight_deadband.h"
HARNESS = ROOT / "tests/cpp/integer_count_tight_deadband_harness.cpp"


def _compiler() -> str:
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("host C++ compiler is unavailable")
    return compiler


@pytest.fixture(scope="session")
def deadband_harness(tmp_path_factory: pytest.TempPathFactory) -> Path:
    output = tmp_path_factory.mktemp("cx318_stage5_deadband") / "deadband"
    subprocess.run(
        [
            _compiler(),
            "-std=c++17",
            "-Wall",
            "-Wextra",
            "-Werror",
            str(HARNESS),
            str(MODULE),
            "-I",
            str(FIRMWARE),
            "-o",
            str(output),
        ],
        check=True,
        cwd=ROOT,
    )
    return output


def _run(deadband_harness: Path, rows: list[tuple[int, bool, bool, int, int]]):
    completed = subprocess.run(
        [str(deadband_harness)],
        input="\n".join(
            f"{counts} {int(available)} {int(fresh)} {session} {epoch}"
            for counts, available, fresh, session, epoch in rows
        )
        + "\n",
        text=True,
        capture_output=True,
        check=True,
        cwd=ROOT,
    )
    return list(csv.DictReader(io.StringIO(completed.stdout)))


def test_cpp_requalifies_then_requires_two_fresh_tight_estimates(deadband_harness: Path) -> None:
    rows = _run(deadband_harness, [(3, True, True, 1, 1), (-2, True, True, 1, 1), (2, True, True, 1, 1)])

    assert (rows[0]["state_before"], rows[0]["state_after"], rows[0]["reason"]) == (
        "REQUALIFY_OUTSIDE", "OUTSIDE", "three_count_outside_hold"
    )
    assert rows[1]["entry_pending"] == "1"
    assert rows[1]["frequency_controller_eligible"] == "0"
    assert rows[2]["state_after"] == "TIGHT_INSIDE"
    assert rows[2]["reason"] == "tight_entry_confirmed"
    assert rows[2]["policy_id"] == "CX318_STAGE5_TIGHT_HYSTERETIC_COUNTS_V1"
    assert [rows[2][field] for field in ("actionable", "actuation_authorized", "authorization_consumed")] == ["0", "0", "0"]


def test_cpp_three_holds_and_two_loose_estimates_release(deadband_harness: Path) -> None:
    rows = _run(deadband_harness, [(2, True, True, 1, 1), (2, True, True, 1, 1), (-3, True, True, 1, 1), (4, True, True, 1, 1), (-4, True, True, 1, 1)])

    assert rows[2]["reason"] == "three_count_inside_hold"
    assert rows[2]["frequency_controller_eligible"] == "0"
    assert rows[3]["release_pending"] == "1"
    assert rows[3]["frequency_controller_eligible"] == "0"
    assert (rows[4]["state_after"], rows[4]["reason"], rows[4]["release_pending"]) == (
        "OUTSIDE", "loose_release_confirmed", "0"
    )
    assert rows[4]["frequency_controller_eligible"] == "1"


@pytest.mark.parametrize("boundary", [(2, 1), (1, 2)])
def test_cpp_invalidity_boundaries_and_opposite_evidence_clear_pending(deadband_harness: Path, boundary: tuple[int, int]) -> None:
    session, epoch = boundary
    rows = _run(deadband_harness, [(2, True, True, 1, 1), (3, True, True, 1, 1), (2, False, False, 1, 1), (2, True, True, 1, 1), (2, True, True, session, epoch), (2, True, True, session, epoch), (2, True, True, session, epoch)])

    assert rows[1]["entry_pending"] == "0"
    assert (rows[2]["state_after"], rows[2]["reason"], rows[2]["absolute_available"]) == (
        "REQUALIFY_OUTSIDE", "invalid_or_stale_requalify", "0"
    )
    assert rows[3]["entry_pending"] == "1"
    assert (rows[4]["state_after"], rows[4]["reason"], rows[4]["entry_pending"]) == (
        "OUTSIDE", "tight_entry_pending", "1"
    )
    assert rows[5]["state_after"] == "TIGHT_INSIDE"
    assert rows[6]["state_after"] == "TIGHT_INSIDE"


def test_cpp_three_count_outside_is_eligible(deadband_harness: Path) -> None:
    row = _run(deadband_harness, [(3, True, True, 1, 1)])[0]

    assert row["state_after"] == "OUTSIDE"
    assert row["reason"] == "three_count_outside_hold"
    assert row["frequency_controller_eligible"] == "1"


def test_cpp_handles_int64_min_without_absolute_overflow(deadband_harness: Path) -> None:
    row = _run(deadband_harness, [(-9223372036854775808, True, True, 1, 1)])[0]

    assert row["absolute_counts"] == "9223372036854775808"
    assert row["reason"] == "outside_loose_evidence"
