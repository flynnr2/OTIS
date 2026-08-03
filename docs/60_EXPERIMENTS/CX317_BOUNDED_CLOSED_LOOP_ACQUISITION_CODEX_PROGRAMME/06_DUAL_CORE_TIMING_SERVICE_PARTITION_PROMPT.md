# Stage 6 Prompt: Dual-Core Timing/Service Partition

Execute Stage 6 after both single-core active campaigns pass. This stage changes
architecture but performs no feedback-derived DAC write until parity and
isolation gates pass.

## Goal

Move from a successful experimental controller to an architecture in which
service-plane stalls cannot corrupt timing capture, estimation or control
state.

## Frozen core convention

For the Arduino-Pico Nano RP2040 Connect implementation:

- Core 0 is the service, I/O and physical-actuator execution plane;
- Core 1 is the protected timing and discipline plane.

Update conflicting repository documents and diagrams. Do not preserve a
contradictory core number for historical wording; preserve the architectural
intent and document the migration decision.

## Core 1 ownership

Core 1 owns:

- PIO/DMA completion and ring draining;
- monotonic observation and decision sequences;
- canonical raw reference/snapshot/count construction and validation;
- reference continuity and age used by control;
- selected estimator and diagnostic estimator state;
- control state, budgets and response-state evaluation;
- actuator-request generation;
- timing-critical fault detection.

Core 1 must require no timely Core 0 service to keep capturing and estimating.
If a non-droppable actuator transaction cannot complete, it must stop new
requests and enter a defined fail-static fault.

## Core 0 ownership

Core 0 owns:

- USB serial transport and command framing;
- bounded GNSS message parsing and receiver metadata production;
- environment-sensor service;
- telemetry formatting/export;
- run-control and host interaction;
- physical I2C DAC execution;
- accepted/applied acknowledgement generation.

The GNSS service publishes immutable qualified metadata to Core 1. It does not
publish PPS timestamps.

## Cross-core contracts

Use bounded fixed-size queues and immutable messages.

Non-droppable:

- validated mode/arm/recovery/abort changes;
- receiver qualification state transitions used by control;
- actuator request, rejection, acceptance and applied acknowledgement;
- critical fault and state-transition records.

Droppable with explicit counters:

- duplicate status snapshots;
- display/diagnostic summaries;
- redundant formatted telemetry.

Raw observations must remain reconstructable even if formatted export is
dropped. No queue may share mutable estimator or controller state.

For every actuator request, define sequence, decision reference, requested
code, deadline and one-time authorization. Core 0 rejects stale or duplicate
requests. Core 1 accepts only the exactly matching acknowledgement and uses the
confirmed applied code.

## Incremental implementation

1. Add cross-core types, queues and deterministic host/native tests.
2. Run both cores with control preview-only and compare against single-core
   fixtures.
3. Move timing ownership without modifying the PIO program or raw semantics.
4. Exercise receiver metadata, environment, telemetry and manual DAC service
   on Core 0.
5. Prove transaction fault behavior with a simulated actuator before active
   hardware re-arming.

## Isolation tests

Deliberately stall or overload Core 0 while verifying Core 1:

- receives every expected hardware snapshot within its ring budget;
- maintains monotonic sequences and estimator state;
- makes no spurious actionable decision;
- accounts for dropped droppable telemetry;
- faults safely on non-droppable queue exhaustion or actuator timeout.

Exercise USB backpressure, command bursts, GNSS bursts/malformed sentences,
environment I2C delay, telemetry saturation and a simulated lost actuator
acknowledgement. Do not deliberately stall Core 1 and call that a service-plane
test.

## Live observe-only proof

Flash a dedicated dual-core preview profile and run only long enough to cover:

- warmup and multiple selected estimates;
- quiet and bounded service-load intervals;
- metadata qualification and a controlled synthetic/fixture invalidation;
- queue high-water and drop accounting;
- exact host/firmware decision parity.

Do not repeat the previous six-hour observation merely for duration. Duration
must be justified by the mechanisms being exercised.

## Deliverables and exit gate

Deliver an architecture decision, corrected docs, queue contracts, parity and
fault fixtures, a sealed dual-core preview proof, full test/build validation,
and a Stage 6 report.

Pass if timing/control state is isolated from service load, all non-droppable
messages are accounted, and no feedback-derived DAC write occurred.
