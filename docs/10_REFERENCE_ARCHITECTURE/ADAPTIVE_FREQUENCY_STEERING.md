# Adaptive FLL/PLL Steering Architecture Decision

**Status:** selected architecture; existing FLL qualification and positive
coherent FLL/PLL physical-control evidence is retained and reused. The remaining
work is a minimal operational-policy delta, not a new estimator, controller,
transaction path, platform, or general characterization programme. No firmware
profile, campaign bundle, physical authority, frequency-control arm, phase
actuation, automatic retry, or restoration authority is created by this
document.

**Effective date:** 2026-08-26

## Decision

OTIS will use one coherent adaptive FLL/PLL steering architecture for the CX317
VCOCXO. Bounded reactive frequency steering is its dependable baseline. A
slower phase term may request a bounded temporary frequency bias through the
same policy and actuator transaction path. OTIS will not make either term
depend on the existence of one durable equilibrium DAC code or on a prediction
of future oscillator drift.

The default implementation basis is the existing CX320/CX322 coherent law,
selected relative-phase estimator, active-hybrid firmware engine, host replay,
transaction path, and operational tooling. This decision does not authorize a
greenfield replacement. Change an inherited semantic only when retained replay
shows that it is the specific obstacle to sustained useful operation.

The controlled objective is the D8 oscillator's measured frequency error
relative to D14 PPS over declared observation windows. The AD5693R code is an
evolving control state. A changing code is expected when the discipline process
rejects oscillator drift; a stationary code is neither the objective nor proof
of a correct output.

The next policy refinement retains the already demonstrated slow, bounded
sampled-data FLL/integral servo class:

1. retain exact D14-qualified D8 count observations in their canonical domains;
2. form a current frequency-error observation from a prospectively frozen set
   of accepted windows;
3. distinguish an interval containing zero from persistent same-sign evidence;
4. translate current observed error into fractional code demand using the
   retained positive plant-gain envelope;
5. carry unapplied fractional demand as a provenance-bearing correction-debt
   state;
6. issue an integer-code request only when persistence, debt, cadence, range,
   movement, freshness, acknowledgement, and diagnostic gates permit it;
7. exclude the frozen settling interval after an applied write, observe the
   actual response, and repeat.

The concrete aggregation, persistence, correction fraction, debt rule, maximum
step, cadence, and terminal limits are not selected here. They must be frozen
before replay and may not be moved after seeing evaluation results.

## Evidence supporting the decision

This decision synthesizes retained physical evidence without weakening any
historical campaign criterion:

- the selected local plant slope is positive, nominally
  `0.00017008467693813145 Hz/code`, with six drift-cancelled retained values
  spanning `0.00016357422282453626..0.00017334010044578463 Hz/code`;
- the rapid interleaved survey remained monotonic with fitted
  `0.0001699582 Hz/code` and `R2=0.9970`;
- a 900-second settling exclusion followed by the selected 600-second estimator
  produced within-dwell spread below the retained empirical detection floor;
- the lower-side frequency-only qualification applied `+21` codes and observed
  the expected `+0.003333332 Hz` response before two-estimate tight entry;
- sustained-hybrid Attempt 4 completed eleven automatic transactions over
  40,537 qualified seconds before its frozen low-efficiency terminal;
- CX322 completed a sealed 12-hour physical acquisition with exact replay of 66
  hybrid decisions and four phase-material transactions. The matched absolute
  relative-phase slope fell from `0.001937057182` to `0.000939358315 cycles/s`
  (a `0.515059068` improvement fraction), while its prospective frequency RMS
  and tight-occupancy limits passed;
- retained interior history effects are approximately `2.4500` and `7.3493`
  equivalent codes, and the post-warmup drift evidence corresponds to roughly
  a few equivalent codes per hour; and
- targeted-characterization Attempt 6 completed twelve predetermined dwells and
  36 supports with clean evidence. Lower, centre, and upper observations
  repeated their frequency classes and bracketed zero, while all three frozen
  durable-equilibrium models had empty complete sets at minimum, nominal, and
  maximum gain.

The positive conclusion is controllability by slow feedback. The negative
conclusion is limited to the frozen durable-equilibrium representations. A
model's inability to explain canonical observations is evidence against that
model; it is not evidence that the observations or physical plant failed.

## Existing qualification and positive control evidence are reused

This decision does **not** reopen or require repetition of the established FLL
or coherent FLL/PLL integration evidence:

- CX317's sealed 24-hour bounded frequency-control run qualified the FLL
  measurement, decision, transaction, acknowledgement, re-arm, and service
  path. It completed 150 consecutive in-band observations after its automatic
  correction;
- the lower-side frequency-control result applied `+21` codes and observed the
  expected `+0.003333332 Hz` response;
- CX320 physically applied a genuine combined request and established the
  expected near-resolution response limitation;
- CX322 then supplied the stronger positive result: four combined requests all
  changed by the phase term, the last two were wholly phase-driven, the matched
  phase ramp was approximately halved, and frequency performance remained
  within its frozen comparison limits; and
- sustained-hybrid Attempt 4 completed eleven automatic transactions over
  40,537 qualified seconds and included a natural reversal.

Those results retain their exact historical identities, envelopes, criteria,
and limitations. The sustained-hybrid fixed controller's low-efficiency result
and the durable-equilibrium model rejection are evidence against those specific
policies and models. They do not invalidate the already exercised FLL, combined
FLL/PLL, measurement, command, acknowledgement, or actuator boundaries.

No FLL or FLL/PLL architecture or plumbing requalification is required merely
because this decision changes how the evidence is interpreted or because a new
policy reuses those unchanged boundaries. Repeat only the shortest affected
gate when a material change alters a decision-relevant measurement, command,
actuation, authority, or safety semantic. New correction-debt, fallback, or
estimator-containment semantics require focused deterministic replay and
integration checks. A further physical run would exercise ordinary operation
or validate only a materially changed command law or new performance claim
that retained evidence cannot establish; it would not requalify the unchanged
FLL/PLL architecture.

## Reuse ledger

The successor must compose these retained capabilities rather than recreate
them:

| Layer | Retained result or implementation | Reuse boundary |
|---|---|---|
| D14/D8 measurement | PPS-gated cumulative-snapshot backend, count-observation contract, and selected non-overlapping 600-second estimator | Reuse exact raw/derived semantics, continuity rules, time domain, and estimator identity. |
| Relative phase | Exact integer D8-cycle accumulator relative to D14 within an unjoined phase epoch, selected profile, host implementation, firmware implementation, and parity fixtures | Reuse unchanged; it is relative phase, not UTC or calibrated absolute phase. |
| Reactive FLL | Sealed CX317 bounded I-only control and endurance result | Reuse the observed-error correction law, range, cadence, settling, acknowledgement, and fail-static transaction boundaries. |
| Coherent FLL/PLL | CX320 policy/engine and the positive CX322 12-hour result | Start with the existing combined frequency-plus-bounded-phase-bias law. The open question is sustained operating authority and maintenance behavior after the experimental four-application budget. |
| Plant and range | Positive local gain envelope, rapid monotonic survey, CX319 range-spanning map, settling evidence, hysteresis/repeatability observations, and Attempt 6 repeated lower/centre/upper supports | Use these as conservative bounds and replay inputs; do not turn them back into a permanent equilibrium-code model. |
| Response interpretation | Frozen response classifier plus CX320/CX322 near-resolution evidence | Keep small healthy responses nonterminal and use cumulative/longer evidence where an individual correction is below the 600-second detection floor. |
| Actuator transaction | Exact request, acceptance, application, DAC-epoch, first-dependent-observation, response, and acknowledgement path across the two cores and host | Reuse unchanged unless a concrete interface defect is found. |
| Replay and telemetry | Existing `AHY`, `ACT`, estimate, phase, response, supervisor, analyzer, sealing, and registration records and tools | Extend the existing schemas only for a decision-bearing missing field; do not create a parallel runner or evidence format. |
| GNSS recovery | Attempt 6's retained D14/D8-support behavior across transient serial-metadata dequalification | A metadata lapse may temporarily hold a new decision but must not erase valid D14/D8 evidence or fail the acquisition. |
| D10 external events | D10 is unclaimed by current PPS-gated steering profiles; explicit external-event/loopback profiles already emit `EVT` records | D10 absence, noise, malformed edges, or D10-local overflow can degrade only D10 evidence. D10 never gates D14/D8 steering or the run terminal. |
| Operational platform | Existing sole-owner capture, command/acknowledgement, bounded abort, rotation, analyzer, sealing, registration, preflight, and actual-process rehearsal machinery | Use this path. Rehearse only an operationally significant change; do not build another campaign framework. |

The incomplete CX318 programme does not confer authority and its failed campaign
ledger is not reused. Its estimator and preview work products are reusable
because later CX319/CX320/CX322 programmes independently bound, exercised, and
replayed those exact semantics.

## Baseline state and terminology

The baseline controller may retain only state needed to make current reactive
decisions, including:

- last confirmed applied code and DAC epoch;
- exact source/evidence frontier of the current observation;
- current frequency-error interval in the D14-qualified D8 measurement model;
- same-sign persistence and clean-window qualification;
- fractional correction debt and its code-domain provenance;
- last requested/applied delta and response identity;
- settling, cadence, range, movement, saturation, and anti-windup state; and
- explicit hold, inhibit, fallback, and requalification reasons.

This state is not a calibrated equilibrium code, a prediction of future drift,
or a claim about unobserved internal OCXO temperature. Nearby-air SHT41 data is
a labeled covariate only until a separate relationship to oscillator state is
physically established.

Use `frequency error`, `frequency syntonization`, `discipline`, `hold`, and
`holdover` with the meanings in `OTIS_REFERENCE_TERMINOLOGY.md`. Do not use a
stationary DAC code as the definition of `stable`, `locked`, or `accurate`.

## Reference and qualification behaviour

D14 remains the sole authoritative PPS/reference input and D8 remains the sole
authoritative oscillator/count input. GNSS serial metadata may qualify receiver
state but cannot replace D14 timing evidence. D10 is not a PPS witness and does
not participate in this control path.

A transient qualification loss may hold a new actuation decision while capture
and otherwise valid D14/D8 history continue. It must not reset or erase valid
non-actuating support merely because a later metadata snapshot is temporarily
behind. Requalification must be bounded and causal. Persistent reference,
identity, capture, ordering, actuator-state, or acknowledgement contradictions
retain their independently declared hold or fail-static consequences.

### GNSS serial-metadata hold

A checksum error, malformed sentence, freshness lapse, missing quality field,
or brief metadata dequalification is `GNSS_METADATA_HOLD`, not a measurement,
controller, or operating-run failure, provided D14/D8 evidence and the last
confirmed actuator state remain coherent. During this hold:

- D14/D8 capture, phase accumulation, telemetry, analysis, and evidence
  preservation continue;
- the last confirmed DAC code remains static and no new arm or correction is
  issued;
- valid pre-glitch canonical observations and causally supported estimator
  history are retained rather than reset;
- metadata requalification is recorded explicitly, and the next actuation
  decision must be based on a fresh causally sufficient post-requalification
  observation; and
- the operating run continues and reports hold duration and lost control
  opportunity rather than a failure terminal.

Transaction handling must be race-free. A request not yet accepted may be
explicitly withdrawn before entering hold. Once the actuator owner has accepted
a request, complete and record that one bounded transaction, then hold further
decisions; an acceptance is not safely undone by a later metadata snapshot. An
unknown application result, contradictory DAC epoch, or missing acknowledgement
remains an actuator-provenance fault. That fault is not caused or excused by the
metadata glitch.

Loss or contradiction of authoritative D14 timing is separately a reference
condition, not a GNSS serial-metadata glitch. A persistent receiver identity or
configuration contradiction may keep control held and require operator review,
but it still does not rewrite retained D14/D8 observations or invalidate the
physical acquisition.

The existing transaction layer supplies the nonterminal hold and
fresh-requalification path. The engineering long-run implementation separates
`GNSS_METADATA_HOLD` from authoritative-reference and actuator-provenance
faults in that existing path rather than creating another controller or
supervisor. It records whether a private request was withdrawn before release
or whether a released request completed under Core 0 ownership, retains the
exact applied-code/session/epoch frontier, and requires fresh same-receiver
metadata followed by a causally later exact D14/D8 observation before rearm.

The 2026-08-28 D9 programme closed its output gate as materially incomplete, so
the first implementation of these semantics was intentionally a permanently
non-effective reference oracle and native deterministic fixture. It binds
Core 1 private withdrawal, Core 0 ownership after durable release, acceptance
through application/DAC epoch/first consumer/response, absorbing actuator
provenance and low-efficiency states, phase-loss latching, and causal metadata
requalification. It does not itself alter the live CX322 firmware, schemas,
parser, supervisor, or authority profile. The exact historical contract is
[`cx322_non_effective_operational_semantics_contract_v1.json`](../60_EXPERIMENTS/OTIS_D9_OUTPUT_AND_ADAPTIVE_STEERING_INTEGRATION_PROGRAMME/cx322_non_effective_operational_semantics_contract_v1.json).

Later explicit operator instructions authorize distinct 24-hour frequency-only
and 72-hour unchanged-CX322 engineering runs with D9 forwarding and D6
diagnostics enabled. Their live profiles implement the applicable metadata-hold
transaction behavior directly while retaining the original request laws. They
keep new-actuation authority open until an exact 1,500-second endpoint reserve;
48/1,008 and 144/3,024 application/cumulative-code ceilings respectively are
cadence-derived safety bounds, not targets or completion conditions. D14 and D8
remain the only reference and oscillator/control truth; D9
configuration/readback is an output-leg entry and continuity gate, and D6
remains zero-authority. This later authority does not select or retroactively
promote the non-effective Prompt 03 oracle, revise the incomplete D9
waveform/load terminal, or establish a public delivered-output claim.

D10 is not claimed by the current PPS-gated steering profiles. If a future
operating profile enables D10 `EVT` capture, D10-local invalidity, noise, gaps,
or overflow must remain local to the external-event evidence plane. It cannot
enter D14/D8 validity, steering eligibility, or the operating-run terminal. If
D10 traffic can starve or corrupt D14/D8 capture, that is a platform-isolation
defect to repair, not a reason to make D10 a timing-health veto.

## Future-estimator containment invariant

An unpromoted Kalman, alpha-beta, drift, thermal, learned, or other future
estimator is an optional zero-authority consumer. It may produce additive
derived evidence, but it may not participate in canonical measurement validity,
baseline reactive-control eligibility, serial ownership, queue health, abort,
or physical campaign terminal decisions.

Its missing input, stale output, numerical failure, internal contradiction,
model mismatch, or bad prediction shall produce a local status such as
`shadow_unavailable`, `shadow_stale`, or `shadow_model_rejected`. The estimator
fails itself. It shall not:

- invalidate or rewrite canonical D14/D8 evidence;
- stop healthy capture or finalization;
- reset valid baseline estimator or correction-debt history;
- inhibit an otherwise eligible reactive decision;
- alter the baseline requested/applied DAC sequence;
- backpressure or starve timing, control, transport, or evidence queues; or
- reinterpret physical reality as failed because its model is infeasible.

Before promotion, enabling, disabling, stalling, killing, delaying, or
deliberately corrupting the estimator must leave canonical records, baseline
decisions, applied DAC transactions, and non-shadow terminal state identical.
Only additive shadow records and explicit shadow-drop counters may differ.

After a separately authorized promotion, a predictive estimator remains
subordinate to the independent command envelope. Incoherent or unavailable
output withdraws that estimator's authority and selects the prospectively
frozen reactive fallback or hold. It does not retroactively invalidate prior
measurements or successfully completed acquisition gates.

## Evidence retained for future estimator evaluation

Ordinary reactive operation must retain enough causal evidence to support or
reject a future estimator without a new general characterization campaign:

- canonical per-PPS D14 reference and D8 count observations, exact domains,
  sequences, continuity, resets, wraps, gaps, flags, and capture session;
- every accepted and rejected observation window and its reason;
- requested and applied code, acknowledgement, DAC epoch, application tick,
  transaction identity, and first dependent observation;
- pre-decision frequency-error interval, persistence, correction debt,
  thresholds, proposed delta, applied delta, and every limit/hold reason;
- the frozen settling boundary and all post-write response windows;
- observed response, finite-run transaction gain, overshoot, reversal, clamp,
  cumulative movement, and recovery state;
- time since boot, qualification, last write, and uninterrupted same-code
  residence;
- available environment and supply measurements as explicitly labeled
  covariates, including missing and stale states;
- GNSS identity/configuration/quality metadata as qualification evidence; and
- future shadow estimator identity, configuration, causal evidence frontier,
  state, prediction, residual/innovation, age, local status, and drop counters.

Raw evidence remains authoritative. A future estimator must be evaluated with
causal replay and a prospectively frozen identification/held-out split. It may
be promoted only if it materially improves declared output metrics over the
reactive baseline without unacceptable actuator cost. Candidate metrics include
accumulated absolute frequency error, declared-band occupancy, accumulated
phase error relative to D14, recovery time, DAC path length, reversals,
overshoot, wrong-sign responses, and residual behavior. Thresholds and any
probabilistic interpretation require a separate frozen contract.

## Coherent FLL/PLL and holdover boundary

The selected architecture retains one coherent FLL/PLL policy rather than two
independent loops competing for the DAC. Both bounded FLL steering and the
combined FLL/PLL integration path already have physical evidence and are not
being requalified here. The FLL term rejects currently observed frequency
error. The PLL term may request a small, bounded temporary frequency bias whose
accumulated area reduces a same-epoch D14-relative phase error. The policy
combines both contributions before one set of persistence, debt, cadence,
range, movement, acknowledgement, and safety gates.

The PLL term may not assume return to a permanent equilibrium code. Missing,
stale, rejected, or incoherent phase evidence removes only the PLL contribution;
it does not invalidate D14/D8 frequency evidence or inhibit an otherwise
eligible FLL correction. A materially changed phase-control rule requires its
own causal replay, limits, and promotion decision. Physical authority is needed
only to exercise that changed rule, not to requalify the unchanged FLL/PLL
measurement and transaction path.

Reference hold and holdover remain distinct from active FLL correction. Initial
holdover retains the last confirmed safe code. Predictive holdover is a future
estimator use case and inherits the containment and promotion requirements
above.

## Proportionate work for a changed policy

The next work must not be another open-ended equilibrium characterization or a
repeat qualification of unchanged FLL/PLL boundaries. Before promoting a
materially changed policy it must:

1. bind the existing selected estimator, relative-phase engine, combined
   controller, transaction path, replay, and operational tool identities;
2. freeze only the minimal policy delta needed to move from CX322's
   four-application experiment to bounded sustained use. Use the retained CX322
   post-budget `+8.279592074`-code reversal demand and Attempt 4 natural-reversal
   history to choose the finite movement/application/hold envelope;
3. compare explicit correction debt against the unchanged existing law in
   causal replay. Adopt it only if it improves declared frequency/phase and
   actuator-cost metrics; otherwise retain the existing law;
4. turn model rejection, low-efficiency detection, optional-estimator failure,
   transient GNSS metadata loss, and any D10-local problem into explicit local
   hold/degraded states while canonical acquisition continues. In particular,
   replace the current active-hybrid host terminal on
   `setup_gnss_eligible=false` with the transaction-aware
   `GNSS_METADATA_HOLD` above. Retain
   fail-static actuation for an authoritative D14/D8, applied-code,
   acknowledgement, identity, safety, or shared-capture contradiction;
5. implement the delta in the existing host and firmware parity engines and
   exercise only the changed semantics with deterministic retained-evidence and
   fault fixtures;
6. if firmware or operational semantics change, build the affected exact
   profile and rehearse the existing complete operational path; and
7. then use the instrument in a bounded operating run. Treat that run as
   operational performance evidence, not another FLL/PLL or platform
   qualification campaign.

No new physical characterization is justified unless replay identifies a
specific safety-, validity-, or decision-bearing parameter that retained
evidence cannot bound.
