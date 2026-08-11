from __future__ import annotations

from host.otis_tools.host_attach_health_contract import (
    FRESH_HOST_ATTACH_MAXIMUM_UPTIME_S,
    evaluate_host_attach_history,
    host_attach_uptime_observations,
)


def _rows(values: list[int]) -> list[dict[str, str]]:
    return [
        {
            "record_type": "STS",
            "status_seq": str(index),
            "component": "cx317_active",
            "status_key": "uptime_s",
            "status_value": str(value),
        }
        for index, value in enumerate(values, start=1)
    ]


def test_first_fresh_attach_uptime_is_retained_independently() -> None:
    rows = _rows([30, 612, 620])

    assert host_attach_uptime_observations(rows) == [
        (1, 30),
        (2, 612),
        (3, 620),
    ]
    result = evaluate_host_attach_history(
        rows, frozen_uptime_s=30, frozen_status_seq=1
    )

    assert result["exact"] is True
    assert result["within_fresh_host_attach_limit"] is True


def test_late_attach_is_rejected_even_if_later_pps_state_is_healthy() -> None:
    late = FRESH_HOST_ATTACH_MAXIMUM_UPTIME_S + 1

    result = evaluate_host_attach_history(
        _rows([late, 612]), frozen_uptime_s=late, frozen_status_seq=1
    )

    assert result["exact"] is False
    assert result["within_fresh_host_attach_limit"] is False


def test_attach_record_must_be_the_first_observed_uptime() -> None:
    result = evaluate_host_attach_history(
        _rows([30, 40]), frozen_uptime_s=40, frozen_status_seq=2
    )

    assert result["exact"] is False
    assert result["first_observation_matches_frozen_record"] is False
