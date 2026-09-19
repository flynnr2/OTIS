# Adafruit device dependencies

These are reviewed, vendored source releases. They are dependencies, not OTIS
implementations. Each directory retains its upstream license and `UPSTREAM.json`
with repository URL, tag, commit and SHA-256 of every retained file. Examples,
assets and upstream CI files are omitted. The fixed builder verifies the inventory
and hashes, gives these directories explicit Arduino `--library` precedence,
and incorporates their bytes into firmware source provenance. It does not resolve
an arbitrary library installed in the operator's sketchbook.

| Library | Release | Use |
|---|---|---|
| Adafruit SHT4x | 1.0.5 | High-precision temperature/humidity, heater disabled |
| Adafruit BMP280 | 3.0.0 | Calibration, configuration and compensation |
| Adafruit GPS | 1.9.0 | `Adafruit_NMEA` framing validation and `Adafruit_GNSS` stateless decoding |
| Adafruit BusIO | 1.17.4 | Sensor I2C transactions |
| Adafruit Unified Sensor | 1.1.15 | Sensor event types |

## Local BMP280 integration patch

`Adafruit_BMP280.h/.cpp` contain one bounded integration patch:

- latch every register read/write failure across initialization/configuration;
- reject initialization with failed I/O or zero T1/P1 calibration coefficients;
- add `readSample()` to acquire pressure and temperature in one six-byte burst,
  then use the existing Adafruit compensation methods against that local sample;
- reject skipped-channel sentinel values and nonfinite/nonpositive results.

The compensation equations are unchanged. The normal Adafruit individual read
methods are not OTIS's acquisition interface. OTIS does not call the unbounded
`takeForcedMeasurement()` wait. All other vendored libraries are unmodified.

A dependency update must preserve its upstream identity/license, review the local
patch against the new release, update file hashes, and exercise the actual
library code through the sensor and GNSS native tests before the fixed build and
resource audit. Do not silently refresh dependencies during a campaign.
