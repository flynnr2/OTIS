# OTIS MVP Hardware Reference

This document captures the initial hardware direction for the OTIS MVP.

The OTIS MVP intentionally prioritizes:

- deterministic timing semantics;
- architectural clarity;
- reproducibility;
- observability;
- replayable telemetry;
- disciplined reference-centric timestamping.

The MVP does not initially attempt:

- state-of-the-art phase-noise performance;
- sub-nanosecond interpolation;
- telecom-grade holdover;
- ultra-low-cost optimization.

The intent is to establish a scientifically serious reference architecture that is:

- understandable;
- reproducible;
- extensible;
- experimentally useful.

---

# Hardware Philosophy

OTIS should define:

- timing semantics;
- architectural boundaries;
- instrumentation behavior;
- telemetry contracts;

rather than hard-coding dependence on specific vendors or parts.

Where possible:

- interchangeable DACs;
- interchangeable oscillators;
- interchangeable GNSS receivers;

should remain feasible behind stable conceptual interfaces.

---

# MVP Hardware Layers

| Layer                  | Purpose                                           |
|------------------------|---------------------------------------------------|
| GNSS reference         | external UTC-disciplined timing reference         |
| Disciplined oscillator | stable local frequency reference                  |
| Timing fabric          | deterministic counting and event capture          |
| Steering               | oscillator frequency adjustment                   |
| Power                  | low-noise analog and digital rails                |
| Host                   | telemetry, replay, dashboards, analysis           |
| Distribution           | buffered timing outputs and input conditioning    |

---

# 1. Timing Fabric MCU

Initial OTIS MVP implementations are expected to use an RP2040/RP2350-class MCU.

The timing fabric should:

- count disciplined reference cycles;
- capture external events deterministically;
- capture GNSS PPS edges;
- generate structured telemetry;
- isolate timing truth from host/UI activity.

## Candidate Parts

| Component                  | Notes                                                |
|----------------------------|------------------------------------------------------|
| Raspberry Pi Pico 2        | likely initial reference implementation              |
| RP2350                     | preferred long-term MCU family direction             |
| Raspberry Pi Pico          | acceptable early-development platform                |
| RP2040 module variants     | acceptable if clocking and power are well specified  |

## Initial Direction

The Raspberry Pi Pico 2 is likely the best initial OTIS MVP target because it provides:

- PIO state machines;
- deterministic digital timing behavior;
- DMA;
- dual cores;
- strong tooling ecosystem;
- broad availability.

---

# 2. GNSS Timing Receiver

The GNSS receiver establishes the external timing reference.

The receiver should prioritize:

- high-quality PPS behavior;
- timing-oriented firmware support;
- good community understanding;
- stable operation.

## Candidate Parts

| Component                  | Notes                                                |
|----------------------------|------------------------------------------------------|
| u-blox ZED-F9T             | likely best modern serious timing choice             |
| u-blox NEO-M8T             | excellent proven timing receiver                     |
| u-blox LEA-M8T             | mature timing-oriented option                        |
| u-blox timing evaluation kits | useful during early development                  |

## Initial Direction

The ZED-F9T is probably the strongest long-term target.

The NEO-M8T remains attractive because:

- widely understood;
- proven in timing applications;
- lower cost;
- easier experimentation.

---

# 3. Oscillator

The oscillator is the heart of the system.

OTIS should initially prioritize:

- stability;
- repeatability;
- observability;
- clean control behavior.

## Oscillator Classes

| Oscillator Type | Notes                                                |
|-----------------|------------------------------------------------------|
| TCXO            | useful for early experimentation                     |
| VCXO            | useful for learning discipline behavior              |
| OCXO            | preferred serious MVP direction                      |
| Rubidium        | future advanced experimentation                      |

## Candidate OCXOs

| Component                          | Notes                                         |
|------------------------------------|-----------------------------------------------|
| Bliley NV47 series                 | respected modern OCXO family                  |
| Connor-Winfield DOCXO series       | strong modern commercially available options  |
| Isotemp OCXO 134 series            | widely used in Time-Nuts experimentation      |
| Morion MV89 / MV85 surplus units   | common surplus experimentation path           |
| Oscilloquartz surplus OCXOs        | historically respected telecom-grade units    |

## Initial Direction

The MVP should probably target:

- a controllable OCXO;
- 10 MHz output;
- analog steering input;
- reasonable availability.

Surplus telecom OCXOs are entirely acceptable for early OTIS experimentation.

---

# 4. DAC / Steering

The DAC steers the oscillator.

The steering path should prioritize:

- low noise;
- monotonicity;
- stable reference behavior;
- predictable temperature behavior.

## Candidate Parts

| Component                  | Notes                                                |
|----------------------------|------------------------------------------------------|
| MCP4822                    | simple early experimentation DAC                     |
| AD5683R                    | attractive precision integrated-reference DAC        |
| AD5693R                    | precision low-noise option                           |
| LTC2641                    | attractive precision candidate                       |
| MCP4728                    | acceptable early-development option                  |

## Initial Direction

Initial OTIS versions should emphasize:

- architecture correctness;
- telemetry visibility;
- deterministic behavior;

before pursuing extreme DAC refinement.

---

# 5. Timing Distribution and Conditioning

OTIS should eventually provide:

- buffered 10 MHz outputs;
- buffered PPS outputs;
- external event inputs;
- optional isolated paths.

## Candidate Parts

| Component                  | Notes                                                |
|----------------------------|------------------------------------------------------|
| 74LVC1G17                  | useful Schmitt-trigger conditioning                  |
| 74AHCT1G125                | level shifting / buffering                           |
| NB3L553                    | clock fanout experimentation                         |
| LMK1C110x family           | future higher-performance clock distribution         |

---

# 6. Power Architecture

Power integrity is critical.

OTIS should prioritize:

- analog/digital rail separation;
- low-noise regulation;
- careful grounding;
- thermal stability;
- deterministic power-up behavior.

## Candidate Approaches

| Component / Approach       | Notes                                                |
|----------------------------|------------------------------------------------------|
| LT3042 regulators          | strong low-noise analog rail candidate               |
| Separate analog/digital rails | strongly encouraged                             |
| Linear regulation          | preferred for sensitive timing sections              |
| Shielded OCXO enclosure    | likely beneficial later                              |

---

# 7. Host Systems

Linux hosts are optional but first-class.

The host should provide:

- append-only logging;
- replay tooling;
- dashboards;
- telemetry archival;
- analysis.

## Candidate Hosts

| Component                  | Notes                                                |
|----------------------------|------------------------------------------------------|
| Raspberry Pi Zero 2 W      | likely ideal initial OTIS host                       |
| Raspberry Pi 4 / 5         | useful for heavier analysis and dashboards           |
| Linux laptop/workstation   | entirely valid development environment               |

---

# 8. Environmental Instrumentation

Environmental telemetry is important because timing systems are strongly affected by:

- temperature;
- supply stability;
- airflow;
- enclosure behavior.

## Candidate Parts

| Component                  | Notes                                                |
|----------------------------|------------------------------------------------------|
| SHT41                      | strong humidity and temperature sensor               |
| BMP280                     | useful pressure and temperature telemetry            |
| PT100/PT1000 probes        | future higher-accuracy thermal instrumentation       |

---

# 9. Future FPGA / CPLD Direction

OTIS is initially MCU-first.

However, the architecture should remain compatible with future:

- FPGA timing fabrics;
- interpolation engines;
- advanced phase detectors;
- higher-performance reciprocal counters.

## Candidate Future Directions

| Component                  | Notes                                                |
|----------------------------|------------------------------------------------------|
| Lattice ECP5               | attractive open FPGA ecosystem                       |
| ICE40 family               | accessible experimentation platform                  |
| Small CPLDs                | useful for deterministic glue logic                  |

---

# Initial MVP Summary

The likely initial OTIS MVP hardware stack currently looks approximately like:

| Function                   | Likely Initial Choice                                |
|----------------------------|------------------------------------------------------|
| Timing MCU                 | Raspberry Pi Pico 2                                  |
| GNSS receiver              | u-blox ZED-F9T or NEO-M8T                            |
| Oscillator                 | controllable 10 MHz OCXO                             |
| DAC                        | precision SPI DAC                                    |
| Host                       | Raspberry Pi Zero 2 W                                |
| Timing fabric              | RP2040/RP2350 PIO + DMA                              |
| Logs and analysis          | Linux-based append-only telemetry tooling            |

This should be viewed as:

- an architectural reference point;
- an experimental baseline;
- an evolving instrumentation platform;

rather than a permanently fixed BOM.
