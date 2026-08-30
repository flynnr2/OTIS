# forwarded_monitor_snapshots_v1.csv

`MNS` preserves the raw cumulative snapshot produced by the optional D6/GPIO18
forwarded-output monitor. It is diagnostic-only evidence from the physical
D9-to-D6 series-resistor loopback. It is not a D14 PPS witness, a substitute
for D8, or an input to measurement validity, estimation, control, abort, or a
run terminal.

| Column | Type | Meaning |
|---|---|---|
| `record_type` | enum | Always `MNS`. |
| `schema_version` | integer | Always `1`. |
| `session` | uint32 | D6 monitor session; comparisons never cross a change. |
| `reference_session` | uint32 | Authoritative D14/D8 capture session associated with this snapshot. |
| `snapshot_sequence` | uint32 | Monitor-local snapshot ordinal; uint32 wrap is continuous. |
| `cumulative_down_counter` | uint32 | Raw PIO X down-counter snapshot. |
| `reference_sequence` | uint32 | Exact accepted D14 boundary sequence used for association. |
| `reference_timestamp_ticks` | uint64 | Associated D14 boundary in `rp2040_timer0`. |
| `status` | uint32 bit mask | D6-local status; nonzero status is never silently bridged. |
| `backend` | string | Exact monitor backend identity. |
| `channel_id` | integer | Exactly `3`, the D6 diagnostic channel. |

Adjacent clean records may be reconstructed by unsigned down-counter
subtraction only when monitor session, reference session, both sequences, and
the declared `rp2040_timer0` ordering are continuous. A gap, duplicate,
session change, nonzero local status, or an interval above the declared
ambiguity limit invalidates that derived interval and establishes a new
anchor. Raw records remain unchanged.

`MNS` can corroborate threshold-crossing edge continuity and a declared D8:D6
count ratio. It cannot establish D9 voltage, waveform, duty cycle, edge rate,
ringing, jitter, propagation delay, load drive, phase noise, UTC alignment, or
absolute frequency accuracy.
