# raw_events_v1.csv

## Purpose

Canonical compact CSV encoding of `EVENT_CAPTURE` records emitted by OTIS firmware.

This is the primary timing-observation scientific artifact.

## Schema

| Field | Meaning |
|---|---|
| record_type | compact record tag; `EVT` means `EVENT_CAPTURE` |
| schema_version | schema revision |
| event_seq | monotonic event counter |
| channel_id | capture channel |
| edge | rising/falling |
| timestamp_ticks | raw reference-domain timestamp |
| clock_domain | clock source domain |
| flags | capture status flags |

## Record Type Semantics

`EVENT_CAPTURE` is the conceptual OTIS record type for external/user timing
observations captured by the timing fabric.

`EVT` is the compact CSV wire tag for `EVENT_CAPTURE` in this schema.

The record describes what was captured, not what the event means in a particular
experiment. Mode profiles and host-side analysis interpret channels, edges, and
intervals as pendulum ticks, oscillator comparison pulses, TIC measurements, radio
timing events, or other application-specific meanings.

## Design Constraints

- application-neutral;
- replayable;
- lossless;
- deterministic;
- explicit provenance.

## Non-Goals

This file does NOT directly encode:

- pendulum semantics;
- tick/tock interpretation;
- oscillator phase analysis;
- Allan deviation;
- derived timing metrics.

Those belong host-side.
