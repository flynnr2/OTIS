# OTIS Run Report

## Run Identity
- run_id: h1_vcocxo_dac_sweep_006
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
- started_at_utc: 2026-05-15T12:47:43Z
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
- csv/ref.csv (raw_events_v1): present, 725 rows, headers: record_type, schema_version, event_seq, channel_id, edge, timestamp_ticks, capture_domain, flags
- csv/cnt.csv (count_observations_v1): present, 758 rows, headers: record_type, schema_version, count_seq, channel_id, gate_open_ticks, gate_close_ticks, gate_domain, counted_edges, source_edge, source_domain, flags
- csv/sts.csv (health_v1): present, 3146 rows, headers: record_type, schema_version, status_seq, timestamp_ticks, status_domain, component, status_key, status_value, severity, flags
- csv/dac_steps.csv (dac_steps_v1): present, 165 rows, headers: record_type, schema_version, seq, elapsed_ms, step_index, dac_code_requested, dac_code_applied, dac_code_clamped, dac_voltage_measured_v, ocxo_tune_voltage_measured_v, dwell_ms, event, flags

## Row Counts
- count_observations_v1: 758
- dac_steps_v1: 165
- health_v1: 3146
- raw_events_v1: 725

## Raw Event Summary
- row_count: 725
- record_type_counts: {'REF': 725}
- channel_type_counts: {'CH1 REF': 725}
- first_timestamp_ticks: 538486592
- last_timestamp_ticks: 12138440384
- duration_ticks: 11599953792
- duration_seconds: 724.997
- duration_note: using rp2040_timer0 nominal_hz
- timestamp_monotonic: True
- duplicate_timestamp_count: 0
- event_seq_monotonic: True
- event_seq_gap_count: 0
- CH1 intervals ticks: count=724, min=15999904.000, max=31999648.000, mean=16022035.624, stddev=594213.798

## Reference / PPS Summary
- reference edge count: 725
- rp2040_timer0: intervals=724, mean=16022035.624 ticks / 1.00138 s, min=0.999994 s, max=1.99998 s, stddev=0.0371384 s, ppm_error_vs_1s=1377.227 ppm; using manifest nominal_hz

## Count Observation Summary
- row_count: 758
- mean_observed_frequency_hz: 10000038.218
- min_observed_frequency_hz: 9998003.992
- max_observed_frequency_hz: 10000999.001
- stddev_observed_frequency_hz: 228.822
- ppm_error_vs_nominal: not computed
- mean_window_seconds: 0.00100164
- min_window_seconds: 0.001001
- max_window_seconds: 0.00101
- frequency_note: source nominal not computed: source_domain values ['h1_ocxo_open_loop'] not declared with nominal_hz

## Health / Status Summary
- row_count: 3146
- severity_counts: {'INFO': 3143, 'WARN': 3}
- status_key_counts: {'accepted_code': 9, 'active_step': 4, 'arduino_core': 1, 'board': 1, 'boot': 1, 'capture_backend': 1, 'ch0_generic_event': 1, 'ch1_pps_reference': 1, 'ch2_osc_observation': 1, 'clamps_configured': 4, 'dropped_count': 757, 'enable_dac_ad5693r': 1, 'enable_h1_dac_sweep': 1, 'enable_rp2040_boot_diag': 1, 'enable_status_led': 1, 'enabled': 5, 'error_flags': 757, 'event_count': 757, 'fc0_measure_period_ms': 1, 'gain_mode': 1, 'git_commit': 1, 'gpsdo_steering': 1, 'h1_open_loop': 1, 'i2c_address': 2, 'init': 1, 'initialized': 1, 'last_applied_code': 1, 'last_counted_edges': 4, 'last_elapsed_us': 4, 'last_gate_close_ticks': 4, 'last_gate_open_ticks': 4, 'last_measured_khz': 4, 'last_requested_code': 1, 'last_write_ok': 1, 'limitation': 1, 'load': 3, 'max_code': 2, 'measure_period_ms': 4, 'min_code': 2, 'mode': 2, 'name': 1, 'nominal_capture_clock_hz': 1, 'nominal_ocxo_hz': 1, 'nominal_pps_hz': 1, 'nominal_tcxo_hz': 1, 'profile': 7, 'reference_mode': 1, 'requested_code': 9, 'running': 4, 'schema_version': 1, 'step_count': 4, 'tcxo_counter_backend': 2, 'timestamp_latch': 1, 'uptime_seconds': 757, 'valid': 4, 'version': 1}
- counter_summaries: {'dropped_count': {'first': 0, 'last': 0, 'max': 0, 'delta': 0}, 'enable_rp2040_boot_diag': {'first': 1, 'last': 1, 'max': 1, 'delta': 0}, 'error_flags': {'first': 0, 'last': 0, 'max': 0, 'delta': 0}}
- latest_capture_status: {'mode': 'irq_reconstructed', 'timestamp_latch': 'irq_micros_reconstructed', 'limitation': 'bench_validation_not_final_pio_dma_metrology', 'nominal_capture_clock_hz': '16000000', 'fc0_measure_period_ms': '1000', 'tcxo_counter_backend': 'rp2040_fc0_gpin0', 'event_count': '724', 'dropped_count': '0', 'error_flags': '0'}

## Validation Findings
- raw_events.csv: PPS interval 1 in rp2040_timer0 is 31999648 ticks; expected approximately 16000000

## Validation Warnings
- run_manifest.json: firmware_version is not populated
- run_manifest.json: host_tool_version is not populated
- run_manifest.json: firmware_git_commit is not populated
- run_manifest.json: host_git_commit is not populated
- run_006: COMPLETE marker is missing; run may not be ready to commit as a fixture
- csv/evt.csv: CSV has headers but no data rows

## Anomalies
- raw_events_v1: 1 PPS/reference interval(s) in rp2040_timer0 outside 0.8-1.2 s

## Development Usefulness
- keep_as_fixture: False
- reason: not fixture-ready: resolve missing files, validation findings, or missing raw rows

## Reproduction Commands
- `python3 -m host.otis_tools.validate_run runs/h1_open_loop/dac_manual_sweep/run_006`
- `python3 -m host.otis_tools.report_run runs/h1_open_loop/dac_manual_sweep/run_006`
- `python3 -m host.otis_tools.report_run runs/h1_open_loop/dac_manual_sweep/run_006 --json runs/h1_open_loop/dac_manual_sweep/run_006/reports/summary.json`
