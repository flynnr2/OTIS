# Pre-G17-Fix Capture Anomalies

This capture is preserved as separate negative evidence. Do not merge these
rows into the clean post-G17-fix `run_014` plant fit.

## FC0 Count Path

- `cnt.csv` contains 40 count windows.
- 26 count windows have `counted_edges=0` with flags `528`.
- The first zero-count window is `count_seq=8`, around 2251.777 s elapsed.
- `fc0_valid_for_control` remains `false` in the captured STS telemetry.

## Capture Transport

- `dropped_count` remains `0`.
- `error_flags` remains `0`.

## Classification

This is retained as pre-repair hardware-path negative evidence. The clean
post-fix capture in `run_014/csv/` supersedes it for plant fitting, but the raw
pre-fix files remain available for diagnosing the repaired G17 conditioning
fault history.
