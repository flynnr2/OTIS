# Stage 4 Prompt: Campaign A — Acquisition From A950

Execute Stage 4 only after Stage 3 passes and the exact active artifact is
preserved and identified.

## Goal

Demonstrate repeated automatic I-only frequency correction from the existing
`0xA950` state while learning same-backend response and settling behavior.

This is one capped campaign, not a series of human-approved single-step runs.

## Immutable Campaign A envelope

- exact starting code: `0xA950` / 43344;
- maximum automatic corrections: 16;
- maximum absolute correction: 21 codes per decision;
- maximum cumulative movement from start: 336 codes absolute;
- hard range: `0xA800..0xAB00`;
- minimum applied-to-applied cadence: 1800 s;
- after every DAC epoch: at least 900 s exclusion plus 600 s entirely fresh
  authoritative support;
- one outstanding actuator request maximum;
- I-only frequency policy only;
- GPS receiver metadata gate required for every decision;
- no automatic restoration on stop or fault.

## Entry procedure

1. Confirm sole board/serial identity and no serial owner.
2. Compile, preserve and hash the exact artifact; run complete preflight tests.
3. Flash and open a unique capture before sending any command.
4. Confirm live build/profile/backend/resource/GNSS identity.
5. Establish exactly `0xA950` using the independent manual path if the current
   physical state cannot be proven. This manual establishment does not count as
   an automatic correction.
6. Complete warmup and fresh estimator qualification.
7. Probe both abort paths without a DAC write.
8. Arm one exact Campaign A identity and expiry.

## Automatic execution

For each decision:

1. assert every eligibility and budget field;
2. persist the pre-decision evidence capsule;
3. create one bounded request;
4. clear `actionable` as the request is consumed;
5. require exact accepted/applied acknowledgement;
6. record the DAC epoch and reset all estimator/control history;
7. collect the 60 s diagnostic trajectory without giving it authority;
8. wait for full exclusion and fresh authoritative support;
9. classify the response using the frozen policy;
10. continue automatically if healthy, indeterminate within its cumulative
    allowance, or outside deadband with no stop reason.

The commissioning interpretation applies only to the first response: a clean
near-resolution indeterminate result may continue; a confidently wrong sign,
actuator fault, eligibility fault or excessive response stops immediately.

Stop successfully when the error is inside the evidence deadband for the
pre-frozen consecutive-decision requirement, the correction limit is reached,
the clamp is reached, or further movement is not justified. Distinguish these
from faults.

## Monitoring

Monitor continuously enough to detect faults and preserve evidence. Do not use
blind sleeps. Report at every arm, request, applied acknowledgement, response
classification, automatic continuation, successful stop or fault.

No user response is needed between healthy corrections.

## Analysis and deliverables

After the run stops:

- seal and revalidate raw and derived evidence;
- replay every decision and transaction from the immutable source;
- calculate per-step and cumulative response, response sign, effective gain,
  settling trajectory and t50/t90/t95 where supported;
- report quantization-aware indeterminate cases honestly;
- compare actual convergence with all prior replay envelopes;
- preserve every step as a separately indexed capsule;
- do not discard the final stopping step.

## Exit gate

Pass if at least one automatic correction is safely applied, every transaction
and decision replays exactly, the response never violates a stop rule, and the
campaign reaches a defined healthy terminal state or deadband.

If a fault stops the campaign, classify Stage 4 as diagnostic and do not
proceed automatically to Campaign B.
