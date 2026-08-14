# Time-Domain and Rollover Contract

## Status

Normative for current `CX319_EVIDENCE_EPOCH_1` validators, estimators,
supervisors, replay, analysis, and sealing paths. The executable authority is
`host/otis_tools/time_domains.py`.

## Rule

Rollover behavior is selected by the timestamp's declared or contract-inherited
domain. A caller cannot enable rollover with an unrelated Boolean, modulus, or
other optional switch. An absent, unsupported, or contradictory domain fails
closed.

| Domain | Nominal rate | Width/modulus | Progress rule |
|---|---:|---:|---|
| `rp2040_timer0` | 16,000,000 ticks/s | 36 bits; `2^32 * 16` ticks | modular forward; any interval at least half the modulus is ambiguous and rejected |
| `h1_cx317_ocxo_10mhz` | 10,000,000 edges/s | unbounded in current host evidence | strict non-wrapping |
| `host_elapsed_ms` | 1,000 ticks/s | unbounded in current host evidence | strict non-wrapping |
| `fixture`, `fixture_100hz` | fixture-defined | unbounded | strict non-wrapping test domains only |

`rp2040_timer0` is the reconstructed firmware coordinate formed from the
wrapping Arduino/RP2040 microsecond counter and the 16 MHz tick projection. A
lower raw value is a legal rollover only when the modular forward distance is
positive and less than half the modulus. The same observation is rejected as
backward, reordered, corrupt, or ambiguous when those conditions do not hold.

## Boundaries

- Raw pre-wrap and post-wrap values remain unchanged in canonical evidence.
- Derived extended values are reconstructed only after domain validation.
- Duplicate timestamps are accepted only where the consuming contract permits
  equality; interval endpoints require strictly positive progress.
- A declared capture-session or segmented-capture boundary clears temporal
  progression state. Consumers never bridge sessions by treating a reset as a
  rollover.
- Sequence continuity, session identity, gap limits, and domain progression
  remain independent checks. A legal timestamp wrap does not excuse a sequence
  gap or stale record.
- Manifest declarations may repeat canonical width, modulus, and rollover
  fields, but any contradiction is rejected.

Current deterministic coverage includes ordinary progression, exact-boundary
and multi-record rollover, illegal backward movement, half-modulus ambiguity,
duplicates, unsupported and contradictory domains, capture segmentation,
snapshot reconstruction, accumulated-span estimation, relative-phase
estimation, supervisor cadence, CSV validation, and firmware/host replay
consumers.
