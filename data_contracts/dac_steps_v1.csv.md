# dac_steps_v1.csv

## Purpose

`dac_steps_v1.csv` records physical DAC application attempts made by the fixed
adaptive-hybrid image. It is actuator evidence, not controller authority or a
lock claim. `manual_apply` identifies the single setup transaction;
`active_apply` identifies an accepted automatic transaction. Their matching
failure events preserve an unsuccessful or ambiguous physical attempt.

## Schema

| Field | Type | Meaning |
|---|---|---|
| `record_type` | enum | compact record tag; `DAC` |
| `schema_version` | uint | schema revision; currently `1` |
| `seq` | uint64 | monotonic DAC telemetry sequence within the run |
| `elapsed_ms` | uint64 | firmware elapsed milliseconds at emission |
| `step_index` | int | setup command sequence or adaptive request sequence |
| `dac_code_requested` | uint16 | requested DAC code for this event |
| `dac_code_applied` | uint16 | accepted/applied DAC code, after safety validation |
| `dac_code_clamped` | bool | `1` when the request would have crossed clamps; such rows are safety rejections |
| `dac_voltage_measured_v` | decimal/null | manual measured DAC output voltage, empty until recorded |
| `ocxo_tune_voltage_measured_v` | decimal/null | manual measured OCXO tune voltage, empty until recorded |
| `dwell_ms` | uint32 | zero in the fixed transaction path |
| `event` | enum | `manual_apply`, `manual_write_failed`, `active_apply`, or `active_write_failed` |
| `flags` | uint32 | numeric bitmask from `capture_flags_v1` |

## Example

```csv
record_type,schema_version,seq,elapsed_ms,step_index,dac_code_requested,dac_code_applied,dac_code_clamped,dac_voltage_measured_v,ocxo_tune_voltage_measured_v,dwell_ms,event,flags
DAC,1,7,12000,42,43085,43085,0,,,0,active_apply,0
```

## Transaction attribution

Every row joins a current setup or adaptive transaction by the sequence in
`step_index`. Requested/applied code, the exact transaction record,
acknowledgement, DAC epoch, and first dependent decision are the authoritative
causal chain; proximity to a `CNT` row is not sufficient attribution.

A same-code setup application is still a physical transition. It opens a new
DAC epoch and frequency, phase, tight-band, and adaptive-hybrid consumers must
requalify against that epoch.
