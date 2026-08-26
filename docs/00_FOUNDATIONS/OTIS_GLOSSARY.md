# OTIS Glossary

## Reference Domain
A timing domain defined by a specific disciplined or free-running reference source.

## Timing Fabric
The hardware responsible for deterministic counting, capture, and timestamping.

## Deterministic Capture
Hardware-latched timestamp acquisition independent of CPU response latency.

## Provenance
Metadata describing how a timing value was produced.

## Replayability
Ability to reconstruct analysis deterministically from preserved telemetry.

## Discipline Engine
Logic responsible for steering a reference oscillator toward an external reference.

## Reactive Frequency Steering
Bounded discipline from current qualified frequency-error observations without
requiring future-drift prediction or one permanent actuator code.

## Correction Debt
Provenance-bearing fractional actuator demand not yet realized as an integer
DAC-code application.

## Shadow Estimator
A zero-authority estimator whose output is additive evidence and whose failure
cannot invalidate canonical observations or the selected baseline controller.

## Holdover
Operation during temporary absence of the external reference source.

## Raw Telemetry
Uninterpreted measurements captured directly from instrumentation hardware.

## Derived Telemetry
Values computed from raw telemetry through explicitly documented transforms.

## Clock Domain Crossing
Translation or comparison between separate timing domains.
