# CX317 Active Status Snapshot v1

## Purpose

`cx317_active_status_snapshot_v1` defines one complete, coherent command-
bearing `cx317_active` status burst inside `health_v1`. It changes no CSV
columns. It defines which ordered `STS` rows may be used together for a
control-readiness or supervision decision.

## Envelope

Every burst has exactly this order:

1. `snapshot_generation_begin=<positive generation>`;
2. `snapshot_contract=cx317_active_status_snapshot_v1`;
3. each of the 29 canonical active-status fields exactly once and in the
   firmware-declared order;
4. `snapshot_generation_complete=<same generation>`.

The generation increases once per attempted snapshot and never uses zero.
Only the newest complete generation is eligible. A missing field, duplicate
field, unknown contract, mismatched marker, incomplete newer generation, or
non-increasing generation makes that attempted burst ineligible. Consumers
must not fill a missing field from an older generation.

The canonical field vocabulary is owned by
`host/otis_tools/active_status_contract.py` and is source-guarded against the
shared firmware visitor used by both direct and dual-core publication.

## Decision rule

Ordinary non-active health remains latest-value telemetry. Command-bearing
consumers combine it only with one complete active snapshot selected by the
contract above. Missing complete active status is failure, never clean or
zero.
