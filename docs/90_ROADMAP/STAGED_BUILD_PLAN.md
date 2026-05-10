# Staged Build Plan

## Stage 0 — Foundations

Define:
- architecture;
- terminology;
- semantics;
- telemetry philosophy.

## Stage 1 — RP2040 Timing Core

Implement:
- deterministic counter;
- PPS capture;
- event capture;
- telemetry emission.

## Stage 2 — Basic GPSDO

Implement:
- DAC steering;
- discipline loop;
- lock states;
- holdover.

## Stage 3 — Host Appliance

Implement:
- append-only logging;
- replay tooling;
- dashboards;
- analysis reports.

## Stage 4 — Instrument Modes

Add:
- frequency counter mode;
- programmable pulse generation;
- external reference comparison.

## Stage 5 — Advanced Timing Fabric

Potentially introduce:
- FPGA timing engines;
- interpolation techniques;
- advanced phase comparison.

## Stage 6 — Advanced Metrology

Potential future areas:
- environmental modeling;
- phase-noise characterization;
- distributed timing systems.
