# PPS Capture Latency and Jitter Audit — 2026-08-01

Status: accepted engineering conclusion and regression constraint

Scope: the `pio_wait_cumulative_snapshot_dma_v1` PPS-gated count path on the
Arduino Nano RP2040 Connect with the ECS 16 MHz source and real GPS PPS. This
audit determines where latency can affect the measurement, what the accepted
campaign can and cannot identify, and which invariants later firmware must
preserve.

## Decision

The authoritative PPS-gated `CNT` aperture is already at the practical useful
limit of the selected RP2040 integer-edge architecture. One PIO state machine
counts oscillator edges and copies its own cumulative counter at a recognized
PPS rise. CPU interrupt latency, ISR body length, DMA arbitration, foreground
scheduling, USB traffic, serial commands, telemetry formatting, and core
assignment all occur outside that aperture.

No capture-firmware change is justified by the accepted evidence. In
particular, making the D14 diagnostic ISR shorter or moving it to RAM could
improve its reconstructed `REF` timestamp, but it cannot reduce the official
raw-count spread. Future work must not describe such an ISR change as a count
aperture or frequency-resolution improvement.

This is not a claim of zero latency, zero jitter, or isolated firmware jitter.
The declared digital result is bounded integer-edge allocation at asynchronous
boundaries. Pad threshold, metastability margin, GPS PPS behavior, ECS behavior,
power, temperature, and other physical effects remain combined in the
end-to-end evidence unless independently measured.

## Audited build and source identity

The instruction audit used the exact qualification-v4 artifact later exercised
by the sealed overnight run:

```text
profile: phase5_qualification
FQBN: rp2040:rp2040:arduino_nano_connect:freq=133
compiler: arm-none-eabi-g++ 16.1.0
Arduino-Pico core: 6.0.0
UF2 SHA-256: c33d877e6d419cf253131060ebf19e3c2465379cd770a660ca280c357b2b851f
ELF SHA-256: 4bc54d39f60ad9b0e936133b9b6dbc756e6c678f2e74bb0ce00325ca0e0349cf
```

The relevant sources copied into that build are identical to the current PIO
backend, D14 IRQ, capture ring, boundary ring, and count-observation sources
apart from Arduino's generated `#line` directives. The ELF contains the
expected 15 assembled PIO words byte-for-byte.

Primary local artifacts:

- `build/firmware_flashes/20260731_real_gps_phase5_qualification_v4/phase5_qualification/artifacts/firmware_build_manifest.json`
- `build/firmware_flashes/20260731_real_gps_phase5_qualification_v4/phase5_qualification/artifacts/otis_nano_rp2040_connect.ino.elf`
- `runs/phase5_pps_backend/pps_remediation_20260801T004553Z_real_gps_overnight_alternating_load_v4`

## Timing-domain audit

| Layer | Mechanism | Can move the official count boundary? |
|---|---|---|
| Oscillator counting | PIO `WAIT` plus `JMP X--` | Yes; this is the authoritative edge counter. |
| PPS counter snapshot | `IN X, 32` in the same PIO state machine | Yes; this is the authoritative boundary action. |
| PIO input synchronizers | enabled independently on oscillator and PPS | They establish the asynchronous digital sampling boundary and its bounded edge allocation. |
| RX FIFO and DMA | completed-word transport to an SRAM ring | No. Delay can create backlog or, on exhaustion, an explicit invalidating fault. |
| D14 GPIO IRQ | reconstructed `micros()` REF timestamp and compact event | No. It validates and associates the reference but does not latch, stop, reset, or read the PIO counter. |
| Foreground, USB, serial, preview, sensors | pairing, validation, emission and services | No. Delay can create reported backlog/loss; it cannot change an immutable PIO snapshot. |

Absolute latency is therefore not the governing count metric. What matters is
whether asynchronous boundary allocation is bounded and whether any variable
software delay lies between the physical event and the counter snapshot. The
first is proved to one oscillator edge for the declared digital envelope; the
second has been removed by construction.

## PIO instruction conclusion

At a pinned 133 MHz PIO clock, one PIO cycle is approximately 7.52 ns. The
longest reachable valid path from a completed oscillator `WAIT` until the
opposite-level `WAIT` is installed is four cycles, approximately 30 ns. The
16 MHz oscillator period is 62.5 ns. A stalled `WAIT` re-evaluates its input on
every PIO clock; it is not a software polling loop.

The exhaustive instruction model covered 7,936 phase/duty cases and 55,552
adjacent PPS intervals. It found no missed or double-counted synchronized
oscillator rise and only -1, 0, or +1 edge interval-boundary error. For every
tested contiguous span from one through seven intervals, total span error also
remained -1, 0, or +1 rather than accumulating.

There may be another valid encoding that saves a PIO cycle on one branch. Such
a change would not beat integer endpoint quantization or improve the declared
one-edge result at 16 MHz. It would change the proved program and require the
full proof and proportionate bench gates again. Instruction-count reduction is
not, by itself, an engineering reason to make that change.

Input-synchronizer bypass is specifically rejected as a latency optimization.
It would trade a small nominal delay for worse metastability protection without
improving the integer-edge measurement contract.

## CPU and ISR instruction conclusion

The exact v4 ELF was compiled for Cortex-M0+ with `-Os` and no LTO flag. Its
D14 callback is 200 bytes and its capture-ring push is 120 bytes. The first
substantive callback action calls `micros()`. That function is a small direct
timer-register read. `digitalRead`, event initialization, diagnostic counters,
and the ring copy all follow the timestamp.

The Arduino core's shared GPIO dispatcher executes before the callback, and
the callback executes from XIP flash at the default interrupt priority. Thus
the reconstructed D14 timestamp is not the minimum-latency GPIO timestamp the
RP2040 could produce. A direct SDK handler, RAM-resident code, a direct timer
read, or a different priority could reduce diagnostic timestamp latency or
variation.

Those changes are not count-path optimizations. The official PIO snapshot has
already occurred, and the handler's remaining work occurs after its own
timestamp. Their only plausible value would be a future requirement for more
precise diagnostic REF timing or much more closely spaced fault edges. Such a
requirement must be stated and tested before changing the current code.

## Evidence-based spread disposition

The sealed overnight comparison contains 16,798 exact, traceable one-second
windows. Raw counts range from 15,999,995 through 15,999,999, with population
spread approximately 0.78 Hz. There was no PIO, DMA, ring, parser, session, or
continuity fault, and the snapshot backlog high-water was one.

A descriptive post-qualification audit found:

- reconstructed D14 interval population spread of approximately 3.5 us;
- Pearson correlation between exact-window reconstructed D14 interval variation
  and raw count of approximately 0.004, effectively absent for this dataset;
- similar quiet/load raw-count distributions and an aggregate load-minus-quiet
  difference of approximately -0.03 Hz, retained as characterization; and
- approximately 0.52 Hz population spread among non-overlapping 60-second block
  means, while the proved digital endpoint bound over a clean 60-second
  cumulative span is one edge total, approximately 0.017 Hz when expressed as
  a span mean.

The one-second spread is compatible with asynchronous integer-edge allocation
plus slower end-to-end behavior. After modest cumulative averaging, the
non-accumulating digital endpoint bound is much smaller than the observed
block-to-block behavior. The longer-term variation therefore cannot reasonably
be assigned primarily to CPU/ISR latency. It remains combined ECS/GPS/input/
environmental behavior because this campaign has no independent traceable
counter, physical phase sweep, or complete environmental attribution.

These values are descriptive characterization, not new component tolerances or
an uncertainty budget.

## Normative regression invariants

All later firmware evolution must preserve these rules unless an explicit
architecture decision replaces this mechanism and repeats its gates:

1. One PIO state machine must remain the sole owner of oscillator counting and
   the cumulative PPS snapshot.
2. The D14 IRQ, DMA, foreground, another core, PWM, and any second PIO state
   machine must not stop, reset, reload, inject into, read, or define the
   authoritative counter aperture.
3. DMA remains transport of an already immutable PIO word. Backlog, RX stall,
   DMA error, stopped DMA, and ring overwrite remain explicit fail-closed
   conditions, never timing corrections.
4. Oscillator and PPS input synchronizers remain enabled. The system/PIO clock,
   divider, pins, `WAIT`/decrement/snapshot ownership, FIFO/autopush settings,
   and assembled program words remain bound to the proof.
5. Any change to those proof-bound items must fail review until
   `tools/verify_pio_snapshot.py`, the static architecture tests, the firmware
   matrix, and proportionate hardware evidence pass for the new identity.
6. The first snapshot is an anchor only. A gap, fault, restart, association
   loss, or outage requires a new session/anchor and a second clean snapshot.
   A late word must never be paired retroactively.
7. Raw `CNT.counted_edges` remains the adjacent same-session cumulative
   snapshot difference. D14 timer-normalized frequency remains diagnostic and
   must not replace or rewrite the raw count.
8. Service load must remain outside the aperture. Moving estimator or control
   work between cores must not redefine hardware capture ownership.
9. One-second raw observations remain preserved for traceability and fault
   localization. Longer estimator spans should use cumulative snapshot
   endpoints so the digital edge-allocation error does not accumulate.
10. A claimed improvement below the one-edge instantaneous contract requires a
    different capability, such as phase interpolation, a time-interval
    measurement path, or an external synchronous counter/latch. ISR tuning is
    not evidence for such a claim.

The repository tests intentionally enforce the most important source-level
parts of these invariants. Reviewers must still inspect semantic changes;
string-level tests cannot prove architectural intent on their own.

## Roadmap consequence

The capture-latency question is closed for the accepted observe-only backend.
The next work is estimator/preview integration, not speculative aperture
micro-optimization. Preserve raw one-second snapshots and characterize
cumulative estimator spans; approximately 60--120 seconds is a data-supported
range to explore, not a frozen control constant. Physical phase/duty margin
remains not tested and non-blocking on the present fixture. Active actuation
remains a separate reviewed gate.
