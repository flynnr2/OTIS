# OTIS Future Directions — RP2040 Sensor & DSP Possibilities

_Status: exploratory / future-looking_  
_Priority: intentionally low during MVP phase_

---

# Purpose

This document captures potentially interesting future directions for OTIS-like systems using the Raspberry Pi RP2040 platform (especially the Arduino Nano RP2040 Connect), while explicitly avoiding current scope creep.

The intent is:
- preserve useful ideas;
- avoid rediscovering them later;
- maintain architectural clarity;
- keep MVP focus on sacred timing capture.

---

# Guiding Principle

OTIS should aggressively preserve the distinction between:

## Sacred Capture Path
Deterministic, timestamp-grade event acquisition.

Examples:
- PPS capture
- comparator edge timing
- photogate transitions
- disciplined oscillator measurements

Characteristics:
- deterministic;
- low-jitter;
- minimal ISR latency;
- minimal software involvement;
- provenance-preserving.

## Interpretation / Analysis Path
Higher-level interpretation, DSP, visualization, ML, networking, etc.

Examples:
- FFTs
- vibration analysis
- microphone DSP
- gesture classification
- anomaly detection
- dashboards
- WiFi
- cloud publishing

Characteristics:
- disposable;
- non-deterministic acceptable;
- latency-tolerant;
- replaceable/evolvable.

This separation may become one of OTIS's defining architectural principles.

---

# Why RP2040 Is Interesting

The RP2040 is attractive because it combines:

- dual-core architecture;
- DMA;
- large SRAM;
- PIO (Programmable IO);
- flexible clocking;
- strong embedded DSP potential.

The Arduino Nano RP2040 Connect additionally integrates:
- IMU;
- microphone;
- WiFi/Bluetooth;
- crypto chip.

Relevant features from the board datasheet include:
- dual-core Cortex-M0+ at 133 MHz;
- 264 kB SRAM;
- DMA controller;
- 8 PIO state machines;
- 16 MB external QSPI flash;
- onboard IMU;
- onboard PDM microphone;
- onboard secure element.  [oai_citation:0‡ABX00053-datasheet.pdf](sediment://file_0000000045b0720a81aead706f5c8ec9)

---

# PIO (Programmable IO)

PIO is arguably the RP2040's most important OTIS-relevant feature.

PIO can:
- timestamp edges;
- implement custom serial protocols;
- generate deterministic pulse trains;
- offload timing-sensitive logic from CPU cores.

Potential OTIS uses:
- PPS capture;
- comparator edge capture;
- pulse-width measurement;
- custom timing interfaces;
- deterministic trigger generation.

PIO is far more interesting to OTIS than WiFi or ML features.

---

# Dual-Core Partitioning

A plausible long-term architecture:

## Core 0 — Sacred Timing
Responsibilities:
- PPS capture
- edge timestamping
- disciplined timing
- ring buffers
- deterministic acquisition
- minimal interrupt latency

## Core 1 — Disposable Services
Responsibilities:
- DSP
- UI
- WiFi
- visualization
- telemetry
- FFTs
- anomaly detection
- sensor fusion

This maps naturally onto OTIS philosophy.

---

# ST LSM6DSOXTR IMU

Integrated 6-axis IMU:
- 3-axis accelerometer
- 3-axis gyroscope
- FIFO
- interrupt engine
- machine-learning core
- embedded temperature sensor.  [oai_citation:1‡ABX00053-datasheet.pdf](sediment://file_0000000045b0720a81aead706f5c8ec9)

Potential future OTIS uses:
- environmental vibration characterization;
- disturbance detection;
- transport/shock logging;
- identifying external vibration coupling;
- preserving "interesting intervals";
- detecting human interaction with clocks/instruments.

Examples:
- HVAC vibration;
- floor resonance;
- building motion;
- nearby traffic/elevator/plumbing effects.

Interesting concept:
- IMU-triggered preservation of high-rate timing ring buffers.

---

# ST MP34DT06JTR Digital MEMS Microphone

Integrated omnidirectional digital MEMS microphone:
- PDM interface;
- 64 dB SNR;
- audio-oriented MEMS sensing element.  [oai_citation:2‡ABX00053-datasheet.pdf](sediment://file_0000000045b0720a81aead706f5c8ec9)

Potential future uses:
- escapement acoustics;
- beat detection;
- anomaly detection;
- recoil/drop/lock characterization;
- case resonance analysis;
- audio-assisted diagnostics.

Professional watch timing machines are fundamentally:
- precision acoustic acquisition systems;
- plus DSP.

---

# Important Caveat About the Microphone

The onboard microphone is:
- DIGITAL;
- PDM-based.

This means:
- DSP/decimation required;
- not naturally edge-oriented;
- less suitable for sacred timestamp capture.

Therefore:

## Good Use
- RP2040/Pi DSP pipelines;
- FFTs;
- spectral analysis;
- anomaly detection.

## Bad Use
- primary deterministic timestamp acquisition.

For sacred timing capture:
- comparator-conditioned analog sensors remain preferable.

---

# Contact Microphone vs Digital MEMS Mic

Current OTIS preference remains:

## Sacred Timing
1. Photogate
2. Comparator-conditioned contact microphone
3. PPS

## Rich Diagnostics
1. Digital microphone DSP
2. IMU
3. Environmental sensing

The digital MEMS mic is potentially very useful —
but primarily on the analysis side.

---

# ATECC608A Secure Element

Integrated crypto/security chip:
- secure key storage;
- SHA/HMAC;
- AES-128;
- RNG;
- ECDSA validation support.  [oai_citation:3‡ABX00053-datasheet.pdf](sediment://file_0000000045b0720a81aead706f5c8ec9)

Potential OTIS uses:
- device identity;
- signed log manifests;
- tamper-evident provenance;
- signed calibration/configuration metadata.

Interesting future concept:
- signed timing runs;
- reproducible instrument provenance;
- firmware hash + config hash + log digest signatures.

Not relevant to timing precision itself.

---

# Strong Recommendation

For MVP:
- avoid scope creep aggressively;
- prioritize deterministic capture;
- keep firmware simple;
- defer DSP/sensor fusion/ML.

The RP2040's real strategic value is:
- deterministic programmable IO;
- architectural separation;
- future extensibility.

Not:
- onboard AI;
- WiFi;
- gimmicky ML features.

---

# Suggested Long-Term Direction

OTIS should likely evolve toward:

## Tier 1 — Instrument Kernel
Deterministic acquisition appliance.

## Tier 2 — Analysis Layer
Host-side interpretation and visualization.

## Tier 3 — Optional Rich Diagnostics
Audio DSP, IMU analysis, ML, cloud features, etc.

The key architectural lesson:
interpretation should remain replaceable without compromising timing integrity.