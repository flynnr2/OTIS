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
containing:

- a finite list of candidate symmetric deadbands;
- candidate hysteretic entry/release threshold pairs where justified;
- the consecutive fresh-estimate requirements for entry and release;
- the exact counterfactual state, rounding, cadence, clamp, dither and
  cumulative-budget rules;
- acceptance metrics and a rule for handling temporally correlated estimates.

Run every candidate against the same authoritative 600 s estimates in Parts A
and B. Shadow results must never become actionable, consume an authorization,
change live controller or response-classifier state, alter a budget or cause a
DAC write. Preserve the source-observation references and exact counterfactual
decision for replay.

## Part A: active cross-core confirmation

Create one unique run and arm a maximum of four automatic corrections:

- start from the last confirmed safe applied code, recorded exactly at entry;
- maximum individual correction no greater than the frozen post-Campaign-B
  value and never greater than 21 codes;
- maximum total absolute movement 84 codes;
- cadence no faster than the frozen post-Campaign-B value and never faster
  than its measured settling/fresh-support requirement;
- hard range `0xA800..0xAB00`;
- all GNSS, capture, estimator, model, response, queue, actuator and abort
  gates active.

Include a bounded Core 0 service-load interval between eligible decisions.
Confirm the exact request crosses Core 1 to Core 0 and the exact applied
acknowledgement returns before control state advances.

Use Part A to confirm that the shadow contract consumes the exact qualified
estimator evidence emitted by Core 1 and agrees with exact host replay. The
maximum four corrections are confirmation evidence, not sufficient support to
select or adopt a refined deadband.

Analyze and seal immediately. If healthy, continue to Part B without requiring
a separate long observe-only run or per-step operator approvals.

## Part B: 24-hour bounded frequency-control endurance

Use a new run identity and exact preserved artifact.

Limits:

- duration: 24 hours after warmup/qualification;
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
  corrections, convergence, deadband occupancy, alternating corrections and
  path length;
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
2. does not create unjustified extra writes, alternating corrections, path
   length or boundary churn;
3. passes counterfactual replay of Campaigns A/B and Stage 7, including all
   safety, transaction and fault cases, with every changed decision explained;
4. records its finite-run uncertainty, temporal-support limitations and any
   unresolved directional hysteresis.

Do not narrow below the frozen empirical detection floor without separately
versioned estimator evidence that justifies the change. Any adopted refinement
is a new V3 control/response policy and exact artifact. It has no retrospective
authority over Stage 7 and requires a separate active validation run before it
can replace V2.

## Deliverables and exit gate

Deliver sealed confirmation and endurance evidence, the frozen shadow contract
and exact candidate replay, updated plant/control profiles where justified,
full verification, and a Stage 7 report. Clearly distinguish a V3 candidate or
recommendation from the authoritative V2 policy used to pass Stage 7.

Pass if the cross-core controller performs every transaction exactly, the
24-hour run completes without unexplained fault or capture degradation, the
loop remains bounded and non-oscillatory, and every decision replays.
