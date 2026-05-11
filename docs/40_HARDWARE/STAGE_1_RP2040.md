# Stage 1 RP2040 Timing Core

The initial OTIS implementation is an open-loop RP2040 timing appliance. Its purpose is to prove the capture, telemetry, provenance, and replay architecture before adding oscillator steering or GPSDO control loops.

Stage 1 is not primarily a GPSDO. It is a deterministic timestamp and reference observation platform.

## Goals

- capture GNSS PPS as a reference event;
- observe a TCXO, OCXO, GPSDO output, or oscillator under test as an input signal;
- capture generic external timing events;
- emit canonical raw event telemetry;
- preserve explicit timing-domain and provenance metadata;
- support host-side replay and analysis from recorded artifacts.

## Hardware Assumption

The RP2040 board clock remains the implementation clock for firmware, USB, DMA, and PIO execution. Stage 1 does **not** require feeding a TCXO or OCXO into the RP2040 system clock input.

Reference oscillators enter Stage 1 as conditioned GPIO signals observed by the PIO/DMA capture fabric.

```text
RP2040 board clock
  -> runs firmware / USB / PIO / DMA

TCXO / OCXO / oscillator under test
  -> buffer / level conditioning
  -> RP2040 GPIO / PIO
  -> observed as reference-signal evidence

GNSS PPS
  -> RP2040 GPIO / PIO
  -> captured as a reference event
```

See `docs/10_REFERENCE_ARCHITECTURE/REFERENCE_SIGNAL_MODEL.md`.

## Timing Fabric

The RP2040 PIO subsystem is initially envisioned as the timing fabric.

PIO responsibilities may include:

- edge capture;
- reciprocal counting;
- counter gating;
- reference-pulse counting;
- pushing timestamp/count records into DMA-backed buffers.

Firmware should keep the timing-critical path small. The CPU may drain buffers, attach metadata, and emit telemetry, but it should not create event time after the fact.

## Arduino Nano RP2040 Connect Firmware Target

The H0/SW1 Arduino entrypoint targets the Earle Philhower `arduino-pico` core
for the Arduino Nano RP2040 Connect. The Arduino Mbed OS Nano Boards core is not
the target for OTIS timing firmware.

This choice preserves a simple Arduino sketch workflow for early smoke tests
while keeping direct access to RP2040/Pico SDK facilities, `setup1()` /
`loop1()` multicore structure, and PIO tooling for later capture steps.

## Stage 1 Milestones

### Stage 1A — PPS Capture

Capture GNSS PPS edges and emit raw records with monotonically increasing sequence numbers, captured ticks, channel identity, edge type, and capture flags.

### Stage 1B — TCXO / Reference Oscillator Observation

Feed the available TCXO through the buffer into an RP2040 GPIO/PIO path. Count or capture the reference signal against PPS intervals so the host can estimate frequency error, jitter, missing counts, and interval stability.

### Stage 1C — Generic Event Capture

Add at least one application-neutral event input. It should not be hard-coded as a pendulum, TIC channel, or GPSDO signal. Application meaning belongs in the host profile and manifest.

### Stage 1D — Canonical Telemetry

Emit records compatible with `data_contracts/raw_events_v1.csv.md` and the canonical event model in `docs/20_TELEMETRY/canonical_event_model.md`.

### Stage 1E — Host Replay

Record raw serial logs, parsed CSV, and a run manifest sufficient to reconstruct intervals, PPS comparisons, reference oscillator estimates, and capture quality without relying on hidden firmware state.

## Non-Goals

Initial RP2040 implementations are not expected to:

- close a GPSDO loop;
- steer an OCXO or VCXO;
- drive an EFC DAC;
- achieve state-of-the-art phase noise;
- replace dedicated FPGA TDCs;
- provide laboratory-grade metrology;
- hide reference quality inside the MCU clock tree.

The initial focus is architectural correctness, deterministic behavior, explicit provenance, and replayable raw observations.
