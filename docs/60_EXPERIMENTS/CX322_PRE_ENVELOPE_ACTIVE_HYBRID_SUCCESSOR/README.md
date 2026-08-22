# CX322 Pre-Envelope Active-Hybrid Successor

## Decision

CX322 prospectively replaces the CX321 exact-equality plant-sign entry gate.
It admits two healthy, contiguous 1,500-second pre-stimulus estimates when
their total counts differ by at most one count, then measures the response from
the conservative envelope containing both pre estimates. The selected
identification stimulus is 25 DAC codes. The 600-second natural hybrid
controller, its phase and frequency terms, rounding, materiality and response
checkpoints remain unchanged.

This is an offline, non-effective design decision. It neither reinterprets the
consumed CX321 bundle nor authorizes a flash, reset, DAC write, rehearsal or
live acquisition. The executable decision record is
[`cx322_pre_envelope_response_observability_v1.json`](../../../profiles/qualification/cx322_pre_envelope_response_observability_v1.json).

## Why CX321 stopped, and what may change

CX321 attempt 3 reached two individually healthy fixed-code estimates:

```text
pre1 = 15,000,000,003 counts   error = +3 counts
pre2 = 15,000,000,002 counts   error = +2 counts
```

The frozen exact-equality precondition correctly prevented actuation. No
identification response was observed, so that result must remain a bounded
non-pass. For a successor, however, the one-count movement is inside the
retained fixed-code behavior and should be treated as measured baseline
uncertainty rather than requiring equality that the instrument rarely
delivers.

The successor question was deliberately narrow: can the observed one-count
movement be admitted while retaining zero observed null attribution, adequate
response sensitivity, the characterized code range and enough authority for
the two required natural hybrid transactions?

## Exhaustive fixed-code comparison

The comparison replays every complete CX321 timeline placement over the same
43,227 accepted fixed-code intervals. Both legal exclusion-boundary phases are
covered: 900 intervals when application is exactly aligned and 901 when the
first eligible interval opens at the following D14 boundary.

For a requested positive code movement, the conservative pre baseline is the
higher pre total. For a requested negative movement, it is the lower:

```text
B+ = max(pre1, pre2)
B- = min(pre1, pre2)

S = sign(delta_code) * (post - Bsign)
pass magnitude iff S >= 3 exact counts
```

Thus the post estimate must clear the entire two-window pre envelope by the
existing three-count detection floor in the requested direction. A drift
inside that envelope cannot be credited to the DAC stimulus.

| Boundary phase | Complete placements | `|pre2-pre1| <= 1` | Eligible fraction | Null positive detections | Null negative detections |
|---:|---:|---:|---:|---:|---:|
| 900 | 36,928 | 35,600 | 96.404% | 0 | 0 |
| 901 | 36,926 | 35,598 | 96.404% | 0 | 0 |

The CX321 exact-equality gate admitted 18,219 of 36,926 noncoincident
placements, or 49.339%. Conditional on the live absolute-frequency and health
gates, the selected count-difference rule nearly doubles finite-record entry
coverage without admitting a null placement at the three-count floor. The
historical fixed-code level itself is outside the live absolute-frequency band,
so that band is not included in the percentage. These are exhaustive results
over retained difference evidence, not a calibrated future false-positive
probability.

## Why the response step changes from 21 to 25 codes

Relaxing only the precondition while continuing to subtract `pre2` is not
valid: it produces 59 positive null attributions in the 901-boundary replay and
170 in the 900-boundary replay. The pre-envelope removes those false
attributions, but its retained signed null response ranges down to `-3` counts.
The smallest synthetic plant contribution that always clears the existing
three-count floor is therefore six counts:

```text
required shift = detection floor - worst retained signed null
               = 3 - (-3)
               = 6 counts
```

Using the conservative retained plant gain

```text
Gmin = 0.00016357422282453626 Hz/code
```

the minimum code step is

```text
Nmin = ceil(6 / (1500 * Gmin))
     = ceil(24.4537307342)
     = 25 codes
```

Twenty-four codes predict only `5.888672` response counts at `Gmin` and do not
establish the conservative six-count replay shift. Twenty-five codes predict:

```text
25 G = 0.004089355570613407 .. 0.004333502511144616 Hz
     = 6.134033355920110 .. 6.500253766716924 counts over 1500 s
```

Adding an exact six-count shift passes every eligible placement in both
directions and both boundary phases. An exact five-count shift misses 105
negative-direction placements in the 901 phase and 225 in the 900 phase, so
retaining 21 codes would knowingly retain a measured detection hole.

The 25-code requests from setup `0xA83C` are `0xA823` and `0xA855`, both inside
the characterized `0xA800..0xAB00` range. The retained per-code gain samples
were reconstructed from 80-, 176- and 256-code transitions. Applying their
conservative minimum to 25 codes therefore retains the same local-linearity
assumption already used for CX321's 21-code design; it is not a direct 25-code
plant measurement. The step does not extrapolate outside the characterized DAC
code envelope.

## Entry band and TIGHT re-entry

The selected pre errors are two through five 1,500-second counts, nonzero and
of the same sign. Both estimates must be healthy, same-epoch, contiguous and
non-overlapping; their difference must be at most one count, and the unchanged
600-second controller state must also be `TIGHT_INSIDE`.

The lower entry limit increases from one to two counts. At a one-count starting
error, the largest modeled 25-code response could overshoot nominal by
`5.500254` 1,500-second counts, outside the existing `TIGHT_INSIDE` entry
frequency bound. From a two-count starting error, the worst modeled overshoot
is only:

```text
6.5002537667 - 2 = 4.5002537667 counts over 1500 s
                         = 0.0030001692 Hz
```

That remains below the existing `2/600 = 0.0033333333 Hz` TIGHT entry bound.
This restriction is therefore derived from the unchanged controller gate, not
chosen after seeing a future response. The modeled mean does not replace the
required observed two-estimate `TIGHT_INSIDE` re-entry.

The attempt-3 `+3`, `+2` evidence satisfies this prospective entry condition.
It does not retroactively authorize or pass the consumed CX321 run.

## Alternatives rejected

| Candidate | Result |
|---|---|
| Relaxed precondition, response from `pre2`, 21 codes | Reject: 59/170 positive null attributions across the two phases. |
| Pre-envelope, 21 codes | Reject: zero null attribution, but retained five-count response misses remain. |
| Linear drift extrapolation | Reject: it amplifies count quantization into false attributions and additionally depends on request-to-application timing. |
| Two persistent post windows, 21 codes | Reject: adds 1,500 seconds but does not eliminate the five-count response misses. |
| Two-direction bracket | Reject here: consumes another application and movement authority and requires new multi-transaction/chatter semantics. |
| Pre-envelope, 25 codes | Select: zero observed null attribution and full conservative six-count replay sensitivity. |

## Authority budget and scientific scope

The design retains the existing four-application, 84-code global campaign
limit rather than expanding physical authority merely to preserve an optional
spare. Identification consumes one application and 25 codes. Three application
slots and 59 movement codes remain; two required natural transactions can
still each use the unchanged 21-code natural maximum, leaving one slot and 17
movement codes. A third full-size 21-code natural transaction is not promised.

The identification transaction remains separate from natural controller
demand, phase materiality, direction history and chatter semantics. It enters
only the shared application, cumulative-movement and cadence accounting. CX322
does not claim a calibrated false-positive rate, guaranteed future detection,
new plant behavior or improved hybrid performance.

## Next milestone

Implement the pre-envelope admission and 25-code identification transaction in
the existing firmware/host path, add deterministic regressions across the
firmware decision, telemetry, host replay and first downstream natural
consumer, then freeze and rehearse one new exact bundle. Physical execution
requires a separate exact-bundle operator decision after those gates pass.
