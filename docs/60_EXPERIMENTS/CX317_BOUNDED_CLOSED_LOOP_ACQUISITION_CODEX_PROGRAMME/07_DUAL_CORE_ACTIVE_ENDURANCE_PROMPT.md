# Stage 7 Prompt: Dual-Core Active Confirmation and Endurance

Execute Stage 7 only after the dual-core preview/isolation gate passes and the
post-Campaign-B policy replays exactly on the dual-core implementation.

## Goal

Confirm active transaction behavior across the new core boundary, then proceed
directly to a bounded 24-hour frequency-control endurance run if the
confirmation remains healthy.

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

- acquisition and deadband occupancy;
- applied correction count, direction, magnitude and path length;
- residual frequency-error distribution and drift;
- response and settling consistency with Campaigns A/B;
- GNSS qualification availability and outages;
- Core 0/Core 1 queue depth, high-water, loss and latency;
- actuator request/ack/application latency and failures;
- service-load effects;
- any dither, saturation, clamp approach or recovery event;
- exact host replay of every decision.

Do not promote this to calibrated accuracy, UTC traceability, phase lock or
holdover evidence.

## Deliverables and exit gate

Deliver sealed confirmation and endurance evidence, updated plant/control
profiles where justified, full verification, and a Stage 7 report.

Pass if the cross-core controller performs every transaction exactly, the
24-hour run completes without unexplained fault or capture degradation, the
loop remains bounded and non-oscillatory, and every decision replays.
