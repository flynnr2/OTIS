# Arduino Nano RP2040 Connect First MVP Direction

The first OTIS bench MVP should explicitly target the Arduino Nano RP2040
Connect using the Earle Philhower `arduino-pico` core.

This is intentional.

The goal of the first MVP is not to maximize hardware capability.

The goal is to validate:

- deterministic timing semantics;
- PIO-based timing-fabric architecture;
- reference-domain timestamping;
- telemetry and provenance models;
- disciplined Core 0 / Core 1 partitioning through the Arduino-Pico model;
- host separation.

The Nano RP2040 Connect is sufficient for these goals while keeping the active
firmware entrypoint in the Arduino workflow.

Using the Arduino Nano RP2040 Connect first also encourages architectural
discipline:

- timing-critical work remains isolated;
- service functionality remains secondary;
- Core 0 remains timing-focused;
- Core 1 remains service-focused.

Potential later reference-appliance directions may include:

- lower-level Pico SDK firmware if the Arduino-Pico path proves inadequate;
- RP2350 / Raspberry Pi Pico 2;
- FPGA-assisted timing fabrics;
- more advanced interpolation techniques.

However, these should not be prerequisites for validating the core OTIS architecture.

The old standalone Pico SDK firmware scaffold is deprecated and archived under
`firmware/deprecated/rp2040_pico_sdk/` for reference only. New firmware work
belongs in `firmware/arduino/otis_nano_rp2040_connect/`.
