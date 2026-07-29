# PPS Reference Characterization

## Purpose

A GNSS PPS is a reference event stream, not a noiseless one-second oscillator.
OTIS should characterize the observed PPS path before choosing estimator windows
or loop bandwidths and should continue monitoring it during operation.

The objective is to distinguish short-term timing noise and path anomalies from
long-term frequency authority.

## Primary derived series

From adjacent valid `REF_CAPTURE` observations derive:

```text
interval_i       = t_i - t_(i-1)
interval_error_i = interval_i - nominal_period
phase_residual_i = t_i - fitted_reference_epoch(i)
```

The fitted epoch, unwrap rules, nominal period, implementation-clock calibration,
and all rejection rules must be recorded.

## Minimum plots

A reference characterization report should include:

1. PPS-to-PPS interval error versus time;
2. histogram and empirical cumulative distribution of interval error;
3. phase residual versus time after an explicitly stated fit;
4. accepted and rejected observations with reason classes;
5. interval error versus receiver quality fields when available;
6. interval error versus temperature, supply, session/reset boundaries, and
   capture-path counters where relevant;
7. stability measures over multiple averaging times, with estimator assumptions.

Plotting only a histogram is insufficient: a plausible distribution can hide
bursts, periodic structure, resets, missed edges, or thermal/session dependence.

## Summary statistics

Report, where meaningful:

- count and duration;
- mean, median, standard deviation, MAD, and robust scale;
- selected percentiles and tail counts;
- short/long/missed/impossible interval classes;
- contiguous clean-run lengths;
- autocorrelation or spectral features if structure is suspected;
- results before and after each documented quality gate.

Do not assume Gaussian tails. Preserve and report outliers before deciding
whether they are reference events, capture-path faults, or unresolved evidence.

## Interpretation for FLL and PLL

A PPS-gated ratio estimator uses the reference boundaries to estimate average
plant frequency. Increasing the averaging interval generally reduces sensitivity
to individual PPS excursions but slows response to real oscillator changes.

A phase estimator is directly exposed to PPS timing noise and fixed/variable path
delay. It therefore needs a precise phase definition, calibrated delays where
claimed, quality gating, and a bandwidth low enough not to transfer excessive
reference noise into the VCOCXO.

Characterization should inform, not automatically choose:

- FLL averaging window;
- PLL bandwidth and phase weighting;
- outlier and continuity gates;
- acquisition and requalification duration;
- holdover entry criteria;
- uncertainty growth when the reference is absent.

## Control boundary

Reference characterization products are diagnostics/metrology inputs. A single
unusual PPS interval must not directly command a DAC correction. Any influence on
control must pass through versioned estimator, diagnostic, eligibility, and policy
records.

## Local PPS Calibration For H1 Count Gates

For sub-hertz DAC/CX317 work, a many-hour run-wide RP2040 tick-rate estimate is
not sufficient by itself. Slow local movement in the RP2040 timer can be
misattributed to the oscillator under test when a 300 s count gate is converted
with one average tick rate.

The H1 host analysis preserves the legacy run-wide estimate but prefers
`LOCAL_PPS_INTERPOLATED` when both count-gate boundaries are bracketed by
accepted REF/PPS observations. The mapper is piecewise linear between adjacent
accepted PPS observations in the same `rp2040_timer0` domain. Rejected PPS
intervals remain diagnostic evidence and are not used for interpolation.

Per-gate diagnostics are written to `csv/h1_count_frequency_estimates.csv` using
`h1_count_frequency_estimates_v1.csv`. This is a host-side correction to
existing count observations, not a replacement for raw counts or timestamps.

This differs from the planned PPS-gated-ratio backend, where accepted PPS edges
define the count gate at capture time. That backend remains the cleaner future
measurement path and needs its own validation before it becomes the preferred
live backend.

`dac_manual_sweep/run_017` remains the canonical rollover-specific example for
this rule. The
raw REF timestamps span about 72408.641 s and include 16 RP2040 timer rollovers:
raw timestamps are therefore not monotonic, but the unwrapped REF series is
monotonic and has no host-classified PPS anomalies. The temporary D10 PPS
witness matched D14 one-for-one at the end of the run, with no D10 short,
overflow, or burst rows. The D14 `rejected_long_count` ended at 16, matching the
number of raw timestamp rollovers; treat that counter as a rollover-sensitive
diagnostic artifact unless firmware diagnostics are updated to compute the
interval on unwrapped timestamps.
