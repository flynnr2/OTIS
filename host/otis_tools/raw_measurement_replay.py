"""Pure D14 REF/SNP-to-CNT reconstruction shared by live and offline consumers.

This layer owns single-owner raw identity, counter domains, and aperture arithmetic. It
has no recorder, manifest, frontier, campaign, controller, or sealing policy.
"""
from __future__ import annotations

from typing import Any

from .time_domains import forward_progress

SELECTED_ESTIMATOR_ID = "OTIS_PPS_GATED_FREQUENCY_ESTIMATOR_V1"

# Current pps_snapshots_v2 backend and fixed firmware profile.  SNP status is
# transport status, not OtisFlagsV1.  Its counter domain is inherited from the
# backend; its reference coordinate is inherited from the SNP wire contract.
_SNAPSHOT_BACKEND = "pio_wait_cumulative_snapshot_fifo_irq_v2"
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


def _ordered_reference_derivative_audit(
    snapshots: list[dict[str, str]], references: list[dict[str, str]],
) -> list[int]:
    """Audit the retained REF presentation of each single-owner SNP.

    REF serial event numbers remain independent. Whole-session pattern matching
    handles recorder prefixes and suffixes without feeding REF placement into
    SNP interval selection or qualification.
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
            raise ValueError("SNP has missing or out-of-order REF derivative placement")
        earliest.append(start)
        frontier = start + len(pattern)
    latest = []
    frontier = len(references)
    for pattern, starts in reversed(list(zip(blocks, placements))):
        start = next((value for value in reversed(starts) if value + len(pattern) <= frontier), None)
        if start is None:
            raise ValueError("SNP has missing or out-of-order REF derivative placement")
        latest.append(start)
        frontier = start
    if earliest != list(reversed(latest)):
        raise ValueError("SNP timestamp occurrence has ambiguous REF derivative placement")
    return [index for start, pattern in zip(earliest, blocks)
            for index in range(start, start + len(pattern))]


def _raw_count_replay(
    snapshots: list[dict[str, str]], references: list[dict[str, str]],
    counts: list[dict[str, str]],
) -> tuple[bool, dict[str, Any], list[dict[str, Any]]]:
    """Reconstruct SNP v2/CNT evidence without giving REF a second authority.

    SNP owns the PIO word, identity, FIFO service coordinate and uncertainty.
    REF is audited as the immutable same-owner derivative; it is not searched
    to decide which snapshot belongs to a reference candidate.
    """
    source_errors: list[str] = []
    reference_errors: list[str] = []
    intervals: list[dict[str, Any]] = []
    count_index: dict[tuple[int, int, int], dict[str, str]] = {}
    seen_snapshots: set[tuple[int, int]] = set()
    consumed_counts: set[tuple[int, int, int]] = set()
    count_order: list[tuple[int, int, int]] = []
    closed_sessions: set[int] = set()
    wraps = 0
    previous: dict[str, str] | None = None
    previous_boundary_inhibited = False

    try:
        previous_event_sequence: int | None = None
        for row in references:
            event_sequence = _u32(row, "event_seq")
            if previous_event_sequence is not None and event_sequence <= previous_event_sequence:
                raise ValueError("REF sequence duplicate/reordering or inadmissible wrap")
            previous_event_sequence = event_sequence
            if (row["record_type"], row["channel_id"], row["edge"], row["capture_domain"]) != (
                "REF", "1", "R", _RAW_REFERENCE_DOMAIN
            ):
                raise ValueError("REF channel, edge or domain differs from current D14 producer")
            if _u32(row, "flags") != 1 << 4:
                raise ValueError("REF derivative flags differ from the current producer")
            _u32(row, "timestamp_ticks")
    except (KeyError, TypeError, ValueError) as error:
        reference_errors.append(str(error))

    try:
        # REF is a serial-format derivative of SNP.  Audit it after parsing the
        # authoritative SNP stream, without feeding it into interval selection.
        association = _ordered_reference_derivative_audit(snapshots, references)
        for snapshot, reference_index in zip(snapshots, association):
            if _u32(snapshot, "reference_timestamp_ticks") != _u32(
                references[reference_index], "timestamp_ticks"
            ):
                raise ValueError("REF derivative timestamp differs from SNP service coordinate")
    except (KeyError, TypeError, ValueError) as error:
        reference_errors.append(str(error))

    try:
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

        for row in snapshots:
            session = _u32(row, "session")
            sequence = _u32(row, "snapshot_sequence")
            reference_sequence = _u32(row, "reference_sequence")
            service_ticks = _u32(row, "reference_timestamp_ticks")
            uncertainty = _u32(row, "timestamp_uncertainty_ticks")
            _u32(row, "cumulative_down_counter")
            status = _u32(row, "status")
            if row.get("record_type") != "SNP" or row.get("schema_version") != "2":
                raise ValueError("unsupported SNP record contract")
            if row.get("backend") != _SNAPSHOT_BACKEND:
                raise ValueError("unsupported SNP counter backend/domain")
            if reference_sequence != sequence:
                raise ValueError("SNP reference_sequence differs from its single-owner ordinal")
            if status & ~0x1F:
                raise ValueError("SNP status uses unknown v2 bits")
            if (uncertainty == 0xFFFFFFFF) != bool(status & (1 << 1)):
                raise ValueError("SNP unbounded timestamp status and uncertainty disagree")
            if (session, sequence) in seen_snapshots:
                raise ValueError("duplicate SNP session/sequence")
            seen_snapshots.add((session, sequence))
            if previous is None or session != int(previous["session"]):
                if session in closed_sessions:
                    raise ValueError("SNP returns to a closed session")
                if previous is not None:
                    closed_sessions.add(int(previous["session"]))
                previous = row
                previous_boundary_inhibited = False
                continue
            opening_sequence = int(previous["snapshot_sequence"])
            if sequence != (opening_sequence + 1) % _U32_MODULUS:
                raise ValueError("SNP sequence gap/reordering")
            opening_ticks = int(previous["reference_timestamp_ticks"])
            progress = forward_progress(opening_ticks, service_ticks, domain=_RAW_REFERENCE_DOMAIN)
            if not progress.valid or progress.distance_ticks is None:
                raise ValueError(f"ambiguous SNP service-coordinate progression: {progress.reason}")
            service_delta = progress.distance_ticks
            opening_uncertainty = int(previous["timestamp_uncertainty_ticks"])
            interval_min = service_delta - uncertainty
            interval_max = service_delta + opening_uncertainty
            timing_status = status & 0x3
            transport_status = status & ~0x3
            age_ambiguous = (
                timing_status != 0
                or uncertainty >= (1 << 31)
                or opening_uncertainty >= (1 << 31)
            )
            old_x = int(previous["cumulative_down_counter"])
            new_x = int(row["cumulative_down_counter"])
            delta = (old_x - new_x) % _U32_MODULUS
            counter_unambiguous = delta <= _MAXIMUM_WINDOW_EDGES
            wraps += int(new_x > old_x and counter_unambiguous)
            # CNT is a service-coordinate diagnostic with the wider raw gate
            # bounds.  SNP uncertainty participates in reference selection,
            # but does not turn this diagnostic into a reconstructed latch.
            raw_boundary_valid = (
                service_delta >= _PPS_MIN_INTERVAL_US
                and service_delta <= _PPS_MAX_INTERVAL_US
            )
            count_boundary_valid = timing_status == 0
            counter_snapshot_valid = transport_status == 0
            boundary_valid = raw_boundary_valid and not previous_boundary_inhibited
            expected_flags = 1 << 4
            if status:
                expected_flags |= (1 << 5) | (1 << 12)
            if delta == 0:
                expected_flags |= (1 << 5) | (1 << 9)
            if new_x > old_x and not counter_unambiguous:
                expected_flags |= (1 << 5) | (1 << 12)
            if not boundary_valid:
                expected_flags |= (1 << 3) | (1 << 12)
            key = (sequence, opening_ticks, service_ticks)
            count = count_index.get(key)
            count_exact = count is not None and int(count["counted_edges"]) == delta and int(count["flags"]) == expected_flags
            if key in consumed_counts:
                raise ValueError("CNT pair identity is ambiguous across sessions")
            consumed_counts.add(key)
            count_order.append(key)
            if not count_exact:
                source_errors.append(f"CNT {sequence} does not reproduce SNP arithmetic, endpoints or flags")
            intervals.append({
                "session": session,
                "opening_sequence": opening_sequence,
                "closing_sequence": sequence,
                "closing_ticks": service_ticks,
                "counted_edges": delta,
                "count_exact": count_exact,
                "service_delta_ticks": service_delta,
                "interval_min_ticks": interval_min,
                "interval_max_ticks": interval_max,
                "observation_age_ambiguous": age_ambiguous,
                "measurement_valid": bool(
                    boundary_valid
                    and count_boundary_valid
                    and counter_snapshot_valid
                    and delta > 0
                    and counter_unambiguous
                ),
            })
            previous_boundary_inhibited = (
                not raw_boundary_valid or not count_boundary_valid
            )
            previous = row
        if count_order != list(count_index):
            source_errors.append("CNT order differs from raw aperture order")
        if consumed_counts != set(count_index):
            source_errors.append("CNT records lack a unique adjacent same-session SNP pair")
    except (KeyError, TypeError, ValueError) as error:
        source_errors.append(str(error))

    source_exact = not source_errors and bool(intervals)
    reference_exact = not reference_errors
    errors = source_errors + reference_errors
    exact = source_exact and reference_exact
    return exact, {
        "exact": exact,
        "source_exact": source_exact,
        "reference_derivative_exact": reference_exact,
        "counter_domain": "uint32_cumulative_down_counter_modulo_2^32",
        "backend": _SNAPSHOT_BACKEND,
        "reference_domain": _RAW_REFERENCE_DOMAIN,
        "reference_timestamp_semantics": "fifo_cpu_service_coordinate",
        "interval_count": len(intervals),
        "counter_wrap_count": wraps,
        "unassociated_reference_count": max(0, len(references) - len(snapshots)),
        "capture_completeness_claimed": False,
        "invalid_aperture_count": sum(not item["measurement_valid"] for item in intervals),
        "errors": errors[:20],
        "error_count": len(errors),
        "scope": "single_owner_snapshot_count_arithmetic_service_interval_and_ref_derivative_integrity",
    }, intervals
