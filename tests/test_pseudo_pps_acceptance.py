from __future__ import annotations

import json
from pathlib import Path

from host.otis_tools.pseudo_pps_acceptance import (
    CleanIntervalObservation,
    CleanRunAcceptancePolicy,
    main,
    score_clean_run,
)


FIXTURE = Path("tests/fixtures/pseudo_pps/clean_acceptance_v1.json")


def _policy(*, load: bool = False) -> CleanRunAcceptancePolicy:
    return CleanRunAcceptancePolicy(
        centre_source="nominal_with_tolerance",
        centre_evidence=(
            "test fixture nominal expectation with explicit +/-10 Hz bound"
        ),
        expected_oscillator_hz=16_000_000.0,
        maximum_centre_offset_hz=10.0,
        maximum_boundary_residual_edges=1.0,
        maximum_adjacent_difference_edges=2,
        maximum_load_mean_shift_hz=0.25,
        require_load_comparison=load,
        minimum_intervals_per_load_state=3,
    )


def _run(
    counts: list[int], *, load_from: int | None = None
) -> list[CleanIntervalObservation]:
    return [
        CleanIntervalObservation(
            session_id="s1",
            snapshot_sequence=index + 10,
            reference_sequence=index + 40,
            counted_edges=count,
            load_state=(
                "load"
                if load_from is not None and index >= load_from
                else "baseline"
            ),
        )
        for index, count in enumerate(counts)
    ]


def test_stable_clean_run_slightly_above_nominal_can_pass() -> None:
    report = score_clean_run(
        _run([16_000_004, 16_000_005, 16_000_004, 16_000_003]),
        _policy(),
    )

    assert report.accepted
    assert report.centre_offset_hz == 4.0


def test_stable_clean_run_slightly_below_nominal_can_pass() -> None:
    report = score_clean_run(
        _run([15_999_996, 15_999_995, 15_999_996, 15_999_997]),
        _policy(),
    )

    assert report.accepted
    assert report.centre_offset_hz == -4.0


def test_allowed_centre_offset_does_not_conceal_excess_jitter() -> None:
    report = score_clean_run(
        _run([15_999_999, 16_000_009, 15_999_999, 16_000_009]),
        _policy(),
    )

    assert not report.accepted
    assert report.checks["oscillator_frequency_offset"]
    assert not report.checks["boundary_quantisation"]


def test_allowed_centre_offset_does_not_conceal_load_shift() -> None:
    report = score_clean_run(
        _run(
            [16_000_003, 16_000_004, 16_000_003,
             16_000_004, 16_000_005, 16_000_004],
            load_from=3,
        ),
        _policy(load=True),
    )

    assert not report.accepted
    assert report.checks["oscillator_frequency_offset"]
    assert not report.checks["service_plane_load_invariance"]


def test_isolated_count_error_beyond_boundary_proof_fails() -> None:
    report = score_clean_run(
        _run([16_000_004, 16_000_004, 16_000_008, 16_000_004]),
        _policy(),
    )

    assert not report.accepted
    assert not report.checks["boundary_quantisation"]


def test_missing_or_duplicate_snapshot_fails_independently_of_mean() -> None:
    missing = _run([16_000_004] * 4)
    missing[2] = CleanIntervalObservation(
        "s1", 13, 42, 16_000_004
    )
    duplicate = _run([16_000_004] * 4)
    duplicate[2] = CleanIntervalObservation(
        "s1", 11, 42, 16_000_004
    )

    missing_report = score_clean_run(missing, _policy())
    duplicate_report = score_clean_run(duplicate, _policy())

    assert missing_report.checks["oscillator_frequency_offset"]
    assert duplicate_report.checks["oscillator_frequency_offset"]
    assert not missing_report.checks["capture_continuity"]
    assert not duplicate_report.checks["capture_continuity"]


def test_clean_acceptance_cli_writes_a_strict_pass(tmp_path: Path) -> None:
    output = tmp_path / "score.json"

    assert main([str(FIXTURE), "--output", str(output), "--strict"]) == 0
    report = json.loads(output.read_text(encoding="utf-8"))
    assert report["accepted"] is True
    assert report["centre_offset_hz"] == 4.0
