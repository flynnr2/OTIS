# Timestamping Model

OTIS timestamps are hardware-derived observations within explicit capture domains.

A timestamp is not merely a number. It is a claim about:

- what was captured;
- where the capture occurred;
- how the capture was derived;
- which timing domain produced the captured ticks;
- and what provenance accompanies the observation.

## Timestamp Semantics

A valid timestamp should include or imply:

- captured event identity;
- capture domain;
- capture mechanism;
- counter/tick state;
- schema version;
- provenance context.

## Deterministic Capture

Capture should occur in hardware before:

- interrupt service;
- buffering;
- telemetry formatting;
- host transport.

The timing-critical capture path should remain as small and deterministic as practical.

## Raw vs Derived Time

OTIS distinguishes between:

- raw captured counts;
- reconstructed timestamps;
- transformed or adjusted timestamps;
- estimated phase/frequency values;
- disciplined or projected domains.

Raw observations should remain available whenever practical.

## Capture Domain Semantics

`capture_domain` names the native timing domain in which `timestamp_ticks` were latched.

It is not automatically:

- UTC;
- the GNSS domain;
- the oscillator-under-test domain;
- or a host-reconstructed timeline.

A TCXO pulse train captured by an RP2040 PIO program may still produce timestamps in the local RP2040 capture domain.

## Cross-Domain Semantics

Cross-domain comparisons require:

- explicit transforms;
- synchronization assumptions;
- provenance;
- uncertainty acknowledgment.

Host-side analysis may construct:

- PPS-aligned domains;
- disciplined domains;
- UTC projections;
- oscillator-relative domains;
- synthetic comparison domains.

Those transforms should remain explicit and replayable.

## Reference Signals

OTIS treats PPS, TCXO, OCXO, GPSDO, and oscillator-under-test inputs as observable reference signals.

For the Stage 1 RP2040 MVP, these reference signals enter the timing fabric as observable GPIO/PIO inputs rather than replacing the RP2040 implementation clock.

See `REFERENCE_SIGNAL_MODEL.md`.
