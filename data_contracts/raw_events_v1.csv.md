# raw_events_v1.csv

## Purpose

Canonical event stream emitted by OTIS firmware.

This is the primary scientific artifact.

## Schema

| Field | Meaning |
|---|---|
| record_type | EVT |
| schema_version | schema revision |
| event_seq | monotonic event counter |
| channel_id | capture channel |
| edge | rising/falling |
| timestamp_ticks | raw reference-domain timestamp |
| clock_domain | clock source domain |
| flags | capture status flags |

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
