from __future__ import annotations

from host.otis_tools.active_status_contract import (
    ACTIVE_STATUS_COMPONENT,
    ACTIVE_STATUS_KEYS,
    ACTIVE_STATUS_SNAPSHOT_CONTRACT,
    SNAPSHOT_BEGIN_KEY,
    SNAPSHOT_COMPLETE_KEY,
    SNAPSHOT_CONTRACT_KEY,
    latest_complete_active_status,
)
from host.otis_tools.firmware_host_contract import (
    ACTIVE_STATUS_VALUE_WIRE_TYPES,
    WIRE_TYPES,
)


def _row(key: str, value: str) -> dict[str, str]:
    return {
        "record_type": "STS",
        "schema_version": "1",
        "component": ACTIVE_STATUS_COMPONENT,
        "status_key": key,
        "status_value": value,
    }


def _valid_value(key: str) -> str:
    wire_type = WIRE_TYPES[ACTIVE_STATUS_VALUE_WIRE_TYPES[key]]
    kind = wire_type["kind"]
    if kind == "integer":
        return "0"
    if kind == "enum":
        return str(wire_type["values"][0])
    if kind == "escaped_atom":
        return "value"
    if kind == "lower_hex":
        return "a" * int(wire_type["length"])
    if kind == "hex_integer":
        return "0x0000"
    if kind == "literal_or":
        return str(wire_type["literal"])
    raise AssertionError(f"unhandled ACTIVE status wire type {kind}")


def _snapshot(generation: int, *, contract: str = ACTIVE_STATUS_SNAPSHOT_CONTRACT) -> list[dict[str, str]]:
    rows = [
        _row(SNAPSHOT_BEGIN_KEY, str(generation)),
        _row(SNAPSHOT_CONTRACT_KEY, contract),
    ]
    rows.extend(_row(key, _valid_value(key)) for key in ACTIVE_STATUS_KEYS)
    rows.append(_row(SNAPSHOT_COMPLETE_KEY, str(generation)))
    return rows


def test_exact_adaptive_status_contract_is_complete_and_selected() -> None:
    snapshot = latest_complete_active_status(_snapshot(7))
    assert snapshot[SNAPSHOT_CONTRACT_KEY] == (
        "adaptive_hybrid_active_status_snapshot_v1"
    )
    assert snapshot[SNAPSHOT_BEGIN_KEY] == "7"
    assert snapshot[SNAPSHOT_COMPLETE_KEY] == "7"
    assert set(ACTIVE_STATUS_KEYS) <= snapshot.keys()


def test_retired_contract_and_partial_new_generation_are_rejected() -> None:
    retired_contract = "retired_active_status_snapshot_v1"
    assert latest_complete_active_status(_snapshot(1, contract=retired_contract)) == {}
    rows = _snapshot(1)
    rows.extend(
        [
            _row(SNAPSHOT_BEGIN_KEY, "2"),
            _row(SNAPSHOT_CONTRACT_KEY, ACTIVE_STATUS_SNAPSHOT_CONTRACT),
            _row(ACTIVE_STATUS_KEYS[0], "1"),
        ]
    )
    assert latest_complete_active_status(rows) == {}
