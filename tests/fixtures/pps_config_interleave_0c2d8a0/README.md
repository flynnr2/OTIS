# Retained PPS/CONFIG interleave

`health_records.csv` retains the exact `STS` records with `status_seq`
82426 through 82611 from the inhibited zero-write attempt held at
2026-09-12T12:47:02Z on frozen candidate
`0c2d8a085102267831528648cde88854db5b4866`.

Source evidence:

- diagnostic package: `inhibited-zero-write-20260912T120727Z-held-diagnostic-0c2d8a0`;
- source member: `context/serial-first-hold-lines-100200-101300.log`;
- retained range: Core 1 PPS snapshot generation 240, the interleaved Core 0
  `CONFIG?` response, and following ACTIVE snapshot generation 433;
- retained rows are unchanged; the CSV header only names the `health_v1`
  columns.

The original stream becomes invalid at status 82466 because the Core 0
configuration response repeats `pps_gate/boundary_owner` while the Core 1 PPS
snapshot is open. Tests retain that rejection, then project the proposed
single-writer repair by removing only the four Core 0 `pps_gate` configuration
records (82466 through 82469).
