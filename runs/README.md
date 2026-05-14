# OTIS Run Captures

`runs/` holds repeatable bench capture directories for OTIS hardware and firmware stages. It is intended for templates, small representative captures, and enough metadata to reproduce or audit a run without changing firmware behavior.

## Artifact Types

- `serial_raw.log` is the forensic ground truth: the raw serial stream captured from the device.
- `csv/` contains parsed records split by record family for validation and analysis.
- `reports/` contains validation output, short summaries, and anomaly notes.
- `plots/` contains generated visual checks for inspection.
- `derived/` contains regeneratable analysis products such as statistics and replay caches.

Plots and derived files should be reproducible from the raw serial log, CSVs, manifest, and host tooling. Treat `manifest.json` as required for every real committed run.

## H0/SW1 Capture Types

- `h0_sw1/synthetic_usb`: synthetic USB stream exercises host parsing and validation without external timing hardware.
- `h0_sw1/gpio_loopback`: GPIO loopback capture for basic edge timestamp behavior.
- `h0_sw1/gps_pps`: GPS PPS reference capture.
- `h0_sw1/tcxo_observe`: TCXO observe or frequency-count capture.

The `h0_sw1_5a_pio/` and `h0_sw1_5b_dma/` trees reserve the same bench categories for later PIO and DMA timestamp work.

## H1 Open-Loop Runs

H1 run templates reserve open-loop OCXO/DAC bench characterization categories.
They are documentation and host-run scaffolds only; they do not imply that SW2
GPSDO steering firmware exists.

- `h1_open_loop/ocxo_power_warmup`: oscillator power, current, and warm-up observation.
- `h1_open_loop/dac_output_verify`: DAC I2C, reference, gain, and output-voltage checks.
- `h1_open_loop/ocxo_free_run`: oscillator observed without automatic steering.
- `h1_open_loop/dac_manual_sweep`: manual DAC increments with frequency-response notes.
- `h1_open_loop/settling_thermal`: settling and thermal observations after fixed manual conditions.

H1 runs remain open-loop artifacts. They should document oscillator identity,
pinout source, measured power rails, DAC part, DAC reference, I2C address,
conditioning path, RP2040-safe logic level, safety limits, and any manual DAC
command sequence. They should not imply that SW2 GPSDO control-loop firmware
exists.

Suggested H1 manifest additions:

```json
{
  "h_phase": "H1",
  "stage": "OPEN_LOOP",
  "capture_type": "",
  "oscillator": {
    "part": "",
    "nominal_frequency_hz": null,
    "output_type": "",
    "supply_voltage_v": null,
    "control_voltage_range_v": null,
    "pinout_source": ""
  },
  "dac": {
    "part": "AD5693R",
    "resolution_bits": 16,
    "interface": "i2c",
    "i2c_address": "0x4C",
    "reference_voltage_v": null,
    "gain_mode": "",
    "measured_output_min_v": null,
    "measured_output_max_v": null
  },
  "control_path": {
    "network": "",
    "rc_filter": "",
    "buffer": "",
    "measured_control_voltage_v": null
  },
  "conditioning": {
    "oscillator_output_conditioner": "",
    "rp2040_pin": "D8/GPIO20/GPIN0",
    "logic_voltage_v": null
  },
  "safety_limits": {
    "dac_min_code": null,
    "dac_max_code": null,
    "control_voltage_min_v": null,
    "control_voltage_max_v": null
  }
}
```

## Lifecycle

```text
copy _template to run_001
capture serial_raw.log
parse CSVs
validate
report
inspect plots
commit small representative runs
```

For unattended macOS host-appliance runs, prefer the device-owning daemon:

```bash
python3 -m host.otis_tools.capture_device \
  --device /dev/cu.usbmodem101 \
  --baud 115200 \
  --run-dir runs/2026-05-13_h0_pps_tcxo_001
```

It creates and uses this layout:

```text
runs/2026-05-13_h0_pps_tcxo_001/
  raw/
    serial.log
  csv/
    raw_events.csv
    count_observations.csv
    health.csv
  reports/
  run_manifest.json
```

During capture, no other process should open the serial device. Use
`validate_run`, `report_run`, and any analysis scripts against files in the run
directory. Reconnects, malformed UTF-8, dropped partial lines, byte counts, and
shutdowns are logged explicitly; existing `raw/serial.log` content is never
truncated.

Use the helper when available:

```bash
python3 -m host.otis_tools.init_run --stage h0_sw1 --capture-type gps_pps --run-id run_001
```

Then capture raw serial output, parse it into `csv/`, run validation and reporting, and commit only the representative data that is useful for future development.

## A0 Replay and Report Workflow

For a flat example run, keep the current manifest paths:

```bash
python3 -m host.otis_tools.validate_run examples/h0_pps_tcxo_synthetic
python3 -m host.otis_tools.report_run examples/h0_pps_tcxo_synthetic
```

For an H0/SW1 run directory, the normal host loop is:

```bash
python3 -m host.otis_tools.capture_serial --template runs/h0_sw1/gps_pps/_template --run-dir runs/h0_sw1/gps_pps/run_001 --run-id run_001 < serial_raw.log
python3 -m host.otis_tools.validate_run runs/h0_sw1/gps_pps/run_001
python3 -m host.otis_tools.report_run runs/h0_sw1/gps_pps/run_001 --output runs/h0_sw1/gps_pps/run_001/reports/summary.md --json runs/h0_sw1/gps_pps/run_001/reports/summary.json
```

Usually commit:

- `manifest.json` or `run_manifest.json`
- `notes.md` or `README.md`
- parsed CSV artifacts listed by the manifest
- validation and report summaries
- small representative raw logs when they are diagnostically useful

Usually leave disposable or regenerate:

- plots
- caches and replay scratch files
- huge raw serial logs
- temporary stdout dumps

The report tool is intentionally conservative. It computes timing and frequency metrics only when manifest domains declare clear nominal units; otherwise it still reports row counts, headers, structural checks, validation findings, and a note explaining which fields or domains were ambiguous.
