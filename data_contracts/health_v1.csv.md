# health_v1.csv

## Purpose

`health_v1.csv` records device status, health transitions, counters, warnings, restart breadcrumbs, and other operational telemetry.

Health/status records are intentionally separated from event captures and oscillator observations.

Use the `STS` record family for device and pipeline state.

## Schema

| Field | Type | Meaning |
|---|---|---|
| `record_type` | enum | compact tag; always `STS` |
| `schema_version` | uint | schema revision |
| `status_seq` | uint64 | monotonic status record counter |
| `timestamp_ticks` | uint64 | timestamp in `status_domain` |
| `status_domain` | string | timestamp domain |
| `component` | string | emitting subsystem |
| `status_key` | string | compact status key |
| `status_value` | string | status payload |
| `severity` | enum | `INFO`, `WARN`, `ERROR`, `FATAL` |
| `flags` | uint32 | numeric flags from `capture_flags_v1` |

## Example

```csv
record_type,schema_version,status_seq,timestamp_ticks,status_domain,component,status_key,status_value,severity,flags
STS,1,7,1600000000,rp2040_timer0,capture,ring_fill_pct,12,INFO,0
STS,1,8,1600100000,rp2040_timer0,pps,reference_valid,true,INFO,0
STS,1,9,1600200000,rp2040_timer0,system,restart_reason,brownout,WARN,32
```

## Design Rule

Status is not a fake capture channel.

Do not encode operational telemetry as invented `EVT` rows. Keep health/state telemetry distinct from scientific timing observations.

## Count-Observation Status

Count backends emit health/status rows for backend selection, anomaly reasons,
bad-window counters, startup inhibit, and control eligibility. These rows are
ordinary `STS` records; they do not extend the CSV schema.

Backend-neutral count readiness uses component `count_path`. Hardware-specific
sample details may still name the physical backend in their values, but the
component and control-readiness keys do not imply FC0 ownership:

| Component | Key | Meaning |
|---|---|---|
| `count_path` | `observation_valid` | latest count observation was bounded and internally coherent |
| `count_path` | `control_eligible` | startup inhibit has expired and enough clean windows have followed it |
| `count_path` | `fault_latched` | a post-inhibit count window was invalid |
| `count_path` | `last_window_invalid_reason` | latest count-window anomaly reason |
| `count_path` | `consecutive_bad_windows` | consecutive invalid count windows |
| `count_path` | `total_bad_windows` | invalid count windows observed in this boot |

PPS-gated ratio runs add component `pps_gate`:

| Component | Key | Meaning |
|---|---|---|
| `pps_gate` | `backend` | selected PPS-gated backend name |
| `pps_gate` | `state` | `idle`, `armed`, `open`, or `fault` |
| `pps_gate` | `valid` | latest bounded PPS-gated window validity |
| `pps_gate` | `last_reason` | latest PPS-gate validity or fault reason |
| `pps_gate` | `reference_validity` | independent `valid`, `invalid`, or `unavailable` state for the authoritative PPS side |
| `pps_gate` | `reference_reason` | typed reference conclusion, including duplicate/short/long/missing/flagged/recovery cases |
| `pps_gate` | `count_validity` | independent `valid`, `invalid`, or `unavailable` oscillator-count state |
| `pps_gate` | `count_reason` | typed count conclusion, including valid/zero/saturated/unavailable cases |
| `pps_gate` | `boundary_owner` | timing owner, currently `pio_state_machine` |
| `pps_gate` | `aperture_backend` | physical implementation, currently `pio_wait_cumulative_snapshot_dma_v1` |
| `pps_gate` | `backend_qualified` | explicit bench-qualification gate for control eligibility |
| `pps_gate` | `boundary_sequence` | modulo-2^32 atomic boundary sequence |
| `pps_gate` | `boundary_validity` | independent count-boundary capture conclusion |
| `pps_gate` | `boundary_reason` | typed boundary capture reason |
| `pps_gate` | `aperture_validity` | independent physical counter-window conclusion |
| `pps_gate` | `aperture_reason` | typed snapshot/wrap/completeness reason |
| `pps_gate` | `observation_pair_validity` | whether two atomic boundaries form a defensible pair |
| `pps_gate` | `observation_pair_reason` | typed pair/sequence reason |
| `pps_gate` | `fifo_continuity` | `continuous`, `duplicate`, `gap`, `overflow`, or `unavailable` |
| `pps_gate` | `association_state` | `awaiting_anchor`, `anchor`, `clean`, sequence-associated `associated_invalid`, or fail-closed `lost` state |
| `pps_gate` | `association_loss_reason` | `ref_without_snapshot`, snapshot backend fault/timeout, or `none` |
| `pps_gate` | `association_loss_count` | saturating count of closed REF/SNP associations |
| `pps_gate` | `association_recovery_count` | saturating count of fresh adjacent clean pairs after association loss |
| `pps_gate` | `association_loss_reference_sequence` | D14 source sequence that could not be associated; zero until the first loss |
| `pps_gate` | `boundary_ring_depth` / `boundary_ring_capacity` | bounded ISR-to-foreground queue health |
| `pps_gate` | `boundary_ring_dropped_count` | atomic observations lost because that queue was full |
| `pps_gate` | `ratio_available` | latest bounded window is valid and has nonzero counted edges |
| `pps_gate` | `last_interval_us` | latest bounded PPS gate interval in microseconds |
| `pps_gate` | `missing_pps_count` | missing stop-PPS faults |
| `pps_gate` | `pps_interval_anomaly_count` | PPS intervals outside configured validity limits |
| `pps_gate` | `count_saturated_count` | oscillator counter saturation events |
| `pps_gate` | `accepted_window_count` | accepted PPS-gated count windows |
| `pps_gate` | `rejected_window_count` | rejected PPS-gated count windows |
| `pps_gate` | `consecutive_bad_window_count` | consecutive invalid PPS-gated windows |
| `pps_gate` | `total_bad_window_count` | invalid PPS-gated windows observed in this boot |
| `pps_gate` | `startup_inhibit_active` | startup inhibit state for control eligibility |
| `pps_gate` | `control_eligible` | latest count/PPS gate has met control-readiness requirements |
| `pps_gate` | `count_resolution_edges` | native integer count resolution, currently one edge |
| `pps_gate` | `declared_max_captured_edge_rate_hz` | conservative PIO/system-clock ceiling used only to exclude an unobservable full counter wrap; not expected oscillator frequency |
| `pps_gate` | `counter_aperture_uncertainty_ns` | evidence-backed aperture uncertainty or `unavailable` |
| `pps_gate` | `reference_frequency_uncertainty_ppb` | evidence-backed reference uncertainty or `unavailable` |

`ratio_available` is a validity indicator, not a firmware-emitted numeric ratio.
Host analysis derives the actual ratio and frequency from `CNT`, `REF`, and run
metadata.

Reference, count snapshot, boundary, physical aperture, pair, and FIFO
continuity are independent eligibility inputs. A reference-only fault must not
be rewritten as a bad oscillator count, or vice versa. Measurement validity
requires every physical/provenance dimension; control eligibility additionally
requires `backend_qualified=true` and the existing startup/recovery gates.

Steady state emits aggregate health at a bounded ten-second default cadence.
Detailed rows are emitted on a transition, anomaly, timeout, or explicit
query. `command/config_snapshot=begin` and `end` delimit each bounded
`CONFIG?` response.

Command-bearing `cx317_active` fields are a special coherent burst governed by
[`cx317_active_status_snapshot_v1.md`](cx317_active_status_snapshot_v1.md).
They must not be read as independent latest values.

## Hardware Resource Ownership Status

Firmware resource ownership is reported with component `resource_registry`.
`valid`, `complete`, `conflict_count`, and `binding_failure_count` expose the
registry outcome. Per-class claim counts include GPIO, IRQ, PIO state machine,
PIO instruction memory, DMA, timer, and clock resources. `claim_00`,
`claim_01`, and subsequent deterministic keys preserve the physical identity,
owner, role, and bound/pending state of each selected claim.

These are additive status rows. They do not replace backend-specific
initialization status or any raw timing observation. The normative ownership
map is
[`../docs/50_SOFTWARE/HARDWARE_RESOURCE_OWNERSHIP.md`](../docs/50_SOFTWARE/HARDWARE_RESOURCE_OWNERSHIP.md).

## Boot Capability Status

Firmware reports the selected boot profile and its capability gate with
component `boot_capabilities`. Each selected capability has a requirement and a
typed outcome in `requirement:outcome` form:

- `Ready`: initialization completed successfully;
- `OptionalDegraded`: an explicitly optional selected capability failed;
- `RequiredUnavailable`: a required selected capability did not initialize;
- `FatalConflict`: resource selection or ownership is invalid.

`selected_profile`, `selected_count`, `overall`, `degraded`, and `run_mode`
summarize the set. `run_mode=Ready` is emitted only after every selected
capability has a known result and every required measurement and transport
capability is `Ready`. Optional failure is therefore visible as
`overall=OptionalDegraded` and `degraded=true`; it is never represented as an
unqualified successful boot.

Registry `valid` and `complete` remain separate status keys. An invalid
registry is a `FatalConflict`; a valid but incomplete registry is
`RequiredUnavailable`, because an expected dynamic resource did not bind.

## Diagnostics relationship

`health_v1` is low-level status evidence. First-class diagnostic findings are
additive and use the sole current diagnostic contract,
[`diagnostics_v1.csv.md`](diagnostics_v1.csv.md). Host replay may derive `DIAG`
rows from `STS`, `REF`, `CNT`, `DAC`, manifests, and reports, but must not
remove or rewrite the original `STS` rows.
