# OTIS Platform Stabilization Completion Report

## Decision

The OTIS platform-stabilization programme passed its completion gate on
2026-08-11. P0-P7 are complete.

This result authorizes no campaign progression. CX318 Stage 5 remains
suspended, incomplete, unsealed, and non-promotable. Reconsidering that work
requires an explicit operator decision, a new programme identity, new profiles
derived from the stabilized platform, and a fresh no-write rehearsal.

## Delivered platform state

- Stage 5 creation, execution, and promotion paths fail closed under the
  tracked programme-status authority.
- PIO establishes the physical aperture; IRQ timestamps are explicitly
  observer/diagnostic evidence.
- Active decisions consume one versioned, complete, fresh status snapshot.
- Boot, serial, command, acknowledgement, obstruction, handoff, abort, and
  shutdown waits are bounded.
- Static SRAM reserve and live stack/heap observations are explicit; queue,
  PIO/DMA, registry, and transport margins fail closed when unavailable.
- `diagnostics_v1`, the current file contracts, and bounded active policy v2
  are the sole current authorities. Compatibility-only v0 surfaces were
  removed because there are no external consumers.
- Fast, Standard/Campaign, Release, Bench, and Historical profile lifecycles
  are executable. Archived programme profiles are outside default checks.
- The current metrology claim is limited to bounded experimental frequency
  and arbitrary-epoch relative phase; the missing physical and calibration
  components remain unavailable.
- Serial ownership, exact flash, obstruction, priority abort, same-owner
  evidence rotation, analysis, sealing, and external evidence registration are
  one current platform workflow.
- Firmware count-path status and live memory observation are owned modules
  rather than coordinator-local implementations.
- Raw-package deletion remains unavailable. Content-addressed retention and a
  reviewed mothball gate exist; future deletion still requires the declared
  stable/mature milestone and explicit operator approval.

## Final Release gate

The final no-hardware Release gate passed after the last operational firmware
change:

- Python/native suite: `987 passed`;
- current Release firmware profiles: 18 expected-pass builds passed;
- permanent structural guards: 14 expected-fail builds failed for their named
  reasons;
- pinned Arduino CLI 1.4.1, RP2040 core 6.0.0, and GCC 16.1.0 identities were
  verified;
- all firmware builds passed `otis_firmware_resource_budget_v1`; and
- all wire fixtures and the example validation/report path passed.

The exact Bench build reported 111,560 bytes of static dynamic-memory use and
150,584 bytes available for runtime stack and heap, against the required
minimum runtime reserve of 104,858 bytes.

## Bench attempts and escaped defects

Two finite non-actuating attempts failed one analysis gate each. Both were
retained outside Git and registered as `failed_rehearsal` evidence:

1. `rehearsal_20260811T082901Z`, content identity
   `3934c054ad582573ac0d3a7755469bea74e09dde9fbb73d5d298a10534af1e0f`:
   `CONFIG?` did not expose `pps_gate/snapshot_ring_capacity`. Nine count and
   nine snapshot rows were present and every other gate passed. The defect was
   moved into an explicit source regression.
2. `rehearsal_20260811T085559Z`, content identity
   `c2cbfa33968c80ec2ba8f5264c3c4a80930b9ed63ddcbf0861589059cf279901`:
   the snapshot backlog high-water was still periodic rather than explicitly
   queryable, so the short handoff could occur before it was emitted. Eight
   count and eight snapshot rows were present and every other gate passed. The
   explicit `FC0?` response now includes the live PPS queue state.

These were platform defects caught by the completion rehearsal, not scientific
rejections and not campaign escapes.

## Successful exact-bundle rehearsal

The successful package is local ignored evidence at
`runs/platform_stabilization/rehearsal_20260811T085859Z`:

- run status: complete;
- actuation and preview authority: compiled out;
- PPS physical qualification promotion: disabled;
- exact profile: `cx317_fixed_code_baseline`;
- firmware source identity:
  `d4241b09b6b96cbe34062e28631a10e723a7a2faa22e04ef4080602f7a100c90`;
- firmware configuration identity:
  `c9bcace83cfdbf859256d431928c311d76a9ccbf337865494eaa67a7f3738a8f`;
- UF2 identity:
  `cd9b3b7df6dd8716f683d3706841cc2e5a52c61bf57ecc9d08e10530128bae67`;
- board serial: `503533748A919118` before and after the single flash;
- observations: 10 count rows and 10 aperture snapshots;
- snapshot queue high-water/capacity: 1/128;
- minimum observed Core 0 free stack: 7,736 bytes;
- minimum observed free heap: 149,456 bytes;
- commands sent, in order: `CONFIG?`, `DAC?`, `FC0?`, `ACTIVE ABORT`;
- normal FIFO obstruction: saturated with 256 timestamped queued queries;
- priority abort: observed before stale normal work;
- capture PID: 38,815 before and after obstruction and through logical
  evidence rotation;
- serial reopen/reconnect count: zero;
- actuation rows and fatal status rows: zero;
- all nine analyzer criteria: pass;
- evidence snapshot digest:
  `e9db83707d2151c114bd47374a63a7f606235110a8498fa33d685d5c3ea5b1c9`;
- pass seal identity:
  `75a484e128afed3c2bf017fb2a6a8292eaf5d0ac4b171ba762dbbe0978d61c81`;
- complete package content identity:
  `d29f182c5b0c0735eef48a51d413684d4b7168294ca5097c61b924272aa2841e`.

The external `otis_evidence_index_v1` validates all three registered package
identities against their retained locations.

## Claims boundary

This is non-actuating platform execution evidence. It is not a calibration and
does not establish traceable absolute frequency, calibrated phase, UTC, lock,
holdover, receiver/cable/pad delay, physical PPS qualification, or combined or
expanded measurement uncertainty. Those limitations remain governed by
`../50_SOFTWARE/CURRENT_METROLOGY_CLAIM.md`.
