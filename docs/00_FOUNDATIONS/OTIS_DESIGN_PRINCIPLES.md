# OTIS Design Principles

## OTIS North Star

OTIS is a provenance-preserving timing instrument.

Its primary purpose is not merely to generate accurate time or frequency, but to
capture, discipline, reconstruct, and analyze timing behavior in a way that
remains observable, auditable, replayable, and evolvable over time.

OTIS should be understood as a sacred timestamp appliance with forensic-grade
observability. It is not primarily trying to be the most accurate possible DIY
GPSDO, a feature-rich timing appliance, a black-box autonomous controller, or a
"Kalman everything" experiment.

This framing has concrete design consequences:

- timing capture paths are sacred and must not be contaminated by UI, logging,
  WiFi, dashboards, storage, or other service work;
- timing domains are explicit, named, and preserved across firmware, telemetry,
  host tooling, and analysis;
- canonical raw telemetry is captured before derived interpretation, and raw
  records remain authoritative after later reconstruction;
- hardware boundaries are modular enough that GPS/GNSS modules, DACs,
  TCXO/OCXO/VCOCXO parts, buffers, level shifters, and related front-end
  components can be upgraded or swapped without disturbing the core timing
  architecture;
- deterministic capture, replayability, and offline reconstruction are
  first-class requirements, not debugging conveniences;
- estimator, discipline, control-loop, and holdover outputs carry provenance
  that identifies their source observations, assumptions, and methodology;
- control evolves in stages: observe, characterize, replay, estimate,
  discipline, then holdover;
- hardware substitutions are treated as experiments: explicit, documented, and
  comparable through telemetry, configuration, manifests, and analysis metadata;
- host-side analysis may reinterpret historical runs as models improve, without
  rewriting what the instrument originally observed;
- engineering choices should be explicit over clever, especially where ambiguity
  could weaken trust in captured timing evidence.

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

## 12. Future Abstraction From Experience

OTIS is intentionally proceeding as a concrete, working modular GPSDO /
timing-lab platform before attempting to extract a general timing framework. The
project should remain focused on completing the current roadmap: hardware
bring-up, characterization, control-loop implementation, long-run validation,
and operational observability. Future abstraction is a design consideration, not
a current deliverable.

If, after OTIS has produced real hardware results and mature firmware/data
pipelines, common timing primitives emerge, they may be extracted into a
reusable timing core. At that point, OTIS, a Stratum-1 time-server application,
oscillator characterization rigs, or other timing tools could become sibling
applications built on top of that core. GNSSTimeServer is an illustrative future
comparison point for this kind of sibling application model, not a dependency or
committed integration target.

Until then, the project should avoid premature generalization and should not
disrupt the current roadmap in pursuit of framework design.

Principle: design for future abstraction, but only abstract from experience.
