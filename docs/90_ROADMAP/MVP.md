# OTIS MVP

The OTIS MVP succeeds if it can:

1. Discipline a 10 MHz reference oscillator to GNSS PPS.
2. Capture external timing events deterministically.
3. Timestamp events against the disciplined reference domain.
4. Emit provenance-rich replayable telemetry.
5. Survive long unattended runs.
6. Produce meaningful stability and phase diagnostics.

The MVP intentionally prioritizes:
- architectural clarity;
- deterministic semantics;
- observability;
- replayability.

It does not initially prioritize:
- extreme metrology performance;
- broad hardware compatibility;
- polished consumer UX.
