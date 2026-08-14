# CX318 Relative-Phase, Hybrid-Preview and Tight-Deadband Codex Programme

## Programme suspended — 2026-08-11

The operator suspended this programme during Stage 5 because repeated platform
defects made further campaign execution scientifically and operationally
unjustified. The tracked record below is the complete execution record. No
later rehearsal, promotion, live leg, or seal exists.

The programme is **incomplete, unsealed, non-promotable, and not authorized to
resume**. Existing Stage 5 profiles and artifacts are historical failed-attempt
evidence, not current operational profiles. Do not repair the record
retrospectively, create a completion seal, reuse its promotion ledger, or infer
authority from the fact that an old profile still compiles.

Platform stabilization now proceeds under
[`../COMPLETED_AND_HISTORICAL/OTIS_PLATFORM_STABILIZATION_PROGRAMME.md`](../COMPLETED_AND_HISTORICAL/OTIS_PLATFORM_STABILIZATION_PROGRAMME.md).
Any future CX318 restart must follow that programme's completion gate and use a
new programme identity, new profiles, a newly frozen bundle, and a fresh exact
no-write rehearsal.

This folder contains the programme selected after the sealed CX317 bounded
frequency-control endurance result.

Its primary goal is:

`replayable_relative_phase_estimator_and_non_actionable_bounded_hybrid_preview`

It deliberately runs a second, already-supported learning track in parallel:

`bounded_live_validation_of_the_tighter_hysteretic_frequency_deadband`

The two tracks share measurements and evidence, but not authority. The tighter
frequency policy may use the previously qualified frequency-control transaction
path within the exact limits in the master prompt. Phase and hybrid-preview
outputs have zero actuation authority for the whole programme.

## Recommended Codex setting

Execute the complete master prompt with **GPT-5.6 Sol at Extra High reasoning**.
This is long, high-value, agentic work combining metrology semantics, replay,
firmware, live hardware, fault handling and evidence preservation. Sol/High is
reasonable for an individually supervised implementation stage, but Extra High
is recommended for the unattended master and both live campaign stages.

Terra/High is suitable for bounded supporting work such as re-running an exact
analysis, inspecting a sealed dataset or repairing a narrow test failure. Do not
use Terra as the primary model for the master execution unless usage pressure
outweighs the additional review depth. Medium is not recommended for the live
authority or final evidence decisions.

The master explicitly authorizes the Sol/Extra High lead to delegate independent
supporting work to Terra/High subagents. The lead retains contract selection,
integration, hardware control, authority, live gates and final scientific
decisions. Terra workers may accelerate evidence inspection, replay analysis,
test/log triage, disjoint implementation and documentation review, but may not
flash, arm, issue a DAC command, weaken a gate or make a programme decision.

## Execution order

1. `00_MASTER_UNATTENDED_PROMPT.md`
2. `01_EVIDENCE_AND_CONTRACT_FREEZE_PROMPT.md`
3. `02_RELATIVE_PHASE_ESTIMATOR_AND_REPLAY_PROMPT.md`
4. `03_BOUNDED_HYBRID_PREVIEW_PROMPT.md`
5. `04_FIRMWARE_PARITY_AND_LIVE_PREVIEW_PROMPT.md`
6. `05_TIGHT_DEADBAND_BIDIRECTIONAL_ACTIVE_TRIAL_PROMPT.md`
7. `06_COMBINED_STRESS_AND_FAULT_CAMPAIGN_PROMPT.md`
8. `07_FINAL_REVIEW_AND_NEXT_GOAL_PROMPT.md`

`PROGRAMME_STATE_TEMPLATE.md` is the durable campaign ledger. Copy it into the
new run directory before changing firmware or touching the bench.

## Fast-learning philosophy

This is not another conservative qualification staircase. Use the sealed CX317
evidence rather than repeating it. Implement several cheap non-actionable
estimator and preview candidates at once, replay them against all existing
evidence, put the best candidates live quickly, and deliberately exercise both
sides of the tighter frequency band.

Failure is useful when it is bounded, replayable and leaves the last confirmed
DAC state known. Do not extend a run merely to rescue a hypothesis.

## Operator amendments during execution

On 2026-08-09 the operator required a finite evidence-bearing rehearsal before
every subsequent long hardware run in this programme. The rehearsal must use
the same exact firmware/profile, authority boundary and stop conditions as the
long run, and it must pass before that long run starts. A failed rehearsal is a
stop, not permission to weaken a gate.

The operator also authorized one controlled Stage 4 premise-setting
`DAC SET 0xA828` transaction after the reboot made the external DAC register
unknowable. It is a separately captured setup stimulus, not automatic control
authority. No second Stage 4 DAC write is permitted, and phase/hybrid authority
remains zero.

The installed legacy Stage 7 profile rejected the first setup command as
`rejected_active_profile_start_only`; its captured DAC and active-transaction
files remained header-only, so no physical DAC write occurred. The replacement
setup path must first flash the dedicated `cx318_stage4_premise_setup` image.
That image is compile-time restricted to one explicit `DAC SET 0xA828` attempt
per boot, clamps both DAC limits to A828, consumes the attempt before I2C, and
excludes alternate DAC commands, sweeps, previews, controllers, dual-core
authority and GPS transmission. The host must durably latch that sole attempt
before enqueueing it and must never retry it after failure, reset or reflash.

On 2026-08-10 the first Stage 5 Leg A no-write rehearsal exposed two distinct
platform facts before any DAC transaction. The measurement path lost one
reference-to-snapshot association and correctly entered fail-static; the old
telemetry path then byte-interleaved independent chunked records. The repaired
bundle therefore gives the USB stream one exclusive chunked-frame owner and
emits a structured decision-local `ASL` record before any association-loss
rearm. A healthy Stage 5 leg requires zero `ASL` rows.

The exact rehearsal-to-live path also retains one capture PID and one open
serial handle. At the rehearsal endpoint it rotates into a command-free
transition spool, seals and analyzes the immutable rehearsal, creates the live
manifest from the passed seal, and only then rotates into the live segment.
There is no serial close/reopen or ownerless analysis interval. This complete
promotion path must pass rehearsal before another long Stage 5 run.

A later 2026-08-10 retry exposed a separate timing-core stack defect before
promotion or any DAC transaction. The first long `CTL` record contained a
12-byte overwrite inside an otherwise intact 522-byte frame, with no USB
reconnect, parser burst or surrounding record damage. Exact-build stack-usage
analysis showed that total SRAM was comfortable, but the first post-warm-up
Core 1 call chain could exceed its separate 8 KiB stack because several
1536-byte formatting and evidence-copy buffers were nested. The repair gives
each sole-producer module static formatting/copy scratch storage. On the exact
Stage 5 profile the largest timing-path frames then fell from 2224/2008/1824
bytes to 712/520/496 bytes, while static SRAM use remained approximately 52%.
A short accelerated physical discriminator subsequently emitted 247/247 intact
`CTL` records with valid UTF-8 and zero capture parser errors or reconnects.
That discriminator is diagnostic evidence only: capture began after boot and
the firmware drop counter was already 27, remaining unchanged throughout. A
fresh exact-profile no-write rehearsal from a clean build remains mandatory
before either Stage 5 setup write.

The stack-hardened exact-profile rehearsal then completed its full 2700 s
window cleanly, including an intact long `CTL` stream, both environmental
sensors, a selected 600 s estimate, exact TDB replay, zero transport or
firmware drops, and header-only DAC/active files. Promotion nevertheless
stopped in its no-authority transition because the immutable seal required
`cx317_active.dac_epoch=0`, while the dual-core status publisher had omitted
that field. The direct publisher and internal status object did contain it.
This was a host/firmware contract-integration escape, not a physical rig
failure and not evidence of a DAC write.

Before another Stage 5 hardware run, the bounded cleanup replaces the two
hand-written active-status lists with one shared 29-field firmware visitor and
uses one versioned host pre-write predicate in the supervisor, rehearsal seal,
promotion defence and offline preflight. Missing telemetry is no longer
treated as clean. The supervisor allows at most 30 s for the first complete
status burst, so the omitted-field defect would now stop cheaply rather than
at the end of a long rehearsal. Terminology is explicit throughout: `0xA828`
is the inherited Stage-4-sealed preview baseline, `0xA808`/`0xA848` is the
planned live stimulus, and physical DAC confirmation remains `unknown` until
a successful live setup transaction. The no-I/O preflight also requires the
bound clean UF2 source identity to equal the current contract-bearing firmware
source, preventing an older clean binary from borrowing the new source-tree
checks. Promotion uses deterministic rotation
operation identities plus a durable phase ledger; an immutable failed seal
ends at `REHEARSAL_RETRY_REQUIRED` and can never be retried into live.

After Stage 5, perform the operator-requested broader programme audit for
similar contract duplication, missing-as-clean predicates, late-only checks,
ambiguous state provenance and special-case lifecycle paths before entering a
later long-running stage.

## Authorization boundary

These files are a proposed programme, not standing permission to actuate the
rig. The operator must explicitly instruct Codex to execute the master prompt.
That instruction authorizes only the exact setup writes and bounded
frequency-derived corrections defined there.

It does not authorize:

- a phase-derived DAC write;
- hybrid phase/frequency actuation;
- a phase-lock, UTC, calibrated-accuracy or holdover claim;
- a wider DAC range, larger automatic step, faster automatic cadence or
  unbounded retry;
- GPS receiver transmission or configuration;
- automatic restoration after a fault;
- pushing commits or opening a pull request.

## Intended outcome

A successful programme leaves OTIS with:

- a versioned relative-phase observable derived from the accepted cumulative
  PPS snapshots;
- exact host replay and firmware parity for the selected phase estimator;
- a bounded multi-candidate hybrid phase/frequency preview with zero authority;
- controlled reference-loss, phase-step and recovery evidence;
- a two-direction live result for the tighter hysteretic frequency deadband;
- a combined live record showing how tight frequency acquisition and phase
  preview interact;
- a concise decision on whether to proceed immediately to a separately
  authorized bounded active-hybrid trial.
