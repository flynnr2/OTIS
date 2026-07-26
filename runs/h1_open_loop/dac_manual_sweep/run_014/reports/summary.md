# OTIS Run Report

## Run Identity
- run_id: run_014
- manifest_loaded: True
- stage: OPEN_LOOP
- h_phase: H1
- capture_mode: observation_only_open_loop
- bringup_mode: not present
- template: False
- board: arduino_nano_rp2040_connect
- firmware_name: not present
- firmware_version: not present
- firmware_git_commit: not present
- host_tool_version: 0.0.0
- host_git_commit: 897fcbe198cbce402b84fe47b3107ea6fb887426
- profile: not present
- started_at_utc: 2026-07-25T08:02:58Z
- ended_at_utc: 2026-07-26T13:11:43Z

## Run State
- capture_in_progress.flag: False
- COMPLETE: True

## Session Summary
- session_count: 1
- reconnect_event_count: 0
- reboot_marker_count: 0
- split_reasons: none
- session_0001: start_reason=capture_start, close_reason=not recorded, source=run_manifest

## SW1 Boundary
- SW1 capture mode: irq_reconstructed. Timestamps are suitable for bench validation and protocol bring-up, not final PIO/DMA metrology.
- manifest: H1 open-loop characterization only. No closed-loop GPSDO steering is implemented or implied.
- manifest: Power-path fields are explicit nulls or empty strings until measured on the bench.
- manifest: This run characterizes the new CX317 dirty-to-clean power path and should not be mixed with earlier power-path data without noting the topology change.
- manifest: The pre-G17-fix capture is preserved under derived/pre_g17_fix_capture_2026-07-25/ as negative hardware evidence and is excluded from the clean post-fix plant fit.
- manifest: REF/PPS cadence anomalies are explicitly gated as diagnostic-only unresolved reference/capture-path evidence; anomalous REF rows remain in csv/ref.csv and are not control-eligible.

## Artifact Inventory
- csv/evt.csv (raw_events_v1): present, 0 rows, headers: record_type, schema_version, event_seq, channel_id, edge, timestamp_ticks, capture_domain, flags
- csv/ref.csv (raw_events_v1): present, 87737 rows, headers: record_type, schema_version, event_seq, channel_id, edge, timestamp_ticks, capture_domain, flags
- csv/cnt.csv (count_observations_v1): present, 284 rows, headers: record_type, schema_version, count_seq, channel_id, gate_open_ticks, gate_close_ticks, gate_domain, counted_edges, source_edge, source_domain, flags
- csv/sts.csv (health_v1): present, 340794 rows, headers: record_type, schema_version, status_seq, timestamp_ticks, status_domain, component, status_key, status_value, severity, flags
- csv/dac_steps.csv (dac_steps_v1): present, 612 rows, headers: record_type, schema_version, seq, elapsed_ms, step_index, dac_code_requested, dac_code_applied, dac_code_clamped, dac_voltage_measured_v, ocxo_tune_voltage_measured_v, dwell_ms, event, flags
- csv/environment.csv (environment_v1): present, 170278 rows, headers: record_type, schema_version, env_seq, timestamp_ticks, observation_domain, source, role, temperature_c, relative_humidity_pct, pressure_pa, flags

## Row Counts
- count_observations_v1: 284
- dac_steps_v1: 612
- environment_v1: 170278
- health_v1: 340794
- raw_events_v1: 87737

## Raw Event Summary
- row_count: 87737
- record_type_counts: {'REF': 87737}
- channel_type_counts: {'CH1 REF': 87737}
- first_timestamp_ticks: 11068991920
- last_timestamp_ticks: 1373269516272
- duration_ticks: 1362200524352
- duration_seconds: 85137.533
- duration_note: using rp2040_timer0 nominal_hz
- timestamp_wrap_count: 19
- timestamp_monotonic: True
- timestamp_raw_monotonic: False
- duplicate_timestamp_count: 0
- event_seq_monotonic: True
- event_seq_gap_count: 0
- CH1 intervals ticks: count=87736, min=1168.000, max=16000192.000, mean=15526129.802, stddev=2654432.569, wrap_count=19

## Reference / PPS Summary
- reference edge count: 87737
- rp2040_timer0: intervals=87736, mean=15526129.802 ticks / 0.970383 s, min=7.3e-05 s, max=1.00001 s, stddev=0.165902 s, ppm_error_vs_1s=-29616.887 ppm, wrap_count=19; using manifest nominal_hz
- rp2040_timer0 PPS anomalies by class: {'short_interval': 2719}
| index | interval_ticks | class | missed_pps |
| --- | ---: | --- | ---: |
| 54 | 10387728 | short_interval | not computed |
| 55 | 5612160 | short_interval | not computed |
| 70 | 7657312 | short_interval | not computed |
| 71 | 8342560 | short_interval | not computed |
| 97 | 7113360 | short_interval | not computed |
| 98 | 8886544 | short_interval | not computed |
| 999 | 3208000 | short_interval | not computed |
| 1000 | 1620416 | short_interval | not computed |
| 1001 | 357312 | short_interval | not computed |
| 1002 | 10814192 | short_interval | not computed |
| 1008 | 8897056 | short_interval | not computed |
| 1009 | 343824 | short_interval | not computed |
| 1010 | 614816 | short_interval | not computed |
| 1011 | 959632 | short_interval | not computed |
| 1012 | 352784 | short_interval | not computed |
| 1013 | 596592 | short_interval | not computed |
| 1014 | 333968 | short_interval | not computed |
| 1015 | 357296 | short_interval | not computed |
| 1016 | 601968 | short_interval | not computed |
| 1017 | 352960 | short_interval | not computed |

## Count Observation Summary
- row_count: 284
- mean_observed_frequency_hz: 10000054.324
- min_observed_frequency_hz: 10000044.780
- max_observed_frequency_hz: 10000071.363
- stddev_observed_frequency_hz: 4.28716
- unflagged_nonzero_row_count: 284
- mean_unflagged_nonzero_frequency_hz: 10000054.324
- stddev_unflagged_nonzero_frequency_hz: 4.28716
- zero_count_rows: 0
- flagged_zero_count_rows: 0
- ppm_error_vs_nominal: 5.432 ppm
- mean_window_seconds: 300
- min_window_seconds: 300
- max_window_seconds: 300.001
- frequency_note: nominal source frequency from h1_ocxo_open_loop

## Health / Status Summary
- row_count: 340794
- severity_counts: {'INFO': 340788, 'WARN': 6}
- status_key_counts: {'accepted_code': 2, 'active_step': 19, 'clamps_configured': 19, 'consecutive_bad_windows': 2, 'dropped_count': 85139, 'enabled': 20, 'error_flags': 85139, 'event_count': 85139, 'fc0_clean_window_count': 2, 'fc0_fault': 2, 'fc0_observed_valid': 2, 'fc0_valid_for_control': 2, 'gain_mode': 1, 'gate_period_us': 2, 'i2c_address': 1, 'initialized': 1, 'last_applied_code': 1, 'last_counted_edges': 2, 'last_elapsed_us': 2, 'last_first_sample_khz': 2, 'last_gate_close_ticks': 2, 'last_gate_open_ticks': 2, 'last_last_sample_khz': 2, 'last_max_sample_khz': 2, 'last_measured_khz': 2, 'last_min_sample_khz': 2, 'last_requested_code': 1, 'last_sample_count': 2, 'last_sampled_elapsed_us': 2, 'last_valid_sample_count': 2, 'last_window_flags': 2, 'last_window_invalid_reason': 2, 'last_write_ok': 1, 'last_zero_sample_count': 2, 'load': 18, 'max_code': 1, 'measure_period_ms': 2, 'measurement_mode': 2, 'min_code': 1, 'pending_start': 19, 'profile': 37, 'reference_mode': 1, 'requested_code': 2, 'running': 19, 'start': 1, 'startup_inhibit_active': 2, 'startup_inhibit_elapsed_s': 2, 'step_count': 19, 'total_bad_windows': 2, 'uptime_seconds': 85139, 'valid': 2}
- counter_summaries: {'dropped_count': {'first': 0, 'last': 0, 'max': 0, 'delta': 0}, 'error_flags': {'first': 0, 'last': 0, 'max': 0, 'delta': 0}}
- latest_capture_status: {'event_count': '88393', 'dropped_count': '0', 'error_flags': '0'}

## Validation Findings
- none

## Validation Warnings
- manifest.json: firmware_version is not populated
- manifest.json: firmware_git_commit is not populated
- manifest.json: PPS cadence anomaly gate declared for rp2040_timer0 (short_interval, count=2719); gated intervals are diagnostic-only, not control-eligible
- csv/evt.csv: CSV has headers but no data rows

## Anomalies
- raw_events_v1: 2719 PPS/reference interval(s) in rp2040_timer0 outside 0.8-1.2 s

## Development Usefulness
- keep_as_fixture: True
- reason: valid run with parseable listed artifacts

## Reproduction Commands
- `python3 -m host.otis_tools.validate_run runs/h1_open_loop/dac_manual_sweep/run_014`
- `python3 -m host.otis_tools.report_run runs/h1_open_loop/dac_manual_sweep/run_014`
- `python3 -m host.otis_tools.report_run runs/h1_open_loop/dac_manual_sweep/run_014 --json runs/h1_open_loop/dac_manual_sweep/run_014/reports/summary.json`
