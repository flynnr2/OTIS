# OTIS Architecture Diagrams

This document is the working home for lightweight architecture diagrams that explain
OTIS over time.

These diagrams are intentionally not final schematics, PCB drawings, or implementation
commitments. They preserve architectural intent while the MVP evolves.

The diagrams should remain:

- reference-domain explicit;
- timing-path explicit;
- host-interpretation explicit;
- conservative about what the CPU is allowed to define;
- easy to revise as the hardware and firmware settle.

---

## Diagram Set Roadmap

| Diagram family              | Purpose                                                            | Status                                                        |
|-----------------------------|--------------------------------------------------------------------|---------------------------------------------------------------|
| Timing-domain diagrams      | Show where timing truth lives and how timestamps are referenced.   | First-pass ASCII.                                             |
| Queue/flow diagrams         | Show bounded movement from capture to host, including backpressure.| First-pass ASCII.                                             |
| Telemetry lifecycle diagrams| Show raw capture, annotation, archival, replay, and analysis.      | First-pass ASCII.                                             |
| Discipline-loop diagrams    | Show GNSS/PPS, oscillator steering, lock state, and provenance.    | First-pass ASCII.                                             |
| Hardware wiring diagrams    | Show concrete MVP signal wiring and physical interfaces.           | Started in `docs/40_HARDWARE/MVP_ASCII_WIRING_DIAGRAM.md`.    |
| Future rendered diagrams    | Mermaid/SVG/block diagrams for README-quality presentation.        | Later, after the architecture settles.                        |

---

## 1. Timing-Domain Diagram

OTIS should always make the timing domain visible. A timestamp is not merely a
number; it is a hardware-derived observation in a named reference domain.

```text
                  +------------------------------------------+
                  |             Reference Domain             |
                  |                                          |
 GNSS PPS ------->|  discipline observation / phase error     |
                  |                                          |
 OCXO / XO ------>|  counter clock / timestamp fabric         |
                  +--------------------+---------------------+
                                       |
                                       | reference-domain ticks
                                       v
                  +------------------------------------------+
                  |              Timing Fabric               |
                  |                                          |
 Event input ---->|  hardware edge capture                   |
 PPS input ------>|  hardware reference capture              |
                  |  deterministic counters / PIO / DMA      |
                  +--------------------+---------------------+
                                       |
                                       | raw timestamp records
                                       v
                  +------------------------------------------+
                  |          Timing-Aware Firmware           |
                  |                                          |
                  |  classify records                        |
                  |  attach provenance                       |
                  |  manage bounded queues                   |
                  |  run discipline state machine            |
                  +--------------------+---------------------+
                                       |
                                       | telemetry stream
                                       v
                  +------------------------------------------+
                  |                 OTIS Host                |
                  |                                          |
                  |  append-only logs                        |
                  |  replay                                  |
                  |  mode-profile interpretation             |
                  |  analysis / dashboards / reports         |
                  +------------------------------------------+
```

### Key Rule

The timing fabric creates timestamp truth. Firmware and host software may explain,
transform, replay, and analyze that truth, but they must not silently redefine it.

---

## 2. Queue and Flow Diagram

The queue architecture should make backpressure and loss semantics explicit. A
record may be delayed, flagged, summarized, or dropped according to policy, but it
should not become semantically ambiguous.

```text
             timing-critical path                          non-timing-critical path

      +------------------------------+                 +------------------------------+
      |        Timing Fabric         |                 |           OTIS Host          |
      |                              |                 |                              |
input |  hardware capture latch      |                 |  serial / USB reader         |
----->|  capture ring / DMA          |                 |  append-only raw log         |
 PPS  |                              |                 |  parsed CSV / records        |
----->|                              |                 |  latest-state cache          |
      +---------------+--------------+                 |  dashboard / analysis        |
                      |                                +---------------^--------------+
                      | capture records                                |
                      v                                                | telemetry
      +------------------------------+                 +---------------+--------------+
      |      Core 0 Timing Service   |                 |   Core 1 Instrument Service  |
      |                              |                 |                              |
      |  drain capture rings         |                 |  format / package records    |
      |  maintain ordering           |                 |  optional display updates    |
      |  attach timing provenance    |                 |  optional sensor polling     |
      |  run discipline loop         |                 |  command queue handling      |
      |  enqueue telemetry           +---------------->|  host-link service           |
      +---------------+--------------+                 +------------------------------+
                      |
                      | bounded internal state
                      v
      +------------------------------+
      |    Explicit Fault / Status   |
      |                              |
      |  overflow flags              |
      |  queue high-water marks      |
      |  dropped-record counters     |
      |  host-link status            |
      +------------------------------+
```

### Design Intent

Core 0 should be able to continue preserving timing semantics even when displays,
filesystems, dashboards, network services, or hosts fall behind.

---

## 3. Telemetry Lifecycle Diagram

OTIS telemetry should support later reinterpretation. Application meaning belongs
mainly host-side, so the same timestamped event stream can describe a pendulum,
an oscillator comparison, a time-interval measurement, or another timing experiment.

```text
+-------------------------+
| Physical Event          |
|                         |
| edge / pulse / PPS      |
+------------+------------+
             |
             v
+-------------------------+
| Raw Capture             |
|                         |
| channel_id              |
| edge                    |
| timestamp_ticks         |
| clock_domain            |
| capture_flags           |
+------------+------------+
             |
             v
+-------------------------+
| Firmware Provenance     |
|                         |
| schema_version          |
| boot/run identity       |
| reference_state         |
| queue/fault_state       |
| config_snapshot         |
+------------+------------+
             |
             v
+-------------------------+
| Host Archival           |
|                         |
| raw serial log          |
| parsed canonical CSV    |
| manifest                |
| host events             |
+------------+------------+
             |
             v
+-------------------------+
| Mode Interpretation     |
|                         |
| generic TIC             |
| pendulum profile        |
| oscillator check        |
| radio timing profile    |
+------------+------------+
             |
             v
+-------------------------+
| Analysis Products       |
|                         |
| rate / drift            |
| jitter / residuals      |
| Allan deviation         |
| phase decomposition     |
| environmental links     |
+-------------------------+
```

### Design Intent

The canonical record should describe what was captured. The mode profile should
explain what that capture means for a particular experiment.

---

## 4. Discipline-Loop Diagram

The discipline loop explains how the reference oscillator is characterized and
steered. It should not erase the raw PPS/reference observations that justified the
loop decision.

```text
                         +------------------------------+
                         |        GNSS Timing RX        |
                         |                              |
                         |  PPS / time solution / fix   |
                         +---------------+--------------+
                                         |
                                         | PPS
                                         v
+-------------------------+      +------------------------------+
| Controlled Oscillator   |      |    PPS Capture / Phase       |
|                         |      |    Error Measurement         |
| OCXO / VCXO / XO        +----->|                              |
| reference output        |      |  timestamp PPS vs counter    |
| EFC / tune input        |<--+  |  preserve raw observations   |
+------------+------------+   |  +---------------+--------------+
             |                |                  |
             | clock          |                  v
             v                |  +------------------------------+
+-------------------------+   |  |     Discipline Estimator     |
| Timing Fabric           |   |  |                              |
|                         |   |  |  phase error                 |
| event timestamps        |   |  |  frequency estimate          |
| reference captures      |   |  |  lock / holdover confidence  |
+------------+------------+   |  +---------------+--------------+
             |                |                  |
             | telemetry      |                  v
             v                |  +------------------------------+
+-------------------------+   |  |       Steering Policy        |
| Telemetry Stream        |   |  |                              |
|                         |   |  |  DAC code decision           |
| raw captures            |   |  |  slew / clamp / holdover     |
| estimator state         |   |  |  update reason               |
| DAC updates             |   |  +---------------+--------------+
| lock state              |   |                  |
+-------------------------+   |                  | SPI / control voltage
                              +------------------+
```

### Design Intent

A DAC update or lock-state transition is explanatory control telemetry. It does
not replace the raw reference captures, phase observations, or estimator history.

---

## 5. Host-Side Interpretation Boundary

This is the most important application-agnostic boundary for OTIS.

```text
              OTIS appliance                            host / analysis layer

      +------------------------------+              +------------------------------+
      | Hardware-captured facts      |              | Application interpretation   |
      |                              |              |                              |
      | channel 0 rising edge        |              | pendulum tick                |
      | channel 0 falling edge       |              | pendulum tock                |
      | channel 1 PPS edge           +------------->| oscillator comparison        |
      | timestamp ticks              |              | TIC interval                 |
      | reference domain             |              | radio timing event           |
      | flags / provenance           |              | unknown pulse train          |
      +------------------------------+              +------------------------------+
```

### Design Intent

The RP2040/RP2350 firmware should not need to know whether an event stream is a
pendulum with two or four meaningful events per swing cycle, an oscillator-quality
check, a radio timing experiment, or an unknown pulse train. It should emit clean,
replayable, reference-domain-explicit facts.

---

## Maintenance Notes

When these diagrams evolve:

- keep ASCII versions close to the architecture docs for easy review in diffs;
- add rendered diagrams later only when the underlying architecture has settled;
- avoid diagram drift by linking each rendered diagram back to its source text;
- update diagrams when schema semantics, queue boundaries, or timing domains change;
- do not let presentation diagrams hide loss, uncertainty, clock-domain transforms,
  or host-side interpretation boundaries.
