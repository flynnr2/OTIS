# OTIS Core Partitioning

This document describes the conceptual partitioning of responsibilities within
OTIS timing systems.

The goal is to preserve deterministic timing semantics while still permitting:

- telemetry emission;
- instrumentation services;
- environmental sensing;
- dashboards;
- optional local displays;
- durable logging.

---

# Fundamental Principle

The timing fabric establishes timing truth.

The CPU observes and manages timing information.

The CPU does **not** create event time.

---

# Conceptual Layering

```text
PIO / DMA          deterministic timing fabric
Core 1             protected timing and discipline core
Core 0             service, I/O and instrumentation core
OTIS Host          archival, replay, dashboards, analysis
```

## Arduino-Pico implementation decision

The Nano RP2040 Connect firmware uses the Arduino-Pico core convention
explicitly: Arduino `setup()` / `loop()` execute the Core 0 service plane and
`setup1()` / `loop1()` execute the Core 1 timing plane.  This convention is an
architectural invariant, not a scheduler hint.

Core 1 owns PIO/DMA setup and draining, raw reference/snapshot/count sequence
construction, reference continuity, estimators, preview/control state and
actuator-request generation.  Core 0 owns USB transport and command framing,
GNSS parsing, environment I2C, telemetry export, run control and physical DAC
I2C execution.  GNSS qualification crosses to Core 1 as immutable metadata;
PPS timestamps never cross from the GNSS service.

Core 0 is the sole executor for the mutable GNSS UART receive ring, parser,
link state machine, and transmit state. Core 1 never services that state,
including before the first USB carrier attaches. Core 0 continues the bounded
GNSS service path while the carrier is absent, so single ownership does not
make receiver progress depend on host attachment.

The concrete queues and interrupt rings are fixed-size and allocation-free.
The mechanically checked normative inventory is
`firmware/arduino/otis_nano_rp2040_connect/otis_resource_inventory.json`.
It covers all six cross-core queues plus the capture and PPS/count-boundary
rings, including producer, consumer, capacity, loss policy, permitted absence,
and recovery. Every cross-core queue is SPSC: Core 0 is the sole producer of
the service queue and Core 1 is the sole producer of the other five. Core 0
drains Core 1 boot telemetry directly to the wire exactly once; it never
republishes a consumed record.

Automatic actuator transactions use a request sequence, decision reference,
requested code, explicitly named wrapping monotonic-seconds deadline, one-time
authorization sequence and nonce. Both core guards compare that same domain
with wrap-safe signed differences. Acceptance and application are separate
acknowledgements.

The initial setup is a separate two-phase transaction. A host request binds an
exact post-attachment status generation and nonce, session, configuration
SHA-256, expiry, code, and one-shot ordinal. Core 1 authorizes current lease,
GNSS/reference, partition and active state; Core 0 first accepts without I2C;
Core 1 revalidates the same authority; Core 0 consumes it immediately before
the sole I2C call. The correlated phases are `host_written`,
`firmware_received`, `core1_authorized`/`core1_rejected`, `core0_accepted`,
`core1_execution_released`, `applied`/`failed`, and the later observed result.
A stale, duplicate, mismatched or late acknowledgement faults fail-static;
there is no automatic retry or restoration write.

Core 0 diagnostic commands enqueue requests to Core 1. Core 1 alone reads or
polls timing state and publishes one immutable generation-bound diagnostic
snapshot. Core 0 only transports those records.

---

# Timing Fabric

The timing fabric is responsible for:

- reciprocal counting;
- PPS capture;
- external event capture;
- deterministic timestamp latching;
- pulse generation;
- reference-domain observation.

The timing fabric should operate independently of:

- interrupt latency;
- filesystem activity;
- display updates;
- sensor polling;
- host responsiveness.

## Candidate Implementations

| Implementation          | Notes                                            |
|-------------------------|--------------------------------------------------|
| RP2040 PIO + DMA        | likely initial OTIS MVP direction                |
| FPGA timing fabric      | future advanced timing architecture              |
| CPLD glue logic         | useful deterministic support logic               |

---

# Core 1 — Protected Timing and Discipline Core

Core 1 should be treated as timing-critical infrastructure.

## Responsibilities

| Responsibility                  | Notes                                   |
|---------------------------------|-----------------------------------------|
| drain capture rings             | deterministic handling                  |
| discipline loop                 | DAC steering and lock control           |
| reference-domain bookkeeping    | timing semantics and provenance         |
| telemetry classification        | timing-aware record generation          |
| queue management                | bounded deterministic behavior          |

## Core 1 Should Avoid

| Avoid                             | Reason                                 |
|-----------------------------------|----------------------------------------|
| OLED rendering                    | unnecessary latency and contention     |
| filesystem writes                 | unpredictable stalls                   |
| network stacks                    | uncontrolled timing behavior           |
| sensor polling                    | low-priority activity                  |
| blocking serial writes            | backpressure risk                      |
| heap-heavy allocation             | determinism and fragmentation concerns |

Core 1 should remain:

- deterministic;
- bounded;
- observable;
- timing-focused.

Optional future estimators must not share authority or backpressure with the
canonical capture and reactive-control path. Before promotion they consume a
bounded copy of evidence and publish only additive shadow records. If their
consumer is absent or slow, bounded shadow work may be dropped with explicit
counters; capture, baseline estimator state, control eligibility, abort, and
actuator transactions must continue unchanged.

A future estimator may not become a second hidden owner of control state.
Promotion requires one explicit policy boundary and a frozen reactive fallback.
An estimator-local fault withdraws that estimator, not the timing fabric or
canonical physical evidence.

---

# Core 0 — Instrument Service and I/O Core

Core 0 hosts the Arduino/USB foreground and may host optional
instrument-service functionality.

## Potential Responsibilities

| Responsibility                  | Notes                                   |
|---------------------------------|-----------------------------------------|
| OLED updates                    | optional local status                   |
| environmental sensors           | low-rate telemetry                      |
| telemetry formatting            | non-critical processing                 |
| optional SD logging             | secondary storage path                  |
| command handling                | non-timing-critical interaction         |
| USB/UART packaging              | transport-layer work                    |

## Important Constraints

Core 0 may:

- fall behind;
- shed non-critical work;
- drop telemetry with explicit flags;
- reduce display update rates.

Core 0 must **never**:

- stall Core 1;
- compromise deterministic capture;
- redefine timing truth.

---

# OTIS Host Responsibilities

The preferred durable logging and analysis layer remains OTIS Host.

Potential host environments include:

- Raspberry Pi Zero 2 W;
- larger Raspberry Pi systems;
- Linux laptops/workstations.

## Host Responsibilities

| Responsibility                  | Notes                                   |
|---------------------------------|-----------------------------------------|
| append-only logging             | primary durable storage                 |
| replay tooling                  | reproducibility                         |
| dashboards                      | observability                           |
| Allan deviation analysis        | long-run characterization               |
| telemetry archival              | scientific record preservation          |
| APIs                            | future ecosystem support                |

The host is not timing authority.

The host consumes timing telemetry generated by the timing fabric.

---

# Optional Peripheral Philosophy

OTIS may support:

- OLED displays;
- environmental sensors;
- SD logging;
- status LEDs;
- local controls.

However:

these are instrument-service features, not timing-fabric features.

They must remain architecturally isolated from deterministic timing behavior.

---

# SD Logging Guidance

Direct SD logging from the timing appliance is acceptable as:

- optional functionality;
- backup capture;
- local convenience.

It should not initially be treated as the primary archival architecture.

Preferred architecture:

```text
OTIS Core  →  telemetry stream  →  OTIS Host logging and archival
```

Filesystem activity must never compromise:

- deterministic capture;
- timestamp provenance;
- discipline behavior.

---

# Architectural Summary

```text
GNSS PPS
    ↓
disciplined reference oscillator
    ↓
PIO / DMA timing fabric
    ↓
hardware-latched event timestamps
    ↓
Core 1 timing semantics and discipline
    ↓
Core 0 instrumentation and I/O services
    ↓
OTIS Host archival and analysis
```
