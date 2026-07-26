# OTIS Vision

OTIS exists to create a transparent, reproducible, scientifically serious timing
instrumentation platform.

It is not enough for OTIS to produce a disciplined output. OTIS must preserve the
evidence from which that output was derived, quantify what it believes, diagnose
why that belief may be degraded, and explain every control action.

## Motivation

Many precision timing systems are operationally opaque:

- timing telemetry is under-specified or unavailable;
- provenance and clock-domain assumptions are implicit;
- raw evidence is discarded after filtering;
- lock is presented as a Boolean without uncertainty or reasons;
- diagnostics are treated as debugging output rather than instrument behaviour;
- capture, control, user interface, and networking are tightly coupled.

OTIS addresses these shortcomings with a deterministic, reference-centric,
provenance-preserving architecture.

## Initial identity

OTIS initially targets a canonical timing instrument appliance with:

- an observable, steerable local oscillator;
- deterministic event and reference capture;
- explicit measurement, metrology, diagnostics, and control layers;
- structured, versioned telemetry;
- offline replay and long-run analysis;
- conservative frequency and phase discipline;
- health, uncertainty, and control-eligibility reporting.

## Instrument promise

OTIS should be able to answer:

- What did the hardware observe?
- In which clock domain?
- What estimates were derived, with what uncertainty?
- Which evidence was rejected, and why?
- What is healthy, degraded, stale, or unresolved?
- Why was control permitted or inhibited?
- Why did the DAC move, and was the requested movement applied?

## Long-term direction

OTIS may evolve into a broader instrumentation ecosystem with interchangeable
timing fabrics, oscillator and reference adapters, distributed timing sources,
advanced metrology, and multiple applications. Modularity must not compromise
semantic rigor, raw provenance, or control safety.

The immediate project remains a concrete, working GPSDO and timing-lab platform.
Future abstractions should be extracted from demonstrated hardware and software
experience rather than designed prematurely.

## Intended audience

Primary audiences include precision timing researchers, Time-Nuts community
members, horological instrumentation researchers, RF and oscillator
experimenters, and scientific instrumentation engineers.

OTIS documentation aims for serious but readable scientific engineering,
explicit assumptions and limitations, reproducible methodology, and honest
statements of confidence.
