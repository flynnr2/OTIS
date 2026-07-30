# OTIS End-to-End Validation Plan

This plan validates the current Arduino Nano RP2040 Connect firmware and host
tooling after the count-observation refactor, anomaly telemetry, host reporting,
PPS-gated ratio backend implementation, and measurement-contract documentation.
It is a bench execution checklist, not a firmware feature request.

The validation owner should record the git commit, Arduino core version, board
serial/device path, wiring, oscillator/reference source, capture duration, and
all command output for every run. Raw serial logs are the behavioral source of
truth; generated CSV and reports are derived evidence.

## Pass/Fail Policy

A validation leg passes only when all of these are true:

- firmware compiles with the intended mode/backend flags;
- `BOOT` appears and `BOOT_FATAL` does not appear;
- `boot_capabilities,run_mode=Ready` appears only after all selected required
  capabilities report `Ready`;
- `resource_registry,valid=true` and `resource_registry,complete=true` both
  appear;
- any selected optional failure is reported as `OptionalDegraded`;
- serial output remains parseable as ordinary OTIS CSV/boot records;
- expected `EVT`, `REF`, `CNT`, `STS`, `DAC`, or `ENV` families appear for the
  selected mode;
- `capture,dropped_count` is zero for representative runs;
- PIO runs report `capture,pio_fifo_overflow_drop_count=0` when that status key
  is present;
- count-window anomalies are explicit in `CNT` flags and `STS` rows, never
  hidden by suppressed `CNT` rows;
- `python3 -m host.otis_tools.validate_run <run_dir>` exits zero;
- `python3 -m host.otis_tools.report_run <run_dir>` produces a report with no
  unexplained validation findings.

Fail the run and preserve artifacts when any of these occur:

- boot fatal, repeated reset loop, or serial framing loss;
- malformed CSV rows or unknown record tags;
- missing required record family for the mode;
- unflagged zero `counted_edges`;
- non-positive count gate windows;
- PPS cadence outside host sanity bounds after the startup interval;
- post-startup `fc0_fault=true` without an intentional anomaly test;
- `capture,dropped_count` or PIO FIFO overflow is nonzero.

## No-Hardware Dry Checks

Run these before any bench time:

```bash
python3 firmware/arduino/validation/scripts/run_no_hardware_checks.py
```

The script expands to:

```bash
python3 -m pytest

python3 tools/firmware_matrix.py

python3 tools/otis_wire_validate.py \
  firmware/arduino/validation/golden/synthetic_sw1_excerpt.txt \
  --profile synthetic

python3 tools/otis_wire_validate.py \
  firmware/arduino/validation/golden/gpio_loopback_sw1_excerpt.txt \
  --profile gpio_loopback

python3 tools/otis_wire_validate.py \
  firmware/arduino/validation/golden/gpin0_observe_sw1_excerpt.txt \
  --profile gpin0_observe

python3 -m host.otis_tools.validate_run examples/h0_pps_tcxo_synthetic
python3 -m host.otis_tools.report_run examples/h0_pps_tcxo_synthetic
```

Expected result: all commands exit zero. The report command writes Markdown to
stdout and should include raw event, count observation, and health summaries.
The example run may warn about intentionally unpopulated fixture provenance or a
missing `COMPLETE` marker; those warnings are acceptable for this dry check.

## Compile Matrix

The versioned intentional matrix is
`firmware/arduino/firmware_matrix.json`. It contains the qualification,
observe-only, characterization, explicit laboratory actuator, and
representative capture/count profiles, plus known-invalid guard tuples. It
intentionally does not compile the theoretical cross-product.

```bash
python3 tools/firmware_matrix.py --check-environment
python3 tools/firmware_matrix.py --list
python3 tools/firmware_matrix.py
```

The matrix passes only when every supported profile compiles and every invalid
tuple fails with its named diagnostic. Each supported profile writes its
binary, generated provenance header, build log, and
`firmware_build_provenance.json` below the ignored
`build/firmware_matrix/<profile>/` directory.

## Run Directory and Capture Pattern

For short validation captures, the existing monitor-to-splitter path is enough:

```bash
arduino-cli monitor -p /dev/cu.usbmodemXXXX -c baudrate=115200 \
  | python3 -m host.otis_tools.capture_serial \
      --template examples/h0_gps_pps \
      --run-dir runs/validation/gps_pps_run_001 \
      --run-id gps_pps_run_001
```

For longer H1 and anomaly runs, prefer `capture_device` so raw serial, CSV
splitting, host status, reconnect markers, and optional command FIFO handling
are captured in one place:

```bash
python3 -m host.otis_tools.capture_device \
  --device /dev/cu.usbmodemXXXX \
  --run-dir runs/validation/h1_long_gate_run_001 \
  --command-fifo runs/validation/h1_long_gate_run_001/commands.fifo
```

After every run:

```bash
python3 -m host.otis_tools.validate_run runs/validation/<run_id>
python3 -m host.otis_tools.report_run runs/validation/<run_id>
```

Pass criteria: validation exits zero; report generation completes; raw serial,
CSV files, manifest, and report output are retained.

## Bench Leg 1: Synthetic USB Sanity

Purpose: prove USB serial, boot/status records, headers, parser compatibility,
and deterministic synthetic `EVT`, `REF`, and `CNT` rows.

Wiring: USB only.

Duration: 10 to 20 seconds after boot.

Firmware: compile/upload `OTIS_SW1_MODE_SYNTHETIC_USB`.

Expected telemetry:

- `system,mode=SW1_SYNTHETIC_USB`;
- CSV header rows for raw events, count observations, health, DAC, and ENV when
  enabled;
- synthetic `EVT`, `REF`, and `CNT` rows;
- no `BOOT_FATAL`;
- no parser errors.

Pass criteria: `tools/otis_wire_validate.py --profile synthetic` passes on the
raw log and host run validation/report commands pass.

## Bench Leg 2: GPIO Loopback

Purpose: prove live local GPIO edge capture without external timing hardware.

Wiring:

- jumper `D7` to `D10`;
- no oscillator input required;
- USB connected.

Duration: at least 60 seconds.

Firmware: compile/upload `OTIS_SW1_MODE_GPIO_LOOPBACK`.

Expected telemetry:

- `system,mode=SW1_GPIO_LOOPBACK`;
- live `EVT` rows on `CH0`;
- monotonic `event_seq`;
- `capture,dropped_count=0`;
- if PIO FIFO is enabled, `capture,pio_fifo_overflow_drop_count=0`.

Pass criteria: host validation/report pass; expected CH0 `EVT` rows are present.

## Bench Leg 3: GPS PPS Reference Capture

Purpose: prove reference capture on `CH1`.

Wiring:

- conditioned GPS PPS to `D14` / GPIO26 / `CH1`;
- common ground between GPS/reference source and RP2040 board;
- use a 3.3 V logic-safe PPS input.

Duration: minimum 120 seconds after GPS has a stable PPS. Prefer 10 minutes for
representative PPS cadence evidence.

Firmware: compile/upload `OTIS_SW1_MODE_GPS_PPS`; run both IRQ and PIO FIFO
variants if bench time permits.

Expected telemetry:

- `system,mode=SW1_GPS_PPS`;
- rising-edge `REF` rows on `CH1`;
- PPS intervals approximately one second in `rp2040_timer0` ticks;
- no unexpected `EVT` or `CNT` requirement for this mode;
- no capture drops or PIO overflow.

Pass criteria: host PPS cadence validation passes after startup; report shows
reference/PPS summary without unexplained anomalies.

## Bench Leg 4: TCXO/OCXO Count Observation, Existing Backend

Purpose: prove the current FC0/GPIN0 count-observation path and anomaly
telemetry before testing PPS-gated ratio behavior.

Wiring:

- oscillator output conditioned to 3.3 V logic and connected to `D8` / GPIO20 /
  GPIN0 / `CH2`;
- optional GPS PPS on `D14` / `CH1`;
- common ground across oscillator, conditioner, reference, and RP2040 board.

Duration: minimum 15 minutes for startup-inhibit and clean-window evidence.
Use at least 60 seconds for a quick smoke run.

Firmware: compile/upload `OTIS_SW1_MODE_TCXO_OBSERVE` using the default
FC0/GPIN0 backend.

Expected telemetry:

- `CNT` rows on `CH2`;
- `source_domain=h0_tcxo_16mhz` for H0 TCXO runs;
- `fc0,window_invalid_reason=none` on clean windows;
- `fc0,fc0_observed_valid=true` once clean observations are present;
- `fc0,fc0_valid_for_control=true` only after startup inhibit and clean-window
  qualification;
- `fc0,fc0_fault=false` after clean post-inhibit windows.

Pass criteria: host validation/report pass, no unflagged zero counts, no
post-startup `fc0_fault=true` in a nominal run.

## Bench Leg 5: PIO Long-Gate H1 Mode

Purpose: prove H1 raw-edge long-gate counting, PPS coexistence, DAC telemetry,
and H1 characterization summary.

Wiring:

- H1 OCXO output conditioned to 3.3 V logic and connected to `D8` / GPIO20 /
  GPIN0 / `CH2`;
- GPS PPS or lab PPS to `D14` / `CH1`;
- AD5693R DAC on I2C if DAC telemetry/sweep validation is in scope;
- common ground across all equipment;
- verify conditioning does not invert or divide unexpectedly, or document the
  inversion/division ratio in run notes.

Duration:

- smoke: at least two H1 long gates, currently at least 10 minutes with the
  default 300 s long gate;
- characterization: at least the loaded sweep dwell plan plus warmup. Prefer
  60 minutes or longer for stable slope/drift evidence.

Firmware: compile/upload `OTIS_SW1_MODE_H1_OCXO_OBSERVE` with
`OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE`.

Expected telemetry:

- `capture,tcxo_counter_backend=pio_long_gate_gpio20`;
- `CNT` rows on `CH2` with `source_domain=h1_ocxo_open_loop`;
- `REF` rows on `CH1` when PPS is wired;
- `STS` rows for `fc0,last_window_invalid_reason`,
  `fc0,consecutive_bad_windows`, `fc0,total_bad_windows`, and `fc0,fc0_fault`;
- DAC `STS`/`DAC` rows if DAC is enabled;
- no post-startup invalid windows in a nominal run.

Post-run commands:

```bash
python3 -m host.otis_tools.validate_run runs/validation/h1_long_gate_run_001
python3 -m host.otis_tools.report_run runs/validation/h1_long_gate_run_001
python3 -m host.otis_tools.h1_characterize runs/validation/h1_long_gate_run_001 --nominal-hz 10000000
```

Pass criteria: validation/report pass; H1 characterization writes its summary
and points artifacts; the report identifies PPS-calibrated clock use when valid
PPS rows exist.

## Bench Leg 6: PPS-Gated Ratio Backend

Purpose: prove the new PPS-gated count ratio backend is hardware-clean before
using it as a metrology path.

The authoritative Phase 5 acceptance procedure, fixed thresholds, independent
source typing, uncertainty requirements, sealing steps, and disposition rules
are in
`docs/60_EXPERIMENTS/PHASE_5_PPS_GATED_BACKEND_BENCH_RUNBOOK.md`. This leg is a
smoke precursor and cannot by itself qualify the backend.

Prerequisite: compile with
`OTIS_TCXO_COUNTER_BACKEND=OTIS_TCXO_COUNTER_BACKEND_PPS_GATED_RATIO` and
confirm boot/status telemetry names the PPS-gated backend.

Wiring:

- PPS/reference to `D14` / `CH1`;
- oscillator-under-test conditioned to `D8` / GPIO20 / `CH2`;
- common ground;
- stable PPS source already locked before capture starts.

Duration:

- smoke: 120 seconds;
- acceptance: 30 minutes minimum;
- soak: 2 to 4 hours before relying on the backend for future design decisions.

Expected telemetry:

- `capture,tcxo_counter_backend=pps_gated_ratio`;
- `pps_gate,backend=pps_gated_ratio`;
- `pps_gate,boundary_owner=pps_gpio_irq`;
- `pps_gate,aperture_backend=pps_isr_stop_sample_restart_v1`;
- `pps_gate,backend_qualified=false` in the qualification candidate;
- `pps_gate,state` transitions through `armed` / `open` in nominal operation;
- `pps_gate,valid=true` for bounded clean windows;
- `pps_gate,reference_validity=valid` and
  `pps_gate,count_validity=valid` independently for clean windows;
- typed `pps_gate,reference_reason` and `pps_gate,count_reason`;
- `pps_gate,ratio_available=true` for valid nonzero count windows;
- `pps_gate,missing_pps_count=0` after startup in nominal operation;
- `pps_gate,pps_interval_anomaly_count=0` after startup in nominal operation;
- `pps_gate,count_saturated_count=0`;
- `pps_gate,control_eligible=false` throughout the unqualified candidate;
- `REF` rows on `CH1` and `CNT` rows on `CH2`;
- count windows align to sequence-continuous atomic PPS boundaries by
  construction or are explicitly withheld/flagged as invalid;
- no unflagged zero `counted_edges`;
- no non-positive or implausible gate duration findings;
- `fc0,fc0_fault=false` in nominal operation.

Pass criteria:

- compile, host validation, report generation, and the focused 60-window quiet
  plus 60-window loaded contract pass;
- count-derived frequency agrees with the existing FC0 or PIO long-gate backend
  within the expected bench tolerance recorded in the run notes;
- anomaly counters remain zero after startup in a nominal run.

Rollback criteria:

- If PPS-gated runs show missing PPS, unstable PPS interval selection,
  non-positive windows, unflagged zero counts, unexplained count discontinuity,
  post-startup invalid windows, counter saturation, or disagreement with the
  existing backend beyond bench tolerance, do not use the PPS-gated backend for
  characterization.
- Rebuild with `OTIS_TCXO_COUNTER_BACKEND=OTIS_TCXO_COUNTER_BACKEND_FC0_GPIN0`
  for H0 TCXO or `OTIS_TCXO_COUNTER_BACKEND=OTIS_TCXO_COUNTER_BACKEND_PIO_LONG_GATE`
  for H1 OCXO.
- Preserve the failed PPS-gated raw log and report as a fault fixture candidate.

## Bench Leg 7: Host Capture, Validation, and Reporting

Purpose: prove the host pipeline can ingest, split, validate, and summarize all
bench modes.

For each run:

```bash
python3 -m host.otis_tools.validate_run runs/validation/<run_id>
python3 -m host.otis_tools.report_run runs/validation/<run_id>
```

Expected output:

- `OK ...` lines for each required CSV contract;
- report includes raw event summary, reference/PPS summary, count observation
  summary, health status summary, and anomalies section;
- H1 runs include PPS-calibrated count/frequency context when usable PPS rows
  exist.

Pass criteria: both commands exit zero and any report anomaly is explained in
the operator notes.

## Bench Leg 8: Anomaly and Fault Reporting

Purpose: prove invalid observations are emitted, flagged, and visible in host
reports.

Nominal anomaly injections:

- no oscillator connected for one count window;
- oscillator disconnected after startup inhibit has elapsed;
- PPS disconnected during a PPS-gated ratio run;
- deliberately invalid divided GPIO IRQ count source if using
  `OTIS_TCXO_COUNTER_BACKEND_GPIO_IRQ`.

Expected telemetry:

- raw `CNT` rows are still emitted for bounded invalid windows;
- PPS missing-stop faults without an honest close boundary are reported through
  `pps_gate` `STS` rows rather than a fabricated clean `CNT`;
- `flags` include the appropriate invalid bit such as
  `SOURCE_HEALTH_SUSPECT`, `INPUT_STUCK_LOW`, or `GATE_INCOMPLETE`;
- `fc0,window_invalid_reason` or `fc0,last_window_invalid_reason` names the
  condition;
- `fc0,consecutive_bad_windows` and `fc0,total_bad_windows` increase;
- after startup inhibit, `fc0,post_startup_invalid_window=true` and
  `fc0,fc0_fault=true` for invalid windows.
- for PPS-gated missing-PPS injection, `pps_gate,missing_pps_count` increases
  and `pps_gate,ratio_available=false`.

Pass criteria: anomaly state is visible as ordinary `STS` rows and report
findings match the injected fault. No bounded invalid observation may disappear
by suppressing `CNT`.

## Recommended First Bench Run

Start with the lowest-risk full pipeline:

1. Compile and upload `OTIS_SW1_MODE_SYNTHETIC_USB`.
2. Capture 10 to 20 seconds over USB only.
3. Run `tools/otis_wire_validate.py --profile synthetic` on the raw log.
4. Run `host.otis_tools.validate_run` and `host.otis_tools.report_run`.

Only after that passes, run GPIO loopback for 60 seconds, then GPS PPS for 120
seconds, then TCXO/OCXO count observation. Do not begin PPS-gated ratio
acceptance until the existing FC0/PIO count backend is clean on the same bench
wiring.
