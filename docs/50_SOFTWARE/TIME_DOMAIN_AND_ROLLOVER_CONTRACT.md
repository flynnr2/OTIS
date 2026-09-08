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

| Domain | Rate | Source and quantum | Width/modulus | Progress rule |
|---|---:|---|---:|---|
| `rp2040_monotonic_us32` | 1,000,000 us/s | native RP2040 `micros()`/`timerawl`; 1 us quantum | 32 bits; `2^32` us | modular forward; any interval at least half the modulus is ambiguous and rejected |
| `rp2040_monotonic_us64` | 1,000,000 us/s | session-bound reconstruction of `rp2040_monotonic_us32`; same 1 us quantum | 64-bit current wire value | strict non-wrapping |
| `h1_cx317_ocxo_10mhz` | 10,000,000 edges/s | counted D8 edges; 1 edge quantum | unbounded in current host evidence | strict non-wrapping |
| `host_elapsed_ms` | 1,000 ticks/s | host-local elapsed-time projection; 1 ms quantum | unbounded in current host evidence | strict non-wrapping |
| `fixture`, `fixture_100hz` | fixture-defined | fixture-defined | unbounded | strict non-wrapping test domains only |

`rp2040_monotonic_us32` carries the native wrapping 1 MHz Arduino `micros()` or
RP2040 `timerawl` value without rescaling. It is a local, non-metrological
ordering and telemetry coordinate. Its 1 MHz timer reference comes from the
board's RP2040 clock-generation tree, not D8; the normally 133 MHz `clk_sys`
CPU/PIO clock is not its timestamp quantum. It must not be used as the
metrological timebase for D10 events. A
lower raw value is a legal rollover only when the modular forward distance is
positive and less than half the modulus. Otherwise it is backward, reordered,
cross-session, corrupt, or ambiguous.

`rp2040_monotonic_us64` reconstructs the same native microsecond coordinate
across raw wraps within one capture session. Extension changes rollover
behaviour, not the underlying source, 1 us quantum, accuracy, or authority.

## Deferred D10 metrological domain

This cleanup does not introduce a D10 capture domain or change metrology
hardware. D14 remains the sole PPS/reference authority; D8 remains the
authoritative oscillator/count input, currently the 10 MHz VCOCXO; and D10
remains optional external-event evidence. Before a D10-bearing metrological
campaign, firmware must introduce and qualify a separate versioned D8-derived
hardware-capture domain with D14 session and anchor provenance. That work is
deliberately separate from removal of the obsolete local ×16 encoding.

## Boundaries

- Current raw values are native microseconds. Historical projected evidence is
  interpreted only by the exact historical revision that produced it; current
  code provides no alias or compatibility conversion.
- Derived extended values are reconstructed only after domain validation.
- Duplicate timestamps are accepted only where the consuming contract permits
  equality; interval endpoints require strictly positive progress.
- A declared capture-session or segmented-capture boundary clears temporal
  progression state. Consumers never bridge sessions by treating a reset as a
  rollover.
- Sequence continuity, session identity, gap limits, and domain progression
  remain independent checks. A legal timestamp wrap does not excuse a sequence
  gap or stale record.
- Current generators emit the complete canonical declaration and validators
  reject missing, obsolete, unknown, or contradictory declarations.

Current deterministic coverage includes ordinary progression, exact-boundary
and multi-record rollover, illegal backward movement, half-modulus ambiguity,
duplicates, unsupported and contradictory domains, capture segmentation,
snapshot reconstruction, accumulated-span estimation, relative-phase
estimation, supervisor cadence, CSV validation, and firmware/host replay
consumers.
