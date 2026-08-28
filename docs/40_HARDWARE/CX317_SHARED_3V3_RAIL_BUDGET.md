# CX317 Shared 3.3 V Rail Budget

## Purpose and scope

This note records the present, component-level power budget for the dedicated
3.3 V rail built for the CX317 VCOCX and its SN74LVC1G17 oscillator-output
buffer. It is a bench-planning and wiring record, not a ripple, transient,
thermal, or precision-noise qualification of that rail.

The installed rail is:

```text
USB-C breakout (5 V)
  -> Adafruit TPS62827 3.3 V buck-converter breakout
  -> nominal 120 ohm-at-100-MHz ferrite bead
  -> CX317 and SN74LVC1G17 buffer
```

The exact ferrite part number is not yet recorded. It may be a Murata
BLM31PG121SN1L, but that identity is unconfirmed. The observed loaded rail was
3.292 V. The TPS62827 breakout has a conservative 2 A continuous board rating.

## Current component budget

| Component | Supply requirement | Current or power evidence | Use on dedicated 3.3 V rail |
|---|---:|---:|---|
| CX317 VCOCX | 3.13 to 3.47 V recommended | OTIS safety screen uses a 4 W maximum; at the observed 3.292 V rail this is approximately 1.22 A | Installed principal load |
| SN74LVC1G17 10 MHz buffer | 1.65 to 5.5 V | 10 microampere maximum static `I_CC`; dynamic current depends on frequency, load, and edge rate | Installed; compatible |
| Adafruit Ultimate GPS / PA1616S | Breakout VIN 3.0 to 5.5 V; PA1616S VCC 3.0 to 4.3 V | 20 mA tracking; 25 mA acquisition at 3.3 V. An active antenna may require up to 28 mA from the module antenna supply. | Compatible |
| Future u-blox GNSS | Exact module/breakout dependent | Not budgeted until the exact part number, supply path, and antenna arrangement are selected | Conditional |
| Adafruit AD5693R DAC breakout | VIN 3 to 5 V | The local breakout guide does not state a board-level maximum current; expected to be small compared with CX317 but not credited as a quantified margin | Compatible |
| SHT41 environmental sensor | 1.08 to 3.6 V | 320 to 500 microampere while measuring; 2.2 microampere average at one measurement per second, heater off. Heater modes draw 6 to 100 mA. | Compatible if heater remains off |
| BMP280 environmental-sensor breakout | VIN 3 to 5 V | The local breakout guide does not state a board-level maximum current; it is not credited as a quantified margin | Compatible |
| Arduino Nano RP2040 Connect | USB 5 V or VIN 4 to 20 V with SJ4 intact. With **SJ4 cut**, a regulated 3.3 V source may be connected to `+3V3` and GND. | Arduino does not publish a maximum board-power value (`TBC`); Wi-Fi/Bluetooth can add burst current | Compatible only after cutting SJ4 and using the documented external-3.3-V arrangement |

At the conservative CX317 maximum, the nominal remaining TPS62827 board-rating
headroom is approximately `2.00 A - 1.22 A = 0.78 A`. That is sufficient in
principle for the listed low-power peripherals, but it is not a measurement of
combined cold-start, radio-burst, or rail-ripple behaviour.

## Nano external-3.3-V power path

Arduino's pinout documentation explicitly supports external 3.3 V operation:
cutting the connected **SJ4** solder jumper disconnects the Nano's onboard
3.3 V buck output, after which a regulated external 3.3 V source connects to
`+3V3` and its return to GND. This is the relevant documented arrangement for
sharing the dedicated TPS62827 rail with the Nano.

Do **not** connect the external 3.3 V rail with SJ4 still connected, because
that would parallel it with the Nano's onboard buck output. Once SJ4 is cut,
USB no longer powers the board; retain the external rail whenever USB is used
for data/programming. Confirm the required USB data/programming behaviour in a
brief bench check after the power-path change.

## Required verification before sharing the rail

Before adding all compatible peripherals to this rail:

1. Record cold-start and normal-operation buck-output current with the actual
   connected load, using the intended GNSS antenna configuration.
2. Keep Wi-Fi and Bluetooth disabled unless their current peaks are included in
   that measurement.
3. Confirm the CX317 supply remains within 3.13 to 3.47 V at its module pins.
4. Treat rail ripple/transients and ground-return behaviour as unqualified until
   measured; the earlier DC and cold-start observation does not establish them.
5. Re-run the direct capture-health screen after any power-path or grounding
   change.

## Sources

- `docs/datasheets/cx317.pdf`, p. 2.
- `docs/datasheets/sn74lvc1g17.pdf`, pp. 1 and 5.
- `docs/datasheets/CD PA1616S Datasheet.v05.pdf`, pp. 10 to 13.
- `docs/datasheets/adafruit-ad5693r-16-bit-dac-breakout-board.pdf`, pp. 4 to 7.
- `docs/datasheets/Adafruit.Datasheet_SHT4x.pdf`, pp. 1 and 9.
- `docs/datasheets/Adafruit-bmp280-barometric-pressure-plus-temperature-sensor-breakout.pdf`, pp. 6 and 11.
- Arduino Nano RP2040 Connect datasheet, pp. 6 to 7 and 11:
  <https://docs.arduino.cc/resources/datasheets/ABX00053-datasheet.pdf>.
- Arduino Nano RP2040 Connect pinout, SJ4 external-3.3-V instruction:
  <https://docs.arduino.cc/resources/pinouts/ABX00053-full-pinout.pdf>.
- `docs/60_EXPERIMENTS/COMPLETED_AND_HISTORICAL/CX317_PPS_GATED_ESTIMATOR_CONTROL_FINAL_READINESS.md`, rows for the buck output, USB-C source, ferrite bead, and rail-ripple limitation.
