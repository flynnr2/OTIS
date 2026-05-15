# Validation Report

Run validation parses the captured `EVT`, `REF`, `CNT`, and `STS` files.

Known validation finding:

- The first PPS interval is approximately 32M `rp2040_timer0` ticks instead of
  the expected 16M ticks. This is treated as a startup/capture artifact for this
  H1 bench run because subsequent PPS intervals return to approximately 16M
  ticks.

Known warnings:

- `COMPLETE` marker is intentionally absent.
- Firmware/host provenance fields are not populated in the manifest.
- `csv/evt.csv` is header-only; no generic event input was used.

Useful rows captured:

- `csv/ref.csv`: PPS/reference rows present.
- `csv/cnt.csv`: VCOCXO/OCXO FC0 count observations present.
- `csv/sts.csv`: DAC command/status telemetry present.
