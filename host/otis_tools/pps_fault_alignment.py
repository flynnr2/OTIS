"""Align captured pseudo-PPS truth with REF/SNP/CNT evidence for scoring."""

from __future__ import annotations

import argparse
import csv
import json
from collections import defaultdict
from pathlib import Path
from typing import Any


TICKS_PER_US = 16
TIMESTAMP_RECONSTRUCTED = 1 << 4
REFERENCE_VALIDITY_SUSPECT = 1 << 3
GATE_INCOMPLETE = 1 << 12

EXPECTED_CLASSIFICATION = {
    "short_interval": "short_interval",
    "long_interval": "long_interval",
    "double_secondary": "double_edge",
    "bounce_secondary": "bounce_glitch",
    "narrow_glitch": "narrow_glitch",
    "positive_phase_step": "positive_phase_step",
    "negative_phase_step_safe": "negative_phase_step",
    "sustained_positive_offset": "sustained_positive_offset",
    "sustained_negative_offset": "sustained_negative_offset",
}
IGNORED_CLASSES = {"clean", "marker", "recovery", "double_primary", "bounce_primary"}


def _rows(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def classify_observed_interval(interval_us: int) -> str:
    """Classify a measured rising-edge interval without consulting PGT truth."""

    if interval_us < 10_000:
        return "bounce_glitch"
    if interval_us < 100_000:
        return "double_edge"
    if 700_000 <= interval_us < 800_000:
        return "short_interval"
    if 850_000 <= interval_us <= 950_000:
        return "negative_phase_step"
    if 998_500 <= interval_us <= 999_500:
        return "sustained_negative_offset"
    if 1_000_500 <= interval_us <= 1_001_500:
        return "sustained_positive_offset"
    if 1_050_000 <= interval_us <= 1_150_000:
        return "positive_phase_step"
    if 1_200_000 < interval_us <= 1_300_000:
        return "long_interval"
    if 1_900_000 <= interval_us <= 2_100_000:
        return "likely_missed_1_pps"
    if 2_900_000 <= interval_us <= 3_100_000:
        return "likely_missed_2_pps"
    return "nominal"


def _snapshot_assessment(
    event_id: str,
    snapshot: dict[str, str],
    count: dict[str, str] | None,
) -> dict[str, Any]:
    flags = int(count["flags"]) if count is not None else GATE_INCOMPLETE
    invalid = bool(flags & (REFERENCE_VALIDITY_SUSPECT | GATE_INCOMPLETE))
    reasons: list[str] = []
    if flags & REFERENCE_VALIDITY_SUSPECT:
        reasons.append("reference_interval_outlier")
    if flags & GATE_INCOMPLETE:
        reasons.append("gate_incomplete")
    if count is None:
        reasons.append("count_observation_missing")
    return {
        "event_id": event_id,
        "snapshot_sequence": int(snapshot["snapshot_sequence"]),
        "measurement_valid": not invalid,
        "reasons": reasons,
    }


def align_fault_run(run_dir: Path) -> dict[str, Any]:
    csv_dir = run_dir / "csv"
    truth_rows = _rows(csv_dir / "pseudo_pps_truth.csv")
    refs = [
        row for row in _rows(csv_dir / "raw_events.csv")
        if row["record_type"] == "REF"
    ]
    snapshots = _rows(csv_dir / "pps_snapshots.csv")
    counts = _rows(csv_dir / "count_observations.csv")
    count_by_close = {int(row["gate_close_ticks"]): row for row in counts}

    schedules: dict[int, list[dict[str, str]]] = defaultdict(list)
    profiles: dict[int, str] = {}
    for row in truth_rows:
        session = int(row["generator_session"])
        profiles[session] = row["profile_id"]
        if row["event"] == "schedule":
            schedules[session].append(row)

    aligned_sessions: list[dict[str, Any]] = []
    cursor = 0
    for session in sorted(schedules):
        steps = schedules[session]
        emitted = [row for row in steps if int(row["pulse_width_us"]) > 0]
        observed_refs = refs[cursor : cursor + len(emitted)]
        observed_snapshots = snapshots[cursor : cursor + len(emitted)]
        if len(observed_refs) != len(emitted) or len(observed_snapshots) != len(emitted):
            raise ValueError(
                f"session {session} {profiles[session]} expected {len(emitted)} "
                "physical pulses but capture ended early"
            )
        ref_by_sequence = {
            int(step["generator_sequence"]): reference
            for step, reference in zip(emitted, observed_refs, strict=True)
        }
        snapshot_by_sequence = {
            int(step["generator_sequence"]): snapshot
            for step, snapshot in zip(emitted, observed_snapshots, strict=True)
        }
        emitted_sequences = [int(row["generator_sequence"]) for row in emitted]
        first_offset = int(emitted[0]["scheduled_offset_us"])
        session_start_ticks = int(observed_refs[0]["timestamp_ticks"]) - (
            first_offset * TICKS_PER_US
        )
        aligned_sessions.append(
            {
                "session": session,
                "profile_id": profiles[session],
                "steps": steps,
                "emitted_sequences": emitted_sequences,
                "ref_by_sequence": ref_by_sequence,
                "snapshot_by_sequence": snapshot_by_sequence,
                "session_start_ticks": session_start_ticks,
            }
        )
        cursor += len(emitted)
    if cursor != len(refs) or cursor != len(snapshots):
        raise ValueError(
            f"aligned {cursor} physical pulses but capture contains "
            f"{len(refs)} REF and {len(snapshots)} SNP rows"
        )

    truth: list[dict[str, Any]] = []
    detections: list[dict[str, Any]] = []
    validity: list[dict[str, Any]] = []
    event_number = 0

    for aligned in aligned_sessions:
        steps = aligned["steps"]
        emitted_sequences = aligned["emitted_sequences"]
        ref_by_sequence = aligned["ref_by_sequence"]
        snapshot_by_sequence = aligned["snapshot_by_sequence"]
        profile_id = aligned["profile_id"]
        session = int(aligned["session"])
        sequence_to_position = {
            sequence: position for position, sequence in enumerate(emitted_sequences)
        }
        index = 0
        while index < len(steps):
            step = steps[index]
            intended = step["intended_class"]
            sequence = int(step["generator_sequence"])
            expected: str | None = None
            target_sequence: int | None = None

            if int(step["pulse_width_us"]) == 0:
                omitted_count = 1
                while (
                    index + omitted_count < len(steps)
                    and int(steps[index + omitted_count]["pulse_width_us"]) == 0
                ):
                    omitted_count += 1
                next_index = index + omitted_count
                if next_index >= len(steps):
                    raise ValueError(f"terminal omission in session {session}")
                target_sequence = int(steps[next_index]["generator_sequence"])
                expected = f"likely_missed_{omitted_count}_pps"
                index = next_index
            elif intended in EXPECTED_CLASSIFICATION:
                target_sequence = sequence
                expected = EXPECTED_CLASSIFICATION[intended]
            elif intended not in IGNORED_CLASSES:
                raise ValueError(f"unhandled intended class {intended!r}")

            if expected is not None and target_sequence is not None:
                position = sequence_to_position[target_sequence]
                # The first physical pulse in a session is an anchor, so an
                # absolute sustained offset is not detectable until pulse two.
                if position == 0:
                    index += 1
                    continue
                target_ref = ref_by_sequence[target_sequence]
                previous_ref = ref_by_sequence[emitted_sequences[position - 1]]
                target_snapshot = snapshot_by_sequence[target_sequence]
                interval_us = (
                    int(target_ref["timestamp_ticks"])
                    - int(previous_ref["timestamp_ticks"])
                ) // TICKS_PER_US
                observed = classify_observed_interval(interval_us)
                event_number += 1
                event_id = f"fault-{event_number:03d}-s{session}-q{sequence}"
                truth.append(
                    {
                        "event_id": event_id,
                        "generator_session": str(session),
                        "generator_sequence": sequence,
                        "profile_id": profile_id,
                        "profile_version": int(step["profile_version"]),
                        "kind": "fault",
                        "expected_classification": expected,
                        "scheduled_timestamp_ticks": int(aligned["session_start_ticks"])
                        + int(step["scheduled_offset_us"]) * TICKS_PER_US,
                        "time_domain": target_ref["capture_domain"],
                    }
                )
                if observed != "nominal":
                    detections.append(
                        {
                            "detection_id": f"detection-{event_number:03d}",
                            "event_id": event_id,
                            "classification": observed,
                            "reference_sequence": int(target_ref["event_seq"]),
                            "timestamp_ticks": int(target_ref["timestamp_ticks"]),
                            "time_domain": target_ref["capture_domain"],
                        }
                    )
                close_ticks = int(target_ref["timestamp_ticks"])
                validity.append(
                    _snapshot_assessment(
                        event_id,
                        target_snapshot,
                        count_by_close.get(close_ticks),
                    )
                )
            index += 1

    invalid = sum(not row["measurement_valid"] for row in validity)
    return {
        "schema_version": 1,
        "truth": truth,
        "physical_detections": detections,
        "snapshot_validity": validity,
        "diagnostics": [],
        "alignment_summary": {
            "generator_session_count": len(aligned_sessions),
            "scheduled_step_count": sum(len(item["steps"]) for item in aligned_sessions),
            "physical_reference_count": len(refs),
            "snapshot_count": len(snapshots),
            "count_observation_count": len(counts),
            "expected_fault_event_count": len(truth),
            "classified_fault_event_count": len(detections),
            "invalidated_fault_measurement_count": invalid,
            "valid_fault_measurement_count": len(validity) - invalid,
        },
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Align pseudo-PPS PGT, REF, SNP, and CNT evidence for scoring."
    )
    parser.add_argument("run_dir", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    aligned = align_fault_run(args.run_dir)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(aligned, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(aligned["alignment_summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
