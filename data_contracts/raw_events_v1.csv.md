# raw_events_v1.csv

## Purpose

Canonical compact CSV encoding of raw OTIS edge-capture records emitted by capture firmware.

This is the primary timing-observation artifact for individual pulse edges. It is intentionally application-neutral.

## Schema

| Field | Type | Meaning |
|---|---|---|
| `record_type` | enum | compact record tag; `EVT` means user/event capture, `REF` means reference capture |
| `schema_version` | uint | schema revision; currently `1` |
| `event_seq` | uint64 | monotonic observation counter within the emitting device/run |
| `channel_id` | uint16 | physical or logical capture channel |
| `edge` | enum | captured edge: `R` rising, `F` falling, `B` both/unspecified edge when hardware cannot disambiguate |
| `timestamp_ticks` | uint64 | raw timestamp ticks latched or reconstructed by the timing fabric |
| `capture_domain` | string | native domain in which `timestamp_ticks` was captured |
| `flags` | uint32 | numeric bitmask from `capture_flags_v1` |

## Record Type Semantics

| Tag | Conceptual type | Use |
|---|---|---|
| `EVT` | `EVENT_CAPTURE` | external/user timing observations such as photogates, comparator pulses, TIC inputs, and generic event pulses |
| `REF` | `REF_CAPTURE` | declared reference events such as GNSS PPS, lab reference PPS, or other reference-class timing pulses |

Reference captures should not be encoded as `EVT` plus a semantic flag. Use `REF` so host tooling, replay, and discipline analysis preserve the distinction between user events and reference observations.

The record describes what was captured, not what the event means in a particular experiment. Profiles and host-side analysis interpret channels, edges, and intervals as pendulum ticks, oscillator comparison pulses, radio timing events, or other application-specific meanings.

## H0 Reference Channels

The initial H0 mapping is a profile convention, not a permanent firmware law:

| Channel | H0 role | Expected record family |
|---:|---|---|
| `0` | generic pulse/event input | `EVT` |
| `1` | GNSS PPS reference input | `REF` |
| `2` | TCXO/XCXO observation input when divided to capturable pulse rates | `EVT` or count observation, depending on mode |

Device status uses `health_v1.csv` / `STS`; it is not a channel in `raw_events_v1`.

## Domain Semantics

`capture_domain` names the native timing domain in which `timestamp_ticks` was latched.

It does not necessarily mean UTC, the external reference domain, the oscillator source by itself, or a host-reconstructed timeline.

Derived datasets may project raw captures into reconstructed, disciplined, reference, UTC, or host domains. Those projections must preserve provenance back to this raw `capture_domain`.

## Pulse Examples

```csv
record_type,schema_version,event_seq,channel_id,edge,timestamp_ticks,capture_domain,flags
EVT,1,1000,0,R,1600001234,rp2040_timer0,0
EVT,1,1001,0,F,1600001872,rp2040_timer0,0
REF,1,1002,1,R,1600010000,rp2040_timer0,0
```

A host profile might derive a pulse width from the first two rows and a phase offset versus the `REF` row, but those are derived products, not raw capture semantics.

## Relationship to Count Observations

High-rate oscillator observation must not be represented by emitting every oscillator edge. For TCXO/XCXO observation at rates such as 10 MHz or 16 MHz, use `count_observations_v1.csv` unless the oscillator has been divided down to an event rate that is intentionally capturable as raw edges.

## Flags

`flags` is a numeric bitmask defined by `data_contracts/capture_flags_v1.md`.

Unallocated bits are reserved and must be emitted as zero until assigned by a future schema revision.

## Non-Goals

This file does not directly encode:

- pendulum tick/tock interpretation;
- oscillator phase analysis;
- Allan deviation;
- derived timing metrics;
- lock-state conclusions;
- oscillator steering decisions;
- device health messages.

Those belong in host-side analysis, derived datasets, status streams, or explicit control telemetry.
