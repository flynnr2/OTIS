# Canonical Event Model

## Purpose

The canonical event model defines the raw records emitted by OTIS capture firmware and persisted by the host.

It should be:

- minimal;
- stable;
- explicit;
- lossless;
- application-neutral.

The RP2040 firmware should not interpret events as pendulum swings, oscillator phase measurements, or radio timing intervals.

Firmware emits timestamped events.
Host software interprets them.

## Architectural Principle

```text
RP2040 firmware = deterministic timestamp appliance
Host software   = interpretation + analysis engine
```

## Canonical Event Record

The conceptual record type is `EVENT_CAPTURE`. In `raw_events_v1.csv`, the compact
CSV tag `EVT` is used as the wire encoding of `EVENT_CAPTURE`.

Conceptual event structure:

```text
record_type,
schema_version,
event_seq,
channel_id,
edge,
timestamp_ticks,
clock_domain,
flags
```

Example:

```csv
EVT,1,123456,0,R,9876543210,MAIN,0
EVT,1,123457,0,F,9876548120,MAIN,0
EVT,1,123458,1,R,9880000000,MAIN,PPS_CANDIDATE
```

## Why this split matters

The same raw event stream may represent:

- pendulum photogate events;
- GPS PPS edges;
- oscillator comparison pulses;
- TIC measurements;
- HAM/radio timing experiments;
- encoder transitions;
- laboratory trigger signals.

Interpretation should therefore live entirely host-side.

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
