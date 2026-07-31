# Phase 5 PPS-Gated Backend Qualification Report

## Decision

**Open / not qualified.** The active candidate is
`pio_wait_cumulative_snapshot_dma_v1`, with the physical boundary owned by one
PIO state machine. The historic Bench Run 001 exercised the rejected
`pps_isr_stop_sample_restart_v1` implementation and contains no raw cumulative
`SNP` evidence. It cannot be reused to qualify this candidate.

The enforced safety state remains:

```text
pps_gate/backend_qualified=false
status.control_ready=false
phase4_preview/actuation_authorized=false
no PPS/count-derived DAC write is authorized
```

## Current implementation

The 133 MHz PIO programme alternates oscillator-level `WAIT` instructions,
decrements X on each synchronized rising edge, tests PPS through independent
`JMP PIN` mapping, and autopushes `IN X, 32` once per accepted PPS. PIO owns the
count and snapshot boundary. DMA owns only completed-word transport into a
128-word ring. The D14 GPIO IRQ independently preserves physical REF events;
it does not stop, sample, restart, or otherwise control the counter.

The raw evidence chain is:

```text
REF: independent physical PPS observation
SNP: raw cumulative PIO down-counter plus REF association
CNT: adjacent, same-session modulo difference derived from two clean SNP rows
```

The first snapshot of every session is an anchor. Any reference/snapshot gap,
association loss, invalid status, FIFO stall, DMA error, ring overwrite,
oscillator outage, or reset invalidates continuity. Recovery requires two fresh
snapshots, and no late snapshot may be paired retroactively.

## Digital proof status

The checked-in instruction-level proof assembles the actual 15-word programme
and covers 256 oscillator phases at every integer duty from 35% through 65%:

```text
7,936 cases
55,552 reconstructed intervals
no missed or double-counted synchronized oscillator rising edge
boundary error only -1, 0, or +1 edge
maximum four PIO clocks from completed WAIT to opposite WAIT
```

It also verifies counter wrap, sequence/session semantics, mid-high startup,
finite oscillator-stop tail, full-FIFO failure, DMA ring capacity/wrap/
overwrite, installed pin mappings, synchronizers, autopush, PIO0 ownership,
133 MHz clock, divider 1, and fatal transport faults. This is a no-hardware
proof, not pad-level timing qualification.

## Host qualification rules

The qualification analyser now requires the `pps_snapshots_v1` source and
checks raw SNP reconstruction against every CNT. The official estimate is:

```text
official_raw_frequency = counted_edges / nominal_reference_interval
```

Timer-normalised frequency is retained only as a non-authoritative diagnostic.
It cannot override failed physical aperture, raw count, or continuity gates.
Reports separately expose raw jitter, timer-normalised diagnostic jitter,
quiet/load statistics, mean shift, invalid windows, physical PPS faults,
capture/storage faults, backlog, and parser/telemetry faults.

Pseudo-PPS generator truth (`PGT`), physical detection (`REF`), snapshot status
(`SNP`), and diagnostic policy remain separate evidence planes. Strict fault
scoring requires zero unexplained missed, false, duplicate, or misclassified
detections; exact outage/restoration transitions; invalid measurements around
faults; and clean two-snapshot recovery.

## Remaining hardware gates

The bench campaign in
`PPS_BACKEND_REMEDIATION_BENCH_HANDOFF.md` must still demonstrate:

1. actual D8 waveform duty, threshold integrity, and rise/fall behavior;
2. a 16 MHz PPS-to-oscillator phase sweep across the complete 62.5 ns period;
3. clean pseudo-PPS loopback and every required malformed-PPS class;
4. real-GPS quiet operation without false physical-outage or continuity loss;
5. alternating quiet/load equivalence using official raw counts;
6. population jitter no more than 1.5 Hz and quiet/load mean shift no more
   than 0.05 Hz;
7. extended resource, wrap, reset/session, and transport stability; and
8. a newly sealed overnight run directly comparable in procedure, but not in
   backend identity, to `candidate_20260730T192721Z`.

If the 16 MHz timing envelope fails on the assembled hardware, stop and use the
documented external counter/capture latch or CPLD fallback. ISR, DMA, or a
second PIO state machine must not be substituted as boundary owner.

Qualification never changes automatically from one run. Evidence review and a
deliberate later source change are required before the compile-time gate can be
set. Until then, the backend is engineering evidence only and control remains
blocked.
