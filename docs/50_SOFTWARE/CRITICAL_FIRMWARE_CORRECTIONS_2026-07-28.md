# Critical Firmware Corrections — 2026-07-28

## Scope

This correction pass resolves the reviewed defects in serial framing, boot
diagnostics, PIO state-machine ownership, PIO counter validation, and active
firmware documentation. It does not change OTIS CSV schemas, timestamp-domain
meaning, capture roles, control behavior, or hardware wiring.

## Corrections

| Area | Defect | Correction | Evidence preserved |
|---|---|---|---|
| Serial framing | Known record tags with the wrong column count, and lines containing malformed UTF-8, could enter contract CSVs. Oversized partial lines could resume parsing before their original newline boundary. | Contract CSVs now accept only complete, valid-UTF-8, contract-width frames. The line framer discards an oversized frame through its terminating newline. | `capture_device` still appends the original bytes to `raw/serial.log`; `capture_serial` now also writes its input to `raw/serial.log`. Parser and host markers remain diagnostic evidence. |
| Boot diagnostics | `BOOTDIAG`, headers, and provenance were written after the bounded serial wait even when USB serial was not ready. Scratch-register fields were read after current-boot breadcrumbs had overwritten part of the previous state. | Raw RP2040 registers are copied before breadcrumb mutation. The one-shot boot/protocol banner is emitted only when USB serial is ready and remains pending for a late host; a terminator establishes a fresh record boundary first. | `BOOTDIAG.wd_s0..wd_s7` now contain the preserved pre-breadcrumb values. The decoded `BOOT` record remains available and the wire tags/schema stay unchanged. |
| PIO ownership | Sparse edge capture silently used PIO0/SM0 without claiming it, while the long-gate counter asked the SDK for an unused state machine. A combined build could assign both paths to SM0. | Both paths use non-panicking SDK claims for unused PIO0 state machines and fail initialization explicitly when no state machine or program space is available. Boot telemetry exposes the claimed PIO block and state-machine numbers. | Existing PIO FIFO and count records/counters remain unchanged; initialization failure remains visible through `STS`. |
| Counter validation | The PPS-gated path rejected a terminal 32-bit PIO count, but the ordinary PIO long-gate path emitted the same condition as valid. Zero-count rows also omitted the documented source-health flag. | A shared arithmetic helper preserves the best available count and marks terminal counts saturated. Both PIO count paths flag and reject saturation. Long-gate telemetry reports its saturation count. Zero-count rows include `SOURCE_HEALTH_SUSPECT` and `INPUT_STUCK_LOW`. | Saturated and zero observations are still emitted as raw `CNT` rows when the gate is bounded; flags and `STS` diagnostics prevent them from being treated as clean. |
| Documentation drift | The firmware README named the wrong default mode and stale DAC limits/step size; PIO and loopback compile examples conflicted with the checked-in dual-observer guard. | Active firmware, backend, boot, host, runbook, and validation documents now match the checked-in configuration and commands. | Historical run evidence and roadmap documents were not rewritten. |

## Regression Coverage

Automated tests cover:

- complete-line framing across serial read chunks;
- oversized complete and partial frames;
- raw preservation with malformed UTF-8 and invalid column counts;
- raw preservation in the stdin-based capture path;
- boot-diagnostic capture ordering and serial-ready banner gating;
- dynamic PIO state-machine claiming in the edge backend;
- PIO counter values immediately below and at terminal saturation.

The firmware compile matrix for this correction includes:

1. the checked-in default H1 build;
2. combined PIO FIFO edge capture plus PIO long-gate count, with the temporary
   dual observer disabled;
3. the PPS-gated ratio backend;
4. the checked-in default with raw boot diagnostics disabled.

## Compatibility Assessment

- OTIS wire tags, schema versions, CSV columns, record ordering within a line,
  timestamp domains, and flag bit assignments are unchanged.
- Host tools continue to ignore boot records when splitting contract CSVs.
- Invalid known-tag frames no longer contaminate derived CSVs. They remain
  replayable from the raw log; consumers that relied on malformed rows being
  copied into a contract CSV were relying on invalid data.
- `capture_serial` adds `raw/serial.log` to newly captured runs. Existing run
  layouts and manifest-declared CSV paths are unchanged.
- `BOOTDIAG.wd_s0..wd_s3` now represent the earlier, pre-breadcrumb evidence
  promised by a raw boot snapshot. This is a correctness change to field timing,
  not a schema change.
- New `STS` keys (`pio_block`, `pio_sm`,
  `pio_long_gate_count_saturated_count`) are additive.

## Risk Assessment

| Risk | Assessment | Required hardware check |
|---|---|---|
| PIO claim interaction | Low software risk: the combined configuration compiles and both owners use SDK claims. Actual state-machine assignments depend on other board/core users. | Boot the combined build and confirm `capture/pio_sm` differs from `capture/pio_long_gate_sm`; verify both `REF` and `CNT` activity. |
| Delayed USB attachment | Low-to-medium residual risk: banner state and captured snapshot are deterministic, but USB behavior is core/host dependent. | Power the board without an open monitor, attach after the serial wait, and confirm exactly one complete `BOOT`, `BOOTDIAG`, header set, and provenance banner. |
| Counter saturation | Low software risk, high metrology consequence if mishandled. Terminal arithmetic is covered without hardware; no bench source has forced the PIO counter to terminal count in this pass. | Use a controlled high-rate/long-gate test or injected counter fixture and confirm the raw `CNT` remains present with `COUNT_SATURATED`, warning telemetry increments, and control eligibility is false. |
| Early-register interpretation | The snapshot is captured at the first sketch boot phase, not at the RP2040 reset vector. Arduino core initialization has already occurred. | Treat clock fields as sketch-entry evidence only; retain an SW2 hardware/reset-vector task if earlier forensics are required. |
| Mid-record USB loss/backpressure | Raw host framing now prevents partial records from entering CSVs, but firmware still has no transport backpressure counter. | Exercise disconnect/reconnect during output and confirm raw markers plus parser diagnostics account for every rejected partial frame. |

## Hardware Handoff

The software ownership boundary is ready for hardware validation. Hardware work
should close the checks above before claiming hardware-clean PIO timing or
counter saturation behavior. No active-control or steering authority is added
by this correction pass.
