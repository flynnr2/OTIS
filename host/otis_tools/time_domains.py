"""Canonical timestamp-domain semantics for current OTIS evidence.

The domain name carried by a record (or inherited from its governing wire
contract) selects rollover behaviour.  Callers cannot opt into rollover with
an unrelated Boolean: unknown and contradictory domain declarations fail
closed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


RP2040_TIMER0_MICROS_WRAP_TICKS = (1 << 32) * 16


@dataclass(frozen=True)
class TimeDomain:
    name: str
    nominal_hz: int
    counter_width_bits: int | None
    modulus_ticks: int | None
    rollover: str

    @property
    def permits_rollover(self) -> bool:
        return self.rollover == "modular_forward"

    @property
    def maximum_unambiguous_forward_ticks(self) -> int | None:
        return self.modulus_ticks // 2 if self.modulus_ticks is not None else None


TIME_DOMAINS: Mapping[str, TimeDomain] = {
    "rp2040_timer0": TimeDomain(
        name="rp2040_timer0",
        nominal_hz=16_000_000,
        counter_width_bits=36,
        modulus_ticks=RP2040_TIMER0_MICROS_WRAP_TICKS,
        rollover="modular_forward",
    ),
    # CX321 plant-sign evidence carries firmware-extended TIMER0 coordinates.
    # These values are reconstructed monotonically across the 32-bit
    # microsecond source wrap and therefore must never be reinterpreted as the
    # modular raw timer domain above.
    "rp2040_timer0_extended": TimeDomain(
        name="rp2040_timer0_extended",
        nominal_hz=16_000_000,
        counter_width_bits=None,
        modulus_ticks=None,
        rollover="strict_nonwrapping",
    ),
    # D8 counted-edge totals are not RP2040 timer coordinates.  Current CSV
    # timestamp fields do not use this domain, but declaring its strict
    # non-wrapping semantics prevents an accidental timer-style inference.
    "h1_cx317_ocxo_10mhz": TimeDomain(
        name="h1_cx317_ocxo_10mhz",
        nominal_hz=10_000_000,
        counter_width_bits=None,
        modulus_ticks=None,
        rollover="strict_nonwrapping",
    ),
    "host_elapsed_ms": TimeDomain(
        name="host_elapsed_ms",
        nominal_hz=1_000,
        counter_width_bits=None,
        modulus_ticks=None,
        rollover="strict_nonwrapping",
    ),
    # Deterministic contract fixtures use a deliberately non-wrapping domain.
    "fixture": TimeDomain(
        name="fixture",
        nominal_hz=1,
        counter_width_bits=None,
        modulus_ticks=None,
        rollover="strict_nonwrapping",
    ),
    "fixture_100hz": TimeDomain(
        name="fixture_100hz",
        nominal_hz=100,
        counter_width_bits=None,
        modulus_ticks=None,
        rollover="strict_nonwrapping",
    ),
}


@dataclass(frozen=True)
class ForwardProgress:
    valid: bool
    distance_ticks: int | None
    rollover_count: int
    reason: str


def time_domain(name: str) -> TimeDomain:
    if not name:
        raise ValueError("timestamp domain is absent")
    try:
        return TIME_DOMAINS[name]
    except KeyError as exc:
        raise ValueError(f"unsupported timestamp domain {name!r}") from exc


def validate_domain_declarations(domains: object) -> tuple[str, ...]:
    """Validate current manifest declarations against canonical semantics."""

    if not isinstance(domains, list) or not domains:
        return ("run_manifest.json: domains must be a non-empty list",)
    errors: list[str] = []
    seen: set[str] = set()
    for index, value in enumerate(domains, start=1):
        if not isinstance(value, dict):
            errors.append(f"run_manifest.json: domain {index} is not an object")
            continue
        name = value.get("name")
        if not isinstance(name, str) or not name:
            errors.append(f"run_manifest.json: domain {index} has no name")
            continue
        if name in seen:
            errors.append(f"run_manifest.json: duplicate domain declaration {name!r}")
            continue
        seen.add(name)
        try:
            semantics = time_domain(name)
        except ValueError as exc:
            errors.append(f"run_manifest.json: {exc}")
            continue
        try:
            nominal_hz = int(value["nominal_hz"])
        except (KeyError, TypeError, ValueError):
            errors.append(
                f"run_manifest.json: domain {name!r} has no integer nominal_hz"
            )
            continue
        if nominal_hz != semantics.nominal_hz:
            errors.append(
                f"run_manifest.json: domain {name!r} nominal_hz={nominal_hz} "
                f"contradicts canonical {semantics.nominal_hz}"
            )
        optional = {
            "counter_width_bits": semantics.counter_width_bits,
            "modulus_ticks": semantics.modulus_ticks,
            "rollover": semantics.rollover,
        }
        for field, expected in optional.items():
            if field in value and value[field] != expected:
                errors.append(
                    f"run_manifest.json: domain {name!r} {field}={value[field]!r} "
                    f"contradicts canonical {expected!r}"
                )
    return tuple(errors)


def forward_progress(
    previous: int,
    current: int,
    *,
    domain: str,
    allow_equal: bool = True,
) -> ForwardProgress:
    semantics = time_domain(domain)
    if previous < 0 or current < 0:
        return ForwardProgress(False, None, 0, "negative_timestamp")
    if current == previous:
        return ForwardProgress(
            allow_equal,
            0 if allow_equal else None,
            0,
            "equal_timestamp" if allow_equal else "duplicate_timestamp",
        )
    if current > previous:
        distance = current - previous
        maximum = semantics.maximum_unambiguous_forward_ticks
        if maximum is not None and distance >= maximum:
            return ForwardProgress(False, None, 0, "excessive_ambiguous_gap")
        return ForwardProgress(True, distance, 0, "forward")
    if not semantics.permits_rollover or semantics.modulus_ticks is None:
        return ForwardProgress(False, None, 0, "illegal_backward_movement")
    if previous >= semantics.modulus_ticks or current >= semantics.modulus_ticks:
        return ForwardProgress(False, None, 0, "value_outside_domain_modulus")
    distance = semantics.modulus_ticks - previous + current
    maximum = semantics.maximum_unambiguous_forward_ticks
    if distance <= 0 or (maximum is not None and distance >= maximum):
        return ForwardProgress(False, None, 0, "illegal_or_ambiguous_wrap")
    return ForwardProgress(True, distance, 1, "rollover_forward")


def unwrap_domain_ticks(values: Iterable[int], *, domain: str) -> tuple[list[int], int]:
    raw = list(values)
    if not raw:
        return [], 0
    semantics = time_domain(domain)
    unwrapped = [raw[0]]
    wraps = 0
    for previous, current in zip(raw, raw[1:]):
        progress = forward_progress(previous, current, domain=domain)
        if not progress.valid or progress.distance_ticks is None:
            raise ValueError(
                f"{domain} timestamp progression {previous}->{current} is invalid: "
                f"{progress.reason}"
            )
        wraps += progress.rollover_count
        unwrapped.append(current + wraps * (semantics.modulus_ticks or 0))
    return unwrapped, wraps
