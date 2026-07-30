# PPS-Gated Ratio Backend Design

## Scope and invariant

`OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO` counts oscillator rising edges on
`D8` / GPIO20 between PPS events on `D14` / GPIO26. It emits raw `REF` and
`CNT` evidence; frequency, ratio, ppm, estimation, and actuation remain outside
this backend.

The governing invariant is:

> Foreground execution never defines the physical count aperture. A reference
> is usable only when its count boundary was captured by the same accepted PPS
> event with explicit sequence and validity provenance.

## Architecture decision

The corrected backend uses the surgical PPS-ISR-owned implementation:

```text
D14 rising GPIO IRQ
  -> read one rp2040_timer0 timestamp
  -> disable/sample/restart the PIO oscillator counter
  -> publish one OtisPpsCountBoundaryObservation to a bounded SPSC ring

foreground
  -> pop that atomic observation
  -> validate sequence, reference interval, counter window and pairing
  -> emit the corresponding REF, bounded CNT, transition/anomaly STS
```

A continuous PIO counter with a PPS-triggered hardware latch remains the
preferred future endpoint. The current five-instruction PIO counter has no
direct cross-state-machine register snapshot path, and adding a routed
multi-state-machine/DMA fabric would be disproportionate to this correction.
The ISR backend removes the confirmed foreground aperture defect without
changing the higher-level observation semantics.

The ISR path uses only fixed register operations and one fixed-size ring push.
It contains no allocation, formatting, serial output, floating point,
estimator work, delay, blocking FIFO call, or other service-plane operation.
The counter is restarted before the observation is published.

## Atomic observation and bounded transfer

`OtisPpsCountBoundaryObservation` contains:

- a modulo-\(2^{32}\) boundary sequence;
- the PPS event's reconstructed `rp2040_timer0` timestamp;
- the interval edge count captured at that event;
- capture flags;
- physical-aperture flags.

The dedicated ISR-to-foreground ring has seven usable entries by default
(`OTIS_PPS_COUNT_BOUNDARY_RING_SIZE=8`). Producer and consumer indices have one
owner each. Compile-time checks require a power-of-two size and bounded
8-bit indices. A full ring increments a saturating `uint32_t` drop counter;
the next deliverable observation carries
`OTIS_PPS_APERTURE_OBSERVATION_OVERFLOW`. Its sequence gap prevents an
opportunistic join to an older `REF`. A boundary observation is the only source
for both its `REF` emission and count processing.

For this backend, emitted `CNT.count_seq` equals the closing boundary sequence.
The first boundary is sequence 0 and has no preceding window; the first clean
`CNT` therefore normally has sequence 1. A dropped boundary produces an
auditable `CNT` sequence gap rather than a newly packed foreground sequence.

Sequence continuity uses unsigned arithmetic, so `UINT32_MAX -> 0` is
continuous. Duplicate and gap relations are explicit. The interval-count
backend does not expose a cumulative counter wrap in normal one-second use.
The shared boundary helper nevertheless defines single-wrap unsigned
cumulative-snapshot subtraction for a future continuous backend; a delta above
the implementation maximum is `counter_wrap_ambiguous`, not silently valid.

## Startup, missing PPS, and reacquisition

The first PPS starts the physical counter and publishes a boundary with
`previous_boundary_unavailable` / `physical_aperture_incomplete`; it emits a
`REF` but no fabricated `CNT`.

When PPS is missing, foreground may report the timeout, but it does not stop or
restart the counter. Only a later PPS IRQ may close that aperture. The long
bounded observation is rejected by reference validity, followed by one
deterministic previous-boundary/reacquisition inhibit. Duplicate, short, long,
flagged, sequence-gap, overflow, and unavailable-boundary cases similarly
cannot become clean pairs.

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
additionally requires backend qualification plus the existing startup,
recovery, and clean-window gates. The checked-in qualification candidate sets
`OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED=0`; therefore it can produce bench
evidence but cannot authorize control.

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
paths can alter the IRQ-owned aperture.

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

- GPIO26 and its GPIO IRQ through the existing `edge_capture` owner, with role
  `pps_reference_and_count_boundary_irq`;
- GPIO20, one dynamically allocated PIO0 state machine, and its five-word
  program through `count_observation`;
- no DMA channel and no additional IRQ.

The PIO and GPIO claims remain conflict-checked and visible through the resource
registry. A gated build with the CPU-timestamped PIO edge-queue capture backend
is rejected at compile time because that backend cannot provide an immediate
PPS-owned count boundary.

Remaining limitations are explicit:

- the timestamp is read in the GPIO IRQ and carries
  `TIMESTAMP_RECONSTRUCTED`; it is not a hardware-latched timer capture;
- ISR entry latency and the bounded stop/sample/restart dead time contribute
  aperture quantisation;
- a future continuous hardware snapshot would remove restart dead time;
- host/unit tests do not qualify those hardware limits.

Foreground backlog can now cause an explicit observation-ring overflow, but it
cannot shorten the physical count aperture or trigger rapid stale
stop/restart operations.
