# CX320 Active-Hybrid Contract and Authority

## Scope and current authority

CX320 tests one coherent bounded controller. It combines the authoritative
600-second frequency estimate with a capped reference-relative phase term and
passes one integer delta through the existing request, authority, acceptance,
application and response transaction. It adds no second DAC writer or hidden
integrator.

This document is descriptive and grants no physical authority. Current
programme state and allowed operations are recorded in
`profiles/programme_status_v2.json`; a live run additionally requires an exact
immutable activation descended from explicit operator authority.

## Timing and topology

- D14 is the sole PPS/reference input.
- D8 is the sole oscillator/count input. Phase is cumulative D8-cycle movement
  relative to qualified D14 PPS inside one declared phase epoch.
- GNSS serial metadata qualifies the same receiver that supplies D14; it never
  replaces D14 as timing authority.
- D10 is the independent external-event input and cannot enter reference
  validity, phase authority, control eligibility or actuation.
- D9/GPOUT0 is deferred. CX320 changes no D8/D9 routing and claims no delivered
  public timing output.

Phase zero is arbitrary at the first qualified boundary of each epoch. Epochs
are never joined by a guessed offset. Raw phase remains unchanged; modeled and
counterfactual quantities are separately identified.

## Frozen controller semantics

The machine-readable policy is
`profiles/discipline/cx320_bounded_active_hybrid_tight_v1.json`. Its numerical
baseline is `p21600_cap1_epoch_reseed_v3` interpreted under current tight-band
semantics:

- phase pull-in horizon: 21,600 seconds;
- phase-bias cap: `1/600 Hz`;
- combined controller gain: `2884.5027706464516` codes/Hz/decision;
- one combined step, limited to 21 codes and `0xA800..0xAB00`;
- no persistent hidden integrator: demand is recomputed from current evidence
  after every application or hold;
- half-away-from-zero rounding after step limiting;
- minimum applied cadence: 1,800 seconds;
- four applications and 84 codes of cumulative absolute movement shared by
  frequency acquisition and phase steering;
- one outstanding request; no automatic retry or restoration.

The phase cap contributes approximately 4.8075 controller codes before
combination and limiting. A static plant offset for the same `1/600 Hz` bias is
9.6150--10.1891 codes across the measured plant-gain envelope. These are
different interpretations and are never conflated.

Phase is materially influential only when removing the phase term while
holding the same input, state and limits changes the final rounded requested
delta. A nonzero floating term alone is not material influence.

## Controller mathematics and intuition

Frequency is the slope of phase; phase is the accumulated position. The
frequency term stops present drift, while the deliberately weaker phase term
slowly returns accumulated D8-cycle displacement toward the arbitrary opening
level of the current continuous phase epoch. It does not align an output to UTC
or to an absolute D14 edge, and it never joins separate phase epochs.

For one authoritative decision, define:

- `e_f = f_hat_D8_given_D14 - 10,000,000 Hz`, the signed authoritative
  600-second frequency error;
- `phi`, the signed accumulated D8-cycle displacement from the current phase
  epoch origin;
- `T_phi = 21,600 s`, the phase pull-in horizon;
- `B_phi = 1/600 Hz`, the absolute phase-bias cap; and
- `K = 2884.5027706464516 codes/Hz/decision`, the controller gain.

The frequency and phase demands are expressed in the same frequency unit:

```text
u_f   = -e_f
u_phi = clamp(-phi / T_phi, -B_phi, +B_phi)
```

When phase authority is qualified, the one controller demand is:

```text
u_combined = u_f + u_phi
```

Otherwise `u_phi` is exactly zero. A state may also authorize no request even
when a diagnostic term is nonzero.

The single integer actuator path is:

```text
delta_raw  = K * u_combined
delta_step = round_half_away_from_zero(clamp(delta_raw, -21, +21))
code_req   = clamp(code_applied + delta_step, 0xA800, 0xAB00)
delta_final = code_req - code_applied
```

Cadence, application-count, cumulative-movement, chatter, progressive-state
and outstanding-transaction gates may still replace `delta_final` with a hold
or fail-static transition. The controller recomputes demand from current
evidence after every application or hold; there is no unrecorded integrator
state accumulating behind a limit.

The exact frequency-only counterfactual repeats the same integer path with
`u_phi = 0`. Phase is materially influential only when its final integer delta
differs from that counterfactual after identical limiting and rounding.

The sign convention gives the intended physical intuition:

- positive frequency error produces a negative frequency demand;
- positive accumulated phase displacement produces a small negative frequency
  bias, so future D8 cycles accumulate more slowly; and
- negative accumulated phase displacement produces the opposite bias.

For example, `phi = +18` cycles represents `+1.8 us` at 10 MHz. Returning
18 cycles over 21,600 seconds calls for `u_phi = -0.000833333... Hz`, or
approximately `-2.404` raw controller codes before combination and rounding.
At `phi = +36` cycles the requested phase bias reaches the frozen
`-1/600 Hz` cap, approximately `-4.8075` raw controller codes. Thus phase
steering cannot dominate the overall 21-code step authority.

With measured plant gain `G` in the frozen range
`0.00016357422282453626..0.00017334010044578463 Hz/code`, the nominal physical
response model is:

```text
delta_f_predicted = G * delta_final
```

The response checkpoint does not accept this model as observation. It requires
fresh post-settling physical evidence and, for an accepted signed response,
`delta_f_observed * delta_final > 0` in the exact applied DAC epoch.

## Progressive states

1. `FREQUENCY_ACQUIRE`: phase term is zero; only settled-outside frequency
   acquisition may use the shared budget.
2. `PHASE_QUALIFY`: two fresh authoritative estimates have established
   `TIGHT_INSIDE`; phase remains zero through a further 1,800-second continuous
   comparison residence while exact phase/epoch eligibility accumulates.
3. `FIRST_PHASE_TRANSACTION`: at most one phase-material application is in its
   mandatory response/replay/tight-reacquisition checkpoint.
4. `HYBRID_TRACKING`: remaining authority is released only after that exact
   checkpoint passes.
5. `PHASE_DEGRADED_FREQUENCY_ONLY`: clean phase-only invalidation revokes phase
   authority and invalidates the old epoch; independently healthy frequency
   control may continue inside the remaining shared budget, but the CX320
   result cannot pass.
6. `FAIL_STATIC`: automatic actuation is disarmed at the last confirmed code.

Phase influence additionally requires current D14/D8 and same-receiver GNSS
qualification, one continuous phase epoch, exact applied code/DAC epoch in the
frequency estimator, phase estimator, controller, prior recorder publication
and response classifier, clean diagnostics/queues/transport, exact run/bundle
identity, and no unresolved request or response.

The first material response `ACKE` is prospectively defined as a host
attestation: the host must first durably preserve and independently replay the
matching `AHY` and `ACT` evidence. Only then may it acknowledge the response
phase. Firmware does not release later hybrid authority until that response is
healthy, support and applied epoch are exact, and frequency re-enters
`TIGHT_INSIDE`.

## Decision evidence

`active_hybrid_decisions_v1` (`AHY`) is the canonical per-decision record. It
preserves both estimator identities, phase epoch/continuity, raw frequency and
phase inputs, separate terms, combined demand, every limit, integer request,
frequency-only counterfactual, materiality, policy states, transaction
identity/status, actual downstream code/epoch and reason. Serialized records
are observations and always `actionable=false`; the private existing
transaction is the only authority-bearing path.

`ACT` continues to preserve request, acceptance, application and response
transactions. `HPR` remains the historical/counterfactual observational
candidate and is not relabeled as physical active evidence.

## Finite programme and decisions

The proposed physical run has a 43,200-second qualified limit starting at the
first complete fresh authoritative 600-second estimate after exact setup
support, and a 57,600-second wall-clock limit starting when the sole capture
owner records the exact run identity before setup. Neither may be extended.
The qualified origin and elapsed interval are measured in the estimate's
`rp2040_timer0` device domain and remain bound to the same capture session;
host UTC records only when the supervisor observed the origin. Host clock
steps or service latency must not move the 41,400-second correction-admission
close or the 43,200-second qualified endpoint. The independent 57,600-second
absolute endpoint retains its declared wall-clock origin.

The prospective baseline is the final continuous 1,800 seconds of
`PHASE_QUALIFY` immediately before the first material application. The primary
phase metric is absolute OLS slope of raw relative phase cycles per second
within each unjoined epoch; secondary metrics are cumulative movement and
maximum excursion. Passing requires at least two material applications, the
first checkpoint, at least 10% and one-cycle matched-interval phase improvement,
no more than `1/600 Hz` frequency RMS degradation, no more than 0.1 tight-band
occupancy degradation, all common-health gates and an exact static terminal.

The complete primary decision vocabulary is frozen in the policy. An honest
non-pass remains decision-bearing and cannot be tuned, extended or retried
after observation.
