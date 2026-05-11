# OTIS MVP Targets

OTIS uses two MVP targets so the immediate build does not get confused with the
later GPSDO instrument goal.

## SW1 Capture MVP

The near-term SW1 MVP succeeds if it can:

1. Capture GNSS PPS edges, generic pulse edges, and oscillator count observations on RP2040-class hardware.
2. Emit canonical `EVT`, `REF`, `CNT`, and `STS` records.
3. Preserve explicit capture domains and provenance.
4. Produce run directories that host tooling can validate, replay, and report on.
5. Keep DAC steering, GPSDO control loops, and application-specific interpretation out of firmware.

## Instrument MVP

The later instrument MVP succeeds if it can:

1. Discipline a 10 MHz reference oscillator to GNSS PPS.
2. Capture external timing events deterministically.
3. Timestamp events against an explicitly defined disciplined or projected reference domain.
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
