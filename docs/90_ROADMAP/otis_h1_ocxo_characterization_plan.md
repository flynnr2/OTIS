# OTIS H1 — OCXO / DAC Open-Loop Characterization Plan

## Purpose

This phase is explicitly **open-loop characterization**, not GPSDO control-loop implementation.

The objective is to empirically derive:

```text
DAC code
→ DAC output voltage
→ OCXO tune voltage
→ OCXO frequency shift
→ FC0 measurement response
```

Only after these relationships are characterized should SW2 closed-loop steering be designed.

---

# Guiding Principles

## Do Not Prematurely Implement the Control Loop

Avoid introducing:

- PI/PID control
- automatic steering
- adaptive filtering
- holdover logic
- Kalman/filter experimentation
- discipline state machines

until the hardware transfer characteristics are measured.

The immediate goal is:

```text
Understand the plant before designing the controller.
```

---

# High-Level Phase Sequence

1. Verify OCXO power/current/warmup
2. Verify DAC I²C + output voltage
3. Manually sweep DAC — complete enough for connected scripted capture
4. Measure count observations vs DAC setting — analysis-useful with 300 s long gates
5. Derive Hz/V and ppm/V — present in reports, not yet control-authorized
6. Characterize settling time and thermal behavior — present in reports, not yet loop constants
7. Restore clean post-inhibit count validity under the revised power/conditioning path — complete in `run_014`
8. Resolve or explicitly gate PPS/reference cadence anomalies
9. Only then design any guarded control-loop actuation experiment

---

# Suggested Run Directory Structure

```text
runs/h1_open_loop/
  ocxo_power_warmup/run_001/
  dac_output_verify/run_001/
  dac_manual_sweep/run_001/
  fc0_vs_dac/run_001/
  settling_thermal/run_001/
```

Each run should contain:

```text
serial_raw.log
count_observations.csv
health.csv
run_manifest.json
notes.md
reports/summary.md
plots/
```

Current H1 DAC sweep status:

- AD5693R I2C initialization and manual `DAC SET` movement have been verified.
- Conservative clamps are configured at `0x7000..0x9000`.
- Built-in tiny sweeps use bench-visible `0x0400` code steps around midpoint.
- Long-gate slope profiles use 300 s raw-edge count windows and 900 s DAC
  dwells for repeated center-bracketed analysis.
- Host parsing extracts `dac_steps_v1` rows, including profile load, dwell
  windows, FC0 attribution, completion, stop, and safety rejection.
- Host characterization now produces PPS-calibrated frequency estimates,
  center-bracketed slopes, settling estimates, warmup drift, near-VCOCXO
  temperature summaries, PPS anomaly tables, startup control eligibility, and
  FC0 bad-window diagnostics.
- `run_010` is analysis-useful after explicit session/anomaly classification,
  but it is not fixture-ready.
- `run_011`, `run_012`, and `run_013` show that post-inhibit zero-count faults
  can occur under the faulted bench configuration.
- `run_014` isolated that fault to a SN74LVC1G17 breakout solder issue: pin 2
  was shorted to pin 5. After rework, direct ECS-TXO, ECS-TXO-through-G17, and
  CX317-through-G17 checks counted correctly.
- The clean `run_014` capture completed with 284 300 s count windows, zero
  zero-count rows, all `CNT` rows flagged `16`, no host capture drops, 18 sweep
  passes, `fc0_valid_for_control: true`, and usable slope, settling, warmup and
  thermal analysis.
- The next bench decision is no longer count-path repair; it is PPS/reference
  anomaly review and conservative plant-model freeze before any guarded SW2
  actuation experiment.

---

# Bench Logging Template

Maintain a structured bench log with at least:

```text
time
DAC code
DAC measured voltage
OCXO tune voltage
OCXO supply voltage
OCXO current draw
FC0 count
computed frequency
ppm from nominal
temperature / thermal notes
comments
```

When I2C environmental telemetry is enabled, prefer SHT4x as the
near-VCOCXO temperature source (`source=sht4x`, `role=vcocxo_near`). BMP280
temperature should be treated as secondary context; its pressure reading remains
useful for longer bench/environment correlation.

---

# Phase 1 — OCXO Power / Current / Warmup

Verify:
- power behavior
- current draw
- warmup behavior
- output existence
- safe thermal operation

---

# Phase 2 — DAC I²C and Voltage Verification

Verify:
- I²C communication
- DAC monotonicity
- actual voltage output range
- predictable operation

Status: complete enough for the AD5693R breakout in unloaded bench testing.

---

# Phase 3 — Safe DAC-to-OCXO Tune Integration

Recommended chain:

```text
DAC → RC low-pass → optional buffer → OCXO tune input
```

---

# Phase 4 — FC0 Measurement Path Verification

Recommended measurement chain:

```text
OCXO output
→ conditioning/buffer
→ RP2040 GPIN0 / FC0
```

---

# Phase 5 — Manual DAC Sweep

Suggested dwell:
- 2–5 minutes per point

Remain close to nominal tune voltage initially.

Status: built-in scripted sweeps and manual DAC steps are complete enough for
connected open-loop characterization. The remaining work is not basic host-side
correlation; it is proving that the count-observation path remains clean after
startup inhibit under the revised power/conditioning setup.

---

# Phase 6 — Derive Hz/V and ppm/V

```text
rp2040_tick_rate_hz = mean(valid REF/PPS interval ticks)
gate_seconds = FC0_gate_ticks / rp2040_tick_rate_hz
measured_hz = FC0_count / gate_seconds
```

```text
ppm = 1e6 * (measured_hz - nominal_hz) / nominal_hz
```

Compute local slopes:

```text
Hz/V  = ΔHz / ΔV
ppm/V = Δppm / ΔV
```

When REF/PPS rows are present, H1 analysis must use the PPS-calibrated
`rp2040_timer0` rate for FC0 gate duration. The nominal 16 MHz RP2040 value is
only a fallback for missing or unusable PPS evidence. The calibrated rate is a
derived correction for legacy H1 count windows; it is not a license to treat the
RP2040 board clock as the future event-stamping timebase.

Current status: slope estimates exist in `run_009` through `run_014`, including
center-bracketed slope tables. `run_014` provides the first clean repaired-path
evidence: 35 center-bracketed slope rows with a positive median slope of about
4.30 Hz/V. Treat this as plant-model input, not a firmware constant, until the
valid voltage neighbourhood, uncertainty, noise floor, settling cadence, and
PPS/reference validity policy are recorded in a versioned model.

---

# Phase 7 — Settling Time Characterization

Measure:
- 50% settling time
- 90% settling time
- 95% settling time
- practical full settling
- overshoot
- slow thermal drift

Current status: settling estimates exist in the H1 characterization summaries.
Earlier runs include invalid count windows and pathological excursions; `run_014`
provides clean repaired-path settling evidence, but it is still an analysis
result rather than a selected SW2 loop cadence.

---

# Phase 8 — Thermal and Warmup Characterization

Suggested duration:
- minimum: 1–2 hours
- preferred: 4+ hours

Outputs:
- warmup profile
- stabilization time
- post-warmup drift
- frequency vs time

Current status: environmental telemetry is present in recent H1 runs, with
SHT4x near-VCOCXO samples preferred for thermal context. `run_014` captured a
24-hour-class repaired-path run with SHT4x near-VCOCXO temperature from about
23.30 C to 27.83 C and post-warmup drift around -0.0417 ppm/hour. Thermal
behavior should still influence SW2 only through an explicit model or gate, not
ad hoc firmware constants.

---

# Phase 9 — Only Then Design SW2 Control Loop

Define:
- loop cadence
- bandwidth
- DAC step quantization
- startup holdoff
- lock criteria
- voltage clamps
- anti-windup behavior
- thermal gating
- holdover strategy

---

# Expected Future SW2 Shape

```text
startup:
  fixed nominal DAC
  observe only

warmup:
  no steering

acquire:
  slow coarse correction

discipline:
  very slow PI or I-only control

safety:
  clamp DAC range
```

---

# Fast-Execution Bring-Up Sequence

1. OCXO power only
2. DAC output only
3. OCXO output into FC0 path
4. Free-run capture
5. DAC connected at nominal tune voltage
6. Tiny ± tuning steps
7. Settling characterization
8. Cold/warmup characterization

---

# Final Reminder

```text
No closed-loop control until the open-loop transfer function is measured.
```
