# Timestamping Model

OTIS timestamp values belong to explicit clock domains. Their provenance states
whether hardware latched the event or software merely observed and labelled it.

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

## RP2040 Local Coordinate Is Not Metrology Time

`rp2040_monotonic_us32` is the native 1 MHz, wrapping microsecond coordinate
from `micros()`/`timerawl`; `rp2040_monotonic_us64` is its session-bound
non-wrapping reconstruction. They are RP2040-local implementation coordinates.
They are useful for ordering records, deadlines, telemetry, rollover handling,
and diagnostics, but they are not metrological event time.

For current H1 captures, host analysis should use REF/PPS observations to
estimate the actual RP2040 tick rate before converting RP2040-gated count
windows to seconds. Reports must preserve that as a derived calibration, not as
raw timestamp truth.

For the planned PPS-gated ratio backend, PPS edges define count-window
boundaries but do not turn `rp2040_monotonic_us32` ticks into PPS-domain timestamps.
Firmware should emit the raw oscillator count and the gate boundary ticks in the
declared gate domain. Host analysis may then derive PPS-normalized ratio,
frequency, and ppm from the visible `REF` and `CNT` streams. Those derived
values must remain replayable products rather than replacements for raw `CNT`
fields.

The metrology fabric is separate. D14 is the sole authoritative PPS/reference
input. D8 is the sole authoritative oscillator/count input, currently the
10 MHz VCOCXO that D14 disciplines. D10 is the external event input and must be
hardware-captured against a versioned D8-derived domain. Environmental samples
may retain a raw local acquisition timestamp and later be projected into that
metrology domain with stated acquisition latency and uncertainty. Neither
projection nor local ordering may overwrite the raw observations.

## Reference Signals

OTIS treats PPS, TCXO, OCXO, GPSDO, and oscillator-under-test inputs as observable reference signals.

For the Stage 1 RP2040 MVP, these reference signals enter the timing fabric as observable GPIO/PIO inputs rather than replacing the RP2040 implementation clock.

See `REFERENCE_SIGNAL_MODEL.md`.
