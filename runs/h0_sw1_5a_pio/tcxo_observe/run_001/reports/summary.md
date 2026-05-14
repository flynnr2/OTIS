# OTIS Run Report

## Run Identity
- run_id: h0_sw1_5a_pio_tcxo_observe_run_001
- manifest_loaded: True
- stage: SW1
- h_phase: H0
- capture_mode: irq_reconstructed
- bringup_mode: SW1_TCXO_OBSERVE
- template: False
- board: arduino_nano_rp2040_connect
- firmware_name: otis_nano_rp2040_connect
- firmware_version: SW1
- firmware_git_commit: not present
- host_tool_version: 0
- host_git_commit: not present
- profile: {'name': 'h0_reference', 'version': 1}
- started_at_utc: 2026-05-14T09:15:06Z
- ended_at_utc: not present

## Run State
- capture_in_progress.flag: False
- COMPLETE: False

## SW1 Boundary
- SW1 capture mode: irq_reconstructed. Timestamps are suitable for bench validation and protocol bring-up, not final PIO/DMA metrology.
- manifest: SW1 timestamps may be IRQ/micros-derived rather than final PIO/DMA hardware timestamps.

## Artifact Inventory
- raw_events.csv (raw_events_v1): present, 141 rows, headers: record_type, schema_version, event_seq, channel_id, edge, timestamp_ticks, capture_domain, flags
- count_observations.csv (count_observations_v1): present, 141 rows, headers: record_type, schema_version, count_seq, channel_id, gate_open_ticks, gate_close_ticks, gate_domain, counted_edges, source_edge, source_domain, flags
- health.csv (health_v1): present, 1128 rows, headers: record_type, schema_version, status_seq, timestamp_ticks, status_domain, component, status_key, status_value, severity, flags

## Row Counts
- count_observations_v1: 141
- health_v1: 1128
- raw_events_v1: 141

## Raw Event Summary
- row_count: 141
- record_type_counts: {'REF': 141}
- channel_type_counts: {'CH1 REF': 141}
- first_timestamp_ticks: 39825024
- last_timestamp_ticks: 2279820000
- duration_ticks: 2239994976
- duration_seconds: 140
- duration_note: using rp2040_timer0 nominal_hz
- timestamp_monotonic: True
- duplicate_timestamp_count: 0
- event_seq_monotonic: True
- event_seq_gap_count: 0
- CH1 intervals ticks: count=140, min=15999888.000, max=16000016.000, mean=15999964.114, stddev=21.5404

## Reference / PPS Summary
- reference edge count: 141
- rp2040_timer0: intervals=140, mean=15999964.114 ticks / 0.999998 s, min=0.999993 s, max=1 s, stddev=1.34627e-06 s, ppm_error_vs_1s=-2.243 ppm; using manifest nominal_hz

## Count Observation Summary
- row_count: 141
- mean_observed_frequency_hz: 16000049.596
- min_observed_frequency_hz: 16000000.000
- max_observed_frequency_hz: 16000999.001
- stddev_observed_frequency_hz: 216.994
- ppm_error_vs_nominal: not computed
- mean_window_seconds: 0.00100122
- min_window_seconds: 0.001001
- max_window_seconds: 0.001004
- frequency_note: source nominal not computed: source_domain values ['h0_tcxo_16mhz'] not declared with nominal_hz

## Health / Status Summary
- row_count: 1128
- severity_counts: {'INFO': 1128}
- status_key_counts: {'dropped_count': 141, 'error_flags': 141, 'event_count': 141, 'pio_fifo_drained_event_count': 141, 'pio_fifo_empty_count': 141, 'pio_fifo_max_drain_batch': 141, 'pio_fifo_overflow_drop_count': 141, 'uptime_seconds': 141}
- counter_summaries: {'dropped_count': {'first': 0, 'last': 0, 'max': 0, 'delta': 0}, 'error_flags': {'first': 0, 'last': 0, 'max': 0, 'delta': 0}, 'pio_fifo_overflow_drop_count': {'first': 0, 'last': 0, 'max': 0, 'delta': 0}}
- latest_capture_status: {'event_count': '141', 'dropped_count': '0', 'error_flags': '0', 'pio_fifo_drained_event_count': '141', 'pio_fifo_empty_count': '50400539', 'pio_fifo_overflow_drop_count': '0', 'pio_fifo_max_drain_batch': '1'}

## Validation Findings
- none

## Validation Warnings
- run_manifest.json: firmware_git_commit is not populated
- run_manifest.json: host_git_commit is not populated
- run_001: COMPLETE marker is missing; run may not be ready to commit as a fixture

## Anomalies
- none

## Development Usefulness
- keep_as_fixture: True
- reason: valid run with parseable listed artifacts

## Reproduction Commands
- `python3 -m host.otis_tools.validate_run runs/h0_sw1_5a_pio/tcxo_observe/run_001`
- `python3 -m host.otis_tools.report_run runs/h0_sw1_5a_pio/tcxo_observe/run_001`
- `python3 -m host.otis_tools.report_run runs/h0_sw1_5a_pio/tcxo_observe/run_001 --json runs/h0_sw1_5a_pio/tcxo_observe/run_001/reports/summary.json`
