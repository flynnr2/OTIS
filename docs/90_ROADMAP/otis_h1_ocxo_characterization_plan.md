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
3. Manually sweep DAC — complete enough for unloaded DAC output and scripted capture
4. Measure FC0 counts vs DAC setting — next host analysis step
5. Derive Hz/V and ppm/V
6. Characterize settling time and thermal behavior
7. Only then design the control loop

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
- Built-in `tiny_plus_minus_1` and `tiny_plus_minus_2` sweeps now use
  bench-visible `0x0400` code steps around midpoint.
- Host parsing extracts `dac_steps_v1` rows, including profile load, dwell
  windows, FC0 attribution, completion, stop, and safety rejection.
- The next prompt/work item is `04_h1_host_characterization_analysis`: correlate
  DAC step telemetry with FC0 count observations and bench voltage notes.

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
unloaded DAC output verification. The remaining work is host-side analysis of
frequency/count response versus DAC setting once the oscillator tune path is
connected under the documented safety limits.

---

# Phase 6 — Derive Hz/V and ppm/V

```text
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

---

# Phase 7 — Settling Time Characterization

Measure:
- 50% settling time
- 90% settling time
- 95% settling time
- practical full settling
- overshoot
- slow thermal drift

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
