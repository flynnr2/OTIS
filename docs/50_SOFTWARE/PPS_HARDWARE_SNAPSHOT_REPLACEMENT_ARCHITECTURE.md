# PPS Hardware-Snapshot Replacement Architecture

Status: selected for implementation; Stage 1 digital proof passed, bench qualification pending
Decision date: 2026-07-31
Scope: replacement architecture for the failed PPS-gated ratio aperture; no firmware implementation is made by this note

## Decision

Use one PIO state machine to observe both the oscillator input and PPS input. The
state machine continuously maintains a wrapping 32-bit oscillator-edge counter
and copies that counter to its RX FIFO when it recognizes a PPS low-to-high
transition. A DMA channel drains the already-captured words into a circular SRAM
ring.

This is a hardware-owned boundary because the same autonomous state machine that
recognizes PPS also snapshots its own counter state. CPU interrupt latency, USB
load, and DMA bus latency occur after the snapshot and cannot move the
measurement aperture.

The selected program is edge-driven: `WAIT PIN` blocks on the oscillator level,
while the independently selected `JMP PIN` path observes PPS. A stalled `WAIT`
evaluates its input every PIO clock, so the oscillator is not sampled only once
per complete control loop. The assembled program has passed the Stage 1 static
cycle analysis and exhaustive instruction-level phase/duty sweep at an
explicitly pinned 133 MHz `clk_sys`. The declared digital envelope is now
16 MHz with 35--65% duty cycle. Analog board qualification remains mandatory.

If the program cannot meet that timing gate, stop. The acceptable fallback is an
external synchronous counter/latch or small CPLD clocked by the oscillator and
latched by PPS. Moving the late read to DMA, another PIO state machine, or a
different CPU ISR is not an acceptable fallback.

## Why the replaced architecture failed

The rejected `pps_isr_stop_sample_restart_v1` implementation made the D14 GPIO
ISR the aperture owner. On each PPS interrupt it:

1. disables the oscillator-counting PIO state machine;
2. injects instructions to copy and push the remaining loop count;
3. reads the FIFO;
4. restarts, reloads, and re-enables the state machine.

The measured interval therefore begins and ends when software services the GPIO
interrupt, not when PPS crosses the input synchronizer. Interrupt entry time and
the stop/read/restart sequence vary with USB and foreground activity. Timer
normalization can describe that variable software interval, but cannot repair
the count aperture or make the result qualification-grade.

The failed qualification evidence remains evidence about that implementation.
It must not be reclassified after this replacement is introduced.

## Alternatives considered

| Candidate | Result | Reason |
|---|---|---|
| One PIO state machine owns oscillator count and PPS snapshot | **Selected** | PPS recognition and counter copy execute in one deterministic hardware instruction path. |
| Separate oscillator and PPS PIO state machines | Rejected | RP2040 state machines can synchronize with IRQ flags but cannot exchange register data. A second state machine cannot atomically snapshot the first state machine's `X`. |
| PIO counter with DMA acting as the PPS latch | Rejected | DMA requests and bus transfers are arbitrated after the event. DMA can move a captured word but cannot define a coherent PPS boundary. PIO scratch registers are not memory-mapped DMA sources. |
| PWM external edge counter | Rejected | The 16-bit PWM counter has no external capture register. Its B input selects the count event and cannot independently latch on PPS. |
| Frequency counter (`FC0`) | Rejected | `FC0` measures over an internally configured interval and has no PPS-triggered capture path. |
| Timer alarm/capture or interpolator | Rejected | The RP2040 timer has no external pin-capture input, and interpolators are CPU execution units rather than autonomous event capture hardware. |
| Reset an interval counter at every PPS in one PIO state machine | Rejected | Reset/push sequencing creates edge-accounting dead time. A cumulative counter permits adjacent snapshots and modulo subtraction without stopping oscillator observation. |
| External counter/latch or CPLD | Viable fallback | It satisfies the invariant, but requires a hardware change and is unnecessary if the Stage 1 PIO timing proof passes. |

## Selected signal path

```text
 D8 / GPIO20 oscillator ----\
                              > PIO0 state machine
 D14 / GPIO26 PPS -----------/   - recognizes oscillator rises
                                  - maintains wrapping X down-counter
                                  - recognizes PPS rise
                                  - copies X to ISR/RX FIFO
                                             |
                                      RX DREQ (transport)
                                             |
                                      one DMA channel
                                             |
                                  128-word SRAM snapshot ring
                                             |
                                      foreground pairing
                                       /             \
                         adjacent snapshot delta    D14 REF timestamp
                                  CNT value          gate-time evidence
```

Neither the D14 ISR nor DMA may stop, reset, reload, read, or otherwise alter the
PIO counter. Input synchronizers remain enabled for both asynchronous inputs.

## PIO counter and edge semantics

The program encodes oscillator and PPS phase in its control state. It alternates
blocking waits for oscillator high and low; each stalled `WAIT` evaluates its
mapped oscillator input every PIO clock. Between completed waits it checks the
independently mapped PPS input:

- a recognized oscillator low-to-high transition executes `JMP X--` once;
- a recognized PPS low-to-high transition copies the current `X` into the input
  shift register with a 32-bit `IN X, 32`, causing an autopush to the RX FIFO;
- a PPS high period produces one snapshot and must be followed by a recognized
  low before another snapshot can be produced;
- a stuck oscillator blocks the state machine and therefore blocks further PPS
  snapshots;
- a stuck PPS does not block oscillator counting; and
- `X` is initialized once per acquisition session and is never reset at PPS.

The exact instruction listing is an implementation artifact, not something to
infer from pseudocode in this note. It must be assembled with the installed PIO
assembler and checked against an exhaustive transition/cycle model before
integration.

### Simultaneous sampled edges

After a high `WAIT` completes, `JMP X--` executes before the corresponding PPS
check. If the synchronized oscillator and PPS become high together, that
oscillator rise is included in the snapshot and therefore closes the interval
ending at that PPS boundary. This stable program-order rule is encoded in the
instruction-level proof.

### Counter arithmetic

`X` is a wrapping 32-bit down-counter. Define the logical cumulative count at
snapshot `n` as:

```text
C[n] = -X[n] mod 2^32
```

The interval count is:

```text
delta[n] = C[n] - C[n-1] mod 2^32
         = X[n-1] - X[n] mod 2^32
```

The existing increasing-counter wrap helper must not be reused blindly. The
down-counter convention should have one named helper with boundary tests around
`0x00000000` and `0xffffffff`.

Modulo subtraction is unambiguous only when policy proves the physical interval
contains fewer than `2^32` oscillator edges. At 16 MHz, one wrap takes about
268.4 seconds. The configured maximum oscillator frequency and REF timestamp
gap must jointly rule out a full wrap. Any gap that cannot do so is invalid,
even if the modulo delta looks plausible.

## Timing and frequency envelope

The qualification target is the supplied nominal 16 MHz TCXO signal.

The firmware matrix must explicitly select a 133 MHz system clock for every
build that enables this backend. It must not inherit the Arduino core's current
board-menu default, because that default can change and may exceed the RP2040
datasheet maximum.

At PIO divider 1:

```text
worst completed WAIT to opposite WAIT installed = 4 PIO cycles
4 / 133 MHz                                      = 30.08 ns
16 MHz period                                    = 62.50 ns
35% minimum high or low phase                    = 21.88 ns
```

The four-cycle installation bound alone is not a sufficient pulse-width proof,
because a stalled `WAIT` tests its input every 7.52 ns rather than only after
the control path completes. Stage 1 therefore combines the path bound with an
instruction-level model of the two-flop synchronizers and all oscillator phase
offsets. The two distinct gates are:

1. **Before firmware integration:** assemble the real program, prove every
   reachable valid control path, and simulate 256 phase offsets at every integer
   duty cycle from 35% through 65%, including PPS transitions, two-flop input
   synchronization, and snapshot autopush with FIFO space. A full FIFO is an
   explicitly unbounded fault path, not part of the valid timing envelope. This
   gate passed for 7,936 cases and 55,552 adjacent PPS intervals; interval error
   was confined to -1, 0, or +1 oscillator edge.
2. **Before qualification:** measure input duty cycle, synchronizer behavior,
   phase sweep, and temperature/voltage margin on the target board.

The first gate is sufficient to continue implementation and has passed. The
second requires hardware. Until it passes, the backend remains explicitly
unqualified. The proof and immutable assembled listing are recorded in
`PPS_PIO_PROOF_AND_VERIFICATION.md`.

## FIFO, DMA, and SRAM ring

- Join the selected PIO state machine's FIFOs for an eight-word RX FIFO.
- Use one high-priority DMA channel paced by that RX FIFO's DREQ.
- Transfer 32-bit snapshot words into a naturally aligned 128-word
  (`512` byte) circular SRAM ring.
- Program a long transfer count and derive the producer ordinal from the
  monotonic decrement of `TRANS_COUNT`; do not use the wrapped write address as
  the only progress indicator.
- Publish/consume DMA progress with the required RP2040 memory barrier and
  stable-read protocol.

Sequence number `0` is the first DMA-produced snapshot of an acquisition
session. The foreground consumer keeps a 32-bit hardware producer ordinal and a
separate extended software count if needed for telemetry.

DMA is deliberately not the aperture owner. Normal DMA latency may delay the
arrival of the word in SRAM, but the word already contains the PIO value from
the PPS transition. The RX FIFO absorbs short arbitration delays.

### Overflow and transfer faults

The 128-word ring can retain at most 128 unread PPS snapshots. Before reading a
slot, foreground computes producer-consumer distance from the DMA transfer
count. A distance greater than 128 means data was overwritten:

- increment the explicit drop/overwrite counter;
- discard all unread snapshot slots;
- clear the current anchor and REF association;
- wait for a fresh snapshot anchor and then an adjacent snapshot before
  publishing another CNT value.

PIO `FDEBUG.RXSTALL`, an unexpected stopped DMA channel, or a DMA AHB error is a
hardware transfer fault. Report it and fail closed. Because autopush stalls when
the RX FIFO is full, such a fault can eventually stall the state machine and
lose oscillator edges; recovery must therefore start a new acquisition session
outside any interval reported as valid.

No overflow, sequence gap, duplicate, out-of-order word, or transfer error may
be normalized into a valid sample.

## Boundary, startup, and recovery rules

| Condition | Required behavior |
|---|---|
| First PPS snapshot after boot/rearm | Establish anchor only; do not emit CNT. |
| Second adjacent valid snapshot | First interval that may emit CNT. |
| 32-bit counter wrap | Use down-counter modulo subtraction if the timestamp/frequency envelope proves fewer than `2^32` edges. |
| Missing PPS | Counter continues. Timeout is diagnostic; the eventual long pair is invalid and acquisition rearms. |
| Missing/stuck oscillator | The SM parks in `WAIT`; D14 REF events continue independently, missing snapshots invalidate association, and recovery starts a new session with two fresh snapshots before CNT. A snapshot already on the finite post-`WAIT` path when oscillation stops is late/unusable and is never paired retroactively. |
| PPS held high | Produce exactly one snapshot until a recognized low rearms PPS. |
| PPS bounce or short/long interval | Retain hardware snapshots for diagnosis, but reject the interval under REF quality rules. |
| Narrow PPS seen by GPIO but not sampled by PIO | Preserve REF, report `ref_without_snapshot`, invalidate and close association, reject any late/ambiguous word, rearm and clear old transport state, then require a fresh anchor plus adjacent snapshot; never publish a CNT across the event. |
| PIO/D14 observer sequence disagreement | Invalidate association and rearm; do not guess which event was real. |
| DMA/ring overflow | Report loss, discard unread data, and require a fresh anchor plus adjacent snapshot. |
| PIO or DMA restart | Start a new session and require two new snapshots; never bridge a restart. |
| System-clock or PIO-divider change while armed | Forbidden. Treat any forced change as session invalidation. |

## ISR and observer roles

### D14 PPS GPIO ISR

The D14 ISR remains useful for the reconstructed REF timestamp and signal
diagnostics, but it is no longer a count boundary:

- remove the call that stops/samples/restarts the PIO counter;
- enqueue D14 as a normal REF observation with its captured timer tick;
- never touch the PIO state machine, FIFO, DMA channel, or counter from the ISR.

Foreground associates the `n`th PIO snapshot with the `n`th D14 REF observation
within one acquisition session. The snapshot delta is the authoritative CNT
numerator. Adjacent D14 timestamps provide gate-time evidence and retain the
`TIMESTAMP_RECONSTRUCTED` provenance; they do not define the physical counting
aperture.

If the PIO and GPIO observers do not see the same sequence, no clean CNT sample
is published until association is re-established.

### D10 dual observer

The D10 observer stays independent and diagnostic-only. It must never trigger,
reset, validate, or substitute for the PIO snapshot. Disagreement among D10,
D14, and PIO sequences is a fail-closed quality diagnostic, not a voting
mechanism.

## Resource ownership

The resource registry and ownership document must be changed with the
implementation, not ahead of it.

| Resource | Proposed owner/use |
|---|---|
| D8 / GPIO20 | PIO oscillator input |
| D14 / GPIO26 | Shared physical PPS input: PIO snapshot input plus GPIO REF observer |
| PIO block/state machine | One dynamically claimed PIO0 state machine |
| PIO instruction memory | Actual assembled program length, replacing the current fixed five-word claim |
| PIO RX DREQ | Snapshot transport request |
| DMA channel | One dynamically claimed high-priority channel |
| SRAM | One aligned 128 × 32-bit snapshot ring plus consumer state |
| D10 / GPIO5 | Existing independent PPS witness; unchanged |

The ownership model must represent D14's two read-only consumers without
claiming that the GPIO IRQ owns the count boundary. A suitable composite role is
`pps_capture_fabric`; the authoritative `boundary_owner` remains the PIO state
machine.

PIO1 is not assumed available, and a second state machine is not required.

## Pseudo-PPS injection assignment

The guarded `pseudo_pps_loopback` build assigns D3 / GPIO15 to the deterministic
pseudo-PPS generator. Normal and real-GPS builds do not claim it and leave it
as an input. The generator additionally returns D3 to high impedance whenever
it is disabled, stopped, complete, or faulted.

The loopback fixture must place approximately 1 kΩ in series between D3 and
D14. The real GPS/PPS driver must be physically disconnected before the
generator is armed so that two outputs cannot contend. D4 / GPIO16 and D5 /
GPIO17 remain unassigned alternatives, not runtime-selectable generator pins.

Do not repurpose D10, D7, D8, D14, D9, D2, D13, the I2C pins, serial pins, or
Nano RP2040 Connect internal-only pins for this fixture.

## Contract and telemetry migration

Keep the public backend selector `PPS_GATED_RATIO`, but give this mechanism a
new identity:

```text
boundary_owner=pio_state_machine
aperture_backend=pio_wait_cumulative_snapshot_dma_v1
```

Startup/status telemetry should additionally expose:

- counter width and direction;
- PIO block, state machine, program offset/length, clock, and divider;
- declared maximum oscillator frequency;
- RX FIFO depth, DMA channel, ring capacity, producer sequence, and consumer
  sequence;
- snapshot overwrite count, PIO RX stall state, DMA error state, and recovery
  session number;
- D14-to-PIO association state and D10 observer disagreement counters; and
- an explicit `qualified=false` state until the new backend passes its own
  qualification campaign.

The raw CNT contract must change from “count captured by the PPS ISR” to
“difference between adjacent PIO-owned cumulative snapshots.” `gate_ticks`
remains the difference between adjacent associated D14 REF timestamps and must
not be described as the counter's aperture. Timer-normalized rate remains a
diagnostic value and must not become the qualification estimator.

The host qualifier must reject the old identity when testing the replacement,
require raw snapshot/count fields, require contiguous hardware snapshot
sequences, and fail on any session change, overflow, observer mismatch, or
transfer fault. Existing evidence and parsers for
`pps_isr_stop_sample_restart_v1` remain identifiable as the old mechanism.

## Staged implementation plan

Each stage should be a reviewable commit and leave all no-hardware checks green.

1. **PIO primitive and proof**
   - write and assemble the dual-input program;
   - add an exhaustive four-level-state transition simulator;
   - prove the four-cycle opposite-`WAIT` installation bound and simultaneous-edge rule;
   - pin the qualification matrix to 133 MHz;
   - stop with no integration if the proof fails.
2. **Snapshot transport**
   - add PIO initialization, joined RX FIFO, DMA claim/configuration, aligned
     128-word ring, stable producer reading, and fault/overflow handling;
   - keep the new backend unreachable except from focused tests.
3. **Measurement integration**
   - replace the ISR boundary hook with PIO/DMA snapshot consumption;
   - keep D14 REF capture and D10 witness independent;
   - implement sequence association, down-counter delta, validity, rearm, and
     session behavior.
4. **Contracts, resources, and host**
   - update resource claims, raw/status schemas, host parsing, and qualifier
     identity checks together;
   - retain explicit compatibility handling for historical old-backend data.
5. **Pseudo-PPS and bench enablement**
   - choose one candidate pin only after schematic/front-end review;
   - implement a guarded test-only generator and contention-safe startup;
   - run phase, duty-cycle, load, duration, and fault-injection tests.
6. **Qualification**
   - begin a new evidence run under the new mechanism identity;
   - do not amend or reuse the failed ISR-owned run as passing evidence.

## No-hardware verification required

- Assemble the PIO source using the pinned installed toolchain.
- Exhaustively sweep 256 oscillator phase offsets at every integer 35--65% duty
  point while modelling both input synchronizers.
- Assert one decrement per recognized oscillator rise and one snapshot per
  recognized PPS rise.
- Assert the oscillator-decrement-before-PPS-snapshot simultaneous-edge convention.
- Calculate every valid path from a completed oscillator `WAIT` until the
  opposite-level `WAIT` is installed, including snapshot/autopush with FIFO
  space.
- Model a continuously draining FIFO and deliberately stalled DMA; prove that a
  full FIFO is detected as an invalidating fault rather than assigned a finite
  sampling guarantee.
- Test ring-address wrap, exact capacity, overwrite by one word, producer
  ordinal arithmetic, consumer delay, and stable publication.
- Test down-counter arithmetic across zero and reject ambiguous full-wrap gaps.
- Test startup anchor, missing/duplicate PPS, missing oscillator, PIO/D14
  mismatch, observer overflow, DMA error, and controlled rearm.
- Statistically inject arbitrary CPU/USB/serial delays after the PIO snapshot
  and assert that snapshot values and interval deltas are unchanged.
- Assert through static source checks that the D14 ISR cannot disable, restart,
  inject into, or read the PIO counter.
- Update the firmware matrix and host contract tests to require the new
  mechanism identity.

These tests can establish the digital state-machine semantics and demonstrate
that software delay is no longer in the boundary path. They cannot establish
analog input integrity or the real board's timing margin.

## Bench questions that remain

- What oscillator high/low pulse widths reach the synchronized GPIO across
  voltage and temperature?
- Does a phase sweep between the 16 MHz oscillator and PPS ever produce a
  missed/double edge or violate the declared simultaneous-edge convention?
- Does PPS input rise time, ringing, or front-end conditioning create additional
  PIO-recognized transitions?
- Does sustained USB/serial load produce any FIFO stall or DMA error telemetry?
- Does the system remain lossless across the intended run duration, and does
  deliberate DMA starvation fail closed?
- Whether the selected D3 pseudo-PPS path is electrically safe on the assembled board, and
  is the real PPS source isolated before loopback drive?

## Go/no-go checkpoint

**Go** for the coordinated replacement implementation. The assembled-program
digital proof passed for the declared 16 MHz, 35--65% duty envelope because PPS
recognition and the counter snapshot occur in the same PIO state machine,
before DMA or CPU service. This is not yet a bench qualification result.

**No-go** for:

- operation outside the proved 16 MHz, 35--65% digital envelope;
- any build that does not explicitly pin and report the proven PIO/system clock;
- calling the D14 IRQ, DMA, PWM, or a second PIO state machine the aperture
  owner; or
- qualification before the bench timing-margin questions are closed.

The smallest remaining uncertainty is not architectural ownership. It is
whether the Nano RP2040 Connect pad actually receives a waveform inside the
proved duty/rise/fall envelope across the intended conditions. Stage 1 resolves
the digital half; the 16 MHz phase-sweep bench campaign resolves the electrical
half.

## Primary references

- [RP2040 Datasheet](https://datasheets.raspberrypi.com/rp2040/rp2040-datasheet.pdf):
  PIO state machines, FIFOs, synchronization, DMA pacing, PWM, clocks, and timer.
- [Pico SDK hardware API](https://www.raspberrypi.com/documentation/pico-sdk/hardware.html):
  installed-core APIs and register-level ownership needed by the implementation.
- [Arduino Nano RP2040 Connect full pinout](https://docs.arduino.cc/resources/pinouts/ABX00053-full-pinout.pdf):
  header pin and RP2040 GPIO mapping.
