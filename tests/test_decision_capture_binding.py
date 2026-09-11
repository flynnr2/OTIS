from __future__ import annotations

import pytest

from host.otis_tools.adaptive_hybrid_supervisor import AdaptiveHybridSupervisor
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


def test_actual_supervisor_binds_source_identity_as_well_as_capture_age():
    estimate = {
        "estimator_timestamp_ticks": "2000000",
        "time_domain": "rp2040_monotonic_us32",
        "source_reference_first_seq": "1",
        "source_reference_last_seq": "601",
    }
    decision = {
        "decision_timestamp_ticks": "2000123",
        "time_domain": "rp2040_monotonic_us64",
        "source_first_sequence": "1", "source_last_sequence": "601",
    }
    consumes = AdaptiveHybridSupervisor._decision_timestamp_consumes_estimate
    assert consumes(decision, estimate)
    assert not consumes({**decision, "source_last_sequence": "602"}, estimate)
    assert not consumes({**decision, "time_domain": "rp2040_monotonic_us32"}, estimate)
    assert not consumes(decision, {**estimate, "estimator_timestamp_ticks": "2000124"})
