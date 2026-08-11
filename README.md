# OTIS

## Open Timing Instrumentation System

OTIS is an open timing instrumentation platform for deterministic, reference-centric timing measurement and replayable timing analysis.

OTIS is not merely a GPSDO project. It is an instrumentation architecture in which a timing reference and capture fabric create explicit, auditable records of events, references, oscillator observations, status, and derived timing products.

The project north star is documented in
[`docs/00_FOUNDATIONS/OTIS_DESIGN_PRINCIPLES.md`](docs/00_FOUNDATIONS/OTIS_DESIGN_PRINCIPLES.md):
OTIS is a provenance-preserving timing instrument, not a black-box timing
appliance.

## Local Run Evidence Policy

The repository `.gitignore` is authoritative and must be respected at all
times. In particular, `runs/` is intentionally ignored because it contains
local bench captures, sealed evidence packages, generated reports, and other
potentially large run artifacts. These files are valuable scientific evidence,
but they are stored and retained locally rather than committed to Git.

Do not bypass this policy with `git add -f`, alternate Git plumbing, or
temporary ignore-rule changes. A path under `runs/` in the documentation
identifies a local evidence location and is not a promise that the artifact is
present in a fresh clone. Promote only compact, reviewed conclusions,
machine-readable models, contracts, and purpose-built test fixtures to tracked
directories outside `runs/`.

## Current Status

The
[`OTIS_PLATFORM_STABILIZATION_PROGRAMME`](docs/60_EXPERIMENTS/OTIS_PLATFORM_STABILIZATION_PROGRAMME.md)
passed its completion gate on 2026-08-11. Its reviewed result is in
[`OTIS_PLATFORM_STABILIZATION_COMPLETION_REPORT`](docs/60_EXPERIMENTS/OTIS_PLATFORM_STABILIZATION_COMPLETION_REPORT.md).

The
[`CX319_STABILIZED_TIGHT_DEADBAND_PROGRAMME`](docs/60_EXPERIMENTS/CX319_STABILIZED_TIGHT_DEADBAND_PROGRAMME/00_MASTER_PROGRAMME.md)
is now active for **offline preparation only**. Repository work, deterministic
replay, tests and firmware builds are authorized; flashing, serial access,
command FIFOs, DAC writes, control arming, bench rehearsal and live execution
remain unauthorized pending a separate operator gate.

CX318 Stage 5 remains suspended, incomplete, unsealed, and non-promotable.
CX319 does not resume the old campaign, reuse its promotion ledger or give its
profiles current authority.

The current scientific claim is limited to bounded experimental frequency and
arbitrary-epoch relative-phase evidence. OTIS does not presently claim
traceable absolute frequency, calibrated phase, UTC, lock, or holdover.

Earlier H0/SW1, H1, Phase 4/5, CX317, and CX318 results remain useful
development history. They are not all current supported-product profiles:

- the architecture, terminology, and first data contracts are being made explicit;
- the host-side tooling validates synthetic fixtures and captured run directories;
- diagnostic firmware supports explicit USB synthetic, GPIO loopback, GPS PPS, and TCXO/OCXO observation modes;
- the non-PIO H0/SW1 validation path is healthy;
- the SW1.5a PIO FIFO path is complete enough for sparse-edge observation;
- the standalone Pico SDK firmware scaffold has been archived under `firmware/deprecated/`;
- the first hardware target was **H0**: RP2040 + Adafruit Ultimate GPS breakout + ECS-TXO-5032-160-TR 16 MHz TCXO + SN74AHCT1G14 edge-conditioning experiments.

### Historical development context

The following sections preserve the evidence path that produced the current
platform. Their stage-specific next steps and support language are historical;
the platform-stabilization programme above is authoritative for current work.

The current H1 CX317/AD5693R plant model is
`profiles/plant_models/cx317_h1_bench_v3.json` (model version 4). Run 019 supplies broad
monotonicity and gain; Run 020 supplies the direct local crossing bracket,
drift-cancelled gain, repeatability, and settling evidence. The observe-only
model records a crossing near `0xA950`, local gain
`0.0001559..0.0001876 Hz/code`, applicability over `0xA800..0xB400`, and a
disabled candidate envelope `0xA800..0xAB00`. Both `control_ready` and
`actuation_enabled` remain false. See
`docs/60_EXPERIMENTS/RUN_020_PLANT_MODEL_RESULTS.md`.

The observe-only discipline replay, developed during historical Phase 4, is
complete. Versioned `EST` and
preview-only `CTL` records can be reproduced deterministically from canonical
run evidence, the model, diagnostics, policy, and configuration with:

```bash
python3 -m host.otis_tools.observe_only_discipline_replay /path/to/local/run
```

It writes only beneath the run's legacy, provenance-bearing
`derived/phase4_replay_v3/` directory, verifies
that source-evidence hashes remain unchanged, and contains no DAC write path.
The opt-in live firmware engine now passes deterministic fixture parity and
emits the same normative `EST`/`CTL` contracts without a callable actuation
route. Host and live frequency observations use
`LOCAL_PPS_BOUNDARY_INTERPOLATED_V1`: each count-window boundary is mapped
independently between its surrounding accepted PPS observations, with no
extrapolation. Target USB-load/reconnect testing and a long live observe-only run are
still required, so the firmware-parity exit gate and all active actuation
remain incomplete. See
`docs/50_SOFTWARE/OBSERVE_ONLY_DISCIPLINE_LIVE_ENGINEERING_NOTE.md`.

The current, locally retained SW1.5a evidence run is
`runs/h0_sw1_5a_pio/tcxo_observe/run_001`, recorded from manifest commit
`4cb0fc8088cbc36eeaa0e52e5c4661b86b738aca`. It validates with:

```bash
python3 -m host.otis_tools.validate_run runs/h0_sw1_5a_pio/tcxo_observe/run_001
```

Expected output:

```text
OK raw_events.csv: 141 rows
OK count_observations.csv: 141 rows
OK health.csv: 1128 rows
```

The `COMPLETE` marker is present.

## Repository Map

| Directory | Purpose |
|---|---|
| `data_contracts/` | normative schemas and semantic contracts |
| `firmware/arduino/otis_nano_rp2040_connect/` | active Arduino Nano RP2040 Connect firmware platform |
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

SW1.5a preserves this architecture boundary:

```text
Sparse event capture -> PIO FIFO path
High-rate oscillator observation -> GPIN0/FC0 gated-count path
```

PIO FIFO is for sparse event observation only: PPS, GPIO loopback, and future
low-rate event edges. Raw TCXO/OCXO input on `D8` / `GPIO20` / `GPIN0` must use
FC0/gated-count style observation, not PIO FIFO edge logging.

H1 OCXO/DAC characterization, Phase 4 host replay, and deterministic
host/firmware engine parity are complete. The replacement Phase 5
`pio_wait_cumulative_snapshot_dma_v1` backend was accepted on 2026-08-01 as the
qualified observe-only PPS-gated measurement architecture. Its campaign covers
clean pseudo-PPS, 30/31 strict fault cases with one accepted rising-edge-only
width-blind limitation, real-GPS quiet/load operation, 11,388-window extended
evidence, and a newly sealed 16,798-window overnight run with exact raw
snapshot reconstruction and zero capture/PIO/DMA/ring/session fault. Physical
phase/duty margin remains not tested because the ECS fixture cannot control it;
this is recorded as non-blocking rather than passed. PPS- or
count-error-derived DAC writes remain prohibited until the later reviewed
guarded-actuation gate.

An exact qualification-v4 ELF and source audit subsequently confirmed that the
authoritative aperture contains no CPU/ISR, DMA, USB, serial, foreground, or
core-scheduling latency. The PIO state machine owns both edge counting and the
cumulative PPS snapshot. The remaining measured spread is retained as
end-to-end ECS/GPS/capture characterization, not isolated firmware jitter.
This conclusion is now a regression constraint documented in
`docs/50_SOFTWARE/PPS_CAPTURE_LATENCY_JITTER_AUDIT_20260801.md`.
The deliberately narrower claim that current results may carry, including the
nominal 100 ns/cycle relative-phase conversion and unavailable uncertainty
components, is recorded in
`docs/50_SOFTWARE/CURRENT_METROLOGY_CLAIM.md`.

## Quick Host Scaffold Check

From the repository root:

```bash
python3 -m venv .venv
.venv/bin/python -m pip config --site set global.cache-dir .cache/pip
.venv/bin/python -m pip install -e ".[dev]"
.venv/bin/python -m pytest
.venv/bin/python -m host.otis_tools.validate_run examples/h0_pps_tcxo_synthetic
.venv/bin/python -m host.otis_tools.report_run examples/h0_pps_tcxo_synthetic
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

## Architecture note: diagnostics as a first-class subsystem

OTIS separates measurement, metrology, diagnostics, control, and telemetry. See
`docs/10_REFERENCE_ARCHITECTURE/MEASUREMENT_METROLOGY_DIAGNOSTICS_CONTROL.md` and
`docs/10_REFERENCE_ARCHITECTURE/DIAGNOSTICS_AND_CONFIDENCE_ARCHITECTURE.md` for
the normative model. Every future control action is expected to be explainable
from preserved observations, estimates, diagnostic gates, policy, and actuator
acknowledgement.
