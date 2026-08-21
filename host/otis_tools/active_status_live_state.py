"""Atomic live-health handoff derived from the canonical status stream.

The append-only health CSV remains scientific evidence.  Live supervisors use
this separately published state so an arbitrary prefix of a multi-record
active-status generation can never masquerade as a stable control-plane view.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Iterable, Mapping

from .active_status_contract import (
    ACTIVE_STATUS_COMPONENT,
    ALL_ACTIVE_STATUS_WIRE_KEYS,
    SNAPSHOT_BEGIN_KEY,
    SNAPSHOT_COMPLETE_KEY,
    SNAPSHOT_CONTRACT_KEY,
    active_status_wire_keys,
)


LIVE_STATE_CONTRACT = "cx317_active_status_live_state_v1"
LIVE_STATE_PATH = Path("reports/cx317_active_status_live_state_v1.json")
LIVE_STATE_SCHEMA_VERSION = 1
LIVE_STATES = frozenset({"in_progress", "complete", "invalid"})


def _positive_int(value: object) -> int | None:
    try:
        parsed = int(str(value))
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _record(row: Mapping[str, str]) -> dict[str, str]:
    return {
        key: row.get(key, "")
        for key in (
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
    }


class ActiveStatusLiveReducer:
    """Reduce complete CSV records into explicit live snapshot states."""

    def __init__(self) -> None:
        self.latest_nonactive: dict[tuple[str, str], dict[str, str]] = {}
        self.current_generation: int | None = None
        self.current_active: dict[str, dict[str, str]] = {}
        self.newest_started_generation = 0
        self.newest_complete_generation = 0
        self.invalid_reason: str | None = None

    def _frontier(self, row: Mapping[str, str]) -> dict[str, object]:
        return {
            "frontier_status_seq": _positive_int(row.get("status_seq")),
            "frontier_timestamp_ticks": _positive_int(
                row.get("timestamp_ticks")
            ),
            "frontier_status_domain": row.get("status_domain", ""),
        }

    def _state(
        self,
        state: str,
        row: Mapping[str, str],
        *,
        reason: str,
        records: list[dict[str, str]] | None = None,
    ) -> dict[str, object]:
        return {
            "schema_version": LIVE_STATE_SCHEMA_VERSION,
            "contract": LIVE_STATE_CONTRACT,
            "state": state,
            "reason": reason,
            "generation": self.current_generation,
            "newest_started_generation": self.newest_started_generation,
            "newest_complete_generation": (
                self.newest_complete_generation or None
            ),
            "records": records or [],
            **self._frontier(row),
        }

    def _invalidate(
        self, row: Mapping[str, str], reason: str
    ) -> dict[str, object]:
        self.invalid_reason = reason
        return self._state("invalid", row, reason=reason)

    def observe(
        self, row: Mapping[str, str]
    ) -> dict[str, object] | None:
        """Return a publishable state only at begin, complete, or invalid."""

        if row.get("record_type") != "STS":
            return None
        component = row.get("component", "")
        key = row.get("status_key", "")
        if component != ACTIVE_STATUS_COMPONENT:
            if component and key:
                self.latest_nonactive[(component, key)] = _record(row)
            return None
        if self.invalid_reason is not None:
            return None

        if key == SNAPSHOT_BEGIN_KEY:
            if self.current_generation is not None:
                return self._invalidate(
                    row,
                    "new snapshot generation began before the prior "
                    f"generation {self.current_generation} completed",
                )
            generation = _positive_int(row.get("status_value"))
            if generation is None:
                return self._invalidate(
                    row, "snapshot begin generation is not positive"
                )
            if generation <= self.newest_started_generation:
                return self._invalidate(
                    row,
                    "snapshot generation did not increase monotonically: "
                    f"{generation} <= {self.newest_started_generation}",
                )
            self.current_generation = generation
            self.newest_started_generation = generation
            self.current_active = {key: _record(row)}
            return self._state(
                "in_progress", row, reason="snapshot_generation_started"
            )

        if self.current_generation is None or key not in ALL_ACTIVE_STATUS_WIRE_KEYS:
            return None
        if key in self.current_active:
            return self._invalidate(
                row,
                f"duplicate active snapshot key {key!r} in generation "
                f"{self.current_generation}",
            )
        self.current_active[key] = _record(row)
        if key != SNAPSHOT_COMPLETE_KEY:
            return None

        completed_generation = _positive_int(row.get("status_value"))
        contract = self.current_active.get(SNAPSHOT_CONTRACT_KEY, {}).get(
            "status_value"
        )
        required_wire_keys = active_status_wire_keys(str(contract))
        if completed_generation != self.current_generation:
            return self._invalidate(
                row,
                "snapshot completion generation differs from begin: "
                f"{completed_generation} != {self.current_generation}",
            )
        if required_wire_keys is None:
            return self._invalidate(
                row, f"active snapshot contract is {contract!r}"
            )
        missing = sorted(set(required_wire_keys) - set(self.current_active))
        if missing:
            return self._invalidate(
                row, "active snapshot is missing keys: " + ", ".join(missing)
            )

        generation = self.current_generation
        self.newest_complete_generation = generation
        records = [
            *self.latest_nonactive.values(),
            *self.current_active.values(),
        ]
        records.sort(
            key=lambda item: (item["component"], item["status_key"])
        )
        state = self._state(
            "complete",
            row,
            reason="snapshot_generation_complete",
            records=records,
        )
        self.current_generation = None
        self.current_active = {}
        state["generation"] = generation
        return state


@dataclass(frozen=True)
class LiveHealthState:
    state: str
    health: dict[tuple[str, str], str]
    generation: int | None
    observed_monotonic_ns: int | None
    diagnostic: str


def _invalid_state(diagnostic: str) -> LiveHealthState:
    return LiveHealthState("invalid", {}, None, None, diagnostic)


def read_live_health_state(
    path: Path, *, required_query_nonce: int | None = None
) -> LiveHealthState:
    """Read and validate one atomically published live-health state."""

    if not path.is_file():
        return LiveHealthState(
            "absent", {}, None, None, "live-health state is absent"
        )
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return _invalid_state(f"cannot read live-health state: {exc}")
    if not isinstance(value, dict):
        return _invalid_state("live-health state is not a JSON object")
    if (
        value.get("schema_version") != LIVE_STATE_SCHEMA_VERSION
        or value.get("contract") != LIVE_STATE_CONTRACT
    ):
        return _invalid_state("live-health state identity is invalid")
    state = value.get("state")
    if state not in LIVE_STATES:
        return _invalid_state(f"live-health state value is invalid: {state!r}")
    generation = _positive_int(value.get("generation"))
    observed_monotonic_ns = _positive_int(value.get("observed_monotonic_ns"))
    diagnostic = str(value.get("reason", "unspecified"))
    if observed_monotonic_ns is None:
        return _invalid_state("live-health observation clock is absent")
    if state != "complete":
        return LiveHealthState(
            str(state), {}, generation, observed_monotonic_ns, diagnostic
        )
    if generation is None:
        return _invalid_state("complete live-health generation is absent")
    if (
        _positive_int(value.get("newest_started_generation")) != generation
        or _positive_int(value.get("newest_complete_generation"))
        != generation
    ):
        return _invalid_state("complete live-health generation is incoherent")
    records = value.get("records")
    if not isinstance(records, list):
        return _invalid_state("complete live-health records are absent")

    latest: dict[tuple[str, str], str] = {}
    for item in records:
        if not isinstance(item, dict) or item.get("record_type") != "STS":
            return _invalid_state("live-health record is malformed")
        component = item.get("component")
        key = item.get("status_key")
        record_key = (component, key)
        if not isinstance(component, str) or not isinstance(key, str):
            return _invalid_state("live-health record identity is malformed")
        if record_key in latest:
            return _invalid_state(
                f"duplicate live-health record {component}.{key}"
            )
        latest[record_key] = str(item.get("status_value", ""))

    contract = latest.get(
        (ACTIVE_STATUS_COMPONENT, SNAPSHOT_CONTRACT_KEY), ""
    )
    required_wire_keys = active_status_wire_keys(contract)
    if required_wire_keys is None:
        return _invalid_state(
            f"complete live-health active snapshot contract is {contract!r}"
        )
    active = {
        key: latest.get((ACTIVE_STATUS_COMPONENT, key))
        for key in required_wire_keys
    }
    missing = sorted(key for key, item in active.items() if item is None)
    if missing:
        return _invalid_state(
            "complete live-health active snapshot is missing keys: "
            + ", ".join(missing)
        )
    if (
        active[SNAPSHOT_BEGIN_KEY] != str(generation)
        or active[SNAPSHOT_COMPLETE_KEY] != str(generation)
        or active[SNAPSHOT_CONTRACT_KEY] != contract
    ):
        return _invalid_state("complete live-health active snapshot is invalid")
    if required_query_nonce is not None and active.get("query_nonce") != str(
        required_query_nonce
    ):
        return LiveHealthState(
            "unmatched",
            {},
            generation,
            observed_monotonic_ns,
            "complete live-health query nonce is not current",
        )
    return LiveHealthState(
        "complete",
        latest,
        generation,
        observed_monotonic_ns,
        diagnostic,
    )


def reduce_health_rows(
    rows: Iterable[Mapping[str, str]],
) -> dict[str, object] | None:
    """Return the last publishable state for deterministic replay tooling."""

    reducer = ActiveStatusLiveReducer()
    latest: dict[str, object] | None = None
    for row in rows:
        update = reducer.observe(row)
        if update is not None:
            latest = update
    return latest
