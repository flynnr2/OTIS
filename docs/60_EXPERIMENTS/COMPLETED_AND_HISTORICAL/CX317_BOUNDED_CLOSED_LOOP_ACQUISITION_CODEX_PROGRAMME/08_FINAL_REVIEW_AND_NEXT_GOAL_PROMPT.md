# Stage 8 Prompt: Final Review and Next Goal

Execute Stage 8 after the last completed hardware stage. This stage is review,
verification and documentation only. Do not move the DAC.

## Goal

Decide what OTIS has actually demonstrated and select the fastest defensible
next product goal.

## Audit

Audit:

- clean source/build/run identities and immutable seals;
- GNSS receiver metadata and PPS eligibility behavior;
- both single-core acquisition campaigns;
- response classification, gain, settling and bidirectional convergence;
- every request/accepted/applied transaction;
- correction, cumulative, cadence and range budgets;
- abort and fail-static behavior;
- dual-core ownership, queues, isolation and load tests;
- active confirmation and endurance evidence;
- host/firmware replay parity;
- all stopped, indeterminate and anomalous steps;
- current physical and metrological limitations;
- final full tests, firmware matrix and no-hardware validation.

Do not use clean software tests to overrule failed bench evidence. Do not use
successful code-domain control to claim calibrated frequency, UTC, phase lock
or holdover.

## Required decision

Choose exactly one:

- `blocked_before_active_control`;
- `bounded_control_needs_revision`;
- `bounded_frequency_acquisition_passed`;
- `dual_core_frequency_control_endurance_passed`.

## Next-goal selection

Recommend one primary next goal, with explicit rationale:

- frequency acquisition refinement and wider environmental applicability;
- phase-estimator definition and bounded hybrid phase/frequency preview;
- reference-loss holdover and controlled recovery;
- GNSS receiver provisioning or timing-grade GNSS upgrade;
- physical waveform/voltage/metrology qualification;
- product/platform interfaces after the timing core is stable.

Do not bundle all later goals into one programme. Prefer the goal that removes
the largest remaining barrier to a credible GPSDO.

## Required final report

Create a tracked report under `docs/60_EXPERIMENTS/` containing:

- concise decision and rationale;
- exact evidence, firmware, model, estimator, policy and response identities;
- correction history and terminal code for every active run;
- measured convergence, gain, settling, hysteresis, deadband and dither;
- GNSS validity/availability evidence and limitations;
- cross-core architecture and isolation results;
- fault, abort, recovery and evidence-preservation outcomes;
- exact final tests/builds and explained skips;
- every remaining blocker and unsupported claim;
- the one recommended next programme.

Update roadmap/readiness documents to agree. Preserve previous reports and
models as historical evidence.

## Completion

Mark the programme complete only when the report, durable state and referenced
artifacts agree and validate. Record the last confirmed applied code and leave
it static. Do not delete evidence, automatically restore, push, open a pull
request or archive the task without separate authorization.
