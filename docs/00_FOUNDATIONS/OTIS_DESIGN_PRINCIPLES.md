# OTIS Design Principles

## 1. Reference-Centric Timing

All timing events are measured against an explicit reference domain.

A timestamp without an associated reference domain is incomplete.

## 2. Deterministic Capture

The CPU may observe timing events, but it must not create their time.

Hardware capture mechanisms should establish timing truth independently of:
- interrupt latency;
- scheduling jitter;
- logging activity;
- UI/network activity.

## 3. Raw Telemetry Preservation

Raw timing telemetry is a primary scientific artifact.

Derived values must not overwrite or obscure raw observations.

## 4. Component Quality Does Not Define Architecture

Lower-quality parts reduce absolute metrological authority, not architectural
validity.

A system built with an inexpensive GNSS module or TCXO should preserve the same
capture, provenance, replay, and analysis semantics as a system built with a
timing-grade receiver and OCXO.

Component quality affects uncertainty, noise floor, holdover, lock robustness,
and confidence in final timing claims. It must not affect the meaning of raw
capture records or firmware state.

## 5. Replayability

Logs should permit deterministic offline replay and reconstruction.

Replayability is a first-class architectural goal.

## 6. Provenance

All derived values should carry explicit provenance:
- source reference domain;
- discipline state;
- estimation methodology;
- schema version.

## 7. Explicit Clock Domains

Clock domains must be named and explicit.

Cross-domain comparisons must declare assumptions and transformations.

## 8. Instrumentation First

OTIS prioritizes:
- correctness;
- observability;
- determinism;
- traceability.

It does not optimize primarily for:
- lowest cost;
- minimal firmware;
- consumer UX.

## 9. Architecture Before Implementation

Conceptual architecture must remain distinct from implementation choices.

Examples:
- deterministic capture is architectural;
- RP2040 PIO is an implementation choice.

## 10. Host Isolation

Networking, dashboards, and storage must not compromise timing correctness.

Timing truth belongs to the timing fabric, not the host.

## 11. Scientific Explicitness

Known limitations, assumptions, and unresolved questions should be documented
explicitly.
