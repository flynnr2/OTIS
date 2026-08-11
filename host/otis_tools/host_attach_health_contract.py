"""Shared host-attach telemetry baseline semantics.

Ordinary cross-core telemetry is explicitly lossy diagnostic output. A
cumulative drop count already present when the host first attaches is retained
as a frozen baseline; every later increment is a runtime failure. Evidence,
capture, preview, partition, and control gates remain absolute.
"""

from __future__ import annotations

from typing import Iterable, Mapping

from .prewrite_readiness_contract import (
    Health,
    PrewriteHealthIntegrity,
    evaluate_health_integrity as _evaluate_health_integrity,
)


TELEMETRY_DROP_KEY = ("dual_core", "telemetry_dropped")
TELEMETRY_BASELINE_STABLE_OBSERVATIONS = 2
HOST_ATTACH_UPTIME_KEY = ("cx317_active", "uptime_s")
FRESH_HOST_ATTACH_MAXIMUM_UPTIME_S = 120


def evaluate_health_integrity(
    health: Health,
    *,
    telemetry_drop_baseline: int = 0,
) -> PrewriteHealthIntegrity:
    """Apply absolute health gates relative to one frozen attach baseline."""

    normalized = dict(health)
    observed = health.get(TELEMETRY_DROP_KEY)
    additional_missing: list[str] = []
    additional_mismatches: list[str] = []
    if observed is None:
        additional_missing.append("missing dual_core.telemetry_dropped")
    else:
        try:
            observed_value = int(observed)
        except ValueError:
            additional_mismatches.append(
                "dual_core.telemetry_dropped="
                f"{observed!r}, expected unsigned integer"
            )
        else:
            if observed_value < 0:
                additional_mismatches.append(
                    "dual_core.telemetry_dropped="
                    f"{observed!r}, expected unsigned integer"
                )
            elif observed_value != telemetry_drop_baseline:
                additional_mismatches.append(
                    "dual_core.telemetry_dropped="
                    f"{observed!r}, expected frozen host-attach baseline "
                    f"{telemetry_drop_baseline}"
                )
        normalized[TELEMETRY_DROP_KEY] = "0"
    base = _evaluate_health_integrity(normalized)
    missing = tuple(dict.fromkeys((*base.missing, *additional_missing)))
    mismatches = tuple(
        dict.fromkeys((*base.mismatches, *additional_mismatches))
    )
    return PrewriteHealthIntegrity(
        clean=not missing and not mismatches,
        missing=missing,
        mismatches=mismatches,
    )


def telemetry_drop_observations(
    rows: Iterable[Mapping[str, str]],
) -> list[tuple[int, int]]:
    """Return ordered ``(status_seq, cumulative_drop_count)`` observations."""

    observations: list[tuple[int, int]] = []
    for row in rows:
        if (
            row.get("record_type") != "STS"
            or row.get("component") != TELEMETRY_DROP_KEY[0]
            or row.get("status_key") != TELEMETRY_DROP_KEY[1]
        ):
            continue
        try:
            status_seq = int(row.get("status_seq", ""))
            value = int(row.get("status_value", ""))
        except ValueError as exc:
            raise ValueError(
                "malformed dual_core.telemetry_dropped observation"
            ) from exc
        if status_seq <= 0 or value < 0:
            raise ValueError(
                "dual_core.telemetry_dropped observation must have positive "
                "status_seq and unsigned value"
            )
        observations.append((status_seq, value))
    return observations


def host_attach_uptime_observations(
    rows: Iterable[Mapping[str, str]],
) -> list[tuple[int, int]]:
    """Return ordered firmware uptimes observed after the host attached."""

    observations: list[tuple[int, int]] = []
    for row in rows:
        if (
            row.get("record_type") != "STS"
            or row.get("component") != HOST_ATTACH_UPTIME_KEY[0]
            or row.get("status_key") != HOST_ATTACH_UPTIME_KEY[1]
        ):
            continue
        try:
            status_seq = int(row.get("status_seq", ""))
            uptime_s = int(row.get("status_value", ""))
        except ValueError as exc:
            raise ValueError(
                "malformed cx317_active.uptime_s observation"
            ) from exc
        if status_seq <= 0 or uptime_s < 0:
            raise ValueError(
                "cx317_active.uptime_s observation must have positive "
                "status_seq and unsigned uptime"
            )
        observations.append((status_seq, uptime_s))
    return observations


def evaluate_host_attach_history(
    rows: Iterable[Mapping[str, str]],
    *,
    frozen_uptime_s: int,
    frozen_status_seq: int,
) -> dict[str, object]:
    """Prove that the retained attach record is the first firmware uptime."""

    observations = host_attach_uptime_observations(rows)
    status_sequences = [status_seq for status_seq, _ in observations]
    uptimes = [uptime_s for _, uptime_s in observations]
    first = observations[0] if observations else None
    status_sequences_strictly_increasing = all(
        later > earlier
        for earlier, later in zip(status_sequences, status_sequences[1:])
    )
    uptimes_nondecreasing = all(
        later >= earlier for earlier, later in zip(uptimes, uptimes[1:])
    )
    exact = (
        frozen_uptime_s >= 0
        and frozen_uptime_s <= FRESH_HOST_ATTACH_MAXIMUM_UPTIME_S
        and frozen_status_seq > 0
        and first == (frozen_status_seq, frozen_uptime_s)
        and status_sequences_strictly_increasing
        and uptimes_nondecreasing
    )
    return {
        "exact": exact,
        "frozen_uptime_s": frozen_uptime_s,
        "frozen_status_seq": frozen_status_seq,
        "maximum_uptime_s": FRESH_HOST_ATTACH_MAXIMUM_UPTIME_S,
        "observation_count": len(observations),
        "first_observation": (
            None
            if first is None
            else {"status_seq": first[0], "uptime_s": first[1]}
        ),
        "status_sequences_strictly_increasing": (
            status_sequences_strictly_increasing
        ),
        "uptimes_nondecreasing": uptimes_nondecreasing,
        "first_observation_matches_frozen_record": (
            first == (frozen_status_seq, frozen_uptime_s)
        ),
        "within_fresh_host_attach_limit": (
            0 <= frozen_uptime_s <= FRESH_HOST_ATTACH_MAXIMUM_UPTIME_S
        ),
    }


def evaluate_telemetry_drop_history(
    rows: Iterable[Mapping[str, str]],
    *,
    frozen_baseline: int,
    frozen_status_seq: int,
) -> dict[str, object]:
    """Prove the baseline was stable at freeze and never advanced afterward."""

    observations = telemetry_drop_observations(rows)
    status_sequences = [status_seq for status_seq, _ in observations]
    values = [value for _, value in observations]
    status_sequences_strictly_increasing = all(
        later > earlier
        for earlier, later in zip(status_sequences, status_sequences[1:])
    )
    nondecreasing = all(
        later >= earlier for earlier, later in zip(values, values[1:])
    )
    post_freeze = [
        value
        for status_seq, value in observations
        if status_seq >= frozen_status_seq
    ]
    freeze_index = next(
        (
            index
            for index, (status_seq, _value) in enumerate(observations)
            if status_seq == frozen_status_seq
        ),
        None,
    )
    stable_before_freeze = (
        freeze_index is not None
        and freeze_index >= TELEMETRY_BASELINE_STABLE_OBSERVATIONS - 1
        and all(
            observations[index][1] == frozen_baseline
            for index in range(
                freeze_index - TELEMETRY_BASELINE_STABLE_OBSERVATIONS + 1,
                freeze_index + 1,
            )
        )
    )
    exact = (
        frozen_baseline >= 0
        and frozen_status_seq > 0
        and status_sequences_strictly_increasing
        and nondecreasing
        and stable_before_freeze
        and bool(post_freeze)
        and all(value == frozen_baseline for value in post_freeze)
    )
    return {
        "exact": exact,
        "frozen_baseline": frozen_baseline,
        "frozen_status_seq": frozen_status_seq,
        "observation_count": len(observations),
        "observations": [
            {"status_seq": status_seq, "value": value}
            for status_seq, value in observations
        ],
        "status_sequences_strictly_increasing": (
            status_sequences_strictly_increasing
        ),
        "nondecreasing_before_freeze": nondecreasing,
        "stable_observations_required": TELEMETRY_BASELINE_STABLE_OBSERVATIONS,
        "stable_before_freeze": stable_before_freeze,
        "no_increment_after_freeze": (
            bool(post_freeze)
            and all(value == frozen_baseline for value in post_freeze)
        ),
    }


__all__ = [
    "FRESH_HOST_ATTACH_MAXIMUM_UPTIME_S",
    "HOST_ATTACH_UPTIME_KEY",
    "TELEMETRY_BASELINE_STABLE_OBSERVATIONS",
    "TELEMETRY_DROP_KEY",
    "evaluate_host_attach_history",
    "evaluate_health_integrity",
    "evaluate_telemetry_drop_history",
    "host_attach_uptime_observations",
    "telemetry_drop_observations",
]
