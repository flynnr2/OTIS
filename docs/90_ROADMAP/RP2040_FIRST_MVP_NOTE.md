# RP2040-First MVP Direction

The first OTIS bench MVP should explicitly target the RP2040 / Raspberry Pi Pico.

This is intentional.

The goal of the first MVP is not to maximize hardware capability.

The goal is to validate:

- deterministic timing semantics;
- PIO-based timing-fabric architecture;
- reference-domain timestamping;
- telemetry and provenance models;
- disciplined Core 0 / Core 1 partitioning;
- host separation.

The RP2040 is sufficient for these goals.

Using RP2040 first also encourages architectural discipline:

- timing-critical work remains isolated;
- service functionality remains secondary;
- Core 0 remains timing-focused;
- Core 1 remains service-focused.

Potential later reference-appliance directions may include:

- RP2350 / Raspberry Pi Pico 2;
- FPGA-assisted timing fabrics;
- more advanced interpolation techniques.

However, these should not be prerequisites for validating the core OTIS architecture.
