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
implemented with bounded resources and an independent loss path.

## Timing fabric

One PIO state machine continuously counts D8 and snapshots its cumulative
counter when it recognizes D14 high after low. Core 1's bounded FIFO interrupt
drains immutable words into a software ring. There is no independent D14 GPIO
ISR or DMA transport. REF and SNP represent the same session and source ordinal;
REF's RP2040 timer coordinate is observed after the FIFO read, not latched at
the physical D14 edge. The last known-empty FIFO observation supplies a
conservative recognition bracket. See [single reference owner](SINGLE_REFERENCE_OWNER_REPAIR.md).

Adjacent valid raw snapshots produce canonical count intervals. The common
selector separately qualifies accepted spans using the complete recognition
bracket. CPU scheduling, USB, logging and host service never define or improve
the PIO count aperture. Delayed service can widen qualification uncertainty or
exhaust transport; it cannot rewrite a retained count.

The canonical raw D14 timestamp and D8 snapshot remain separate from every
derived interval, estimate, phase value, and regulation decision. Counter
domain, width, rollover, sequence, and capture-session identity travel with the
records needed to reconstruct them.

Offline selected-frequency replay first associates raw D14 REF records with
the declared cumulative-snapshot backend, then reconstructs each same-session
CNT as `(previous_X - current_X) mod 2^32`. Endpoints, sequence/order and
observable exclusion flags must agree before a count may support an estimate.
A plausible CNT or matching EST cannot override inconsistent raw snapshots.
The current emitted oscillator source domain is `h1_oscillator_10mhz`; current
manifest generators declare that exact domain, with no retired alias.

This raw-pair check proves retained arithmetic and association, not physical
capture completeness. Unassociated terminal references remain visible, and
missing or ambiguous pairs cannot enter selected estimates. The simulated
operational rehearsal exercises a real raw anchor/pair fixture but does not
claim to exercise a physical 600-aperture estimator producer.

## Core ownership

| Core | Responsibility |
|---|---|
| Core 1 | D14/D8 FIFO/ring service, acceptance, estimation and regulation state |
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
`SINGLE_REFERENCE_OWNER_REPAIR.md`, and
`COUNT_OBSERVATION_MEASUREMENT_CONTRACT.md` for the detailed D14/D8 contracts.

The [current capture assessment](PPS_CAPTURE_CURRENT_ASSESSMENT_2026_09_19.md)
separates the D8-dependent delay before D14 recognition from the fixed one-clock
recognition-to-X-copy path. Its conditional synchronized-input bound does not
provide a hardware timer marker or change raw SNP/REF or LAT availability.
