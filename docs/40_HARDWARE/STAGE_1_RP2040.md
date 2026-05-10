# Stage 1 RP2040 Timing Core

The initial OTIS implementation targets an MCU-first architecture.

## Goals

- deterministic counting;
- GNSS PPS capture;
- external event capture;
- telemetry emission;
- basic discipline experimentation.

## Timing Fabric

The RP2040 PIO subsystem is initially envisioned as the timing fabric.

PIO responsibilities may include:
- reciprocal counting;
- event latching;
- pulse generation;
- counter gating.

## Non-Goals

Initial RP2040 implementations are not expected to:
- achieve state-of-the-art phase noise;
- replace dedicated FPGA TDCs;
- provide laboratory-grade metrology.

The initial focus is architectural correctness and deterministic behavior.
