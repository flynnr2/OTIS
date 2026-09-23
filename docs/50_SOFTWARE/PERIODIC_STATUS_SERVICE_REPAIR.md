# Periodic status service repair

The recurring ten-second status report now yields the Core 0 loop after each
complete STS row. One frozen view supplies the report; the existing serial-frame
arbiter owns each row across partial writes. Its USB service makes one native
try-lock attempt, copies at most 192 available bytes and returns. It never calls
`Serial.print`, `Serial.write`, a blocking mutex, `tud_task`, a polling loop or a
wait. No new serial owner or telemetry queue is introduced.

## Evidence and finding

The operator reported a healthy, sealed 300.828636541-second zero-write bench
observation of PR #193's image. At session 1/source 120, D14 queue precommit to
consumer return was 437,797 us, while the periodic STS block spanned about
406,780 us. D8's corresponding queue sample was 439,140 us. Stage-3 cumulative
`>4096 us` counts rose to 31/289 (D14) and 32/291 (D8), without output-queue loss.
These are supplied findings, not an independent decode of the bench package.
That package remains on the bench Mac with sealed SHA-256
`2a07e4e7684bc851b0194fe96ff59600044987c49dc66129696462bbcf5c0164`.

The prior loop drained raw observations, then synchronously emitted the entire
periodic report before returning to drainage. Each textual STS field traversed
`otis_emit_csv_text`, which called the transport for individual characters.
The pinned Arduino-Pico 6.1.0 `SerialUSB::write` repeatedly services TinyUSB and
flushes transfers, and waits for FIFO capacity when necessary. Its USB mutex
wrapper can also wait for the other core. Thus merely splitting the report
without replacing its blocking write path would not bound a service attempt.
The source supports the reported stall mechanism; it does not separate the
measured 407 ms into formatting, USB scheduling, contention and backpressure.
`SerialUSB::begin` ignores its nominal baud argument; 115200 is not a measured
USB CDC throughput.

LAT stage 3 and stage 4 start at the **same** output precommit. They overlap;
never add them. Only matching channel/session/source/precommit samples permit
stage-4 minus stage-3 subtraction. For source 120 the additional pop-to-dispatch
work was 64 us for D14 and 44 us for D8. Neither endpoint measures completed
formatting, accepted USB bytes, USB transfer completion or host receipt.

## Retained view and framing

At the ten-second opportunity, Core 0 copies the existing queue statistics,
GNSS receiver snapshot, published phase status and frequency diagnostic counters.
These are frozen until the report ends or is explicitly cancelled. They are
coherent copies from their existing getters, not a simultaneous global snapshot
of both cores and hardware. Reading a newer receiver sentence during output
cannot replace a later field of the old receiver view.

The report begins with `periodic_status/generation_begin`, records
`snapshot_ticks` and `snapshot_domain=rp2040_monotonic_us32`, and ends with the
matching `generation_end`. STS row timestamps retain their ordinary formatting
instant, so interleaved status timestamps and sequences remain monotonically
ordered. The source-view coordinate is separate from those emission coordinates.
A generation is diagnostic provenance; it has no command or control authority.

One traversal selects one row from the fixed field vocabulary. Unselected
numeric rows skip formatting. This shares the GNSS/frequency field definitions
with existing full status emission without allocating a queue of formatted
reports. A 384-byte fixed buffer holds the whole selected, percent-encoded STS
record before any USB write; overflow discards the incomplete generation with
no emitted prefix. The STS sequence is allocated only after the arbiter selects
this producer. The buffer and byte offset remain immutable until complete.

Each service attempt uses capacity inspection and FIFO copy under the same
native USB try-lock, followed by at most one TinyUSB endpoint-scheduling attempt.
That scheduling operation does not wait for physical delivery. After an accepted
prefix, the arbiter excludes every other wire producer until the row completes;
between rows the existing round-robin arbitration and main loop run normally.
Canonical observation drainage, command input, GNSS servicing and metadata
publication therefore have opportunities throughout a report. The existing
fixed total pending-frame horizon still applies; partial byte progress cannot
restart it. Explicit abort input is serviced while a frame is incomplete.

`CONFIG?` and `DUALCORE?` may publish overlapping diagnostic namespaces. Between
complete rows they cancel a pending periodic generation with an explicit
`generation_cancel` before publishing fresh query values. Carrier loss also
abandons the generation, but cannot promise a cancellation row reached the host.
The saturating `incomplete_generations` count in later reports exposes firmware
abandonment; a missing end marker alone already means incomplete evidence.
Neither cancellation nor formatting overflow has capture or abort authority.

## Limits and verification

This repair targets the demonstrated periodic block. Boot/configuration reports,
canonical observation formatters and other existing synchronous writers retain
their current paths. It is not a claim that all Core 0 work or all USB calls now
have a target worst-case execution-time bound. Transport obstruction retains
its existing firmware fail-static contract; missing diagnostic rows are not a
scientific failure. A full USB FIFO may still delay canonical dispatch until
one complete retained row is admitted or the existing transport horizon expires.

The native regression executes the actual periodic renderer, generation logic,
Core 0 loop, serial arbiter and liveness logic with deterministic service doubles.
It exercises repeated changing generations, fault-dependent fields, short/zero
FIFO capacity, row ordering, complete framing, command/abort opportunities and
non-renewing obstruction deadlines. USB admission tests execute the production
adapter with a contended mutex and bounded FIFO. They prove the specified
software behavior, not Nano execution costs or physical USB throughput.

The combined handoff retains exact build/resource and release results and runs
the real host process rehearsal. The remaining finite five-minute inhibited
observation should compare fresh LAT stage-3/4 counts and matched outliers across
multiple periodic reports, while preserving capture/replay, queue-drop, memory
and terminal evidence. No extra actuation or GPIO-marker experiment is needed.
A smaller observed maximum would still not be a worst-case guarantee.

Review also exposed an existing input obstruction: a retained normal command
previously stopped subsequent input scanning while an output frame was pending,
so a later explicit abort could be hidden behind it. The same command collector
now continues its fixed 32-byte scan, admits explicit abort independently, and
counts/reports additional normal-command rejection without replacing the one
retained command. The native regression executes that production function with
multiple pending commands, two aborts, malformed input and oversized lines;
normal output resumes exactly once for the originally admitted command.
