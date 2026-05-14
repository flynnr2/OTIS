# OTIS Arduino SW1 behavioral baselines

This directory captures the pre-refactor SW1 behavior for
`firmware/arduino/otis_nano_rp2040_connect`.

Use this as the R0 baseline process before changing firmware internals. The
goal is to preserve raw serial output and generated parser artifacts so later
refactor commits can be compared against known-good SW1 behavior.

## Ground rules

- Do not change firmware behavior to satisfy this process.
- Do not change the wire format, timestamp semantics, public field names, tag
  names, or existing diagnostics.
- Build each mode from the current SW1 sketch and record the exact commit used.
- Keep raw serial logs. Derived CSV and reports are useful, but the raw log is
  the behavioral source of truth.
- Use representative captures long enough to include boot records, CSV headers,
  status records, capture records, and periodic counters. For PPS and TCXO
  hardware runs, prefer at least 60 seconds.

## Artifact layout

Place generated R0 artifacts under `firmware/arduino/validation/baselines/`.
The committed `.gitkeep` keeps the directory present without committing large
bench captures by default.

For each mode, the intended artifact names are:

```text
raw/<mode>_raw_serial.txt
csv/<mode>_raw_events.csv
csv/<mode>_count_observations.csv
csv/<mode>_health.csv
reports/<mode>_validation.md
reports/<mode>_summary.json
```

The CSV tag names (`raw_events`, `count_observations`, `health`) match the
existing host contracts. Modes that do not emit count observations may still
produce a header-only `count_observations` CSV.

## Baseline modes

### synthetic

Purpose: USB serial, boot/status records, CSV headers, parser compatibility,
and deterministic synthetic `EVT`, `REF`, and `CNT` records.

Build:

```bash
arduino-cli compile --fqbn rp2040:rp2040:arduino_nano_connect \
  --build-property compiler.cpp.extra_flags=-DOTIS_SW1_BRINGUP_MODE=OTIS_SW1_MODE_SYNTHETIC_USB \
  firmware/arduino/otis_nano_rp2040_connect
```

Capture:

```bash
arduino-cli monitor -p /dev/cu.usbmodemXXXX -c baudrate=115200 \
  > firmware/arduino/validation/baselines/raw/synthetic_raw_serial.txt
```

Expected capture records: synthetic `EVT`, `REF`, and `CNT`.

### gpio_loopback

Purpose: local GPIO edge capture without external timing hardware.

Wiring: jumper `D7` to `D10`.

Build:

```bash
arduino-cli compile --fqbn rp2040:rp2040:arduino_nano_connect \
  --build-property compiler.cpp.extra_flags=-DOTIS_SW1_BRINGUP_MODE=OTIS_SW1_MODE_GPIO_LOOPBACK \
  firmware/arduino/otis_nano_rp2040_connect
```

Capture:

```bash
arduino-cli monitor -p /dev/cu.usbmodemXXXX -c baudrate=115200 \
  > firmware/arduino/validation/baselines/raw/gpio_loopback_raw_serial.txt
```

Expected capture records: live `EVT` records on `CH0`.

### gps_pps

Purpose: GPS PPS/reference input behavior when hardware is connected.

Wiring: conditioned GPS PPS to `D14` / `GPIO26` / `CH1`.

Build:

```bash
arduino-cli compile --fqbn rp2040:rp2040:arduino_nano_connect \
  --build-property compiler.cpp.extra_flags=-DOTIS_SW1_BRINGUP_MODE=OTIS_SW1_MODE_GPS_PPS \
  firmware/arduino/otis_nano_rp2040_connect
```

Capture:

```bash
arduino-cli monitor -p /dev/cu.usbmodemXXXX -c baudrate=115200 \
  > firmware/arduino/validation/baselines/raw/gps_pps_raw_serial.txt
```

Expected capture records: rising-edge `REF` records on `CH1` with
approximately one-second cadence under the current SW1 timestamp model.

### tcxo_observe

Purpose: GPIN0 / TCXO observation behavior when oscillator hardware is
connected, with PPS capture if wired.

Wiring: TCXO observation on `D8` / `GPIO20` / `GPIN0`; conditioned GPS PPS on
`D14` / `GPIO26` / `CH1` when available.

Build:

```bash
arduino-cli compile --fqbn rp2040:rp2040:arduino_nano_connect \
  --build-property compiler.cpp.extra_flags=-DOTIS_SW1_BRINGUP_MODE=OTIS_SW1_MODE_TCXO_OBSERVE \
  firmware/arduino/otis_nano_rp2040_connect
```

Capture:

```bash
arduino-cli monitor -p /dev/cu.usbmodemXXXX -c baudrate=115200 \
  > firmware/arduino/validation/baselines/raw/tcxo_observe_raw_serial.txt
```

Expected capture records: hardware frequency-counter `CNT` records on `CH2`;
`REF` records on `CH1` if PPS is wired.

## Parse and validate an existing raw log

After capturing a raw serial file, run:

```bash
python3 firmware/arduino/validation/scripts/parse_baseline_serial.py \
  --mode synthetic \
  --raw firmware/arduino/validation/baselines/raw/synthetic_raw_serial.txt
```

Replace `synthetic` with `gpio_loopback`, `gps_pps`, or `tcxo_observe`.

The script writes the intended `raw/`, `csv/`, and `reports/` artifacts under
`firmware/arduino/validation/baselines/`. It reuses the existing
`host.otis_tools` parser, validator, and reporter.

## Wire-format regression validation

Small committed wire-format fixtures live under
`firmware/arduino/validation/golden/`. They are intentionally short excerpts,
not full bench captures. Use them to catch accidental protocol changes before
or after firmware refactors:

```bash
python3 tools/otis_wire_validate.py \
  firmware/arduino/validation/golden/synthetic_sw1_excerpt.txt \
  --profile synthetic

python3 tools/otis_wire_validate.py \
  firmware/arduino/validation/golden/gpio_loopback_sw1_excerpt.txt \
  --profile gpio_loopback

python3 tools/otis_wire_validate.py \
  firmware/arduino/validation/golden/gpin0_observe_sw1_excerpt.txt \
  --profile gpin0_observe
```

The validator checks raw serial text directly. It validates known OTIS record
tags, field names, field order, schema version, numeric parseability, monotonic
sequence counters, expected boot/reset diagnostics, required boot/config/status
fields, capture records for the selected profile, ring drop fields, and PIO
overflow fields when a PIO capture mode is present.

It emits Markdown by default and exits non-zero on hard failures. JSON output is
available for CI or scripted checks:

```bash
python3 tools/otis_wire_validate.py \
  firmware/arduino/validation/golden/synthetic_sw1_excerpt.txt \
  --profile synthetic \
  --format json \
  --output firmware/arduino/validation/reports/synthetic_wire_summary.json
```

For captures that begin after the protocol banner and CSV headers, use
`--no-require-headers`. Older committed SW1 raw logs may still be useful as
negative regression samples if they predate newer `firmware` and `protocol`
status metadata.

## Validation checklist

Before R1 begins, capture and validate all four modes above. Record the
firmware commit, board/core versions, wiring, capture duration, and whether the
IRQ or PIO FIFO backend was used.

Each representative run should show:

- firmware compiles for `rp2040:rp2040:arduino_nano_connect`;
- `BOOT` appears and `BOOT_FATAL` does not appear;
- no unexpected reset loop in the captured raw serial log;
- CSV header/schema rows for `EVT`/`REF`, `CNT`, and `STS` contracts;
- expected `STS` boot/config records, including `system boot`,
  `protocol schema_version`, `firmware name/version/git_commit`, `system mode`,
  `capture mode`, board/core, pin mapping, and build flags;
- expected capture records for the selected mode;
- `capture,dropped_count` remains zero in the representative run;
- `capture,pio_fifo_overflow_drop_count` remains zero when the PIO FIFO backend
  is used;
- sequence counters and timestamps are monotonic where expected;
- emitted field names and record tags match the current host contracts;
- serial output remains parseable by `host.otis_tools.capture_serial`,
  `host.otis_tools.validate_run`, and `host.otis_tools.report_run`.
