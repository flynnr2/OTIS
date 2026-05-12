# RP2040 firmware scaffold

This directory is the low-level Pico SDK SW1 firmware scaffold for the H0 OTIS
prototype.

The active Arduino Nano RP2040 Connect entrypoint lives in
`firmware/arduino/otis_nano_rp2040_connect` and targets the Earle Philhower
`arduino-pico` core. Keep this Pico SDK scaffold as a reference/escape hatch for
PIO/DMA-heavy work that becomes awkward inside the Arduino build flow.

## SW1 goal

Prove the smallest useful capture loop:

1. emit a boot/status `STS` record;
2. emit `REF` records for PPS rising edges on `CH1`;
3. emit synthetic or loopback `EVT` records on `CH0`;
4. emit `CNT` observations for a gated or divided oscillator source on `CH2`;
5. keep DAC steering, GPSDO control loops, and semantic profile interpretation out of firmware.

The firmware should produce canonical CSV records matching the v1 contracts in `data_contracts/`, plus enough health records to distinguish clean runs from explicit data loss.

## Proposed first proof sequence

1. USB-only synthetic emitter.
2. GPIO loopback edge capture.
3. GPS PPS capture.
4. Generic event input capture.
5. TCXO count observation.

Each step should leave behind a run directory with raw serial logs, parsed CSVs, a manifest, validator output, and a short report.

## Skeleton layout

- `CMakeLists.txt`: Pico SDK build skeleton.
- `src/main.c`: minimal entry point and synthetic SW1 smoke emission.
- `src/otis_boot_diag.c`: optional `OTIS_ENABLE_RP2040_BOOT_DIAG` early boot
  register snapshot; see `docs/50_SOFTWARE/RP2040_BOOT_DIAGNOSTICS.md`.
- `src/otis_protocol.h`: record tags, channel IDs, domains, and flag constants.
- `src/otis_records.h`: narrow record emitter interfaces.
- `src/otis_emit.c`: CSV emission helpers.
- `src/capture_core.c`: future PIO/GPIO capture ownership boundary.
- `src/transport_core.c`: future serial/USB transport ownership boundary.
- `src/health.c`: future health/status ownership boundary.
- `src/capture_pio.pio`: placeholder for capture PIO program.

The files are intentionally boring. The first firmware should prove contracts and run rigor before adding clever capture or control-loop machinery.
