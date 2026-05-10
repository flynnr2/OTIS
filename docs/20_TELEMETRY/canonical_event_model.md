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

The RP2040 firmware should not interpret events as pendulum swings, oscillator
phase measurements, or radio timing intervals.

Firmware emits timestamped observations.
Host software interprets them.

## Architectural Principle

```text
RP2040 firmware = deterministic timestamp appliance
Host software   = interpretation + analysis engine
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
