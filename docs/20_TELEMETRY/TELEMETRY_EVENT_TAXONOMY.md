# Telemetry Event Taxonomy

## Purpose

This document defines the initial OTIS telemetry/event taxonomy.

The taxonomy exists to keep timing observations, discipline state, control actions,
context telemetry, host operations, and derived analysis products semantically
separate.

This separation is central to OTIS:

```text
Timing fabric = timestamp truth
Firmware      = observation emission + minimal state reporting
Host          = interpretation, replay, analysis, dashboards, archival
```

`raw_events_v1.csv` is therefore not the whole OTIS telemetry universe. It is the
canonical timing observation stream. Other telemetry records may coexist, but they
must not pollute the semantics of raw event capture.

---

## Core Principle

`EVENT_CAPTURE`, `REF_CAPTURE`, and `COUNT_OBSERVATION` are observations.

They describe what the timing fabric captured, not what the event means in an
experiment.

Firmware should not encode application semantics such as:

- pendulum tick/tock;
- oscillator phase result;
- radio timing classification;
- scope calibration meaning;
- experiment-specific pass/fail status.

Those meanings belong in host-side profiles, replay tools, and derived analysis
products.

---

## Record Classes

| Class              | Meaning                                      | Timing authority? |
|--------------------|----------------------------------------------|-------------------|
| observation         | Hardware-captured timing observation         | yes               |
| state              | Device or loop state                         | no                |
| diagnostic         | Evidence-backed health/quality conclusion    | no                |
| control_action     | Deliberate steering or output action         | no                |
| context            | Environmental or operating context           | no                |
| provenance         | Configuration, schema, calibration, identity | no                |
| host_ops           | Host-side logging or operational events      | no                |
| fault              | Explicit anomaly or error                    | no                |
| derived            | Replayable analysis output                   | no                |

Only observation records establish timestamped timing facts. Other records explain,
contextualize, or derive from those facts.

---

## Initial Record Types

| Record type        | Class          | Purpose                                                  |
|--------------------|----------------|----------------------------------------------------------|
| `EVENT_CAPTURE`    | observation    | External/user timing event captured by the timing fabric |
| `REF_CAPTURE`      | observation    | Reference event captured by the timing fabric            |
| `COUNT_OBSERVATION` | observation   | Gated/windowed count of a high-rate source               |
| `FORWARDED_MONITOR_SNAPSHOT` | diagnostic | Raw zero-authority D6 cumulative snapshot         |
| `DISCIPLINE_STATE` | state          | Discipline loop state and estimator status                 |
| `DIAGNOSTIC_EVENT` | diagnostic     | Health, quality, confidence, reason, and control effect    |
| `DAC_UPDATE`       | control_action | Oscillator steering command or applied control action    |
| `ACTIVE_TRANSACTION_TIMING` | control_action | Exact counter-domain timing sidecar for an active transaction record |
| `ACTIVE_HYBRID_DECISION_TIMING` | state | Exact counter-domain timing sidecar for a hybrid decision record |
| `ENVIRONMENT`      | context        | Temperature, pressure, humidity, voltage, board context  |
| `DEVICE_STATE`     | provenance     | Boot, firmware, hardware, clock-source, runtime state    |
| `CONFIG_SNAPSHOT`  | provenance     | Run configuration, selected profile, calibration, schema |
| `HOST_EVENT`       | host_ops       | Logging, rollover, backlog, network, command, UI event   |
| `ERROR_EVENT`      | fault          | Explicit fault, anomaly, overflow, invalid state         |
| `ANALYSIS_PRODUCT` | derived        | Replayable host-derived metrics and reports             |

This list is intentionally small but extensible. New record types should be added
only when they define a genuinely distinct semantic class.

---

## Observation Records

### `EVENT_CAPTURE`

An `EVENT_CAPTURE` record describes a captured event on an external/user channel.

It should answer:

```text
At reference-domain time T, channel C observed edge E with capture metadata M.
```

It should not answer:

```text
Was this a pendulum tick?
Was this a good oscillator cycle?
Was this the impulse side of a clock?
Was this a valid experiment result?
```

Those are profile and analysis questions.

The compact CSV representation in `raw_events_v1.csv` uses `EVT` as the wire tag
for `EVENT_CAPTURE`.

### `REF_CAPTURE`

A `REF_CAPTURE` record describes a captured reference event, such as GNSS PPS or
another declared reference input.

It should still be a raw observation. It may identify the reference source, capture
channel, edge, timestamp, and validity flags, but should not hide raw timing facts
behind discipline-loop conclusions.

Reference captures may later be used to derive phase error, frequency estimates,
lock quality, and steering decisions.

Host diagnostics may also derive PPS/reference interval anomaly classes from
adjacent `REF` observations:

| Class | Meaning |
|----------------------|-------------------------------------------------|
| `normal_interval`    | Interval is within the configured nominal band. |
| `short_interval`     | Interval is shorter than the nominal band.      |
| `long_interval`      | Interval is long but not integer-PPS-like.      |
| `likely_missed_1_pps` | Interval is close to two PPS periods.          |
| `likely_missed_n_pps` | Interval is close to N+1 PPS periods.          |
| `impossible_interval` | Interval is zero or negative after unwrapping. |
| `unknown`            | Required nominal timing metadata is unavailable. |

These classes are derived analysis products. They do not prove whether the
missing edge occurred in the receiver, GPIO input, capture hardware, IRQ/FIFO/
DMA path, or firmware unless the corresponding raw status counters are emitted.

### `COUNT_OBSERVATION`

A `COUNT_OBSERVATION` record describes a bounded count of a high-rate source,
such as a TCXO, OCXO, VCXO, divided oscillator, or PPS-gated oscillator window.

It should answer:

```text
Between gate boundary A and gate boundary B, source S produced N counted edges.
```

It should not answer:

```text
What is the calibrated oscillator frequency?
Is the oscillator locked?
Should the DAC move?
Is the run fixture-ready?
```

Those are host-derived, profile, reporting, or control-readiness questions.

The compact CSV representation in `count_observations_v1.csv` uses `CNT` as the
wire tag for `COUNT_OBSERVATION`.

### `FORWARDED_MONITOR_SNAPSHOT`

`FORWARDED_MONITOR_SNAPSHOT` is a raw observation of the optional D6 loopback
sidecar, encoded as `MNS` in `forwarded_monitor_snapshots_v1.csv`. It preserves
the monitor session, D14/D8 reference session and boundary identity, cumulative
down-counter value, local status, backend, and channel 3. It may corroborate a
declared D8:D6 edge-count relationship but has zero timing or control authority.

An `MNS` record is never a D14 reference, never substitutes for D8, and cannot
qualify a D9 waveform. Missing, stale, corrupt, discontinuous, or overflowing
monitor evidence remains D6-local unless the implementation demonstrably
compromises the separate D14/D8 path.

### Exact active-control timing sidecars

The long-run D9/D6 engineering profiles encode `ACTIVE_TRANSACTION_TIMING` as
`AT2` in `active_transactions_v2.csv` and
`ACTIVE_HYBRID_DECISION_TIMING` as `AH2` in
`active_hybrid_decisions_v2.csv`. These are not new timing observations and do
not replace D14 `REF` or D8 `CNT`. They bind each legacy `ACT1` transaction or
`AHY1` decision one-to-one to a monotonic `rp2040_timer0_extended` event or
decision timestamp and repeat the complete run, build, profile, session and
source-frontier identity needed for causal replay.

The original records remain canonical for transaction and controller content;
the sidecars are canonical for their exact lifecycle timing in the activated
24-hour and 72-hour programmes. A verifier must reject a missing, duplicate,
reordered or identity-inconsistent join and must not substitute the legacy
whole-second display fields for cadence, response-reserve, right-censor,
endpoint or terminal decisions.

---

## Diagnostic Records

### `DIAGNOSTIC_EVENT`

A `DIAGNOSTIC_EVENT` describes an evidence-backed conclusion about source
quality, subsystem health, estimator qualification, model applicability, or
control eligibility.

It should identify a stable diagnostic/reason code, subsystem, severity, state,
confidence in the diagnosis, first/last seen times, supporting observation or
estimate ranges, algorithm version, and control consequence.

Diagnostic records do not establish timing truth and do not replace `REF`, `CNT`,
`EVT`, `EST`, or `CTL` records. They explain whether and why those records may be
trusted or used for control. Important transitions should be explicit events;
periodic snapshots may coexist for current-state reporting.

Avoid a single ambiguous confidence field. Observation validity, source quality,
estimate uncertainty, model applicability, control eligibility, and confidence
in a diagnosis are distinct concepts.

The additive draft CSV contract is documented in
`data_contracts/diagnostics_v1.csv.md`. Existing `health_v1` / `STS` rows
remain valid low-level status and migration inputs; draft `DIAG` rows are the
first-class diagnostic findings used by replay tests.

### PPS REF/SNP association taxonomy

Keep the following conclusions distinct when aligning pseudo-PPS evidence:

| Condition | Required evidence/result |
|---|---|
| REF-only narrow glitch | PGT `narrow_glitch`, physical REF observed, explicit SNP absence, `association_state=lost`, `ref_without_snapshot`, no CNT |
| Extra REF edge | Additional physical REF/sequence evidence; classify cadence separately from whether PIO produced SNP |
| Missing SNP | Explicit absence assessment; never infer absence merely because an aligned file omitted a row |
| Association loss | Close old pairing/session state, increment the saturating loss counter, reject late or ambiguous SNP words |
| Measurement invalidation | No valid CNT may span the affected event; `count_snapshot_absent`/gate-incomplete status remains explicit |
| Restored clean acquisition | First new-session SNP is `anchor`; the adjacent clean successor changes association to `clean` and is the first CNT candidate |

These are not aliases for `reference_missing_pps`. Multiple REF-only glitches
while association is already lost must not manufacture repeated physical-outage
transitions.

---

## State and Control Records

### `DISCIPLINE_STATE`

`DISCIPLINE_STATE` records describe the state of the discipline engine.

Examples:

- acquiring;
- locked;
- holdover;
- unlocked;
- estimator residuals;
- loop confidence;
- selected reference source;
- active clock domain.

These records are explanatory. They do not replace raw captures.

### `DAC_UPDATE`

`DAC_UPDATE` records describe deliberate steering actions.

Examples:

- DAC code applied;
- delta from prior code;
- target oscillator/control output;
- reason for update;
- loop state at time of update.

A DAC update is not itself a timing observation. It is a control action that may
explain later timing behavior.

---

## Context and Provenance Records

### `ENVIRONMENT`

`ENVIRONMENT` records describe physical context.

Examples:

- ambient temperature;
- board temperature;
- pressure;
- humidity;
- supply voltage;
- enclosure or sensor metadata.

Environmental telemetry should be timestamped, but it must not be confused with
hardware-captured event timing.

### `DEVICE_STATE`

`DEVICE_STATE` records describe instrument identity and operating state.

Examples:

- boot count;
- reset reason;
- firmware version;
- hardware revision;
- active oscillator;
- selected clock source;
- timing fabric configuration.

### `CONFIG_SNAPSHOT`

`CONFIG_SNAPSHOT` records describe the run configuration required for replay.

Examples:

- schema versions;
- selected mode profile;
- channel mapping;
- calibration constants;
- discipline tunables;
- output configuration.

A complete run should include enough configuration provenance to permit future
reinterpretation of raw observations.

---

## Host and Fault Records

### `HOST_EVENT`

`HOST_EVENT` records describe host-side operations and interruptions.

Examples:

- file opened or rolled over;
- backlog threshold crossed;
- dropped host record;
- network reconnect;
- dashboard restart;
- command received;
- analysis job started.

Host events are important for observability, but they must not define timing truth.

### `ERROR_EVENT`

`ERROR_EVENT` records describe explicit faults or anomalies.

Examples:

- capture overflow;
- invalid schema record;
- malformed input line;
- missed reference interval;
- impossible state transition;
- storage failure.

Do not bury significant anomalies only in generic flags when a distinct fault
record would be clearer and more replayable.

---

## Derived Records

### `ANALYSIS_PRODUCT`

`ANALYSIS_PRODUCT` records describe host-derived artifacts.

Examples:

- Allan deviation table;
- phase residual summary;
- oscillator stability report;
- pendulum cycle table;
- environmental correlation result;
- FFT or spectral product.

Derived products must identify their inputs, schema versions, transforms,
preprocessing assumptions, and filtering methodology.

Derived products should never overwrite or obscure raw observations.

---

## Relationship to Mode Profiles

Mode profiles interpret generic records.

For example, the same `EVENT_CAPTURE` stream may represent:

- pendulum photogate events;
- oscillator comparison pulses;
- TIC measurements;
- radio timing pulses;
- encoder transitions;
- laboratory trigger signals.

The firmware should emit the same kind of raw event record in all cases. The
profile explains how channels, edges, intervals, and reference captures should be
interpreted.

```text
canonical raw events
        ↓
mode profile
        ↓
derived datasets
        ↓
analysis + visualization
```

---

## Naming Guidance

Use long conceptual names in documentation and schemas:

```text
EVENT_CAPTURE
REF_CAPTURE
DISCIPLINE_STATE
CONFIG_SNAPSHOT
```

Compact encodings may use shorter wire tags when appropriate:

```text
EVT = compact CSV tag for EVENT_CAPTURE
REF = compact CSV tag for REF_CAPTURE
CNT = compact CSV tag for COUNT_OBSERVATION
```

When compact tags are used, the mapping to conceptual record types must be explicit
and versioned.

---

## Review Questions

When adding or changing telemetry records, ask:

1. Is this a raw observation, state, action, context, host operation, fault, or derived product?
2. Does this record establish timing truth, or merely explain/contextualize it?
3. Is the relevant clock/reference domain explicit?
4. Is the schema version explicit?
5. Could this be replayed offline from append-only logs?
6. Is application meaning being pushed into firmware unnecessarily?
7. Is the same semantic definition duplicated elsewhere?

If the answer to question 6 is yes, the design probably belongs in a mode profile
or host analysis layer rather than in capture firmware.
