# OTIS SW2 — Repository-Context Roadmap

**Lifecycle note (updated 2026-08-21):** this is a historical roadmap through the
sealed CX317 result. The subsequent CX318 Stage 5 programme remains suspended,
incomplete, and unsealed. The platform-stabilization programme in
`../60_EXPERIMENTS/OTIS_PLATFORM_STABILIZATION_PROGRAMME.md` passed its
completion gate. Historical “next” actions below are not current execution
authority. The `CX319_STABILIZED_TIGHT_DEADBAND_PROGRAMME` subsequently passed
lower-side acquisition and completed its range map and mapping-informed
frequency-only Part B programme. CX319 is frozen. CX320 physically applied one
firmware-driven, phase-material combined correction, but the exact response was
below the frozen empirical detection floor and failed its positive-sign
checkpoint. It is a bounded non-pass with no remaining live authority. See
`../60_EXPERIMENTS/CX320_ACTIVE_HYBRID_PROGRAMME/12_STAGE5_ATTEMPT9_RESPONSE_OBSERVABILITY_TERMINAL.md`.
CX321 implemented that design, but its two healthy physical pre-estimates
differed by one count and the frozen exact-equality gate correctly made no DAC
application. It is a sealed bounded non-pass. The selected offline CX322
successor uses a one-count pre-envelope gate and a 25-code identification step
before the unchanged 600-second natural controller. Implementation and
physical authority remain pending; current details are in
`../60_EXPERIMENTS/CX322_PRE_ENVELOPE_ACTIVE_HYBRID_SUCCESSOR/README.md`.

**Status:** revised through the completed and sealed CX317 bounded closed-loop
acquisition programme on 8 August 2026; decision
`dual_core_frequency_control_endurance_passed`

**Scope:** H1 completion through SW2 observe-only, guarded actuation, hybrid discipline, holdover, and timing-platform scaffolding

**Current evidence caveat:** the programme has now demonstrated bounded
single-core acquisition, dual-core transaction-safe active control and a
sealed 24-hour endurance pass on the exact tested rig. Stage 7B moved once from
`0xA815` to `0xA828`, then remained inside the frozen frequency deadband for
90,000 s while all service and transport gates passed. This establishes the
bounded frequency-control layer, not calibrated absolute accuracy, UTC
traceability, phase lock, holdover, timing-grade receiver performance or
physical waveform margin. Historical `run_019`/`run_020` remain contextual
plant evidence rather than CX317 specifications.

---


## Diagnostics-first architecture commitment

SW2 treats four workstreams as co-equal and explicitly separated:

1. **Measurement** preserves reference, count, event, actuator, environmental,
   and low-level health observations.
2. **Metrology** derives frequency, phase, drift, stability, plant response, and
   uncertainty with provenance.
3. **Diagnostics** evaluates source quality, path integrity, estimator
   qualification, model applicability, subsystem health, and control eligibility
   using stable reason codes and evidence references.
4. **Control** consumes metrology and diagnostic gates under a versioned policy;
   it never hides diagnostic inference inside the DAC driver.

This is not an additional dashboard milestone. It changes acceptance criteria for
all SW2 packages:

- raw evidence is retained even when invalid for control;
- every Boolean eligibility state includes reasons;
- important diagnostic transitions are explicit and replayable;
- live and host replay diagnostics should converge on common fixtures;
- every requested/applied DAC change traces through estimate, diagnostic gate,
  policy, request, limit handling, and acknowledgement;
- reference, count-path, estimator, plant-model, actuator, and service-plane
  health are independently visible;
- control responds conservatively to diagnosed quality without diagnostics
  directly actuating hardware.

The normative architecture is defined in:

- `docs/10_REFERENCE_ARCHITECTURE/MEASUREMENT_METROLOGY_DIAGNOSTICS_CONTROL.md`;
- `docs/10_REFERENCE_ARCHITECTURE/DIAGNOSTICS_AND_CONFIDENCE_ARCHITECTURE.md`;
- `docs/30_ANALYSIS/PPS_REFERENCE_CHARACTERIZATION.md`.


## 1. Executive decision

The earlier generic SW2 roadmap had the right long-term shape, but it treated OTIS too much like a greenfield firmware project. The repository already contains much of the necessary scaffolding:

- explicit timing and reference terminology;
- canonical, versioned telemetry contracts;
- raw/derived separation;
- RP2040 capture backends;
- FC0 count observations and control-eligibility gates;
- DAC support, clamping and deterministic manual sweeps;
- run manifests, validation, reporting and session-aware analysis;
- H1 characterisation tooling;
- an existing SW2-readiness document and staged Codex prompt pack.

SW2 should therefore **extend the existing observation-and-replay architecture**, not introduce a parallel set of generic `Observation`, `Estimator`, `Controller`, and `Actuator` abstractions simply because they look tidy.

The recommended path is now:

1. preserve the qualified PPS-gated measurement backend and canonical evidence contracts — **complete**;
2. preserve deterministic host/firmware estimator and controller replay — **complete**;
3. preserve bounded single-core bidirectional acquisition evidence — **complete**;
4. preserve the Core 0 service / Core 1 timing ownership and fail-static transport contract — **complete**;
5. preserve the sealed 24-hour bounded dual-core frequency-control endurance result — **complete**;
6. define a replayable phase estimator and bounded hybrid phase/frequency preview with zero actuation authority — **complete**;
7. qualify that preview against recorded evidence and explicit phase/reference-loss diagnostics — **complete as zero-authority evidence**;
8. qualify hybrid phase steering only under a separate programme after its estimator, limits and abort behavior are sealed — **CX320 and CX321 bounded non-passes; CX322 offline successor selected with a one-count pre-envelope gate and 25-code plant-sign transaction before unchanged natural hybrid requests**;
9. add reference-loss holdover and controlled recovery;
10. prove that the timing engine can accept another reference adapter without changing capture semantics, control logic or the DAC driver.

### 2026-08-08 bounded frequency-control milestone

The CX317 bounded closed-loop acquisition programme passed all eight stages.
The final decision is `dual_core_frequency_control_endurance_passed`; the
sealed report is
`../60_EXPERIMENTS/CX317_BOUNDED_CLOSED_LOOP_ACQUISITION_FINAL_REPORT.md`.
The terminal hardware state is static `0xA828`. Final verification recorded
790 passed tests, two expected skips, 22/22 supported firmware profiles and
7/7 intended guards. The one selected next programme is phase-estimator
definition and a non-actionable bounded hybrid phase/frequency preview.

### Historical 2026-08-03 observe-only milestone

The CX317 PPS-gated programme completed Stages 1 through 7 with four valid
evidence seals and a 16/16 final-readiness gate pass. The final integrated
verification recorded 594 passed tests, 2 expected Run 020 skips, 15/15
positive firmware profiles, 4/4 guarded negative profiles, three passing wire
fixtures and passing synthetic validate/report checks. The resulting decision
is deliberately capped at `ready_for_more_observe_only_testing`; no feedback-
derived DAC command was issued and no actuation authority was created.

The architectural objective remains larger than a GPSDO:

> OTIS should be a provenance-preserving timing instrument whose discipline engine is one consumer of canonical timing observations and whose outputs can support other applications, including a ClockMesh/RSN-style node, time-server integration, oscillator characterisation, and reference comparison.

---

## 2. What the current repository changes about the plan

### 2.1 Do not create a second telemetry model

The repository already defines stable record families such as:

- `EVT` — event observations;
- `REF` — reference observations;
- `CNT` — count observations;
- `STS` — health/status;
- `DAC` / `dac_steps.csv` — actuator and sweep evidence;
- environmental records;
- capture flags and explicit clock domains.

SW2 should add **derived discipline records** and state fields while preserving these raw contracts. It should not replace `REF` and `CNT` with a new all-purpose firmware struct whose semantics are less explicit.

A useful internal representation is still appropriate, but it should be an adapter over the canonical contracts and must preserve:

- source identity;
- native timestamp/count domain;
- sequence and continuity;
- flags;
- quality/eligibility;
- the raw record from which a derived estimate was produced.

### 2.2 Do not duplicate the existing DAC layer

`otis_dac_ad5693r.*` already provides the natural actuator boundary. Extend it rather than introducing a competing `OscillatorActuator` hierarchy now.

The missing distinction is not “driver versus actuator”; it is:

- **hardware-valid range**;
- **manual characterisation range**;
- **automatic-control range**;
- **maximum automatic update**;
- **last confirmed applied code**.

These must be represented separately.

The checked-in `run_020` characterization clamp is `0x6000..0xFC00`.
`run_019` shows that the historical `0x7000..0x9000` range does not reach the
10 MHz crossing and is therefore not a defensible control envelope. The
Phase 3 model records:

- local model applicability `0xA800..0xB400`;
- nominal crossing code `0xA950`;
- a conservative automatic-control candidate `0xA800..0xAB00`;
- maximum manual/open-loop preview step `0x0300`.

The automatic range remains disabled and is not an actuation authorisation.
SW2 must continue to represent hardware, characterization, and automatic-control
limits separately.

### 2.3 The host is already a first-class part of the instrument

Replay and analysis should not be deferred to a late SW2 phase. The host tooling already validates and characterises runs; it should become the first execution environment for the estimator and controller policy.

The safest development order is:

```text
recorded REF/CNT/DAC/STS data
            |
            v
host discipline replay
            |
            v
firmware observe-only parity
            |
            v
guarded firmware actuation
```

This lets OTIS compare policies against the same evidence and avoids tuning a live controller by intuition.

### 2.4 H1 FC0 characterisation is not automatically the SW2 control backend

The current 300-second long-gate FC0 path is useful for:

- identifying gross count faults;
- measuring long-term frequency response;
- estimating DAC slope;
- studying settling, warmup and thermal behaviour.

It is probably too slow and too disconnected from individual PPS intervals to be the sole live discipline observation.

The repository implements the **PPS-gated ratio backend** as the preferred SW2
live frequency-observation path. Its
`pio_wait_cumulative_snapshot_dma_v1` architecture was accepted for
observe-only use on 2026-08-01 after clean, fault, real-GPS, load, extended, and
sealed overnight testing. It produces canonical `CNT` observations whose gate
is defined by accepted PPS edges while preserving PPS validity and
oscillator-count validity separately. The accepted width-only fault limitation
and unavailable physical phase/duty sweep remain explicit; neither authorizes
actuation.

The subsequent exact-ELF and source audit concludes that this measurement path
is already at the practical useful latency/jitter limit of the selected
integer-edge RP2040 architecture. The D14 IRQ is not a cycle-minimal timestamp
path, but it is diagnostic and cannot move the raw count aperture. Future
firmware must preserve the ownership and proof invariants in
`../50_SOFTWARE/PPS_CAPTURE_LATENCY_JITTER_AUDIT_20260801.md`; routine ISR,
multicore, DMA, USB, or telemetry refactoring must not be presented as a raw
count-resolution improvement.

The 300-second H1 path remains valuable as an independent metrology and validation channel.

### 2.5 Preserve a hardware-timing-plane/service-plane architecture

The PIO/DMA capture fabric is the timing plane below both CPU cores. SW2 may use
the RP2040's two cores as an additional service/estimation boundary, but core
placement must not redefine the already autonomous count aperture:

```text
As per Earle Philhower's advices that  Core 0 handles USB and should generally perform Wi-Fi operations
Core 0 — service, I/O and application plane
Core 1 — protected snapshot-consumption, estimation and discipline plane
```

This does not mean that SW2 should begin with a disruptive multicore rewrite before the H1 evidence gates are closed. It does mean that new SW2 interfaces, queues and ownership rules must be designed so the intended partition is clear and can be enforced incrementally.

#### Core 1 responsibilities

Core 1 should own work whose delay, ordering or jitter can affect snapshot
consumption, estimation or discipline integrity. PIO retains physical capture
ownership:

- timely consumption of immutable PPS/oscillator snapshots;
- monotonic timing and sequence ownership;
- construction and validation of canonical raw timing observations;
- reference-age and continuity tracking;
- phase, frequency, drift and uncertainty estimation;
- operating-state transitions;
- controller evaluation and actuator-request generation;
- timing-critical fault detection.

Core 1 must not depend on timely servicing by Core 0 in order to continue capturing and estimating correctly.

#### Core 0 responsibilities

Core 0 should own work that may be delayed without corrupting timing:

- USB serial transport and telemetry formatting;
- command parsing and configuration servicing;
- environmental sensor polling;
- GNSS message parsing outside the PPS capture path;
- status presentation and diagnostics;
- host communications;
- future ClockMesh/RSN, NTP/chrony and PTP adapters;
- other application-layer services;
- provisionally, physical DAC I²C transactions if their latency or blocking behaviour makes them unsuitable for Core 1.

#### Actuator boundary

The timing plane owns the control decision. The actuator layer owns whether and when a requested code is safely applied.

If DAC I²C writes execute on Core 1, the contract must distinguish:

- requested DAC code;
- accepted DAC code;
- applied DAC code;
- request and application sequence numbers;
- request and application timestamps;
- clamping or slew limiting;
- stale-request rejection;
- I²C success or failure.

The estimator and controller must use the confirmed applied code rather than assume that a request was applied.

#### Cross-core communication

Use bounded, fixed-size message channels and immutable records rather than shared mutable controller state.

```text
Core 1 -> Core 0:
    observations for export
    estimator snapshots
    control decisions
    events and faults
    actuator requests

Core 0 -> Core 1:
    validated mode/configuration changes
    actuator acknowledgements
    qualified external/network observations
    source-health updates
```

Timing observations, actuator acknowledgements and critical state changes must not be silently lost. Routine status and duplicate telemetry snapshots may be dropped under load, but every drop must be counted and reported.

#### Isolation requirement

A stalled or overloaded service plane must not corrupt the timing plane. SW2
testing should deliberately block USB output, delay non-critical I2C activity,
overload telemetry, and temporarily stall Core 0 while verifying that the
PIO/DMA fabric and protected Core 1 path continue to:

- capture expected timing events;
- maintain monotonic sequencing;
- update the estimator and state machine;
- avoid spurious control actions;
- account for lost service-plane telemetry;
- enter a defined fault or degraded state if a non-droppable cross-core channel cannot be serviced.

Separately stalling Core 1 should demonstrate bounded PIO/DMA buffering followed
by explicit fail-closed backlog/overflow behavior; Core 0 must not take over or
fabricate the timing observation. The hardware/core boundary is therefore part
of the SW2 platform architecture, even though its implementation should be
staged so that it does not obscure the completed H1 evidence boundary or the
next observe-only work.

---

## 3. Interpretation of `run_014`, `run_016`, `run_017`, and `run_019`

`run_014` is no longer unresolved. It should be treated as **Outcome B: count
path clean, plant response useful, but not yet an actuation-authoritative model**.

The pre-fix evidence showed real zero-count windows. The hardware isolation path
found that the SN74LVC1G17 breakout had pin 2, the A input, shorted to pin 5,
VCC. After cleaning and resoldering the G17, the bench confirmed direct
ECS-TXO-to-D8 counting, ECS-TXO-through-G17 counting, and CX317-through-G17
counting. The post-fix clean `run_014` completed with:

- 284 300 s count windows;
- zero zero-count rows;
- all `CNT` rows flagged `16`;
- no host dropped records, capture error flags, parser errors, or reconnects;
- 18 completed DAC sweep passes and 90 dwell starts/completes;
- `fc0_valid_for_control: true` after startup qualification;
- positive local centre-bracketed slope evidence, with median slope about
  4.30 Hz/V;
- warmup and thermal evidence over a 24-hour-class capture.

The remaining caveat is not the repaired count path. It is the
PPS/reference-cadence evidence: the raw REF stream contains 2719 short REF/PPS
intervals, mostly concentrated early in the run but not startup-only. Host
characterization ignored out-of-band PPS intervals for tick-rate calibration,
and `run_014/manifest.json` gates the matching anomaly set as diagnostic-only
and not control-eligible. Current telemetry cannot assign root cause to the
GPS/PPS source versus GPIO/capture/IRQ/FIFO/DMA/firmware handling.

`run_016` then retried H1-B with the corrected firmware defaults and the
pre-sweep PPS/reference qualification segment:

- DAC clamps were `0x7000..0x9000`;
- active DAC dwell was 900 s;
- the local sweep exercised `0x7c00`, `0x7e00`, `0x8000`, `0x8200`, and
  `0x8400`;
- 153 300 s count windows were captured with no zero-count rows;
- all expected DAC dwell starts and dwell completes were present;
- capture drops and capture error flags remained zero;
- `fc0_valid_for_control` and `reference_valid_for_control` were true;
- the REF stream contained 45,917 valid PPS intervals and no PPS anomalies.

The reference result is good: the `run_014` PPS anomaly burst did not recur in
the H1-B retry. The plant result is not good enough for control authority:
repeated center points span about 11.6 Hz, while the median target deltas at the
smaller local steps are only about 0.1 Hz to 0.3 Hz and the center-bracketed
Hz/V estimates are mixed sign.

Consequence at that point: preserve the pre-G17-fix capture as negative
hardware evidence, carry PPS/reference validity gates forward as permanent
control safety policy, and **do not jump directly to PLL/PI or even guarded
I-only actuation**. This led to the higher-SNR H1-B work now completed by
`run_019` and `run_020`.

`run_016` was the first measurement-confidence update after adding the local PPS
interpolator. The regenerated H1 report uses the host-side local PPS
interpolator for existing count gates:

- 153 count windows;
- 152 `LOCAL_PPS_INTERPOLATED` estimates;
- one startup-edge fallback to `RUN_WIDE_TICK_RATE`;
- no PPS anomalies in the analysed REF stream;
- `fc0_valid_for_control: true`;
- retained legacy-vs-local comparison with median difference 0.007 Hz,
  standard deviation 3.13 Hz, and span 14.48 Hz.

This confirms that the former run-wide RP2040 tick-rate conversion could move
sub-hertz conclusions by much more than the DAC/CX317 response being measured.
For H1 plant-authority conclusions, use locally PPS-calibrated estimates when
valid support exists and retain the run-wide estimate only as a labelled
diagnostic comparison.

The corrected `run_016` evidence made centre-bracketed `0x0800` and `0x1000`
steps useful for the next conservative plant-model fit. `run_017` then provided
the following measurement-confidence update:

- 242 300 s count windows;
- 241 `LOCAL_PPS_INTERPOLATED` estimates;
- one startup-edge fallback to `RUN_WIDE_TICK_RATE`;
- no host-classified PPS anomalies after unwrapping 16 RP2040 timer rollovers;
- no reconnects or reboot/header markers;
- `fc0_valid_for_control: true`;
- D10 PPS witness agreement with D14: final raw counts both 72970, with no D10
  short, overflow, or burst rows;
- observed CX317 output from about 9.999997327 MHz at DAC `0x7000` to about
  9.999998711 MHz at DAC `0x9000`;
- centre-bracketed `0x0800`/`0x1000` slopes about 4.15..4.67 Hz/V, positive and
  consistent with the CX317 datasheet-derived 10 MHz expectation of about
  3.0..6.1 Hz/V over 0.0 V..3.3 V.

The remaining `run_017` caveat is diagnostic, not a host-metrology failure: D14
`rejected_long_count` ended at 16, matching the 16 raw timestamp rollovers. Treat
that as a rollover-sensitive firmware diagnostic artifact unless the firmware
counter is changed to compute intervals on unwrapped timestamps. Environmental
regression remains diagnostic, not explanatory authority, because nearby
air-temperature terms are confounded with elapsed time and the CX317 internal
oven state is not directly measured.

`run_019` supersedes `run_017` as the broad-response reference:

- one continuous 12.89 h session;
- 155 of 155 non-zero count windows and 46,394 of 46,394 PPS intervals valid;
- no parser, reconnect, capture-drop, overflow, or saturation failures;
- wide-fit gain `0.000169064 Hz/code`, `R²=0.999920`;
- four drift-cancelled estimates equivalent to 4.38..4.50 Hz/V;
- inferred 10 MHz crossing near `0xAE00`, approximately 1.692 V;
- final 8.17 h `0x8000` hold with 0.043665 Hz standard deviation.

Its actual Arduino IDE configuration was `0x0100..0xFF00`, centre `0x8000`,
900 s dwell, and `0x0200` tiny steps, rather than the planned crossing-focused
profile. Broad linearity and crossing location are supported; local crossing
gain, hysteresis, and resolved settling are not. The absence of `COMPLETE`, an
evidence manifest, pre-run Git snapshots, and operator DMM observations also
keeps the run analysis-useful rather than sealed.

`run_020` closes the focused crossing-region evidence gap for an observe-only
plant model:

- the preflight verified the intended Arduino IDE firmware configuration and
  exact profile before the sweep began;
- 77 of 77 count windows and 23,250 of 23,250 PPS intervals were valid;
- there were no capture, parser, reconnect, drop, saturation, or overflow
  failures;
- `0xA800` was below 10 MHz by `0.036767 Hz`, while `0xAB00` was above by
  `0.059011 Hz`;
- direct interpolation gives crossing code `0xA927`; time-aware regressions
  give `0xA94C..0xA964`; the model uses rounded nominal code `0xA950`;
- the conservative within-run crossing band is `0xA840..0xAA00`;
- four drift-cancelled local slopes are
  `0.000155907..0.000187610 Hz/code`, with mean
  `0.000167304 Hz/code`;
- seven uncontaminated transitions had a maximum resolved `t95` of about
  `653 s`, supporting the configured `900 s` exclusion;
- the final count sequence straddled the immediate `0x8000` restore and is
  preserved as raw evidence but excluded from the final-centre and settling
  calculations.

The result supports model applicability over `0xA800..0xB400` and a disabled
automatic-envelope candidate of `0xA800..0xAB00`. Repeated centre observations
still contain drift/thermal structure, endpoint bidirectional hysteresis was not
measured, and the approximately `1.648 V` crossing voltage is inferred from the
separate `run_018` DMM calibration rather than measured directly in `run_020`.
Those limitations are explicit in the model and prevent an active-control
claim.

---

## 4. Target SW2 architecture in OTIS terms

The existing repository language should remain authoritative.

```text
REFERENCE SOURCES / CAPTURE SOURCES
GNSS PPS | external PPS | future network/reference adapter
                 |
                 v
TIMING FABRIC AND CANONICAL RAW OBSERVATIONS
REF | CNT | EVT | source-specific status | explicit domains
                 |
                 v
CONTROL-ELIGIBILITY AND QUALITY GATES
freshness | continuity | flags | startup inhibit | clean windows
                 |
                 v
DISCIPLINE ESTIMATOR
phase state | frequency state | drift state | uncertainty | provenance
                 |
                 v
CONTROL POLICY / OPERATING STATE
observe | acquire | settle | locked | holdover | recover | fault
                 |
                 v
CONTROL DECISION RECORD
error terms | proposed code | limits | reasons | model version
                 |
                 v
AD5693R ACTUATION GATE
preview-only or authorised apply | clamp | slew | I2C result
                 |
                 v
CX317 / OUTPUT REFERENCE
```

The host consumes every level and must be able to reproduce all derived decisions from preserved raw observations plus versioned configuration.

### 4.1 Preserve three distinct concepts

SW2 must not conflate:

1. **reference authority** — GNSS, external PPS, remote timing source, etc.;
2. **measurement/capture domain** — RP2040 timer, PPS-defined gate, FC0 count domain, future hardware timestamp domain;
3. **steered oscillator/output domain** — the CX317 10 MHz signal and any time scale derived from it.

A future RSN/ClockMesh adapter may provide observations or peer-quality information. It does not automatically become “truth,” and it should not silently redefine the capture clock or oscillator phase.

### 4.2 Frequency and time service are separate products

The first SW2 product is a disciplined 10 MHz frequency output. A phase-aligned pulse or full time-of-day service is a later product.

The engine should therefore maintain separate concepts for:

- frequency syntonisation;
- phase alignment;
- epoch/time-of-day knowledge;
- leap/discontinuity handling;
- output generation.

This separation is important for future NTP, PTP, chrony, RSN or time-server applications. A good frequency estimate is not by itself a trustworthy UTC time scale.

---

## 5. PLL, FLL and the recommended “both-ish” evolution

The current repository correctly recommends an initial guarded I-only frequency controller. That should remain the first actuation target.

### 5.1 Do not implement independent loops that fight each other

Avoid a design where an FLL writes one correction and a PLL writes another correction without a shared state and explicit authority.

Instead, maintain an estimator with at least:

- phase residual;
- frequency offset;
- optional frequency drift;
- uncertainty and observation age.

Then use one state-aware control policy whose weighting changes by operating state.

### 5.2 Acquisition: FLL-dominant

During acquisition:

- trust accumulated count/frequency evidence more than instantaneous PPS phase;
- make slow, bounded corrections;
- require persistent valid observations;
- use the known plant slope and sign;
- keep phase correction disabled or tightly bounded.

The first live implementation should be a very slow integral frequency controller, because it is simple, auditable and naturally compatible with the current H1 evidence programme.

### 5.3 Settling: introduce phase information gradually

Once frequency error is small and stable:

- retain the slow frequency correction;
- introduce a bounded phase term;
- reduce gains as confidence increases;
- prevent a single PPS outlier from causing a DAC step;
- log the separate frequency and phase contributions.

### 5.4 Locked: hybrid estimator, one coherent policy

In lock, phase and frequency should both be estimated continuously. The controller may be described as a low-bandwidth PLL, a PI loop informed by frequency estimates, or a hybrid FLL/PLL. The name matters less than these properties:

- one coherent control output;
- explicit loop bandwidth and update cadence;
- clear phase and frequency terms;
- no hidden adaptive behaviour;
- anti-windup;
- quality-weighted or quality-gated observations;
- reproducibility in host replay.

### 5.5 Holdover is neither PLL nor FLL

During holdover there is no trustworthy live reference error to close against. The engine predicts or freezes oscillator control using the last trustworthy model.

Initial holdover should be fail-static: retain the last confirmed safe DAC code. Later versions may add drift and temperature models only after dedicated data supports them.

### 5.6 Do not start with PID or Kalman control

- A derivative term is unlikely to help against noisy, quantised, low-rate timing observations and can amplify measurement noise.
- A Kalman-style estimator may eventually be useful, but only after OTIS has a characterised oscillator noise model and can demonstrate improvement against simpler estimators using replay.

The repository’s “explicit over clever” principle should govern this decision.

---

## 6. Revised staged roadmap

## Stage H1-A — Resolve the physical and measurement path

**Purpose:** establish that the CX317 can be observed reliably under the revised power and conditioning topology.

### Status

Passed for the count-observation path in the repaired topology. The G17 solder
fault has been identified, repaired, and separated from the clean plant
evidence.

Remaining cleanup:

1. Backfill any manifest/version fields that are still blank where the value can
   be recovered from the bench or repository state.
2. Keep the pre-G17-fix capture as a distinct session/evidence set; do not merge
   it into the post-fix plant fit.
3. Keep PPS/reference anomaly fault telemetry on the SW2 safety list, but do
   not let it displace the next plant-focused H1-B run; `run_016` is clean
   reference-path evidence for the current topology.

### Exit gate

H1-A passes only when the count-observation path has a documented period of control-eligible operation with no unexplained post-inhibit invalid windows.

`run_014` satisfies this gate for count observations, and `run_017` adds clean
D10 PPS witness evidence for the later confirmation sweep. Passing H1-A does not
establish an actuation-ready plant model or a reference-validity model.

---

## Stage H1-B — Produce a locally applicable observe-only plant model

**Purpose:** replace directional or fault-contaminated slope evidence with a
versioned model suitable for calculating deterministic, bounded previews. Live
actuation requires a later, separate gate.

### Status

Passed for the Phase 3 observe-only handoff using `run_020`, with the Phase 4
estimator-contract correction applied. The current model is
`profiles/plant_models/cx317_h1_bench_v3.json` (model version 4).

### Required experiments

- repeated centre-to-low-to-centre-to-high-to-centre sweeps around `0xAE00`;
  completed by `run_020`;
- at least two step sizes, with any future smaller step sized above the measured
  noise floor rather than assumed from DAC resolution alone;
- repeated centre returns to bound return-path repeatability; endpoint
  bidirectional hysteresis remains a later guarded-actuation prerequisite;
- sufficient dwell to estimate settling at each step;
- fixed and documented power/conditioning topology;
- per-dwell voltage measurements where practical, or a separately calibrated DAC-voltage model with stated uncertainty;
- temperature and warmup tracking;
- a static-centre run to estimate the short-term measurement noise floor using the same observation method intended for SW2.

### Required model artefact

The versioned, machine-readable plant-model file is:

```text
profiles/plant_models/cx317_h1_bench_v3.json
```

It should include:

- oscillator identity;
- hardware topology identifier;
- DAC identity/reference/gain;
- nominal code;
- automatic-control minimum and maximum;
- local `Hz/code` and `ppm/code` with sign;
- uncertainty and valid neighbourhood;
- measured settling statistics;
- temperature range;
- source run IDs and commits;
- explicit invalidation conditions.

Do not hide this model as constants scattered across firmware files.

### Exit gate

- local slope sign is repeatable;
- slope uncertainty is small enough to choose a conservative update;
- settling and measurement noise support an update cadence;
- automatic-control range is explicitly narrower than or equal to the bench-tested range;
- the model is traceable to completed runs.

`run_016` did not pass this exit gate. `run_020` now passes it for observe-only
use: it supplies a traceable positive local gain, a conservative crossing
estimate and band, repeated-centre dispersion, and a settling bound. The
model's explicit applicability and unresolved conditions must be enforced;
this gate does not authorise DAC actuation.

---

## Stage SW2-0 — Freeze contracts and introduce discipline semantics

**Purpose:** define SW2 additions without changing actuation.

### Repository work

1. Add or promote a draft first-class diagnostic contract with stable reason
   codes, evidence references, persistence, diagnostic confidence, and explicit
   control consequence. The current additive draft is
   `data_contracts/diagnostics_v1.csv.md`.
2. Add a document defining:
   - discipline observation eligibility;
   - estimator outputs;
   - control decision records;
   - state transitions;
   - plant-model versioning;
   - raw-to-derived provenance.
3. Add backend-generic names alongside current FC0 compatibility names, such as:
   - `count_observed_valid`;
   - `count_valid_for_control`;
   - `count_fault`;
   - `reference_valid_for_control`.
4. Superseded by the platform-stabilization contract reset: current builds use
   backend-neutral `count_path` status and do not retain compatibility aliases.
5. Define unavailable values explicitly; unknown gain must never be encoded as zero.

### Deliverable

A normative data contract for a derived discipline-decision record, tentatively `CTL v1`, containing at least:

- estimator timestamp and domain;
- source observation sequence/range;
- reference source ID;
- control state and transition reason;
- phase estimate and uncertainty;
- frequency estimate and uncertainty;
- drift estimate and uncertainty, if available;
- plant model ID/version;
- proposed code and delta;
- applied code and delta;
- clamp/slew/eligibility/fault flags;
- policy version and configuration hash;
- `preview_only` / `actuation_authorised` status.

### Exit gate

Host parser, validator and fixtures understand the new diagnostic and future
discipline records while all existing tests and contracts remain valid.
Reference/count-path and actuator diagnostic fixtures must demonstrate preserved
raw evidence, control inhibition, clearing or latching behavior, and
deterministic replay without hardware actuation.

---

## Stage SW2-1 — Host-side estimator and policy replay

**Purpose:** make the discipline logic testable before placing it in firmware.

### Status

Passed for host-only Phase 4 replay. The normative `EST v2`, `RFO v1`, `DIAG
v1`, and observe-only `CTL v1` contracts, strict host validation, deterministic canonical-record
adapter, boundary-interpolated frequency estimator, roadmap-aligned preview
state machine, model-v4 method-contract applicability policy, bounded correction preview, replay CLI, and
fault/repeatability fixtures are implemented. Derived products are confined to
the supplied run's `derived/phase4_replay_v3/` directory and source evidence is
content-hashed before and after.

This status includes native host/firmware estimator parity. Physical
gate-aperture and live PPS-gated measurement qualification were subsequently
accepted by the separate Phase 5 campaign on 2026-08-01. Stage SW2-1 itself
still makes no active-actuation claim: every Phase 4 CTL remains preview-only,
unauthorized, and non-actionable.

### Required components

- adapter from canonical `REF`, `CNT`, `STS` and DAC records into discipline inputs;
- deterministic estimator;
- control-state machine;
- preview-only controller policy;
- replay command that writes derived `CTL` records without modifying raw files;
- plots/reports comparing actual DAC steps, model predictions and policy previews.

### Initial estimator

Keep it simple and explicit:

- accepted PPS interval/phase residual;
- frequency estimate from valid count observations;
- fast and slow frequency averages;
- robust outlier handling;
- reference and count age;
- optional linear drift estimate disabled by default;
- confidence derived from sample count, dispersion, continuity and age.

### Required simulation/replay cases

- free-running constant offset;
- known DAC step using H1 evidence;
- PPS outlier;
- missing PPS;
- invalid/zero count window;
- startup inhibit;
- sustained measurement fault;
- plant model unavailable;
- proposed correction beyond control clamp;
- reference loss and return.

### Exit gate

The host can reproduce every decision deterministically from raw records, the plant model and configuration.

---

## Stage SW2-2 — Firmware observe-only discipline skeleton

**Purpose:** run the same state and policy logic live, with all actuation prohibited.

### Status

Implementation and deterministic parity are complete; the live exit gate is
still open. The opt-in firmware build now runs the bounded mean estimator,
eligibility gates, roadmap state subset, model-v3 applicability checks, and
correction preview while exposing no DAC-write callback. Normative live `EST
v2`/`RFO v1`/`DIAG v1`/`CTL v1` rows pass strict host validation, and the
exact C++ engine
matches host replay across startup, reference loss/return, count fault, model
mismatch/out-of-range, and clamp fixtures.

The checked-in default keeps the preview disabled. All preview authorization
and actionability fields remain false. The default, preview, PPS-gated,
alternative sparse-capture, FC0, and divided-signal GPIO count builds compile.

The target board has since completed Phase 5 PPS-gated capture qualification,
including service-plane load and long-duration runs. Those runs used the
qualification build rather than the live Phase 4 preview build. Stage SW2-2
therefore still needs one integrated long live preview/parity run before its
exit gate passes; no actuation gate is affected.

### Operating states

Use a small state set aligned with current readiness language:

```text
BOOT
SAFE_OBSERVE
WARMUP_INHIBIT
QUALIFYING
ACQUIRE_PREVIEW
SETTLE_PREVIEW
LOCKED_PREVIEW
HOLDOVER_PREVIEW
RECOVER_PREVIEW
MANUAL_OPEN_LOOP
FAULT
```

The `*_PREVIEW` suffix should remain until actuation for that state is explicitly authorised.

### Requirements

- estimator consumes only control-eligible observations;
- raw records continue regardless of control eligibility;
- controller produces a preview code but cannot call the DAC write path;
- manual sweep and nominal restore remain distinct modes;
- all state transitions and reasons are emitted;
- the host replay and firmware agree within defined numeric tolerances on the same fixture.

### Exit gate

A long live run demonstrates that observe-only SW2 remains stable, does not disturb capture, and produces explainable preview decisions.

---

## Stage SW2-3 — Validate PPS-gated ratio measurement

**Purpose:** establish the preferred live frequency observation for the discipline loop.

### Status

**Complete and accepted for observe-only measurement on 2026-08-01.** The
single-PIO-state-machine backend passed exact raw `SNP`/`CNT` reconstruction,
real-GPS continuity, deliberate service load, timer rollovers, extended and
sealed overnight operation. The final overnight comparison contains 16,798
eligible windows across 14 quiet/load pairs with zero capture, PIO, DMA, ring,
parser, or session-continuity fault. The fault campaign scored 30/31 strict;
the sole 10 microsecond width-only miss is an accepted rising-edge-only
observability limitation. Physical phase/duty margin is not tested because the
ECS fixture cannot control it and is recorded as non-blocking, not passed.

This closes the measurement-backend gate only. Existing qualification evidence
retains `backend_qualified=false`, and all actuation authorization remains
false pending a separate operational-profile and guarded-control decision.

### Requirements

- define the count gate from accepted PPS edges;
- preserve raw PPS and count validity separately;
- emit canonical `CNT` observations with explicit source and gate domains;
- detect missing, duplicate, implausible or discontinuous PPS gates;
- detect zero, saturated, stale or otherwise invalid oscillator counts;
- compare against the independent long-gate FC0 path where possible;
- quantify resolution, bias, jitter and fault behaviour;
- demonstrate that USB/telemetry activity does not alter the measurement.

### Important rule

A PPS-gated count is eligible for control only when both sides are eligible:

```text
reference valid
AND
oscillator count valid
AND
startup/warmup qualification passed
AND
no relevant capture fault
```

### Exit gate

**Passed with the documented limitations.** The backend has clean bench
evidence and host validation. It does not itself authorise DAC movement.

The post-qualification latency/jitter audit also passed as an architecture
review: no CPU/ISR path lies inside the official aperture, the exact v4 ELF
matches the proved PIO mechanism, and no capture code change is justified.
This conclusion is now a regression constraint for every later SW2 stage.

---

## Stage SW2-4 — First guarded frequency actuation

**Purpose:** perform the smallest credible closed-loop experiment, not declare a finished GPSDO.

### Controller

- very slow I-only frequency control;
- no active phase term;
- correction based on averaged, control-eligible frequency error;
- plant-model conversion from error to a small code preview;
- strict per-update and cumulative bounds;
- anti-windup when inhibited, clamped, slew-limited or faulted.

### Safety requirements

- explicit operator-selected actuation build/profile;
- automatic-control candidate `0xA800..0xAB00`, which contains the model
  crossing band and remains disabled until this stage is explicitly
  authorised;
- manual characterisation clamp represented separately;
- update interval derived from measured settling, never merely copied from a roadmap placeholder;
- maximum code delta derived from slope uncertainty and noise floor;
- several consecutive valid observations before every update;
- fail-static on lost eligibility;
- last confirmed applied code tracked separately from requested code;
- bounded I²C recovery with no uncontrolled repeated writes;
- immediate transition to `FAULT` or fail-static on post-qualification invalid count windows;
- an operator abort command that does not depend on the estimator being healthy.

### Experiment sequence

1. run observe-only and preview simultaneously;
2. compare preview against expected response;
3. arm actuation explicitly;
4. permit one bounded correction;
5. return to observation and measure response;
6. only later permit repeated corrections;
7. restore nominal/manual-safe code at experiment end under operator control.

### Exit gate

Repeated tests converge frequency in the expected direction without instability, limit violations, unexplained count faults or capture degradation.

---

## Stage SW2-5 — Frequency acquisition state machine

**Purpose:** turn the guarded experiment into a reproducible FLL-dominant acquisition mode.

### Add

- acquisition entry/exit hysteresis;
- dwell-time requirements;
- confidence thresholds;
- integrator state reset rules;
- recovery from saturation;
- distinction between no reference, bad reference and bad oscillator observation;
- configuration profiles tied to a plant-model version.

### Exit gate

Cold and warm starts repeatedly reach a defined frequency-acquired state, and replay explains every correction.

---

## Stage SW2-6 — Phase estimator and hybrid lock

**Purpose:** add phase coherence without sacrificing frequency stability.

### Preconditions

- frequency acquisition is boring and repeatable;
- PPS residual behaviour is characterised;
- cable/receiver/logic delays relevant to the phase definition are documented;
- the project has stated what phase is being aligned: oscillator-derived epoch, generated PPS, or another explicit signal.

### Add

- phase residual contract with an explicit sign convention;
- phase uncertainty and outlier handling;
- bounded phase contribution;
- `SETTLING` and `LOCKED` entry/exit hysteresis;
- bumpless transfer from acquisition to hybrid lock;
- separate telemetry for frequency and phase correction components;
- phase-step handling policy.

### Control philosophy

Continue using the slow frequency estimate while introducing a low-bandwidth phase term. Do not run two independent actuators or integrators that can fight one another.

### Exit gate

Hybrid operation improves the chosen phase metric without materially degrading frequency stability or increasing DAC chatter.

---

## Stage SW2-7 — Holdover and controlled recovery

**Purpose:** make reference loss an explicit operating mode rather than an exception.

### Initial holdover

- freeze the last confirmed safe DAC code;
- stop integrating reference error;
- continue raw oscillator/environment observations;
- increase phase/frequency uncertainty with time;
- record holdover start, duration and reason.

### Recovery

- requalify reference and count observations;
- measure the returning phase residual without immediately correcting it;
- choose re-entry through acquisition or settling based on error and uncertainty;
- bound any correction;
- log the complete episode.

### Later holdover models

Only after dedicated evidence:

- linear drift/ageing;
- temperature compensation;
- time-since-warmup dependence;
- confidence-weighted model selection.

### Exit gate

Reference-loss and return tests are safe, deterministic and replayable.

---

## Stage SW2-8 — Platform boundary and second-source proof

**Purpose:** demonstrate that OTIS is scaffolding for other timing applications rather than firmware hard-wired to one GPS PPS input.

### Define a reference adapter boundary

A reference adapter may provide:

- source identity and class;
- source-native observation;
- mapping to an OTIS reference observation;
- uncertainty/quality;
- age and continuity;
- authority policy;
- discontinuity/leap indicators where applicable.

It must not:

- overwrite raw capture history;
- conceal network latency or uncertainty;
- silently claim the same quality as hardware PPS;
- write the DAC directly;
- redefine OTIS clock domains implicitly.

### Proof adapter

Implement one non-GNSS or simulated source adapter. Suitable first choices are:

- deterministic simulated PPS/frequency observations; or
- a second physical external PPS input.

A ClockMesh/RSN adapter should remain a later application proof unless its protocol specification, quality semantics and transport behaviour are sufficiently available.

### Future application boundary

The timing engine should expose read-only products such as:

- current source and authority;
- phase/frequency/drift estimates;
- uncertainty;
- oscillator/control state;
- holdover age;
- health and provenance.

Applications can then include:

- GPSDO control;
- ClockMesh/RSN node participation;
- chrony/NTP reference-clock feed;
- PTP support component;
- time/frequency monitor;
- oscillator comparator;
- laboratory frequency standard;
- generated pulse/frequency services.

### Exit gate

A second source can drive observe-only estimation without changes to the DAC driver or core estimator policy, and its native provenance remains visible.

---

## 7. State-estimation guidance

### 7.1 One coherent state, multiple estimators if useful

The earlier roadmap recommended “one estimator.” Interpret that as one coherent published timing state, not necessarily one monolithic algorithm.

It is acceptable to have separately testable components for:

- reference interval validation;
- frequency estimation;
- phase estimation;
- drift estimation;
- confidence/uncertainty.

They must publish a coherent snapshot with common provenance and age.

### 7.2 Do not promote derived values to raw truth

- Raw `REF` and `CNT` records remain immutable.
- Rejected observations remain recorded.
- Filters and estimator versions are named.
- Reprocessing a run with a new estimator creates new derived artefacts; it does not rewrite the source CSVs.

### 7.3 Quality should be structured, not one Boolean

Retain the existing eligibility flags, but also expose reasons:

- startup inhibit;
- insufficient clean windows;
- stale reference;
- suspect PPS interval;
- missing/zero/saturated count;
- sequence discontinuity;
- capture drop/error;
- plant model absent or mismatched;
- actuator unavailable;
- policy not authorised.

A Boolean answers whether control may proceed; the reason fields explain why.

---

## 8. Configuration and versioning

SW2 reproducibility requires four independently versioned items:

1. firmware/host code commit;
2. telemetry/data-contract version;
3. estimator/control policy version and configuration hash;
4. hardware/plant-model version.

### Recommended profile separation

```text
profiles/
  measurement/
  discipline/
  plant_models/
  applications/
```

The exact directory names can follow repository conventions, but avoid one profile that mixes pin mappings, plant slope, control gains and application behaviour without clear sections.

### Required configuration classes

- measurement backend and gate;
- reference validity;
- count validity;
- startup/warmup qualification;
- plant model;
- automatic-control clamp;
- manual-characterisation clamp;
- maximum update and cadence;
- estimator windows;
- state thresholds/hysteresis;
- holdover/recovery policy;
- application/source authority.

Invalid or mismatched configuration must force observe-only or fault, never silently fall back to active steering.

---

## 9. Telemetry additions

The existing readiness document lists most required fields. Group them into stable records rather than adding an indefinitely widening `STS` line.

### Raw records — preserve

- `REF`;
- `CNT`;
- `EVT`;
- environment;
- low-level health/drop/error counters.

### Derived estimator record

Suggested family: `EST`.

Fields should cover:

- estimator sequence/time;
- source range/provenance;
- phase/frequency/drift estimates;
- uncertainties;
- reference/count ages;
- eligibility and rejection reasons;
- estimator version/configuration hash.

### Control decision record

Suggested family: `CTL`.

Fields should cover:

- operating state and reason;
- policy version;
- frequency and phase terms;
- integrator state;
- requested delta/code;
- preview/applied distinction;
- clamp/slew/saturation;
- plant-model version;
- actuation authorisation;
- bus/write result.

### Event record

State transitions, faults, source changes, model changes, arming/disarming and recovery events should be explicit events rather than inferred solely from sampled status.

---

## 10. Repository-specific Codex work packages

Each task below is intentionally narrower than “implement SW2.”

### Package 1 — Close H1 evidence follow-up

Completed: the clean `run_014` reports are generated, recoverable manifest
fields are backfilled, the pre-G17-fix capture remains separate negative
evidence, and the PPS/reference cadence anomaly is explicitly gated as
diagnostic-only unresolved evidence. `run_017` adds D10-witness confirmation
and timestamp-rollover handling. `run_019` adds the broad response, crossing
location, and long hold. The sealed `run_020` adds focused local crossing,
gain, repeated-centre, and settling evidence and is represented by plant-model
version 3. Do not enable automatic DAC actuation.

### Package 2 — Separate DAC limit classes

Refactor configuration and status so hardware/manual-characterisation limits are distinct from automatic-control limits. Preserve existing sweep behaviour. Automatic control remains disabled. Add compile-time/configuration validation and tests.

### Package 3 — Define plant-model schema

Add a documented machine-readable plant-model schema and loader on the host. Populate it only from authorised completed runs. Unknown fields remain unknown, not zero.

### Package 4 — Define `EST` and `CTL` contracts

Completed for Phase 4 host replay: normative contracts, strict validators, and
focused fixtures are present. DAC output is unchanged.

### Package 5 — Host observe-only estimator

Completed: frequency estimation and distinct validity, diagnostic, confidence,
and eligibility gates consume existing canonical records. Output is confined to
a run's `derived/phase4_replay_v3/` directory and raw/source hashes are checked
unchanged.

### Package 6 — Host preview controller

Completed as a static model-inversion correction preview, not an integrating
controller: the state machine requires plant-model version 4 and the exact
estimator-method contract, and emits bounded
`CTL` proposals without a hardware write path. I-only accumulation remains a
future guarded-actuation concern.

### Package 7 — Firmware observe-only parity

Implementation and deterministic fixture parity are complete. Run the
integrated preview build live with the accepted PPS-gated backend under
service-plane load and long-duration observation. No PPS/count-derived DAC
writes.

### Package 8 — PPS-gated ratio backend validation

Repository remediation replaces the rejected ISR-owned aperture with the
single-PIO-state-machine `pio_wait_cumulative_snapshot_dma_v1` candidate. The
15-word digital proof passes at pinned 133 MHz for 16 MHz and 35--65% duty;
cumulative snapshot/session contracts, minimal ISR diagnostics, deterministic
negative fixtures, explicit estimator typing, qualification analysis, and the
new bench handoff are present.

**Current result: complete and accepted for observe-only measurement on
2026-08-01.** Bench Run 001 remains historical evidence for the rejected
ISR-owned mechanism. The replacement campaign supplies clean pseudo-PPS,
30/31 strict fault, real-GPS quiet/load, 11,388-window extended, and sealed
16,798-window overnight evidence with exact SNP/CNT reconstruction and zero
capture/PIO/DMA/ring/session fault. The 10 microsecond width-only miss is an
accepted rising-edge observability limitation. Controlled physical phase/duty
margin is not tested because the ECS fixture cannot perform it and is recorded
as non-blocking, not passed. Independent absolute metrology remains future
characterization, not a reopened digital-backend gate. Do not enable control.

### Package 9 — First-actuation experiment plan

Using completed H1 evidence, calculate proposed cadence, update size, clamps, qualification and abort rules. Produce a runbook only.

### Package 10 — Single-step guarded actuation

Implement an explicitly armed one-step experiment with preview, apply, observe and disarm phases. No continuous loop.

### Package 11 — Repeated I-only acquisition

Enable repeated bounded updates only after Package 10 evidence passes. Add anti-windup and state hysteresis.

### Package 12 — Phase definition and estimator

Document the exact phase observable and delay assumptions before implementing phase-aware control.

### Package 13 — Hybrid lock

Add bounded phase contribution with replay comparison and long-run validation.

### Package 14 — Holdover and recovery

Start fail-static; add predictive models only in later packages.

### Package 15 — Second-source/platform proof

Add a simulated or external PPS reference adapter and demonstrate estimator reuse without weakening provenance.

Every Codex prompt should specify:

- exact objective;
- files/directories allowed to change;
- contracts that must remain backward compatible;
- explicit non-goals;
- tests and commands;
- required run/report artefacts;
- safety behaviour;
- acceptance gate;
- assumptions and unresolved questions.

---

## 11. Things to retain from other timing projects

### Keep

- conservative, low-bandwidth control;
- extensive telemetry and state visibility;
- explicit warmup/acquisition/lock/holdover states;
- receiver/reference quality as an input, not an afterthought;
- offline replay and parameter comparison;
- calibration of DAC-to-frequency response;
- distinction between frequency and phase control;
- host/network services outside the deterministic capture path;
- source quality and confidence;
- fail-static behaviour.

### Avoid copying blindly

- project-specific magic gains;
- claims of lock based on one threshold;
- aggressive PPS chasing;
- opaque adaptive filters;
- assumed DAC linearity over the full range;
- hiding invalid measurements;
- treating a consumer GNSS PPS as noiseless UTC;
- mixing UI/network work into timing-critical firmware;
- making protocol participation synonymous with timing authority.

### Especially relevant for ClockMesh/RSN-style work

- model peer/network information as another observation source with latency and uncertainty;
- preserve local oscillator and local capture measurements independently;
- publish quality honestly so peers can decide how much to trust OTIS;
- keep network consensus or ranking outside the DAC driver;
- do not let a network protocol redefine the core raw-event contracts;
- design read-only timing-state APIs before writable remote control;
- ensure loss of the network leaves a valid local holdover/free-run mode.

---

## 12. Explicit non-goals until later

Do not allow these to delay the first safe SW2 loop:

- full ClockMesh/RSN protocol implementation;
- PTP grandmaster implementation;
- NTP/chrony integration;
- multi-reference voting;
- Kalman filtering;
- temperature-compensated holdover;
- ageing self-calibration;
- automatic persistent tuning profiles;
- a web UI;
- a disruptive all-at-once dual-core rewrite before the timing-plane/service-plane contracts and H1 evidence gates are ready;
- final PCB abstractions;
- absolute-time/UTC claims beyond the available evidence;
- nanosecond performance claims.

---

## 13. Revised milestone gates

### M0 — H1 measurement path credible

- `run_014` is complete and classified for count-path validity;
- `run_017`, `run_019`, and `run_020` provide clean D10 PPS witness
  confirmation;
- no unexplained post-inhibit invalid count windows over the eligibility period;
- fixed hardware topology documented.

### M1 — Plant model validated for local observe-only use

- slope sign/magnitude and uncertainty;
- settling;
- noise floor;
- repeatability evidence and an explicit endpoint-hysteresis limitation;
- temperature/warmup context;
- versioned plant model.

**Status:** passed for observe-only use with explicit applicability and
unresolved-condition bounds. It is not an active-control authority.

### M2 — Observe-only discipline replay

- `EST`/`CTL` contracts;
- host estimator/state machine/preview;
- deterministic replay.

**Status:** passed for host replay. Firmware parity is implemented; the
integrated long live preview gate and every actuation gate remain open.

### M3 — Live observe-only parity and core isolation

- firmware emits equivalent preview decisions;
- the timing plane and service plane have explicit ownership and bounded cross-core contracts;
- capture and estimator behaviour remain healthy while service-plane USB, telemetry and non-critical I²C work are deliberately stressed;
- droppable and non-droppable queue policies are tested and observable;
- no automatic actuation path exists.

**Status:** implementation and deterministic parity are complete; the
integrated long live preview run remains open.

### M4 — Live discipline measurement validated

- PPS-gated ratio or authorised alternative works cleanly;
- exact capture/continuity and load invariants pass;
- absolute bias and independent metrology remain separately characterized with
  their available uncertainty rather than invented as a digital-backend gate.

**Status:** passed for observe-only measurement on 2026-08-01 with the accepted
width-only limitation and physical phase/duty item not tested/non-blocking. It
does not authorize actuation.

### M5 — Guarded frequency actuation

- one-step and then repeated slow I-only corrections are safe and convergent.

### M6 — Frequency acquisition operational

- repeatable startup/acquisition with state hysteresis and fault handling.

### M7 — Hybrid phase/frequency lock

- explicit phase definition;
- bounded phase term;
- demonstrated improvement without instability.

### M8 — Holdover and recovery

- fail-static holdover;
- controlled requalification and recovery;
- uncertainty tracked.

### M9 — Platform proof

- second source adapter;
- application-facing timing state;
- no GNSS-specific estimator/controller dependency;
- raw provenance preserved.

---

## 14. Definition of SW2 complete

SW2 should be considered complete when OTIS can:

1. preserve and validate raw timing observations in explicit domains;
2. distinguish observation validity from eligibility for control;
3. load a versioned, evidence-backed plant model;
4. estimate frequency and phase with uncertainty and provenance;
5. replay estimator and controller decisions on the host;
6. run the same policy observe-only in firmware;
7. acquire frequency using safe, bounded control;
8. transition to a documented phase-aware hybrid lock;
9. fail static on reference, count, model or actuator faults;
10. enter holdover and recover without abrupt steering;
11. explain every requested and applied DAC change in telemetry;
12. accept at least one alternative or simulated reference through a clean adapter;
13. keep timing capture, estimation and control correct when the service/application core is stalled or overloaded;
14. expose timing state to future applications without allowing those applications to bypass the timing fabric or safety gates.

At that point OTIS is both a credible GPSDO and a credible foundation for broader timing applications. The platform proof is not that every protocol has been implemented; it is that adding a protocol or reference source no longer requires redesigning capture, estimation, control safety, or actuation.

---

## 15. Immediate next actions

1. Run the integrated live Phase 4 estimator/preview build with the accepted
   PPS-gated backend under deliberate service load and long-duration
   observation; keep every actionability field false.
2. Use the accepted backend evidence and CX317 plant model to characterize the
   estimator span, noise floor, and preview cadence without inventing an
   isolated firmware-jitter number.
   Preserve one-second raw snapshots and evaluate cumulative endpoint spans;
   approximately 60--120 seconds is an evidence-supported exploration range,
   not a frozen controller constant.
3. Prepare the separately reviewed guarded-actuation policy: safe operational
   profile, update size, cadence, abort, fail-static, and recovery rules.
4. Keep active DAC steering blocked until that separate policy, cadence,
   maximum-update, abort, and guarded-actuation gate is explicitly reviewed and
   reopened.
