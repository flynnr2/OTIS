# OTIS MVP ASCII Wiring Diagram

This document provides an initial conceptual wiring diagram for the OTIS MVP.

It is not a final schematic. It is intended to show the major functional blocks,
signal directions, and architectural boundaries.

```text
                                   ┌──────────────────────┐
                                   │      GNSS ANTENNA    │
                                   │   Active Multi-band  │
                                   └──────────┬───────────┘
                                              │ RF
                                              │
                                   ┌──────────▼───────────┐
                                   │   GNSS TIMING RX     │
                                   │  ZED-F9T / NEO-M8T   │
                                   │                      │
                                   │  PPS ─────────────┐  │
                                   │  NMEA/UBX UART ─┐ │  │
                                   └─────────────────│─┴──┘
                                                     │
                                                     │
                                   ┌─────────────────▼─────────────────┐
                                   │            OTIS CORE              │
                                   │                                   │
                                   │        RP2040 / RP2350            │
                                   │                                   │
                                   │  PIO timing fabric                │
                                   │  DMA capture rings                │
                                   │  discipline engine                │
                                   │  telemetry emission               │
                                   │                                   │
                                   │  PPS capture input  ◄─────────────┘
                                   │  GNSS serial input  ◄─────────────┐
                                   │                                   │
                                   │  SPI DAC control ─────────────┐   │
                                   │                               │   │
                                   │  Event capture input ◄──────┐ │   │
                                   │                             │ │   │
                                   │  PPS output ─────────────┐  │ │   │
                                   │                          │  │ │   │
                                   │  Telemetry UART/USB ────┼──┘ │   │
                                   └──────────────────────────│────┘   │
                                                              │        │
                                                              │        │
                         External pulse / pendulum            │        │
                         / reference input                    │        │
                                   │                          │        │
                                   ▼                          ▼        ▼

                    ┌─────────────────────┐      ┌──────────────────────┐
                    │ Input Conditioning  │      │   Precision DAC      │
                    │ SN74LVC1G17 etc.    │      │ AD5693R / AD5683R    │
                    └─────────┬───────────┘      └──────────┬───────────┘
                              │                             │
                              │                             │ EFC / tuning voltage
                              │                             ▼
                              │               ┌──────────────────────────┐
                              │               │          OCXO            │
                              │               │      10 MHz OCXO         │
                              │               │                          │
                              │               │  EFC input ◄─────────────┘
                              │               │                          
                              │               │  10 MHz out ─────────┐
                              │               └──────────────────────┘
                              │                                        │
                              │                                        │
                              │                         ┌──────────────▼──────────────┐
                              │                         │   Clock Distribution /      │
                              │                         │   Buffering / Level Shift   │
                              │                         │                              │
                              │                         │  fanout / buffering          │
                              │                         │  clean logic conversion      │
                              │                         └──────────────┬──────────────┘
                              │                                        │
                              │                                        │
                              │                 ┌──────────────────────┼──────────────────────┐
                              │                 │                      │                      │
                              │                 ▼                      ▼                      ▼
                              │
                              │        10 MHz reference out      OTIS internal        Frequency counter /
                              │        (BNC / SMA)               reference input      external instruments
                              │
                              │
                              ▼

                 ┌───────────────────────────────────────────────────┐
                 │                  OTIS HOST                        │
                 │                                                   │
                 │        Raspberry Pi Zero 2 W                      │
                 │                                                   │
                 │  append-only logs                                 │
                 │  replay tooling                                   │
                 │  dashboards                                       │
                 │  Allan deviation                                  │
                 │  telemetry archival                               │
                 │  APIs / future OTIS Console                       │
                 └───────────────────────────────────────────────────┘
```

---

# Power Architecture

```text
             clean DC input
                    │
        ┌───────────┴───────────┐
        │                       │
        ▼                       ▼

  digital regulation      analog low-noise regulation
                               (LT3042 etc.)
        │                       │
        │                       │
        ▼                       ▼

   RP2040 / host          OCXO / DAC / analog timing paths
```

---

# Timing Truth

```text
GNSS PPS
    ↓
disciplined OCXO
    ↓
hardware counters / PIO timing fabric
    ↓
hardware-latched event timestamps
    ↓
CPU / telemetry / logging
```

---

# Architectural Principle

The CPU observes timing events.

The CPU does **not** create their time.
