# Host Architecture

OTIS hosts are responsible for observability and analysis, not timing truth.

The preferred OTIS architecture preserves a strong separation between:

- deterministic timing capture;
- timing semantics and discipline;
- instrumentation services;
- archival and analysis.

---

# Conceptual Partitioning

```text
PIO / DMA          deterministic timing fabric
Core 0             timing and discipline core
Core 1             instrumentation services
OTIS Host          archival, replay, dashboards, analysis
```

The host is intentionally outside the timing-critical path.

---

# Host Responsibilities

Potential host responsibilities include:

- append-only logging;
- telemetry archival;
- replay tooling;
- dashboards;
- report generation;
- API exposure;
- long-run analysis;
- Allan deviation analysis;
- environmental correlation.

The host should be optimized for:

- observability;
- reproducibility;
- archival durability;
- scientific analysis.

---

# Linux Hosts

Linux hosts are optional but first-class.

Likely initial host environments:

| Host                         | Notes                                 |
|------------------------------|---------------------------------------|
| Raspberry Pi Zero 2 W        | likely preferred OTIS appliance host  |
| Raspberry Pi 4 / 5           | heavier analysis and dashboards       |
| Linux laptop/workstation     | excellent development environment     |

The OTIS timing appliance should still operate meaningfully without a Linux host.

However, Linux hosts significantly enhance:

- observability;
- replayability;
- analysis capability;
- archival workflows.

---

# Timing Isolation

Host activity must not influence:

- deterministic capture;
- timestamp correctness;
- timing semantics;
- discipline-loop behavior.

The host consumes timing telemetry.

The host does not establish timing truth.

---

# Instrument Service Separation

Optional instrumentation-service functionality may exist within the OTIS appliance.

Examples include:

- OLED displays;
- environmental sensors;
- status LEDs;
- optional local SD logging.

These should remain architecturally separated from:

- the timing fabric;
- deterministic capture;
- Core 0 timing work.

---

# Recommended Logging Architecture

Preferred architecture:

```text
OTIS timing appliance
        ↓
structured telemetry stream
        ↓
OTIS Host append-only archival
        ↓
replay and analysis tooling
```

This preserves:

- deterministic capture isolation;
- replayability;
- observability;
- analysis flexibility.

---

# Long-Term Direction

Future OTIS hosts may eventually support:

- distributed timing analysis;
- reference comparison dashboards;
- remote observability;
- historical telemetry indexing;
- automated characterization runs;
- calibration tooling;
- future OTIS Console functionality.

These remain host-layer responsibilities, not timing-fabric responsibilities.
