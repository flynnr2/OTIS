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

## Expected behavior

After boot, the sketch emits CSV header lines and sample `STS`, `EVT`, `REF`,
and `CNT` records over USB serial. This is still a synthetic SW1 smoke emitter,
not live GPIO, PPS, or oscillator capture.

Status LED support is compiled out by default. Build with
`OTIS_ENABLE_STATUS_LED=1` only for local bring-up visibility; the disabled path
does not require RGB LED, NINA, or WiFi LED libraries.

## H0 channel pin convention

The first live-capture pass should use this Arduino pin convention:

| OTIS channel | Role | Arduino pin |
|---:|---|---:|
| `CH0` | generic pulse/event input | `D2` |
| `CH1` | PPS/reference input | `D3` |
| `CH2` | divided/gated oscillator observation | `D4` |

These are firmware conventions for the H0 prototype. Electrical conditioning,
voltage limits, and final bench wiring remain hardware responsibilities.

## Optional CLI compile

```bash
arduino-cli compile --fqbn rp2040:rp2040:arduino_nano_connect firmware/arduino/otis_nano_rp2040_connect
```
