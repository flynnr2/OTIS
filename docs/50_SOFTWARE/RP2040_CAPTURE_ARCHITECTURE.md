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
| `CH2` | divided/gated oscillator observation input | `D8` / `GPIO20` / `GPIN0` |

## Reserved Clock Pins

The SW1 H0 pin convention keeps RP2040 clock-function pins explicit:

| Arduino pin | RP2040 GPIO | Clock function | OTIS use |
|---:|---:|---|---|
| `D8` | `GPIO20` | `GPIN0` | external OCXO/reference input |
| `D9` | `GPIO21` | `GPOUT0` | internal clock visibility, reserved output |
| `D2` | `GPIO25` | `GPOUT3` | secondary diagnostic clock, reserved output |

Do not reuse `D9` or `D2` as general capture inputs.

## SW1 H0 Bring-Up Modes

The Arduino Nano RP2040 Connect sketch supports explicit compile-time bring-up
modes:

| Mode | Done means |
|---|---|
| `SW1_SYNTHETIC_USB` | host captures valid `STS`, `EVT`, `REF`, and `CNT` rows from USB serial and validates the run |
| `SW1_GPIO_LOOPBACK` | `D7` output jumpered to `D10` produces live `EVT` rows on `CH0` with increasing sequence numbers and timestamps |
| `SW1_GPS_PPS` | GPS PPS on `D14` produces `REF` rows on `CH1`; host cadence sanity is approximately 1 Hz |
| `SW1_TCXO_OBSERVE` | TCXO observation on `D8` / `GPIO20` / `GPIN0` produces `CNT` rows on `CH2` through the RP2040 frequency counter by default, and GPS PPS on `CH1` is captured when wired |

The live interrupt path is a first SW1 bring-up mechanism. It emits canonical
records with explicit provenance, including `TIMESTAMP_RECONSTRUCTED` where the
timestamp comes from the RP2040 timer read in firmware rather than a PIO/DMA
latch. Later SW1 work may replace this mechanism with the intended PIO-backed
capture fabric without changing the CSV contracts.

`SW1_TCXO_OBSERVE` is a count-observation mode. The default SW1 backend uses
the RP2040 clock frequency counter with `GPIO20` configured as `CLOCK GPIN0`.
Do not attach a raw 16 MHz TCXO to a GPIO interrupt path; that will starve
firmware and USB service. The GPIO interrupt counter backend is reserved for
deliberately divided, interrupt-safe test signals.

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
