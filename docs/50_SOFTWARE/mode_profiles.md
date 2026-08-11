# OTIS Mode Profiles

## Purpose

Mode profiles were introduced to allow host-side interpretation of generic
canonical event streams. Canonical raw capture remains application-neutral,
but the current firmware also contains explicit OTIS product, measurement,
diagnostic, and bounded-control profiles. Do not describe the complete firmware
as application-neutral.

## Philosophy

The RP2040 should not know:

- whether a pendulum emits 2 or 4 events;
- whether an input is a reference such as GNSS PPS;
- whether a signal represents a clock, encoder, or radio timing pulse;
- whether timing should be interpreted as tick/tock.

Profiles define those semantics host-side.

## Current lifecycle

`h0_reference.yaml` remains a diagnostic/reference profile. The unimplemented
`generic_tic` and `pendulum_synchronome` examples were retired during platform
stabilization because they had no executable consumer or near-term product
owner. Git history preserves their exploratory intent; the active repository
does not imply support for them.

## Long-Term Direction

Where a concrete product requires host-side semantic interpretation, a
versioned profile may provide the bridge between:

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
