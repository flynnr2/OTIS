# Auto steer service and count excursion investigation 31 October 2026

The 6–31 October observation supports a narrow capture-service repair and an
offline study of controller sensitivity to localized count contributions.
Reference tolerances, numerical steering policy and response margins remain
unchanged. The new firmware image is an offline candidate; the instrument was
left in its separately confirmed operator HOLD and has not been reflashed.

## Timing service repair

The retained run contains 2,442 reference-qualification losses. Replaying the
frozen selector over all 2,169,592 SNPs reproduces their exact closing source
identities and acceptance epochs: 2,440 observation-age ambiguity cases and two
late boundaries. The first group has near-nominal point service intervals but
recognition brackets crossing the unchanged acceptance band. This extends the
[September investigation](AUTONOMOUS_REFERENCE_DISCONTINUITIES_20260926.md);
it does not turn an observation-time bracket into a measured PPS outage or
interrupt latency.

The synchronous periodic publisher formats capture, reference, monitor and
instrument status before returning to the normal FIFO-empty poll. The candidate
observes the FIFO empty before and after each bounded status field instead of
leaving the recognition lower bound unchanged throughout that burst.

The observation samples the native timer before inspecting FIFO-empty state,
serialized with the FIFO IRQ. A racing push either prevents the update or
occurs after the retained timer sample. The existing one-tick recognition
allowance remains in the uncertainty calculation. A nonempty FIFO never
advances the lower bound. The observer does not read a word, consume a software
record, replenish interrupt/word credit, clear a fault, rearm capture, or service
measurement/control state. It therefore preserves the state of a complete status
generation. The ordinary foreground poll remains the sole credit boundary.

The deterministic collision regression compiles the actual sketch periodic
publisher, monitor publisher, active status visitor and real queue with a native
count-status port and an 80-microsecond field-cost model. A PPS placed inside the
burst has a 6,001-microsecond bracket with refresh disabled and loses reference
qualification. With refresh enabled its bracket is at most 81 microseconds;
the real selector accepts the span and the real frequency estimator retains
continuous source support. Complete instrument status still reports the same
code/epoch and matching generation markers.

The backend's actual native hardware port also checks that refresh cannot renew
spent interrupt credit, enable its source, consume a pending word, run from
Core 0, or alter a retained fault. The FIFO helper separately exercises a push
racing the timer/empty pair. These are deterministic firmware regressions,
not measured RP2040 execution bounds. A short physical gate must still measure
the new image's SNP brackets under ordinary complete publication and preserve
the unchanged reference criteria. Do not require a rare spontaneous failure as
the qualification stimulus or repeat the completed 25-day acquisition.

## Epoch 305 source and baseline sensitivity

The [comparison contract](phase_excursion_comparison_v1.json) was frozen before
this comparison execution. It defines source-shape outputs, seven synthetic
traces, alternative pre-window baselines and a conditional arithmetic projection.
It is retrospective diagnosis of an inspected case, not independent validation
or a new qualification criterion. Its outputs have zero operating authority.

A deliberately small [source fixture](../../tests/fixtures/adaptive_hybrid/epoch305_count_excursion_20261031.json)
retains five complete 600-span windows as raw downcounter/service/uncertainty
tuples, the exact decision, write, application and response, and their archive
identity. Every window reconstructs from adjacent modulo-2^32 downcounter
differences and satisfies the existing recognition-bracket predicate. No count
or phase observation is deleted or relabelled.

The selected pre-window has four extra D8 counts supplied by one span; its other
599 spans have zero residual individually. The unchanged controller arithmetic
at the recorded ordinary-path checkpoint reproduces the actual −20-code
request. A localized four-count source and four separately distributed counts
reach that arithmetic as the same aggregate error and recorded phase, producing
the same request. Source shape is not represented by those aggregate inputs.

Conditionally assigning the four-count contribution to a localized phase change,
while retaining the recorded seven-cycle raw relative phase, gives a −1-code
projection through the same arithmetic. This identifies a possible distinction
for a future estimator; it does not establish the physical source of the four
counts, validate a phase-step detector, or authorize that unissued command.
Post-application measurements cannot supply a physical response to it.

Using the same recorded post-window with different descriptive pre-baselines
also changes a fresh-state local classifier result:

| Pre baseline                 | Pre error Hz | Post minus pre Hz | Local response label              |
| ---------------------------- | ------------ | ----------------- | --------------------------------- |
| Recorded selected pre window | +0.006666667 | -0.010000000      | Excess response                   |
| Previous complete window     | -0.001666667 | -0.001666667      | Healthy below the detection floor |
| Mean of two previous windows | -0.000833333 | -0.002500000      | Healthy below the detection floor |

These comparisons preserve the historical IRS classification 5. They do not
reconstruct the earlier classifier's complete cumulative state or replace its
recorded verdict. They show why a transient-bearing pre-window cannot by itself
isolate excessive DAC gain. Source observations implicate neither the oscillator
nor D14 independently: a four-cycle count change can have several physical
origins.

## Next comparison boundary

Keep the numerical controller as the baseline. A future candidate may retain
source-localization and persistence evidence for the FLL contribution while
preserving canonical phase, rather than treating every finite-window phase
contribution as sustained frequency error. Compare both signs, persistent error,
mixed transient/bias, and zero-net quantization pairs under the frozen matrix.
Only a separately frozen future contract may turn candidate behaviour into a
qualification gate. Neither acceptance-band widening nor a post-hoc response
baseline change is adopted here.

The subsequent [source-aware response comparison](PHASE_EXCURSION_TRADEOFF_STUDY_20261031.md)
executes 3,060 synthetic scenarios across six methods and audits all seven
large recorded applications. Targeted confirmation is the next offline candidate
for the demonstrated single-span shape; pure frequency response matches baseline
in the tested cases, while mixed and wider changes retain limitations. This
result does not promote a numerical policy or deploy the capture-service image.

## Provenance and verification

Acquisition session: `15433150169270463301`. Raw acquisition ZIP SHA-256:
`f73cd9001fef7a761f4bae8cfb62b525bfea3aabb51b31fa7b94928884a5b49e`.
The unchanged numerical policy SHA-256 is
`9568fc3cd5ba8d6e1ad91776e22058adc040e7b18e32a42a498f7caf9a738bc9`.
The [machine-readable comparison result](phase_excursion_comparison_result_20261031.json)
binds its contract, fixture and exact arithmetic sources. Reproduce it with
`python tools/analyze_phase_excursion_case.py --output /absolute/local/result.json`.

The fixed `adaptive_hybrid_regulation` image compiles with the pinned Arduino
CLI 1.4.1, RP2040 core 6.1.0 and approved compiler package. Program use is
174,344 bytes, static dynamic memory 150,824 bytes, leaving the existing
111,320-byte runtime reserve. Its exact input set is
`a6503e800bb1ce2d72fe39af216711c83d4899e7dcfd3f8d6c3b02605526478f`;
UF2 SHA-256 is
`57b4ecefe671bd80f7cb631c1b90346c1f489f3fbc55154cf31f445be3d3721e`.
Build provenance retains its working-tree state and is not relabelled as a
historical or physically qualified image. No numerical profile, reference
contract or wire layout changed.

Verification: 473 current tests passed; one check for the default core source
location was skipped. Its four CDC/DTR/reset assertions also passed against the
checksum-verified isolated core 6.1.0 used for this build. The exhaustive current
PIO sweep and generated-instruction comparison passed with the pinned pioasm.
Changed Python files pass lint and the diff passes whitespace checks. Repository
lint reports 106 findings, all in unchanged files; this investigation does not
repair that separate lint debt. The existing detached host/PTY operational-path
tests are included in the suite. No new physical acquisition, serial attachment
or deployment occurred.
