from __future__ import annotations

from pathlib import Path

import pytest

from host.otis_tools.h1_latest_estimate import format_latest_estimate, read_latest_valid_estimate


HEADER = (
    "count_seq,elapsed_s,gate_open_raw_timestamp,gate_close_raw_timestamp,"
    "gate_open_unwrapped_timestamp,gate_close_unwrapped_timestamp,raw_gate_ticks,"
    "counted_edges,legacy_gate_seconds,legacy_frequency_hz,legacy_ppm,"
    "local_pps_gate_seconds,local_pps_frequency_hz,local_pps_ppm,"
    "frequency_difference_hz,frequency_difference_fractional,pps_time_open,"
    "pps_time_close,pps_before_open_timestamp,pps_after_open_timestamp,"
    "pps_before_close_timestamp,pps_after_close_timestamp,pps_support_count,"
    "max_pps_gap_seconds,estimator_mode,estimator_valid,estimator_quality_flags"
)


def _write_estimates(run_dir: Path, rows: list[str]) -> None:
    csv_dir = run_dir / "csv"
    csv_dir.mkdir(parents=True)
    (csv_dir / "h1_count_frequency_estimates.csv").write_text(
        "\n".join([HEADER, *rows, ""]),
        encoding="utf-8",
    )


def test_latest_estimate_uses_last_valid_local_pps_row(tmp_path: Path) -> None:
    _write_estimates(
        tmp_path,
        [
            "1,300,,,,,,3000000000,,,,300,9999999.900,-0.010,,,,,,,,,,,LOCAL_PPS_INTERPOLATED,true,",
            "2,600,,,,,,3000000000,,,,300,10000000.183,0.0183,,,,,,,,,,,LOCAL_PPS_INTERPOLATED,true,",
            "3,900,,,,,,3000000000,,,,,,,,,,,,,,,,UNAVAILABLE,false,missing_pps",
        ],
    )

    estimate = read_latest_valid_estimate(tmp_path)

    assert estimate.count_seq == 2
    assert estimate.local_pps_frequency_hz == 10000000.183
    assert estimate.local_pps_ppm == 0.0183
    assert format_latest_estimate(estimate, 0xA400) == "DAC 0xA400 | 10000000.183 Hz | +0.018 ppm | valid"


def test_latest_estimate_rejects_missing_valid_rows(tmp_path: Path) -> None:
    _write_estimates(
        tmp_path,
        [
            "1,300,,,,,,3000000000,,,,,,,,,,,,,,,,UNAVAILABLE,false,missing_pps",
        ],
    )

    with pytest.raises(ValueError, match="no valid local-PPS estimates"):
        read_latest_valid_estimate(tmp_path)
