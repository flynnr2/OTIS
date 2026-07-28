# PPS Ownership Architecture

## Decision

The sparse reference capture backend is the sole firmware authority for a
physical PPS edge. It constructs one `OtisCapturedEdge` containing:

- channel and reference classification;
- edge polarity;
- the captured `rp2040_timer0` timestamp;
- capture provenance and quality flags.

That captured event is passed unchanged to all firmware consumers. The `REF`
emitter, IRQ reference diagnostics, and PPS-gated count backend must not sample
the pin or create another timestamp for the same edge.

This is an ownership decision, not a new telemetry abstraction. The existing
`REF`, `CNT`, and `STS` wire contracts remain unchanged.

## Event Flow

```text
D14 PPS edge
    |
    v
IRQ or sparse PIO capture backend
    |
    v
one OtisCapturedEdge(timestamp_ticks, flags)
    |--------------------------|
    v                          v
REF raw record          PPS-gated counter
                               |
                               v
                    CNT boundary + pps_gate STS
```

For the GPIO IRQ backend, raw and accepted-edge diagnostic counters are updated
from the same timestamp used in the queued `OtisCapturedEdge`. The capture ring
only transports that record; it does not timestamp it again.

The optional D10 dual observer remains a diagnostic witness of a separate
physical input. It may preserve independent witness evidence, but it is not a
second authority for D14 PPS, `REF`, or gated-count boundaries.

## Deterministic Consumption

Reference capture is serviced before the missing-PPS timeout check in each
foreground loop. This prevents a captured boundary already waiting in the
backend or ring from being declared missing first.

The PPS-gated backend receives the authoritative timestamp and flags directly.
It uses consecutive captured timestamps as `CNT.gate_open_ticks` and
`CNT.gate_close_ticks`. Flags from both boundary events are combined on the
bounded `CNT` observation so capture provenance is not lost.

The oscillator counter is stopped before serial emission of the corresponding
`REF` row. This minimizes foreground stop latency. Wire rows can therefore be
interleaved by record type; host replay must use the existing per-record
sequences and timestamps rather than assuming cross-type serial order.

## Evidence and Failure Behaviour

- Every accepted captured PPS remains a raw `REF` row.
- A GPIO IRQ ring overflow preserves raw IRQ diagnostic counts and reports the
  existing capture-drop telemetry; an unqueued edge cannot silently become a
  gated-count boundary.
- A missing stop event produces the existing explicit `pps_gate` fault and no
  invented clean `CNT` close boundary.
- Implausible captured intervals remain bounded raw observations with the
  existing reference-validity and incomplete-gate flags.
- No host schema or CSV column changes are required.

## Compatibility

The change is wire-compatible: record tags, columns, channel IDs, domains,
sequence counters, and status keys are unchanged. The intentional behavioural
change is that PPS-gated `CNT` boundaries now exactly reuse captured `REF`
timestamps instead of timestamps from a second foreground D14 poll.

The internal `otis_capture_ring_push_from_isr` interface now accepts a complete
`OtisCapturedEdge`. This prevents transport code from silently recapturing time.
It is an internal firmware API with no host impact.

## Engineering Notes

- Default and PPS-gated H1 firmware selectors must both compile.
- Regression tests enforce one timer read in the IRQ capture handler, no timer
  read in the capture ring, and no D14 polling in the PPS-gated counter.
- Backend validation should compare every bounded PPS-gated `CNT` open/close
  timestamp to the corresponding adjacent `REF` timestamps.

## Risk Assessment

| Risk | Treatment | Residual validation |
|---|---|---|
| Foreground PIO counter stop occurs after the physical edge | Counter handling runs before serial emission; captured timestamp remains exact evidence | Measure count bias and jitter on the bench |
| Capture backlog contains more than one PPS | Every event is replayed in order, but late counter stops cannot reconstruct hardware gating | Exercise host backpressure and verify overflow/status evidence |
| Timer rollover between boundaries | Existing timer-domain rollover extension remains in the gated backend | Retain rollover regression and bench crossing test |
| Host assumes `REF` precedes related `CNT` on the serial wire | Contracts already separate record sequences and provide timestamps | Confirm backend ingest does not impose cross-tag ordering |
| D10 witness is mistaken for PPS authority | Documentation explicitly limits it to diagnostic evidence | Check run manifests and status interpretation during backend validation |

## Backend Validation Handoff

Backend validation is ready to test:

1. two adjacent D14 `REF` events map exactly to each bounded `CNT` gate open and
   close timestamp;
2. PPS anomaly diagnostics classify the same intervals visible in raw `REF`;
3. missing PPS and capture overflow preserve explicit fault evidence;
4. default and PPS-gated firmware builds retain their existing wire contracts.
