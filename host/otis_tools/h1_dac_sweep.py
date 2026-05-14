from __future__ import annotations

from dataclasses import dataclass


BUILTIN_PROFILES = frozenset({"center_only", "tiny_plus_minus_1", "tiny_plus_minus_2"})


@dataclass(frozen=True)
class DacSweepStep:
    code: int
    dwell_ms: int


def clamps_configured(min_code: int, max_code: int) -> bool:
    return 0 < min_code <= max_code < 0xFFFF


def validate_step(code: int, min_code: int, max_code: int) -> bool:
    return min_code <= code <= max_code


def build_builtin_profile(
    profile_name: str,
    min_code: int,
    max_code: int,
    *,
    step_codes: int = 1,
    dwell_ms: int = 5000,
) -> list[DacSweepStep]:
    if profile_name not in BUILTIN_PROFILES:
        raise ValueError(f"unknown H1 DAC sweep profile: {profile_name}")
    if not clamps_configured(min_code, max_code):
        raise ValueError("DAC sweep profiles require configured non-rail clamps")
    if step_codes < 1:
        raise ValueError("step_codes must be at least 1")
    if dwell_ms < 1:
        raise ValueError("dwell_ms must be at least 1")

    center = (min_code + max_code) // 2
    if profile_name == "center_only":
        codes = [center]
    elif profile_name == "tiny_plus_minus_1":
        codes = [center, center + step_codes, center, center - step_codes, center]
    else:
        codes = [
            center,
            center + step_codes,
            center,
            center - step_codes,
            center,
            center + (2 * step_codes),
            center,
            center - (2 * step_codes),
            center,
        ]

    rejected = [code for code in codes if not validate_step(code, min_code, max_code)]
    if rejected:
        raise ValueError(f"profile {profile_name} exceeds DAC clamps: {rejected}")
    return [DacSweepStep(code=code, dwell_ms=dwell_ms) for code in codes]
