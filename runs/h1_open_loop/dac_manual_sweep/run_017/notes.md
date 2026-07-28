# H1 DAC/CX317 Characterisation Planned Run

Run ID: `run_017`

Run directory: `runs/h1_open_loop/dac_manual_sweep/run_017`

Status: complete.

Physical setup: Whole-assembly cardboard airflow shield; not a thermally isolated
CX317 enclosure.

## Closeout Summary

`run_017` completed as an H1 manual open-loop DAC/CX317 characterization run.
The host capture started at `2026-07-27T11:58:21Z` and stopped at
`2026-07-28T08:05:11Z`, for about 72,410 seconds elapsed. The scripted DAC
sequence completed all nine planned dwell starts, ended the final `0x8000`
dwell, and logged `restore_ack code=0x8000`.

Validation and analysis found 242 valid count windows, 241 local-PPS
interpolated frequency estimates, no invalid count windows, no host-classified
PPS cadence anomalies after RP2040 timer unwrapping, no reconnects, no reboot
markers, no parser errors, and no capture drops. The D10 PPS witness matched D14
at run end: D14 raw count 72970, D10 raw count 72970, D14-D10 delta 0.

`csv/evt.csv` is header-only. That is expected for this run because CH0 generic
event capture was not part of the H1 topology. PPS observations are captured as
`REF` rows in `csv/ref.csv`, and the temporary D10 PPS witness is emitted as
`STS` diagnostics. The empty `EVT` file must not be interpreted as evidence that
arbitrary CH0 events were observed to be absent.

D14 `rejected_long_count` ended at 16, matching the 16 RP2040 timer wraps in the
raw timestamp stream. Host-side unwrapped PPS intervals remained normal, so this
is a firmware diagnostic rollover artefact in the historical run data rather
than a PPS metrology anomaly. The firmware diagnostic path now classifies
intervals with rollover-safe modular arithmetic; the historical `run_017` count
remains preserved as raw evidence.

`run_017` provides strong H1 evidence that the PPS, FC0 measurement path, DAC
application path, and CX317 response are coherent and suitable for subsequent
observe-only SW2 development within the verified `0x7000..0x9000` range. It
does not grant automatic actuation authority.

## Inspection Summary

- `run_016` structure: `manifest.json`, `config.env`, `notes.md`, `control/`,
  `raw/serial.log`, split `csv/`, `plots/`, `derived/reference_prequal/`, and
  `reports/`.
- Current run-directory convention: H1 DAC manual sweeps live under
  `runs/h1_open_loop/dac_manual_sweep/run_NNN`.
- Actual capture command: `python3 -m host.otis_tools.capture_device` with
  `--run-dir` and optional `--command-fifo`.
- Actual serial command mechanism: `python3 -m host.otis_tools.send_command`
  writes validated commands into the capture-owned FIFO.
- Actual timed sequence runner for this run:
  `python3 -m host.otis_tools.h1_dac_sequence`.
- Actual analysis/report commands:
  `python3 -m host.otis_tools.validate_run`,
  `python3 -m host.otis_tools.report_run`, and
  `python3 -m host.otis_tools.h1_characterize`.
- Serial discovery: `ls -1 /dev/cu.usbmodem*` and/or `arduino-cli board list`;
  capture supports `--auto-detect` only when exactly one `/dev/cu.usbmodem*`
  device exists.
- Firmware build/flash tooling: `arduino-cli compile` and `arduino-cli upload`
  with FQBN `rp2040:rp2040:arduino_nano_connect`.
- Required diagnostics are present in source:
  `OTIS_ENABLE_PPS_DUAL_OBSERVER`, D14 PPS stats, D10 witness stats,
  D14-minus-D10 agreement, burst counters, and D10 buffer overflow counters.
- D10 conflict check: D10 is `OTIS_PIN_GENERIC_EVENT`; for this run it is used
  only by `otis_pps_dual_observer_begin()` as `INPUT` with rising-edge IRQ.
  Do not build GPIO loopback or any mode that drives D10.
- Host H1 analysis includes `LOCAL_PPS_INTERPOLATED`, legacy run-wide frequency,
  local-vs-legacy differences, estimator flags, and PPS support fields in
  `csv/h1_count_frequency_estimates.csv`.

## Firmware Configuration

Use the existing H1 open-loop count-gate path. Do not switch to
`OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO`.

The selected backend is:

- sparse REF capture: `OTIS_CAPTURE_BACKEND_IRQ` on D14;
- oscillator observation: `OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE`, emitted as
  `CNT` rows with a 300 s gate;
- D10 witness: `OTIS_ENABLE_PPS_DUAL_OBSERVER=1`;
- DAC support: `OTIS_ENABLE_DAC_AD5693R=1`, clamps `0x7000..0x9000`;
- manual open-loop only: no discipline loop or automatic steering is enabled.

Compile and upload with:

```bash
RUN_DIR=runs/h1_open_loop/dac_manual_sweep/run_017
FQBN=rp2040:rp2040:arduino_nano_connect
SKETCH=firmware/arduino/otis_nano_rp2040_connect
FIRMWARE_GIT_COMMIT="$(git rev-parse --short=12 HEAD)"
OTIS_H1_FLAGS="-DOTIS_FIRMWARE_GIT_COMMIT=\\\"${FIRMWARE_GIT_COMMIT}\\\" -DOTIS_SW1_BRINGUP_MODE=OTIS_SW1_MODE_H1_OCXO_OBSERVE -DOTIS_CAPTURE_BACKEND=OTIS_CAPTURE_BACKEND_IRQ -DOTIS_TCXO_COUNTER_BACKEND=OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE -DOTIS_ENABLE_PPS_DUAL_OBSERVER=1 -DOTIS_ENABLE_DAC_AD5693R=1 -DOTIS_ENABLE_H1_DAC_SWEEP=1 -DOTIS_DAC_MIN_CODE=0x7000u -DOTIS_DAC_MAX_CODE=0x9000u -DOTIS_H1_LONG_GATE_PERIOD_US=300000000u -DOTIS_ENABLE_ENV_SENSORS=1 -DOTIS_ENABLE_ENV_SHT4X=1 -DOTIS_ENABLE_ENV_BMP280=1"

arduino-cli compile --fqbn "$FQBN" \
  --build-property "compiler.cpp.extra_flags=${OTIS_H1_FLAGS}" \
  "$SKETCH"

SERIAL_DEVICE=/dev/cu.usbmodemXXXX
arduino-cli upload -p "$SERIAL_DEVICE" --fqbn "$FQBN" \
  --build-property "compiler.cpp.extra_flags=${OTIS_H1_FLAGS}" \
  "$SKETCH"
```

After upload, the startup `STS` rows must show:

- `build/enable_pps_dual_observer=1`;
- `build/capture_backend=irq_reconstructed`;
- `build/tcxo_counter_backend=pio_long_gate`;
- `capture/counter_gate_period_us=300000000`;
- `dac/min_code=0x7000` and `dac/max_code=0x9000`;
- `pps_dual_observer/d14_pps_pin=D14`;
- `pps_dual_observer/d10_witness_pin=D10`;
- `pps_dual_observer/d10_input_mode=INPUT_no_pull`;
- `pins/d10_pps_witness=D10_input_rising_no_pull`.

## Planned DAC Schedule

| Step | Phase | DAC code | Duration | Primary analysis use |
| ---: | --- | ---: | ---: | --- |
| 1 | Warm-up / initial centre | `0x8000` | 180 min | retain all; first 60 min warm-up |
| 2 | Positive medium | `0x8800` | 45 min | final 30 min settled |
| 3 | Centre B | `0x8000` | 45 min | final 30 min settled |
| 4 | Negative medium | `0x7800` | 45 min | final 30 min settled |
| 5 | Centre C | `0x8000` | 45 min | final 30 min settled |
| 6 | Positive large | `0x9000` | 45 min | final 30 min settled |
| 7 | Centre D | `0x8000` | 45 min | final 30 min settled |
| 8 | Negative large | `0x7000` | 45 min | final 30 min settled |
| 9 | Final centre | `0x8000` | 120 min minimum | may extend overnight |

Total planned duration is about 10 h 15 min. Do not repeat the excursion
sequence automatically overnight. The final state must remain `DAC=0x8000`.

## Capture Procedure

Use `capture_device` so raw serial, split CSV files, host markers, parser
errors, command accept/reject markers, reconnects, and run status are preserved.
Do not use `cat` or `screen` on the serial port.

Preferred one-terminal capture command:

```bash
RUN_DIR=runs/h1_open_loop/dac_manual_sweep/run_017
[ ! -s "$RUN_DIR/raw/serial.log" ] || { echo "Refusing to append to existing non-empty $RUN_DIR/raw/serial.log"; exit 1; }
mkdir -p "$RUN_DIR/control" "$RUN_DIR/raw" "$RUN_DIR/csv" "$RUN_DIR/reports" "$RUN_DIR/plots" "$RUN_DIR/derived/reference_prequal"
caffeinate -dimsu python3 -m host.otis_tools.capture_device \
  --auto-detect \
  --baud 115200 \
  --run-dir "$RUN_DIR" \
  --command-fifo "$RUN_DIR/control/commands.fifo" \
  2>&1 | tee "$RUN_DIR/control/capture_device.stdout.log"
```

`caffeinate -dimsu` prevents display sleep, idle sleep, disk sleep, and user-idle
sleep while the capture command is running. It exits when capture exits.

Two-terminal alternative:

```bash
# Terminal 1
RUN_DIR=runs/h1_open_loop/dac_manual_sweep/run_017
[ ! -s "$RUN_DIR/raw/serial.log" ] || { echo "Refusing to append to existing non-empty $RUN_DIR/raw/serial.log"; exit 1; }
python3 -m host.otis_tools.capture_device \
  --auto-detect \
  --baud 115200 \
  --run-dir "$RUN_DIR" \
  --command-fifo "$RUN_DIR/control/commands.fifo" \
  2>&1 | tee "$RUN_DIR/control/capture_device.stdout.log"
```

```bash
# Terminal 2, after capture starts
CAPTURE_PID="$(pgrep -n -f 'host.otis_tools.capture_device.*run_017')"
caffeinate -dimsu -w "$CAPTURE_PID"
```

Verify caffeinate:

```bash
pmset -g assertions | grep -E 'caffeinate|PreventUserIdle|PreventSystemSleep'
```

Stop an accidentally orphaned `caffeinate`:

```bash
pkill -x caffeinate
```

## Sequence Runner

Dry-run first:

```bash
python3 -m host.otis_tools.h1_dac_sequence \
  --run-dir runs/h1_open_loop/dac_manual_sweep/run_017 \
  --dry-run
```

Run the timed sequence only after capture is active, startup configuration is
verified, D14/D10 counts are healthy, and the cardboard shield is installed:

```bash
caffeinate -dimsu python3 -m host.otis_tools.h1_dac_sequence \
  --run-dir runs/h1_open_loop/dac_manual_sweep/run_017 \
  --fifo runs/h1_open_loop/dac_manual_sweep/run_017/control/commands.fifo \
  --ack-timeout-s 30 \
  2>&1 | tee -a runs/h1_open_loop/dac_manual_sweep/run_017/control/run_017_sequence.stdout.log
```

The runner prints the whole timeline, sends each `DAC SET` through the existing
FIFO, waits for a fresh `STS,dac,accepted_code` row for that code, records actual
transition attempts in `control/run_017_sequence.log`, uses monotonic dwell
timing, and attempts to restore `0x8000` on normal exit or interruption.

Manual fallback before the experiment begins:

```bash
python3 -m host.otis_tools.send_command --fifo "$RUN_DIR/control/commands.fifo" "DAC SET 0x8000"
python3 -m host.otis_tools.send_command --fifo "$RUN_DIR/control/commands.fifo" "DAC?"
python3 -m host.otis_tools.send_command --fifo "$RUN_DIR/control/commands.fifo" "DAC LIMITS?"
python3 -m host.otis_tools.send_command --fifo "$RUN_DIR/control/commands.fifo" "FC0?"
python3 -m host.otis_tools.send_command --fifo "$RUN_DIR/control/commands.fifo" "SWEEP?"
```

Do not manually clock-watch the ten-hour structured run unless the automated
runner fails before the sequence starts and the run is deliberately postponed or
converted to a shorter diagnostic.

## Live Monitoring

These commands read files written by capture; they do not open the serial port.

Latest DAC status:

```bash
tail -n 200 "$RUN_DIR/csv/sts.csv" | awk -F, '$6=="dac"{print}'
```

D14/D10 PPS diagnostics:

```bash
tail -n 1000 "$RUN_DIR/csv/sts.csv" | awk -F, '$6 ~ /^pps/ {print}'
```

Key health and backend status:

```bash
tail -n 1000 "$RUN_DIR/csv/sts.csv" | awk -F, '$6=="capture" || $6=="fc0" || $6=="pps_d14" || $6=="pps_d10" || $6=="pps_dual_observer"{print}'
```

Latest count observation:

```bash
tail -n 5 "$RUN_DIR/csv/cnt.csv"
```

Environmental telemetry:

```bash
tail -n 20 "$RUN_DIR/csv/environment.csv"
```

Raw-file growth:

```bash
ls -lh "$RUN_DIR/raw/serial.log"
tail -n 20 "$RUN_DIR/raw/serial.log"
```

Expected telemetry fields include:

- `pps_d14/raw_edge_count`, `accepted_pps_count`, `rejected_short_count`,
  `rejected_long_count`, `last_raw_interval`;
- `pps_d10/raw_edge_count`, `short_interval_count`, `last_interval`,
  `buffer_overflow_count`;
- `pps_dual_observer/d14_raw_minus_d10_raw`, `agreement_state`,
  `burst_active`, `burst_count`;
- `capture/dropped_count`, `capture/error_flags`;
- `capture/pio_fifo_overflow_drop_count` only if the PIO FIFO sparse-edge
  backend is compiled, which is not the selected run_017 configuration;
- `fc0/fc0_observed_valid`, `fc0_valid_for_control`, `fc0_fault`,
  `last_counted_edges`, `last_gate_open_ticks`, `last_gate_close_ticks`;
- `environment` SHT4x temperature and humidity, BMP280 pressure.

## Continue While Logging

Do not automatically stop for an isolated short PPS candidate, brief D14/D10
divergence, burst detection, long PPS interval, local-PPS invalid gate,
environmental transient, or unexpected frequency move. Preserve the evidence and
record visible disturbances. Do not open the box just to inspect a telemetry
anomaly.

## Stop Or Pause Conditions

Stop or pause for safety/data integrity if:

- DAC code is outside `0x7000..0x9000`;
- the runner fails to verify a commanded DAC code;
- Vc or supply moves outside the previously verified envelope;
- board resets repeatedly;
- serial capture stops or `raw/serial.log` stops growing;
- disk space is exhausted;
- cardboard touches a warm component or bare conductor;
- visible or smelled overheating occurs;
- diagnostic queues overflow continuously enough to destroy evidence;
- firmware enters an unintended automatic-control mode;
- D10 is detected as an output;
- timestamps become structurally invalid across all streams.

Safe interruption and restore:

```bash
# Interrupt the sequence runner with Ctrl-C; it attempts DAC SET 0x8000.
python3 -m host.otis_tools.send_command --fifo "$RUN_DIR/control/commands.fifo" "DAC SET 0x8000"
python3 -m host.otis_tools.send_command --fifo "$RUN_DIR/control/commands.fifo" "DAC?"
tail -n 50 "$RUN_DIR/csv/sts.csv" | awk -F, '$6=="dac"{print}'
```

## Post-Run

1. Let the runner complete or interrupt it; verify restore to `0x8000`.
2. Stop capture with `Ctrl-C` in the capture terminal.
3. Record end time, GNSS lock state, box state, photographs, and disturbances.
4. Preserve raw capture hash:

```bash
shasum -a 256 "$RUN_DIR/raw/serial.log" | tee "$RUN_DIR/raw/serial.log.sha256"
```

5. Validate and regenerate reports:

```bash
python3 -m host.otis_tools.validate_run "$RUN_DIR" | tee "$RUN_DIR/reports/validate_report.md"
python3 -m host.otis_tools.report_run "$RUN_DIR" \
  --output "$RUN_DIR/reports/summary.md" \
  --json "$RUN_DIR/reports/summary.json"
python3 -m host.otis_tools.h1_characterize "$RUN_DIR" \
  --settling-discard-s 900 \
  --warmup-s 3600 \
  --nominal-hz 10000000
```

Check for parser errors, missing records, resets, reconnects, and overflows:

```bash
grep -E 'parser_error|malformed_utf8|serial_disconnected|BOOT|HDR|overflow|rejected|FATAL|ERROR' "$RUN_DIR/raw/serial.log" | tee "$RUN_DIR/reports/anomalies.md"
tail -n 200 "$RUN_DIR/csv/sts.csv" | awk -F, '$8=="WARN" || $8=="ERROR" || $8=="FATAL"{print}'
```

The required post-run outputs are produced primarily by
`h1_characterize`: local-PPS and legacy frequency timelines, local-vs-legacy
difference, DAC/frequency summaries, centre-bracketed responses, slope
estimates, settling and warm-up plots, estimator validity and PPS-support
columns, environmental diagnostics, and CSV files for reproducible follow-up.
Use the locally recalculated `run_016` report as the historical comparator.

## Analysis Semantics

For each excursion, use centre dwells immediately before and after the excursion
to interpolate the centre trajectory through the excursion period. Compute:

```text
delta_f = excursion_frequency - interpolated_centre_frequency
```

Compute separate responses for `+0x0800`, `-0x0800`, `+0x1000`, and `-0x1000`.
Retain settling points, but use the final 30 min of each 45 min dwell for the
primary step estimate unless the data justify a documented alternative. Do not
force a plant slope if the result is inconsistent.

Physical comparison:

- `run_016`: exposed bench assembly.
- `run_017`: whole-assembly cardboard airflow shield.

This is not a controlled CX317-only enclosure comparison.

## Operator Placeholders

Fill these at execution time:

- serial device;
- Mac model or host identifier;
- firmware commit and dirty-tree state after build;
- host-analysis commit and dirty-tree state after run;
- start and end time in Europe/London;
- GNSS lock/fix state before capture, before sequence, and after first hour;
- shield placement time;
- box dimensions and cable openings;
- CX317, SHT4x, BMP280, DAC, buck-converter, and RP2040 positions;
- whether the box is lifted at the bottom;
- room and bench conditions;
- all touching, movement, opening, or disturbance events.

## Proposed Commit Message

Prepare shielded H1 DAC characterisation run_017
