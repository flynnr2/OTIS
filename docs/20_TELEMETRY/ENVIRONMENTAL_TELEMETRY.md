# Environmental Telemetry

## Purpose

Environmental telemetry records sampled context that helps interpret timing behavior.

It is not part of the raw edge-capture channel model by default. Temperature,
humidity, pressure, supply rails, enclosure state, and similar measurements are
usually slow sampled observations or provenance, not events latched by the timing
fabric.

## Design Boundary

OTIS reserves numbered capture channels for signals with timing semantics:

- captured edges;
- reference pulses;
- gates;
- counted pulse trains;
- other signals observed by the timing fabric.

Environmental measurements should be represented as named telemetry sources or
manifest provenance until a sampled-observation contract exists. They should not
be encoded as fake `raw_events_v1` channels merely because they are useful to
analysis.

This boundary keeps the H0 channel map simple:

- `CH0` generic pulse/event input;
- `CH1` PPS/reference input;
- `CH2` oscillator count observation on `D8` / `GPIO20` / `GPIN0`.

## Why It Matters

Environmental data can explain or constrain later analysis of:

- oscillator frequency drift;
- reference stability;
- front-end behavior;
- supply sensitivity;
- thermal settling;
- long-run bench or enclosure conditions.

The data is important, but its importance does not imply edge-capture semantics.

## Future Contract Direction

A future environmental or sampled-observation contract should describe basics
such as:

- source identity;
- measurement kind;
- value;
- unit;
- observation time or domain;
- provenance and validity flags.

Exact sensors, buses, sample rates, column names, and validation rules are left
open until there is hardware and host tooling that need them.

## Manifest Guidance

Profiles and run manifests may eventually declare environmental sources by name
and purpose, for example oscillator temperature or board temperature. Those
declarations should remain descriptive until the project has a concrete sampled
telemetry contract.

Do not allocate new numbered capture channels for environmental sensors unless a
sensor output is intentionally connected to the timing fabric as an edge, gate,
or counted signal.
