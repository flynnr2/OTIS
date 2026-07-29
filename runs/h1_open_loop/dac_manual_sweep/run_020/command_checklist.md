# run_020 Command Checklist

Run shell commands from the OTIS repository root. Firmware compilation and
upload are performed only in the Arduino IDE.

## 1. Confirm the Complete IDE Configuration

Open:

`firmware/arduino/otis_nano_rp2040_connect/otis_config.h`

The Run 020 configuration must be:

| Setting | Required value |
| --- | --- |
| `OTIS_FIRMWARE_CONFIG_ID` | `"run_020_crossing_v1"` |
| `OTIS_SW1_BRINGUP_MODE` | `OTIS_SW1_MODE_H1_OCXO_OBSERVE` |
| `OTIS_CAPTURE_BACKEND` | `OTIS_CAPTURE_BACKEND_IRQ` |
| `OTIS_TCXO_COUNTER_BACKEND` | `OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE` |
| `OTIS_H1_LONG_GATE_PERIOD_US` | `300000000u` |
| `OTIS_FC0_STARTUP_INHIBIT_MS` | `600000u` |
| `OTIS_FC0_CONTROL_READY_CLEAN_WINDOWS` | `3u` |
| `OTIS_ENABLE_PPS_DUAL_OBSERVER` | `1` |
| `OTIS_ENABLE_DAC_AD5693R` | `1` |
| `OTIS_DAC_AD5693R_I2C_ADDRESS` | `0x4Cu` |
| `OTIS_DAC_MIN_CODE` | `0x6000u` |
| `OTIS_DAC_MAX_CODE` | `0xFC00u` |
| `OTIS_ENABLE_ENV_SENSORS` | `1` |
| `OTIS_ENABLE_ENV_SHT4X` | `1` |
| `OTIS_ENABLE_ENV_BMP280` | `1` |
| `OTIS_ENABLE_H1_DAC_SWEEP` | `1` |
| `OTIS_H1_DAC_SWEEP_DEFAULT_DWELL_MS` | `2400000u` |
| `OTIS_H1_DAC_SWEEP_SLOPE_DWELL_MS` | `2400000u` |
| `OTIS_H1_DAC_SWEEP_TINY_STEP_CODES` | `0x0300u` |

These values produce centre `0xAE00` and the focused profile:

```text
AE00, B100, AE00, AB00, AE00, B400, AE00, A800, AE00
```

Use the Arduino IDE to Verify and Upload the sketch. Do not use CLI flags.
Close the IDE Serial Monitor and Serial Plotter afterward.

## 2. Terminal 1 — Capture Serial Under Caffeinate

Start promptly after the IDE upload. This refuses to append to existing raw
evidence:

```bash
RUN_DIR=runs/h1_open_loop/dac_manual_sweep/run_020
[ ! -s "$RUN_DIR/raw/serial.log" ] || { echo "Refusing to append to existing $RUN_DIR/raw/serial.log"; exit 1; }
mkdir -p "$RUN_DIR/control" "$RUN_DIR/raw" "$RUN_DIR/csv" "$RUN_DIR/reports" "$RUN_DIR/plots" "$RUN_DIR/derived/reference_prequal"
date -u | tee "$RUN_DIR/control/start-time.txt"
git status --short --branch | tee "$RUN_DIR/control/git-status-before-run.txt"
git rev-parse HEAD | tee "$RUN_DIR/control/git-head-before-run.txt"
git diff -- firmware host profiles schemas tests | tee "$RUN_DIR/control/source-diff-before-run.patch"
caffeinate -dimsu python3 -m host.otis_tools.capture_device \
  --auto-detect \
  --baud 115200 \
  --run-dir "$RUN_DIR" \
  --command-fifo "$RUN_DIR/control/commands.fifo" \
  --status-interval 60 \
  2>&1 | tee "$RUN_DIR/control/capture_device.stdout.log"
```

Leave this terminal running until the sequence completes and the final
`0x8000` acknowledgement has been captured.

## 3. Terminal 2 — Enforced Preflight

Run this immediately after capture starts. It validates the immutable
configuration and profile promptly, then waits—without starting the
sweep—until FC0 completes startup qualification:

```bash
RUN_DIR=runs/h1_open_loop/dac_manual_sweep/run_020
caffeinate -dimsu python3 "$RUN_DIR/run_020_preflight.py" \
  --fifo "$RUN_DIR/control/commands.fifo" \
  --raw-log "$RUN_DIR/raw/serial.log" \
  2>&1 | tee "$RUN_DIR/control/run_020_preflight.stdout.log"
```

Do not proceed unless it prints:

```text
RUN 020 PREFLIGHT PASSED
```

A failure cannot start or leave a sweep running; it first sends `SWEEP STOP`
and restores `0x8000`. The default FC0 qualification timeout is 30 minutes.

## 4. Terminal 2 — Run the Focused Six-Hour Profile

This reruns the same fail-closed preflight immediately before `SWEEP START`.
It restores `0x8000` on success, timeout, error, or `Ctrl-C`:

```bash
RUN_DIR=runs/h1_open_loop/dac_manual_sweep/run_020
caffeinate -dimsu python3 "$RUN_DIR/run_020_execute.py" \
  --fifo "$RUN_DIR/control/commands.fifo" \
  --raw-log "$RUN_DIR/raw/serial.log" \
  --timeout-s 22200 \
  2>&1 | tee "$RUN_DIR/control/run_020_sequence.stdout.log"
```

Expected profile duration is six hours: nine codes × 2400 seconds.

## 5. Terminal 3 — Useful Monitoring

High-level process status:

```bash
RUN_DIR=runs/h1_open_loop/dac_manual_sweep/run_020
tail -F "$RUN_DIR/control/capture_device.stdout.log" "$RUN_DIR/control/run_020_sequence.stdout.log"
```

DAC transitions, counts, and warnings:

```bash
RUN_DIR=runs/h1_open_loop/dac_manual_sweep/run_020
tail -F "$RUN_DIR/raw/serial.log" | rg --line-buffered '^(DAC|CNT),|^STS,.*,(WARN|ERROR|FATAL),'
```

On-demand snapshots:

```bash
RUN_DIR=runs/h1_open_loop/dac_manual_sweep/run_020
tail -n 30 "$RUN_DIR/csv/dac_steps.csv"
tail -n 10 "$RUN_DIR/csv/cnt.csv"
tail -n 20 "$RUN_DIR/csv/environment.csv"
tail -n 1200 "$RUN_DIR/csv/sts.csv" | awk -F, '$6 ~ /^(capture|pps|fc0|dac|sweep|resource_registry)/ {print}'
ls -lh "$RUN_DIR/raw/serial.log"
pmset -g assertions | rg 'caffeinate|PreventUserIdle|PreventSystemSleep'
```

Non-interrupting instrument queries:

```bash
RUN_DIR=runs/h1_open_loop/dac_manual_sweep/run_020
python3 -m host.otis_tools.send_command --fifo "$RUN_DIR/control/commands.fifo" "DAC?"
python3 -m host.otis_tools.send_command --fifo "$RUN_DIR/control/commands.fifo" "FC0?"
python3 -m host.otis_tools.send_command --fifo "$RUN_DIR/control/commands.fifo" "SWEEP?"
```

## 6. Partial or Final Analysis

This regenerates derived artifacts without modifying the raw log:

```bash
RUN_DIR=runs/h1_open_loop/dac_manual_sweep/run_020
python3 -m host.otis_tools.h1_characterize \
  "$RUN_DIR" \
  --settling-discard-s 900 \
  --warmup-s 1800 \
  --nominal-hz 10000000
python3 -m host.otis_tools.h1_latest_estimate "$RUN_DIR"
tail -n 30 "$RUN_DIR/csv/h1_characterization_points.csv"
tail -n 30 "$RUN_DIR/csv/h1_center_bracketed_slopes.csv"
```

## 7. Emergency Stop and Restore

Interrupt the sequence terminal first. If its automatic restoration cannot
reach the device:

```bash
RUN_DIR=runs/h1_open_loop/dac_manual_sweep/run_020
python3 -m host.otis_tools.send_command --fifo "$RUN_DIR/control/commands.fifo" "SWEEP STOP"
python3 -m host.otis_tools.send_command --fifo "$RUN_DIR/control/commands.fifo" "DAC SET 0x8000"
python3 -m host.otis_tools.send_command --fifo "$RUN_DIR/control/commands.fifo" "DAC?"
```

Do not stop capture until the `last_applied_code,0x8000` acknowledgement is in
the raw log.
