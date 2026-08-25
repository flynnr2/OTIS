# Codex Prompt: Establish Sustained-Hybrid Equilibrium-Estimator Feasibility

You are working in the OTIS repository on the computer attached to the bench
rig. Complete the smallest decision-bearing offline study that determines
whether retained evidence can identify the oscillator's durable DAC
equilibrium separately from a temporary phase-steering displacement well
enough to justify a later bounded trajectory-planning study.

Do not stop after writing a plan, architecture note, or estimator prototype.
Freeze the evidence, model semantics, usefulness threshold, validation split,
and terminal rules before calculating the decision result. Carry the work
through one immutable observability verdict. Do not rescue an estimator by
changing its model, evidence partition, nuisance bounds, or usefulness gate
after seeing the result.

This is an estimator-feasibility study, not another deadband comparison and
not a controller-selection exercise.

## Decision served

The mode-separation study established that preserving phase-material control
is possible, but that the plant then has to recover from the early 17-code
phase path. The three frozen candidates reactively moved back toward a
frequency-maintenance point, consumed 28 to 32 path codes, and lost too much
tight-band occupancy.

Test the following architecture hypothesis rather than assuming it:

> OTIS can represent the applied DAC command as a durable estimated
> frequency-equilibrium code plus a deliberately temporary phase-steering
> displacement. If the equilibrium is observable with useful bounded
> uncertainty, a later controller can plan a finite-area phase manoeuvre and
> an intentional return instead of rediscovering and reactively undoing its
> own phase correction.

Use the decomposition

```text
applied_dac_code = equilibrium_code + phase_steering_displacement
```

only as an explicit estimator/controller state representation. The two terms
are not two physical actuators, and the phase-steering displacement is not a
second independently observed plant state.

The study must answer one primary question:

> Does the retained evidence constrain `equilibrium_code` tightly and
> robustly enough that a subsequent finite-area phase-trajectory study has a
> non-vacuous feasible region under the already frozen phase, frequency,
> occupancy, path, range, cadence, and provenance constraints?

## Required terminal outcomes

Deliver exactly one of:

1. **`equilibrium_state_observable_for_bounded_trajectory_study`** — the
   retained evidence supports an explicit bounded equilibrium-state
   estimator, passes held-out prediction and sensitivity gates, and is narrow
   enough under the prospectively frozen usefulness criterion to justify a
   separately frozen trajectory-planning study;
2. **`equilibrium_state_not_observable_targeted_characterization_required`**
   — the state is structurally confounded, empirically inconsistent, too
   uncertain, too history-dependent, or too wide to support that next study;
   identify the minimum additional characterization evidence that would
   discriminate the gap, without creating physical authority; or
3. **`study_invalid_due_to_evidence_or_model_binding_failure`** — required
   retained evidence or identities cannot be validated, the exact baseline
   cannot be reproduced, or the frozen model cannot be evaluated without an
   unsupported claim.

A no-observability result is valid progress. Do not turn it into an estimator
selection, controller implementation, firmware change, bundle, rehearsal, or
physical run.

## Authority boundary

This prompt authorizes:

- read-only inspection and validation of retained evidence;
- deterministic offline reconstruction and set-membership analysis;
- creation of a prospectively frozen study contract;
- small deterministic tools, tests, and deliberately small fixtures;
- immutable machine-readable and reviewed decision reports;
- a non-effective next-study requirements document when observability passes;
- a non-effective targeted-characterization requirements document when it
  does not; and
- proportionate verification limited to the changed offline and programme
  status surfaces.

This prompt does **not** authorize:

- serial-device access or ownership;
- firmware flash or reset;
- GNSS transmission;
- DAC setup, challenge, stimulus, restore, or any other DAC write;
- control arm, live FIFO use, activation, Attempt 5, or a physical run;
- physical rehearsal or live acquisition;
- creation of an effective authority or exact live bundle;
- implementation in firmware or a live host controller; or
- treating any tracked or stale programme status as physical permission.

Do not open a serial device, call a live runner, flash, reset, or access the
bench even if an existing guard would permit it. The current programme must
remain inactive and every physical-authority field false.

## Naming and scope

Use the offline study identity
`OTIS_SUSTAINED_HYBRID_EQUILIBRIUM_ESTIMATOR_FEASIBILITY_STUDY_V1`.

Put its reviewed artifacts under
`docs/60_EXPERIMENTS/OTIS_SUSTAINED_HYBRID_EQUILIBRIUM_ESTIMATOR_FEASIBILITY_STUDY/`.
Do not create a new `CX###` identifier, successor policy, discipline profile,
firmware profile, activation, bundle, rehearsal identity, or run directory.

Do not modify firmware, shared live-control behavior, transport, protocol, or
hardware contracts. If the study reveals that such a change is necessary,
record it as a later gate and stop.

## Read first

Read and apply at least:

- repository-root `AGENTS.md` and all applicable nested instructions;
- `docs/00_FOUNDATIONS/OTIS_REFERENCE_TERMINOLOGY.md`;
- `docs/00_FOUNDATIONS/OTIS_ARCHITECTURE_OVERVIEW.md`;
- `docs/00_FOUNDATIONS/OTIS_NON_GOALS.md`;
- `docs/60_EXPERIMENTS/OTIS_SUSTAINED_HYBRID_REGULATION_V1/README.md`;
- the V1
  `04_ATTEMPT4_PHASE4_ATTESTATION_AND_SCIENTIFIC_TERMINAL.md` report;
- `docs/60_EXPERIMENTS/OTIS_SUSTAINED_HYBRID_SUCCESSOR_OFFLINE_STUDY/DECISION.md`;
- `docs/60_EXPERIMENTS/OTIS_SUSTAINED_HYBRID_MODE_SEPARATION_OFFLINE_STUDY/ARCHITECTURE.md`;
- `docs/60_EXPERIMENTS/OTIS_SUSTAINED_HYBRID_MODE_SEPARATION_OFFLINE_STUDY/DECISION.md`;
- both predecessor frozen contracts and immutable comparison reports;
- Attempt 4's immutable manifest, activation, bundle, seal, evidence manifest,
  AHY, ACT, selected-estimate, tight-band, raw phase, response, and raw
  observation records under
  `runs/otis_sustained_hybrid_regulation_v1/live_attempt4_20260823T2148Z`;
- the raw source packages named by the retained plant-model profile, when
  present locally and identity-valid;
- `profiles/programme_status_v2.json` and its execution-guard tests;
- `profiles/discipline/otis_sustained_hybrid_regulation_v1.json`;
- `profiles/estimators/cx317_pps_gated_selected_v1.json`;
- `profiles/estimators/cx318_relative_phase_selected_v1.json`;
- `profiles/plant_models/cx317_pps_gated_v2.json`;
- `profiles/discipline/cx317_response_classification_v2.json`;
- `host/otis_tools/active_hybrid_policy.py`;
- `host/otis_tools/active_hybrid_replay.py`;
- both predecessor offline-study comparators and their focused tests; and
- the current programme-status loader and fail-closed operation guards.

Preserve `runs/` as ignored local scientific evidence. Never force-add an
ignored artifact or weaken `.gitignore`. Commit only reviewed summaries,
contracts, small purpose-built fixtures, and deterministic offline tools.

## Frozen predecessor identities

Validate, rather than merely copy, at least these current tracked identities:

- mode-separation architecture file SHA-256
  `ae4967c4fdb8bcb532052f14290e2dccd3a61d7c238bdec28111e81120adbf0b`;
- mode-separation contract semantic SHA-256
  `c02ce352d5224b5ed395d48d62a2ddc8a99654d08b95ad23a182186a716a37eb`;
- mode-separation contract file SHA-256
  `f0af0cbcac15b9758e4ae4ba3e2246a4c9ec6dc51804f4b5df1540f503083165`;
- mode-separation report semantic SHA-256
  `6b971643c106fabe0cec2c267f733ded330469ad7596125fb2dd33e57a6b9aef`;
- mode-separation report file SHA-256
  `27bcdf5b3cc4ec1db23c835a3a0df11e832ed27682863bcea7a1fa5d4d2c7b07`;
- mode-separation comparator SHA-256
  `9fe68acc9efcd5fd60a1f1b4982a2a485e5cca1d21dbdce418189fc57d93b85a`;
- Attempt 4 registered evidence-content SHA-256
  `aa7ac41bb07192f4de5807547899d50b0e51b3c60bbcac4f8e9cadb6fc6a2a90`;
- V1 policy SHA-256
  `015c133d5898e9c5f21dd3de10612cf8d09ff025c1f9f89345bd8fcc3a0d485c`;
  and
- every estimator, plant-model, response-policy, source-package, manifest,
  seal, and raw-evidence identity transitively declared by the frozen
  contracts.

If current tracked identities legitimately differ before this prompt is run,
do not silently update these values. Determine whether the change is part of
this study's inputs. Rebind prospectively with an explicit provenance record
only when decision-relevant semantics are unchanged; otherwise stop with the
invalid-study terminal.

## Facts the study must reproduce before estimation

Treat these as observed only after validation:

- V1 exact replay contains 52 decisions and eleven applications
  `-6,-1,-1,-6,-1,-1,-1,+5,+5,-5,+5`;
- the first seven applications are phase-material, consume 17 path codes, and
  end at code 43051;
- the final four V1 applications are frequency-only maintenance, consume 20
  additional path codes, and produce the frozen low-efficiency terminal;
- all three mode-separated candidates preserve the seven early applications
  and achieve approximately 1.943 cycles and 72.7% matched phase improvement;
- their modeled natural path is 28 to 32 codes and their tight-band occupancy
  degradation is 15.2% to 23.9%;
- the authoritative frequency estimator uses non-overlapping 600-second
  selected outputs with one count equal to `1/600 Hz`;
- its profile declares an empirical detection floor of approximately
  `2/600 Hz` and does not provide calibrated resolution or combined
  uncertainty;
- the retained plant model provides a finite minimum, nominal, and maximum
  differential gain but not a calibrated population uncertainty model;
- Attempt 4's formal physical qualification remains failed because its eleven
  contemporaneous pre-phase-4 response-replay attestations were not retained;
  and
- no predecessor offline result created a successor or physical authority.

Reproduce the exact chronology, code, DAC epoch, support-window identity,
counter domain, and status terminal before accepting any derived equilibrium
result. A mismatch is an evidence/tool-binding defect, not license to repair
history.

## State and observation semantics

Define all state in precise OTIS terms before fitting or bounding it.

At minimum distinguish:

- `applied_dac_code`: the exact acknowledged AD5693R code and DAC epoch;
- `equilibrium_code`: a modeled code or code interval at which the qualified
  D8 oscillator frequency error relative to D14 is zero under explicitly
  stated thermal, direction/history, and time assumptions;
- `phase_steering_displacement_codes`: the modeled arithmetic difference
  `applied_dac_code - equilibrium_code`;
- qualified 600-second D8 count/frequency observations relative to D14;
- raw arbitrary-epoch relative phase observations and their exact phase epoch;
- plant differential gain in `Hz/code` with its sign and provenance; and
- any bounded drift, hysteresis, repeatability, quantization, settling, or
  reference nuisance term.

`equilibrium_code` is a model state, not a directly measured canonical value,
not proof of oscillator calibration, and not a claim of traceable zero
frequency error. `phase_steering_displacement_codes` is bookkeeping for a
planned single-actuator trajectory, not a second actuator or a measured phase
state.

Never overwrite raw evidence with either value. Never join raw phase epochs
using a guessed offset. D14 remains the sole PPS/reference authority, D8 the
sole oscillator/count input, and D10 an external event input only. D10 must not
enter this estimator.

## Estimation discipline

Prefer a deterministic set-membership or interval estimator. The retained
evidence does not justify invented Gaussian noise, fitted covariance, Bayesian
confidence, or Kalman-optimality claims.

Use a declared observation relation of the general form

```text
qualified_frequency_error
  = plant_gain * (applied_dac_code - equilibrium_code)
  + declared_nuisance_terms
```

but do not assume that this simple relation is adequate. Test its residual
structure and identifiability. Every nuisance bound must come from a validated
retained source, an exact quantization construction, or a prospectively frozen
conservative derivation. Label empirical finite-run bounds as such; do not
promote them to calibrated or population uncertainty.

Do not reuse the predecessor comparator's rejected construction that adds the
full hysteresis and same-code repeatability spans as a fixed discontinuous
offset for every nonzero candidate/source code difference. Preserve the
mode-separation model correction:

- ordinary differential response uses the retained gain envelope;
- reversal hysteresis is an explicit direction/history perturbation or
  dead-zone hypothesis;
- same-code repeatability is an observation-consistency perturbation; and
- combined calibrated uncertainty remains unavailable.

## Stage 0: validate and inventory evidence

Before freezing an estimator:

1. Validate all tracked and ignored evidence identities used by the study.
2. Reproduce both predecessor immutable reports and exact V1 baseline without
   overwriting them.
3. Inventory every eligible constant-code dwell, code transition, response
   window, natural reversal, same-code return, temperature record, frequency
   support, settling exclusion, and phase epoch.
4. State which observations can constrain equilibrium, gain, drift,
   hysteresis, and repeatability, and which parameters remain confounded.
5. Separate physical characterization observations from Attempt 4 validation
   observations and from predecessor modeled counterfactuals.
6. Exclude modeled candidate continuations from estimator identification.
7. Preserve exact applied-code and DAC-epoch identity through the first
   dependent frequency and phase observations after every application.

If the retained source packages named by the plant model are unavailable or
cannot be identity-validated, do not substitute values copied from a summary
and call the estimator independently validated. Freeze the resulting evidence
gap and use the invalid or not-observable terminal as appropriate.

## Stage 1: prospectively freeze the feasibility contract

Before computing equilibrium intervals or validation metrics, create a
machine-readable contract and concise reviewed methodology under a new
descriptive study folder.

Freeze:

- all source paths, manifests, seals, content hashes, and tracked profile/tool
  identities;
- the exact baseline replay expectations;
- state definitions, units, reference domains, counter domains, and sign
  conventions;
- eligible and excluded evidence with exact reasons;
- a causal identification set and a genuinely held-out validation set;
- no more than three small, nested model hypotheses needed to discriminate
  fixed equilibrium, bounded slow drift, and reversal/history dependence;
- the gain envelope and every nuisance construction;
- settling, support-window, phase-epoch, DAC-epoch, session, temperature, and
  freshness rules;
- the set-membership algorithm, canonical arithmetic, rounding, interval
  closure, and deterministic ordering;
- structural-identifiability and residual checks;
- held-out predictive checks and sensitivity cases;
- a numeric downstream-usefulness criterion derived before results;
- terminal and tie rules;
- report schema, canonical semantic hashing, and tool identity;
- the no-I/O authority boundary; and
- the three terminal outcomes named above.

Do not randomly split adjacent supports from the same dwell between
identification and validation. Prefer source-run or complete-segment holdout
that prevents temporal and DAC-epoch leakage. Attempt 4 should remain held out
from plant-characterization identification wherever the retained source set
makes that possible.

### Bounded model hypotheses

Use the smallest nested set that can expose confounding. A suitable default is:

1. one constant equilibrium interval within each prospectively declared
   thermally qualified segment;
2. the same equilibrium with a bounded slow-drift term whose limit is derived
   independently from eligible same-code dwell evidence; and
3. direction/history-conditioned equilibrium intervals only when retained
   natural reversal and return evidence can identify them.

These are diagnostic identifiability hypotheses, not three controllers and not
an invitation to search a broad model grid. Do not add temperature
coefficients, aging terms, arbitrary splines, hidden modes, or free change
points merely to improve fit. A more complex hypothesis is admissible only
when a prospectively declared residual check discriminates it and sufficient
independent evidence exists.

### Freeze usefulness before seeing the estimate

An equilibrium interval is useful only relative to the next decision. Before
calculating it, derive and freeze the maximum tolerable equilibrium uncertainty
from unchanged downstream constraints, including:

- the original phase gate of at least one matched cycle and 10% improvement;
- preservation of frequency RMS, tail, and tight occupancy without more than
  the previously frozen material degradation;
- at most 27 natural path codes at the Attempt 4 horizon;
- the existing range, step, cadence, application, transaction, and
  fail-static limits;
- the retained minimum/nominal/maximum gain; and
- an intentional finite-area excursion and return rather than reactive
  equilibrium rediscovery.

Document the derivation and units. It may be a maximum interval width, a
maximum worst-case return error, or an equivalent robust-feasibility
criterion. It must be numeric, deterministic, and independent of the observed
estimator result. If no defensible usefulness threshold can be derived from
the retained constraints, the state is not yet decision-useful; do not invent
one from the fitted interval.

Do not quietly inherit the exact seven early V1 applications as a required
future trajectory. They are retained evidence and a phase-performance
baseline, not necessarily the correct planned manoeuvre. Conversely, a future
trajectory may not win by applying no material phase correction.

## Stage 2: execute the frozen observability study

For every frozen model hypothesis:

1. Establish structural identifiability before numerical fitting. Show which
   combinations of equilibrium, gain, drift, and hysteresis can and cannot be
   distinguished by the available code/time history.
2. Compute the complete feasible equilibrium set or a conservative enclosure;
   do not return only the optimizer's preferred point.
3. Preserve integer-count and exact-counter arithmetic as far as the evidence
   permits. Do not pass decision-bearing elapsed time through rounded seconds
   or binary floating point without a bounded, documented conversion.
4. Validate prospectively held-out physical observations using intervals
   generated without their outcomes.
5. Report coverage, interval width, worst residual, tail residual, and any
   observation that makes the feasible set empty.
6. Perform leave-one-segment-out or another frozen small sensitivity check so
   one dwell, reversal, or run cannot silently determine the answer.
7. Exercise minimum, nominal, and maximum gain; quantization boundaries;
   same-code positive and negative one-count perturbations; reversal dead-zone
   behavior; declared slow drift; settling boundaries; DAC-epoch changes;
   and any eligible temperature envelope.
8. Compare against an uninformative baseline such as the full characterized
   DAC range or per-support free equilibrium. The estimator must materially
   reduce uncertainty rather than merely rename the applied code.
9. Check whether the resulting worst-case equilibrium set satisfies the
   frozen downstream-usefulness criterion.
10. Keep every reported field labeled as observed, reconstructed, derived,
    fitted, bounded, or modeled.

Raw arbitrary-epoch phase may test the consistency of an implied finite-area
frequency excursion within its own epoch. It must not be used to manufacture a
zero-frequency equilibrium or join epochs. Do not use phase observations both
to identify equilibrium and to claim independent phase validation without an
explicit non-overlapping evidence partition.

## Frozen feasibility gate

Return
`equilibrium_state_observable_for_bounded_trajectory_study` only when all of
the following pass:

1. Every required identity and exact V1 baseline check passes.
2. The equilibrium state is structurally identifiable under at least one
   prospectively credible model and is not rendered unbounded by another
   equally supported frozen model.
3. The complete feasible set is nonempty for identification evidence.
4. Held-out physical observations satisfy the prospectively frozen predictive
   interval and residual criteria.
5. The result remains bounded and decision-useful under all required gain,
   quantization, drift, repeatability, hysteresis, and leave-one-segment-out
   cases.
6. The worst-case equilibrium uncertainty passes the independently derived
   downstream-usefulness criterion.
7. The result is materially narrower than the uninformative baseline and is
   not simply the latest applied code, final V1 code, or a fitted controller
   target relabeled as an estimate.
8. Exact source identity, DAC epoch, counter domain, support, and provenance
   remain reconstructable for every estimator update and validation decision.
9. No raw phase epochs are joined and no D10 observation enters the estimator.
10. The claim remains a finite-evidence observability result, not calibration,
    physical qualification, lock, accuracy, or authority.

If any required condition fails, return the not-observable terminal unless an
identity or model-binding defect makes the study invalid. Do not average away
a failing gain/history case, select only the nominal result, or widen a
threshold after inspection.

## Stage 3A: deliverables when observability passes

When and only when the feasibility gate passes, create a concise non-effective
trajectory-study requirements document that freezes the next question but
does not implement or select a controller. It must specify:

- the validated equilibrium-state semantics and update evidence;
- the complete uncertainty representation to carry forward;
- a proposed finite-area phase manoeuvre abstraction that departs from and
  intentionally returns toward equilibrium;
- the constraints and failure states the trajectory planner must preserve;
- how observed frequency and same-epoch raw phase would update or abort a
  planned manoeuvre;
- required host/firmware parity and observe-only shadow evidence before any
  actuation proposal; and
- the exact additional authority a later prompt would need.

Do not create a policy, production estimator profile, firmware code, live host
surface, bundle, rehearsal, or authority proposal.

## Stage 3B: deliverables when observability fails

When the state is not observable or not decision-useful, create one concise
non-effective characterization requirements document. Identify:

- the exact unresolved parameter or confounding relationship;
- why existing retained evidence cannot resolve it;
- the smallest additional physical evidence capable of discriminating it;
- the necessary code-domain dwell, return, and reversal geometry at the level
  of scientific requirements;
- required duration/support count derived from the desired equilibrium
  precision and current 600-second quantization;
- necessary D14, D8, DAC epoch, response, temperature, and provenance records;
- prospective analysis, success, invalidity, and stop criteria;
- which existing operational path could carry the experiment; and
- the fact that no execution, bundle, activation, or physical authority has
  been created.

Prefer one largest safe finite characterization capable of answering the
question over a chain of micro-runs. Stay inside the established DAC envelope
when describing prospective requirements, but do not issue commands or create
effective authority.

## Stage 4: publish and close

Create one immutable machine-readable report containing:

- every frozen source and tool identity;
- exact predecessor and V1 reproduction results;
- the evidence inventory and validation partition;
- state, model, nuisance, and arithmetic semantics;
- structural-identifiability results;
- every equilibrium feasible set and sensitivity result;
- held-out prediction metrics;
- the derivation and value of the frozen usefulness threshold;
- an explicit check row for every feasibility-gate condition;
- the selected terminal and first discriminating failure;
- observed, reconstructed, derived, bounded, and modeled provenance labels;
- limitations and unexercised physical boundaries; and
- a canonical semantic digest and comparator identity.

Publish a concise reviewed `DECISION.md`. Update
`profiles/programme_status_v2.json` with a separately named closed offline
study entry, `active_programme: null`, historical-validation-only operations,
all physical-authority fields false, immutable report identities, and the next
gate. Update the current-support and sustained-hybrid programme documentation
only where necessary to point to the new terminal.

Do not rewrite either predecessor immutable report or decision. Do not mutate
historical run artifacts.

## Verification discipline

Add focused deterministic tests for:

- contract and source-identity validation;
- exact baseline reproduction;
- interval arithmetic and empty/unbounded feasible sets;
- gain sign and unit handling;
- quantization boundaries;
- segment and held-out partition isolation;
- DAC-epoch, session, settling, and phase-epoch reset semantics;
- every frozen model and nuisance branch;
- usefulness-gate evaluation and terminal selection;
- canonical report hashing;
- programme-status closure and authority guards; and
- absence of live, serial, firmware-flash, DAC-write, or control imports from
  the offline comparator.

Run the focused estimator-study, predecessor-study, programme-status, and
authority-guard tests. Run broader host tests only when shared offline or
status behavior changed. This task should not change firmware, so do not run a
firmware matrix merely for ceremony. If unexpected firmware or shared live
files are already changing concurrently, preserve them, keep this study
isolated, and report that unrelated verification boundary explicitly.

## Stop conditions

Stop and publish the corresponding bounded terminal when:

- a required source identity or exact baseline cannot be reproduced;
- the identification/validation partition would leak later outcomes;
- the equilibrium and gain are structurally confounded by retained evidence;
- the feasible set is empty, unbounded, history-ambiguous, or wider than the
  frozen usefulness limit;
- held-out prediction or a required sensitivity case fails;
- a conclusion would require calibrated uncertainty that does not exist;
- a conclusion would require joining raw phase epochs;
- the task would need a firmware/live-controller change;
- any next step would require serial access, flash, reset, DAC activity,
  physical rehearsal, or live authority; or
- the repository contains overlapping user work that cannot be preserved
  while making the offline changes.

Do not add evidence, change the split, add a model, relax a nuisance bound,
move the usefulness threshold, or reinterpret a failed case after inspecting
results. A materially different second attempt requires a new separately
frozen contract and explicit operator direction.

## Completion deliverables

Finish with:

1. a prospectively frozen estimator-feasibility contract and methodology;
2. an identity-bound deterministic offline estimator/comparator and focused
   tests;
3. an immutable machine-readable observability report;
4. a concise scientific decision separating facts, derivations, modeled
   bounds, assumptions, and limitations;
5. a closed offline programme-status entry with no physical authority;
6. exactly one non-effective next-step document: trajectory-study requirements
   if observable, or targeted-characterization requirements if not; and
7. one explicit next gate.

Report the outcome in decision-bearing terms. The result is evidence that an
equilibrium-state architecture is or is not sufficiently observable from the
retained finite data. It is never calibration, physical qualification, a
selected controller, or permission to operate the bench.
