# Arduino Nano RP2040 Connect Clock Pin Strategy

This note documents the OTIS MVP clock-pin strategy for the Arduino Nano RP2040
Connect / ABX00053.

The Nano RP2040 Connect uses an onboard 12 MHz MEMS oscillator for the RP2040
XIN path. OTIS MVP firmware keeps the RP2040 running from that onboard
oscillator. The onboard MEMS oscillator is the platform clock for firmware, USB,
PIO, DMA, and normal RP2040 execution.

An external GPSDO or OCXO is treated as a separate instrument/reference clock.
It enters the RP2040 as an observable signal for measurement and correlation,
not as a replacement for the board clock.

## Usable Header Clock Pins

| Arduino pin | RP2040 GPIO | RP2040 clock function | OTIS use |
|---|---:|---|---|
| D8 | GPIO20 | CLOCK GPIN0 | external OCXO/GPSDO reference input |
| D9 | GPIO21 | CLOCK GPOUT0 | RP2040 internal clock diagnostic output |
| D2 | GPIO25 | CLOCK GPOUT3 | secondary RP2040 internal clock diagnostic output |

D8 / GPIO20 / GPIN0 is the preferred non-surgical reference-clock ingress for
OTIS MVP hardware on the Nano RP2040 Connect.

Firmware guardrail: the raw 10 MHz / 16 MHz CXO input on GPIN0 is consumed by
the single-state-machine PPS snapshot programme. The PIO X register counts
edges and only one cumulative word is pushed per accepted PPS; individual
oscillator edges are never enqueued. FC0 remains useful for diagnostics but
does not own a PPS aperture.

GPOUT0 and GPOUT3 expose RP2040 internal clocks for diagnostics, validation,
and external measurement. They are not evidence that the external reference has
become the RP2040 system clock.

## Internal Board Clock Paths

GPOUT1 / GPIO23 is used internally by the microphone clock path and is not
header-exposed for OTIS use.

GPIN1 / GPIO22 is used internally by the microphone data path and is not
header-exposed for OTIS use.

## Clock-Domain Model

For the OTIS MVP:

- onboard MEMS oscillator means platform clock;
- GPSDO/OCXO means instrument/reference clock;
- GPIN0 brings the external reference into the RP2040 for measurement and
  correlation;
- GPOUT0 and GPOUT3 expose RP2040 internal clocks for diagnostics, validation,
  and external measurement;
- host-side analysis must preserve clock-domain provenance.

The external reference should remain visible as a measured input domain. Host
artifacts and analysis should distinguish RP2040 platform-clock observations
from GPSDO/OCXO reference-clock observations.

## PPS and Loopback Pins

| Arduino pin | RP2040 GPIO | Normal role | Loopback-only role |
|---|---:|---|---|
| D14 | GPIO26 | physical GPS PPS input; shared read-only by PIO and GPIO REF observer | pseudo-PPS input |
| D10 | GPIO5 | external event/edge input to be measured against the disciplined oscillator | unchanged input |
| D3 | GPIO15 | unclaimed input/high impedance | deterministic pseudo-PPS output |

The `pseudo_pps_loopback` build is the only profile allowed to drive D3. Before
arming it, disconnect the real GPS PPS output and wire D3 through an
approximately 1 kΩ series resistor to D14. Stop, completion, reset, underflow,
and resource faults all return D3 to high impedance. Never enable the loopback
driver against a connected GPS output.

## Electrical Requirements

The external reference input must be conditioned before it reaches RP2040 GPIO:

- use 3.3 V CMOS logic levels;
- do not feed 5 V logic into RP2040 GPIO;
- do not feed raw sine directly into RP2040 GPIO;
- use a comparator, squarer, or suitable buffer for sine or low-slew signals;
- provide a common ground between the external reference equipment and the
  Nano RP2040 Connect.

For firmware bring-up, start with a divided reference if that is simpler. A
1 MHz or 100 kHz conditioned reference is acceptable before attempting a 10 MHz
input.

## Initial Wiring Recommendation

```text
GPSDO / OCXO
  -> conditioning / divider
  -> D8 / GPIO20 / CLOCK GPIN0
```

The conditioning/divider block is responsible for voltage compatibility, edge
quality, and any temporary frequency division needed for early firmware tests.

## Non-Goals / Not MVP

The OTIS MVP on the Nano RP2040 Connect does not include:

- XIN modification;
- replacing the onboard oscillator;
- rerooting `clk_sys`.

Those are not required for the MVP clock-pin strategy and should not be treated
as the default path for early OTIS hardware.
