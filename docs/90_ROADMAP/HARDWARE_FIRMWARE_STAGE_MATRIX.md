# Hardware / Firmware / Host Stage Matrix

## Naming Rule

OTIS uses separate stage prefixes:

- `F`: foundations and documentation;
- `H`: hardware configurations;
- `SW`: software, firmware, and host tooling;
- `A`: analysis capability.

This avoids using `Stage 1` to mean different things in hardware, firmware, and roadmap documents.

## Current Matrix

| Stage  | Name                          | Description                                                                                     | Status          |
|--------|-------------------------------|-------------------------------------------------------------------------------------------------|-----------------|
| `F0`   | Foundation                    | architecture, terminology, contracts, design principles                                         | active          |
| `H0`   | Prototype capture hardware    | RP2040 + Adafruit Ultimate GPS PPS + ECS-TXO-5032-160-TR 16 MHz TCXO + conditioning experiments | planned/active  |
| `SW0`  | Host scaffold/contracts       | validation, replay, examples, schema fixtures                                                   | active          |
| `SW1`  | First capture firmware        | emit `EVT`, `REF`, `CNT`, and `STS` from Arduino Nano RP2040 Connect via Arduino-Pico           | next            |
| `A0`   | Basic replay/report           | validate runs and derive simple intervals/frequency estimates                                   | next            |
| `H1`   | Steerable oscillator prep     | open-loop XCXO/OCXO + DAC steering-path bring-up before SW2 control-loop firmware               | future          |
| `SW2`  | Control-loop firmware         | explicit GPSDO/discipline-loop telemetry and control                                            | future          |

## Immediate Next Milestone

Do not jump directly to DAC/GPSDO control. First prove:

```text
Arduino Nano RP2040 Connect captures PPS + generic pulse + oscillator count observations
→ emits canonical records
→ host validates, replays, and reports basic estimates
```

The Arduino Nano RP2040 Connect firmware target for SW1 is the
Earle Philhower `arduino-pico` core, not Arduino Mbed OS Nano Boards. This keeps
the Arduino entrypoint while preserving access to Pico SDK, multicore, and PIO
facilities needed by the timing-fabric stages.

Observation boundary for H0/SW1.5a:

| Signal class | Backend |
|---|---|
| Sparse edges such as GPS PPS, slow GPIO loopback, and future low-rate events | PIO FIFO edge backend |
| Raw CXO on `D8` / `GPIO20` / `GPIN0`, including 10 MHz / 16 MHz TCXO/OCXO/XCXO inputs | RP2040 FC0 / gated-count backend |

The standalone Pico SDK scaffold is deprecated and archived under
`firmware/deprecated/rp2040_pico_sdk/` for reference only. New SW1 firmware work
belongs in `firmware/arduino/otis_nano_rp2040_connect/`.

H1 remains a hardware-prep and open-loop characterization stage. Its preparation
package lives in `docs/40_HARDWARE/H1_STEERABLE_OSCILLATOR_PREP.md`; SW2 should
not begin until the oscillator output, manual DAC command path, and open-loop
tuning sensitivity have been characterized from real hardware.
