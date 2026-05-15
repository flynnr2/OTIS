# H1 Characterization Summary

## Inputs
- run_id: h1_vcocxo_dac_sweep_006
- run_dir: runs/h1_open_loop/dac_manual_sweep/run_006
- nominal_hz: 10000000.000
- settling_discard_s: 0
- warmup_s: 1800.000
- stability_ppm: 0.1
- count_windows: 758
- dac_events: 165

## Formulas
- measured_hz = counted_edges / gate_seconds
- ppm = 1e6 * (measured_hz - nominal_hz) / nominal_hz
- Hz/V = delta Hz / delta V
- ppm/V = delta ppm / delta V
- Hz/code and ppm/code are computed when voltage is unavailable.
- settling_discard_s removes initial count windows in each DAC dwell before per-step summary statistics are computed.

## DAC Step Summaries
- step_0_5: code=32768, voltage_v=unavailable, direction=unknown, windows=5, discarded=0, elapsed_s=340.518..344.518, median_hz=10000000.000, mean_hz=10000000.000, stddev_hz=0, MAD_hz=0, IQR_hz=0, median_ppm=0
- step_1_13: code=33792, voltage_v=unavailable, direction=up, windows=5, discarded=0, elapsed_s=345.518..349.518, median_hz=10000000.000, mean_hz=10000000.000, stddev_hz=0, MAD_hz=0, IQR_hz=0, median_ppm=0
- step_2_21: code=32768, voltage_v=unavailable, direction=down, windows=5, discarded=0, elapsed_s=350.518..354.518, median_hz=10000000.000, mean_hz=10000000.000, stddev_hz=0, MAD_hz=0, IQR_hz=0, median_ppm=0
- step_3_29: code=31744, voltage_v=unavailable, direction=down, windows=5, discarded=0, elapsed_s=355.518..359.518, median_hz=10000000.000, mean_hz=10000000.000, stddev_hz=0, MAD_hz=0, IQR_hz=0, median_ppm=0
- step_4_37: code=32768, voltage_v=unavailable, direction=up, windows=305, discarded=0, elapsed_s=360.518..664.518, median_hz=10000000.000, mean_hz=10000045.833, stddev_hz=209.302, MAD_hz=0, IQR_hz=0, median_ppm=0
- step_0_50: code=32768, voltage_v=unavailable, direction=repeat, windows=5, discarded=0, elapsed_s=665.518..669.518, median_hz=10000000.000, mean_hz=10000000.000, stddev_hz=0, MAD_hz=0, IQR_hz=0, median_ppm=0
- step_1_58: code=33792, voltage_v=unavailable, direction=up, windows=5, discarded=0, elapsed_s=670.518..674.518, median_hz=10000000.000, mean_hz=10000000.000, stddev_hz=0, MAD_hz=0, IQR_hz=0, median_ppm=0
- step_2_66: code=32768, voltage_v=unavailable, direction=down, windows=5, discarded=0, elapsed_s=675.518..679.518, median_hz=10000000.000, mean_hz=10000199.601, stddev_hz=446.321, MAD_hz=0, IQR_hz=0, median_ppm=0
- step_3_74: code=31744, voltage_v=unavailable, direction=down, windows=5, discarded=0, elapsed_s=680.518..684.518, median_hz=10000000.000, mean_hz=10000000.000, stddev_hz=0, MAD_hz=0, IQR_hz=0, median_ppm=0
- step_4_82: code=32768, voltage_v=unavailable, direction=up, windows=23, discarded=0, elapsed_s=685.518..707.518, median_hz=10000000.000, mean_hz=10000130.218, stddev_hz=343.777, MAD_hz=0, IQR_hz=0, median_ppm=0
- step_0_94: code=32768, voltage_v=unavailable, direction=repeat, windows=5, discarded=0, elapsed_s=708.518..712.518, median_hz=10000000.000, mean_hz=10000000.000, stddev_hz=0, MAD_hz=0, IQR_hz=0, median_ppm=0
- step_1_102: code=33792, voltage_v=unavailable, direction=up, windows=5, discarded=0, elapsed_s=713.518..717.518, median_hz=10000000.000, mean_hz=10000199.601, stddev_hz=446.321, MAD_hz=0, IQR_hz=0, median_ppm=0
- step_2_110: code=32768, voltage_v=unavailable, direction=down, windows=5, discarded=0, elapsed_s=718.518..722.518, median_hz=10000000.000, mean_hz=10000000.000, stddev_hz=0, MAD_hz=0, IQR_hz=0, median_ppm=0
- step_3_118: code=31744, voltage_v=unavailable, direction=down, windows=5, discarded=0, elapsed_s=723.518..727.518, median_hz=10000000.000, mean_hz=10000000.000, stddev_hz=0, MAD_hz=0, IQR_hz=0, median_ppm=0
- step_4_126: code=32768, voltage_v=unavailable, direction=up, windows=5, discarded=0, elapsed_s=728.518..732.518, median_hz=10000000.000, mean_hz=10000000.000, stddev_hz=0, MAD_hz=0, IQR_hz=0, median_ppm=0
- step_5_134: code=34816, voltage_v=unavailable, direction=up, windows=5, discarded=0, elapsed_s=733.518..737.518, median_hz=10000000.000, mean_hz=10000000.000, stddev_hz=0, MAD_hz=0, IQR_hz=0, median_ppm=0
- step_6_142: code=32768, voltage_v=unavailable, direction=down, windows=5, discarded=0, elapsed_s=738.518..742.518, median_hz=10000000.000, mean_hz=10000000.000, stddev_hz=0, MAD_hz=0, IQR_hz=0, median_ppm=0
- step_7_150: code=30720, voltage_v=unavailable, direction=down, windows=5, discarded=0, elapsed_s=743.518..747.518, median_hz=10000000.000, mean_hz=10000000.000, stddev_hz=0, MAD_hz=0, IQR_hz=0, median_ppm=0
- step_8_158: code=32768, voltage_v=unavailable, direction=up, windows=11, discarded=0, elapsed_s=748.518..758.518, median_hz=10000000.000, mean_hz=10000090.728, stddev_hz=300.91, MAD_hz=0, IQR_hz=0, median_ppm=0

## Local Slopes
- 32768 -> 33792: Hz/V=unavailable, ppm/V=unavailable, Hz/code=0, ppm/code=0
- 33792 -> 32768: Hz/V=unavailable, ppm/V=unavailable, Hz/code=0, ppm/code=0
- 32768 -> 31744: Hz/V=unavailable, ppm/V=unavailable, Hz/code=0, ppm/code=0
- 31744 -> 32768: Hz/V=unavailable, ppm/V=unavailable, Hz/code=0, ppm/code=0
- 32768 -> 33792: Hz/V=unavailable, ppm/V=unavailable, Hz/code=0, ppm/code=0
- 33792 -> 32768: Hz/V=unavailable, ppm/V=unavailable, Hz/code=0, ppm/code=0
- 32768 -> 31744: Hz/V=unavailable, ppm/V=unavailable, Hz/code=0, ppm/code=0
- 31744 -> 32768: Hz/V=unavailable, ppm/V=unavailable, Hz/code=0, ppm/code=0
- 32768 -> 33792: Hz/V=unavailable, ppm/V=unavailable, Hz/code=0, ppm/code=0
- 33792 -> 32768: Hz/V=unavailable, ppm/V=unavailable, Hz/code=0, ppm/code=0
- 32768 -> 31744: Hz/V=unavailable, ppm/V=unavailable, Hz/code=0, ppm/code=0
- 31744 -> 32768: Hz/V=unavailable, ppm/V=unavailable, Hz/code=0, ppm/code=0
- 32768 -> 34816: Hz/V=unavailable, ppm/V=unavailable, Hz/code=0, ppm/code=0
- 34816 -> 32768: Hz/V=unavailable, ppm/V=unavailable, Hz/code=0, ppm/code=0
- 32768 -> 30720: Hz/V=unavailable, ppm/V=unavailable, Hz/code=0, ppm/code=0
- 30720 -> 32768: Hz/V=unavailable, ppm/V=unavailable, Hz/code=0, ppm/code=0

## Settling Behavior
- step_index=1, code=32768->33792: baseline_hz=10000000.000, final_hz=10000000.000, t50_s=0.292506, t90_s=0.292506, t95_s=0.292506, overshoot_percent=unavailable, residual_drift_hz_per_s=0; insufficient response amplitude
- step_index=2, code=33792->32768: baseline_hz=10000000.000, final_hz=10000000.000, t50_s=0.292502, t90_s=0.292502, t95_s=0.292502, overshoot_percent=unavailable, residual_drift_hz_per_s=0; insufficient response amplitude
- step_index=3, code=32768->31744: baseline_hz=10000000.000, final_hz=10000000.000, t50_s=0.292501, t90_s=0.292501, t95_s=0.292501, overshoot_percent=unavailable, residual_drift_hz_per_s=0; insufficient response amplitude
- step_index=4, code=31744->32768: baseline_hz=10000000.000, final_hz=10000000.000, t50_s=0.292505, t90_s=0.292505, t95_s=0.292505, overshoot_percent=unavailable, residual_drift_hz_per_s=-0.488191; insufficient response amplitude
- step_index=0, code=32768->32768: baseline_hz=10000000.000, final_hz=10000000.000, t50_s=0.122505, t90_s=0.122505, t95_s=0.122505, overshoot_percent=unavailable, residual_drift_hz_per_s=0; insufficient response amplitude
- step_index=1, code=32768->33792: baseline_hz=10000000.000, final_hz=10000000.000, t50_s=0.122507, t90_s=0.122507, t95_s=0.122507, overshoot_percent=unavailable, residual_drift_hz_per_s=0; insufficient response amplitude
- step_index=2, code=33792->32768: baseline_hz=10000000.000, final_hz=10000499.002, t50_s=4.1225, t90_s=4.1225, t95_s=4.1225, overshoot_percent=100, residual_drift_hz_per_s=998.006; estimated from median before-step baseline and last-half after-step final value
- step_index=3, code=32768->31744: baseline_hz=10000499.002, final_hz=10000000.000, t50_s=0.122505, t90_s=0.122505, t95_s=0.122505, overshoot_percent=0, residual_drift_hz_per_s=0; estimated from median before-step baseline and last-half after-step final value
- step_index=4, code=31744->32768: baseline_hz=10000000.000, final_hz=10000000.000, t50_s=0.122506, t90_s=0.122506, t95_s=0.122506, overshoot_percent=unavailable, residual_drift_hz_per_s=0; insufficient response amplitude
- step_index=0, code=32768->32768: baseline_hz=10000000.000, final_hz=10000000.000, t50_s=0.948505, t90_s=0.948505, t95_s=0.948505, overshoot_percent=unavailable, residual_drift_hz_per_s=0; insufficient response amplitude
- step_index=1, code=32768->33792: baseline_hz=10000000.000, final_hz=10000000.000, t50_s=0.948505, t90_s=0.948505, t95_s=0.948505, overshoot_percent=unavailable, residual_drift_hz_per_s=0; insufficient response amplitude
- step_index=2, code=33792->32768: baseline_hz=10000000.000, final_hz=10000000.000, t50_s=0.947501, t90_s=0.947501, t95_s=0.947501, overshoot_percent=unavailable, residual_drift_hz_per_s=0; insufficient response amplitude
- step_index=3, code=32768->31744: baseline_hz=10000000.000, final_hz=10000000.000, t50_s=0.947505, t90_s=0.947505, t95_s=0.947505, overshoot_percent=unavailable, residual_drift_hz_per_s=0; insufficient response amplitude
- step_index=4, code=31744->32768: baseline_hz=10000000.000, final_hz=10000000.000, t50_s=0.947504, t90_s=0.947504, t95_s=0.947504, overshoot_percent=unavailable, residual_drift_hz_per_s=0; insufficient response amplitude
- step_index=5, code=32768->34816: baseline_hz=10000000.000, final_hz=10000000.000, t50_s=0.947506, t90_s=0.947506, t95_s=0.947506, overshoot_percent=unavailable, residual_drift_hz_per_s=0; insufficient response amplitude
- step_index=6, code=34816->32768: baseline_hz=10000000.000, final_hz=10000000.000, t50_s=0.947501, t90_s=0.947501, t95_s=0.947501, overshoot_percent=unavailable, residual_drift_hz_per_s=0; insufficient response amplitude
- step_index=7, code=32768->30720: baseline_hz=10000000.000, final_hz=10000000.000, t50_s=0.947504, t90_s=0.947504, t95_s=0.947504, overshoot_percent=unavailable, residual_drift_hz_per_s=0; insufficient response amplitude
- step_index=8, code=30720->32768: baseline_hz=10000000.000, final_hz=10000000.000, t50_s=0.947502, t90_s=0.947502, t95_s=0.947502, overshoot_percent=unavailable, residual_drift_hz_per_s=-99.8004; insufficient response amplitude

## Warmup Drift
- samples: 758
- initial_frequency_hz: 9998019.802
- initial_ppm: -198.02
- total_elapsed_s: 756.999
- drift_after_warmup_hz_per_s: 0.00878274
- drift_after_warmup_ppm_per_hour: 3.16179
- practical_stability_time_s: 754.999
- note: used final third because requested warmup window exceeds run duration

## Hysteresis / Sweep Direction
- code=30720: up_median_hz=unavailable, down_median_hz=10000000.000, delta_hz=unavailable, repeated_center_span_hz=unavailable; up/down comparison unavailable
- code=31744: up_median_hz=unavailable, down_median_hz=10000000.000, delta_hz=unavailable, repeated_center_span_hz=unavailable; up/down comparison unavailable
- code=32768: up_median_hz=10000000.000, down_median_hz=10000000.000, delta_hz=0, repeated_center_span_hz=0; up/down medians compared at repeated DAC code; repeated-code span available
- code=33792: up_median_hz=10000000.000, down_median_hz=unavailable, delta_hz=unavailable, repeated_center_span_hz=unavailable; up/down comparison unavailable
- code=34816: up_median_hz=10000000.000, down_median_hz=unavailable, delta_hz=unavailable, repeated_center_span_hz=unavailable; up/down comparison unavailable

## Generated Artifacts
- csv/h1_characterization_points.csv
- plots/dac_code_vs_hz.png
- plots/settling_response.png
- plots/warmup_drift.png

## SW2 Readiness
- open_loop_slope_known: false
- safe_voltage_window_known: true
- settling_time_characterized: false
- warmup_characterized: true
- recommended_next_action: capture a DAC sweep with repeated count windows at two or more DAC codes
