# Phase 5 PPS-Gated Backend Qualification Report

## Decision

**Accepted on 2026-08-01 as the qualified observe-only PPS-gated measurement
backend, with the documented limitations below.** The active candidate is
`pio_wait_cumulative_snapshot_dma_v1`, with the physical boundary owned by one
PIO state machine. Its clean, fault-injection, real-GPS, alternating-load,
extended, and newly sealed overnight evidence supports progression to live
estimator/preview integration. This acceptance qualifies capture and
measurement semantics; it does not authorize DAC actuation. The historic Bench
Run 001 exercised the rejected `pps_isr_stop_sample_restart_v1` implementation
and contains no raw
cumulative `SNP` evidence; it was not reused.

The accepted evidence build and current checked-in qualification profile retain
this enforced safety state:

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

## Post-qualification latency and jitter audit

The exact v4 ELF used by the sealed overnight campaign was inspected after the
evidence review. The ELF contains the expected 15 PIO words, and its relevant
build-copied sources match the current PIO backend, D14 IRQ, capture ring,
boundary ring, and count-observation sources apart from generated `#line`
directives. The D14 callback timestamps first; its GPIO sampling, event
construction, diagnostics, and ring copy follow. The Arduino shared GPIO
dispatcher, XIP execution, non-inlined `micros()` call, and default IRQ priority
mean that this auxiliary REF timestamp is not an absolute minimum-latency GPIO
capture. None of those details lies inside the official PIO-owned count
aperture.

The overnight data reinforces that separation. Across 16,798 windows, the
correlation between reconstructed D14 interval variation and raw count was
approximately 0.004. Quiet/load distributions were similar and all transport
and continuity counters remained clean. At longer cumulative spans the proved
one-edge digital endpoint contribution falls as one edge per span, while the
observed block-to-block variation remains materially larger. The remaining
spread is therefore retained as end-to-end ECS/GPS/input/environmental
characterization, not reported as isolated firmware jitter.

No capture-firmware change was accepted from this audit. Future firmware must
preserve the anti-regression invariants in
`../50_SOFTWARE/PPS_CAPTURE_LATENCY_JITTER_AUDIT_20260801.md`; a shorter ISR may
improve diagnostic REF timing but must not be claimed to improve raw `CNT`.

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

Clean pseudo-PPS scoring also separates oscillator centre frequency from
boundary quantisation. The centre must be backed by an independent reference,
a fitted run mean, or a documented nominal expectation with an explicit
tolerance; it is not required to equal 16,000,000 exactly. The proved boundary
residual/adjacent-difference limit, quiet/load mean shift, continuity,
malformed-reference evidence, and parser loss remain independent hard gates.
For narrow glitches, REF-without-SNP is a legitimate fail-closed outcome only
when absence, association loss, no crossing CNT, late-word rejection, and
fresh anchor-plus-adjacent recovery are explicit.

## Hardware evidence disposition

The planned evidence in `PPS_BACKEND_REMEDIATION_BENCH_HANDOFF.md` is complete:

1. clean pseudo-PPS loopback passes; malformed-PPS scoring is 30/31 strict,
   with the sole 10 microsecond width-only glitch miss accepted and documented
   as a rising-edge-only observability limitation;
2. real-GPS quiet operation passes without false physical outage or continuity
   loss;
3. sequential and bracketed quiet/load runs pass digital/load integrity, with
   mean shifts retained only as characterization;
4. every declared short, extended, and overnight segment remains below the
   1.5 Hz coarse architecture-spread screen;
5. extended operation crosses timer wrap while resource, DMA, ring, transport,
   parser, and session counters remain clean; and
6. the newly sealed overnight v4 run contributes 16,798 exact windows across
   14 guarded quiet/load pairs, with zero loss or continuity fault.

The overnight v2 report's aggregate `failed` state is expected for a standalone
nominal run: only its fault-detection and post-fault-recovery checks fail
because no faults were injected there. All other acceptance checks pass. The
separate pseudo-PPS evidence supplies fault classification and recovery; the
campaign conclusion is therefore based on the evidence set, not on pretending
that one quiet run exercised every mode.

Actual D8 waveform measurement and the controlled phase/duty sweep are not
supported by the current ECS fixture and are recorded as not tested and
non-blocking. If a later capable fixture shows
that the 16 MHz timing envelope fails on the assembled hardware, stop and use the
documented external counter/capture latch or CPLD fallback. ISR, DMA, or a
second PIO state machine must not be substituted as boundary owner.

Qualification never changes automatically from one run. The deliberate review
was completed and accepted on 2026-08-01. Existing sealed artifacts remain
immutable and therefore continue to report `backend_qualified=false`; the
checked-in qualification build also remains fail-safe. Reflecting acceptance
in a future operational build is a separate, reviewed source/profile change.
Even then, backend qualification alone must not make a `CTL` row actionable or
authorize a DAC write: control remains blocked until the guarded-actuation gate
is separately approved.
