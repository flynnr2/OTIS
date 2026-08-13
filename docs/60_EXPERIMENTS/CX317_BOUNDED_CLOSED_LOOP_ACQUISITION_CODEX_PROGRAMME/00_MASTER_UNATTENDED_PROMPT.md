# Master Prompt: CX317 Bounded Closed-Loop Acquisition Programme

> Historical topology note: this completed programme included a temporary
> same-PPS D10 witness experiment. Current OTIS topology forbids that use: D14
> alone is PPS authority, D8 is the oscillator input, and D10 is reserved for
> independent external-event measurement.

You are operating in the OTIS repository on the same computer as the connected
bench rig. Execute this programme in order and continue through every safe gate
without asking for routine confirmation.

This is an active-control programme. It follows a successfully completed
observe-only programme, but it grants only tightly bounded experimental
actuation. Treat every limit below as immutable during a live campaign.

## Accepted starting evidence

Treat the following as authoritative unless validation finds an identity or
integrity mismatch:

- the accepted count backend is
  `pio_wait_cumulative_snapshot_dma_v1`;
- the selected authoritative estimator is
  `PPS_CUMULATIVE_SNAPSHOT_SPAN_V1`, 600 s, non-overlapping;
- the 60 s overlapping estimator is diagnostic only;
- the same-backend Stage 5 model measured positive gain
  `0.000163574222824536..0.000173340100445785 Hz/code`;
- the characterized code range is `0xA800..0xAB00`;
- the retained fail-static starting code is `0xA950`;
- the proposed maximum individual correction is 21 codes;
- a DAC epoch invalidates old estimator history, followed by 900 s settling
  exclusion and 600 s fresh support;
- no automatic decision may occur more often than once per 1800 s during the
  initial active campaigns;
- Stage 6 previously demonstrated 22,200 continuous seconds of clean live
  observe-only operation, host/firmware parity, service-load tolerance, and
  zero unintended DAC commands;
- calibrated combined uncertainty, sub-resolution t95, connected-voltage
  calibration, D8 physical margin, and GNSS metadata qualification were not
  established.

For this programme, unavailable calibrated combined uncertainty blocks a
calibrated accuracy or traceability claim; it does not by itself block bounded
code-domain learning inside the already exercised range. The controller uses
the empirical detection floor, deadband, response envelope and live validity
gates. Likewise, unavailable sub-resolution t95 does not require another long
static campaign before first actuation: the initial 1800 s cadence carries the
passed 900 s exclusion plus 600 s fresh-support rule while Campaign A measures
the dynamic response directly.

Read first:

- `docs/60_EXPERIMENTS/CX317_PPS_GATED_ESTIMATOR_CONTROL_FINAL_READINESS.md`
- `docs/50_SOFTWARE/CX317_PPS_GATED_SELECTED_ESTIMATOR.md`
- `docs/50_SOFTWARE/PPS_CUMULATIVE_SNAPSHOT_SPAN_ESTIMATOR.md`
- `profiles/estimators/cx317_pps_gated_selected_v1.json`
- `profiles/plant_models/cx317_pps_gated_v2.json`
- `profiles/discipline/cx317_pps_gated_i_only_preview_v2.json`
- `profiles/discipline/cx317_response_classification_v2.json`
- `profiles/discipline/cx317_bounded_active_v2.json`
- `docs/90_ROADMAP/OTIS_SW2_REVISED_ROADMAP.md`
- every prompt in this programme folder.

## Programme philosophy

Maximize safe learning rate. Do not insert a long observe-only campaign between
stages merely because the next stage changes authority. Use deterministic
replay, bounded live preflights, and automatic continuation through healthy
steps.

Every active correction is simultaneously:

- one bounded control decision;
- one actuator transaction;
- one plant-response experiment;
- one immutable evidence capsule.

An indeterminate single small-step response near estimator resolution is not
automatically a fault. Wrong-sign response, growing error, broken identity,
loss of measurement integrity or a failed actuator transaction is a fault.
Measurement validity, code-domain model applicability and control eligibility
are separate decisions. Preserve and classify every valid response even when
the model is inapplicable. Model inapplicability enters fail-static
`OUT_OF_MODEL_HOLD`; it is not rewritten as a measurement fault.

SHT41 nearby-air temperature is a labelled telemetry covariate. The observed
range is not a demonstrated CX317 case/oven-temperature limit and is not an
actuation veto for this non-temperature-dependent plant model. Missing, stale
or out-of-context SHT41 data must be recorded honestly but does not invalidate
an otherwise healthy frequency observation, model or control decision.

Do not weaken a gate after live evidence begins. Preserve failed or stopped
runs as diagnostic evidence.

## Stages

1. clean baseline and immutable evidence handoff;
2. bounded GNSS-UART qualification and actuator/electrical preflight;
3. active-controller transaction path, replay, and source-level safety gates;
4. Campaign A: automatic acquisition from `0xA950`, up to 16 corrections;
5. Campaign B: acquisition from the other side of the crossing, initially
   `0xA800`, up to 8 corrections, followed by a model/policy update;
6. incremental dual-core timing/service partition;
7. dual-core active confirmation and one 24 h bounded endurance run;
8. final review and recommendation for the next product goal.

## Authority granted only when this master is explicitly executed

You may:

- inspect, modify, test and document repository code in programme scope;
- add receiver metadata, active-control, actuator-transaction, multicore,
  analysis and run-control contracts and tooling;
- compile and flash explicit programme firmware profiles;
- read the GPS UART and parse bounded receiver metadata;
- execute the predeclared connected-voltage DAC points in Stage 2;
- arm the dedicated active-control profile only after Stages 1 through 3 pass;
- execute Campaign A with at most 16 feedback-derived corrections;
- execute Campaign B with at most 8 feedback-derived corrections;
- execute the post-migration confirmation and endurance limits declared in
  Stage 7;
- continue automatically from the first healthy correction to later healthy
  corrections without operator approval between steps;
- stop fail-static at the last confirmed applied code;
- repair narrow defects, rebuild, run a new smoke capture, and restart only in
  a new run directory;
- create local commits when the worktree is suitable, but do not push or open a
  pull request without a separate request.

## Immutable active-control envelope

Until a later stage explicitly freezes a narrower value:

| Parameter | Limit |
|---|---:|
| DAC hard range | `0xA800..0xAB00` |
| maximum correction per decision | 21 codes absolute |
| Campaign A starting code | `0xA950` |
| Campaign A maximum automatic corrections | 16 |
| Campaign A maximum cumulative movement from start | 336 codes absolute |
| Campaign B predetermined starting code | `0xA800` |
| Campaign B maximum automatic corrections | 8 |
| Campaign B maximum cumulative automatic movement from start | 168 codes absolute |
| initial minimum time between applied corrections | 1800 s |
| post-write exclusion | at least 900 s |
| fresh authoritative support after exclusion | at least 600 s |
| active controller | incremental I-only frequency control |

Stage 7 may use a revised cadence or step only if Stages 4 and 5 produce an
evidence-backed policy, deterministic replay passes, and the revised value is
no more aggressive than the validated response permits. It may never widen the
hard DAC range without a new programme.

## Authority fields and arming

Active authority must be explicit and short-lived:

- the default and preview profiles remain non-actuating;
- only a dedicated programme profile may set `actuation_enabled=true`;
- `actuation_authorized=true` is permitted only after exact run/build/profile,
  GNSS, estimator, code-domain plant-model, applied-code, capture-owner and
  abort gates pass;
- `actionable=true` may exist only for the one decision being transacted;
- authority clears immediately after the request is accepted or on any fault;
- a new correction requires a new full eligibility decision;
- reboot, reconnect, session discontinuity or stale metadata clears arming.

No serial command may directly set `actionable=true` or supply an arbitrary
feedback-derived DAC code.

## Universal active stop conditions

Stop further DAC writes immediately and retain the last confirmed applied code
if any of these occurs:

- operator abort, lost abort path, lost capture owner or unexpected reconnect;
- firmware reset, boot identity mismatch, configuration/profile/hash mismatch
  or session discontinuity;
- GNSS metadata invalid, stale, checksum-invalid, fix-invalid or inconsistent
  with the declared receiver policy;
- missing, duplicate, short, long or discontinuous PPS used by the estimator;
- any current use of D10 as PPS witness, authority, health veto, or control
  input;
- snapshot sequence gap, association loss, zero/saturated count, FIFO/DMA/ring
  fault, parser loss or transport discontinuity;
- estimator invalidity or loss of required fresh estimator support;
- code outside the hard electrical range or any attempt to extrapolate a write
  outside it;
- DAC request/accepted/applied mismatch, stale request, I2C failure, missing
  acknowledgement or application timeout;
- correction magnitude, cumulative budget, correction count or cadence limit
  exceeded;
- response with confidently wrong sign, response outside the pre-frozen broad
  model/noise envelope, or error growth satisfying the pre-frozen stop rule;
- an unexpected actuator write, duplicate write, or non-programme command;
- a non-droppable cross-core queue fault after the dual-core migration.

On a fault:

- do not automatically command `0xA950` or any other restoration code;
- do not continue after merely clearing a warning;
- emit and preserve the stopping reason and complete step capsule;
- close and seal the run as stopped/diagnostic when possible;
- require explicit recovery in a new run or a stage-defined recovery leg.

If measurement evidence is valid but the code-domain plant model is
inapplicable, do not label the measurement as faulty. Preserve its numerical
response classification, clear actionability and integrator state, retain the
last confirmed applied code, continue telemetry in `OUT_OF_MODEL_HOLD`, and
require an applicable model plus fresh contiguous estimator support before a
new correction. An out-of-context SHT41 value alone cannot enter this hold.

## Response classification

Before Campaign A, freeze a versioned response-classification policy derived
from replay, count quantization, the empirical detection floor, measured gain,
fixed-code noise and the 60 s diagnostic trajectory.

It must distinguish:

- `healthy_detected`;
- `healthy_indeterminate_near_resolution`;
- `inside_deadband`;
- `limit_reached`;
- `wrong_sign`;
- `excess_response`;
- `growing_error`;
- `measurement_or_actuator_fault`.

The first indeterminate result may continue if all safety evidence is healthy.
Repeated indeterminate results must be assessed cumulatively. Thresholds may
not be changed during a live campaign.

## GNSS boundary

GPS TX to Nano RX is a required read-only evidence input before active control.
Parse at least RMC and GGA equivalents with checksum, validity, fix quality,
UTC/date availability, satellite count, metadata age and identity epoch.

The UART does not timestamp PPS and must not replace the raw hardware `REF`.
Receiver metadata qualifies whether a PPS may influence control.

Nano TX to GPS RX remains silent during initial active campaigns. Do not send
receiver configuration commands merely for convenience. Stage 8 may recommend
a separately versioned provisioning profile, but this programme does not need
to transmit to the GPS to succeed.

## Dual-core boundary

Do not place the multicore migration before the first active learning. After
Campaigns A and B establish the controller/plant transaction, implement:

- Core 0: USB, host commands, bounded GNSS parsing, environment service,
  telemetry formatting, and physical I2C actuator execution;
- Core 1: PIO/DMA completion service, raw observation construction, sequence
  ownership, estimator, control state, actuator-request generation and
  timing-critical fault detection.

Core 1 sends immutable actuator requests. Core 0 returns immutable accepted and
applied acknowledgements. Core 1 must never assume a request was applied.
Core 0 must serialize the existing shared I2C bus explicitly; environment
polling may be delayed or dropped, while an actuator transaction is bounded,
uniquely acknowledged and never duplicated.

Stall and overload Core 0—not Core 1—during isolation testing. Core 1 must
continue timing work or enter a defined fail-static state without inventing an
actuation.

## Durable state

Before changing firmware or touching the rig:

1. require a clean `main` checkout aligned with `origin/main` and no other
   linked worktree;
2. create `runs/cx317_bounded_closed_loop_acquisition/<UTC campaign id>/`;
3. copy `PROGRAMME_STATE_TEMPLATE.md` to `PROGRAMME_STATE.md`;
4. record repository state, exact board/serial identity, firmware hashes,
   model/estimator/policy identities, receiver wiring and last applied code;
5. update state atomically on every stage transition, build, flash, arm,
   authority change, DAC request/ack/application, abort, fault, capture start,
   capture stop and evidence seal.

Never repeat a sealed successful stage because conversational context was lost.
Trust the ledger and immutable evidence.

## Defect policy

Classify defects as receiver metadata, reference capture, oscillator count,
estimator, control policy, actuator transaction, I2C/plant, service plane,
cross-core transport, host capture, evidence tooling, or test infrastructure.

Preserve the failing evidence, reproduce the narrowest case, repair the
smallest surface, run focused and full verification, build a new identified
artifact, smoke it without actuation, and restart active work only in a new run
directory. Do not weaken safety thresholds to turn a failure into a pass.

## Completion

The programme completes only after Stage 8 reports one of:

- `blocked_before_active_control`;
- `bounded_control_needs_revision`;
- `bounded_frequency_acquisition_passed`;
- `dual_core_frequency_control_endurance_passed`.

Even the final outcome does not authorize phase steering, predictive holdover,
adaptive control, UTC/time-of-day claims, a wider DAC range, or permanent
unbounded operation.
