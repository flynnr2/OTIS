# PPS Ownership Architecture

## Decision

PPS has two independent read-only observers with different authority:

- the single PIO state machine owns the oscillator count and physical count
  snapshot boundary; and
- the D14 GPIO IRQ owns a reconstructed REF timestamp and physical-presence
  diagnostic event.

Neither observer substitutes for the other. The optional D10 input is a third,
diagnostic-only witness. DMA and foreground transport or associate truth but do
not own it.

The hard rule is:

> Physical measurement boundaries are hardware-owned. ISRs may transport or
> annotate already-latched truth but may not define the aperture.

## Event flow

```text
                       D14 / GPIO26 PPS
                         /             \
                        /               \
            PIO JMP PIN                 GPIO IRQ
                 |                         |
 D8 oscillator -> one PIO SM              +-- timestamp + compact REF record
 WAIT PIN          X-- / IN X,32           +-- physical PPS progress
                 |                         |
          immutable SNP word               |
                 |                         |
         joined FIFO -> DMA                |
                 |                         |
                 +--------- foreground association
                                  |
                         adjacent X difference
                                  |
                  raw SNP + REF + bounded CNT + STS

D10 / GPIO5 witness -> separate compact ISR record -> diagnostics only
```

## Authority by field

| Evidence | Owner | Meaning |
|---|---|---|
| `SNP.cumulative_down_counter` | PIO state machine | immutable cumulative 32-bit down-counter copied at PIO-recognized PPS |
| `SNP.snapshot_sequence/session` | DMA transport plus backend session state | continuity/ownership metadata; DMA does not define the value or boundary |
| `REF.timestamp_ticks` | D14 GPIO IRQ | reconstructed RP2040 timer observation of physical PPS |
| `CNT.counted_edges` | foreground arithmetic over adjacent PIO snapshots | `previous_X - current_X mod 2^32`; no foreground time participates |
| `CNT.gate_open/close_ticks` | associated adjacent D14 records | reference/gate-time evidence, not the count aperture |
| D10 witness | D10 minimal ISR/foreground diagnostics | independent corroboration only; never a voting authority |

## Deterministic association

The D14 ISR captures one timer tick and publishes one fixed-size record. It
does not touch PIO, DMA, or the counter. Foreground pairs the next contiguous
PIO snapshot with the next D14 source sequence in the same acquisition
session. Cross-type serial order is irrelevant; sequences, sessions, and raw
timestamps are authoritative.

The first pair after boot or rearm establishes an anchor only. A clean `CNT`
requires an adjacent PIO sequence, adjacent D14 source sequence, one session,
acceptable REF interval/flags, valid snapshot status, and an unambiguous
counter delta.

If a second D14 REF is waiting while the first has no PIO snapshot, association
is immediately lost, even if a snapshot word has appeared by the time
foreground notices the second REF. Firmware rearms the PIO/DMA session, clears
all old transport/pairing state, and requires two fresh snapshots. No later
word is paired retroactively with the unmatched REF. The first new-session
snapshot is the anchor and its adjacent successor is the first CNT candidate.
`pps_gate/association_state`, `association_loss_reason`, and the saturating
loss/recovery counters expose this transition. The unmatched REF remains raw
evidence; no synthetic SNP or CNT is created for it.

## Presence, backlog, and diagnostics

Physical PPS presence follows the D14 hardware/ISR producer marker, not
foreground drain or telemetry time. One continuous outage creates one missing
transition; repeated watchdog polls do not create new outages. A later new D14
event creates one restoration transition. Optional reminders use their own
counter.

PIO snapshot production, snapshot drain, measurement reconstruction, telemetry
emission, control consumption, foreground backlog, and telemetry backpressure
are separate progress planes. Backlog within capacity can delay reporting but
cannot alter captured count values or become `reference_missing_pps`.

## Failure behavior

- D14 ring overflow is a capture/storage fault, not proof that physical PPS is
  absent.
- PIO snapshot sequence gap/duplicate, D14 source-sequence mismatch, session
  change, RX stall, DMA error/stop, or snapshot-ring overwrite invalidates
  continuity.
- Missing PPS with a continuing oscillator may produce a later long snapshot;
  reference validity rejects it.
- A narrow malformed D14 pulse may produce REF without SNP. The event is
  reported as `ref_without_snapshot`, closes the old association, invalidates
  the affected interval, and cannot be bridged by a later snapshot.
- A stopped oscillator parks the PIO state machine in `WAIT`. D14 continues;
  missing snapshot association fails closed and resumption begins a new
  session.
- Short, long, duplicate, bounce, glitch, or otherwise malformed PPS evidence
  remains raw and diagnostic, but cannot become control-valid measurement.
- The checked-in backend remains `backend_qualified=false`, so no PPS-gated
  observation authorizes actuation.

## Validation obligations

1. Every candidate `CNT` must reconstruct exactly from adjacent raw `SNP`
   values.
2. Snapshot and D14 source sequences must be contiguous and associated REF
   timestamps must be present in raw evidence.
3. Quiet/load changes may alter backlog and reporting latency but not raw count
   distribution or mean beyond the reviewed thresholds.
4. One outage/restoration must produce exactly one transition each.
5. D14 and D10 ISR bodies must remain bounded event-preservation paths with no
   policy, formatting, serial, floating point, PIO, or DMA choreography.

See `PPS_PIO_PROOF_AND_VERIFICATION.md`,
`PPS_GATED_RATIO_BACKEND_DESIGN.md`, and
`ISR_AND_PPS_DIAGNOSTICS_REMEDIATION.md` for the detailed proofs and rules.
