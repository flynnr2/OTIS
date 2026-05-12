# Stage 1 Arduino Nano RP2040 Connect Timing Core

The initial OTIS implementation is an open-loop Arduino Nano RP2040 Connect
timing appliance using the Earle Philhower `arduino-pico` core. Its purpose is
to prove the capture, telemetry, provenance, and replay architecture before
adding oscillator steering or GPSDO control loops.

Stage 1 is not primarily a GPSDO. It is a deterministic timestamp and reference observation platform.

## Goals

- capture GNSS PPS as a reference event;
- observe a TCXO, OCXO, GPSDO output, or oscillator under test as an input signal;
- capture generic external timing events;
- emit canonical raw event telemetry;
- preserve explicit timing-domain and provenance metadata;
- support host-side replay and analysis from recorded artifacts.

## Hardware Assumption

The RP2040 board clock remains the implementation clock for firmware, USB, DMA, and PIO execution. Stage 1 does **not** require feeding a TCXO or OCXO into the RP2040 system clock input.

Reference oscillators enter Stage 1 as conditioned GPIO signals observed by the PIO/DMA capture fabric.

```text
RP2040 board clock
  -> runs firmware / USB / PIO / DMA

TCXO / OCXO / oscillator under test
  -> buffer / level conditioning
  -> RP2040 GPIO / PIO
  -> observed as reference-signal evidence

GNSS PPS
  -> RP2040 GPIO / PIO
  -> captured as a reference event
```

See `docs/10_REFERENCE_ARCHITECTURE/REFERENCE_SIGNAL_MODEL.md`.

## Timing Fabric

The RP2040 PIO subsystem is initially envisioned as the timing fabric.

PIO responsibilities may include:

- edge capture;
- reciprocal counting;
- counter gating;
- reference-pulse counting;
- pushing timestamp/count records into DMA-backed buffers.

Firmware should keep the timing-critical path small. The CPU may drain buffers, attach metadata, and emit telemetry, but it should not create event time after the fact.

## Arduino Nano RP2040 Connect Firmware Target

The H0/SW1 Arduino entrypoint targets the Earle Philhower `arduino-pico` core
for the Arduino Nano RP2040 Connect. The Arduino Mbed OS Nano Boards core is not
the target for OTIS timing firmware.

This choice preserves a simple Arduino sketch workflow for early smoke tests
while keeping direct access to RP2040/Pico SDK facilities, `setup1()` /
`loop1()` multicore structure, and PIO tooling for later capture steps.

The standalone Pico SDK scaffold is deprecated and archived under
`firmware/deprecated/rp2040_pico_sdk/` for reference only. New SW1 firmware work
belongs in `firmware/arduino/otis_nano_rp2040_connect/`.

## Status Indication: RP2040 Built-in RGB LED

The Arduino Nano RP2040 Connect built-in RGB LED may be used as a coarse
human-visible bring-up indicator. It is a convenience/debug/status indicator,
not a diagnostic data channel. Serial logs, CSV output, and later dashboard
state remain authoritative.

LED updates must never occur inside ISRs, capture callbacks, PIO timing paths,
PPS handlers, or other timing-sensitive code. The status LED layer must be
low-rate, nonblocking, heap-free, and silent: no blocking delays, no dynamic
allocation, no `Serial` printing, and no dependency that can disturb capture
timing. Prefer state-change-driven updates over periodic redraws; periodic LED
polling, if used for blink timing, belongs only in noncritical foreground code.

The rest of OTIS must not call board LED pins or RGB libraries directly. Use a
single board abstraction such as:

```c
void otis_status_led_set(OtisSystemState state);
```

All board-specific RGB LED details are hidden behind this layer. Compile-time
gating is required:

- `OTIS_ENABLE_STATUS_LED=0`: all status LED calls compile to no-ops and do not
  require RGB LED libraries or NINA/WiFi LED dependencies.
- `OTIS_ENABLE_STATUS_LED=1`: the board-port implementation may drive the
  built-in RGB LED from noncritical foreground code only.

On the Nano RP2040 Connect, the built-in RGB LED is common-anode and uses
inverted logic: `HIGH` is off and `LOW` is on. Treat this as a board-port
specific detail, not core OTIS logic. If LED support proves intrusive because of
NINA/RGB library behavior, keep the abstraction and compile the implementation
out.

State priority is deterministic. If several conditions are true, the highest
applicable state wins:

1. Fatal/config fault overrides everything.
2. Missing/invalid oscillator overrides PPS/acquisition states.
3. PPS missing/stale overrides lock/acquire states.
4. Holdover/degraded overrides healthy lock.
5. Healthy locked/logging is the lowest-priority steady-state success.

Optional activity overlays must be brief and must not obscure fault or health
state. Unknown state must fail safe to LED off or red fault; the current minimal
Arduino stub uses LED off.

Initial color/pattern contract:

| State | LED behavior |
|---|---|
| Boot starting | brief white flash |
| Waiting for PPS/GPS | slow blue pulse or blink |
| PPS seen / acquiring | solid blue |
| Locked / healthy / logging | solid green |
| Valid capture heartbeat | brief green blink only if it does not obscure health |
| Holdover / degraded | yellow pulse or blink |
| Missing oscillator / missing clock source | fast red blink |
| Fatal/config fault | solid red |
| USB/config/debug mode | purple |
| Optional host/API/WiFi activity | brief cyan/white overlay only when safe |

Acceptance criteria:

- Code builds with `OTIS_ENABLE_STATUS_LED=0`.
- Code builds with `OTIS_ENABLE_STATUS_LED=1`.
- No timing-critical source file directly manipulates the RGB LED.
- A grep for board-specific RGB calls shows they are confined to the status LED
  module.
- No ISR contains status LED calls.
- State priority is deterministic and documented.
- Unknown state fails safe to LED off or red fault, explicitly documented.

This is intentionally small. Do not introduce dashboards, menus, animation
frameworks, telemetry protocols, or new runtime dependencies for this layer.

## Stage 1 Milestones

### Stage 1A — PPS Capture

Capture GNSS PPS edges and emit raw records with monotonically increasing sequence numbers, captured ticks, channel identity, edge type, and capture flags.

### Stage 1B — TCXO / Reference Oscillator Observation

Feed the available TCXO through the buffer into an RP2040 GPIO/PIO path. Count or capture the reference signal against PPS intervals so the host can estimate frequency error, jitter, missing counts, and interval stability.

### Stage 1C — Generic Event Capture

Add at least one application-neutral event input. It should not be hard-coded as a pendulum, TIC channel, or GPSDO signal. Application meaning belongs in the host profile and manifest.

### Stage 1D — Canonical Telemetry

Emit records compatible with `data_contracts/raw_events_v1.csv.md` and the canonical event model in `docs/20_TELEMETRY/canonical_event_model.md`.

### Stage 1E — Host Replay

Record raw serial logs, parsed CSV, and a run manifest sufficient to reconstruct intervals, PPS comparisons, reference oscillator estimates, and capture quality without relying on hidden firmware state.

## Non-Goals

Initial Arduino Nano RP2040 Connect implementations are not expected to:

- close a GPSDO loop;
- steer an OCXO or VCXO;
- drive an EFC DAC;
- achieve state-of-the-art phase noise;
- replace dedicated FPGA TDCs;
- provide laboratory-grade metrology;
- hide reference quality inside the MCU clock tree.

The initial focus is architectural correctness, deterministic behavior, explicit provenance, and replayable raw observations.
