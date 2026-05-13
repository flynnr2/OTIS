# OTIS Run Report

## Run Identity
- run_id: h0_sw1_synthetic_usb_run_001
- bringup_mode: SW1_SYNTHETIC_USB
- template: False
- profile: {'name': 'h0_reference', 'version': 1}
- started_at_utc: 2026-05-13T20:32:50Z
- ended_at_utc: not present

## Artifact Inventory
- raw_events.csv (raw_events_v1): present, 4 rows, headers: record_type, schema_version, event_seq, channel_id, edge, timestamp_ticks, capture_domain, flags
- count_observations.csv (count_observations_v1): present, 1 rows, headers: record_type, schema_version, count_seq, channel_id, gate_open_ticks, gate_close_ticks, gate_domain, counted_edges, source_edge, source_domain, flags
- health.csv (health_v1): present, 95 rows, headers: record_type, schema_version, status_seq, timestamp_ticks, status_domain, component, status_key, status_value, severity, flags

## Row Counts
- count_observations_v1: 1
- health_v1: 95
- raw_events_v1: 4

## Raw Event Summary
- row_count: 4
- record_type_counts: {'EVT': 2, 'REF': 2}
- channel_type_counts: {'CH0 EVT': 2, 'CH1 REF': 2}
- first_timestamp_ticks: 1600001234
- last_timestamp_ticks: 1632000000
- duration_ticks: 31998766
- duration_seconds: 1.99992
- duration_note: using rp2040_timer0 nominal_hz
- timestamp_monotonic: True
- duplicate_timestamp_count: 0
- event_seq_monotonic: True
- event_seq_gap_count: 0
- CH0 intervals ticks: count=1, min=638, max=638, mean=638, stddev=not computed
- CH1 intervals ticks: count=1, min=16000000.000, max=16000000.000, mean=16000000.000, stddev=not computed

## Reference / PPS Summary
- reference edge count: 2
- rp2040_timer0: intervals=1, mean=16000000.000 ticks / 1 s, min=1 s, max=1 s, stddev=not computed s, ppm_error_vs_1s=0.000 ppm; using manifest nominal_hz

## Count Observation Summary
- row_count: 1
- mean_observed_frequency_hz: 16000000.000
- min_observed_frequency_hz: 16000000.000
- max_observed_frequency_hz: 16000000.000
- stddev_observed_frequency_hz: not computed
- ppm_error_vs_nominal: not computed
- mean_window_seconds: 1
- min_window_seconds: 1
- max_window_seconds: 1
- frequency_note: source nominal not computed: source_domain values ['h0_tcxo_16mhz'] not declared with nominal_hz

## Health / Status Summary
- row_count: 95
- severity_counts: {'INFO': 95}
- status_key_counts: {'arduino_core': 1, 'board': 1, 'boot': 1, 'ch0_generic_event': 1, 'ch1_pps_reference': 1, 'ch2_osc_observation': 1, 'dropped_count': 22, 'error_flags': 22, 'event_count': 22, 'mode': 1, 'uptime_seconds': 22}
- counter_summaries: {'dropped_count': {'first': 0, 'last': 0, 'max': 0, 'delta': 0}, 'error_flags': {'first': 0, 'last': 0, 'max': 0, 'delta': 0}}

## Validation Findings
- none

## Anomalies
- none

## Development Usefulness
- keep_as_fixture: True
- reason: valid run with parseable listed artifacts

## Reproduction Commands
- `python3 -m host.otis_tools.validate_run runs/h0_sw1/synthetic_usb/run_001`
- `python3 -m host.otis_tools.report_run runs/h0_sw1/synthetic_usb/run_001`
- `python3 -m host.otis_tools.report_run runs/h0_sw1/synthetic_usb/run_001 --json runs/h0_sw1/synthetic_usb/run_001/reports/summary.json`
