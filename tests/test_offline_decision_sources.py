from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from host.otis_tools import adaptive_hybrid_replay as replay


def _manifest() -> SimpleNamespace:
    return SimpleNamespace(
        root=Path("/unused"),
        files=[
            {
                "contract": "active_hybrid_decisions_v2",
                "path": "active_hybrid_decisions_v2.csv",
            }
        ],
    )


def _source() -> dict[str, object]:
    return {
        "estimate_id": "est:frequency_regulation:pps_gated_frequency:000001",
        "estimator_sha256": "a" * 64,
        "source_capture_session": 7,
        "source_reference_first_seq": 101,
        "source_reference_last_seq": 701,
        "estimator_timestamp_ticks": 700_000_000,
        "time_domain": "rp2040_monotonic_us32",
        "frequency_error_hz": "0.001666666667",
        "accumulated_edge_error_counts": 1,
        "pass": True,
    }


def _decision(**changes: str) -> dict[str, str]:
    row = {
        "decision_sequence": "11",
        "capture_session": "7",
        "source_first_sequence": "101",
        "source_last_sequence": "701",
        "frequency_estimator_sha256": "a" * 64,
        "frequency_error_hz": "0.001666666667",
        "accumulated_edge_error_counts": "1",
        "decision_timestamp_ticks": "700000123",
        "time_domain": "rp2040_monotonic_us64",
    }
    row.update(changes)
    return row


def _replay(
    monkeypatch: pytest.MonkeyPatch,
    decisions: list[dict[str, str]],
    sources: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    monkeypatch.setattr(replay, "_read_csv", lambda _path: decisions)
    return replay.replay_active_decision_measurement_sources(
        _manifest(),
        {"selected_estimate_sources": [_source()] if sources is None else sources},
    )


def test_offline_decision_source_join_requires_exact_raw_selected_estimate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _replay(monkeypatch, [_decision()])

    assert result["exact"] is True
    assert result["decision_count"] == 1
    assert result["consumed_selected_source_count"] == 1
    assert result["unconsumed_selected_source_count"] == 0
    assert result["joins"] == [
        {
            "decision_sequence": "11",
            "source_key": [7, 101, 701],
            "estimate_id": _source()["estimate_id"],
            "exact": True,
        }
    ]


@pytest.mark.parametrize(
    "changes",
    [
        {"source_last_sequence": "702"},
        {"decision_timestamp_ticks": "760000001"},
        {"capture_session": "8"},
        {"frequency_estimator_sha256": "b" * 64},
        {"frequency_error_hz": "0.001666666668"},
        {"accumulated_edge_error_counts": "2"},
    ],
)
def test_offline_decision_source_join_rejects_missing_future_cross_session_or_numeric_source(
    monkeypatch: pytest.MonkeyPatch, changes: dict[str, str]
) -> None:
    result = _replay(monkeypatch, [_decision(**changes)])

    assert result["exact"] is False
    assert result["consumed_selected_source_count"] == 0
    assert result["error_count"] == 1
    assert result["joins"][0]["exact"] is False


def test_offline_decision_source_join_rejects_an_unproven_selected_source(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = {**_source(), "pass": False, "source_exact": False}
    result = _replay(monkeypatch, [_decision()], [source])

    assert result["exact"] is False
    assert result["joins"][0]["estimate_id"] == source["estimate_id"]
    assert result["joins"][0]["exact"] is False


def test_offline_decision_source_join_allows_unused_estimates_and_zero_ahy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    result = _replay(monkeypatch, [])

    assert result["exact"] is True
    assert result["decision_count"] == 0
    assert result["selected_source_count"] == 1
    assert result["consumed_selected_source_count"] == 0
    assert result["unconsumed_selected_source_count"] == 1
