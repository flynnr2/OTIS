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
| `count_seq` | uint32 | closing `SNP.snapshot_sequence`; modulo-2^32 and qualified by the associated SNP capture session |
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
rising edges and atomically pushes its cumulative value when D14 satisfies the
reference condition. A bounded RX-FIFO IRQ drains the immutable word. The SNP
FIFO CPU service coordinate and its lower-bound uncertainty describe service,
not a hardware D14 latch. `REF` is emitted from the same owner as a canonical
raw derivative and does not independently define the count aperture.

A `CNT` row is emitted only when its opening and
closing atomic boundary observations are sequence-continuous. A nominal
timestamp interval and nonzero count do not establish a complete physical
aperture: `GATE_INCOMPLETE`, boundary overrun/order flags, snapshot failure,
zero count, or saturation make the row ineligible. A sequence gap with no
defensible opening timestamp produces `REF` plus `STS`, not a fabricated
`CNT`. Its `count_seq` is the 32-bit closing `SNP.snapshot_sequence`, so a lost
boundary remains visible as a sequence gap within one snapshot capture session.
`UINT32_MAX -> 0` is continuous within a session. A snapshot-backend rearm opens
a new session whose first snapshot is ordinal 0 and whose first possible clean
`CNT` closes at ordinal 1.

The CNT wire row has no capture-session field. A standalone
`count_observations_v1.csv` validator therefore checks its shape, field values,
domains, flags, and each gate's timestamp progression but cannot establish
sequence or timestamp ordering between rows. Decision-bearing replay joins CNT
rows to the unique adjacent same-session SNP pair by closing ordinal and
exact gate endpoints. That joined replay rejects duplicates, gaps, reordering,
cross-session apertures, and ambiguous service-coordinate progression.

See `docs/50_SOFTWARE/COUNT_OBSERVATION_MEASUREMENT_CONTRACT.md` for the full
contract.

## Current use

`CH2` is the sole oscillator/count role on D8 / GPIO20. Its source domain names
the physical CX317 10 MHz oscillator. D10 external-event evidence, D6 monitor
evidence, and D14 timestamps cannot replace or redefine a `CNT` observation.
