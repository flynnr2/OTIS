# Telemetry Philosophy

OTIS telemetry is intended to function as a scientific record.

## Telemetry Goals

Telemetry should support:
- replayability;
- offline reconstruction;
- long-run analysis;
- provenance tracking;
- reproducible experimentation.

## Raw First

Raw telemetry is preferred over aggressively processed summaries.

## Append-Only Philosophy

Logs should be append-only wherever practical.

## Schema Versioning

Schemas should evolve explicitly and conservatively.

Breaking changes must be versioned.

## Human and Machine Readability

Telemetry should support:
- automated tooling;
- direct inspection;
- long-term archival.

Both CSV and structured machine formats may coexist.
