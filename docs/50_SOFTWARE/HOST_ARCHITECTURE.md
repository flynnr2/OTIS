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

For unattended hardware runs the host serial path has a single owner:

```text
USB serial device
        ↓
host.otis_tools.capture_device
        ↓
raw/serial.log
        ↓
manifest-driven CSV splitter
        ↓
validate_run / report_run
```

`capture_device` is the only process that opens `/dev/cu.usbmodem*`. Other host
tools operate on the raw log, CSV files, manifest, and reports emitted into the
run directory. This preserves forensic ordering and avoids competing serial
readers.

## Aperiodic Serial Commands

Some H1 characterization workflows need occasional host commands while a run is
being captured, for example `DAC MID`, `DAC SET <code>`, `SWEEP START`, or
`SWEEP STOP`. These commands should still preserve single serial ownership:
`capture_device` remains the only process that opens the USB serial device.

The preferred shape is a small command ingress owned by `capture_device`, with a
separate one-shot helper writing validated commands into that ingress:

```text
one-shot host command helper
        ↓
run-local command FIFO or socket
        ↓
host.otis_tools.capture_device
        ↓
USB serial device
```

The v0.1 host interface is:

```bash
python3 -m host.otis_tools.capture_device \
  --device /dev/cu.usbmodem101 \
  --run-dir runs/.../run_001 \
  --command-fifo runs/.../run_001/control/commands.fifo

python3 -m host.otis_tools.send_command \
  --fifo runs/.../run_001/control/commands.fifo \
  "DAC MID"
```

This command path is intentionally not a general serial terminal. It should only
accept known atomic commands whose effects are represented by firmware telemetry:

- `HELP`
- `DAC?`
- `DAC LIMITS?`
- `DAC MID`
- `DAC ZERO`
- `DAC SET <decimal-or-0xhex-code>`
- `FC0?`
- `SWEEP?`
- `SWEEP LOAD <known-profile>`
- `SWEEP START`
- `SWEEP STOP`
- `SWEEP STEP`
- `SWEEP CLEAR`

Open-ended command construction, such as arbitrary `SWEEP ADD` sequences, should
not be part of this path unless a later runbook defines a bounded, auditable use
case. Prefer firmware-builtin sweep profiles for repeatable characterization.

Every command decision must be auditable in `raw/serial.log` through
`# OTIS_HOST` markers. At minimum, rejected commands should record the rejection
reason, and accepted commands should record the normalized command before serial
write and the write result afterward. The command bytes themselves should not be
inserted into the raw device byte stream because that would pollute replay and
CSV parsing. Firmware `STS`/`DAC` records remain the command acknowledgement
source; `capture_device` should not block capture waiting for synchronous
responses.

---

# SW1 Bring-Up Host Path

For SW1/H0 bring-up, host tooling intentionally stays small:

- `python3 -m host.otis_tools.capture_serial` reads firmware serial CSV from
  stdin and splits `EVT`/`REF`, `CNT`, and `STS` rows into a run directory based
  on a template manifest. It creates `capture_in_progress.flag` while capture is
  active and removes it after stdin closes cleanly.
- `python3 -m host.otis_tools.capture_device` owns a USB serial device for
  unattended runs, appends raw bytes and host reconnect markers to
  `raw/serial.log`, frames complete lines, and feeds the same CSV splitter used
  by `capture_serial`. It reconnects after USB/RP2040 resets with bounded
  buffering and drops only incomplete lines with explicit forensic markers.
- `python3 -m host.otis_tools.validate_run` checks manifest/profile consistency,
  known SW1 modes, known H0 channels, CSV headers, malformed rows, record types,
  required fields, monotonic sequences/timestamps, PPS cadence sanity, and TCXO
  count sanity. It warns for in-progress captures, missing `COMPLETE` markers,
  missing optional artifacts, empty CSVs, and unpopulated provenance fields.
- `python3 -m host.otis_tools.report_run` renders a Markdown A0 replay report
  covering run identity, SW1 capture limitations, completion state, artifact
  inventory, row counts, raw-event monotonicity, PPS/reference interval sanity,
  count-observation frequency estimates when units are declared, health/status
  counters, validation findings, warnings, anomalies, and fixture usefulness.
  Use `--output` to write the Markdown report and `--json` to write the same
  high-level summary as machine-readable JSON.

SW1 capture mode: irq_reconstructed. Timestamps are suitable for bench
validation and protocol bring-up, not final PIO/DMA metrology.

These tools do not infer PPS quality, oscillator frequency error, lock state,
discipline state, steering quality, Allan deviation, or other SW2/A-stage
claims.

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
