# PPS Cumulative Snapshot CSV Contract v1

`SNP` preserves the raw hardware-owned PIO counter snapshot after foreground
has associated it with the independently captured physical `REF` event.  It is
the authoritative source for reconstructing an interval count.  `CNT` is the
derived adjacent-snapshot result; host arrival time and timer-normalised
frequency are diagnostic only.

| Field | Type | Meaning |
|---|---|---|
| `record_type` | enum | Always `SNP`. |
| `schema_version` | integer | Always `1`. |
| `session` | u32 | Capture session. A change forbids differencing across the boundary. |
| `snapshot_sequence` | u32 | DMA producer ordinal within the session, modulo 2^32. |
| `cumulative_down_counter` | u32 | Raw PIO X value captured with `IN X, 32`; not an interval. |
| `reference_sequence` | u32 | Sequence of the associated physical `REF` rising edge. |
| `reference_timestamp_ticks` | u64 | Immutable timestamp of that `REF`, in the `rp2040_timer0` domain. |
| `status` | u32 bitmask | Snapshot transport/capture status; zero is clean. |
| `backend` | text | Capture implementation identity. The candidate is `pio_wait_cumulative_snapshot_dma_v1`. |

Canonical header:

```csv
record_type,schema_version,session,snapshot_sequence,cumulative_down_counter,reference_sequence,reference_timestamp_ticks,status,backend
```

For adjacent clean records in one session:

```text
interval_count = (previous.cumulative_down_counter
                  - current.cumulative_down_counter) mod 2^32
```

The first record in every session is an anchor and must not produce `CNT`.
Snapshot and reference sequences must both be adjacent modulo 2^32.  Any
status bit, gap, duplicate, ambiguous full counter wrap, association loss,
FIFO/DMA/ring fault, or session transition fails closed.  Reacquisition needs
two new clean snapshots; late records are never paired retroactively.

`reference_timestamp_ticks` inherits the canonical `rp2040_timer0` domain from
this contract. Legal modular progression is automatic; a session transition
resets temporal reconstruction and is never treated as a timer rollover. See
`docs/50_SOFTWARE/TIME_DOMAIN_AND_ROLLOVER_CONTRACT.md`.
