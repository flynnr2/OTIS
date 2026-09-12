"""PPS status cohorts must not merge a partial publication with an old one."""
from __future__ import annotations

import csv
from copy import deepcopy
from io import StringIO
from pathlib import Path
from types import SimpleNamespace

import pytest

from host.otis_tools.active_status_live_state import (
    ActiveStatusLiveReducer,
    read_live_health_state,
)
from host.otis_tools.adaptive_hybrid_contract import (
    ADAPTIVE_HYBRID_PROGRAMME,
    INHIBITED_ZERO_WRITE,
)
from host.otis_tools.adaptive_hybrid_supervisor import (
    AdaptiveHybridSupervisor,
    _authoritative_capture_health_faults,
)
from host.otis_tools.capture_device import ActiveStatusLivePublisher
from host.otis_tools.contracts import HEALTH_FIELDS
from tests.runtime_fixtures import construct_simulated_supervisor

FIXTURE = (
    Path(__file__).parent
    / "fixtures/startup_census_539ff6a/health_records.csv"
)
ACTIVE_END = 699
QUERY_NONCE = 1_312_243_200
U32_MODULUS = 1 << 32


def _fixture_rows() -> list[dict[str, str]]:
    with FIXTURE.open(newline="", encoding="utf-8") as stream:
        rows = list(csv.DictReader(stream))
    # This retained compact fixture preserves its raw ``+record_type`` header.
    for row in rows:
        row["record_type"] = row.pop("+record_type")
    return rows


def _line(row: dict[str, str]) -> str:
    stream = StringIO()
    writer = csv.DictWriter(stream, fieldnames=HEALTH_FIELDS)
    writer.writerow(row)
    return stream.getvalue().rstrip("\r\n")


def _pps_rows(generation: int, *, sequence_base: int, anchor_ticks: int) -> list[dict[str, str]]:
    source = [
        deepcopy(row)
        for row in _fixture_rows()
        if row["component"] == "pps_gate"
    ]
    assert source and source[0]["status_key"] == "snapshot"
    assert source[-1]["status_key"] == "startup_inhibit_active"
    for offset, row in enumerate(source):
        row["status_seq"] = str(sequence_base + offset)
        row["timestamp_ticks"] = str((anchor_ticks + offset) % U32_MODULUS)
        if row["status_key"] == "snapshot_generation":
            row["status_value"] = str(generation)
        elif row["status_key"] == "accepted_anchor_timestamp_ticks":
            row["status_value"] = str(anchor_ticks)
    return source


def _active_rows(
    generation: int, *, sequence_base: int, frontier_ticks: int
) -> list[dict[str, str]]:
    source = [
        deepcopy(row)
        for row in _fixture_rows()
        if row["component"] == "adaptive_hybrid"
        and int(row["status_seq"]) <= ACTIVE_END
        and int(row["status_seq"]) >= 648
    ]
    assert source and source[0]["status_key"] == "snapshot_generation_begin"
    assert source[-1]["status_key"] == "snapshot_generation_complete"
    for offset, row in enumerate(source):
        row["status_seq"] = str(sequence_base + offset)
        row["timestamp_ticks"] = str((frontier_ticks + offset) % U32_MODULUS)
        if row["status_key"] in {
            "snapshot_generation_begin",
            "snapshot_generation_complete",
        }:
            row["status_value"] = str(generation)
    return source


def _publish(publisher: ActiveStatusLivePublisher, rows: list[dict[str, str]]) -> None:
    for row in rows:
        publisher.process_line(_line(row), transport_generation=1)


def _health(publisher: ActiveStatusLivePublisher) -> dict[tuple[str, str], str]:
    selection = read_live_health_state(
        publisher.path, required_query_nonce=QUERY_NONCE
    )
    return selection.health if selection.state == "complete" else {}


def _supervisor(tmp_path: Path, health: dict[tuple[str, str], str]) -> AdaptiveHybridSupervisor:
    subject = construct_simulated_supervisor(tmp_path, purpose=INHIBITED_ZERO_WRITE)
    subject.spec = SimpleNamespace(
        campaign="adaptive_hybrid_regulation",
        run_identity=health[("adaptive_hybrid", "run_identity")],
        profile=health[("adaptive_hybrid", "image_identity")],
        start_code=ADAPTIVE_HYBRID_PROGRAMME.setup_code,
        correction_limit=0,
        cumulative_limit=0,
    )
    subject.identities = {
        key: health[("adaptive_hybrid", key)]
        for key in (
            "estimator_sha256",
            "model_sha256",
            "active_policy_sha256",
            "response_policy_sha256",
            "numerical_policy_sha256",
        )
    }
    subject.expected_build_identity = health[("adaptive_hybrid", "build_identity")]
    subject.reference_acceptance_policy_sha256 = health[
        ("adaptive_hybrid", "reference_acceptance_policy_sha256")
    ]
    subject._save = lambda: None
    subject._programme_event = lambda *_args, **_kwargs: None
    return subject


def test_partial_pps_generation_cannot_merge_old_tail_into_zero_write_authority(
    tmp_path: Path,
) -> None:
    """Begin/end without required middle rows is non-authoritative."""
    publisher = ActiveStatusLivePublisher(tmp_path)
    _publish(publisher, _pps_rows(4, sequence_base=10_000, anchor_ticks=10_000_000))
    _publish(publisher, _active_rows(2, sequence_base=20_000, frontier_ticks=11_000_000))
    healthy = _health(publisher)
    assert healthy
    assert not _authoritative_capture_health_faults(healthy)

    # These are a concrete adverse G5: its changed continuity state and
    # discontinuity counters never reach capture, while begin/end do.
    partial = _pps_rows(5, sequence_base=30_000, anchor_ticks=12_000_000)
    for row in partial:
        if row["status_key"] == "fifo_continuity":
            row["status_value"] = "unavailable"
        elif row["status_key"] == "association_state":
            row["status_value"] = "lost"
        elif row["status_key"] in {
            "association_loss_count",
            "physical_aperture_incomplete_count",
        }:
            row["status_value"] = "1"
    partial = [
        row
        for row in partial
        if row["status_key"]
        not in {
            "fifo_continuity",
            "association_state",
            "association_loss_count",
            "physical_aperture_incomplete_count",
        }
    ]
    _publish(publisher, partial)
    _publish(publisher, _active_rows(3, sequence_base=40_000, frontier_ticks=13_000_000))
    mixed = _health(publisher)

    assert mixed == {} or _authoritative_capture_health_faults(mixed)
    subject = _supervisor(tmp_path / "supervisor", healthy)
    subject._maybe_establish_zero_write_aperture_origin(mixed)
    assert subject.state["qualification_started_utc"] is None


def test_pps_cohort_releases_only_after_its_complete_generation(tmp_path: Path) -> None:
    publisher = ActiveStatusLivePublisher(tmp_path)
    full = _pps_rows(5, sequence_base=30_000, anchor_ticks=12_000_000)
    end_index = next(
        index for index, row in enumerate(full) if row["status_key"] == "snapshot" and row["status_value"] == "end"
    )
    reducer = ActiveStatusLiveReducer()
    updates = [
        update
        for row in full[:end_index]
        if (update := reducer.observe(row)) is not None
    ]
    assert updates[-1]["state"] == "in_progress"
    _publish(publisher, full[:end_index])

    _publish(publisher, full[end_index:])
    _publish(publisher, _active_rows(3, sequence_base=50_000, frontier_ticks=13_100_000))
    health = _health(publisher)
    assert health
    assert not _authoritative_capture_health_faults(health)
    subject = _supervisor(tmp_path / "supervisor", health)
    subject._maybe_establish_zero_write_aperture_origin(health)
    assert subject.state["qualification_started_utc"] is not None


@pytest.mark.parametrize("next_generation", [4, 3])
def test_duplicate_or_out_of_order_pps_generation_invalidates_live_reduction(
    next_generation: int,
) -> None:
    reducer = ActiveStatusLiveReducer()
    first = _pps_rows(4, sequence_base=10_000, anchor_ticks=10_000_000)
    second = _pps_rows(next_generation, sequence_base=20_000, anchor_ticks=11_000_000)
    updates = []
    for row in [*first, *second]:
        update = reducer.observe(row)
        if update is not None:
            updates.append(update)
    assert updates
    assert updates[-1]["state"] == "invalid"


def test_complete_pps_cohort_allows_existing_producer_tick_wrap_bound(
    tmp_path: Path,
) -> None:
    """Cohort handling must preserve the existing uint32 freshness relation."""
    publisher = ActiveStatusLivePublisher(tmp_path)
    anchor = U32_MODULUS - 700_000
    _publish(publisher, _pps_rows(7, sequence_base=10_000, anchor_ticks=anchor))
    _publish(publisher, _active_rows(2, sequence_base=20_000, frontier_ticks=300_000))
    health = _health(publisher)
    assert health
    assert not _authoritative_capture_health_faults(health)
    subject = _supervisor(tmp_path / "supervisor", health)
    subject._maybe_establish_zero_write_aperture_origin(health)
    assert subject.state["qualification_started_utc"] is not None
