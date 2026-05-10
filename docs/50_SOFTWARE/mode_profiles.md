# OTIS Mode Profiles

## Purpose

Mode profiles allow host-side interpretation of generic canonical event streams.

Firmware remains application-neutral.

## Philosophy

The RP2040 should not know:

- whether a pendulum emits 2 or 4 events;
- whether an input is a reference such as GNSS PPS;
- whether a signal represents a clock, encoder, or radio timing pulse;
- whether timing should be interpreted as tick/tock.

Profiles define those semantics host-side.

## Example

```yaml
mode: pendulum_synchronome
profile_schema_version: 1
profile_version: 1
inputs:
  photogate_channel: 0
reference_inputs:
  gnss_pps_channel: 1
assumptions:
  nominal_period_s: 2.0
  impulse_period_swings: 15
interpretation:
  pair_edges: true
  infer_tick_tock: true
```

## Example Modes

- generic_tic
- pendulum_synchronome
- oscillator_compare
- tcxo_benchmark
- ham_radio_timing

## Long-Term Direction

Profiles become the semantic bridge between:

```text
canonical raw events
        ↓
mode interpretation
        ↓
derived datasets
        ↓
analysis + visualisation
```

## Profile Versioning

`profile_schema_version` identifies the structure of the profile file itself.

`profile_version` identifies the semantic version of a specific profile. It may
change when channel mappings, assumptions, or interpretation policy change even
if the YAML schema remains the same.
