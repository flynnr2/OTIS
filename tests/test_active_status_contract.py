from __future__ import annotations

import csv
from pathlib import Path

from host.otis_tools.active_status_contract import (
    ACTIVE_STATUS_KEYS,
    ACTIVE_STATUS_SNAPSHOT_CONTRACT,
    CX321_ACTIVE_STATUS_KEYS,
    CX321_ACTIVE_STATUS_SNAPSHOT_CONTRACT,
    SNAPSHOT_BEGIN_KEY,
    SNAPSHOT_COMPLETE_KEY,
    SNAPSHOT_CONTRACT_KEY,
    evaluate_solicited_attach_snapshot_history,
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


def _burst(
    generation: int,
    *,
    missing: str | None = None,
    contract: str = ACTIVE_STATUS_SNAPSHOT_CONTRACT,
) -> list[dict[str, str]]:
    keys = (
        CX321_ACTIVE_STATUS_KEYS
        if contract == CX321_ACTIVE_STATUS_SNAPSHOT_CONTRACT
        else ACTIVE_STATUS_KEYS
    )
    rows = [
        _row("cx317_active", SNAPSHOT_BEGIN_KEY, str(generation)),
        _row(
            "cx317_active",
            SNAPSHOT_CONTRACT_KEY,
            contract,
        ),
    ]
    rows.extend(
        _row("cx317_active", key, f"{generation}:{key}")
        for key in keys
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


def test_active_snapshot_contract_carries_cx320_first_consumer_state() -> None:
    assert {
        "hybrid_state",
        "hybrid_reason",
        "first_phase_checkpoint_passed",
        "phase_nonzero_application_count",
        "phase_material_application_count",
        "frequency_only_application_count",
    } <= set(ACTIVE_STATUS_KEYS)


def test_cx321_v2_requires_and_retains_plant_sign_state() -> None:
    status = latest_complete_active_status(
        _burst(3, contract=CX321_ACTIVE_STATUS_SNAPSHOT_CONTRACT)
    )

    assert status[SNAPSHOT_CONTRACT_KEY] == (
        CX321_ACTIVE_STATUS_SNAPSHOT_CONTRACT
    )
    assert status["plant_sign_state"] == "3:plant_sign_state"
    assert latest_complete_active_status(
        _burst(
            4,
            contract=CX321_ACTIVE_STATUS_SNAPSHOT_CONTRACT,
            missing="plant_sign_state",
        )
    ) == {}


def test_cx321_frozen_wire_truncation_is_canonicalized_without_changing_raw() -> None:
    rows = _burst(5, contract=CX321_ACTIVE_STATUS_SNAPSHOT_CONTRACT)
    target = next(
        row
        for row in rows
        if row["status_key"]
        == "plant_sign_accumulator_accepted_intervals"
    )
    target["status_key"] = "plant_sign_accumulator_accepted_interva"

    status = latest_complete_active_status(rows)

    assert target["status_key"] == "plant_sign_accumulator_accepted_interva"
    assert status["plant_sign_accumulator_accepted_intervals"] == (
        "5:plant_sign_accumulator_accepted_intervals"
    )


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


def test_solicited_attach_history_binds_nonce_generation_and_uptime() -> None:
    rows = [*_burst(4), *_burst(5)]
    for row in rows:
        if row.get("status_key") == "query_nonce":
            generation = row["status_value"].split(":", 1)[0]
            row["status_value"] = "77" if generation == "4" else "88"
        if row.get("status_key") == "uptime_s":
            generation = row["status_value"].split(":", 1)[0]
            row["status_value"] = "42" if generation == "4" else "52"

    result = evaluate_solicited_attach_snapshot_history(
        rows,
        query_nonce=77,
        frozen_uptime_s=42,
        frozen_generation=4,
        maximum_uptime_s=120,
    )

    assert result["exact"] is True
    assert result["first_matching_generation"] == 4
    assert result["first_matching_uptime_s"] == 42
