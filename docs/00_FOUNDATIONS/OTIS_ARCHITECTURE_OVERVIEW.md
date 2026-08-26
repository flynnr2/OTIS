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
