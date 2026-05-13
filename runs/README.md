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

Use the helper when available:

```bash
python3 -m host.otis_tools.init_run --stage h0_sw1 --capture-type gps_pps --run-id run_001
```

Then capture raw serial output, parse it into `csv/`, run validation and reporting, and commit only the representative data that is useful for future development.
