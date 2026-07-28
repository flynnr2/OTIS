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

Historical count-readiness keys use component `fc0` even when the active backend
is not physically FC0. They are compatibility status surfaces:

| Component | Key | Meaning |
|---|---|---|
| `fc0` | `fc0_observed_valid` | latest count observation was bounded and internally coherent |
| `fc0` | `fc0_valid_for_control` | startup inhibit has expired and enough clean windows have followed it |
| `fc0` | `fc0_fault` | a post-inhibit count window was invalid |
| `fc0` | `last_window_invalid_reason` | latest count-window anomaly reason |
| `fc0` | `consecutive_bad_windows` | consecutive invalid count windows |
| `fc0` | `total_bad_windows` | invalid count windows observed in this boot |

PPS-gated ratio runs add component `pps_gate`:

| Component | Key | Meaning |
|---|---|---|
| `pps_gate` | `backend` | selected PPS-gated backend name |
| `pps_gate` | `state` | `idle`, `armed`, `open`, or `fault` |
| `pps_gate` | `valid` | latest bounded PPS-gated window validity |
| `pps_gate` | `last_reason` | latest PPS-gate validity or fault reason |
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

`ratio_available` is a validity indicator, not a firmware-emitted numeric ratio.
Host analysis derives the actual ratio and frequency from `CNT`, `REF`, and run
metadata.

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

## Diagnostics Migration

`health_v1` remains the compatibility status contract. First-class diagnostic
findings are additive and are documented in `diagnostics_draft_v0.csv.md`. Host
replay may derive `DIAG` rows from `STS`, `REF`, `CNT`, `DAC`, manifests, and
reports, but must not remove or rewrite the original `STS` rows.
