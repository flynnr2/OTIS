# Pseudo-PPS Generator Truth CSV Contract v1

`PGT` is the generator's authoritative intended schedule. It is a separate
evidence plane from physical `REF` detections, PIO counter snapshots, derived
diagnostics, and host arrival time. A schedule row states what the single PIO
waveform engine was asked to produce; marker rows delimit the actual generator
session outcome.

| Field | Type | Meaning |
|---|---|---|
| `record_type` | enum | Always `PGT`. |
| `schema_version` | integer | Always `1`. |
| `truth_seq` | u32 | Strictly increasing truth-stream sequence. |
| `generator_session` | u32 | Increments for every accepted `START`. |
| `profile_id` | text | Versioned built-in profile identifier, or `NONE` for a pre-session resource fault. |
| `profile_version` | u16 | Profile definition version. |
| `generator_sequence` | u32 | One-based schedule row index; zero for markers. |
| `event` | enum | `schedule`, `start`, `completion`, `abort`, `underflow`, or `resource_fault`. |
| `intended_class` | text | Fault/clean class for schedules; `marker` for markers. |
| `scheduled_offset_us` | u32 | Intended offset from PIO start; zero for markers. |
| `scheduled_interval_us` | u32 | Intended delay from the prior logical schedule item; zero for markers. |
| `pulse_width_us` | u32 | Intended high width; zero for omissions and markers. |
| `flags` | bitmask | OTIS v1 flags. |

Canonical header:

```csv
record_type,schema_version,truth_seq,generator_session,profile_id,profile_version,generator_sequence,event,intended_class,scheduled_offset_us,scheduled_interval_us,pulse_width_us,flags
```

An omission is a `schedule` row with `pulse_width_us=0`; it intentionally has
no corresponding physical rising edge. `completion` is emitted only after the
PIO consumes its low-state sentinel. `abort`, `underflow`, and `resource_fault`
mean the output was returned to high impedance and the remaining plan must not
be treated as generated.
