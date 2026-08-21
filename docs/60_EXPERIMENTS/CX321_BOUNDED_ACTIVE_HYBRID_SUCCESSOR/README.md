# CX321 Bounded Active-Hybrid Successor

## Offline design decision

CX321 is the selected offline successor to the sealed CX320 bounded non-pass.
It does not repeat attempt 9, reinterpret its zero response, lower the frozen
detection floor, or scale the natural hybrid controller to manufacture a large
material request.

The selected design adds one separately identified `PLANT_SIGN_QUALIFY`
transaction before phase qualification. It uses the already bounded 21-code
maximum step and the unchanged authoritative 600-second estimator to establish
that the current session's D14/D8 measurement and DAC path can observe the
positive plant sign. Only after that gate passes and frequency re-enters
`TIGHT_INSIDE` may the run open a fresh 1,800-second phase-comparison baseline
and use the unchanged natural hybrid controller.

This is a design decision, not physical authority. No exact bundle, activation,
flash, reset, serial access, setup stimulus, DAC write, control arm, physical
rehearsal or live acquisition is authorized.

## Quantitative basis

The frozen lower plant gain and empirical response-detection floor are:

```text
G_min = 0.00016357422282453626 Hz/code
F_det = 0.0033333317438761396 Hz
```

Therefore:

```text
d_detect = ceil(F_det / G_min)
         = ceil(20.378099228090218)
         = 21 codes
```

Twenty codes do not clear the floor at the measured lower gain:

```text
20 G_min = 0.003271484456490725 Hz < F_det
```

Twenty-one codes predict:

```text
21 G = 0.0034350586793152614 .. 0.003640142109361477 Hz
```

By contrast, CX320's natural six-code transaction predicted only
`0.0009814453369472176..0.0010400406026747078 Hz`, or approximately
`0.589..0.624` of one 600-second count increment. Attempt 7 serialized a
one-count signed response at invalid 1,499-second support; attempt 9 serialized
zero at exact 1,500-second support. Both healthy-indeterminate outcomes are
plausible quantizations of a sub-resolution response. Repeating six codes does
not make the sign gate better posed.

The natural controller also cannot reliably generate a detectable response
while tight. One frequency count contributes about 4.8075 raw controller
codes. Even the retained-inside three-count case plus the full phase cap gives
only:

```text
3 * 4.8075 + 4.8075 = 19.2300 -> 19 codes
```

Nineteen codes remain below `F_det` at `G_min`. Increasing controller gain,
strengthening the phase term, or scaling a natural hybrid request to 21 would
change the controller science and its counterfactual materiality. CX321 does
none of those things.

## Selected plant-sign gate

After exact setup propagation and `TIGHT_INSIDE` entry:

1. After the setup change's 900-second exclusion, require the first two complete
   non-overlapping selected 600-second estimates to be contiguous, valid, in the
   current setup/DAC epoch, the exact same nonzero signed integer count, and
   within the one- or two-count entry band. They complete 1,500 and 2,100
   seconds after setup. This entry is observation-only: no automatic application
   may precede the identification stimulus, and the applied code must still be
   exact setup code `0xA83C`. If those conditions are not met, the plant-sign
   stimulus is not exercised; CX321 does not spend an unqualified frequency-
   acquisition application first.
2. Apply exactly one identification stimulus:

   ```text
   delta_id = -21 * sign(pre_error_counts)
   ```

   From setup code `0xA83C`, positive pre-error requests `0xA827`; negative
   pre-error requests `0xA851`. Both remain inside `0xA800..0xAB00`.
3. Hold one exact 2,400-second characterization-style dwell in the
   `rp2040_timer0` domain. Exclude the first 900 seconds. The existing response
   transaction uses the first complete fresh selected estimate at 1,500
   seconds and retains its 30-second evidence-acknowledgement deadline. An exact
   acknowledgement moves only to `PLANT_SIGN_CONFIRM`; it does not release
   phase or actuation authority. A second non-overlapping selected output at
   2,100 seconds confirms same-epoch continuity, common health and tight
   re-entry, but does not change the response statistic or classification.
   Prohibit another request before 2,400 seconds.
4. Define:

   ```text
   f_pre  = exact latest selected-600 error that generated the ID request
   f_post = first complete fresh selected-600 error after the 900 s exclusion
   r_id   = f_post - f_pre
   ```

   The immediately preceding pre-stimulus estimate must have the exact same
   signed integer count as `f_pre`, but it is an eligibility check—not an
   averaged baseline. Likewise, the 2,100-second post output is confirmation,
   not an aggregate. The response therefore retains the existing one-window
   estimator and frozen detection floor.

5. Pass only when all identity, continuity, epoch, common-health, transaction,
   replay and tight-reentry gates are exact and:

   ```text
   r_id * delta_id > 0
   abs(r_id) >= 0.0033333317438761396 Hz
   abs(r_id) <= 0.009890137738354194 Hz
   ```

The upper bound is the existing 21-code excess-response threshold. Because the
predicted post-stimulus error is inside the frozen frequency deadband, the
existing classifier may legitimately label a successful transaction
`inside_deadband`; that health label is admissibility, not sign evidence. The
independent numerical product and magnitude predicates above must still pass.
A zero or below-floor response does not pass merely because it is otherwise
healthy. A wrong-sign, excessive, invalid, discontinuous or inexact response
stops fail-static. There is no automatic retry or restoration.

## Conditional hybrid continuation

The identification stimulus is not a frequency-control application, phase-
control application, phase-material application, or phase-performance sample.
It never enters the natural controller demand or its frequency-only
counterfactual.

It does consume one of the four application slots and 21 of the 84 movement
codes. A passing gate therefore leaves three applications and 63 codes: enough
for two required natural phase-material applications plus one spare.

After the exact first-response ACK, second-output confirmation, 2,400-second
boundary and tight re-entry all pass, CX321 starts a new 1,800-second frequency-
only `PHASE_QUALIFY` comparison baseline at the post-identification code. The
earliest natural material application is 4,200 seconds after the identification
stimulus, or 6,300 seconds after setup. All boundaries use exact recorded
`rp2040_timer0` ticks; host integer-second uptime is only a conservative lower
bound and cannot open a gate early. The original 12-hour qualified and 16-hour
absolute limits remain unchanged; using the attempt-9 timing analogue leaves
approximately 38,390 seconds, or 10.66 hours, after that earliest material
entry.

A later small natural response may remain
`healthy_indeterminate_near_resolution`. It may clear the transaction only if
the same-run plant-sign attestation remains exact and current, its own evidence
is valid and noncontradictory, replay and applied epoch are exact, and frequency
re-enters `TIGHT_INSIDE`. CX321 records separately:

- plant sign physically observed by the identification transaction;
- each material-response classification; and
- whether each material transaction's own sign was observed or remains
  unresolved.

An indeterminate material response is never relabelled as signed. The complete
programme still requires two natural material applications, phase improvement,
frequency preservation and every frozen common-health and terminal criterion.

The plant-sign attestation is current only inside the same finite run and exact
identity chain. Reset/reflash, session or topology/identity change, D14/D8
discontinuity, common-health fault, an ownerless capture handoff, an unproven DAC
epoch, contradictory response, or replay/consumer propagation failure
invalidates it and stops fail-static. Continuous capture-file rotation within
the same exact session and healthy acknowledged natural DAC transitions preserve
it. A zero or opposite sub-floor natural response remains unresolved rather
than contradictory only when the existing classifier still labels it
`healthy_indeterminate_near_resolution` or `inside_deadband`.

## Alternatives rejected at this milestone

| Alternative | Evidence-based disposition |
|---|---|
| Repeat six codes with the 600-second estimator | Rejected: attempts 7 and 9 demonstrate quantization-sensitive sign outcomes below the frozen floor. |
| Wait for more independent 600-second outputs without changing the estimator | Rejected: additional outputs do not change an individual estimator's count quantum or the exact-transaction response. |
| Introduce a longer or aggregated response estimator | Deferred: this is a new estimator contract requiring its own empirical floor, parity, classifier and timing qualification. The selected second post-stimulus output is only a continuity/health confirmation and is not averaged into the response. |
| Apply several unverified natural corrections before sign qualification | Rejected: it consumes scarce authority before the first causal gate and violates the current progressive-authority lesson. |
| Scale the first natural hybrid request to 21 codes | Rejected: it makes phase materiality artificial and changes the controller being tested. |
| Accept healthy-indeterminate as observed sign | Rejected: health is not signed causal evidence. |
| Use a two-direction `+/-21` bracket | Reserved fallback: stronger drift cancellation, but it consumes two applications and 42 codes, leaving no spare after the two required material transactions. |

## Frozen artifacts and next gate

The selected machine-readable designs are:

- `profiles/qualification/cx321_bounded_response_observability_v1.json`;
- `profiles/discipline/cx321_bounded_active_hybrid_plant_sign_v1.json`.

The next milestone is implementation and deterministic proof of the new
`PLANT_SIGN_QUALIFY` state across firmware, host replay, supervision, analysis
and the first downstream consumer. After that, CX321 still requires affected
verification, an exact immutable bundle, structural preflight, a complete
live-topology rehearsal and a separate explicit operator decision. Until all
of those exist and that exact decision is made, current authority remains
offline preparation only.
