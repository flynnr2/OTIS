# CX318 Relative-Phase, Hybrid-Preview and Tight-Deadband Codex Programme

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
