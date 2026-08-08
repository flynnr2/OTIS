# Stage 2 Prompt: Relative-Phase Estimator and Replay

Execute Stage 2 after the Stage 1 contracts pass. This is host-only and
non-actionable.

## Goal

Implement a simple, replayable phase/frequency state that exposes useful
relative phase movement without implying UTC, absolute epoch or lock.

## Required raw estimator

Implement the master's cumulative edge-error convention exactly. Preserve each
accepted interval and produce a phase record with:

- phase epoch and observation sequence;
- opening/closing snapshot and reference identities;
- interval edge count and signed edge error;
- cumulative relative phase in cycles and nanoseconds;
- capture session, DAC epoch and qualification state;
- discontinuity/invalidation reason;
- observation age;
- raw/derived method and configuration hashes;
- calibrated uncertainty explicitly unavailable unless independently supplied.

Start a new phase epoch after session change, reset, unbridgeable reference or
snapshot discontinuity. Do not join epochs by guessing an offset. Preserve a
detected phase step as an event in the current epoch while continuity remains
valid. Preserve raw cumulative phase across a healthy DAC epoch; filters may
reset or reseed only as declared and must retain the raw phase source.

## Candidate estimators

Implement and compare at least:

1. exact raw accumulator plus the existing 600 s authoritative frequency
   estimate;
2. rolling linear phase/frequency regression over predeclared windows;
3. a simple alpha-beta phase/frequency tracker with fixed gains.

These are candidates, not a requirement to select a sophisticated estimator.
Prefer the simplest candidate that preserves phase steps, estimates frequency
usefully, rejects faults cleanly and replays exactly.

Freeze candidate parameters before evaluating the live Stage 4 record. Do not
tune against the eventual live result and then call that result independent.

## Replay corpus

Replay, without modifying sources:

- Phase 5 pseudo-PPS clean and fault campaigns;
- Phase 5 real-GPS short, extended and overnight campaigns;
- CX317 Stage 3 fixed-code evidence;
- Campaigns A and B;
- Stage 6 dual-core evidence;
- every Stage 7 Part A/Part B attempt with adequate raw inputs;
- the sealed Stage 7B endurance run.

Preserve missing-source cases explicitly; do not manufacture phase records for
legacy runs that lack sufficient snapshot continuity.

## Mandatory synthetic cases

Test:

- exact nominal frequency and zero phase movement;
- constant positive/negative frequency offset;
- counter wrap;
- one-cycle and multi-cycle phase steps;
- phase ramp and frequency drift;
- alternating boundary quantization;
- missing/duplicate/short/long PPS;
- snapshot gap, association mismatch and session restart;
- DAC epoch transition, raw-phase continuity and fresh requalification;
- GNSS invalid/stale/recovery;
- long reference loss and return;
- malformed and reordered inputs;
- deterministic repeated replay.

Each sign test must prove that positive accumulated phase produces the expected
negative corrective frequency direction in later preview calculations.

## Selection metrics

Report:

- exact raw-reconstruction parity;
- phase-step preservation and recovery;
- frequency bias/error versus the existing 600 s estimator;
- residual RMS, range and temporal structure by phase epoch;
- lag and response to injected changes;
- sensitivity to candidate parameters;
- false continuity and false recovery counts;
- code/complexity and replay determinism.

Do not optimize only RMS by fitting away real phase movement.

## Deliverables and exit gate

Deliver host implementation, schemas/profiles, fixtures, replay artifacts,
candidate comparison, selected estimator identity and Stage 2 report.

Pass only if the selected estimator is exact at the raw boundary, deterministic,
fail-closed across discontinuities, explicit about epoch/uncertainty and better
than the raw accumulator only where the improvement is explainable.
