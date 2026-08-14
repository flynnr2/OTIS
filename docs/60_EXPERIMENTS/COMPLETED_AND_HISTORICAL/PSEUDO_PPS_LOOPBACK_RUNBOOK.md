# Deterministic Pseudo-PPS Loopback Runbook

This is a test-only source for exercising the real D14 PPS capture and
PIO/DMA count-snapshot path. Normal firmware profiles compile it out. The
`pseudo_pps_loopback` build boots with the generator idle and D3 high
impedance; no waveform starts without explicit `ARM` and `START` commands.

## Wiring and electrical safety

1. Power down the Nano RP2040 Connect and disconnect the real GPS PPS source.
2. Connect **D3 / GPIO15** through an approximately **1 kOhm series resistor**
   to **D14 / GPIO26**.
3. Connect the instrument grounds. Do not drive D14 from any second source.
4. Flash only the `pseudo_pps_loopback` matrix profile, then power up.

Both pins are 3.3 V GPIO. The resistor limits accidental opposing-drive
current to roughly 3.3 mA, but it does not make contention acceptable. Stop,
completion, abort, underflow, and reset all return D3 to input/high-Z.

## Hardware timing contract

The generator owns exactly one PIO0 state machine and one DMA channel. Its PIO
clock is derived from the validated 133 MHz system clock with a divider of 133,
giving 1 MHz and 1 microsecond resolution. Each finite profile is compiled into
at most 600 logical steps and 1,201 DMA words (two words per physical pulse plus
a terminal sentinel). The nominal period is 1,000,000 microseconds and nominal
high width is 100,000 microseconds; fault-profile values are fixed in firmware.

For the first pulse, the low-loop word is `rise_offset_us - 8`. For subsequent
pulses it is `rise_interval_us - previous_width_us - 7`. The high-loop word is
`width_us - 3`. These constants account for every PIO instruction between pin
transitions; host tests decode the assembled words and prove the reconstructed
rises and widths equal every profile schedule. The first eight words are loaded
before the state machine is enabled, and DMA refills only through the PIO TX
DREQ. Foreground execution never supplies a timing word.

The PIO executes `set pins, 0` before either blocking `pull`. An unexpected TX
stall or DMA bus error therefore latches `underflow`, stops the engine, and
returns D3 to high-Z without manufacturing an edge. The zero sentinel is
consumed while low, sets polled PIO IRQ flag 7, and enters a low terminal loop;
the foreground observes that flag only to publish completion and release D3.
No ISR, second state machine, or foreground delay owns a waveform edge.

## Commands

Commands use the existing newline-delimited, 63-byte-bounded control framing:

```text
PPSGEN PROFILES?
PPSGEN ARM CLEAN_SOAK_10M
PPSGEN START
PPSGEN?
PPSGEN STOP
```

`ARM` is accepted only while not running and only for a built-in v1 profile.
`START` is accepted only from `armed`; `STOP` aborts an armed or running
profile. No command changes a period or width ad hoc. `CLEAN_SOAK_10M` is one
continuous 600-pulse schedule; use it for the clean acceptance run so host
command latency cannot create artificial outages between short blocks.

The isolated loopback matrix profile tightens the reference-acceptance band to
999,500–1,000,500 microseconds. Production profiles retain their own configured
band. The strict test-only band is wide relative to the observed clean hardware
jitter while ensuring the ±100 ms phase steps and sustained ±1 ms offsets are
invalidated instead of being admitted as clean count windows.

## Evidence and expected result

Archive `PGT` rows in `csv/pseudo_pps_truth.csv` alongside `REF`, `SNP`, `CNT`,
`STS`, and diagnostics. `PGT` is intended generator truth, not proof that an
edge reached D14. Compare it against physical detections and valid hardware
snapshots. The `COMPOSITE` profile is exactly: 30 clean pulses; one short
interval; 10 clean; one omission; recovery; a double; a bounce; 30 clean.

Abort the run on `underflow` or `resource_fault`. A `completion` marker is
valid only after the PIO consumed its terminal sentinel while low. Never infer
success from host arrival time or from `PGT` alone.

For a clean profile, do not require exactly 16,000,000 edges per nominal
one-second gate. The generator establishes the gate timing but does not
calibrate the external oscillator. Score the run with
`host.otis_tools.pseudo_pps_acceptance` using an independently referenced
oscillator frequency, a fitted run mean, or a documented nominal value with an
explicit frequency tolerance. Independently require the proved boundary
residual/adjacent-difference bound, sequence continuity, no malformed PPS or
parser loss, and no load-dependent mean or distribution change.

A sufficiently narrow D14 pulse can be observed as REF by the GPIO path while
the oscillator-edge-driven PIO program never reaches a PPS observation point.
That is a legitimate malformed-reference outcome: record the REF, explicitly
assess SNP as absent, invalidate association, publish no valid CNT across the
event, reject any late/ambiguous word, and reacquire with a fresh anchor
followed by an adjacent snapshot. Do not demand one SNP for this electrically
generated malformed pulse.

## Known width-only limitation

The D14 qualification path observes rising-edge cadence; it does not measure
the high time of every reference pulse. A pulse with a 10 microsecond high time
and otherwise nominal one-second rising-edge spacing is therefore intentionally
retained as a capability probe, but it is not distinguishable from a nominal
reference by this backend. Detecting and invalidating that case would require a
falling-edge/pulse-width capture path and a delayed validity decision. Do not
relabel the event as detected or weaken strict scoring. Record the miss as an
explicit width-blind limitation unless the reference threat model justifies
that additional architecture.
