# Stage 6 Prompt: Combined Live Stress and Fault Campaign

Execute Stage 6 after Stage 5 passes. Use separate run identities for the
real-GPS active-frequency observation and destructive/synthetic fault
rehearsals.

## Goal

Observe the selected tight frequency policy and hybrid preview together long
enough to expose interaction failures, then attack phase/reference handling
directly without granting phase authority.

## Part A: combined real-GPS run

Start from the last confirmed Stage 5 code. Do not issue a nominal-restore or
new stimulus write.

Freeze before arming:

- selected tight frequency policy;
- selected relative-phase estimator;
- finite hybrid-preview candidate set;
- exact build/profile/model/response identities;
- 12 h qualified duration, 90 min qualification deadline and 16 h absolute
  wall-clock ceiling;
- at most 8 automatic frequency corrections;
- at most 168 codes cumulative automatic movement;
- unchanged 21-code step and 1800 s minimum cadence;
- scheduled service-load bursts and finite terminal-clear deadline.

Run normal real-GPS service, environmental collection, telemetry and declared
USB load. Do not inject a destructive physical reference or power fault while
the active frequency profile is armed.

Preserve every 1 s phase input, selected phase output, 60/600 s frequency
estimate, active frequency decision and hybrid-preview candidate decision.

Part A passes when it reaches the exact finite endpoint, clears authority,
replays exactly, preserves timing/service isolation, respects all budgets and
shows no phase-to-authority contamination. Zero automatic correction is a valid
pass if the tight policy remains legitimately inside.

Do not automatically extend to 24 h. Permit an extension only when a
predeclared metric is genuinely decision-ambiguous, and record that decision
before seeing extension data.

## Part B: phase and reference fault rehearsal

Use non-actuating pseudo-PPS or deterministic host/firmware fixtures. Exercise:

- positive and negative one-cycle phase steps;
- larger bounded phase steps;
- constant phase offset and frequency ramp;
- missing, duplicate, short and long PPS;
- reference loss of several declared durations;
- return with clean requalification;
- snapshot gap/association loss and capture-session restart;
- GNSS invalid, stale and identity-epoch transition;
- Core 0 service stall and telemetry backpressure;
- phase-estimator/preview queue saturation;
- reordered, duplicated and malformed records;
- abort during acquire, tracking preview and recovery preview.

Verify that faults produce explicit preview states, end the old phase epoch,
grow or mark uncertainty honestly, and never create a DAC request. Do not label
the reference-loss behaviour as holdover; this programme demonstrates only
preview loss/recovery semantics.

## Combined analysis

Report:

- measured tight-band occupancy, corrections, path and churn;
- relative-phase movement and detrended residual without absolute claims;
- modeled phase improvement for every selected hybrid candidate;
- frequency degradation, if any, introduced by the phase term in preview;
- candidate sensitivity to plant gain and pull-in assumptions;
- state transitions around real and injected faults;
- recovery duration and phase-epoch discontinuities;
- Core 0/Core 1 isolation, queue depth/loss and transaction latency;
- exact host/firmware/live replay;
- all evidence that phase/hybrid authority remained zero.

## Deliverables and exit gate

Deliver sealed Part A and Part B evidence, combined comparison, full tests,
firmware matrix, no-hardware validation and Stage 6 report.

Pass when the tight frequency loop remains bounded, at least one hybrid preview
materially reduces modeled phase movement without unacceptable modeled
frequency/chatter cost, every fault fails closed, and no preview value influences
physical actuation.
