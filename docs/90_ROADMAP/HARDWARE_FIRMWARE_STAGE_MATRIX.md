# Hardware / Firmware / Host Stage Matrix

## Naming Rule

OTIS uses separate stage prefixes:

- `F`: foundations and documentation;
- `H`: hardware configurations;
- `SW`: software, firmware, and host tooling;
- `A`: analysis capability.

This avoids using `Stage 1` to mean different things in hardware, firmware, and roadmap documents.

## Current Matrix

| Stage | Name | Description | Status |
|---|---|---|---|
| `F0` | Foundation | architecture, terminology, contracts, design principles | active |
| `H0` | Prototype capture hardware | RP2040 + Adafruit Ultimate GPS PPS + ECS-TXO-5032-160-TR 16 MHz TCXO + conditioning experiments | planned/active |
| `SW0` | Host scaffold/contracts | validation, replay, examples, schema fixtures | active |
| `SW1` | First capture firmware | emit `EVT`, `REF`, `CNT`, and `STS` from RP2040 | next |
| `A0` | Basic replay/report | validate runs and derive simple intervals/frequency estimates | next |
| `H1` | Steerable oscillator hardware | higher-grade GNSS, XCXO, DAC steering path | future |
| `SW2` | Control-loop firmware | explicit GPSDO/discipline-loop telemetry and control | future |

## Immediate Next Milestone

Do not jump directly to DAC/GPSDO control. First prove:

```text
RP2040 captures PPS + generic pulse + oscillator count observations
→ emits canonical records
→ host validates, replays, and reports basic estimates
```
