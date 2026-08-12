# Telemetry Philosophy

OTIS telemetry is a versioned scientific record of what the instrument observed,
what it inferred, what it diagnosed, and what it did.

Telemetry is transport and representation. It must preserve the distinction
between measurement, metrology, diagnostics, state, control, context, provenance,
and host operations.

## Goals

Telemetry should support replayability, offline reconstruction, long-run
analysis, provenance tracking, reproducible experimentation, fault isolation,
uncertainty reporting, and explanation of every control action.

## Raw first

Canonical observations are preserved before filtering or interpretation. Derived
records may reject or annotate observations but must never overwrite or obscure
them.

## Explainability

A complete run should permit reconstruction of:

- accepted and rejected source observations;
- frequency, phase, drift, and uncertainty estimates;
- active diagnostic findings and reason codes;
- control eligibility and inhibition;
- requested and applied actuator changes;
- configuration, policy, algorithm, and plant-model versions.

## Append-only and transitions

Logs should be append-only wherever practical. Important state changes, faults,
source changes, arming/disarming, and recovery events should be explicit records,
not inferred only from periodic snapshots.

## Schema versioning

Schemas evolve explicitly and conservatively. Breaking changes are versioned.
Unknown fields remain unknown rather than being represented as plausible zeros.

## Human and machine readability

Telemetry should support automated tooling, direct inspection, and long-term
archival. CSV and structured machine formats may coexist when their semantics are
identical and documented.

## Capacity and failure

Timing observations, actuator acknowledgements, critical diagnostic transitions,
and control actions must not be silently lost. Droppable routine snapshots must
have explicit counters. Transport or host failure must not alter timing truth and
must be visible in later replay.

For the supported carrier-dependent generation, absence beyond the declared
2,000 ms TX-progress horizon invalidates evidence continuity even though it
does not redefine already captured timestamps. The partial frame and drained
post-fault queues are not durable evidence. Reset/new session is required.

Command phases use distinct names: host byte completion is `host_written`;
device records distinguish receive, each authority decision, physical
application or failure, and the subsequent observed result. These meanings
must never be collapsed into “command acknowledged.”
