from __future__ import annotations

import csv
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from types import SimpleNamespace

import pytest

from host.otis_tools import adaptive_hybrid_replay as replay
from host.otis_tools import raw_measurement_replay as raw
from host.otis_tools.accepted_span_replay import POLICY_PATH, accepted_window_ref
from host.otis_tools.adaptive_hybrid_analyze import _validate_manifest_csvs
from host.otis_tools.authoritative_inputs import (
    collect_authoritative_inputs,
    validate_authoritative_inputs,
)
from host.otis_tools.contracts import CONTRACT_FIELDS

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
        snapshots.append(dict(record_type="SNP", schema_version="2", session="1", snapshot_sequence=str(seq),
            cumulative_down_counter=str(counter), reference_sequence=str(seq), reference_timestamp_ticks=str(ticks),
            timestamp_uncertainty_ticks="1", status="0", backend="pio_wait_cumulative_snapshot_fifo_irq_v2"))
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
        accepted_sample_count=str(len(edge_counts)), source_status_refs="live:STS:pps_gate",
        source_dac_ref="live:DAC:1", config_hash="a" * 64, observation_validity="valid",
        reference_validity="valid", count_validity="valid",
        frequency_observation_hz=f"{frequency:.12f}", frequency_estimate_hz=f"{frequency:.12f}",
        frequency_error_hz=f"{frequency - 10_000_000.0:.12f}")]
    return {"counts.csv": counts, "snapshots.csv": snapshots, "ref.csv": references, "evt.csv": [], "estimates.csv": estimates,
            "spans.csv": accepted_rows(snapshots, counts, first_ordinal=first_sequence)}


def diagnostic_estimate(rows, *, estimate_seq=0, opening_offset=0):
    """Build the compact form of an actual overlapping diagnostic EST row."""
    sources = rows["spans.csv"][
        opening_offset : opening_offset + replay.DIAGNOSTIC_ESTIMATOR_SAMPLE_COUNT
    ]
    first, last = sources[0], sources[-1]
    opening = (int(first["accepted_boundary_ordinal"]) - 1) % MODULUS
    closing = int(last["accepted_boundary_ordinal"])
    total = sum(int(span["counted_edges"]) for span in sources)
    frequency = float(total) / replay.DIAGNOSTIC_ESTIMATOR_SAMPLE_COUNT
    row = deepcopy(rows["estimates.csv"][0])
    row.update(
        estimate_seq=str(estimate_seq),
        estimate_id=f"est:frequency_regulation:diagnostic60:{estimate_seq:06d}",
        estimator_version=replay.DIAGNOSTIC_ESTIMATOR_ID,
        estimator_timestamp_ticks=last["closing_reference_timestamp_ticks"],
        capture_session=last["capture_session"],
        source_acceptance_epoch=last["acceptance_epoch"],
        source_opening_accepted_boundary_ordinal=str(opening),
        source_closing_accepted_boundary_ordinal=str(closing),
        source_opening_snapshot_sequence=first["opening_snapshot_sequence"],
        source_closing_snapshot_sequence=last["closing_snapshot_sequence"],
        source_opening_reference_sequence=first["opening_reference_sequence"],
        source_closing_reference_sequence=last["closing_reference_sequence"],
        source_accepted_spans_ref=accepted_window_ref(
            int(last["capture_session"]), int(last["acceptance_epoch"]),
            opening, closing,
        ),
        accepted_sample_count=str(replay.DIAGNOSTIC_ESTIMATOR_SAMPLE_COUNT),
        frequency_estimate_hz=f"{frequency:.12f}",
        frequency_error_hz=f"{frequency - 10_000_000.0:.12f}",
        preview_eligibility="false",
        eligibility_reason_codes="diagnostic_non_authoritative",
    )
    return row


def run_measurement(monkeypatch, rows):
    files = [dict(contract=contract, path=path) for contract, path in [
        ("count_observations_v1", "counts.csv"), ("pps_snapshots_v2", "snapshots.csv"),
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
        frequency_observation_hz="10000000.000000000000",
        frequency_estimate_hz="10000000.000000000000", frequency_error_hz="0.000000000000")
    exact, report, _ = run_measurement(monkeypatch, rows)
    assert exact, report
    assert report["accepted_span_replay"]["raw_count_replay"]["invalid_aperture_count"] == 1


def test_new_session_reanchors_and_estimate_uses_its_exact_closing_identity(monkeypatch):
    earlier = raw_measurement_rows([10_000_000] * 3)
    later = raw_measurement_rows(first_ticks=4_000_000)
    for row in later["snapshots.csv"]:
        row.update(session="2")
    for index, row in enumerate(later["ref.csv"]):
        row["event_seq"] = str(index + 1004)
    later["spans.csv"] = earlier["spans.csv"] + accepted_rows(later["snapshots.csv"], later["counts.csv"])
    later["estimates.csv"][0].update(capture_session="2", source_opening_reference_sequence="0",
        source_closing_reference_sequence="600", source_accepted_spans_ref=accepted_window_ref(2, 1, 0, 600))
    for filename in ("snapshots.csv", "ref.csv", "counts.csv"):
        later[filename] = earlier[filename] + later[filename]
    exact, report, _ = run_measurement(monkeypatch, later)
    assert exact, report
    assert report["accepted_span_replay"]["raw_count_replay"]["interval_count"] == 603


def test_analyzer_accepts_session_reset_and_in_session_count_sequence_wrap(
    tmp_path: Path,
):
    earlier = raw_measurement_rows(
        [10_000_000] * 5,
        first_sequence=MODULUS - 3,
    )
    # The first new-session CNT is more than half a monotonic-us32 period
    # after the previous CNT. Two retained REF-only observations preserve
    # unambiguous D14 chronology across the D8-local absence.
    later = raw_measurement_rows(first_ticks=2_152_000_000)
    for row in later["snapshots.csv"]:
        row.update(session="2")
    for index, row in enumerate(later["ref.csv"]):
        row["event_seq"] = str(index + 1008)
    bridge_references = []
    for event_seq, ticks in ((1006, 1_000_000_000), (1007, 2_000_000_000)):
        row = deepcopy(earlier["ref.csv"][-1])
        row.update(event_seq=str(event_seq), timestamp_ticks=str(ticks))
        bridge_references.append(row)
    later["spans.csv"] = earlier["spans.csv"] + accepted_rows(
        later["snapshots.csv"], later["counts.csv"]
    )
    later["estimates.csv"] = []
    later["snapshots.csv"] = earlier["snapshots.csv"] + later["snapshots.csv"]
    later["ref.csv"] = (
        earlier["ref.csv"] + bridge_references + later["ref.csv"]
    )
    later["counts.csv"] = earlier["counts.csv"] + later["counts.csv"]

    files = [
        {"contract": contract, "path": filename}
        for contract, filename in (
            ("count_observations_v1", "counts.csv"),
            ("pps_snapshots_v2", "snapshots.csv"),
            ("accepted_pps_spans_v1", "spans.csv"),
            ("estimates_v3", "estimates.csv"),
        )
    ]
    files.extend(
        {
            "contract": "raw_events_v1",
            "record_type": record_type,
            "path": filename,
        }
        for record_type, filename in (("REF", "ref.csv"), ("EVT", "evt.csv"))
    )
    contract_by_filename = {
        "counts.csv": "count_observations_v1",
        "snapshots.csv": "pps_snapshots_v2",
        "spans.csv": "accepted_pps_spans_v1",
        "estimates.csv": "estimates_v3",
        "ref.csv": "raw_events_v1",
        "evt.csv": "raw_events_v1",
    }
    for filename, rows in later.items():
        path = tmp_path / filename
        fieldnames = CONTRACT_FIELDS[contract_by_filename[filename]]
        with path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(rows)
    manifest = SimpleNamespace(
        root=tmp_path,
        files=files,
        known_channels=frozenset({0, 1, 2}),
        known_domains=frozenset({"rp2040_monotonic_us32"}),
    )

    assert [
        int(row["count_seq"]) for row in later["counts.csv"][:6]
    ] == [MODULUS - 2, MODULUS - 1, 0, 1, 2, 1]

    csv_results = _validate_manifest_csvs(
        manifest,
        expected_policy_sha256=measurement_manifest_value()[
            "reference_acceptance"
        ]["policy_sha256"],
    )
    assert all(result["exact"] for result in csv_results.values()), csv_results
    exact, report, _ = replay._measurement_replay(
        manifest, measurement_manifest_value()
    )
    assert exact, report
    assert report["accepted_span_replay"]["raw_count_replay"][
        "interval_count"
    ] == 605

    # A standalone CNT file cannot classify this corruption. The joined replay
    # must still reject it using same-session SNP identity and exact endpoints.
    later["counts.csv"][1]["count_seq"] = later["counts.csv"][0]["count_seq"]
    counts_path = tmp_path / "counts.csv"
    with counts_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=CONTRACT_FIELDS["count_observations_v1"]
        )
        writer.writeheader()
        writer.writerows(later["counts.csv"])
    assert _validate_manifest_csvs(
        manifest,
        expected_policy_sha256=measurement_manifest_value()[
            "reference_acceptance"
        ]["policy_sha256"],
    )["count_observations_v1"]["exact"] is True
    exact, report, _ = replay._measurement_replay(
        manifest, measurement_manifest_value()
    )
    assert not exact
    assert not report["accepted_span_replay"]["raw_count_replay"]["exact"]

    # Per-row gate semantics remain a standalone CSV responsibility.
    later["counts.csv"][0]["gate_close_ticks"] = later["counts.csv"][0][
        "gate_open_ticks"
    ]
    with counts_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=CONTRACT_FIELDS[
            "count_observations_v1"
        ])
        writer.writeheader()
        writer.writerows(later["counts.csv"])
    count_validation = _validate_manifest_csvs(
        manifest,
        expected_policy_sha256=measurement_manifest_value()[
            "reference_acceptance"
        ]["policy_sha256"],
    )["count_observations_v1"]
    assert count_validation["exact"] is False
    assert any(
        "gate progression" in error for error in count_validation["errors"]
    )


@pytest.mark.parametrize("filename", ["counts.csv", "ref.csv"])
def test_reordered_records_are_not_silently_sorted_into_validity(monkeypatch, filename):
    rows = raw_measurement_rows()
    rows[filename][100], rows[filename][101] = rows[filename][101], rows[filename][100]
    exact, report, _ = run_measurement(monkeypatch, rows)
    assert not exact, report


def test_declared_timestamp_ambiguous_batch_is_reconstructable_but_not_usable():
    rows = raw_measurement_rows([10_000_000] * 3)
    rows["snapshots.csv"][1]["status"] = "1"
    rows["counts.csv"][0]["flags"] = str(16 | (1 << 5) | (1 << 12))
    rows["counts.csv"][1]["flags"] = str(16 | (1 << 3) | (1 << 12))
    exact, report, intervals = raw_replay(rows)
    assert exact, report
    assert [item["measurement_valid"] for item in intervals] == [False, False, True]
    assert intervals[0]["observation_age_ambiguous"] is True


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
    assert any("ambiguous REF derivative placement" in error for error in report["errors"])


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
    assert any("ambiguous REF derivative placement" in error for error in report["errors"])


def test_raw_ref_is_emitted_from_the_same_fifo_snapshot_owner():
    root = Path(__file__).resolve().parents[1]
    source = (root / "firmware/arduino/otis_nano_rp2040_connect/otis_nano_rp2040_connect.ino").read_text()
    producer = source.split("void drain_reference_snapshots(void)", 1)[1].split(
        "void service_adaptive_hybrid_regulation_application_outcome", 1
    )[0]
    assert "const auto observation = otis_reference_boundary(snapshot);" in producer
    assert "message.raw_edge.timestamp_ticks = snapshot.service_ticks;" in producer
    assert "snapshot.cumulative_down_counter, snapshot.sequence," in producer


def test_estimate_preserves_equal_single_owner_consumer_identity(monkeypatch):
    rows = raw_measurement_rows()
    exact, report, _ = run_measurement(monkeypatch, rows)
    assert exact, report
    assert all(
        row["snapshot_sequence"] == row["reference_sequence"]
        for row in rows["snapshots.csv"]
    )
    estimate = rows["estimates.csv"][0]
    assert estimate["source_opening_snapshot_sequence"] == estimate["source_opening_reference_sequence"]
    assert estimate["source_closing_snapshot_sequence"] == estimate["source_closing_reference_sequence"]

def test_missing_opening_snapshot_leaves_first_retained_count_unproven():
    rows = raw_measurement_rows([10_000_000] * 3)
    del rows["snapshots.csv"][0]
    del rows["ref.csv"][0]
    exact, report, intervals = raw_replay(rows)
    assert not exact
    assert len(intervals) == 2
    assert all(item["count_exact"] for item in intervals)
    assert "CNT records lack a unique adjacent same-session SNP pair" in report["errors"]


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


def test_accepted_span_requires_complete_uncertainty_interval_inside_window():
    from host.otis_tools.accepted_span_replay import replay_accepted_spans

    rows = raw_measurement_rows([10_000_000])
    closing = rows["snapshots.csv"][1]
    closing["reference_timestamp_ticks"] = "1001251"
    closing["timestamp_uncertainty_ticks"] = "2"
    rows["ref.csv"][1]["timestamp_ticks"] = "1001251"
    rows["counts.csv"][0]["gate_close_ticks"] = "1001251"
    rows["spans.csv"][0]["closing_reference_timestamp_ticks"] = "1001251"
    manifest = measurement_manifest_value()
    exact, report, _ = replay_accepted_spans(
        rows["snapshots.csv"], rows["ref.csv"], rows["counts.csv"],
        rows["spans.csv"],
        acceptance_policy=validate_authoritative_inputs(
            manifest["authoritative_inputs"]
        ).document(POLICY_PATH),
        acceptance_policy_sha256=manifest["reference_acceptance"][
            "policy_sha256"
        ],
    )
    assert not exact
    assert report["raw_count_replay"]["exact"]
    assert "complete admission interval differs" in report["errors"][0]


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
        "selected_sources_exact": True,
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


def test_selected_replay_isolated_from_actual_overlapping_diagnostic_rows(monkeypatch):
    rows = raw_measurement_rows()
    selected = rows["estimates.csv"][0]
    selected["estimate_seq"] = "1"
    first_diagnostic = diagnostic_estimate(rows, estimate_seq=0)
    second_diagnostic = diagnostic_estimate(rows, estimate_seq=2, opening_offset=1)
    rows["estimates.csv"] = [first_diagnostic, selected, second_diagnostic]

    exact, report, estimates_by_id = run_measurement(monkeypatch, rows)

    assert exact, report
    assert report["raw_measurement_exact"] is True
    assert report["estimate_replay"] == {
        "applicability": "emitted_selected_estimates",
        "emitted_count": 1,
        "selected_sources_exact": True,
        "exact": True,
    }
    assert report["diagnostic_estimate_replay"]["emitted_count"] == 2
    assert report["diagnostic_estimate_replay"]["exact"] is True
    assert report["diagnostic_estimate_replay"]["authority"] == "none"
    assert report["estimate_stream_integrity"]["exact"] is True
    assert report["known_estimator_versions"]["exact"] is True
    assert list(estimates_by_id) == ["selected-1"]
    assert [source["estimate_id"] for source in report["selected_estimate_sources"]] == [
        "selected-1"
    ]
    assert report["selected_estimate_sources"][0]["source_status_refs"] == (
        "live:STS:pps_gate"
    )
    assert report["selected_estimate_sources"][0]["source_dac_ref"] == "live:DAC:1"
    assert report["selected_estimate_sources"][0]["source_dac_epoch"] == 1
    assert report["comparisons"][0]["absolute_observation_difference_hz"] == 0.0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("frequency_error_hz", "1.000000000000"),
        ("frequency_observation_hz", "9999999.000000000000"),
        ("source_status_refs", "live:SNP:0:60"),
        ("source_dac_ref", "live:DAC:not-a-number"),
        ("observation_validity", "invalid"),
        ("preview_eligibility", "true"),
    ],
)
def test_diagnostic_corruption_fails_locally_without_vetoing_selected_replay(
    monkeypatch, field, value,
):
    rows = raw_measurement_rows()
    diagnostic = diagnostic_estimate(rows, estimate_seq=0)
    diagnostic[field] = value
    rows["estimates.csv"] = [diagnostic, rows["estimates.csv"][0]]

    exact, report, estimates_by_id = run_measurement(monkeypatch, rows)

    assert exact, report
    assert report["raw_measurement_exact"] is True
    assert report["estimate_replay"]["exact"] is True
    assert report["estimate_replay"]["selected_sources_exact"] is True
    assert report["diagnostic_estimate_replay"]["exact"] is False
    assert report["diagnostic_estimate_replay"]["error_count"] == 1
    assert list(estimates_by_id) == ["selected-1"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("frequency_error_hz", "1.000000000000"),
        ("frequency_observation_hz", "9999999.000000000000"),
        ("source_status_refs", "live:SNP:0:600"),
        ("source_dac_ref", "live:DAC:02"),
    ],
)
def test_selected_corruption_still_fails_decision_bearing_replay(
    monkeypatch, field, value,
):
    rows = raw_measurement_rows()
    diagnostic = diagnostic_estimate(rows, estimate_seq=0)
    rows["estimates.csv"][0][field] = value
    rows["estimates.csv"] = [diagnostic, rows["estimates.csv"][0]]

    exact, report, estimates_by_id = run_measurement(monkeypatch, rows)

    assert exact is False
    assert report["raw_measurement_exact"] is True
    assert report["estimate_replay"]["exact"] is False
    assert report["estimate_replay"]["selected_sources_exact"] is False
    assert report["diagnostic_estimate_replay"]["exact"] is True
    assert estimates_by_id == {}


def test_unknown_estimator_is_reported_and_cannot_supply_a_selected_source(monkeypatch):
    rows = raw_measurement_rows()
    unknown = diagnostic_estimate(rows, estimate_seq=0)
    unknown["estimator_version"] = "unpromoted_unknown_estimator_v1"
    unknown["estimate_id"] = "est:frequency_regulation:unknown:000000"
    rows["estimates.csv"] = [unknown]

    exact, report, estimates_by_id = run_measurement(monkeypatch, rows)

    assert exact is False
    assert report["raw_measurement_exact"] is True
    assert report["estimate_replay"]["exact"] is False
    assert report["estimate_replay"]["selected_sources_exact"] is True
    assert report["estimate_replay"]["emitted_count"] == 0
    assert report["known_estimator_versions"] == {
        "exact": False,
        "unknown_row_count": 1,
        "unknown_versions": {"unpromoted_unknown_estimator_v1": 1},
    }
    assert report["selected_estimate_sources"] == []
    assert estimates_by_id == {}


@pytest.mark.parametrize("mutation", ["sequence_gap", "identity_collision"])
def test_estimate_stream_corruption_reaches_consumed_estimate_verdict(
    monkeypatch, mutation,
):
    rows = raw_measurement_rows()
    diagnostic = diagnostic_estimate(rows, estimate_seq=0)
    selected = rows["estimates.csv"][0]
    if mutation == "sequence_gap":
        selected["estimate_seq"] = "2"
    else:
        selected["estimate_id"] = diagnostic["estimate_id"]
    rows["estimates.csv"] = [diagnostic, selected]

    exact, report, _ = run_measurement(monkeypatch, rows)

    assert exact is False
    assert report["raw_measurement_exact"] is True
    assert report["estimate_stream_integrity"]["exact"] is False
    assert report["estimate_replay"]["exact"] is False


@pytest.mark.parametrize(("decision_dac_epoch", "expected_exact"), [("1", True), ("2", False)])
def test_active_decision_binds_selected_estimate_dac_epoch(
    monkeypatch, decision_dac_epoch, expected_exact,
):
    rows = raw_measurement_rows()
    _, measurement, _ = run_measurement(monkeypatch, rows)
    decision = {
        "decision_sequence": "1",
        "capture_session": "1",
        "source_acceptance_epoch": "1",
        "source_opening_accepted_boundary_ordinal": "0",
        "source_closing_accepted_boundary_ordinal": "600",
        "frequency_estimator_sha256": "a" * 64,
        "frequency_error_hz": "0.000000000000",
        "accumulated_edge_error_counts": "0",
        "decision_timestamp_ticks": "600000123",
        "time_domain": "rp2040_monotonic_us64",
        "dac_epoch": decision_dac_epoch,
    }
    monkeypatch.setattr(replay, "_read_csv", lambda _path: [decision])
    manifest = SimpleNamespace(
        root=Path("/unused"),
        files=[{
            "contract": "active_hybrid_decisions_v3",
            "path": "active_hybrid_decisions_v3.csv",
        }],
    )

    result = replay.replay_active_decision_measurement_sources(manifest, measurement)

    assert result["exact"] is expected_exact
    assert result["joins"][0]["exact"] is expected_exact
