# PPS Cumulative Snapshot CSV Contract v2

`SNP` is the canonical single-owner D14/D8 boundary observation. The unchanged
PIO state machine recognizes D14, atomically pushes its cumulative D8 downcounter
word, and continues counting. The FIFO IRQ service assigns the capture session
and ordinal when it reads that immutable word. No independent GPIO observation
is associated with the PIO word.

| Field | Type | Meaning |
|---|---|---|
| `record_type` | enum | Always `SNP`. |
| `schema_version` | integer | Always `2`. |
| `session` | u32 | Capture session. A change forbids differencing across the boundary. |
| `snapshot_sequence` | u32 | Committed FIFO-word ordinal within the session, modulo 2^32. Identity advances once per word read, not once per IRQ. |
| `cumulative_down_counter` | u32 | Raw PIO X value captured with `IN X, 32`; not an interval. |
| `reference_sequence` | u32 | Consumer-identity copy of `snapshot_sequence`; it must equal `snapshot_sequence`. It is not `REF.event_seq`. |
| `reference_timestamp_ticks` | u64 | RP2040 timer coordinate at FIFO CPU service, encoded in the wrapping `rp2040_monotonic_us32` domain. It is not a hardware-latched D14 timestamp. |
| `timestamp_uncertainty_ticks` | u32 | Lower-bound service uncertainty: elapsed microsecond ticks since the IRQ owner last observed this FIFO empty, plus one tick for the audited PIO recognition-to-push quantization margin. `UINT32_MAX` means unknown. |
| `status` | u32 bitmask | FIFO transport/service status. Zero alone is eligible for qualification. |
| `backend` | text | Always `pio_wait_cumulative_snapshot_fifo_irq_v2`. |

Canonical header:

```csv
record_type,schema_version,session,snapshot_sequence,cumulative_down_counter,reference_sequence,reference_timestamp_ticks,timestamp_uncertainty_ticks,status,backend
```

For adjacent records in one session:

```text
interval_count = (previous.cumulative_down_counter
                  - current.cumulative_down_counter) mod 2^32
service_delta = (current.reference_timestamp_ticks
                 - previous.reference_timestamp_ticks) mod 2^32
recognition_interval_min = service_delta - current.timestamp_uncertainty_ticks
recognition_interval_max = service_delta + previous.timestamp_uncertainty_ticks
```

The service coordinate and uncertainty bound the possible PIO recognition
interval. They do not claim a D14 latch timestamp, measured capture-to-service
latency, or timing derived from D8. `timestamp_uncertainty_ticks >= 2^31` is
ambiguous for modular interval selection. `UINT32_MAX` must be paired with
`TIMESTAMP_UNBOUNDED`.

Status bits are:

| Bit | Name | Meaning |
|---:|---|---|
| 0 | `TIMESTAMP_AMBIGUOUS` | More than one committed word was drained in the IRQ batch; every word in that batch carries the bit. |
| 1 | `TIMESTAMP_UNBOUNDED` | No retained FIFO-empty lower bound exists; uncertainty is `UINT32_MAX`. |
| 2 | `PIO_RXSTALL` | The PIO reported a stalled push. |
| 3 | `RING_FULL` | The bounded software ring could not accept another committed FIFO word. |
| 4 | `IRQ_BUDGET_EXHAUSTED` | The FIFO source remained asserted after the bounded eight-word drain. |

Any nonzero status prevents qualification. Unknown status bits are invalid.
The first record in a session is an anchor only. Sequence continuity is modulo
2^32 within a session; a rearm opens a fresh nonzero session and cannot bridge
an interval.

`REF` is emitted as a canonical raw derivative of the same owner and retains its
own serial event numbering. Host replay audits that derivative for preservation
and wire integrity, but it does not search an independent REF stream to decide
which PIO word a SNP belongs to. `CNT` remains the derived adjacent-SNP count and
must reproduce the raw cumulative arithmetic and service-coordinate endpoints.

The accepted-reference selector uses the complete possible recognition interval
against the frozen `1,000,000 ± 1,250` tick criterion. A candidate is early only
when its maximum possible interval is below the lower bound. Acceptance requires
the minimum and maximum both inside the bounds. An overlap with a boundary loses
qualification as `ObservationAgeAmbiguous`; unknown uncertainty and every
nonzero status are likewise ineligible.

## Capture recognition and static digital bound

The D14 test precedes `IN X,32` by one PIO clock without an intervening change
to X. Before that test, D8 WAIT instructions make recognition depend on D8
transitions. Under the explicitly proved synchronized-D8 dwell envelope of
4–9 PIO clocks per high/low phase, an armed D14 high held through recognition
reaches IN within ten clocks. This conditional implementation bound is not an
individual hardware timestamp, physical pin guarantee, or live verification
of that dwell envelope. It must not tighten `timestamp_uncertainty_ticks` or
replace the timer-domain recognition bracket. See [the current assessment](../docs/50_SOFTWARE/PPS_CAPTURE_CURRENT_ASSESSMENT_2026_09_19.md).
