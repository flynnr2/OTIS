# CX321 Response-Observability Candidate Comparison

Date: 2026-08-21
Status: offline decision complete; no physical authority

## Decision

CX321 v2 selects a dedicated, identification-only 1,500-second cumulative-
snapshot estimator with a three-exact-count response floor. The identification
stimulus remains 21 DAC codes. The natural hybrid controller, its authoritative
600-second estimator, its request mathematics and its material-response
classifier remain unchanged.

The selected gate is:

```text
pre1 = first complete 1500 s total after the setup exclusion
pre2 = next contiguous complete 1500 s total
eligible only if pre1 == pre2, error is nonzero and inside the entry band

delta_id = -21 * sign(pre2_error_counts)

post = first complete 1500 s total after the 900 s response deadline
r_counts = post - pre2

pass only if:
    r_counts * delta_id > 0
    3 <= abs(r_counts) <= 14
    all identity, support, epoch, health, replay, ACK and tight-entry gates pass
```

This replaces the v1 proposal to classify the first fresh 600-second response.
It makes implementation the next offline preparation gate; it does not claim
implementation complete or authorize a bundle, rehearsal or physical work.

## Evidence and reconstruction

The fixed-code null source is Stage 3 run
`stage3_fixed_code_20260801T121709Z`. Its stable region contains 43,227
consecutive accepted one-second intervals, CNT sequences `2201..45427`, with no
invalid interval or DAC command. The authoritative source hashes are frozen in
`profiles/qualification/cx321_response_observability_comparison_v1.json`.

The plant-parity source is Stage 5 run
`stage5_fresh_session_smoke_20260802T080043Z`. Each of its nine 2,400-second
visits retains at least 1,501 seconds after the frozen 900-second exclusion, so
each visit supplies one complete 1,500-second estimate without extrapolation.

Current HEAD correctly refuses to read these historical packages as current
evidence. The reconstruction therefore used the acquisition revision recorded
by the package and the historical analysis revision
`b4b3ca46019a740c77ea52267c8fb5e96998f00e`. Verdicts were evaluated in exact
integer-count space; no subtraction of two approximately 10 MHz floating-point
values determined a pass or failure. The exact 43,227 interval counts are
retained in the provenance-bound compact fixture
`tests/fixtures/cx321_stage3_stable_interval_counts_v1.json`; current tests
recompute both candidate histograms from that fixture.

For each candidate, the null replay enumerated every possible start within the
stable interval record using the candidate's complete prospective timeline,
including setup exclusion, two pre-stimulus windows, response exclusion and all
post-stimulus windows. The 900-second deadline is not treated as 900 complete
PPS intervals: the first usable interval must open at or after the deadline.
An exactly D14-aligned application therefore gives a 900-interval phase; a
noncoincident application gives 901. Both phases were exhaustively replayed.
The detailed table below reports the noncoincident 901-interval phase, matching
the retained Stage 5 windows, which opened `900.628..900.745` seconds after
acknowledgement. The 900-phase results are also frozen in the comparison
profile. Overlapping candidate placements are deliberately
included: the result is an exhaustive outcome enumeration over this retained
record, not an estimate of independent statistical trials.

## Common plant model

The conservative retained lower gain is:

```text
G_min = 0.00016357422282453626 Hz/code
```

The exact 1,500-second reconstruction of the nine plant visits produced a
drift-cancelled gain envelope of approximately:

```text
0.000164713541422220 .. 0.000172526245099798 Hz/code
```

The comparison continues to size the stimulus with the slightly lower retained
600-second `G_min`; it does not improve the bound merely because the new
estimator's observed minimum is higher.

For 21 codes:

```text
21 G = 0.0034350586793152614 .. 0.003640142109361477 Hz
```

## Candidate results

| Candidate (reported 901-interval phase) | Eligible null placements | Observed false attribution | Expected 21-code response | Decision |
|---|---:|---:|---:|---|
| First 600 s response, two-count floor | 9,564 | 39 positive, 35 negative | `2.061..2.184` counts | Reject |
| Two persistent 600 s responses, one-count floor | 9,564 | 208 positive, 81 negative | `2.061..2.184` counts per response | Reject |
| Two persistent 600 s responses, two-count floor | 9,564 | 0 in either direction | `2.061..2.184` counts per response | Do not select |
| One 1,500 s response, three-count floor | 18,219 | 0 in either direction | `5.153..5.460` counts | Select |
| Two-direction 21-code bracket | not qualified by current classifier | exact linear-drift cancellation | `4.122..4.368` 600 s contrast counts | Reserve redesign |

### Present single-window 600-second gate

The complete schedule occupies 4,202 accepted intervals from an arbitrary
setup boundary: 901 intervals to the first eligible support, two 600-second pre
windows, an identification boundary, 901 intervals to response support, then
two 600-second post windows. Of 39,026 complete
placements, 9,564 had exact-equal pre totals.

Using only the first post window and the frozen two-count floor produced 74
false signed detections. The modeled lower 21-code response clears that floor by
only `0.061` count. An injected exactly-two-count shift passed 6,733 of 9,564
positive placements and 8,069 of 9,564 negative placements. This candidate is
not sufficiently separated from the observed null behavior.

### Persistent 600-second gates

Requiring both post windows to move by one count in the commanded direction is
worse: the fixed-code record contains 289 such outcomes. “Persistent” is not a
substitute for a magnitude floor.

Requiring each post window independently to clear the full two-count floor
produced no false attribution in this record. However, an injected exactly-
two-count shift passed only 2,893 of 9,564 positive placements and 7,350 of
9,564 negative placements. The large directional difference is a property of
the retained fixed-code sequence and illustrates the gate's poor margin at the
predicted minimum. A second post window also adds 600 seconds without improving
the quantization of either response estimate.

### Longer-window estimators

The fixed-code screen applied one prospective rule to all candidates:

```text
floor_counts = observed non-overlapping fixed-code range + 1 exact count
```

| Span | Independent fixed-code outputs | Fixed range | Floor | Floor, Hz | Minimum floor-clearing step at retained `G_min` | 21-code response | Direct plant-dwell parity |
|---:|---:|---:|---:|---:|---:|---:|---|
| 1,200 s | 36 | 2 counts | 3 counts | 0.0025 | 16 codes | `4.122..4.368` counts | yes |
| 1,500 s | 28 | 2 counts | 3 counts | 0.0020 | 13 codes | `5.153..5.460` counts | yes |
| 1,800 s | 24 | 2 counts | 3 counts | 0.001667 | 11 codes | `6.183..6.552` counts | no |

The 1,200-second estimator has less response margin. The retained plant dwells
do not contain a complete 1,800-second settled window, so selecting 1,800
seconds would claim parity the evidence cannot provide. Longer exploratory
windows also have too few independent fixed-code outputs and no direct plant-
dwell parity; favorable origin alignment was not treated as qualification.

The 1,500-second estimator is therefore the longest candidate with direct
parity to every retained plant visit. Its strict executable configuration,
exact contract and plant reconstruction are frozen separately in
`profiles/estimators/cx321_plant_sign_1500_config_v1.json`,
`profiles/estimators/cx321_plant_sign_1500_v1.json` and
`profiles/qualification/cx321_plant_parity_1500_reconstruction_v1.json`.

Its complete null timeline is:

```text
setup application
  + exclude through 900 s deadline
  + first full interval and 1500 intervals pre1
  + 1500 intervals pre2 and ID request = at or after setup + 3900 s
ID acknowledged application (new exact timing origin)
  + exclude through 900 s deadline
  + first full interval and 1500 intervals post
  = response close at or after ID application + 2400 s
```

Across all 18,219 exact-equal-pre placements, the post-minus-pre response was:

```text
-2 counts:      2
-1 count:   1,102
 0 counts:  13,785
+1 count:   3,149
+2 counts:    181
```

This is the noncoincident 901-interval phase. The exact-deadline-aligned
900-interval phase also had 18,219 eligible placements, with response counts
from `-2` through `+2` and no three-count detection. The decision is therefore
unchanged across both legal support alignments.

Thus the equal-pre condition does not make the response identically zero, and
a sign-only predicate would be invalid. No placement reached the three-count
floor. Adding an ideal five-count shift—the integer response below the modeled
21-code minimum—made every placement pass in both directions.

The arithmetic floor-clearing stimulus for the new floor is 13 codes:

```text
ceil(0.002 / G_min) = 13
```

But 13 codes predict only `3.190` counts at `G_min`, a `0.190`-count margin.
CX321 therefore retains 21 codes: it is already inside the characterized
envelope and supplies more than two counts of modeled minimum margin. It is no
longer described as the smallest floor-clearing step for the selected
estimator.

### Drift-cancelled two-direction bracket

For an outbound response `r1` over duration `D1` followed by a return response
`r2` over `D2`, the exact linear-drift-cancelling contrast is:

```text
C = 2 * (D2*r1 - D1*r2) / (D1 + D2)
```

Under `f(code,t) = offset + G*code + b*t`, this cancels the linear drift term
and returns the two-leg plant contrast. It is scientifically attractive, but
it consumes two applications and 42 movement codes. That leaves exactly two
applications and 42 codes for the required two natural material transactions,
with no spare. More importantly, it needs a newly qualified multi-transaction
classifier: the current per-leg wrong-sign rule can fault a leg that the
combined drift-cancelled statistic would accept, and an intentional return
conflicts with current chatter-history semantics. It remains a future redesign,
not a fallback hidden inside v2.

## Interpretation and limitations

The exercise compares measured false-attribution behavior over retained
evidence; it does not establish a calibrated false-positive probability,
guarantee a future detection or make the plant model generally control-ready.
The fixed-code run and plant run occurred in historical sessions. Their exact
identities and unchanged measurement topology make them appropriate for this
offline design decision, but a future implementation still needs deterministic
firmware/host parity, affected verification, an exact bundle, complete
operational-path rehearsal and separate exact-bundle physical authority.

The new estimator is only for the one identification transaction. All natural
hybrid decisions and their response checkpoints remain on the selected
600-second estimator so the CX320 controller science and counterfactual
materiality are not changed.
