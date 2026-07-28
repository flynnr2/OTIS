# run_018 Operator Checklist

Run directory: `runs/h1_open_loop/dac_manual_sweep/run_018`

Purpose: manually bracket where the CX317 crosses `10000000.000000 Hz` and
characterise the plant above the current verified automatic DAC range.

This is not a control-loop experiment. Leave `control_ready=false` and
`actuation_enabled=false`. Do not implement or enable SW2 control logic. Do not
automatically widen the firmware control limits.

## Pre-run Checklist

- [ ] Hardware configuration recorded.
- [ ] Firmware version recorded.
- [ ] Git commit recorded.
- [ ] Ambient temperature recorded, if available.
- [ ] Shield/enclosure description recorded.
- [ ] DMM connected to CX317 tuning voltage.
- [ ] Serial logging running through `capture_device`.
- [ ] FC0 healthy.
- [ ] PPS healthy.
- [ ] Startup confirms H1 observe mode, 300 s long gate, DAC support, D14 PPS,
      and D10 witness.
- [ ] SW2 remains disabled: `control_ready=false`,
      `actuation_enabled=false`.

## DAC Schedule

| Step | DAC Code | Applied? | Vc (V) | Estimated Hz | PPM | Valid | Settled | Notes |
| ---: | --- | --- | ---: | ---: | ---: | --- | --- | --- |
| 1 | `0x8000` baseline |  |  |  |  |  |  |  |
| 2 | `0x9000` |  |  |  |  |  |  |  |
| 3 | `0x9800` |  |  |  |  |  |  |  |
| 4 | `0xA000` |  |  |  |  |  |  |  |
| 5 | `0xA800` |  |  |  |  |  |  |  |
| 6 | `0xAC00` |  |  |  |  |  |  |  |
| 7 | `0xAE00` if not bracketed |  |  |  |  |  |  |  |

If the crossing occurs between two measured points, refine manually with
approximately `0x0200` or `0x0100` DAC-code steps until the crossing is well
bracketed.

## Per-step Reminders

- Apply the requested DAC code manually.
- Confirm the firmware reports the applied DAC code.
- Measure CX317 tuning voltage with the DMM.
- Wait for settling before using the estimates.
- Capture at least two or three valid 300 s windows at each code.
- Continue only if `estimator_valid == true`.
- Record the latest `local_pps_frequency_hz`.
- Record the latest `local_pps_ppm`.
- Record observations immediately in `control/operator_manual_log.md`.
- Note unusual behavior: temperature change, serial warning, enclosure opened,
  DMM disturbance, PPS warning, FC0 warning, or DAC acknowledgement issue.

## Latest Valid Estimate

After each analysis run:

```bash
RUN_DIR=runs/h1_open_loop/dac_manual_sweep/run_018
python3 -m host.otis_tools.h1_latest_estimate "$RUN_DIR" --dac-code 0xA400
```

Primary analysis file:

```text
csv/h1_count_frequency_estimates.csv
```

Primary observables:

- `local_pps_frequency_hz`
- `local_pps_ppm`
- `estimator_valid`

The crossing target is:

```text
local_pps_frequency_hz = 10000000.000000 Hz
```

## Crossing Summary

Highest code still below 10 MHz:

Lowest code above 10 MHz:

Estimated crossing code:

Recommended future automatic range:

Comments:

