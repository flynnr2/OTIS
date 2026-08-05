# GPSDO Long-Term Monitoring and Refinement

This is a future-design note. It applies only after the rig has independently
earned its GPSDO operational claims. It does not change the current
observe-only or bounded-active authority.

## Principle: adaptive evidence, fixed control

Normal operation may collect and analyse evidence continuously, but it must
not automatically narrow or widen the active deadband, alter gain, change
cadence, or write DAC codes for the purpose of self-calibration. A live policy
remains versioned and fixed until a separately reviewed replacement has passed
bounded active validation.

The deadband is a decision threshold, not a direct claim of frequency,
UTC, phase-lock, holdover, or traceable accuracy. A low residual alone cannot
establish the health of the GNSS reference, antenna, capture chain, or an
absolute timing comparison.

## Continuous health and evidence ledger

Preserve a rolling, replayable record of:

- residual-frequency median, robust spread, tails, drift, lagged
  autocorrelation and effective sample size;
- fixed-code residuals, authoritative deadband occupancy, continuous
  residence, boundary crossings and frozen shadow-policy outcomes;
- correction count, code path length, reversals, alternation/dither markers,
  clamp approach and DAC-code trend;
- naturally observed plant gain, directional hysteresis and settling response;
- GNSS/PPS availability and continuity, receiver solution/quality indicators,
  capture latency/jitter and configuration/firmware identity;
- available environment and supply telemetry as covariates, without treating
  correlation as permission for automatic compensation.

Analyses must account for serial correlation. Ordinary independent-sample SEM
is not sufficient for policy recommendations.

## Shadow review and policy recommendations

Run pre-frozen shadow deadbands and hysteresis policies against the same
qualified observations as the live controller. A periodic report may recommend
investigation or nominate a later validation candidate when it sees persistent
evidence that a candidate improves error without material actuator cost, or
when current residual spread/churn indicates that the active guard band merits
review.

Such a report is advisory only. Its promotion path is:

1. Preserve and seal the evidence and recommendation.
2. Review the metrology, reference-chain and actuator-health context.
3. Freeze a new versioned candidate policy with explicit acceptance and
   materiality limits.
4. Validate it in a bounded active run.
5. Promote it only after that validation passes; otherwise retain the existing
   policy or enter a conservative hold/investigation state.

## Periodic focused characterisation

Use maintenance windows, rather than normal service, for infrequent bounded
bidirectional DAC-step characterisation. Its purpose is to re-measure local
Hz/code gain, directional hysteresis, settling, code-dependent nonlinearity
and clamp margin. It must preserve the same safety, range, cadence, capture,
fresh-support and fail-static constraints as an active validation campaign.

Use multi-day or multi-week fixed-code observations across ordinary
environmental variation to refresh stability and drift evidence. Repeat a
short acceptance characterisation after changes to oscillator/DAC hardware,
antenna or receiver configuration, timing/capture firmware, power system, or
the physical installation.

## Independent calibration and accuracy evidence

Self-observation of the PPS-disciplined loop cannot by itself calibrate
absolute frequency or UTC/phase accuracy. For those claims, periodically
compare the unit to an independent reference, such as a characterised second
GNSSDO with a time-interval/phase comparator, a common-view GNSS comparison,
or a traceable laboratory reference. Keep the comparison method, uncertainty
budget, reference identity and environmental conditions with the result.

An external comparison is especially important following a persistent health
alert, a material hardware/configuration change, or before tightening an
accuracy claim.
