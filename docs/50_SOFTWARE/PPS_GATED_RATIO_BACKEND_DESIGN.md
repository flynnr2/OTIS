# PPS-Gated Ratio Backend Design

## Scope and invariant

`OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO` counts oscillator rising edges on
`D8` / GPIO20 between PPS events on `D14` / GPIO26. It emits raw `REF` and
`CNT` evidence; frequency, ratio, ppm, estimation, and actuation remain outside
this backend.

Qualification status: accepted on 2026-08-01 for observe-only measurement
after the Phase 5 clean, fault, real-GPS, load, extended, and sealed overnight
campaign. The accepted limitations are the rising-edge-only width fault and
the physical phase/duty sweep that the installed ECS fixture cannot perform.

The governing invariant is:

> Foreground execution never defines the physical count aperture. A reference
> is usable only when its count boundary was captured by the same accepted PPS
> event with explicit sequence and validity provenance.

## Architecture decision

The production candidate is `pio_wait_cumulative_snapshot_dma_v1`:

```text
D8 / GPIO20 oscillator -- WAIT PIN --> one PIO0 state machine -- X--
D14 / GPIO26 PPS ------- JMP PIN ---> same state machine ------ IN X,32
                                                               autopush
                                                                  |
                                                           joined RX FIFO
                                                                  |
                                                         DMA transport only
                                                                  |
                                                        128-word SRAM ring

D14 GPIO IRQ --> independent reconstructed REF timestamp/diagnostics
foreground   --> associate immutable snapshot + REF, difference adjacent X
```

The same PIO state machine recognizes oscillator edges and copies its own
cumulative counter when PPS is high after an armed low. This makes the
physical aperture hardware-owned. It never stops, samples, resets, reloads, or
restarts the counter at PPS. ISR, DMA, USB, serial, and foreground latency occur
after the snapshot and cannot move it.

This separation was checked against the exact qualification-v4 ELF after the
sealed campaign. The resulting decision is not to optimize the aperture
speculatively: the PIO count/snapshot path is at the practical useful limit of
the integer-edge architecture, while the non-minimal D14 ISR is diagnostic
only. `PPS_CAPTURE_LATENCY_JITTER_AUDIT_20260801.md` is the normative regression
record for later firmware changes.

The edge-driven program alternates oscillator `WAIT` instructions. A stalled
`WAIT` evaluates every PIO clock; `JMP PIN` independently observes PPS between
oscillator levels. The checked-in 15-word listing and timing proof are in
`PPS_PIO_PROOF_AND_VERIFICATION.md`.

## Atomic observation and bounded transfer

The raw `SNP` snapshot plus its associated
`OtisPpsCountBoundaryObservation` contain:

- a session and modulo-\(2^{32}\) hardware snapshot sequence;
- the wrapping 32-bit cumulative PIO down-counter value;
- the independent D14 source sequence;
- the PPS event's reconstructed `rp2040_timer0` timestamp;
- the adjacent modulo difference used as the interval edge count;
- capture flags;
- physical-aperture flags.

The joined PIO RX FIFO holds eight words. A high-priority RX-DREQ-paced DMA
channel writes an aligned 128-word circular SRAM ring. DMA's monotonic transfer
count owns the producer ordinal; foreground alone owns the consumer. A distance
above 128, PIO `RXSTALL`, DMA AHB error, or unexpected DMA stop is explicit
continuity loss and starts a new session. The D14 record ring is separate and
cannot manufacture a hardware snapshot.

For this backend, emitted `CNT.count_seq` equals the closing boundary sequence.
The first boundary is sequence 0 and has no preceding window; the first clean
`CNT` therefore normally has sequence 1. A dropped boundary produces an
auditable `CNT` sequence gap rather than a newly packed foreground sequence.

For down-counter snapshots, `delta = previous_X - current_X mod 2^32`.
Sequence `UINT32_MAX -> 0` is also continuous. At 16 MHz a full counter wrap is
268.435456 seconds, while a valid REF interval is at most 1.2 seconds; a gap
that cannot exclude a full wrap is `counter_wrap_ambiguous`, not silently valid.

## Startup, missing PPS, and reacquisition

PIO starts in PPS-high state so a mid-pulse enable cannot fabricate a snapshot.
The first associated snapshot of a session is an anchor and emits no fabricated
`CNT`. The second clean adjacent snapshot may close the first interval.

When PPS is missing but the oscillator continues, PIO keeps counting and D14's
physical watchdog reports one outage transition. A later long boundary is
rejected. When the oscillator stops, PIO parks in `WAIT` and D14 continues
independently; the missing snapshot invalidates association. Resumption starts
a new session, clears old unread transport and pairing state, and requires a
fresh anchor plus adjacent snapshot. Duplicate, short, long, flagged,
sequence-gap, overflow, and
unavailable-boundary cases cannot become clean pairs.

If a boundary sequence is missing, the delivered interval count cannot be
honestly associated with the last foreground timestamp. Firmware preserves the
current `REF` and fault status but withholds that `CNT`, then uses the current
boundary as the next anchor.

## Independent validity dimensions

Foreground derives and reports these conclusions independently:

| Dimension | Required condition |
|---|---|
| reference interval | PPS interval and capture flags are acceptable |
| count boundary | the current PPS event completed the bounded boundary action |
| counter window | snapshot is available, aperture complete, wrap unambiguous, count nonsaturated and physically possible |
| observation pair | a previous atomic boundary exists and sequence is continuous |
| FIFO continuity | no sequence discontinuity or boundary-ring overflow |
| backend qualification | `OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED=1` |

Measurement validity requires the first five dimensions. Control eligibility
additionally requires a build/profile that reflects backend qualification plus
the existing startup, recovery, and clean-window gates. The checked-in
qualification candidate and all sealed campaign evidence set
`OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED=0`; they remain immutable and cannot
authorize control. The later acceptance decision does not retroactively change
those artifacts or authorize DAC actuation.

Typed reasons include:

- `boundary_capture_unavailable`;
- `boundary_sequence_gap`, `boundary_sequence_duplicate`;
- `boundary_observation_overflow`;
- `counter_snapshot_invalid`;
- `counter_wrap_handled`, `counter_wrap_ambiguous`;
- `physical_aperture_incomplete`;
- `reference_missing_pps`, `reference_pps_duplicate`,
  `reference_pps_short_interval`, `reference_pps_long_interval`;
- `reference_previous_boundary_invalid`;
- `count_zero`, `count_saturated`.

`GATE_INCOMPLETE` marks a physical aperture or pairing failure.
`REFERENCE_VALIDITY_SUSPECT` independently marks a reference failure.
Host qualification treats `GATE_INCOMPLETE`, boundary overflow/order flags,
zero, source-health faults, and saturation as count/aperture invalid. A
nonzero, nonsaturated count cannot override those flags.

## Telemetry policy

Every defensible completed pair emits one compact `CNT`; every delivered
boundary emits its `REF`. Stable windows do not emit a full status bundle.
Aggregate `pps_gate` and capture health is emitted every ten seconds by default.
Detailed status is emitted on the first pair, validity/control or anomaly-
reason transition, unpairable boundary, missing-PPS timeout, or explicit query.
Every repeated bounded anomaly still emits its flagged `CNT`; rate limiting
never suppresses the raw evidence.

`CONFIG?` emits one bounded, begin/end-delimited snapshot of compile-time and
backend metadata. Serial command intake is byte-bounded and processes at most
one complete command per loop pass. Boundary-ring draining precedes command,
DAC-sweep, environment, and periodic-status service. None of these service
paths can alter the PIO-owned aperture.

The CSV schema remains v1. Added `pps_gate` status keys are additive:
`boundary_owner`, `aperture_backend`, `backend_qualified`,
`boundary_sequence`, `boundary_validity`, `aperture_validity`,
`observation_pair_validity`, `fifo_continuity`, ring depth/capacity/drop
counters, and typed reason/counter fields. Existing emitters are single-
foreground-producer line writers; the disturbed Run 001 pre-reset frames were
caused by competing host serial ownership, not an identified concurrent
firmware writer.

## Resources and limitations

The backend claims:

- GPIO26 as a shared read-only PPS input: PIO boundary input and independent
  D14 GPIO REF observer;
- GPIO20, one dynamically allocated PIO0 state machine, and its 15-word
  program through `count_observation`;
- one dynamically allocated high-priority DMA channel and an aligned
  128-word SRAM snapshot ring.

The PIO and GPIO claims remain conflict-checked and visible through the resource
registry. A gated build with the CPU-timestamped PIO edge-queue capture backend
is rejected at compile time because that backend cannot provide an immediate
PPS-owned count boundary.

Remaining limitations are explicit:

- the D14 timestamp is read in the GPIO IRQ and carries
  `TIMESTAMP_RECONSTRUCTED`; it is gate-time evidence, not the count aperture;
- direct asynchronous frequency counting has normal boundary quantization of
  at most one oscillator edge in the proved digital model;
- stopped-oscillator recovery deliberately sacrifices PPS snapshots and fails
  closed;
- host/unit tests do not qualify pad-level waveform and timing margin.

Foreground backlog can cause explicit ring overflow, but it cannot shorten the
physical count aperture or change already-captured PIO words.
