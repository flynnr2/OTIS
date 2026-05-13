# OTIS Hardware Development Stages

This document captures the current hardware-development ladder for OTIS. It is
intentionally framed as **strong opinions, loosely held**: the point is not to
freeze one bill of materials, but to make the substitution seams explicit enough
that hardware changes test the architecture rather than accidentally redefining
it.

The staged firmware roadmap should remain the controlling plan for software
implementation. This document complements it by describing which hardware
capabilities should be introduced at each stage and what each substitution is
intended to prove.

## Guiding Principle

OTIS should progress by replacing one timing block at a time:

```text
capture architecture first
-> steerable oscillator second
-> oscillator/DAC substitution third
-> timing-grade GNSS fourth
-> instrument-grade integration fifth
```

The goal is not simply to buy better parts. The goal is to demonstrate that OTIS
can preserve stable timing semantics while reference sources, oscillators, DACs,
conditioning circuits, and event sources are substituted.

## Stage 0 - Open-Loop Architecture MVP

Representative hardware:

```text
RP2040
Adafruit Ultimate GPS Breakout
ECS-TXO-5032-160-TR 16 MHz TCXO
SN74AHCT1G14 clock/edge conditioning
host-side logging and analysis
```

Purpose:

- prove deterministic event capture on the RP2040;
- establish raw timestamp logging;
- exercise PPS capture and timestamp-domain naming;
- prove host-side replay and analysis workflow;
- keep the hardware cheap, understandable, and debuggable.

This stage is not expected to be a high-authority timing reference. The Adafruit
GPS module and modest TCXO are sufficient to develop the architecture, telemetry,
logging, terminology, and analysis contracts.

Expected result:

- OTIS can capture events against an explicit timing domain;
- raw and adjusted quantities are clearly separated;
- the host can reconstruct and explain timing behavior;
- component quality is visible as metrological authority, not baked into capture
  semantics.

## Stage 1 - First Steerable Oscillator / GPSDO Stage

Current H/SW staging splits this into `H1` hardware preparation followed later
by `SW2` control-loop firmware. See `H1_STEERABLE_OSCILLATOR_PREP.md` for the
open-loop bring-up criteria that should be met before closed-loop steering work
starts.

Representative hardware:

```text
RP2040
Adafruit Ultimate GPS Breakout, initially retained as PPS reference
surplus or evaluation-board OCXO / VCOCXO
16-bit integrated-reference DAC, e.g. AD5683R / AD5693R class
low-pass / protection / scaling network for oscillator control voltage
clock conditioning into the RP2040 timing domain
```

This stage intentionally collapses the earlier idea of a separate "add DAC" stage
and "replace oscillator" stage. A DAC is only architecturally meaningful once it
is steering a real oscillator or a realistic oscillator-control input. Therefore,
the first control-loop stage should introduce the steerable oscillator and DAC
together.

Purpose:

- prove the oscillator-control abstraction;
- implement the first real GPSDO-style loop;
- log DAC commands, loop state, estimator provenance, and oscillator-control
  metadata;
- characterize warmup, tuning slope, holdover, and control-voltage behavior;
- keep the GNSS reference constant so the oscillator-control change is isolated.

Recommended DAC posture:

Use a modest 16-bit integrated-reference DAC from the start of this stage rather
than beginning with a 12-bit development DAC.

Rationale:

- the cost delta is small compared with an OCXO, PCB work, and test time;
- 16-bit resolution avoids early ambiguity about DAC quantization limits;
- an integrated reference reduces external precision-reference decisions;
- the software/control telemetry can be designed around the serious path from
  day one;
- it better matches OTIS's goal of being a credible timing instrument rather than
  a toy GPSDO demo.

Caveat:

A 16-bit DAC does not create a 16-bit system. Layout, supply noise, oscillator
control sensitivity, thermal gradients, grounding, filtering, and loop design can
all dominate the DAC data-sheet numbers.

Expected result:

- OTIS can steer an oscillator while preserving explicit provenance;
- the control loop is explainable from logs;
- the oscillator block is represented by measured parameters rather than hidden
  assumptions.

Example oscillator metadata:

```yaml
oscillator:
  role: disciplined_local_reference
  type: ocxo
  nominal_hz: 10000000
  output_form: sine_or_cmos_conditioned
  control_input: dac_voltage
  tuning_slope_hz_per_volt: measured
  warmup_model: measured
  holdover_model: measured
```

Example DAC metadata:

```yaml
dac:
  role: oscillator_control
  resolution_bits: 16
  reference: integrated
  output_range_volts: measured
  code_to_voltage_model: measured
  command_logging: required
```

## Stage 2 - Oscillator and DAC Substitution Tests

Representative substitutions:

```text
OCXO A -> OCXO B
AD5683R-class DAC -> AD5693R / LTC2641-class DAC
breadboard/control lash-up -> first small control PCB
simple output conditioning -> cleaner buffer/filter chain
```

Purpose:

- prove that the oscillator-control module is actually substitutable;
- distinguish DAC limits from oscillator limits;
- measure whether better analog parts produce visible improvements;
- validate that metadata and telemetry capture the differences without schema
  churn.

This stage should not change the GNSS reference unless the experiment explicitly
requires it. Keep the reference side stable while changing the local oscillator
and analog-control path.

Key questions:

- does a better oscillator improve raw stability before disciplining?
- does a better DAC reduce visible quantization, noise, or limit-cycle behavior?
- does the loop need different gains because the oscillator tuning slope changed?
- can the host analysis compare runs without special-case interpretation?

Expected result:

- OTIS treats oscillator/DAC choices as module parameters;
- substitutions change measured performance, not the meaning of timestamp,
  phase, lock, holdover, or adjusted quantities.

## Stage 3 - Timing-Grade GNSS Reference

Representative hardware:

```text
u-blox ZED-F9T-class timing GNSS
survey-in / fixed-position timing mode
clean PPS path into RP2040 capture
optional sawtooth-correction support later
existing OCXO + DAC path retained initially
```

Purpose:

- replace the general GPS breakout with a timing-grade reference source;
- test the reference-source abstraction independently of the oscillator-control
  abstraction;
- determine whether improved PPS quality is visible in loop residuals, lock
  behavior, holdover transitions, and long averaging windows.

This stage should retain the already-characterized steerable oscillator path at
first. Otherwise, improved GNSS and changed oscillator behavior become difficult
to separate.

Expected result:

- OTIS can substitute a better timing reference without redefining capture or
  adjustment semantics;
- reference quality is recorded as authority/provenance metadata;
- the host can compare general-GPS and timing-GNSS runs cleanly.

Example reference metadata:

```yaml
reference:
  role: primary_time_reference
  type: gnss_pps
  module_class: timing_grade
  mode: survey_in_or_fixed_position
  pps_accuracy_class: measured_or_datasheet
  sawtooth_correction: optional_later
```

## Stage 4 - Instrument-Grade Integration

Representative work:

```text
purpose-designed PCB
quiet power tree
separate analog/digital return strategy
thermal management around OCXO and DAC/reference path
shielding and connector discipline
calibrated reference inputs/outputs
front-panel or appliance-style host integration
```

Purpose:

- turn the validated development architecture into a serious instrument;
- reduce environmental and layout-induced error sources;
- make the build reproducible by others;
- preserve modularity while improving analog hygiene.

This is the point where precision analog details should become first-class
engineering work. Earlier stages should avoid premature analog perfection unless
needed to answer a specific experiment.

Expected result:

- stable, reproducible hardware;
- documented build variants;
- credible comparison between low-cost and higher-authority configurations;
- a platform others can extend without semantic drift.

## Recommended Interleaving with Firmware Stages

| Hardware stage | Firmware / host emphasis |
|---|---|
| Stage 0 - open-loop RP2040 + GPS + TCXO | capture primitives, raw logs, schema discipline, replay tooling |
| Stage 1 - OCXO + 16-bit DAC | oscillator model, DAC command path, loop state, lock/holdover semantics |
| Stage 2 - substitution tests | module metadata, run manifests, comparative analysis reports |
| Stage 3 - timing GNSS | reference metadata, PPS-quality fields, survey/fixed-position state |
| Stage 4 - instrument integration | production configuration, calibration records, reproducibility docs |

## Practical Recommendation

The preferred near-term sequence is:

```text
1. Build Stage 0 with the RP2040, Adafruit GPS, ECS TCXO, and AHCT1G14.
2. Move directly to a steerable OCXO plus a 16-bit integrated-reference DAC.
3. Swap oscillator and DAC variants deliberately to test substitutability.
4. Only then replace the general GPS breakout with timing-grade GNSS.
5. Harden the analog, power, thermal, and mechanical design once the seams work.
```

That ordering keeps the project focused on OTIS's core claim: transparent,
reproducible timing instrumentation in which better components increase
metrological authority without changing the meaning of the data.
