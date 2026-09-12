from __future__ import annotations

from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import pytest

from host.otis_tools import adaptive_hybrid_replay as replay
from host.otis_tools import raw_measurement_replay as raw
from host.otis_tools.accepted_span_replay import POLICY_PATH, accepted_window_ref
from host.otis_tools.authoritative_inputs import (
    collect_authoritative_inputs,
    validate_authoritative_inputs,
)

MODULUS = 1 << 32


@lru_cache(maxsize=1)
def measurement_manifest_value():
    inputs = validate_authoritative_inputs(collect_authoritative_inputs())
    binding = inputs.binding(POLICY_PATH)
    return {"transaction_identities": {"estimator_sha256": "a" * 64},
            "authoritative_inputs": inputs.as_dict(),
            "reference_acceptance": {"path": POLICY_PATH,
                "policy_id": inputs.document(POLICY_PATH)["policy_id"],
                "policy_sha256": binding["sha256"]}}


def accepted_rows(snapshots, counts, *, epoch=1, first_ordinal=0):
    """Declare a retained tracking horizon; this fixture does not claim boot acquisition."""
    policy_hash = measurement_manifest_value()["reference_acceptance"]["policy_sha256"]
    result = []
    for index, (opening, closing, count) in enumerate(zip(snapshots, snapshots[1:], counts), 1):
        result.append(dict(record_type="APS", schema_version="1", capture_session=closing["session"],
            acceptance_epoch=str(epoch), accepted_boundary_ordinal=str((first_ordinal + index) % MODULUS),
            opening_snapshot_sequence=opening["snapshot_sequence"], closing_snapshot_sequence=closing["snapshot_sequence"],
            opening_reference_sequence=opening["reference_sequence"], closing_reference_sequence=closing["reference_sequence"],
            opening_reference_timestamp_ticks=opening["reference_timestamp_ticks"], closing_reference_timestamp_ticks=closing["reference_timestamp_ticks"],
            time_domain="rp2040_monotonic_us32", source_count_first_sequence=count["count_seq"],
            source_count_last_sequence=count["count_seq"], source_count_record_count="1",
            counted_edges=count["counted_edges"], excluded_candidate_count="0", nominal_interval_count="1",
            acceptance_policy_sha256=policy_hash))
    return result


def raw_measurement_rows(edge_counts=None, *, first_sequence=0, first_ticks=0, first_event_sequence=1000, interval_ticks=1_000_000):
    """A raw current-producer fixture, including both boundary anchors."""
    edge_counts = [10_000_000] * 600 if edge_counts is None else edge_counts
    snapshots, references, counts = [], [], []
    counter = MODULUS - 1
    for index in range(len(edge_counts) + 1):
        seq = (first_sequence + index) % MODULUS
        ticks = (first_ticks + index * interval_ticks) % MODULUS
        if index:
            counter = (counter - edge_counts[index - 1]) % MODULUS
            counts.append(dict(record_type="CNT", schema_version="1", count_seq=str(seq), channel_id="2",
                gate_open_ticks=str((ticks - interval_ticks) % MODULUS), gate_close_ticks=str(ticks),
                gate_domain="rp2040_monotonic_us32", counted_edges=str(edge_counts[index - 1]),
                source_edge="R", source_domain="h1_oscillator_10mhz", flags="16"))
        snapshots.append(dict(record_type="SNP", schema_version="1", session="1", snapshot_sequence=str(seq),
            cumulative_down_counter=str(counter), reference_sequence=str(seq), reference_timestamp_ticks=str(ticks),
            status="0", backend="pio_wait_cumulative_snapshot_dma_v1"))
        references.append(dict(record_type="REF", schema_version="1", event_seq=str(first_event_sequence + index), channel_id="1",
            edge="R", timestamp_ticks=str(ticks), capture_domain="rp2040_monotonic_us32", flags="16"))
    frequency = float(sum(edge_counts)) / len(edge_counts)
    estimates = [dict(estimate_seq="1", estimate_id="selected-1", estimator_version=replay.SELECTED_ESTIMATOR_ID,
        estimator_timestamp_ticks=snapshots[-1]["reference_timestamp_ticks"], time_domain="rp2040_monotonic_us32",
        capture_session="1", source_acceptance_epoch="1",
        source_opening_accepted_boundary_ordinal=str(first_sequence),
        source_closing_accepted_boundary_ordinal=snapshots[-1]["snapshot_sequence"],
        source_opening_snapshot_sequence=str(first_sequence), source_closing_snapshot_sequence=snapshots[-1]["snapshot_sequence"],
        source_opening_reference_sequence=str(first_sequence), source_closing_reference_sequence=snapshots[-1]["reference_sequence"],
        source_accepted_spans_ref=accepted_window_ref(1, 1, first_sequence, int(snapshots[-1]["snapshot_sequence"])),
        accepted_sample_count=str(len(edge_counts)),
        config_hash="a" * 64, observation_validity="valid", reference_validity="valid", count_validity="valid",
        frequency_estimate_hz=f"{frequency:.12f}", frequency_error_hz=f"{frequency - 10_000_000.0:.12f}")]
    return {"counts.csv": counts, "snapshots.csv": snapshots, "ref.csv": references, "evt.csv": [], "estimates.csv": estimates,
            "spans.csv": accepted_rows(snapshots, counts, first_ordinal=first_sequence)}


def run_measurement(monkeypatch, rows):
    files = [dict(contract=contract, path=path) for contract, path in [
        ("count_observations_v1", "counts.csv"), ("pps_snapshots_v1", "snapshots.csv"),
        ("accepted_pps_spans_v1", "spans.csv"), ("estimates_v3", "estimates.csv")]]
    files += [dict(contract="raw_events_v1", record_type=tag, path=path) for tag, path in [("REF", "ref.csv"), ("EVT", "evt.csv")]]
    monkeypatch.setattr(replay, "_read_csv", lambda path: rows[path.name])
    return replay._measurement_replay(SimpleNamespace(root=Path("/unused"), files=files),
        measurement_manifest_value())


def raw_replay(rows):
    return raw._raw_count_replay(rows["snapshots.csv"], rows["ref.csv"], rows["counts.csv"])


def test_valid_raw_count_and_native_timestamp_wrap_replay(monkeypatch):
    rows = raw_measurement_rows(first_ticks=MODULUS - 2_000_000)
    original = deepcopy(rows)
    exact, report, _ = run_measurement(monkeypatch, rows)
    assert exact, report
    assert report["accepted_span_replay"]["raw_count_replay"]["counter_wrap_count"] == 1
    assert rows == original


def test_raw_counter_and_sequence_wrap_are_derived_from_current_contract(monkeypatch):
    rows = raw_measurement_rows(first_sequence=MODULUS - 300)
    exact, report, _ = run_measurement(monkeypatch, rows)
    assert exact, report


def test_valid_derived_counts_cannot_mask_frozen_raw_counter(monkeypatch):
    rows = raw_measurement_rows()
    for row in rows["snapshots.csv"]:
        row["cumulative_down_counter"] = str(MODULUS - 1)
    exact, report, _ = run_measurement(monkeypatch, rows)
    assert not exact
    assert not report["accepted_span_replay"]["raw_count_replay"]["exact"]
    assert report["comparisons"][0]["pass"] is False


@pytest.mark.parametrize("mutation", ["snapshot_gap", "reference_mismatch", "session_crossing", "counter_domain", "timestamp_domain", "duplicate_count", "missing_count", "endpoint", "status", "count_only"])
def test_one_sided_raw_or_derived_corruption_fails_closed(monkeypatch, mutation):
    rows = raw_measurement_rows()
    if mutation == "snapshot_gap":
        del rows["snapshots.csv"][200]
    elif mutation == "reference_mismatch":
        rows["ref.csv"][200]["timestamp_ticks"] = "200000001"
    elif mutation == "session_crossing":
        rows["snapshots.csv"][200]["session"] = "2"
    elif mutation == "counter_domain":
        rows["snapshots.csv"][200]["backend"] = "unknown_counter"
    elif mutation == "timestamp_domain":
        rows["ref.csv"][200]["capture_domain"] = "rp2040_monotonic_us64"
    elif mutation == "duplicate_count":
        rows["counts.csv"].append(deepcopy(rows["counts.csv"][0]))
    elif mutation == "missing_count":
        del rows["counts.csv"][200]
    elif mutation == "endpoint":
        rows["counts.csv"][200]["gate_open_ticks"] = "200000001"
    elif mutation == "status":
        rows["snapshots.csv"][200]["status"] = "1"
    elif mutation == "count_only":
        rows["counts.csv"][200]["counted_edges"] = "10000001"
    exact, report, _ = run_measurement(monkeypatch, rows)
    assert not exact, report
    assert not report["accepted_span_replay"]["raw_count_replay"]["exact"]


def test_declared_zero_aperture_is_reconstructable_but_cannot_enter_estimate(monkeypatch):
    rows = raw_measurement_rows([0] + [10_000_000] * 599)
    rows["counts.csv"][0]["flags"] = str(16 | (1 << 5) | (1 << 9))
    raw_exact, report, intervals = raw_replay(rows)
    assert raw_exact, report
    assert not intervals[0]["measurement_valid"]
    exact, report, _ = run_measurement(monkeypatch, rows)
    assert not exact
    assert report["accepted_span_replay"]["raw_count_replay"]["exact"]


def test_declared_short_aperture_and_recovery_are_excluded_then_resume():
    rows = raw_measurement_rows([10_000_000] * 4)
    # The second boundary is 0.5 seconds after the first; subsequent intervals
    # return to one second. Firmware excludes the next interval for recovery.
    for index in range(1, 5):
        ticks = index * 1_000_000 - 500_000
        rows["snapshots.csv"][index]["reference_timestamp_ticks"] = str(ticks)
        rows["ref.csv"][index]["timestamp_ticks"] = str(ticks)
        rows["counts.csv"][index - 1]["gate_close_ticks"] = str(ticks)
        if index > 1:
            rows["counts.csv"][index - 1]["gate_open_ticks"] = str(ticks - 1_000_000)
    for count in rows["counts.csv"][:2]:
        count["flags"] = str(16 | (1 << 3) | (1 << 12))
    exact, report, intervals = raw_replay(rows)
    assert exact, report
    assert [item["measurement_valid"] for item in intervals] == [False, False, True, True]


def test_excessive_nonwrapping_counter_delta_is_never_valid():
    rows = raw_measurement_rows([200_000_000])
    exact, report, intervals = raw_replay(rows)
    # Producer arithmetic can be reproduced; independent plausibility still
    # rejects use in a selected estimate even where producer flags are clean.
    assert exact, report
    assert not intervals[0]["measurement_valid"]


def test_replay_bounds_match_current_firmware_profile():
    root = Path(__file__).resolve().parents[1]
    config = (root / "firmware/arduino/otis_nano_rp2040_connect/otis_config.h").read_text()
    protocol = (root / "firmware/arduino/otis_nano_rp2040_connect/otis_protocol.h").read_text()
    assert '#define OTIS_DOMAIN_H1_OSCILLATOR_10MHZ "h1_oscillator_10mhz"' in protocol
    for declaration in (
        "#define OTIS_PPS_GATE_MIN_INTERVAL_US 800000u",
        "#define OTIS_PPS_GATE_MAX_INTERVAL_US 1200000u",
        "#define OTIS_PPS_SNAPSHOT_MAX_CAPTURED_EDGE_RATE_HZ 133000000u",
    ):
        assert declaration in config


def test_declared_bad_aperture_does_not_poison_later_complete_estimate(monkeypatch):
    rows = raw_measurement_rows([0] + [10_000_000] * 608)
    rows["counts.csv"][0]["flags"] = str(16 | (1 << 5) | (1 << 9))
    # Retain the loss and eight acquisition intervals, then expose the new
    # accepted anchor and the subsequent complete 600-span window.
    rows["spans.csv"] = accepted_rows(rows["snapshots.csv"][9:], rows["counts.csv"][9:], epoch=2)
    estimate = rows["estimates.csv"][0]
    estimate.update(source_acceptance_epoch="2", source_opening_accepted_boundary_ordinal="0",
        source_closing_accepted_boundary_ordinal="600", source_accepted_spans_ref=accepted_window_ref(1, 2, 0, 600),
        source_opening_snapshot_sequence="9", source_opening_reference_sequence="9", accepted_sample_count="600",
        frequency_estimate_hz="10000000.000000000000", frequency_error_hz="0.000000000000")
    exact, report, _ = run_measurement(monkeypatch, rows)
    assert exact, report
    assert report["accepted_span_replay"]["raw_count_replay"]["invalid_aperture_count"] == 1


def test_new_session_reanchors_and_estimate_uses_its_exact_closing_identity(monkeypatch):
    earlier = raw_measurement_rows([10_000_000] * 3)
    later = raw_measurement_rows(first_ticks=4_000_000)
    for index, row in enumerate(later["snapshots.csv"]):
        row.update(session="2", reference_sequence=str(index + 4))
    for index, row in enumerate(later["ref.csv"]):
        row["event_seq"] = str(index + 1004)
    later["spans.csv"] = earlier["spans.csv"] + accepted_rows(later["snapshots.csv"], later["counts.csv"])
    later["estimates.csv"][0].update(capture_session="2", source_opening_reference_sequence="4",
        source_closing_reference_sequence="604", source_accepted_spans_ref=accepted_window_ref(2, 1, 0, 600))
    for filename in ("snapshots.csv", "ref.csv", "counts.csv"):
        later[filename] = earlier[filename] + later[filename]
    exact, report, _ = run_measurement(monkeypatch, later)
    assert exact, report
    assert report["accepted_span_replay"]["raw_count_replay"]["interval_count"] == 603


@pytest.mark.parametrize("filename", ["counts.csv", "ref.csv"])
def test_reordered_records_are_not_silently_sorted_into_validity(monkeypatch, filename):
    rows = raw_measurement_rows()
    rows[filename][100], rows[filename][101] = rows[filename][101], rows[filename][100]
    exact, report, _ = run_measurement(monkeypatch, rows)
    assert not exact, report


def test_declared_snapshot_overwrite_is_reconstructable_but_not_usable():
    rows = raw_measurement_rows([10_000_000] * 3)
    rows["snapshots.csv"][1]["status"] = "1"
    rows["counts.csv"][0]["flags"] = str(16 | (1 << 1) | (1 << 12))
    exact, report, intervals = raw_replay(rows)
    assert exact, report
    assert [item["measurement_valid"] for item in intervals] == [False, True, True]


def test_actual_operational_rehearsal_bootstrap_has_one_replayable_aperture():
    from tools.otis_rehearsal_device import DeterministicPtyInstrument

    instrument = object.__new__(DeterministicPtyInstrument)
    instrument.raw_interval_adjustments = {}
    instrument.runtime = {"authoritative_inputs": measurement_manifest_value()["authoritative_inputs"]}
    instrument.reference_acceptance_binding = measurement_manifest_value()["reference_acceptance"]
    emitted = []
    instrument._emit_rows = lambda fields, rows: emitted.extend(rows)
    instrument._emit_initial_observations()
    assert [int(row["event_seq"]) for row in emitted
            if row["record_type"] in {"EVT", "REF"}] == [1000, 1001, 1002]
    exact, report, intervals = raw._raw_count_replay(
        [row for row in emitted if row["record_type"] == "SNP"],
        [row for row in emitted if row["record_type"] == "REF"],
        [row for row in emitted if row["record_type"] == "CNT"],
    )
    assert exact, report
    assert len(intervals) == 1
    assert intervals[0]["counted_edges"] == 10_000_000
    assert intervals[0]["measurement_valid"]


def test_unpaired_terminal_ref_is_retained_without_claiming_capture_completeness(monkeypatch):
    rows = raw_measurement_rows()
    terminal_ref = deepcopy(rows["ref.csv"][-1])
    terminal_ref.update(event_seq="1601", timestamp_ticks="601000000")
    rows["ref.csv"].append(terminal_ref)
    exact, report, _ = run_measurement(monkeypatch, rows)
    assert exact, report
    assert report["accepted_span_replay"]["raw_count_replay"]["unassociated_reference_count"] == 1
    assert report["accepted_span_replay"]["raw_count_replay"]["capture_completeness_claimed"] is False


def test_independent_emitter_offset_and_external_event_gaps_do_not_veto_d14(monkeypatch):
    rows = raw_measurement_rows()
    assert int(rows["ref.csv"][0]["event_seq"]) - int(rows["snapshots.csv"][0]["reference_sequence"]) == 1000
    # The global emitter can process arbitrary EVT traffic between D14 edges.
    # D14 replay must not require that optional evidence to explain the gap.
    for row in rows["ref.csv"][200:]:
        row["event_seq"] = str(int(row["event_seq"]) + 1_000_000)
    original = deepcopy(rows)
    exact, report, _ = run_measurement(monkeypatch, rows)
    assert exact, report
    assert rows == original


@pytest.mark.parametrize("mutation", ["duplicate_event_seq", "event_sequence_wrap", "missing_reference", "source_sequence_gap", "missing_source_sequence"])
def test_independent_order_and_source_continuity_still_fail_closed(mutation):
    rows = raw_measurement_rows([10_000_000] * 3)
    if mutation == "duplicate_event_seq":
        rows["ref.csv"][1]["event_seq"] = rows["ref.csv"][0]["event_seq"]
    elif mutation == "event_sequence_wrap":
        for index, row in enumerate(rows["ref.csv"]):
            row["event_seq"] = str((MODULUS - 2 + index) % MODULUS)
    elif mutation == "missing_reference":
        del rows["ref.csv"][1]
    elif mutation == "source_sequence_gap":
        rows["snapshots.csv"][1]["reference_sequence"] = "99"
    else:
        del rows["snapshots.csv"][1]["reference_sequence"]
    exact, report, _ = raw_replay(rows)
    assert not exact, report


def test_repeated_low32_timestamps_across_twelve_wraps_have_unique_ordered_occurrences():
    # 2^20 us is inside the admitted aperture and repeats low32 values every
    # 4096 edges. Matching the full ordered run distinguishes all 12 cycles.
    rows = raw_measurement_rows([10_000_000] * (12 * 4096 + 600), interval_ticks=1 << 20)
    exact, report, intervals = raw_replay(rows)
    assert exact, report
    assert len(intervals) == 12 * 4096 + 600
    assert rows["ref.csv"][0]["timestamp_ticks"] == rows["ref.csv"][4096]["timestamp_ticks"]
    assert all(item["measurement_valid"] for item in intervals)


def test_repeated_timestamp_pattern_with_two_legal_placements_is_ambiguous():
    rows = raw_measurement_rows([10_000_000] * 4098, interval_ticks=1 << 20)
    # The retained SNP/CNT subset could refer to either occurrence in REF.
    # Their source ordinals cannot be equated with the emitter's ordinals.
    rows["snapshots.csv"] = rows["snapshots.csv"][:3]
    rows["counts.csv"] = rows["counts.csv"][:2]
    exact, report, _ = raw_replay(rows)
    assert not exact
    assert "ambiguous D14 REF association" in report["errors"][0]


def test_duplicate_timestamp_occurrence_cannot_be_chosen_arbitrarily():
    rows = raw_measurement_rows([10_000_000])
    for row in rows["snapshots.csv"]:
        row["reference_timestamp_ticks"] = "0"
    for row in rows["ref.csv"]:
        row["timestamp_ticks"] = "0"
    duplicate = deepcopy(rows["ref.csv"][-1])
    duplicate["event_seq"] = "1002"
    rows["ref.csv"].append(duplicate)
    exact, report, _ = raw_replay(rows)
    assert not exact
    assert "ambiguous D14 REF association" in report["errors"][0]


def test_raw_association_uses_actual_distinct_producer_sequence_fields():
    root = Path(__file__).resolve().parents[1]
    source = (root / "firmware/arduino/otis_nano_rp2040_connect/otis_nano_rp2040_connect.ino").read_text()
    emitter = source.split("void emit_captured_edge(", 1)[1].split("OtisRegulationStaticCodeState regulation_static_code_state", 1)[0]
    assert "record.source_sequence," in emitter
    assert "message.raw_edge.sequence = runtime_state.sequences.event_seq++;" in emitter
    assert "message.raw_edge.reference_record = record.reference_record;" in emitter


def test_estimate_names_distinct_snapshot_and_physical_source_ordinals(monkeypatch):
    rows = raw_measurement_rows()
    for row in rows["snapshots.csv"]:
        row["reference_sequence"] = str(int(row["reference_sequence"]) + 7300)
    rows["spans.csv"] = accepted_rows(rows["snapshots.csv"], rows["counts.csv"])
    rows["estimates.csv"][0].update(source_opening_reference_sequence="7300", source_closing_reference_sequence="7900")
    exact, report, _ = run_measurement(monkeypatch, rows)
    assert exact, report
    root = Path(__file__).resolve().parents[1]
    firmware = root / "firmware/arduino/otis_nano_rp2040_connect"
    source = (firmware / "otis_nano_rp2040_connect.ino").read_text()
    assert "observation.sequence = snapshot.sequence;" in source
    assert "snapshot_message.snapshot.reference_sequence =\n      observation.reference_sequence;" in source
    live = (firmware / "otis_frequency_regulation_live.cpp").read_text()
    assert "accepted_boundary_ordinal" in live
    assert "static_cast<unsigned long>(span.last_sequence)" in live
    assert "span.selected_first_reference_sequence" in live
    assert "span.last_reference_sequence" in live


def test_missing_opening_snapshot_leaves_first_retained_count_unproven():
    rows = raw_measurement_rows([10_000_000] * 3)
    del rows["snapshots.csv"][0]
    del rows["ref.csv"][0]
    exact, report, intervals = raw_replay(rows)
    assert not exact
    assert len(intervals) == 2
    assert all(item["count_exact"] for item in intervals)
    assert "CNT records lack a unique adjacent same-session SNP/REF pair" in report["errors"]


def test_accepted_ordinals_cannot_hide_a_skipped_raw_interval(monkeypatch):
    rows = raw_measurement_rows([10_000_000] * 601)
    del rows["spans.csv"][1]
    for ordinal, span in enumerate(rows["spans.csv"], 1):
        span["accepted_boundary_ordinal"] = str(ordinal)
    rows["estimates.csv"][0].update(source_closing_accepted_boundary_ordinal="600",
        source_accepted_spans_ref=accepted_window_ref(1, 1, 0, 600), accepted_sample_count="600")
    exact, report, _ = run_measurement(monkeypatch, rows)
    assert not exact
    assert report["accepted_span_replay"]["raw_count_replay"]["exact"]
    assert "previous accepted boundary" in report["accepted_span_replay"]["errors"][0]


def test_accepted_span_cannot_skip_an_earlier_in_window_candidate():
    from host.otis_tools.accepted_span_replay import replay_accepted_spans
    rows = raw_measurement_rows([10_000_000, 10_000])
    rows["snapshots.csv"][2]["reference_timestamp_ticks"] = "1001000"
    rows["ref.csv"][2]["timestamp_ticks"] = "1001000"
    rows["counts.csv"][1].update(gate_close_ticks="1001000", flags=str(16 | (1 << 3) | (1 << 12)))
    span = rows["spans.csv"][0]
    span.update(closing_snapshot_sequence="2", closing_reference_sequence="2",
                closing_reference_timestamp_ticks="1001000", source_count_last_sequence="2",
                source_count_record_count="2", excluded_candidate_count="1", counted_edges="10010000")
    manifest = measurement_manifest_value()
    exact, report, _ = replay_accepted_spans(rows["snapshots.csv"], rows["ref.csv"], rows["counts.csv"], [span],
        acceptance_policy=validate_authoritative_inputs(manifest["authoritative_inputs"]).document(POLICY_PATH),
        acceptance_policy_sha256=manifest["reference_acceptance"]["policy_sha256"])
    assert not exact
    assert report["raw_count_replay"]["exact"]
    assert "at or after the acceptance window" in report["errors"][0]


def test_raw_accepted_spans_replay_without_estimator_output(monkeypatch):
    rows = raw_measurement_rows()
    rows["estimates.csv"] = []

    exact, report, estimates = run_measurement(monkeypatch, rows)

    assert exact, report
    assert report["raw_measurement_exact"] is True
    assert report["accepted_span_replay"]["raw_count_replay"]["exact"] is True
    assert report["estimate_replay"] == {
        "applicability": "not_applicable_no_emitted_estimates",
        "emitted_count": 0,
        "exact": True,
    }
    assert report["selected_estimate_sources"] == []
    assert estimates == {}


def test_missing_raw_count_fails_even_without_estimator_output(monkeypatch):
    rows = raw_measurement_rows()
    rows["estimates.csv"] = []
    del rows["counts.csv"][300]

    exact, report, _ = run_measurement(monkeypatch, rows)

    assert exact is False
    assert report["accepted_span_replay"]["raw_count_replay"]["exact"] is False
