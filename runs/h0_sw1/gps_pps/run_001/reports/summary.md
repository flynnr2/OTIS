# OTIS Run Report

## Run Identity
- run_id: h0_sw1_gps_pps_run_001
- bringup_mode: SW1_GPS_PPS
- template: False
- profile: {'name': 'h0_reference', 'version': 1}
- started_at_utc: 2026-05-13T20:37:44Z
- ended_at_utc: not present

## Artifact Inventory
- raw_events.csv (raw_events_v1): present, 27 rows, headers: record_type, schema_version, event_seq, channel_id, edge, timestamp_ticks, capture_domain, flags
- health.csv (health_v1): present, 111 rows, headers: record_type, schema_version, status_seq, timestamp_ticks, status_domain, component, status_key, status_value, severity, flags

## Row Counts
- health_v1: 111
- raw_events_v1: 27

## Raw Event Summary
- row_count: 27
- record_type_counts: {'REF': 27}
- channel_type_counts: {'CH1 REF': 27}
- first_timestamp_ticks: 28585696
- last_timestamp_ticks: 444585056
- duration_ticks: 415999360
- duration_seconds: 26
- duration_note: using rp2040_timer0 nominal_hz
- timestamp_monotonic: True
- duplicate_timestamp_count: 0
- event_seq_monotonic: True
- event_seq_gap_count: 0
- CH1 intervals ticks: count=26, min=15999792.000, max=16000016.000, mean=15999975.385, stddev=40.2407

## Reference / PPS Summary
- reference edge count: 27
- rp2040_timer0: intervals=26, mean=15999975.385 ticks / 0.999998 s, min=0.999987 s, max=1 s, stddev=2.51504e-06 s, ppm_error_vs_1s=-1.538 ppm; using manifest nominal_hz

## Count Observation Summary
- not present

## Health / Status Summary
- row_count: 111
- severity_counts: {'INFO': 111}
- status_key_counts: {'arduino_core': 1, 'board': 1, 'boot': 1, 'ch0_generic_event': 1, 'ch1_pps_reference': 1, 'ch2_osc_observation': 1, 'dropped_count': 26, 'error_flags': 26, 'event_count': 26, 'mode': 1, 'uptime_seconds': 26}
- counter_summaries: {'dropped_count': {'first': 0, 'last': 0, 'max': 0, 'delta': 0}, 'error_flags': {'first': 0, 'last': 0, 'max': 0, 'delta': 0}}

## Validation Findings
- none

## Anomalies
- none

## Development Usefulness
- keep_as_fixture: True
- reason: valid run with parseable listed artifacts

## Reproduction Commands
- `python3 -m host.otis_tools.validate_run runs/h0_sw1/gps_pps/run_001`
- `python3 -m host.otis_tools.report_run runs/h0_sw1/gps_pps/run_001`
- `python3 -m host.otis_tools.report_run runs/h0_sw1/gps_pps/run_001 --json runs/h0_sw1/gps_pps/run_001/reports/summary.json`
