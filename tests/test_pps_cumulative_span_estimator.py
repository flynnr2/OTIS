from __future__ import annotations

from dataclasses import replace
from hashlib import sha256
from pathlib import Path
import csv
import json

import pytest

from host.otis_tools.pps_cumulative_span_estimator import (
    DEFAULT_CONFIG,
    METHOD_ID,
    IntervalEvidence,
    analyze_run,
    estimate_spans,
    load_config,
    load_run_inputs,
)


UINT32_MASK = (1 << 32) - 1


def _config(*, spans: tuple[int, ...] = (1, 5), modes: tuple[str, ...] = ("non_overlapping", "overlapping")):
    return replace(load_config(DEFAULT_CONFIG), candidate_spans_s=spans, output_modes=modes)


def _interval(
    closing: int,
    *,
    counted: int = 10_000_000,
    valid: bool = True,
    reasons: tuple[str, ...] = (),
    session: str = "1",
    control_epoch: str = "static",
    settling_excluded: bool = False,
    timer_ticks: int = 16_000_000,
) -> IntervalEvidence:
    return IntervalEvidence(
        session_id=session,
        opening_snapshot_sequence=closing - 1,
        closing_snapshot_sequence=closing,
        interval_counted_edges=counted,
        opening_reference_event_sequence=1000 + closing - 1,
        closing_reference_event_sequence=1000 + closing,
        opening_reference_timestamp_ticks=(closing - 1) * timer_ticks,
        closing_reference_timestamp_ticks=closing * timer_ticks,
        cnt_sequence=closing,
        valid=valid,
        reasons=reasons,
        control_epoch=control_epoch,
        settling_excluded=settling_excluded,
    )


def _write_run(
    root: Path,
    counts: list[int],
    *,
    start_counter: int = 3_000_000_000,
    sessions: list[int] | None = None,
    snapshot_sequences: list[int] | None = None,
    snapshot_status: dict[int, int] | None = None,
    health_key: str = "mode",
    health_value: str = "TEST",
    raw_marker: dict | None = None,
) -> Path:
    run_dir = root / "run"
    csv_dir = run_dir / "csv"
    csv_dir.mkdir(parents=True)
    sessions = sessions or [1] * (len(counts) + 1)
    snapshot_sequences = snapshot_sequences or list(range(len(counts) + 1))
    snapshot_status = snapshot_status or {}

    manifest = {
        "schema_version": 1,
        "run_id": "span_fixture",
        "template": False,
        "stage": "PHASE5_PPS_BACKEND_QUALIFICATION",
        "h_phase": "H1",
        "capture_mode": "pio_wait_cumulative_snapshot_with_independent_gpio_ref",
        "board": "arduino_nano_rp2040_connect",
        "domains": [
            {"name": "rp2040_timer0", "nominal_hz": 16_000_000},
            {"name": "h0_tcxo_16mhz", "nominal_hz": 10_000_000},
        ],
        "channels": [
            {"channel_id": 1, "role": "reference", "record_family": "raw_events_v1"},
            {"channel_id": 2, "role": "count", "record_family": "count_observations_v1"},
        ],
        "files": [
            {"path": "csv/ref.csv", "contract": "raw_events_v1"},
            {"path": "csv/cnt.csv", "contract": "count_observations_v1"},
            {"path": "csv/snp.csv", "contract": "pps_snapshots_v1"},
            {"path": "csv/sts.csv", "contract": "health_v1"},
        ],
    }
    (run_dir / "run_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )

    reference_rows = []
    snapshot_rows = []
    count_rows = []
    counter = start_counter
    for index in range(len(counts) + 1):
        sequence = snapshot_sequences[index]
        timestamp = index * 16_000_000
        reference_rows.append(
            ["REF", 1, 1000 + index, 1, "R", timestamp, "rp2040_timer0", 16]
        )
        snapshot_rows.append(
            [
                "SNP",
                1,
                sessions[index],
                sequence,
                counter,
                sequence,
                timestamp,
                snapshot_status.get(index, 0),
                "pio_wait_cumulative_snapshot_dma_v1",
            ]
        )
        if index < len(counts):
            next_counter = (counter - counts[index]) & UINT32_MASK
            closing_sequence = snapshot_sequences[index + 1]
            count_rows.append(
                [
                    "CNT",
                    1,
                    closing_sequence,
                    2,
                    timestamp,
                    timestamp + 16_000_000,
                    "rp2040_timer0",
                    counts[index],
                    "R",
                    "h0_tcxo_16mhz",
                    16,
                ]
            )
            counter = next_counter

    def write_csv(name: str, header: list[str], rows: list[list[object]]) -> None:
        with (csv_dir / name).open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(header)
            writer.writerows(rows)

    write_csv(
        "ref.csv",
        [
            "record_type",
            "schema_version",
            "event_seq",
            "channel_id",
            "edge",
            "timestamp_ticks",
            "capture_domain",
            "flags",
        ],
        reference_rows,
    )
    write_csv(
        "snp.csv",
        [
            "record_type",
            "schema_version",
            "session",
            "snapshot_sequence",
            "cumulative_down_counter",
            "reference_sequence",
            "reference_timestamp_ticks",
            "status",
            "backend",
        ],
        snapshot_rows,
    )
    write_csv(
        "cnt.csv",
        [
            "record_type",
            "schema_version",
            "count_seq",
            "channel_id",
            "gate_open_ticks",
            "gate_close_ticks",
            "gate_domain",
            "counted_edges",
            "source_edge",
            "source_domain",
            "flags",
        ],
        count_rows,
    )
    write_csv(
        "sts.csv",
        [
            "record_type",
            "schema_version",
            "status_seq",
            "timestamp_ticks",
            "status_domain",
            "component",
            "status_key",
            "status_value",
            "severity",
            "flags",
        ],
        [["STS", 1, 1, 1, "rp2040_timer0", "system", health_key, health_value, "INFO", 0]],
    )
    if raw_marker is not None:
        raw_dir = run_dir / "raw"
        raw_dir.mkdir()
        (raw_dir / "serial.log").write_text(
            "# OTIS_HOST " + json.dumps(raw_marker) + "\n", encoding="utf-8"
        )
    return run_dir


def _file_hashes(run_dir: Path) -> dict[str, str]:
    return {
        str(path.relative_to(run_dir)): sha256(path.read_bytes()).hexdigest()
        for path in sorted(run_dir.rglob("*"))
        if path.is_file() and "derived" not in path.parts
    }


def test_default_contract_is_versioned_and_supports_required_spans() -> None:
    config = load_config(DEFAULT_CONFIG)
    assert config.method_id == METHOD_ID
    assert config.accumulator_width_bits >= 64
    assert config.candidate_spans_s == (1, 5, 10, 30, 60, 120, 300, 600)
    assert config.output_modes == ("non_overlapping", "overlapping")


def test_exact_integer_and_fractional_hz_results() -> None:
    intervals = [_interval(index + 1) for index in range(5)]
    intervals[-1] = replace(intervals[-1], interval_counted_edges=9_999_999)
    estimates = estimate_spans(intervals, _config())
    five_second = [item for item in estimates if item.span_seconds == 5]
    assert {item.authoritative_frequency_hz for item in five_second} == {9_999_999.8}
    assert {item.total_contiguous_counted_edges for item in five_second} == {49_999_999}
    assert {item.count_increment_hz for item in five_second} == {0.2}


@pytest.mark.parametrize(
    ("counts", "minimum_wraps"),
    [
        ([10_000_000] * 10, 0),
        ([10_000_000] * 600, 1),
        ([133_000_000] * 100, 3),
    ],
)
def test_raw_reconstruction_handles_zero_one_and_multiple_wraps(
    tmp_path: Path, counts: list[int], minimum_wraps: int
) -> None:
    run_dir = _write_run(tmp_path, counts)
    config = _config(spans=(len(counts),), modes=("non_overlapping",))
    inputs = load_run_inputs(run_dir, config)
    estimates = estimate_spans(inputs.intervals, config)
    assert inputs.valid_adjacent_interval_count == len(counts)
    assert inputs.invalid_interval_count == 0
    assert len(estimates) == 1
    assert estimates[0].total_contiguous_counted_edges == sum(counts)
    assert estimates[0].total_contiguous_counted_edges > minimum_wraps * (1 << 32)


def test_each_adjacent_delta_is_accumulated_once() -> None:
    counts = [10_000_001, 9_999_999, 10_000_002, 9_999_998, 10_000_003]
    estimates = estimate_spans(
        [_interval(index + 1, counted=value) for index, value in enumerate(counts)],
        _config(spans=(5,), modes=("non_overlapping",)),
    )
    assert estimates[0].total_contiguous_counted_edges == sum(counts)
    assert estimates[0].first_snapshot_sequence == 0
    assert estimates[0].last_snapshot_sequence == 5


def test_startup_partial_span_waits_for_complete_support() -> None:
    config = _config(spans=(5,), modes=("non_overlapping",))
    assert estimate_spans([_interval(index + 1) for index in range(4)], config) == ()
    estimates = estimate_spans(
        [_interval(index + 1) for index in range(5)], config
    )
    assert len(estimates) == 1
    assert estimates[0].first_snapshot_sequence == 0
    assert estimates[0].last_snapshot_sequence == 5


def test_fault_requires_two_fresh_snapshot_endpoints_before_recovery() -> None:
    intervals = [
        _interval(1),
        _interval(2, valid=False, reasons=("dma_fault",)),
        _interval(3),
    ]
    estimates = estimate_spans(
        intervals, _config(spans=(1,), modes=("non_overlapping",))
    )
    assert [item.last_snapshot_sequence for item in estimates] == [1, 3]


def test_overlapping_outputs_are_not_independent_decisions() -> None:
    estimates = estimate_spans(
        [_interval(index + 1) for index in range(6)],
        _config(spans=(5,)),
    )
    nonoverlap = [item for item in estimates if item.mode == "non_overlapping"]
    overlap = [item for item in estimates if item.mode == "overlapping"]
    assert len(nonoverlap) == 1
    assert len(overlap) == 2
    assert all(item.independent_control_decision for item in nonoverlap)
    assert not any(item.independent_control_decision for item in overlap)


@pytest.mark.parametrize(
    "reason",
    [
        "reference_missing",
        "reference_duplicate",
        "reference_malformed",
        "snapshot_status_nonzero",
        "association_loss",
        "snapshot_sequence_gap_or_out_of_order",
        "fifo_fault",
        "dma_fault",
        "snapshot_overwrite",
        "oscillator_fault",
        "count_zero",
        "parser_transport_loss",
        "reset",
    ],
)
def test_every_fault_splits_spans_and_recovers_from_fresh_support(reason: str) -> None:
    intervals = [
        _interval(1),
        _interval(2, valid=False, reasons=(reason,)),
        _interval(3),
        _interval(4),
    ]
    estimates = estimate_spans(
        intervals, _config(spans=(1, 2), modes=("non_overlapping",))
    )
    assert [item.last_snapshot_sequence for item in estimates if item.span_seconds == 1] == [1, 3, 4]
    assert [item.last_snapshot_sequence for item in estimates if item.span_seconds == 2] == [4]


def test_session_and_dac_boundaries_are_never_bridged() -> None:
    intervals = [
        _interval(1, session="1", control_epoch="dac_a"),
        _interval(2, session="1", control_epoch="dac_a"),
        _interval(3, session="1", control_epoch="dac_b"),
        _interval(4, session="1", control_epoch="dac_b", settling_excluded=True),
        _interval(5, session="2", control_epoch="dac_b"),
    ]
    estimates = estimate_spans(
        intervals, _config(spans=(2,), modes=("overlapping",))
    )
    assert len(estimates) == 1
    assert estimates[0].first_snapshot_sequence == 0
    assert estimates[0].last_snapshot_sequence == 2


def test_authoritative_nominal_denominator_differs_from_timer_diagnostic() -> None:
    interval = _interval(1, counted=10_000_000, timer_ticks=15_999_920)
    estimate = estimate_spans(
        [interval], _config(spans=(1,), modes=("non_overlapping",))
    )[0]
    assert estimate.authoritative_frequency_hz == 10_000_000.0
    assert estimate.diagnostic_timer_normalized_frequency_hz != 10_000_000.0
    assert estimate.uncertainty_status == "unavailable"


def test_loader_fails_closed_on_snapshot_gap(tmp_path: Path) -> None:
    run_dir = _write_run(
        tmp_path,
        [10_000_000, 10_000_000],
        snapshot_sequences=[0, 2, 3],
    )
    inputs = load_run_inputs(run_dir, _config(spans=(1,)))
    assert inputs.invalid_interval_count == 1
    assert any(
        "snapshot_sequence_gap_or_out_of_order" in item.reasons
        for item in inputs.intervals
    )


def test_loader_fails_closed_on_missing_cnt(tmp_path: Path) -> None:
    run_dir = _write_run(tmp_path, [10_000_000, 10_000_000])
    path = run_dir / "csv" / "cnt.csv"
    rows = list(csv.reader(path.open(newline="", encoding="utf-8")))
    with path.open("w", newline="", encoding="utf-8") as handle:
        csv.writer(handle).writerows(rows[:-1])
    inputs = load_run_inputs(run_dir, _config(spans=(1,)))
    assert inputs.invalid_interval_count == 1
    assert "cnt_missing" in inputs.intervals[-1].reasons


def test_loader_fails_closed_on_zero_oscillator_count(tmp_path: Path) -> None:
    run_dir = _write_run(tmp_path, [0])
    inputs = load_run_inputs(run_dir, _config(spans=(1,)))
    assert inputs.invalid_interval_count == 1
    assert "count_zero" in inputs.intervals[0].reasons


def test_loader_fails_closed_on_invalid_snapshot_status(tmp_path: Path) -> None:
    run_dir = _write_run(
        tmp_path,
        [10_000_000],
        snapshot_status={1: 1},
    )
    inputs = load_run_inputs(run_dir, _config(spans=(1,)))
    assert inputs.invalid_interval_count == 1
    assert "snapshot_status_nonzero" in inputs.intervals[0].reasons


@pytest.mark.parametrize(
    ("health_key", "health_value", "expected_reason"),
    [
        ("snapshot_dma_error_count", "1", "health_snapshot_dma_error_count_nonzero"),
        ("snapshot_dma_stopped_count", "1", "health_snapshot_dma_stopped_count_nonzero"),
        ("snapshot_pio_rxstall_count", "1", "health_snapshot_pio_rxstall_count_nonzero"),
        ("snapshot_overwrite_count", "1", "health_snapshot_overwrite_count_nonzero"),
        ("boundary_ring_dropped_count", "1", "health_boundary_ring_dropped_count_nonzero"),
        ("association_loss_count", "2", "health_association_loss_count_nonzero"),
        ("actuation_authorized", "true", "unsafe_actuation_authorized_true"),
        ("agreement_state", "MISMATCH", "d14_d10_disagreement"),
    ],
)
def test_loader_fails_closed_on_run_health_fault(
    tmp_path: Path, health_key: str, health_value: str, expected_reason: str
) -> None:
    run_dir = _write_run(
        tmp_path,
        [10_000_000],
        health_key=health_key,
        health_value=health_value,
    )
    inputs = load_run_inputs(run_dir, _config(spans=(1,)))
    assert expected_reason in inputs.global_reason_codes
    assert inputs.invalid_interval_count == 1


def test_loader_fails_closed_on_transport_fault(tmp_path: Path) -> None:
    run_dir = _write_run(
        tmp_path,
        [10_000_000],
        raw_marker={
            "event": "capture_stopped",
            "parser_errors": 1,
            "reconnect_count": 0,
            "malformed_utf8": 0,
            "commands_rejected": 0,
        },
    )
    inputs = load_run_inputs(run_dir, _config(spans=(1,)))
    assert "transport_parser_errors_nonzero" in inputs.global_reason_codes
    assert inputs.invalid_interval_count == 1


def test_analysis_is_deterministic_and_preserves_source_evidence(tmp_path: Path) -> None:
    run_dir = _write_run(tmp_path, [10_000_000] * 10)
    before = _file_hashes(run_dir)
    first = analyze_run(run_dir, output_path=run_dir / "derived" / "first.json")
    second = analyze_run(run_dir, output_path=run_dir / "derived" / "second.json")
    assert first.read_bytes() == second.read_bytes()
    assert _file_hashes(run_dir) == before
    report = json.loads(first.read_text(encoding="utf-8"))
    assert report["source_immutability_verified"] is True
    assert report["authoritative_denominator"].startswith("nominal accepted PPS")
