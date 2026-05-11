# OTIS Arduino Nano RP2040 Connect sketch

This folder is the Arduino IDE entrypoint for OTIS firmware smoke tests.

## Board setup

- Board: **Arduino Nano RP2040 Connect**
- Core package: **Arduino Mbed OS Nano Boards**
- FQBN: `arduino:mbed_nano:nanorp2040connect`
- Serial monitor baud rate: `115200`

## Expected behavior

After boot, the sketch emits CSV header lines and sample `STS`, `EVT`, `REF`, and `CNT` records over USB serial.

## Optional CLI compile

```bash
arduino-cli compile --fqbn arduino:mbed_nano:nanorp2040connect firmware/arduino/otis_nano_rp2040_connect
```
