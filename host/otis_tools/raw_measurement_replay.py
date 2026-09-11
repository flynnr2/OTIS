"""Pure D14 REF/SNP-to-CNT reconstruction shared by live and offline consumers.

This layer owns raw association, counter domains, and aperture arithmetic. It
has no recorder, manifest, frontier, campaign, controller, or sealing policy.
"""
from __future__ import annotations

from typing import Any

from .time_domains import forward_progress

SELECTED_ESTIMATOR_ID = "OTIS_PPS_GATED_FREQUENCY_ESTIMATOR_V1"

# Current pps_snapshots_v1 backend and fixed firmware profile.  SNP status is
# transport status, not OtisFlagsV1.  Its counter domain is inherited from the
# backend; its reference coordinate is inherited from the SNP wire contract.
_SNAPSHOT_BACKEND = "pio_wait_cumulative_snapshot_dma_v1"
_RAW_REFERENCE_DOMAIN = "rp2040_monotonic_us32"
_U32_MODULUS = 1 << 32
_PPS_MIN_INTERVAL_US = 800_000
_PPS_MAX_INTERVAL_US = 1_200_000
_MAXIMUM_WINDOW_EDGES = 133_000_000 * _PPS_MAX_INTERVAL_US // 1_000_000
_REFERENCE_INVALID_FLAGS = 0x1FFF & ~(1 << 4)


def _u32(row: dict[str, str], field: str) -> int:
    value = int(row[field])
    if not 0 <= value < _U32_MODULUS:
        raise ValueError(f"{field} is outside uint32")
    return value


def _ordered_reference_association(
    snapshots: list[dict[str, str]], references: list[dict[str, str]],
) -> list[int]:
    """Find the unique ordered REF occurrence for every SNP timestamp.

    Wire event numbers and D14 source ordinals are independent. Within one
    session, consecutive SNP source ordinals require consecutive D14 records.
    Match whole session patterns, so repeated low32 ticks after rollover do
    not become global identities. Prefix/suffix REF rows may be unassociated.
    """
    blocks: list[list[int]] = []
    previous_session = None
    for row in snapshots:
        session = _u32(row, "session")
        if session != previous_session:
            blocks.append([])
        blocks[-1].append(_u32(row, "reference_timestamp_ticks"))
        previous_session = session
    reference_ticks = [_u32(row, "timestamp_ticks") for row in references]
    placements: list[list[int]] = []
    for pattern in blocks:
        # Linear pattern matching avoids quadratic scans on repeated ticks.
        prefix = [0] * len(pattern)
        matched = 0
        for index in range(1, len(pattern)):
            while matched and pattern[index] != pattern[matched]:
                matched = prefix[matched - 1]
            matched += pattern[index] == pattern[matched]
            prefix[index] = matched
        starts = []
        matched = 0
        for index, ticks in enumerate(reference_ticks):
            while matched and ticks != pattern[matched]:
                matched = prefix[matched - 1]
            matched += ticks == pattern[matched]
            if matched == len(pattern):
                starts.append(index + 1 - len(pattern))
                matched = prefix[matched - 1]
        placements.append(starts)
    earliest = []
    frontier = 0
    for pattern, starts in zip(blocks, placements):
        start = next((value for value in starts if value >= frontier), None)
        if start is None:
            raise ValueError("SNP has missing or out-of-order D14 REF association")
        earliest.append(start)
        frontier = start + len(pattern)
    latest = []
    frontier = len(references)
    for pattern, starts in reversed(list(zip(blocks, placements))):
        start = next((value for value in reversed(starts) if value + len(pattern) <= frontier), None)
        if start is None:
            raise ValueError("SNP has missing or out-of-order D14 REF association")
        latest.append(start)
        frontier = start
    if earliest != list(reversed(latest)):
        raise ValueError("SNP timestamp occurrence has ambiguous D14 REF association")
    return [index for start, pattern in zip(earliest, blocks)
            for index in range(start, start + len(pattern))]


def _raw_count_replay(
    snapshots: list[dict[str, str]], references: list[dict[str, str]],
    counts: list[dict[str, str]],
) -> tuple[bool, dict[str, Any], list[dict[str, Any]]]:
    """Reconstruct current firmware CNT records from immutable SNP/REF rows.

    This verifies arithmetic, association and observable aperture exclusions.
    It does not recreate GNSS qualification, settling, or hardware capture.
    Ambiguous pair identities and absent records fail this replay locally.
    """
    errors: list[str] = []
    intervals: list[dict[str, Any]] = []
    count_index: dict[tuple[int, int, int], dict[str, str]] = {}
    seen_snapshots: set[tuple[int, int]] = set()
    consumed_counts: set[tuple[int, int, int]] = set()
    count_order: list[tuple[int, int, int]] = []
    previous_reference_sequence: int | None = None
    used_references: set[int] = set()
    previous_reference_index: int | None = None
    closed_sessions: set[int] = set()
    wraps = 0
    previous: dict[str, str] | None = None
    previous_boundary_inhibited = False
    try:
        for row in references:
            key = (_u32(row, "event_seq"), _u32(row, "timestamp_ticks"))
            # event_seq spans REF and optional EVT emissions. Its declared
            # capture-segment domain forbids wrap, but permits unrelated gaps.
            if previous_reference_sequence is not None and key[0] <= previous_reference_sequence:
                raise ValueError("REF sequence duplicate/reordering or inadmissible wrap")
            previous_reference_sequence = key[0]
            if (row["record_type"], row["channel_id"], row["edge"], row["capture_domain"]) != (
                "REF", "1", "R", _RAW_REFERENCE_DOMAIN
            ):
                raise ValueError("REF channel, edge or domain differs from current D14 producer")
            _u32(row, "flags")
        for row in counts:
            key = (_u32(row, "count_seq"), _u32(row, "gate_open_ticks"), _u32(row, "gate_close_ticks"))
            if key in count_index:
                raise ValueError("duplicate CNT identity")
            if (row["record_type"], row["channel_id"], row["source_edge"], row["gate_domain"], row["source_domain"]) != (
                "CNT", "2", "R", _RAW_REFERENCE_DOMAIN, "h1_oscillator_10mhz"
            ):
                raise ValueError("CNT channel, edge or domain differs from current D14/D8 producer")
            _u32(row, "counted_edges")
            _u32(row, "flags")
            count_index[key] = row
        association = _ordered_reference_association(snapshots, references)
        for row, reference_index in zip(snapshots, association):
            session = _u32(row, "session")
            sequence = _u32(row, "snapshot_sequence")
            reference_key = (_u32(row, "reference_sequence"), _u32(row, "reference_timestamp_ticks"))
            _u32(row, "cumulative_down_counter")
            status = _u32(row, "status")
            if row["record_type"] != "SNP" or row["backend"] != _SNAPSHOT_BACKEND:
                raise ValueError("unsupported SNP counter backend/domain")
            if status & ~1:
                # Fatal backend statuses stop production; do not invent a
                # usable aperture for a contradictory or unknown status.
                raise ValueError("unsupported or fatal SNP transport status")
            if (session, sequence) in seen_snapshots:
                raise ValueError("duplicate SNP session/sequence")
            seen_snapshots.add((session, sequence))
            used_references.add(reference_index)
            if previous is None or session != int(previous["session"]):
                if session in closed_sessions:
                    raise ValueError("SNP returns to a closed session")
                if previous is not None:
                    closed_sessions.add(int(previous["session"]))
                previous = row
                previous_reference_index = reference_index
                previous_boundary_inhibited = False
                continue  # A session's first retained pair is only an anchor.
            opening_sequence = int(previous["snapshot_sequence"])
            opening_reference = int(previous["reference_sequence"])
            if sequence != (opening_sequence + 1) % _U32_MODULUS or reference_key[0] != (opening_reference + 1) % _U32_MODULUS:
                raise ValueError("SNP or associated REF sequence gap/reordering")
            opening_ticks = int(previous["reference_timestamp_ticks"])
            closing_ticks = reference_key[1]
            progress = forward_progress(opening_ticks, closing_ticks, domain=_RAW_REFERENCE_DOMAIN)
            if not progress.valid or progress.distance_ticks is None:
                raise ValueError(f"ambiguous D14 timestamp progression: {progress.reason}")
            old_x = int(previous["cumulative_down_counter"])
            new_x = int(row["cumulative_down_counter"])
            delta = (old_x - new_x) % _U32_MODULUS
            counter_unambiguous = delta <= _MAXIMUM_WINDOW_EDGES
            wraps += int(new_x > old_x and counter_unambiguous)
            assert previous_reference_index is not None
            reference_flags = int(references[previous_reference_index]["flags"]) | int(references[reference_index]["flags"])
            if reference_flags & ~0xFFFF:
                raise ValueError("unknown REF flags")
            raw_boundary_valid = (
                not reference_flags & _REFERENCE_INVALID_FLAGS
                and _PPS_MIN_INTERVAL_US <= progress.distance_ticks <= _PPS_MAX_INTERVAL_US
            )
            boundary_valid = raw_boundary_valid and not previous_boundary_inhibited
            expected_flags = reference_flags
            if status & 1:
                expected_flags |= (1 << 1) | (1 << 12)
            if delta == 0:
                expected_flags |= (1 << 5) | (1 << 9)
            # Mirror emitted flags, but independently reject every excessive
            # delta, including the producer's unflagged non-wrap large delta.
            if new_x > old_x and not counter_unambiguous:
                expected_flags |= (1 << 5) | (1 << 12)
            if not boundary_valid:
                expected_flags |= (1 << 3) | (1 << 12)
            key = (sequence, opening_ticks, closing_ticks)
            count = count_index.get(key)
            count_exact = count is not None and int(count["counted_edges"]) == delta and int(count["flags"]) == expected_flags
            if key in consumed_counts:
                raise ValueError("CNT pair identity is ambiguous across sessions")
            consumed_counts.add(key)
            count_order.append(key)
            if not count_exact:
                errors.append(f"CNT {sequence} does not reproduce SNP/REF arithmetic, endpoints or flags")
            intervals.append({
                "session": session, "opening_sequence": opening_sequence,
                "closing_sequence": sequence, "closing_ticks": closing_ticks,
                "counted_edges": delta, "count_exact": count_exact,
                "measurement_valid": bool(boundary_valid and not status and delta > 0 and counter_unambiguous),
            })
            previous_boundary_inhibited = not raw_boundary_valid
            previous = row
            previous_reference_index = reference_index
        if count_order != list(count_index):
            errors.append("CNT order differs from raw aperture order")
        if consumed_counts != set(count_index):
            errors.append("CNT records lack a unique adjacent same-session SNP/REF pair")
    except (KeyError, TypeError, ValueError) as error:
        errors.append(str(error))
    exact = not errors and bool(intervals)
    return exact, {
        "exact": exact, "counter_domain": "uint32_cumulative_down_counter_modulo_2^32",
        "backend": _SNAPSHOT_BACKEND, "reference_domain": _RAW_REFERENCE_DOMAIN,
        "interval_count": len(intervals), "counter_wrap_count": wraps,
        "unassociated_reference_count": len(references) - len(used_references),
        "capture_completeness_claimed": False,
        "invalid_aperture_count": sum(not item["measurement_valid"] for item in intervals),
        "errors": errors[:20], "error_count": len(errors),
        "scope": "raw_association_count_arithmetic_and_observable_aperture_validity",
    }, intervals
