"""PPS status cohorts must not merge a partial publication with an old one."""

from __future__ import annotations

import csv
import re
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

FIXTURE = Path(__file__).parent / "fixtures/startup_census_539ff6a/health_records.csv"
INTERLEAVE_FIXTURE = (
    Path(__file__).parent / "fixtures/pps_config_interleave_0c2d8a0/health_records.csv"
)
FIRMWARE_SKETCH = (
    Path(__file__).parents[1]
    / "firmware/arduino/otis_nano_rp2040_connect/otis_nano_rp2040_connect.ino"
)
FIRMWARE_COUNT_SOURCE = (
    Path(__file__).parents[1]
    / "firmware/arduino/otis_nano_rp2040_connect/otis_count_observation.cpp"
)
LEGACY_CORE0_CONFIG_PPS_KEYS = frozenset(
    {
        "boundary_owner",
        "aperture_backend",
        "backend_qualified",
        "boundary_ring_capacity",
    }
)
CURRENT_FRAMED_PPS_CONFIG_KEYS = frozenset(
    {
        "boundary_owner",
        "aperture_backend",
        "hardware_count_boundary",
    }
)

_CURRENT_PPS_KEY_RENAMES = {
    "backend_qualified": "hardware_count_boundary",
    "valid": "raw_window_valid",
    "state": "raw_window_state",
    "last_reason": "raw_window_reason",
    "association_state": "capture_state",
    "association_loss_reason": "capture_loss_reason",
    "association_loss_count": "capture_loss_count",
    "association_loss_reference_sequence": "capture_loss_consumer_ordinal",
    "snapshot_producer_sequence": "snapshot_producer_ordinal",
    "snapshot_consumer_sequence": "snapshot_consumer_ordinal",
    "snapshot_overwrite_count": "snapshot_ring_full_count",
    "snapshot_dma_error_count": "snapshot_irq_budget_exhausted_count",
    "snapshot_dma_stopped_count": "snapshot_timestamp_ambiguous_count",
    "physical_pps_state": "capture_service_state",
    "physical_pps_missing_count": "capture_service_stale_count",
    "physical_pps_restored_count": "capture_service_resumed_count",
    "physical_pps_reminder_count": "capture_service_reminder_count",
}
_RETIRED_PPS_KEYS = frozenset(
    {
        "association_recovery_count",
        "boundary_ring_depth",
        "boundary_ring_capacity",
        "boundary_ring_dropped_count",
        "snapshot_dma_channel",
    }
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


def _interleave_rows() -> list[dict[str, str]]:
    with INTERLEAVE_FIXTURE.open(newline="", encoding="utf-8") as stream:
        return list(csv.DictReader(stream))


def _project_single_pps_writer(
    rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    """Remove only the four Core 0 PPS records from the retained CONFIG block."""

    projected: list[dict[str, str]] = []
    in_config = False
    for row in rows:
        if (
            row["component"] == "command"
            and row["status_key"] == "config_snapshot"
            and row["status_value"] == "begin"
        ):
            in_config = True
        if not (
            in_config
            and row["component"] == "pps_gate"
            and row["status_key"] in LEGACY_CORE0_CONFIG_PPS_KEYS
        ):
            projected.append(deepcopy(row))
        if (
            row["component"] == "command"
            and row["status_key"] == "config_snapshot"
            and row["status_value"] == "end"
        ):
            in_config = False
    return _project_current_pps_schema(projected)


def _project_current_pps_schema(
    rows: list[dict[str, str]],
) -> list[dict[str, str]]:
    projected: list[dict[str, str]] = []
    for source in rows:
        row = deepcopy(source)
        if row["component"] == "pps_gate":
            key = row["status_key"]
            if key in _RETIRED_PPS_KEYS:
                continue
            row["status_key"] = _CURRENT_PPS_KEY_RENAMES.get(key, key)
            if (
                row["status_key"] == "aperture_backend"
                and row["status_value"] == "pio_wait_cumulative_snapshot_dma_v1"
            ):
                row["status_value"] = "pio_wait_cumulative_snapshot_fifo_irq_v2"
        projected.append(row)
    return projected


def _resequence(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    ordered = deepcopy(rows)
    anchor_ticks = int(
        next(
            row["status_value"]
            for row in ordered
            if row["component"] == "pps_gate"
            and row["status_key"] == "accepted_anchor_timestamp_ticks"
        )
    )
    for offset, row in enumerate(ordered):
        row["status_seq"] = str(90_000 + offset)
        row["timestamp_ticks"] = str(anchor_ticks + 2_000 * (offset + 1))
    return ordered


def _config_interleave_at(position: str) -> list[dict[str, str]]:
    """Move the repaired CONFIG response across the two framed cohorts."""

    repaired = _project_single_pps_writer(_interleave_rows())
    pps_begin = next(
        index
        for index, row in enumerate(repaired)
        if row["component"] == "pps_gate"
        and row["status_key"] == "snapshot"
        and row["status_value"] == "begin"
    )
    pps_end = next(
        index
        for index, row in enumerate(repaired)
        if row["component"] == "pps_gate"
        and row["status_key"] == "snapshot"
        and row["status_value"] == "end"
    )
    config_begin = next(
        index
        for index, row in enumerate(repaired)
        if row["component"] == "command"
        and row["status_key"] == "config_snapshot"
        and row["status_value"] == "begin"
    )
    config_ack = next(
        index
        for index, row in enumerate(repaired)
        if row["component"] == "command"
        and row["status_key"] == "timing_config_snapshot"
    )
    active_begin = next(
        index
        for index, row in enumerate(repaired)
        if row["component"] == "adaptive_hybrid"
        and row["status_key"] == "snapshot_generation_begin"
    )
    active_end = next(
        index
        for index, row in enumerate(repaired)
        if row["component"] == "adaptive_hybrid"
        and row["status_key"] == "snapshot_generation_complete"
    )

    config = repaired[config_begin : config_ack + 1]
    without_config = repaired[:config_begin] + repaired[config_ack + 1 :]
    pps = [row for row in without_config if pps_begin <= repaired.index(row) <= pps_end]
    between = [
        row for row in without_config if pps_end < repaired.index(row) < active_begin
    ]
    active = [
        row
        for row in without_config
        if active_begin <= repaired.index(row) <= active_end
    ]
    if position == "before_pps":
        ordered = [*config, *pps, *between, *active]
    elif position == "within_pps":
        return repaired
    elif position == "after_pps":
        ordered = [*pps, *config, *between, *active]
    elif position == "within_active":
        split = len(active) // 2
        ordered = [*pps, *between, *active[:split], *config, *active[split:]]
    elif position == "after_active":
        ordered = [*pps, *between, *active, *config]
    else:
        raise AssertionError(f"unknown interleave position {position!r}")
    return _resequence(ordered)


def _line(row: dict[str, str]) -> str:
    stream = StringIO()
    writer = csv.DictWriter(stream, fieldnames=HEALTH_FIELDS)
    writer.writerow(row)
    return stream.getvalue().rstrip("\r\n")


def _pps_rows(
    generation: int, *, sequence_base: int, anchor_ticks: int
) -> list[dict[str, str]]:
    source = _project_current_pps_schema(
        [
            deepcopy(row)
            for row in _fixture_rows()
            if row["component"] == "pps_gate"
        ]
    )
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
    selection = read_live_health_state(publisher.path, required_query_nonce=QUERY_NONCE)
    return selection.health if selection.state == "complete" else {}


def _supervisor(
    tmp_path: Path, health: dict[tuple[str, str], str]
) -> AdaptiveHybridSupervisor:
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
    _publish(
        publisher, _active_rows(2, sequence_base=20_000, frontier_ticks=11_000_000)
    )
    healthy = _health(publisher)
    assert healthy
    assert not _authoritative_capture_health_faults(healthy)

    # These are a concrete adverse G5: its changed continuity state and
    # discontinuity counters never reach capture, while begin/end do.
    partial = _pps_rows(5, sequence_base=30_000, anchor_ticks=12_000_000)
    for row in partial:
        if row["status_key"] == "fifo_continuity":
            row["status_value"] = "unavailable"
        elif row["status_key"] == "capture_state":
            row["status_value"] = "lost"
        elif row["status_key"] in {
            "capture_loss_count",
            "physical_aperture_incomplete_count",
        }:
            row["status_value"] = "1"
    partial = [
        row
        for row in partial
        if row["status_key"]
        not in {
            "fifo_continuity",
            "capture_state",
            "capture_loss_count",
            "physical_aperture_incomplete_count",
        }
    ]
    _publish(publisher, partial)
    _publish(
        publisher, _active_rows(3, sequence_base=40_000, frontier_ticks=13_000_000)
    )
    mixed = _health(publisher)

    assert mixed == {} or _authoritative_capture_health_faults(mixed)
    subject = _supervisor(tmp_path / "supervisor", healthy)
    subject._maybe_establish_zero_write_aperture_origin(mixed)
    assert subject.state["qualification_started_utc"] is None


def test_pps_cohort_releases_only_after_its_complete_generation(tmp_path: Path) -> None:
    publisher = ActiveStatusLivePublisher(tmp_path)
    full = _pps_rows(5, sequence_base=30_000, anchor_ticks=12_000_000)
    end_index = next(
        index
        for index, row in enumerate(full)
        if row["status_key"] == "snapshot" and row["status_value"] == "end"
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
    _publish(
        publisher, _active_rows(3, sequence_base=50_000, frontier_ticks=13_100_000)
    )
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


def test_retained_config_interleave_reproduces_duplicate_pps_key_hold() -> None:
    rows = _interleave_rows()
    assert rows[0]["status_seq"] == "82426"
    assert rows[-1]["status_seq"] == "82611"

    reducer = ActiveStatusLiveReducer()
    updates = [update for row in rows if (update := reducer.observe(row)) is not None]

    assert updates[-1]["state"] == "invalid"
    assert updates[-1]["reason"] == "duplicate PPS snapshot key 'boundary_owner'"
    assert updates[-1]["frontier_status_seq"] == 82466


def test_core0_cannot_emit_into_timing_owned_status_cohorts() -> None:
    sketch = FIRMWARE_SKETCH.read_text(encoding="utf-8")
    direct_core0_cohort_emit = re.compile(
        r"\bemit_status(?:_[a-z0-9]+)?\s*\(\s*"
        r'"(?:pps_gate|adaptive_hybrid)"'
    )
    assert direct_core0_cohort_emit.search(sketch) is None

    start = sketch.index(
        "} else if (command.kind == OtisSerialCommandKind::ConfigQuery)"
    )
    end = sketch.index(
        "} else if (command.kind == OtisSerialCommandKind::DualCoreQuery)",
        start,
    )
    config_query = sketch[start:end]

    assert "OtisRunControlKind::DiagnosticConfigQuery" in config_query
    assert "queue_dual_core_active_control(" in config_query

    count_source = FIRMWARE_COUNT_SOURCE.read_text(encoding="utf-8")
    pps_start = count_source.index("void emit_pps_gate_status(")
    pps_end = count_source.index("\nvoid emit_pps_gate_window_status(", pps_start)
    framed_pps = count_source[pps_start:pps_end]
    assert framed_pps.index('"snapshot", "begin"') < framed_pps.index(
        '"snapshot_generation"'
    )
    for key in CURRENT_FRAMED_PPS_CONFIG_KEYS:
        assert f'"pps_gate", "{key}"' in framed_pps
        assert framed_pps.index(f'"pps_gate", "{key}"') < framed_pps.index(
            '"snapshot", "end"'
        )


@pytest.mark.parametrize(
    "position",
    [
        "before_pps",
        "within_pps",
        "after_pps",
        "within_active",
        "after_active",
    ],
)
def test_config_interleave_with_single_pps_writer_reaches_zero_write_endpoint(
    tmp_path: Path,
    position: str,
) -> None:
    rows = _config_interleave_at(position)
    publisher = ActiveStatusLivePublisher(tmp_path / position)
    _publish(publisher, rows)

    selection = read_live_health_state(
        publisher.path, required_query_nonce=1_731_280_765
    )
    assert selection.state == "complete"
    assert selection.generation == 433
    assert not _authoritative_capture_health_faults(selection.health)

    subject = _supervisor(tmp_path / f"{position}_supervisor", selection.health)
    subject._maybe_establish_zero_write_aperture_origin(selection.health)
    assert subject.state["qualification_started_utc"] is not None
    assert subject._inhibited_zero_write_terminal_ready(selection.health)


def test_repaired_stream_still_rejects_a_true_pps_producer_duplicate() -> None:
    rows = _project_single_pps_writer(_interleave_rows())
    duplicate_index = next(
        index
        for index, row in enumerate(rows)
        if row["component"] == "pps_gate" and row["status_key"] == "boundary_owner"
    )
    rows.insert(duplicate_index + 1, deepcopy(rows[duplicate_index]))

    reducer = ActiveStatusLiveReducer()
    updates = [update for row in rows if (update := reducer.observe(row)) is not None]

    assert updates[-1]["state"] == "invalid"
    assert updates[-1]["reason"] == "duplicate PPS snapshot key 'boundary_owner'"
