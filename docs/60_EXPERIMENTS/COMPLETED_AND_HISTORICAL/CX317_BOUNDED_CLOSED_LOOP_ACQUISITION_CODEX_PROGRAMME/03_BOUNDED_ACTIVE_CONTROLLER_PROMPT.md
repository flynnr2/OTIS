# Stage 3 Prompt: Bounded Active Controller

Execute Stage 3 after GNSS and actuator preflight passes. Implement and test the
active path, but do not arm or execute it on hardware in this stage.

## Goal

Convert the proved preview into a transaction-safe experimental controller
whose only live authority is the immutable master envelope.

## Architecture

Retain the existing estimator and I-only numerical policy. Do not add phase,
proportional, derivative, Kalman, adaptive, thermal-compensation or holdover
terms.

Keep three modules distinct:

1. estimator/control decision: produces an immutable bounded request;
2. authority/transaction layer: verifies run identity, arming, budgets,
   freshness and one-request-at-a-time semantics;
3. actuator owner: performs I2C and reports accepted/applied outcome.

The controller must use the last confirmed applied code. A request is not an
applied code.

## Required active transaction

Every possible DAC write must have:

- run, session, build, profile, estimator, model and policy identity;
- decision and source-observation references;
- current confirmed applied code;
- requested delta and requested code;
- step, cumulative, count, cadence and range checks;
- short-lived authorization sequence/nonce;
- accepted or rejected state and reason;
- applied code, application sequence/timestamp and I2C result;
- post-write DAC epoch and estimator-history reset;
- one immutable step capsule tying pre-state to eventual response.

Reject duplicate, stale, reordered or already-consumed requests. Permit only
one request outstanding. Missing acknowledgement or ambiguous I2C outcome is a
fault and cannot be retried automatically.

## Arming and abort

Add a dedicated active firmware/profile identity. Default and preview builds
remain structurally unable to actuate from the controller.

Arming must bind exact run/build/profile/model/estimator/policy/response hashes,
correction and cumulative budgets, start code, code range and expiry. Reboot or
session change clears it.

The independent host abort FIFO and a bounded device-side abort command must
both inhibit new requests. Abort must not depend on a healthy estimator and
must not issue a restoration write.

## Response policy

Create and freeze a versioned response-classification contract before hardware
actuation. Derive its thresholds from:

- measured gain minimum/maximum;
- 21-code predicted response;
- 600 s quantization and fixed-code statistics;
- empirical detection floor and hysteresis;
- 60 s diagnostic trajectory;
- replayed drift and temperature context.

Test cumulative evidence across steps so one near-resolution result can remain
healthy/indeterminate while persistent absence, confidently wrong sign,
excessive response or growing error stops the campaign.

Classify measurement-valid response evidence before evaluating eligibility for
the next request. Model inapplicability enters `OUT_OF_MODEL_HOLD` without
erasing the response. Nearby-air SHT41 data remains a recorded covariate and is
not a measurement, model-applicability or control gate.

## Mandatory replay and fault injection

Replay both Campaign A and Campaign B and at least:

- ideal convergence;
- smallest/largest measured gain;
- quantized and noisy response;
- initial indeterminate response followed by cumulative detection;
- wrong-sign plant;
- excessive gain;
- drift and temperature context, including missing and out-of-observed-context
  SHT41 data without a temperature-derived veto;
- valid response followed by model inapplicability, fail-static hold and fresh
  requalification;
- GNSS fix invalid/stale/recovery;
- missing/malformed PPS and snapshot/count faults;
- requested/accepted/applied disagreement;
- I2C failure, timeout, duplicate and stale acknowledgement;
- clamp, step, cumulative, correction-count and cadence limits;
- capture-owner loss, reconnect, reboot and abort;
- telemetry backpressure with healthy control state;
- lost non-droppable transaction evidence.

## Source and build guards

Add tests that fail if:

- any non-programme profile gains controller-to-DAC reachability;
- active parameters differ from the bound profile;
- an actionable decision bypasses GNSS/reference/count/code-domain-model,
  applied-code, capture-owner or abort eligibility;
- model inapplicability can erase a valid response or produce a new write
  before fresh requalification;
- any fault causes automatic restore or uncontrolled retry;
- `actionable` remains true after request consumption;
- telemetry formatting can mutate controller state.

Run focused, full and firmware-matrix verification. Build the dedicated active
artifact but do not flash it.

## Deliverables and exit gate

Deliver the active policy/profile, transaction and response contracts, host and
firmware fixtures, campaign dry runs, exact authorization review, and Stage 3
report.

Pass only when all failure cases stop locally and the happy paths complete
without exceeding a bound. This gate makes Campaign A eligible to be armed; it
does not itself move the DAC.
