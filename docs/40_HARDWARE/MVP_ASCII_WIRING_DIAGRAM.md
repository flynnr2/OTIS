# OTIS MVP ASCII Wiring Diagram

This document provides conceptual wiring diagrams for the OTIS MVP.

It is not a final schematic. It shows major functional blocks, signal directions,
and architectural boundaries.

The important Stage 1 distinction is that the RP2040 board clock remains the
implementation clock. External oscillators such as TCXOs, OCXOs, GPSDO outputs,
or oscillators under test enter OTIS first as observable timing signals.

---

## Stage 1 Open-Loop Measurement MVP

```text
                         ┌──────────────────────┐
                         │      GNSS ANTENNA    │
                         └──────────┬───────────┘
                                    │ RF
                                    ▼
                         ┌──────────────────────┐
                         │   GNSS RECEIVER      │
                         │ Adafruit Ultimate /  │
                         │ future timing GNSS   │
                         │                      │
                         │ PPS ─────────────┐   │
                         │ NMEA UART ─────┐ │   │
                         └────────────────│─┴───┘
                                          │
                                          │
                ┌─────────────────────────▼─────────────────────────┐
                │                  OTIS CORE                         │
                │                RP2040 board                        │
                │                                                    │
                │ RP2040 board clock                                 │
                │   -> firmware / USB / PIO / DMA / housekeeping     │
                │                                                    │
                │ PIO / DMA capture fabric                           │
                │   PPS reference capture  ◄─────────────────────────┘
                │   GNSS serial input      ◄─────────────────────────┐
                │   oscillator input       ◄──────────────┐          │
                │   generic event input    ◄──────┐       │          │
                │                                  │       │          │
                │ USB / serial telemetry ──────────┼───────┼──────────┘
                └──────────────────────────────────┼───────┼───────────
                                                   │       │
                                                   │       │
                       external event / trigger    │       │
                                                   │       │
                                                   ▼       ▼
                         ┌──────────────────────┐  ┌──────────────────────┐
                         │ Input Conditioning   │  │ TCXO / OCXO /        │
                         │ comparator / buffer  │  │ oscillator under test│
                         └──────────────────────┘  └──────────┬───────────┘
                                                              │
                                                              ▼
                                                   ┌──────────────────────┐
                                                   │ Buffer / Level Shift │
                                                   │ e.g. AHCT/LVC gate   │
                                                   └──────────────────────┘

                ┌───────────────────────────────────────────────────┐
                │                    OTIS HOST                       │
                │ Raspberry Pi / laptop                              │
                │                                                    │
                │ append-only raw logs                               │
                │ parsed raw_events.csv                              │
                │ run_manifest.json                                  │
                │ replay tooling                                     │
                │ analysis / plots / reports                         │
                └───────────────────────────────────────────────────┘
```

### Stage 1 Timing Truth

```text
physical edges / reference signals
    ↓
PIO / DMA capture fabric
    ↓
hardware-derived raw observations
    ↓
canonical telemetry
    ↓
host replay and interpretation
```

The TCXO is not hidden inside the RP2040 clock tree in Stage 1. It is a signal
observed by the timing fabric.

---

## Future GPSDO / Steered-Oscillator Architecture

Later stages may add a controlled oscillator, DAC steering, holdover policy, and
reference distribution. That is a later control architecture, not a Stage 1 MVP
assumption.

```text
                         ┌──────────────────────┐
                         │   GNSS TIMING RX     │
                         │  PPS / time solution │
                         └──────────┬───────────┘
                                    │ PPS
                                    ▼
                ┌─────────────────────────────────────────────┐
                │                  OTIS CORE                  │
                │                                             │
                │ PIO / DMA capture fabric                    │
                │ discipline estimator                        │
                │ lock / holdover state                       │
                │ explicit control telemetry                  │
                │                                             │
                │ DAC control ───────────────────────────┐    │
                │ reference observation ◄────────────┐    │    │
                └────────────────────────────────────│────│────┘
                                                     │    │
                                                     │    ▼
                                      ┌──────────────▼──────────────┐
                                      │      Precision DAC          │
                                      │ AD5683R / AD5693R / etc.    │
                                      └──────────────┬──────────────┘
                                                     │ EFC / tuning voltage
                                                     ▼
                                      ┌─────────────────────────────┐
                                      │       OCXO / VCXO            │
                                      │ controlled oscillator        │
                                      │ 10 MHz output ─────────┐     │
                                      └────────────────────────│─────┘
                                                               │
                                                               ▼
                                      ┌─────────────────────────────┐
                                      │ distribution / buffering     │
                                      │ reference outputs            │
                                      │ optional OTIS observation    │
                                      └─────────────────────────────┘
```

### Future GPSDO Timing Truth

```text
raw PPS/reference observations
    ↓
phase/frequency estimator
    ↓
explicit steering decision
    ↓
controlled oscillator behavior
    ↓
continued raw observation and provenance
```

A DAC update or lock-state transition is explanatory control telemetry. It does
not replace the raw observations that justify it.

---

## Power Architecture

```text
             clean DC input
                    │
        ┌───────────┴───────────┐
        │                       │
        ▼                       ▼

  digital regulation      analog low-noise regulation
        │                       │
        │                       │
        ▼                       ▼

   RP2040 / host          oscillator / DAC / analog timing paths
```

---

## Architectural Principle

The CPU observes timing events.

The CPU does **not** create their time.
