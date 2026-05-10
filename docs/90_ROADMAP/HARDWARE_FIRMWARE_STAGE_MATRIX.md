# OTIS Hardware / Firmware Stage Matrix

This document makes the interaction between OTIS hardware stages and firmware /
host implementation stages explicit.

The firmware roadmap remains the controlling implementation plan for software.
The hardware roadmap defines which physical capabilities are available to test
that software. This matrix states which firmware capabilities can be developed on
early hardware, which require later hardware, and which should be revalidated
when components are substituted.

## Hardware Stage Reference

| Hardware stage | Short name | Representative capability |
|---|---|---|
| H0 | Open-loop MVP | RP2040 + general GPS PPS + TCXO + edge conditioning |
| H1 | First steerable oscillator | OCXO / VCOCXO + 16-bit integrated-reference DAC |
| H2 | Substitution tests | alternate OCXO/DAC/conditioning/control PCB variants |
| H3 | Timing GNSS | timing-grade GNSS PPS, survey/fixed-position mode |
| H4 | Instrument integration | production PCB, power, thermal, shielding, calibrated I/O |

## Firmware / Host Capability Dependencies

| Firmware / host capability | Minimum hardware stage | Why | Later revalidation |
|---|---:|---|---|
| deterministic event capture | H0 | requires only capture inputs and a local timing domain | revalidate at H1/H3/H4 for clock/reference changes |
| raw timestamp logging | H0 | independent of oscillator authority | revalidate after schema or transport changes |
| PPS capture and tagging | H0 | general GPS PPS is sufficient for architecture | revalidate at H3 with timing-grade PPS |
| timestamp-domain terminology | H0 | semantic discipline can start immediately | revalidate whenever a new timing domain is added |
| raw vs adjusted field separation | H0 | can be defined before high-quality adjustment exists | revalidate at H1 once steering/discipline exists |
| host replay tooling | H0 | should operate on raw logs from the beginning | revalidate at every stage as metadata expands |
| basic frequency / phase estimation | H0 | PPS vs local clock comparisons are available | revalidate at H1/H3 with better oscillator/reference |
| run manifests and hardware metadata | H0 | even early hardware must be described explicitly | extend at H1/H2/H3/H4 |
| DAC driver and command logging | H1 | meaningful only once a DAC drives a real control path | revalidate at H2 with DAC substitutions |
| oscillator-control abstraction | H1 | requires steerable oscillator plus DAC/control voltage | revalidate at H2 with alternate oscillators |
| GPSDO-style control loop | H1 | requires closed-loop control of local oscillator | revalidate at H3 with better reference |
| lock / unlock semantics | H1 | lock becomes meaningful once a loop can discipline | tune/revalidate at H3 and H4 |
| holdover semantics | H1 | requires a controlled local reference that can coast | revalidate with better OCXO and thermal design |
| oscillator warmup model | H1 | requires OCXO/VCOCXO behavior | refine at H2/H4 |
| tuning-slope characterization | H1 | requires measurable DAC-to-oscillator response | repeat for each H2 oscillator/control variant |
| DAC quantization/noise analysis | H1 | requires real DAC effect on oscillator control | deepen at H2 with DAC substitutions |
| component-substitution metadata | H2 | requires at least two variants to compare | continue at H3/H4 |
| comparative run reports | H2 | requires repeated runs across controlled substitutions | continue at H3/H4 |
| timing-reference abstraction | H3 | fully exercised by replacing general GPS with timing GNSS | revalidate with external PPS/10 MHz sources later |
| GNSS survey/fixed-position state logging | H3 | requires timing-grade GNSS features | refine with module-specific support |
| PPS-quality / sawtooth metadata | H3 | requires timing GNSS data beyond generic PPS | optional sawtooth correction can follow later |
| production configuration model | H4 | requires settled hardware and build variants | maintain across releases |
| calibration records | H4 | most useful once hardware is mechanically/electrically stable | repeat after repairs or hardware revisions |
| reproducibility documentation | H4 | depends on stable BOM/layout/build process | maintain with each hardware revision |

## Blocking Rules

The following rules should guide implementation sequencing:

1. Do not make the RP2040 firmware depend on a specific application such as a
   pendulum, oscillator test, or GPSDO. Event interpretation belongs host-side.
2. Do not implement DAC/control-loop semantics as final until H1 exists. A DAC
   driver can be prototyped earlier, but closed-loop meaning requires a
   steerable oscillator.
3. Do not treat timing-grade GNSS support as required for the first GPSDO loop.
   H1 should initially retain the general GPS reference so the oscillator-control
   change is isolated.
4. Do not change GNSS reference and oscillator/control hardware in the same
   validation step unless the purpose is explicitly integration testing.
5. Do not let component upgrades redefine timestamp, phase, capture, lock,
   holdover, raw, adjusted, disciplined, or synchronized semantics.
6. Treat every hardware substitution as a metadata and replayability test, not
   merely a performance test.

## Suggested Interleaving

```text
H0 + firmware capture foundation
  -> raw capture, PPS capture, schemas, host replay, run manifests

H1 + firmware control foundation
  -> DAC command path, oscillator model, loop state, lock/holdover, warmup

H2 + substitution validation
  -> module metadata, comparative reports, per-variant calibration records

H3 + reference validation
  -> timing GNSS state, PPS quality metadata, reference-source substitution

H4 + instrument hardening
  -> production config, calibration history, reproducible build docs
```

## Practical Consequence

The first hardware MVP can and should support a large fraction of the firmware
foundation. However, the following capabilities are blocked until H1:

- real DAC-controlled disciplining;
- oscillator tuning-slope characterization;
- meaningful GPSDO lock/holdover behavior;
- DAC quantization/noise impact on oscillator control.

The following capabilities are blocked until H3:

- timing-GNSS survey/fixed-position state;
- timing-grade PPS-quality metadata;
- sawtooth-correction support;
- true reference-source substitution validation.

This preserves a clean sequence:

```text
build capture semantics early;
add control semantics when the oscillator becomes steerable;
validate substitution before upgrading the reference;
harden the instrument only after the semantics survive substitution.
```
