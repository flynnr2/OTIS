# Nano RP2040 software service-latency baseline

The existing 15-instruction PIO counter remains the sole owner of the D14/D8
count aperture. Service diagnostics observe later software operations; they
cannot improve count accuracy or modify raw evidence, qualification, DAC policy
or abort decisions. D10 remains unimplemented. No hardware operation is
authorized by this implementation or its offline checks.

## Endpoint definitions

All available endpoint coordinates use the shared RP2040 peripheral timer's
native `rp2040_monotonic_us32` domain. Units alone never permit subtraction
from a D8 count. Both cores share this timer; no cross-core clock fit is needed.

| Stage | Exact start → end | Interpretation |
|---|---|---|
| FIFO read to foreground | Timer sampled immediately after reading an immutable PIO RX word → timer sampled after foreground pops that same ring record | Includes record creation and ring residence. Normal reads occur in the FIFO ISR; fault-preservation polling can also read committed words. Neither is a D14 GPIO callback or hardware latch. |
| First foreground consumption to ready | Foreground pop endpoint → return from reference-acceptance observation | Includes mapping, raw REF/SNP publication and selection for that exact snapshot. |
| Ready to first estimator consumer | Selection ready → immediately before phase-estimator selection consumption | Includes preceding CNT/APS publication and runtime updates; not completion of estimation or a DAC application. |
| Queue precommit to consumer return | Timer sampled after slot copy, before release publication → successful consumer pop return | Measured software envelope around residence. Includes pre-release work; exact release-to-consumption duration is unavailable. |
| Output entry to firmware transport service | The same output precommit coordinate → Core 0 canonical formatter dispatch | Includes queue residence and dispatch work. Not completed formatting, serial-buffer acceptance, USB completion or host receipt. |

The pre-attachment discard path records successful queue consumption but marks
output dispatch missing; discarding is not a firmware transport endpoint.

D14 and D8 samples refer to the same hardware snapshot session and source
sequence, with separate channel labels. D8 diagnostics occur once per D14
snapshot, never for every oscillator edge. Queue-message identities remain
explicit; no REF ordinal, accepted-span ordinal, FIFO IRQ count or unrelated
queue sequence may substitute for a snapshot identity. There is no independent
D14 GPIO ISR endpoint in current code. GNSS UART parsing and receiver
qualification remain separate from PPS diagnostics.

Native low-word subtraction permits one wrap only under the caller's bounded
same-event lifetime below `2^31` microseconds. A modular delta alone cannot
exclude an extra full wrap. Restart changes capture session. Missing endpoints,
duplicates, contradictory order, unknown domains and unresolved lifetime are
missing or ambiguous diagnostics, never zero latency or canonical capture
failure. An observed maximum is not a worst-case execution-time guarantee.

## Hardware-marker assessment and disposition

Current explicit OTIS ownership is two PIO0 state machines and two separately
loaded copies of the 15-word snapshot program: 30 of 32 PIO0 instruction words.
D8 uses PIO0 IRQ1 and a 128-record software ring; D6 polls its own FIFO. Neither
claims DMA. D10 claims no PIO, IRQ, DMA or diagnostic store. PIO1 and unclaimed
DMA channels are potential resources, not a pre-qualified timing solution.

The existing RX word contains `X`, the cumulative D8 counter, not a timer
coordinate. The empty-FIFO/service bracket bounds PIO recognition conservatively
but is not an independently recorded hardware start marker. A DMA-triggered
timer read would observe a later arbitrated bus transaction. Its count/IRQ/DMA
arrival ordinal cannot establish an edge-latched timer coordinate.

A second event-driven PIO counter could record its own D14 sampling coordinate,
but cannot read the first state machine's `X`. It would need a new explicit
same-event join across startup, missing pulses, stalled D8, FIFO loss and restart,
and a bounded mapping of its PIO clock origin/rate to the timer. A nominal
133 MHz-to-microsecond conversion supplies neither phase nor an uncertainty
bound. Instrumenting the original snapshot with an additional instruction or
handshake changes the aperture proof and its four-clock path. No such replacement
is justified solely to provide a nominal latency number.

A concrete paired-waveform alternative uses two synchronously started
one-instruction samplers at 133 MHz with 32-bit autopush. It needs the two
remaining PIO0 SMs, one shared instruction word and two DMA channels, consumes
33.25 MB/s of combined SRAM writes, and fills each eight-word FIFO in 1.925 us.
Two 32 KiB rings retain only 1.971 ms per input and consume 64 KiB before retained
windows and state. They also require gap-free DMA reload, overwrite detection,
continuous bounded scanning and a proof tying sampled edges to the count SM.
This is incompatible with the existing static-memory ceiling and offers no
PIO0 SM reserve for future D10. Moving it to PIO1 does not remove its memory,
service, synchronization or identity requirements.

The preceding frozen single-owner build used 150,396 static bytes against the
157,286-byte ceiling, leaving 6,890 bytes of budget headroom. Its protected
104,858-byte minimum runtime reserve cannot be spent on waveform rings. Those
numbers size the assessment; the final baseline build must report its own
identities and usage. No budget is weakened. This is a finite rejection of the
assessed additions under current constraints, not a claim that every possible
RP2040 circuit is impossible.

**Disposition:** hardware-recognition-to-service, electrical-D14-edge-to-service,
exact queue-release residence, physical transport completion and fractional
D8-cycle capture remain explicitly unavailable. No new capture hardware marker
is installed. The useful software-stage measurements are implemented without
replacing the sound count mechanism or restoring the removed GPIO/DMA path.

## Statistics and diagnostic isolation

The bounded statistics retain eligible, missing and ambiguous counts, extrema
with raw endpoint/source identities, threshold exceedances, diagnostic drops,
eight histogram bins and two largest individual eligible samples per stream.
Version 1 histogram inclusive upper bounds in microseconds are
`1, 4, 16, 64, 256, 1024, 4096, 2147483647`. Threshold comparisons are strictly
`elapsed > threshold`; thresholds are observational. Counters saturate visibly.
Session changes establish a new source-order epoch while retained extrema keep
their original identities. Individual samples occupy 24 bytes and each statistics
object is compile-time bounded to 224 bytes. A separate retained sample preserves
the most recent missing or ambiguous observation, including raw coordinates.

Formatting and publication occur outside the capture IRQ. Diagnostic export
has bounded, drop-new storage and no control/abort authority. Missing exported
records cannot be interpreted as unchanged or clean statistics. Uncertainty
and integer timer quantization must remain explicit; software endpoint precision
is not physical timing accuracy. LAT v1 emits one immutable statistics snapshot in seven parts (`p=0..6`):
counts, histogram, minimum, maximum, two slow samples, and last noneligible
sample. Generation, channel and stage identify the group. Export is limited to
one row per 250 ms, round-robin across ten streams. The six Core 1 streams use
a one-request/one-response mailbox; the four Core 0 streams are copied locally.
There is no timeout, wait or producer backpressure. A missed row increments
that stream's saturating export-drop counter; later snapshots carry the total.
Absent individual samples have explicit presence/status/domain fields.

The dedicated best-effort USB enqueue accepts an entire diagnostic row or drops
it, with reserved buffer space and no waiting. It does not share canonical
pending-frame ownership. Seven parts need at least 1.75 seconds per stream;
Core 1 mailbox requests require another scheduling opportunity. Ten streams
therefore need at least 17.5 seconds for one sweep, plus six request slots under
normal service. Maximum export is four rows per second, each under 256 bytes;
a stalled reader reduces coverage without creating diagnostic abort authority.

The host consumer retains raw rows and explicitly marks missing parts,
duplicate/reordered records, generation gaps and conflicting identities. A
`complete` report means all seven parts form a coherent snapshot; nonzero
missing/ambiguous/drop counters still describe diagnostic coverage loss. It does
not assert scientific health. Malformed LAT schema, CSV and UTF-8 are retained
as local diagnostic errors, without incrementing canonical parser-fault counts
or notifying the acquisition-frontier authority. BOOT and canonical record
validation remain strict. Decode a retained raw log with:

```sh
python3 -m host.otis_tools.service_latency path/to/raw.log
```

Records from historical firmware remain bound to their original revision.

## Original 6.0.0 offline verification (2026-09-19)

The current release suite passed **731 tests** in 108.42 seconds. After the
final empty-drain overhead reduction, 25 affected diagnostic, identity,
queue-ownership and capture-source checks passed again. Native diagnostic tests
use AddressSanitizer and UndefinedBehaviorSanitizer. Actual firmware-formatted
LAT rows pass through the host decoder; injected missing, duplicate, uncertain,
wrapped, congested and malformed records remain explicit and diagnostic-local.
The suite's operational rehearsal exercises host processes and synthetic-device
transport, obstruction, priority abort, closure and evidence finalization. It
does not exercise physical firmware interrupts, USB or DAC propagation.

The unchanged PIO digital proof passed 7,936 cases and 55,552 intervals, with
only -1/0/+1 boundary errors and the same four-clock longest opposite-WAIT path.
The exact fixed firmware compiled using the pinned Arduino core **6.0.0** and
compiler, via the existing isolated CLI at
`/private/tmp/otis-adafruit-toolchain/arduino-cli`; the globally installed 6.1.0
core was rejected and neither the pin nor the global install was changed.

| Final image resource | Bytes |
|---|---:|
| Program storage | 228,288 |
| Static RAM | 154,676 |
| Runtime RAM available | 107,468 |
| Static ceiling / remaining headroom | 157,286 / 2,610 |
| Static increase over preceding single-owner image | 4,280 |

Ten 200-byte statistics stores, a 200-byte mailbox, a 200-byte report snapshot,
a 256-byte formatter buffer, 16 added bytes per observation-queue slot and small
owner/cadence counters account for the diagnostic storage. No heap allocation,
new IRQ/PIO/DMA resource, or relaxed memory reserve is introduced. Per snapshot,
Core 1 performs six bounded statistics updates and Core 0 four for REF/SNP;
one update examines at most eight histogram bins and two tail slots. Queue
stamps add bounded timer reads at successful publication/consumption. Empty
capture drainage adds no timer read; mailbox service performs one atomic state
check. Formatting is Core 0 only, at most four rows/s and below 1,024 bytes/s.
Target execution time and live stack margins remain physical measurements,
not results of the native tests or the linker's static audit.

Local build artifacts and exact input identities are retained under
`build/service-latency-baseline/artifacts/firmware_build_manifest.json` (ignored,
not committed). Source-set SHA-256:
`3525127b892cb13153865dbac30969a1b7883ab358c211b3eef8f0d85efb8b26`.
UF2 SHA-256:
`75bfdf74d0adc11304067e894143727dad4bf34108bfc0a8c15e31d208ae156c`.
The machine-readable wire contract is linked from
[`service_latency_v1.md`](../../data_contracts/service_latency_v1.md).

## Verification and shortest physical gate

Run the native driver/diagnostic/queue regressions and current host parser tests,
then the release suite and fixed firmware build/resource audit. Re-run the
unchanged assembled-word PIO proof with the pinned assembler:

```sh
python3 tools/verify_pio_snapshot.py --pioasm /Users/richardflynn/Library/Arduino15/packages/rp2040/tools/pqt-pioasm/5.0.0-9576866/pioasm
python3 tools/build_firmware.py --output-dir build/service-latency
```

The instruction model proves its declared digital envelope, not electrical
input margin or IRQ response time. Deterministic rollover, session, duplicate,
batch, queue-congestion, histogram and drop tests prove software behavior;
native timer doubles do not measure instrumentation time on the target.

Current physical preparation follows the autonomous implementation's separately
authorized integration gate. The [6.1.0 bench handoff](BENCH_CORE_6_1_0_HANDOFF.md)
below its supersession notice records the earlier inhibited bundle only. Current
firmware intentionally writes its boot code and can steer after qualification.

Historical preparation followed [the 6.1.0 bench handoff](BENCH_CORE_6_1_0_HANDOFF.md):
perform preflight and synthetic operational rehearsals on the development Mac,
then reproduce the image, flash once and run the five-minute inhibited observation
on the bench Mac. Physical USB obstruction is a separate future experiment;
the prepared host rehearsal already exercises synthetic transport obstruction. Retain canonical D14/D8 continuity and new diagnostics together, verify
exact message identities and bounded drop behavior, and measure service/instrumentation
overhead on the actual Nano. Preserve existing pre-actuation eligibility gates;
no separate actuation is necessary merely to observe software latency. Independent
edge/service instrumentation is required before claiming a hardware-to-service
latency bound. No flash or physical acquisition was performed for the offline
implementation.

## Follow-up to the reported five-minute 6.1.0 observation

The operator reported healthy capture/replay and zero writes, but recurring
output-queue delays around synchronous status reports and two startup-only
selector-to-first-consumer outliers. Those supplied figures remain reported
bench evidence until the sealed package is independently inspected.

- [Periodic output repair](PERIODIC_STATUS_SERVICE_REPAIR.md): freeze one view,
  serialize one complete row at a time through the existing arbiter, and use
  bounded native USB admission. Stages 3/4 retain their overlapping endpoints.
- [Startup review](STARTUP_ESTIMATOR_SERVICE_REVIEW.md): the first two count
  transitions format 64/71 status rows; defer that work until after first phase
  consumption. No estimator-execution time is inferred from stage 2.
- [Current capture assessment](PPS_CAPTURE_CURRENT_ASSESSMENT_2026_09_19.md):
  retain the PIO aperture, prove recognition-to-X-copy is one PIO clock and add
  current 10 MHz/count and conditional 4–9-clock input-dwell proofs. The
  conditional SM-input bound is not a measured physical-edge or timer latency;
  hardware-to-service remains unavailable (`hw=0`).

The combined prepared handoff records the new image's own resources, identities,
release verification and host rehearsals. Physical improvements remain for the
single finite inhibited bench observation; successful prior acquisition is not
repeated to repair an offline consumer.

The exact follow-up build and focused bench instructions are recorded in
[the service/capture handoff](SERVICE_CAPTURE_BENCH_HANDOFF.md).
