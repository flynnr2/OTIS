# Current Metrology Claim

## Status and scope

This document is the current claim boundary for the stabilized OTIS platform.
It applies to the Arduino Nano RP2040 Connect, the fixed
`pio_wait_cumulative_snapshot_fifo_irq_v2` D14/D8 capture mechanism, and the physical
CX317 oscillator topology. It is an experimental measurement claim, not a
calibration certificate or a claim that control action proves correctness.

OTIS currently supports:

- bounded digital oscillator-edge count over accepted nominal PPS intervals;
- frequency derived from those integer counts using the declared nominal
  interval duration; and
- session-local, arbitrary-epoch relative phase expressed in oscillator cycles
  and a nominal time equivalent.

OTIS does not currently claim traceable absolute frequency, calibrated phase,
UTC alignment, reference or cable-delay calibration, combined or expanded
uncertainty, phase lock, or holdover.

## Frequency meaning and digital bound

For a clean span containing `N` accepted nominal one-second PPS intervals:

```text
total_counted_edges = sum(exact same-epoch accepted-span D8 counts)
experimental_frequency_hz = total_counted_edges / (N * 1 nominal second)
digital_count_increment_hz = 1 / N
```

The accepted instruction proof found endpoint allocation error of only `-1`,
`0`, or `+1` oscillator edge over every contiguous tested span of one through
seven intervals; it did not accumulate once per interval. Subject to the
unchanged proof-bound PIO program, clock, pin, synchronizer, snapshot, FIFO,
bounded FIFO transport, and validity assumptions, the supported digital component is therefore
one oscillator edge total over a clean span. Expressed as a span mean, this is
`1/N Hz` at a nominal `N`-second duration. It is a digital architecture bound,
not the uncertainty of the complete instrument.

The denominator is nominal PPS duration. Reconstructed RP2040 timer timestamps
are diagnostic evidence and do not redefine the hardware aperture or silently
calibrate the PPS reference. A result must therefore be described as an
experimental PPS-referenced frequency observation unless every missing
physical and calibration component has been established independently.

## Relative-phase meaning and units

Within one continuous phase epoch:

```text
interval_edge_error_cycles = interval_edges - declared_nominal_edges
relative_phase_cycles = sum(accepted interval_edge_error_cycles)
relative_phase_time_ns = relative_phase_cycles * 100 nominal ns/cycle
```

The `100 ns/cycle` conversion comes only from the declared nominal CX317
frequency of 10 MHz. It is a nominal unit conversion, not 100 ns absolute-time
accuracy, capture resolution, or calibrated delay. Positive edge error
increases the reported relative phase. The epoch zero is arbitrary at the
opening snapshot of a continuous session.

Session changes, acceptance-epoch changes, reset evidence, unbridgeable reference evidence,
unbounded or ambiguous recognition timing, sequence discontinuity, and ambiguous
counter wrap end the epoch. No guessed offset bridges them. A healthy DAC epoch
transition may remain inside the same raw phase epoch only while physical
capture continuity is preserved. An excluded early candidate or delivery-only
control hold preserves that history; this does not make the DAC observation or a
derived controller authoritative.

## Evidence and limitations

The unchanged PIO counting claim draws on the historical capture audit below.
That record used DMA transport and does not qualify the new FIFO IRQ adapter:

- the exact PIO instruction audit covered 7,936 phase/duty cases and 55,552
  adjacent intervals;
- span error remained within one edge total for every tested contiguous span
  from one through seven intervals;
- the sealed overnight campaign contained 16,798 traceable one-second windows
  with no PIO, DMA, ring, parser, session, or continuity fault; and
- service-plane load did not exhibit correlation with raw count in that record.

The current firmware changes do not alter the proof-bound aperture. Any change
to a bound PIO word, clock, divider, synchronizer, pin, state-machine ownership,
snapshot rule, FIFO/autopush setting, or transport semantics invalidates
reuse of the digital proof until its required verification is repeated.

The following components remain unavailable or unqualified:

- exact receiver revision and operating-state-dependent PPS timing bound;
- antenna, propagation, PPS cable, level-conversion, pad-threshold, and board
  delay calibration;
- physical D8/PPS phase and duty-cycle margin across the supported electrical
  envelope;
- independent traceable frequency or time-interval comparison;
- calibration, correlation, drift, environmental, and reference components
  needed for a combined uncertainty; and
- a coverage factor and distribution supporting expanded uncertainty.

Receiver presence, pulse cadence, or a clean digital validity state is not
physical PPS qualification. Unknown components stay `unavailable`; empirical
spread must not be relabelled as calibrated uncertainty.

## Platform completion bench gate

The operational-path rehearsal may support this bounded claim only by
confirming that the exact fixed image preserves the declared mechanism identity,
resource ownership, coherent status, continuous serial capture, queue and
memory margins, transport-obstruction recovery, independent priority abort,
same-owner evidence rotation, analysis, and sealing without a
capture-invalidating fault. That rehearsal is not a new calibration and cannot
close the physical limitations above.

## Normative sources

- `COUNT_OBSERVATION_MEASUREMENT_CONTRACT.md`
- `PPS_CUMULATIVE_SNAPSHOT_SPAN_ESTIMATOR.md`
- `PPS_CAPTURE_LATENCY_JITTER_AUDIT_20260801.md`
- `OTIS_REFERENCE_TERMINOLOGY.md`

## Candidate reference-selection limitation

The integrated acceptance candidate uses an inclusive ±1.25 ms local timing
window after eight acquisition intervals. It retains the actual raw endpoints
and each intervening fragment, and can therefore exclude a gross early edge
without discarding a continuously measured nominal span. This admission rule
cannot identify an impostor inside the same window. Its numerical and retained
recording checks do not qualify the receiver electrically or establish a new
physical 72-hour result. The original recorded attempts retain their original
contracts and outcomes. See `data_contracts/reference_acceptance_v2.md` for the
current policy and required integration gates.

The current selector applies that window to the entire PIO-recognition bracket,
not merely its CPU-service endpoint. A bracket crossing either limit withholds
qualification. This is an explicit change from independent GPIO timestamp
association; it does not measure electrical D14 edge timing. No current result
claims measured capture-to-service latency. See `SINGLE_REFERENCE_OWNER_REPAIR.md`.
