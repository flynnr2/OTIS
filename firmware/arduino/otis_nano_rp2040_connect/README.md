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

Select one bring-up mode at compile time with `OTIS_SW1_BRINGUP_MODE`.
The default is `SW1_SYNTHETIC_USB`.

| Mode | Purpose | Records |
|---|---|---|
| `SW1_SYNTHETIC_USB` | USB serial, framing, parser, and validation sanity | synthetic `STS`, `EVT`, `REF`, `CNT` |
| `SW1_GPIO_LOOPBACK` | prove GPIO edge capture before external hardware | live `EVT` on `CH0` |
| `SW1_GPS_PPS` | capture Adafruit Ultimate GPS PPS | live `REF` on `CH1` |
| `SW1_TCXO_OBSERVE` | count a conditioned/divided TCXO observation input, with PPS capture if wired | gated `CNT` on `CH2`, `REF` on `CH1` |

The live GPIO/PPS paths are first bring-up interrupt captures. Their emitted
timestamps use `rp2040_timer0` and carry `TIMESTAMP_RECONSTRUCTED`; they are not
yet the later PIO/DMA hardware-latched path. The TCXO mode emits count windows
instead of pretending that every 16 MHz edge is a host-useful raw event.

Status LED support is compiled out by default. Build with
`OTIS_ENABLE_STATUS_LED=1` only for local bring-up visibility; the disabled path
does not require RGB LED, NINA, or WiFi LED libraries.
When enabled, this smoke sketch uses the plain RP2040-accessible `LED_BUILTIN`
for a brief boot indication and later USB/config/debug status indication.
The Nano RP2040 Connect also has an RGB LED, but it is part of the NINA WiFi
module. There appear to be compatibility issues between the Earle Philhower
`arduino-pico` RP2040 core and the WiFiNINA/Arduino_SpiNINA libraries, so OTIS
does not currently drive the NINA RGB LED.
The startup self-test is enabled by default whenever status LED support is
enabled. It blinks `LED_BUILTIN`. Build with
`OTIS_ENABLE_STATUS_LED_BOOT_TEST=0` to skip the self-test while keeping later
status LED behavior.

RP2040 boot diagnostics are also compiled out by default. Build with
`OTIS_ENABLE_RP2040_BOOT_DIAG=1` to emit one `BOOTDIAG,v=1` register snapshot
after USB serial startup and before normal OTIS records. See
`docs/50_SOFTWARE/RP2040_BOOT_DIAGNOSTICS.md` for the field schema and reset
forensics limits.

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

Explicit mode builds:

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

To validate the RGB LED path, compile with both LED macros enabled:

```bash
arduino-cli compile --fqbn rp2040:rp2040:arduino_nano_connect \
  --build-property compiler.cpp.extra_flags="-DOTIS_ENABLE_STATUS_LED=1 -DOTIS_STATUS_LED_USE_NINA_RGB=1" \
  firmware/arduino/otis_nano_rp2040_connect
```
