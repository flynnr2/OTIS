"""Offline measurement, response, capsule, and D10-isolation replay helpers."""

from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any


SELECTED_ESTIMATOR_ID = "OTIS_PPS_GATED_FREQUENCY_ESTIMATOR_V1"
SERIALIZED_12_DECIMAL_HALF_UNIT = Decimal("0.0000000000005")


def _read_csv(path: Path) -> list[dict[str, str]]:
    if not path.is_file():
        return []
    with path.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _contract_paths(manifest: Any, contract: str) -> list[Path]:
    return [
        manifest.root / item["path"]
        for item in manifest.files
        if item.get("contract") == contract
    ]


def _single_contract_path(manifest: Any, contract: str) -> Path:
    paths = _contract_paths(manifest, contract)
    if len(paths) != 1:
        raise ValueError(f"expected one {contract} artifact, got {len(paths)}")
    return paths[0]


def _raw_event_path(manifest: Any, record_type: str) -> Path:
    entries = [
        item
        for item in manifest.files
        if item.get("contract") == "raw_events_v1"
        and item.get("record_type") == record_type
    ]
    if len(entries) != 1:
        raise ValueError(f"expected one {record_type} raw-event artifact")
    return manifest.root / entries[0]["path"]


def _selected_frequency_estimator_sha256(manifest_value: dict[str, Any]) -> str:
    transaction_identities = manifest_value.get("transaction_identities", {})
    frozen = (
        transaction_identities.get("estimator_sha256")
        if isinstance(transaction_identities, dict)
        else None
    )
    if not isinstance(frozen, str) or len(frozen) != 64:
        raise ValueError("frozen frequency-estimator identity is unavailable")
    try:
        int(frozen, 16)
    except ValueError as error:
        raise ValueError("frozen frequency-estimator identity is malformed") from error
    return frozen


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
    from .time_domains import forward_progress

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


def _measurement_replay(
    manifest: Any,
    manifest_value: dict[str, Any],
) -> tuple[bool, dict[str, Any], dict[str, dict[str, str]]]:
    """Recompute D14-gated D8 frequency estimates; retain D10 separately."""
    counts = _read_csv(_single_contract_path(manifest, "count_observations_v1"))
    snapshots = _read_csv(_single_contract_path(manifest, "pps_snapshots_v1"))
    references = _read_csv(_raw_event_path(manifest, "REF"))
    d10_local_error: str | None = None
    try:
        external_events = _read_csv(_raw_event_path(manifest, "EVT"))
    except (OSError, UnicodeError, csv.Error) as error:
        external_events = []
        d10_local_error = f"{type(error).__name__}: {error}"
    estimates = _read_csv(_single_contract_path(manifest, "estimates_v2"))
    d10_channel_exact = d10_local_error is None and all(
        row.get("record_type") == "EVT" and row.get("channel_id") == "0"
        for row in external_events
    )
    d14_channel_exact = bool(references) and all(
        row.get("record_type") == "REF" and row.get("channel_id") == "1"
        for row in references
    )
    if not counts or not snapshots or not references or not estimates:
        return False, {
            "reason": "D14/D8 measurement replay source is empty",
            "D10": {
                "row_count": len(external_events),
                "channel_exact": d10_channel_exact,
                "local_error": d10_local_error,
            },
        }, {}
    expected_hash = _selected_frequency_estimator_sha256(manifest_value)
    raw_exact, raw_report, raw_intervals = _raw_count_replay(snapshots, references, counts)
    estimate_sequences = [_u32(row, "estimate_seq") for row in estimates]
    sequence_exact = all(
        current == (previous + 1) % _U32_MODULUS
        for previous, current in zip(estimate_sequences, estimate_sequences[1:])
    )
    raw_closings: dict[tuple[int, int], list[int]] = {}
    for index, interval in enumerate(raw_intervals):
        raw_closings.setdefault((interval["closing_sequence"], interval["closing_ticks"]), []).append(index)
    exact = sequence_exact and d14_channel_exact and raw_exact
    identifiers: set[str] = set()
    selected_windows: list[tuple[int, int]] = []
    comparisons: list[dict[str, Any]] = []
    selected_estimate_sources: list[dict[str, Any]] = []
    estimates_by_id: dict[str, dict[str, str]] = {}
    for row in estimates:
        identifier = row["estimate_id"]
        unique = identifier not in identifiers
        identifiers.add(identifier)
        estimates_by_id[identifier] = row
        exact &= unique
        if row.get("estimator_version") != SELECTED_ESTIMATOR_ID:
            continue
        first = int(row["source_reference_first_seq"])
        last = int(row["source_reference_last_seq"])
        # EST's source_reference_* names carry SNP boundary sequences in the
        # current firmware. Its exact closing timestamp disambiguates rearm.
        closing_ticks = row.get("estimator_timestamp_ticks", "")
        candidates = raw_closings.get((last, int(closing_ticks)), []) if closing_ticks.isdecimal() else []
        # Retained source positions express non-overlap across both counter
        # rollover and session rearm, without comparing unrelated sequences.
        selected_windows.append((candidates[0] - 599, candidates[0] + 1) if len(candidates) == 1 else (-1, -1))
        sources = []
        if len(candidates) == 1 and candidates[0] >= 599:
            sources = raw_intervals[candidates[0] - 599:candidates[0] + 1]
        source_exact = (
            len(sources) == 600
            and row.get("time_domain") == _RAW_REFERENCE_DOMAIN
            and sources[0]["opening_sequence"] == first
            and len({item["session"] for item in sources}) == 1
            and all(item["count_exact"] and item["measurement_valid"] for item in sources)
        )
        if source_exact:
            total = sum(item["counted_edges"] for item in sources)
            # The selected firmware estimator performs both operations in its
            # declared binary64 implementation domain before serializing each
            # result to 12 decimal places.  Replaying the rational quotient
            # instead invents precision that the producer never possessed at
            # a 10 MHz magnitude (and can reject its separately computed error
            # even when the source edge total is exact).
            frequency_binary64 = float(total) / 600.0
            error_binary64 = frequency_binary64 - 10_000_000.0
            frequency = Decimal.from_float(frequency_binary64)
            error = Decimal.from_float(error_binary64)
            frequency_difference = abs(Decimal(row["frequency_estimate_hz"]) - frequency)
            error_difference = abs(Decimal(row["frequency_error_hz"]) - error)
        else:
            total = None
            frequency_difference = Decimal("Infinity")
            error_difference = Decimal("Infinity")
        row_exact = (
            unique
            and source_exact
            and int(row["source_count_seq"]) == last
            and int(row["accepted_sample_count"]) == 600
            and row["config_hash"] == expected_hash
            and row["observation_validity"] == "valid"
            and row["reference_validity"] == "valid"
            and row["count_validity"] == "valid"
            and frequency_difference <= SERIALIZED_12_DECIMAL_HALF_UNIT
            and error_difference <= SERIALIZED_12_DECIMAL_HALF_UNIT
        )
        exact &= row_exact
        source_summary = {
            "estimate_id": identifier,
            "estimator_sha256": row.get("config_hash"),
            "source_capture_session": (
                sources[0]["session"] if source_exact else None
            ),
            "source_reference_first_seq": first,
            "source_reference_last_seq": last,
            "estimator_timestamp_ticks": (
                int(closing_ticks) if closing_ticks.isdecimal() else None
            ),
            "time_domain": row.get("time_domain"),
            "frequency_error_hz": row.get("frequency_error_hz"),
            "accumulated_edge_error_counts": (
                total - 600 * 10_000_000 if total is not None else None
            ),
            "source_exact": source_exact,
            "pass": row_exact,
        }
        selected_estimate_sources.append(source_summary)
        comparisons.append(
            {
                **source_summary,
                "total_counted_edges": total,
                "absolute_frequency_difference_hz": (
                    None if frequency_difference.is_infinite() else float(frequency_difference)
                ),
                "absolute_error_difference_hz": (
                    None if error_difference.is_infinite() else float(error_difference)
                ),
                "pass": row_exact,
            }
        )
    nonoverlap = bool(selected_windows) and all(
        later_first >= earlier_last
        for (_, earlier_last), (later_first, _) in zip(selected_windows, selected_windows[1:])
    )
    exact &= nonoverlap
    return bool(exact), {
        "estimate_sequence_exact": sequence_exact,
        "raw_count_replay": raw_report,
        "calculation_domain": "firmware_ieee754_binary64_then_fixed_12_decimal",
        "selected_count": len(selected_windows),
        "selected_nonoverlap": nonoverlap,
        "D10": {
            "row_count": len(external_events),
            "channel_exact": d10_channel_exact,
            "local_error": d10_local_error,
            "authority": "evidence_only",
            "enters_D14_D8_replay": False,
        },
        "D14": {"row_count": len(references), "channel_exact": d14_channel_exact},
        "comparisons": comparisons,
        "selected_estimate_sources": selected_estimate_sources,
    }, estimates_by_id


def replay_active_decision_measurement_sources(
    manifest: Any, measurement: dict[str, Any]
) -> dict[str, Any]:
    """Bind every retained AHY decision to one reconstructed selected EST.

    The raw measurement replay establishes an EST's D14/D8 source aperture;
    this physical-only consumer proves the later operational decision consumed
    that same selected estimate.  EST rows remain observational unless an AHY
    record actually names their source span.
    """

    from .firmware_host_contract import bounded_modular_lag_matches

    errors: list[str] = []
    joins: list[dict[str, Any]] = []
    try:
        decisions = _read_csv(
            _single_contract_path(manifest, "active_hybrid_decisions_v2")
        )
        sources = measurement.get("selected_estimate_sources")
        if not isinstance(sources, list):
            raise ValueError("selected measurement source summaries are unavailable")
        source_index: dict[tuple[int, int, int], list[dict[str, Any]]] = {}
        for source in sources:
            if not isinstance(source, dict):
                raise ValueError("selected measurement comparison is malformed")
            session = source.get("source_capture_session")
            first = source.get("source_reference_first_seq")
            last = source.get("source_reference_last_seq")
            if not all(type(value) is int for value in (session, first, last)):
                continue
            source_index.setdefault((session, first, last), []).append(source)
        for decision in decisions:
            key: tuple[int, int, int] | None = None
            try:
                key = (
                    int(decision["capture_session"]),
                    int(decision["source_first_sequence"]),
                    int(decision["source_last_sequence"]),
                )
                candidates = source_index.get(key, [])
                source = candidates[0] if len(candidates) == 1 else None
                exact = (
                    source is not None
                    and source.get("pass") is True
                    and decision.get("frequency_estimator_sha256")
                    == source.get("estimator_sha256")
                    and Decimal(decision["frequency_error_hz"])
                    == Decimal(str(source["frequency_error_hz"]))
                    and int(decision["accumulated_edge_error_counts"])
                    == source.get("accumulated_edge_error_counts")
                    and bounded_modular_lag_matches(
                        "estimate_capture_precedes_operational_decision",
                        source=int(source["estimator_timestamp_ticks"]),
                        source_domain=str(source["time_domain"]),
                        target=int(decision["decision_timestamp_ticks"]),
                        target_domain=decision.get("time_domain", ""),
                    )
                )
            except (KeyError, TypeError, ValueError, ArithmeticError):
                source = None
                exact = False
            joins.append(
                {
                    "decision_sequence": decision.get("decision_sequence"),
                    "source_key": list(key) if key is not None else None,
                    "estimate_id": None if source is None else source.get("estimate_id"),
                    "exact": exact,
                }
            )
            if not exact:
                errors.append(
                    f"AHY {decision.get('decision_sequence', '?')} has no unique exact selected EST source"
                )
    except (OSError, UnicodeError, csv.Error, KeyError, TypeError, ValueError) as error:
        errors.append(str(error))
        decisions = []
        source_index = {}
    used = {
        item["estimate_id"] for item in joins
        if item.get("exact") and isinstance(item.get("estimate_id"), str)
    }
    source_count = sum(len(items) for items in source_index.values())
    return {
        "exact": not errors,
        "decision_count": len(decisions),
        "selected_source_count": source_count,
        "consumed_selected_source_count": len(used),
        "unconsumed_selected_source_count": source_count - len(used),
        "joins": joins,
        "errors": errors[:20],
        "error_count": len(errors),
        "scope": "physical_AHY_to_selected_EST_source_timestamp_session_and_numeric_binding",
    }


class ResponseClass(str, Enum):
    HEALTHY_DETECTED = "healthy_detected"
    HEALTHY_INDETERMINATE = "healthy_indeterminate_near_resolution"
    INSIDE_DEADBAND = "inside_deadband"
    LIMIT_REACHED = "limit_reached"
    WRONG_SIGN = "wrong_sign"
    EXCESS_RESPONSE = "excess_response"
    GROWING_ERROR = "growing_error"
    MEASUREMENT_OR_ACTUATOR_FAULT = "measurement_or_actuator_fault"


@dataclass(frozen=True)
class ResponseResult:
    classification: ResponseClass
    reason: str
    observed_response_hz: float | None
    cumulative_response_hz: float | None
    consecutive_indeterminate: int


class ResponseClassifier:
    def __init__(
        self, *, observational: bool, policy_document: dict[str, Any]
    ) -> None:
        value = policy_document
        if value.get("policy_id") != "OTIS_RESPONSE_CLASSIFICATION_V1":
            raise ValueError("response classification identity differs")
        p = value["parameters"]
        self.gain_min = float(p["gain_min_hz_per_code"])
        self.gain_max = float(p["gain_max_hz_per_code"])
        self.floor = float(p["empirical_detection_floor_hz"])
        self.deadband = float(p["error_deadband_hz"])
        self.wrong_sign_minimum = float(p["wrong_sign_minimum_hz"])
        self.growth_margin = float(p["growing_error_margin_hz"])
        self.excess_margin = float(p["excess_response_additive_margin_hz"])
        self.maximum_indeterminate = int(p["maximum_consecutive_indeterminate"])
        self.observational = observational
        self.baseline_error_hz: float | None = None
        self.cumulative_delta_codes = 0
        self.consecutive_indeterminate = 0

    def classify(
        self, *, pre_error_hz: float, post_error_hz: float, applied_delta_codes: int,
        current_code: int, minimum_code: int, maximum_code: int,
    ) -> ResponseResult:
        if applied_delta_codes == 0 or not all(map(math.isfinite, (pre_error_hz, post_error_hz))):
            return ResponseResult(ResponseClass.MEASUREMENT_OR_ACTUATOR_FAULT, "invalid_response_evidence", None, None, 0)
        if self.baseline_error_hz is None:
            self.baseline_error_hz = pre_error_hz
        self.cumulative_delta_codes += applied_delta_codes
        observed = post_error_hz - pre_error_hz
        cumulative = post_error_hz - self.baseline_error_hz
        if (
            observed * applied_delta_codes < 0
            and abs(observed) >= self.wrong_sign_minimum
        ) or (
            cumulative * self.cumulative_delta_codes < 0
            and abs(cumulative) >= self.wrong_sign_minimum
        ):
            result = (ResponseClass.WRONG_SIGN, "observed_response_opposes_positive_plant_gain")
        elif abs(post_error_hz) > abs(pre_error_hz) + self.growth_margin:
            result = (ResponseClass.GROWING_ERROR, "absolute_error_grew_beyond_frozen_margin")
        elif abs(observed) > abs(applied_delta_codes) * self.gain_max + self.excess_margin:
            result = (ResponseClass.EXCESS_RESPONSE, "response_exceeds_gain_envelope_plus_empirical_margin")
        elif (
            observed * applied_delta_codes > 0 and abs(observed) >= self.floor
        ) or (
            cumulative * self.cumulative_delta_codes > 0
            and abs(cumulative) >= self.floor
        ):
            result = (ResponseClass.HEALTHY_DETECTED, "response_detected_with_commanded_sign")
        else:
            self.consecutive_indeterminate += 1
            if (
                not self.observational
                and self.consecutive_indeterminate > self.maximum_indeterminate
                and abs(self.cumulative_delta_codes) * self.gain_min >= 2 * self.floor
            ):
                result = (ResponseClass.MEASUREMENT_OR_ACTUATOR_FAULT, "persistent_response_absence_after_cumulative_expected_detection")
            else:
                result = (ResponseClass.HEALTHY_INDETERMINATE, "healthy_evidence_below_empirical_detection_floor")
        if result[0] is not ResponseClass.HEALTHY_INDETERMINATE:
            self.consecutive_indeterminate = 0
        return ResponseResult(result[0], result[1], observed, cumulative, self.consecutive_indeterminate)


def _response_replay(
    rows: list[dict[str, str]], minimum_code: int, maximum_code: int,
    *, response_classification_observational: bool = False,
    response_policy_document: dict[str, Any],
) -> tuple[bool, list[dict[str, Any]]]:
    classifier = ResponseClassifier(
        observational=response_classification_observational,
        policy_document=response_policy_document,
    )
    grouped: dict[int, list[dict[str, str]]] = {}
    for row in rows:
        if row.get("event") != "manual_start":
            grouped.setdefault(int(row["request_sequence"]), []).append(row)
    exact = True
    results: list[dict[str, Any]] = []
    for request_sequence, group in sorted(grouped.items()):
        events = [row["event"] for row in group]
        if events != ["request_created", "request_accepted", "application", "response"]:
            exact = False
            results.append({"request_sequence": request_sequence, "events": events, "exact": False})
            continue
        created, _, applied, response = group
        replayed = classifier.classify(
            pre_error_hz=float(created["pre_error_hz"]),
            post_error_hz=float(response["post_error_hz"]),
            applied_delta_codes=int(created["requested_delta_codes"]),
            current_code=int(applied["applied_code"]),
            minimum_code=minimum_code,
            maximum_code=maximum_code,
        )
        row_exact = (
            response["response_class"] == replayed.classification.value
            and response["reason"] == replayed.reason
            and replayed.observed_response_hz is not None
            and math.isclose(float(response["observed_response_hz"]), replayed.observed_response_hz, rel_tol=0, abs_tol=5e-9)
        )
        exact &= row_exact
        results.append({"request_sequence": request_sequence, "replayed_class": replayed.classification.value, "exact": row_exact})
    return bool(exact), results


def _capsules_exact(
    run_dir: Path, rows: list[dict[str, str]], events: list[dict[str, Any]],
    supervisor_state: dict[str, Any], *,
    permitted_unacknowledged_sequences: frozenset[int] = frozenset(),
) -> tuple[bool, dict[str, str]]:
    expected_rows = [row for row in rows if row.get("event") != "manual_start"]
    hashes: dict[str, str] = {}
    exact = True
    expected_paths: set[Path] = set()
    phase = {"request_created": 1, "request_accepted": 2, "application": 3, "application_fault": 3, "response": 4}
    acknowledgements = {
        (int(item["record_sequence"]), int(item["phase"]))
        for item in events if item.get("event") == "transaction_phase_acknowledged"
    }
    for row in expected_rows:
        record = int(row["transaction_record_sequence"])
        relative = Path("reports") / f"step_{int(row['request_sequence']):03d}" / f"record_{record:06d}_{row['event']}.json"
        expected_paths.add(relative)
        path = run_dir / relative
        if not path.is_file() or json.loads(path.read_text(encoding="utf-8")) != row:
            exact = False
            continue
        hashes[str(relative)] = sha256(path.read_bytes()).hexdigest()
        if ((record, phase[row["event"]]) in acknowledgements) != (record not in permitted_unacknowledged_sequences):
            exact = False
    actual = {
        path.relative_to(run_dir)
        for path in (run_dir / "reports").glob("step_*/record_*_*.json")
        if not path.name.endswith("_response_replay_attestation.json")
    }
    exact &= actual == expected_paths
    expected_sequences = sorted(
        int(row["transaction_record_sequence"])
        for row in expected_rows
        if int(row["transaction_record_sequence"]) not in permitted_unacknowledged_sequences
    )
    exact &= sorted(supervisor_state.get("acknowledged_record_sequences", [])) == expected_sequences
    return bool(exact), hashes
