# PPS PIO Proof and Verification

Status: Stage 1 digital proof passed; hardware timing qualification pending
Mechanism: `pio_wait_cumulative_snapshot_dma_v1`
Proof date: 2026-07-31
Proved clock/envelope: RP2040 `clk_sys` and PIO at 133 MHz, oscillator at
16 MHz, integer duty-cycle stress points 35--65%

## Decision

The single-state-machine, oscillator-edge-driven `WAIT` implementation passes
the repository's digital go/no-go gate. Implementation may continue on the
existing RP2040. This result does not qualify the analog signal path or the
assembled board; the backend remains compiled with
`OTIS_PPS_BOUNDARY_BACKEND_QUALIFIED=0` until the phase-sweep bench campaign
passes.

The proof is bound to the checked-in assembled words and to the firmware
installation. If the program, initial PC, wrap points, pin mappings,
synchronizers, FIFO/autopush configuration, PIO divider, system clock, or DMA
ring configuration changes, `tools/verify_pio_snapshot.py` fails.

If a future version fails this gate, implementation stops. The documented
fallback is an external synchronous counter/latch or CPLD. An ISR, DMA engine,
or second PIO state machine must not be substituted as the aperture owner.

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

D14's GPIO IRQ is an independent REF observer and timestamp source. It does not
stop, restart, inject into, sample, or reset the PIO counter. DMA transports an
already-captured word. Neither ISR latency nor DMA/USB/foreground latency moves
the PIO-owned aperture.

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
required before CNT publication. PIO/DMA restart, continuity loss, association
loss, or oscillator-stop recovery increments the session and repeats this
two-snapshot rule. No interval crosses CPU-owned initialization or rearm.

## Stopped-oscillator behavior

An oscillator which remains low parks at a high `WAIT`; one which remains high
parks at a low `WAIT`. PPS cannot be observed while parked. If oscillation stops
after a `WAIT` has completed, at most the already-entered finite path can run
before the opposite wait parks; any resulting or resume-time late snapshot is
not evidence of a timely PPS boundary.

D14 therefore continues to report REF independently, but an unmatched REF or
missing snapshot invalidates association. Recovery starts a new session and
drops all old association and unread transport state. The first fresh snapshot
is an anchor and its adjacent successor is the first CNT candidate. A word that
appears after an unmatched REF, including one already present when a second REF
is noticed, must never be paired retroactively with the earlier REF.

## FIFO, DMA, and memory ownership

The state machine's RX FIFOs are joined for eight 32-bit words. Autopush occurs
at exactly 32 bits. One dynamically claimed, high-priority DMA channel is paced
by the selected state machine's RX DREQ and writes a 128-word, 512-byte-aligned
circular SRAM ring. The DMA transfer count, read with a stable-read/barrier
protocol, is the producer ordinal; the wrapped address is not used as the sole
progress indicator.

DMA is transport only. It cannot inspect `X`, trigger the snapshot, define PPS,
or repair a missing PIO event. Foreground owns consumption and association but
does not own the boundary.

A full joined RX FIFO stalls `IN`/autopush indefinitely. The proof deliberately
fills all eight words and observes `RXSTALL`; this is outside the valid timing
envelope. Firmware treats sticky `FDEBUG.RXSTALL`, DMA AHB error, unexpected DMA
stop, or a producer-consumer distance above 128 as continuity loss and fails
closed into a new session.

## Installed configuration proved

The repository verifier asserts all of the following against production source:

- Nano RP2040 Connect FQBN includes `freq=133`, and runtime requires
  `clock_get_hz(clk_sys) == 133000000`;
- PIO0, one state machine, program length 15, wrap 0--14, initial PC 11;
- `IN_BASE=GPIO20` for oscillator `WAIT PIN` and `JMP_PIN=GPIO26` for PPS;
- input synchronizer bypass bits cleared for both inputs;
- shift-right, 32-bit autopush, joined RX FIFO, and PIO divider 1.0;
- 32-bit, RX-DREQ-paced, high-priority DMA; and
- 128-word aligned circular ring with fatal transport-fault handling.

## Reproducing the proof

From the repository root:

```sh
python3 tools/verify_pio_snapshot.py \
  --pioasm /Users/richardflynn/Library/Arduino15/packages/rp2040/tools/pqt-pioasm/5.0.0-9576866/pioasm
python3 tools/firmware_matrix.py --profile phase5_qualification
```

The first command must report 7,936 cases, 55,552 intervals, only `-1/0/+1`
boundary errors, a four-clock maximum, and the installed configuration above.
The second must compile the backend at the pinned 133 MHz board setting.

## Remaining bench gate

The backend remains unqualified until the target board passes a 16 MHz phase
sweep with measured pad-level duty cycle and edge quality, 35--65% stress,
sustained USB/serial/DMA load, long-duration continuity, and deliberate fault
injection. The supplied TCXO's 40/60 symmetry and conditioned edge specifications
make this plausible, but the actual waveform at the RP2040 pad is authoritative.

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
