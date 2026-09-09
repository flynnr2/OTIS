# PPS-gated oscillator plant v1

`profiles/plant_models/pps_gated_oscillator_plant_v1.json` is the sole current
plant-model authority for adaptive-hybrid regulation. Its exact identity is:

- reference: `model:pps_gated_oscillator_plant_v1`;
- model ID: `OTIS_PPS_GATED_OSCILLATOR_PLANT_V1`;
- semantic version on the wire: `1`;
- artifact identity: SHA-256 of the profile's exact bytes.

Firmware `CTL` records must emit all four values. The host contract validator
compares the reference, model ID, and semantic version exactly and compares the
emitted hash with the current profile bytes. A different, missing, or stale
identity is a model-local validation failure and cannot be treated as control
authority.

The profile binds the actual instrument topology: D14 is the sole PPS/reference
input, D8 is the sole oscillator/count input, D10 is optional external-event
evidence with no control or terminal authority, and the actuator is the AD5693R
at address `0x4C`. It records the bounded automatic-control range
`0xA800..0xAB00`, nominal code, gain sign and interval, settling exclusion,
selected control cadence, evidence-backed temperature span, invalidation
conditions, and known limitations.

Unknown physical quantities remain explicit limitations. They must not be
invented as zeros or used to widen applicability. A topology, actuator,
estimator, range, or measurement-semantics change requires a new deliberate
plant profile and a coordinated firmware/host contract change; the current
reader has no compatibility branch for retired model layouts.
