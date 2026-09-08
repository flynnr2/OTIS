from __future__ import annotations

from .time_domains import (
    RP2040_MONOTONIC_US32_MODULUS,
    unwrap_domain_ticks,
)


def unwrap_ticks(values: list[int], *, domain: str) -> tuple[list[int], int]:
    """Reconstruct one declared timestamp domain without caller opt-in flags."""

    return unwrap_domain_ticks(values, domain=domain)
