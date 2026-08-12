from __future__ import annotations

import csv
from pathlib import Path

from host.otis_tools.active_status_contract import (
    ACTIVE_STATUS_KEYS,
    ACTIVE_STATUS_SNAPSHOT_CONTRACT,
    SNAPSHOT_BEGIN_KEY,
    SNAPSHOT_COMPLETE_KEY,
    SNAPSHOT_CONTRACT_KEY,
    latest_complete_active_status,
    latest_complete_health,
)


def _row(component: str, key: str, value: str) -> dict[str, str]:
    return {
        "record_type": "STS",
        "component": component,
        "status_key": key,
        "status_value": value,
    }


def _burst(generation: int, *, missing: str | None = None) -> list[dict[str, str]]:
    rows = [
        _row("cx317_active", SNAPSHOT_BEGIN_KEY, str(generation)),
        _row(
            "cx317_active",
            SNAPSHOT_CONTRACT_KEY,
            ACTIVE_STATUS_SNAPSHOT_CONTRACT,
        ),
    ]
    rows.extend(
        _row("cx317_active", key, f"{generation}:{key}")
        for key in ACTIVE_STATUS_KEYS
        if key != missing
    )
    rows.append(
        _row("cx317_active", SNAPSHOT_COMPLETE_KEY, str(generation))
    )
    return rows


def test_only_a_complete_generation_is_eligible() -> None:
    rows = [*_burst(1), *_burst(2)[:-1]]

    status = latest_complete_active_status(rows)

    assert status == {}


def test_newer_incomplete_or_duplicate_burst_cannot_mix_with_older_state() -> None:
    duplicate = _burst(2)
    duplicate.insert(5, _row("cx317_active", "state", "duplicate"))
    rows = [*_burst(1), *duplicate, *_burst(3, missing="dac_epoch")]

    status = latest_complete_active_status(rows)

    assert status == {}


def test_newest_complete_generation_replaces_the_previous_generation() -> None:
    status = latest_complete_active_status([*_burst(1), *_burst(2)])

    assert status[SNAPSHOT_BEGIN_KEY] == "2"
    assert status["dac_epoch"] == "2:dac_epoch"


def test_complete_health_keeps_other_components_but_never_partial_active(
    tmp_path: Path,
) -> None:
    path = tmp_path / "health.csv"
    fieldnames = (
        "record_type",
        "schema_version",
        "status_seq",
        "timestamp_ticks",
        "status_domain",
        "component",
        "status_key",
        "status_value",
        "severity",
        "flags",
    )
    rows = [
        _row("capture", "dropped_count", "0"),
        *_burst(1),
        _row("capture", "dropped_count", "4"),
        *_burst(2)[:-1],
    ]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for sequence, row in enumerate(rows, start=1):
            writer.writerow(
                {
                    **row,
                    "schema_version": "1",
                    "status_seq": str(sequence),
                    "timestamp_ticks": str(sequence),
                    "status_domain": "rp2040_timer0",
                    "severity": "INFO",
                    "flags": "0",
                }
            )

    health = latest_complete_health(path)

    assert health[("capture", "dropped_count")] == "4"
    assert not any(component == "cx317_active" for component, _ in health)


def test_required_query_nonce_rejects_buffered_pre_boundary_status(
    tmp_path: Path,
) -> None:
    path = tmp_path / "health.csv"
    fieldnames = (
        "record_type", "schema_version", "status_seq", "timestamp_ticks",
        "status_domain", "component", "status_key", "status_value",
        "severity", "flags",
    )
    rows = [*_burst(1), *_burst(2)]
    for row in rows:
        if row.get("status_key") == "query_nonce":
            generation = row["status_value"].split(":", 1)[0]
            row["status_value"] = "111" if generation == "1" else "222"
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for sequence, row in enumerate(rows, start=1):
            writer.writerow({
                **row, "schema_version": "1", "status_seq": str(sequence),
                "timestamp_ticks": str(sequence),
                "status_domain": "rp2040_timer0", "severity": "INFO",
                "flags": "0",
            })

    assert not any(
        component == "cx317_active"
        for component, _ in latest_complete_health(
            path, required_query_nonce=111
        )
    )
    current = latest_complete_health(path, required_query_nonce=222)
    assert current[("cx317_active", "query_nonce")] == "222"
