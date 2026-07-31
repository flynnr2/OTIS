# ISR and PPS Diagnostics Remediation

Status: implemented for the PPS hardware-snapshot candidate
Date: 2026-07-31

## Hard rule

Physical measurement boundaries are hardware-owned. ISRs may preserve or
annotate already-latched truth, but they may not define the count aperture.

An OTIS interrupt handler is limited to reading or acknowledging its event,
capturing immutable scalar state, publishing one compact fixed-size record or
updating a monotonic field, and returning. Formatting, serial I/O, floating
point, diagnostic policy, estimation, control, allocation, retries, blocking
loops, and multi-stage peripheral choreography belong outside interrupt
context.

## ISR inventory after remediation

| Handler | Trigger/rate | ISR work | Shared state | Deferred work | Bounded path |
|---|---|---|---|---|---|
| `handle_capture_edge` | D14 PPS, nominal 1 Hz; other sparse capture modes | Read timer tick and input level; construct one `OtisCapturedEdge`; attempt one fixed ring push; increment monotonic counters | Capture ring indices/record, D14 raw/latest counters | Interval classification, REF telemetry, PIO/D14 association, snapshot reconstruction, diagnostics and control preview | One timestamp read, one GPIO read, one ring-capacity branch/copy; no loop |
| `handle_d10_witness_edge` | D10 diagnostic witness, nominal 1 Hz plus malformed bursts | Read timer tick and input level; construct one `D10WitnessEvent`; attempt one fixed buffer push; increment monotonic counters | Witness ring indices/record and raw/latest counters | Interval arithmetic, short/long/burst classification, diagnostics | One timestamp read, one GPIO read, one buffer-capacity branch/copy; no loop |
| `handle_tcxo_observation_edge` | Deliberately divided GPIO counter profile only | Increment one volatile counter | `tcxo_edge_count` | Gate timing, reset/read, classification and telemetry | One increment |

There are no serial calls, formatting, floating-point operations, estimators,
control decisions, dynamic allocation, policy classifiers, PIO stop/start/read,
or DMA manipulation in these handlers. Static tests extract the actual handler
bodies and enforce the principal prohibitions.

## Removed interrupt responsibilities

The rejected D14 boundary callback disabled the oscillator PIO state machine,
injected instructions, sampled the FIFO, reset/reloaded the counter, and
restarted counting from the GPIO ISR. That sequence made variable CPU latency
part of the physical aperture. It has been removed.

The D14 ISR is now only an independent physical REF observer. The single PIO
state machine owns oscillator counting and the cumulative PPS snapshot. DMA
transports the already-owned snapshot. Foreground associates the immutable PIO
word with the queued D14 record and rejects any mismatch.

D10 previously computed intervals and applied short/long policy in its ISR.
Those operations now run in `otis_pps_dual_observer_service`; the ISR only
preserves the event.

## Separate progress planes

`OtisPpsDiagnostics` retains independent markers for:

- latest physical D14 PPS arrival;
- latest PIO snapshot produced;
- latest snapshot drained;
- latest measurement reconstructed;
- latest snapshot telemetry emitted; and
- latest control/preview consumer observation.

It also retains foreground backlog depth/capacity/high-water and a separate
telemetry-backpressure state. Snapshot drain, telemetry service, and control
progress cannot change physical PPS presence.

## Outage state machine

The physical watchdog has three states: `never_seen`, `present`, and `missing`.
Only a new D14 producer sequence can establish or restore presence. One
continuous timeout produces exactly one `physical_pps_missing` transition and
increments the outage counter once. Optional reminders use a distinct event and
counter. A later new D14 event produces one `physical_pps_restored` transition.

Timer intervals use the repository's RP2040 timer wrap arithmetic. Producer
sequence continuity uses unsigned 32-bit adjacency, including
`UINT32_MAX -> 0`. A foreground queue gap is recorded independently and does
not masquerade as a new physical outage.

## Fault taxonomy

The implementation keeps these concepts distinct:

| Plane | Examples |
|---|---|
| Physical reference | missing/restored, short, long, duplicate/extra, bounce/glitch |
| Hardware snapshot | snapshot absent, sequence gap/duplicate, session change, PIO RX stall |
| Capture/storage | D14 ring overflow, DMA error/stop, snapshot SRAM overwrite |
| Service plane | foreground backlog/high-water, telemetry backpressure |
| Measurement | stale, zero/out-of-envelope count, invalid association, reacquisition anchor |

Storage exhaustion is a fail-closed continuity loss. Continued physical D14
progress with delayed foreground drain raises backlog evidence but does not
raise `reference_missing_pps` and cannot alter an immutable PIO snapshot.

## Timing witness

No additional ISR witness pin is enabled in normal firmware. D3/GPIO15 is
reserved for the guarded pseudo-PPS generator, and the implementation does not
create a competing visibility output. A future bench-only ISR-duration witness
must receive its own centrally validated pin/profile and must remain disabled
by default; telemetry inside an ISR is not an acceptable timing witness.

## Verification

The focused C++/Python diagnostics harness covers delayed foreground service,
one outage under repeated polling, restoration, timer and sequence wrap,
backlog/backpressure, overflow separation, session reset, and exactly-once
transition counters. `tests/test_pps_snapshot_backend_architecture.py` also
checks the ISR bodies and confirms D14 has no PIO/DMA aperture control.
