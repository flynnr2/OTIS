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

## Implemented Contract

Low-rate environmental observations use `environment_v1.csv` / `ENV` rows:

```text
record_type,schema_version,env_seq,timestamp_ticks,observation_domain,source,role,temperature_c,relative_humidity_pct,pressure_pa,flags
```

For H1 VCOCXO characterization, `source=sht4x` and `role=vcocxo_near`
is the preferred temperature signal because the SHT4x family is a better
temperature sensor than the BMP280. BMP280 rows are still useful as pressure
context and a secondary temperature cross-check, typically with
`role=pressure_reference`.

## Manifest Guidance

Profiles and run manifests may declare environmental sources by name and
purpose, for example oscillator temperature or board temperature. Those
declarations describe sampled context and do not allocate capture channels.

Do not allocate new numbered capture channels for environmental sensors unless a
sensor output is intentionally connected to the timing fabric as an edge, gate,
or counted signal.
