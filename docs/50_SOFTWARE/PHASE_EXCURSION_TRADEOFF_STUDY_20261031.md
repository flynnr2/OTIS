# Localized phase contributions and frequency response comparison 31 October 2026

Targeted confirmation is a useful next offline candidate. A single multi-count
accepted span can trigger a large correction even when later phase progression
is nominal. Waiting for one further complete source window only for that shape
avoids the modeled large correction without imposing blanket delay on distributed
frequency evidence. The comparison does not establish which physical source
moved, promote an estimator or change the numerical operating policy.

## Recorded events and source confidence

The [large-step audit](large_steering_step_audit_20261031.json) covers every
retained application of magnitude at least ten codes, seven applications in
total. Six ordinary-path arithmetic checkpoints reproduce their recorded
requests exactly. The seventh, epoch 266, is a maintenance request requiring
earlier persistence/debt state; its source is audited but no incomplete
checkpoint projection is attributed to it.

| Elapsed day | Applied step | Net source count residual | Source shape                                   | Following applications                     |
| ----------- | ------------ | ------------------------- | ---------------------------------------------- | ------------------------------------------ |
| 1.277       | +10          | -2                        | Six nonzero spans, each at most one cycle      | -1, -1, -6                                 |
| 2.027       | -15          | +3                        | One three-cycle span; the other 599 are zero   | +15 after 45.0 minutes                     |
| 2.058       | +15          | -3                        | Nineteen nonzero spans, each at most one cycle | +1, +1, +1                                 |
| 7.566       | +15          | -3                        | Twenty-nine nonzero spans, at most one cycle   | -5 after 65.0 minutes, then -1, -1         |
| 20.533      | +10          | -2                        | Twenty-two nonzero spans, at most one cycle    | -5, -1, -1                                 |
| 23.491      | -20          | +4                        | One four-cycle span; the other 599 are zero    | +15 after 55.0 minutes, then +6            |
| 23.529      | +15          | -3                        | Fifty-one nonzero spans, at most one cycle     | +6, +1, +1                                 |

The earlier -15/+15 pair is therefore another instance of the localized
positive contribution followed by intervention and a later negative residual.
The day-7.57 +15 request has distributed source evidence and is a useful
challenge case for a filter that should not suppress every large request.

At snapshot 174596, the downcounter difference gives 10,000,003 cycles.
Subsequent intervals remain nominal until the -15 application 587.009 native
timer seconds later. The first subsequent negative residual appears 746.996
seconds after the excursion, already 159.987 seconds after the application,
and is mixed with positive residuals. There is no pre-intervention -3 rebound
or -1/-1/-1 recovery. Those later data cannot establish natural PPS recovery
because the oscillator had already been changed.

The +4 case likewise retains its counter offset, without an immediate opposite
rebound. An isolated corrupted cumulative snapshot would normally produce a
compensating difference at the next correct reading. These records argue against
that specific one-record error; they do not rule out a persistent counter/input
fault. Nearby SNP status is clear. No D6 monitor observation is available in
the later event's segment to corroborate it independently.

Three and four cycles correspond to 300 and 400 ns at 10 MHz. D14 edge movement,
a completed oscillator phase change and a persistent capture offset can have
indistinguishable relative observations. The timer service coordinates do not
resolve those electrical changes. Downstream smoothing cannot create the raw
counter difference, but averaging a finite phase contribution into a frequency
window does not establish continuing frequency bias. D14 remains the chosen
long-term timing authority; this study does not introduce another reference.

## Comparison contract and methods

The [frozen diagnostic contract](phase_excursion_tradeoff_v1.json) defines six
methods, source audits, a synthetic plant and outcome measures. The complete
matrix has 3,060 scenarios and 18,360 method/scenario executions. Constants were
not retuned against the results. The original epoch-305 case and earlier events
are retrospective examples, not independent qualification evidence.

All methods retain the canonical raw observations and closing relative phase.

1. Baseline: unchanged selected 600-span aggregate and hybrid arithmetic.
2. Blanket confirmation: require a preceding complete same-sign FLL window
   before a nonzero-FLL proposal. Pure phase decisions retain their path.
3. Single-span separation: when exactly one span has a residual of magnitude
   at least two cycles and all other residuals sum to at most one cycle,
   conditionally remove that span's contribution from the derived FLL input.
4. Targeted confirmation: for the same localization predicate, defer the whole
   proposal for one subsequent complete window at the same source/DAC identity.
   Do not apply a small phase correction first and restart settling.
5. Segmented fit: fit cumulative counts to a trend plus one phase step, with
   at least 60 spans on each side, fitted step magnitude at least two cycles,
   and at least 36 cycle-squared improvement over a straight-line fit. Project
   its slope into integer-equivalent FLL counts only when those gates pass.
6. Combined method: use that fit when supported; otherwise use targeted
   confirmation for the single-span-localized case. Other source uses the
   unchanged aggregate.

The fitted constants are exploratory model gates, not calibrated statistical
significance or reference-validity thresholds. They have no operating authority.
Single-span separation explicitly assumes the localized contribution belongs
to a completed phase change; targeted confirmation does not require that
immediate assignment.

## Conditional model and observed tradeoffs

The model uses the actual hybrid engine, tagged-debt commit and actual integer
tight-band component. It retains the 900-second measurement exclusion,
600-span windows, response completion no earlier than 1500 seconds, no correction
at that response frontier, 1800-second minimum cadence, step and range bounds.
A small applied correction therefore incurs the existing observation/cadence
cost. References and metadata stay qualified in the performance matrix; this
does not qualify recovery paths or replace those existing gates.

The idealized plant uses the frozen gain-envelope endpoints and nominal gain,
four fractional count phases, both signs and five within-window onset positions.
It includes frequency steps and ramps, phase changes spread over 1/5/30 spans,
mixed phase/frequency changes, bounded reference-phase jitter and counter-offset
glitches. It assumes instantaneous code-to-frequency response and no hysteresis,
ageing or analog readback. Initial raw relative phase is fixed at three cycles;
this is not a sweep of every possible phase/controller checkpoint. Disturbance
amplitudes and timing are declared synthetic inputs, not receiver measurements.

In 360 noiseless single-span phase-offset scenarios, the baseline makes at
least one application of ten or more codes in 120 cases. Targeted confirmation,
single-span separation and the combined method make none. Their maximum step
over the subsequent eight-hour model is six codes; this does not mean every
later correction is one code. Blanket confirmation also avoids all large
applications in this subset. A fit alone misses some boundary-positioned steps.

In all 624 pure frequency-step and 264 frequency-ramp cases, the source-aware
methods match every reported baseline performance metric, including integrated
frequency error and first correctly directed application timing. These methods
retain the ordinary response to distributed
frequency evidence in this matrix. Blanket confirmation adds up to 1200 seconds
for steps and 3300 seconds for ramps. Its average integrated-error ratio to
baseline is 1.053 for steps and 1.105 for ramps; these are means of case ratios,
not estimated physical performance probabilities.

The harder cases expose limits:

| Scenario family                           | Cases | Baseline cases with large applications | Targeted confirmation | Fit with targeted fallback |
| ----------------------------------------- | ----- | -------------------------------------- | --------------------- | -------------------------- |
| Noiseless one-span phase offset           | 360   | 120                                    | 0                     | 0                          |
| Noiseless phase change over 5 or 30 spans | 720   | 291                                    | 285                   | 141                        |
| Noiseless snapshot offset and rebound     | 120   | 20                                     | 0                     | 0                          |
| Quiet oscillator with 1.5-cycle jitter    | 12    | 10                                     | 10                    | 10                         |

The narrow rule does not solve wider phase contributions or endpoint jitter.
The combined fit helps wider changes but still misses boundary/unsupported
shapes. Blanket confirmation rejects more of those effects, at a demonstrated
drift-response cost. In 744 mixed frequency-plus-phase cases, targeted and combined
methods can delay the first correctly directed application by up to 2100 seconds
relative to baseline. No method is a universal winner, and a ten-minute evidence
wait is not automatically a ten-minute closed-loop response penalty. Some
differences reach the existing response/settling frontiers.

At the recorded ordinary-path checkpoints, conditional single-span separation
changes the -15 and -20 projections to -1. Targeted confirmation reports those
proposals pending, without claiming what an unobserved next source window would
have contained. It preserves the day-7.57 +15 projection. Recorded later
measurements followed the actual commands and cannot be reused as responses to
the unissued alternatives.

## Whole retained source check

The localization predicate matches exactly two of the 3,078 selected windows:
the +3-count and +4-count cases. The segmented fit selects only the later case;
the earlier change occurs at span 13 and lacks its required pre-step support.
This is useful selectivity on the retained source, not a forecast that only two
commands would differ in a different closed-loop history.

This check reconstructs 600 accepted APS spans, not 600 raw candidates. Three
selected windows bridge early-excluded raw candidates and contain 601 or 602
raw intervals. Treating each fragment as a nominal second produces false giant
residuals. An initial raw-candidate diagnostic survey is retained locally and
superseded; the accepted-span survey and all seven large-step fixtures agree
with the canonical count reconstruction. No acceptance criterion or source row
was altered.

## Decision and remaining evidence

Carry targeted confirmation forward as the simplest next offline candidate for
the demonstrated single-span problem. It avoids immediately assigning a physical
cause or issuing a small action that restarts settling. Keep conditional
separation and segmented fitting as comparison models, not live estimators.
Do not add blanket persistence to every frequency decision on these results.

The comparison supports avoiding the two observed large localized requests
without slowing the tested pure drift cases. It does not establish safe response
under every mixed disturbance, reference phase history, plant transient or
controller checkpoint. A future candidate needs separate source/phase-state
coverage and a frozen prospective gate before promotion. Neither the current
controller, deployed image, reference qualification, historical response labels
nor their uncertainty claims change here.

## Reproduction and verification

Use `python -m tools.compare_phase_excursion_tradeoffs --output /absolute/local/study`
and `python -m tools.audit_large_steering_steps --output /absolute/local/audit`.
The [machine-readable study result](phase_excursion_tradeoff_result_20261031.json)
binds the frozen contract, model input and native binary. The audit binds its
deliberately small source fixture to raw acquisition ZIP SHA-256
`f73cd9001fef7a761f4bae8cfb62b525bfea3aabb51b31fa7b94928884a5b49e`.

Thirty focused checks pass, including the unchanged native hybrid-policy tests,
source arithmetic, audit checkpoints and a quantized closed-loop smoke case.
Every full model application additionally asserts cadence, code/step bounds and
exact application/first-consumer commit. Changed Python lint passes. The offline
tools are not linked into firmware, and no serial operation or deployment occurs.

Self-review corrected a combined-model fallback precedence error to implement
the frozen rule; its original execution is retained under the local study.
Repeating the full matrix changed no output row. No model constants or criteria
were adjusted after examining results. The prior compiled capture-service repair
is unchanged and remains subject to its separate physical integration gate.
