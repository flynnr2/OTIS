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

## RP2040 Timebase Is Not Timing Truth

The RP2040 timer domain is an implementation and transport timebase unless it is
explicitly promoted by provenance. It may be useful for ordering records,
measuring approximate intervals, detecting rollover, and deriving diagnostics
from captured PPS rows, but it is not the metrological source for events of
interest.

For current H1 captures, host analysis should use REF/PPS observations to
estimate the actual RP2040 tick rate before converting RP2040-gated count
windows to seconds. Reports must preserve that as a derived calibration, not as
raw timestamp truth.

For the planned PPS-gated ratio backend, PPS edges define count-window
boundaries but do not turn `rp2040_timer0` ticks into PPS-domain timestamps.
Firmware should emit the raw oscillator count and the gate boundary ticks in the
declared gate domain. Host analysis may then derive PPS-normalized ratio,
frequency, and ppm from the visible `REF` and `CNT` streams. Those derived
values must remain replayable products rather than replacements for raw `CNT`
fields.

The intended GPSDO/VCOCXO architecture is a parallel timing fabric: pulses of
interest should be stamped in a timer domain derived from the GPSDO'd VCOCXO.
The RP2040 board clock should not be used as the event-stamping timebase for
those pulses merely because it is convenient to read in firmware.

## Reference Signals

OTIS treats PPS, TCXO, OCXO, GPSDO, and oscillator-under-test inputs as observable reference signals.

For the Stage 1 RP2040 MVP, these reference signals enter the timing fabric as observable GPIO/PIO inputs rather than replacing the RP2040 implementation clock.

See `REFERENCE_SIGNAL_MODEL.md`.
