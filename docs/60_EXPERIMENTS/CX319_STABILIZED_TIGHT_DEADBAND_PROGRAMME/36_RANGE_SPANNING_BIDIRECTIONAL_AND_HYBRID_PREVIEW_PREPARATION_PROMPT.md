# Range-Spanning Bidirectional and Hybrid-Preview Preparation Prompt

## Authority and immediate duty

The CX319 G3 upper-side live run reached its immutable terminal state on
2026-08-13. Do not repeat or reinterpret that physical acquisition. Use the
finalized result and evidence identities in
`37_Q4_UPPER_SIDE_NONACTIONABLE_PHYSICAL_RESULT.md` as a frozen input to this
preparation.

This prompt authorizes offline preparation only. It does not authorize a
firmware flash, serial-device access, reset, DAC write, control arm, physical
rehearsal, live acquisition, or phase/hybrid actuation. Those operations require
a later explicit operator decision bound to an exact machine-readable bundle.

The completed run did not produce an actionable negative-direction condition.
Its required disposition is already complete:

1. the unchanged acquisition was finalized through the analyzer, sealing and
   registration path;
2. the result is classified as a non-actionable upper stimulus with
   demonstrated stable tight-band hold, not controller rejection or successful
   upper-direction qualification; and
3. the exact terminal DAC state, identities, raw evidence and non-pass
   provenance are preserved.

## Decision-bearing objective

Design and prepare a new, separately identified physical programme that will:

> Demonstrate repeatable bidirectional acquisition of the tight frequency band
> across a deliberately excited local DAC range; map all four state-dependent
> deadband boundaries at useful code-domain resolution; characterize the
> intervening plant response and hysteresis; use matched lower/upper response
> evidence to accelerate activation and correction cadence safely; and
> evaluate the selected hybrid controller continuously in zero-authority
> preview so that a bounded active-hybrid qualification can be proposed
> immediately if the evidence supports it.

The programme must be focused and ambitious. Do not substitute another
single-point G3 retry or a long passive dwell.

## Frozen physical basis

Use the current physical plant evidence and the completed G2/G3 evidence.

- Use the frozen nominal crossing near `43069.627` / approximately `0xA83E`,
  not the synthetic rehearsal value `0xA833`.
- Account for the conservative crossing replay envelope
  `0xA817..0xA864`.
- Retain `0xA800..0xAB00` as the characterized hard operating envelope.
- Preserve the authoritative 600-second accumulated integer-edge-count
  semantics while mapping the existing deadband.
- Use the measured local slope, approximately `0.0001701 Hz/code`, while
  retaining its finite-run provenance and limitations.

At that slope, one DAC code contributes approximately `0.102` accumulated
count over 600 seconds, and one integer count is equivalent to approximately
`9.8` DAC codes. The nominal code-domain landmarks are therefore approximately:

| State-dependent boundary | Nominal vicinity |
|---|---:|
| Lower release, inside to outside at `-4` counts | `0xA816` |
| Lower entry, outside to inside at `-2` counts | `0xA82A` |
| Upper entry, outside to inside at `+2` counts | `0xA851` |
| Upper release, inside to outside at `+4` counts | `0xA865` |

These are design centres, not acceptance truths. Freeze actual scan regions
from all available immutable evidence before execution.

## Programme structure

Prepare two physical parts under separate state and authority transitions but
one provenance-linked programme.

### Part A — fine non-actuating boundary map

Map all four state-dependent transitions:

1. lower-side `OUTSIDE` to `TIGHT_INSIDE` while increasing code;
2. `TIGHT_INSIDE` to upper-side `OUTSIDE` while increasing code;
3. upper-side `OUTSIDE` to `TIGHT_INSIDE` while decreasing code; and
4. `TIGHT_INSIDE` to lower-side `OUTSIDE` while decreasing code.

Use a monotonic two-pass method that preserves hysteretic state:

1. Perform a first survey through each predicted transition region using
   four-code steps.
2. Use that survey to bracket each observed transition.
3. Repeat the complete outbound-and-return trajectory using one-code steps
   within at least plus or minus four codes of each observed transition.
4. Do not use bisection or arbitrary point ordering if it would destroy the
   state history needed to interpret hysteresis.
5. At each fine point, require at least two fresh authoritative 600-second
   observations. Increase adaptively to a maximum of six observations when
   adjacent values or classifications are mixed.
6. At the last code retaining the prior state and the first code producing a
   candidate transition, require at least four fresh observations unless a
   predeclared sequential stopping rule requires more.
7. Require the policy's actual consecutive-observation transition predicate;
   do not infer a state transition from an isolated count.
8. Repeat enough of the return path to distinguish reproducible hysteresis
   from drift or a one-visit anomaly.

Target a tested transition bracket no wider than two DAC codes where the
finite evidence is consistent. A one-code bracket is desirable but not a
mandatory claim. If adjacent codes produce mixed results, report the observed
mixed-transition interval rather than forcing a single threshold.

Preserve separately:

- the exact count-domain policy boundaries;
- each observed code-domain transition bracket;
- temporal drift or visit-to-visit displacement;
- measurement quantization and repeated-window evidence;
- the distinction between finite-run resolution and calibrated or population
  uncertainty.

Do not claim that a one-code scan establishes a permanently known one-code
physical boundary. One code is approximately `0.0001701 Hz`, while an
individual 600-second integer-count observation has approximately
`0.001667 Hz` quantization. The resolution claim must be supported by repeated
observations, phase/frequency covariates where valid, and honest interval
reporting.

Externally commanded scan transitions are setup stimuli that open new DAC
epochs. Frequency, phase, and hybrid control authority must remain disarmed
during Part A. Preserve raw observations unchanged and label any aggregated,
unwrapped, fitted, or drift-adjusted result as derived evidence.

### Part B — automatic range-spanning frequency-control traversal

Use a precommitted trajectory of this form:

```text
lower outside
-> automatic positive-direction acquisition
-> qualified deadband dwell
-> high outside
-> automatic negative-direction acquisition
-> qualified deadband dwell
-> low outside
-> automatic positive-direction reacquisition
-> final qualified deadband dwell
```

Treat externally commanded endpoint transitions as setup stimuli that open new
DAC epochs. Disarm or transfer authority explicitly as required. Never mix an
external setup transition with armed automatic-control authority. Let automatic
frequency control own every return-to-deadband portion.

Endpoint selection requirements:

- Select endpoints with several accumulated counts of margin beyond the
  applicable hysteretic release boundary. Do not place an endpoint exactly at
  the predicted `+/-4`-count boundary.
- Evaluate approximately `0xA800`, or the already demonstrated `0xA808`, for
  the lower endpoint and approximately `0xA880..0xA890` for the upper endpoint,
  but derive and justify the exact codes from retained evidence and Part A.
- Keep all movement inside `0xA800..0xAB00`.
- Confirm prospectively that correction count, maximum step, cumulative
  movement, cadence, settling, and hard-range budgets can recover each
  endpoint.
- Revise the new programme's frozen finite budgets before execution if the
  evidence requires it. Never weaken or extend them after seeing live results.

The automatic corrections should provide the range-spanning response
staircase wherever possible. Do not add an independent fine open-loop sweep to
Part B when Part A and the controlled trajectory already answer the question.

## Required physical and control analysis

Preserve and analyze at least:

- measured response at every applied code and DAC epoch;
- response sign, magnitude, latency, settling, and repeatability;
- local slope and any material departure from the existing linear model;
- all four entry and release transition intervals;
- three-count state-retention behaviour;
- code-domain hysteresis width in both directions;
- correction efficiency, overshoot, reversal, chatter, and alternation;
- crossing/midpoint stability through the outbound and return sequence;
- repeatability of the final lower-side acquisition;
- exact request, acceptance, application, response, authority, session, and
  ordering provenance; and
- reference, capture, queue, transport, and diagnostic health throughout.

A pass requires the complete trajectory, not merely a final inside-band state.

## Hybrid preview boundary

Run the selected relative-phase estimator and selected hybrid candidate
continuously over Parts A and B, but keep every phase and hybrid output strictly
non-actionable:

- no hybrid-derived DAC request;
- no hybrid influence on frequency-controller delta or eligibility;
- no mutation of live response or movement-budget state; and
- explicit zero-authority evidence in firmware, telemetry, host replay, and
  final analysis.

Compare the hybrid preview with the observed frequency-only trajectory.
Determine whether it:

- selects the correct direction;
- respects phase-bias and movement caps;
- remains stable across DAC-epoch and band-state transitions;
- predicts reduced reference-relative phase movement;
- avoids unacceptable modeled frequency degradation;
- avoids repeated alternation, chatter, clamp, and low-efficiency faults; and
- replays exactly across firmware and host implementations.

Include deterministic non-actuating fault coverage through the first
decision-bearing hybrid consumer and every authority boundary. Do not claim
that coherent host fixtures establish an unexercised firmware or physical
boundary.

## Activation and correction cadence acceleration

Treat cadence acceleration as a required decision-bearing output, not an
optional optimization.

After matched lower- and upper-side physical response evidence exists:

- derive response latency, settling time, estimator-support requirements, and
  transaction-completion latency separately for both directions;
- compare directions and use the slower demonstrated bound wherever a shared
  timing value is required;
- determine whether the inherited 900-second settling exclusion, 600-second
  estimator span, 1500-second full-history reset, and 1800-second activation
  or correction cadence remain justified;
- replace unnecessarily conservative waiting periods with the shortest
  evidence-supported frozen timings that retain an explicit margin;
- state the raw observations, calculation, margin, assumptions, and
  applicability behind each shortened interval;
- verify the new timing with response replay, estimator/controller parity,
  cadence-boundary tests, and accelerated operational rehearsal; and
- prove that acceleration cannot reuse pre-write evidence, cross DAC epochs,
  overlap transactions, violate response classification, or act before the
  first complete fresh downstream decision.

Preserve the authoritative 600-second estimator when the objective is to map
the existing count-domain deadband. Shortening that span changes the policy's
count-domain meaning and must be treated as a separately identified policy
experiment, not as mere acceleration. Faster overlapping, diagnostic, or
phase-derived estimates may be retained as supplementary evidence but must not
silently define the deadband transitions.

The existing timing values must not survive merely because they were inherited.
Conversely, do not shorten any interval speculatively or adapt it after
examining the live qualification. If matched physical evidence cannot justify
acceleration, retain the interval and state the evidence gap precisely.

## Automatic domain-aware rollover semantics

Make legitimate RP2040 counter and timestamp rollover support automatic and
domain-aware in every validator, analyzer, replay path, supervisor, finalizer,
and sealing check used by the programme.

- Every counter or timestamp must declare or unambiguously inherit its clock or
  counter domain from the governing contract.
- Derive legal width, modulus, forward-distance calculation, and rollover
  behaviour from that declared domain.
- Canonical RP2040 rollover handling must not depend on a caller remembering an
  optional Boolean or similar opt-in flag.
- Remove, replace, or fail closed on APIs where omission of an optional
  rollover flag can misclassify legitimate RP2040 wrap as backward time.
- Accept a wrap only when the declared domain permits it and the transition is
  valid forward progression under that domain's width, modulus, and ordering
  rules.
- Reject absent, unknown, contradictory, and unsupported domains.
- Retain strict backward-movement rejection for domains whose contracts do not
  permit wrapping.
- Do not infer wrap merely because a later numeric value is smaller.
  Distinguish wrap from reordering, duplication, stale data, excessive gaps,
  session changes, capture gaps, and corruption.
- Preserve raw pre-wrap and post-wrap values unchanged. Label every derived
  extended value with its reconstruction, domain, assumptions, and provenance.
- Apply identical semantics in firmware-facing validation, host capture,
  replay, supervision, analysis, finalization, evidence indexing, and sealing.
- Validate historical artifacts against the manifest and domain contract with
  which they were created. Do not require them to satisfy a newer domain matrix
  unless migration is explicitly in scope.

Add deterministic checks for no-wrap progression, exact-boundary wrap,
progression across wrap, multiple records around wrap, illegal backward
movement, excessive ambiguous gaps, absent or contradictory domains,
duplicate/reordered records, session transition near wrap, and host/firmware
replay parity. Cover the complete producer-to-first-decision-bearing-consumer
path, not merely a shared utility function.

Treat any optional caller-controlled rollover switch as a platform defect.
Repair it at the shared semantic layer, run the focused regression, affected
integration checks, and required operational-path rehearsal, then return
promptly to the decision-bearing physical programme.

## Operational path and verification

Use the stabilized capture, supervisor, transaction, priority-abort, analysis,
sealing, and registration paths. Do not create a bespoke bench runner unless
the existing operational path genuinely cannot represent the programme. If a
platform change is required, add the cheapest deterministic regression
covering both sides of the affected handoff and its first decision-bearing
consumer.

Before proposing physical execution:

1. Freeze the programme contract, boundary-scan regions, point ordering,
   sequential stopping rule, endpoint calculations, correction budgets,
   accelerated cadence, estimator windows, domain-aware rollover semantics,
   command envelope, stop conditions, expected transactions, build identity,
   host tools, analyzer, seal, and registration path.
2. Run proportionate Fast, Campaign, and affected Release verification.
3. Rehearse the real operational topology, including commands, exact
   acknowledgements, cadence and rollover boundaries, transport obstruction,
   independent abort, continuous serial ownership, logical rotation, analysis,
   sealing, and registration.
4. Produce a concise evidence-backed readiness report and a machine-readable,
   non-effective authority proposal.
5. Stop and request explicit operator authorization for the exact frozen
   physical bundle.

## Predeclared terminal outcomes

At minimum distinguish:

- fine boundary map and bidirectional frequency acquisition passed;
- endpoint excitation remained insufficient;
- a transition interval could not be bounded at the target resolution;
- deadband or plant model requires revision;
- positive or negative controller response failed;
- hysteresis, chatter, alternation, or efficiency failed;
- cadence acceleration was invalid or unsupported;
- hybrid preview requires revision;
- counter/timestamp domain or rollover-contract fault;
- measurement, transaction, authority, or platform fault; and
- operator abort.

A programme pass requires consistent finite-run boundary intervals, healthy
positive and negative automatic transactions, qualified entry from both
directions, repeatable return behaviour, exact replay, all movement and timing
budgets respected, domain-correct rollover handling throughout, and zero
phase/hybrid authority contamination.

If the range-spanning frequency programme and hybrid preview pass, immediately
prepare, but do not execute without separate authorization, a short and
separately identified bounded active-hybrid programme. Base its perturbations,
limits, and cadence on the preserved physical trajectory. Do not silently
promote hybrid preview inside this frequency-only programme.

Keep work directed toward this decision-bearing result. Do not expand into
unrelated telemetry improvement, historical migration, generalized framework
work, or narrative documentation beyond what is required to preserve changed
semantics, authority, provenance, and operational readiness.
