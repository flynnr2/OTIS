# Run 014 Anomalies

Generated after the full analysis pass on 2026-07-26.

## PPS / REF Cadence

- `csv/ref.csv` contains 2719 short PPS intervals out of 87736 intervals.
- The anomalies are explicitly gated in `manifest.json` as diagnostic-only,
  not control-eligible REF/PPS evidence. The validator only accepts this run
  when the observed PPS anomaly class, count, index span, and event-sequence
  span match that manifest gate.
- The anomalies are not startup-only. Capture starts around firmware uptime
  691 s, while anomalous intervals occur from about 744.812 s to 1916.805 s
  elapsed. They are early relative to the full capture, but they extend beyond
  the startup inhibit period.
- The anomalies are concentrated in 16 clusters, especially a dense burst from
  about 1692.806 s to 1796.805 s elapsed, plus smaller groups through about
  1916.805 s elapsed. No short REF/PPS interval is observed after that point in
  the 23.6-hour-class capture.
- `h1_characterize` ignored these intervals for PPS calibration and completed
  using 85017 valid PPS intervals.
- Current instrumentation cannot distinguish GPS receiver absence from GPIO,
  capture hardware, IRQ, FIFO, DMA, or firmware-path extra/missed REF edges.
- Classification: source-related versus capture-path-related remains
  unresolved. The anomaly is closed for H1 plant-fit purposes by excluding
  affected REF/PPS intervals from calibration/control eligibility, not by
  assigning root cause.

## Count / DAC / Capture Health

- Count observations are clean: 284 `CNT` rows, zero zero-edge rows, and all
  `CNT` flags are `16`.
- Capture transport is clean: `dropped_count` and `error_flags` stay at zero;
  the raw log reports `parser_errors=0` and `reconnect_count=0`.
- DAC sweep completed all 18 passes: 90 dwell starts, 90 dwell completes, and 18
  `complete` rows.
- DAC voltage fields in `csv/dac_steps.csv` are empty, so characterization used
  the manifest measured DAC voltage model.

## Characterization Caveats

- One early DAC characterization point is marked `degraded` because it overlaps
  the PPS anomaly burst; the remaining 89 points are marked `normal`.
- The pre-G17-fix capture is preserved under
  `derived/pre_g17_fix_capture_2026-07-25/` as separate negative hardware
  evidence and is excluded from the clean post-fix plant fit.
- `ended_at_utc` and `host_tool_version` were backfilled from recoverable
  artifacts. Firmware version and firmware git commit remain unknown and are
  intentionally not invented.
