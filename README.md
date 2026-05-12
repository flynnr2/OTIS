# OTIS

## Open Timing Instrumentation System

OTIS is an open timing instrumentation platform for deterministic, reference-centric timing measurement and replayable timing analysis.

OTIS is not merely a GPSDO project. It is an instrumentation architecture in which a timing reference and capture fabric create explicit, auditable records of events, references, oscillator observations, status, and derived timing products.

## Current Status

This repository has moved from **F0 / SW0 foundation** into the first
**SW1 / H0 bring-up** path:

- the architecture, terminology, and first data contracts are being made explicit;
- the host-side tooling validates synthetic fixtures and header-only hardware run templates;
- the active SW1 firmware supports explicit USB synthetic, GPIO loopback, GPS PPS, and TCXO observation modes;
- the standalone Pico SDK firmware scaffold has been archived under `firmware/deprecated/`;
- the first hardware target is **H0**: RP2040 + Adafruit Ultimate GPS breakout + ECS-TXO-5032-160-TR 16 MHz TCXO + SN74AHCT1G14 edge-conditioning experiments.

H0 hardware is assumed wired and ready for bench testing, but this repo does
not claim real hardware validation until captured non-template run directories
are added.

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

The first firmware pass stays deliberately small:

1. USB-only synthetic emitter producing valid `STS`, `EVT`, `REF`, and `CNT` rows.
2. GPIO loopback edge capture on `CH0`.
3. GPS PPS rising-edge capture on `CH1`.
4. Gated or divided TCXO count observation on `CH2`.
5. Host validation and reporting for every captured run directory.

Do not add DAC steering, GPSDO loops, or application-specific profile interpretation until this chain is boring and repeatable.

## SW1 / H0 Bring-Up Order

1. `SW1_SYNTHETIC_USB`: prove USB serial, record framing, parser, validation, and report tooling.
2. `SW1_GPIO_LOOPBACK`: jumper `D7` to `D10` and prove live GPIO edge capture on `CH0`.
3. `SW1_GPS_PPS`: connect GPS PPS to `D14` and prove `REF` cadence on `CH1`.
4. `SW1_TCXO_OBSERVE`: feed the conditioned/divided TCXO observation path to `D8` / `GPIO20` / `GPIN0` and emit `CNT` windows on `CH2`.
5. Combined real run: capture PPS plus TCXO observations using the H0 manifest template.

The firmware emits raw/canonical observations in the RP2040 capture-domain
model. Host tooling may check PPS cadence and count sanity, but oscillator
quality, lock state, steering quality, and GPSDO discipline claims remain out of
scope for SW1.

## Quick Host Scaffold Check

From the repository root:

```bash
python3 -m pip install -e ".[dev]"
python3 -m pytest
python3 -m host.otis_tools.validate_run examples/h0_pps_tcxo_synthetic
python3 -m host.otis_tools.report_run examples/h0_pps_tcxo_synthetic
```

Header-only hardware run templates are available under:

```text
examples/h0_usb_synthetic/
examples/h0_gpio_loopback/
examples/h0_gps_pps/
examples/h0_pps_tcxo_real/
```

## License

MIT License.
