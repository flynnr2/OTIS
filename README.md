# OTIS

## Open Timing Instrumentation System

OTIS is an open timing instrumentation platform for deterministic, reference-centric timing measurement and replayable timing analysis.

OTIS is not merely a GPSDO project. It is an instrumentation architecture in which a timing reference and capture fabric create explicit, auditable records of events, references, oscillator observations, status, and derived timing products.

## Current Status

This repository is currently in **F0 / SW0 foundation** status, with the first **SW1** firmware landing zone now present:

- the architecture, terminology, and first data contracts are being made explicit;
- the initial host-side tooling scaffold exists before clever firmware is added;
- the active SW1 firmware landing zone is the Arduino Nano RP2040 Connect sketch;
- the standalone Pico SDK firmware scaffold has been archived under `firmware/deprecated/`;
- the first hardware target is **H0**: RP2040 + Adafruit Ultimate GPS breakout + ECS-TXO-5032-160-TR 16 MHz TCXO + SN74AHCT1G14 edge-conditioning experiments.

The next milestone is **SW1**: Arduino Nano RP2040 Connect firmware that emits canonical records which host tooling can validate, replay, and report on.

## Repository Map

| Directory | Purpose |
|---|---|
| `data_contracts/` | normative schemas and semantic contracts |
| `firmware/arduino/otis_nano_rp2040_connect/` | active Arduino Nano RP2040 Connect SW1 firmware |
| `firmware/deprecated/rp2040_pico_sdk/` | archived Pico SDK scaffold for reference only |
| `host/otis_tools/` | host-side validation/replay/report tooling scaffold |
| `profiles/` | declarative experiment/profile mappings |
| `schemas/` | placeholder for future machine-readable schema artifacts |
| `examples/` | synthetic and captured example runs |
| `tests/` | host-side tests and golden fixtures |

## SW1 Firmware Smoke Target

The first firmware pass should stay deliberately small:

1. USB-only synthetic emitter producing valid `STS`, `EVT`, `REF`, and `CNT` rows.
2. GPIO loopback edge capture on `CH0`.
3. GPS PPS rising-edge capture on `CH1`.
4. Gated or divided TCXO count observation on `CH2`.
5. Host validation and reporting for every captured run directory.

Do not add DAC steering, GPSDO loops, or application-specific profile interpretation until this chain is boring and repeatable.

## Quick Host Scaffold Check

From the repository root:

```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest
python3 -m host.otis_tools.validate_run examples/h0_pps_tcxo_synthetic
python3 -m host.otis_tools.report_run examples/h0_pps_tcxo_synthetic
```

## License

MIT License.
