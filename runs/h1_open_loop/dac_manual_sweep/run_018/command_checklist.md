# run_018 Operator Command Checklist

Run all commands from the repository root.

```bash
RUN_DIR=runs/h1_open_loop/dac_manual_sweep/run_018
date
git status --short --branch | tee "$RUN_DIR/control/git-status-before-run.txt"
git rev-parse HEAD | tee "$RUN_DIR/control/git-head-before-run.txt"
ls -1 /dev/cu.usbmodem*
arduino-cli board list
```

```bash
FQBN=rp2040:rp2040:arduino_nano_connect
SKETCH=firmware/arduino/otis_nano_rp2040_connect
FIRMWARE_GIT_COMMIT="$(git rev-parse --short=12 HEAD)"
OTIS_H1_FLAGS="-DOTIS_FIRMWARE_GIT_COMMIT=\\\"${FIRMWARE_GIT_COMMIT}\\\" -DOTIS_SW1_BRINGUP_MODE=OTIS_SW1_MODE_H1_OCXO_OBSERVE -DOTIS_CAPTURE_BACKEND=OTIS_CAPTURE_BACKEND_IRQ -DOTIS_TCXO_COUNTER_BACKEND=OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE -DOTIS_ENABLE_PPS_DUAL_OBSERVER=1 -DOTIS_ENABLE_DAC_AD5693R=1 -DOTIS_ENABLE_H1_DAC_SWEEP=1 -DOTIS_DAC_MIN_CODE=0x7000u -DOTIS_DAC_MAX_CODE=0xAE00u -DOTIS_H1_LONG_GATE_PERIOD_US=300000000u -DOTIS_ENABLE_ENV_SENSORS=1 -DOTIS_ENABLE_ENV_SHT4X=1 -DOTIS_ENABLE_ENV_BMP280=1"
arduino-cli compile --fqbn "$FQBN" --build-property "compiler.cpp.extra_flags=${OTIS_H1_FLAGS}" "$SKETCH"
SERIAL_DEVICE=/dev/cu.usbmodemXXXX
arduino-cli upload -p "$SERIAL_DEVICE" --fqbn "$FQBN" --build-property "compiler.cpp.extra_flags=${OTIS_H1_FLAGS}" "$SKETCH"
```

```bash
[ ! -s "$RUN_DIR/raw/serial.log" ] || { echo "Refusing to append to existing non-empty $RUN_DIR/raw/serial.log"; exit 1; }
mkdir -p "$RUN_DIR/control" "$RUN_DIR/raw" "$RUN_DIR/csv" "$RUN_DIR/reports" "$RUN_DIR/plots" "$RUN_DIR/derived/reference_prequal"
caffeinate -dimsu python3 -m host.otis_tools.capture_device --auto-detect --baud 115200 --run-dir "$RUN_DIR" --command-fifo "$RUN_DIR/control/commands.fifo" 2>&1 | tee "$RUN_DIR/control/capture_device.stdout.log"
```

Second terminal:

```bash
RUN_DIR=runs/h1_open_loop/dac_manual_sweep/run_018
pmset -g assertions | grep -E 'caffeinate|PreventUserIdle|PreventSystemSleep'
python3 -m host.otis_tools.send_command --fifo "$RUN_DIR/control/commands.fifo" "DAC?"
python3 -m host.otis_tools.send_command --fifo "$RUN_DIR/control/commands.fifo" "DAC LIMITS?"
python3 -m host.otis_tools.send_command --fifo "$RUN_DIR/control/commands.fifo" "FC0?"
python3 -m host.otis_tools.send_command --fifo "$RUN_DIR/control/commands.fifo" "SWEEP?"
tail -n 200 "$RUN_DIR/csv/sts.csv" | awk -F, '$6=="pps_d14" || $6=="pps_d10" || $6=="pps_dual_observer" || $6=="dac" || $6=="fc0"{print}'
tail -n 5 "$RUN_DIR/csv/cnt.csv"
```

Manual DAC commands:

```bash
python3 -m host.otis_tools.send_command --fifo "$RUN_DIR/control/commands.fifo" "DAC SET 0x8000"
python3 -m host.otis_tools.send_command --fifo "$RUN_DIR/control/commands.fifo" "DAC SET 0x9000"
python3 -m host.otis_tools.send_command --fifo "$RUN_DIR/control/commands.fifo" "DAC SET 0x9800"
python3 -m host.otis_tools.send_command --fifo "$RUN_DIR/control/commands.fifo" "DAC SET 0xA000"
python3 -m host.otis_tools.send_command --fifo "$RUN_DIR/control/commands.fifo" "DAC SET 0xA800"
python3 -m host.otis_tools.send_command --fifo "$RUN_DIR/control/commands.fifo" "DAC SET 0xAC00"
python3 -m host.otis_tools.send_command --fifo "$RUN_DIR/control/commands.fifo" "DAC SET 0xAE00"
```

Live monitoring:

```bash
tail -n 200 "$RUN_DIR/csv/sts.csv" | awk -F, '$6=="dac"{print}'
tail -n 1000 "$RUN_DIR/csv/sts.csv" | awk -F, '$6 ~ /^pps/ {print}'
tail -n 5 "$RUN_DIR/csv/cnt.csv"
tail -n 20 "$RUN_DIR/csv/environment.csv"
ls -lh "$RUN_DIR/raw/serial.log"
```

Analysis and latest estimate:

```bash
python3 -m host.otis_tools.validate_run "$RUN_DIR" | tee "$RUN_DIR/reports/validate_report.md"
python3 -m host.otis_tools.report_run "$RUN_DIR" --output "$RUN_DIR/reports/summary.md" --json "$RUN_DIR/reports/summary.json"
python3 -m host.otis_tools.h1_characterize "$RUN_DIR" --settling-discard-s 900 --warmup-s 3600 --nominal-hz 10000000
python3 -m host.otis_tools.h1_latest_estimate "$RUN_DIR" --dac-code 0xA400
```

Safe restore:

```bash
python3 -m host.otis_tools.send_command --fifo "$RUN_DIR/control/commands.fifo" "DAC SET 0x8000"
python3 -m host.otis_tools.send_command --fifo "$RUN_DIR/control/commands.fifo" "DAC?"
tail -n 50 "$RUN_DIR/csv/sts.csv" | awk -F, '$6=="dac"{print}'
```
