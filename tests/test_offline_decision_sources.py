from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from host.otis_tools import adaptive_hybrid_replay as replay


def _manifest() -> SimpleNamespace:
    return SimpleNamespace(root=Path("/unused"), files=[
        {"contract": "instrument_decision_v2", "path": "instrument_decision_v2.csv"},
    ])


def _source() -> dict[str, object]:
    return {
        "estimate_id": "est:frequency_regulation:pps_gated_frequency:000001",
        "source_capture_session": 7,
        "source_acceptance_epoch": 2,
        "source_opening_accepted_boundary_ordinal": 101,
        "source_closing_accepted_boundary_ordinal": 701,
        "estimator_timestamp_ticks": 700_000_000,
        "time_domain": "rp2040_monotonic_us32",
        "source_dac_epoch": 7,
        "accumulated_edge_error_counts": 1,
        "pass": True,
    }


def _decision(**changes: str) -> dict[str, str]:
    row = {
        "sequence": "11", "capture_session": "7",
        "acceptance_epoch": "2", "opening_accepted_boundary": "101",
        "closing_accepted_boundary": "701", "edge_error_counts": "1",
        "timestamp_ticks": "700000123", "dac_epoch": "7",
    }
    row.update(changes)
    return row


def _replay(monkeypatch: pytest.MonkeyPatch, decisions: list[dict[str, str]],
            sources: list[dict[str, object]] | None = None) -> dict[str, object]:
    monkeypatch.setattr(replay, "_read_csv", lambda _path: decisions)
    return replay.replay_instrument_decision_sources(
        _manifest(), {"selected_estimate_sources": [_source()] if sources is None else sources}
    )


def test_instrument_decision_source_join_requires_exact_raw_selected_estimate(monkeypatch) -> None:
    result = _replay(monkeypatch, [_decision()])
    assert result["exact"] is True
    assert result["decision_count"] == 1
    assert result["consumed_selected_source_count"] == 1
    assert result["unconsumed_selected_source_count"] == 0
    assert result["joins"] == [{
        "decision_sequence": "11", "source_key": [7, 2, 101, 701],
        "estimate_id": _source()["estimate_id"], "exact": True,
    }]


@pytest.mark.parametrize("changes", [
    {"closing_accepted_boundary": "702"},
    {"timestamp_ticks": "760000001"},
    {"capture_session": "8"},
    {"acceptance_epoch": "3"},
    {"dac_epoch": "8"},
    {"edge_error_counts": "2"},
])
def test_instrument_source_join_rejects_missing_future_cross_session_or_numeric_source(
    monkeypatch, changes,
) -> None:
    result = _replay(monkeypatch, [_decision(**changes)])
    assert result["exact"] is False
    assert result["consumed_selected_source_count"] == 0
    assert result["error_count"] == 1


def test_instrument_source_join_rejects_unproven_or_duplicated_source(monkeypatch) -> None:
    source = {**_source(), "pass": False}
    assert _replay(monkeypatch, [_decision()], [source])["exact"] is False
    assert _replay(monkeypatch, [_decision()], [_source(), _source()])["exact"] is False


def test_instrument_source_join_allows_unused_estimates_and_zero_decisions(monkeypatch) -> None:
    result = _replay(monkeypatch, [])
    assert result["exact"] is True
    assert result["decision_count"] == 0
    assert result["selected_source_count"] == 1
    assert result["consumed_selected_source_count"] == 0
    assert result["unconsumed_selected_source_count"] == 1


def test_instrument_source_join_rejects_orphan_decision(monkeypatch) -> None:
    result = _replay(monkeypatch, [_decision()], [])
    assert result["exact"] is False
    assert result["selected_source_count"] == 0
    assert result["joins"][0]["estimate_id"] is None
    assert result["errors"] == ["IDC 11 has no unique exact selected D14/D8 source"]
