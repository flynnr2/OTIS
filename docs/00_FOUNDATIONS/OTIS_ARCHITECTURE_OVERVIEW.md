# OTIS Architecture Overview

OTIS is organized as a provenance-preserving pipeline. The layers may be placed
across timing fabric, MCU cores, and host software, but their semantic boundaries
remain stable.

```text
physical references, plant oscillator, and events
                       |
                       v
              deterministic capture
                       |
                       v
                  measurement
                       |
                       v
                   metrology
                       |
                       v
                 diagnostics
                       |
                       v
                    control
                       |
                       v
             actuator / disciplined output

Telemetry and provenance span every layer; host replay can reconstruct the path.
```

## Physical and reference layer

Contains the GNSS PPS or other external reference, the CX317-controlled VCOCXO or
other plant oscillator, DAC and analogue steering path, buffers/dividers, and
external event inputs.

The optional D8/GPIN0 to D9/GPOUT0 path is a delivered forwarded output, not a
new reference or measurement authority. The optional D6 loopback is a
zero-authority diagnostic observation of that output. Both remain distinct
from canonical D14/D8 capture and control truth.

The RP2040 system oscillator is an implementation clock. It runs the instrument
and provides capture coordinates, but it is not automatically metrological truth.

## Timing fabric

Responsible for deterministic counting, PPS/reference capture, external event
capture, gate boundaries, timestamp latching, and pulse generation. The timing
fabric establishes raw timing evidence independently of interrupt, logging,
network, or UI latency.

## Measurement layer

Emits canonical observations and low-level status without hiding facts behind
filtered conclusions. Examples include `REF`, `CNT`, `EVT`, DAC acknowledgements,
environment, and drop/error counters.

## Metrology layer

Derives frequency, phase, drift, stability, plant sensitivity, correlations, and
uncertainty from measurements using explicit assumptions and provenance.

## Diagnostics layer

Assesses reference quality, count-path validity, oscillator and actuator health,
estimator qualification, model applicability, service-plane integrity, and
control eligibility. Diagnostic conclusions are evidence-backed and replayable.

## Control layer

Implements acquisition, FLL/frequency steering, PLL/phase steering, lock,
holdover, requalification, and safe actuation. It consumes metrology and explicit
diagnostic gates; it does not redefine raw observations.

## Host and application layer

Provides archival, replay, reports, plots, comparative analysis, dashboards,
APIs, and future applications. Host activity must not compromise timing capture
or bypass control safety.

The intended standalone operating model puts instrument state, acquisition,
qualification and oscillator control in firmware. Host attachment first
discovers the running instrument; it does not establish its initial state or
authorize a reset or controller takeover. Operating policy and serial evidence
detail are separate choices. The current firmware still uses a host-acknowledged
campaign protocol; autonomous startup steering and compact output remain
future work with explicit authority and evidence contracts.

## Guiding principles

- Keep implementation, plant, and reference domains explicit.
- Preserve raw observations before interpretation.
- Separate measurement, metrology, diagnostics, control, and telemetry.
- Make uncertainty and reason codes visible.
- Make every control action explainable and replayable.
- Treat optional or future estimator failure as local to that estimator. A
  model that cannot explain an observation does not invalidate the observation,
  canonical evidence, baseline control path, or physical reality.
- Hold the last confirmed actuator state and enter documented reference hold or
  holdover when reference evidence is temporarily unavailable; reserve latched
  fail-static state for integrity, ordering, capture-loss, or actuator failures
  that cannot be requalified in place.

## Accepted-reference integration

The current candidate selects immutable PIO-owned D14/D8 snapshots through
one reference acceptance gate. Raw SNP/CNT/REF remain canonical; REF is a
presentation of the same snapshot rather than an independent GPIO owner.
APS separately identifies accepted D8 spans, their acceptance epoch and full
raw source range. One immutable selection feeds frequency and relative-phase
measurement, then transaction identity, recorder readiness, replay and duration
accounting. Raw interval diagnostics have no separate control-admission role.

FIFO service coordinates are CPU observations, not hardware-latched D14 edge
timestamps. Their explicit uncertainty brackets PIO snapshot recognition using
a prior FIFO-empty observation. The whole possible interval must satisfy the
reference tolerance. Receiver metadata remains a separate control gate.
See [the single-owner contract](../50_SOFTWARE/SINGLE_REFERENCE_OWNER_REPAIR.md)
for bounds, fault retention and the distinction between PIO recognition and an
electrical D14 edge. Session/acceptance-epoch changes require fresh support;
an uninterrupted campaign cannot sum different epochs.

## Unattended finite host supervision

The detached local launcher runs the existing host command owner and capture
worker. A separate read-only observer retains transition notifications and a
heartbeat. It requires neither Codex nor network access, cannot grant authority,
and cannot restart or terminate the owner. Unknown discrepancies retain review
holds; known receiver metadata recovery remains causal and automatic. Firmware
continues to own hardware capture, controller decisions and independent safety
expiry. This is host-acknowledged operation, not autonomous firmware startup.
