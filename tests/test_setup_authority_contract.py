from __future__ import annotations

import json
from pathlib import Path

from host.otis_tools.bounded_tight_deadband_prewrite_contract import (
    canonical_prewrite_fixture,
)
from host.otis_tools.setup_authority_contract import (
    SETUP_AUTHORITY_CONTRACT,
    canonical_health,
    replay_setup_authority_input,
    write_setup_authority_input,
)


BUILD_IDENTITY = "a" * 64 + ":" + "b" * 64
IDENTITY = {
    "run_identity": "run:1",
    "build_identity": BUILD_IDENTITY,
    "profile_identity": "profile",
    "estimator_sha256": "c" * 64,
    "model_sha256": "d" * 64,
    "active_policy_sha256": "e" * 64,
    "response_policy_sha256": "f" * 64,
    "numerical_policy_sha256": "1" * 64,
}


def _value() -> dict[str, object]:
    health = canonical_prewrite_fixture(
        expected_identity=IDENTITY, planned_live_stimulus_code=0xA808
    )
    health[("cx317_active", "snapshot_generation_begin")] = "7"
    health[("cx317_active", "snapshot_generation_complete")] = "7"
    health[("cx317_active", "query_nonce")] = "99"
    health[("cx317_active", "session_id")] = "4"
    health[("cx317_active", "uptime_s")] = "620"
    return {
        "contract": SETUP_AUTHORITY_CONTRACT,
        "created_utc": "2026-08-12T10:00:00Z",
        "request": {
            "authorization_sequence": 1,
            "status_generation": 7,
            "query_nonce": 99,
            "expires_s": 650,
            "session_id": 4,
            "requested_code": 0xA808,
            "one_shot_ordinal": 1,
            "configuration_identity": "b" * 64,
        },
        "health": canonical_health(health),
        "active_row_count": 0,
        "dac_row_count": 0,
        "telemetry_drop_baseline": 0,
    }


def test_retained_setup_authority_replays_exactly(tmp_path: Path) -> None:
    path = tmp_path / "authority.json"
    write_setup_authority_input(path, _value())

    replay = replay_setup_authority_input(
        path,
        expected_identity=IDENTITY,
        planned_live_stimulus_code=0xA808,
    )

    assert replay.exact is True
    assert replay.errors == ()


def test_replay_rejects_changed_request_even_with_rehashed_json(
    tmp_path: Path,
) -> None:
    path = tmp_path / "authority.json"
    value = _value()
    value["request"]["query_nonce"] = 100  # type: ignore[index]
    write_setup_authority_input(path, value)

    replay = replay_setup_authority_input(
        path,
        expected_identity=IDENTITY,
        planned_live_stimulus_code=0xA808,
    )

    assert replay.exact is False
    assert any("query_nonce" in item for item in replay.errors)


def test_authority_record_is_create_only(tmp_path: Path) -> None:
    path = tmp_path / "authority.json"
    write_setup_authority_input(path, _value())

    try:
        write_setup_authority_input(path, _value())
    except FileExistsError:
        pass
    else:
        raise AssertionError("setup authority record was overwritten")
    assert json.loads(path.read_text())["contract"] == SETUP_AUTHORITY_CONTRACT
