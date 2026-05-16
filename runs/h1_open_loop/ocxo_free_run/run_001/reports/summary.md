# OTIS Run Report

## Run Identity
- run_id: run_001
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
- started_at_utc: 2026-05-15T14:00:44Z
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
- csv/ref.csv (raw_events_v1): present, 60000 rows, headers: record_type, schema_version, event_seq, channel_id, edge, timestamp_ticks, capture_domain, flags
- csv/cnt.csv (count_observations_v1): present, 60000 rows, headers: record_type, schema_version, count_seq, channel_id, gate_open_ticks, gate_close_ticks, gate_domain, counted_edges, source_edge, source_domain, flags
- csv/sts.csv (health_v1): present, 240044 rows, headers: record_type, schema_version, status_seq, timestamp_ticks, status_domain, component, status_key, status_value, severity, flags

## Row Counts
- count_observations_v1: 60000
- health_v1: 240044
- raw_events_v1: 60000

## Raw Event Summary
- row_count: 60000
- record_type_counts: {'REF': 60000}
- channel_type_counts: {'CH1 REF': 60000}
- first_timestamp_ticks: 8789856
- last_timestamp_ticks: 68713260896
- duration_ticks: 68704471040
- duration_seconds: 4294.029
- duration_note: using rp2040_timer0 nominal_hz
- timestamp_monotonic: False
- duplicate_timestamp_count: 0
- event_seq_monotonic: False
- event_seq_gap_count: 1
- CH1 intervals ticks: count=59999, min=-68703476848.000, max=16000016.000, mean=948722.697, stddev=1012195068.162

## Reference / PPS Summary
- reference edge count: 60000
- rp2040_timer0: intervals=59999, mean=948722.697 ticks / 0.0592952 s, min=-4293.967 s, max=1 s, stddev=63.2622 s, ppm_error_vs_1s=-940704.831 ppm; using manifest nominal_hz

## Count Observation Summary
- row_count: 60000
- mean_observed_frequency_hz: 9679321.192
- min_observed_frequency_hz: 0
- max_observed_frequency_hz: 10000999.001
- stddev_observed_frequency_hz: 1761313.672
- ppm_error_vs_nominal: -32067.881 ppm
- mean_window_seconds: 0.00100149
- min_window_seconds: 0.001001
- max_window_seconds: 0.001007
- frequency_note: nominal source frequency from h1_ocxo_open_loop

## Health / Status Summary
- row_count: 240044
- severity_counts: {'INFO': 240041, 'WARN': 3}
- status_key_counts: {'active_step': 1, 'arduino_core': 1, 'board': 1, 'boot': 1, 'capture_backend': 1, 'ch0_generic_event': 1, 'ch1_pps_reference': 1, 'ch2_osc_observation': 1, 'clamps_configured': 1, 'dropped_count': 59999, 'enable_dac_ad5693r': 1, 'enable_h1_dac_sweep': 1, 'enable_rp2040_boot_diag': 1, 'enable_status_led': 1, 'enabled': 2, 'error_flags': 59999, 'event_count': 59999, 'fc0_measure_period_ms': 1, 'gain_mode': 1, 'git_commit': 1, 'gpsdo_steering': 1, 'h1_open_loop': 1, 'i2c_address': 2, 'init': 1, 'initialized': 1, 'last_applied_code': 1, 'last_requested_code': 1, 'last_write_ok': 1, 'limitation': 1, 'max_code': 2, 'min_code': 2, 'mode': 2, 'name': 1, 'nominal_capture_clock_hz': 1, 'nominal_ocxo_hz': 1, 'nominal_pps_hz': 1, 'nominal_tcxo_hz': 1, 'profile': 1, 'reference_mode': 1, 'running': 1, 'schema_version': 1, 'step_count': 1, 'tcxo_counter_backend': 2, 'timestamp_latch': 1, 'uptime_seconds': 59999, 'version': 1}
- counter_summaries: {'dropped_count': {'first': 0, 'last': 0, 'max': 0, 'delta': 0}, 'enable_rp2040_boot_diag': {'first': 1, 'last': 1, 'max': 1, 'delta': 0}, 'error_flags': {'first': 0, 'last': 0, 'max': 0, 'delta': 0}}
- latest_capture_status: {'event_count': '59993', 'dropped_count': '0', 'error_flags': '0', 'mode': 'irq_reconstructed', 'timestamp_latch': 'irq_micros_reconstructed', 'limitation': 'bench_validation_not_final_pio_dma_metrology', 'nominal_capture_clock_hz': '16000000', 'fc0_measure_period_ms': '1000', 'tcxo_counter_backend': 'rp2040_fc0_gpin0'}

## Validation Findings
- csv/ref.csv: row 8: event_seq must be strictly increasing; previous=1605, current=1000
- csv/ref.csv: row 8: timestamp_ticks must be monotonic; previous=9710922816, current=24624400
- csv/ref.csv: row 4302: timestamp_ticks must be monotonic; previous=68712266688, current=8789856
- csv/ref.csv: row 8597: timestamp_ticks must be monotonic; previous=68712423824, current=8947008
- csv/ref.csv: row 12892: timestamp_ticks must be monotonic; previous=68712508080, current=9031232
- csv/ref.csv: row 17187: timestamp_ticks must be monotonic; previous=68712598528, current=9121696
- csv/ref.csv: row 21482: timestamp_ticks must be monotonic; previous=68712697984, current=9221152
- csv/ref.csv: row 25777: timestamp_ticks must be monotonic; previous=68712782752, current=9305920
- csv/ref.csv: row 30072: timestamp_ticks must be monotonic; previous=68712854544, current=9377712
- csv/ref.csv: row 34367: timestamp_ticks must be monotonic; previous=68712897328, current=9420480
- csv/ref.csv: row 38662: timestamp_ticks must be monotonic; previous=68712961776, current=9484928
- csv/ref.csv: row 42957: timestamp_ticks must be monotonic; previous=68713021328, current=9544496
- csv/ref.csv: row 47252: timestamp_ticks must be monotonic; previous=68713094096, current=9617248
- csv/ref.csv: row 51547: timestamp_ticks must be monotonic; previous=68713184256, current=9707424
- csv/ref.csv: row 55842: timestamp_ticks must be monotonic; previous=68713260896, current=9784048
- csv/cnt.csv: row 8: count_seq must be strictly increasing; previous=607, current=1
- csv/cnt.csv: row 8: gate_open_ticks must be monotonic; previous=9720256064, current=24258880
- csv/cnt.csv: row 8: gate_close_ticks must be monotonic; previous=9720272080, current=24274992
- csv/cnt.csv: row 4302: gate_open_ticks must be monotonic; previous=68712256032, current=8779280
- csv/cnt.csv: row 4302: gate_close_ticks must be monotonic; previous=68712272064, current=8795296
- csv/cnt.csv: row 8597: gate_open_ticks must be monotonic; previous=68712779328, current=9302592
- csv/cnt.csv: row 8597: gate_close_ticks must be monotonic; previous=68712795360, current=9318608
- csv/cnt.csv: row 12892: gate_open_ticks must be monotonic; previous=68713302576, current=9825856
- csv/cnt.csv: row 12892: gate_close_ticks must be monotonic; previous=68713318592, current=9841872
- csv/cnt.csv: row 17187: gate_open_ticks must be monotonic; previous=68713825808, current=10349120
- csv/cnt.csv: row 17187: gate_close_ticks must be monotonic; previous=68713841824, current=10365152
- csv/cnt.csv: row 21482: gate_open_ticks must be monotonic; previous=68714349136, current=10872336
- csv/cnt.csv: row 21482: gate_close_ticks must be monotonic; previous=68714365152, current=10888352
- csv/cnt.csv: row 25777: gate_open_ticks must be monotonic; previous=68714872368, current=11395664
- csv/cnt.csv: row 25777: gate_close_ticks must be monotonic; previous=68714888400, current=11411696
- csv/cnt.csv: row 30072: gate_open_ticks must be monotonic; previous=68715395616, current=11918928
- csv/cnt.csv: row 30072: gate_close_ticks must be monotonic; previous=68715411648, current=11934960
- csv/cnt.csv: row 34367: gate_open_ticks must be monotonic; previous=68715918864, current=12442176
- csv/cnt.csv: row 34367: gate_close_ticks must be monotonic; previous=68715934896, current=12458208
- csv/cnt.csv: row 38662: gate_open_ticks must be monotonic; previous=68716442128, current=12965456
- csv/cnt.csv: row 38662: gate_close_ticks must be monotonic; previous=68716458160, current=12981472
- csv/cnt.csv: row 42957: gate_open_ticks must be monotonic; previous=68716965408, current=13488720
- csv/cnt.csv: row 42957: gate_close_ticks must be monotonic; previous=68716981424, current=13504736
- csv/cnt.csv: row 47252: gate_open_ticks must be monotonic; previous=68717488656, current=14011968
- csv/cnt.csv: row 47252: gate_close_ticks must be monotonic; previous=68717504688, current=14028000
- csv/cnt.csv: row 51547: gate_open_ticks must be monotonic; previous=68718011968, current=14535216
- csv/cnt.csv: row 51547: gate_close_ticks must be monotonic; previous=68718028000, current=14551248
- csv/cnt.csv: row 55842: gate_open_ticks must be monotonic; previous=68718535216, current=15058512
- csv/cnt.csv: row 55842: gate_close_ticks must be monotonic; previous=68718551248, current=15074544
- csv/sts.csv: row 29: status_seq must be strictly increasing; previous=2474, current=1
- csv/sts.csv: row 29: timestamp_ticks must be monotonic; previous=9720287200, current=24098720
- csv/sts.csv: row 17249: timestamp_ticks must be monotonic; previous=68712289920, current=8802224
- csv/sts.csv: row 34429: timestamp_ticks must be monotonic; previous=68712810016, current=9322976
- csv/sts.csv: row 51609: timestamp_ticks must be monotonic; previous=68713333184, current=9845824
- csv/sts.csv: row 68789: timestamp_ticks must be monotonic; previous=68713856800, current=10369824
- csv/sts.csv: row 85969: timestamp_ticks must be monotonic; previous=68714380176, current=10892816
- csv/sts.csv: row 103149: timestamp_ticks must be monotonic; previous=68714902928, current=11415952
- csv/sts.csv: row 120329: timestamp_ticks must be monotonic; previous=68715426560, current=11939344
- csv/sts.csv: row 137509: timestamp_ticks must be monotonic; previous=68715949808, current=12462736
- csv/sts.csv: row 154689: timestamp_ticks must be monotonic; previous=68716472656, current=12985552
- csv/sts.csv: row 171869: timestamp_ticks must be monotonic; previous=68716996544, current=13508800
- csv/sts.csv: row 189049: timestamp_ticks must be monotonic; previous=68717519504, current=14032400
- csv/sts.csv: row 206229: timestamp_ticks must be monotonic; previous=68718042832, current=14555376
- csv/sts.csv: row 223409: timestamp_ticks must be monotonic; previous=68718565728, current=15078720
- raw_events.csv: PPS interval 7 in rp2040_timer0 is -9686298416 ticks; expected approximately 16000000
- raw_events.csv: PPS interval 4301 in rp2040_timer0 is -68703476832 ticks; expected approximately 16000000
- raw_events.csv: PPS interval 8596 in rp2040_timer0 is -68703476816 ticks; expected approximately 16000000
- raw_events.csv: PPS interval 12891 in rp2040_timer0 is -68703476848 ticks; expected approximately 16000000
- raw_events.csv: PPS interval 17186 in rp2040_timer0 is -68703476832 ticks; expected approximately 16000000
- raw_events.csv: PPS interval 21481 in rp2040_timer0 is -68703476832 ticks; expected approximately 16000000
- raw_events.csv: PPS interval 25776 in rp2040_timer0 is -68703476832 ticks; expected approximately 16000000
- raw_events.csv: PPS interval 30071 in rp2040_timer0 is -68703476832 ticks; expected approximately 16000000
- raw_events.csv: PPS interval 34366 in rp2040_timer0 is -68703476848 ticks; expected approximately 16000000
- raw_events.csv: PPS interval 38661 in rp2040_timer0 is -68703476848 ticks; expected approximately 16000000
- raw_events.csv: PPS interval 42956 in rp2040_timer0 is -68703476832 ticks; expected approximately 16000000
- raw_events.csv: PPS interval 47251 in rp2040_timer0 is -68703476848 ticks; expected approximately 16000000
- raw_events.csv: PPS interval 51546 in rp2040_timer0 is -68703476832 ticks; expected approximately 16000000
- raw_events.csv: PPS interval 55841 in rp2040_timer0 is -68703476848 ticks; expected approximately 16000000

## Validation Warnings
- manifest.json: firmware_version is not populated
- manifest.json: host_tool_version is not populated
- manifest.json: firmware_git_commit is not populated
- manifest.json: host_git_commit is not populated
- run_001: COMPLETE marker is missing; run may not be ready to commit as a fixture
- csv/evt.csv: CSV has headers but no data rows

## Anomalies
- raw_events_v1: timestamp_ticks are not monotonic in manifest file order
- raw_events_v1: event_seq is not strictly increasing in manifest file order
- raw_events_v1: 14 PPS/reference interval(s) in rp2040_timer0 outside 0.8-1.2 s

## Development Usefulness
- keep_as_fixture: False
- reason: not fixture-ready: resolve missing files, validation findings, or missing raw rows

## Reproduction Commands
- `python3 -m host.otis_tools.validate_run runs/h1_open_loop/ocxo_free_run/run_001`
- `python3 -m host.otis_tools.report_run runs/h1_open_loop/ocxo_free_run/run_001`
- `python3 -m host.otis_tools.report_run runs/h1_open_loop/ocxo_free_run/run_001 --json runs/h1_open_loop/ocxo_free_run/run_001/reports/summary.json`
