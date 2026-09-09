# RP2040 Capture Architecture

Current HEAD implements one fixed capture and regulation topology. There is no
capture-backend selector, bring-up mode, or alternate firmware profile.

## Authority and channel roles

| Signal | Pin/channel | Role |
|---|---|---|
| D14 | GPIO26 / CH1 | sole authoritative PPS/reference input |
| D8 | GPIO20 / CH2 | sole oscillator/count input used by regulation |
| D10 | GPIO5 / CH0 | reserved external-event evidence; capture not implemented |
| D9 | GPIO21 | forwarded oscillator output; no timing or control authority |
| D6 | GPIO18 / CH3 | fail-local forwarded-output monitor; no control authority |

D10 is not a PPS witness. Its absence, noise, invalidity, or overflow cannot
affect D14/D8 validity, setup authority, regulation eligibility, actuation, or
a run terminal. The pin/channel and host `EVT` contract are retained, but the
firmware deliberately makes no isolation claim until a D10 capture path can be
implemented without sharing D14's singleton GPIO interrupt/ring ownership.

## Timing fabric

D14 reference edges are captured through the dedicated reference IRQ path and
timestamped in the RP2040 monotonic-microsecond domain. D8 is continuously
counted by the PIO snapshot programme; D14 snapshots its cumulative counter,
and DMA transports the hardware observations. Adjacent qualified snapshots
produce canonical count intervals. CPU scheduling, USB, logging, and host
service never define the physical count aperture.

The canonical raw D14 timestamp and D8 snapshot remain separate from every
derived interval, estimate, phase value, and regulation decision. Counter
domain, width, rollover, sequence, and capture-session identity travel with the
records needed to reconstruct them.

## Core ownership

| Core | Responsibility |
|---|---|
| Core 1 | D14/D8 timing capture, DMA/ring service, estimation and regulation state |
| Core 0 | sole serial owner, GNSS metadata/configuration, environment service, status emission, and physical DAC I2C execution |

Bounded immutable queues are the only cross-core handoff. Capture producers are
serviced even when no host carrier is attached. Requested/applied DAC codes,
acknowledgements, DAC epochs, and the first dependent decision retain exact
identity across the boundary.

## Diagnostic sidecars

D9 forwarding and the D6 cumulative snapshot monitor are always present. D6
uses its own fail-local queue and cannot backpressure or veto D14/D8. D6
evidence can diagnose forwarded-output continuity but does not qualify analog
waveform shape, jitter, loading, or independent frequency.

GNSS serial metadata qualifies the receiver that supplies D14 PPS but never
replaces D14 timing. A recoverable metadata anomaly holds new corrections at
the last confirmed DAC code while D14/D8 capture and canonical evidence
continue.

## Loss and failure semantics

Every queue or capture layer reports loss at the boundary that can observe it.
A D14/D8 discontinuity invalidates only the affected timing frontier and may
hold or fail static according to the fixed policy. D6 and future D10 faults
remain local. Missing, duplicated, partial, late, or out-of-order records are
never interpreted as zero or clean.

See `PPS_OWNERSHIP_ARCHITECTURE.md`,
`PPS_GATED_RATIO_BACKEND_DESIGN.md`, and
`COUNT_OBSERVATION_MEASUREMENT_CONTRACT.md` for the detailed D14/D8 contracts.
