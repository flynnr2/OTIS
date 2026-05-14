# dac_steps_v1.csv

## Purpose

`dac_steps_v1.csv` records H1 open-loop DAC sweep lifecycle and step telemetry.
It is lab automation evidence only. Rows must not be interpreted as closed-loop
control, steering decisions, PPS lock state, or frequency correction behavior.

## Schema

| Field | Type | Meaning |
|---|---|---|
| `record_type` | enum | compact record tag; `DAC` |
| `schema_version` | uint | schema revision; currently `1` |
| `seq` | uint64 | monotonic DAC/sweep telemetry sequence within the run |
| `elapsed_ms` | uint64 | firmware elapsed milliseconds at emission |
| `step_index` | int | active sweep step index, or `-1` for run-level events |
| `dac_code_requested` | uint16 | requested DAC code for this event |
| `dac_code_applied` | uint16 | accepted/applied DAC code, after safety validation |
| `dac_code_clamped` | bool | `1` when the request would have crossed clamps; such rows are safety rejections |
| `dac_voltage_measured_v` | decimal/null | manual measured DAC output voltage, empty until recorded |
| `ocxo_tune_voltage_measured_v` | decimal/null | manual measured OCXO tune voltage, empty until recorded |
| `dwell_ms` | uint32 | requested dwell time for the step |
| `event` | string | event name such as `start`, `profile_loaded`, `step_apply`, `dwell_start`, `fc0_window`, `dwell_complete`, `stop`, `complete`, or `safety_reject` |
| `flags` | uint32 | numeric bitmask from `capture_flags_v1` |

## Example

```csv
record_type,schema_version,seq,elapsed_ms,step_index,dac_code_requested,dac_code_applied,dac_code_clamped,dac_voltage_measured_v,ocxo_tune_voltage_measured_v,dwell_ms,event,flags
DAC,1,7,12000,1,32769,32769,0,,,5000,fc0_window,16
```

## Count Attribution

During an active sweep, firmware should emit a `DAC` row with event
`fc0_window` near each `CNT` observation. That row provides the active step
index and DAC code for reconstructing DAC setting versus FC0 count without
changing the stable `count_observations_v1` schema.
