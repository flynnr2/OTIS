# Run 019 Plant-Model Results

## Status

Run 019 is the current broad-range H1 DAC-to-frequency reference. It provides
analysis-useful evidence across nearly the full configured DAC range, but it is
not a sealed fixture or a control-authoritative local plant model.

The uploaded Arduino IDE build used the configuration present in
`otis_config.h`:

- DAC range: `0x0100..0xFF00`
- centre/return code: `0x8000`
- slope dwell: 900 s
- tiny-step size: `0x0200`
- long gate: 300 s

This differed from the intended run manifest, which described
`0x6000..0xFC00`, a centre near `0xAE00`, 2400 s dwells, and `0x0300` tiny
steps. The acquired evidence is therefore interpreted according to the
configuration that actually ran. Run 020 is the focused local-crossing
confirmation using the intended header-only Arduino IDE configuration.

## Measurement health

The run produced one continuous 12.89 h session:

- 155 of 155 non-zero count windows were valid
- 46,394 of 46,394 PPS intervals were valid
- no parser, reconnect, capture-drop, saturation, or overflow events occurred
- the final D14/D10 counter comparison reported zero delta and `MATCHING`
- six warnings were confined to expected startup qualification

Run 019 is substantially cleaner than the earlier rollover-affected evidence.
However, `COMPLETE`, an evidence manifest, pre-run Git snapshots, and operator
DMM observations were not captured. It is suitable for plant analysis, but not
for claiming a fully sealed or directly voltage-traceable fixture.

## Broad DAC response

Representative settled medians were:

| DAC code | Median frequency (Hz) |
|---:|---:|
| `0x0100` | 9,999,992.480189 |
| `0x4080` | 9,999,995.285562 |
| `0x8000` | approximately 9,999,997.99 to 9,999,998.03 |
| `0xBF80` | 10,000,000.699916 |
| `0xFF00` | 10,000,003.514548 |

The first nine-point wide sweep gives:

```text
frequency_hz =
    9,999,992.464549134
    + 0.000169064163979 * dac_code
R² = 0.999919771
residual standard deviation = 0.029423806 Hz
```

Four drift-cancelled slope estimates span
`0.000165320..0.000170028 Hz/code`. Combined with the Run 018 voltage
calibration, this corresponds to approximately `4.38..4.50 Hz/V`.

These results validate monotonic, approximately linear broad-range response
over the exercised hardware range. They do not establish that the same slope
is an adequate local dynamic model for closed-loop design.

## 10 MHz crossing

Crossing estimates from the broad data span approximately
`0xADC3..0xAEF6`, with median `0xADDA`. The global fit predicts `0xAE1C`.
Using the Run 018 DAC-voltage fit, the crossing is approximately 1.692 V.

The sampled data do not contain a close measured bracket: the highest sampled
point below 10 MHz was `0x8400`, and the lowest sampled point above it was
`0xBF80`. Tiny steps around `0x8000` were noise- and drift-dominated because
that centre is well below the crossing. Run 020 therefore targets the
`0xAE00` region directly.

The earlier `0x7000..0x9000` concept must not be treated as a viable automatic
control envelope: its upper limit does not reach the observed 10 MHz crossing.

## Settling, hold, and environment

Primary analysis used a 300 s settling discard because the actual dwell was
900 s. A strict 900 s discard leaves no settled windows; those strict outputs
are retained as evidence rather than silently relaxed.

At the available 300 s gate granularity, most wide transitions appear settled
by the first post-discard midpoint (about 150 s), while one return transition
appears closer to 450 s. These observations are useful for planning but are
not sufficiently resolved to serve as loop time constants.

The final `0x8000` hold contained 99 windows over 8.17 h:

- median: 9,999,997.974452 Hz
- standard deviation: 0.043665 Hz
- fitted drift: +0.002104 Hz/h (+0.000210 ppm/h)

Temperature ranged from 28.327 °C to 29.566 °C. Simple residual correlation
was negligible, but this does not demonstrate thermal independence.

## Applicability and next use

Run 019 supports:

- broad monotonicity and linearity
- approximate plant gain
- locating the 10 MHz crossing near `0xAE00`
- validation of the counting and diagnostic path over a long run
- planning focused observe-only measurements

Run 019 does not support:

- active steering
- a final automatic DAC envelope
- a local crossing slope or hysteresis model
- resolved settling constants
- direct DMM-traceable voltage claims

Run 020 is the focused crossing-region experiment. Until it is analysed, the
programme remains ready for observe-only work, not active control.
