# Stage 2 Prompt: GNSS and Actuator Preflight

Execute Stage 2 after the Stage 1 baseline passes. This stage may perform only
predetermined manual/open-loop DAC writes. It may not issue a feedback-derived
correction.

## Goal

Qualify the obvious health of the PPS source and present actuator topology
without turning calibration gaps into a long observe-only programme.

## Part A: read-only GNSS metadata

Implement a bounded, allocation-free or statically bounded receiver service
for GPS TX to Nano RX.

Requirements:

- explicitly claim the UART pins and peripheral in the resource registry;
- verify the Nano/Philhower `Serial1` pin mapping on the actual board;
- read only during this programme; Nano TX to GPS RX must remain silent;
- validate NMEA checksum and parse at least RMC and GGA equivalents;
- emit receiver identity/configuration when available, RMC validity, GGA fix
  quality, UTC/date availability, satellite count, HDOP if supplied, message
  age, checksum failures, parser drops and a receiver identity epoch;
- use fixed line length, byte budget and per-service-call work limit;
- preserve raw PPS capture independently;
- associate fresh receiver metadata with PPS/control eligibility without
  treating UART arrival time as the PPS timestamp;
- invalidate control eligibility on invalid/stale fix metadata while continuing
  raw capture and diagnostic telemetry;
- add deterministic fixtures for checksum failure, truncated/oversize input,
  stale metadata, fix loss/return, UTC invalid, reconnect and message-order
  variation.

Observe the actual module long enough to freeze an evidence-backed metadata
freshness limit. Prefer a few minutes covering multiple valid RMC/GGA epochs;
do not turn this into an overnight test.

The minimum active-control reference gate is a current valid receiver fix,
fresh checksum-valid metadata, healthy raw PPS cadence and unchanged receiver
identity. This is an operational qualification gate, not UTC traceability or a
calibrated PPS-accuracy claim.

## Part B: present-topology actuator sanity

With the dedicated manual path, capture owner and abort path active:

1. query and record the live firmware/build/backend/resource identity;
2. obtain one exact applied-code acknowledgement establishing the initial
   state;
3. execute the predetermined manual points `0xA800`, `0xA950`, `0xAB00`, then
   return to `0xA950` under healthy conditions;
4. at each point, allow the operator to record connected Vc with the available
   instrument and its identity; treat this as a practical wiring/monotonicity
   screen unless calibration uncertainty is genuinely available;
5. confirm requested = accepted = applied, clamp false, I2C success and no
   additional DAC write;
6. retain PPS/count/temperature health throughout.

If a suitable oscilloscope is available, record D8 low/high levels, duty,
rise/fall time and margin at the three points. If it is unavailable, record the
physical-margin limitation and continue only if all digital observations are
clean. Lack of a scope blocks a physical-margin claim, not automatically the
bounded code-domain campaign.

Any non-monotonic, implausible or unsafe connected voltage, abnormal waveform,
count fault, acknowledgement mismatch or I2C fault blocks active progression.

## Part C: live GNSS/load smoke

At static `0xA950`, run a bounded smoke interval with normal receiver parsing
and one deliberate telemetry/USB load segment. Confirm:

- no raw observation loss;
- no receiver-parser starvation;
- no estimator contamination;
- no DAC command;
- receiver metadata loss correctly inhibits eligibility and recovery requires
  fresh data.

## Deliverables and exit gate

Deliver receiver contracts/fixtures, a dedicated non-actuating GNSS smoke
profile, sealed short evidence, voltage/waveform observations, and a Stage 2
report.

Pass if GNSS metadata reliably qualifies the PPS source, actuator
acknowledgements are exact, the present topology passes practical safety and
monotonicity checks, and the rig ends at confirmed `0xA950` with active
authority false.
