# OTIS Run Report

## Run Identity
- run_id: run_017
- manifest_loaded: True
- stage: OPEN_LOOP
- h_phase: H1
- capture_mode: observation_only_open_loop
- bringup_mode: not present
- template: False
- board: arduino_nano_rp2040_connect
- firmware_name: not present
- firmware_version: SW1
- firmware_git_commit: 0ebdae3266635bc98b9518a59fcfaa68751c4024
- host_tool_version: 0.0.0
- host_git_commit: 0ebdae3266635bc98b9518a59fcfaa68751c4024
- profile: not present
- started_at_utc: 2026-07-27T11:58:21Z
- ended_at_utc: 2026-07-28T08:05:11Z

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
- manifest: Whole-assembly cardboard airflow shield is not a thermally isolated CX317 enclosure and includes nearby heat sources.
- manifest: The sequence runner uses direct DAC SET commands and host-side timing; it does not emit firmware DAC dwell_start/fc0_window rows for each manual dwell.
- manifest: DAC command acknowledgement is verified from STS dac/accepted_code rows captured by capture_device.
- manifest: D10 witness diagnostics are temporary H1 diagnostics and must remain disabled for unrelated generic-event or loopback work.
- manifest: run_017 is not a discipline-loop, PLL/FLL, holdover, or automatic-steering test.
- manifest: Do not compare run_017 as a controlled CX317-only enclosure test; compare run_016 exposed bench assembly with run_017 whole-assembly cardboard airflow shield.

## Artifact Inventory
- csv/evt.csv (raw_events_v1): present, 0 rows, headers: record_type, schema_version, event_seq, channel_id, edge, timestamp_ticks, capture_domain, flags
- csv/ref.csv (raw_events_v1): present, 72410 rows, headers: record_type, schema_version, event_seq, channel_id, edge, timestamp_ticks, capture_domain, flags
- csv/cnt.csv (count_observations_v1): present, 242 rows, headers: record_type, schema_version, count_seq, channel_id, gate_open_ticks, gate_close_ticks, gate_domain, counted_edges, source_edge, source_domain, flags
- csv/sts.csv (health_v1): present, 1737908 rows, headers: record_type, schema_version, status_seq, timestamp_ticks, status_domain, component, status_key, status_value, severity, flags
- csv/dac_steps.csv (dac_steps_v1): present, 9 rows, headers: record_type, schema_version, seq, elapsed_ms, step_index, dac_code_requested, dac_code_applied, dac_code_clamped, dac_voltage_measured_v, ocxo_tune_voltage_measured_v, dwell_ms, event, flags
- csv/environment.csv (environment_v1): present, 144820 rows, headers: record_type, schema_version, env_seq, timestamp_ticks, observation_domain, source, role, temperature_c, relative_humidity_pct, pressure_pa, flags

## Row Counts
- count_observations_v1: 242
- dac_steps_v1: 9
- environment_v1: 144820
- health_v1: 1737908
- raw_events_v1: 72410

## Raw Event Summary
- row_count: 72410
- record_type_counts: {'REF': 72410}
- channel_type_counts: {'CH1 REF': 72410}
- first_timestamp_ticks: 9014932704
- last_timestamp_ticks: 1167553189152
- duration_ticks: 1158538256448
- duration_seconds: 72408.641
- duration_note: using rp2040_timer0 nominal_hz
- timestamp_wrap_count: 16
- timestamp_monotonic: True
- timestamp_raw_monotonic: False
- duplicate_timestamp_count: 0
- event_seq_monotonic: True
- event_seq_gap_count: 0
- CH1 intervals ticks: count=72409, min=15999808.000, max=16000064.000, mean=15999920.679, stddev=28.2413, wrap_count=16

## Reference / PPS Summary
- reference edge count: 72410
- rp2040_timer0: intervals=72409, mean=15999920.679 ticks / 0.999995 s, min=0.999988 s, max=1 s, stddev=1.76508e-06 s, ppm_error_vs_1s=-4.958 ppm, wrap_count=16; using manifest nominal_hz

## Count Observation Summary
- row_count: 242
- mean_observed_frequency_hz: 10000047.565
- min_observed_frequency_hz: 10000037.127
- max_observed_frequency_hz: 10000058.103
- stddev_observed_frequency_hz: 4.84394
- unflagged_nonzero_row_count: 242
- mean_unflagged_nonzero_frequency_hz: 10000047.565
- stddev_unflagged_nonzero_frequency_hz: 4.84394
- zero_count_rows: 0
- flagged_zero_count_rows: 0
- ppm_error_vs_nominal: 4.757 ppm
- mean_window_seconds: 300
- min_window_seconds: 300
- max_window_seconds: 300.006
- frequency_note: nominal source frequency from h1_ocxo_open_loop

## Health / Status Summary
- row_count: 1737908
- severity_counts: {'INFO': 1669227, 'WARN': 68681}
- status_key_counts: {'accepted_code': 11, 'accepted_pps_count': 72410, 'active_step': 1, 'agreement_state': 72410, 'buffer_overflow_count': 72410, 'burst_active': 72410, 'burst_count': 72410, 'clamps_configured': 1, 'consecutive_bad_windows': 1, 'd14_raw_minus_d10_raw': 72410, 'dropped_count': 72410, 'enabled': 2, 'error_flags': 72410, 'event_count': 72410, 'fc0_clean_window_count': 1, 'fc0_fault': 1, 'fc0_observed_valid': 1, 'fc0_valid_for_control': 1, 'gain_mode': 1, 'gate_period_us': 1, 'i2c_address': 1, 'initialized': 1, 'last_accepted_timestamp': 72410, 'last_applied_code': 1, 'last_counted_edges': 1, 'last_edge_timestamp': 72410, 'last_elapsed_us': 1, 'last_first_sample_khz': 1, 'last_gate_close_ticks': 1, 'last_gate_open_ticks': 1, 'last_interval': 72410, 'last_last_sample_khz': 1, 'last_max_sample_khz': 1, 'last_measured_khz': 1, 'last_min_sample_khz': 1, 'last_raw_interval': 72410, 'last_raw_timestamp': 72410, 'last_requested_code': 1, 'last_sample_count': 1, 'last_sampled_elapsed_us': 1, 'last_valid_sample_count': 1, 'last_window_flags': 1, 'last_window_invalid_reason': 1, 'last_write_ok': 1, 'last_zero_sample_count': 1, 'max_code': 2, 'measure_period_ms': 1, 'measurement_mode': 1, 'min_code': 2, 'pending_start': 1, 'profile': 1, 'raw_edge_count': 144820, 'reference_mode': 1, 'rejected_long_count': 72410, 'rejected_short_count': 72410, 'requested_code': 11, 'running': 1, 'sampled_high_count': 144820, 'sampled_low_count': 144820, 'short_interval_count': 72410, 'startup_inhibit_active': 1, 'startup_inhibit_elapsed_s': 1, 'step_count': 1, 'total_bad_windows': 1, 'uptime_seconds': 72410, 'valid': 1}
- counter_summaries: {'dropped_count': {'first': 0, 'last': 0, 'max': 0, 'delta': 0}, 'error_flags': {'first': 0, 'last': 0, 'max': 0, 'delta': 0}}
- latest_capture_status: {'event_count': '72970', 'dropped_count': '0', 'error_flags': '0'}

## Validation Findings
- none

## Validation Warnings
- csv/evt.csv: CSV has headers but no data rows

## Anomalies
- none

## Development Usefulness
- keep_as_fixture: True
- reason: valid run with parseable listed artifacts

## Reproduction Commands
- `python3 -m host.otis_tools.validate_run runs/h1_open_loop/dac_manual_sweep/run_017`
- `python3 -m host.otis_tools.report_run runs/h1_open_loop/dac_manual_sweep/run_017`
- `python3 -m host.otis_tools.report_run runs/h1_open_loop/dac_manual_sweep/run_017 --json runs/h1_open_loop/dac_manual_sweep/run_017/reports/summary.json`
