# Codex Prompt: Cross-Campaign Adaptive-Steering Evidence and Finite Policy Decision

## Purpose

Use OTIS's sealed, completed physical evidence to answer the next controller
decision before changing the live instrument:

> Does a small, prospectively frozen change to the successful CX322 coherent
> FLL/PLL law improve frequency, D14-relative phase and actuator-cost behavior
> enough to justify implementation, while recoverable metadata, phase, model
> and shadow conditions are moved out of acquisition-failure semantics?

This is an offline analysis and design programme. It is not another plant
characterization campaign, a new estimator programme, or permission to touch
the board. Start from the existing CX322 law and existing analyzers. Build one
provenance-preserving cross-campaign derived view over immutable canonical
records; do not create a parallel capture, telemetry or controller stack.

The architectural basis is
[`ADAPTIVE_FREQUENCY_STEERING.md`](../10_REFERENCE_ARCHITECTURE/ADAPTIVE_FREQUENCY_STEERING.md).
Its historical claims and terminals remain unchanged.

## Immediate operating boundary: an unrelated GNSS baud soak is active

The bench is running the GNSS baud-envelope soak. Treat that acquisition as an
invariant until the operator says it has stopped, finalized and sealed.

During the soak this prompt authorizes only:

- read-only inspection of completed evidence packages and repository sources;
- an isolated Git worktree that is not the soak's active checkout;
- host-only derived analysis, replay code, deterministic fixtures and tests;
- tracked contracts, reports and implementation specifications; and
- exact source-change proposals for later firmware work.

During the soak it does **not** authorize:

- opening, probing or enumerating a serial device;
- reading from or writing to the live capture, supervisor, command, finalizer
  or monitor processes;
- reset, upload, flash, DAC write, control arm or physical rehearsal;
- firmware compilation or a build command that might discover a board;
- editing, switching or cleaning the active soak checkout;
- reading the active GNSS soak as an input to this study; or
- stopping, rotating, sealing or otherwise helping the soak.

Do not infer that a shell command is safe merely because its intended result is
offline. Use an explicit isolated worktree and host-only commands. If the
separation cannot be proved, stop.

## Decision-bearing deliverables

Produce all of the following:

1. an immutable source ledger and machine-readable analysis contract;
2. one normalized cross-campaign derived evidence view with exact provenance;
3. multi-horizon phase, stability, response, environment, actuator and hold
   analyses;
4. exact replay of each source under its own recorded law/envelope, plus exact
   unchanged-CX322 replay on CX322 and explicitly counterfactual application
   of that calculation to other applicable chronologies;
5. a finite, prospectively frozen comparison of the unchanged law and no more
   than three minimal changed candidates;
6. a provisional recommendation to retain CX322 unchanged or carry exactly one
   bounded delta to the later D9/FLL-output gate;
7. an implementation-ready operational-semantics specification and
   deterministic fault matrix; and
8. a clear stop report identifying what now requires firmware integration,
   compilation, rehearsal and physical evidence.

Do not create a successor firmware profile, live bundle, physical authority,
activation or Attempt 5 in this offline programme.

## Primary immutable evidence

At minimum bind and validate these three completed packages:

| Role | Package | Historical boundary |
|---|---|---|
| Qualified FLL baseline | `runs/cx317_bounded_closed_loop_acquisition/campaign_20260803T080615Z/stage7/part_b_final_20260807T073432Z` | Sealed 24-hour frequency-control endpoint. No native relative-phase file; reconstruct only when the exact canonical D14/D8 records and historical domain contract permit it. |
| Positive coherent controller | `runs/cx322_bounded_hybrid_fact_gathering/stage5_live_attempt7_20260822T1921Z` | Sealed 12-hour CX322 acquisition with four phase-material applications. |
| Sustained maintenance/reversal evidence | `runs/otis_sustained_hybrid_regulation_v1/live_attempt4_20260823T2148Z` | Retained 40,537-qualified-second chronology with eleven applications and a natural reversal. Preserve its failed physical-qualification terminal and its independently replayed low-efficiency result. |

Use the exact package manifest, applicable terminal attestation,
content/evidence snapshot and consumed-file hashes that each historical source
actually retained. Validate a historical artifact against the manifest and
tool revision that created it; do not demand that it satisfy the current
expanding product matrix.

The following completed sources may be added with explicit, narrower roles
when their applicable attestations and identities validate:

- the fixed-code Stage 3 baseline for measurement/noise context;
- CX319 Part A and its provenance-linked superseding reanalysis for
  multi-code response, settling and history context;
- completed CX319 Part B streams for preview and traversal context, without
  joining their phase epochs;
- CX320 Attempt 9 for its near-resolution combined response;
- targeted-characterization Attempt 6 for repeated lower/centre/upper dwells
  and held-out environment/history checks; and
- older Run 020 or recovered Stage 5 products only as separately labeled
  prior/sensitivity evidence, never pooled as current selected-600 evidence.

Failed attempts before scientific stimulus may be used only to analyze the
specific platform or metadata failure. They are not controller-performance or
stability populations.

Do not include the active GNSS baud soak, an unsealed substitute run, a live
file, or a package merely because it has a familiar directory name.

## Stage 0: freeze source authority and the analysis contract

Before calculating study results, create a versioned machine-readable contract
that freezes:

- every allowed source package and the strongest terminal attestation and
  package identity its historical contract actually retained: physical seal,
  exit gate, transitive reviewed binding, evidence snapshot, registered
  content digest or an explicit `not_retained` field;
- the exact source files consumed and their SHA-256 digests;
- source revision, firmware/build/profile/policy/analyzer identities;
- board, receiver and topology identities where the packages retain them;
- capture backend, counter domain and rollover semantics;
- estimator and relative-phase method/configuration identities;
- the acquisition terminal, scientific terminal, allowed analysis roles and
  explicit exclusions for every source;
- all segmentation and qualification rules;
- phase horizons and ADEV/HDEV tau grid;
- response horizons, settling rules and censoring rules;
- selected-600 opening boundary, inclusive/exclusive frontier rules, alignment
  origin after boot/gap/settling, and whether a deliberately skipped window
  advances that origin;
- environmental source, role, lag, freshness and missingness rules;
- controller candidates, exact numerical parameters and state-reset rules;
- the exact post-divergence counterfactual model: equations/version, state at
  the divergence frontier, DAC-to-frequency and frequency-to-phase
  propagation, minimum/nominal/maximum gain cases, disturbance/residual
  construction, uncertainty/conservatism, held-out validation and invalidity
  rules;
- evaluation metrics, thresholds, ranking and terminal outcomes; and
- output schema, paths and semantic digest procedure.

Hash the contract before candidate result rows are generated. If an input
defect requires a semantic change, create a new contract version with a
pre-result rationale. Never silently edit a frozen contract after inspecting
candidate performance.

Do not require an older source to possess a later package/seal concept. Require
the strongest applicable historical identity, exact consumed-file hashes and
explicit missing provenance fields. The study is invalid, rather than
partially persuasive, if a required source's own recorded identity or own-law
replay does not reproduce. Require unchanged CX322 request-law replay only on
CX322 evidence. CX322's four-application envelope and Attempt 4's separately
identified sustained law/envelope are different historical inputs; running
CX322 mathematics over Attempt 4 is counterfactual from the first evaluated
frontier, not exact historical replay.

## Stage 1: build one logical cross-campaign derived view

Extend the existing replay and analyzer path. Reuse, rather than fork, the
semantics in:

- `host/otis_tools/measurement_replay.py`;
- `host/otis_tools/control_evidence_replay.py`;
- `host/otis_tools/pps_cumulative_span_estimator.py`;
- `host/otis_tools/active_hybrid_live_analyze.py`; and
- the existing evidence index, contracts and time-domain helpers.

The output is a derived analysis product, not a new canonical wire format. Put
every output in a separate derived package/tree. Write nothing—including a
convenience index, cache or report—below any source package root. Raw CSV
files, manifests, seals, prior reports and historical terminals remain
byte-for-byte unchanged. Prove pre/post equality of each registered full-tree
content identity, or of its exact registered file manifest plus absence of
added files where no full-tree digest exists.

Use one manifest plus normalized derived tables rather than a guessed flat
join. Every analytical row must carry a common source binding and, where the
source makes the field applicable:

- source campaign, run, package, package identity, terminal-attestation class
  and identity, and source-file hash;
- source revision, build, profile, policy and analyzer identity;
- capture session, capture backend and exact clock/counter domain;
- D14 reference and D8 count sequences, snapshots, qualification and flags;
- estimator identity, configuration and exact source frontier;
- phase method, phase epoch and phase observation frontier;
- applied code, DAC epoch, transaction and request/application/response
  identity;
- controller state, authority and exact hold/degraded/inhibit/fault reason;
- environmental sample identity, source, role, domain, age, freshness, flags
  and missingness; and
- an explicit availability or exclusion reason for every inapplicable field.

Never encode unavailable as zero, unchanged, healthy or causally current.
Never forward-fill across a session, domain, sequence, phase, DAC or declared
continuity boundary.

At minimum emit normalized products equivalent to:

- source/package ledger;
- qualified D14/D8 interval and continuity segments;
- selected-estimator analysis windows;
- phase windows;
- actuator transactions and response horizons;
- controller, hold and degraded episodes; and
- environmental associations.

Each derived artifact must bind the frozen contract digest, tool revision,
generation time and exact source-file digests.

### Continuity and segmentation

Build one shared segmenter and make every analysis request its relevant
continuity keys. Break, reject or explicitly stratify at least on:

- capture-session change;
- counter-domain, backend, nominal-source or configuration change;
- illegal counter movement or unknown rollover contract;
- nonconsecutive snapshot, count or D14 reference sequences;
- invalid observation, capture or qualification flags;
- missing interval or undeclared discontinuity;
- phase-epoch change for every phase-derived product and for the primary
  requested ADEV/HDEV view; a separately labeled frequency-domain sensitivity
  view may omit that break only when D14/D8 continuity remains exact and it
  makes no phase-continuity claim;
- DAC application/epoch and settling boundary when the analysis claims
  fixed-code or response behavior; and
- terminal, reset, boot or source-identity contradiction.

Do not join a phase zero across epochs or runs. Do not hide control
applications inside a claimed stationary/fixed-code segment. A separately
labeled whole-controller stability view may include declared applications as
real operating behavior, but it must not be confused with fixed-code plant
stability.

## Stage 2: compute the retained-evidence view

### Multi-horizon D14-relative phase

For horizons exactly:

`600, 1500, 3600, 7200, 21600 seconds`

compute within every eligible contiguous, unjoined phase epoch:

- signed and absolute OLS slope in D8 cycles per D14 second;
- exact slope numerator/denominator where integer evidence permits it;
- signed endpoint movement;
- peak-to-peak phase excursion;
- maximum absolute excursion from the window origin;
- window count and excluded-window reasons; and
- application-anchored pre/post windows where exact support exists.

Define alignment and overlap prospectively. Report unavailable when a segment
cannot support a complete horizon; never shorten a horizon or bridge an epoch.
For old packages without native relative-phase records, reconstruct only from
exact adjacent D14/D8 integer evidence under a named derived method. Label that
method and never imply a historical firmware phase observation existed.

### ADEV and HDEV

Implement reusable overlapping Allan deviation and overlapping Hadamard
deviation over contiguous, qualified D8-relative-to-D14 fractional-frequency
observations. There is no current reusable implementation; do not copy an
unreviewed one-off result from a historical report.

The contract must freeze an integer tau grid and minimum difference-term count.
Include the requested phase horizons when statistically supportable and use a
prospectively declared logarithmic grid for shorter tau. For every result
record:

- statistic and estimator definition;
- tau and base sampling interval;
- segment and population identity;
- overlap policy and exact difference-term count;
- fractional-frequency value and 10 MHz-equivalent Hz value;
- detrending policy, which defaults to **none**;
- quantization/reference/calibration limitations; and
- exclusion or insufficient-support reason.

Do not form a difference term across a capture gap, phase epoch or undeclared
discontinuity. Pool same-tau numerators across eligible segments only under an
explicit term-count-weighted rule; never stitch segment endpoints. Report
fixed-code, FLL-controlled and coherent-controlled populations separately.

These are empirical end-to-end D8-relative-to-D14 stability results. They are
not traceable oscillator-only specifications because receiver sawtooth,
reference calibration, cable delay and complete uncertainty are unavailable.

Use analytic fixtures with known constant, linear and quadratic phase or
frequency behavior and assert exact term counts before accepting physical
results.

### Frequency performance

Reconstruct one common selected, fresh, non-overlapping 600-second estimator
where source contracts allow it. Preserve the historical estimator records and
identities as separate evidence; do not silently replace them.

Use the contract's exact opening/alignment rule. Bind the first included D14
boundary, whether source frontiers are inclusive, the reset origin after every
gap/application/settling boundary and whether a deliberately excluded window
advances the non-overlap origin. These choices are decision-bearing inputs to
RMS, occupancy, recovery and persistence; they may not be selected after
seeing the result.

For each campaign and declared control-state population compute:

- RMS signed frequency error;
- median, tails and maximum absolute frequency error;
- signed quantiles;
- occupancy in prospectively frozen common bands;
- historical policy-state occupancy as a separate measure;
- qualified duration and excluded duration/reasons; and
- recovery to the common band after each application, with censoring.

Do not mix overlapping 60-second diagnostic estimates with the authoritative
selected-600 population. Mark comparisons incompatible where source,
estimator or qualification semantics cannot be reconstructed into the common
view.

### Response horizons

Generalize the same-DAC-epoch and right-censoring work beginning at
`host/otis_tools/active_hybrid_live_analyze.py::_response_horizon_facts`.
Retain its useful explicit censoring but close an important gap: selecting the
first AHY decision after a target timestamp is insufficient unless the
decision's complete source window and actual horizon are known.

Freeze two distinct estimands rather than moving the requested horizon
silently:

- `trailing_selected600_at_horizon`: a complete 600-second window whose opening
  is no earlier than the application, whose closing is at or after the target
  horizon, and whose requested and actual closing horizons are both reported;
  this may include the declared settling transient and must say so; and
- `settled_selected600_at_horizon`: the same estimator with its opening no
  earlier than `application + settling_exclusion`. It is unavailable at early
  horizons that cannot support a full settled window.

For each exact application and each frozen response horizon:

- bind request, acceptance, application, applied code and DAC epoch;
- identify the pre-application estimator frontier;
- bind the post estimator's opening and closing frontiers and require them to
  satisfy the selected estimand exactly;
- require the same applied code and DAC epoch throughout support;
- report requested and actual elapsed horizon separately;
- compute signed response and code-domain gain only when support is exact;
- classify wrong sign, near resolution, overshoot and recovery; and
- right-censor at a subsequent application, authoritative D14/D8/session/count
  continuity or identity break, terminal or lack of full support.

GNSS serial-metadata loss marks control ineligibility/hold. It does not censor,
erase or invalidate an otherwise exact D14/D8 response observation. Record the
response as scientific evidence and separately gate its use for later control
until causal metadata requalification.

Missing/right-censored response is not zero response. Do not reuse later
physical observations for a counterfactual code path after divergence.

### Environment

Use environmental records only as labeled covariates. At minimum:

- filter exact `source=sht4x`, `role=vcocxo_near`, valid flags for primary
  nearby-air temperature/humidity;
- keep BMP280 temperature and pressure separate;
- join in the declared device counter domain with explicit wrap handling;
- retain sample sequence, age, freshness and missingness;
- exclude settling and analyze inside exact fixed-code/DAC-epoch and
  control-state regions;
- freeze lag values and minimum range/sample requirements before fitting; and
- report within-campaign and held-out/leave-one-campaign-out consistency.

At minimum report descriptive ranges, temperature rate, correlation and simple
prospectively defined slopes with their support. Do not call a nearby-air
association an OCXO temperature coefficient, internal state, causal effect or
predictive authority.

Preserve the historical targeted-characterization report unchanged. Its
existing analyzer collects every nonempty `temperature_c` row, including
BMP280, while labeling the aggregate `SHT41_nearby_air`. Correct the filter only
in the new derived analysis and add a deterministic regression for source and
role separation.

### Actuator, hold and operating cost

For every campaign report at least three non-interchangeable duration
denominators:

- authoritative D14/D8 measurement-qualified duration;
- control-decision-eligible duration; and
- settled same-code duration.

GNSS metadata hold remains inside measurement-qualified duration but outside
control-eligible duration. Settling remains outside control-eligible and
settled same-code durations. Every rate must name its denominator; do not let a
new hold semantic improve a rate by silently shrinking exposure.

Then compute:

- application/correction count and applications per named duration hour;
- absolute DAC path, net movement and path per named duration hour;
- net/path efficiency, explicitly `abs(net movement) / absolute path` when
  path is nonzero;
- step distribution and code residence;
- direction reversals and repeated alternation;
- response class, wrong-sign response, overshoot and censored recovery;
- phase-material versus frequency-only applications;
- settling and ineligible time;
- hold/degraded episodes, duration, lost control opportunity and recovery; and
- terminal code, outstanding demand and exact terminal classification.

Keep code-domain conclusions separate from unmeasured DAC voltage. Compare the
qualified FLL, CX322 and sustained Attempt 4 directly where common semantics
exist. Represent FLL phase metrics as reconstructed or unavailable, never zero.
Preserve Attempt 4's formal failed qualification and its useful retained
scientific chronology simultaneously.

## Stage 3: evaluate one finite controller delta

### Baseline and candidate limit

Start from the unchanged CX322 measurement, phase and combined request law.
Do not introduce a new estimator, durable equilibrium code, drift predictor,
thermal model or controller family.

Freeze no more than these three policies:

1. `cx322_unchanged`;
2. `cx322_tagged_debt_with_bounded_backcalculation`; and
3. `cx322_tagged_debt_backcalculation_plus_same_sign_persistence`.

Bounded clamp/back-calculation anti-windup is mandatory for every candidate
that retains debt; it is not an optional unsafe comparator. Do not add a grid
of tunings or rescue a failed candidate after inspection.

The contract must freeze one exact value for each undecided parameter before
candidate evaluation, including:

- same-sign consecutive-window count;
- interval construction and the treatment of an interval containing zero;
- cadence-blocked debt accrual or non-accrual;
- maximum debt and fixed-point/rational representation;
- rounding rule;
- settling, hold, age and requalification behavior;
- reset/freeze/discard rules at session, DAC, phase and identity changes; and
- component allocation/back-calculation after an actual application.

Use exact `accumulated_edge_error_counts`, the bounded PLL contribution and the
frozen count-quantization model to construct the **combined correction-demand
interval**. Do not create sign persistence from a rounded display frequency.
The persistence sign is the sign of the bounded combined correction-demand
interval after applying the positive plant-gain envelope. An interval
containing zero has no sign for this purpose, including when the FLL and PLL
terms oppose one another.

### Tagged correction debt

Debt is a derived code-domain state, not authority. Retain at least:

- total, FLL-origin and PLL-origin debt;
- sign and exact rational/fixed-point representation;
- capture session, D14/D8 source frontier and estimator identity;
- applied code and DAC epoch;
- phase epoch/frontier for the PLL component;
- plant-gain and policy identity; and
- update, freeze, discard or back-calculation reason.

The controller still produces one combined integer request through the
existing transaction path. Phase-origin attribution is mandatory so phase loss
cannot leave hidden PLL debt actuating in FLL fallback.

The unchanged CX322 increment is the complete raw code demand produced by its
existing gain multiplied by its combined FLL/PLL frequency demand. It is not
only the fractional part of that number. Bounded fractional debt may be
committed either by the explicit eligible zero-request decision transition or
as the residual after a confirmed actual application.

The minimal application-path reference behavior to compare is:

```text
candidate_debt = prior_committed_debt + unchanged_CX322_full_raw_code_demand
limited_demand = apply_existing_step_and_range_limits(candidate_debt)
integer_request = frozen_signed_round(limited_demand)
debt_after_confirmed_application = limited_demand - actual_applied_delta
```

Demand removed by a hard step/range limit must not remain as an unbounded
hidden integrator. At an outward hard endpoint, outward debt back-calculates or
clamps according to the frozen rule. Unknown application, contradictory epoch
or missing acknowledgement remains an actuator-provenance fault.

Debt needs an explicit transaction commit protocol:

- retain one committed debt state and a separate immutable pending proposal
  bound to the exact request/decision identity;
- do not mutate committed debt or persistence while a request, acceptance,
  application or required response is outstanding, except for the single
  application-commit transition defined below;
- at an otherwise eligible, cadence-eligible causal decision whose bounded
  demand rounds to zero, atomically commit that bounded post-limit residual as
  debt, advance its exact evidence frontier and emit a non-actionable
  `debt_updated_without_request` decision; do not invent an `ACT` transaction;
- when cadence, hold or unsatisfied persistence suppresses evaluation, do not
  commit the current increment: retain prior committed debt unchanged and
  record the exact suppression reason;
- on exact application acknowledgement **and** exact applied-code/DAC-epoch
  propagation through the first dependent consumer, atomically replace
  committed debt once with the residual calculated from the confirmed applied
  delta and advance its causal frontier; then freeze it while the required
  response remains outstanding;
- if an authoritative rejection or expiry is confirmed before acceptance,
  discard the pending proposal and leave prior committed debt unchanged,
  applying the frozen persistence reset/freeze reason;
- if acceptance wins, complete and acknowledge the exact bounded transaction
  before any further decision; and
- if neither rejection/expiry nor acceptance obtains a bounded authoritative
  outcome, make debt non-actionable and enter actuator-provenance fail-static.

Freeze every no-application case explicitly. The initial reference semantics
are: cadence/hold/unsatisfied-persistence and phase-direction holds do not
commit the current increment; exhausted finite authority freezes prior debt as
non-actionable; and a hard endpoint back-calculates the outward component to
zero before any zero-request residual is committed. No suppressed demand may
remain as hidden unbounded authority.

For the persistence candidate, pre-threshold intervals qualify persistence but
do **not** accrue committed or pending debt. Once persistence is satisfied, add
only the current cadence-eligible full CX322 raw code demand; do not silently
sum all suppressed intervals and increase loop gain. Persistence advances only
on fresh, non-overlapping, contiguous intervals with the required combined
demand sign, same session, exact applied code/DAC epoch, complete settling,
causal frontier and compatible phase state. A zero-containing interval cannot
advance persistence or create new debt. Freeze valid history through a
metadata hold, but require a new complete post-requalification observation
before any request.

After debt composition, step/range limiting and rounding, retain the existing
phase-direction-coherence gate. Debt must not create a request whose direction
violates the unchanged phase-authority rule. Reconstruct the exact
frequency-only counterfactual by applying the same debt/limit/rounding path
with the current PLL increment and all PLL-origin debt removed. Define
`phase_materially_influenced` from whether that integer request differs; use
that identity for component attribution and every phase-efficiency claim.

### Replay claim boundary

Emit three separate layers and never blend their claims:

1. **Exact historical replay** — replay each physical chronology under its own
   recorded policy and finite authority envelope. It must reproduce every
   retained decision, integer request, application and state exactly. Require
   unchanged CX322 calculation replay on CX322 evidence only. Attempt 4 must
   first reproduce under its separately bound sustained policy; applying CX322
   or a candidate to Attempt 4 begins a causal counterfactual at the first
   evaluated frontier. Compare envelope limits and request-law effects
   separately.
2. **Causal one-step counterfactual** — at a retained decision frontier, a
   candidate may consume only evidence that physically existed before that
   frontier. This remains exact only until its first different application.
3. **Modeled continuation** — after the first candidate/historical application
   divergence, every plant, phase and subsequent controller result is an
   explicitly modeled counterfactual under the contract's frozen equations,
   gain cases, state initialization, disturbance construction and uncertainty
   bounds.

After divergence the observed plant belongs to the historical applied-code
path. It is not physical evidence for the candidate, even if the code paths
later meet numerically. Record the first divergence frontier and never rejoin
the physical-claim layer. Validate the model independently against held-out
retained responses and reject its decision-bearing use when its frozen
validity gates fail. A model-invalid candidate may appear only as sensitivity;
it cannot support recommending a changed policy.

Use CX322 and Attempt 4 for own-law exact replay followed by the explicitly
labeled counterfactual comparisons above. Use the qualified FLL and additional
completed/attested sources as baselines, plant bounds, perturbations or
held-out checks only where their schemas and authority make that valid.

### Selection rule

Freeze exact thresholds before candidate evaluation. Correction debt or
persistence may be provisionally recommended only if the candidate:

- preserves every identity, safety, range, cadence and transaction invariant;
- is no worse than CX322 on the frozen frequency RMS, tail and band-occupancy
  gates over all required retained-gain/sensitivity cases;
- is no worse on the frozen phase-slope and excursion gates;
- is no worse on path per hour, reversal/chatter, application count and
  recovery gates;
- materially improves the prospectively declared frequency, phase **and**
  actuator-cost decision metrics rather than trading an unbounded loss in one
  for a gain in another; and
- passes every gap, epoch, hold, saturation and transaction perturbation.

The post-divergence model must also pass its frozen held-out and uncertainty
gates in every case required by the contract. If it does not, no changed
candidate may be recommended from modeled continuation; retain the unchanged
law provisionally unless an own-law replay mismatch makes the whole study
invalid.

If no changed candidate clears the frozen rule, provisionally retain the
unchanged CX322 request calculation. Still proceed with the operational
hold/degraded-state corrections below; they are containment defects, not an
excuse to select an inferior controller.

The offline result is provisional until the output programme's D9 waveform and
frequency-only FLL-output soak gate passes. That later evidence may confirm the
recommendation or reveal output non-interference/resource behavior that blocks
integration. It may not be used to retune a failed candidate silently.

Allowed study terminals are:

- `provisional_finite_policy_delta_recommended_pending_d9_gate`;
- `provisional_cx322_unchanged_pending_d9_gate`; or
- `study_invalid_due_to_evidence_or_replay_mismatch`.

## Stage 4: freeze operational semantics independent of policy selection

These are implementation/containment corrections supported by current
evidence. They do not require another general plant-characterization run.

### Transaction-aware `GNSS_METADATA_HOLD`

Separate GNSS serial-metadata qualification from authoritative D14/D8 health.
The current host terminal at
`host/otis_tools/active_hybrid_live_supervisor.py` around line 932 and the
combined firmware predicate in
`firmware/arduino/otis_nano_rp2040_connect/otis_cx317_active_live.cpp` around
line 379 are concrete change sites.

Freeze and test this race-free behavior:

- metadata loss with no request created: consume/withdraw any unused live arm,
  inhibit new actuation requests and enter `GNSS_METADATA_HOLD` at the last
  confirmed DAC code;
- request created privately on Core 1 but not durably released to Core 0:
  withdraw it locally, consume its unused arm, durably record the exact
  withdrawal identity and enter hold; do not publish a newly ineligible
  request;
- request durably released to Core 0 but not accepted: do not clear a Core 1
  flag or invent an owner-cancellation protocol. Let the existing sole
  actuator owner resolve that exact request within its bounded
  acceptance/rejection/expiry contract;
- acknowledged rejection/expiry before acceptance: record it and enter hold
  with no application;
- acceptance wins: complete and acknowledge that exact bounded transaction,
  then hold all later actuation requests;
- application complete but response pending: retain exact transaction/epoch
  state, continue recording and interpreting exact D14/D8 response evidence,
  but do not use it to re-arm control before fresh causal metadata
  requalification;
- no bounded authoritative rejection, expiry or acceptance outcome; unknown
  application; contradictory DAC epoch; or missing acknowledgement: fail
  static as actuator-provenance uncertainty; and
- recovery: require fresh qualifying metadata and a complete causally later
  D14/D8 observation before any new actuation decision.

During metadata hold, D14/D8 capture, relative-phase accumulation, canonical
telemetry, non-actionable controller/diagnostic decisions and acquisition
continue. Preserve valid pre-hold history, while preventing it from acting as
the sole post-recovery decision support. Record hold entry/exit, duration,
transaction phase, lost opportunity and exact requalification frontier.

The same outstanding-transaction rule applies if phase authority disappears:
inhibit future phase requests; withdraw a private unreleased request; allow a
released request to reach its bounded owner-resolved rejection/expiry or
accepted completion; preserve its application/response evidence; then enter
the appropriate FLL fallback. Never undo an accepted phase-material request by
clearing local state.

### Phase and low-efficiency degradation

- Missing, stale, stepped or rejected phase evidence removes the PLL term and
  discards PLL-origin debt after the outstanding-transaction rule above;
  healthy frequency evidence and valid FLL-origin debt fall back to the
  existing FLL. Discarded PLL debt is never silently reactivated; new phase
  contribution requires a fresh qualified phase frontier.
- Hybrid/path low efficiency must first be attributed over a prospectively
  frozen causal window using each applied request's exact
  `phase_materially_influenced` identity and tagged path components. Degrade to
  conservative FLL only when the degrading component is demonstrably
  PLL/phase-local.
- Repeated low efficiency in frequency-only fallback may inhibit further
  automatic actuation while D14/D8 acquisition continues; it is not evidence
  that measurement failed.
- A contradiction of the indispensable positive-gain/range envelope may hold
  or fail-static actuation because reactive conversion is no longer supported.
  Keep that distinct from rejection of an optional equilibrium/predictive
  model.

### Model, shadow and D10 containment

- Optional model or shadow failure is local to that estimator. It must not
  change canonical records, baseline decisions, transactions, authority,
  queues or non-shadow terminal state.
- The current active phase estimator is not the optional future shadow; do not
  weaken its active-policy semantics by relabeling it.
- A future shadow needs bounded nonblocking input, local drop/status counters
  and kill/stall/corruption invariance tests.
- D10 remains external-event evidence. D10-local absence, noise, invalidity,
  overflow or queue failure remains D10-local.

Retain fail-static automatic actuation for authoritative D14/D8 contradiction,
capture/session/order corruption, applied-code or DAC-epoch contradiction,
acceptance/application/acknowledgement uncertainty, safety/range violation or
shared-capture compromise.

Produce an exact state-transition table, telemetry/schema impact map, host and
firmware change map, and deterministic fixture matrix. Add no new field merely
for narrative convenience; extend existing `AHY`, `ACT`, status and diagnostic
records only for a decision-bearing missing identity or state.

## Stage 5: offline implementation and verification

While the baud soak remains active, implementation may cover only the isolated
host analysis/reference path and deterministic tests. It may produce a precise
firmware patch plan, but must not edit the active soak checkout or compile
firmware.

Required host tests include:

- source/package/file hash mismatch and immutable-source assertions;
- every segment break, legal rollover and incompatible-domain rejection;
- no phase-epoch joining;
- known ADEV/HDEV fixtures and exact term counts;
- all phase horizons and insufficient-support handling;
- trailing-at-horizon versus fully settled response support and every censor
  reason;
- environment source/role/flags, staleness, missingness and timer wrap;
- application/path/reversal and all three named duration denominators;
- each source's own-law replay, exact CX322-on-CX322 replay and
  first-divergence labeling;
- debt update, rounding, cap, reset, freeze, discard and back-calculation;
- same-sign persistence, zero-containing intervals and non-overlap;
- unused-arm and private-unreleased-request withdrawal, released-pending owner
  resolution, accepted completion and response-pending metadata hold;
- phase loss to FLL fallback, low-efficiency degradation and static inhibit;
- shadow kill/stall/corruption invariance; and
- D10-local failure isolation.

Run focused host tests only. Do not use a broad firmware matrix as a proxy for
the offline decision.

## Mandatory stop and later physical sequence

Stop the offline task when the source ledger, frozen contract, derived results,
candidate decision, operational state table, deterministic host tests and
firmware change map are complete.

After the operator confirms that the GNSS baud run has stopped, finalized and
sealed, a later task may:

1. establish the exact integration base, including the finalized UART changes;
2. implement and qualify D9/GPOUT0 plus the diagnostic D6 monitor in the
   unchanged FLL profile;
3. perform D9 waveform qualification and the frequency-only output soak;
4. confirm or reject the provisional controller recommendation against the
   D9/FLL-output result without retuning it, then implement the confirmed
   delta, `GNSS_METADATA_HOLD`, FLL fallback, degraded states and isolated
   shadow in the existing Python/C++ parity path;
5. run focused changed-semantics tests, the affected exact firmware build and
   complete operational-path rehearsal; and
6. seek separate authority for one finite 72-hour integrated trial using the
   exact qualified D9 load.

The 72-hour trial must judge D14-relative frequency performance, unjoined phase
slope/excursion, recovery, holds/degraded residence, applications/path per hour,
natural reversals, shadow containment and delivered-output non-interference.
It is operating evidence for the confirmed law, not a repeat qualification of
unchanged FLL/PLL plumbing.

## Completion report

Return a concise decision-bearing report containing:

- exact source ledger and exclusions;
- derived-view schema and artifact identities;
- data completeness and comparability matrix;
- phase, ADEV/HDEV, response, environment, frequency and actuator results;
- exact replay and candidate divergence ledger;
- provisional recommended/retained policy decision with frozen-gate results
  and the pending D9 confirmation boundary;
- operational state machine and concrete host/firmware changes;
- historical limitations and newly discovered analyzer defects;
- tests run and source-immutability proof; and
- the exact stop boundary and next authorized firmware/bench gate.

State observed facts, derived results, counterfactual models and hypotheses
separately. Do not strengthen an empirical D8-relative-to-D14 result into UTC
traceability, oscillator-only stability, calibrated accuracy, thermal causality
or a qualified delivered-output claim.
