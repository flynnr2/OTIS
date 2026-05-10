# raw_events_v1.csv

## Purpose

Canonical compact CSV encoding of raw OTIS timing-observation records emitted by
capture firmware.

This is the primary timing-observation scientific artifact.

## Schema

| Field | Meaning |
|---|---|
| record_type | compact record tag; `EVT` means `EVENT_CAPTURE`, `REF` means `REF_CAPTURE` |
| schema_version | schema revision for this CSV contract |
| event_seq | monotonic observation counter within the emitting device/run |
| channel_id | capture channel |
| edge | captured edge; `R` = rising, `F` = falling |
| timestamp_ticks | raw timestamp ticks latched by the timing fabric |
| capture_domain | native domain in which `timestamp_ticks` was captured |
| flags | unsigned numeric capture-status bitmask |

## Record Type Semantics

`EVENT_CAPTURE` is the conceptual OTIS record type for external/user timing
observations captured by the timing fabric.

`REF_CAPTURE` is the conceptual OTIS record type for declared reference events
captured by the timing fabric, such as GNSS PPS or another reference input.

`EVT` is the compact CSV wire tag for `EVENT_CAPTURE`.

`REF` is the compact CSV wire tag for `REF_CAPTURE`.

Reference captures should not be encoded as `EVT` plus a semantic flag. Use `REF`
so host tooling, replay, and discipline analysis can preserve the distinction
between user events and reference observations.

The record describes what was captured, not what the event means in a particular
experiment. Mode profiles and host-side analysis interpret channels, edges, and
intervals as pendulum ticks, oscillator comparison pulses, TIC measurements, radio
timing events, or other application-specific meanings.

## Domain Semantics

`capture_domain` names the native timing domain in which `timestamp_ticks` was
latched.

It does not necessarily mean:

- UTC;
- the external reference domain;
- the oscillator source by itself;
- a host-reconstructed timeline.

Derived datasets may project raw captures into reconstructed, disciplined,
reference, UTC, or host domains. Those projections must preserve provenance back
to this raw `capture_domain`.

## Flags

`flags` is an unsigned numeric bitmask. Symbolic names may be used in
documentation and host tooling, but compact CSV records should carry the numeric
value.

Initial allocation:

| Bit | Hex | Symbol | Meaning |
|---:|---:|---|---|
| 0 | `0x00000001` | `CAPTURE_OVERFLOW_NEARBY` | capture occurred near a counter overflow or required overflow disambiguation |
| 1 | `0x00000002` | `CAPTURE_RING_OVERRUN` | capture ring overran before the host/firmware drained it |
| 2 | `0x00000004` | `EDGE_ORDER_SUSPECT` | edge order or polarity sequence was unexpected |
| 3 | `0x00000008` | `REFERENCE_VALIDITY_SUSPECT` | reference capture was emitted but reference validity was uncertain |
| 4 | `0x00000010` | `TIMESTAMP_RECONSTRUCTED` | timestamp includes deterministic reconstruction beyond the hardware latch |
| 5 | `0x00000020` | `SOURCE_HEALTH_SUSPECT` | input source or conditioning health was suspect |

Unallocated bits are reserved and must be emitted as zero until assigned by a
future schema revision.

Flags are for capture status and quality metadata. They must not be used to
change the primary semantic class of a record. For example, use `REF` for GNSS PPS
captures rather than `EVT` with a `PPS_CANDIDATE` flag.

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
- derived timing metrics;
- lock-state conclusions;
- oscillator steering decisions.

Those belong host-side or in explicit state/control telemetry.
