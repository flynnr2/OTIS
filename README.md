# OTIS

## Open Timing Instrumentation System

OTIS is an open timing instrumentation platform for deterministic, reference-centric timing measurement and replayable timing analysis.

OTIS is not merely a GPSDO project. It is an instrumentation architecture in which a timing reference and capture fabric create explicit, auditable records of events, references, oscillator observations, status, and derived timing products.

## Current Status

This repository is currently in **F0 / SW0 foundation** status:

- the architecture, terminology, and first data contracts are being made explicit;
- the initial host-side tooling scaffold exists before clever firmware is added;
- the RP2040 firmware directory is a design scaffold, not a working capture implementation yet;
- the first hardware target is **H0**: RP2040 + Adafruit Ultimate GPS breakout + ECS-TXO-5032-160-TR 16 MHz TCXO + SN74AHCT1G14 edge-conditioning experiments.

The next milestone is **SW1**: RP2040 capture firmware that emits canonical records which host tooling can validate, replay, and report on.

## Stage Naming

OTIS uses separate stage prefixes so documentation, hardware, firmware, and host tooling do not get conflated.

| Prefix | Meaning | Current examples |
|---|---|---|
| `F` | foundation / documentation stage | `F0`: conceptual foundation and contracts |
| `H` | hardware stage | `H0`: RP2040 + GPS PPS + 16 MHz TCXO prototype |
| `SW` | software/tooling/firmware stage | `SW0`: host scaffold and contracts; `SW1`: first capture firmware |
| `A` | analysis stage | `A0`: synthetic replay and basic interval reports |

## H0 / SW0 Reference Shape

The first concrete build keeps the design clean while accepting prototype-grade components:

- **RP2040** as the initial capture/control MCU;
- **Adafruit Ultimate GPS breakout** as the first GNSS PPS source;
- **ECS-TXO-5032-160-TR 16 MHz TCXO** as the first external oscillator observation source;
- **SN74AHCT1G14** as an early edge-conditioning experiment, with RP2040 GPIO voltage limits documented explicitly;
- host-side tooling as the first place where interpretation, validation, replay, and reports live.

Higher-grade GNSS receivers, OCXO/VCXO/XCXO modules, DAC steering, GPSDO behavior, and modular profile support are future stages. The H0 prototype should not bake those later meanings into the raw capture records.

## Canonical Record Families

| Family | Contract | Purpose |
|---|---|---|
| Raw edge captures | `data_contracts/raw_events_v1.csv.md` | individual captured edges such as pulses and PPS |
| Count observations | `data_contracts/count_observations_v1.csv.md` | gated/divided oscillator observations without emitting every edge |
| Reference observations | `data_contracts/reference_observations_v1.csv.md` | interpreted reference timing observations derived from raw records |
| Derived intervals | `data_contracts/derived_intervals_v1.csv.md` | host-derived intervals with explicit provenance |
| Device health/status | `data_contracts/health_v1.csv.md` | status, health, counters, warnings, and diagnostic breadcrumbs |
| Run manifest | `data_contracts/run_manifest_v1.json.md` | run-level provenance and hardware/software metadata |

Status and health messages are represented by the `STS` stream. They are not fake capture channels.

## Initial Channel Roles

Profiles assign meaning, but the H0 reference mapping is:

| Channel | Reference role | Notes |
|---:|---|---|
| `CH0` | generic pulse/event input | photogate, logic pulse, comparator-shaped analog pulse, TIC input |
| `CH1` | GNSS PPS reference input | reference-class pulse capture |
| `CH2` | TCXO/XCXO observation input | divided, gated, or counted oscillator observation |

The profile, not the firmware, decides whether `CH0` is a pendulum, radio timing pulse, switch event, or something else.

## Repository Map

| Directory | Purpose |
|---|---|
| `data_contracts/` | normative schemas and semantic contracts |
| `docs/00_FOUNDATIONS/` | project principles, glossary, vision, and non-goals |
| `docs/10_REFERENCE_ARCHITECTURE/` | capture, timestamp, reference, and channel models |
| `docs/20_TELEMETRY/` | telemetry philosophy and taxonomy |
| `docs/30_ANALYSIS/` | metrology and statistical analysis notes |
| `docs/40_HARDWARE/` | hardware stages, input front ends, wiring references |
| `docs/50_SOFTWARE/` | coding conventions, host architecture, firmware principles |
| `docs/60_EXPERIMENTS/` | measurement methodology |
| `docs/90_ROADMAP/` | staged implementation plan |
| `firmware/rp2040/` | RP2040 firmware design scaffold |
| `host/otis_tools/` | host-side validation/replay/report tooling scaffold |
| `profiles/` | declarative experiment/profile mappings |
| `schemas/` | machine-readable schema stubs and examples |
| `examples/` | synthetic and captured example runs |
| `tests/` | host-side tests and golden fixtures |

## Development Bias

OTIS should be engineered enough without becoming clever for its own sake:

- keep raw capture simple and application-neutral;
- keep semantic interpretation host-side where possible;
- prefer explicit schemas over implicit conventions;
- treat raw data as a scientific artifact;
- preserve provenance from derived products back to raw records;
- flag repetition and semantic drift aggressively;
- handle edge cases deliberately rather than assuming ideal signals.

## Quick Host Scaffold Check

From the repository root:

```bash
python -m pytest
python -m host.otis_tools.validate_run examples/h0_pps_tcxo_synthetic
python -m host.otis_tools.report_run examples/h0_pps_tcxo_synthetic
```

The tooling is intentionally small at SW0. Its purpose is to anchor contracts and tests before firmware complexity arrives.

## License

MIT License.
