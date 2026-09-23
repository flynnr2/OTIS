from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from host.otis_tools import adaptive_hybrid_replay as replay
from host.otis_tools.time_domains import bounded_us32_capture_to_us64_decision


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
def test_instrument_decision_projects_bounded_raw_capture(
    captured: int, decision: int, expected: bool,
) -> None:
    assert bounded_us32_capture_to_us64_decision(captured, decision) is expected


def test_instrument_decision_joins_exact_selected_d14_d8_source(monkeypatch) -> None:
    estimate = {
        "estimate_id": "selected", "pass": True,
        "estimator_timestamp_ticks": "2000000",
        "time_domain": "rp2040_monotonic_us32",
        "source_capture_session": 1, "source_acceptance_epoch": 2,
        "source_opening_accepted_boundary_ordinal": 1,
        "source_closing_accepted_boundary_ordinal": 601,
        "accumulated_edge_error_counts": 0, "source_dac_epoch": 0,
    }
    decision = {
        "sequence": "1", "timestamp_ticks": "2000123",
        "capture_session": "1", "acceptance_epoch": "2",
        "opening_accepted_boundary": "1", "closing_accepted_boundary": "601",
        "edge_error_counts": "0", "dac_epoch": "0",
    }
    manifest = SimpleNamespace(root=Path("/unused"), files=[{
        "contract": "instrument_decision_v2", "path": "instrument_decision_v2.csv",
    }])

    def consumes(row, source):
        monkeypatch.setattr(replay, "_read_csv", lambda _path: [row])
        return replay.replay_instrument_decision_sources(
            manifest, {"selected_estimate_sources": [source]}
        )["exact"]

    assert consumes(decision, estimate)
    assert not consumes({**decision, "closing_accepted_boundary": "602"}, estimate)
    assert not consumes({**decision, "acceptance_epoch": "3"}, estimate)
    assert not consumes({**decision, "capture_session": "2"}, estimate)
    assert not consumes({**decision, "edge_error_counts": "1"}, estimate)
    assert not consumes({**decision, "dac_epoch": "1"}, estimate)
    assert not consumes(decision, {**estimate, "time_domain": "rp2040_timer_us64"})
    assert not consumes(decision, {**estimate, "estimator_timestamp_ticks": "2000124"})
    assert consumes({**decision, "timestamp_ticks": str((1 << 32) + 50)},
                    {**estimate, "estimator_timestamp_ticks": (1 << 32) - 100})
