# CX322 bounded direct-hybrid fact gathering

## Decision served

CX322 asks what the unchanged natural firmware hybrid controller actually does
on this rig over a bounded long horizon. It does not ask a short plant-response
gate to prove that the controller is worth observing.

The acquisition succeeds when the exact bounded run completes with coherent
D14/D8 measurement authority, DAC/application provenance, firmware-to-host
replay, and a clear static terminal. Phase materiality, response sign,
response magnitude, phase improvement, and frequency preservation remain
scientific results. Low or absent movement is a fact, not an acquisition
failure.

The frozen candidate contract is
`profiles/discipline/cx322_bounded_hybrid_fact_gathering_v1.json`.

## Unchanged controller

CX322 changes response-checkpoint disposition, not the natural controller:

\[
f_{\mathrm{frequency}} = -\hat e_f
\]

\[
f_{\mathrm{phase}} =
\operatorname{clamp}\!\left(
-\frac{\phi_{D8\,\mathrm{relative\,to}\,D14}}{21600\ \mathrm{s}},
-\frac{1}{600}\ \mathrm{Hz},
+\frac{1}{600}\ \mathrm{Hz}
\right)
\]

\[
\Delta c = \operatorname{round}_{\mathrm{half\ away\ from\ zero}}\!\left(
\operatorname{clamp}\!\left(
2884.5027706464516\,(f_{\mathrm{frequency}}+f_{\mathrm{phase}}),
-21,
+21
\right)
\right)
\]

The same 600-second authoritative frequency estimator, 21,600-second phase
pull-in, 21-code step limit, four-application limit, 84-code path limit,
1,800-second applied cadence, and `0xA800..0xAB00` DAC range remain in force.
The policy loader mechanically compares every controller-relevant field with
the bound CX320 predecessor before accepting the CX322 policy.

## Response checkpoint meaning

Each application still requires:

1. the exact applied code and DAC epoch at every downstream consumer;
2. 900 seconds of settling exclusion and 600 seconds of fresh support;
3. durable ACT and AHY records;
4. exact independent host replay before phase-4 acknowledgement; and
5. TIGHT re-entry before later phase authority.

The checkpoint proves that the observation is attributable and replayable. It
does not require the response class, sign, or magnitude to agree with a plant
prior. `healthy_indeterminate_near_resolution`, `wrong_sign`, `growing_error`,
and `excess_response` are retained without becoming terminal by themselves.
Malformed measurement, actuator, identity, epoch, or replay evidence remains
fail-closed.

An independent host-verifier disagreement enters a durable, review-required
diagnostic quarantine; it is not by itself proof that the firmware or physical
evidence is invalid. The supervisor suppresses new SETUP/ARM authority,
retains the exact pending phase and last confirmed DAC identity, and keeps the
sole serial owner and healthy capture running while the discrepancy is
classified. An already-issued evidence acknowledgement may complete when its
exact causal phase is independently verifiable and unrelated to the finding.
Only an unverifiable acknowledgement is withheld. The firmware may then enter
its own bounded fail-static state after the evidence-acknowledgement timeout,
but that does not authorize the host to abort or tear down capture.
The independent replay therefore joins each AHY decision boundary to the exact
selected-estimator `rp2040_timer0` coordinate, including canonical 36-bit
rollover, rather than using the lossy integer-second AHY display field for
phase-residence or cadence decisions. Host abort follows only after review and
explicit approval establish that continuing cannot preserve safety or
decision-bearing scientific validity. Firmware retains its own independent
bounded fail-static behavior, and an explicit operator abort remains a
separate path. Loss of the sole capture owner is recorded as an observed
terminal fact; it does not let another host component invent abort authority.
A defect confined to non-authoritative offline
bookkeeping or reporting may instead be repaired and replayed from unchanged
retained evidence. Any actuation, code, epoch, or budget change while
quarantined is an immediate authority-safety violation.

The wire-compatible firmware field `first_phase_checkpoint_passed` means
“exact checkpoint recorded” in CX322. CX322 host state and analysis expose the
unambiguous alias `first_phase_observation_checkpoint_exact`; neither name is a
scientific pass claim.

The firmware field is the level of the current response transaction: it may
clear when a later application resets estimator history and remain clear until
that application's response completes. The supervisor separately latches the
first exact checkpoint and its `later_authority_released` transition. A later
application is authorized by that retained causal release, not by the
instantaneous current-transaction level; `HYBRID_TRACKING` still requires the
current firmware checkpoint to be asserted.

## Facts produced

For every application, analysis reports the commanded delta, applied code and
epoch, frequency and phase controller terms, the frequency-only
counterfactual, and response views at 600, 1,500, 3,600, and 7,200 seconds.
Every horizon is bound to the same DAC epoch. If another application or the
terminal occurs first, the horizon is explicitly right-censored; it is never
filled with zero or interpreted as clean.

Across the run, analysis reports the available response count by horizon,
positive-direction fraction, and minimum/median/maximum observed Hz-per-code
gain, alongside phase slope/excursion, frequency residual RMS/tails, TIGHT
occupancy, and natural application counts. Historical direction, gain,
detection-floor, 10% phase-improvement, one-count RMS, and 10% occupancy
criteria are labelled descriptive prior comparisons, not acceptance gates.

## Finite terminal contract

- Qualified duration: 43,200 seconds from the first complete fresh
  authoritative estimate after exact setup and common-health qualification.
- Absolute wall limit: 57,600 seconds from capture-owned run identity.
- No extension, automatic retry, or automatic restoration.
- Clean phase loss degrades to frequency-only control and remains an observed
  outcome.
- Only the existing prospective controller safeguards
  `prospective_repeated_alternation` and `prospective_low_efficiency_path` map
  to `bounded_direct_hybrid_early_safety_stop`.
- Every other firmware fail-static cause maps to measurement-authority or
  platform fault; an authority-bound breach is never relabelled as science.

The complete healthy endpoint is
`bounded_direct_hybrid_evidence_acquired`, regardless of whether the rig
produced material phase applications or responses that agreed with the priors.

## Entry discipline

Before bench entry, freeze a new CX322 firmware build, exact bundle, proposal,
structural preflight, and complete operational-path rehearsal. The rehearsal
must exercise the actual host topology, durable phase-4 replay/acknowledgement,
low/no and wrong-direction nonterminal paths, the next downstream natural
decision, transport obstruction, priority-abort delivery before capture close,
analysis, sealing, and registration. It is not physical qualification.

Coverage is deliberately attributed by boundary: the real capture and live
supervisor processes carry an `inside_deadband` response through durable
AHY/ACT replay, phase-4 consumption, nonterminal retention, and later-authority
release; deterministic host scenarios cover every other admissible response
class; C++ regressions cover the firmware low/no and wrong-direction branches.
The rehearsal receipt must retain that provenance and must not claim that its
PTY or fixtures exercised the physical plant.

The prior CX320/CX321 bundle and proposal hashes cannot authorize CX322. A new
exact bundle hash requires an explicit operator decision before flash, reset,
serial ownership, setup, or live acquisition.

## Integration-escape review (attempts 1--6)

The first six physical starts did not reject the CX322 controller science.
They exposed three firmware integration defects and three host-platform
escapes:

1. The CX322 exact timer projection was compiled out by a CX321-only source
   guard.
2. Exact decision-timestamp dispatch was independently compiled under a
   CX321-only guard.
3. The supervisor incorrectly treated overlapping `phase_nonzero` and
   `frequency_only` counts as mutually exclusive.
4. Firmware did not record the exact phase-qualification origin on the
   frequency-acquire transition.
5. Host replay replaced an exact timer coordinate with lossy integer seconds
   at the phase-residence boundary, disagreed with firmware, and withheld the
   acknowledgement until firmware correctly timed out fail-static.
6. The host pre-acknowledgement check accepted a generation-fresh but causally
   stale status snapshot and aborted before acknowledging a valid second
   request.

Attempts 1, 2, and 4 are classified as firmware defects under intended
integration. Attempts 3 and 5 are testing/supervisor harness escapes. Attempt
6 is a host orchestration escape. Secondary offline finalization or abort-
reporting defects were recovered from retained evidence and did not themselves
justify another physical acquisition.

The durable entry requirements are therefore:

- build and exercise the exact frozen firmware profile, with source-guard
  checks proving that every required timestamp and wire field is present;
- retain exact counter-domain coordinates end to end and compare exact tick
  deltas directly with exact tick thresholds;
- derive harness predicates from the frozen contract, including every legal
  overlap and repetition;
- bind live queries to causal identity and frontier, not generation freshness
  alone, and use bounded retry/hold for coherent older snapshots;
- rehearse the complete progressive path through at least the second request,
  acknowledgement, retained response, later-authority release, and first
  dependent decision; and
- attribute fixture coverage honestly: host fixtures do not prove firmware
  compile guards, cross-core propagation, device-driver behavior, or the
  physical plant.

These rules are also retained in the repository-root `AGENTS.md` so that they
apply before future OTIS campaign work, rather than depending on this campaign
document being rediscovered.

## Entry result (2026-08-22)

The exact offline entry sequence passed:

- firmware UF2 SHA-256:
  `a5a7c48702c3b54d48d8055c99ed882293ea84d74b62a585c7f15a9b66dc51ac`;
- exact bundle SHA-256:
  `ebe9e446f0445cbe5cae741f729b5e0af480ca6088484ccdf1df357568a2158f`;
- non-effective proposal SHA-256:
  `6bd897c1a6fb60924001e62d73bf5177ec2fbb38f1bfde46eeceb87d1aa423ab`;
- structural-preflight SHA-256:
  `1a8d0067eb7ba2a801ed332752ad810a8fbad689b4d5bf809b77ac4ede626a75`;
- live-topology rehearsal SHA-256:
  `d2de2eabea73ac765563363e89503d9de383881282e371d5d5410a93da82f205`.

The PTY rehearsal used the real capture and live-supervisor processes and
confirmed durable phases 1--4, exact firmware consumption of phase 4,
nonterminal response retention, TIGHT reacquisition before later authority,
independent abort delivery through a saturated normal-command path, a complete
ABORTED/fail-static snapshot preserving the last confirmed DAC code, logical
rotation under the same sole serial owner, and successful analysis, sealing,
and registration. Capture recorded zero parser errors. It performed zero
physical actions and supplies no physical qualification evidence.

That entry statement is retained as the historical pre-live record. Operator
authority was subsequently granted for the exact attempt-7 successor bundle,
and the 12-hour physical campaign completed successfully. The terminal result,
scientific interpretation, evidence identities, and successor-design boundary
are recorded in
`01_STAGE5_ATTEMPT7_TERMINAL.md`. No additional CX322 physical attempt is
authorized; the next gate is an offline successor-design decision.
