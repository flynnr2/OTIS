from __future__ import annotations

from host.otis_tools.pps_fault_alignment import classify_observed_interval


def test_observed_interval_classifier_covers_campaign_classes() -> None:
    assert classify_observed_interval(2_000) == "bounce_glitch"
    assert classify_observed_interval(50_000) == "double_edge"
    assert classify_observed_interval(750_000) == "short_interval"
    assert classify_observed_interval(900_000) == "negative_phase_step"
    assert classify_observed_interval(999_000) == "sustained_negative_offset"
    assert classify_observed_interval(1_000_000) == "nominal"
    assert classify_observed_interval(1_001_000) == "sustained_positive_offset"
    assert classify_observed_interval(1_100_000) == "positive_phase_step"
    assert classify_observed_interval(1_250_000) == "long_interval"
    assert classify_observed_interval(2_000_000) == "likely_missed_1_pps"
    assert classify_observed_interval(3_000_000) == "likely_missed_2_pps"
