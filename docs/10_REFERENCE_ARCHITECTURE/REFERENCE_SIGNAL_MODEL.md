# Reference Signal Model

OTIS treats reference signals as observable evidence, not as hidden assumptions.

A reference signal may be used for epoching, comparison, syntonization,
synchronization, discipline estimation, or oscillator characterization, but it
should remain visible in the raw record stream whenever practical.

## Core Distinction

OTIS distinguishes between:

- the MCU system clock that runs firmware, USB, DMA, and housekeeping;
- the capture domain in which hardware timestamps are latched;
- reference signals presented to the timing fabric as observable inputs;
- derived or reconstructed domains produced later by firmware or host analysis.

For the RP2040 MVP, OTIS does **not** require replacing the RP2040 system clock
with an external oscillator. A TCXO, OCXO, GPSDO output, or oscillator under test
should initially enter the system as a conditioned GPIO signal observed by PIO and
DMA.

```text
RP2040 board clock
  -> runs firmware / USB / PIO / DMA / housekeeping

TCXO / OCXO / oscillator under test
  -> conditioning / buffer
  -> RP2040 GPIO / PIO
  -> counted, timestamped, or compared as observed reference evidence

GNSS PPS
  -> RP2040 GPIO / PIO
  -> captured as a reference event
  -> used for epoching, interval comparison, and later discipline analysis

External event inputs
  -> conditioning / comparator / buffer
  -> RP2040 GPIO / PIO
  -> captured as application-neutral timing events
```

## Reference Signal Classes

| Signal class | Example | Initial OTIS treatment |
|---|---|---|
| MCU system clock | RP2040 board oscillator | implementation clock; not automatically metrological truth |
| Reference event | GNSS PPS | `REF_CAPTURE` observation |
| Reference oscillator | 10 MHz TCXO / OCXO | observed pulse train or counted reference signal |
| Oscillator under test | XO / TCXO / OCXO output | observed event stream for host-side comparison |
| User event | photogate / comparator / trigger | `EVENT_CAPTURE` observation |
| Control output | DAC code / enable / pulse output | explicit control telemetry, not a substitute for raw observations |

## MVP Policy

The Stage 1 RP2040 MVP should prefer open-loop measurement:

```text
reference signals in -> capture fabric -> raw observations out -> host replay
```

It should not initially hide the reference oscillator inside the MCU clock tree.
Keeping the oscillator observable preserves:

- explicit clock-domain semantics;
- raw evidence for later replay;
- visibility into reference quality;
- freedom to compare multiple references;
- a clean boundary between measurement and discipline/control.

## Capture Domain vs Reference Source

A `capture_domain` names the domain in which `timestamp_ticks` were latched. It
is not necessarily the same thing as the physical source being measured.

For example, a TCXO pulse train captured by an RP2040 PIO program may produce
records whose `capture_domain` is the local RP2040 capture domain, while the
input source identity is described by channel configuration, manifest metadata,
or reference-state telemetry.

Do not infer that a timestamp is in the TCXO domain merely because the TCXO was
the signal being captured.

## Future GPSDO / Steered-Oscillator Stages

Later OTIS stages may add:

- DAC steering;
- OCXO or VCXO EFC control;
- discipline state machines;
- holdover policy;
- reference output distribution;
- alternative capture fabrics.

Those stages should still preserve the raw reference observations that justified
any estimator, lock-state, or DAC decision.

A disciplined oscillator may become part of a future timing fabric, but that is a
later architecture choice, not a Stage 1 assumption.

## Design Rule

Reference oscillators enter OTIS first as signals to be observed. They may later
become sources to be steered, distributed, or promoted into a timing fabric, but
that promotion must be explicit in the run manifest, telemetry, and provenance.
