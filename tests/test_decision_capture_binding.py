from __future__ import annotations

import pytest
from pathlib import Path
from types import SimpleNamespace

from host.otis_tools import adaptive_hybrid_replay as replay
from host.otis_tools.firmware_host_contract import (
    RELATIONS, bounded_modular_lag_matches,
)


RELATION = "estimate_capture_precedes_operational_decision"


@pytest.mark.parametrize("captured,decision,expected", [
    (1_000_000, 1_000_000, True),
    (1_000_000, 1_000_123, True),
    (1_000_000, 61_000_000, True),
    (1_000_000, 61_000_001, False),
    (1_000_001, 1_000_000, False),
    ((1 << 32) - 100, (1 << 32) + 50, True),
    ((1 << 32) - 100, 50, False),
    (-1, 1_000_000, False),
    (1 << 32, 1 << 32, False),
])
def test_operational_decision_requires_bounded_preceding_capture(
    captured, decision, expected,
):
    assert RELATIONS[RELATION]["maximum_lag_ticks"] == 60_000_000
    assert bounded_modular_lag_matches(
        RELATION, source=captured, source_domain="rp2040_monotonic_us32",
        target=decision, target_domain="rp2040_monotonic_us64",
    ) is expected


def test_current_decision_replay_binds_source_identity_as_well_as_capture_age(monkeypatch):
    estimate = {
        "estimate_id": "selected",
        "pass": True,
        "estimator_timestamp_ticks": "2000000",
        "time_domain": "rp2040_monotonic_us32",
        "source_capture_session": 1, "source_acceptance_epoch": 2,
        "source_opening_accepted_boundary_ordinal": 1,
        "source_closing_accepted_boundary_ordinal": 601,
        "estimator_sha256": "a" * 64, "frequency_error_hz": "0",
        "accumulated_edge_error_counts": 0,
    }
    decision = {
        "decision_timestamp_ticks": "2000123",
        "time_domain": "rp2040_monotonic_us64",
        "capture_session": "1", "source_acceptance_epoch": "2",
        "source_opening_accepted_boundary_ordinal": "1", "source_closing_accepted_boundary_ordinal": "601",
        "frequency_estimator_sha256": "a" * 64, "frequency_error_hz": "0",
        "accumulated_edge_error_counts": "0",
    }
    manifest = SimpleNamespace(root=Path("/unused"), files=[{"contract": "active_hybrid_decisions_v3", "path": "decisions.csv"}])
    def consumes(decision, estimate):
        monkeypatch.setattr(replay, "_read_csv", lambda _path: [decision])
        return replay.replay_active_decision_measurement_sources(manifest, {"selected_estimate_sources": [estimate]})["exact"]
    assert consumes(decision, estimate)
    assert not consumes({**decision, "source_closing_accepted_boundary_ordinal": "602"}, estimate)
    assert not consumes({**decision, "source_acceptance_epoch": "3"}, estimate)
    assert not consumes({**decision, "capture_session": "2"}, estimate)
    assert not consumes({**decision, "time_domain": "rp2040_monotonic_us32"}, estimate)
    assert not consumes(decision, {**estimate, "estimator_timestamp_ticks": "2000124"})
    assert consumes({**decision, "decision_timestamp_ticks": str((1 << 32) + 50)},
                    {**estimate, "estimator_timestamp_ticks": (1 << 32) - 100})
