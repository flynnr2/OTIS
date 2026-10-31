"""Retained hardware counts and unpromoted source-shape comparisons."""

import hashlib
import json

import pytest

from tools.analyze_phase_excursion_case import (
    DEFAULT_CONTRACT,
    DEFAULT_FIXTURE,
    analyze,
    reconstruct,
)


def test_epoch305_comparison_preserves_source_and_separates_model_assumptions():
    before = DEFAULT_FIXTURE.read_bytes()
    result = analyze()
    assert DEFAULT_FIXTURE.read_bytes() == before
    assert (
        result["contract_sha256"]
        == hashlib.sha256(DEFAULT_CONTRACT.read_bytes()).hexdigest()
    )
    assert result["source_windows"]["selected_pre"] == {
        "signed_count_total": 4,
        "nonzero_span_count": 1,
        "maximum_absolute_single_span_count": 4,
        "first_half_count_total": 4,
        "second_half_count_total": 0,
    }
    cases = {r["name"]: r for r in result["synthetic_shapes"]}
    localized = cases["positive_localized"]
    persistent = cases["positive_persistent"]
    assert localized["first"]["nonzero_span_count"] == 1
    assert persistent["first"]["nonzero_span_count"] == 4
    assert localized["next"]["signed_count_total"] == 0
    assert persistent["next"]["signed_count_total"] == 4
    assert (
        localized["recorded_phase_arithmetic_projection"]
        == persistent["recorded_phase_arithmetic_projection"]
    )
    assert result["recorded_native_aggregate_projection"]["delta_codes"] == -20
    assert result["conditional_zero_FLL_retained_phase_projection"]["delta_codes"] == -1
    assert [
        r["fresh_state_local_classifier"]["classification"]
        for r in result["response_comparisons"]
    ] == [5, 1, 1]
    assert result["frozen_response_classification"] == 5
    assert result["authority"] == "offline_diagnostic_only"


def test_source_counter_corruption_cannot_be_normalized_into_the_study():
    fixture = json.loads(DEFAULT_FIXTURE.read_bytes())
    window = next(r for r in fixture["windows"] if r["name"] == "selected_pre")
    window["raw_snp"][-1][1] += 1
    with pytest.raises(AssertionError):
        reconstruct(window)
