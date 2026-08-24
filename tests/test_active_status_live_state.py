from __future__ import annotations

import json
from pathlib import Path
import time

from host.otis_tools.active_status_contract import (
    ACTIVE_STATUS_KEYS,
    ACTIVE_STATUS_SNAPSHOT_CONTRACT,
    CX321_ACTIVE_STATUS_KEYS,
    CX321_ACTIVE_STATUS_SNAPSHOT_CONTRACT,
    SUSTAINED_HYBRID_ACTIVE_STATUS_KEYS,
    SUSTAINED_HYBRID_ACTIVE_STATUS_SNAPSHOT_CONTRACT,
    SNAPSHOT_BEGIN_KEY,
    SNAPSHOT_COMPLETE_KEY,
    SNAPSHOT_CONTRACT_KEY,
)
from host.otis_tools.active_status_live_state import (
    ActiveStatusLiveReducer,
    LIVE_STATE_CONTRACT,
    LiveHealthState,
    read_live_health_state,
)


def _row(
    sequence: int, component: str, key: str, value: str
) -> dict[str, str]:
    return {
        "record_type": "STS",
        "schema_version": "1",
        "status_seq": str(sequence),
        "timestamp_ticks": str(sequence * 1600),
        "status_domain": "rp2040_timer0",
        "component": component,
        "status_key": key,
        "status_value": value,
        "severity": "INFO",
        "flags": "0",
    }


def _burst(
    generation: int,
    *,
    nonce: int = 99,
    contract: str = ACTIVE_STATUS_SNAPSHOT_CONTRACT,
) -> list[dict[str, str]]:
    if contract == CX321_ACTIVE_STATUS_SNAPSHOT_CONTRACT:
        keys = CX321_ACTIVE_STATUS_KEYS
    elif contract == SUSTAINED_HYBRID_ACTIVE_STATUS_SNAPSHOT_CONTRACT:
        keys = SUSTAINED_HYBRID_ACTIVE_STATUS_KEYS
    else:
        keys = ACTIVE_STATUS_KEYS
    values = {
        key: f"value:{key}" for key in keys
    }
    values["query_nonce"] = str(nonce)
    rows = [
        _row(2, "cx317_active", SNAPSHOT_BEGIN_KEY, str(generation)),
        _row(
            3,
            "cx317_active",
            SNAPSHOT_CONTRACT_KEY,
            contract,
        ),
    ]
    rows.extend(
        _row(index, "cx317_active", key, values[key])
        for index, key in enumerate(keys, start=4)
    )
    rows.append(
        _row(
            len(rows) + 2,
            "cx317_active",
            SNAPSHOT_COMPLETE_KEY,
            str(generation),
        )
    )
    return rows


def _published(value: dict[str, object]) -> dict[str, object]:
    return {
        **value,
        "observed_monotonic_ns": time.monotonic_ns(),
        "observed_utc": "2026-08-12T12:00:00.000000Z",
        "capture_pid": 123,
        "transport_generation": 1,
    }


def test_every_wire_cut_is_explicitly_pending_until_exact_completion() -> None:
    burst = _burst(7)
    for cut in range(1, len(burst)):
        reducer = ActiveStatusLiveReducer()
        reducer.observe(_row(1, "capture", "dropped_count", "0"))
        latest = None
        for row in burst[:cut]:
            update = reducer.observe(row)
            if update is not None:
                latest = update
        assert latest is not None
        assert latest["state"] == "in_progress"
        assert latest["records"] == []

    reducer = ActiveStatusLiveReducer()
    reducer.observe(_row(1, "capture", "dropped_count", "0"))
    latest = None
    for row in burst:
        update = reducer.observe(row)
        if update is not None:
            latest = update
    assert latest is not None
    assert latest["state"] == "complete"
    assert latest["generation"] == 7
    assert len(latest["records"]) == len(burst) + 1


def test_complete_atomic_state_carries_one_coherent_health_frontier(
    tmp_path: Path,
) -> None:
    reducer = ActiveStatusLiveReducer()
    reducer.observe(_row(1, "capture", "dropped_count", "0"))
    latest = None
    for row in _burst(8, nonce=1234):
        update = reducer.observe(row)
        if update is not None:
            latest = update
    assert latest is not None
    path = tmp_path / "state.json"
    path.write_text(json.dumps(_published(latest)), encoding="utf-8")

    selected = read_live_health_state(path, required_query_nonce=1234)

    assert isinstance(selected, LiveHealthState)
    assert selected.state == "complete"
    assert selected.generation == 8
    assert selected.health[("capture", "dropped_count")] == "0"
    assert (
        selected.health[("cx317_active", SNAPSHOT_COMPLETE_KEY)] == "8"
    )
    unmatched = read_live_health_state(path, required_query_nonce=4321)
    assert unmatched.state == "unmatched"
    assert unmatched.health == {}


def test_cx321_v2_atomic_state_requires_and_returns_plant_fields(
    tmp_path: Path,
) -> None:
    reducer = ActiveStatusLiveReducer()
    latest = None
    for row in _burst(
        12,
        nonce=321,
        contract=CX321_ACTIVE_STATUS_SNAPSHOT_CONTRACT,
    ):
        update = reducer.observe(row)
        if update is not None:
            latest = update
    assert latest is not None and latest["state"] == "complete"
    path = tmp_path / "cx321_state.json"
    path.write_text(json.dumps(_published(latest)), encoding="utf-8")

    selected = read_live_health_state(path, required_query_nonce=321)

    assert selected.state == "complete"
    assert selected.health[("cx317_active", "plant_sign_state")] == (
        "value:plant_sign_state"
    )


def test_sustained_atomic_state_requires_and_returns_decision_identities(
    tmp_path: Path,
) -> None:
    reducer = ActiveStatusLiveReducer()
    latest = None
    for row in _burst(
        14,
        nonce=323,
        contract=SUSTAINED_HYBRID_ACTIVE_STATUS_SNAPSHOT_CONTRACT,
    ):
        update = reducer.observe(row)
        if update is not None:
            latest = update
    assert latest is not None and latest["state"] == "complete"
    path = tmp_path / "sustained_state.json"
    path.write_text(json.dumps(_published(latest)), encoding="utf-8")

    selected = read_live_health_state(path, required_query_nonce=323)

    assert selected.state == "complete"
    assert selected.health[
        ("cx317_active", "deliberate_challenge_dac_epoch")
    ] == "value:deliberate_challenge_dac_epoch"


def test_cx321_atomic_state_canonicalizes_frozen_truncated_wire_key(
    tmp_path: Path,
) -> None:
    rows = _burst(
        13,
        nonce=322,
        contract=CX321_ACTIVE_STATUS_SNAPSHOT_CONTRACT,
    )
    target = next(
        row
        for row in rows
        if row["status_key"]
        == "plant_sign_accumulator_accepted_intervals"
    )
    target["status_key"] = "plant_sign_accumulator_accepted_interva"
    reducer = ActiveStatusLiveReducer()
    latest = None
    for row in rows:
        update = reducer.observe(row)
        if update is not None:
            latest = update
    assert latest is not None and latest["state"] == "complete"
    path = tmp_path / "cx321_truncated_state.json"
    path.write_text(json.dumps(_published(latest)), encoding="utf-8")

    selected = read_live_health_state(path, required_query_nonce=322)

    assert selected.state == "complete"
    assert selected.health[
        ("cx317_active", "plant_sign_accumulator_accepted_intervals")
    ] == "value:plant_sign_accumulator_accepted_intervals"


def test_duplicate_missing_and_interrupted_generations_are_invalid() -> None:
    duplicate = _burst(1)
    duplicate.insert(5, duplicate[5].copy())
    reducer = ActiveStatusLiveReducer()
    updates = [item for row in duplicate if (item := reducer.observe(row))]
    assert updates[-1]["state"] == "invalid"
    assert "duplicate" in str(updates[-1]["reason"])

    missing = [
        row for row in _burst(1) if row["status_key"] != "dac_epoch"
    ]
    reducer = ActiveStatusLiveReducer()
    updates = [item for row in missing if (item := reducer.observe(row))]
    assert updates[-1]["state"] == "invalid"
    assert "missing keys" in str(updates[-1]["reason"])

    interrupted = [*_burst(1)[:-1], _burst(2)[0]]
    reducer = ActiveStatusLiveReducer()
    updates = [
        item for row in interrupted if (item := reducer.observe(row))
    ]
    assert updates[-1]["state"] == "invalid"
    assert "before the prior generation" in str(updates[-1]["reason"])


def test_reader_never_returns_health_from_in_progress_or_invalid_state(
    tmp_path: Path,
) -> None:
    reducer = ActiveStatusLiveReducer()
    pending = reducer.observe(_burst(9)[0])
    assert pending is not None
    path = tmp_path / "state.json"
    path.write_text(json.dumps(_published(pending)), encoding="utf-8")
    selected = read_live_health_state(path, required_query_nonce=99)
    assert selected.state == "in_progress"
    assert selected.health == {}

    value = _published(pending)
    value["contract"] = LIVE_STATE_CONTRACT + "_corrupt"
    path.write_text(json.dumps(value), encoding="utf-8")
    corrupt = read_live_health_state(path, required_query_nonce=99)
    assert corrupt.state == "invalid"
    assert corrupt.health == {}
