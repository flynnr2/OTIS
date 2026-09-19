# health_v1.csv

## Purpose

`health_v1.csv` records operational state, counters, warnings, capability
outcomes, and command snapshots. It uses the `STS` record family and remains
separate from canonical `REF`, `EVT`, `CNT`, and controller evidence.

Status is not a synthetic capture channel. An `STS` row cannot replace a raw
observation, establish a missing timestamp, or silently repair incomplete
evidence.

## Schema

| Field | Type | Meaning |
|---|---|---|
| `record_type` | enum | always `STS` |
| `schema_version` | uint | currently `1` |
| `status_seq` | uint32 | strictly increasing status-record sequence within a current capture segment; rollover is not admissible inside that segment |
| `timestamp_ticks` | uint64 | timestamp in `status_domain` |
| `status_domain` | string | declared timestamp domain |
| `component` | string | emitting subsystem |
| `status_key` | string | component-local field name |
| `status_value` | string | field value |
| `severity` | enum | `INFO`, `WARN`, `ERROR`, or `FATAL` |
| `flags` | uint32 | `capture_flags_v1` bitmask |

## Current fixed measurement path

D14 is the sole reference authority. D8 is the sole oscillator-count input.
The fixed count path uses one continuously running PIO counter on D8 and a
bounded RX-FIFO IRQ that drains each D14-triggered cumulative snapshot into one
software ring. There is no selectable count or reference-capture profile in
current firmware.

Component `pps_gate` reports the independent validity dimensions needed to
interpret that path:

- `reference_validity` and `reference_reason` describe the D14 side;
- `count_validity` and `count_reason` describe the D8 count side;
- `boundary_validity`, `aperture_validity`, and
  `observation_pair_validity` retain the atomic-boundary, physical-aperture,
  and adjacent-pair conclusions;
- `fifo_continuity`, sequence, backlog, overflow, and dropped counters retain
  transport continuity evidence;
- `capture_state`, `capture_loss_count`, and `capture_loss_reason` retain the
  fail-static state of the single-owner capture path;
- `snapshot_producer_ordinal`, `snapshot_consumer_ordinal`, backlog, high-water,
  ring-full, IRQ-budget, RXSTALL, and timestamp-ambiguity counters retain the
  specific FIFO service and continuity evidence; ordinal fields are not
  sequences and the retired `snapshot_*_sequence` keys are not current status;
- `state`, `valid`, `last_reason`, startup/requalification fields, and
  `control_eligible` state the current fixed-path conclusion; and
- implementation/provenance fields identify the PIO/FIFO-IRQ owner, counter
  width/direction, service-coordinate semantics, resolution, and resources.

Reference and count validity remain independent. A D14 fault must not be
reported as a bad oscillator count, and a D8 fault must not be reported as a
bad reference. Lifetime anomaly counters remain evidence of prior events; they
do not permanently poison a subsequently requalified path.

`ratio_available` is a validity indicator, not a numeric ratio. Host analysis
derives ratio and frequency from canonical `CNT`, `REF`, status, and manifest
inputs. Unknown uncertainty is emitted as `unavailable`, never zero.

## Command snapshots

`CONFIG?` and `COUNT?` publish bounded snapshots. Begin/complete generation
markers make partial, duplicated, or mixed-generation results ineligible.
Core 1 owns timing state; Core 0 transports immutable snapshot messages and
does not reconstruct timing state from live getters.

`ACTIVE SNAPSHOT <nonce>` publishes component `adaptive_hybrid` under
[`adaptive_hybrid_active_status_snapshot_v2.md`](adaptive_hybrid_active_status_snapshot_v2.md).
Every canonical field must appear exactly once between equal non-zero
generation markers. A command-bearing consumer may also require the solicited
nonce. A newer incomplete generation prevents fallback to an older eligible
one.

Component `adaptive_hybrid_setup` records the correlated setup lifecycle and
its command, authorization, status-generation, query-nonce, session, code, and
DAC-epoch identities. The current acceptance event is `request_accepted`.
Rejecting or contradictory identity is terminal for that one setup attempt;
there is no compatibility retry path.

## GNSS qualification

Component `gnss_receiver` reports the fixed boot promotion to 115200, exact
receiver/output qualification, parser and UART continuity, metadata freshness,
and requalification state. GNSS metadata qualifies the receiver that supplies
D14; it cannot replace D14 timing authority. A recoverable metadata anomaly
holds new corrections while D14/D8 capture and canonical evidence continue.

## D9, D6, and D10

Component `forwarded_clock_output` reports the fixed D8/GPIN0 to D9/GPOUT0
configuration and readback. This is digital configuration evidence, not an
analog waveform, loading, jitter, or independent-frequency claim.

Component `forwarded_clock_monitor` and its queue-health fields describe the
fail-local D6 diagnostic path. D6 status has no reference, regulation,
actuation, abort, or terminal authority.

Component `external_event` reports D10/channel 0 as `not_implemented` in the
fixed firmware. D10 remains an optional external-event contract only. Its
absence, noise, invalidity, or overflow cannot enter D14/D8 validity, setup,
regulation, actuation, or a run terminal.

## Boot and resource evidence

Component `boot_capabilities` reports the outcome of each fixed capability as
`Ready`, `OptionalDegraded`, `RequiredUnavailable`, or `FatalConflict`, plus
the overall run-mode conclusion. A valid but incomplete resource registry is
`RequiredUnavailable`; an ownership conflict is `FatalConflict`. No selected
profile or profile matrix exists on current HEAD.

Component `resource_registry` reports complete, deterministic ownership of
GPIO, IRQ, PIO state machine and instruction memory, DMA, timer, and clock
resources. See
[`../docs/50_SOFTWARE/HARDWARE_RESOURCE_OWNERSHIP.md`](../docs/50_SOFTWARE/HARDWARE_RESOURCE_OWNERSHIP.md).

## Emission and interpretation

Steady state emits aggregate health at a bounded cadence. Transitions,
anomalies, explicit queries, and command transactions emit their required
detail immediately. Missing, stale, partial, duplicated, contradictory, or
out-of-order status is not clean evidence.

Offline tools may derive findings from status and canonical records, but those
findings cannot erase or rewrite the original rows and have no independent
timing or control authority.

### Status producer ownership

Core 1 owns the `pps_gate` and `adaptive_hybrid` live snapshot namespaces.
Core 0 serializes their queued records but does not independently publish
copies of their fields. A core-0 `CONFIG?` response may interleave with either
cohort between complete serial records; it requests timing configuration with
`DiagnosticConfigQuery` instead of repeating PPS fields. The PPS snapshot
continues to publish boundary owner, aperture backend, backend qualification,
and boundary-ring capacity from the timing owner.

An interleaved record from another component does not become a PPS or ACTIVE
snapshot member. A duplicate key within either owned snapshot remains invalid,
even when both values match. There is no last-value-wins or special CONFIG
exception in the host reducer. The wire schema and timing meanings are unchanged.

### Incremental Core 0 periodic reports

The periodic service report freezes its getter results once and transports one
complete STS row per scheduling opportunity. Component `periodic_status` carries
`generation_begin`, `snapshot_ticks`, `snapshot_domain`, `incomplete_generations`
and a matching `generation_end`. The snapshot coordinate describes the retained
view's origin; each STS header keeps its actual formatting-time coordinate and
wire-ordered status sequence. This does not imply a simultaneous atomic snapshot
across all hardware and cores. Its age-dependent GNSS fields are relative to the
retained origin, not the later emission time.

Other record families and independently owned status cohorts may interleave
between complete rows. `CONFIG?`/`DUALCORE?` cancel an unfinished periodic report
with `generation_cancel` before publishing overlapping fields. A cancelled,
unclosed, duplicated or contradictory generation is incomplete diagnostic
evidence. Carrier loss may prevent an end/cancel marker; the next report's
saturating incomplete count does not repair missing rows. Core 1 PPS and ACTIVE
cohort contracts and command acknowledgements retain their existing meanings.
See [the output-service repair](../docs/50_SOFTWARE/PERIODIC_STATUS_SERVICE_REPAIR.md).

When a normal command is retained behind an incomplete output frame, bounded
input scanning continues so a later explicit `ACTIVE ABORT` can reach the timing
owner. Further normal commands cannot overwrite that retained command: they are
rejected and counted. After output resumes and the admitted command executes
once, `command/deferred_commands_rejected` reports the count since its previous
emission (saturating at UINT32_MAX). This is explicit input rejection accounting,
not a retry or command acknowledgement. The host still must not pipeline normal
commands behind an unresolved acknowledgement.
