# RP2040 Capture Architecture

## Scope

This document describes the H0/SW1 RP2040 capture architecture and its staged
implementation. Historical bring-up sections remain labelled by their SW1
stage; the current PPS-gated ratio backend and the dual-core ownership split
below are implemented architecture, not future placeholders. The Arduino
backend boundary is documented in `ARDUINO_CAPTURE_BACKENDS.md`.

## Design Principles

- deterministic edge observation first;
- host-side interpretation second;
- explicit timing domains always;
- replayability preserved;
- minimal hidden firmware semantics.

## Core Separation

The frozen Arduino-Pico division is:

| Core | Responsibility |
|---|---|
| Core 0 | USB/serial transport, status emission, host commands and service I/O |
| Core 1 | timing capture, DMA/ring ownership, timestamp-domain integrity and discipline |

Timing capture and discipline state remain isolated from non-deterministic
host/service work. Any later change to this convention requires a new
architecture decision and new isolation evidence.

For the Arduino Nano RP2040 Connect path, SW1 targets the Earle Philhower
`arduino-pico` core. `setup()` / `loop()` own host-facing USB serial transport,
GNSS/environment service and physical DAC I2C execution on Core 0;
`setup1()` / `loop1()` own PIO/DMA draining, raw timing construction,
estimation and control state on Core 1. Bounded immutable queues are the only
cross-core contract. Earlier GPIO bring-up proofs were single-core; that is
historical evidence and not the current discipline architecture.

## Capture Families

The RP2040 should emit separate semantic record families:

| Family | Meaning |
|---|---|
| `EVT` | generic pulse/event captures |
| `REF` | reference captures such as PPS |
| `CNT` | count observations |
| `MNS` | raw D6 forwarded-output monitor snapshots |
| `STS` | status/health telemetry |

## Count Philosophy

A 10 MHz or 16 MHz oscillator should not normally emit every edge.

Preferred approaches:

- gated counting;
- reciprocal counting;
- divider chains;
- hardware counters with explicit observation windows.

The PPS-gated ratio backend follows this count-observation rule: one PIO state
machine autonomously snapshots its cumulative oscillator-edge counter on PPS,
PPS edges remain independently visible as `REF` rows, raw cumulative values
remain visible as `SNP`, and adjacent hardware snapshots produce the raw `CNT`.
The associated D14 timestamps validate the nominal gate but do not define the
physical count aperture. Host analysis may derive oscillator ratio, frequency,
and ppm from the raw streams.
See `PPS_GATED_RATIO_BACKEND_DESIGN.md` and
`COUNT_OBSERVATION_MEASUREMENT_CONTRACT.md`.

## Frozen SW1 H0 Inputs

The SW1 Arduino Nano RP2040 Connect live-capture convention is:

| Channel | Role | Arduino pin |
|---:|---|---:|
| `CH0` | generic pulse/event input | `D10` |
| `CH1` | PPS/reference input | `D14` |
| `CH2` | divided/gated oscillator observation input | `D8` / `GPIO20` / `GPIN0` |
| `CH3` | zero-authority forwarded-output monitor | `D6` / `GPIO18` |

## Reserved Clock Pins

The SW1 H0 pin convention keeps RP2040 clock-function pins explicit:

| Arduino pin | RP2040 GPIO | Clock function | OTIS use |
|---:|---:|---|---|
| `D8` | `GPIO20` | `GPIN0` | external OCXO/reference input |
| `D9` | `GPIO21` | `GPOUT0` | compile-time GPIN0 forwarded output, otherwise reserved/high impedance |
| `D2` | `GPIO25` | `GPOUT3` | secondary diagnostic clock, reserved output |

All active and reserved GPIO, IRQ, PIO, DMA, timer, and clock claims are
validated before mode hardware setup. The authoritative ledger and emitted
ownership diagnostics are defined in
[`HARDWARE_RESOURCE_OWNERSHIP.md`](HARDWARE_RESOURCE_OWNERSHIP.md).

Do not reuse `D9` or `D2` as general capture inputs. D6 is selected only by the
exact readiness profile and remains outside the authoritative capture plane.

## D6 diagnostic sidecar

The optional D6 monitor reuses the proved cumulative PIO snapshot programme in
a distinct PIO0 state machine and instruction range. D6 supplies `IN_BASE`;
D14 is a shared read-only snapshot condition. Firmware emits one raw `MNS`
record per serviced snapshot and may derive a channel-3 `CNT` interval only
from adjacent monitor and D14 identities. Each `MNS` carries both the monitor
session and authoritative reference session so a reset boundary cannot be
bridged by recency.

The monitor has its own drop-new queue and no DMA. It never backpressures the
D14/D8 queue. Missing snapshots, FIFO backlog, resource exhaustion, local
status, sequence gaps, duplicate identities, and ambiguous counter movement
re-anchor or disable only the monitor. D6 records cannot enter D14/D8 validity,
selected estimation, control eligibility, actuator requests, abort, or a run
terminal.

The retained Prompt 02 physical package exercised this sidecar with the D9 to
D6 1 kΩ loopback. Its 90 same-reference D8:D6 comparisons differed by zero or
one cycle, within the frozen two-cycle tolerance, while the 90 D14/D8 monitor
stratum intervals remained healthy. This is a D6-local digital-continuity
result, not a replacement for an external D9 waveform/frequency instrument or
an input to control truth. The package's D9 waveform terminal remains
`output_function_correct_but_waveform_evidence_incomplete`.

## SW1 H0 Bring-Up Modes

The Arduino Nano RP2040 Connect sketch supports explicit compile-time bring-up
modes:

| Mode | Done means |
|---|---|
| `SW1_SYNTHETIC_USB` | host captures valid `STS`, `EVT`, `REF`, and `CNT` rows from USB serial and validates the run |
| `SW1_GPIO_LOOPBACK` | `D7` output jumpered to `D10` produces live `EVT` rows on `CH0` with increasing sequence numbers and timestamps |
| `SW1_GPS_PPS` | GPS PPS on `D14` produces `REF` rows on `CH1`; host cadence sanity is approximately 1 Hz |
| `SW1_TCXO_OBSERVE` | TCXO observation on `D8` / `GPIO20` / `GPIN0` produces `CNT` rows on `CH2` through the RP2040 frequency counter by default, and GPS PPS on `CH1` is captured when wired |

`SW1_TCXO_OBSERVE` and `H1_OCXO_OBSERVE_OPEN_LOOP` can select the PPS-gated
ratio count backend with `OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO`. That
selector changes how the `CNT` gate is formed; it does not change `CNT` into a
derived frequency record.

The live interrupt path is a first SW1 bring-up mechanism. It emits canonical
records with explicit provenance, including `TIMESTAMP_RECONSTRUCTED` where the
timestamp comes from the RP2040 timer read in firmware rather than a PIO/DMA
latch. Later SW1 work may replace this mechanism with the intended PIO-backed
capture fabric without changing the CSV contracts.

## SW1.5a PIO FIFO Edge Capture

SW1.5a introduces a deliberately narrow PIO backend:

- one PIO state machine;
- rising-edge detection only;
- one selected GPIO based on bring-up mode;
- CPU drains the PIO RX FIFO;
- existing `EVT` / `REF` protocol emission is reused;
- no DMA and no oscillator steering.

The firmware switch is `OTIS_CAPTURE_BACKEND`. The conservative default is
`OTIS_CAPTURE_BACKEND_IRQ`, which preserves SW1 `capture_mode=irq_reconstructed`.
The experimental backend is `OTIS_CAPTURE_BACKEND_PIO_FIFO`, which emits
`capture_mode=pio_fifo_cpu_timestamped`.

The PIO program proves that selected GPIO edges are observed by PIO, but it does
not yet latch final event timestamps in hardware. Firmware reads the FIFO in the
main loop and attaches an `rp2040_timer0` timestamp at drain time. Records
therefore keep `TIMESTAMP_RECONSTRUCTED`, and reports must treat them as
PIO-detected but CPU-timestamped.

Initial routing:

| Bring-up mode | PIO GPIO | Channel | Record family |
|---|---:|---:|---|
| `SW1_GPIO_LOOPBACK` | `D10` / GPIO5 | `CH0` | `EVT` |
| `SW1_GPS_PPS` | `D14` / GPIO26 | `CH1` | `REF` |
| `SW1_TCXO_OBSERVE` | `D14` / GPIO26 | `CH1` | `REF` |

PIO FIFO status is emitted through `STS` rows: `pio_init`, `pio_gpio`,
`pio_edge`, `pio_fifo_drained_event_count`, `pio_fifo_empty_count`,
`pio_fifo_overflow_drop_count`, and `pio_fifo_max_drain_batch`. Nonzero
overflow/drop status is a warning that the FIFO was not serviced fast enough;
the current counter is not a precise edge-loss total.

SW1.5b is expected to replace CPU-drain timestamp attachment with a DMA-backed
path and a clearer hardware timestamp strategy.

`SW1_TCXO_OBSERVE` is a count-observation mode. The default SW1 backend uses
the RP2040 clock frequency counter with `GPIO20` configured as `CLOCK GPIN0`.
Alternate count-observation backends include GPIO IRQ divided-only counting,
PIO long-gate raw-edge counting, and PPS-gated ratio counting.
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
