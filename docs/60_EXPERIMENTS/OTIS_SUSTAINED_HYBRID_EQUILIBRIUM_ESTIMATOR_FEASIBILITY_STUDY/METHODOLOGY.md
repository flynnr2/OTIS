# Sustained-hybrid equilibrium-estimator feasibility methodology

## Frozen question and claim boundary

This offline study asks whether retained physical evidence can constrain a
modeled durable `equilibrium_code` separately from temporary
`phase_steering_displacement_codes` well enough to justify a later bounded
trajectory study. The machine-readable authority is
[`study_contract_v1.json`](study_contract_v1.json). It was frozen before any
equilibrium interval, held-out metric, sensitivity result, or observability
terminal was calculated.

The decomposition

```text
applied_dac_code = equilibrium_code + phase_steering_displacement_codes
```

is a one-actuator estimator/controller representation. `equilibrium_code` is
not a canonical measurement, calibration, traceable zero-frequency point, or
proof of accuracy. The displacement is neither a second actuator nor an
independently observed state. Raw observations remain unchanged.

The study is offline only. D14 remains the sole reference input, D8 the sole
oscillator/count input, and D10 is excluded. Serial access, reset, flash, GNSS
transmission, FIFO use, DAC writes, arm, rehearsal, live acquisition, and all
effective authority are false.

## Evidence partition

The complete nine-dwell Stage 5 characterization is the only proposed
identification source. Complete dwell segments remain together; adjacent
600-second supports are never split between identification and validation.
Attempt 4 is held out as one complete physical validation run. Its retained
frequency supports may test prediction only, and same-epoch raw phase may test
finite-area consistency only. The rapid nine-visit characterization is a
sensitivity source because its settled outputs use 60/120-second diagnostic
support rather than the selected 600-second method.

All predecessor candidate continuations after their first code-path divergence
are excluded because they are modeled. Cross-epoch raw phase offsets and all
D10 records are excluded.

## Frozen models and arithmetic

The comparator may evaluate only three nested diagnostic hypotheses:

1. one constant equilibrium interval for the complete Stage 5 segment;
2. the same interval with at most 1.91 codes/hour slow drift, derived outward
   from the retained same-code centre drift and minimum gain; and
3. direction/history-conditioned intervals only at the retained natural
   reversals and same-code returns, with the maximum observed 7.3493-code
   difference represented as an outward eight-code reversal dead zone.

Ordinary differential response uses the retained positive minimum, nominal,
and maximum gain. Same-code repeatability is exercised as separate positive and
negative one-count observation perturbations, never as a fixed offset for
every code difference. Calibrated resolution and combined uncertainty remain
unavailable.

The estimator is closed set-membership. Count construction, interval
intersection, and gate comparisons use integer and rational arithmetic. A
600-second integer count `c` maps prospectively to the closed half-count
frequency interval `[(2c-1)/1200, (2c+1)/1200] Hz`. Supports reset at DAC epoch,
capture session, invalidity, or settling boundaries. Raw phase epochs are never
joined.

## Frozen usefulness gate

An equilibrium interval is useful only if its endpoint span is at most 18
codes. That limit is independent of the estimated result:

- An interval spanning 18 codes admits an integer centre no more than nine
  codes from either endpoint.
- Nine codes at maximum retained gain is `0.0015600609040120617 Hz`, below the
  unchanged `1/600 Hz` frequency-RMS degradation allowance and below one
  authoritative 600-second count.
- One code held for `ceil(1 / minimum_gain) = 6114 seconds` has at least one
  cycle of finite phase area. A one-code departure and intentional return costs
  two path codes.
- Adding the nine-code worst-case return correction gives 11 path codes, below
  the unchanged 27-code limit. This is a non-vacuous prospective region and
  does not require replaying V1's exact seven early actions.

The complete result must also pass all gain, quantization, repeatability,
hysteresis, slow-drift, settling, identity-reset, temperature-context, and
leave-one-complete-segment-out cases; cover every held-out physical observation
within the frozen residual gate; remain nonempty; and be materially narrower
than the 768-code characterized range.

## Terminal precedence

A required identity, exact baseline, evidence partition, or frozen model
binding failure stops before estimation and returns
`study_invalid_due_to_evidence_or_model_binding_failure`. Numerical
confounding, an empty/unbounded/wide set, held-out failure, or any failed
sensitivity returns
`equilibrium_state_not_observable_targeted_characterization_required`.
Observability requires every gate row to pass. No threshold, split, nuisance,
or model may change after inspection.

## Separately frozen recovered-source attempt

The first attempt stopped before estimation because the exact Stage 5 plan was
absent from the active checkout. That immutable invalid report remains
unchanged. After the operator directed `proceed`, the exact 3,459-byte plan was
recovered at the recorded SHA-256 and restored without normalization. The
recovery evidence and dirty-source limitation are recorded in
[`SOURCE_RECOVERY.md`](SOURCE_RECOVERY.md).

Before rerunning any numerical model, the second attempt froze
[`study_contract_recovery_v2.json`](study_contract_recovery_v2.json). It binds
the original contract and exact scientific-section digest, so the evidence
split, three hypotheses, gain cases, nuisances, sensitivity list, 18-code
usefulness gate, terminal order, and authority are unchanged. It adds only the
raw Stage 5 file bindings and deterministic executable details that the first
comparator never reached.

For each settled Stage 5 dwell, the recovered comparator reconstructs the
first two non-overlapping 600-D14-interval supports directly from D8 cumulative
snapshots and per-interval counts. Every interval must retain one capture
session, one DAC epoch, contiguous D14 identity, exact D8 down-counter
arithmetic, valid flags, and a start at or after the 900-second exclusion.
Integer count error is the sole input to the frozen half-count interval.

The slow-drift projection uses exact D14 sequence distance in hours and exact
rational half-plane intersection. The history hypothesis uses one durable base
and one common return offset bounded to `[-8,+8]` codes; it does not attach a
full hysteresis offset to every code change. Attempt 4's 52 selected supports
remain wholly held out. A held-out count bin is covered only when its closed
half-count interval intersects the prediction made from identification; all 52
must pass. A cross-run drift prediction fails closed because no common session
time origin was frozen.

The result is
`equilibrium_state_not_observable_targeted_characterization_required`. All
three complete identification sets are empty at minimum, nominal, and maximum
gain. This is a finite-evidence model-consistency result, not calibration and
not a claim that the physical oscillator lacks an equilibrium.
