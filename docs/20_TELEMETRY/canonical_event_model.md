# Canonical Event Model

## Purpose

The canonical event model defines the raw observation records emitted by OTIS
capture firmware and persisted by the host.

It should be:

- minimal;
- stable;
- explicit;
- lossless;
- application-neutral.

The Arduino Nano RP2040 Connect firmware should not interpret events as
pendulum swings, oscillator phase measurements, or radio timing intervals.

Firmware emits timestamped observations.
Host software interprets them.

## Architectural Principle

```text
Arduino Nano RP2040 Connect firmware = deterministic timestamp appliance
Host software                         = interpretation + analysis engine
```

## Canonical Observation Records

OTIS currently distinguishes two raw observation record types:

| Conceptual type | Compact tag | Meaning |
|---|---|---|
| `EVENT_CAPTURE` | `EVT` | external/user timing event captured by the timing fabric |
| `REF_CAPTURE` | `REF` | declared reference event captured by the timing fabric |

Both are raw observations. Neither encodes application-specific conclusions.

`EVT` is for user/external event channels such as photogates, comparator
crossings, oscillator comparison pulses, encoder transitions, RF timing pulses,
or laboratory triggers.

`REF` is for declared reference inputs such as GNSS PPS or another reference
event used for discipline, syntonization, synchronization, or later comparison.

Do not encode GNSS PPS as `EVT` plus a semantic flag. Use `REF`.

## Conceptual Record Structure

```text
record_type,
schema_version,
event_seq,
channel_id,
edge,
timestamp_ticks,
capture_domain,
flags
```

`capture_domain` is the native timing domain in which `timestamp_ticks` was
latched. It is not necessarily UTC, and it is not necessarily the same thing as a
reference domain or oscillator source name.

## Examples

```csv
EVT,1,123456,0,R,9876543210,MAIN,0
EVT,1,123457,0,F,9876548120,MAIN,0
REF,1,123458,1,R,9880000000,MAIN,0
```

In this example, the `REF` row is a captured reference event, such as a GNSS PPS
edge, latched in the local `MAIN` capture domain.

## Flags

Flags describe capture status and quality metadata. They must not carry primary
record-type semantics.

For example, use:

```text
REF,...,0
```

not:

```text
EVT,...,PPS_CANDIDATE
```

Reference identity, validity, lock state, and discipline conclusions should be
represented by explicit reference records, configuration/provenance records, or
discipline-state telemetry rather than by overloading `EVENT_CAPTURE`.

## Why this split matters

The same raw observation stream may represent:

- pendulum photogate events;
- GNSS PPS edges;
- oscillator comparison pulses;
- TIC measurements;
- HAM/radio timing experiments;
- encoder transitions;
- laboratory trigger signals.

Interpretation should therefore live host-side.

## Canonical OTIS Run Artifacts

A complete OTIS run should contain:

```text
raw_events.csv
health.csv
run_manifest.json
selected_profile.yaml
```

Everything else should be reproducible from those artifacts.

## Derived Products

Derived outputs may include:

- pendulum cycle tables;
- PPS phase error;
- Allan deviation;
- oscillator stability reports;
- heatmaps;
- FFT analysis;
- impulse classification;
- timing residual analysis.

These are not firmware responsibilities.

## Temporary D10 PPS Witness Telemetry

For the H1 PPS anomaly investigation, firmware can be built with
`OTIS_ENABLE_PPS_DUAL_OBSERVER=1`. D14 remains the normal PPS reference path.
D10 is configured as `INPUT`, rising-edge only, with no internal pull, and is
temporarily tied to the same physical PPS signal as an independent diagnostic
witness.

Periodic `STS` records expose raw diagnostic accounting without changing REF
acceptance, count gates, DAC behavior, or control eligibility:

- `pps_d14.raw_edge_count`, `accepted_pps_count`, `rejected_short_count`,
  `rejected_long_count`, `last_raw_timestamp`, `last_raw_interval`,
  `last_accepted_timestamp`, `sampled_high_count`, `sampled_low_count`;
- `pps_d10.raw_edge_count`, `last_edge_timestamp`, `last_interval`,
  `short_interval_count`, `sampled_high_count`, `sampled_low_count`,
  `buffer_overflow_count`;
- `pps_dual_observer.d14_raw_minus_d10_raw`, `agreement_state`,
  `burst_active`, and `burst_count`.

The D14 and D10 interval diagnostics classify intervals with modular RP2040
`micros()`-derived timer arithmetic. A normal PPS interval that crosses the
32-bit timer rollover must remain a normal interval and must not increment
`rejected_long_count` or the D10 long-interval diagnostic. Historical captures
made before this correction can still contain rollover-contaminated D14
`rejected_long_count` values; preserve those raw counts as evidence and qualify
them with host-side unwrapped REF analysis before using them in readiness
judgements.

Interpretation is diagnostic: both pins bursting suggests shared electrical or
upstream PPS behavior; D14-only activity points toward the D14 capture/backend or
downstream path; D10-only activity points toward D10-local wiring/configuration
or threshold asymmetry; normal raw counters with anomalous emitted records points
downstream of capture. Sampled pin level is evidence, but it cannot reconstruct
electrical glitches shorter than ISR latency.
