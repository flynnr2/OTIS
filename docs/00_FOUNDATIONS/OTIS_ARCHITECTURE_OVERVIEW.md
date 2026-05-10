# OTIS Architecture Overview

OTIS is organized into several conceptual layers.

## Reference Layer

Responsible for:
- GNSS reference acquisition;
- disciplined oscillator generation;
- DAC steering;
- reference output generation.

Example implementations:
- OCXO;
- VCXO;
- GNSS timing receivers.

## Timing Fabric Layer

Responsible for:
- deterministic counting;
- event capture;
- phase comparison;
- pulse generation.

This layer defines timing truth.

Potential implementations:
- RP2040 PIO;
- FPGA;
- CPLD.

## Control Layer

Responsible for:
- discipline algorithms;
- telemetry generation;
- state management;
- DAC control.

The control layer must not define timestamps.

## Host Layer

Responsible for:
- logging;
- dashboards;
- replay tooling;
- analytics;
- APIs.

Linux hosts are first-class but optional.

## Guiding Principle

All timing events should ultimately be expressed relative to a disciplined
reference domain.
