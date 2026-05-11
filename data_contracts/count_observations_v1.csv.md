# count_observations_v1.csv

## Purpose

`count_observations_v1.csv` records gated or windowed counts of a high-rate source such as a TCXO, OCXO, VCXO, divided XCXO, or frequency-output module.

It exists because a 10 MHz or 16 MHz oscillator must not be represented as a raw emitted edge stream. The firmware should count edges in hardware or a deterministic capture fabric and emit compact observations.
