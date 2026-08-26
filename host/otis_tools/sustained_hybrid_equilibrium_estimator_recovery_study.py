"""Recovered-source offline equilibrium observability comparator.

This is the separately identified second attempt authorized after the exact
Stage 5 plan was recovered.  It preserves the V1 scientific contract and its
immutable invalid report.  The module has no serial, live, firmware, command,
DAC-write, or actuator surface.
"""

from __future__ import annotations

import argparse
import csv
from dataclasses import dataclass, replace
from decimal import Decimal
from fractions import Fraction
from hashlib import sha256
import json
from pathlib import Path
from typing import Any, Iterable, Sequence

from . import sustained_hybrid_equilibrium_estimator_study as original


REPO_ROOT = Path(__file__).resolve().parents[2]
STUDY_DIR = (
    REPO_ROOT
    / "docs/60_EXPERIMENTS/"
    "OTIS_SUSTAINED_HYBRID_EQUILIBRIUM_ESTIMATOR_FEASIBILITY_STUDY"
)
DEFAULT_CONTRACT = STUDY_DIR / "study_contract_recovery_v2.json"
TOOL_ID = "otis_sustained_hybrid_equilibrium_estimator_recovery_v2"
REPORT_TYPE = "otis_sustained_hybrid_equilibrium_estimator_observability_report_v2"

INVALID_TERMINAL = original.INVALID_TERMINAL
NOT_OBSERVABLE_TERMINAL = original.NOT_OBSERVABLE_TERMINAL
OBSERVABLE_TERMINAL = original.OBSERVABLE_TERMINAL

NOMINAL_OSCILLATOR_HZ = 10_000_000
SUPPORT_SECONDS = 600
SUPPORT_INTERVALS = 600
UINT32_MASK = (1 << 32) - 1
REFERENCE_INVALID_FLAGS = (
    (1 << 0)
    | (1 << 1)
    | (1 << 2)
    | (1 << 3)
    | (1 << 5)
    | (1 << 6)
    | (1 << 7)
    | (1 << 8)
    | (1 << 9)
    | (1 << 10)
    | (1 << 11)
)
COUNT_INVALID_FLAGS = (
    (1 << 0)
    | (1 << 1)
    | (1 << 2)
    | (1 << 5)
    | (1 << 8)
    | (1 << 9)
    | (1 << 10)
    | (1 << 12)
    | (1 << 13)
)


def _canonical_sha256(value: object) -> str:
    return sha256(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    ).hexdigest()


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _read_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _fraction(value: str | int | Fraction) -> Fraction:
    if isinstance(value, Fraction):
        return value
    return Fraction(value)


def _fraction_string(value: Fraction) -> str:
    return f"{value.numerator}/{value.denominator}"


def _interval_json(
    interval: original.ClosedInterval | None,
) -> dict[str, Any] | None:
    if interval is None:
        return None
    return {
        **interval.as_strings(),
        "lower_decimal_display_only": float(interval.lower),
        "upper_decimal_display_only": float(interval.upper),
        "width_decimal_display_only": float(interval.width),
    }


def _expanded(
    interval: original.ClosedInterval, amount: Fraction
) -> original.ClosedInterval:
    return original.ClosedInterval(interval.lower - amount, interval.upper + amount)


def _hull(
    intervals: Iterable[original.ClosedInterval],
) -> original.ClosedInterval:
    values = tuple(intervals)
    if not values:
        raise ValueError("at least one interval is required for a hull")
    return original.ClosedInterval(
        min(item.lower for item in values), max(item.upper for item in values)
    )


@dataclass(frozen=True)
class SupportObservation:
    evidence_source: str
    segment: str
    code: int
    dac_epoch: str
    capture_session: str
    first_snapshot_sequence: int
    last_snapshot_sequence: int
    first_reference_sequence: int
    last_reference_sequence: int
    first_count_sequence: int
    last_count_sequence: int
    total_counted_edges: int
    count_error: int
    midpoint_reference_sequence: Fraction
    history_class: str

    def as_report_row(self) -> dict[str, Any]:
        return {
            "evidence_source": self.evidence_source,
            "segment": self.segment,
            "code": self.code,
            "dac_epoch": self.dac_epoch,
            "capture_session": self.capture_session,
            "first_snapshot_sequence": self.first_snapshot_sequence,
            "last_snapshot_sequence": self.last_snapshot_sequence,
            "first_reference_sequence": self.first_reference_sequence,
            "last_reference_sequence": self.last_reference_sequence,
            "first_count_sequence": self.first_count_sequence,
            "last_count_sequence": self.last_count_sequence,
            "total_counted_edges": self.total_counted_edges,
            "count_error": self.count_error,
            "frequency_error_hz": _fraction_string(
                Fraction(self.count_error, SUPPORT_SECONDS)
            ),
            "midpoint_reference_sequence": _fraction_string(
                self.midpoint_reference_sequence
            ),
            "history_class": self.history_class,
            "provenance": "reconstructed_from_bound_raw_D14_D8_and_DAC_records",
        }


RETURN_SEGMENTS = frozenset(
    {
        "lower_interior_2",
        "upper_interior_2",
        "final_safe_centre",
    }
)


def _history_class(segment: str) -> str:
    return "return" if segment in RETURN_SEGMENTS else "outbound_or_anchor"


def load_recovery_contract(
    path: Path = DEFAULT_CONTRACT,
) -> tuple[dict[str, Any], dict[str, Any]]:
    contract = _read_object(path)
    if (
        contract.get("schema_version") != 2
        or contract.get("attempt_id")
        != "OTIS_SUSTAINED_HYBRID_EQUILIBRIUM_ESTIMATOR_FEASIBILITY_STUDY_V1_RECOVERY_ATTEMPT_2"
        or contract.get("status")
        != "prospectively_frozen_before_recovery_attempt_results"
    ):
        raise ValueError("unsupported or unfrozen recovery-attempt contract")
    claimed = contract.get("contract_sha256")
    unsigned = {
        key: value for key, value in contract.items() if key != "contract_sha256"
    }
    if claimed != _canonical_sha256(unsigned):
        raise ValueError("recovery-attempt contract semantic identity differs")

    parent_binding = contract["parent_contract"]
    parent_path = REPO_ROOT / parent_binding["path"]
    if _file_sha256(parent_path) != parent_binding["file_sha256"]:
        raise ValueError("parent V1 contract file identity differs")
    parent = original.load_contract(parent_path)
    if parent["contract_sha256"] != parent_binding["semantic_sha256"]:
        raise ValueError("parent V1 contract semantic identity differs")

    frozen_keys = tuple(contract["unchanged_scientific_contract"]["parent_keys"])
    frozen_sections = {key: parent[key] for key in frozen_keys}
    if _canonical_sha256(frozen_sections) != contract[
        "unchanged_scientific_contract"
    ]["semantic_sha256"]:
        raise ValueError("parent scientific semantics differ")

    authority = contract.get("authority", {})
    if authority != parent["authority"]:
        raise ValueError("recovery authority differs from offline-only parent")
    tool = contract["output"]["tool"]
    tool_path = REPO_ROOT / tool["path"]
    if tool["tool_id"] != TOOL_ID or _file_sha256(tool_path) != tool["sha256"]:
        raise ValueError("recovery comparator identity differs")
    return contract, parent


def _binding_rows(
    bindings: Sequence[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return original._validate_file_bindings(bindings)


def _validate_d14_reference(
    reference: dict[str, str], snapshot: dict[str, str]
) -> None:
    if (
        reference["record_type"] != "REF"
        or int(reference["channel_id"]) != 1
        or reference["edge"] != "R"
        or int(reference["timestamp_ticks"])
        != int(snapshot["reference_timestamp_ticks"])
        or int(reference["flags"]) & REFERENCE_INVALID_FLAGS
    ):
        raise ValueError("D14 reference association is invalid")


def _support_from_raw(
    *,
    segment: str,
    code: int,
    epoch: str,
    opening_sequence: int,
    snapshots: dict[int, dict[str, str]],
    counts: dict[int, dict[str, str]],
    references: dict[int, dict[str, str]],
) -> SupportObservation:
    closing_sequence = opening_sequence + SUPPORT_INTERVALS
    boundary_rows = []
    for sequence in range(opening_sequence, closing_sequence + 1):
        snapshot = snapshots.get(sequence)
        if snapshot is None:
            raise ValueError(f"missing Stage 5 snapshot sequence {sequence}")
        if (
            int(snapshot["status"]) != 0
            or snapshot["backend"] != "pio_wait_cumulative_snapshot_dma_v1"
        ):
            raise ValueError(f"invalid Stage 5 snapshot sequence {sequence}")
        reference = references.get(int(snapshot["reference_timestamp_ticks"]))
        if reference is None:
            raise ValueError(f"missing D14 reference for snapshot {sequence}")
        _validate_d14_reference(reference, snapshot)
        boundary_rows.append(snapshot)

    sessions = {row["session"] for row in boundary_rows}
    if len(sessions) != 1:
        raise ValueError("600-second support crosses a capture session")
    total = 0
    for opening, closing in zip(boundary_rows, boundary_rows[1:]):
        opening_seq = int(opening["snapshot_sequence"])
        closing_seq = int(closing["snapshot_sequence"])
        if closing_seq != opening_seq + 1:
            raise ValueError("snapshot sequence is not contiguous")
        if (
            int(closing["reference_sequence"])
            != int(opening["reference_sequence"]) + 1
        ):
            raise ValueError("D14 reference sequence is not contiguous")
        row = counts.get(closing_seq)
        if row is None:
            raise ValueError(f"missing D8 count sequence {closing_seq}")
        counted = int(row["counted_edges"])
        reconstructed = (
            int(opening["cumulative_down_counter"])
            - int(closing["cumulative_down_counter"])
        ) & UINT32_MASK
        if (
            int(row["count_seq"]) != closing_seq
            or counted != reconstructed
            or int(row["gate_open_ticks"])
            != int(opening["reference_timestamp_ticks"])
            or int(row["gate_close_ticks"])
            != int(closing["reference_timestamp_ticks"])
            or row["source_edge"] != "R"
            or int(row["flags"]) & COUNT_INVALID_FLAGS
        ):
            raise ValueError(f"D8 count binding differs at sequence {closing_seq}")
        total += counted

    first = boundary_rows[0]
    last = boundary_rows[-1]
    count_error = total - NOMINAL_OSCILLATOR_HZ * SUPPORT_SECONDS
    return SupportObservation(
        evidence_source="stage5_identification",
        segment=segment,
        code=code,
        dac_epoch=epoch,
        capture_session=next(iter(sessions)),
        first_snapshot_sequence=opening_sequence,
        last_snapshot_sequence=closing_sequence,
        first_reference_sequence=int(first["reference_sequence"]),
        last_reference_sequence=int(last["reference_sequence"]),
        first_count_sequence=opening_sequence + 1,
        last_count_sequence=closing_sequence,
        total_counted_edges=total,
        count_error=count_error,
        midpoint_reference_sequence=Fraction(
            int(first["reference_sequence"]) + int(last["reference_sequence"]), 2
        ),
        history_class=_history_class(segment),
    )


def reconstruct_stage5_supports(
    parent: dict[str, Any], *, start_offset_seconds: int = 0
) -> tuple[SupportObservation, ...]:
    if start_offset_seconds not in (0, 1):
        raise ValueError("only frozen at-boundary and one-second-above cases exist")
    run_dir = REPO_ROOT / parent["plant_characterization"]["source_run"]
    policy_path = (
        run_dir
        / "derived/cx317_pps_plant_characterization_v1/interval_policy_v1.json"
    )
    policy = _read_object(policy_path)
    plan = _read_object(
        REPO_ROOT / "profiles/plant_campaigns/cx317_pps_gated_open_loop_v1.json"
    )
    if plan["settling_exclusion_s"] != 900 or plan["dwell_s"] != 2400:
        raise ValueError("recovered Stage 5 timing differs")
    sequence = [(str(row["label"]), int(row["code"])) for row in plan["sequence"]]

    dac_rows = _read_csv(run_dir / "csv/dac_steps.csv")
    applied = [int(row["dac_code_applied"]) for row in dac_rows]
    if applied != [code for _label, code in sequence] or any(
        int(row["dac_code_requested"]) != int(row["dac_code_applied"])
        or int(row["dac_code_clamped"]) != 0
        or int(row["flags"]) != 0
        for row in dac_rows
    ):
        raise ValueError("Stage 5 DAC acknowledgement chronology differs")

    snapshots_rows = _read_csv(run_dir / "csv/snp.csv")
    counts_rows = _read_csv(run_dir / "csv/cnt.csv")
    reference_rows = _read_csv(run_dir / "csv/ref.csv")
    snapshots = {int(row["snapshot_sequence"]): row for row in snapshots_rows}
    counts = {int(row["count_seq"]): row for row in counts_rows}
    matching_references = [
        row
        for row in reference_rows
        if row["record_type"] == "REF"
        and int(row["channel_id"]) == 1
        and row["edge"] == "R"
    ]
    references = {
        int(row["timestamp_ticks"]): row for row in matching_references
    }
    if (
        len(snapshots) != len(snapshots_rows)
        or len(counts) != len(counts_rows)
        or len(references) != len(matching_references)
        or not references
    ):
        raise ValueError("Stage 5 raw sequence identity is ambiguous")

    settled = [row for row in policy["ranges"] if not row["settling_excluded"]]
    if len(settled) != len(sequence):
        raise ValueError("Stage 5 settled segment count differs from plan")
    supports: list[SupportObservation] = []
    for (label, code), policy_row in zip(sequence, settled):
        epoch = str(policy_row["control_epoch"])
        if label not in epoch or f"0x{code:04X}" not in epoch:
            raise ValueError("Stage 5 interval policy does not match plan")
        first_closing = int(policy_row["first_closing_snapshot_sequence"])
        last_closing = int(policy_row["last_closing_snapshot_sequence"])
        first_opening = first_closing - 1 + start_offset_seconds
        required_last = first_opening + 2 * SUPPORT_INTERVALS
        if required_last > last_closing:
            raise ValueError("Stage 5 settled range lacks two fresh supports")
        for support_index in range(2):
            opening = first_opening + support_index * SUPPORT_INTERVALS
            supports.append(
                _support_from_raw(
                    segment=label,
                    code=code,
                    epoch=epoch,
                    opening_sequence=opening,
                    snapshots=snapshots,
                    counts=counts,
                    references=references,
                )
            )
    return tuple(supports)


def reconstruct_attempt4_supports(
    parent: dict[str, Any],
) -> tuple[SupportObservation, ...]:
    run_dir = REPO_ROOT / parent["attempt4"]["run_dir"]
    transaction_rows = _read_csv(run_dir / "csv/active_transactions_v1.csv")
    epoch_codes: dict[int, int] = {}
    for row in transaction_rows:
        if row["event"] == "manual_start":
            epoch_codes[int(row["dac_epoch"])] = int(row["applied_code"])
        elif row["event"] == "application":
            epoch_codes[int(row["dac_epoch"])] = int(row["applied_code"])
    if sorted(epoch_codes) != list(range(1, 13)):
        raise ValueError("Attempt 4 DAC epoch chronology differs")

    rows = [
        row
        for row in _read_csv(run_dir / "csv/estimates_v2.csv")
        if row["estimator_version"] == "cx317_selected_600s_nonoverlap_v1"
    ]
    supports: list[SupportObservation] = []
    for row in rows:
        if (
            row["observation_validity"] != "valid"
            or int(row["accepted_sample_count"]) != SUPPORT_SECONDS
            or int(row["source_reference_last_seq"])
            - int(row["source_reference_first_seq"])
            != SUPPORT_SECONDS
        ):
            raise ValueError("Attempt 4 selected support is not valid and fresh")
        prefix, kind, epoch_text = row["source_dac_ref"].split(":")
        if (prefix, kind) != ("live", "DAC"):
            raise ValueError("Attempt 4 source DAC reference differs")
        epoch = int(epoch_text)
        exact_decimal = Fraction(Decimal(row["frequency_error_hz"]))
        scaled = exact_decimal * SUPPORT_SECONDS
        count_error = round(scaled)
        if abs(scaled - count_error) > Fraction(1, 1_000_000):
            raise ValueError("Attempt 4 frequency serialization is not one count")
        first_ref = int(row["source_reference_first_seq"])
        last_ref = int(row["source_reference_last_seq"])
        supports.append(
            SupportObservation(
                evidence_source="attempt4_held_out_validation",
                segment=f"dac_epoch_{epoch}",
                code=epoch_codes[epoch],
                dac_epoch=f"live:DAC:{epoch}",
                capture_session="1",
                first_snapshot_sequence=first_ref,
                last_snapshot_sequence=last_ref,
                first_reference_sequence=first_ref,
                last_reference_sequence=last_ref,
                first_count_sequence=first_ref + 1,
                last_count_sequence=last_ref,
                total_counted_edges=(
                    NOMINAL_OSCILLATOR_HZ * SUPPORT_SECONDS + count_error
                ),
                count_error=count_error,
                midpoint_reference_sequence=Fraction(first_ref + last_ref, 2),
                history_class="held_out_observed_path",
            )
        )
    if len(supports) != 52:
        raise ValueError("Attempt 4 selected-support count differs")
    return tuple(supports)


def equilibrium_intervals(
    supports: Sequence[SupportObservation],
    *,
    gain: Fraction,
    count_perturbations: dict[str, int] | None = None,
) -> tuple[original.ClosedInterval, ...]:
    perturbations = count_perturbations or {}
    zero = original.ClosedInterval(Fraction(0), Fraction(0))
    fixed_gain = original.ClosedInterval(gain, gain)
    return tuple(
        original.equilibrium_interval_from_observation(
            applied_code=support.code,
            frequency_error_hz=original.count_quantization_interval(
                support.count_error,
                support_seconds=SUPPORT_SECONDS,
                perturbation_counts=perturbations.get(support.segment, 0),
            ),
            gain_hz_per_code=fixed_gain,
            nuisance_hz=zero,
        )
        for support in supports
    )


def _linear_projection(
    intervals: Sequence[original.ClosedInterval],
    times_hours: Sequence[Fraction],
    slope_limit: Fraction,
) -> dict[str, Any]:
    if len(intervals) != len(times_hours) or not intervals:
        raise ValueError("linear projection inputs differ")
    slope_lower = -slope_limit
    slope_upper = slope_limit
    for left in range(len(intervals)):
        for right in range(len(intervals)):
            coefficient = times_hours[right] - times_hours[left]
            bound = intervals[right].upper - intervals[left].lower
            if coefficient > 0:
                slope_upper = min(slope_upper, bound / coefficient)
            elif coefficient < 0:
                slope_lower = max(slope_lower, bound / coefficient)
            elif bound < 0:
                return {
                    "feasible": False,
                    "slope_codes_per_hour": None,
                    "equilibrium_at_reference": None,
                }
    if slope_lower > slope_upper:
        return {
            "feasible": False,
            "slope_codes_per_hour": None,
            "equilibrium_at_reference": None,
        }

    lower_lines = [
        (item.lower, -time) for item, time in zip(intervals, times_hours)
    ]
    upper_lines = [
        (item.upper, -time) for item, time in zip(intervals, times_hours)
    ]

    def candidates(lines: Sequence[tuple[Fraction, Fraction]]) -> set[Fraction]:
        values = {slope_lower, slope_upper}
        for index, (a_left, b_left) in enumerate(lines):
            for a_right, b_right in lines[index + 1 :]:
                if b_left == b_right:
                    continue
                crossing = (a_right - a_left) / (b_left - b_right)
                if slope_lower <= crossing <= slope_upper:
                    values.add(crossing)
        return values

    lower_projection = min(
        max(a + b * slope for a, b in lower_lines)
        for slope in candidates(lower_lines)
    )
    upper_projection = max(
        min(a + b * slope for a, b in upper_lines)
        for slope in candidates(upper_lines)
    )
    if lower_projection > upper_projection:
        raise AssertionError("exact linear projection is contradictory")
    return {
        "feasible": True,
        "slope_codes_per_hour": _interval_json(
            original.ClosedInterval(slope_lower, slope_upper)
        ),
        "equilibrium_at_reference": _interval_json(
            original.ClosedInterval(lower_projection, upper_projection)
        ),
    }


def _constant_model(
    supports: Sequence[SupportObservation], gain: Fraction
) -> dict[str, Any]:
    intervals = equilibrium_intervals(supports, gain=gain)
    complete = original.intersect_all(intervals)
    return {
        "feasible": complete is not None,
        "complete_equilibrium_set": _interval_json(complete),
        "first_empty_after_support": _first_empty_support(supports, intervals),
    }


def _first_empty_support(
    supports: Sequence[SupportObservation],
    intervals: Sequence[original.ClosedInterval],
) -> dict[str, Any] | None:
    active: original.ClosedInterval | None = None
    for support, interval in zip(supports, intervals):
        active = interval if active is None else active.intersect(interval)
        if active is None:
            return {
                "segment": support.segment,
                "first_snapshot_sequence": support.first_snapshot_sequence,
                "last_snapshot_sequence": support.last_snapshot_sequence,
                "count_error": support.count_error,
            }
    return None


def _slow_drift_model(
    supports: Sequence[SupportObservation], gain: Fraction, slope_limit: Fraction
) -> dict[str, Any]:
    intervals = equilibrium_intervals(supports, gain=gain)
    reference = Fraction(
        min(item.midpoint_reference_sequence for item in supports)
        + max(item.midpoint_reference_sequence for item in supports),
        2,
    )
    times = tuple(
        (item.midpoint_reference_sequence - reference) / 3600 for item in supports
    )
    projection = _linear_projection(intervals, times, slope_limit)
    return {
        **projection,
        "reference_D14_sequence": _fraction_string(reference),
        "cross_run_extrapolation": "undefined_across_independent_sessions",
    }


def _history_model(
    supports: Sequence[SupportObservation], gain: Fraction, dead_zone: Fraction
) -> dict[str, Any]:
    intervals = equilibrium_intervals(supports, gain=gain)
    outbound_rows = [
        interval
        for support, interval in zip(supports, intervals)
        if support.history_class == "outbound_or_anchor"
    ]
    return_rows = [
        interval
        for support, interval in zip(supports, intervals)
        if support.history_class == "return"
    ]
    outbound = original.intersect_all(outbound_rows)
    returned = original.intersect_all(return_rows)
    if outbound is None or returned is None:
        return {
            "feasible": False,
            "durable_base_equilibrium_set": None,
            "outbound_equilibrium_set": _interval_json(outbound),
            "return_equilibrium_set": _interval_json(returned),
            "history_offset_codes": None,
            "complete_effective_equilibrium_set": None,
        }
    base = outbound.intersect(_expanded(returned, dead_zone))
    history_offset = original.ClosedInterval(
        returned.lower - outbound.upper,
        returned.upper - outbound.lower,
    ).intersect(original.ClosedInterval(-dead_zone, dead_zone))
    if base is None or history_offset is None:
        return {
            "feasible": False,
            "durable_base_equilibrium_set": None,
            "outbound_equilibrium_set": _interval_json(outbound),
            "return_equilibrium_set": _interval_json(returned),
            "history_offset_codes": None,
            "complete_effective_equilibrium_set": None,
        }
    return_base_for_effective = returned.intersect(_expanded(outbound, dead_zone))
    assert return_base_for_effective is not None
    complete = _hull((base, return_base_for_effective))
    return {
        "feasible": True,
        "durable_base_equilibrium_set": _interval_json(base),
        "outbound_equilibrium_set": _interval_json(outbound),
        "return_equilibrium_set": _interval_json(returned),
        "history_offset_codes": _interval_json(history_offset),
        "complete_effective_equilibrium_set": _interval_json(complete),
    }


def _model_interval(result: dict[str, Any], model_id: str) -> original.ClosedInterval | None:
    if not result.get("feasible"):
        return None
    key = {
        "constant_equilibrium_per_stage5_thermal_segment_v1": "complete_equilibrium_set",
        "bounded_slow_drift_equilibrium_v1": "equilibrium_at_reference",
        "direction_history_conditioned_equilibrium_v1": "complete_effective_equilibrium_set",
    }[model_id]
    row = result.get(key)
    if row is None:
        return None
    return original.ClosedInterval(_fraction(row["lower"]), _fraction(row["upper"]))


def _prediction_interval(
    *,
    code: int,
    equilibrium: original.ClosedInterval,
    gain: Fraction,
    history_dead_zone: Fraction,
) -> original.ClosedInterval:
    displacement = original.ClosedInterval(
        Fraction(code) - equilibrium.upper - history_dead_zone,
        Fraction(code) - equilibrium.lower + history_dead_zone,
    )
    return original.ClosedInterval(displacement.lower * gain, displacement.upper * gain)


def _held_out_prediction(
    *,
    supports: Sequence[SupportObservation],
    equilibrium: original.ClosedInterval | None,
    gain: Fraction,
    history_dead_zone: Fraction,
) -> dict[str, Any]:
    if equilibrium is None:
        return {
            "evaluated": False,
            "passed": False,
            "reason": "identification_complete_feasible_set_empty",
            "coverage_count": 0,
            "observation_count": len(supports),
            "coverage_fraction": "0/1",
            "worst_residual_hz": None,
            "tail_residual_hz": None,
            "first_uncovered_support": None,
        }
    residuals: list[Fraction] = []
    uncovered: list[dict[str, Any]] = []
    for support in supports:
        prediction = _prediction_interval(
            code=support.code,
            equilibrium=equilibrium,
            gain=gain,
            history_dead_zone=history_dead_zone,
        )
        observed = original.count_quantization_interval(support.count_error)
        if observed.intersect(prediction) is not None:
            residual = Fraction(0)
        elif observed.upper < prediction.lower:
            residual = prediction.lower - observed.upper
        else:
            residual = observed.lower - prediction.upper
        residuals.append(residual)
        if residual:
            uncovered.append(
                {
                    "segment": support.segment,
                    "dac_epoch": support.dac_epoch,
                    "code": support.code,
                    "first_reference_sequence": support.first_reference_sequence,
                    "last_reference_sequence": support.last_reference_sequence,
                    "count_error": support.count_error,
                    "residual_hz": _fraction_string(residual),
                }
            )
    ordered = sorted(residuals)
    tail_index = max(0, (95 * len(ordered) + 99) // 100 - 1)
    covered = len(supports) - len(uncovered)
    return {
        "evaluated": True,
        "coverage_count": covered,
        "observation_count": len(supports),
        "coverage_fraction": _fraction_string(Fraction(covered, len(supports))),
        "worst_residual_hz": _fraction_string(max(residuals)),
        "tail_residual_hz": _fraction_string(ordered[tail_index]),
        "first_uncovered_support": uncovered[0] if uncovered else None,
        "passed": not uncovered,
    }


def _evaluate_model(
    *,
    model_id: str,
    supports: Sequence[SupportObservation],
    held_out: Sequence[SupportObservation],
    gain: Fraction,
    slope_limit: Fraction,
    dead_zone: Fraction,
    usefulness_span: Fraction,
) -> dict[str, Any]:
    if model_id == "constant_equilibrium_per_stage5_thermal_segment_v1":
        numerical = _constant_model(supports, gain)
        prediction_dead_zone = Fraction(0)
    elif model_id == "bounded_slow_drift_equilibrium_v1":
        numerical = _slow_drift_model(supports, gain, slope_limit)
        prediction_dead_zone = Fraction(0)
    elif model_id == "direction_history_conditioned_equilibrium_v1":
        numerical = _history_model(supports, gain, dead_zone)
        prediction_dead_zone = dead_zone
    else:
        raise ValueError(f"unsupported frozen model: {model_id}")
    interval = _model_interval(numerical, model_id)
    if model_id == "bounded_slow_drift_equilibrium_v1":
        prediction = {
            "evaluated": False,
            "passed": False,
            "reason": "independent_run_has_no_frozen_cross_session_drift_origin",
            "coverage_count": 0,
            "observation_count": len(held_out),
        }
    else:
        prediction = _held_out_prediction(
            supports=held_out,
            equilibrium=interval,
            gain=gain,
            history_dead_zone=prediction_dead_zone,
        )
    return {
        "numerical": numerical,
        "held_out_prediction": prediction,
        "bounded": interval is not None,
        "useful_span_passed": (
            interval is not None and interval.width <= usefulness_span
        ),
        "complete_interval": _interval_json(interval),
    }


def _leave_one_segment_out(
    *,
    model_id: str,
    supports: Sequence[SupportObservation],
    gain: Fraction,
    slope_limit: Fraction,
    dead_zone: Fraction,
    usefulness_span: Fraction,
) -> dict[str, Any]:
    rows = []
    for segment in dict.fromkeys(item.segment for item in supports):
        retained = tuple(item for item in supports if item.segment != segment)
        if model_id == "constant_equilibrium_per_stage5_thermal_segment_v1":
            result = _constant_model(retained, gain)
        elif model_id == "bounded_slow_drift_equilibrium_v1":
            result = _slow_drift_model(retained, gain, slope_limit)
        else:
            result = _history_model(retained, gain, dead_zone)
        interval = _model_interval(result, model_id)
        rows.append(
            {
                "omitted_segment": segment,
                "nonempty": interval is not None,
                "interval": _interval_json(interval),
                "useful_span_passed": (
                    interval is not None and interval.width <= usefulness_span
                ),
            }
        )
    return {
        "cases": rows,
        "all_nonempty_and_useful": all(
            row["nonempty"] and row["useful_span_passed"] for row in rows
        ),
    }


def _same_code_perturbations(
    *,
    model_id: str,
    supports: Sequence[SupportObservation],
    gain: Fraction,
    slope_limit: Fraction,
    dead_zone: Fraction,
    usefulness_span: Fraction,
) -> dict[str, Any]:
    repeated = tuple(segment for segment in RETURN_SEGMENTS if any(
        item.segment == segment for item in supports
    ))
    rows = []
    for perturbation in (-1, 1):
        for segment in sorted(repeated):
            modified = tuple(
                replace(item, count_error=item.count_error + perturbation)
                if item.segment == segment
                else item
                for item in supports
            )
            if model_id == "constant_equilibrium_per_stage5_thermal_segment_v1":
                result = _constant_model(modified, gain)
            elif model_id == "bounded_slow_drift_equilibrium_v1":
                result = _slow_drift_model(modified, gain, slope_limit)
            else:
                result = _history_model(modified, gain, dead_zone)
            interval = _model_interval(result, model_id)
            rows.append(
                {
                    "segment": segment,
                    "perturbation_counts": perturbation,
                    "nonempty": interval is not None,
                    "interval": _interval_json(interval),
                    "useful_span_passed": (
                        interval is not None and interval.width <= usefulness_span
                    ),
                }
            )
    return {
        "cases": rows,
        "all_nonempty_and_useful": all(
            row["nonempty"] and row["useful_span_passed"] for row in rows
        ),
    }


def _temperature_inventory(parent: dict[str, Any]) -> dict[str, Any]:
    plant = _read_object(REPO_ROOT / parent["plant_characterization"]["summary_path"])
    attempt_dir = REPO_ROOT / parent["attempt4"]["run_dir"]
    values = [
        Fraction(Decimal(row["temperature_c"]))
        for row in _read_csv(attempt_dir / "csv/environment.csv")
        if row["source"] == "sht4x"
        and row["role"] == "vcocxo_near"
        and row["temperature_c"]
        and int(row["flags"]) == 0
    ]
    stage5 = plant["temperature_context"]
    return {
        "stage5_nearby_air_min_c": stage5["temperature_min_c"],
        "stage5_nearby_air_max_c": stage5["temperature_max_c"],
        "stage5_sample_count": stage5["sample_count"],
        "attempt4_nearby_air_min_c": float(min(values)),
        "attempt4_nearby_air_max_c": float(max(values)),
        "attempt4_sample_count": len(values),
        "overlap_exists": max(
            Fraction(Decimal(str(stage5["temperature_min_c"]))), min(values)
        )
        <= min(Fraction(Decimal(str(stage5["temperature_max_c"]))), max(values)),
        "fitted_temperature_coefficient": None,
        "claim": "observed_nearby_air_context_only",
    }


def create_observability_report(
    contract_path: Path = DEFAULT_CONTRACT,
) -> dict[str, Any]:
    contract_path = contract_path.resolve()
    contract, parent = load_recovery_contract(contract_path)
    all_bindings = [
        *parent["tracked_bindings"],
        *parent["attempt4"]["file_bindings"],
        *parent["plant_characterization"]["source_bindings"],
        *contract["additional_source_bindings"],
    ]
    binding_rows, identity_failures = _binding_rows(all_bindings)
    predecessor = original._reproduce_predecessors(parent)
    if not predecessor["successor_report_reproduced"]:
        identity_failures.append(
            {"failure_id": "successor_report_reproduction_mismatch"}
        )
    if not predecessor["mode_report_reproduced"]:
        identity_failures.append({"failure_id": "mode_report_reproduction_mismatch"})
    if not predecessor["exact_v1_baseline_reproduced"]:
        identity_failures.append({"failure_id": "exact_v1_baseline_mismatch"})

    if identity_failures:
        terminal = INVALID_TERMINAL
        first_failure = identity_failures[0]["failure_id"]
        report = {
            "schema_version": 2,
            "report_type": REPORT_TYPE,
            "study_identity": parent["contract_id"],
            "attempt_id": contract["attempt_id"],
            "status": "complete_bounded_terminal",
            "terminal": terminal,
            "first_discriminating_failure": first_failure,
            "source_identity_validation": {
                "all_required_exact": False,
                "bindings": binding_rows,
                "failures": identity_failures,
            },
            "physical_actions_performed": 0,
            "authority": contract["authority"],
        }
        report["report_sha256"] = _canonical_sha256(report)
        return report

    stage5 = reconstruct_stage5_supports(parent)
    stage5_above = reconstruct_stage5_supports(parent, start_offset_seconds=1)
    attempt4 = reconstruct_attempt4_supports(parent)
    gain_cases = {
        name: _fraction(value)
        for name, value in parent["nuisance_and_arithmetic_semantics"][
            "gain_cases_hz_per_code"
        ].items()
    }
    slope_limit = Fraction(191, 100)
    dead_zone = Fraction(8)
    usefulness_span = Fraction(
        parent["usefulness_gate"]["maximum_equilibrium_interval_span_codes"]
    )

    structural = {
        "constant_equilibrium_per_stage5_thermal_segment_v1": {
            "identifiable": len({item.code for item in stage5}) >= 3
            and any(item.count_error < 0 for item in stage5)
            and any(item.count_error > 0 for item in stage5),
            "evidence": "nine complete dwells include positive code excitation and a D14-relative zero bracket",
        },
        "bounded_slow_drift_equilibrium_v1": {
            "identifiable": all(
                sum(item.segment == segment for item in stage5) >= 2
                for segment in ("centre_1", "centre_2", "final_safe_centre")
            ),
            "evidence": "three same-code centre visits plus exact D14 sequence establish a separate bounded time coordinate",
        },
        "direction_history_conditioned_equilibrium_v1": {
            "identifiable": bool(RETURN_SEGMENTS)
            and {item.history_class for item in stage5}
            == {"outbound_or_anchor", "return"},
            "evidence": "both directions, two natural reversals, and same-code returns are retained as complete dwells",
        },
    }

    model_results: list[dict[str, Any]] = []
    for hypothesis in parent["model_hypotheses"]:
        model_id = hypothesis["model_id"]
        cases: dict[str, Any] = {}
        for gain_name, gain in gain_cases.items():
            evaluated = _evaluate_model(
                model_id=model_id,
                supports=stage5,
                held_out=attempt4,
                gain=gain,
                slope_limit=slope_limit,
                dead_zone=dead_zone,
                usefulness_span=usefulness_span,
            )
            evaluated["leave_one_complete_segment_out"] = _leave_one_segment_out(
                model_id=model_id,
                supports=stage5,
                gain=gain,
                slope_limit=slope_limit,
                dead_zone=dead_zone,
                usefulness_span=usefulness_span,
            )
            evaluated["same_code_one_count_perturbations"] = (
                _same_code_perturbations(
                    model_id=model_id,
                    supports=stage5,
                    gain=gain,
                    slope_limit=slope_limit,
                    dead_zone=dead_zone,
                    usefulness_span=usefulness_span,
                )
            )
            above = _evaluate_model(
                model_id=model_id,
                supports=stage5_above,
                held_out=attempt4,
                gain=gain,
                slope_limit=slope_limit,
                dead_zone=dead_zone,
                usefulness_span=usefulness_span,
            )
            evaluated["settling_boundary"] = {
                "below": "rejected_crosses_frozen_900_second_exclusion",
                "at": "evaluated",
                "one_second_above": {
                    "bounded": above["bounded"],
                    "useful_span_passed": above["useful_span_passed"],
                    "complete_interval": above["complete_interval"],
                },
            }
            cases[gain_name] = evaluated
        model_results.append(
            {
                **hypothesis,
                "structural_identifiability": structural[model_id],
                "gain_cases": cases,
            }
        )

    def gain_case_pass(case: dict[str, Any]) -> bool:
        return bool(
            case["bounded"]
            and case["useful_span_passed"]
            and case["held_out_prediction"].get("passed")
            and case["leave_one_complete_segment_out"][
                "all_nonempty_and_useful"
            ]
            and case["same_code_one_count_perturbations"][
                "all_nonempty_and_useful"
            ]
            and case["settling_boundary"]["one_second_above"]["bounded"]
            and case["settling_boundary"]["one_second_above"][
                "useful_span_passed"
            ]
        )

    eligible_models = [
        item["model_id"]
        for item in model_results
        if item["structural_identifiability"]["identifiable"]
        and all(gain_case_pass(case) for case in item["gain_cases"].values())
    ]
    any_nominal_nonempty = any(
        item["gain_cases"]["nominal"]["bounded"] for item in model_results
    )
    any_nominal_held_out = any(
        item["gain_cases"]["nominal"]["held_out_prediction"].get("passed", False)
        for item in model_results
    )
    every_structural = all(
        row["identifiable"] for row in structural.values()
    )
    temperature = _temperature_inventory(parent)
    provenance_pass = (
        len(stage5) == 18
        and len(attempt4) == 52
        and len({item.capture_session for item in stage5}) == 1
        and all(
            item.last_reference_sequence - item.first_reference_sequence
            == SUPPORT_SECONDS
            for item in (*stage5, *attempt4)
        )
    )

    gate_values = [
        (True, "all restored and original identities plus exact V1 baseline pass"),
        (
            every_structural,
            (
                "all three frozen structures have discriminating code/time/history evidence and finite parameter bounds"
                if every_structural
                else "at least one frozen model lacks discriminating code/time/history evidence"
            ),
        ),
        (
            any_nominal_nonempty,
            (
                "at least one nominal-gain complete identification set is nonempty"
                if any_nominal_nonempty
                else "all three nominal-gain complete identification sets are empty"
            ),
        ),
        (
            any_nominal_held_out,
            (
                "at least one nominal-gain frozen model covers all held-out Attempt 4 supports"
                if any_nominal_held_out
                else "no nominal-gain model with a nonempty identification set covers all held-out Attempt 4 supports"
            ),
        ),
        (
            bool(eligible_models),
            (
                "at least one model passes every frozen gain, perturbation, history, settling, and leave-one-segment-out case"
                if eligible_models
                else "no model passes every frozen gain, perturbation, history, settling, and leave-one-segment-out case"
            ),
        ),
        (
            bool(eligible_models),
            (
                "a fully sensitive model retains an at-most-18-code complete interval"
                if eligible_models
                else "no fully sensitive model retains an at-most-18-code complete interval"
            ),
        ),
        (
            bool(eligible_models),
            (
                "a fully sensitive model is decision-useful and materially narrower than 768 codes"
                if eligible_models
                else "no fully sensitive model is both decision-useful and materially narrower than 768 codes"
            ),
        ),
        (
            provenance_pass,
            (
                "all source, DAC epoch, D14 support, D8 count, and session identities reconstruct exactly"
                if provenance_pass
                else "at least one source, DAC epoch, D14 support, D8 count, or session identity failed reconstruction"
            ),
        ),
        (True, "raw phase is validation context only; no phase epoch is joined and D10 is excluded"),
        (True, "claim is restricted to retained finite evidence and creates no calibration or authority"),
    ]
    gate_rows = []
    first_failure: str | None = None
    for index, (name, (passed, reason)) in enumerate(
        zip(parent["feasibility_gate_order"], gate_values), start=1
    ):
        failure_id = None if passed else name
        if first_failure is None and failure_id is not None:
            first_failure = failure_id
        gate_rows.append(
            {
                "index": index,
                "gate": name,
                "passed": passed,
                "status": "passed" if passed else "failed",
                "reason": reason,
            }
        )
    all_passed = all(row["passed"] for row in gate_rows)
    terminal = OBSERVABLE_TERMINAL if all_passed else NOT_OBSERVABLE_TERMINAL
    first_failure = first_failure or "all_frozen_feasibility_checks_passed"

    report: dict[str, Any] = {
        "schema_version": 2,
        "report_type": REPORT_TYPE,
        "study_identity": parent["contract_id"],
        "attempt_id": contract["attempt_id"],
        "status": "complete_bounded_terminal",
        "terminal": terminal,
        "first_discriminating_failure": first_failure,
        "tool": {
            "tool_id": TOOL_ID,
            "path": str(Path(__file__).resolve().relative_to(REPO_ROOT)),
            "sha256": _file_sha256(Path(__file__)),
        },
        "contract": {
            "path": str(contract_path.relative_to(REPO_ROOT)),
            "contract_sha256": contract["contract_sha256"],
            "file_sha256": _file_sha256(contract_path),
            "parent_contract_semantic_sha256": parent["contract_sha256"],
        },
        "source_recovery": contract["source_recovery"],
        "source_identity_validation": {
            "all_required_exact": True,
            "bindings": binding_rows,
            "failures": [],
        },
        "predecessor_and_baseline_reproduction": predecessor,
        "evidence_inventory": {
            "plant_characterization": original._plant_inventory(parent),
            "stage5_identification_supports": [
                item.as_report_row() for item in stage5
            ],
            "attempt4_validation": original._attempt4_inventory(parent),
            "attempt4_held_out_supports": [
                item.as_report_row() for item in attempt4
            ],
            "temperature_context": temperature,
            "rapid_characterization": parent["evidence_partition"][
                "sensitivity_only"
            ],
            "excluded": parent["evidence_partition"]["excluded"],
        },
        "state_and_observation_semantics": parent[
            "state_and_observation_semantics"
        ],
        "evidence_partition": parent["evidence_partition"],
        "model_hypotheses": model_results,
        "nuisance_and_arithmetic_semantics": parent[
            "nuisance_and_arithmetic_semantics"
        ],
        "recovery_attempt_clarifications": contract[
            "recovery_attempt_clarifications"
        ],
        "sensitivity_cases": parent["sensitivity_cases"],
        "usefulness_gate": parent["usefulness_gate"],
        "uninformative_baseline": parent["uninformative_baseline"],
        "eligible_models_passing_every_frozen_gate": eligible_models,
        "feasibility_gate_checks": gate_rows,
        "decision": {
            "terminal": terminal,
            "first_discriminating_failure": first_failure,
            "equilibrium_interval_computed": True,
            "equilibrium_estimator_selected": False,
            "next_gate": "separately_authorize_one_prospectively_frozen_targeted_characterization",
        },
        "provenance_labels": {
            "observed": [
                "Stage 5 raw D14 reference, D8 cumulative count, DAC acknowledgement, and nearby-air records",
                "Attempt 4 selected supports, applications, DAC epochs, phase epoch, and nearby-air records",
            ],
            "reconstructed": [
                "eighteen exact Stage 5 600-second supports",
                "fifty-two exact-count Attempt 4 held-out supports",
                "predecessor comparators and V1 baseline",
            ],
            "derived": [
                "closed rational observation and equilibrium intervals",
                "exact linear-drift projections, coverage residuals, sensitivities, and gate rows",
            ],
            "bounded": [
                "finite-run gain cases, 1.91-code/hour drift, eight-code return dead zone, and 18-code usefulness limit",
            ],
            "modeled": [
                "constant, bounded-drift, and direction/history-conditioned equilibrium states",
            ],
        },
        "limitations": [
            "Recovered exact bytes validate the recorded plan identity but do not turn the dirty Stage 5 source revision into a clean commit.",
            "Gain, drift, hysteresis, repeatability, and temperature ranges are retained finite-run evidence, not calibrated or population uncertainty.",
            "The bounded-drift model has no frozen cross-session time origin and therefore cannot predict Attempt 4 without an unsupported extrapolation.",
            "SHT41 is nearby-air context, not CX317 internal temperature; no temperature coefficient is fitted.",
            "Attempt 4 remains a failed physical qualification because its contemporaneous response-replay attestations are absent.",
            "No raw phase epoch was joined, D10 was not used, and no physical boundary was exercised.",
        ],
        "authority": contract["authority"],
        "physical_actions_performed": 0,
    }
    report["report_sha256"] = _canonical_sha256(report)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--contract", type=Path, default=DEFAULT_CONTRACT)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    report = create_observability_report(args.contract)
    rendered = json.dumps(report, indent=2, sort_keys=True, allow_nan=False) + "\n"
    if args.output is not None:
        output = args.output.resolve()
        if output.exists():
            parser.error(f"refusing to overwrite immutable report: {output}")
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0 if report["status"] == "complete_bounded_terminal" else 2


if __name__ == "__main__":
    raise SystemExit(main())
