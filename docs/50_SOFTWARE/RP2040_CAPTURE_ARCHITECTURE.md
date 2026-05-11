# RP2040 Capture Architecture

## Scope

This document describes the intended H0/SW1 RP2040 capture architecture.

It is intentionally a design note rather than a finalized implementation.

## Design Principles

- deterministic edge observation first;
- host-side interpretation second;
- explicit timing domains always;
- replayability preserved;
- minimal hidden firmware semantics.

## Core Separation

Suggested first-pass division:

| Core | Responsibility |
|---|---|
| Core 0 | timing capture, DMA/ring ownership, timestamp-domain integrity |
| Core 1 | USB/serial transport, status emission, host commands |

The exact split may evolve, but timing capture must remain isolated from non-deterministic host/service work.

For the Arduino Nano RP2040 Connect path, SW1 targets the Earle Philhower
`arduino-pico` core. Its Arduino-facing multicore model maps naturally onto the
intended split: `setup()` / `loop()` can own host-facing USB serial transport on
core 0, while `setup1()` / `loop1()` can later own capture/ring-buffer work on
core 1. The first GPIO proof may remain single-core until the record contract
and live edge path are proven.

## Capture Families

The RP2040 should emit separate semantic record families:

| Family | Meaning |
|---|---|
| `EVT` | generic pulse/event captures |
| `REF` | reference captures such as PPS |
| `CNT` | count observations |
| `STS` | status/health telemetry |

## Count Philosophy

A 10 MHz or 16 MHz oscillator should not normally emit every edge.

Preferred approaches:

- gated counting;
- reciprocal counting;
- divider chains;
- hardware counters with explicit observation windows.

## Frozen SW1 H0 Inputs

The SW1 Arduino Nano RP2040 Connect live-capture convention is:

| Channel | Role | Arduino pin |
|---:|---|---:|
| `CH0` | generic pulse/event input | `D10` |
| `CH1` | PPS/reference input | `D14` |
| `CH2` | divided/gated oscillator observation input | `D2` |

## Overflow Policy

All timestamp domains must define:

- counter width;
- rollover semantics;
- reconstruction policy;
- overflow provenance flags.

## Loss Policy

The firmware should prefer:

```text
explicitly flagged loss
```

over:

```text
silent loss
```

A scientifically imperfect but explicit artifact is preferable to an apparently clean artifact that silently lost provenance.
