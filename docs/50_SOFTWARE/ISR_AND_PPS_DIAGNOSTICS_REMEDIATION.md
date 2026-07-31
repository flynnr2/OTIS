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

Costs below are source-level upper bounds, not bench timing measurements.

| Source / handler | Trigger and effective frequency | State read | State written | Peripheral and queue operations | Branches / loops / calls | Policy in ISR | Cost and justification |
|---|---|---|---|---|---|---|---|
| D14 GPIO26 / `handle_capture_edge` | Configured GPIO edge; nominal PPS is 1 Hz, malformed bursts remain input-limited | RP2040 `timerawl`, one `gpio_get`, immutable channel/config scalars, ring head/tail | One compact `OtisCapturedEdge`, ring head, raw D14 producer sequence or accepted capture sequence; ring drop counter on full | Direct timer/GPIO reads; one bounded capture-ring push | Fixed configuration/level branches and one capacity branch; no loop; calls only the inline timer helper, SDK GPIO read, and fixed push | None | Constant time: one timer register read, one GPIO register read, one fixed record copy. Sequence increments remain because they preserve causality and expose gaps. |
| D10 GPIO5 / `handle_d10_witness_edge` | Diagnostic rising edge; nominal 1 Hz plus malformed bursts | RP2040 `timerawl`, one `gpio_get`, witness ring head/tail | One `D10WitnessEvent`, ring head, saturating raw/overflow/buffered counters | Direct timer/GPIO reads; one bounded witness-ring push | One capacity branch; no loop; fixed helper calls only | None | Constant time. Timestamp and sampled level are the minimum witness evidence; level statistics, intervals, and burst classification are deferred. |
| Divided oscillator GPIO / `handle_tcxo_observation_edge` | Only the explicitly divided GPIO-counter profile; rate must satisfy that profile's interrupt-safe constraint | `tcxo_edge_count` | `tcxo_edge_count` | None | One increment; no branch, loop, or call | None | Minimum possible software edge counter. The counter is gate-bounded and read/reset by foreground; raw MHz input is prohibited. |

No timer/alarm, DMA IRQ, PIO IRQ handler, serial/USB interrupt callback,
core-to-core IRQ, or pseudo-PPS CPU ISR is registered by OTIS firmware. The
pseudo-PPS completion PIO IRQ flag is polled in foreground; snapshot DMA is
polled transport; serial framing runs from the bounded foreground service
loop. Arduino/core-internal interrupt machinery is outside repository-owned
callback code and has no OTIS policy callback.

There are no serial calls, formatting, floating-point operations, estimators,
control decisions, dynamic allocation, policy classifiers, PIO stop/start/read,
or DMA manipulation in repository-owned handlers. Static tests extract the
actual handler bodies, require direct RP2040 GPIO/timer reads for D14/D10, and
enforce the principal prohibitions.

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
preserves the event. Its sampled-level counts and latest timestamp also move in
foreground from the queued raw record. D14 sampled-level counts, accepted
counts, latest timestamps, and interval classification likewise update only
when foreground drains the immutable capture record.

## Queue and counter audit

| Queue / transport | Capacity and overflow | Continuity response |
|---|---|---|
| D14/general capture ring | 31 usable fixed records; reject-new on full; saturating drop counter; no overwrite | Producer sequence plus drop status exposes loss. PPS association cannot silently recover through a dropped REF. |
| D10 witness ring | 15 usable fixed records; reject-new on full; saturating overflow counter; no overwrite | D10 is diagnostic-only; overflow remains explicit and cannot validate/rearm PPS. |
| REF/SNP association ring | 127 usable fixed records; reject-new; saturating drop counter and overflow-pending flag | Overflow flags the next evidence, fails measurement validity, and cannot rearm physical state merely by draining. |
| PIO RX + snapshot DMA ring | 8-word RX FIFO and 128-word SRAM ring; producer-distance overwrite detection; saturating overwrite/continuity/fault counters | Transport stops or association rearms; unread words are discarded and a fresh anchor plus adjacent snapshot is required. |

Diagnostic counters that may persist for a boot now saturate where silent wrap
would mislead. D14 capture sequences intentionally retain modulo-2^32 wrap
semantics because adjacency across `UINT32_MAX -> 0` is part of the wire
contract. The divided-edge measurement counter is reset every bounded gate and
is not a lifetime diagnostic.

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
