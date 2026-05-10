# Staged Build Plan

## Stage 0 — Foundations

Define:
- architecture;
- terminology;
- timing-domain semantics;
- telemetry philosophy;
- provenance expectations;
- replayability expectations.

Stage 0 is substantially established in the current OTIS documentation set.
The next effort is consolidation and implementation alignment rather than large-scale conceptual invention.

## Stage 1 — RP2040 Timing Core

Implement an open-loop RP2040 timing appliance.

Primary goals:
- deterministic capture;
- PPS reference capture;
- observable TCXO/OCXO/reference inputs;
- generic event capture;
- canonical telemetry emission;
- replayable raw artifacts.

Stage 1 intentionally treats reference oscillators as observable signals entering the timing fabric. The RP2040 board clock remains the implementation clock.

### Stage 1A — PPS Capture

Capture GNSS PPS edges and emit canonical raw records.

### Stage 1B — Reference Oscillator Observation

Observe a TCXO, OCXO, GPSDO output, or oscillator under test through the PIO/DMA timing fabric.

### Stage 1C — Generic Event Capture

Capture application-neutral timing events.

### Stage 1D — Canonical Telemetry

Emit replayable `raw_events_v1.csv` compatible records plus health/provenance metadata.

### Stage 1E — Host Replay

Reconstruct timing relationships and analysis products from raw artifacts and manifests.

## Stage 2 — Basic GPSDO / Controlled Oscillator

Implement:
- DAC steering;
- discipline estimation;
- lock states;
- holdover policy;
- explicit control telemetry.

Raw observations remain authoritative scientific artifacts even after discipline/control loops are introduced.

## Stage 3 — Host Appliance

Implement:
- append-only logging;
- replay tooling;
- dashboards;
- analysis reports;
- manifest-driven experiment replay.

## Stage 4 — Instrument Modes

Add:
- frequency counter mode;
- oscillator characterization;
- programmable pulse generation;
- external reference comparison;
- time interval counter workflows.

## Stage 5 — Advanced Timing Fabric

Potentially introduce:
- FPGA timing engines;
- interpolation techniques;
- advanced phase comparison;
- higher-rate capture fabrics.

## Stage 6 — Advanced Metrology

Potential future areas:
- environmental modeling;
- phase-noise characterization;
- distributed timing systems;
- multi-node timing fabrics.
