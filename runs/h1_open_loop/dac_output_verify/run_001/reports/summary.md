# OTIS Run Report

## Run Identity
- run_id: h1_vcocxo_dac_observeonly_001
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
- started_at_utc: 2026-05-15T12:16:42Z
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
- csv/ref.csv (raw_events_v1): present, 248 rows, headers: record_type, schema_version, event_seq, channel_id, edge, timestamp_ticks, capture_domain, flags
- csv/cnt.csv (count_observations_v1): present, 250 rows, headers: record_type, schema_version, count_seq, channel_id, gate_open_ticks, gate_close_ticks, gate_domain, counted_edges, source_edge, source_domain, flags
- csv/sts.csv (health_v1): present, 1037 rows, headers: record_type, schema_version, status_seq, timestamp_ticks, status_domain, component, status_key, status_value, severity, flags

## Row Counts
- count_observations_v1: 250
- health_v1: 1037
- raw_events_v1: 248

## Raw Event Summary
- row_count: 248
- record_type_counts: {'REF': 248}
- channel_type_counts: {'CH1 REF': 248}
- first_timestamp_ticks: 96485200
- last_timestamp_ticks: 4064471568
- duration_ticks: 3967986368
- duration_seconds: 247.999
- duration_note: using rp2040_timer0 nominal_hz
- timestamp_monotonic: True
- duplicate_timestamp_count: 0
- event_seq_monotonic: True
- event_seq_gap_count: 0
- CH1 intervals ticks: count=247, min=15999904.000, max=31999872.000, mean=16064722.138, stddev=1015988.047

## Reference / PPS Summary
- reference edge count: 248
- rp2040_timer0: intervals=247, mean=16064722.138 ticks / 1.00405 s, min=0.999994 s, max=1.99999 s, stddev=0.0634993 s, ppm_error_vs_1s=4045.134 ppm; using manifest nominal_hz

## Count Observation Summary
- row_count: 250
- mean_observed_frequency_hz: 10000019.964
- min_observed_frequency_hz: 10000000.000
- max_observed_frequency_hz: 10000999.001
- stddev_observed_frequency_hz: 139.748
- ppm_error_vs_nominal: not computed
- mean_window_seconds: 0.0010017
- min_window_seconds: 0.001001
- max_window_seconds: 0.001005
- frequency_note: source nominal not computed: source_domain values ['h1_ocxo_open_loop'] not declared with nominal_hz

## Health / Status Summary
- row_count: 1037
- severity_counts: {'INFO': 1035, 'WARN': 2}
- status_key_counts: {'accepted_code': 11, 'dropped_count': 250, 'enabled': 1, 'error_flags': 250, 'event_count': 250, 'gain_mode': 1, 'i2c_address': 1, 'initialized': 1, 'last_applied_code': 1, 'last_requested_code': 1, 'last_write_ok': 1, 'max_code': 2, 'min_code': 2, 'reference_mode': 1, 'rejected_code': 1, 'requested_code': 12, 'set': 1, 'uptime_seconds': 250}
- counter_summaries: {'dropped_count': {'first': 0, 'last': 0, 'max': 0, 'delta': 0}, 'error_flags': {'first': 0, 'last': 0, 'max': 0, 'delta': 0}}
- latest_capture_status: {'event_count': '249', 'dropped_count': '0', 'error_flags': '0'}

## Validation Findings
- raw_events.csv: PPS interval 1 in rp2040_timer0 is 31999872 ticks; expected approximately 16000000

## Validation Warnings
- run_manifest.json: firmware_version is not populated
- run_manifest.json: host_tool_version is not populated
- run_manifest.json: firmware_git_commit is not populated
- run_manifest.json: host_git_commit is not populated
- run_001: COMPLETE marker is missing; run may not be ready to commit as a fixture
- csv/evt.csv: CSV has headers but no data rows

## Anomalies
- raw_events_v1: 1 PPS/reference interval(s) in rp2040_timer0 outside 0.8-1.2 s

## Development Usefulness
- keep_as_fixture: False
- reason: not fixture-ready: resolve missing files, validation findings, or missing raw rows

## Reproduction Commands
- `python3 -m host.otis_tools.validate_run runs/h1_open_loop/dac_output_verify/run_001`
- `python3 -m host.otis_tools.report_run runs/h1_open_loop/dac_output_verify/run_001`
- `python3 -m host.otis_tools.report_run runs/h1_open_loop/dac_output_verify/run_001 --json runs/h1_open_loop/dac_output_verify/run_001/reports/summary.json`
