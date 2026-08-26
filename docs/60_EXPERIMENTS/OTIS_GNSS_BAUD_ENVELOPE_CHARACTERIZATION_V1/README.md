# OTIS GNSS Baud-Envelope Characterization V1

## Status and authority

This document specifies a new, non-actuating GNSS serial-link experiment. It
does not authorize a firmware flash, reset, serial-device access, PMTK
transmission, physical acquisition, receiver reconfiguration, or any DAC or
control action.

The programme identity is
`OTIS_GNSS_BAUD_ENVELOPE_CHARACTERIZATION_V1`. Its purpose is to select the
highest defensible operational baud for the installed PA1616S/MT3339 receiver
and current OTIS service-plane topology while preserving enough evidence to
explain why each tested baud is clean, marginal, or unusable.

The programme is deliberately one continuous, provenance-linked physical run,
not a series of independent pass/fail attempts. Baud-local corruption,
metadata dequalification, transition failure, and recovery are scientific
observations. They degrade or terminate only the current baud segment unless a
separate platform, evidence, or unrecoverable-link condition makes the rest of
the programme impossible or invalid.

## Decision served

Answer one primary question:

> Across the five decision-bearing operating rates from 9600 through 115200,
> what is the highest rate that remains clean under the real OTIS workload, has measured
> receive-service margin, transitions and requalifies repeatably, and does not
> compromise D14/D8 timing capture?

The result must distinguish:

- receiver or electrical serial corruption;
- UART hardware overrun, framing, parity, or break evidence;
- raw UART acquisition starvation;
- firmware raw-ring or parser-consumer backlog;
- valid parser resynchronization after a genuinely incomplete line;
- expected metadata-quality changes unrelated to serial transport;
- planned baud transitions and the deliberately higher peak-status workload;
- USB/status workload coupling; and
- an unexercised or invalid evidence path.

Do not reduce the result to `115200 passed` or `115200 failed`. Produce a
per-baud operating envelope, a causal fault classification, and one selected
operational-baud recommendation or an explicit no-promotion result.

## Why this programme is needed

The transition mechanism is already physically credible, but runtime stability
at 115200 is not established:

- targeted-characterization Attempt 3 at 115200 ended with 2,662 valid
  metadata frames, 28 metadata checksum failures, 42 truncations, and one
  oversize record;
- Attempt 4 at 115200 ended with 18,343 valid metadata frames, 60 checksum
  failures, nine truncations, and three oversize records; and
- Attempt 6 at 9600 retained 137,028 valid metadata frames with zero checksum,
  truncation, oversize, configuration, transmit, or link-loss failures.

Those runs used different campaign revisions, durations, and live chronology.
They establish a real baud-correlated problem, but they cannot identify its
layer or provide a same-artifact baud comparison.

The current implementation has several good properties:

- fixed 96-byte metadata and 256-byte discovery collectors;
- `$` start synchronization, CR/LF handling, checksum validation, bounded
  field parsing, and explicit oversize discard;
- a new `$` before newline is treated as evidence that the preceding line was
  incomplete, not as a complete message;
- exact PMTK705 identity and PMTK514 or bounded observed-output confirmation;
- capture-first loop ordering;
- UART service at the top of the Core 0 loop and after every complete `STS`
  record; and
- D14/D8 timing work isolated on the protected timing path.

The current path nevertheless cannot localize the observed failures:

- UART0 is polled with a fixed 32-byte receive budget per service call;
- no hardware overrun, framing, parity, or break counters are recorded;
- maximum time between raw drains is unknown;
- FIFO/ring backlog and budget-exhaustion evidence is unavailable;
- link and metadata counters are lifetime totals that mix discovery,
  transition, stress, and steady-online phases;
- only 9600 and 115200 are compile-time operational targets; and
- there is no progressive, request-bound runtime baud-transition transaction
  for a continuous multi-baud run.

At 115200, 32 wire bytes span approximately 2.78 ms; at 9600 they span
approximately 33.33 ms. The fixed byte budget alone is not proof of starvation,
because loop cadence and hardware FIFO state are unmeasured. It does make the
missing drain-gap and hardware-error evidence decision-bearing.

The parser is not expected to parse a half-message merely because bytes arrive
quickly. It processes a line only at newline and resynchronizes at `$`. A
truncation therefore indicates an incomplete collected line, a malformed line,
or a parser-shape rejection. The new telemetry must identify which upstream
condition preceded it.

## Supported baud set and exact command boundary

Test exactly these documented rates:

| Baud | Fixed PMTK251 packet |
|---:|---|
| 9600 | `$PMTK251,9600*17\r\n` |
| 19200 | `$PMTK251,19200*22\r\n` |
| 38400 | `$PMTK251,38400*27\r\n` |
| 57600 | `$PMTK251,57600*2C\r\n` |
| 115200 | `$PMTK251,115200*1F\r\n` |

Do not test 4800 because it is below the decision range. Do not test 14400:
9600 is the already-proven floor and 19200 is the next decision-bearing
operating step, so 14400 would consume overnight time without changing the
primary selection logic. Do not invent or scan another intermediate rate.

Firmware may transmit only the constant packets above plus the already bounded
PMTK605, PMTK414, and PMTK314 query/configuration packets. A host may request a
declared target baud under the characterization profile, but it may never
supply raw receiver bytes or an arbitrary baud. Source guards and emitted-binary
inspection must prove that every allowed packet is present and no generic UART
transmit surface exists.

## Required receive-path hardening before the physical run

The physical comparison must characterize the receiver and a credible OTIS
implementation, not an avoidable polling blind spot. Before freezing a live
bundle, replace the direct polling-only byte path with the smallest bounded
Core 0 UART acquisition layer that supplies causal evidence.

### Fixed interrupt-backed raw ring

Use UART0 RX interrupt service owned by the existing GNSS UART resource:

1. The ISR drains the hardware RX FIFO until empty.
2. Each raw data-register read preserves the low eight data bits and its
   overrun, break, parity, and framing flags before any parser sees the byte.
3. Observations enter one fixed-size single-producer/single-consumer ring in
   exact arrival order. Each entry carries the data byte, hardware error flags,
   and an explicit loss-before marker when one or more preceding bytes could
   not be retained. No heap, parsing, formatting, logging, PMTK state
   transition, or telemetry emission is permitted in the ISR.
4. Keep the ISR hot path to direct FIFO-status/data-register reads, the minimal
   error/drop counters, and one lock-free SPSC enqueue. It may read the declared
   free-running counter once on entry and once on exit to measure service gap
   and residence time; it must not read a clock per byte, take a lock, call a
   callback, calculate ring high water, copy a snapshot, or clear unrelated
   interrupts. All reducible accounting and formatting belongs in the Core 0
   consumer.
5. The Core 0 service path drains the software ring into the existing link and
   metadata collectors with a prospectively frozen byte/time budget.
6. Ring capacity must hold at least two complete maximum configured-output
   bursts plus the longest legal PMTK response, with an explicit memory-budget
   result. Freeze the exact power-of-two capacity before the accelerated
   operational check.
7. Ring overflow is explicit evidence. It must never overwrite retained
   observations. Increment the dropped-byte count and attach a loss-before
   marker to the next retained observation. On that marker, the Core 0
   consumer closes both collectors under a raw-acquisition-loss reason before
   delivering the post-gap byte, so bytes on either side of a loss can never
   be stitched into one apparent message.
8. Enabling or disabling the UART IRQ must not change D14/D8 capture ownership,
   timing timestamps, or Core 1 authority.

Do not introduce a new DMA dependency unless deterministic testing shows the
bounded interrupt-backed ring cannot meet the declared envelope. UART DMA would
be a separately justified implementation change, not an automatic escalation.

### Service and hardware telemetry

Retain monotonic lifetime counters and segment-local baselines for at least:

- UART bytes observed and bytes dropped before retention;
- UART RX interrupt count, maximum bytes drained in one ISR, maximum ISR
  entry-to-entry gap, and maximum ISR residence time in an exact counter
  domain;
- hardware overrun, framing, parity, and break counts;
- raw-ring current depth, high-water mark, and overflow count;
- parser-consumer service-call count;
- maximum consumer-service gap in `rp2040_timer0` or another explicitly named
  monotonic domain with sufficient resolution;
- bytes drained per consumer call, maximum drain batch, budget-exhausted calls,
  and ring-nonempty-after-budget calls;
- checksum-valid and checksum-failed link frames;
- metadata checksum failures, parser drops, truncations, and oversize lines;
- RMC, GGA, and GSA counts, line-length extrema, and inter-frame-gap extrema;
- metadata hold count, cumulative duration, longest duration, and recovery
  latency;
- discovery, planned-transition, recovery, peak-load, and ordinary-online
  phases;
  and
- current baud segment, baud epoch, transition request, and evidence frontier.

Use segment deltas for conclusions. Wrong-baud discovery bytes and planned
transition effects must not contaminate ordinary- or peak-online fault rates.

When a parser fault occurs, retain a bounded sanitized fault capsule containing
the baud segment, phase, hardware-error deltas, raw-ring state, preceding
consumer gap, partial line length, delimiter/checksum classification, last good
frame sequence, and sentence type when recoverable. Do not log receiver
position fields or turn the programme into a raw NMEA location archive.

### Configured output cadence

The exact frozen PMTK output shape remains RMC/GGA/GSA-only. Historical Attempt
6 evidence shows approximately one RMC, one GGA, and two GSA frames per second
for this receiver, with total valid frames equal to that `1:1:2` cadence. Bind
and verify the actual line-length and cadence distribution rather than assuming
that the PMTK field value implies only one physical GSA line.

A different checksum-valid cadence is a configuration/receiver-behaviour
finding. It is not automatically a serial corruption result, and it must not be
silently normalized away.

## Progressive baud-transition transaction

Create one characterization-only progressive transaction. It must be disabled
in every non-characterization firmware profile.

Each request binds:

- campaign and firmware identity;
- request sequence and baud-segment identity;
- source baud and source baud epoch;
- one target from the fixed allowlist;
- command-table identity;
- exact current receiver identity and output configuration; and
- the expected prior completed transition.

The transaction is complete only after:

1. the request is accepted exactly once;
2. the metadata collector is explicitly closed and its partial line discarded
   under a planned-transition reason;
3. the fixed PMTK251 packet is physically transmitted and UART busy clears;
4. UART0 changes to the target rate;
5. a fresh checksum-valid PMTK705 response proves the receiver at that rate;
6. PMTK514 or the existing bounded observation fallback proves the exact
   output shape;
7. fresh checksum-valid RMC, GGA, and both normally observed GSA streams are
   received in the new baud epoch; and
8. the first dependent host segment snapshot contains the exact request,
   target, confirmed baud, baud epoch, identity, configuration, and fresh
   metadata frontier.

An acknowledgement that the host request was accepted is not transition
completion. Retransmission of the identical request must be idempotent; a
contradictory sequence, target, or source epoch is a platform fault.

### Bounded transition recovery

If target identity is not confirmed, perform one bounded scan of the five-rate
characterization set and record where the receiver is actually found. Do not
scan or target 4800: the installed receiver defaults to the already-proven
9600 rate, and 4800 adds no decision or recovery value to this programme.
Preserve the failed target transaction and recovered rate as separate facts.

If the receiver is recovered, classify the target segment as transition
unreliable and continue to the next scheduled target from the exact recovered
state. Do not loop indefinitely on the failed rate. If no supported rate
recovers the receiver after the frozen scan/deadline, retain D14/D8 capture for
the bounded recovery window and then use the programme-level
`serial_link_unrecoverable` terminal because subsequent baud transitions are no
longer executable.

## One continuous overnight physical programme

Use one firmware artifact, one flash, one capture session, one continuously
known USB serial owner, and no MCU reset between baud segments. Never write the
DAC. Compile out or source-guard every DAC/control write surface.

The first programme is a deliberately fast screen and soak, because the
retained 115200 faults appeared within minutes rather than days. It contains
exactly 12 confirmed-online hours plus bounded transition and recovery time:

| Segment | Baud | Confirmed-online duration | Purpose |
|---|---:|---:|---|
| S01 | 9600 | 20 min | opening known-good reference screen |
| S02 | 19200 | 20 min | first upward-sweep screen |
| S03 | 38400 | 20 min | first upward-sweep screen |
| S04 | 57600 | 20 min | first upward-sweep screen |
| S05 | 115200 | 20 min | first high-rate screen |
| S06 | 57600 | 45 min | separated return visit with peak workload |
| S07 | 38400 | 45 min | separated return visit with peak workload |
| S08 | 19200 | 45 min | separated return visit with peak workload |
| S09 | 9600 | 45 min | intermediate known-good comparison |
| S10 | 115200 | 6 h 5 min | primary high-rate soak under the intended workload |
| S11 | 9600 | 75 min | closing known-good soak and final state |

The five first-sweep segments total one hour 40 minutes. The four 45-minute
return visits total three hours. The 115200 soak and closing 9600 segment
complete the exact 12 hours. Every rate receives at least two separated visits;
115200 receives six hours 25 minutes total, and 9600 receives two hours 20
minutes total.

This is screening and operating evidence, not a multi-day failure-rate
qualification. If faults are absent, the retained frame denominator and `3/N`
bound determine whether a longer follow-up would materially change the baud
selection.

Record environmental covariates, but do not use nearby-air temperature to
excuse a serial error without causal evidence.

### Segment behaviour

Start duration accounting only after the progressive transaction and fresh
metadata requalification complete.

- Each 20-minute first-sweep visit runs the full ordinary intended workload
  without deliberate fault injection.
- Each 45-minute return visit runs 25 minutes of ordinary workload, 15 minutes
  of the peak status workload below, and five clean minutes that must
  re-establish stable counters and fresh metadata before the next transition.
- S10 runs 15 minutes of ordinary entry, 15 minutes of peak status workload,
  and five hours 35 minutes of uninterrupted ordinary soak.
- S11 runs 75 uninterrupted clean minutes at 9600. It contains no peak-load
  phase and establishes the final receiver state and closing comparison.

No planned raw-acquisition or parser-consumer gap is injected in this first
overnight programme. The new hardware-error, drain-gap, ring-depth, and parser
telemetry observes the margins and faults produced by the real workload. A
later targeted margin exercise is justified only if the overnight result is
clean but cannot distinguish a feasible rate because the measured headroom is
too small or unknown.

### Peak status workload

Use the real complete status/configuration path, not a synthetic CPU busy loop.
Freeze its maximum cadence from the existing operational host contract. Do not
send a new challenge until the preceding response has a complete end marker and
the host has drained it. Record challenge identity, response size, duration,
USB transport progress, UART ring high-water, and maximum UART consumer gap.

Do not intentionally obstruct the only evidence carrier during the live
characterization. Cover transport-obstruction detection and independent
bounded abort in the short offline operational check, where lost scientific
evidence cannot confound baud stability.

## Local degradation and programme stop semantics

The following are baud-segment evidence, not programme failures:

- checksum, truncation, oversize, or parser faults;
- UART hardware errors;
- raw-ring high water or overflow;
- metadata dequalification and recovery;
- failure to confirm one requested target when another frozen candidate rate
  recovers the receiver;
- a rate classified as unstable, marginal, or transition-unreliable.

During any metadata loss, D14/D8 capture and canonical evidence continue. No
control or DAC action exists to hold, resume, or fail.

Stop the programme early only for:

- D14/D8 capture loss, shared queue corruption, or evidence discontinuity that
  invalidates the non-interference claim;
- unknown or contradictory firmware, receiver, request, baud-epoch, or output-
  configuration identity;
- an emitted UART command outside the frozen fixed table;
- raw-ring memory/ordering corruption;
- loss of the sole USB serial owner or an evidence-carrier fault that prevents
  reliable continuation/finalization;
- receiver state unrecoverable at every frozen candidate rate after the bounded
  recovery procedure; or
- an independent operator stop.

Do not convert repeated baud-local faults into a generic fail-static terminal.
Continue until the schedule or a true programme stop condition is complete.

## Per-baud analysis and classification

Analyze ordinary, peak-load, transition, and recovery phases separately. For
every baud report:

- two-visit identities and environmental ranges;
- confirmed-online seconds and valid frames by type;
- bytes and frames between every ordinary-online hardware or parser fault;
- fault rates per byte, frame, and online hour;
- metadata availability and transport-caused hold duration;
- maximum ordinary-online raw-acquisition and consumer-service gaps;
- raw-ring high water and overflow;
- maximum UART ISR drain batch and maximum observed raw acquisition gap;
- maximum parser-consumer gap, ring high water, and remaining ring capacity;
- transition attempts, confirmations, latencies, failures, and recovered rates;
- D14/D8 and all shared service-plane health deltas; and
- whether both separated visits agree.

When an event count is zero, report the observed denominator and the finite
one-sided 95% Poisson upper-rate approximation `3/N`. Label it as a finite
empirical bound, not proof of a timeless failure probability or independence.

Assign exactly one steady-online class per baud:

1. `operationally_feasible_observed`;
2. `operationally_feasible_low_margin`;
3. `nominally_clean_insufficient_evidence`;
4. `transport_unstable`;
5. `platform_confounded`; or
6. `not_exercised`.

Also assign one independent transition class per baud:

1. `transition_reliable_observed`;
2. `transition_unreliable`;
3. `transition_platform_confounded`; or
4. `transition_not_assessed`.

Keep these dimensions separate. A baud can, for example, have clean
steady-online transport and an unreliable entry transaction, or have reliable
transitions but corrupt ordinary NMEA traffic. Report both facts rather than
letting one hide the other.

`operationally_feasible_observed` requires all of:

- zero ordinary-online UART hardware, raw-ring overflow, checksum, truncation,
  oversize, and parser-drop events in both separated visits;
- zero transport-caused metadata holds in ordinary and peak-load phases;
- exact identity and output configuration throughout both visits;
- no D14/D8 or shared-platform degradation;
- no evidence that the UART ISR failed to drain the available hardware bytes;
  and
- raw-ring high water no greater than half its capacity under the largest
  observed ordinary or peak-load consumer gap.

`operationally_feasible_low_margin` may be selected only when ordinary and
peak-load evidence is clean but ring headroom, service-gap evidence, or repeat
duration does not demonstrate the factor-of-two observed margin above. A baud
with any unplanned ordinary-online transport fault cannot
receive either feasible class in V1.

Use the remaining steady-online classes as follows:

- `nominally_clean_insufficient_evidence` means the retained online interval
  is clean but one or both planned visits or their required denominators did
  not complete, so V1 cannot claim the planned repeat evidence;
- `transport_unstable` means at least one unplanned online UART, ring,
  checksum, truncation, oversize, parser-drop, or transport-caused metadata
  hold event occurred in otherwise attributable evidence;
- `platform_confounded` means capture, telemetry, counter attribution, or
  shared-platform degradation prevents a defensible transport result; and
- `not_exercised` means no valid confirmed-online interval was obtained at that
  baud.

`transition_reliable_observed` requires every scheduled entry and exit for
that baud to complete within its frozen deadline and bind the first dependent
snapshot. Any failed target transaction produces `transition_unreliable`, even
when the receiver is recovered and the programme continues. Use
`transition_platform_confounded` when transaction evidence is invalid and
`transition_not_assessed` when no transaction involving that baud was validly
attempted.

Recommend the highest baud having both
`operationally_feasible_observed` and `transition_reliable_observed`. If none
exceeds 9600, retain 9600. Do not prefer a higher baud merely because its raw
error rate is small; the operational benefit must not be purchased with an
unexplained metadata hold, narrow service margin, or unreliable transition.

## Causal fault classification

Use the first available upstream evidence:

| First evidence | Primary interpretation |
|---|---|
| UART overrun | hardware FIFO was not drained within the arrival envelope |
| framing/parity/break without overrun | baud/framing/electrical/receiver serial evidence |
| raw-ring overflow without UART overrun | firmware consumer or service-plane backlog |
| parser fault with clean UART and ring | receiver byte content, collector semantics, or parser defect; inspect the sanitized capsule |
| metadata quality loss with clean serial framing | receiver solution/qualification change, not baud instability |
| D14/D8 degradation correlated with GNSS load | platform isolation defect, not a baud-local health veto |

Do not claim causation from checksum or truncation counts alone.

## Final state and programme terminals

S11 deliberately returns the receiver to 9600 as part of the authorized
schedule, not as an improvised post-failure restore. A healthy completion
requires fresh PMTK705 identity, exact output confirmation, and fresh RMC/GGA/
GSA evidence at 9600. If the receiver becomes unreachable, do not send blind
restoration commands; report the last confirmed rate and transition phase.

Deliver exactly one programme terminal:

1. `multi_baud_characterization_complete` — all scheduled segments completed,
   every baud has steady-online and transition classifications, and one
   recommendation exists;
2. `multi_baud_characterization_partial_receiver_recovered` — one or more
   segments could not complete, the receiver was recovered at a documented
   baud, final evidence is coherent, and the partial result remains useful;
3. `serial_link_unrecoverable` — no frozen candidate rate recovered the receiver
   within the frozen procedure, while retained evidence through that point is
   finalized; or
4. `programme_invalid_due_to_platform_or_evidence_failure` — capture,
   identity, ownership, ordering, telemetry, or finalization failure prevents a
   valid baud comparison.

A result in which one or several bauds are unstable can still be
`multi_baud_characterization_complete`.

## Required retained artifacts

Retain in `runs/otis_gnss_baud_envelope_characterization_v1/`:

- exact source, build, toolchain, ELF, UF2, command-table, and profile identity;
- immutable campaign contract and segment schedule;
- preflight and accelerated no-I/O operational-check reports;
- raw canonical D14/D8, status, environment, command, acknowledgement, and
  supervisor evidence;
- progressive baud-transition ledger;
- segment/phase ledger with exact counter baselines and deltas;
- sanitized UART/parser fault capsules;
- monitor state and transition history;
- per-baud analysis plus cross-baud comparison;
- seal, content-addressed snapshot, and registration evidence; and
- final physical receiver state.

Keep `runs/` ignored. Commit only reviewed contracts, schemas, tools, tests,
small deterministic fixtures, and reports.

## Proportionate preflight and operational check

Before requesting physical authority:

1. extend parser fixtures for every legal line shape and fault capsule;
2. deterministically test UART data/error extraction, raw-ring wrap, overflow,
   high water, and consumer budgets;
3. exercise every legal baud transition, same-target request, duplicate
   request, timeout, recovery-at-different-baud, and unrecoverable scan in the
   firmware/host transaction harness;
4. prove discovery and planned-transition counters are excluded from ordinary
   and peak-load online deltas;
5. prove all rate-local failures continue to the next segment while every true
   programme stop condition stops;
6. build the exact no-DAC characterization profile and inspect the binary for
   the complete fixed command table and absence of generic UART/DAC write
   surfaces;
7. run campaign-focused tests and the release-level checks required by the
   changed UART, protocol, and service-plane surfaces;
8. run one short accelerated no-I/O operational check through all eleven
   scheduled segments, local-fault continuation, final 9600 state, analyzer,
   seal, and registration; and
9. state that existing physical evidence already proves GNSS/RP2040 wiring,
   UART communication, PMTK exchange, and NMEA parsing, while the live run must
   establish only the new multi-baud transition path, high-rate stability, and
   real workload margin.

Do not build a programmable serial-source HIL campaign or requalify ordinary
GNSS communication. The short operational check protects only the newly added
transaction, scheduling, evidence-attribution, and finalization paths from
wasting the overnight run.

Only then freeze one exact non-effective candidate bundle and ask the operator
for explicit physical authority.
