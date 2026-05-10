# Host Architecture

OTIS hosts are responsible for observability and analysis, not timing truth.

## Host Responsibilities

Potential responsibilities:
- append-only logging;
- telemetry archival;
- replay tooling;
- dashboards;
- report generation;
- API exposure.

## Linux Hosts

Linux hosts are optional but first-class.

Likely initial host environments:
- Raspberry Pi Zero 2 W;
- desktop Linux systems.

## Timing Isolation

Host activity must not influence:
- deterministic capture;
- timestamp correctness;
- timing semantics.
