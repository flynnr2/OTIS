# OTIS Reference Terminology

OTIS is a timing and metrology system. In this domain, apparently simple words such as timestamp, phase, raw, adjusted, disciplined, synchronized, lock, and holdover carry precise technical meaning.

This document defines reference terminology for OTIS documentation, data contracts, firmware interfaces, host tooling, and analysis reports.

It is deliberately more precise than a casual glossary. The intent is to prevent semantic drift as OTIS grows beyond a single firmware target or use case.

---

## Design Rules

### Raw observations are sacred

Raw captured timing observations should not be silently overwritten, normalized, or retroactively reinterpreted.

Derived values may evolve. Raw observations should remain replayable.

### Provenance must be explicit

Every timing value should make it possible to answer:

- what generated this value;
- what clock or counter domain it belongs to;
- whether it was captured, reconstructed, projected, adjusted, or estimated;
- what reference, if any, was used;
- what uncertainty or policy decision remains embedded in the value.

### Capture and interpretation are separate concerns

OTIS firmware should primarily capture events and preserve enough metadata for later reconstruction.

Host-side software should normally own interpretation, including pendulum analysis, oscillator characterization, Allan deviation, event classification, phase analysis, and application-specific models.

Metrology required by the instrument's selected live controller remains a
firmware responsibility. Offline host interpretation does not make a connected
host the owner of firmware operating state or a prerequisite for the intended
standalone instrument.

### Domains are not optional

Two numeric timestamps with the same unit are not necessarily comparable. They may come from different timing domains.

Any cross-domain comparison must be explicit about the reconstruction, projection, or synchronization step that made the comparison meaningful.

---

## Core Terms

### Event

An observable occurrence in time.

Examples:

- PPS edge;
- photogate transition;
- comparator crossing;
- oscillator edge;
- RF transition;
- external trigger.

An event is conceptual. It exists whether or not OTIS successfully captures it.

### Capture

The act of recording timing information associated with an event.

In OTIS, capture usually means hardware-latched timing acquisition rather than CPU-latency-defined timing.

Examples:

- event-system to timer-capture hardware;
- PIO edge capture;
- timer compare/capture register latch;
- deterministic hardware timestamping fabric.

Capture is observation, not interpretation.

### Timestamp

A numeric representation of when an event occurred relative to a specific timing domain.

A timestamp is:

- domain-relative;
- quantized;
- finite precision;
- not automatically UTC;
- not automatically synchronized;
- not automatically globally comparable.

Examples:

- raw counter ticks;
- software-extended timer ticks;
- reconstructed local ticks;
- projected nanoseconds;
- UTC estimate.

Avoid using timestamp as a synonym for wall-clock time.

### Counter

A monotonically advancing hardware or software-extended value used to measure elapsed time inside a domain.

Examples:

- 16-bit timer;
- software-extended 32-bit timer;
- 64-bit monotonic counter;
- cycle counter;
- RP2040 timer.

Counters define local timing domains. They are not inherently synchronized to external time.

### Actuator monotonic seconds

The wrapping unsigned 32-bit projection of the Arduino/RP2040 monotonic
millisecond counter used only for actuator transaction expiry on both cores.
It is not a capture timestamp, UTC, or `rp2040_monotonic_us32` evidence coordinate.
Intervals are compared with wrap-safe signed differences and must remain below
half the representation range.

### RP2040 monotonic microseconds

The RP2040-local operational coordinate used for record ordering, deadlines,
telemetry, and non-metrological interval checks. Its raw canonical domain is
`rp2040_monotonic_us32`: the native wrapping 32-bit `micros()`/`timerawl`
microsecond count. One coordinate unit is exactly one microsecond; the nominal
rate is 1,000,000 units per second and the modulus is `2^32` microseconds.

`rp2040_monotonic_us64` is the non-wrapping, session-bound reconstruction of
that raw coordinate. Firmware forms it from successive D14 observation
timestamps by adding each wrap-safe adjacent interval. Nearby setup,
application, and acknowledgement instants may be projected into it only when
the retained session and distance make that projection unambiguous. Extension
changes rollover behaviour, not source, resolution, accuracy, or authority.

Both domains come from the RP2040 timer peripheral's 1 MHz reference, derived
from the board's RP2040 clock-generation tree. They are not derived from D8.
The normally 133 MHz `clk_sys` CPU/PIO operating clock is a separate clock-tree
output, not the timer's timestamp quantum; choosing native microseconds here
changes neither clock. These domains must not be presented as the
metrological timebase for D10 events.

The metrology path is separate: D14 is the sole authoritative PPS/reference
input, D8 is the authoritative oscillator/count input (currently the 10 MHz
VCOCXO), and D10 is the external event input to be measured against that
D14-disciplined D8 timebase. Local RP2040 timestamps may order or transport
those records, but cannot substitute for the D8-derived hardware capture.

### Retained acquisition frontier

The opening D14/SNP boundary of the first uniquely reconstructable interval
retained by a recorder under a policy frozen before acquisition. This is a
statement about recorded evidence coverage, not the beginning of physical
capture, a new clock epoch, a timing correction, or permission to reset the
instrument. Earlier received rows remain explicit unqualified evidence. The
recorded frontier cannot advance to exclude later faults. An estimator source
is complete only when every interval on which it depends is retained after
that frontier and independently verified.

### Accepted reference and accepted span

A reference observation admitted under an explicit, versioned selection
policy. The last accepted reference is an interpretation anchor; it is
distinct from the latest raw edge, the raw capture session and the recorder's
retained acquisition frontier. An excluded candidate cannot silently become
that anchor.

An accepted span is a derived D8 count between two admitted raw D14/SNP
endpoints. It retains the complete intervening raw source, including any
excluded candidates. Its accepted-boundary ordinal and acceptance epoch must
not be substituted for raw source ordinals or a phase epoch. The integrated candidate records these identities separately in APS and the
versioned estimator, phase and active-control records. Raw adjacent CNT
records retain their original meaning.

### Instrument operating policy and evidence profile

An instrument operating policy specifies who may authorize control, how the
oscillator is qualified and steered, and how holds, faults and configuration
transitions behave. An evidence profile specifies the observations and derived
records delivered to a consumer, their rate/coverage bounds and loss semantics.
They are distinct: changing output detail does not transfer control ownership.
Standalone control and compact output are intended future capabilities, not
properties already established by the current supervised campaign.

### Capture-to-service latency

A diagnostic interval between a precisely identified capture event and a
precisely identified software-service observation in a common or explicitly
related clock domain. Its name must state the actual endpoints. Current OTIS
records FIFO-word-read service coordinates and later software-stage endpoints
in the RP2040 timer domain. The independent D14 GPIO ISR has been removed.
The PIO D8 count snapshot does not latch that timer; neither the service
coordinate nor its conservative recognition bracket is a measured hardware
start marker. Software-stage intervals exclude all delay before their named
start and cannot be called physical-edge-to-service or PIO-latch-to-ISR latency.

### Host written

A host-operation observation that the sole serial carrier completed writing a
command's bytes. It does not mean firmware received, authorized, applied, or
observed the requested action. Those are separate correlated device phases.

### Current status generation

The newest complete coherent snapshot generation, provided that no newer
generation has begun incompletely or faulted. For attachment-sensitive
authority it must also carry the exact solicited post-attachment nonce.

### Active decision production time

The current active decision's `decision_timestamp_ticks` identifies the actual
Core 1 decision-production instant, extended within its capture session into
`rp2040_monotonic_us64`. It orders lifecycle transitions and governs operational
cadence. It is distinct from the D14 boundary at which the source estimate
closed. The estimate keeps its captured coordinate and exact source sequences;
a declared bounded source-before-decision relation joins the two. The
`decision_timestamp_s` field is a display projection of that same exact tick,
never an independently sampled clock or a replacement for exact comparisons.

### Transport obstruction horizon

The declared maximum total interval for which a formatted output frame may
remain pending. Intermittent byte progress does not extend it. Reaching the
horizon is a transport fault and an evidence-continuity boundary; it is not a
statement about timing capture truth before the fault.

### Quantization

The finite resolution imposed by the tick rate of the timing source.

Examples:

- the native RP2040 local coordinate has 1 us ticks;
- the current 10 MHz D8 VCOCXO count has a 100 ns cycle;
- a native 16 MHz counter would have 62.5 ns ticks.

Quantization is distinct from accuracy, precision, jitter, stability, and drift.

Sub-tick statistical estimates may be meaningful over many observations, but individual raw captures remain quantized.

---

## Timing Domains

### Domain

A timing reference frame within which timestamps are directly meaningful.

A domain is defined by some combination of:

- clock source;
- tick rate;
- phase origin;
- counter width;
- overflow semantics;
- reconstruction rules;
- discipline state.

Rollover is part of the domain, not a property selected ad hoc by a consumer.
Current validators derive counter width, modulus, legal forward distance, and
ambiguity limits from the declared or contract-inherited domain. A lower raw
value is not automatically a wrap; it may instead be reordered, stale,
cross-session, corrupt, or too ambiguous to reconstruct.

Examples:

- local MCU counter domain;
- capture peripheral domain;
- reconstructed shared timeline;
- PPS-disciplined software timeline;
- host monotonic clock;
- UTC.

### Clock domain

A timing domain created by a particular clock source or oscillator.

Examples:

- free-running crystal oscillator domain;
- OCXO-derived MCU clock domain;
- GPSDO-derived 10 MHz domain;
- host OS monotonic-clock domain.

### Capture domain

The domain in which a captured timestamp was originally latched.

A capture domain may differ from the domain used later for analysis.

### Shared timeline

A native or reconstructed timeline into which multiple event streams can be projected for comparison.

Examples:

- multiple capture paths reconstructed into a common MCU counter timeline;
- raw event streams projected into a host-side nanosecond timeline.

A shared timeline is useful only when its reconstruction rules are explicit.

### Reconstruction

The process of deriving a more useful timestamp or timeline from lower-level timing observations.

Examples:

- extending a 16-bit counter to 32 bits;
- resolving overflow around a capture event;
- translating capture-local values into a shared timeline;
- reconstructing an event stream from raw CSV records.

Reconstruction is derived, even if it is deterministic.

### Projection

Mapping timing information into another representation or coordinate system.

Examples:

- ticks to seconds;
- local ticks to nanoseconds;
- event time to oscillator phase;
- timestamp sequence to pendulum phase.

Projection may be reversible or lossy. Lossy projections should not replace raw inputs.

### Clock domain crossing

Any comparison, transformation, or transfer of timing information across domains.

Clock domain crossings must be treated as explicit provenance boundaries.

---

## Raw, Derived, Canonical, and Adjusted

### Raw

Data that represents a direct observation with minimal transformation.

Examples:

- captured counter value;
- edge polarity;
- capture sequence number;
- raw event record;
- unadjusted cycles between events.

Raw does not mean accurate, calibrated, noise-free, or globally meaningful. It means minimally interpreted.

### Derived

Data computed from one or more upstream observations.

Examples:

- reconstructed timestamp;
- period estimate;
- PPS-adjusted interval;
- oscillator frequency estimate;
- inferred pendulum phase;
- Allan deviation.

Derived values should preserve clear provenance back to raw inputs.

### Canonical

A representation intended to maximize reconstructability, auditability, and future reinterpretation.

Canonical data should preserve:

- raw observations where practical;
- explicit domains;
- transformation metadata;
- sequence and ordering information;
- enough context for offline replay.

Canonical does not necessarily mean convenient. It means durable and replayable.

### Derived mode

A representation optimized for immediate analysis or convenience.

Derived mode may include already-computed values that are useful downstream, but it must not obscure whether those values are estimates, reconstructions, or adjustments.

### Adjusted

A value modified using a correction model, reference estimate, calibration, or discipline state.

Examples:

- PPS-adjusted interval;
- temperature-adjusted oscillator estimate;
- calibrated frequency error;
- host-reconstructed adjusted timestamp.

Adjusted values are estimates. They are not raw captures.

Avoid names such as `corrected` unless the correction model and reference are unambiguous.

---

## Synchronization and Discipline

### Synchronization

Alignment of time or phase between systems or domains.

Synchronization answers: do these systems agree about time or phase under the stated model?

Synchronization may refer to phase, epoch, or time-of-day alignment. It does not automatically imply oscillator discipline or long-term stability.

### Syntonization

Alignment of frequency between systems or oscillators.

Two systems may be syntonized without being phase-synchronized. For example, they may run at the same rate but have an offset.

Use synchronization for time/phase alignment and syntonization for frequency alignment when the distinction matters.

### Discipline

An active control process that steers a local oscillator, counter, or software timeline toward an external reference.

Examples:

- GPS-disciplined oscillator;
- PPS-disciplined software clock;
- frequency estimator steering a local timebase.

Discipline is not the same as synchronization. A disciplined system can still have residual phase error, frequency error, jitter, and holdover limitations.

### Disciplined

Subject to an active discipline process.

A disciplined value should identify the reference and estimator used, or at least the discipline domain that produced it.

Examples:

- `pps_disciplined_ticks`;
- `gpsdo_disciplined_10mhz`;
- `disciplined_frequency_estimate_hz`.

### Reactive frequency steering

A discipline policy that adjusts the local oscillator in response to current,
qualified frequency-error observations rather than requiring a prediction of
future drift or one permanent actuator setting.

For OTIS, the selected baseline uses D14-qualified D8 observations and one
versioned command policy. Reactive does not mean immediate or aggressive; the
observation window, persistence, correction fraction, cadence, and actuator
limits remain explicit and may be deliberately slow.

### Forwarded clock output

A hardware clock-output path that presents a selected input clock at another
pin through an explicitly identified source mux and divider. For the initial
OTIS D9 path, D8/GPIO20/GPIN0 is forwarded through GPOUT0 to D9/GPIO21 with
integer divisor one and fractional divisor zero. Forwarding does not make the
source the MCU system, reference, peripheral, PIO, or DMA clock and does not by
itself qualify the delivered electrical waveform.

### Diagnostic forwarded-output monitor

A zero-authority observation of a forwarded output, retained separately from
the authoritative measurement path. OTIS uses D6/GPIO18 for this role. A D6
count relationship may corroborate digital threshold crossings and continuity,
but D6 never becomes D14 PPS authority, D8 oscillator truth, control evidence,
or a waveform instrument. Monitor absence or failure is local unless it
demonstrably compromises the independent D14/D8 capture path.

### Correction debt

A derived control state representing fractional actuator demand that has been
justified by accepted observations but not yet realized as an integer DAC-code
application.

Correction debt must name its code domain, source evidence frontier, policy,
gain assumption, and update history. It is not raw frequency error, accumulated
phase error, a calibrated equilibrium code, or permission to actuate.

The unchanged CX322 request law does not commit a new tagged correction-debt
state. When its non-effective operational semantics discard a cached
phase-derived contribution and no committed PLL debt exists, record
`not_applicable_no_committed_pll_debt`; do not manufacture debt to make the
transition appear stateful.

### GNSS metadata hold

`GNSS_METADATA_HOLD` is a bounded inhibition of new control requests caused by
missing, stale, malformed, or otherwise unqualified serial metadata from the
receiver that supplies D14. It is not holdover and does not make GNSS serial
data a timing reference. Healthy D14/D8 measurement, estimation, phase
accumulation, response observation, and canonical telemetry continue while the
last confirmed DAC code is retained.

Measurement validity passed to phase and frequency consumers therefore refers
to D14/D8 evidence alone. Receiver metadata eligibility is a separate control
qualification. Metadata age at publication plus residence after publication
defines the receiver message's full causal age; each component does not grant
a separate freshness interval.

### Phase-degraded FLL

`PHASE_DEGRADED_FLL` means qualified D14/D8 frequency evidence remains usable
but phase-derived requests are inhibited. A later phase recovery opens a new
explicit phase epoch; numerical proximity alone cannot rejoin a retired epoch.

### Low-efficiency inhibit

`LOW_EFFICIENCY_INHIBIT` is a static automatic-actuation inhibit entered after
the prospectively frozen number of independent, identity-bound, completed
FLL-only low-efficiency episodes. Measurement continues. Recovery requires
explicit future operator authority and is never an automatic retry.

### Actuator-provenance fail-static

`ACTUATOR_PROVENANCE_FAIL_STATIC` is the absorbing state used when the applied
code, DAC epoch, request owner, outcome, or first dependent consumer cannot be
established by the exact deadline or has contradictory identity. Silence is
not inferred to mean rejection, application, or unchanged state.

### Shadow estimator

A named, versioned estimator that consumes a bounded copy of canonical evidence
and has zero control or terminal authority. Its output is additive derived
telemetry used for causal replay and comparison.

Missing, stale, delayed, contradictory, corrupt, or infeasible shadow output
fails the shadow estimator only. It must not invalidate upstream observations,
alter the selected baseline controller, backpressure timing capture, or fail a
physical run.

### Lock

A state in which a discipline or synchronization process has met its configured acceptance criteria.

Lock is a policy decision, not proof of truth.

Lock criteria may include:

- residual phase error threshold;
- frequency error threshold;
- PPS interval sanity;
- jitter or MAD threshold;
- minimum consecutive good samples;
- reference validity.

A locked system may still be wrong if the reference, wiring, assumptions, or thresholds are wrong.

### Holdover

Operation after loss or rejection of the external reference while attempting to maintain timing continuity.

During holdover, the system relies on:

- local oscillator stability;
- previous discipline estimates;
- aging and temperature assumptions;
- configured holdover policy.

Holdover should be represented as a distinct state, not silently treated as locked operation.

### Free-running

Operating without active external discipline.

A free-running oscillator may be very high quality. Free-running only means it is not currently being steered by an external reference.

---

## Accuracy, Precision, Stability, Drift, and Jitter

### Accuracy

Closeness to a reference truth.

Examples:

- frequency error relative to GPS;
- UTC time offset;
- oscillator ppm error.

Accuracy is not the same as precision or stability.

### Precision

Repeatability or granularity of measurement.

Examples:

- low timestamp dispersion;
- fine capture resolution;
- repeatable edge timing.

A system may be precise but inaccurate.

### Stability

Consistency of timing behavior over time.

Stability may be described using:

- Allan deviation;
- frequency variance;
- phase noise;
- drift over a specified interval.

A stable oscillator may still be offset from nominal frequency.

### Drift

Slow change in phase or frequency over time.

Examples:

- temperature-driven oscillator frequency shift;
- oscillator aging;
- voltage sensitivity;
- mechanical pendulum rate change.

Drift is generally lower-frequency behavior than jitter.

### Jitter

Short-term timing variation.

Examples:

- edge uncertainty;
- comparator noise;
- capture-path variation;
- reference pulse noise;
- ISR-service-time variation when measuring software latency.

Jitter should not be conflated with long-term drift.

---

## Phase and Frequency

### Frequency

Rate of oscillation or event recurrence.

Examples:

- 10 MHz oscillator;
- 1 PPS reference;
- pendulum period;
- event rate.

Frequency error is commonly expressed as ppm, ppb, or fractional frequency.

### Phase

Relative position within a repeating cycle, or relative offset between two timing processes.

Examples:

- PPS edge arriving early or late relative to local prediction;
- pendulum impulse phase;
- oscillator phase offset.

Phase is relational. Always state phase relative to what.

### Phase error

Difference between expected and observed phase.

May be expressed as:

- seconds;
- ticks;
- cycles;
- degrees;
- radians.

### Frequency error

Difference between actual and expected rate.

Frequency error accumulates into phase error over time.

---

## OTIS Naming Guidance

Prefer names that carry provenance and domain information.

Good examples:

- `raw_capture_ticks`;
- `capture_domain`;
- `reconstructed_ticks`;
- `raw_cycles`;
- `adjusted_cycles`;
- `pps_adjusted_ns`;
- `disciplined_frequency_hz`;
- `utc_estimate_ns`;
- `lock_state`;
- `holdover_age_s`.

Avoid ambiguous names:

- `time`;
- `timestamp` when the domain is not obvious;
- `corrected`;
- `synced`;
- `stable`;
- `accurate`;
- `phase` without a reference.

When a compact wire encoding is needed, document the conceptual term separately from the wire tag.

Example:

- conceptual record: `EVENT_CAPTURE`;
- compact CSV tag: `EVT`.

---

## Anti-Patterns

### Silent domain crossing

Do not compare values from different domains without documenting the reconstruction or synchronization step.

### Treating lock as truth

Lock means configured criteria were met. It does not prove that the system is correct.

### Replacing raw values with adjusted values

Adjusted estimates are useful, but they must not destroy raw provenance.

### Using corrected without saying corrected by what

Prefer adjusted, calibrated, projected, reconstructed, or disciplined when those terms are more precise.

### Hiding estimator identity

If a value came from a fast estimator, slow estimator, blended estimator, median filter, PLL, FLL, or host-side model, preserve that identity.

---

## Relationship to the OTIS Glossary

`OTIS_GLOSSARY.md` is the short reference glossary.

This document is the stricter terminology standard for timing semantics. If a term appears in both places, this document should be treated as the more precise source for timing-system meaning.

---

## Working Summary

In OTIS:

- events are observable occurrences;
- captures are observations;
- timestamps are domain-relative representations;
- counters define local timing domains;
- reconstruction and projection are derived operations;
- adjusted values are estimates;
- synchronization is relational alignment;
- discipline is an active control process;
- lock is a policy state;
- holdover is degraded operation without active reference;
- raw provenance is sacred.

Precision timing systems become fragile when terminology becomes fuzzy. This document exists to prevent that drift.

## FIFO service coordinate and PIO recognition bracket

A FIFO service coordinate is the RP2040 CPU timer observation after an immutable
PIO snapshot word is read. It is not a hardware-latched pin timestamp. The
recognition bracket is the conservative interval bounded by a prior FIFO-empty
observation and service, with the declared IN/autopush publication allowance.
Its width bounds timing uncertainty; it is not a measured service latency.
With the current D8-driven PIO program it bounds snapshot recognition, not the
electrical D14 transition when the oscillator is absent or slow. An unavailable
or ambiguous bracket remains explicit and cannot qualify a reference.

### Endurance completion and unanswered escalation

Endurance completion means the declared host monotonic observation window ended
with exact disarmed terminal evidence. Accepted D14/D8 apertures and control
availability are reported separately; elapsed host duration is not metrological
measurement duration. An unanswered escalation is retained evidence awaiting
review plus the frozen immediate operating response. It is never implicit
approval, a new control lease, or an automatic scientific failure.
