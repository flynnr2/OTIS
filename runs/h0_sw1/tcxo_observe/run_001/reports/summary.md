# OTIS Run Report

## Run Identity
- run_id: h0_sw1_tcxo_observe_run_001
- bringup_mode: SW1_TCXO_OBSERVE
- template: False
- profile: {'name': 'h0_reference', 'version': 1}
- started_at_utc: 2026-05-13T20:42:23Z
- ended_at_utc: not present

## Artifact Inventory
- raw_events.csv (raw_events_v1): present, 79 rows, headers: record_type, schema_version, event_seq, channel_id, edge, timestamp_ticks, capture_domain, flags
- count_observations.csv (count_observations_v1): present, 80 rows, headers: record_type, schema_version, count_seq, channel_id, gate_open_ticks, gate_close_ticks, gate_domain, counted_edges, source_edge, source_domain, flags
- health.csv (health_v1): present, 320 rows, headers: record_type, schema_version, status_seq, timestamp_ticks, status_domain, component, status_key, status_value, severity, flags

## Row Counts
- count_observations_v1: 80
- health_v1: 320
- raw_events_v1: 79

## Raw Event Summary
- row_count: 79
- record_type_counts: {'REF': 79}
- channel_type_counts: {'CH1 REF': 79}
- first_timestamp_ticks: 102098800
- last_timestamp_ticks: 1350098176
- duration_ticks: 1247999376
- duration_seconds: 78
- duration_note: using rp2040_timer0 nominal_hz
- timestamp_monotonic: True
- duplicate_timestamp_count: 0
- event_seq_monotonic: True
- event_seq_gap_count: 0
- CH1 intervals ticks: count=78, min=15999968.000, max=16000032.000, mean=15999992.000, stddev=14.662

## Reference / PPS Summary
- reference edge count: 79
- rp2040_timer0: intervals=78, mean=15999992.000 ticks / 1 s, min=0.999998 s, max=1 s, stddev=9.16375e-07 s, ppm_error_vs_1s=-0.500 ppm; using manifest nominal_hz

## Count Observation Summary
- row_count: 80
- mean_observed_frequency_hz: 16000012.488
- min_observed_frequency_hz: 16000000.000
- max_observed_frequency_hz: 16000999.001
- stddev_observed_frequency_hz: 110.991
- ppm_error_vs_nominal: not computed
- mean_window_seconds: 0.00100109
- min_window_seconds: 0.001001
- max_window_seconds: 0.001002
- frequency_note: source nominal not computed: source_domain values ['h0_tcxo_16mhz'] not declared with nominal_hz

## Health / Status Summary
- row_count: 320
- severity_counts: {'INFO': 320}
- status_key_counts: {'dropped_count': 80, 'error_flags': 80, 'event_count': 80, 'uptime_seconds': 80}
- counter_summaries: {'dropped_count': {'first': 0, 'last': 0, 'max': 0, 'delta': 0}, 'error_flags': {'first': 0, 'last': 0, 'max': 0, 'delta': 0}}

## Validation Findings
- none

## Anomalies
- none

## Development Usefulness
- keep_as_fixture: True
- reason: valid run with parseable listed artifacts

## Reproduction Commands
- `python3 -m host.otis_tools.validate_run runs/h0_sw1/tcxo_observe/run_001`
- `python3 -m host.otis_tools.report_run runs/h0_sw1/tcxo_observe/run_001`
- `python3 -m host.otis_tools.report_run runs/h0_sw1/tcxo_observe/run_001 --json runs/h0_sw1/tcxo_observe/run_001/reports/summary.json`
