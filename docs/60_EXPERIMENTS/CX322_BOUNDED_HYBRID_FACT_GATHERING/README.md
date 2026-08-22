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

The wire-compatible firmware field `first_phase_checkpoint_passed` means
“exact checkpoint recorded” in CX322. CX322 host state and analysis expose the
unambiguous alias `first_phase_observation_checkpoint_exact`; neither name is a
scientific pass claim.

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
