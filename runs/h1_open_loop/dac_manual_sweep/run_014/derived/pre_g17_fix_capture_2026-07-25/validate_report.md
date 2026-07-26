# Pre-G17-Fix Capture Validation Note

This preserved capture does not include a standalone manifest, so it is not a
separate `validate_run` target. It is retained under `run_014/derived/` as
negative hardware evidence only.

Observed recoverable checks from the preserved CSVs:

- `ref.csv`: 11948 REF rows.
- `cnt.csv`: 40 CNT rows, including 26 zero-count rows with flags `528`.
- `sts.csv`: host/capture counters show `dropped_count=0` and `error_flags=0`.
- Classification: pre-G17-repair count-path failure evidence, excluded from the
  clean post-fix plant fit.
