# Pulse Input Front End

## Purpose

This document defines the first OTIS pulse-input assumptions for H0 and future stages.

The pulse input path is intentionally generic.

A pulse may represent:

- photogate interruption;
- comparator-shaped analog event;
- GNSS PPS;
- TIC edge;
- open-drain sensor output;
- divided oscillator output;
- radio timing pulse;
- switch closure;
- laboratory timing reference.

The capture system should observe edges deterministically without embedding application meaning into firmware.

## Initial Electrical Assumption

H0 assumes:

- RP2040 GPIO-safe logic levels only;
- 3.3 V logic into RP2040 inputs;
- external conditioning required for higher voltages or analog signals.

## Input Classes

| Class | Typical source | Notes |
|---|---|---|
| logic pulse | MCU, divider, logic gate | clean digital edge |
| open-drain/open-collector | sensors, PPS outputs | requires pull-up policy |
| photogate | optical interrupter | may require shaping/hysteresis |
| comparator-shaped analog | contact mic, analog threshold detector | comparator semantics matter |
| PPS/reference | GNSS PPS or lab reference | reference-class semantics |
| divided oscillator | TCXO/XCXO divider chain | usually better represented by count observations |

## Conditioning Guidance

Recommended first-pass conditioning:

- Schmitt-trigger edge cleaning where appropriate;
- explicit pull-up/pull-down policy;
- short ground returns;
- explicit level assumptions;
- documented inversion semantics.

The H0 reference experiments use SN74AHCT1G14-based edge conditioning, but RP2040 GPIO voltage assumptions must remain explicit.

## Capture Semantics

Profiles may request:

- rising-only capture;
- falling-only capture;
- both-edge capture;
- pulse-width derivation;
- dead-time/debounce policy.

Raw records should still preserve the original edge observations wherever practical.

## Pulse Quality Flags

Recommended quality flags include:

- `PULSE_TOO_NARROW`
- `PULSE_TOO_WIDE`
- `EDGE_ORDER_SUSPECT`
- `INPUT_STUCK_LOW`
- `INPUT_STUCK_HIGH`
- `SOURCE_HEALTH_SUSPECT`

## Design Rule

Do not let front-end circuitry redefine timestamp semantics.

Better hardware may improve edge quality, jitter, and reliability, but raw observation semantics should remain stable across hardware substitution.
