# Master Prompt: CX318 Relative Phase, Hybrid Preview and Tight Deadband

You are operating in the OTIS repository on the same computer as the connected
bench rig. Execute this programme in order. Continue through every healthy,
pre-authorized gate without asking for routine confirmation.

Recommended execution setting: GPT-5.6 Sol, Extra High reasoning.

This programme moves quickly. Reuse sealed evidence, run non-actionable
candidates in parallel, prefer finite falsification tests to long passive waits,
and allow bounded failure to identify the wrong assumptions. Never trade away
measurement identity, replay, authority separation or fail-static behaviour.

## Lead model and delegated workers

The primary executing agent is the **GPT-5.6 Sol, Extra High** lead. The lead
owns the durable ledger, task plan, contract freezes, integration, all live
hardware interaction, authority transitions, gate decisions, scientific claims
and final report.

Use **GPT-5.6 Terra, High** subagents proactively for concrete independent work
when delegation materially reduces elapsed time. Suitable delegated tasks
include:

- read-only sealed-evidence and identity audits;
- independent raw-phase reconstruction and replay-corpus analysis;
- bounded candidate-grid evaluation;
- focused test or log-failure triage;
- source-level authority-reachability review;
- implementation in explicitly assigned disjoint files;
- documentation and claims-boundary cross-checks.

Use available concurrency, normally no more than three supporting workers at
once. Give each worker a bounded task, exact inputs, prohibited actions and a
required concise evidence-bearing result. Avoid parallel edits to the same file
or subsystem. Wait for all results required by the current gate, inspect their
evidence, resolve disagreements and integrate centrally; a subagent's assertion
is never itself a passed gate.

Terra subagents may not:

- touch the bench, flash firmware, open a serial owner or issue a DAC/GPS
  command;
- arm, authorize, consume authority or update the authoritative programme
  ledger;
- freeze or change an active estimator, policy, threshold, budget or stop rule;
- decide that a hardware stage passes, advance a live stage or select the final
  scientific claim;
- weaken a test or reinterpret failed live evidence as passing;
- commit, push, delete or reseal evidence.

Keep ambiguous architecture decisions, cross-layer safety changes, live-run
supervision and final synthesis on the Sol/Extra High lead. If subagents are not
available, continue serially without changing any gate or scope.

## Primary objective

Deliver a replayable relative-phase estimator and a non-actionable bounded
hybrid phase/frequency preview. In parallel, validate the tighter hysteretic
frequency deadband using the already-qualified frequency-only actuation path.

The phase estimator and hybrid preview remain non-actionable for the entire
programme. No result in this programme authorizes phase steering.

## Accepted starting evidence

Treat the following as authoritative unless exact validation finds an integrity
or identity mismatch:

- the CX317 programme decision is
  `dual_core_frequency_control_endurance_passed`;
- the accepted measurement backend is
  `pio_wait_cumulative_snapshot_dma_v1`;
- the selected authoritative frequency estimator is
  `PPS_CUMULATIVE_SNAPSHOT_SPAN_V1`, 600 s non-overlapping;
- the 60 s overlapping estimate remains diagnostic;
- Core 1 owns timing, measurement, estimation and request generation; Core 0
  owns services, physical I2C actuation and acknowledgements;
- the last confirmed DAC code is `0xA828` and must be treated as physically
  unknown until live identity/query evidence reconfirms it;
- the hard characterized DAC range is `0xA800..0xAB00`;
- the maximum automatic frequency correction is 21 codes;
- the initial automatic correction cadence is no faster than 1800 s;
- every DAC epoch requires at least 900 s settling exclusion followed by 600 s
  of fresh authoritative support;
- Stage 7B qualified 151/151 authoritative observations, applied one `+19`
  correction, then retained the final code for 90,000 s;
- the authoritative V2 deadband was
  `abs(error) <= 0.006249995628992717 Hz`;
- the Stage 7 shadow result made both
  `hysteretic_two_count_to_v2` and
  `symmetric_two_count_floor_guard` eligible on Stage 7 data only;
- no shadow candidate was adopted or granted authority;
- calibrated absolute accuracy, UTC traceability, phase lock, absolute epoch
  alignment, holdover and physical waveform margin remain unclaimed.

Read first:

- `docs/60_EXPERIMENTS/CX317_BOUNDED_CLOSED_LOOP_ACQUISITION_FINAL_REPORT.md`;
- `docs/90_ROADMAP/OTIS_SW2_REVISED_ROADMAP.md`;
- `docs/90_ROADMAP/SW2_GPSDO_CONTROL_LOOP_READINESS.md`;
- `docs/30_ANALYSIS/PPS_REFERENCE_CHARACTERIZATION.md`;
- `docs/10_REFERENCE_ARCHITECTURE/TIMESTAMPING_MODEL.md`;
- `docs/50_SOFTWARE/PPS_HARDWARE_SNAPSHOT_REPLACEMENT_ARCHITECTURE.md`;
- `docs/50_SOFTWARE/PPS_CUMULATIVE_SNAPSHOT_SPAN_ESTIMATOR.md`;
- `docs/50_SOFTWARE/CX317_PPS_GATED_SELECTED_ESTIMATOR.md`;
- `profiles/discipline/cx317_stage7_shadow_deadband_v1.json` through V3;
- the sealed Stage 7B exit gate and raw snapshot evidence;
- every prompt in this programme folder.

## Claims boundary

The relative-phase observable is a session-local comparison between cumulative
oscillator edge count and nominal edge count across qualified PPS intervals.
Its zero is arbitrary at the first qualified boundary of a phase epoch.

It is not automatically:

- UTC;
- an absolute time error;
- calibrated cable/receiver/aperture delay;
- the phase of a generated output PPS;
- continuous across reset, session loss or an unqualified reference interval;
- evidence of phase lock.

Use `RELATIVE_PHASE_ACQUIRE`, `HYBRID_TRACKING_PREVIEW`,
`REFERENCE_LOST_PREVIEW`, `RECOVER_PREVIEW` and `FAULT_PREVIEW` or equally
explicit preview-only names. Do not emit `LOCKED` as a demonstrated state.

## Required relative-phase convention

For adjacent qualified snapshots in one capture session:

```text
interval_edges[k] = (previous_X - current_X) mod 2^32
edge_error[k] = interval_edges[k] - 10,000,000
relative_phase_cycles[k] = sum(edge_error[1..k])
relative_phase_time_ns[k] = relative_phase_cycles[k] * 100
```

Positive phase means the oscillator produced excess cycles and is inferred to
have advanced relative to the nominal PPS-defined interval sequence. A positive
phase term therefore requires a negative frequency bias when bleeding the phase
toward the epoch zero. Record the sign convention in every contract and test it
with synthetic vectors.

The exact nominal-frequency and conversion values must come from a versioned
profile. Do not silently generalize this CX317 programme to another oscillator.

A DAC epoch does not end a raw phase epoch when snapshot/reference continuity
remains valid. Record the DAC transition in the phase stream, reset or reseed
only the estimator components declared by policy, and preserve the raw
cumulative phase across the write. Likewise, a detected phase step remains a
visible event in the same phase epoch unless reference identity or continuity is
actually lost. Do not erase the quantity the preview is intended to reduce.

## Programme stages

1. validate sealed evidence and freeze new contracts;
2. implement and replay several relative-phase estimators;
3. implement the multi-candidate bounded hybrid preview;
4. establish host/firmware parity and a short static-code live preview;
5. run two deliberate live frequency-only legs validating the tighter
   hysteretic deadband from opposite directions while hybrid remains preview;
6. run combined real-GPS observation and separate fail-closed fault/phase-step
   rehearsals;
7. audit evidence and select the next single goal.

## Authority granted only when this master is explicitly executed

You may:

- inspect, modify, test and document repository code in programme scope;
- create versioned phase-estimator, hybrid-preview, tight-deadband, telemetry,
  replay, analysis and run-control contracts;
- compile and flash explicit programme firmware profiles;
- run non-actionable host replay, simulation and live preview;
- perform the exact setup writes `0xA808` and `0xA848` in Stage 5 after its
  preflight passes;
- arm the dedicated tight-deadband frequency-only profile for at most four
  automatic corrections and 84 codes of cumulative automatic movement per leg;
- continue automatically between healthy decisions inside a leg;
- run the combined Stage 6 frequency-only campaign inside its frozen limits;
- stop fail-static at the last confirmed applied code;
- repair narrow defects and restart only in a new run directory;
- create local commits when the worktree is suitable.

You may not:

- let phase, hybrid state or phase-derived frequency bias cause or alter a DAC
  request;
- make a hybrid preview actionable, consume authorization or mutate the live
  frequency controller, response classifier or movement budget;
- transmit to or configure the GPS receiver;
- widen any live limit after a run begins;
- automatically restore a nominal code after fault, reset or abort;
- push, open a pull request or delete evidence without separate instruction.

## Tight-deadband experimental policy

Freeze the active candidate before Stage 5 using integer count semantics over
the authoritative 600 s estimate:

| Rule | Frozen value |
|---|---:|
| tight entry | absolute 600 s edge error `<= 2` counts |
| loose release | absolute 600 s edge error `>= 4` counts |
| three-count region | retain previous band state |
| entry persistence | 2 consecutive fresh authoritative estimates |
| release persistence | 2 consecutive fresh authoritative estimates |
| initial/rearm band state | `REQUALIFY_OUTSIDE` |
| maximum automatic step | 21 codes |
| minimum automatic cadence | 1800 s |
| post-write exclusion | 900 s |
| fresh support | 600 s |
| automatic retry | forbidden |
| automatic restoration | forbidden |

The decimal equivalents may be reported, but integer accumulated-edge
decisions are authoritative. Preserve the original V2 threshold as the loose
release boundary and historical comparison, not as tight-entry success.

Do not silently adopt the symmetric candidate. Run it in shadow for comparison.

## Live frequency-only envelope

| Parameter | Limit |
|---|---:|
| DAC hard range | `0xA800..0xAB00` |
| lower-leg exact setup code | `0xA808` |
| upper-leg exact setup code | `0xA848` |
| maximum automatic correction | 21 codes absolute |
| maximum automatic corrections per Stage 5 leg | 4 |
| maximum cumulative automatic movement per Stage 5 leg | 84 codes |
| minimum time between automatic corrections | 1800 s |
| maximum outstanding request | 1 |
| active controller | frequency-only incremental I control |
| hybrid/phase authority | zero |

The predetermined setup write is a separately recorded stimulus transaction,
not an automatic correction. It must bind the exact requested/applied code and
open a new DAC epoch. No other arbitrary setup code is authorized.

Stage 6 may retain the selected Stage 5 tight policy with at most eight
automatic corrections and 168 codes total movement during its combined real-
GPS run. It may not increase step size or cadence.

## Hybrid-preview candidate envelope

Implement one coherent counterfactual control output. Do not create independent
FLL and PLL actuators or integrators that can fight each other.

At minimum evaluate the Cartesian product of:

- pull-in times: 3600 s, 10,800 s and 21,600 s;
- absolute phase-derived frequency-bias caps: `1/600 Hz` and `2/600 Hz`;
- historical V2 and tight hysteretic frequency-band semantics.

The conceptual combination is:

```text
phase_bias_hz = clamp(-relative_phase_cycles / pull_in_time_s,
                      -phase_bias_cap_hz,
                      +phase_bias_cap_hz)
combined_frequency_error_hz = frequency_term_hz + phase_bias_hz
```

Freeze the exact selected formula, update cadence, rounding, anti-windup,
settling, history-reset and state-transition rules before live preview. Emit the
frequency and phase contributions separately as well as the combined
counterfactual request.

## Universal stop conditions for live writes

Immediately inhibit further writes and retain the last confirmed applied code
on:

- operator abort, loss of abort path, capture owner or transport continuity;
- reset, reconnect, identity/profile/hash mismatch or session discontinuity;
- invalid/stale GNSS qualification or malformed reference evidence;
- missing, duplicate, short, long or discontinuous PPS used by the estimator;
- snapshot association/sequence loss, ambiguous wrap, zero/saturated count,
  FIFO/DMA/ring/parser fault or non-droppable queue loss;
- stale/invalid estimator support or failure to requalify a DAC epoch correctly;
- range, correction, cumulative, cadence or outstanding-request violation;
- request/accepted/applied disagreement, I2C failure or ambiguous application;
- confidently wrong-sign, excessive or persistently growing frequency response;
- repeated alternation/dither or an unexplained host/firmware replay mismatch;
- any evidence that a phase or hybrid-preview value influenced live authority,
  controller state, requested delta or DAC application.

On failure, seal diagnostic evidence. Do not modify a threshold and continue the
same run. Repair narrowly and restart under a new run identity.

## Durable state

Before code changes or bench interaction:

1. require a clean supported checkout and record its exact branch/commit;
2. do not discard or overwrite unrelated user work;
3. create `runs/cx318_relative_phase_hybrid_preview/<UTC campaign id>/`;
4. copy `PROGRAMME_STATE_TEMPLATE.md` to `PROGRAMME_STATE.md`;
5. bind all source, build, hardware, estimator, model, policy and evidence
   identities;
6. update state atomically at every stage, flash, setup write, arm, request,
   acknowledgement, application, abort, fault, capture and seal transition.

Never repeat a sealed successful stage because conversational context was lost.

## Defect and continuation policy

- Fix ordinary software defects, rerun proportionate tests and continue.
- Preserve every failed live attempt under its own run identity.
- Do not turn a scientific failure into a software pass by weakening a gate.
- Do not wait through another 24-hour run by default. Stage 6 is finite and
  short enough to falsify the programme; extend only when its predeclared
  decision is genuinely ambiguous.
- If hardware is unavailable, complete all no-hardware stages, leave the ledger
  at the exact hardware gate and report the concrete blocker.

## Completion

Complete only when Stage 7 produces a tracked final report, roadmap/readiness
documents agree, all referenced artifacts validate, and the final confirmed DAC
code is recorded and left static.
