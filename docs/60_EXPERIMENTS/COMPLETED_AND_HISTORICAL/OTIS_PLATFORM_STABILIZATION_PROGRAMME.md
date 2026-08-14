# OTIS Platform Stabilization Programme

## Status

**Completed 2026-08-11.** All P0-P7 completion criteria passed. The reviewed
result and exact evidence identities are recorded in
`OTIS_PLATFORM_STABILIZATION_COMPLETION_REPORT.md`.

CX318 Stage 5 remains suspended. Completion of this programme does not resume
it or authorize a successor campaign. The interrupted Stage 5 work is
incomplete, unsealed, and not promotable, and it must not be resumed from its
old profiles or artifacts. A new programme identity still requires an explicit
operator decision.

The operator approved this programme on 2026-08-11 with the following
decisions:

- platform stabilization is the only current programme priority;
- the tracked CX318 record is the complete Stage 5 record; no later rehearsal
  or seal exists;
- the current scientific claim is bounded experimental frequency and
  arbitrary-epoch relative-phase evidence;
- there are no external contract consumers and no backward-compatibility
  obligation at this development stage;
- raw evidence remains content-addressed outside Git for now, with a future
  reviewed mothball/deletion gate after OTIS is stable and mature;
- product/hardware abstraction is deferred until a concrete second target
  exists;
- the existing bench environment and characterized `0xA800..0xAB00` DAC
  envelope remain applicable.

## Non-negotiable invariants

1. Hardware capture establishes timing truth.
2. CPU, ISR, USB, logging, storage, and host scheduling do not define the
   authoritative aperture.
3. Canonical observations remain distinct from derived, diagnostic,
   estimated, and controlled values.
4. Missing evidence is never interpreted as clean or zero.
5. Association loss, sequence gaps, resets, and DAC epochs break continuity
   explicitly.
6. Mutable state and hardware resources have one owner.
7. Requested, accepted, applied, and observed control phases remain distinct.
8. Serialized evidence is never actionable authority.
9. Serial capture has one continuously draining owner.
10. Failed and incomplete attempts remain explicitly identified.
11. Abstraction requires demonstrated repeated semantics.

## Baseline at programme start

The clean repository baseline at commit
`71c4044fb782f273276ed8b10a3180a995f6d388` produced:

- Python suite: `962 passed`, `2 skipped`, `1 failed`;
- sole Python failure:
  `test_repository_wide_measurement_semantics_inventory_is_current`;
- failure reason: the tracked measurement-semantics inventory was stale after
  the review prompt was added;
- pinned Arduino environment: CLI `1.4.1`, RP2040 core `6.0.0`,
  `arm-none-eabi-g++` `16.1.0`, with installed-byte hashes matching the matrix;
- firmware matrix: all 26 expected-pass profiles compiled and all 15
  expected-fail profiles failed with their named guard.

Historical test or build reports are not current-baseline evidence.

## Work sequence and gates

### P0 — Mothball CX318 Stage 5

- mark the programme suspended, incomplete, unsealed, and non-promotable;
- preserve the exact failed-attempt narrative and content identities;
- exclude Stage 5 from active/default campaign verification;
- prevent accidental use of its promotion path;
- define new stabilized-platform prerequisites for any future restart.

### P1 — Establish current platform truth

- correct timing-ownership, lifecycle, roadmap, and matrix documentation;
- restore generated-inventory integrity;
- record a reproducible current Release baseline.

### P2 — Stabilize runtime foundations

- replace mixed-age status aggregation with complete, versioned, fresh
  snapshots;
- bound boot, command, transport, shutdown, and acknowledgement waits;
- enforce stack, SRAM, queue, PIO/DMA, and transport budgets;
- add deterministic regression scenarios for every escaped platform failure.

### P3 — Reset contracts and policy ownership

- establish one current machine-readable wire-contract authority;
- remove obsolete aliases and compatibility-only readers;
- establish one identified policy source across firmware, host, manifests, and
  telemetry;
- make missing evidence fail closed in every current analyzer.

### P4 — Establish verification and profile lifecycle

- encode Fast, Standard/Campaign, Release, Bench, and historical tiers;
- keep current safeguards in default verification;
- move completed programmes out of default verification;
- retire assets with no current, diagnostic, safety, or evidentiary purpose.

### P5 — Qualify the bounded metrology claim

- distinguish receiver availability from physical PPS qualification;
- create an evidence-backed bounded uncertainty statement;
- characterize physical capture limitations;
- make nominal phase units unambiguous.

### P6 — Consolidate the platform

- consolidate serial ownership, preflight, supervision, abort, analysis, and
  sealing as platform behavior;
- decompose the firmware coordinator along existing ownership boundaries;
- remove superseded programme structure after behavioral equivalence is
  verified.

### P7 — Evidence lifecycle and completion

- maintain a content-addressed evidence index outside Git;
- define mothball and future deletion prerequisites;
- pass the final Release gate and a complete non-actuating platform rehearsal.

## Stage 5 restart gate

Stage 5 may be reconsidered only after P0-P7 complete. A restart requires a new
programme identity, new profiles created from the stabilized platform, a frozen
exact bundle, and a fresh successful no-write rehearsal. Old interrupted
profiles do not acquire current authority merely because they still compile.

## Current scientific boundary

OTIS may presently support bounded experimental frequency and arbitrary-epoch
relative-phase evidence. It does not claim traceable absolute frequency,
calibrated phase, UTC, lock, or holdover. Units, diagnostics, reports, and
profiles must not imply those stronger claims.

## Evidence retention and future deletion

Raw packages remain outside Git and should retain a content hash, source/build
identity, profile identity, attempt classification, result or failure reason,
analyzer identity, and storage location. A package may be mothballed when no
active investigation depends on it and its lessons are captured in reviewed
tests or documentation.

Raw deletion requires a later declared stable/mature milestone, no unresolved
dependency, a reviewed compact summary and identity record, and explicit
operator approval. Tracked summaries and hashes normally remain after raw
deletion.

The executable index and the full mothball/deletion gates are defined in
`docs/50_SOFTWARE/EVIDENCE_LIFECYCLE.md`.

## Completion criteria

The programme is complete only when:

1. Stage 5 cannot be accidentally promoted or resumed;
2. architecture and lifecycle documentation are current;
3. generated inventories and the current Release gate pass;
4. command decisions consume one complete, fresh status snapshot;
5. operational waits are bounded;
6. memory, queue, resource, and transport margins are evidenced;
7. escaped failure classes have deterministic regression coverage;
8. one current contract authority and one policy identity exist;
9. obsolete compatibility and programme scaffolding are removed;
10. verification tiers and profile lifecycle are executable;
11. the bounded metrology claim is bench-supported and honestly limited;
12. platform orchestration is separated from campaign policy;
13. a non-actuating exact-bundle rehearsal exercises capture, obstruction,
    abort, analysis, and sealing successfully.

All thirteen criteria passed on 2026-08-11. The machine-readable programme
status therefore records no active programme rather than selecting a next
campaign implicitly.
