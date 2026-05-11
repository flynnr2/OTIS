# derived_intervals_v1.csv

## Purpose

`derived_intervals_v1.csv` stores intervals derived from raw observations.

Examples:

- pulse widths;
- rising-to-rising intervals;
- PPS-to-PPS intervals;
- phase differences;
- reconstructed half-cycles;
- oscillator frequency estimates.

## Design Rule

Derived intervals are not raw observations.

Every derived row should preserve provenance back to:

- source record family;
- source sequence numbers;
- timing domains;
- profile assumptions.

## Philosophy

OTIS intentionally separates:

```text
raw observation
→ derived interval
→ analysis/report conclusion
```

so replayability and scientific provenance survive future reinterpretation.
