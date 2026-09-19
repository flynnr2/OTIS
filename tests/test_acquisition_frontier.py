from __future__ import annotations

import csv
from copy import deepcopy
import io
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from host.otis_tools.acquisition_frontier import (
    AcquisitionFrontierTracker, FRONTIER_PATH, FRONTIER_POLICY,
    FRONTIER_STATE_PATH, _digest, read_acquisition_readiness,
    select_required_replay_rows,
)
from host.otis_tools.adaptive_hybrid_replay import _measurement_replay
from host.otis_tools.authoritative_inputs import (
    REFERENCE_ACCEPTANCE_POLICY_PATH,
    validate_authoritative_inputs,
    collect_authoritative_inputs,
)
from host.otis_tools.contracts import CONTRACT_FIELDS
from test_raw_measurement_replay import raw_measurement_rows


class RecordedStream:
    def __init__(self, root: Path, rows):
        self.root, self.rows = root, rows
        frozen = validate_authoritative_inputs(collect_authoritative_inputs())
        policy = frozen.document(REFERENCE_ACCEPTANCE_POLICY_PATH)
        binding = frozen.binding(REFERENCE_ACCEPTANCE_POLICY_PATH)
        self.policy_sha = str(binding["sha256"])
        self.first_sequence = int(rows["snapshots.csv"][0]["snapshot_sequence"])
        old = rows["estimates.csv"][0]
        estimate = {field: "" for field in CONTRACT_FIELDS["estimates_v3"]}
        estimate.update(
            record_type="EST", schema_version="3", estimate_seq="1",
            estimate_id="selected-1", estimator_timestamp_ticks=old["estimator_timestamp_ticks"],
            time_domain="rp2040_monotonic_us32", capture_session="1",
            source_acceptance_epoch="1",
            source_opening_accepted_boundary_ordinal="0",
            source_closing_accepted_boundary_ordinal="600",
            source_opening_snapshot_sequence=str(self.first_sequence),
            source_closing_snapshot_sequence=rows["snapshots.csv"][-1]["snapshot_sequence"],
            source_opening_reference_sequence=str(self.first_sequence),
            source_closing_reference_sequence=rows["snapshots.csv"][-1]["reference_sequence"],
            source_accepted_spans_ref="live:APS:1:1:0:600",
            source_status_refs=old["source_status_refs"],
            source_dac_ref=old["source_dac_ref"],
            estimator_version=old["estimator_version"], config_hash=old["config_hash"],
            observation_validity="valid", reference_validity="valid",
            reference_continuity="true", count_validity="valid",
            count_continuity="true", diagnostic_health="healthy",
            frequency_observation_hz=old["frequency_observation_hz"],
            frequency_estimate_hz=old["frequency_estimate_hz"],
            frequency_error_hz=old["frequency_error_hz"], accepted_sample_count="600",
            drift_enabled="false", preview_eligibility="true",
        )
        rows["estimates.csv"] = [estimate]
        rows["spans.csv"] = []
        root.mkdir(exist_ok=True)
        (root / "raw").mkdir()
        self.raw = root / "raw/serial.log"
        self.raw.write_bytes(b"")
        self.manifest = {
            "acquisition_frontier": FRONTIER_POLICY,
            "transaction_identities": {"estimator_sha256": "a" * 64},
            "authoritative_inputs": frozen.as_dict(),
            "reference_acceptance": {
                "policy_id": policy["policy_id"], "policy_sha256": self.policy_sha,
                "path": REFERENCE_ACCEPTANCE_POLICY_PATH,
            },
            "files": [
                {"contract": "raw_events_v1", "record_type": "REF", "path": "ref.csv"},
                {"contract": "raw_events_v1", "record_type": "EVT", "path": "evt.csv"},
                {"contract": "pps_snapshots_v2", "path": "snapshots.csv"},
                {"contract": "count_observations_v1", "path": "counts.csv"},
                {"contract": "accepted_pps_spans_v1", "path": "spans.csv"},
                {"contract": "estimates_v3", "path": "estimates.csv"},
            ],
        }
        self.paths = {"REF": "ref.csv", "SNP": "snapshots.csv", "CNT": "counts.csv", "APS": "spans.csv", "EST": "estimates.csv"}
        self.fields = {}
        for tag, filename in self.paths.items():
            self.fields[tag] = (
                list(CONTRACT_FIELDS["accepted_pps_spans_v1"])
                if tag == "APS"
                else list(rows[filename][0])
            )
            with (root / filename).open("w", newline="") as handle:
                csv.writer(handle, lineterminator="\n").writerow(self.fields[tag])
        (root / "evt.csv").write_text("record_type,channel_id\n")
        self.tracker = AcquisitionFrontierTracker(root, self.manifest)
        self.line = 0

    def emit(self, row):
        self.line += 1
        stream = io.StringIO(newline="")
        csv.writer(stream, lineterminator="\n").writerow([row[name] for name in self.fields[row["record_type"]]])
        encoded = stream.getvalue().encode()
        path = self.root / self.paths[row["record_type"]]
        offset = path.stat().st_size
        with path.open("ab") as handle:
            handle.write(encoded)
        with self.raw.open("ab") as handle:
            handle.write(encoded)
        previous = self.tracker.frontier
        self.tracker.observe(row, line_number=self.line, csv_byte_offset=offset)
        if previous is None and self.tracker.frontier is not None:
            self.tracker.note_marker_search_offset(self.raw.stat().st_size)
            with self.raw.open("ab") as handle:
                handle.write(b"# OTIS_HOST " + json.dumps({
                    "event": "acquisition_frontier_established",
                    "frontier_sha256": self.tracker.frontier["frontier_sha256"],
                    "capture_line_ordinal": self.line,
                }).encode() + b"\n")

    def boundary(self, index):
        self.emit(self.rows["ref.csv"][index])
        self.emit(self.rows["snapshots.csv"][index])
        if index:
            self.emit(self.rows["counts.csv"][index - 1])
            opening = self.rows["snapshots.csv"][index - 1]
            closing = self.rows["snapshots.csv"][index]
            count = self.rows["counts.csv"][index - 1]
            span = {
                field: "" for field in CONTRACT_FIELDS["accepted_pps_spans_v1"]
            }
            span.update(
                record_type="APS", schema_version="1", capture_session=closing["session"],
                acceptance_epoch="1", accepted_boundary_ordinal=str(index),
                opening_snapshot_sequence=opening["snapshot_sequence"],
                closing_snapshot_sequence=closing["snapshot_sequence"],
                opening_reference_sequence=opening["reference_sequence"],
                closing_reference_sequence=closing["reference_sequence"],
                opening_reference_timestamp_ticks=opening["reference_timestamp_ticks"],
                closing_reference_timestamp_ticks=closing["reference_timestamp_ticks"],
                time_domain="rp2040_monotonic_us32",
                source_count_first_sequence=count["count_seq"],
                source_count_last_sequence=count["count_seq"],
                source_count_record_count="1", counted_edges=count["counted_edges"],
                excluded_candidate_count="0", nominal_interval_count="1",
                acceptance_policy_sha256=self.policy_sha,
            )
            self.rows["spans.csv"].append(span)
            self.emit(span)

    def readiness(self, identity=None, session=1):
        return read_acquisition_readiness(self.root, self.manifest,
            source_estimate_id=identity, expected_capture_session=session)

    def replay(self):
        return _measurement_replay(SimpleNamespace(root=self.root, files=self.manifest["files"]), self.manifest)


def test_mid_session_prefix_retained_anchor_then_full_source_authority(tmp_path):
    rows = raw_measurement_rows(first_sequence=10, first_ticks=10_000_000)
    stream = RecordedStream(tmp_path, rows)
    assert stream.readiness()["errors"] == []
    stream.boundary(0)
    assert not stream.readiness()["ready"]
    stream.boundary(1)
    assert stream.readiness()["ready"]
    assert not stream.readiness("selected-1")["ready"]
    artifact = (tmp_path / FRONTIER_PATH).read_bytes()
    for index in range(2, 601):
        stream.boundary(index)
    selected = dict(rows["estimates.csv"][0], estimate_seq="2")
    stream.emit(selected)
    readiness = stream.readiness("selected-1")
    assert readiness["ready"], readiness
    assert (tmp_path / FRONTIER_PATH).read_bytes() == artifact
    assert len(list(csv.DictReader((tmp_path / "counts.csv").open()))) == 600
    exact, report, _ = stream.replay()
    assert exact, report
    assert report["acquisition_frontier"]["unqualified_selected_estimate_ids"] == []


def test_estimate_may_precede_raw_drain_but_cannot_authorize_until_exact_source(tmp_path):
    rows = raw_measurement_rows()
    stream = RecordedStream(tmp_path, rows)
    stream.boundary(0)
    stream.boundary(1)
    stream.emit(rows["estimates.csv"][0])
    assert not stream.readiness("selected-1")["ready"]
    assert not stream.tracker.errors
    for index in range(2, 601):
        stream.boundary(index)
    assert stream.readiness("selected-1")["ready"], stream.tracker.errors


def test_interior_source_gap_latches_hold_without_advancing_frontier(tmp_path):
    rows = raw_measurement_rows([10_000_000] * 4)
    stream = RecordedStream(tmp_path, rows)
    stream.boundary(0)
    stream.boundary(1)
    artifact = (tmp_path / FRONTIER_PATH).read_bytes()
    stream.boundary(3)
    assert not stream.readiness()["ready"]
    assert stream.readiness()["errors"]
    assert (tmp_path / FRONTIER_PATH).read_bytes() == artifact


@pytest.mark.parametrize("mutation", ["errors_absent", "ids_string", "proof_altered", "marker_absent", "source_altered", "raw_source_altered"])
def test_corrupted_frontier_or_live_proof_never_grants_authority(tmp_path, mutation):
    rows = raw_measurement_rows([10_000_000] * 2)
    stream = RecordedStream(tmp_path, rows)
    stream.boundary(0)
    stream.boundary(1)
    stream.emit(rows["estimates.csv"][0])
    path = tmp_path / FRONTIER_STATE_PATH
    state = json.loads(path.read_text())
    if mutation == "errors_absent":
        del state["errors"]
    elif mutation == "ids_string":
        state["qualified_estimate_ids"] = "selected-1"
    elif mutation == "proof_altered":
        state["qualified_estimates"] = [{"estimate_id": "invented"}]
    elif mutation == "marker_absent":
        stream.raw.write_bytes(b"\n".join(line for line in stream.raw.read_bytes().splitlines() if not line.startswith(b"# OTIS_HOST")) + b"\n")
    elif mutation == "source_altered":
        target = tmp_path / "snapshots.csv"
        target.write_text(target.read_text().replace("4294967295", "4294967294"))
    else:
        stream.raw.write_bytes(stream.raw.read_bytes().replace(b"4294967295", b"4294967294"))
    path.write_text(json.dumps(state))
    # Raw-source corruption is checked independently by offline full-raw
    # binding; live authority reads exact CSV rows and its bounded raw marker.
    if mutation != "raw_source_altered":
        assert not stream.readiness()["ready"]
    exact, _, _ = stream.replay()
    assert not exact


def test_ready_estimate_replays_immutable_accepted_source_and_estimate_content(
    tmp_path,
):
    """A mutable ready-proof is only a byte locator, never ARM evidence.

    The older pointer-only readiness check would have accepted each mutation:
    all changed pointers/hashes remain internally consistent with their CSV
    rows.  The current gate must reconstruct the exact selected APS/raw source
    and the EST's own source identity and arithmetic.
    """
    rows = raw_measurement_rows([10_000_000] * 1200)
    stream = RecordedStream(tmp_path, rows)
    # RecordedStream normally builds one EST over all supplied source rows.
    # This test retains two windows, so freeze the first EST at the first 600.
    first_estimate = rows["estimates.csv"][0]
    first_closing = rows["snapshots.csv"][600]
    first_estimate.update(
        source_closing_snapshot_sequence=first_closing["snapshot_sequence"],
        source_closing_reference_sequence=first_closing["reference_sequence"],
        estimator_timestamp_ticks=first_closing["reference_timestamp_ticks"],
    )
    for index in range(601):
        stream.boundary(index)
    stream.emit(rows["estimates.csv"][0])
    assert stream.readiness("selected-1")["ready"], stream.tracker.errors

    # Retain a second, genuine 600-span window after the first estimate has
    # already become ready.  The live state therefore still names the first
    # window while the canonical CSV contains another individually valid one.
    for index in range(601, 1201):
        stream.boundary(index)

    def accepted_span_pointers() -> list[dict[str, int | str]]:
        pointers: list[dict[str, int | str]] = []
        with (tmp_path / "spans.csv").open("rb") as handle:
            header = next(csv.reader([handle.readline().decode("utf-8")]))
            ordinal = 0
            while raw := handle.readline():
                ordinal += 1
                offset = handle.tell() - len(raw)
                values = next(csv.reader([raw.decode("utf-8")]))
                row = dict(zip(header, values))
                pointers.append(
                    {
                        "csv_row_ordinal": ordinal,
                        # boundary zero emits REF/SNP; every later boundary
                        # emits REF/SNP/CNT/APS in that producer order.
                        "capture_line_ordinal": 2 + 4 * ordinal,
                        "csv_byte_offset": offset,
                        "row_sha256": _digest(row),
                    }
                )
        return pointers

    state_path = tmp_path / FRONTIER_STATE_PATH
    baseline_state = json.loads(state_path.read_text())
    estimate_path = tmp_path / "estimates.csv"
    baseline_estimate = estimate_path.read_bytes()

    def replace_estimate(changes: dict[str, str], state: dict) -> None:
        row = next(csv.DictReader(baseline_estimate.decode("utf-8").splitlines()))
        row.update(changes)
        with estimate_path.open("w", newline="") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=stream.fields["EST"], lineterminator="\n"
            )
            writer.writeheader()
            writer.writerow(row)
        proof = state["qualified_estimates"][0]
        proof["record"] = row
        proof["row_sha256"] = _digest(row)
        proof["capture_session"] = int(row["capture_session"])
        proof["source_acceptance_epoch"] = int(row["source_acceptance_epoch"])
        proof["source_opening_accepted_boundary_ordinal"] = int(
            row["source_opening_accepted_boundary_ordinal"]
        )
        proof["source_closing_accepted_boundary_ordinal"] = int(
            row["source_closing_accepted_boundary_ordinal"]
        )

    cases: list[tuple[str, dict[str, str]]] = [
        ("numeric", {"frequency_error_hz": "1.000000000000"}),
        (
            "epoch",
            {
                "source_acceptance_epoch": "2",
                "source_accepted_spans_ref": "live:APS:1:2:0:600",
            },
        ),
        (
            "endpoint",
            {
                "source_opening_snapshot_sequence": str(
                    int(rows["estimates.csv"][0]["source_opening_snapshot_sequence"])
                    + 1
                )
            },
        ),
    ]
    for name, changes in cases:
        state = deepcopy(baseline_state)
        replace_estimate(changes, state)
        state_path.write_text(json.dumps(state))
        readiness = stream.readiness("selected-1")
        assert not readiness["ready"], (name, readiness)
        assert readiness["errors"], (name, readiness)

    # Restore the genuine EST, then forge the mutable proof to name the later
    # complete window.  Every pointer and digest is genuine, but it is not the
    # canonical EST's declared window and its raw source is different.
    estimate_path.write_bytes(baseline_estimate)
    state = deepcopy(baseline_state)
    state["qualified_estimates"][0]["accepted_span_sources"] = (
        accepted_span_pointers()[600:1200]
    )
    state_path.write_text(json.dumps(state))
    readiness = stream.readiness("selected-1")
    assert not readiness["ready"], readiness
    assert readiness["errors"], readiness


def test_session_transition_clears_previous_source_and_waits_for_current_pair(tmp_path):
    rows = raw_measurement_rows()
    stream = RecordedStream(tmp_path, rows)
    for index in range(601):
        stream.boundary(index)
    stream.emit(rows["estimates.csv"][0])
    assert stream.readiness("selected-1")["ready"]
    later = raw_measurement_rows([10_000_000] * 2, first_ticks=601_000_000, first_event_sequence=1601)
    for row in later["snapshots.csv"]:
        row["session"] = "2"
    stream.rows = later
    stream.boundary(0)
    assert not stream.readiness("selected-1", session=2)["ready"]
    assert not stream.readiness(session=2)["ready"]
    stream.boundary(1)
    assert stream.readiness(session=2)["ready"], stream.tracker.errors
    assert not stream.readiness("selected-1", session=2)["ready"]


def test_nonfinite_estimate_becomes_local_discrepancy(tmp_path):
    rows = raw_measurement_rows()
    stream = RecordedStream(tmp_path, rows)
    for index in range(601):
        stream.boundary(index)
    bad = dict(rows["estimates.csv"][0], frequency_error_hz="NaN")
    stream.emit(bad)
    assert stream.tracker.errors
    assert not stream.readiness("selected-1")["ready"]


def test_frontier_is_first_complete_pair_even_when_aperture_is_invalid(tmp_path):
    rows = raw_measurement_rows([0, 10_000_000])
    rows["counts.csv"][0]["flags"] = str(16 | (1 << 5) | (1 << 9))
    stream = RecordedStream(tmp_path, rows)
    stream.boundary(0)
    stream.boundary(1)
    assert stream.readiness()["ready"]
    assert stream.tracker.frontier["first_count"]["record"]["counted_edges"] == "0"
    artifact = (tmp_path / FRONTIER_PATH).read_bytes()
    stream.boundary(2)
    assert (tmp_path / FRONTIER_PATH).read_bytes() == artifact


def test_new_authority_before_recorded_marker_cannot_be_repaired_offline(tmp_path):
    rows = raw_measurement_rows()
    stream = RecordedStream(tmp_path, rows)
    for index in range(601):
        stream.boundary(index)
    stream.emit(rows["estimates.csv"][0])
    assert stream.replay()[0]
    premature = b'# OTIS_HOST {"event":"host_command_sent","command":"ACTIVE ARM 1 2 3"}\n'
    stream.raw.write_bytes(premature + stream.raw.read_bytes())
    exact, report, _ = stream.replay()
    assert not exact
    assert "precedes" in report["acquisition_frontier"]["errors"][0]


def test_duplicate_changed_estimate_identity_revokes_source_readiness(tmp_path):
    rows = raw_measurement_rows()
    stream = RecordedStream(tmp_path, rows)
    for index in range(601):
        stream.boundary(index)
    stream.emit(rows["estimates.csv"][0])
    assert stream.readiness("selected-1")["ready"]
    stream.emit(dict(rows["estimates.csv"][0], estimate_seq="2", frequency_error_hz="1.0"))
    assert not stream.readiness("selected-1")["ready"]
    assert any("duplicated" in error for error in stream.tracker.errors)


def test_ordinary_counts_do_not_rewrite_live_state_each_second(tmp_path):
    rows = raw_measurement_rows([10_000_000] * 10)
    stream = RecordedStream(tmp_path, rows)
    stream.boundary(0)
    stream.boundary(1)
    state = (tmp_path / FRONTIER_STATE_PATH).read_bytes()
    for index in range(2, 11):
        stream.boundary(index)
    assert (tmp_path / FRONTIER_STATE_PATH).read_bytes() == state


def test_selected_raw_count_occurrences_ignore_prefix_from_prior_timer_wrap(
    tmp_path,
):
    rows = raw_measurement_rows([10_000_000] * 4900)
    stream = RecordedStream(tmp_path, rows)
    for index in range(4901):
        stream.boundary(index)
    estimate = dict(stream.rows["estimates.csv"][0])
    estimate.update(
        source_opening_accepted_boundary_ordinal="4300",
        source_closing_accepted_boundary_ordinal="4900",
        source_opening_snapshot_sequence="4300",
        source_closing_snapshot_sequence="4900",
        source_opening_reference_sequence="4300",
        source_closing_reference_sequence="4900",
        source_accepted_spans_ref="live:APS:1:1:4300:4900",
        estimator_timestamp_ticks=rows["snapshots.csv"][4900][
            "reference_timestamp_ticks"
        ],
    )
    stream.emit(estimate)
    readiness = stream.readiness("selected-1")
    assert readiness["ready"], readiness
