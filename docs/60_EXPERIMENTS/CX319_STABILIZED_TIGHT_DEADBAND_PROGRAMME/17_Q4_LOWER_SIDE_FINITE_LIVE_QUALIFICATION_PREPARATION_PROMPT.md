# CX319 Prompt 17: Q4 Lower-Side Finite Live Qualification Preparation

## Purpose and numbering

Prepare the next decision-bearing CX319 gate after the completed adversarial-
review Q1--Q3 sequence.

In this prompt, **Q4** means the adversarial-review gate "one finite bounded
live qualification." It maps to **CX319 G2**, the lower-side finite frequency-
only leg. It is not CX319 G4, and it does not resume CX318 Stage 5 or any
retired CX318 operational artifact.

This prompt authorizes offline preparation only. It does not authorize opening
a serial device, creating a command FIFO, flashing firmware, resetting the
board, issuing a setup stimulus or DAC command, arming control, applying an
automatic correction, running a physical rehearsal, or starting a live leg.

## Decision-bearing objective

Produce a reviewable exact-bundle readiness result that answers one question:

> Is the current `CX319_EVIDENCE_EPOCH_1` lower-side workflow ready to be
> proposed for one separately authorized finite live qualification without
> making that live run the next integration test?

The later physical experiment, if separately authorized, must determine
whether the frozen integer-count tight hysteretic frequency policy can make at
least one healthy positive automatic correction from the lower-side stimulus
and reach two-estimate tight entry within the existing bounded envelope. Phase
and hybrid outputs remain observable and replayable but have zero actuator
authority.

## Normative inputs

Read and bind at least:

- `docs/10_REFERENCE_ARCHITECTURE/OTIS_ADVERSARIAL_ARCHITECTURE_REVIEW.md`,
  especially Q4 and its residual stop conditions;
- `docs/60_EXPERIMENTS/CX319_STABILIZED_TIGHT_DEADBAND_PROGRAMME/00_MASTER_PROGRAMME.md`,
  especially G2 and the universal authority boundary;
- `docs/60_EXPERIMENTS/CX319_STABILIZED_TIGHT_DEADBAND_PROGRAMME/16_Q1_Q3_SEQUENCE_AUTHORITY.md`;
- `docs/50_SOFTWARE/CX319_COMPATIBILITY_RESET_REPORT_20260812.md`;
- `docs/50_SOFTWARE/CX319_EVIDENCE_EPOCH_1.md`;
- `docs/50_SOFTWARE/VERIFICATION_AND_PROFILE_LIFECYCLE.md`;
- `profiles/programme_status_v2.json`; and
- the current lower-leg profile, policy, estimator, plant-model, authority,
  contract, analyzer, and firmware-matrix entries selected by the candidate.

Treat the old G2 v5/v6/v7 activations, the former conditional G3 authority, and
the Q1--Q3 authority as consumed historical records. Do not revive, edit, or
extend them.

## Entry facts to verify, not assume

Before preparing a proposal, verify that:

1. the repository is clean and the selected revision is explicit;
2. the active programme remains `cx319_stabilized_tight_deadband` with only
   offline preparation allowed;
3. Q1, inhibited Q2, and physical no-write Q3 retain passing immutable seals
   and registered evidence identities;
4. the sealed Q3 package validates read-only under the current compatibility
   floor without modifying its source evidence;
5. `cx319_tight_lower` is a supported current profile;
6. the characterized `0xA800..0xAB00` operating envelope remains applicable;
7. no later evidence changes the known terminal board, firmware, DAC, GNSS, or
   oscillator-control topology; and
8. no live or physical Q4 authority is currently effective.

An unknown installed image or applied DAC code is a provenance gap, not by
itself evidence of physical danger. Record it explicitly and make the proposed
entry transaction establish the required current state.

## Q3-to-Q4 transfer audit

Compare the exact sealed Q3 bundle with the proposed Q4 bundle across firmware,
configuration, host behavior, command grammar, protocol, serial-owner and
process topology, FIFO and queue behavior, timing, verifier semantics,
authority, stop conditions, analyzer, sealing, registration, and evidence
layout.

Classify every difference as one of:

- provenance- or path-only, with no operational effect;
- deterministically covered by current replay, preflight, or accelerated
  operational-path rehearsal; or
- operationally significant and therefore requiring the shortest affected
  physical no-write gate to be repeated before live authority can be proposed.

Do not repeat Q1--Q3 merely because source paths, module names, or documentation
changed. Conversely, do not transfer Q3 qualification across a change that can
affect commands, acknowledgement, capture completeness, ownership, timing,
segmentation, safety, firmware behavior, finalization, or the scientific
observation.

If the exact Q3 UF2 and installed-image provenance can be retained under the
current epoch, bind them explicitly. If a new firmware build or flash is
required, report Q4 as blocked pending a fresh exact-bundle physical no-write
qualification; do not silently substitute the new binary for the Q3-qualified
one.

## Freeze the non-authorizing candidate

Freeze one immutable Q4/G2 lower-side candidate bundle containing:

- selected Git revision and clean-tree evidence;
- `CX319_EVIDENCE_EPOCH_1` package identity;
- firmware source revision, `cx319_tight_lower` profile, complete generated
  configuration, build manifest, toolchain identity, and UF2 SHA-256;
- exact Q1, Q2, and Q3 seal and registered-package bindings;
- current policy, estimator, hybrid preview, plant model, response policy,
  numerical policy, diagnostics, status-snapshot, and contract identities;
- capture, supervisor, transaction, abort, rotation, analyzer, evidence,
  sealing, and registration tool identities;
- expected device, board, boot, build-provenance, configuration, DAC-status,
  timing-status, GNSS/PPS, and nonce-bound active-snapshot transcript;
- command vocabulary, command cadence, timeouts, acknowledgements, one-owner
  topology, obstruction procedure, independent abort, stop conditions, and
  output locations; and
- an explicit authority declaration in which every physical, write, setup,
  arm, automatic-correction, flash, reset, and serial-access permission is
  false.

Do not use an old CX318 Stage 5 bundle, promotion ledger, manifest, analyzer,
profile, or seal as current input. Do not alter sealed evidence under `runs/`
and do not force-add ignored artifacts.

## Frozen proposed live envelope

The proposal must retain the existing CX319 G2 scientific envelope unless a
separate reviewed programme decision changes it:

- one exact lower-side setup stimulus at `0xA808`, opening a new DAC epoch;
- setup is not evidence of automatic-controller direction;
- no automatic correction until the complete setup authorization, receipt,
  Core 1 authorization, Core 0 acceptance, Core 1 release, physical
  application, acknowledgement, DAC row, and independent replay chain passes;
- at least one complete healthy positive automatic request, acceptance,
  application, acknowledgement, and response transaction;
- two consecutive fresh 600-second estimates with absolute accumulated edge
  error at most two counts for tight entry;
- at most four automatic corrections;
- at most 21 codes per automatic correction;
- at most 84 codes cumulative absolute automatic movement;
- at least 1,800 seconds between applied automatic corrections;
- 900 seconds settling exclusion followed by 600 seconds fresh support after
  every write;
- one request outstanding;
- hard range `0xA800..0xAB00`;
- 90-minute qualification deadline and four-hour maximum qualified duration;
- no retry, restoration, threshold change, duration extension, or automatic
  reboot recovery; and
- continuously zero phase-derived and hybrid-derived actuator authority.

The proposal may expose less automatic authority only if it can still answer
the lower-side scientific question. It must never exceed these bounds.

## Required offline verification

Using the exact candidate revision and identities:

1. run the current Release tier, including both supported profiles and all
   expected-failure guards;
2. validate the sealed Q3 package read-only and preserve its original verdict;
3. replay the selected frequency, relative-phase, hybrid-preview, tight-band,
   transaction, response, and fault fixtures;
4. prove host/firmware parity for the selected lower profile and policy;
5. prove structurally that phase and hybrid values cannot change active delta,
   eligibility, response, budget, or transaction authority;
6. run the no-I/O structural preflight against the frozen candidate;
7. run the complete accelerated operational path using the actual candidate
   capture, supervisor, transaction, obstruction, abort, rotation, analyzer,
   evidence snapshot, seal, and temporary-index registration surfaces; and
8. fault-inject missing, stale, partial, duplicated, reordered, wrong-session,
   wrong-generation, wrong-nonce, and failed/ambiguous setup evidence and prove
   fail-static, no-retry behavior.

The rehearsal must include the setup-only checkpoint and prove that automatic
authority remains unavailable until the complete setup chain is independently
accepted. It must also exercise qualification and cadence boundaries using
accelerated time or deterministic replay without representing that as physical
qualification.

Do not weaken a gate to make the rehearsal pass. Any discovered ordinary host,
orchestration, analyzer, or finalization defect is a platform defect caught in
rehearsal. Repair only the narrow cause, freeze a new bundle identity, rerun the
invalidated verification, and retain the failed attempt.

## Readiness outcomes

Choose exactly one:

- `q4_offline_ready_for_separate_live_authority_decision`;
- `q4_requires_shortest_affected_physical_no_write_requalification`;
- `q4_platform_or_bundle_defect_requires_repair`;
- `q4_scientific_envelope_requires_programme_revision`; or
- `q4_blocked_by_missing_or_inconsistent_evidence`.

An offline pass is not a live pass and grants no physical authority. A
scientific-envelope change is not an implementation repair and requires a
separate operator decision before preparation continues.

## Deliverables

Produce:

- the immutable non-authorizing candidate bundle and its content identity;
- Release, Q3 validation, preflight, replay, parity, and accelerated rehearsal
  results with exact tool and input identities;
- the Q3-to-Q4 transfer-audit table and conclusion;
- a compact offline-readiness report stating observed facts, derived results,
  assumptions, limitations, anomalies, and the selected readiness outcome;
- a machine-readable proposed authority envelope whose physical permissions
  remain disabled; and
- if and only if readiness passes, a separate draft operator-decision record
  naming the exact bundle, stimulus, movement bounds, stop conditions,
  independent abort, expected device, firmware-entry action, and terminal
  physical-state obligations.

Do not mark the draft decision effective, add a live operation to programme
status, or execute it. Stop after presenting the exact proposal for operator
review.

## Final stop boundary

This prompt is complete when the offline readiness result and, if applicable,
the non-effective authority proposal are reviewable. It must stop before all
hardware interaction.

If later live authority is granted, execute it under a new explicit authority
record and the exact passing bundle. Stop immediately on an identity mismatch,
unexpected serial owner, incomplete or stale authority generation, GNSS/PPS
ineligibility, transport or partition fault, missing acknowledgement,
ambiguous application, range/cadence/budget violation, replay disagreement,
abort failure, analyzer non-pass, seal/registration failure, or any new
platform discovery. A finite scientific non-pass is useful evidence and does
not authorize a retry.
