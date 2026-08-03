# CX317 bounded response-classification contract

Status: frozen before first hardware actuation.

Machine-readable authority:
`profiles/discipline/cx317_response_classification_v1.json`, SHA-256
`0a7ec7b8f569da4a233c03e56c42bd7bd522ca1c27e97d4028b6c52a2ecfe963`.

## Bound evidence

The classifier is tied to the positive measured CX317 gain envelope
`0.00016357422282453626..0.00017334010044578463 Hz/code`, the maximum 21-code
step, the selected 600 s non-overlapping estimator, fixed-code statistics, the
empirical detection floor, and the diagnostic 60 s trajectory. The 60 s
trajectory is diagnostic only and never authorizes a write.

Frozen numerical thresholds:

| Parameter | Value |
|---|---:|
| empirical detection floor | `0.0033333317438761396 Hz` |
| error deadband | `0.006249995628992717 Hz` |
| wrong-sign minimum | `0.0033333317438761396 Hz` |
| growing-error margin | `0.006249995628992717 Hz` |
| excess-response additive margin | `0.006249995628992717 Hz` |
| expected 21-code response | `0.0034350586793152615..0.003640142109361477 Hz` |
| maximum consecutive indeterminate results | 2 |

## Inputs and cumulative state

Each response consumes the immutable step's pre-error, the fresh post-error,
the exactly applied delta, the current confirmed code, hard endpoints, and an
evidence-health bit. The classifier retains the first pre-error and cumulative
applied delta across steps. A single sub-floor result can therefore remain
healthy/indeterminate while repeated absence is evaluated against the expected
cumulative response.

## Ordered classes

The classification order is frozen:

1. `measurement_or_actuator_fault` for missing/unhealthy evidence, zero applied
   delta, or non-finite values;
2. `inside_deadband` when absolute post-error is at or below the frozen
   deadband;
3. `limit_reached` when a hard endpoint blocks the correction direction;
4. `wrong_sign` when the per-step or cumulative response confidently opposes
   the positive plant gain;
5. `growing_error` when absolute error grows beyond the frozen margin;
6. `excess_response` when step response exceeds measured maximum gain plus the
   additive empirical margin;
7. `healthy_detected` when step or cumulative response has the commanded sign
   and reaches the detection floor;
8. `healthy_indeterminate_near_resolution` otherwise, unless persistent
   absence has become a measurement/actuator fault.

Wrong sign, growing error, excess response, and measurement/actuator fault
latch the campaign fault. Healthy detected, healthy indeterminate within its
allowance, inside deadband, and limit reached disarm cleanly and require a new
authorization decision.

On the third consecutive indeterminate result, if the cumulative minimum-gain
prediction is at least twice the empirical floor, absence becomes
`measurement_or_actuator_fault`. Thresholds and ordering cannot change during
a live campaign.

## Verification

The deterministic host replay executes both campaign directions across ideal,
minimum/maximum gain, quantized/noisy, cumulative detection, persistent absent
response, wrong sign, growing error, excess gain, drift/temperature,
GNSS/PPS/count faults, transaction disagreements, I2C/acknowledgement faults,
all bounds, capture loss, reconnect, abort, telemetry backpressure, and lost
evidence. The allocation-free C++ harness verifies matching response and
transaction behavior.
