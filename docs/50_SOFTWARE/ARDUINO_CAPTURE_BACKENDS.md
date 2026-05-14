# Arduino Capture Backends

This note maps the current `firmware/arduino` capture implementation to the
future PIO/DMA timestamp path. It is a design-preparation document only. It does
not redefine SW1 behavior, the CSV wire format, timestamp semantics, or the
single-core Arduino service loop.

## Current Boundary

The backend boundary is `otis_capture_backend_*` in
`firmware/arduino/otis_nano_rp2040_connect`:

| File | Current ownership |
|---|---|
| `otis_capture_backend.h/.cpp` | backend selection, foreground service dispatch, aggregate stats |
| `otis_capture_irq.h/.cpp` | GPIO interrupt capture and divided-only TCXO IRQ counting |
| `otis_capture_pio.h/.cpp` | opt-in PIO FIFO edge observation and foreground FIFO drain |
| `otis_capture_ring.h/.cpp` | IRQ-safe software ring for CPU-attached edge records |
| `otis_nano_rp2040_connect.ino` | bring-up mode routing, serial/status emission, foreground service order |
| `otis_timebase.h` | current reconstructed `rp2040_timer0` tick source |
| `otis_protocol.h` | record families, domains, and provenance flags |

Future DMA-backed capture should connect at this backend boundary, not inside
transport or status emission. The next backend should be selected by the same
compile-time capture backend switch pattern used for `OTIS_CAPTURE_BACKEND_IRQ`
and `OTIS_CAPTURE_BACKEND_PIO_FIFO`.

## Current GPIO IRQ Backend

`OtisCaptureBackendKind::GpioIrq` calls `otis_capture_irq_begin()`, which stores
the selected GPIO, channel id, record family hint, and interrupt mode, then
installs an Arduino GPIO interrupt handler.

The IRQ handler:

- determines the edge as `R` for reference records, or by reading the GPIO for
  generic event records;
- calls `otis_capture_ring_push_from_isr()`;
- increments `capture_irq_edge_count` only when the ring push succeeds.

`otis_capture_ring_push_from_isr()` currently owns construction of
`OtisCapturedEdge` for the IRQ path. It reads `otis_capture_ticks_now()`, stores
the record in the software ring, and marks the timestamp with
`OTIS_FLAG_TIMESTAMP_RECONSTRUCTED`.

The foreground loop later calls `drain_capture_ring()`, pops records with
interrupts masked briefly, and emits `EVT` or `REF` rows through
`emit_captured_edge()`.

This backend is the default SW1 behavior. It is suitable for bench validation
and protocol bring-up, not final timestamp metrology.

## Current PIO Edge-Queue Backend

`OtisCaptureBackendKind::PioEdgeQueue` calls `otis_capture_pio_begin()`, which
installs one PIO0 state machine for one selected GPIO. The current PIO program
waits for a low state, waits for a high state, pushes a compact word into the RX
FIFO, and then repeats. It observes rising edges only.

The foreground service path is:

```text
loop()
  -> otis_capture_backend_service()
     -> otis_capture_pio_service()
        -> drain PIO RX FIFO
        -> construct OtisCapturedEdge
        -> emit through configured emit_record callback
```

The current PIO backend deliberately bypasses `otis_capture_ring`: it emits from
foreground service through `OtisCaptureEmitFn`. That keeps the SW1.5a PIO
experiment narrow and avoids introducing a second software queue while the FIFO
is still CPU-drained.

Guardrail: this backend is for sparse edge observation only. Acceptable inputs
are GPS PPS, slow GPIO loopback, and future low-rate event edges. It must not be
used to enqueue raw 10 MHz / 16 MHz CXO edges. Raw oscillator input on `D8` /
`GPIO20` / `GPIN0` belongs on the RP2040 frequency-counter / FC0 /
gated-count path and should be emitted as count observations.

PIO status counters are owned by `otis_capture_pio.cpp`:

- `pio_fifo_drained_event_count`
- `pio_fifo_empty_count`
- `pio_fifo_overflow_drop_count`
- `pio_fifo_max_drain_batch`

`otis_capture_backend_get_stats()` aggregates these with IRQ and ring stats for
periodic `STS` emission.

## Current PIO Is Not Hardware Timestamping

The current PIO backend proves that a selected edge can be observed by PIO. It
does not prove final PIO/DMA timestamp capture.

Specifically:

- PIO pushes an edge marker, not a hardware-latched timer value;
- CPU foreground code drains the FIFO;
- `otis_capture_pio_service()` attaches `otis_capture_ticks_now()` at drain
  time;
- emitted rows keep `capture_domain=rp2040_timer0`;
- emitted rows keep `OTIS_FLAG_TIMESTAMP_RECONSTRUCTED`;
- boot/status rows report `capture_mode=pio_fifo_cpu_timestamped` and
  `timestamp_latch=pio_edge_detect_cpu_timestamped`.

Reports and future code must treat this as PIO-detected but CPU-timestamped.
The PIO FIFO entry is an edge queue, not a timestamp queue.

It is also not a raw MHz oscillator transport. Feeding a 10 MHz or 16 MHz CXO
directly into this queue would measure foreground drain behavior, FIFO overflow,
USB serial throughput, and host capture limits rather than useful oscillator
timestamps.

## Future DMA-Backed Capture Path

The future backend should replace the current CPU-drained PIO edge queue with a
backend that owns hardware capture buffers. The expected shape is:

```text
PIO edge/timestamp program
  -> RX FIFO or side-set/capture fabric
  -> DMA channel(s)
  -> DMA-owned capture buffer
  -> bounded foreground DMA service
  -> canonical OtisCapturedEdge records
  -> existing emitter and wire format
```

The future connection point is `otis_capture_backend_service()`. A future
`PioDmaTimestamp` backend should be serviced there, beside the current
`PioEdgeQueue` service call. The DMA service should do only bounded foreground
work: observe completed DMA spans, translate raw capture entries into
`OtisCapturedEdge` records, update backend counters, and hand records to the
same downstream emission path.

Do not place DMA ownership in `otis_emit.cpp`, `otis_transport_serial.cpp`, host
capture tools, or status emission. Those layers should continue to consume
already-defined records and counters.

## Capture Record Ownership

`OtisCapturedEdge` is the firmware-internal handoff record for `EVT` and `REF`
rows.

Current ownership differs by backend:

| Backend | Record construction owner | Handoff |
|---|---|---|
| GPIO IRQ | `otis_capture_ring_push_from_isr()` | software ring, then foreground drain |
| PIO edge queue | `otis_capture_pio_service()` | direct foreground emit callback |
| Future PIO/DMA timestamp | DMA backend service | DMA buffer to foreground record drain |

The future DMA backend should own its raw DMA entry format privately. It should
convert to `OtisCapturedEdge` only after it can attach the correct channel,
edge, timestamp, domain, and flags. That preserves the existing emitter contract
and keeps the wire format stable unless a later stage explicitly changes it.

## Timestamp Semantics Ownership

Timestamp semantics are owned by the capture backend and the protocol contract,
not by the emitter or host transport.

The backend must decide and document:

- whether `timestamp_ticks` was hardware-latched or reconstructed;
- which native `capture_domain` the ticks belong to;
- whether `OTIS_FLAG_TIMESTAMP_RECONSTRUCTED` is required;
- counter width and rollover reconstruction rules;
- uncertainty or overflow flags that apply near the capture.

`emit_captured_edge()` currently emits every `OtisCapturedEdge` with
`OTIS_DOMAIN_RP2040_TIMER0`. A future DMA-backed backend may continue using that
domain only if the hardware-latched value is in the same RP2040 timer-derived
domain. If a different timer/counter is latched, the domain contract must be
updated before changing emitted semantics.

## Overflow And Drop Counters

Counters live at the layer that can observe the loss:

| Loss source | Current owner | Current surface |
|---|---|---|
| IRQ software ring full | `otis_capture_ring.cpp` | `capture.dropped_count`, `CAPTURE_RING_OVERRUN` |
| PIO RX FIFO stall | `otis_capture_pio.cpp` | `pio_fifo_overflow_drop_count`, `CAPTURE_OVERFLOW_NEARBY` |
| PIO service found no work | `otis_capture_pio.cpp` | `pio_fifo_empty_count` diagnostic |
| Future DMA buffer overrun | future DMA backend | backend stats, later optional diagnostics |
| Future timestamp reconstruction gap | future DMA backend | capture flags and backend stats |

The aggregate reader is `otis_capture_backend_get_stats()`. Periodic status
emission in the sketch should remain a foreground consumer of those stats, not
the owner of loss detection.

Current PIO overflow counts are status indicators, not precise missing-edge
totals. A future DMA backend should make the same distinction explicit: a
counter may mean "known dropped records", "overflow nearby", or "service lag
observed", but it must not silently imply precision it does not have.

## ISR-Safe Code

The following code must remain ISR-safe in the current SW1 path:

- GPIO capture interrupt handlers in `otis_capture_irq.cpp`;
- `otis_capture_ring_push_from_isr()`;
- `otis_capture_ring_note_drop()` when called from overflow-sensitive capture
  contexts;
- small volatile counter updates used by interrupt handlers.

ISR-safe code must not format CSV, call serial transport, allocate memory, block,
perform unbounded loops, or depend on foreground-only state transitions.

A future DMA interrupt, if used, should follow the same rule: acknowledge the
hardware, publish minimal completion state, update ISR-safe counters, and leave
record translation and emission to foreground service.

## Foreground-Only Code

The following code is foreground-only:

- `otis_capture_backend_service()`;
- `otis_capture_pio_service()`;
- `drain_capture_ring()`;
- `emit_captured_edge()`;
- all `otis_emit_*()` functions;
- `otis_transport_serial.*`;
- `emit_periodic_status()`;
- `service_tcxo_gate()` frequency-counter reads.

These paths may perform bounded service loops, serial formatting, status
emission, and host-facing work. They must not be called from GPIO IRQ or future
DMA IRQ handlers.

For a future DMA backend, the foreground service function is the correct place
to drain completed DMA spans and translate them into `OtisCapturedEdge` records.
If output budgeting is added later, it should budget the number of emitted
records without moving transport work into the capture ISR.

## GPIN0 And FC0 Observation

`SW1_TCXO_OBSERVE` uses `D8` / `GPIO20` / `GPIN0` as an oscillator observation
input. With the default `OTIS_TCXO_COUNTER_BACKEND_FC0_GPIN0`, firmware
configures GPIO20 for the RP2040 clock-frequency counter and emits `CNT` rows
for `CH2`.

This validates oscillator presence and approximate counted-edge behavior across
an observation gate. It is not per-edge timestamping:

- FC0 returns a frequency/count observation over a gate;
- the emitted row is a `CNT` record, not an `EVT` or `REF` edge record;
- gate open and close ticks are read in firmware and marked reconstructed;
- raw 16 MHz TCXO edges are not pushed into the current GPIO IRQ or PIO FIFO
  edge paths.

GPIN0/FC0 observation is therefore relevant to oscillator validation and wiring
confidence, but it does not replace the future PIO/DMA per-edge timestamp
backend.

## Non-Goals For This Stage

This stage does not implement:

- DMA setup or DMA interrupts;
- hardware-latched timestamp transfer;
- multicore capture isolation;
- output buffering redesign;
- wire-format changes;
- new timestamp semantics.

The intended result is a clear target for the next implementation stage: add a
new backend at the capture backend boundary, keep DMA/timestamp ownership inside
that backend, and preserve the existing emitter and host-facing contracts until
a deliberate protocol revision is made.
