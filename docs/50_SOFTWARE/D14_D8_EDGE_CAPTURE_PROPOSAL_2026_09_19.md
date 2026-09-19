# D14/D8 edge capture: proposal and implementation gap analysis

Date: 2026-09-19. Status: historical design proposal, not an implemented fine-capture backend.
The current Nano implementation and finite hardware-marker disposition are in
[SERVICE_LATENCY_BASELINE.md](SERVICE_LATENCY_BASELINE.md). This proposal's GPIO/DMA
endpoint inventory is historical and must not be used as current architecture.

Scope: preserve the most useful hardware evidence of D14 PPS arrival relative
to D8 oscillator edges, without software-dependent measurement timing. D10 is
excluded from implementation scope; its eventual independent event channel is
an architectural constraint. GNSS serial remains receiver qualification, not
an edge-timing source.

D14 PPS and future D10 transitions are the events to retain. D8 is their
numeraire: its cycles supply the measurement unit and continuous count
coordinate. Preserve D8 counts and local edge neighbourhoods with those event
records; a separate stream of individual D8 edge timestamps is not required.

Service-latency observability is a first-class deliverable. This incorporates
the conclusions of the project task **was service latency implemented?**
(`01a0a0b5-d14a-78c2-9b98-0cabe6b7c740`): identifiable stage endpoints, a real
hardware start marker, explicit clock relationships, bounded statistics and
tail evidence, and diagnostic isolation from canonical capture.

This review inspected working-tree source at HEAD
`e91bbfd8b7e7881a6303e5d796036e6e5f35310c`, including existing uncommitted work.
It is not a claim about the image currently installed on the instrument. No
firmware, electrical connections, operating policy, or existing evidence was
changed for this proposal.

Publication note: upstream subsequently advanced to
`6bf5dbcfdf12656f643736d527003398117371a7` (PR #190). That implementation keeps
the PIO count boundary but uses a bounded FIFO-drain IRQ and one reference
record owner; the separate GPIO REF path and DMA snapshot transport were
removed. The gap analysis below describes the earlier inspected revision,
not those later changes. See the current
[single-reference-owner design](SINGLE_REFERENCE_OWNER_REPAIR.md) and
[SNP v2 contract](../../data_contracts/pps_snapshots_v2.csv.md). Re-audit current
code before implementation; do not restore the retired path from this report.

## Recommendation

Preserve the current qualified integer-count mechanism until a replacement
passes its own gates. For the complete new requirement, use a small external
synchronous capture engine, most naturally an FPGA with local FIFO storage,
and retain the RP2040 for instrument services and bounded control.

The engine should observe D14 and D8 in one common sampling domain, continuously
count D8 rises, and capture each D14 transition together with its neighbouring
D8 rising edges. It must continue observing D14 if D8 stops. Record formation
must precede bus transfers, interrupts, CPU processing, and qualification.

This is a capability extension beyond the present integer counter, not a
finding that the existing count aperture contains ISR jitter. The existing
PIO capture already excludes that jitter. The new capability is a finer,
reconstructable relationship between edges, plus hardware evidence during an
oscillator outage.

The default scope remains the existing instrument: an external engine is a
proposed hardware substitution, not authorization to modify the bench. A
strict RP2040-only alternative is described below, with its costs and limits.

The immediate implementation scope is the
[Nano RP2040 baseline prompt](NANO_RP2040_CAPTURE_BASELINE_IMPLEMENTATION_PROMPT.md).
An FPGA is a clean architectural option, not a demonstrated necessity. The
continuous-sampling resource estimate below does not rule out a cheaper
event-driven PIO design. Native timer/event capture on a more capable MCU is
also a possible later comparison. A Pi Zero 2 W would primarily add host,
storage and analysis capability; faster CPU software does not itself provide
the missing coherent hardware capture. Hardware substitution remains outside
the baseline task.

## What evidence is actually required?

For every D14 transition, retain:

- which transition was observed, with capture epoch and producer identity;
- its sample coordinate in a named hardware clock domain;
- the cumulative D8 count at that sample;
- the preceding and following D8 rising-edge sample coordinates and indices;
- a simultaneous-sample flag and all continuity/transport status;
- capture configuration and later calibration provenance.

Retain both PPS polarities. The rising edge remains the reference candidate;
the falling edge provides hardware pulse-width and stuck-level evidence and
never becomes an additional PPS authority. Qualification follows capture: a
short, noisy, or unexpected transition is still a raw observation if captured.

The retained evidence is event-centred: each D14 event, and eventually each
D10 event, carries its D8 count and the neighbouring D8 edges needed for local
reconstruction. D8 is counted continuously within the declared input envelope;
its individual edges between retained event neighbourhoods need no archival
records. The neighbourhood is supporting evidence within an event record, not
an additional oscillator-event stream. Incremental event intervals are derived
from retained endpoints, with continuity and ambiguity made explicit.

## Reviewed implementation and gaps (e91bbfd working tree)

| Concern                      | Current implementation                                                                                           | Required change or retained property                                                               |
| ---------------------------- | ---------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------------------------------- |
| D8 count aperture            | One PIO SM owns `X` and `IN X,32` at a recognized D14 rise.                                                      | Preserve hardware ownership; no delayed CPU/DMA counter read.                                      |
| CPU interference with count  | ISR, DMA and foreground execute outside the captured count aperture.                                             | Already correct. ISR optimization cannot improve this raw count.                                   |
| D14 arrival coordinate       | GPIO ISR reads `timerawl`; `REF` is reconstructed local microseconds.                                            | Capture a hardware sampling coordinate independent of ISR entry.                                   |
| D14 position within D8 cycle | No bracketing D8 edge times or fractional-cycle observation.                                                     | Capture neighbouring D8 edges in the same sampling domain.                                         |
| D8 stopped high/low          | Oscillator `WAIT` stalls PPS snapshot observation; GPIO REF may continue.                                        | Continue hardware D14 capture with explicit missing D8 support.                                    |
| PPS pulse shape              | Rising GPIO event plus an ISR-time level sample; PIO recognizes a low before another high.                       | Hardware records of both polarities; no claim about analogue shape.                                |
| Near-simultaneous edges      | Stable PIO count-allocation rule, integer endpoint uncertainty.                                                  | Preserve the sampled rule and report unresolved physical order explicitly.                         |
| Association                  | Foreground joins independently produced REF and SNP streams; disagreement closes association.                    | One event record with hardware-bound count/time identity.                                          |
| Evidence publication         | SNP is emitted after association; unpaired ring words may be discarded during rearm.                             | Publish raw capture independently of derived qualification; retain orphan/gap evidence.            |
| Transport                    | Joined FIFO, one DMA channel, 128-word SRAM ring; stalls/errors/overwrite are explicit.                          | Retain explicit loss semantics; transport cannot move capture time.                                |
| FIFO full                    | Autopush can stall the counting SM; continuity then fails.                                                       | Capture counters continue; full event FIFO drops records with persistent loss evidence.            |
| Clock-domain relationship    | D8 count and RP2040 local microseconds are distinct.                                                             | Add a named fine sampling domain and explicit D8 projection; never relabel local ticks as D8 time. |
| Physical accuracy            | Digital proof and historical bench evidence do not establish input-path skew or analogue margin.                 | Characterize threshold, slew, channel skew, sample ambiguity and reference accuracy separately.    |
| Service latency              | D14 ISR-to-boundary-service age exists; no paired hardware capture/service clock or complete latency statistics. | Hardware markers, bounded clock mapping, stage records, histograms, maxima and threshold evidence. |
| Future D10                   | Reserved, unimplemented, no isolation claim.                                                                     | Independent capture storage and admission; no D14/D8 backpressure or veto.                         |

The historical proof concerns the actual 15-instruction program at 133 MHz,
with a 16 MHz oscillator and the declared 35–65% duty sweep. The current plant
is nominally 10 MHz. The historical proof is useful evidence about its recorded
mechanism/envelope, not a physical accuracy certificate for a new design or a
blanket proof for every lower frequency and waveform.

Code entry points at the reviewed revision:

- [Pin assignments](https://github.com/flynnr2/OTIS/blob/e91bbfd8b7e7881a6303e5d796036e6e5f35310c/firmware/arduino/otis_nano_rp2040_connect/otis_board.h): D14/GPIO26, D8/GPIO20.
- [PIO program](https://github.com/flynnr2/OTIS/blob/e91bbfd8b7e7881a6303e5d796036e6e5f35310c/firmware/arduino/otis_nano_rp2040_connect/otis_pps_snapshot.pio): oscillator waits and hardware count snapshot.
- [Backend](https://github.com/flynnr2/OTIS/blob/e91bbfd8b7e7881a6303e5d796036e6e5f35310c/firmware/arduino/otis_nano_rp2040_connect/otis_pps_snapshot_backend.cpp): `configure_session`, `poll`, `pop`, rearm and transport faults.
- [Reviewed GPIO ISR](https://github.com/flynnr2/OTIS/blob/e91bbfd8b7e7881a6303e5d796036e6e5f35310c/firmware/arduino/otis_nano_rp2040_connect/otis_capture_irq.cpp): historical `handle_capture_edge` and reconstructed REF production; removed by PR #190.
- [Main firmware](https://github.com/flynnr2/OTIS/blob/e91bbfd8b7e7881a6303e5d796036e6e5f35310c/firmware/arduino/otis_nano_rp2040_connect/otis_nano_rp2040_connect.ino): `emit_captured_edge`, `drain_pps_count_boundary_ring`, `emit_pps_count_boundary`, `setup1`, `loop1`.
- [Reviewed snapshot contract](https://github.com/flynnr2/OTIS/blob/e91bbfd8b7e7881a6303e5d796036e6e5f35310c/data_contracts/pps_snapshots_v1.csv.md): historical association and counter semantics; superseded by SNP v2.
- [Accepted count audit](PPS_CAPTURE_LATENCY_JITTER_AUDIT_20260801.md) and [instruction proof](PPS_PIO_PROOF_AND_VERIFICATION.md): existing evidence and its limits.

## Proposed capture engine

### Clocking and input path

Use an independent continuously running capture clock. Set **200 MHz / 5 ns**
as an engineering target, conditional on the selected device, timing closure,
electrical implementation and qualification. This is not a measured accuracy
claim or a component selection. A lower qualified rate is preferable to an
unverified faster one.

Do not clock the whole capture engine directly from D8 or an unmonitored
D8-dependent PLL: that would lose D14 observation when D8 stops. The independent
clock is an interpolation/sampling coordinate, not the oscillator authority.
D8 remains the measured oscillator and D14 remains the sole PPS reference.

Observe the existing D14/D8 signal nets through characterized input paths with
matched synchronizer structure and registered edge detectors. Do not latch an
asynchronously changing multi-bit D8 counter with PPS. Instead, detect both
inputs and update the count in the same capture-clock domain.

Inputs retain metastability protection. Synchronizer latency and channel skew
belong in the uncertainty model; removing protection is not an accuracy
optimization. Define the measurement plane at the instrument input and retain
front-end/cable calibration separately from raw observations.

### State updated on each capture-clock cycle

The engine maintains:

1. a 64-bit capture sample counter;
2. a 64-bit D8 rising-edge count;
3. the latest D8 rising-edge sample coordinate and ordinal;
4. registered D14/D8 levels and transition masks;
5. per-channel event ordinals, overflow counters and continuity state.

On each sampled D14 transition, atomically latch its sample coordinate, the D8
count, preceding D8 edge, polarity, and same-sample transition mask. A sampled
D8 rise at the same coordinate is included in `d8_count_through_sample`. That
is an explicit sampled ordering convention, **not** a claim that the physical
D8 edge arrived first.

Bind the next strictly later D8 rise to that same hardware event identity. A
small pending-record store can finish the record after this edge arrives. Use
a declared bounded timeout, initially proposed as 1 microsecond at nominal
10 MHz; expiry emits the original D14 event with `next_d8_missing`, rather
than withholding the observation. Loss of D8 may withhold a derived phase
estimate but must not erase the PPS capture.

Pending records and completion must support repeated D14 transitions, including
several between D8 rises. Store overflow is explicit. No pending-event wait,
SPI transaction, or full FIFO may stall either input detector or the counters.

### Records, buffering and transfer

Use a versioned event record with these conceptual fields:

| Field                                    | Meaning                                                                       |
| ---------------------------------------- | ----------------------------------------------------------------------------- |
| capture epoch, configuration identity    | Unique session binding and exact hardware/program/clock configuration.        |
| channel, polarity, event ordinal         | Hardware producer identity, allocated even when a later record is lost.       |
| capture sample coordinate                | Raw sample counter at the D14 edge.                                           |
| D8 count through this sample             | Integer hardware count with the declared coincidence convention.              |
| preceding D8 rise coordinate and ordinal | Strictly earlier sampled D8 rise, or explicit absence.                        |
| following D8 rise coordinate             | Strictly later sampled D8 rise, or explicit absence/timeout.                  |
| transition/status mask                   | Same-sample D8 rise, startup, missing bracket, overflow and integrity status. |
| transport integrity                      | Framing and checksum/CRC separate from physical measurement validity.         |

Allow approximately 64 bytes per binary event for sizing; freeze the actual wire
layout during implementation. A dedicated 256-entry D14 FIFO then uses about
16 KiB and covers about 128 seconds at two transitions per second. At 1,000
transitions per second it covers only 256 ms. These are buffer arithmetic, not
an assertion of unlimited noisy-input support. Specify and test both sustained
rate and burst capacity before qualification.

Overflow policy: continue sampling and counting, increment persistent drop
state, and expose the missing event range. Do not overwrite unread records
silently or block the capture clock. Do not infer exact missing-waveform detail
from an overflow count.

Read completed records over a framed SPI link into RP2040 DMA buffers. A FIFO
watermark/data-ready interrupt may request service; a DMA completion interrupt
may publish a completed transfer. Neither interrupt creates a timestamp or
requests a fresh counter sample. Reads must be atomic at record boundaries and
detect truncation, duplicates and checksum failure.

SPI pin allocation, component choice, power, signal loading and board routing
remain hardware integration work. They require an explicit pin/resource audit;
this proposal does not assume that an unused external connector is available.

### Reconstruction

For a non-coincident D14 event at sample `s`, bracketed by D8 rises at `a` and
`b`, with `a < s < b`, and D8 ordinal `k` at `a`, a candidate reconstruction is:

```text
d8_cycle_coordinate = k + (s - a) / (b - a)
```

Keep that as a derived rational coordinate with its source event identity.
It assumes local interpolation between adjacent D8 edges and comparable channel
delays. It is not an independently observed fractional count. Preserve all
integer sample coordinates so another estimator can use a different model.

For two events with unambiguous same-epoch coordinates `k_i + f_i` and
`k_j + f_j`, the incremental interval is:

```text
delta_d8_cycles = (k_j - k_i) + (f_j - f_i)
```

Apply the declared counter rollover/extension rules to the integer term; never
difference across a continuity gap or restart. The fractional terms remain
derived from the preserved neighbourhoods. Retaining cumulative endpoint counts
avoids resetting the counter at each PPS or D10 event and makes incremental
intervals replayable without an oscillator-edge log. Conversion to seconds or
UTC is a further explicit projection. The independent fine sampling clock
supports interpolation; it does not replace D8 as the measurement numeraire.

This local ratio avoids assuming that the independent capture clock is an
accurate long-term replacement for D8. It does not eliminate sample quantization,
clock jitter, differential input delay or interpolation uncertainty. UTC mapping
still requires separately qualified GNSS/time metadata and reference provenance.

For edges observed in the same sample, retain an ordering-ambiguity flag and
an interval-valued result, rather than inventing physical ordering. On missing
brackets, retain the event and integer count but withhold the unsupported fine
projection. Estimator failure remains estimator-local.

### Honest resolution and accuracy claims

At the proposed 200 MHz rate, the sampling grid is 5 ns. Under an ideal fixed
latency model, differencing two independently quantized edges contributes less
than one sampling period of error in either direction. That calculation excludes
channel skew, analogue threshold uncertainty, clock jitter and synchronizer
resolution behaviour; it is not a total 5 ns accuracy specification.

Qualification must measure differential path delay and its variation. Rare
metastability resolution cannot be given an absolute finite bound merely from
a digital simulation. Retain the specified synchronizer design and its assessed
reliability. Published accuracy must state the measurement plane, calibration,
input envelope, uncertainty assumptions and evidence.

## Service-latency measurement is part of the design

Maintain two distinct kinds of evidence: when hardware observed an edge, and
when each service stage handled that observation. Service coordinates may be
CPU observations; they must never overwrite the hardware edge coordinate.

### Endpoints and metrics

Use one record format across channels, with endpoints specific to the path:

| Metric                                 | Start → end                                                               | Coordinate and interpretation                                                                                                |
| -------------------------------------- | ------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| D14 capture-to-first-consumption       | Hardware D14 recognition → first CPU access to its received record        | Capture clock → RP2040 timer; requires the bounded mapping below.                                                            |
| D8 snapshot-to-first-consumption       | Actual D8 count snapshot → first CPU access to that snapshot              | Per D14 boundary, not per 10 MHz edge. In the proposed atomic engine its capture coordinate equals the D14 event coordinate. |
| Capture-to-record-ready                | Hardware event → completed record entering the event FIFO                 | Both in the capture clock. Includes waiting for the following D8 edge or its timeout.                                        |
| Record-ready-to-transfer               | FIFO publication → hardware observation of the record's final SPI bit     | Capture clock with a specified SPI-to-capture synchronization bound. Distinguish this from CPU receipt.                      |
| First consumption-to-observation-ready | First CPU access → validation/association complete                        | Same RP2040 timer; includes software processing and any retained wait.                                                       |
| Observation-ready-to-consumer          | Ready event → first estimator/control consumption                         | Same RP2040 timer, exact source identity.                                                                                    |
| Cross-core residence                   | Successful queue publication → receiver takes the same message            | Same RP2040 timer; measure each relevant queue separately.                                                                   |
| Output residence                       | Record/frame queued → specified firmware transport completion observation | Name the actual endpoint; buffer acceptance is not physical USB completion or host receipt.                                  |
| D14 ISR-to-service                     | Legacy diagnostic ISR timer read → boundary service                       | Preserve the existing metric when the diagnostic observer is enabled.                                                        |
| Hardware-recognition-to-ISR            | Hardware D14 marker → diagnostic ISR timer read                           | Bounded cross-clock mapping; includes interrupt dispatch, excludes unmeasured physical input-to-recognition delay.           |

Future D10 uses the event capture and first-consumption endpoints in its own
channel. Its service coordinate is diagnostic; its metrological event
coordinate remains the separately identified D8 projection. GNSS UART receive,
parse and qualification latency are separate metrics and are not D14 PPS
latency.

The optional D14 GPIO ISR can remain as a minimal, zero-authority diagnostic
observer after it is removed from canonical REF/SNP association. It may record
its own timer and producer ordinal into a bounded diagnostic ring. It must not
touch the hardware counter, trigger capture, delay record publication, or
invalidate canonical observations when its ring loses records. Associate its
events only when hardware/source order is unambiguous; otherwise record a
missing/ambiguous diagnostic match.

Watermark interrupts can represent several capture events. Bind an IRQ sample
to its watermark/notification identity and represented event range; do not
pretend that one interrupt occurred for every edge. Likewise, name a DMA
completion callback timestamp `dma_completion_observed`, not the time the DMA
hardware completed unless that hardware instant has its own captured marker.

### Relate hardware and software clocks without inventing precision

The capture sample counter and RP2040 microsecond counter have different origins
and rates. Their values cannot be subtracted directly, even after a nominal
unit conversion.

Provide a read-only, sequence-tagged clock-correlation transaction. RP2040
records timer values immediately before the request and after the complete
response. The capture engine latches its sample counter at one specified
request-acceptance boundary and returns that value with the transaction token.
The corresponding RP2040 coordinate is enclosed by the before/after timer
observations, including timer quantization. The engine continues input capture
throughout the exchange.

Retain repeated correlation tuples and fit a **bounded** rate/offset relation,
with epoch, validity interval, clock-rate variation allowance and calibration
identity. Do not turn the round-trip midpoint into an exact synchronization.
If these bounds are too wide for the desired latency bins, use a separately
budgeted hardware service-marker input during qualification, or improve the
clock-correlation mechanism before claiming the finer metric.

For example, if the mapped hardware capture lies in RP2040 interval `[c0,c1]`
and first consumption is observed at `m`, its latency lies in
`[m-c1,m-c0]`, widened for endpoint quantization and mapping uncertainty.
Expired mappings, conflicting epochs, ambiguous rollover or inconsistent
ordering produce an unavailable/ambiguous result, not zero or a clamped value.

Use a declared RP2040 timer domain for all software endpoints; both cores share
that timer. Prefer its 64-bit hardware read for new service observations, while
preserving existing canonical low-word records and their explicit extension
contract. A timer-domain relation is not permission to compare it directly
with a D8 count. Host receive timestamps remain in the host monotonic domain:
without a separate bounded host/device mapping, report host-local intervals
only and leave device-capture-to-host latency unavailable.

### Continuous statistics and source-linked tail evidence

Each latency sample identifies capture epoch, channel, source event/snapshot
sequence, stage pair, raw endpoints, domain identifiers, mapping identity,
uncertainty bounds, status and diagnostic sampling policy.

Maintain fixed-size, per-channel/per-stage statistics: observed and eligible
sample counts, unavailable/ambiguous counts, minimum and maximum, a versioned
histogram, threshold-exceedance counts and diagnostic-drop counts. Preserve the
source identities and raw endpoints of maxima and a bounded reservoir of
representative/threshold samples. Histogram binning must respect uncertainty:
do not assign an interval spanning several bins as an exact point sample.
Report definite and possible threshold exceedances separately where needed.

Aggregate at a bounded cadence outside capture handlers. Diagnostic queue
exhaustion drops diagnostic records explicitly and never backpressures capture,
changes raw timestamps, or grants new abort/control authority. Statistics do
not imply complete sampling unless the observation and drop counters prove it.
An observed maximum is not a proven worst-case service bound.

### Latency verification and implementation order

Implement software-stage endpoints and bounded statistics first; they are
useful with the current backend. Label the existing start accurately as the
D14 ISR timestamp. Hardware-to-service metrics become available only once
hardware markers and the clock relation exist. Do not postpone the software
observability until the capture-engine migration is finished.

Deterministically verify endpoint identity, queue publication/consumption,
rollover, delayed/missing markers, partial transfers, batching, mapping expiry,
histogram/threshold ambiguity and diagnostic overflow. Then compare physical
input edges and temporary hardware/service marker outputs on an independent
instrument while applying CPU load, interrupt masking, DMA contention and
serial obstruction. Include marker propagation delay in that measurement.
Measure instrumentation overhead and prove it stays within its frozen budget.
The later D10 stage adds its burst-isolation test to the same path.

The review-time conclusion is also recorded in
[Instrument ownership](INSTRUMENT_OWNERSHIP.md) and
[Reference terminology](../00_FOUNDATIONS/OTIS_REFERENCE_TERMINOLOGY.md): the
implemented ISR-to-service age excludes the physical-edge-to-ISR delay, and
full hardware-latch-to-service measurement remains prospective.

## RP2040-only alternative and why it is not the default production choice

A concrete way to obtain hardware waveform evidence on the existing pins is
two synchronously started PIO samplers, one per signal. Each executes a single
wrapped `IN PINS,1` instruction, with divider 1, 32-bit autopush and an eight-word
RX FIFO. Both use the same PIO block and start/clock-divider operation. DMA moves
the already sampled bits to separate rings. Common bit ordinal, not DMA arrival
time, defines the shared sample coordinate.

This does not require one state machine to read another's `X`. It can retain
the existing hardware count SM independently and add raw waveform windows.
Current explicit PIO0 allocations are two 15-word programs and two SMs: the D8
counter and D6 monitor. Sharing one additional one-word sampler program between
two more SMs would nominally use all four SMs and 31 of 32 instruction words.
Actual build/runtime ownership still needs verification. No spare capacity is
thereby promised for D10.

The arithmetic is significant:

| Quantity                                    | At 133 MHz, one bit per clock per input |
| ------------------------------------------- | --------------------------------------: |
| Sample grid                                 |                                7.519 ns |
| DMA payload per input                       |                             16.625 MB/s |
| Total DMA payload, two inputs               |                              33.25 MB/s |
| FIFO time for eight 32-bit words, per input |                      1.925 microseconds |
| Retention in a 32 KiB ring, per input       |                                1.971 ms |
| Two such rings                              |  64 KiB plus state and retained windows |

The CPU need not stream all of this over USB. It could scan D14 blocks and save,
for example, 256 samples before and after each transition from both rings.
Such a 512-sample pair is 128 bytes and covers about 3.85 microseconds. However,
continuous scanning and copying still have to beat ring overwrite, independently
of serial, estimator and control workload. This is a new strict runtime demand.

There is also a concrete memory obstacle. The retained local
`build/adafruit-release/artifacts/firmware_build_manifest.json` reports 154,216
bytes of static memory against the repository's 157,286-byte limit: only 3,070
bytes of budget headroom. Its 107,928 remaining runtime bytes are a protected
reserve, not permission to spend 64 KiB on capture rings. This is a sizing
reference from that artifact, not a fresh current-tree build result. Do not
weaken the budget or add a runtime allocation to conceal the cost.

DMA address wrapping also does not make a finite transfer count infinite. A
continuous implementation needs gap-free, preconfigured chaining/reload and
unambiguous producer progress across every handoff. Any PIO RX stall destroys
the uniform-sampling assumption for the affected epoch. CPU/IRQ latency can
then cause evidence loss even though it did not alter earlier sample times.

Finally, adding sampled PPS records does not automatically give each waveform
an unambiguous cumulative D8 ordinal. Linking a waveform window to the existing
snapshot requires a proof of the actual count SM's sampled-edge allocation and
source identity, including missed short pulses, startup, stopping and restart.
Ordinal-only pairing is not sufficient. A waveform can remain useful local
evidence even when that global link is unresolved, but cannot be promoted as a
complete replacement record.

**Disposition:** technically useful as a bounded capture experiment, but not
the preferred production architecture under the current memory/service budget.
An independent PIO PPS interval counter is cheaper, but alone still lacks the
atomic D8 count and neighbouring-edge relationship. Neither alternative should
be presented as an already solved fine-capture replacement.

RP2040 facts above are supported by the
[RP2040 datasheet](https://datasheets.raspberrypi.org/rp2040/rp2040_datasheet.pdf),
sections 2.5 and 3.2–3.5, and the
[Pico SDK hardware APIs](https://www.raspberrypi.com/documentation/pico-sdk/hardware.html)
for `pio_enable_sm_mask_in_sync` and `channel_config_set_ring`.

## Future D10 boundary

The external engine can later add D10 to the same sampling clock and D8 count
coordinate, with its own event ordinals, pending store, FIFO, loss counters and
transport quota. Shared sampling does not imply shared backpressure.

Reserve D14 service capacity independently; admit D10 traffic only within a
declared rate/burst envelope. Flooding D10 must neither change D14/D8 sampled
coordinates nor stall their records. Prove arbitration and storage isolation.
D10 remains external-event evidence with no PPS, setup, steering or terminal
authority. No D10 implementation is included in the first stage.

## Finite implementation and qualification programme

1. **Freeze the measurement contract.** Agree the initial sampling target,
   D8 frequency/duty envelope, minimum D14 pulse width, maximum event rate and
   burst, waveform retention scope, coincidence convention and uncertainty
   acceptance criterion. Begin with current 10 MHz D8, not an inferred claim
   of every historical plant's compatibility.
2. **Prove the digital primitive and resources.** Select the engine and link,
   establish timing closure/CDC handling, simulate clock phase and pulse-width
   sweeps, and verify same-sample ordering, counter rollover, missing D8,
   repeated events, full pending stores/FIFOs and persistent gap reporting.
   Complete the electrical and pin audit before any installation.
3. **Integrate producer through replay.** Preserve raw records before selection;
   implement framing, DMA drainage, boot/session identity and deterministic
   replay. Include hardware/CPU service endpoints, bounded clock correlation,
   latency statistics and source-linked tail records. Verify that the first estimator and control consumer receive the
   same exact event/count identity. Do not grant fine estimates control
   authority merely because their records can be emitted.
4. **Rehearse the actual operational path.** Exercise CPU/service load, host
   obstruction, repeated transactions, independent abort, drainage/handoff,
   analysis and sealing. Use deterministic injection for loss and long rollover
   boundaries. No harness result substitutes for hardware capture evidence.
5. **Run a finite observe-only physical comparison.** Use known phase offsets
   across the D14/D8 boundary, including near coincidence, and independently
   observe input edges. Vary signal duty/width and service load; stop/restart
   D8 while PPS continues. Demonstrate unchanged captured values under CPU load,
   no silent loss within the supported envelope, explicit loss outside it,
   and measured differential delay/uncertainty. Ordinary GNSS jitter alone
   cannot identify capture jitter.
6. **Replace at one boundary.** After qualification, use the new raw record as
   the sole precision-capture source; remove GPIO REF ISR dependence and its
   precision association machinery. An optional bounded ISR observer may remain
   solely for the explicitly named diagnostic intervals. Migrate acceptance, metrology, control-source binding,
   resource inventory, host parsers, schemas, methodology, terminology and known
   limitations together. Retain historical evidence under its original identity.

There is no need to repeat historical successful acquisition or invalidate its
integer-count result. The comparison qualifies a new capability. If fine
capture cannot meet the frozen physical or resource requirements, keep the
existing backend and report that result; do not relabel a weaker measurement.

## Decision requested by this proposal

Proceed with the current Nano RP2040 baseline implementation prompt: retain
hardware-owned counting, implement service-stage observability, and assess
hardware markers within a bounded resource/timing study. Use the actual latest
record owner rather than restoring the earlier GPIO/DMA association scheme.
Prefer an external common-clock recorder if the complete fine-capture goal
cannot be met cleanly on the existing hardware. Do not begin an open-ended PIO
rewrite or treat the continuous-sampling estimate as proof that every
RP2040-only approach is infeasible.

This proposal provides architecture and sizing, not a synthesized FPGA image,
RP2040 prototype, physical timing measurement, or approved campaign bundle.
