# Codex Programme: Board Motion Telemetry

## Status and authority

Status: draft programme; offline preparation only.

This programme is independently promotable and non-blocking for the first
public OTIS release. It grants no authority to disturb the current preserved
range-survey state, flash, reset, access the serial device or perform a physical
sensor test. Offline design and fixtures may proceed while the current board
state is preserved.

Motion telemetry has zero timing, reference, diagnostic-gate or control
authority throughout this programme. A future use in compensation or control
would require a separate metrology and active-control programme.

## Decision-bearing objective

Determine whether the Nano RP2040 Connect's onboard LSM6DSOX accelerometer and
gyroscope can provide useful, replayable board-motion context at a bounded data
rate without delaying DAC I2C transactions, stalling Core 1, degrading timing
capture, causing transport loss, or being misrepresented as calibrated
oscillator-vibration evidence.

## Established factual basis

- The onboard LSM6DSOX provides three-axis acceleration and three-axis angular
  rate measurements.
- The board datasheet declares selectable accelerometer ranges of
  `+/-2/4/8/16 g` and gyroscope ranges of
  `+/-125/250/500/1000/2000 dps`.
- The sensor shares I2C0 on GPIO12/GPIO13 with OTIS's AD5693R, SHT4x and BMP280
  clients.
- The schematic ties the LSM6DSOX interrupt output `INT1` to RP2040 GPIO24 and
  appears to select the high `SDO/SA0` address, implying expected I2C address
  `0x6B`. Firmware must confirm identity and address on the actual board rather
  than assuming them.
- OTIS assigns sensor I2C, formatting and transport to Core 0. Core 1 owns
  capture, estimation and control and must remain independent of sensor polling.
- Existing environmental telemetry is sampled context, not a timing-fabric
  event. Motion data belongs at the same architectural layer but needs its own
  schema because its axes, sampling and loss semantics differ.

Use the local sources in:

- `docs/datasheets/ABX00053-datasheet.pdf`;
- `docs/datasheets/ABX00053-schematics.pdf`;
- `docs/datasheets/ABX00053-full-pinout.pdf`;
- `docs/10_REFERENCE_ARCHITECTURE/CORE_PARTITIONING.md`;
- `docs/20_TELEMETRY/TELEMETRY_PHILOSOPHY.md`; and
- `docs/20_TELEMETRY/ENVIRONMENTAL_TELEMETRY.md`.

## Semantic boundary

Call this `board motion telemetry`, not vibration metrology.

The sensor observes motion and orientation of the Nano board at its own package
location. It does not automatically measure motion of the steerable-oscillator package,
enclosure, antenna or output connector. Any relationship depends on documented
mechanical coupling and finite evidence.

The RP2040 time at which firmware reads or receives a sample is not necessarily
the physical sample instant. The telemetry contract must declare whether time
is a host/service read time, interrupt-observation time, FIFO sample time or
sensor timestamp, and preserve the associated age and uncertainty semantics.

Do not encode motion samples as `EVT`, `REF`, `CNT` or a numbered timing
channel. A sensor interrupt may be recorded as sensor-service evidence, but it
does not become timing authority merely because a GPIO edge exists.

## Stage 1: board probe, use case and contract freeze

Without changing the physical board until separately authorized, prepare:

1. an exact I2C identity and register-level probe;
2. expected address, `WHO_AM_I`, reset and default-state checks;
3. axis-orientation documentation relative to the Nano board and OTIS assembly;
4. a bounded set of candidate output-data rates, ranges and filters;
5. a decision on polling versus FIFO/INT1 use;
6. a bandwidth and transport budget for each candidate;
7. I2C transaction-time and DAC-priority requirements;
8. sample, missed-sample, FIFO-overrun, I2C-error and telemetry-drop semantics;
   and
9. one versioned `motion_v1` contract and machine-readable profile.

The first useful target is contextual movement/orientation and disturbance
tagging. Do not choose a high data rate merely because the device supports it.
Conversely, do not call a one-hertz stream shock or vibration capture. Compare a
small finite set of modes and select the cheapest one that can answer the stated
use case.

## Required telemetry contract

Preserve at least:

- record and schema version;
- monotonic sample sequence;
- sensor identity and configuration identity;
- observation timestamp and declared timestamp domain;
- timestamp meaning and sample-age status;
- raw accelerometer X/Y/Z readings;
- raw gyroscope X/Y/Z readings;
- scale/range and output-data-rate configuration;
- converted SI or declared engineering-unit values as explicit derived fields,
  without replacing raw readings;
- validity, saturation, stale, FIFO-overrun and I2C-error flags;
- cumulative produced, missed, discarded and transported counts; and
- board-axis orientation/provenance in the manifest.

Host-derived magnitude, tilt, event classification or correlation must remain
derived products. They must identify their transformation and source rows.

## Stage 2: resource-safe firmware implementation

Implement the sensor as a client of the existing `otis_i2c_bus` owner. The new
module must not call `Wire.begin()` independently.

Required constraints:

- all sensor transactions and formatting remain on Core 0;
- no sensor message enters the Core 1 service-to-timing queue unless a later
  separately reviewed diagnostic use requires it;
- the DAC transaction path has explicit priority over motion sampling;
- a motion read may be deferred or dropped with counters; a DAC request may not
  be delayed past its authority or execution deadline;
- every I2C call is bounded and failure-visible;
- sensor reset or reconfiguration cannot reset or disrupt other I2C clients;
- GPIO24 and INT1 are claimed in the resource registry if, and only if, the
  selected mode uses them;
- fixed-size queues and buffers are used, with no timing-path heap allocation;
- ordinary motion telemetry has an explicit bounded loss policy;
- timing observations, actuator acknowledgements and critical faults retain
  priority over motion rows; and
- profiles can compile the IMU completely out for comparison and recovery.

Add boot status for sensor identity, address, ranges, output-data rate, filter,
FIFO/interrupt mode, sample-period semantics, timestamp semantics, queue
capacity and zero control authority.

## Stage 3: host capture, validation and analysis

Add:

- strict wire and CSV parsing;
- a dedicated motion artifact rather than extending `environment_v1` with
  ambiguous empty columns;
- schema validation and manifest declaration;
- sequence, timestamp-domain, configuration, saturation, stale and loss checks;
- capture-device routing and run finalization;
- generic run validation and evidence sealing;
- simple plots or summaries for raw axes and host-derived magnitudes; and
- correlation tooling that preserves the distinction between coincident motion
  and demonstrated causal timing effects.

Missing motion data must remain missing. Do not manufacture zeros or carry the
last sample forward as if it were a new observation.

## Stage 4: deterministic load and fault verification

Before a physical integrated run, test:

- correct identity and sample decoding;
- positive/negative full-scale conversion and saturation;
- axis ordering and units;
- timestamp and sequence rollover behavior from declared domains;
- polling and, if selected, FIFO/INT1 ordering;
- I2C NACK, short read, stale data, sensor reset and recovery;
- FIFO overrun and bounded discard;
- motion-queue saturation and transport obstruction;
- simultaneous environmental sampling and pending DAC transaction;
- DAC priority and deadline preservation;
- Core 1 progress, capture-ring health and control parity under worst selected
  motion traffic; and
- enabled/disabled firmware matrix profiles.

Use deterministic fixtures for sensor faults. The operational rehearsal must
exercise the actual Core 0 scheduling, serial formatting, capture routing,
analyzer, seal and registration path. Do not claim physical I2C or interrupt
behavior from a host-only mock.

## Stage 5: physical sensor characterization

This stage requires separate explicit operator authority after the current
state-sensitive frequency work has released the board.

Run a finite characterization containing:

- stationary noise and bias in the installed orientation;
- several documented static orientations to check sign and axis mapping;
- a small number of deliberate manual movements or taps with marked event
  times;
- the selected sustained sampling mode;
- representative SHT4x/BMP280 traffic;
- at least one bounded DAC transaction or exact transaction rehearsal;
- representative full timing and hybrid-preview telemetry load;
- transport obstruction and recovery; and
- clean analysis, sealing and registration.

Measure actual sample cadence, gaps, I2C duration, queue depth, dropped rows,
serial load and Core 1/timing health. If the sensor is not mechanically coupled
to the oscillator assembly, state that limitation rather than interpreting a
quiet board as a quiet oscillator.

## Stage 6: final integrated-configuration decision

If isolated motion telemetry passes, decide whether it belongs in the first
public firmware. If included, run the final public-configuration operational
rehearsal and sustained timing/control qualification with the exact selected
motion profile enabled. Reuse earlier evidence only where its relevant inputs
are unchanged.

Motion telemetry may be dropped or deferred under service pressure only as the
frozen contract permits and with exact counters. Its absence must not stop
capture or move the DAC. A sensor or bus failure may inhibit the motion product;
it must affect timing/control only if the same failure demonstrably compromises
the shared DAC bus or another explicit control dependency.

## Terminal decisions

Choose exactly one:

- `board_motion_context_telemetry_qualified`;
- `low_rate_context_qualified_high_rate_or_fifo_deferred`;
- `motion_telemetry_useful_but_excluded_from_initial_public_profile`;
- `motion_telemetry_load_or_i2c_interference_unacceptable`;
- `sensor_identity_or_physical_behavior_not_established`;
- `implementation_or_platform_fault`; or
- `operator_abort`.

## Required deliverables

- `motion_v1` contract, schema and profile;
- board axis/orientation note;
- firmware I2C client and optional INT1 resource ownership;
- host capture, validators, artifact routing and summaries;
- deterministic decoding, load, priority and fault tests;
- operational rehearsal report and seal;
- physical characterization package, seal and registration if authorized;
- tracked final report under `docs/60_EXPERIMENTS/`; and
- updated telemetry, resource, firmware-profile and known-limitations docs.

Stop after offline preparation and present the exact non-effective physical
authority proposal. Do not make motion telemetry a release blocker unless the
operator explicitly makes it part of the required public configuration.
