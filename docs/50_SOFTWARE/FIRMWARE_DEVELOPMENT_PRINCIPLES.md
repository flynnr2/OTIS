# Firmware Development Principles

This document turns OTIS timing philosophy into firmware-development rules.

It is intended for human contributors, ChatGPT, Codex, and other code-generation agents working under human review.

The controlling rule is:

> Firmware must preserve the distinction between capture correctness, reference authority, discipline quality, and final timing claims.

A prototype may use modest hardware. The firmware architecture should still be written as if a timing-grade reference, OCXO, laboratory standard, or future FPGA fabric may be substituted later without changing the meaning of raw observations.

---

## 1. Component Quality Must Not Change Semantics

Lower-quality parts reduce absolute metrological authority, not architectural validity.

Firmware must not encode assumptions that only hold for a particular GNSS receiver, oscillator, DAC, OCXO, TCXO, PPS source, or conditioning circuit.

A lower-quality reference may increase:

- uncertainty;
- jitter;
- drift;
- holdover error;
- lock instability;
- noise floor;
- time-to-confidence.

It must not change the meaning of:

- raw capture timestamps;
- capture domains;
- reference records;
- discipline states;
- provenance fields;
- replay semantics.

Changing from a basic GNSS PPS source to a timing-grade GNSS receiver, or from a TCXO to an OCXO, should be a manifest/provenance/configuration change. It should not require a schema rewrite or reinterpretation of historical raw events.

---

## 2. Capture Correctness Is Separate From Reference Authority

A timestamp may be correctly captured even when the active reference is poor, unlocked, noisy, misconfigured, or later rejected by analysis.

Firmware must therefore keep these questions separate:

| Question                  | Firmware representation                                      |
|---------------------------|--------------------------------------------------------------|
| Was the edge captured?    | capture record, edge, channel, raw timestamp, capture flags   |
| Where was it captured?    | explicit `capture_domain`                                    |
| What was the reference?   | reference identity, reference channel, reference provenance   |
| Was reference usable?     | reference validity / health / lock / holdover state           |
| Was anything adjusted?    | explicit discipline or estimator provenance                   |
| What does it mean?        | host-side interpretation profile and analysis                 |

Do not collapse these into a single `valid` flag.

---

## 3. Raw Before Adjusted

Every adjusted, reconstructed, disciplined, calibrated, projected, or UTC-like value must remain traceable back to raw captured ticks.

Firmware may emit derived estimates when useful, but it must not replace raw observations with derived ones.

Acceptable:

```text
raw_capture_ticks + capture_domain + discipline_state + estimator_id
```

Not acceptable:

```text
corrected_time
```

unless the correction model, source reference, estimator, and provenance are also explicit and raw data remains available.

---

## 4. Firmware Emits Observations, Not Final Claims

Firmware may emit:

- captured event records;
- reference capture records;
- local counter state;
- discipline state;
- estimator values;
- source health flags;
- manifest/configuration/provenance records.

Firmware should not make final metrological claims such as:

- this timestamp is accurate to a specific nanosecond bound;
- this oscillator is stable;
- this run is metrology-grade;
- this pendulum period is valid;
- this Allan deviation result is acceptable.

Those are host-side analysis conclusions. Firmware supplies the observations and provenance needed to make or reject those claims later.

---

## 5. Reference-Agnostic Firmware Assumptions

Firmware should assume the same architecture may later support:

- basic GNSS PPS;
- timing-grade GNSS PPS;
- local TCXO;
- high-quality OCXO;
- GPSDO-derived clock;
- external laboratory reference;
- simulated or replayed reference inputs;
- future FPGA or dedicated timing-fabric implementations.

Component quality may affect configuration, health telemetry, uncertainty metadata, and analysis confidence. It must not affect raw capture semantics.

---

## 6. State Machines Must Preserve Degraded States

Do not treat degraded operation as ordinary operation.

Represent states such as:

- acquiring;
- locked;
- holdover;
- free-running;
- reference suspect;
- reference absent;
- source-health suspect;
- estimator warming up.

Lock is a configured policy state. It is not proof that the reference is true or that downstream timing claims are valid.

---

## 7. Code-Generation Review Checklist

Codex and other generated-code changes should be reviewed against this checklist:

- Does the change preserve raw captured ticks?
- Are capture and reference domains explicit?
- Does it avoid assuming a specific GNSS receiver or oscillator quality?
- Does it separate capture status from reference validity?
- Does it preserve replayability from emitted artifacts?
- Does any adjusted value identify its estimator or discipline provenance?
- Does the firmware avoid host-side interpretation or final metrology claims?
- Are degraded states represented explicitly rather than hidden behind `valid`?
- Would historical raw data remain meaningful after upgrading the reference hardware?

If the answer to any of these is unclear, the change should be treated as a semantic-risk change, not just an implementation detail.
