# H1 OCXO/DAC Characterization Runbook

H1 is open-loop bench characterization of the OCXO, DAC, control path, and
observation path. It is not SW2, and it must not enable automatic DAC steering,
PI/PID control, holdover, or closed-loop GPSDO behavior.

## Bench Preconditions

- Use observation-only firmware with the existing OTIS capture semantics.
- Confirm the oscillator pinout from a datasheet, module marking source, or
  measured continuity notes before power is applied.
- Set bench-supply voltage and current limits before connecting the OCXO.
- Keep the DAC output disconnected from the OCXO tune input until the DAC output
  range and safe tune range are both documented.
- Record unknown values as explicit nulls or empty fields in the run manifest;
  do not infer safety from missing data.

## 1. OCXO Power, Current, And Warm-Up

1. Verify each power rail unloaded.
2. Set current limits for first power-up.
3. Power the OCXO and record initial current, warm current, supply voltage, and
   qualitative thermal behavior.
4. Confirm the oscillator output exists at the measurement point before routing
   it toward OTIS.
5. Initialize a run from `ocxo_power_warmup/_template` and record warm-up notes.

## 2. DAC I2C And Voltage Verification

1. Verify DAC supply and reference voltage.
2. Confirm the AD5693R appears at I2C address `0x4C`.
3. Measure DAC output at minimum, midpoint, and maximum intended codes while
   unloaded.
4. Record gain mode, reference voltage, measured output minimum, and measured
   output maximum.
5. Stop if the measured output can exceed the intended OCXO tune range.

## 3. Safe DAC-To-OCXO Tune Connection

1. Define `dac_min_code`, `dac_max_code`, `control_voltage_min_v`, and
   `control_voltage_max_v` before connection.
2. Add any required divider, resistor isolation, RC filter, clamp, or buffer.
3. Connect the DAC to the OCXO tune input only after the connected control
   voltage is measured inside the safe range.
4. Record the control network and measured control voltage in the manifest.

## 4. OCXO Output Conditioning Into Count Observation

1. Do not connect raw sine, high-voltage logic, or unknown oscillator outputs to
   the RP2040.
2. Use a divider, comparator, squarer, clock buffer, or other documented
   conditioner to produce RP2040-safe logic.
3. Verify logic high/low levels before connecting `D8/GPIO20/GPIN0`.
4. Record conditioner type, logic voltage, inversion, division ratio, and the
   observed domain name.
5. Record the selected count-observation backend:
   `FC0_GPIN0`, `GPIO_IRQ` divided-only, `PIO_LONG_GATE`, or
   `PPS_GATED_RATIO`.
6. For SN74LVC1G17 SOT-23-5 breakout wiring, verify the actual package pinout
   before soldering or probing. The common pinout used in the H1 bench is
   `1=NC`, `2=A input`, `3=GND`, `4=Y output`, `5=VCC`. With the board removed
   and unpowered, check that pin 2 is not shorted to pin 5; the `run_014`
   zero-count fault was traced to that exact solder short.
7. Before trusting a CX317 count fault, perform a narrow count-path smoke test
   with a known clock source: direct ECS-TXO-to-D8, then ECS-TXO-through-G17,
   then CX317-through-G17. A clean 16 MHz ECS-TXO path should produce nonzero
   `CNT` rows near the expected count for the selected gate.

Raw oscillator observation belongs in `CNT` rows. Do not feed raw OCXO edges
into the sparse `EVT`/`REF` capture path.

## 5. Free-Run Capture

1. Allow the OCXO to warm up for the recorded duration.
2. Keep the tune voltage fixed or disconnected, and record which state is used.
3. Initialize an `ocxo_free_run` run and capture count/reference observations.
4. Report frequency offset, missing reference data, dropouts, and anomalies.

For PPS-gated ratio validation, also record:

- PPS source and conditioning into `D14` / GPIO26 / `CH1`;
- oscillator conditioner into `D8` / GPIO20 / `CH2`;
- `pps_gate/backend`, `state`, `valid`, and `ratio_available` status;
- `pps_gate/missing_pps_count`;
- `pps_gate/pps_interval_anomaly_count`;
- `pps_gate/count_saturated_count`;
- whether every accepted PPS-gated `CNT` window has matching visible `REF`
  evidence in the same run.

Treat the first PPS-gated bench run as hardware validation, not as a calibration
authority. It must prove PPS edge ownership, gate start/stop latency,
missing-PPS timeout behavior, and counter saturation behavior before the backend
is marked hardware-clean.

## 6. Manual DAC Sweep

1. Use only the documented safe DAC code range.
2. Compile sweep-capable firmware only when `OTIS_ENABLE_H1_DAC_SWEEP` is set,
   and confirm `SWEEP?` reports the intended profile before starting.
3. Prefer built-in conservative profiles first: `center_only`,
   `tiny_plus_minus_1`, then `tiny_plus_minus_2`.
   The built-in "tiny" profiles use small bench-visible code steps
   (`0x0400` by default), not one raw DAC LSB.
4. Start sweeps explicitly with `SWEEP START`; firmware must not auto-start a
   sweep on boot.
5. Stop with `SWEEP STOP` immediately if the output disappears, clips, or
   approaches a safety limit.
6. For each step, record DAC code, measured DAC output, measured control voltage,
   timestamp, observed frequency estimate, and near-VCOCXO temperature.
7. If SHT4x environmental telemetry is enabled, mount it near the VCOCXO can or
   control-node area and treat `source=sht4x, role=vcocxo_near` as the primary
   thermal proxy. BMP280 temperature is secondary pressure-reference context.

Suggested run layout for scripted sweeps:

```text
runs/h1_open_loop/dac_manual_sweep/run_001/
  run_manifest.json
  raw/serial.log
  csv/cnt.csv
  csv/dac_steps.csv
  csv/environment.csv
  csv/sts.csv
  reports/summary.md
  reports/h1_characterization_summary.md
  plots/
  notes.md
```

Host tools preserve the legacy root-level files above. Session diagnostics are
derived from `raw/serial.log` host markers, firmware BOOT/HDR markers, and CSV
sequence restarts. A continuous capture reports one session. A USB reconnect,
BOOT/HDR marker after data has started, or sequence rollback/restart creates a
new session in reports so pre-reconnect fragments are not silently merged with
the main run.

Every `CNT` row captured during a sweep should be attributable through nearby
`DAC` rows in `csv/dac_steps.csv`, especially `dwell_start`, `fc0_window`, and
`dwell_complete` events. The `fc0_window` event name is historical; it means a
count-observation window, not necessarily the FC0/GPIN0 backend.
When `csv/environment.csv` is present, H1 analysis correlates near-VCOCXO
temperature with DAC dwell summaries and ppm/frequency observations, but does
not apply automatic thermal correction.

H1 characterization uses `--settling-discard-s` to remove early count windows
after each DAC dwell starts. The default is 60 s and the minimum is 0 s. Use
0 s only for short bench smoke tests or fixtures where there are no long dwells.
For real characterization, prefer longer dwell durations and multiple count
windows per step: faster sweeps reduce bench time, but longer dwells reduce
measurement noise and make thermal settling visible. Per-step reports include
used/discarded windows, dwell timing when emitted by firmware, near-VCOCXO
temperature span, and PPS anomaly overlap.

If a PPS/reference anomaly overlaps a DAC step, the raw data is preserved and
the step is marked `quality=degraded`. Degraded steps are not used as normal
inputs for local or center-bracketed slope estimates.

PPS interval classes used by host diagnostics are:

| Class | Meaning |
|---|---|
| `normal_interval` | Interval is within the nominal 0.8..1.2 s acceptance band. |
| `short_interval` | Interval is below the acceptance band. |
| `long_interval` | Interval is above the acceptance band but not close to an integer number of PPS periods. |
| `likely_missed_1_pps` | Interval is close to 2 nominal PPS periods. |
| `likely_missed_n_pps` | Interval is close to N+1 nominal PPS periods. |
| `impossible_interval` | Interval is zero or negative after unwrapping. |
| `unknown` | The capture domain has no usable nominal rate. |

Current telemetry cannot by itself distinguish a missing GNSS PPS edge from a
GPIO, capture hardware, IRQ/FIFO/DMA, or firmware-path missed edge. When those
counters exist, include raw PPS interval, expected interval, interval error,
classification, ignored interval counts, consecutive ignored counts, sequence
number, timestamp, lock state, ISR/capture latency metrics, overflow counters,
FIFO/DMA status, and existing error counters in status or fault telemetry.

## 7. ppm/V Derivation

1. Use measured control voltage at the OCXO tune input, not only requested DAC
   code.
2. Derive Hz/V from settled frequency observations over the local sweep range.
3. Convert to ppm/V using the measured or nominal oscillator frequency.
4. Record the valid voltage interval and do not assume the slope applies outside
   that interval.

## 8. Settling And Thermal Runs

1. Use `settling_thermal` runs for long dwell, step-settling, warm-up, or
   deliberate thermal observations.
2. Record ambient notes, airflow changes, enclosure state, power changes, and
   manual DAC events with timestamps.
3. Prefer SHT4x near the VCOCXO for temperature correlation. Use BMP280 pressure
   as bench/environment context and as a secondary temperature sanity check.
4. Keep the run open-loop: frequency is observed and documented, not corrected
   automatically.

## Current CX317 / AD5693R Bench Status

The first connected CX317 VCOCXO and AD5693R H1 runs are preserved under:

```text
runs/h1_open_loop/dac_output_verify/run_001
runs/h1_open_loop/dac_manual_sweep/run_006
```

Observed unloaded and connected control-voltage measurements at the CX317 pin 4
`Vc` node are consistent with the configured DAC clamp range:

| DAC code | Connected CX317 `Vc` |
|---:|---:|
| `0x7000` | 1.091 V |
| `0x8000` | 1.246 V |
| `0x9000` | 1.401 V |

These values are inside the CX317 operating control-voltage range of 0.0 V to
3.3 V. The connected `Vc` node tracked DAC commands repeatably, and `CNT`,
`REF`, `STS`, and `DAC` telemetry remained present during sweep operation.

The repaired `run_014` topology supersedes the earlier zero-count diagnostic
state. The failed `run_011` through `run_013` count windows were real bench
faults, but the immediate cause was a G17 breakout solder short, not host
parsing or FC0 analysis. After G17 rework, `run_014` completed 284 300 s count
windows with no zero-count rows, all `CNT` rows flagged `16`, no capture drops,
and 18 completed DAC sweep passes. It provides clean repaired-path evidence for
local slope, settling, warmup and thermal analysis.

That evidence is still not permission for automatic steering. `run_014`
validation reports 2719 short PPS/reference intervals, mostly early in the run.
Host characterization ignores out-of-band PPS intervals when calibrating the
RP2040 tick rate, but current telemetry cannot assign root cause to the
reference source versus GPIO/capture/IRQ/FIFO/DMA/firmware handling. Treat
affected reference intervals as not control-eligible until the reference path is
validated or explicitly gated.

PIO long-gate and PPS-gated ratio backends provide different count-window
formation, but they still emit raw `CNT` rows rather than calibrated frequency.
Do not claim ppm/V, settling-time, or control-readiness from a run unless count
validity, reference validity, and DAC attribution are all separately clean or
explicitly qualified. The first PPS interval after startup may appear as an
approximately 32M-tick interval; for these H1 bench captures it is treated as a
startup artifact when subsequent PPS intervals return to approximately 16M
ticks.

For every H1 run with `csv/ref.csv`, the host characterization report should
estimate the RP2040 `rp2040_timer0` tick rate from sane PPS intervals and use
that calibrated rate when converting FC0 gate ticks to seconds. This corrects
the measurement timebase without treating the RP2040 clock as timing truth.
`run_009` showed the RP2040 timer about 4.65 ppm slow against PPS, with roughly
1.6 us single-interval PPS scatter, so uncalibrated count-derived frequencies
were biased high by the same order.

For PPS-gated ratio runs, host analysis should derive ratio/frequency from the
visible `REF` and `CNT` streams plus manifest metadata. Firmware status
`pps_gate/ratio_available=true` means the latest bounded count window is valid
and nonzero; it is not a numeric ratio field.

During `run_009`, the rig was covered by a cardboard box with small cable gaps
at the bottom. Treat that as an airflow shield, not a temperature chamber: it
reduces direct drafts around the VCOCXO but does not remove thermal drift or
bench-environment coupling.

## Closeout

- Commit representative run artifacts only after validation and summary reports
  have been generated.
- Keep large raw logs and plots only when they explain behavior that cannot be
  reconstructed.
- Record unsafe regions and unresolved hardware questions in `notes.md`.
- Do not add closed-loop control concepts, firmware steering, PI/PID state, or
  holdover behavior as part of H1 characterization.
