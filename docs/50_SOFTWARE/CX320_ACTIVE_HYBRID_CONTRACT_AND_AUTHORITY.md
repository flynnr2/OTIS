# CX320 Active-Hybrid Contract and Authority

## Scope and current authority

CX320 tests one coherent bounded controller. It combines the authoritative
600-second frequency estimate with a capped reference-relative phase term and
passes one integer delta through the existing request, authority, acceptance,
application and response transaction. It adds no second DAC writer or hidden
integrator.

Current authority is offline preparation only. The policy, firmware profile,
host tools, builds, preflight, simulated operational-path rehearsal and a
non-effective proposal may be created and validated. No flash, reset, serial
device access, command FIFO, setup stimulus, DAC write, arm, physical rehearsal
or live acquisition is authorized by this document.

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
