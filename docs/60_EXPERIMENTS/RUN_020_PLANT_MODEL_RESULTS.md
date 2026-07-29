# Run 020 Local Plant-Model Results

## Outcome

Run 020 executed the intended focused profile and closes the local-crossing
applicability gap left by Run 019. It directly brackets 10 MHz, confirms a
positive local CX317 gain consistent with the broad Run 019 result, and
provides conservative settling and repeatability bounds.

The evidence supports the versioned observe-only model in
`profiles/plant_models/cx317_h1_bench_v2.json`. It does not authorize active
DAC steering.

## Configuration and measurement health

The enforced preflight verified the uploaded `run_020_crossing_v1`
configuration and exact profile:

```text
AE00,B100,AE00,AB00,AE00,B400,AE00,A800,AE00
```

The six-hour sweep used 2400 s dwells, a 900 s settling discard, 300 s count
gates, the PIO long-gate counter, local PPS interpolation, D14 PPS, and the D10
witness. Results:

- 77 of 77 count windows were valid and non-zero
- 23,250 of 23,250 PPS intervals were valid
- D14 and D10 ended with zero raw-count delta and `MATCHING`
- no parser, reconnect, capture-drop, capture-error, saturation, or overflow
  event occurred
- FC0 ended valid and control-qualified with no fault and zero bad windows
- final DAC restoration to `0x8000` was acknowledged

The 56 warning rows are expected startup/preflight qualification states. They
do not recur after FC0 qualification.

The completed evidence package is sealed by snapshot digest:

```text
4ef9639c0570a497543023443aaeb27f80fc1a66b977b01958d41d1e8eb0698c
```

## Crossing and gain

The direct settled bracket is:

| DAC code | Settled median (Hz) | Error from 10 MHz (Hz) |
|---:|---:|---:|
| `0xA800` | 9,999,999.963233 | -0.036767 |
| `0xAB00` | 10,000,000.059011 | +0.059011 |

Direct interpolation gives `0xA927`. Code-plus-time regressions over all nine
dwell medians give `0xA94C..0xA964`, depending on weighting. The versioned
model therefore uses:

- nominal crossing estimate: `0xA950`
- conservative within-run band: `0xA840..0xAA00`
- estimated crossing voltage: 1.648 V from the separate Run 018 DMM fit

Run 020 did not contain direct DMM measurements, so voltage values are
calibration estimates rather than Run 020 observations.

The four drift-cancelled local slopes are:

```text
0.000155907
0.000155930
0.000169768
0.000187610 Hz/code
```

Mean gain is `0.000167304 Hz/code`; the observed range corresponds to
approximately 4.11..4.95 Hz/V using the Run 018 fit. Run 019's broad
`0.000169064 Hz/code` estimate lies inside this range.

## Repeatability, settling, and exclusion

Corrected `0xAE00` return medians span 0.056718 Hz, with standard deviation
0.022391 Hz. Up/down centre medians differ by 0.032777 Hz. This bounds local
return-path repeatability, but does not fully measure endpoint hysteresis
because each non-centre code was visited in only one direction.

For the seven uncontaminated transitions, t95 estimates are quantized at
approximately 53, 353, or 653 s. All are inside the planned 900 s discard.
The 300 s gate prevents finer dynamic interpretation.

Count sequence 77 straddles the final `0xAE00` dwell completion and immediate
restore to `0x8000`. It is preserved but excluded from final-centre scatter and
settling conclusions. Excluding it changes the final-dwell median by only
0.002467 Hz and does not materially change gain or crossing.

Near-VCOCXO air temperature rose from 28.445 C to 30.455 C and is strongly
confounded with elapsed time. Run 020 does not establish a thermal model.

## Applicability

The promoted model is valid for:

- the Run 020 H1 topology and estimator
- observe-only use
- the measured local range `0xA800..0xB400`
- a candidate automatic envelope of `0xA800..0xAB00` that remains disabled
- gain bounded by `0.0001559..0.0001876 Hz/code`
- a 900 s settling exclusion with the present 300 s gate
- near-VCOCXO air-temperature context of 28.445..30.455 C

It is not valid for active steering, phase discipline, holdover, thermal
compensation, another hardware topology, or use outside its recorded
applicability and diagnostic gates.
