"""Exact retained APS reconstruction from canonical REF, SNP, and CNT rows."""
from __future__ import annotations

from typing import Any

from .raw_measurement_replay import (
    _RAW_REFERENCE_DOMAIN,
    _U32_MODULUS,
    _ordered_reference_association,
    _raw_count_replay,
    _u32,
)

POLICY_PATH = "data_contracts/reference_acceptance_policy_v1.json"
POLICY_ID = "otis_d14_accepted_reference_v1"


def _policy_values(policy: dict[str, Any]) -> tuple[int, int, int, int, int]:
    if (
        policy.get("policy_id") != POLICY_ID
        or policy.get("schema_version") != 1
        or policy.get("admission_coordinate_domain") != _RAW_REFERENCE_DOMAIN
        or policy.get("reference_pin") != "D14"
        or policy.get("count_pin") != "D8"
        or policy.get("rejected_candidate_moves_anchor") is not False
        or policy.get("rejected_candidate_extends_expiry") is not False
        or policy.get("missing_reference_requires_new_acceptance_epoch") is not True
        or policy.get("qualification_may_sum_acceptance_epochs") is not False
        or policy.get("raw_observations_preserved") is not True
        or policy.get("control_authority") is not False
        or policy.get("acquisition_intervals") != 8
    ):
        raise ValueError("frozen acceptance policy semantics differ")
    numeric = tuple(policy.get(name) for name in (
        "nominal_interval_ticks", "tolerance_ticks",
        "maximum_excluded_candidates_per_span",
        "nominal_intervals_per_accepted_span", "maximum_edge_rate_hz",
        "maximum_count_span_ticks",
    ))
    if not all(type(value) is int and value >= 0 for value in numeric):
        raise ValueError("frozen acceptance policy numerical values are malformed")
    nominal, tolerance, excluded, intervals, edge_rate, maximum_ticks = numeric
    if (
        min(nominal, tolerance, intervals, edge_rate, maximum_ticks) <= 0
        or intervals != 1
        or edge_rate * maximum_ticks // 1_000_000 >= _U32_MODULUS
    ):
        raise ValueError("frozen acceptance policy numerical values are not positive")
    return (
        nominal - tolerance, nominal + tolerance, excluded, intervals,
        edge_rate * maximum_ticks // 1_000_000,
    )


def accepted_span_ref(session: int, epoch: int, ordinal: int) -> str:
    return f"live:APS:{session}:{epoch}:{ordinal}"


def accepted_window_ref(session: int, epoch: int, opening: int, closing: int) -> str:
    return f"live:APS:{session}:{epoch}:{opening}:{closing}"


def replay_accepted_spans(
    snapshots: list[dict[str, str]], references: list[dict[str, str]],
    counts: list[dict[str, str]], spans: list[dict[str, str]], *,
    acceptance_policy: dict[str, Any], acceptance_policy_sha256: str,
) -> tuple[bool, dict[str, Any], list[dict[str, Any]]]:
    """Verify retained APS rows without claiming recorder-missed acquisition."""

    errors: list[str] = []
    verified: list[dict[str, Any]] = []
    horizon: dict[str, Any] | None = None
    raw_report: dict[str, Any] = {
        "exact": False,
        "errors": ["raw count replay did not run"],
        "error_count": 1,
    }
    try:
        lower, upper, maximum_excluded, nominal_intervals, maximum_edges = (
            _policy_values(acceptance_policy)
        )
        if (
            not isinstance(acceptance_policy_sha256, str)
            or len(acceptance_policy_sha256) != 64
            or any(c not in "0123456789abcdef" for c in acceptance_policy_sha256)
        ):
            raise ValueError("frozen acceptance-policy SHA-256 is malformed")
        if not spans:
            raise ValueError("accepted PPS span source is empty")
        raw_exact, raw_report, raw_intervals = _raw_count_replay(
            snapshots, references, counts
        )
        if not raw_exact:
            raise ValueError(
                "adjacent raw source does not reconstruct: "
                + "; ".join(raw_report["errors"])
            )
        associations = _ordered_reference_association(snapshots, references)
        positions: dict[tuple[int, int, int], list[int]] = {}
        interval_by_closing: dict[int, dict[str, Any]] = {}
        interval_index = 0
        previous_session: int | None = None
        for index, snapshot in enumerate(snapshots):
            session = _u32(snapshot, "session")
            positions.setdefault((
                session, _u32(snapshot, "snapshot_sequence"),
                _u32(snapshot, "reference_timestamp_ticks"),
            ), []).append(index)
            if previous_session == session:
                if interval_index >= len(raw_intervals):
                    raise ValueError("raw interval positioning is incomplete")
                interval_by_closing[index] = raw_intervals[interval_index]
                interval_index += 1
            previous_session = session
        if interval_index != len(raw_intervals):
            raise ValueError("raw interval positioning is contradictory")

        previous_identity: tuple[int, int, int] | None = None
        previous_closing: tuple[int, int, int, int] | None = None
        seen: set[tuple[int, int, int]] = set()
        for row_number, row in enumerate(spans, start=1):
            if row.get("record_type") != "APS" or row.get("schema_version") != "1":
                raise ValueError(f"APS row {row_number} has the wrong record contract")
            names = (
                "capture_session", "acceptance_epoch", "accepted_boundary_ordinal",
                "opening_snapshot_sequence", "closing_snapshot_sequence",
                "opening_reference_sequence", "closing_reference_sequence",
                "opening_reference_timestamp_ticks", "closing_reference_timestamp_ticks",
                "source_count_first_sequence", "source_count_last_sequence",
                "source_count_record_count", "excluded_candidate_count",
                "nominal_interval_count",
            )
            values = {name: _u32(row, name) for name in names}
            counted_edges = int(row["counted_edges"])
            if not 0 < counted_edges <= maximum_edges:
                raise ValueError(f"APS row {row_number} count exceeds the physical bound")
            identity = (
                values["capture_session"], values["acceptance_epoch"],
                values["accepted_boundary_ordinal"],
            )
            if identity[0] == 0 or identity[1] == 0 or identity in seen:
                raise ValueError(f"APS row {row_number} identity is invalid or duplicated")
            seen.add(identity)
            if row.get("time_domain") != _RAW_REFERENCE_DOMAIN:
                raise ValueError(f"APS row {row_number} time domain differs")
            if row.get("acceptance_policy_sha256") != acceptance_policy_sha256:
                raise ValueError(f"APS row {row_number} policy identity differs")
            excluded = values["excluded_candidate_count"]
            source_count = values["source_count_record_count"]
            if (
                excluded > maximum_excluded
                or source_count != excluded + 1
                or values["nominal_interval_count"] != nominal_intervals
            ):
                raise ValueError(f"APS row {row_number} span cardinality differs")
            opening_key = (
                identity[0], values["opening_snapshot_sequence"],
                values["opening_reference_timestamp_ticks"],
            )
            closing_key = (
                identity[0], values["closing_snapshot_sequence"],
                values["closing_reference_timestamp_ticks"],
            )
            opening_positions = positions.get(opening_key, [])
            closing_positions = positions.get(closing_key, [])
            if len(closing_positions) != 1:
                raise ValueError(f"APS row {row_number} has no unique retained closing SNP")
            closing_position = closing_positions[0]
            if len(opening_positions) != 1:
                if row_number != 1 or opening_positions:
                    raise ValueError(f"APS row {row_number} has no unique retained opening SNP")
                closing_snapshot = snapshots[closing_position]
                closing_ref = references[associations[closing_position]]
                if (
                    _u32(closing_snapshot, "reference_sequence")
                    != values["closing_reference_sequence"]
                    or _u32(closing_ref, "timestamp_ticks")
                    != values["closing_reference_timestamp_ticks"]
                ):
                    raise ValueError("late-attach APS closing evidence is contradictory")
                horizon = {
                    "capture_session": identity[0], "acceptance_epoch": identity[1],
                    "accepted_boundary_ordinal": identity[2],
                    "closing_snapshot_sequence": values["closing_snapshot_sequence"],
                    "closing_reference_sequence": values["closing_reference_sequence"],
                    "closing_reference_timestamp_ticks": values["closing_reference_timestamp_ticks"],
                    "disposition": "producer_declared_late_attach_horizon",
                }
                previous_identity = identity
                previous_closing = (
                    identity[0], values["closing_snapshot_sequence"],
                    values["closing_reference_sequence"],
                    values["closing_reference_timestamp_ticks"],
                )
                continue
            opening_position = opening_positions[0]
            if closing_position - opening_position != source_count:
                raise ValueError(f"APS row {row_number} raw source range is incomplete")
            interval_positions = range(opening_position + 1, closing_position + 1)
            source_intervals = [interval_by_closing[position] for position in interval_positions]
            source_snapshots = snapshots[opening_position : closing_position + 1]
            source_refs = [references[associations[index]] for index in range(
                opening_position, closing_position + 1
            )]
            allowed_flags = int(acceptance_policy["allowed_reference_flags"])
            if any(
                _u32(snapshot, "status") != 0
                or _u32(reference, "flags") & ~allowed_flags
                for snapshot, reference in zip(source_snapshots, source_refs)
            ):
                raise ValueError(f"APS row {row_number} bridges a capture-integrity fault")
            if not all(item["count_exact"] for item in source_intervals):
                raise ValueError(f"APS row {row_number} raw CNT range is not exact")
            opening_snapshot, closing_snapshot = source_snapshots[0], source_snapshots[-1]
            opening_ref, closing_ref = source_refs[0], source_refs[-1]
            if (
                _u32(opening_snapshot, "reference_sequence") != values["opening_reference_sequence"]
                or _u32(closing_snapshot, "reference_sequence") != values["closing_reference_sequence"]
                or _u32(opening_ref, "timestamp_ticks") != values["opening_reference_timestamp_ticks"]
                or _u32(closing_ref, "timestamp_ticks") != values["closing_reference_timestamp_ticks"]
                or values["source_count_first_sequence"] != source_intervals[0]["closing_sequence"]
                or values["source_count_last_sequence"] != source_intervals[-1]["closing_sequence"]
            ):
                raise ValueError(f"APS row {row_number} raw endpoint identity differs")
            interval_ticks = (
                values["closing_reference_timestamp_ticks"]
                - values["opening_reference_timestamp_ticks"]
            ) % _U32_MODULUS
            if not lower <= interval_ticks <= upper:
                raise ValueError(f"APS row {row_number} admission interval differs")
            opening_ticks = values["opening_reference_timestamp_ticks"]
            for intermediate in source_refs[1:-1]:
                candidate_ticks = (
                    _u32(intermediate, "timestamp_ticks") - opening_ticks
                ) % _U32_MODULUS
                if candidate_ticks >= lower:
                    raise ValueError(
                        f"APS row {row_number} excludes a candidate at or after the acceptance window"
                    )
            if sum(item["counted_edges"] for item in source_intervals) != counted_edges:
                raise ValueError(f"APS row {row_number} raw CNT sum differs")
            endpoint_edges = (
                _u32(opening_snapshot, "cumulative_down_counter")
                - _u32(closing_snapshot, "cumulative_down_counter")
            ) % _U32_MODULUS
            if endpoint_edges != counted_edges:
                raise ValueError(f"APS row {row_number} cumulative endpoint count differs")
            if previous_identity is not None:
                old_session, old_epoch, old_ordinal = previous_identity
                if identity[:2] == (old_session, old_epoch):
                    if identity[2] != (old_ordinal + 1) % _U32_MODULUS:
                        raise ValueError(f"APS row {row_number} accepted ordinal is discontinuous")
                    expected_opening = (
                        identity[0], values["opening_snapshot_sequence"],
                        values["opening_reference_sequence"],
                        values["opening_reference_timestamp_ticks"],
                    )
                    if previous_closing != expected_opening:
                        raise ValueError(
                            f"APS row {row_number} does not open at the previous accepted boundary"
                        )
                elif identity[0] == old_session and identity[1] <= old_epoch:
                    raise ValueError(f"APS row {row_number} acceptance epoch moved backward")
            verified.append({
                **values, "counted_edges": counted_edges,
                "interval_ticks": interval_ticks,
                "source_first_snapshot_position": opening_position,
                "source_last_snapshot_position": closing_position,
                "source_exact": True,
            })
            previous_identity = identity
            previous_closing = (
                identity[0], values["closing_snapshot_sequence"],
                values["closing_reference_sequence"],
                values["closing_reference_timestamp_ticks"],
            )
    except (KeyError, TypeError, ValueError) as error:
        errors.append(str(error))
    exact = not errors and bool(verified)
    return exact, {
        "exact": exact, "accepted_span_count": len(verified),
        "late_attach_horizon": horizon,
        "acceptance_policy_sha256": acceptance_policy_sha256,
        "raw_count_replay": raw_report,
        "raw_and_full_csv_preserved": True,
        "errors": errors[:20], "error_count": len(errors),
    }, verified
