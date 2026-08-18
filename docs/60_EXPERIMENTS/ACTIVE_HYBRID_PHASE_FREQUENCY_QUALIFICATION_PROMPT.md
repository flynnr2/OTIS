# Codex Prompt: Bounded Active-Hybrid Phase/Frequency Qualification and Seal

## Purpose

Close the completed CX319 mapping-informed frequency programme as frozen input,
then prepare and, only after a separate exact-bundle authority decision,
execute one decision-bearing bounded active-hybrid phase/frequency
qualification. Analyze, replay, seal and register every physical terminal.

The programme must answer one question:

> Can one coherent controller use the authoritative slow frequency estimate
> for acquisition and stability while a deliberately capped, reference-relative
> phase term materially influences the same DAC request, reduces the declared
> phase-movement metric, preserves frequency performance, and fails in a
> reconstructable bounded manner?

This is the next controller experiment. Do not perform another boundary map or
lower-reacquisition campaign unless a specific new result demonstrates that
the existing plant evidence is insufficient for this decision.

## Authority boundary

This prompt initially authorizes offline work only: evidence audit, tracked
programme closure, design, replay, implementation, tests, builds, structural
preflight, operational-path rehearsal and creation of a non-effective physical
authority proposal.

It does **not** initially authorize a firmware flash, reset, serial-device
access, command FIFO, setup stimulus, DAC write, control arm, physical
rehearsal or live acquisition. After the exact bundle and passing rehearsal
exist, stop and present them for a separate explicit operator decision.

Physical execution may continue only when that later decision identifies the
exact bundle and makes its progressive authority envelope effective. Authority
is consumed by the first physical terminal. Do not retry, extend or weaken a
criterion after seeing evidence.

## Frozen evidence handoff

Use, without modifying, at least:

- `runs/cx319_range_spanning/mapping_informed_part_b_v4_20260817/final_decision_20260818/cx319_mapping_informed_part_b_programme_seal_v1.json`;
- the Part A mapping-readiness record bound by that seal;
- the sealed lower acquisition, right-censored upper traversal and superseding
  upper-completion evidence bound by that seal;
- `profiles/estimators/cx317_pps_gated_selected_v1.json`;
- `profiles/estimators/cx318_relative_phase_selected_v1.json`;
- `profiles/plant_models/cx317_pps_gated_v2.json`;
- `profiles/discipline/cx319_stabilized_tight_deadband_v1.json`; and
- `profiles/discipline/cx319_conditional_part_b_hybrid_observation_v1.json`.

Revalidate exact hashes and semantic identities before using them. Preserve the
programme seal's claims boundary: two physical Part B acquisitions are bound;
the lower reacquisition is an inference, not a third independently observed
physical pass. Do not rewrite the original upper-completion bounded non-pass or
hide its host-only supersession.

The recent physical preview corpus contains 38,993 zero-authority hybrid
records and 22,787 `HYBRID_TRACKING_PREVIEW` records. Recompute, rather than
blindly copy, the following expected summary:

- 22 counterfactual correction proposals;
- 12 proposals with a nonzero phase term;
- 9 proposals whose phase term changes the rounded DAC delta relative to the
  same decision with the phase term removed;
- 7 step-limited proposals;
- zero range clamps; and
- zero `FAULT_PREVIEW` records.

These observations justify an active qualification proposal. They do not prove
physical phase steering because every proposed hybrid correction was
counterfactual.

## Claim boundary

The controlled phase quantity is cumulative D8 oscillator-cycle movement
relative to qualified D14 PPS within one declared phase epoch. D14 remains the
sole PPS/reference input, D8 remains the sole oscillator/count input, and D10
remains the independent external-event input. D10 must not enter reference
validity, phase authority or control eligibility.

The programme does not establish absolute phase, UTC alignment, calibrated
cable delay, traceable frequency accuracy, a phase-aligned PPS, predictive
holdover, or unrestricted operation. Phase epochs must never be joined using a
guessed offset.

D9/GPOUT0 output implementation and qualification are explicitly deferred.
They are a follow-on delivered-output programme after this controller result is
sealed. Do not change D8/D9 clock routing or claim a public output here.

## Stage 0: close the predecessor programme

Before creating the new active programme:

1. Validate the final Part B programme seal and every bound evidence identity.
2. Add a concise tracked CX319 terminal report stating observed facts,
   inference, superseding replay, limitations, last confirmed DAC state and
   the decision to proceed to bounded active-hybrid qualification.
3. Update `README.md`, `profiles/programme_status_v2.json`, the applicable
   roadmap, known-limitations document and CX319 programme index so none still
   claims that Part A or Part B is pending.
4. Preserve the ignored `runs/` evidence unchanged. Never force-add it.
5. State that a future flash or reset makes the physical applied code unknown
   until a new exact setup/application acknowledgement is captured.

Do not repeat physical acquisition merely to make the predecessor narrative
cleaner.

## Stage 1: create one coherent active controller

Use `p21600_cap1_epoch_reseed_v3` as the numerical baseline, not as standing
active authority. Its present identity is observational and retains historical
frequency-band semantics. Create a new descriptive active-hybrid policy and
programme identity that explicitly binds current tight-frequency semantics.

The controller must have one output and one actuator path:

```text
authoritative frequency term
          +
bounded relative-phase bias
          |
          v
one combined limited DAC delta
          |
          v
existing request -> authority -> acceptance -> application -> response path
```

Do not create independent frequency and phase DAC writers, a second hidden
integrator, or a phase path that can bypass the existing transaction authority.

Record for every decision:

- frequency estimate and exact source identity;
- phase estimate, phase epoch and continuity state;
- frequency term;
- phase term;
- combined error or demand before limiting;
- step, range, cadence, count and cumulative-budget limits;
- the final integer requested delta and code;
- the counterfactual integer delta with the phase term removed;
- whether phase materially changed the final integer request;
- authority, request, acceptance, application and response identities;
- actual applied code and DAC epoch observed by every downstream consumer; and
- explicit reason for actuation, hold, degradation, inhibition or fault.

A phase term is materially influential only when removing it changes the final
rounded requested DAC delta after the same declared limiting rules. A merely
nonzero floating-point phase term is not sufficient.

## Stage 2: states and progressive authority

Implement explicit states equivalent to:

1. `FREQUENCY_ACQUIRE` — frequency-only authority; phase term fixed to zero;
2. `PHASE_QUALIFY` — tight-frequency residence established while phase
   continuity and eligibility accumulate; phase term still zero;
3. `FIRST_PHASE_TRANSACTION` — authority for at most one phase-material
   application, followed by a mandatory response/reacquisition checkpoint;
4. `HYBRID_TRACKING` — remaining finite authority released only after the
   first checkpoint passes;
5. `PHASE_DEGRADED_FREQUENCY_ONLY` — phase authority revoked at a clean
   boundary while otherwise healthy frequency control continues; and
6. `FAIL_STATIC` — all automatic actuation disarmed at the last confirmed
   applied code.

Phase influence may begin only after all of the following are simultaneously
true:

- two fresh authoritative 600-second estimates establish `TIGHT_INSIDE`;
- D14 reference and D8 count qualification are current and continuous;
- GNSS metadata qualifies the same receiver that supplies D14 without
  replacing D14 as timing authority;
- one continuous valid phase epoch exists;
- the exact actual applied code and DAC epoch have propagated through the
  estimator, controller, preview/replay, recorder and response classifier;
- diagnostics, capture, queues, transport and transaction authority are clean;
- no request or response classification is outstanding; and
- the complete active policy, bundle and run identity match.

After the first phase-material application, block every subsequent request
until the applied epoch is exact, response support is fresh, response sign is
healthy, the response is replayed exactly, and frequency has re-entered
`TIGHT_INSIDE`. If this checkpoint passes, release the remaining authority
inside the same uninterrupted physical run. This conditional release must be
part of the prospectively frozen bundle; it must not be invented during the
run.

## Stage 3: offline replay, parity and fault proof

Replay the immutable Part A and Part B evidence through the new active policy.
Compare the baseline candidate with only a small finite set of justified
alternatives. Freeze the selected policy and all thresholds before physical
entry.

At minimum, compare:

- phase movement and maximum excursion within each valid phase epoch;
- pre- and post-influence phase slope or another prospectively defined phase
  metric;
- 600-second frequency residual RMS, tails and tight-band occupancy;
- acquisition, phase-qualification and hybrid-entry latency;
- correction count, path, net movement and efficiency;
- reversals, repeated alternation and chatter;
- phase-cap, step, range and cumulative-budget pressure;
- sensitivity to the measured plant-gain envelope; and
- deterministic behavior across DAC-epoch, reference, session and rollover
  boundaries.

The nominal baseline parameters are:

- 21,600-second phase pull-in horizon;
- absolute phase-bias cap of `1/600 Hz` (`0.0016666666666666668 Hz`);
- current controller gain of approximately
  `2884.5027706464516 codes/Hz/decision` if retained; and
- therefore approximately `4.8075` codes of controller contribution at the
  phase cap before combination and limiting.

Also record the distinct plant-equivalent interpretation of that frequency
bias. Do not conflate controller contribution with the code movement that
would statically offset the measured plant by the same frequency.

Require host/firmware parity over the complete decision state and the first
decision-bearing downstream consumer for:

- both correction directions;
- zero, small and capped phase terms;
- a phase term that does and does not change the rounded delta;
- frequency-only acquisition followed by bumpless phase entry;
- step/range/cadence/count/cumulative limiting and anti-windup;
- quantization alternation and direction-coherence holds;
- DAC-epoch reseed and same-code reapplication;
- phase step, phase discontinuity and phase-epoch invalidation;
- reference loss and bounded recovery;
- stale or changed GNSS metadata identity;
- snapshot discontinuity and legal RP2040 rollover;
- wrong-sign, absent, late and right-censored actuator response;
- evidence queue pressure, USB obstruction, serial-owner loss and priority
  abort; and
- terminal disarm with no latent or outstanding authority.

Run proportionate Fast, Campaign and affected Release verification plus all
current supported firmware profiles and relevant expected-failure guards.

## Stage 4: freeze and rehearse the exact physical programme

Prepare one exact 12-hour qualified active-hybrid programme with a 16-hour
absolute wall-clock limit. Derive and freeze the precise timing origin for both
limits. No live extension is allowed.

The intended maximum envelope is:

| Quantity | Maximum or rule |
|---|---:|
| Total automatic applications | 4 |
| Combined step | 21 codes |
| Cumulative absolute movement | 84 codes |
| Minimum applied cadence | 1,800 s |
| Hard DAC range | `0xA800..0xAB00` |
| Phase-bias magnitude | `1/600 Hz` |
| Outstanding requests | 1 |
| Automatic retry | forbidden |
| Automatic restoration | forbidden |

Frequency-only acquisition applications consume the same four-application and
84-code global budgets. They do not satisfy the requirement for a
phase-material transaction. If acquisition exhausts the budget, the result is
a bounded non-pass.

Choose the starting code from the final confirmed predecessor evidence and
current replay, but do not assume it remains physically applied. The exact live
setup transaction must re-establish and acknowledge the code, open a new DAC
epoch, and propagate that epoch through every relevant consumer before control
can arm.

Freeze before physical authority:

- selected controller, estimator, plant and response-policy identities;
- start code and setup provenance;
- phase sign, zero, epoch, unit and invalidation rules;
- numerical phase and frequency comparison metrics and materiality thresholds;
- qualification, pull-in, response and wall-clock boundaries;
- progressive-authority state transitions;
- command and acknowledgement envelope;
- all stop conditions and terminal classifications;
- exact firmware source, profile, configuration and binary;
- capture, supervisor, analyzer, replay, finalizer, seal and registration
  tools; and
- independent priority-abort delivery and terminal-clear requirements.

Rehearse the actual process topology, including setup propagation, one modeled
phase-material transaction, conditional release, response classification,
phase-only degradation, a shared fail-static fault, transport obstruction,
abort delivery, sole serial ownership, logical evidence rotation, analysis,
sealing and registration. Use deterministic or accelerated inputs for long
boundaries without claiming they reproduce the physical plant.

Produce a machine-readable non-effective authority proposal and a concise
readiness report, then stop for explicit operator authorization.

## Stage 5: physical qualification after explicit authority

After the exact proposal is explicitly authorized:

1. Keep the controlling Codex turn active and monitor authoritative supervisor
   state and retained evidence until a terminal state.
2. Establish continuous capture and exact identity before setup.
3. Apply and acknowledge the one exact starting stimulus.
4. Acquire frequency and enter `TIGHT_INSIDE`.
5. Establish the frozen within-run frequency-only comparison segment or other
   prospectively selected baseline needed for the phase-performance decision.
6. Qualify and enable phase influence.
7. Execute the first phase-material transaction and its mandatory checkpoint.
8. On checkpoint pass, continue automatically within the remaining frozen
   budget for the complete 12-hour qualified interval.
9. Stop at the first terminal condition, deliver any required priority abort
   before closing the sole serial owner, and retain the final static code.
10. Analyze, replay, seal and register the unchanged evidence.

Do not tune the controller, change thresholds, extend time, add authority or
restart after observing live behavior.

## Degradation and failure semantics

If only phase-specific evidence becomes invalid at a clean boundary, with no
outstanding request or unresolved response and with frequency/reference
evidence independently healthy:

- revoke phase authority;
- set the phase term to zero;
- invalidate the old phase epoch;
- continue inside the existing frequency-only and global movement budgets; and
- classify the active-hybrid result as a non-pass even if frequency remains
  healthy.

If phase invalidity occurs during a phase-influenced request, application or
response horizon, do not silently continue. Enter fail-static until the
transaction is resolved or the run terminates according to the frozen rule.

Any shared D14/D8 qualification loss, ambiguous DAC epoch, identity mismatch,
capture discontinuity, transaction/acknowledgement fault, wrong-sign response,
range/cadence/budget breach, serial-owner loss, evidence loss or failed abort
delivery is a shared fault and must stop fail-static. Missing or late evidence
is never clean, zero or unchanged.

## Prospective success criteria

The full physical programme passes only if all frozen common-health criteria
pass and:

- at least two complete applications are materially phase-influenced;
- the first transaction checkpoint passes before later authority is released;
- each required response is observed after the declared settling and fresh
  support boundaries and has the predicted physical sign;
- frequency returns to and retains the frozen `TIGHT_INSIDE` criteria;
- the declared reference-relative phase metric improves against the frozen
  comparison without material frequency degradation;
- no persistent alternation, chatter, uncontrolled reversal, clamp or
  low-efficiency path fault occurs;
- every range, step, cadence, count and cumulative budget is respected;
- firmware records and independent host replay agree on every term, limit,
  state, request and downstream DAC epoch;
- capture, GNSS/D14 qualification, D8 measurement, queues, transport and
  actuator response remain healthy; and
- the terminal has one confirmed static code, no outstanding request and no
  latent authority.

A stable hold with no phase-material application is benign frequency evidence
but cannot pass active-hybrid qualification. A single successful
phase-material application may pass the internal causal checkpoint but cannot
pass the complete programme's repeatability requirement.

## Predeclared terminal decisions

Choose exactly one primary decision:

- `bounded_active_hybrid_control_passed`;
- `phase_influence_not_exercised`;
- `first_phase_transaction_passed_sustained_result_incomplete`;
- `phase_channel_degraded_frequency_control_retained`;
- `hybrid_response_wrong_or_frequency_not_reacquired`;
- `hybrid_policy_chatter_or_budget_nonpass`;
- `frequency_performance_materially_degraded`;
- `right_censored_incomplete`;
- `measurement_authority_or_platform_fault`; or
- `operator_abort`.

Classify additional failures without obscuring the primary decision. Preserve
scientific controller rejection, plant/actuator response failure, platform or
harness failure, and operator abort as distinct outcomes.

## Stage 6: replay, seal and tracked conclusion

Every physical terminal, including prewrite and partial terminals, must be
finalized. The analyzer must consume the immutable run manifest and evidence
snapshot with which the acquisition was created.

Required finalization:

1. Validate capture completeness, identities, clock domains, sessions,
   ordering and all declared contracts.
2. Reconstruct every measurement, controller decision, request, acceptance,
   application, response and budget transition independently on the host.
3. Verify phase-materiality by replaying each decision with the phase term
   removed while keeping every other input and limit identical.
4. Preserve raw phase, modeled/counterfactual phase and observed physical
   response as distinct quantities.
5. Report the frozen frequency and phase metrics without moving their
   thresholds after seeing the result.
6. Verify priority-abort submission and delivery separately and prove the
   terminal code and authority state.
7. Create an immutable evidence snapshot, analysis, decision seal and external
   registration record.
8. Revalidate the sealed package and its content identities.
9. Add a concise tracked report under `docs/60_EXPERIMENTS/` stating the
   decision, evidence, limitations, final hardware state and next step.
10. Update roadmap, programme status, control semantics and known limitations
    when the result materially changes them.

The final seal must state exactly how many frequency-only, phase-nonzero and
materially phase-influenced physical applications occurred. It must not call a
counterfactual proposal an observed actuator response or infer repeated
physical success from an unrun leg.

Do not redefine an acceptance path after acquisition. A host-only superseding
replay may correct implementation of a frozen predicate over unchanged raw
evidence, but it may not move that predicate. If the frozen programme does not
pass, seal the honest non-pass and use it to decide the next bounded
experiment.

Stop after the result is sealed, registered and reported. D9/GPOUT0 output
implementation and its focused integrated hybrid confirmation are the next
programme only after successful hybrid steering.
