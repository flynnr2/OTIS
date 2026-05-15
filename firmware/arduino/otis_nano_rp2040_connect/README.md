# OTIS Arduino Nano RP2040 Connect sketch

This folder is the Arduino IDE entrypoint for OTIS firmware smoke tests on the
Arduino Nano RP2040 Connect.

## Board setup

- Board: **Arduino Nano RP2040 Connect**
- Core package: **Raspberry Pi Pico/RP2040/RP2350** by Earle F. Philhower, III
- Boards Manager URL:
  `https://github.com/earlephilhower/arduino-pico/releases/download/global/package_rp2040_index.json`
- Expected FQBN: `rp2040:rp2040:arduino_nano_connect`
- Serial monitor baud rate: `115200`

The sketch intentionally rejects Arduino Mbed OS Nano Boards at compile time.
OTIS targets the Philhower Arduino-Pico core because it exposes the RP2040/Pico
SDK surface, supports `setup1()` / `loop1()` multicore sketches, and leaves a
practical route to PIO-backed capture while retaining an Arduino entrypoint.

If the local Arduino CLI uses a different board identifier, confirm it with:

```bash
arduino-cli board listall | grep -i "Nano RP2040"
```

## SW1 bring-up modes

Select one bring-up mode in `otis_config.h` with `OTIS_SW1_BRINGUP_MODE`.
The default is `SW1_SYNTHETIC_USB`. The config header is the preferred workflow
for Arduino IDE builds; CLI `-D` overrides still work for scripted builds.

| Mode | Purpose | Records |
|---|---|---|
| `SW1_SYNTHETIC_USB` | USB serial, framing, parser, and validation sanity | synthetic `STS`, `EVT`, `REF`, `CNT` |
| `SW1_GPIO_LOOPBACK` | prove GPIO edge capture before external hardware | live `EVT` on `CH0` |
| `SW1_GPS_PPS` | capture Adafruit Ultimate GPS PPS | live `REF` on `CH1` |
| `SW1_TCXO_OBSERVE` | observe the TCXO on `D8` / `GPIO20` / `GPIN0`, with PPS capture if wired | hardware frequency-counter `CNT` on `CH2`, `REF` on `CH1` |
| `OTIS_SW1_MODE_H1_OCXO_OBSERVE` (`H1_OCXO_OBSERVE_OPEN_LOOP`) | manual H1 OCXO lab observation with optional AD5693R DAC commands and explicit open-loop sweeps | hardware frequency-counter `CNT` on `CH2`, `REF` on `CH1`, DAC `STS`/`DAC` telemetry |

The live GPIO/PPS paths are first bring-up interrupt captures. Their emitted
timestamps use `rp2040_timer0` and carry `TIMESTAMP_RECONSTRUCTED`; they are not
yet the later PIO/DMA hardware-latched path. TCXO observe uses the RP2040
frequency counter on `GPIN0` by default so a raw 16 MHz signal does not create a
GPIO interrupt storm. The alternate `OTIS_TCXO_COUNTER_BACKEND_GPIO_IRQ`
backend is only for deliberately divided, interrupt-safe test signals.

`H1_OCXO_OBSERVE_OPEN_LOOP` keeps the same architecture boundary: sparse PPS
edges, if wired, use the normal edge-capture backend, while the raw OCXO input
on `D8` / `GPIO20` / `GPIN0` uses the RP2040 FC0/gated-count path and emits
`CNT` records. It is an open-loop lab instrument mode only. Firmware does not
implement PPS-derived steering, GPSDO locking, holdover, PI/PID correction, or
temperature compensation.

SW1 capture mode: irq_reconstructed. Timestamps are suitable for bench
validation and protocol bring-up, not final PIO/DMA metrology.

## SW1.5a PIO FIFO capture

SW1.5a adds an opt-in PIO FIFO backend for the live edge-capture modes. IRQ
capture remains the default rollback path:

```cpp
#define OTIS_CAPTURE_BACKEND OTIS_CAPTURE_BACKEND_IRQ
```

Enable the experimental PIO path with:

```cpp
#define OTIS_CAPTURE_BACKEND OTIS_CAPTURE_BACKEND_PIO_FIFO
```

or with a CLI override:

```bash
arduino-cli compile --fqbn rp2040:rp2040:arduino_nano_connect \
  --build-property compiler.cpp.extra_flags="-DOTIS_SW1_BRINGUP_MODE=OTIS_SW1_MODE_GPS_PPS -DOTIS_CAPTURE_BACKEND=OTIS_CAPTURE_BACKEND_PIO_FIFO" \
  firmware/arduino/otis_nano_rp2040_connect
```

The SW1.5a PIO backend uses one PIO0 state machine and observes rising edges
only. It pushes compact edge words into the PIO RX FIFO; firmware drains the
FIFO in `loop()` and emits the same `EVT` or `REF` records used by the IRQ
backend. The emitted timestamp is attached by firmware when the FIFO is drained,
so metadata reports `capture_mode=pio_fifo_cpu_timestamped` and
`timestamp_latch=pio_edge_detect_cpu_timestamped`. This is not final
hardware-latched timestamping.

Guardrail: the PIO FIFO backend is only for sparse edge streams such as GPS PPS,
slow GPIO loopback, or future low-rate event inputs. It must not be used to
enqueue raw 10 MHz / 16 MHz CXO edges. Raw oscillator input on `D8` / `GPIO20` /
`GPIN0` should be observed with the RP2040 frequency-counter / FC0 /
gated-count path instead.

PIO input selection follows the selected bring-up mode:

| Mode | PIO input | Expected records |
|---|---|---|
| `SW1_GPIO_LOOPBACK` | `D10` / GPIO5 / `CH0` | rising-edge `EVT` rows |
| `SW1_GPS_PPS` | `D14` / GPIO26 / `CH1` | rising-edge `REF` rows |
| `SW1_TCXO_OBSERVE` | `D14` / GPIO26 / `CH1` | rising-edge `REF` rows plus existing `CNT` rows when TCXO counting is configured |
| `H1_OCXO_OBSERVE_OPEN_LOOP` | `D14` / GPIO26 / `CH1` | rising-edge `REF` rows plus FC0/gated-count `CNT` rows for raw OCXO observation |

Sparse edges map to the PIO FIFO edge backend. Raw CXO on `GPIN0` maps to the
FC0/gated-count backend and emits `CNT`, not one FIFO event per oscillator edge.

The boot/status stream includes `capture_backend`, `pio_init`, `pio_gpio`,
`pio_edge`, `pio_fifo_drained_event_count`, `pio_fifo_empty_count`,
`pio_fifo_overflow_drop_count`, and `pio_fifo_max_drain_batch`. A nonzero
overflow/drop count means the PIO RX FIFO was not drained fast enough; the count
is a status indicator, not a precise missing-edge total.

Suggested first bench sequence:

1. GPIO loopback: jumper `D7` to `D10`, build `SW1_GPIO_LOOPBACK` with
   `OTIS_CAPTURE_BACKEND_PIO_FIFO`, and confirm `EVT` rows and PIO counters.
2. GPS PPS: wire conditioned GPS PPS to `D14`, build `SW1_GPS_PPS` with the PIO
   backend, and confirm `REF` rows and host PPS cadence checks.
3. TCXO/count observation: use `SW1_TCXO_OBSERVE` only for the existing
   count-observation path; do not feed raw high-rate oscillator edges into the
   SW1.5a PIO FIFO edge path.

DMA, hardware-latched timestamp transfer, both-edge capture, and higher-rate
capture fabric work are intentionally deferred to SW1.5b and later.

## H1 open-loop DAC and FC0 commands

H1 DAC support is compile-time gated:

```cpp
#define OTIS_SW1_BRINGUP_MODE OTIS_SW1_MODE_H1_OCXO_OBSERVE
#define OTIS_ENABLE_DAC_AD5693R 1
```

The firmware uses a minimal direct I2C write path for AD5693R rather than adding
an Arduino library dependency. The default I2C address is `0x4C`; `0x4E` is also
accepted:

```cpp
#define OTIS_DAC_AD5693R_I2C_ADDRESS 0x4Cu
```

The DAC output is bounded by compile-time clamps. Defaults are deliberately
conservative and do not permit rail-to-rail sweeps:

```cpp
#define OTIS_DAC_MIN_CODE 0x7000u
#define OTIS_DAC_MAX_CODE 0x9000u
#define OTIS_H1_DAC_SWEEP_TINY_STEP_CODES 0x0400u
```

The built-in `tiny_plus_minus_1` and `tiny_plus_minus_2` profiles use small
bench-visible steps around the clamp midpoint, not 1-LSB metrology steps.

Manual commands are read from the USB serial monitor. Terminate each command
with newline or carriage return:

```text
HELP
DAC?
DAC LIMITS?
DAC SET 0x8000
DAC SET 32768
DAC MID
DAC ZERO
FC0?
SWEEP?
SWEEP LOAD center_only
SWEEP LOAD tiny_plus_minus_1
SWEEP LOAD tiny_plus_minus_2
SWEEP START
SWEEP STOP
SWEEP STEP
SWEEP CLEAR
SWEEP ADD 0x8000 5000
```

`DAC SET <code>` accepts decimal or hex raw 16-bit DAC codes. Values outside
`OTIS_DAC_MIN_CODE` and `OTIS_DAC_MAX_CODE` are rejected and logged with `STS`
warning rows; firmware does not silently move to a clamped value. `DAC ZERO`
sets the configured minimum clamp, not electrical ground unless the clamp is
explicitly configured that way. `DAC MID` sets the midpoint of the configured
clamp window.

The boot/status stream reports H1 open-loop mode, FC0 measurement period,
nominal OCXO frequency assumption, DAC enable state, I2C address, clamp values,
DAC init success/failure, and accepted/rejected DAC command telemetry. `FC0?`
prints the latest gated-count summary as structured `STS` rows. The regular
`CNT` records remain the primary FC0 observation output.

`OTIS_ENABLE_H1_DAC_SWEEP` adds deterministic open-loop sweep commands. Sweeps
are never started on boot; `SWEEP START` is required. Built-in profiles are
deliberately tiny and centered inside the configured DAC clamps. Requests that
would cross clamps are rejected and logged as `DAC` rows with `safety_reject`.
During an active sweep, firmware emits `DAC` rows for `dwell_start`,
`fc0_window`, and `dwell_complete` so each nearby `CNT` observation can be
attributed to the active step index and DAC code without changing the `CNT`
schema.

Wiring summary for H1:

| Signal | Arduino Nano RP2040 Connect pin |
|---|---:|
| sparse PPS/reference input, optional | `D14` / GPIO26 / `CH1` |
| raw OCXO observation input | `D8` / GPIO20 / `GPIN0` / `CH2` |
| AD5693R DAC I2C SDA/SCL | board I2C pins for `Wire` |

Do not route the raw OCXO into the PIO FIFO edge path. Raw OCXO observation is
FC0/gated-count only.

During the boot banner, firmware emits `STS` provenance rows for schema version,
firmware name/version/git commit, board target, Arduino core, bring-up mode,
capture mode, nominal reference frequencies, pin mapping, and compile-time
feature flags. `OTIS_FIRMWARE_GIT_COMMIT` defaults to `unknown`; scripted builds
may override it with `-DOTIS_FIRMWARE_GIT_COMMIT=\"<hash>\"`.

Status LED support is compiled out by default. Set
`OTIS_ENABLE_STATUS_LED` to `1` in `otis_config.h` only for local bring-up
visibility; the disabled path does not require any additional LED libraries.
When enabled, this smoke sketch uses the plain RP2040-accessible `LED_BUILTIN`
for a brief boot indication and later USB/config/debug status indication.
The startup self-test is enabled by default whenever status LED support is
enabled. It blinks `LED_BUILTIN`. Set `OTIS_ENABLE_STATUS_LED_BOOT_TEST` to `0`
to skip the self-test while keeping later status LED behavior.

RP2040 raw boot diagnostics are controlled by `OTIS_ENABLE_RP2040_BOOT_DIAG`.
When enabled, firmware emits one `BOOTDIAG,v=1` register snapshot after USB
serial startup and before normal OTIS records. See
`docs/50_SOFTWARE/RP2040_BOOT_DIAGNOSTICS.md` for the field schema and reset
forensics limits.

The boot path also emits compact `BOOT` telemetry when USB serial is available.
Serial startup is bounded by `OTIS_SERIAL_WAIT_MS` and defaults to 250 ms after
`Serial.begin(115200)`. If the host has not opened USB serial by then, firmware
continues booting and capture setup is not held indefinitely waiting for USB
enumeration.

Safe mode is controlled by persistent boot breadcrumbs. A successful boot is
defined as reaching and completing `RunMode`; that clears the consecutive
failure count. A boot that stops before `RunMode` records a fatal code and
increments the count. Once the stored count reaches
`OTIS_SAFE_MODE_FAILURE_THRESHOLD` on the next reset, firmware enters
diagnostics-only safe mode instead of starting normal capture services.

Boot-hardening test knobs are disabled by default:

- `OTIS_FORCE_BOOT_FAIL_BEFORE_CLOCKS`
- `OTIS_FORCE_BOOT_FAIL_BEFORE_CAPTURE`
- `OTIS_FORCE_BOOT_FAIL_BEFORE_RUN_MODE`

For bench testing, upload one forced-failure build and reset the board repeatedly.
The default threshold is 3 recorded failed boots. Upload a build with all forced
failure knobs disabled to return to normal boot; the next successful `RunMode`
boot clears the failure count.

## Frozen SW1 channel pin convention

The SW1 live-capture pass uses this Arduino pin convention:

| OTIS channel | Role | Arduino pin |
|---:|---|---:|
| `CH0` | generic pulse/event input | `D10` |
| `CH1` | PPS/reference input | `D14` |
| `CH2` | divided/gated oscillator observation | `D8` / `GPIO20` / `GPIN0` |

`SW1_GPIO_LOOPBACK` additionally drives `D7` as a local output. Jumper `D7` to
`D10` for that mode only.

These are frozen firmware conventions for SW1 on the H0 prototype. Electrical
conditioning, voltage limits, and final bench wiring remain hardware
responsibilities.

`D9` / `GPIO21` / `GPOUT0` is reserved for internal clock visibility.
`D2` / `GPIO25` / `GPOUT3` is reserved for the secondary diagnostic clock.
Do not assign either pin to general live-capture inputs.

## CLI compile and upload

```bash
arduino-cli compile --fqbn rp2040:rp2040:arduino_nano_connect firmware/arduino/otis_nano_rp2040_connect
```

For scripted builds, config values can be overridden without editing
`otis_config.h`:

```bash
arduino-cli compile --fqbn rp2040:rp2040:arduino_nano_connect \
  --build-property compiler.cpp.extra_flags=-DOTIS_SW1_BRINGUP_MODE=OTIS_SW1_MODE_SYNTHETIC_USB \
  firmware/arduino/otis_nano_rp2040_connect

arduino-cli compile --fqbn rp2040:rp2040:arduino_nano_connect \
  --build-property compiler.cpp.extra_flags=-DOTIS_SW1_BRINGUP_MODE=OTIS_SW1_MODE_GPIO_LOOPBACK \
  firmware/arduino/otis_nano_rp2040_connect

arduino-cli compile --fqbn rp2040:rp2040:arduino_nano_connect \
  --build-property compiler.cpp.extra_flags=-DOTIS_SW1_BRINGUP_MODE=OTIS_SW1_MODE_GPS_PPS \
  firmware/arduino/otis_nano_rp2040_connect

arduino-cli compile --fqbn rp2040:rp2040:arduino_nano_connect \
  --build-property compiler.cpp.extra_flags=-DOTIS_SW1_BRINGUP_MODE=OTIS_SW1_MODE_TCXO_OBSERVE \
  firmware/arduino/otis_nano_rp2040_connect

arduino-cli compile --fqbn rp2040:rp2040:arduino_nano_connect \
  --build-property compiler.cpp.extra_flags="-DOTIS_SW1_BRINGUP_MODE=OTIS_SW1_MODE_H1_OCXO_OBSERVE -DOTIS_ENABLE_DAC_AD5693R=1" \
  firmware/arduino/otis_nano_rp2040_connect
```

Upload by adding the detected port:

```bash
arduino-cli upload -p /dev/cu.usbmodemXXXX --fqbn rp2040:rp2040:arduino_nano_connect \
  --build-property compiler.cpp.extra_flags=-DOTIS_SW1_BRINGUP_MODE=OTIS_SW1_MODE_GPS_PPS \
  firmware/arduino/otis_nano_rp2040_connect
```

Capture serial into a run directory by piping monitor output through the host
splitter:

```bash
arduino-cli monitor -p /dev/cu.usbmodemXXXX -c baudrate=115200 \
  | python3 -m host.otis_tools.capture_serial \
      --template examples/h0_gps_pps \
      --run-dir runs/h0_gps_pps_001 \
      --run-id h0_gps_pps_001

python3 -m host.otis_tools.validate_run runs/h0_gps_pps_001
python3 -m host.otis_tools.report_run runs/h0_gps_pps_001
```

For a SW1.5a PIO run directory, keep the same host pipeline and set the
manifest capture mode to `pio_fifo_cpu_timestamped`, for example:

```bash
python3 -m host.otis_tools.capture_serial \
  --template examples/h0_gps_pps \
  --run-dir runs/h0_sw1_5a_pio/gps_pps/run_001 \
  --run-id h0_sw1_5a_pio_gps_pps_run_001

python3 -m host.otis_tools.validate_run runs/h0_sw1_5a_pio/gps_pps/run_001
python3 -m host.otis_tools.report_run runs/h0_sw1_5a_pio/gps_pps/run_001
```

For committed representative runs, generate the report, remove
`capture_in_progress.flag` if present, and create `COMPLETE` after validation.
