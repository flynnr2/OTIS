# environment_v1.csv

## Purpose

`environment_v1.csv` records low-rate environmental observations that help
interpret timing behavior without making those observations part of the capture
channel model.

For H1 VCOCXO characterization, near-oscillator temperature is the primary
thermal proxy for warm-up, settling, DAC sweep, and drift analysis.

## Schema

| Field | Type | Meaning |
|---|---|---|
| `record_type` | enum | compact tag; always `ENV` |
| `schema_version` | uint | schema revision |
| `env_seq` | uint64 | monotonic environmental observation counter |
| `timestamp_ticks` | uint64 | timestamp in `observation_domain` |
| `observation_domain` | string | native time domain for `timestamp_ticks` |
| `source` | string | sensor source, for example `sht4x` or `bmp280` |
| `role` | string | placement/use role, for example `vcocxo_near` |
| `temperature_c` | float or empty | temperature in degrees Celsius |
| `relative_humidity_pct` | float or empty | relative humidity in percent |
| `pressure_pa` | float or empty | pressure in pascals |
| `flags` | uint32 | numeric flags from `capture_flags_v1` |

## Example

```csv
record_type,schema_version,env_seq,timestamp_ticks,observation_domain,source,role,temperature_c,relative_humidity_pct,pressure_pa,flags
ENV,1,1,16000000,rp2040_timer0,sht4x,vcocxo_near,31.42,44.8,,0
ENV,1,2,16000012,rp2040_timer0,bmp280,pressure_reference,31.65,,100812.4,0
```

## Design Rule

Environmental observations are sampled context, not raw timing events. Do not
encode temperature, humidity, or pressure as `EVT`, `REF`, or `CNT` rows unless
a sensor output is deliberately connected to the timing fabric as a signal with
edge or gate semantics.
