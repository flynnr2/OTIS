# Current D14/D8 capture assessment

The existing hardware aperture is retained. It captures the authoritative D8
count one PIO clock after recognizing D14. A faster IRQ cannot improve that
capture. No small replacement examined here supplies an earlier, independently
clocked D14 coordinate with the same atomic D8 association and proved counting
margin. This is a bounded assessment of the present Nano implementation, not an
impossibility result for every RP2040 design.

## What is captured, and when

D14/GPIO26 and D8/GPIO20 retain input synchronization. In the unchanged
15-instruction program, D8 `WAIT` completion leads to `JMP PIN` tests of D14.
PC 2 tests D14 after the D8 rise has decremented X; PC 4 tests it after D8 low.
A high at either test in the armed state selects PC 6 or PC 10 respectively.
The very next instruction is `IN X,32`, committing the cumulative downcounter
through 32-bit autopush. No instruction decrements X between that D14 test and
its capture. This is exactly one `clk_sys` period, 1/133,000,000 second, with a
non-full FIFO. The proof now checks both the one-cycle relation and unchanged X.

The recognized D14 high and the immediately following count copy belong to
one hardware operation. X counts D8 rises recognized by this state machine,
modulo 2^32; it is not an RP2040 timer timestamp or a fractional D8 coordinate.
A D8 rise already counted on the high-side path is included. A later physical
D8 rise between the D14 test and IN does not update X there. That program-order
rule does not resolve the physical order of nearly coincident input edges.

The delay **before** the D14 test depends on D8 phase and duty. A pending D8
WAIT cannot test D14 until the required D8 level arrives. A stopped D8 parks
capture; a long dwell can arbitrarily delay recognition. Short D14 activity
between checks can be missed. Startup deliberately suppresses an already-high
PPS until a low has been recognized; the bounds below apply only after arming.

## Conditional digital bound, not a physical accuracy claim

The exact-word verifier now explores every reachable armed program state and
every subsequent synchronized D8 waveform whose high and low dwells each span
4 through 9 PIO samples. It explores all allowed dwell lengths independently,
not just a finite periodic phase sweep. Among 109 reachable states, 50 are armed, including both rearm branch paths.
Provided D14 stays high until recognized and the RX FIFO does not stall:

| Endpoint interval in the PIO execution domain | Proved digital bound |
|---|---:|
| D14 high first presented to the SM → D14 JMP recognizes high | 0–9 clocks |
| D14 JMP recognizes high → IN captures X | exactly 1 clock |
| D14 high first presented to the SM → IN captures X | 1–10 clocks (at most 75.188 ns at 133 MHz) |

An ideal 10 MHz waveform at 35–65% duty has 4.655–8.645 system clocks per
physical high/low phase; sampling with equal fixed input delays yields 4–9
samples. These are declared digital premises, **not measurements of the bench
waveform**. D8 frequency/duty excursions, metastability resolution, distorted
pulses, a stopped oscillator or FIFO stall may violate them. A regression with
longer allowed D8 dwells verifies that the bound grows; existing stopped-D8 and
RXSTALL checks preserve explicit unavailability outside the valid envelope.

The input synchronizers add nominally two clocks. The datasheet also identifies
a register between input mapping and each SM. Pad propagation, sampling phase,
that pipeline, input skew and metastability remain outside the bound above.
The phase-sweep model retains its historical ideal two-flop abstraction; it
must not be read as a complete electrical-pad latency model. No absolute
pad-to-IN maximum or nanosecond physical accuracy follows from these tests.
Removing synchronization would sacrifice asynchronous input protection, not
establish a sound precision improvement. Device details are in the
[RP2040 datasheet, §§3.2–3.5, especially §3.5.6](https://datasheets.raspberrypi.org/rp2040/rp2040-datasheet.pdf).

The current nominal 10 MHz sweep supplements the historical 16 MHz sweep:
7,936 cases, 55,552 adjacent intervals, 256 phase offsets at each integer duty
35–65%, eight D14 pulses per case. Errors against the model's continuous-time
D8 interval count were -1: 8,831; 0: 38,289; +1: 8,432. Every contiguous span
through seven intervals also stays within one edge. Across 63,488 snapshots,
SM-presented D14-to-recognition ranged from zero to nine clocks. Those extrema
are sweep observations; the separate reachable-state proof establishes the
conditional bound. Neither substitutes for physical waveform qualification.

## Why the assessed changes are not installed

| Candidate | Concrete limit for this requirement |
|---|---|
| Shorten recognition-to-IN | Already the next single-cycle instruction. Moving the copy before the branch would capture speculatively and require new ownership/selection semantics. |
| Reorder WAIT/branches | May redistribute phase-dependent response, but cannot inspect D14 while a D8 WAIT stalls. It provides neither an independent D14 coordinate nor a stopped-D8 bound. No proved superior replacement is offered. |
| Poll both inputs in one SM | `JMP PIN` selects one input. Sampling/extracting both levels and updating edge state replaces the WAIT counting loop and its pulse-width margin; it is a new capture implementation requiring a complete count/overflow proof, not an added timestamp. |
| Second event-driven D14 SM | Can detect D14 independently but cannot read the first SM's X. Joining separate ordinals fails to establish identity across startup, short pulses, missing D8, loss and restart. A handshake would alter the original aperture and capture a later count. |
| Read timer with DMA/CPU after an event | Produces a later service/bus coordinate. It does not latch the timer at the D14 edge, and nominal clock-rate conversion does not establish a phase mapping. |
| Continuous paired waveform sampling | At 133 MHz, two one-bit streams require 33.25 MB/s of SRAM writes. Two 32 KiB rings retain only 1.971 ms and exceed the fixed memory headroom; scanning, reload and count association add new deadlines. |

Current explicit allocation is two PIO0 SMs and two separately loaded 15-word
copies (30/32 instructions), including the isolated D6 monitor. D8 uses PIO0
IRQ1 and the existing 128-record ring, with no DMA. PIO1/spare DMA could host
work but do not solve the ownership and clock-mapping problems. No new SM,
instruction, DMA channel, IRQ, SRAM store or runtime work is added here.
The final integrated image supplies its own resource audit; no resource limit
or protected reserve is relaxed to support a capture experiment.

## Contract and verification integration

SNP v2 continues carrying one capture session/source ordinal, raw X and the
actual FIFO-service timer coordinate. The existing prior-empty/service bracket
continues to bound **PIO recognition**, with its one-microsecond publication
allowance; it does not become an electrical-edge bracket. Downstream REF and
LAT use the same snapshot identity. The conditional PIO-clock bound is static
implementation evidence, not an individual sampled coordinate and not a
verified live dwell measurement. It therefore cannot tighten a SNP bracket or
be written into any software-stage field.

LAT v1 retains `hw=0`. PIO-recognition-to-service, electrical-edge-to-service
and fractional D8-cycle capture remain unavailable. Canonical raw evidence is
unchanged. No new parallel timestamp stream or GPIO observer is introduced.

Reproduce with the pinned assembler:

```sh
python3 tools/verify_pio_snapshot.py --pioasm /Users/richardflynn/Library/Arduino15/packages/rp2040/tools/pqt-pioasm/5.0.0-9576866/pioasm
```

The tool binds the real assembled words, generated header, pins, clock,
synchronizers, FIFO and installed backend; reports both frequency sweeps and
the current dwell bound; and checks counter wrap, startup, stopped input and
FIFO exhaustion. Native regressions cover these proof entry points. These are
offline checks. The planned finite zero-write bench observation may assess
service behavior and continuity but cannot independently measure pad-to-capture
accuracy or qualify the assumed D8 waveform envelope. No additional physical
acquisition is requested merely to support this negative design finding.
