"""Independent raw/evidence delivery ordering at the live authority boundary.

These retained-record tests exercise the real tracker and disk readiness reader.
They do not assert firmware queue capacity or physical PPS qualification.
"""
from __future__ import annotations

import pytest

from host.otis_tools.acquisition_frontier import FRONTIER_PATH
from test_acquisition_frontier import RecordedStream
from test_raw_measurement_replay import accepted_rows, raw_measurement_rows


def _pending(stream, identity="selected-1", session=1):
    result = stream.readiness(identity, session=session)
    assert not result["ready"], result
    assert not result["errors"], result
    assert identity in stream.tracker.pending_estimates
    assert identity not in stream.tracker.qualified_estimate_ids


def _through_penultimate(tmp_path):
    rows = raw_measurement_rows()
    spans = accepted_rows(rows["snapshots.csv"], rows["counts.csv"])
    stream = RecordedStream(tmp_path, rows)
    for index in range(600):
        stream.boundary(index)
    # The evidence queue can deliver APS + EST before the raw queue drains its
    # final REF/SNP/CNT. Within the raw queue those three retain producer order.
    stream.emit(spans[-1])
    stream.emit(rows["estimates.csv"][0])
    _pending(stream)
    return stream, rows, spans


def test_complete_aps_and_est_wait_for_final_raw_snp_then_cnt(tmp_path):
    stream, rows, _ = _through_penultimate(tmp_path)
    anchor = (tmp_path / FRONTIER_PATH).read_bytes()
    stream.emit(rows["ref.csv"][-1])
    _pending(stream)
    stream.emit(rows["snapshots.csv"][-1])
    _pending(stream)
    stream.emit(rows["counts.csv"][-1])
    result = stream.readiness("selected-1")
    assert result["ready"], result
    proof = stream.tracker.qualified_estimates[-1]
    assert len(proof["accepted_span_sources"]) == 600
    assert len(proof["raw_snapshot_sources"]) == 601
    assert len(proof["raw_count_sources"]) == 600
    assert (tmp_path / FRONTIER_PATH).read_bytes() == anchor


@pytest.mark.parametrize("contradiction", ["snp_timestamp", "count_value", "duplicate_aps"])
def test_delayed_source_contradiction_latches_hold(tmp_path, contradiction):
    stream, rows, spans = _through_penultimate(tmp_path)
    if contradiction == "duplicate_aps":
        stream.emit(spans[-1])
    reference = dict(rows["ref.csv"][-1])
    snapshot = dict(rows["snapshots.csv"][-1])
    count = dict(rows["counts.csv"][-1])
    if contradiction == "snp_timestamp":
        reference["timestamp_ticks"] = str(int(reference["timestamp_ticks"]) + 1)
        snapshot["reference_timestamp_ticks"] = reference["timestamp_ticks"]
        count["gate_close_ticks"] = reference["timestamp_ticks"]
    elif contradiction == "count_value":
        count["counted_edges"] = str(int(count["counted_edges"]) + 1)
    stream.emit(reference)
    stream.emit(snapshot)
    stream.emit(count)
    result = stream.readiness("selected-1")
    assert not result["ready"], result
    assert result["errors"], result


def _next_session(stream):
    rows = raw_measurement_rows(first_ticks=601_000_000, first_event_sequence=1601)
    for snapshot in rows["snapshots.csv"]:
        snapshot["session"] = "2"
    spans = accepted_rows(rows["snapshots.csv"], rows["counts.csv"])
    estimate = dict(stream.rows["estimates.csv"][0], estimate_id="selected-2",
                    estimate_seq="2", capture_session="2",
                    estimator_timestamp_ticks=rows["snapshots.csv"][-1]["reference_timestamp_ticks"],
                    source_accepted_spans_ref="live:APS:2:1:0:600")
    rows["estimates.csv"] = [estimate]
    rows["spans.csv"] = []
    return rows, spans, estimate


def test_pending_new_session_evidence_survives_raw_session_transition(tmp_path):
    rows = raw_measurement_rows()
    stream = RecordedStream(tmp_path, rows)
    stream.boundary(0)
    stream.boundary(1)
    anchor = (tmp_path / FRONTIER_PATH).read_bytes()
    later, spans, estimate = _next_session(stream)
    # APS1 can overtake the new session's raw seed. Delivering its future EST
    # here separately stresses pending-session retention; it is not a claim
    # that the firmware buffers an entire 600-second raw horizon.
    stream.emit(spans[0])
    stream.emit(estimate)
    _pending(stream, "selected-2", session=1)
    stream.rows = later
    stream.boundary(0)
    _pending(stream, "selected-2", session=2)
    stream.emit(later["ref.csv"][1])
    stream.emit(later["snapshots.csv"][1])
    stream.emit(later["counts.csv"][0])
    _pending(stream, "selected-2", session=2)
    for index in range(2, 601):
        stream.boundary(index)
    result = stream.readiness("selected-2", session=2)
    assert result["ready"], result
    assert stream.tracker.qualified_estimates[-1]["capture_session"] == 2
    assert (tmp_path / FRONTIER_PATH).read_bytes() == anchor
    assert not stream.readiness("selected-2", session=1)["ready"]


@pytest.mark.parametrize("tag", ["APS", "EST"])
def test_closed_session_evidence_is_contradictory_not_pending(tmp_path, tag):
    rows = raw_measurement_rows()
    stale_span = accepted_rows(rows["snapshots.csv"], rows["counts.csv"])[1]
    stream = RecordedStream(tmp_path, rows)
    stream.boundary(0)
    stream.boundary(1)
    stale_estimate = dict(rows["estimates.csv"][0])
    later, _, _ = _next_session(stream)
    stream.rows = later
    stream.boundary(0)
    stream.boundary(1)
    assert stream.readiness(session=2)["ready"]
    stream.emit(stale_span if tag == "APS" else stale_estimate)
    result = stream.readiness(session=2)
    assert not result["ready"], result
    assert result["errors"], result
