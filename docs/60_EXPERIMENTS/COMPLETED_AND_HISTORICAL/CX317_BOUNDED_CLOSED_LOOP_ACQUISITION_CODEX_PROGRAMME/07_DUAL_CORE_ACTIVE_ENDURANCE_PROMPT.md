# Stage 7 Prompt: Dual-Core Active Confirmation and Endurance

Execute Stage 7 only after the dual-core preview/isolation gate passes and the
post-Campaign-B policy replays exactly on the dual-core implementation.

## Goal

Confirm active transaction behavior across the new core boundary, then proceed
directly to a bounded 24-hour frequency-control endurance run if the
confirmation remains healthy.

## Frozen authoritative deadband and shadow refinement

Retain the exact post-Campaign-B V2 evidence deadband of
`abs(frequency_error_hz) <= 0.006249995628992717` for every authoritative
decision in Parts A and B. Do not change it during Part A, between Parts A and
B, or during Part B. Evidence that contradicts its safety or applicability
stops Stage 7 instead of triggering an opportunistic threshold change.

Before Part A, freeze a versioned, non-actionable shadow-analysis contract
with the following candidates and rules:

| Shadow ID | Entry rule | Release rule | Persistence rule |
| --- | --- | --- | --- |
| `S0` | `abs(error_hz) > 0.006249995628992717` | not applicable (symmetric comparator) | one qualified fresh 600 s estimate |
| `S1` | `abs(error_hz) > 0.005000000000000000` | not applicable (symmetric comparator) | one qualified fresh 600 s estimate |
| `S2` | `abs(error_hz) > 0.003333331743876140` | not applicable (symmetric comparator) | one qualified fresh 600 s estimate |
| `H1` | enter when `abs(error_hz) > 0.005000000000000000` | return to hold only when `abs(error_hz) <= 0.006249995628992717` | two consecutive qualified fresh 600 s estimates of the same non-zero sign for entry; one qualifying release estimate |
| `H2` | enter when `abs(error_hz) > 0.003333331743876140` | return to hold only when `abs(error_hz) <= 0.006249995628992717` | two consecutive qualified fresh 600 s estimates of the same non-zero sign for entry; one qualifying release estimate |

`S0` is the exact authoritative comparator run as a replay control. `S1`,
`S2`, `H1` and `H2` are frozen analytic candidates only. The `S2`/`H2`
threshold is the empirical finite-run detection floor, not calibrated
resolution and not a recommended active threshold.

For every candidate, freeze:

- the exact counterfactual state, rounding, cadence, clamp, dither and
  cumulative-budget rules;
- acceptance metrics and a rule for handling temporally correlated estimates.

The counterfactual controller must use the V2 I-only gain, signed rounding,
21-code per-decision clamp, `0xA800..0xAB00` range, 1,800 s minimum cadence,
900 s post-write exclusion, 600 s fresh-support requirement, and the same
one-request, budget and fail-static rules as the authoritative controller.
For candidates that are in a virtual post-write exclusion, record the pending
decision but do not manufacture a fresh measurement or advance virtual state
until the required support would exist. Counterfactual writes are analytical
events only and must never alter the live DAC epoch, estimator history, budget
or controller state.

Run every candidate against the same authoritative 600 s estimates in Parts A
and B. Shadow results must never become actionable, consume an authorization,
change live controller or response-classifier state, alter a budget or cause a
DAC write. Preserve the source-observation references and exact counterfactual
decision for replay.

## Finite test matrix and terminal semantics

No Stage 7 test may wait indefinitely for a deadband crossing, qualification,
response or clear state. The following clocks and outcomes are frozen before
the next hardware run:

| Test | Intention | Nominal duration | Absolute bound | Success | Bounded non-pass outcome |
|---|---|---:|---:|---|---|
| Part A1: fixed-code stability (complete; do not repeat) | Establish natural fixed-code in-deadband stability at retained A82A while continuously exercising dual-core timing, GNSS, queue and shadow paths | sealed actual duration: 43 consecutive qualified 600 s observations, 7 h 10 min | completed at the first eligible boundary after the missing finite endpoint was identified | all 43 observations qualified and inside V2 deadband, zero automatic applications/movement, exact estimator/controller/shadow replay, no pre-stop health or transport fault | preserve as diagnostic evidence for the separate transaction gate; never erase its stability success merely because no actuator transaction occurred |
| Part A2: A800 supplemental active confirmation | Exercise at least one complete live Core 1 request, Core 0 acceptance/application and Core 1 response using a previously characterized safe acquisition initial condition; do not repeat A1 | normally 1.5--2.5 h including warmup | 90 min to qualify, then 4 h qualified; no more than 5.5 h total | 1--4 exact four-phase responses, 60 one-second service queries, a later healthy eligible decision, `DISARMED/evidence_clear`, clean replay and no limit violation | fail-static abort, seal diagnostic evidence and do not enter Part B |
| Part B: endurance | Demonstrate bounded closed-loop service for exactly 24 h after qualification, including fixed-code no-write occupancy | about 24 h 40 min including normal warmup | 90 min to qualify; 24 h qualified plus at most 1 h only to finish an already-outstanding transaction and reach clear state; no more than 26.5 h total | exact 24 h qualified duration, all four scheduled service bursts, every transaction exact, terminal clear, clean health/replay and all budgets respected; zero corrections is a valid pass when every decision stays inside deadband | fail-static abort at qualification or clearance deadline, seal diagnostic evidence and stop hardware progression |
| Frozen shadow replay | Compare predeclared candidate deadbands/hysteresis against the exact live estimates with zero authority | concurrent with Parts A and B | ends with its associated live part | every authoritative observation preserved and every candidate decision replays exactly with zero command/authorization authority | fail Stage 7 analysis; never change the live threshold or extend a run |

The optional host `--duration-s` remains an additional, possibly shorter
emergency ceiling. It can never extend the frozen internal deadlines. A
timeout is diagnostic evidence, never a healthy stop and never permission to
advance.

## Part A: combined stability and active cross-core confirmation

Part A is a composite gate. Preserve the completed A82A run
`part_a_20260804T222508Z` as Part A1 fixed-code stability evidence and do not
repeat its long residency interval. Its overall single-run analyzer correctly
does not claim the separate active transaction gate, but the Stage 7 report
must record the independently proved A1 stability criterion as passed.

Run only the supplemental Part A2 transaction criterion below.

Create one unique run and arm a maximum of four automatic corrections:

- use exact code `0xA800` as the declared acquisition stimulus and record its
  one-shot manual acknowledgement exactly at entry; this code is inside the
  frozen hard range, was directly exercised in Campaign B and has the sealed
  connected-voltage screen, so it is a bounded initial condition rather than
  an opportunistic controller write;
- maximum individual correction no greater than the frozen post-Campaign-B
  value and never greater than 21 codes;
- maximum total absolute movement 84 codes;
- cadence no faster than the frozen post-Campaign-B value and never faster
  than its measured settling/fresh-support requirement;
- hard range `0xA800..0xAB00`;
- all GNSS, capture, estimator, model, response, queue, actuator and abort
  gates active.

Qualification must occur within 90 minutes of supervisor start. After
qualification, the complete Part A exit gate must occur within four hours.
Zero live transactions cannot pass Part A2; the already sealed Part A1 run
separately supplies the fixed-code stability result. Do not force later
reversals or writes after the declared A800 initial condition.

Include a bounded Core 0 service-load interval between eligible decisions.
Confirm the exact request crosses Core 1 to Core 0 and the exact applied
acknowledgement returns before control state advances.

Use Part A to confirm that the shadow contract consumes the exact qualified
estimator evidence emitted by Core 1 and agrees with exact host replay. The
maximum four corrections are confirmation evidence, not sufficient support to
select or adopt a refined deadband.

Analyze and seal immediately. If healthy, combine Part A1 and A2 without
rerunning A1, then continue to Part B without per-step operator approvals.

## Part B: 24-hour bounded frequency-control endurance

Use a new run identity and exact preserved artifact.

Limits:

- duration: 24 hours after warmup/qualification;
- qualification deadline: 90 minutes after supervisor start;
- after the exact 24-hour boundary, inhibit all new arming and allow at most
  one hour only for an already-outstanding transaction to finish and for the
  device to return to `DISARMED/evidence_clear`; otherwise abort fail-static;
- maximum automatic applied corrections: 32;
- maximum individual correction: frozen policy, never above 21 codes;
- maximum sum of absolute automatic movement: 672 codes;
- hard range `0xA800..0xAB00`;
- no correction faster than the frozen validated cadence;
- no automatic restoration or reboot recovery;
- one outstanding request maximum;
- every decision remains fully replayable.

Inside the evidence deadband, continue observing but do not write. Add a
pre-frozen dither/limit-cycle rule that stops repeated alternating corrections
or excessive path length even when net movement is small.

A Part B run that remains inside deadband for all 24 qualified hours may pass
with zero corrections: Part A supplies the required live transaction proof,
while Part B then proves stable no-write endurance, service-load tolerance,
health and exact replay. Lack of a Part B crossing must not extend its clock.

### Part B deadband-refinement evidence plan

Keep V2's `abs(error_hz) <= 0.006249995628992717` comparator authoritative
for the complete run. No observation, shadow event, counterfactual result or
operator interpretation may narrow it, arm a write, alter the integrator reset
rule or change any live policy parameter during Part B.

For every qualified estimate, log the authoritative decision and each shadow
candidate's virtual state and decision: residual and sign; qualified-estimate
sequence number; entry/release state; persistence state; virtual integrator;
unclamped and clamped virtual step; virtual applied code and epoch; virtual
cadence/settling/fresh-support eligibility; and every reason a virtual write
would be withheld. Preserve the exact source observation identifiers used by
all five evaluations.

At analysis time, partition results into fixed-code, settled-post-write and
aggregate series. For each candidate calculate paired differences from `S0`
in median absolute error, RMS error, inside-band occupancy and continuous
residence, plus its correction count, total absolute code path, reversals,
alternating-correction runs, boundary crossings, virtual dither holds and
clamp approaches. Report lag-1 through lag-6 autocorrelation, an explicitly
chosen Newey--West/HAC configuration, and effective sample size. Do not use an
ordinary independent-sample SEM.

The active 24-hour run remains the only source of observed closed-loop error
and actuator results. The shadow replay may establish plausibility and
counterfactual actuator cost; it cannot establish the closed-loop benefit of a
candidate that did not write hardware.

Preserve every qualified 600 s estimate during no-write occupancy, including
the applied code, time since the last DAC epoch, deadband state, preceding
correction direction, GNSS qualification, service-load state and available
environment context. Use these records to characterize fixed-code residuals,
boundary crossings, residence time, drift and repeatability. Treat successive
estimates as a time series rather than assuming they are independent samples.

Use naturally occurring same-code revisits and corrections in both directions
to assess repeatability and hysteresis. Do not force extra reversals or writes
solely to improve deadband characterization, and report hysteresis as
unresolved if the run does not provide adequate direction-paired evidence.

Exercise bounded normal service activity during the run: GNSS parsing,
environment sensing, telemetry output and declared USB load. Do not inject a
destructive physical reference or power fault into an active endurance run.
Use deterministic/simulated fault evidence for destructive cases and rely on
natural live faults to stop fail-static.

## Monitoring

Monitor each authority transition and transaction, plus periodic health. No
blind sleep and no hourly manual approval. A healthy campaign continues.

On fault, preserve the last confirmed code, revoke authority, seal diagnostic
evidence, and stop the programme's hardware progression.

## Analysis

Report:

- acquisition, authoritative V2 deadband occupancy, entry/release crossings
  and continuous residence times;
- applied correction count, direction, magnitude and path length;
- fixed-code and aggregate residual frequency-error distributions, temporal
  dependence and drift;
- naturally observed same-code repeatability and direction-paired hysteresis;
- for every pre-frozen shadow candidate, counterfactual entry/release events,
  persistence decisions, corrections, convergence, deadband occupancy,
  continuous residence, alternating corrections, reversals, path length,
  dither holds, clamp approaches and every withheld virtual write;
- paired `S1`/`S2`/`H1`/`H2` versus `S0` error and actuator-cost comparison,
  including the selected HAC/Newey--West interval, autocorrelation and
  effective sample size;
- candidate sensitivity to GNSS availability, service load, elapsed time and
  available environment context without unsupported causal claims;
- response and settling consistency with Campaigns A/B;
- GNSS qualification availability and outages;
- Core 0/Core 1 queue depth, high-water, loss and latency;
- actuator request/ack/application latency and failures;
- service-load effects;
- any dither, saturation, clamp approach or recovery event;
- exact host replay of every decision.

Do not promote this to calibrated accuracy, UTC traceability, phase lock or
holdover evidence.

## Post-run deadband decision

Only after Part B is complete and its authoritative and shadow evidence is
sealed may the analysis recommend a refined deadband. A smaller symmetric
deadband or hysteretic entry/release rule is justified only if it:

1. remains distinguishable from the 600 s estimator's empirical detection
   floor, quantization and fixed-code residual behavior;
2. improves paired median absolute error by at least one estimator count
   (`0.001666666666666667 Hz`) relative to `S0`, and its paired HAC 95%
   interval excludes zero in the favourable direction;
3. does not materially increase counterfactual corrections, total path
   length, reversals, alternating corrections, boundary churn, dither holds
   or clamp approaches; the report must state the pre-frozen practical
   materiality limits and each observed difference;
4. passes counterfactual replay of Campaigns A/B and Stage 7, including all
   safety, transaction and fault cases, with every changed decision explained;
5. records its finite-run uncertainty, temporal-support limitations and any
   unresolved directional hysteresis.

Do not narrow below the frozen empirical detection floor without separately
versioned estimator evidence that justifies the change. Any adopted refinement
is a new V3 control/response policy and exact artifact. It has no retrospective
authority over Stage 7 and requires a separate active validation run before it
can replace V2. A Stage 7B result may recommend only a later active validation
candidate; it must not automatically adopt a candidate.

## Deliverables and exit gate

Deliver sealed confirmation and endurance evidence, the frozen shadow contract
and exact candidate replay, updated plant/control profiles where justified,
full verification, and a Stage 7 report. Clearly distinguish a V3 candidate or
recommendation from the authoritative V2 policy used to pass Stage 7.

Pass if Part A1's fixed-code stability criterion is sealed, Part A2 performs
every cross-core transaction exactly, the 24-hour Part B run completes within
its finite clearance bound without unexplained fault or capture degradation,
the loop remains bounded and non-oscillatory, and every decision replays.
