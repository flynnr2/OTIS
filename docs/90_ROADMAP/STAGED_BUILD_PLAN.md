# Staged Build Plan

Current status (2026-08-21): this long-horizon plan retains historical stage
context; it is not execution authority. CX319 completed its range map and
mapping-informed Part B programme and is frozen. CX320 then physically applied
one firmware-driven, phase-material combined correction, but its exact response
was below the frozen observability floor and failed the positive-sign
checkpoint. CX320 is a bounded non-pass with no remaining live authority. See
`../60_EXPERIMENTS/CX320_ACTIVE_HYBRID_PROGRAMME/12_STAGE5_ATTEMPT9_RESPONSE_OBSERVABILITY_TERMINAL.md`.
CX321 implemented that design, but its two healthy physical pre-estimates
differed by one count and the frozen exact-equality gate correctly made no DAC
application. It is a sealed bounded non-pass. The selected offline CX322
successor uses a one-count pre-envelope gate and a 25-code identification step
before the unchanged 600-second natural hybrid controller. Implementation and
physical authority remain pending. See
`../60_EXPERIMENTS/CX322_PRE_ENVELOPE_ACTIVE_HYBRID_SUCCESSOR/README.md`.

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

The later PPS-gated high-rate measurement path is also qualified for
observe-only use. On 2026-08-01 the
`pio_wait_cumulative_snapshot_dma_v1` evidence campaign was accepted after
clean pseudo-PPS, fault, real-GPS, quiet/load, extended, and sealed overnight
testing. This closes roadmap Stage SW2-3 with a documented 30/31 width-only
fault limitation and physical phase/duty sweep recorded as not tested and
non-blocking. It does not authorize DAC actuation.

The follow-up exact-ELF latency/jitter audit closes speculative capture-path
optimization for this accepted mechanism. Subsequent stages must preserve the
single-PIO-state-machine count/snapshot aperture and its proof-bound
configuration; ISR, DMA, service-plane, and core-placement changes must not
move the boundary back into software or be claimed as raw-count improvements.
The normative checklist is
`docs/50_SOFTWARE/PPS_CAPTURE_LATENCY_JITTER_AUDIT_20260801.md`.

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

H1 open-loop characterization and the SW2-3 PPS-gated measurement-backend gate
are complete enough to proceed to live observe-only estimator/preview
integration. SW2 active actuation is not started and remains appropriately
deferred. Completed H1 bring-up evidence now
includes AD5693R DAC I2C initialization, configurable characterization clamps,
manual `DAC SET` voltage checks, scripted `SWEEP LOAD` /
`SWEEP START` telemetry, parser extraction of `dac_steps_v1`, environmental
telemetry, 300 s long-gate count observations, session-aware host reporting, and
center-bracketed slope analysis.

The latest H1 evidence still does not authorize SW2 DAC actuation, but the
`run_014` blocker is no longer the count-observation conditioning path,
`run_017` provided a clean local-PPS/D10-witness confirmation, and `run_019`
now supplies the broad-range response reference.
`run_010` remains analysis-useful after explicit segment classification but not
fixture-ready. `run_011`, `run_012`, and `run_013` reported post-startup
zero-count faults. The `run_014` investigation isolated the immediate hardware
fault to the SN74LVC1G17 conditioning breakout: pin 2, the input, was shorted to
pin 5, VCC. After the G17 was cleaned and resoldered, direct ECS-TXO,
ECS-TXO-through-G17, and CX317-through-G17 checks all produced nonzero counts.
The clean `run_014` capture then completed 284 300 s count windows with no
zero-count rows, all `CNT` rows flagged `16`, no host capture drops, and no
parser errors.

`run_019` gives the broad plant evidence: one clean 12.89 h session,
155 valid count windows, no host PPS anomalies, D10/D14 final agreement, a
wide-fit slope of `0.000169064 Hz/code` (`R²=0.999920`), and a 10 MHz crossing
near `0xAE00`. Its actual uploaded configuration was the historical
`0x0100..0xFF00`, 900 s profile, not the intended tight crossing profile.
Accordingly, it validates broad monotonic response but not a local control
model. `run_020` completed the focused confirmation and directly brackets
10 MHz near `0xA950`. Phase 3 freezes model version 3 with observe-only
applicability `0xA800..0xB400` and a disabled candidate range
`0xA800..0xAB00`. The pre-SW2 observe-only plant-model gate is complete;
active-control policy remains deliberately separate.

The intended H1 sequence is:

1. Verify OCXO power, current, warmup, and output level.
2. Verify DAC I2C communication and output voltage range. **Complete enough.**
3. Connect OCXO output to `D8` / `GPIO20` / `GPIN0` through the appropriate conditioning path.
4. Capture free-running OCXO count observations via FC0/GPIN0.
5. Manually step DAC output. **Complete enough for unloaded DAC output.**
6. Measure frequency/count response versus DAC setting. **Analysis-useful, not control-authorized.**
7. Estimate Hz/V and ppm/V. **Complete for observe-only from Run 020 local gain.**
8. Characterize settling time and thermal behavior. **A 900 s exclusion is supported; thermal modelling remains unresolved.**
9. Fix or confirm the count-observation power/conditioning path. **Resolved by `run_014`; G17 solder fault found and repaired.**
10. Review timestamp-rollover diagnostics and freeze a conservative H1 plant model. **Complete for observe-only in model version 3.**
11. Only then design any guarded SW2 actuation experiment.

Implement in order:

- observe-only control telemetry;
- manual nominal DAC restore, guarded by clamps;
- discipline estimation without actuation;
- lock-state and holdover labels that do not imply active steering;
- guarded DAC steering only after the SW2 actuation gate reopens.

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
