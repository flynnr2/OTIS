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

### Quantization

The finite resolution imposed by the tick rate of the timing source.

Examples:

- 16 MHz implies 62.5 ns ticks;
- 10 MHz implies 100 ns ticks;
- 20 MHz implies 50 ns ticks.

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
