# Startup census capture replay fixture

This compact fixture preserves the byte-exact health records that exercise the
first two ACTIVE snapshots from the startup-census diagnostic.

- Source: `runs/diagnostics/startup-census/startup-census-hold-539ff6a-20260912T074349Z/files/health.prefix.csv`
- Source SHA-256: `b8a1bb625abb1587210f4432fc40d22f39241e9f3b2353d0bff7f35278806070`
- ACTIVE generation 1: source lines 360–412, byte offsets 34980–40458
  (inclusive start, exclusive end). It completed before this fixture contains
  any `pps_gate` status.
- PPS-gate snapshot before generation 2: source lines 563–631, byte offsets
  54115–60149.
- ACTIVE generation 2: source lines 649–700, byte offsets 61627–66976
  (inclusive start, exclusive end).

`health_records.csv` retains the original health header and record bytes in
source order, omitting unrelated records. The regression sends each retained
record through the production live-status publisher and reader; it is not a
synthetic health mapping.
