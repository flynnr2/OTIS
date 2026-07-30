# Measurement, Metrology, Diagnostics, and Control

## Purpose

This document defines four distinct responsibilities that must remain explicit
throughout OTIS. They form a processing chain, but they are not synonyms:

```text
physical signals
      |
      v
measurement  ->  metrology  ->  diagnostics  ->  control
      |              |               |              |
 raw facts       estimates       interpretation    action
```

Telemetry transports records from every layer. Telemetry is not itself one of
the layers.

## 1. Measurement

Measurement records what the timing fabric directly observed.

Examples:

- a PPS edge captured at a hardware timestamp;
- a bounded count of oscillator edges between two gate boundaries;
- an external event edge and capture flags;
- a DAC write acknowledgement;
- a sampled temperature or supply voltage.

Measurement records must preserve the relevant clock domain, channel, sequence,
flags, and provenance. They must not silently replace an observation with a
filtered value or a control conclusion.

## 2. Metrology

Metrology transforms measurements into quantitative estimates with stated units,
assumptions, provenance, and uncertainty.

Examples:

- PPS-to-PPS interval error;
- oscillator frequency or fractional-frequency error;
- phase offset and phase residual;
- drift or ageing estimate;
- Allan deviation and related stability statistics;
- DAC-to-frequency sensitivity;
- temperature coefficient;
- holdover error projection.

Metrology may reject observations from a particular estimate, but rejection must
be explicit and replayable. The underlying measurement remains preserved.

## 3. Diagnostics

Diagnostics interprets measurements, metrology products, device state, and
context to assess whether the instrument and its evidence are trustworthy.

Examples:

- reference source noisy, missing, stale, or inconsistent;
- oscillator warming, drifting, or outside the characterized plant envelope;
- count path overflowing, dropping edges, or producing impossible windows;
- DAC saturated, slewing, unacknowledged, or outside the automatic-control span;
- estimator under-qualified, divergent, stale, or dominated by rejected data;
- service-plane overload threatening telemetry completeness but not timing truth.

A diagnostic statement is not a timing fact. It is a versioned conclusion with:

- severity;
- confidence;
- reason code;
- supporting evidence range;
- age and persistence;
- affected subsystem;
- control consequence, if any.

## 4. Control

Control decides whether and how to steer the plant. It consumes metrology and
diagnostic outputs under an explicit policy.

A control decision must identify:

- the observations and estimates on which it depends;
- eligibility and inhibition reasons;
- frequency and phase contributions;
- requested and applied actuator changes;
- clamps, slew limits, and saturation;
- plant-model and policy versions;
- preview versus authorized actuation;
- write acknowledgement or failure.

Control must not infer source health implicitly inside a DAC driver. Source
quality and control eligibility are explicit diagnostic inputs.

## 5. The three timebases

OTIS currently observes three conceptually different timebases:

| Domain | Example | Role |
|---|---|---|
| implementation clock | RP2040 system oscillator | Runs CPU, PIO, DMA, and timers; provides a capture coordinate system but is not automatically metrological truth. |
| plant oscillator | CX317-controlled VCOCXO | Stable local frequency source being characterized and steered. |
| external reference | GNSS PPS | Sparse reference events with excellent long-term frequency authority but non-zero short-term timing noise and possible faults. |

The PPS-gated count observable primarily measures frequency error: the slope in
an error-versus-time model. A phase observable measures offset relative to a
defined edge relationship. SW2 may combine both, but must record the frequency
and phase contributions separately.

## 6. FLL and PLL interpretation

In the simple model

```text
phase_error(t) = frequency_error * t + phase_offset + noise(t)
```

an FLL primarily estimates and reduces `frequency_error`; a PLL additionally
constrains `phase_offset` and prevents accumulated phase wander.

OTIS should not chase individual PPS excursions. The controller should preserve
the VCOCXO's short-term stability while using the PPS's long-term authority.
Loop bandwidth and estimator weighting therefore depend on diagnosed reference
quality, oscillator state, uncertainty, and observation age.

## 7. Explainability requirement

Every requested or applied control action shall be explainable from preserved
records.

A replay tool must be able to answer:

- What changed?
- Why did it change?
- Which observations were accepted or rejected?
- What was believed about frequency, phase, drift, and uncertainty?
- Which diagnostic gates permitted or inhibited control?
- Which policy and plant model were active?

If a DAC movement cannot be reconstructed from recorded evidence and policy, the
instrument is insufficiently observable.

## 8. Placement across firmware and host

The deterministic timing fabric owns capture. Firmware may perform bounded,
low-latency validity checks and emit live state, estimates, diagnostics, and
preview/control records. The host owns archival, deeper characterization,
replay, comparative analysis, plots, and retrospective reinterpretation.

Neither placement changes the semantic boundaries above. Host and firmware
implementations should converge on common contracts and replay fixtures rather
than creating competing meanings.

## 9. Phase 4 host-derived records

The first normative host replay products are:

- `data_contracts/estimates_v2.csv.md` for current `EST` metrology snapshots
  (`estimates_v1` remains a historical compatibility contract);
- `data_contracts/control_previews_v1.csv.md` for observe-only `CTL` decisions.

`EST` keeps raw-observation validity, diagnostic health, estimator confidence,
and preview eligibility distinct. `CTL` references its exact `EST`, model,
policy, and configuration inputs and records model applicability and every
limit result. Phase 4 `CTL` is structurally non-actuating:
`preview_only=true`, `actuation_authorized=false`, and `actionable=false`.
