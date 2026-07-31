from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from host.otis_tools.pps_snapshot_reconstruction import (
    ReconstructionPolicy,
    SnapshotObservation,
    SnapshotReconstructor,
    SnapshotSequenceRelation,
    down_counter_delta_u32,
    reconstruct_snapshots,
    snapshot_sequence_relation_u32,
)


FIXTURE = Path(
    "tests/fixtures/pps_snapshot_reconstruction/scenarios_v1.json"
)


def _fixture() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _policy(value: dict) -> ReconstructionPolicy:
    return ReconstructionPolicy(**value)


def _observation(value: dict) -> SnapshotObservation:
    materialized = dict(value)
    materialized["capture_faults"] = tuple(
        materialized.get("capture_faults", ())
    )
    return SnapshotObservation(**materialized)


def test_fixture_scenarios_encode_fail_closed_reconstruction() -> None:
    fixture = _fixture()
    assert fixture["schema_version"] == 1
    policy = _policy(fixture["policy"])

    for case in fixture["cases"]:
        results = reconstruct_snapshots(
            (_observation(value) for value in case["observations"]), policy
        )
        assert [result.state for result in results] == case["expected_states"], case[
            "id"
        ]
        assert [result.interval_count for result in results] == case[
            "expected_counts"
        ], case["id"]
        if "expected_reason" in case:
            assert any(
                case["expected_reason"] in result.reasons for result in results
            ), case["id"]


def test_down_counter_delta_and_sequence_wrap_are_central_and_explicit() -> None:
    ordinary = down_counter_delta_u32(1000, 900)
    wrapped = down_counter_delta_u32(5, 0xFFFFFFF5)

    assert ordinary.count == 100
    assert not ordinary.wrap_handled
    assert wrapped.count == 16
    assert wrapped.wrap_handled
    assert (
        snapshot_sequence_relation_u32(0xFFFFFFFF, 0)
        is SnapshotSequenceRelation.ADJACENT
    )
    assert (
        snapshot_sequence_relation_u32(7, 7)
        is SnapshotSequenceRelation.DUPLICATE
    )
    assert (
        snapshot_sequence_relation_u32(7, 9)
        is SnapshotSequenceRelation.GAP_OR_OUT_OF_ORDER
    )


def test_first_boundary_is_anchor_only_and_sequence_wrap_emits_next_interval() -> None:
    reconstructor = SnapshotReconstructor(
        ReconstructionPolicy(10_000_000.0, 16_000_000.0)
    )
    first = reconstructor.observe(
        SnapshotObservation(0xFFFFFFFF, "s1", 5, 16_000_000)
    )
    second = reconstructor.observe(
        SnapshotObservation(0, "s1", 0xFFFFFFF5, 32_000_000)
    )

    assert first.anchor_only
    assert first.reasons == ("first_anchor",)
    assert second.valid
    assert second.interval_count == 16
    assert second.sequence_wrap_handled
    assert second.counter_wrap_handled


def test_capture_fault_clears_anchor_and_requires_two_clean_snapshots() -> None:
    reconstructor = SnapshotReconstructor(
        ReconstructionPolicy(10_000_000.0, 16_000_000.0)
    )
    results = [
        reconstructor.observe(SnapshotObservation(1, "s1", 1000, 16_000_000)),
        reconstructor.observe(
            SnapshotObservation(
                2,
                "s1",
                900,
                32_000_000,
                capture_valid=False,
                capture_faults=("ring_overwrite",),
            )
        ),
        reconstructor.observe(SnapshotObservation(3, "s1", 800, 48_000_000)),
        reconstructor.observe(SnapshotObservation(4, "s1", 700, 64_000_000)),
    ]

    assert [result.state for result in results] == [
        "anchor",
        "invalid",
        "anchor",
        "valid",
    ]
    assert results[1].reasons == ("capture_invalid", "ring_overwrite")
    assert results[2].reasons == ("reacquisition_anchor",)
    assert results[3].interval_count == 100


def test_sequence_loss_invalidates_pair_but_current_clean_snapshot_reanchors() -> None:
    reconstructor = SnapshotReconstructor(
        ReconstructionPolicy(10_000_000.0, 16_000_000.0)
    )
    first = reconstructor.observe(
        SnapshotObservation(10, "s1", 1000, 16_000_000)
    )
    lost = reconstructor.observe(
        SnapshotObservation(12, "s1", 800, 48_000_000)
    )
    recovered = reconstructor.observe(
        SnapshotObservation(13, "s1", 700, 64_000_000)
    )

    assert first.anchor_only
    assert not lost.valid
    assert lost.reasons == ("snapshot_sequence_gap_or_out_of_order",)
    assert recovered.valid
    assert recovered.opening_sequence == 12
    assert recovered.interval_count == 100


@pytest.mark.parametrize(
    ("closing_reference_sequence", "expected_reason"),
    [
        (20, "reference_sequence_duplicate"),
        (22, "reference_sequence_gap_or_out_of_order"),
    ],
)
def test_reference_sequence_must_be_adjacent_to_snapshot_association(
    closing_reference_sequence: int, expected_reason: str
) -> None:
    results = reconstruct_snapshots(
        (
            SnapshotObservation(1, "s1", 1000, 16_000_000, 20),
            SnapshotObservation(
                2,
                "s1",
                900,
                32_000_000,
                closing_reference_sequence,
            ),
        ),
        ReconstructionPolicy(16_000_000.0, 16_000_000.0),
    )

    assert results[0].anchor_only
    assert not results[1].valid
    assert results[1].reasons == (expected_reason,)


def test_session_change_never_bridges_old_and_new_counters() -> None:
    results = reconstruct_snapshots(
        (
            SnapshotObservation(100, "old", 1000, 16_000_000),
            SnapshotObservation(101, "old", 900, 32_000_000),
            SnapshotObservation(0, "new", 0xFFFFFFFF, 48_000_000),
            SnapshotObservation(1, "new", 0xFFFFFF9B, 64_000_000),
        ),
        ReconstructionPolicy(10_000_000.0, 16_000_000.0),
    )

    assert [result.state for result in results] == [
        "anchor",
        "valid",
        "anchor",
        "valid",
    ]
    assert results[2].reasons == ("session_boundary",)
    assert results[3].interval_count == 100


def test_full_wrap_envelope_is_rejected_at_the_policy_boundary() -> None:
    ticks_per_second = 16_000_000.0
    max_hz = 10_000_000.0
    threshold_ticks = math.ceil((1 << 32) * ticks_per_second / max_hz)
    policy = ReconstructionPolicy(max_hz, ticks_per_second)

    result = reconstruct_snapshots(
        (
            SnapshotObservation(1, "s1", 1000, 0),
            SnapshotObservation(2, "s1", 900, threshold_ticks),
        ),
        policy,
    )[-1]

    assert not result.valid
    assert result.interval_count is None
    assert result.reasons == ("counter_full_wrap_cannot_be_excluded",)


def test_reference_timer_wrap_is_handled_only_with_an_explicit_modulus() -> None:
    modulus = (1 << 32) * 16
    results = reconstruct_snapshots(
        (
            SnapshotObservation(1, "s1", 1000, modulus - 8_000_000),
            SnapshotObservation(2, "s1", 900, 8_000_000),
        ),
        ReconstructionPolicy(
            10_000_000.0, 16_000_000.0, timestamp_modulus=modulus
        ),
    )

    assert results[-1].valid
    assert results[-1].elapsed_reference_ticks == 16_000_000
    assert results[-1].timestamp_wrap_handled


def test_foreground_delay_does_not_change_snapshot_counts_or_validity() -> None:
    policy = ReconstructionPolicy(10_000_000.0, 16_000_000.0)
    immediate = (
        SnapshotObservation(1, "s1", 1000, 16_000_000, foreground_arrival_ticks=16_000_010),
        SnapshotObservation(2, "s1", 900, 32_000_000, foreground_arrival_ticks=32_000_010),
        SnapshotObservation(3, "s1", 800, 48_000_000, foreground_arrival_ticks=48_000_010),
    )
    delayed = (
        SnapshotObservation(1, "s1", 1000, 16_000_000, foreground_arrival_ticks=200_000_000),
        SnapshotObservation(2, "s1", 900, 32_000_000, foreground_arrival_ticks=500_000_000),
        SnapshotObservation(3, "s1", 800, 48_000_000, foreground_arrival_ticks=900_000_000),
    )

    assert reconstruct_snapshots(immediate, policy) == reconstruct_snapshots(
        delayed, policy
    )


@pytest.mark.parametrize("value", [-1, 1 << 32, True])
def test_unsigned_32_bit_snapshot_fields_are_validated(value: int) -> None:
    with pytest.raises(ValueError):
        SnapshotObservation(value, "s1", 0, 0)
