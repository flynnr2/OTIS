# Diagnostics and Confidence Architecture

## Status

This document defines the intended diagnostics architecture for SW2 and later
OTIS stages. Initial implementations may be smaller, but they should preserve
these semantics.

## North star

OTIS does not merely report that it is locked. It reports why it believes its
output is trustworthy, what evidence supports that belief, what could invalidate
it, and how uncertainty changes with time.

Diagnostics are a first-class subsystem alongside measurement and metrology.
They are not console logging, a dashboard concern, or an after-the-fact report.

## Diagnostic object

A diagnostic finding should contain, directly or by reference:

| Field | Meaning |
|---|---|
| `diagnostic_id` | Stable machine-readable identifier. |
| `subsystem` | Reference, count path, oscillator, actuator, estimator, control, environment, service plane, or storage. |
| `severity` | Informational, degraded, warning, fault, or critical. |
| `state` | Active, cleared, latched, suppressed, or unknown. |
| `confidence` | Confidence in the diagnosis, distinct from confidence in timing accuracy. |
| `reason_code` | Stable explanation suitable for replay and automation. |
| `first_seen` / `last_seen` | Persistence and age. |
| `evidence` | Observation sequences, estimate ranges, counters, and configuration references. |
| `control_effect` | None, reduce trust, inhibit acquisition, inhibit actuation, enter holdover, or fail static. |
| `algorithm_version` | Version/hash of the diagnostic rule or model. |

Human-readable prose may be generated from this structure; prose must not be the
only representation.

## Confidence is plural

OTIS must avoid a single ambiguous `confidence` number. At minimum, distinguish:

- **observation validity** — was a record structurally and physically plausible?
- **source quality** — how trustworthy is the reference or oscillator source now?
- **estimate uncertainty** — what is the interval around a numerical estimate?
- **model applicability** — is the plant/environment within the characterized envelope?
- **control eligibility** — may this evidence participate in an actuation decision?
- **diagnostic confidence** — how strongly does the evidence support a diagnosis?

A Boolean eligibility result should always be accompanied by stable reason codes.

## Health hierarchy

Diagnostics should be grouped into a hierarchy:

```text
instrument health
  +-- timing fabric
  +-- reference source and capture path
  +-- oscillator and count path
  +-- estimator/metrology
  +-- actuator and plant model
  +-- control policy and state machine
  +-- environmental/context sensing
  +-- service plane, transport, storage, and host
```

Overall health must not hide subsystem detail. A service-plane fault may degrade
telemetry completeness while leaving the timing fabric healthy; a reference
fault may leave the oscillator healthy but force holdover.

## Required diagnostic behaviours

### Preserve first evidence

Startup anomalies, invalid windows, dropped records, and actuator failures must
remain visible. Diagnostics annotate or gate evidence; they do not delete it.

### Distinguish source from path

A malformed PPS cadence does not by itself prove a GNSS receiver fault. The
cause may be the receiver, electrical input, GPIO, PIO, FIFO, DMA, firmware, or
transport. Until isolated, report the observed symptom and the unresolved fault
domain honestly.

For PPS-gated measurement, track physical D14 arrival, PIO snapshot production,
foreground drain, reconstruction, telemetry emission, control consumption,
backlog, and backpressure as separate progress planes. Only a new physical D14
event can restore physical PPS presence. A queue backlog or late report is not
a missing PPS; a snapshot gap or storage overflow is a distinct continuity
fault. One continuous physical outage raises one outage transition, with any
periodic reminders counted separately, followed by one restoration transition.

### Track persistence and recovery

Diagnostics should support debounce, qualification, hysteresis, latching, and
explicit clearing. A one-sample excursion, a persistent degradation, and a
recovered fault are different events.

For the established OTIS GNSS/PPS hardware path, an isolated malformed D14
cadence is a recoverable reference-quality event. Preserve every raw edge,
invalidate affected measurement windows, inhibit actuation, retain lifetime
anomaly counters, and require explicit clean-window requalification. Do not
turn a prior anomaly counter into permanent current ineligibility. A new GNSS
receiver, PPS conditioning circuit, wiring topology, or capture implementation
requires fresh qualification before inheriting this recovery policy.

### Influence control through policy

Diagnostics provide explicit quality and eligibility inputs. Policy may respond
by increasing averaging, reducing loop bandwidth, holding the last safe DAC
code, entering holdover, or requiring requalification. Diagnostic code must not
write the DAC directly.

### Remain replayable

Given the same canonical measurements, configuration, diagnostic version, and
plant model, host replay should reproduce the same findings or record why a newer
algorithm differs.

## Initial SW2 diagnostic families

The first implementation should prioritize:

1. reference cadence, age, continuity, and capture-path counters;
2. count-window validity, zero/saturation/overflow, and gate completeness;
3. warmup and control-eligibility qualification;
4. estimator sample count, dispersion, residuals, age, and rejection reasons;
5. plant-model presence, version, local applicability, and limit class;
6. requested/applied DAC consistency, clamp, slew, saturation, and I2C result;
7. queue drops, backpressure, sequence discontinuities, reset/reconnect events;
8. environmental sensor freshness and thermal-transient indicators.

## Diagnostic outputs and records

Diagnostics may be emitted as dedicated event/state records rather than an
indefinitely widening status line. The exact wire schema is a separate data
contract, but it should support:

- transitions as explicit events;
- periodic snapshots for current state;
- evidence references;
- stable reason codes;
- policy/control consequence;
- algorithm version and configuration hash.

Raw `REF`, `CNT`, `EVT`, environment, and low-level health records remain
canonical inputs. `EST` records contain numerical estimator results. `CTL`
records contain control decisions. Diagnostic records explain quality,
eligibility, and faults without replacing any of them.

The current repository contract is
`data_contracts/diagnostics_v1.csv.md`. `DIAG` records carry stable reason
codes, persistence, evidence references, algorithm/configuration identity,
diagnostic confidence, and independent observation, reference, model, and
control effects. They are the normative diagnostic transition surface;
`health_v1` / `STS` remains low-level status evidence rather than a substitute
for diagnostic conclusions.

Phase 4 host replay implements the corresponding normative `EST` and
observe-only `CTL` contracts. Missing `STS` diagnostic context remains
`unknown` and inhibits preview rather than being treated as healthy. A valid
count alone therefore cannot collapse observation validity, diagnostic health,
estimator confidence, model applicability, and preview eligibility into one
control-ready claim.

## Acceptance tests

Diagnostics become first-class only when tests demonstrate that:

- known injected faults produce the expected reason codes and transitions;
- raw evidence remains unchanged;
- control is inhibited or degraded according to policy;
- clearing requires documented requalification;
- replay reproduces live decisions;
- service-plane overload cannot silently corrupt timing truth;
- every applied DAC update can be traced through estimate, diagnostic gate,
  policy decision, request, and acknowledgement.
