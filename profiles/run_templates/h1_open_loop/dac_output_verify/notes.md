# H1 Open-Loop Run Notes

## Purpose

Verify DAC I2C presence, reference behavior, gain mode, and measured output voltage before any closed-loop work.

## Hardware Setup

Record DAC wiring, I2C address, supply/reference voltage, meter connection, load state, oscillator connection state, and grounding.

## Safety Limits

Record the safe DAC code range and measured unloaded output range before connecting the OCXO tune input.

## Capture Command

Record the exact host command used for capture or host-side DAC verification.

## Observations

Summarize ACK/address checks, measured voltages, output monotonicity checks, and any load-dependent behavior.

## Anomalies

Record I2C errors, unexpected gain/reference behavior, unsafe voltages, or host-side interruptions.

## Follow-up

List actions needed before connecting DAC output to the oscillator tune input.
