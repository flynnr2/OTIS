# H1 Characterization Summary

## Inputs
- run_id: run_001
- run_dir: runs/h1_open_loop/ocxo_free_run/run_001
- nominal_hz: 10000000.000
- settling_discard_s: 0
- warmup_s: 1800.000
- stability_ppm: 0.1
- count_windows: 60000
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
- all_counts: code=unavailable, voltage_v=unavailable, direction=unknown, windows=60000, discarded=0, elapsed_s=0.549206..4294.909, median_hz=10000000.000, mean_hz=9679321.192, stddev_hz=1761328.350, MAD_hz=0, IQR_hz=0, median_ppm=0

## Local Slopes
- unavailable: need at least two populated DAC/code summary points

## Settling Behavior
- step_index=0, code=unavailable->unavailable: baseline_hz=unavailable, final_hz=unavailable, t50_s=unavailable, t90_s=unavailable, t95_s=unavailable, overshoot_percent=unavailable, residual_drift_hz_per_s=unavailable; insufficient data: settling analysis requires DAC transitions and multiple count windows

## Warmup Drift
- samples: 60000
- initial_frequency_hz: 10000000.000
- initial_ppm: 0
- total_elapsed_s: 3557.425
- drift_after_warmup_hz_per_s: 206.879
- drift_after_warmup_ppm_per_hour: 74476.307
- practical_stability_time_s: 3515.425
- note: used samples after 1800 s

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
