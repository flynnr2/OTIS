# H1 Manual DAC Range Probe

Run ID: `run_018`

Run directory: `runs/h1_open_loop/dac_manual_sweep/run_018`

Status: planned.

`run_018` follows `run_017` as a manual DAC range-extension and 10 MHz
bracketing run. The purpose is to determine where the CX317 crosses
`10000000.000000 Hz`, collect plant evidence above the currently verified
automatic DAC range, and prepare evidence for a later plant-model update.

This is not a control-loop experiment. Do not add SW2 control logic, do not
enable closed-loop discipline, and do not widen automatic firmware limits based
on planning alone. The SW2 readiness state remains `control_ready=false` and
`actuation_enabled=false`.

## Background

`run_017` established stable PPS and FC0 measurement paths, a coherent and
monotonic DAC to CX317 response, and a verified automatic range of
`0x7000..0x9000`. At `0x9000` the oscillator still appeared slightly low, so the
10 MHz crossing is expected above the current verified range.

The higher DAC codes in this run are manual characterization probes only.

## Firmware Configuration

Use the existing H1 open-loop count-gate path:

- sparse REF capture: `OTIS_CAPTURE_BACKEND_IRQ` on D14;
- oscillator observation: `OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE`;
- 300 s count windows: `OTIS_H1_LONG_GATE_PERIOD_US=300000000u`;
- D10 witness: `OTIS_ENABLE_PPS_DUAL_OBSERVER=1`;
- DAC support: `OTIS_ENABLE_DAC_AD5693R=1`;
- manual open-loop only: no discipline loop, PLL/FLL, or automatic steering.

Build flags:

```bash
RUN_DIR=runs/h1_open_loop/dac_manual_sweep/run_018
FQBN=rp2040:rp2040:arduino_nano_connect
SKETCH=firmware/arduino/otis_nano_rp2040_connect
FIRMWARE_GIT_COMMIT="$(git rev-parse --short=12 HEAD)"
OTIS_H1_FLAGS="-DOTIS_FIRMWARE_GIT_COMMIT=\\\"${FIRMWARE_GIT_COMMIT}\\\" -DOTIS_SW1_BRINGUP_MODE=OTIS_SW1_MODE_H1_OCXO_OBSERVE -DOTIS_CAPTURE_BACKEND=OTIS_CAPTURE_BACKEND_IRQ -DOTIS_TCXO_COUNTER_BACKEND=OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE -DOTIS_ENABLE_PPS_DUAL_OBSERVER=1 -DOTIS_ENABLE_DAC_AD5693R=1 -DOTIS_ENABLE_H1_DAC_SWEEP=1 -DOTIS_DAC_MIN_CODE=0x7000u -DOTIS_DAC_MAX_CODE=0xAE00u -DOTIS_H1_LONG_GATE_PERIOD_US=300000000u -DOTIS_ENABLE_ENV_SENSORS=1 -DOTIS_ENABLE_ENV_SHT4X=1 -DOTIS_ENABLE_ENV_BMP280=1"

arduino-cli compile --fqbn "$FQBN" \
  --build-property "compiler.cpp.extra_flags=${OTIS_H1_FLAGS}" \
  "$SKETCH"
```

Arduino IDE builds now use the same manual command clamp by default:
`OTIS_DAC_MIN_CODE=0x7000u` and `OTIS_DAC_MAX_CODE=0xAE00u`. The currently
verified automatic range is still `0x7000..0x9000`. The operator must not treat
successful manual commands above `0x9000` as authorization for SW2 automatic
actuation.

## Capture Procedure

Use `capture_device`; do not use `cat` or `screen` on the serial port.

```bash
RUN_DIR=runs/h1_open_loop/dac_manual_sweep/run_018
[ ! -s "$RUN_DIR/raw/serial.log" ] || { echo "Refusing to append to existing non-empty $RUN_DIR/raw/serial.log"; exit 1; }
mkdir -p "$RUN_DIR/control" "$RUN_DIR/raw" "$RUN_DIR/csv" "$RUN_DIR/reports" "$RUN_DIR/plots" "$RUN_DIR/derived/reference_prequal"
caffeinate -dimsu python3 -m host.otis_tools.capture_device \
  --auto-detect \
  --baud 115200 \
  --run-dir "$RUN_DIR" \
  --command-fifo "$RUN_DIR/control/commands.fifo" \
  2>&1 | tee "$RUN_DIR/control/capture_device.stdout.log"
```

Before probing, record:

```bash
date | tee "$RUN_DIR/control/start-time.txt"
git status --short --branch | tee "$RUN_DIR/control/git-status-before-run.txt"
git rev-parse HEAD | tee "$RUN_DIR/control/git-head-before-run.txt"
```

## Manual DAC Schedule

Initial sequence:

| Step | Phase | DAC code | Use |
| ---: | --- | ---: | --- |
| 1 | Baseline | `0x8000` | known centre baseline |
| 2 | Upper verified endpoint | `0x9000` | compare with run_017 endpoint |
| 3 | Manual extension | `0x9800` | look for approach to 10 MHz |
| 4 | Manual extension | `0xA000` | bracket candidate |
| 5 | Manual extension | `0xA800` | bracket candidate |
| 6 | Manual extension | `0xAC00` | bracket candidate |

If 10 MHz has not yet been bracketed, add:

| Step | Phase | DAC code | Use |
| ---: | --- | ---: | --- |
| 7 | Optional manual extension | `0xAE00` | only if still below target |

If a crossing occurs between two points, refine manually using approximate
`0x0200` or `0x0100` steps until the highest-below and lowest-above codes are
clear.

Manual command pattern:

```bash
RUN_DIR=runs/h1_open_loop/dac_manual_sweep/run_018
python3 -m host.otis_tools.send_command --fifo "$RUN_DIR/control/commands.fifo" "DAC SET 0x9800"
python3 -m host.otis_tools.send_command --fifo "$RUN_DIR/control/commands.fifo" "DAC?"
tail -n 50 "$RUN_DIR/csv/sts.csv" | awk -F, '$6=="dac"{print}'
```

At each DAC code:

1. Apply the requested DAC code.
2. Confirm firmware reports the applied code.
3. Measure the CX317 tuning voltage with the DMM.
4. Allow the configured settling period.
5. Capture at least two or three valid 300 s measurement windows.
6. Continue only if `estimator_valid == true`.
7. Record observations immediately in `control/operator_manual_log.md`.

## Analysis

After enough 300 s windows have accumulated, regenerate the H1 analysis:

```bash
RUN_DIR=runs/h1_open_loop/dac_manual_sweep/run_018
python3 -m host.otis_tools.validate_run "$RUN_DIR" | tee "$RUN_DIR/reports/validate_report.md"
python3 -m host.otis_tools.report_run "$RUN_DIR" --output "$RUN_DIR/reports/summary.md" --json "$RUN_DIR/reports/summary.json"
python3 -m host.otis_tools.h1_characterize "$RUN_DIR" --settling-discard-s 900 --warmup-s 3600 --nominal-hz 10000000
```

Use:

```text
csv/h1_count_frequency_estimates.csv
```

with these primary observables:

- `local_pps_frequency_hz`
- `local_pps_ppm`
- `estimator_valid`

Only use rows where `estimator_valid == true`. The bracketing objective is to
find where `local_pps_frequency_hz` crosses `10000000.000000 Hz`.

Convenience helper:

```bash
RUN_DIR=runs/h1_open_loop/dac_manual_sweep/run_018
python3 -m host.otis_tools.h1_latest_estimate "$RUN_DIR" --dac-code 0xA400
```

Example output:

```text
DAC 0xA400 | 10000000.183 Hz | +0.018 ppm | valid
```

## Closeout

After capture:

```bash
RUN_DIR=runs/h1_open_loop/dac_manual_sweep/run_018
date | tee "$RUN_DIR/control/end-time.txt"
shasum -a 256 "$RUN_DIR/raw/serial.log" | tee "$RUN_DIR/raw/serial.log.sha256"
grep -E 'parser_error|malformed_utf8|serial_disconnected|BOOT|HDR|overflow|rejected|FATAL|ERROR' "$RUN_DIR/raw/serial.log" | tee "$RUN_DIR/reports/anomalies.md"
```

Closeout notes must state:

- highest code still below 10 MHz;
- lowest code above 10 MHz;
- estimated crossing code;
- measured Vc at each code;
- recommended future automatic range, if any;
- whether the plant model should be updated with the new evidence;
- confirmation that `control_ready=false` and `actuation_enabled=false`.
