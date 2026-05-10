# Timestamping Model

OTIS timestamps are hardware-derived observations within explicit reference
domains.

## Timestamp Semantics

A valid timestamp must include:
- captured event;
- reference domain;
- capture mechanism;
- counter state;
- schema version.

## Deterministic Capture

Capture should occur in hardware before:
- interrupt service;
- buffering;
- telemetry formatting.

## Cross-Domain Semantics

Cross-domain comparisons require:
- explicit transforms;
- synchronization assumptions;
- uncertainty acknowledgment.

## Raw vs Derived Time

OTIS distinguishes between:
- raw captured counts;
- transformed/adjusted timestamps;
- estimated phase/frequency values.

Raw observations should always remain available.
