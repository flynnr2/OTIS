# count_observations_v1.csv

## Purpose

`count_observations_v1.csv` records the fixed D8 oscillator count between
adjacent qualified D14-triggered cumulative PIO snapshots.

It exists because the 10 MHz CX317 oscillator must not be represented as a raw
emitted edge stream. Firmware counts D8 edges in the hardware timing fabric and
emits compact observations.

## Schema

| Field | Type | Meaning |
|---|---|---|
| `record_type` | enum | compact record tag; `CNT` |
| `schema_version` | uint | schema revision; currently `1` |
| `count_seq` | uint64 | monotonic count-observation sequence within the run |
| `channel_id` | uint16 | oscillator/count observation channel |
| `gate_open_ticks` | uint64 | timestamp of gate/window open in `gate_domain` |
| `gate_close_ticks` | uint64 | timestamp of gate/window close in `gate_domain` |
| `gate_domain` | string | timing domain used for gate timestamps |
| `counted_edges` | uint64 | number of observed source edges during the gate |
| `source_edge` | enum | counted source edge: `R`, `F`, or `B` |
| `source_domain` | string | named source being counted, e.g. `h1_cx317_ocxo_10mhz` |
| `flags` | uint32 | numeric bitmask from `capture_flags_v1` |

## Example

```csv
record_type,schema_version,count_seq,channel_id,gate_open_ticks,gate_close_ticks,gate_domain,counted_edges,source_edge,source_domain,flags
CNT,1,42,2,100000000,101000000,rp2040_monotonic_us32,10000000,R,h1_cx317_ocxo_10mhz,0
```

## Semantics

A count observation says:

> Between these two gate timestamps, this many edges of this source were counted.

It does not by itself assert that the oscillator is disciplined, accurate,
locked, PPS-normalized, calibrated, or steerable. Those are higher-level derived
or control states.

`gate_open_ticks` and `gate_close_ticks` are raw gate boundary timestamps in
`gate_domain`. `counted_edges` is the raw observed source-edge count for that
gate. Frequency, ratio, ppm error, stability, and control eligibility are
derived by host tooling from `CNT`, `REF`, `STS`, manifest domains, and run
metadata.

Timestamp progression, including legal rollover, is derived automatically
from `gate_domain`. A caller cannot opt into modular handling independently of
the record. Unknown or contradictory domains, illegal backward movement, and
ambiguous half-modulus gaps fail closed; raw boundary values are not rewritten.

Invalid or startup-suspect windows are preserved when a bounded gate exists.
Firmware marks the `CNT` row with `capture_flags_v1` bits and emits diagnostic
`STS` rows. Host analysis may exclude flagged rows from derived frequency or
control summaries, but it must not delete them from raw artifacts.

If no honest close boundary exists, firmware should report the fault through
`STS` rather than fabricating a clean `CNT` row.

## Fixed backend semantics

One PIO state machine continuously decrements a wrapping 32-bit counter on D8
rising edges and snapshots its cumulative value when D14 satisfies the PPS
condition. DMA transports the immutable word. The D14 GPIO IRQ provides the
independent canonical `REF` timestamp but does not stop, sample, restart, or
otherwise define the count aperture.

A `CNT` row is emitted only when its opening and
closing atomic boundary observations are sequence-continuous. A nominal
timestamp interval and nonzero count do not establish a complete physical
aperture: `GATE_INCOMPLETE`, boundary overrun/order flags, snapshot failure,
zero count, or saturation make the row ineligible. A sequence gap with no
defensible opening timestamp produces `REF` plus `STS`, not a fabricated
`CNT`. Its `count_seq` is the modulo-\(2^{32}\) closing boundary sequence, so a
lost boundary remains visible as a sequence gap.

See `docs/50_SOFTWARE/COUNT_OBSERVATION_MEASUREMENT_CONTRACT.md` for the full
contract.

## Current use

`CH2` is the sole oscillator/count role on D8 / GPIO20. Its source domain names
the physical CX317 10 MHz oscillator. D10 external-event evidence, D6 monitor
evidence, and D14 timestamps cannot replace or redefine a `CNT` observation.
