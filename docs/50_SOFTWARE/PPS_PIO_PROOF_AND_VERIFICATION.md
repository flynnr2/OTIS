# PPS PIO Proof and Verification

Status: unchanged instruction aperture; current bounded FIFO transport verified offline.
Historical DMA-backend observe-only qualification was accepted 2026-08-01;
it does not qualify the current IRQ transport. Physical phase/duty margin remains untested.
Mechanism: single-state-machine cumulative snapshot, bounded FIFO IRQ owner.
Instruction proof date: 2026-07-31; current installation binding updated 2026-09-19.
Proved clock/envelope: RP2040 `clk_sys` and PIO at 133 MHz, oscillator at
16 MHz, integer duty-cycle stress points 35--65%

## Decision

The single-state-machine, oscillator-edge-driven `WAIT` implementation passes
the repository's digital go/no-go gate. The later clean, fault, real-GPS,
service-load, extended, and sealed overnight campaign was accepted on
2026-08-01 as observe-only measurement-backend qualification. This result does
not claim pad-level phase/duty margin: the installed ECS fixture cannot control
that test. The historical evidence remains bound to its original image. Current firmware
has one fixed image; the retired qualification profiles and compile-time
backend selector are not current entry points.

The proof is bound to the checked-in assembled words and to the firmware
installation. If the program, initial PC, wrap points, pin mappings,
synchronizers, FIFO/autopush configuration, PIO divider, system clock, or proved FIFO
transport configuration changes, `tools/verify_pio_snapshot.py` fails.

If a future version fails this gate, implementation stops. The documented
fallback is an external synchronous counter/latch or CPLD. An ISR, DMA engine,
or second PIO state machine must not be substituted as the aperture owner.

The later exact-v4-ELF review confirmed that the compiled D14 ISR, DMA, and
foreground paths remain outside this proved aperture. It found no justified
capture micro-optimization and established explicit anti-regression rules for
future firmware in `PPS_CAPTURE_LATENCY_JITTER_AUDIT_20260801.md`.

## Assembled and annotated listing

The installed `pioasm` version is 2.3.0. The program occupies 15 PIO v0
instructions, wraps from PC 14 to PC 0, and starts at PC 11 so enabling the
state machine during an already-high PPS pulse cannot fabricate a snapshot.

| PC | Word | Assembled instruction | Ownership and effect |
|---:|---:|---|---|
| 0 | `20a0` | `wait 1 pin, 0` | Low-PPS state: stall until synchronized oscillator high. `PIN 0` is relative to `IN_BASE=GPIO20`. |
| 1 | `0042` | `jmp x--, 2` | Count the recognized oscillator rise. `X` decrements for both old-X outcomes. |
| 2 | `00c6` | `jmp pin, 6` | Test synchronized PPS using independent `EXECCTRL_JMP_PIN=GPIO26`; high takes the snapshot path. |
| 3 | `2020` | `wait 0 pin, 0` | Low-PPS state: stall until synchronized oscillator low. |
| 4 | `00ca` | `jmp pin, 10` | Test PPS after recognizing oscillator low. |
| 5 | `0000` | `jmp 0` | PPS still low: return to the high wait. |
| 6 | `4020` | `in x, 32` | Copy cumulative `X`; 32-bit autopush commits the immutable boundary word to RX FIFO. |
| 7 | `2020` | `wait 0 pin, 0` | PPS-high state: install the opposite oscillator wait after a high-side snapshot/check. |
| 8 | `00cb` | `jmp pin, 11` | If PPS remains high, continue the PPS-high state without another snapshot. |
| 9 | `0000` | `jmp 0` | PPS low has rearmed the next PPS rise. |
| 10 | `4020` | `in x, 32` | Snapshot path reached from a low oscillator level. |
| 11 | `20a0` | `wait 1 pin, 0` | PPS-high/start state: stall until synchronized oscillator high. |
| 12 | `004d` | `jmp x--, 13` | Count the recognized oscillator rise. |
| 13 | `00c7` | `jmp pin, 7` | PPS still high suppresses another snapshot; PPS low advances toward low wait. |
| 14 | `0003` | `jmp 3` | PPS low: install the low wait before returning to the low-PPS state. |

The instruction words in
`firmware/arduino/otis_nano_rp2040_connect/otis_pps_snapshot.pio.h` are
compared byte-for-byte with the model every time the proof harness is run with
`--pioasm`.

## Cycle-by-cycle timing proof

Every PIO instruction consumes one 133 MHz clock (7.519 ns) when it completes.
A `WAIT` which has not met its condition remains on that instruction and tests
its input on every PIO clock. The proof therefore measures the finite path
after a `WAIT` completes until the opposite-level `WAIT` is installed; it does
not incorrectly treat a stalled `WAIT` as one poll in a long software loop.

The longest paths are:

```text
completed high WAIT at PC 0
  +1  PC 1  decrement X
  +2  PC 2  check PPS
  +3  PC 6  IN X,32 and autopush       (PPS high path)
  +4  PC 7  opposite low WAIT installed

completed high WAIT at PC 11
  +1  PC 12 decrement X
  +2  PC 13 check PPS
  +3  PC 14 branch                     (PPS low path)
  +4  PC 3  opposite low WAIT installed
```

All other completed-`WAIT` paths install the opposite wait in two or three
clocks. The graph verifier explores both outcomes of every reachable `JMP PIN`
and `JMP X--`; its asserted maximum is exactly four clocks, or 30.075 ns.
With a non-full FIFO, `IN X,32` and autopush together consume one instruction
cycle. There are no delay slots.

At 16 MHz the oscillator period is 62.5 ns and there are 8.3125 PIO clocks per
period. A 35/65 waveform has a shortest physical phase of 21.875 ns. The static
four-cycle path is not used alone as a pulse-width argument: while stalled,
each destination `WAIT` samples every 7.519 ns. The instruction-level phase
model verifies the combined behavior.

## Synchronizer and phase model

Both GPIO paths retain the RP2040 two-flop input synchronizers. The simulator
models the two sequential stages explicitly, executes the real 16-bit words,
and keeps oscillator and PPS synchronization independent. `WAIT PIN` reads the
oscillator through `IN_BASE`; `JMP PIN` reads PPS through `JMP_PIN`.

The current deterministic sweep covers:

- 256 oscillator phase offsets for each duty point;
- every integer duty percentage from 35 through 65;
- 7,936 complete cases;
- eight asynchronous PPS edges per case and 55,552 adjacent intervals;
- FIFO service on the valid path; and
- both `IN X,32` snapshot sites.

It produced exactly one snapshot per simulated PPS, no missed or duplicate
synchronized oscillator rises, and this physical-PPS interval error histogram:

| Error relative to physical interval | Intervals |
|---:|---:|
| -1 edge | 17,508 |
| 0 edges | 21,130 |
| +1 edge | 16,914 |

No interval exceeded one-edge asynchronous boundary quantization. This is a
digital sampling result, not a metastability MTBF claim or an analog waveform
qualification. Duty distortion, pad threshold crossing, rise/fall time,
ringing, voltage, and temperature remain bench questions.

## Edge ownership semantics

The PIO state machine alone owns both actions that define a count boundary:

1. recognizing oscillator rises and updating `X`; and
2. recognizing PPS high after a previously recognized low and executing
   `IN X,32`.

After a high oscillator `WAIT` completes, the next instruction decrements `X`
before PPS is tested. If synchronized oscillator high and PPS high become
observable together, the just-counted oscillator rise is present in the
snapshot and closes the interval ending at that PPS. This program-order rule is
stable at both high-side paths.

The current FIFO IRQ reads already committed words and records the CPU service
coordinate. It never triggers or changes a successful snapshot. REF derives
from that same immutable record; no independent GPIO observer remains. Neither
ISR nor USB/foreground latency moves the PIO-owned aperture. Exhaustion stops
the source and preserves evidence as an explicit continuity fault.

## Counter wrap, start, reset, and session behavior

`X` is initialized to zero only while the state machine is disabled at the
start of an acquisition session. A recognized rise performs wrapping
subtraction, including `0x00000000 -> 0xffffffff`. PPS never resets `X`.

For adjacent snapshots:

```text
interval_edges = (previous_X - current_X) mod 2^32
```

The proof tests subtraction across zero. At 16 MHz a complete 32-bit wrap takes
268.435456 seconds. Firmware's valid REF interval is at most 1.2 seconds, so a
valid interval cannot contain a full wrap; any session or gap that cannot prove
that bound is rejected.

Startup begins at PC 11, conceptually in PPS-high state. A PPS low must first be
recognized before the next high can create a snapshot. The first snapshot of a
new session is an anchor only. Two adjacent, sequence-contiguous snapshots are
required before CNT publication. Explicit capture restart opens a new nonzero session and repeats this
two-snapshot rule. Runtime does not automatically clear faults or rearm.
No interval crosses CPU-owned initialization or rearm.

## Stopped-oscillator behavior

An oscillator which remains low parks at a high `WAIT`; one which remains high
parks at a low `WAIT`. PPS cannot be observed while parked. If oscillation stops
after a `WAIT` has completed, at most the already-entered finite path can run
before the opposite wait parks; any resulting or resume-time late snapshot is
not evidence of a timely PPS boundary.

The current single-owner path cannot emit an independent D14 REF while D8
is stopped. A late recognized snapshot remains raw evidence; it is not proof
of timely physical PPS arrival. The recognition bracket and selector preserve
that limitation. See [current ownership](SINGLE_REFERENCE_OWNER_REPAIR.md).

## FIFO and memory ownership

The state machine's RX FIFOs are joined for eight 32-bit words; autopush occurs
at exactly 32 bits. Core 1 drains at most eight words per service and permits
at most one IRQ service between foreground polls. Its 128-record software ring
retains session, ordinal, count, CPU coordinate and uncertainty. Foreground
consumes records; it does not own the boundary. No DMA channel is claimed.

A full joined FIFO stalls autopush and leaves the valid timing envelope. Sticky
RXSTALL, exhausted service budget or software-ring capacity stops the source
and state machine without clearing retained words. Explicit recovery requires
a new session after evidence preservation. Native backend tests cover these
failure paths separately from the continuously drained instruction proof.

## Installed configuration proved

The repository verifier asserts all of the following against production source:

- Nano RP2040 Connect FQBN includes `freq=133`, and runtime requires
  `clock_get_hz(clk_sys) == 133000000`;
- PIO0, one state machine, program length 15, wrap 0--14, initial PC 11;
- `IN_BASE=GPIO20` for oscillator `WAIT PIN` and `JMP_PIN=GPIO26` for PPS;
- input synchronizer bypass bits cleared for both inputs;
- shift-right, 32-bit autopush, joined RX FIFO and PIO divider 1.0; and
- the bounded FIFO-drain transport and explicit RXSTALL handling.

Native integration checks additionally exercise ring capacity, IRQ budgets,
source filtering, loss preservation and explicit session transitions.

## Reproducing the proof

From the repository root:

```sh
python3 tools/verify_pio_snapshot.py \
  --pioasm /Users/richardflynn/Library/Arduino15/packages/rp2040/tools/pqt-pioasm/5.0.0-9576866/pioasm
python3 tools/build_firmware.py
```

The first command must report 7,936 cases, 55,552 intervals, only `-1/0/+1`
boundary errors, a four-clock maximum, and the installed configuration above.
The second must compile the fixed image at the pinned 133 MHz board setting.

## Remaining physical characterization

Sustained USB/serial/DMA load, long-duration continuity and deliberate fault
injection passed for the historical accepted DMA image. The current FIFO IRQ
image requires its own authorized physical gate; offline checks are not that gate. A controlled 16 MHz PPS phase
sweep with measured pad duty/edge quality and 35--65% stress remains not tested
because the installed ECS fixture cannot generate it. It is a documented,
non-blocking physical-margin limitation rather than a passed test. The supplied
TCXO's 40/60 symmetry and conditioned edge specifications make acceptable
operation plausible, but the actual waveform at the RP2040 pad remains
authoritative if a capable future fixture tests it.

If the bench test finds missed/double edges, errors beyond the allowed direct
counting boundary quantization, RX stalls under supported load, or an input
waveform outside the validated envelope, stop and use the external
counter/latch or CPLD fallback.

## Primary device evidence

- `docs/datasheets/RP2040.datasheet.A700000007747462.pdf`: independent
  `WAIT PIN`/`JMP PIN` mappings, one-cycle PIO instructions, input
  synchronizers, shift/autopush, FIFO join, and DMA DREQ behavior.
- `docs/datasheets/ECS-TXO-5032.pdf`: supplied 16 MHz TCXO symmetry and
  rise/fall limits.
- `docs/datasheets/sn74lvc1g17.pdf`: Schmitt buffer propagation and input
  conditioning limits.
- `docs/datasheets/ABX00053-schematics.pdf`: Nano RP2040 Connect signal path;
  no hidden autonomous counter/capture latch exists.

## Current 10 MHz assessment (2026-09-19)

The verifier also runs the unchanged instruction words at nominal 10 MHz:
7,936 cases and 55,552 adjacent intervals, all within -1/0/+1 model boundary
error. A separate exhaustive reachable-state check proves at most ten PIO
clocks from D14 high presented to the SM to IN, conditional on synchronized
D8 high/low dwells of 4–9 clocks, an armed D14 that remains high and no FIFO
stall. Recognition itself precedes IN by exactly one clock with unchanged X.
These are digital endpoints, not a pad-level or timer-domain latency claim.
The historical two-flop phase model does not model the complete input mapping
pipeline or physical synchronizer behavior. See the [current assessment](PPS_CAPTURE_CURRENT_ASSESSMENT_2026_09_19.md)
for assumptions, current results, alternatives and diagnostic unavailability.
