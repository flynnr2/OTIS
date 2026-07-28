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
8. For the next CX317 slope run, shield the CX317 and nearby steering components
   from airflow. Put the SHT4x inside or immediately adjacent to the shielded
   volume without thermally bonding it to the can, and keep switching regulators
   or other changing heat sources outside that volume where practical.
9. Prefer centre-bracketed `0x0800` and `0x1000` steps for plant-authority
   evidence. `0x0200` and `0x0400` are near the present measurement floor and
   should be treated as diagnostic rather than decisive unless repeatability
   improves.
10. Use locally PPS-calibrated H1 host estimates as the preferred report, with
    the legacy run-wide estimate retained for comparison in
    `csv/h1_count_frequency_estimates.csv`.
11. Enable `OTIS_ENABLE_PPS_DUAL_OBSERVER=1` only for the temporary D10 PPS
    witness experiment. Do not change DAC/CX317 control semantics and do not
    switch to the PPS-gated-ratio backend in the same run unless explicitly
    performing a separate backend A/B validation.

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

For sub-hertz plant work, host reports prefer `LOCAL_PPS_INTERPOLATED` count
estimates when accepted REF/PPS observations bracket both gate boundaries. This
is a derived analysis of existing `CNT` and `REF` evidence; raw count rows remain
authoritative and are not overwritten. Nearby air-temperature regression is
diagnostic only: low explanatory power does not prove airflow or internal CX317
thermal state is irrelevant.

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
affected reference intervals as not control-eligible.

`run_016` is the H1-B retry under the corrected Arduino IDE defaults and the
same FC0/PIO long-gate measurement path. It used DAC clamps `0x7000..0x9000`,
900 s active dwells, and local `0x0200`/`0x0400` excursions around `0x8000`.
The run completed about 12.75 hours with 153 300 s `CNT` windows, no zero-count
rows, no capture drops or error flags, no PPS anomalies across 45,917 valid PPS
intervals, and clean startup/control eligibility. That result validates the
reference/capture path for this topology, but it does not validate the small
local plant gain: repeated center points span about 11.6 Hz and the
center-bracketed small-step slopes are mixed sign. Future plant-authority runs
should use repeated center bracketing with larger safe local steps such as
`0x0800` and `0x1000`, while preserving the same raw `CNT`, `REF`, `STS`, `DAC`,
and environmental telemetry.

PIO long-gate and PPS-gated ratio backends provide different count-window
formation, but they still emit raw `CNT` rows rather than calibrated frequency.
Do not claim ppm/V, settling-time, or control-readiness from a run unless count
validity, reference validity, and DAC attribution are all separately clean or
explicitly qualified. The first PPS interval after startup may appear as an
approximately 32M-tick interval; for these H1 bench captures it is treated as a
startup artifact when subsequent PPS intervals return to approximately 16M
ticks.

For every H1 run with `csv/ref.csv`, the host characterization report should
prefer local PPS interpolation when accepted PPS observations bracket both count
gate boundaries. The retained run-wide RP2040 tick-rate estimate is a labelled
fallback and diagnostic comparison, not the preferred sub-hertz H1 estimator.
`run_009` showed the RP2040 timer about 4.65 ppm slow against PPS, with roughly
1.6 us single-interval PPS scatter, so uncalibrated count-derived frequencies
were biased high by the same order.

The regenerated `run_017` report is the current H1 measurement-confidence
baseline. It reports 242 count windows, 241 locally PPS-interpolated estimates,
one startup-edge run-wide fallback, no host-classified PPS anomalies after
timestamp unwrapping, no reconnects or reboot/header markers, and
`fc0_valid_for_control=true`. The D10 PPS witness matched D14 one-for-one at
the end of the run, with no D10 short, overflow, or burst rows. The historical
D14 `rejected_long_count=16` matched the 16 RP2040 timer rollovers and is a raw
firmware diagnostic artefact, not a host-unwrapped PPS anomaly; firmware
diagnostics now use modular timer interval arithmetic for future rollover
crossings.

`run_017` was a direct host-command DAC sequence, so `csv/dac_steps.csv` was
reconstructed from captured DAC acknowledgement `STS` rows and the host
sequence log after the raw capture completed. Raw `serial.log` was not modified.
Future direct-command sweeps should emit explicit host DAC event rows during
capture or retain the same reconstruction provenance.

`csv/evt.csv` can be header-only for this H1 topology because CH0 generic event
capture is unused. Do not read that file as proof of zero arbitrary events; PPS
observations are in `csv/ref.csv`, and the temporary D10 witness is `STS`
diagnostic telemetry.

The observed settled CX317 outputs over the tested range were:

| DAC code | Observed output |
|---:|---:|
| `0x7000` | 9.999997327 MHz |
| `0x7800` | 9.999997642 MHz |
| `0x8000` | about 9.99999798 MHz |
| `0x8800` | 9.999998334 MHz |
| `0x9000` | 9.999998711 MHz |

The full `0x7000..0x9000` span moved the CX317 by about 1.384 Hz. The
centre-bracketed local slopes across `0x0800` and `0x1000` steps were about
4.15..4.67 Hz/V, positive. For the CX317 10 MHz datasheet tuning range of
roughly +/-0.5 ppm to +/-1.0 ppm over 0.0 V..3.3 V, the implied whole-range
slope is about 3.0..6.1 Hz/V, so the observed narrow-range slope is consistent
with the part. The tested `Vc` span of about 1.091 V..1.401 V remains below the
1.65 V nominal control point and should be treated as lower-midrange evidence,
not full-range linearity proof.

`run_017` environmental analysis remains diagnostic. The SHT4x near-VCOCXO
temperature spanned about 25.43 C to 29.53 C, and post-warmup drift was about
-0.00023 ppm/hour after the configured warmup window. Do not treat low
simple-regression explanatory power as proof that airflow, thermal gradients, or
CX317 internal oven state are irrelevant.

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
