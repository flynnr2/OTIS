from __future__ import annotations


RP2040_TIMER0_MICROS_WRAP_TICKS = (1 << 32) * 16


def unwrap_ticks(values: list[int], *, modulus: int = RP2040_TIMER0_MICROS_WRAP_TICKS) -> tuple[list[int], int]:
    """Unwrap RP2040 micros-derived tick streams across 32-bit micros rollover."""
    if not values:
        return [], 0

    unwrapped: list[int] = []
    offset = 0
    wraps = 0
    previous_raw = values[0]
    half_modulus = modulus // 2

    for value in values:
        if value < previous_raw and previous_raw - value > half_modulus:
            offset += modulus
            wraps += 1
        unwrapped.append(value + offset)
        previous_raw = value

    return unwrapped, wraps
