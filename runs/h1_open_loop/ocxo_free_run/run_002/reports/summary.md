# OTIS Run Report

## Run Identity
- run_id: run_002
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
- host_tool_version: not present
- host_git_commit: not present
- profile: not present
- started_at_utc: 2026-05-16T07:04:25Z
- ended_at_utc: not present

## Run State
- capture_in_progress.flag: False
- COMPLETE: False

## SW1 Boundary
- SW1 capture mode: irq_reconstructed. Timestamps are suitable for bench validation and protocol bring-up, not final PIO/DMA metrology.
- manifest: H1 open-loop characterization only. No closed-loop GPSDO steering is implemented or implied.
- manifest: Unknown oscillator and DAC fields are explicit nulls or empty strings until measured on the bench.

## Artifact Inventory
- csv/evt.csv (raw_events_v1): present, 0 rows, headers: record_type, schema_version, event_seq, channel_id, edge, timestamp_ticks, capture_domain, flags
- csv/ref.csv (raw_events_v1): present, 96205 rows, headers: record_type, schema_version, event_seq, channel_id, edge, timestamp_ticks, capture_domain, flags
- csv/cnt.csv (count_observations_v1): present, 8763 rows, headers: record_type, schema_version, count_seq, channel_id, gate_open_ticks, gate_close_ticks, gate_domain, counted_edges, source_edge, source_domain, flags
- csv/sts.csv (health_v1): present, 385676 rows, headers: record_type, schema_version, status_seq, timestamp_ticks, status_domain, component, status_key, status_value, severity, flags

## Row Counts
- count_observations_v1: 8763
- health_v1: 385676
- raw_events_v1: 96205

## Raw Event Summary
- row_count: 96205
- record_type_counts: {'REF': 96205}
- channel_type_counts: {'CH1 REF': 96205}
- first_timestamp_ticks: 7322832
- last_timestamp_ticks: 68714865712
- duration_ticks: 1539272576144
- duration_seconds: 96204.536
- duration_note: using rp2040_timer0 nominal_hz
- timestamp_wrap_count: 22
- timestamp_monotonic: False
- duplicate_timestamp_count: 0
- event_seq_monotonic: True
- event_seq_gap_count: 0
- CH1 intervals ticks: count=96204, min=15999872.000, max=31999536.000, mean=16000089.145, stddev=51583.484, wrap_count=22

## Reference / PPS Summary
- reference edge count: 96205
- rp2040_timer0: intervals=96204, mean=16000089.145 ticks / 1.00001 s, min=0.999992 s, max=1.99997 s, stddev=0.00322397 s, ppm_error_vs_1s=5.572 ppm, wrap_count=22; using manifest nominal_hz

## Count Observation Summary
- row_count: 8763
- mean_observed_frequency_hz: 9847669.291
- min_observed_frequency_hz: 0
- max_observed_frequency_hz: 10000000.000
- stddev_observed_frequency_hz: 1121877.813
- unflagged_nonzero_row_count: 8560
- mean_unflagged_nonzero_frequency_hz: 9999084.930
- stddev_unflagged_nonzero_frequency_hz: 34181.149
- zero_count_rows: 76
- flagged_zero_count_rows: 76
- ppm_error_vs_nominal: -15233.071 ppm
- mean_window_seconds: 10.001
- min_window_seconds: 10.0008
- max_window_seconds: 10.002
- frequency_note: nominal source frequency from h1_ocxo_open_loop

## Health / Status Summary
- row_count: 385676
- severity_counts: {'INFO': 385673, 'WARN': 3}
- status_key_counts: {'accepted_code': 1, 'active_step': 1, 'arduino_core': 1, 'board': 1, 'boot': 1, 'capture_backend': 1, 'ch0_generic_event': 1, 'ch1_pps_reference': 1, 'ch2_osc_observation': 1, 'clamps_configured': 1, 'dropped_count': 96404, 'enable_dac_ad5693r': 1, 'enable_h1_dac_sweep': 1, 'enable_rp2040_boot_diag': 1, 'enable_status_led': 1, 'enabled': 2, 'error_flags': 96404, 'event_count': 96404, 'fc0_measure_period_ms': 1, 'gain_mode': 1, 'gate_period_us': 1, 'git_commit': 1, 'gpsdo_steering': 1, 'h1_open_loop': 1, 'i2c_address': 2, 'init': 1, 'initialized': 1, 'last_applied_code': 1, 'last_counted_edges': 1, 'last_elapsed_us': 1, 'last_gate_close_ticks': 1, 'last_gate_open_ticks': 1, 'last_measured_khz': 1, 'last_requested_code': 1, 'last_sample_count': 1, 'last_sampled_elapsed_us': 1, 'last_write_ok': 1, 'limitation': 1, 'max_code': 2, 'measure_period_ms': 1, 'min_code': 2, 'mode': 2, 'name': 1, 'nominal_capture_clock_hz': 1, 'nominal_ocxo_hz': 1, 'nominal_pps_hz': 1, 'nominal_tcxo_hz': 1, 'profile': 1, 'reference_mode': 1, 'requested_code': 1, 'running': 1, 'schema_version': 1, 'step_count': 1, 'tcxo_counter_backend': 2, 'timestamp_latch': 1, 'uptime_seconds': 96404, 'valid': 1, 'version': 1}
- counter_summaries: {'dropped_count': {'first': 0, 'last': 0, 'max': 0, 'delta': 0}, 'enable_rp2040_boot_diag': {'first': 1, 'last': 1, 'max': 1, 'delta': 0}, 'error_flags': {'first': 0, 'last': 0, 'max': 0, 'delta': 0}}
- latest_capture_status: {'event_count': '96204', 'dropped_count': '0', 'error_flags': '0', 'mode': 'irq_reconstructed', 'timestamp_latch': 'irq_micros_reconstructed', 'limitation': 'bench_validation_not_final_pio_dma_metrology', 'nominal_capture_clock_hz': '16000000', 'fc0_measure_period_ms': '1000', 'tcxo_counter_backend': 'rp2040_fc0_gpin0'}

## Validation Findings
- csv/sts.csv: row 9: status_seq must be strictly increasing; previous=64, current=1
- csv/sts.csv: row 9: timestamp_ticks must be monotonic; previous=92139104, current=24098256
- raw_events.csv: PPS interval 1 in rp2040_timer0 is 31999536 ticks; expected approximately 16000000

## Validation Warnings
- manifest.json: firmware_version is not populated
- manifest.json: host_tool_version is not populated
- manifest.json: firmware_git_commit is not populated
- manifest.json: host_git_commit is not populated
- run_002: COMPLETE marker is missing; run may not be ready to commit as a fixture
- csv/evt.csv: CSV has headers but no data rows

## Anomalies
- raw_events_v1: timestamp_ticks are not monotonic in manifest file order
- raw_events_v1: 1 PPS/reference interval(s) in rp2040_timer0 outside 0.8-1.2 s

## Development Usefulness
- keep_as_fixture: False
- reason: not fixture-ready: resolve missing files, validation findings, or missing raw rows

## Reproduction Commands
- `python3 -m host.otis_tools.validate_run runs/h1_open_loop/ocxo_free_run/run_002`
- `python3 -m host.otis_tools.report_run runs/h1_open_loop/ocxo_free_run/run_002`
- `python3 -m host.otis_tools.report_run runs/h1_open_loop/ocxo_free_run/run_002 --json runs/h1_open_loop/ocxo_free_run/run_002/reports/summary.json`
