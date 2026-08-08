# Stage 3 Prompt: Bounded Hybrid Phase/Frequency Preview

Execute Stage 3 after the relative-phase estimator is selected. This stage is
host-only and non-actionable.

## Goal

Combine the established frequency estimate and relative phase into one bounded,
state-aware counterfactual control request, with no authority or DAC reachability.

## Architecture

Maintain distinct layers:

```text
raw snapshots
  -> relative-phase and frequency estimator
  -> operating-state policy
  -> one combined hybrid preview
  -> counterfactual plant inverse/limits
  -> telemetry and replay only
```

The frequency and phase components must remain separately visible, but only one
combined counterfactual request is produced. Do not create two independent
integrators or actuators.

## Required candidate grid

Evaluate all pull-in/cap/band combinations in the master. Add a candidate only
when it tests a materially different hypothesis; do not create an unbounded
parameter search.

For every candidate freeze:

- estimator and plant-model identity;
- phase pull-in time and bias cap;
- frequency policy and deadband semantics;
- update and counterfactual-decision cadence;
- rounding, clamp, step and cumulative budgets;
- integrator and anti-windup rules;
- state entry/exit hysteresis;
- phase-step, session-loss and reference-loss behaviour;
- DAC-epoch estimator-reset/reseed and bumpless-transfer behaviour;
- preservation of raw cumulative phase across a healthy DAC epoch;
- explicit authority fields, all false.

Candidate previews may be computed frequently for visibility, but comparisons
of hypothetical DAC chatter must use the declared actuation-like cadence and
fresh-support rules.

## Preview states

At minimum implement:

- `RELATIVE_PHASE_ACQUIRE`;
- `FREQUENCY_ACQUIRED_PREVIEW`;
- `HYBRID_TRACKING_PREVIEW`;
- `PHASE_STEP_HOLD_PREVIEW`;
- `REFERENCE_LOST_PREVIEW`;
- `RECOVER_PREVIEW`;
- `FAULT_PREVIEW`.

No state is named or reported as actual `LOCKED`.

## Mandatory replay comparisons

For every candidate report:

- modeled phase movement and residual distribution;
- modeled frequency error and 600 s stability;
- phase and frequency contributions to every request;
- counterfactual DAC corrections, alternations, path length and clamp approach;
- time to frequency-acquired and hybrid-preview eligibility;
- phase-step overshoot and recovery;
- response to reference loss/return and session reset;
- sensitivity to plant-gain minimum/nominal/maximum;
- exact replay of unchanged historical frequency-only decisions when phase
  contribution is forced to zero.

Reject a candidate that improves phase only by materially worsening frequency
stability, generating repeated alternation, depending on unavailable absolute
epoch information or hiding an unexplained adaptive rule.

## Structural zero-authority requirements

Tests and static inspection must prove that the preview:

- cannot import or call the actuator/serial/I2C path;
- cannot set `actionable` or `actuation_authorized`;
- cannot consume an authorization nonce;
- cannot mutate the active frequency controller, response classifier or budget;
- cannot alter actual applied-code state;
- remains counterfactual after its shadow code diverges;
- records model-based post-divergence values as modeled, not observed.

## Deliverables and exit gate

Deliver versioned candidate profiles, preview engine, deterministic replay,
comparison report, selected live-preview candidates and complete tests.

Pass when at least one bounded candidate reduces modeled relative-phase movement
without material frequency degradation or chatter, and all candidates remain
structurally unable to actuate.
