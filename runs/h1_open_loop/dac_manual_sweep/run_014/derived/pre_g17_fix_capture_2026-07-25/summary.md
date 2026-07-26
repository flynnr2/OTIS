# Pre-G17-Fix Capture Summary

This directory preserves the capture taken before the SN74LVC1G17 breakout
repair. It is negative hardware evidence and is intentionally separate from the
post-fix `run_014` plant-fit inputs.

## Artifact Inventory

- `ref.csv`: 11948 REF rows.
- `cnt.csv`: 40 CNT rows.
- `sts.csv`: 48239 STS rows.
- `dac_steps.csv`: 71 DAC rows.
- `environment.csv`: 23894 ENV rows.
- `evt.csv`: header only.

## Negative Evidence

- 26 of 40 CNT rows have `counted_edges=0` and flags `528`.
- The first zero-count CNT row is `count_seq=8`, around 2251.777 s elapsed.
- STS contains 26 `window_invalid_reason` diagnostic groups and 350 WARN rows.
- Host/capture counters remain clean: `dropped_count=0` and `error_flags=0`.
- DAC sweep telemetry is present, but this capture is excluded from the clean
  `run_014` plant characterization because it predates the G17 repair.
