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

Stage 1 intentionally treats reference oscillators as observable signals entering
the timing fabric. The RP2040 board clock remains the implementation clock.

Current status: H0 is complete enough, SW0 is healthy, SW1 is complete, SW1.5a
PIO sparse-edge validation is complete enough, and A0 is active/usable. The
evidence run is `runs/h0_sw1_5a_pio/tcxo_observe/run_001`, whose manifest records
commit `4cb0fc8088cbc36eeaa0e52e5c4661b86b738aca` and whose validation output is
`OK raw_events.csv: 141 rows`, `OK count_observations.csv: 141 rows`, and
`OK health.csv: 1128 rows`.

The validated SW1.5a split is:

```text
Sparse event capture -> PIO FIFO path
High-rate oscillator observation -> GPIN0/FC0 gated-count path
```

PIO FIFO is for sparse event observation only: PPS, GPIO loopback, and future
low-rate event edges. Raw TCXO/OCXO input on `D8` / `GPIO20` / `GPIN0` must use
FC0/gated-count style observation, not PIO FIFO edge logging.

### Stage 1A — PPS Capture

Capture GNSS PPS edges and emit canonical raw records.

### Stage 1B — Reference Oscillator Observation

Observe a TCXO, OCXO, GPSDO output, or oscillator under test through the
appropriate count-observation path. For the H0/SW1 and SW1.5a RP2040 work, raw
10 MHz / 16 MHz oscillator input on `D8` / `GPIO20` / `GPIN0` belongs on
FC0/gated-count style observation, not PIO FIFO edge logging.

### Stage 1C — Generic Event Capture

Capture application-neutral timing events.

### Stage 1D — Canonical Telemetry

Emit replayable `raw_events_v1.csv` compatible records plus health/provenance metadata.

### Stage 1E — Host Replay

Reconstruct timing relationships and analysis products from raw artifacts and manifests.

### Stage 1F — Sampled Environmental Telemetry Contract

Define the basic contract for sampled environmental telemetry used as
oscillator/reference provenance. This should preserve the distinction between
timing capture channels and slower contextual measurements.

## Stage 2 — Basic GPSDO / Controlled Oscillator

This software stage depends on prior H1 hardware bring-up. H1 should first prove
manual open-loop oscillator observation and DAC steering limits; Stage 2 should
not be used as a reason to add DAC control-loop firmware before that evidence
exists.

H1 is now in open-loop characterization, while SW2 is not started and is
appropriately deferred. Completed H1 bring-up evidence now includes AD5693R DAC
I2C initialization, conservative `0x7000..0x9000` clamp enforcement, manual
`DAC SET` voltage checks, scripted `SWEEP LOAD` / `SWEEP START` telemetry,
parser extraction of `dac_steps_v1`, and bench-visible built-in sweep profiles
using `0x0400` code steps.

The intended H1 sequence is:

1. Verify OCXO power, current, warmup, and output level.
2. Verify DAC I2C communication and output voltage range. **Complete enough.**
3. Connect OCXO output to `D8` / `GPIO20` / `GPIN0` through the appropriate conditioning path.
4. Capture free-running OCXO count observations via FC0/GPIN0.
5. Manually step DAC output. **Complete enough for unloaded DAC output.**
6. Measure frequency/count response versus DAC setting. **Next: host characterization analysis.**
7. Estimate Hz/V and ppm/V.
8. Characterize settling time and thermal behavior.
9. Only then design SW2 discipline/control-loop firmware.

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
