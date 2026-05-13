# OTIS Run Report

## Run Identity
- run_id: h0_sw1_gpio_loopback_run_001
- bringup_mode: SW1_GPIO_LOOPBACK
- template: False
- profile: {'name': 'h0_reference', 'version': 1}
- started_at_utc: 2026-05-13T20:35:38Z
- ended_at_utc: not present

## Artifact Inventory
- raw_events.csv (raw_events_v1): present, 166 rows, headers: record_type, schema_version, event_seq, channel_id, edge, timestamp_ticks, capture_domain, flags
- health.csv (health_v1): present, 168 rows, headers: record_type, schema_version, status_seq, timestamp_ticks, status_domain, component, status_key, status_value, severity, flags

## Row Counts
- health_v1: 168
- raw_events_v1: 166

## Raw Event Summary
- row_count: 166
- record_type_counts: {'EVT': 166}
- channel_type_counts: {'CH0 EVT': 166}
- first_timestamp_ticks: 92048064
- last_timestamp_ticks: 752064064
- duration_ticks: 660016000
- duration_seconds: 41.251
- duration_note: using rp2040_timer0 nominal_hz
- timestamp_monotonic: True
- duplicate_timestamp_count: 0
- event_seq_monotonic: True
- event_seq_gap_count: 0
- CH0 intervals ticks: count=165, min=3995216.000, max=4020784.000, mean=4000096.970, stddev=2722.520

## Reference / PPS Summary
- not present

## Count Observation Summary
- not present

## Health / Status Summary
- row_count: 168
- severity_counts: {'INFO': 168}
- status_key_counts: {'dropped_count': 42, 'error_flags': 42, 'event_count': 42, 'uptime_seconds': 42}
- counter_summaries: {'dropped_count': {'first': 0, 'last': 0, 'max': 0, 'delta': 0}, 'error_flags': {'first': 0, 'last': 0, 'max': 0, 'delta': 0}}

## Validation Findings
- none

## Anomalies
- none

## Development Usefulness
- keep_as_fixture: True
- reason: valid run with parseable listed artifacts

## Reproduction Commands
- `python3 -m host.otis_tools.validate_run runs/h0_sw1/gpio_loopback/run_001`
- `python3 -m host.otis_tools.report_run runs/h0_sw1/gpio_loopback/run_001`
- `python3 -m host.otis_tools.report_run runs/h0_sw1/gpio_loopback/run_001 --json runs/h0_sw1/gpio_loopback/run_001/reports/summary.json`
