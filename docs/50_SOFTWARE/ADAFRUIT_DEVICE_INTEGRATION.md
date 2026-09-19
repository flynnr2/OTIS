# Adafruit sensor and GNSS integration

OTIS delegates SHT4x commands/CRC/conversion, BMP280 calibration/compensation,
and standard GNSS field decoding to the pinned Adafruit releases listed in
[the dependency inventory](../../firmware/arduino/libraries/README.md).
The AD5693R driver remains unchanged: sensor-library adoption does not authorize
DAC reset, output changes or a new control owner.

## Environmental observations

The existing `OtisEnvSample`, source names, roles, units and ENV v1 schema remain.
The combined SHT4x `getEvent()` return propagates transport and CRC errors; the
individual Unified Sensor wrappers are not used because they discard that return.
High precision, no heater and the existing 1000 ms sampling schedule are explicit.
Adafruit SHT initialization now sends its addressed soft reset. BMP initialization
uses Adafruit, then selects sleep before configuring normal mode, x1 temperature
and pressure oversampling, no filter and 1000 ms standby. A bounded status wait
allows an in-flight conversion to finish after the sleep request; a sensor still
busy after 100 ms fails initialization instead of silently ignoring configuration.
Initialization success
does not claim that a measurement has been read.

The small documented BMP patch preserves every I2C error and obtains pressure and
its compensation temperature from one six-byte burst. Invalid reads do not produce
valid ENV records or refresh retained valid temperature evidence. One sensor's
failure does not invalidate the other sensor or enter D14/D8 qualification.

I2C remains owned by OTIS's shared Wire bus. The RP2040 Wire timeout is explicitly
10 ms per underlying bus operation (including DAC operations), rather than its
inherited default. SHT conversion waits 10 ms; a normal SHT sample therefore has
at most two 10 ms I/O budgets plus that conversion wait, and a BMP sample has two
10 ms I/O budgets, excluding bounded software execution. These are service-time
bounds, not hardware capture timestamps. Adafruit's event timestamp is not used
as a timing-fabric timestamp. Library initialization delays occur in peripheral
initialization; repeat initialization is not part of runtime recovery.

## GNSS qualification

Adafruit GPS 1.9.0's transport-independent `Adafruit_NMEA` and `Adafruit_GNSS`
components execute directly. No `Adafruit_GPS` serial object, library interrupt,
blocking sentence wait or cached position is used. OTIS retains UART0 ownership,
the raw receive ring, line length limits, bounded PMTK bootstrap/query/ack phases,
service coordinates, fault capsules, freshness and causal requalification epochs.
D14 remains the sole PPS timing authority; GNSS serial fields are qualification.

Each complete raw line is checksum/frame-validated by Adafruit. RMC/GGA decoding
is stateless. GSA validation and decimal decoding also use Adafruit; OTIS retains
its explicit fix-quality 0..8, satellite-count 0..99 and fix-dimension 1..3 limits.
UTC/date/HDOP text is copied from that sentence without floating-point roundtrips.
A malformed line cannot partially refresh receiver state. Empty fields cannot
inherit a previous fix/time/date. Fresh RMC cannot repair GGA evidence and vice
versa. The existing GSA requalification gate remains separate.

Acceptance is stricter than the former hand-written parser: malformed populated
navigation fields, invalid UTC/date components and incomplete standard field
layouts now cause an explicit parser fault/metadata hold. They preserve the last
confirmed DAC code and timing capture; fresh causal evidence can requalify through
the existing policy. This does not revise historical acquisition verdicts.

## Verification and deployment boundary

`tests/test_adafruit_devices.py` runs the actual SHT4x/BMP280/BusIO sources against
emulated Wire peripherals: known conversion vectors, shared-bus configuration,
short reads, NACKs, CRC faults, calibration/configuration failures, sensor isolation
and recovery. `tests/test_gnss_receiver.py` runs the actual Adafruit decoder and
OTIS receiver through bootstrap, complete sentences, malformed data, causal repair
and receiver-instance isolation. These tests are no-hardware integration checks,
not a physical qualification or an operational-path rehearsal.

The normal release suite, fixed image/resource audit and exact-bundle operational
rehearsal remain required before a newly authorized physical run. Hardware has
not been flashed or operated by this migration.

## Native builds on Apple Silicon and Intel Macs

The manifest approves both Mac compiler packages at the same GCC/toolchain
version, each by its exact installed-byte SHA-256. The builder identifies the
actual installed package by that digest (including Intel under Rosetta), rejects
unreviewed bytes, and records the selected host and digest in build provenance.
The generated firmware header carries that selected digest, not a default host's.
The core version, board configuration and device-library pins are common to both.

Keep Arduino's compiler/board packages in each Mac's local `~/Library/Arduino15`,
and build caches local. Adafruit libraries are source code targeting RP2040 and
are shared in the repository. Do not swap native compiler packages in shared
Documents or sync Arduino's installed package directory between unlike hosts.
Install the manifest's exact RP2040 core 6.0.0 on each Mac with Boards Manager or:

```sh
arduino-cli core install rp2040:rp2040@6.0.0 --additional-urls https://github.com/earlephilhower/arduino-pico/releases/download/global/package_rp2040_index.json
```

Then use the ordinary `tools/build_firmware.py` entry point. Arduino selects the
host-specific package; OTIS checks its approved identity. Firmware artifacts are
bound to the package that produced them; approval of both compilers does not
assert that their output binaries must be byte-identical.

## Verification record — 2026-09-19

- Full current repository suite: **745 passed** (365.58 s).
- Focused device, GNSS and builder checks after the final code changes:
  **19 passed**; these include the bounded BMP busy-state failure and downstream
  GNSS snapshot eligibility checks.
- Fixed image build using the unchanged pinned core and Intel compiler package:
  **pass**, including exact binary marker/provenance and resource audits.
- Flash program: **229,144 bytes**; static RAM: **154,216 bytes**; remaining
  runtime RAM budget: **107,928 bytes**, above the required 104,858-byte reserve.
- Only the initial Apple Silicon diagnostic build used a different compiler hash.
  It is superseded for software build verification by the successful exact-pin
  build in local `build/adafruit-release/`; neither build is a physical result.
- No firmware upload, receiver command, DAC write or physical acquisition was
  performed. The new bundle still needs operational rehearsal before bench use.
