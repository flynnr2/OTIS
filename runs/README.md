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
