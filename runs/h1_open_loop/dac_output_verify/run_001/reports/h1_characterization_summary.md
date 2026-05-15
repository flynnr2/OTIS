# H1 Characterization Summary

## Inputs
- run_id: h1_vcocxo_dac_observeonly_001
- run_dir: runs/h1_open_loop/dac_output_verify/run_001
- nominal_hz: 10000000.000
- settling_discard_s: 0
- warmup_s: 1800.000
- stability_ppm: 0.1
- count_windows: 250
- dac_events: 0

## Formulas
- measured_hz = counted_edges / gate_seconds
- ppm = 1e6 * (measured_hz - nominal_hz) / nominal_hz
- Hz/V = delta Hz / delta V
- ppm/V = delta ppm / delta V
- Hz/code and ppm/code are computed when voltage is unavailable.
- settling_discard_s removes initial count windows in each DAC dwell before per-step summary statistics are computed.

## Warnings
- dac_steps.csv unavailable or empty; DAC-code grouping and voltage plots are limited

## DAC Step Summaries
- all_counts: code=unavailable, voltage_v=unavailable, direction=unknown, windows=250, discarded=0, elapsed_s=5.7565..254.757, median_hz=10000000.000, mean_hz=10000019.964, stddev_hz=140.029, MAD_hz=0, IQR_hz=0, median_ppm=0

## Local Slopes
- unavailable: need at least two populated DAC/code summary points

## Settling Behavior
- step_index=0, code=unavailable->unavailable: baseline_hz=unavailable, final_hz=unavailable, t50_s=unavailable, t90_s=unavailable, t95_s=unavailable, overshoot_percent=unavailable, residual_drift_hz_per_s=unavailable; insufficient data: settling analysis requires DAC transitions and multiple count windows

## Warmup Drift
- samples: 250
- initial_frequency_hz: 10000000.000
- initial_ppm: 0
- total_elapsed_s: 249
- drift_after_warmup_hz_per_s: 0.41896
- drift_after_warmup_ppm_per_hour: 150.826
- practical_stability_time_s: 229
- note: used final third because requested warmup window exceeds run duration

## Hysteresis / Sweep Direction
- unavailable: no repeated DAC-code summary points

## Generated Artifacts
- csv/h1_characterization_points.csv
- plots/warmup_drift.png

## SW2 Readiness
- open_loop_slope_known: false
- safe_voltage_window_known: true
- settling_time_characterized: false
- warmup_characterized: true
- recommended_next_action: capture a DAC sweep with repeated count windows at two or more DAC codes
