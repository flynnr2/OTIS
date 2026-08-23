# CX322 Stage 5 Attempt 7 Terminal

## Decision

CX322 completed its decision-bearing 12-hour physical qualification in attempt
7 (`stage5_live_attempt7_20260822T1921Z`). The terminal result is
`bounded_direct_hybrid_evidence_acquired`: physical acquisition, deterministic
replay, offline analysis, sealing, and evidence registration all passed.

This is an acquisition pass, not a claim that the bounded controller achieved
zero phase slope or revealed a precise one-code plant gain. It established that
the unchanged firmware hybrid law can materially influence phase in the
expected direction without measurably degrading frequency performance. It also
showed that the four-application campaign envelope ends before sustained phase
regulation can be assessed.

No CX322 retry is authorized. The next gate is an offline successor-design
decision using the retained request, response, phase, and budget-hold evidence.

## Physical terminal and evidence integrity

The supervisor reached the exact healthy endpoint at `2026-08-23T08:00:32Z`.
Capture closed cleanly one second later under the same sole serial owner. The
run saw 1,537,671 serial lines, parsed 1,537,653 of them as declared records,
and retained 201,031,513 captured bytes with:

- zero parser errors, reconnects, rejected commands, or owner gaps;
- zero abort submissions or deliveries at the healthy terminal;
- an exact static terminal at DAC code 43054 (`0xA82E`), epoch 5;
- exact replay of all 66 hybrid decisions and all four progressive
  transactions; and
- no missing source artifact, replay discrepancy, or finalization failure.

The immutable evidence identities are:

- seal semantic SHA-256:
  `3ccda92c765c7d69af69fe82c86738b9497ddae6bc3667773df44b84f01036d0`;
- seal file SHA-256:
  `147d602bc9d3a7c0eb47542952330930532d051556ab1aa687395f6d8ed9bf8f`;
- evidence-snapshot semantic SHA-256:
  `a860badcd121273ca2a71945ef4ad2ad489b55c962dbbab2ec8d2dec8072c498`;
  and
- registered package content SHA-256:
  `f71ddb6479c0a140e8f8377998bc37d3556f1e554853ed6476c626fe1400fddf`.

## What the firmware did

Firmware applied the complete authorized budget of four natural,
phase-material corrections:

| Decision | Frequency term (Hz) | Phase term (Hz) | Actual movement | Frequency-only counterfactual |
|---:|---:|---:|---:|---:|
| 6 | -0.001666666940 | -0.000416666667 | -6 codes | -5 codes |
| 9 | -0.001666666940 | -0.000555555556 | -6 codes | -5 codes |
| 11 | 0 | -0.000509259259 | -1 code | 0 codes |
| 13 | 0 | -0.000462962963 | -1 code | 0 codes |

The applied path was therefore `0xA83C -> 0xA836 -> 0xA830 -> 0xA82F ->
0xA82E`, or 14 codes of cumulative movement. Removing the phase term from each
recorded decision yields only 10 codes of frequency-only movement. The phase
channel changed all four integer requests and accounts for the four-code
difference; the final two applications were wholly phase-driven.

There was no chatter, range clamp, I2C failure, cadence breach, or policy
fault. Every application and response was bound to the exact code, DAC epoch,
request, estimator interval, and acknowledgement sequence.

## Phase result

The frozen matched comparison passed:

```text
baseline absolute OLS phase slope       0.001937057182 cycles/s
matched active absolute OLS phase slope 0.000939358315 cycles/s
full active absolute OLS phase slope    0.000948227489 cycles/s
matched 1,800 s improvement             1.795857962 cycles
matched improvement fraction            0.515059068
```

The prospective comparison required at least 1 cycle and 10% improvement.
Both were exceeded. The phase correction therefore produced a real reduction
in the reference-relative phase ramp, approximately halving its magnitude.

It did not establish sustained phase regulation. The four applications were
consumed by device uptime 12,337 seconds. Subsequent decisions remained
observation-only under `global_application_budget_hold`. Relative phase later
crossed zero and reached -26 cycles at the last decision. At that point the
unapplied combined demand was +8.279592074 codes. The controller was asking to
reverse direction, but the frozen experiment correctly prohibited a fifth
application.

This distinguishes two facts: the phase term has useful sign and authority,
but the four-application envelope is too short to observe whether repeated
bidirectional control converges, settles into a bounded cycle, or becomes
inefficient. A static final DAC code proves compliance with the experiment; it
does not prove closed-loop convergence.

## Frequency result

Frequency performance did not degrade under the frozen comparisons:

```text
baseline residual RMS                  0.001666666940 Hz (3 estimates)
active residual RMS                    0.001308802325 Hz (60 estimates)
RMS change                            -0.000357864615 Hz
baseline TIGHT-inside occupancy        1.000000000
active TIGHT-inside occupancy          0.933333333
occupancy degradation                  0.066666667
allowed occupancy degradation          0.100000000
```

The RMS result improved, while TIGHT occupancy decreased by 6.67 percentage
points and remained within the prospective 10-point comparison. The baseline
frequency population contains only three selected estimates, so the numerical
RMS improvement should be treated as descriptive evidence of no material
degradation, not as a precise performance ratio.

## Response observability

The exact 1,500-second responses were:

| Movement | Observed response (Hz) | Classification | Commanded direction seen |
|---:|---:|---|---|
| -6 | -0.001666667 | healthy, near resolution | yes |
| -6 | -0.001666667 | healthy, near resolution | yes |
| -1 | 0 | healthy, near resolution | no observable sign |
| -1 | -0.001666667 | healthy detected | yes |

Three of four observations had the commanded sign, but three were formally
near the empirical resolution floor. Dividing a one-count estimate change by
six codes gives `0.000277777833 Hz/code`; dividing the same one-count change by
one code gives `0.001666667 Hz/code`. Their disparity demonstrates estimator
quantization, not a credible order-of-magnitude plant-gain change. These
observations must not replace the calibrated plant model as precise gain
estimates.

The first three 3,600- and 7,200-second views were right-censored by later
applications. The final one-code application had zero observed response at the
available 3,900- and 7,500-second estimates. The nominal 600-second views also
landed on the next available selected estimate at 1,500 seconds and are marked
as not settling-complete. The defensible conclusion is directional support at
short horizon and no persistent frequency displacement resolvable at the
longer final-code horizons.

## Successor-design consequence

CX322 supports continuing hybrid-control development, but not by reinstating a
short sign gate or simply declaring the present bounded controller qualified.
The successor design should use offline replay to choose a finite authority
envelope that can observe at least one natural direction reversal after the
zero crossing. It must retain the current exact provenance, cadence, range,
per-step bound, fail-static behavior, and nonterminal treatment of
near-resolution responses.

The next decision should compare candidate application-count and stopping
envelopes against the observed request sequence, phase crossing, frequency
occupancy, and prospective chatter/efficiency safeguards. Increasing live
authority is a new operator decision; this terminal grants none.
