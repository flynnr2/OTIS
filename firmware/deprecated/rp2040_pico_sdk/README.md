# Deprecated Pico SDK firmware scaffold

This directory is an archived Pico SDK scaffold. It is not an active OTIS
firmware target.

New firmware work belongs in
`firmware/arduino/otis_nano_rp2040_connect`, which targets the Arduino Nano
RP2040 Connect using the Earle Philhower `arduino-pico` core.

Keep this archive only as reference material for low-level Pico SDK, PIO, DMA,
and boot-diagnostics experiments that may inform the Arduino-Pico path.

## Archived layout

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
