OTIS GPSDO Design Lessons & Reference Projects

Purpose

This document captures architectural lessons, implementation insights, cautionary notes, and design patterns learned from external GPSDO, timing, oscillator, and precision timekeeping projects.

The goal is not to copy other projects directly.

The goal is to:

* stand on the shoulders of giants,
* avoid rediscovering solved problems,
* identify recurring successful patterns,
* identify recurring failure modes,
* preserve useful ideas for future OTIS stages.

OTIS should remain architecturally coherent and aligned with its own goals:

* disciplined engineering,
* explicit provenance,
* excellent observability,
* timing-first architecture,
* clean separation of responsibilities,
* DRY implementation,
* explicit over clever.

⸻

Core OTIS Principle

The Oscillator Is The Clock

The RP2040 (or future MCU/FPGA/etc.) is NOT the clock.

The OCXO/XCXO/TCXO is the clock.

The digital system is:

* a measurement instrument,
* a phase/frequency estimator,
* a loop filter computer,
* a DAC controller,
* a telemetry/statistics engine.

This distinction is foundational.

Bad mental model:

MCU timer -> software timestamps -> pretend precision

Correct mental model:

OCXO/TCXO reference -> MCU timing domain

All important timestamps should ultimately exist in the oscillator’s disciplined timebase.

⸻

Reference Project: STM32-GPSDO

Project

* Project: STM32-GPSDO
* Author: AndrewBCN
* Repository: https://github.com/AndrewBCN/STM32-GPSDO

⸻

Key Lessons From STM32-GPSDO

1. A Breadboard GPSDO Is Feasible

The project demonstrates that a practical GPSDO can be implemented with:

* inexpensive MCU,
* u-blox timing receiver,
* tunable oscillator,
* DAC/PWM control,
* logging and telemetry,
* breadboard-level construction.

Implication for OTIS:

* an MVP does NOT require custom PCB fabrication,
* experimentation should begin early,
* observability matters more initially than mechanical elegance.

⸻

2. Observability Is Critical

The project heavily emphasizes:

* runtime telemetry,
* logging,
* lock diagnostics,
* calibration feedback,
* oscillator monitoring.

OTIS should treat telemetry as first-class.

Important telemetry categories:

* PPS residuals,
* phase error,
* frequency error,
* DAC/Vctl,
* lock state,
* estimator state,
* oscillator warmup state,
* holdover state,
* temperature,
* Allan deviation metrics,
* estimator confidence,
* GPS quality state.

A GPSDO without extensive telemetry is effectively opaque and difficult to improve.

⸻

3. FLL vs PLL Matters

One of the most important conceptual lessons.

A GPSDO loop fundamentally decides:

* what error is being corrected,
* over what timescale,
* with what aggressiveness.

⸻

Frequency-Locked Loop (FLL)

An FLL disciplines frequency.

Typical measurement:

cycles_between_pps_edges

Example:

Expected:
10,000,000 cycles
Measured:
10,000,003 cycles

Oscillator is fast.

Correction:

* low-pass filter the frequency error,
* slowly adjust DAC/Vctl.

Advantages:

* simple,
* robust,
* excellent for noisy PPS,
* easier to stabilize,
* excellent MVP architecture.

Disadvantages:

* weaker short-term phase coherence,
* less precise phase alignment.

OTIS MVP recommendation:

* start with FLL.

⸻

Phase-Locked Loop (PLL)

A PLL disciplines phase.

The loop attempts to minimize:

actual_phase - predicted_phase

Advantages:

* superior phase coherence,
* stronger time alignment,
* better holdover foundations,
* more sophisticated behavior.

Disadvantages:

* much harder to stabilize,
* easier to overreact to GPS noise,
* requires careful loop filter design,
* more dangerous during MVP stage.

⸻

OTIS Recommended Evolution

Stage 1

Pure FLL.

Measure:

cycles_per_pps_error

Then:

* average,
* filter,
* apply gentle DAC corrections.

Priority:

* stability,
* observability,
* repeatability,
* understandable behavior.

⸻

Stage 2

Hybrid FLL + PLL.

Suggested split:

Timescale	Loop Type
milliseconds-seconds	PLL-like phase trimming
seconds-minutes	FLL frequency steering

This mirrors many successful GPSDO architectures.

Important:
GPS PPS is noisy at short timescales.

An aggressive PLL often performs WORSE than a gentle FLL.

⸻

Stage 3

Advanced discipline and holdover.

Potential future directions:

* oscillator aging models,
* adaptive loop constants,
* Kalman-style estimators,
* holdover prediction,
* confidence-weighted steering,
* Allan deviation-informed filtering,
* GPS trust scoring,
* multi-source disciplining.

⸻

4. Calibration Is Essential

STM32-GPSDO emphasizes calibration and tuning characterization.

OTIS should explicitly characterize:

* DAC -> Vctl transfer,
* Vctl -> frequency response,
* warmup curves,
* thermal sensitivity,
* oscillator linearity,
* hysteresis,
* DAC noise sensitivity.

An explicit characterization stage should exist BEFORE closed-loop discipline.

⸻

5. GPS Receiver Configuration Matters

The STM32-GPSDO project explicitly configures u-blox timing parameters.

Important OTIS implication:

* GPS configuration is part of the instrument.

Not merely:

attach PPS pin and hope

Potential timing-oriented configurations:

* stationary mode,
* quiet mode,
* PPS polarity,
* PPS width,
* dynamic model,
* survey-in,
* timing mode,
* satellite constellation selection,
* elevation masks,
* cable delay compensation.

⸻

6. Avoid Early UI Scope Creep

Many timing projects accumulate:

* displays,
* Bluetooth,
* menus,
* touchscreens,
* environmental dashboards,
* cloud integrations.

These are often useful eventually.

However:

* they increase instability,
* consume engineering attention,
* complicate timing paths,
* reduce determinism.

OTIS MVP priority should remain:

measurement integrity first

Suggested architectural separation:

Layer	Responsibility
Timing authority	oscillator, capture, discipline
Host system	storage, dashboard, network
Analysis	offline reconstruction and statistics

⸻

OTIS MVP Guidance (Current)

Recommended Initial Signal Chain

GPS PPS
    -> RP2040 capture
    -> discipline logic
    -> precision DAC
    -> OCXO/XCXO Vctl
    -> buffered 10 MHz reference
    -> RP2040 timing domain

⸻

Current Preferred Philosophy

Prefer:

* explicit telemetry,
* simple stable loops,
* long averaging windows,
* conservative corrections,
* offline analysis,
* deterministic timing,
* strong provenance.

Avoid:

* premature complexity,
* hidden magic filtering,
* UI-first architecture,
* overly aggressive PLL behavior,
* unnecessary async cleverness,
* opaque adaptive systems before instrumentation exists.

⸻

Candidate Future Topics To Add

Potential future additions to this document:

* Leo Bodnar GPSDO architecture observations,
* HP / Symmetricom / Trimble GPSDO behavior,
* Rubidium disciplining references,
* Allan deviation references,
* phase noise measurement techniques,
* DAC noise and filtering strategies,
* OCXO thermal management,
* oscillator aging compensation,
* survey-in strategies,
* dual-frequency GNSS timing,
* PPS jitter characterization,
* FPGA-assisted timestamping,
* reciprocal counters,
* TIC (time interval counter) architectures,
* disciplined DDS synthesis,
* holdover estimator design,
* oscillator characterization methodologies.

⸻

Important OTIS Reminder

The primary OTIS goal is not merely:

"produce a disciplined 10 MHz output"

The larger goal is:

build a deeply observable precision timing instrument

That distinction should guide all architectural decisions.