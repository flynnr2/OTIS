# health_v1.csv

## Purpose

`health_v1.csv` records device status, health transitions, counters, warnings, restart breadcrumbs, and other operational telemetry.

Health/status records are intentionally separated from event captures and oscillator observations.

Use the `STS` record family for device and pipeline state.

## Schema

| Field | Type | Meaning |
|---|---|---|
| `record_type` | enum | compact tag; always `STS` |
| `schema_version` | uint | schema revision |
| `status_seq` | uint64 | monotonic status record counter |
| `timestamp_ticks` | uint64 | timestamp in `status_domain` |
| `status_domain` | string | timestamp domain |
| `component` | string | emitting subsystem |
| `status_key` | string | compact status key |
| `status_value` | string | status payload |
| `severity` | enum | `INFO`, `WARN`, `ERROR`, `FATAL` |
| `flags` | uint32 | numeric flags from `capture_flags_v1` |

## Example

```csv
record_type,schema_version,status_seq,timestamp_ticks,status_domain,component,status_key,status_value,severity,flags
STS,1,7,1600000000,rp2040_timer0,capture,ring_fill_pct,12,INFO,0
STS,1,8,1600100000,rp2040_timer0,pps,reference_valid,true,INFO,0
STS,1,9,1600200000,rp2040_timer0,system,restart_reason,brownout,WARN,32
```

## Design Rule

Status is not a fake capture channel.

Do not encode operational telemetry as invented `EVT` rows. Keep health/state telemetry distinct from scientific timing observations.
