# h1_count_frequency_estimates_v1.csv

Derived H1 host-analysis table. This file is not raw telemetry and must not
replace `count_observations_v1.csv` or `raw_events_v1.csv`.

Each row joins one accepted count observation to the estimator diagnostics used
by `host/otis_tools/h1_characterize.py`.

| Field | Type | Notes |
| --- | --- | --- |
| `count_seq` | uint64 | Source `CNT.count_seq`. |
| `elapsed_s` | float | Host-analysis elapsed timestamp used for DAC dwell grouping. |
| `gate_open_raw_timestamp` | uint64 | Raw `CNT.gate_open_ticks`. |
| `gate_close_raw_timestamp` | uint64 | Raw `CNT.gate_close_ticks`. |
| `gate_open_unwrapped_timestamp` | uint64 | Host-unwrapped gate-open ticks. |
| `gate_close_unwrapped_timestamp` | uint64 | Host-unwrapped gate-close ticks. |
| `raw_gate_ticks` | uint64 | Unwrapped close minus open ticks. |
| `counted_edges` | uint64 | Source `CNT.counted_edges`; not modified by analysis. |
| `legacy_gate_seconds` | float | Gate duration from the retained run-wide or nominal tick-rate estimator. |
| `legacy_frequency_hz` | float | `counted_edges / legacy_gate_seconds`. |
| `legacy_ppm` | float | Legacy estimate relative to nominal oscillator frequency. |
| `local_pps_gate_seconds` | float | PPS-interpolated gate duration when available. |
| `local_pps_frequency_hz` | float | `counted_edges / local_pps_gate_seconds`. |
| `local_pps_ppm` | float | Local PPS estimate relative to nominal oscillator frequency. |
| `frequency_difference_hz` | float | `local_pps_frequency_hz - legacy_frequency_hz`. |
| `frequency_difference_fractional` | float | Difference divided by legacy frequency. |
| `pps_time_open` | float | Interpolated PPS time at gate open. |
| `pps_time_close` | float | Interpolated PPS time at gate close. |
| `pps_before_open_timestamp` | uint64 | Accepted PPS timestamp before or at gate open. |
| `pps_after_open_timestamp` | uint64 | Accepted PPS timestamp after or at gate open. |
| `pps_before_close_timestamp` | uint64 | Accepted PPS timestamp before or at gate close. |
| `pps_after_close_timestamp` | uint64 | Accepted PPS timestamp after or at gate close. |
| `pps_support_count` | uint32 | Accepted PPS observations spanning the gate support. |
| `max_pps_gap_seconds` | float | Largest adjacent accepted PPS interval in the support region. |
| `estimator_mode` | enum | `LOCAL_PPS_INTERPOLATED`, `RUN_WIDE_TICK_RATE`, `NOMINAL_TICK_RATE`, or `UNAVAILABLE`. |
| `estimator_valid` | bool | True only for local PPS estimates valid for H1 plant analysis. |
| `estimator_quality_flags` | string | Pipe-separated diagnostic flags, or `none`. |

Local PPS interpolation uses only adjacent accepted REF/PPS intervals from the
same `rp2040_timer0` timestamp domain. It does not extrapolate by default and
does not interpolate across rejected PPS intervals.
