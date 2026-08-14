# Stage 5 Prompt: Campaign B — Bidirectional Acquisition

Execute Stage 5 only if Campaign A passes and its evidence replays exactly.

## Goal

Prove that the loop can acquire from the opposite side of the crossing, detect
sign correctly in both directions, and produce a better same-backend dynamic
model without turning each correction into a separate approval cycle.

## Pre-campaign analysis

Use Campaign A to update, but not opportunistically loosen:

- response-classification thresholds;
- observed gain range;
- same-backend settling/t95 evidence;
- cadence and exclusion rationale;
- deadband and cumulative-detection logic;
- oscillation or reversal stop rules.

Any change must be versioned, replay both old and new evidence, and remain
inside the master's immutable 21-code, 1800-second initial and hard-range
limits for Campaign B. If Campaign A contradicts the plant sign or makes the
initial envelope unsafe, stop instead of compensating with a wider policy.

## Predetermined reposition

Under a new run identity, healthy capture, active abort path and manual-only
authority:

1. establish `0xA800` as a predetermined open-loop starting state;
2. require exact requested/accepted/applied acknowledgement;
3. record a DAC epoch;
4. complete at least the full exclusion and fresh-support period;
5. confirm a valid negative-side or otherwise model-consistent starting error.

If `0xA800` is no longer model-consistent or the crossing evidence has shifted
outside the characterized envelope, do not arm Campaign B.

## Immutable Campaign B envelope

- starting code: `0xA800` / 43008;
- maximum automatic corrections: 8;
- maximum absolute correction: 21 codes;
- maximum cumulative automatic movement: 168 codes absolute;
- hard range: `0xA800..0xAB00`;
- minimum applied-to-applied cadence: 1800 s;
- at least 900 s exclusion plus 600 s fresh support after every write;
- all Stage 4 GNSS, identity, transaction, response and abort gates.

## Execution

Arm once and automatically chain healthy steps. Use the same per-step capsule
and transaction rules as Campaign A.

Stop on deadband, correction/cumulative/range limit, a pre-frozen healthy
terminal rule, or the first fault. Do not automatically restore `0xA950`.
Leave the final confirmed code static and record it.

## Combined analysis

Analyze both campaigns together:

- convergence direction and rate from both sides;
- response per code and any asymmetry;
- overshoot, reversal, limit-cycle and deadband behavior;
- t50/t90/t95 at 60 s diagnostic resolution where supported;
- 600 s authoritative response and quantization;
- hysteresis and repeatability across visits;
- temperature and elapsed-time context without unsupported causal claims;
- requested/accepted/applied latency and I2C health;
- every indeterminate or stopped step.

Freeze a versioned post-campaign frequency-control policy for the dual-core
phase. It may retain conservative initial values. It may shorten cadence or
change step size only when the combined evidence and replay demonstrate a
wider safety margin; it may not exceed 21 codes or widen `0xA800..0xAB00` in
this programme.

## Deliverables and exit gate

Deliver sealed Campaign B evidence, combined Campaign A/B analysis, updated
plant/settling/response contracts, an updated policy with exact provenance,
and a Stage 5 report.

Pass if acquisition is safe and convergent from both starting sides, all
transactions replay, and no unexplained reversal, dither, capture degradation
or actuator fault occurs.
