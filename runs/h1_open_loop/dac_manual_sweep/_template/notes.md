# H1 Open-Loop Run Notes

## Purpose

Capture manually commanded DAC steps and the OCXO frequency response to derive open-loop tuning sensitivity.

## Hardware Setup

Record oscillator identity, DAC part/address/reference, control network, measured control voltage, output conditioning, reference source, and RP2040 observation pin.

## Safety Limits

Record the verified DAC code range, control-voltage range, and any current or thermal limits before sweeping.

## Capture Command

Record the exact host command used for capture and the sweep command sequence,
including `SWEEP LOAD`, `SWEEP START`, and any `SWEEP STOP` or manual
`SWEEP STEP` actions.

## Observations

Record each DAC code, measured DAC output, measured control voltage, dwell time, frequency estimate, and settling behavior. Cross-check `csv/dac_steps.csv` for `dwell_start`, `fc0_window`, and `dwell_complete` attribution.

## Anomalies

Record unsafe voltages, non-monotonic response, output dropouts, conditioning failures, dropped records, or host-side interruptions.

## Follow-up

List actions needed before deriving ppm/V or choosing later SW2 control limits.
