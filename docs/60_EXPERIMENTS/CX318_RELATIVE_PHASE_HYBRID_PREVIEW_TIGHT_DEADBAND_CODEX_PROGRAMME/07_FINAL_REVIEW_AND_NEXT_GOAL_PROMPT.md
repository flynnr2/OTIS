# Stage 7 Prompt: Final Review and Next Goal

Execute Stage 7 after the last completed hardware stage. This stage is review,
verification and documentation only. Do not move the DAC.

## Goal

Decide what CX318 demonstrated and whether the fastest defensible next goal is
a separately authorized bounded active-hybrid experiment.

## Audit

Audit:

- every source/build/profile/model/estimator/policy identity and evidence seal;
- raw snapshot-to-relative-phase reconstruction;
- phase epoch, sign, units, continuity and invalidation semantics;
- estimator candidate selection and replay corpus;
- hybrid candidate formulae, state transitions, limits and zero authority;
- host/firmware parity and timing/service isolation;
- both tight-deadband active directions and every transaction;
- correction, cadence, path, range and outstanding-request budgets;
- real-GPS combined run and all fault/phase-step rehearsals;
- stopped, partial, failed and anomalous attempts;
- final full tests, firmware matrix and no-hardware validation;
- the final confirmed applied DAC code and static terminal state.

Do not use modeled counterfactual improvement as observed hybrid control. Do not
use relative phase as UTC, absolute epoch, generated-output alignment, calibrated
uncertainty, phase lock or holdover.

## Required decision

Choose exactly one:

- `blocked_before_relative_phase_estimator`;
- `relative_phase_estimator_needs_revision`;
- `relative_phase_and_hybrid_preview_passed_tight_deadband_not_validated`;
- `tight_deadband_validated_hybrid_preview_needs_revision`;
- `relative_phase_hybrid_preview_and_tight_deadband_trial_passed`.

## Next-goal selection

Recommend exactly one primary next goal:

- a separately authorized bounded active-hybrid phase/frequency trial;
- phase-observable/capture improvement;
- tighter-deadband or plant-model revision;
- physical waveform and delay characterization;
- reference-loss holdover preview;
- GNSS provisioning/timing-receiver work.

If the full pass decision is selected and no blocker contradicts it, prefer the
bounded active-hybrid trial. Draft its proposed authority envelope, but do not
execute it under CX318 authority.

## Required final report

Create a tracked report under `docs/60_EXPERIMENTS/` containing:

- decision and concise rationale;
- exact evidence identities and all run outcomes;
- relative-phase definition, measured movement and limitations;
- selected estimator and rejected candidates;
- hybrid candidate comparison and best bounded preview;
- tight-deadband bidirectional results versus V2/shadow predictions;
- combined-run frequency, phase, service and queue evidence;
- fault, recovery, abort and preservation results;
- final tests/builds and explained skips;
- every unsupported claim and remaining blocker;
- one next programme recommendation;
- last confirmed DAC code, left static.

Update the CX318 README, revised roadmap, control-loop readiness and any stage
matrix that would otherwise disagree. Preserve all CX317 reports unchanged as
historical evidence.

## Completion

Mark complete only when the final report, durable state, roadmap and referenced
artifacts agree and validate. Do not restore, delete, push, open a pull request
or archive the task without separate authorization.
