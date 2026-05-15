# H1 VCOCXO + DAC Observe-Only Notes

Capture covers Stage 1 observe-only VCOCXO/OCXO input and Stage 2 unloaded DAC
output verification. DAC output was not connected to the oscillator tune input
during these measurements.

## Bench Measurements

Measured with multimeter at unloaded DAC output:

| Command | DAC code | Measured output |
|---|---:|---:|
| `DAC MID` | `0x8000` | 1.249 V |
| `DAC ZERO` | `0x7000` | 1.093 V |
| `DAC SET 0x8000` | `0x8000` | 1.249 V |
| `DAC SET 0x7000` | `0x7000` | 1.093 V |
| `DAC SET 0x9000` | `0x9000` | 1.405 V |

## Wiring State

- DAC-to-VCOCXO tune input: disconnected.
- VCOCXO/OCXO observation path: conditioned output into `D8/GPIO20/GPIN0`.
- Optional reference path: PPS into `D14/GPIO26/CH1`.
- Control mode: manual open-loop only.

## Initial Interpretation

- DAC output range over configured clamps is approximately 1.093 V to 1.405 V.
- Midscale output is approximately 1.249 V.
- `DAC SET 0x0000` was expected to be rejected by firmware clamps.
