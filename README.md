# OTIS
## Open Timing Instrumentation System

OTIS is an open timing instrumentation platform centered around deterministic,
reference-centric timing measurement and scientifically serious observability.

OTIS is not merely a GPSDO project. It is an instrumentation architecture in which
a disciplined timing reference becomes the timestamp fabric for event measurement,
analysis, generation, and comparison.

Initial focus:
- disciplined timing reference generation;
- deterministic event timestamping;
- provenance-rich telemetry;
- replayable datasets;
- scientifically rigorous observability.

Long-term direction:
- modular timing instrumentation ecosystem;
- FPGA-capable timing fabrics;
- advanced phase/frequency analysis;
- distributed timing instrumentation.

## Project Philosophy

OTIS is guided by several foundational principles:

- The CPU is never in the timing path.
- All timestamps belong to explicit reference domains.
- Raw telemetry is a primary scientific artifact.
- Replayability and provenance matter.
- Instrumentation semantics matter more than implementation convenience.
- Deterministic capture matters more than feature count.

## Documentation Structure

| Directory | Purpose |
|---|---|
| docs/00_FOUNDATIONS | conceptual foundations |
| docs/10_REFERENCE_ARCHITECTURE | timing and reference architecture |
| docs/20_TELEMETRY | telemetry philosophy and schemas |
| docs/30_ANALYSIS | statistical and metrological analysis |
| docs/40_HARDWARE | hardware architecture and stages |
| docs/50_SOFTWARE | host and software architecture |
| docs/60_EXPERIMENTS | methodology and characterization |
| docs/90_ROADMAP | staged implementation plans |

## License

MIT License.
