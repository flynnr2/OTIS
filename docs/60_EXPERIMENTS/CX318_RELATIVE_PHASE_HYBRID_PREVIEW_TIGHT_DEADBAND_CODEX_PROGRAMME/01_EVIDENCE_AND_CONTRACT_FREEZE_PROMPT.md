# Stage 1 Prompt: Evidence Handoff and Contract Freeze

Execute Stage 1 without flashing firmware or issuing a serial/DAC command.

## Goal

Turn the sealed CX317 result into a precise CX318 starting point without
rerunning long successful captures.

## Procedure

1. Create the campaign directory and durable state required by the master.
2. Record exact repository status. Stop before edits if existing changes overlap
   programme files or make source identity ambiguous.
3. Validate the CX317 final report, all mandatory sealed gates, the Stage 7B
   snapshot and the hashes of every referenced estimator/model/policy artifact.
4. Recompute the Stage 7B frequency and shadow summaries from immutable sources.
5. Independently reconstruct from raw cumulative snapshots:
   - adjacent interval edge counts;
   - edge error relative to 10,000,000 edges;
   - cumulative relative-phase cycles and nanoseconds;
   - full-run and final-90,000-s movement;
   - a clearly labelled detrended residual diagnostic.
6. Confirm that this reconstruction changes no existing report and makes no
   calibrated or absolute-phase claim.
7. Inventory the exact firmware/host surfaces that own snapshots, estimator
   state, control state, authority, cross-core requests and physical DAC writes.
8. Prove by source inspection that a new preview module can be structurally
   excluded from live authority and DAC reachability.
9. Freeze schemas/profiles for:
   - raw relative-phase observations;
   - phase-estimator outputs and phase epochs;
   - hybrid-preview candidate decisions;
   - tight hysteretic deadband state;
   - programme run/analysis manifests.
10. Run the full software baseline, firmware matrix and no-hardware validation.
    Repair only genuine baseline defects.

## Required contract decisions

Freeze:

- the sign and units from the master;
- phase-epoch start/reset rules;
- raw-phase continuity across a healthy DAC epoch and visible phase step;
- source snapshot and reference identities;
- continuity and invalidation rules;
- unavailable-versus-estimated uncertainty fields;
- raw versus filtered phase fields;
- preview-only authority fields, all false;
- integer tight-entry/release count semantics;
- explicit separation of tight frequency authority from hybrid preview.

## Explicit non-work

- no long capture;
- no firmware upload;
- no DAC or GPS command;
- no phase-derived control implementation yet;
- no modification to the accepted PIO program, DMA ring or snapshot aperture;
- no adoption of a tighter active deadband in this stage.

## Deliverables and exit gate

Deliver a Stage 1 report, versioned schemas/profiles or exact proposed contract
fixtures, the reconstructed relative-phase evidence summary, architecture
inventory and complete baseline results.

Pass only if all sealed evidence validates, phase reconstruction is deterministic
from raw sources, the arbitrary/session-local epoch is explicit, and the future
preview has no path to authority or DAC application.
