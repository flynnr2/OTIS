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

| Domain | Encoded rate | Source and quantum | Width/modulus | Progress rule |
|---|---:|---|---:|---|
| `rp2040_timer0` | 16,000,000 units/s | 1 MHz RP2040 microsecond counter multiplied by 16; 16 encoded ticks = 1 us quantum | 36 bits; `2^32 * 16` ticks | modular forward; any interval at least half the modulus is ambiguous and rejected |
| `rp2040_timer0_extended` | 16,000,000 units/s | session-bound reconstruction of `rp2040_timer0`; same 16-tick/1 us quantum | unbounded in current host evidence | strict non-wrapping |
| `h1_cx317_ocxo_10mhz` | 10,000,000 edges/s | counted D8 edges; 1 edge quantum | unbounded in current host evidence | strict non-wrapping |
| `host_elapsed_ms` | 1,000 ticks/s | host-local elapsed-time projection; 1 ms quantum | unbounded in current host evidence | strict non-wrapping |
| `fixture`, `fixture_100hz` | fixture-defined | fixture-defined | unbounded | strict non-wrapping test domains only |

`rp2040_timer0` is the projected firmware coordinate formed from the wrapping
1 MHz Arduino `micros()` or RP2040 `timerawl` microsecond counter by multiplying
each source count by 16. Its nominal 16 MHz value is an encoded coordinate
scale, not a native 16 MHz counter and not 62.5 ns capture resolution. Legal
values therefore advance in 16-tick quanta representing 1 us. It is a local,
non-metrological ordering and telemetry coordinate; it is not D8-derived and
must not be used as the metrological timebase for D10 events. A
lower raw value is a legal rollover only when the modular forward distance is
positive and less than half the modulus. The same observation is rejected as
backward, reordered, corrupt, or ambiguous when those conditions do not hold.

`rp2040_timer0_extended` reconstructs the same projected coordinate across raw
wraps within one capture session. Extension changes rollover behavior, not the
underlying source, 1 us quantum, accuracy, or authority.

## Deferred D10 metrological domain

This semantic correction does not introduce a D10 capture domain or change
firmware capture hardware. Existing D10 observations in `rp2040_timer0` remain
optional, local telemetry with zero timing, control, and terminal authority. A
future D10-bearing metrological campaign must first introduce and qualify a
separate versioned D8-derived hardware-capture domain, retain its D14 session
and anchor provenance, and preserve D10 isolation from authoritative D14/D8
capture. That work is deliberately deferred from this repair.

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
- Historical manifest declarations may omit the canonical source, encoding,
  quantum, coordinate-semantics, width, modulus, and rollover fields. Any
  provided contradiction is rejected. Current generators emit the complete
  declaration, and current campaign validators may require it.

Current deterministic coverage includes ordinary progression, exact-boundary
and multi-record rollover, illegal backward movement, half-modulus ambiguity,
duplicates, unsupported and contradictory domains, capture segmentation,
snapshot reconstruction, accumulated-span estimation, relative-phase
estimation, supervisor cadence, CSV validation, and firmware/host replay
consumers.
