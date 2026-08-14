# Codex Programme: Bounded Hybrid Phase/Frequency Control

## Status and authority

Status: draft programme; offline preparation only.

This document grants no phase-derived, hybrid-derived or other new DAC
authority. An instruction to execute it authorizes evidence review, replay,
design, implementation, tests and a non-actionable live-preview proposal only.
Every physical stage requires an exact frozen bundle and explicit operator
authority. The first bounded hybrid actuation and the later sustained active
trial are separate consumed gates.

## Preconditions

Do not select or activate the final controller until:

1. the existing state-preserving fine boundary map has reached a terminal
   result;
2. the range-spanning Part B frequency-only trajectory has passed, or its
   terminal result explicitly identifies the evidence gap that blocks hybrid;
3. matched positive- and negative-direction plant response, settling,
   hysteresis and cadence evidence has been analyzed;
4. the disciplined 10 MHz output programme has reached a terminal qualification
   result for the physical output configuration intended for public use,
   including its frequency-only sustained output soak; and
5. the exact final public configuration has a passing operational-path
   rehearsal with hybrid authority still zero.

The qualified output is a dependency because the active-hybrid programme must
observe the signal users will receive. It is not a new timing authority.
The completed frequency-only output soak is the predeclared baseline for hybrid
comparison. The sustained hybrid trial must reuse the exact qualified output
contract and load configuration, but it confirms integrated behavior rather
than completing output qualification retrospectively.

## Decision-bearing objective

Select, implement and physically qualify one coherent bounded controller that
combines the authoritative slow frequency estimate with a deliberately limited
reference-relative phase contribution, reduces the declared phase-movement
metric, does not materially degrade frequency performance or increase actuator
chatter, and remains exactly replayable through reference loss, recovery,
phase-step, DAC-epoch and service-plane faults.

The initial active claim is deliberately narrow:

> bounded control of cumulative D8 oscillator-cycle movement relative to
> qualified D14 PPS within one declared phase epoch.

It is not UTC alignment, calibrated absolute phase, cable-delay compensation,
traceable accuracy, a generated PPS, or predictive holdover.

## Established evidence and limitations

The existing selected preview is a baseline candidate, not standing authority:

- candidate `p21600_cap1_v2`;
- nominal phase pull-in time 21,600 seconds;
- absolute phase-bias cap `1/600 Hz`;
- historical V2 frequency-band policy;
- selected from modeled counterfactual replay, not active hybrid observation;
- the tight-hysteretic counterpart was rejected by a prospective repeated-
  alternation guard; and
- every existing phase and hybrid output remains non-actionable.

The selected phase observable is an exact integer accumulator of D8 edge error
across qualified D14 intervals. At nominal 10 MHz one cycle is 100 ns. Phase
zero is arbitrary at the first qualified boundary of each phase epoch,
calibrated uncertainty is unavailable, and epochs may not be joined by guessed
offsets.

The latest range-survey prefix retained continuous hybrid preview and coherent
DAC epochs, but manual setup transitions repeatedly reseeded the shadow code.
Those modeled corrections are diagnostic evidence, not observed hybrid plant
response.

Bind these facts from the current tracked profiles and final range-spanning
evidence. Never copy an old result into a new profile without verifying its
source identity and applicability.

## Control requirements

The selected controller must have:

- one coherent output and one explicit authority path;
- separately recorded frequency term, phase term, combined requested change,
  limits and final requested DAC delta;
- frequency-dominant acquisition followed by a bumpless transition to hybrid
  tracking;
- a predeclared phase metric, sign convention and epoch rule;
- bounded phase contribution, step, code range, cadence, correction count and
  cumulative movement;
- explicit anti-windup and reseed behavior;
- hysteretic state transitions and minimum dwell;
- phase-step detection and hold behavior that does not infer a step from one
  quantized interval;
- fail-static reference-loss behavior;
- fresh D14/D8 and DAC-epoch requalification before recovery;
- no automatic restoration write;
- exact request, authorization, acceptance, application, response and budget
  provenance; and
- host/firmware parity through the first applied decision and subsequent
  response classification.

The proposal may tighten the established `0xA800..0xAB00` hard range and
existing frequency-control budgets. It may not widen them merely to make a
hybrid candidate pass. Any phase cap or cadence more aggressive than the
existing preview must be separately justified by the new bidirectional
evidence before physical entry.

## Stage 1: evidence handoff and phase contract

Create a new descriptive programme ledger under a run path such as
`runs/hybrid_phase_frequency_control/<programme_start_UTC>/`.

Freeze:

- final Part A transition intervals and hysteresis evidence;
- final Part B positive/negative response, settling and cadence evidence;
- disciplined-output contract, load, waveform result and frequency-only soak;
- GNSS receiver and D14 qualification contract;
- D8 snapshot, frequency-estimator and relative-phase contracts;
- plant model and gain envelope;
- DAC transaction and response-classification contracts;
- phase sign, zero, epoch, unit, continuity and invalidation semantics;
- public claims and explicit non-claims; and
- the exact decision metrics used to select a controller.

State whether the controlled metric is cumulative oscillator-cycle movement,
an output-edge phase residual, or another precisely observed quantity. If the
metric changes from the existing integer accumulator, treat it as a new
metrology programme rather than silently reusing the old controller.

## Stage 2: candidate replay and selection

Re-evaluate the existing selected candidate and a small finite set of justified
alternatives against all applicable immutable evidence, especially the new
range-spanning Part A and Part B results.

Predeclare comparison metrics for:

- phase movement and maximum excursion within each continuous phase epoch;
- 600-second frequency residual RMS, tails and deadband occupancy;
- acquisition and hybrid-entry latency;
- correction count, path length, net movement and efficiency;
- direction reversals, repeated alternation and chatter;
- step, range, phase-cap and cumulative-budget pressure;
- sensitivity to the measured plant-gain envelope;
- output D9 behavior where waveform evidence is available;
- reference loss, recovery, phase step and DAC-epoch transitions; and
- exact deterministic replay.

Do not select on modeled phase improvement alone. Reject candidates that
improve phase only by materially degrading frequency, consuming excessive DAC
path, oscillating across quantized boundaries, depending on guessed epoch
offsets, or requiring unavailable uncertainty.

Select one candidate and freeze all parameters before the new live preview.
Retain rejected candidates and reasons as diagnostic evidence.

## Stage 3: implementation, parity and fault rehearsal

Implement the selected controller first with structural zero authority.

Required separation:

- estimator and pure controller code have no serial, Wire/I2C or DAC-driver
  dependency;
- the selected controller produces a proposed bounded request only;
- the existing two-core authority and transaction path remains the sole route
  to physical DAC application;
- no second phase actuator, integrator or hidden correction path exists; and
- output generation and motion/environment telemetry cannot bypass eligibility
  or mutate controller state.

Add host/firmware parity fixtures for nominal acquisition, both correction
directions, zero phase, constant phase ramp, quantization alternation, gain
limits, phase cap, step/range clamps, anti-windup, DAC-epoch reseed, phase step,
reference loss/return, stale GNSS metadata, snapshot discontinuity, queue
obstruction, abort and terminal fault.

For every case compare the complete decision state, reason, terms, limits,
budget state and authority fields. Test the producer, cross-core handoff,
actuator request consumer and first response classifier; a pure-engine unit
test alone is insufficient.

Run Fast, Campaign and affected Release verification plus all current supported
firmware profiles and expected-failure guards whose shared control, protocol,
resource or evidence semantics changed.

## Stage 4: exact zero-authority live preview

Prepare a finite exact-bundle preview using:

- the final disciplined-output configuration and declared load;
- the selected hybrid candidate and exact hashes;
- representative environmental/service traffic;
- continuous capture and sole serial ownership;
- real D14/D8 measurements and D9 observation; and
- phase/hybrid actionability and actuation authority fixed false in firmware,
  host supervision, replay and analysis.

The preview must cover at least one complete 21,600-second interval if the
existing six-hour pull-in candidate remains selected, plus enough subsequent
time to observe its proposed hybrid-tracking behavior. Use a different finite
duration only when the newly selected controller and evidence justify it before
the run.

Pass only if the candidate chooses defensible directions, crosses states
bumplessly, respects every budget, avoids chatter/fault, replays exactly, and
prospectively improves phase without material frequency degradation. Preserve
all modeled outputs as modeled and all actual applied codes as actual.

## Stage 5: first bounded active-hybrid transaction gate

This stage requires separate explicit operator authority after the preview is
sealed and reviewed.

Freeze an authority envelope no broader than needed to observe the first
phase-influenced physical response. It must state:

- exact starting code and its evidence provenance;
- selected estimate and phase-observation identities;
- maximum phase contribution and combined step;
- maximum automatic corrections and cumulative movement;
- minimum cadence and settling/fresh-support rule;
- hard code range;
- qualification and authority lifetime;
- independent abort path and terminal-clear requirement;
- required D9 waveform/load monitoring; and
- pass, non-pass and fail-static stop conditions.

A pass requires at least one complete request-to-response transaction in which
the phase term materially and correctly influences the combined request, the
firmware and host replay agree exactly, and the observed response has the
expected sign without violating frequency or waveform limits. A zero-transaction
run may be useful evidence but cannot pass this gate.

Seal and review this result before proposing sustained authority.

## Stage 6: sustained active-hybrid qualification

After the first transaction gate passes, prepare a separately authorized
sustained finite run. For the current six-hour pull-in design, use a 24-hour
qualified interval unless the Stage 2 selection freezes another evidence-based
duration. Do not extend a live run after seeing the result merely to rescue a
hypothesis.

Exercise:

- frequency-dominant acquisition;
- bumpless entry into hybrid tracking;
- sustained phase/frequency behavior;
- both naturally occurring correction directions if available, without
  manufacturing an unapproved setup stimulus;
- D9 output under its qualified load;
- representative environment and service traffic;
- finite reference-loss and recovery rehearsal through the actual supervision
  and abort path; and
- clean disarm, analysis, replay, sealing and registration.

If a physical reference interruption is not authorized, use deterministic
fault injection for the missing boundary and state exactly what remains
unexercised. Fail-static retention of the last confirmed safe DAC code is the
initial reference-loss behavior. Do not claim predictive holdover.

## Acceptance criteria

Freeze numerical materiality thresholds before physical entry. At minimum a
pass requires:

- observed improvement in the declared reference-relative phase metric over a
  matched frequency-only baseline or another predeclared comparison;
- no material degradation of the authoritative frequency metric;
- no unexpected phase/frequency sign disagreement;
- no repeated alternation, uncontrolled reversal, chatter or low-efficiency
  path fault;
- every step, range, cadence, count and cumulative budget respected;
- exact transaction and host/firmware replay;
- healthy D14/D8 capture, GNSS qualification, D9 output and actuator response;
- zero unexplained queue, transport, parsing or evidence loss;
- deterministic fail-static reference-loss behavior and bounded recovery; and
- a terminal static code with no outstanding request or latent authority.

## Terminal decisions

Choose exactly one:

- `bounded_active_hybrid_control_passed`;
- `hybrid_preview_passed_active_response_not_demonstrated`;
- `phase_metric_or_estimator_requires_revision`;
- `hybrid_policy_requires_revision`;
- `frequency_or_output_performance_materially_degraded`;
- `actuator_response_or_budget_failed`;
- `measurement_authority_or_platform_fault`; or
- `operator_abort`.

## Required deliverables

- frozen phase/estimator/controller/output contracts and identities;
- complete candidate comparison and selected policy;
- pure firmware engine plus host replay parity;
- authority-preserving live integration and telemetry;
- zero-authority preview package and seal;
- first active-transaction package and seal if separately authorized;
- sustained active-hybrid package and seal if separately authorized;
- tracked final report under `docs/60_EXPERIMENTS/`;
- updated roadmap, readiness, terminology, control and known-limitations docs;
  and
- concise public claim language distinguishing frequency discipline,
  reference-relative phase control, output delivery, UTC, traceability and
  holdover.

Stop after each authority boundary. A passing preview is a reason to propose a
bounded active gate, not permission to actuate.
