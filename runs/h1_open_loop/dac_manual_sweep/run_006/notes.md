# H1 VCOCXO + DAC Sweep Notes

Capture covers Stage 3 connected DAC-to-CX317 control-input verification and
open-loop DAC sweep telemetry. The AD5693R output was connected through the
existing series resistor to CX317 pin 4 (`Vc`) during this run.

## Wiring State

- DAC output: connected through series resistor to CX317 pin 4 / `Vc`.
- VCOCXO output: conditioned path into `D8/GPIO20/GPIN0`.
- PPS/reference input: connected to `D14/GPIO26/CH1`.
- Control mode: manual open-loop only; no PPS-derived steering.

## Bench Measurements At CX317 Pin 4

Measured with multimeter at the actual VCOCXO control input:

| Command | DAC code | Measured `Vc` |
|---|---:|---:|
| `DAC SET 0x7000` | `0x7000` | 1.091 V |
| `DAC SET 0x8000` | `0x8000` | 1.246 V |
| `DAC SET 0x9000` | `0x9000` | 1.401 V |
| `DAC SET 0x8000` repeat | `0x8000` | 1.246 V |

The connected `Vc` node tracked the expected DAC output range and remained
inside the CX317 operating control-voltage range of 0.0 V to 3.3 V.

## Sweep Coverage

The log includes structured `DAC` rows for:

- `tiny_plus_minus_1`-style centered sweeps around `0x8000`.
- `tiny_plus_minus_2`-style centered sweep extending to `0x8800` and `0x7800`.

The host report and H1 characterization outputs were regenerated from this raw
serial log.

## Known Artifact

The first PPS interval after startup is about 32M `rp2040_timer0` ticks instead
of 16M ticks. This is treated as a startup/capture artifact; subsequent PPS
intervals are approximately 16M ticks. The run is useful for H1 sweep analysis
but should not be marked as a clean fixture without accounting for that startup
interval.

## Interpretation

- DAC-to-`Vc` wiring is healthy.
- `CNT`, `REF`, `STS`, and `DAC` telemetry are all present.
- The configured DAC sweep range is conservative and safe for the CX317 control
  input.
- Frequency response is not resolved by the current short FC0 gate; ppm/V should
  remain unclaimed until a higher-resolution measurement path or longer gate is
  available.
