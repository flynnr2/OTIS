"""Shared replay primitives for the measurement records emitted by CX319.

The ``cx317_*`` values below are deployed wire identities.  They remain
unchanged so current sealed evidence can be replayed exactly.
"""

from __future__ import annotations

from dataclasses import dataclass

from .pps_cumulative_span_estimator import (
    COUNT_INVALID_FLAGS,
    REFERENCE_INVALID_FLAGS,
)


TICKS_PER_SECOND = 16_000_000
SERIALIZED_12_DECIMAL_HALF_UNIT = 5e-13
EXPECTED_BACKEND = "pio_wait_cumulative_snapshot_dma_v1"
EXPECTED_DIAGNOSTIC_VERSION = "cx317_diagnostic_60s_overlap_v1"
EXPECTED_SELECTED_VERSION = "cx317_selected_600s_nonoverlap_v1"


@dataclass(frozen=True)
class Check:
    identifier: str
    passed: bool
    evidence: str


def check_continuity(
    counts: list[dict[str, str]],
    snapshots: list[dict[str, str]],
    references: list[dict[str, str]],
) -> tuple[list[Check], dict[int, dict[str, str]]]:
    """Check sequence and raw SNP/CNT parity without translating wire data."""

    if not counts or not snapshots:
        return [Check("measurement_continuity", False, "empty evidence")], {}
    checks: list[Check] = []
    count_sequences = [int(row["count_seq"]) for row in counts]
    snapshot_sequences = [int(row["snapshot_sequence"]) for row in snapshots]
    expected_counts = list(range(count_sequences[0], count_sequences[-1] + 1))
    expected_snapshots = list(
        range(snapshot_sequences[0], snapshot_sequences[-1] + 1)
    )
    checks.append(Check(
        "count_sequence_continuity",
        count_sequences == expected_counts,
        f"observed {count_sequences[0]}..{count_sequences[-1]} / {len(count_sequences)} rows",
    ))
    checks.append(Check(
        "snapshot_sequence_continuity",
        snapshot_sequences == expected_snapshots,
        f"observed {snapshot_sequences[0]}..{snapshot_sequences[-1]} / {len(snapshot_sequences)} rows",
    ))
    count_by_seq = {int(row["count_seq"]): row for row in counts}
    snapshot_by_seq = {int(row["snapshot_sequence"]): row for row in snapshots}
    reference_timestamps = {
        int(row["timestamp_ticks"])
        for row in references
        if row["record_type"] == "REF"
        and row["edge"] == "R"
        and int(row["channel_id"]) == 1
    }
    valid = True
    mismatch_count = 0
    for sequence, closing in snapshot_by_seq.items():
        if int(closing["status"]) != 0 or closing["backend"] != EXPECTED_BACKEND:
            valid = False
        if int(closing["reference_timestamp_ticks"]) not in reference_timestamps:
            valid = False
        opening = snapshot_by_seq.get(sequence - 1)
        count = count_by_seq.get(sequence)
        if opening is None or count is None:
            continue
        reconstructed = (
            int(opening["cumulative_down_counter"])
            - int(closing["cumulative_down_counter"])
        ) & 0xFFFFFFFF
        if reconstructed != int(count["counted_edges"]):
            mismatch_count += 1
        if int(count["flags"]) & COUNT_INVALID_FLAGS:
            valid = False
    if any(int(row["flags"]) & REFERENCE_INVALID_FLAGS for row in references):
        valid = False
    checks.append(Check(
        "raw_snapshot_count_parity",
        valid and mismatch_count == 0,
        f"{mismatch_count} adjacent SNP/CNT mismatches; backend={EXPECTED_BACKEND}",
    ))
    return checks, count_by_seq
