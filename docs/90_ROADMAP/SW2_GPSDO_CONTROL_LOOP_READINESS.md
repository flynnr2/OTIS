# SW2 GPSDO Control Loop Readiness

## Decision

The bounded frequency-control programme reached
**`dual_core_frequency_control_endurance_passed`** on 2026-08-08. The
authoritative review is
`../60_EXPERIMENTS/CX317_BOUNDED_CLOSED_LOOP_ACQUISITION_FINAL_REPORT.md`.

This is a positive, evidence-sealed result for the exact CX317/AD5693R rig,
PPS-gated 600 s estimator, bounded I-only policy, `0xA800..0xAB00` clamp and
dual-core ownership contract tested by the programme. It is not a claim that a
complete GPSDO product, calibrated frequency standard or UTC/phase discipline
system is ready.

The final Stage 7B run qualified all 151 authoritative observations, applied
one exact `+19`-code correction from `0xA815` to `0xA828`, and then remained
inside the frozen deadband for 150 consecutive observations / 90,000 s. All
four service bursts and re-arm interlocks passed. The host transport recorded
21,279 accepted commands with zero rejection, parser error, reconnect,
malformed UTF-8 or emergency abort. The sealed Stage 7B snapshot and every
earlier mandatory gate revalidate.

Final offline verification passed 790 tests with two expected evidence-
availability skips, all 22 supported firmware profiles, all seven intended
unsafe-profile guards, three wire validators and synthetic validate/report
checks. The board remains static at the last confirmed applied code `0xA828`.

The next primary goal is
**phase-estimator definition and bounded hybrid phase/frequency preview**. It
must begin non-actionable and replayable. Phase steering, calibrated absolute
frequency, UTC traceability, holdover, timing-grade GNSS provisioning and
oscilloscope-based waveform margin remain unsupported; none is authorized by
the completed frequency-control programme.

The sections below preserve the precursor observe-only/backend evidence as
historical context. Where they describe active frequency control as incomplete,
the 2026-08-08 final report supersedes that status without erasing the evidence
that led to it.

## Historical precursor readiness evidence

## Phase 4 host replay readiness

The host-only M2 gate is passed:

- normative `EST v2`, `RFO v1`, `DIAG v1`, and observe-only `CTL v1`
  contracts have strict host validation;
- replay consumes manifest-resolved `REF`, `CNT`, `STS`, and `DAC` evidence;
- estimator qualification uses accepted reference cadence, count validity,
  age, continuity, dispersion, and startup/recovery clean windows;
- model-version-4 identity, estimator-method contract, applicability, excluded sequences, disabled
  candidate range, and manual preview step are enforced;
- repeated execution produces byte-identical derived records;
- raw/source evidence hashes remain unchanged;
- no firmware, serial command, DAC write, arming, PI/PID/Kalman, thermal, or
  holdover-prediction path was added.

This passes deterministic host replay and native estimator parity. Physical
aperture and PPS-gated backend bench qualification were subsequently accepted
by the Phase 5 campaign on 2026-08-01. Active-control policy approval and
guarded actuation remain incomplete.

## Phase 4 live observe-only parity readiness

The firmware implementation and deterministic parity portion of M3 is
complete:

- the exact pure C++ engine used by firmware matches host replay state,
  eligibility, numeric estimate, reason, and preview decisions for the focused
  fixture matrix;
- live firmware emits strict `EST v2`, `RFO v1`, `DIAG v1`, and `CTL v1` rows
  with plant-model, policy, configuration, diagnostic, source, and DAC
  provenance;
- model-version-4 topology/backend/method-contract applicability, disabled candidate range, and
  maximum preview step are enforced;
- the preview module has no DAC-driver include, callback, serial command, or
  returned proposal path to the manual DAC owner;
- bounded paired telemetry drops are accounted without changing estimator
  state or raw capture/count truth;
- default H1, explicit preview, PPS-gated, alternative capture, FC0, and GPIO
  count selector builds compile.

M3 observe-only integration is now passed by the sealed 2026-08-02/03 CX317
replacement run. The live estimator and preview remained numerically aligned
with host replay across five RP2040 timer wraps, the service-plane load caused
no capture or preview loss, and the DAC remained static at `0xA950`. This closes
the integrated live-preview milestone only. Firmware active control and every
actuation gate remain incomplete; `status.control_ready=false`,
`status.actuation_enabled=false`, `actuation_authorized=false`,
`actionable=false`, and `active_live_update_codes=0` remain authoritative.

## Phase 5 PPS-gated backend qualification readiness

**Result: accepted on 2026-08-01 as the qualified observe-only measurement
backend, with documented limitations. The earlier ISR-owned Run 001 remains
historical evidence for the rejected mechanism and did not qualify the new
PIO-owned backend.**

The accepted replacement evidence includes:

- a proved 15-word single-state-machine `WAIT` snapshot program at pinned
  133 MHz for the 16 MHz, 35--65% digital envelope;
- raw cumulative `SNP` evidence and adjacent down-counter reconstruction;
- an independent D14 `REF` observer with minimal ISR and explicit PIO/D14
  association;
- independent `pps_gate/reference_validity` and
  `pps_gate/count_validity`, with typed reasons;
- startup missing-PPS detection, duplicate/short/long classification, count
  zero/saturation handling, and recovery gates;
- explicit unavailable aperture/reference uncertainty hooks;
- deterministic synthetic/negative fixtures;
- explicit candidate and independent estimator/backend/source typing;
- a deterministic qualification report under the local run's `derived/`
  directory;
- an exact bench runbook and data-driven v2 criteria.

The rejected Run 001 captured a post-reset ISR-owned candidate session containing
33111 consecutive one-second windows. Startup qualification, qualifying-size
baseline and serial-status-load segments, missing-PPS inhibition, zero-count
inhibition, and clean-window recovery passed. The disturbed serial session
before the authoritative BOOT is preserved and documented separately from the
declared comparison range.

The new campaign—not Run 001—supplies clean pseudo-PPS evidence, 30/31 strict
fault classification, real-GPS quiet/load evidence, 11,388 extended windows,
and a sealed 16,798-window overnight comparison across 14 pairs. Every accepted
overnight `CNT` reconstructs exactly from adjacent raw `SNP` boundaries and all
capture/PIO/DMA/ring/parser/session counters remain clean. The one missed
10 microsecond width-only fault is an accepted rising-edge-only limitation.
Physical phase/duty margin is not tested because the ECS fixture cannot control
it; this is non-blocking and is not called a pass. Independent absolute
metrology and a complete uncertainty budget also remain outside this
qualification.

The follow-up exact-ELF and source latency/jitter audit found no measurement-
path optimization to make. PIO owns both the oscillator count and cumulative
PPS snapshot; the D14 ISR is an independent reconstructed REF observer, and
DMA/foreground/service work occurs after the immutable snapshot. The observed
spread must remain described as end-to-end ECS/GPS/input/environmental
characterization rather than isolated firmware jitter. The anti-regression
requirements are normative for subsequent estimator and control work; see
`../50_SOFTWARE/PPS_CAPTURE_LATENCY_JITTER_AUDIT_20260801.md`.

See `PHASE_5_PPS_GATED_BACKEND_QUALIFICATION_REPORT.md` and
`PHASE_5_REAL_GPS_EXTENDED_AND_OVERNIGHT_CAMPAIGN_20260801.md`.
Existing evidence/runtime status remains `backend_qualified=false`,
`status.control_ready=false`, and `status.actuation_enabled=false`; reflecting
backend acceptance in an operational profile and authorizing actuation are
separate future changes.

## H1 Evidence Available

Primary artifacts:

- `runs/h1_open_loop/dac_output_verify/run_001/reports/h1_characterization_summary.md`
- `runs/h1_open_loop/dac_output_verify/run_001/reports/summary.md`
- `runs/h1_open_loop/dac_output_verify/run_001/notes.md`
- `runs/h1_open_loop/dac_manual_sweep/run_009/reports/h1_characterization_summary.md`
- `runs/h1_open_loop/dac_manual_sweep/run_010/reports/anomaly_classification.md`
- `runs/h1_open_loop/dac_manual_sweep/run_010/reports/h1_characterization_summary.md`
- `runs/h1_open_loop/dac_manual_sweep/run_010/reports/summary.md`
- `runs/h1_open_loop/dac_manual_sweep/run_011/reports/h1_characterization_summary.md`
- `runs/h1_open_loop/dac_manual_sweep/run_012/reports/h1_characterization_summary.md`
- `runs/h1_open_loop/dac_manual_sweep/run_013/reports/h1_characterization_summary.md`
- `runs/h1_open_loop/dac_manual_sweep/run_014/notes.md`
- `runs/h1_open_loop/dac_manual_sweep/run_016/reports/h1_characterization_summary.md`
- `runs/h1_open_loop/dac_manual_sweep/run_016/csv/h1_count_frequency_estimates.csv`
- `runs/h1_open_loop/dac_manual_sweep/run_017/reports/h1_characterization_summary.md`
- `runs/h1_open_loop/dac_manual_sweep/run_017/reports/summary.md`
- `runs/h1_open_loop/dac_manual_sweep/run_017/reports/anomalies.md`
- `runs/h1_open_loop/dac_manual_sweep/run_017/csv/h1_count_frequency_estimates.csv`
- `runs/h1_open_loop/dac_manual_sweep/run_017/csv/h1_center_bracketed_slopes.csv`
- `runs/h1_open_loop/dac_manual_sweep/run_019/reports/h1_characterization_summary.md`
- `runs/h1_open_loop/dac_manual_sweep/run_019/reports/summary.md`
- `runs/h1_open_loop/dac_manual_sweep/run_019/reports/anomalies.md`
- `runs/h1_open_loop/dac_manual_sweep/run_019/csv/h1_count_frequency_estimates.csv`
- `docs/60_EXPERIMENTS/RUN_019_PLANT_MODEL_RESULTS.md`
- `runs/h1_open_loop/dac_manual_sweep/run_020/evidence_manifest.json`
- `runs/h1_open_loop/dac_manual_sweep/run_020/reports/run_020_analysis_precis.md`
- `runs/h1_open_loop/dac_manual_sweep/run_020/reports/h1_characterization_summary.md`
- `runs/h1_open_loop/dac_manual_sweep/run_020/csv/h1_center_bracketed_slopes.csv`
- `docs/60_EXPERIMENTS/RUN_020_PLANT_MODEL_RESULTS.md`
- `profiles/plant_models/cx317_h1_bench_v3.json` (current model version 4;
  `cx317_h1_bench_v2.json` remains historical)
- `runs/h1_open_loop/ocxo_free_run/run_004/reports/anomalies.md`
- `runs/h1_open_loop/ocxo_free_run/run_004/reports/h1_characterization_summary.md`
- `runs/h1_open_loop/ocxo_free_run/run_004/reports/summary.md`

Observed evidence:

- DAC part: AD5693R over I2C at `0x4C` in the H1 manifests.
- H1 mode: manual open-loop only; closed-loop control is false.
- Unloaded DAC check in `dac_output_verify/run_001/notes.md`:
  - `0x7000` -> 1.093 V
  - `0x8000` -> 1.249 V
  - `0x9000` -> 1.405 V
- Connected CX317 `Vc` check in `dac_manual_sweep/run_006/notes.md`:
  - `0x7000` -> 1.091 V
  - `0x8000` -> 1.246 V
  - `0x9000` -> 1.401 V
  - repeated `0x8000` -> 1.246 V
- Connected `Vc` remained inside the noted CX317 0.0 V to 3.3 V operating
  control-voltage range.
- `dac_manual_sweep/run_009` through `run_013` use 300 s long-gate H1 count
  windows and scripted DAC dwell attribution, replacing the earlier short-gate
  `run_006` evidence as the main plant-characterization source.
- `dac_manual_sweep/run_010/reports/anomaly_classification.md` classifies the
  opening health/environment sequence reset as a host-appended pre-reconnect
  fragment plus a fresh firmware boot; the main post-BOOT segment is
  analysis-useful, but `run_010` is not fixture-ready.
- `dac_manual_sweep/run_010/reports/h1_characterization_summary.md` reports 228
  long-gate count windows, 464 DAC events, 136938 environment samples, and
  session-aware analysis of the final segment.
- `dac_manual_sweep/run_011` is complete, but its characterization reports 108
  invalid/post-startup zero-count windows and `fc0_valid_for_control: false`.
- `dac_manual_sweep/run_012` repeats the issue after connection changes, with
  104 invalid/post-startup zero-count windows and `fc0_fault: true`.
- `dac_manual_sweep/run_013` is a short buffer-bypass diagnostic. It reduces the
  observed bad-window count to 3, but still reports a post-inhibit FC0 fault and
  is not control-ready.
- `dac_manual_sweep/run_014` is the clean dirty-to-clean power-path experiment
  after the G17 breakout repair. The pre-fix capture was preserved separately
  under `derived/pre_g17_fix_capture_2026-07-25/`. The clean capture reports 284
  300 s `CNT` rows, no zero-count rows, all `CNT` flags `16`, no host capture
  drops, no parser errors, 18 completed DAC-sweep passes, and
  `fc0_valid_for_control: true` after startup qualification.
- `dac_manual_sweep/run_014/reports/h1_characterization_summary.md` reports 90
  characterization points, 35 center-bracketed local slopes, a positive median
  slope of about 4.30 Hz/V, warmup drift after warmup of about
  -0.0417 ppm/hour, and near-VCOCXO SHT4x temperature spanning about 23.30 C to
  27.83 C.
- `dac_manual_sweep/run_014/reports/anomalies.md` records the remaining major
  caveat as explicitly gated evidence: 2719 short PPS/reference intervals,
  concentrated early in the run but not startup-only. Host characterization
  ignored out-of-band PPS intervals for tick-rate calibration, and
  `manifest.json` gates the matching anomaly set as diagnostic-only and not
  control-eligible. Current telemetry still cannot distinguish a true
  reference-source issue from GPIO/capture/IRQ/FIFO/DMA/firmware-path extra or
  missed REF edges.
- `dac_manual_sweep/run_016` has been regenerated with the locally
  PPS-interpolated H1 estimator. It reports 153 count windows, 152
  `LOCAL_PPS_INTERPOLATED` estimates, one startup-edge fallback to
  `RUN_WIDE_TICK_RATE`, no PPS anomalies, and `fc0_valid_for_control: true`.
  The retained legacy run-wide estimate differs from the local estimate with
  median 0.007 Hz, standard deviation 3.13 Hz, and span 14.48 Hz, confirming
  that the old run-wide tick-rate conversion is not trustworthy enough for
  sub-hertz DAC/CX317 conclusions.
- In `run_016`, the corrected local-PPS estimates reduce within-dwell scatter
  enough to make centre-bracketed `0x0800` and `0x1000` steps useful plant
  evidence. The repeated centre span is about 0.176 Hz, so `0x0200` and
  `0x0400` remain near the current measurement floor and should not drive plant
  authority conclusions by themselves.
- `run_016` environmental fits remain diagnostic only: only 14 of 153 count
  windows align with nearest SHT4x samples within 5 s under the present host
  alignment, and simple air-temperature terms are confounded with elapsed time.
  Do not conclude that airflow or CX317 internal thermal state is irrelevant.
- `dac_manual_sweep/run_017` is the clean rollover-specific predecessor to
  `run_019`. It reports
  242 count windows, 241 `LOCAL_PPS_INTERPOLATED` estimates, one startup-edge
  fallback to `RUN_WIDE_TICK_RATE`, no host-classified PPS anomalies after
  unwrapping 16 RP2040 timer rollovers, no reconnects, no reboot/header markers,
  and `fc0_valid_for_control: true`.
- In `run_017`, the temporary D10 PPS witness matched D14 at the end of the run:
  final D14 raw count 72970, final D10 raw count 72970, D14-D10 delta 0, no D10
  short rows, no D10 buffer overflow rows, and no burst rows. D14
  `rejected_long_count` ended at 16, matching the 16 timestamp rollovers; treat
  that historical value as a rollover-sensitive firmware diagnostic artifact.
  The firmware diagnostic classifier now uses modular RP2040 timer arithmetic so
  future normal PPS intervals crossing rollover do not increment the long
  rejection counter.
- `run_017` observed CX317 outputs over the tested range from about
  9.999997327 MHz at DAC `0x7000` to about 9.999998711 MHz at DAC `0x9000`.
  The full span is about 1.384 Hz. The centre-bracketed local slopes across
  `0x0800` and `0x1000` steps are about 4.15..4.67 Hz/V, positive and
  consistent with the CX317 datasheet-derived 10 MHz tuning expectation of
  about 3.0..6.1 Hz/V over the full 0.0 V..3.3 V control range.
- `run_017` near-VCOCXO SHT4x temperature spans about 25.43 C to 29.53 C, with
  post-warmup drift about -0.00023 ppm/hour after the configured warmup window.
  The run ended after an overnight static hold at `0x8000`; this is useful
  stability evidence but is still open-loop.
- `run_019` captured one continuous 12.89 h session with 155 of 155 non-zero
  count windows valid, 46,394 of 46,394 PPS intervals valid, final D10/D14
  delta zero, and no parser, reconnect, capture-drop, saturation, or overflow
  failures.
- The actual `run_019` profile was `0x0100..0xFF00`, centre `0x8000`, 900 s
  dwell, and `0x0200` tiny steps. It differed from the intended
  crossing-focused manifest and must be interpreted by the configuration that
  actually ran.
- The first broad sweep fits `0.000169064 Hz/code` with `R²=0.999920`.
  Drift-cancelled estimates give 4.38..4.50 Hz/V using the `run_018` voltage
  fit. Crossing estimates cluster near `0xAE00`, approximately 1.692 V.
- `run_019` did not measure a close crossing bracket: `0x8400` was the highest
  sampled code below 10 MHz and `0xBF80` the lowest above. Tiny steps around
  `0x8000` are not a local crossing model.
- The final `run_019` `0x8000` hold spans 8.17 h with median
  9,999,997.974452 Hz, standard deviation 0.043665 Hz, and fitted drift
  +0.002104 Hz/h. Temperature spans 28.327 C..29.566 C.
- `run_020` executed the exact verified focused profile with 77/77 valid
  non-zero count windows, 23,250/23,250 valid PPS intervals, final D10/D14
  agreement, zero capture/parser/overflow faults, and acknowledged `0x8000`
  restoration.
- `run_020` directly brackets 10 MHz between `0xA800` at
  9,999,999.963233 Hz and `0xAB00` at 10,000,000.059011 Hz. The model crossing
  is `0xA950`, with conservative within-run band `0xA840..0xAA00`.
- Four Run 020 drift-cancelled slopes span
  `0.0001559..0.0001876 Hz/code`, approximately 4.11..4.95 Hz/V using the
  Run 018 fit. Seven uncontaminated transitions have t95 no greater than about
  653 s at 300 s gate resolution.
- `ocxo_free_run/run_004/reports/anomalies.md` reports 20 bad FC0 windows
  confined to startup, with the first clean CNT window about 3.67 minutes after
  the first CNT window and about 10.18 hours of clean observation afterward.
- `ocxo_free_run/run_004/reports/h1_characterization_summary.md` treats the
  current MID free-run data as FC0 control-eligible only after a startup inhibit
  and clean-window requirement; this is an estimator/control gate, not a raw
  capture filter.

## H1 Evidence Missing

Missing or insufficient evidence for active SW2 control:

- No separate `runs/h1_open_loop/settling_thermal/run_001/reports/h1_characterization_summary.md`
  artifact is present, although `run_019` provides an 8.17 h static hold.
- Several run manifests still leave plant-critical fields unset, including
  oscillator nominal frequency, oscillator control-voltage range, DAC reference
  voltage, manifest safety limits, and measured tuning sensitivity.
- The connected sweep lacks populated per-step voltage columns in
  `dac_steps.csv`; most voltage evidence still comes from notes or the manifest
  voltage model rather than measured dwell-row telemetry.
- Run 020 closes local crossing, gain, repeatability, and conservative settling
  for observe-only use. Endpoint bidirectional hysteresis remains unresolved,
  and 300 s gate resolution prevents a fine dynamic model.
- `run_019` is also not a sealed fixture: `COMPLETE`, an evidence manifest,
  pre-run Git snapshots, and operator DMM observations are absent.
- `run_011`, `run_012`, and `run_013` report `fc0_valid_for_control: false`
  because zero-count windows occur after startup inhibit.
- PPS/reference anomalies remain present in the completed `run_014`, but they
  are explicitly gated rather than an unclassified validation failure.
  `run_016`, `run_017`, and `run_019` do not repeat that anomaly in their
  analysed REF streams. SW2 must still treat anomalous reference windows as not
  control-eligible. The modular D14 interval fix subsequently crossed six
  timer rollovers cleanly across the Phase 5 extended and overnight runs;
  historical rollover-sensitive counters remain qualified as historical data.

## Measured Plant Model

Current measured model:

| Quantity                                     | Current value                                              | Source                                  | Design implication                                                       |
| -------------------------------------------- | ---------------------------------------------------------- | --------------------------------------- | ------------------------------------------------------------------------ |
| Manual restore DAC code                      | `0x8000` / 32768                                           | H1 notes and DAC sweep rows             | Historical restore point, not the 10 MHz operating point.                |
| Estimated 10 MHz crossing                    | `0xA950`, within-run band `0xA840..0xAA00`; about 1.648 V  | Run 020 local bracket/regression and Run 018 voltage fit | Nominal observe-only operating point. |
| Candidate automatic-control span             | `0xA800..0xAB00`                                           | Plant model v3                         | Contains crossing band but remains disabled and is not actuation permission. |
| Local model applicability span               | `0xA800..0xB400`                                           | Run 020 settled profile                | Valid observe-only neighbourhood for this topology and estimator. |
| Run 019 characterization span                | `0x0100..0xFF00`                                           | Actual uploaded `run_019` configuration | Broad electrical characterization only; not an actuation span.           |
| Checked-in Run 020 characterization span     | `0x6000..0xFC00`                                           | `otis_config.h`                          | Header-only Arduino IDE test envelope; not an actuation span.             |
| Connected `0x7000..0x9000` tune-voltage span | 1.091 V..1.401 V                                           | `dac_manual_sweep/run_006/notes.md`     | Safe observed narrow envelope.                                           |
| DMM voltage fit                              | about 37.8905 uV/code                                      | `run_018` operator readings             | Useful calibration model; uncertainty and direct Run 019 DMM trace are absent. |
| Broad gain                                   | `0.000169064 Hz/code`; 4.38..4.50 Hz/V; `R²=0.999920`      | `run_019` broad analysis                | Validates broad response, not local controller gain.                      |
| Observed broad output range                  | 9,999,992.480189 Hz at `0x0100` to 10,000,003.514548 Hz at `0xFF00` | `run_019` settled medians        | Demonstrates crossing and monotonic range.                               |
| Local gain                                   | `0.0001559..0.0001876 Hz/code`; 4.11..4.95 Hz/V            | Run 020 drift-cancelled brackets       | Versioned observe-only gain and uncertainty. |
| Settling evidence                            | uncontaminated t95 no greater than about 653 s; 900 s exclusion | Run 020 analysis                    | Supported conservative exclusion, not a control cadence. |
| Startup/control gate                         | 77/77 count windows and 23,250/23,250 PPS intervals valid | Run 020 reports                         | Clean observation path; does not itself authorize actuation.             |
| REF/PPS anomaly gate                         | 2719 short intervals explicitly gated as diagnostic-only and not control-eligible | `run_014` manifest and anomaly report   | Root cause remains unresolved; do not use anomalous REF/PPS windows for control. |
| D10 PPS witness                              | final D14 and D10 raw counts both 72970; no D10 short, overflow, or burst rows | `run_017` summary and status analysis   | Good evidence that the main run did not reproduce the earlier PPS burst. |
| Rollover diagnostic caveat                   | Historical `run_017` D14 `rejected_long_count=16`, matching 16 raw timestamp rollovers | `run_017` summary and firmware review   | Preserved raw artefact; firmware diagnostics now classify intervals with modular timer arithmetic, but historical counts remain qualified by host-unwrapped REF analysis. |
| Current bench next step                      | Integrated live observe-only estimator and correction preview using the accepted PPS-gated backend | Phase 4/Phase 5 accepted evidence | No hardware write or periodic actuation. |

The local model is now available, but actuation remains blocked because the
candidate envelope is not a control policy and earlier reference/diagnostic
validity gates remain mandatory.

## Startup FC0 Control Gate

Run `ocxo_free_run/run_004` established the SW2 architecture requirement: early
FC0 and PPS observations may be present and useful for diagnostics, but they are
not eligible for acquire, lock, estimator seeding, or actuation. Runs `run_011`
through `run_013` add the current blocker: invalid zero-count windows can also
occur after startup inhibit, so the control gate must remain active throughout a
run, not only during warmup. `run_014` shows that the specific zero-count
blocker was hardware-induced and is resolved in the repaired topology, but the
gate remains a required SW2 safety mechanism.

SW2 must distinguish these states:

- `fc0_observed_valid`: raw FC0 telemetry exists and can be reported.
- `fc0_valid_for_control`: the startup inhibit has expired and at least three
  consecutive clean FC0 count windows have followed it.
- `fc0_fault`: an invalid FC0 count window occurred after the startup inhibit.

Initial gate defaults:

- Startup inhibit: 600 s from FC0 observation-mode entry.
- Clean-window requirement: 3 consecutive valid FC0 windows after inhibit.
- Bad windows during inhibit: visible in CNT/STS telemetry, but not controller
  faults.
- Bad windows after inhibit: force `fc0_valid_for_control=false` and inhibit any
  future acquire or discipline transition.

This gate must be implemented as metadata/status around raw observations. Do not
delete or suppress startup CNT/REF rows in capture artifacts.

## PPS-Gated Ratio Backend Readiness

The PPS-gated ratio backend is accepted as the preferred observe-only live
measurement path, but it does not make active GPSDO steering ready by itself.
The backend produces raw PPS-gated `CNT` observations and explicit
`pps_gate` / count-observation `STS` telemetry. Host tools may derive
frequency, ratio, and ppm from those observations.

Control-readiness semantics must remain conservative:

- a PPS-gated `CNT` row is not automatically control-eligible;
- PPS/reference validity and oscillator-count validity are both required;
- startup inhibit and clean-window qualification still apply;
- a clean oscillator count with suspect PPS is invalid for control;
- a clean PPS interval with zero, saturated, or missing oscillator count is
  invalid for control.

The existing `fc0_observed_valid`, `fc0_valid_for_control`, and `fc0_fault`
telemetry names remain compatibility surfaces until host tooling migrates to
backend-generic names. Internally, new PPS-gated implementation work should keep
this logic in the count-observation module, not in the Arduino sketch or DAC
state machine.

## Safe Operating Envelope

The current safe-envelope conclusion is:

- Manual fail-static restore code: `0x8000`.
- Observe-only nominal/crossing code: `0xA950`.
- Crossing uncertainty: `0xA840..0xAA00`.
- Candidate automatic range: `0xA800..0xAB00`, disabled.
- Local applicability/manual range: `0xA800..0xB400`.
- `0x7000..0x9000` is safe historical characterization evidence but is not a
  control candidate because it does not reach the crossing.
- Estimated tune-voltage reporting model, for telemetry only:
  - `Vctl_est = 0.005348 V + dac_code * 0.0000378905 V/code`
- Manual preview step size: at most `0x0300` codes in model version 3.
- Extended bench characterization spans such as `0x6000..0xFC00` are not SW2
  actuation spans. They exist to reveal plant behavior and bench faults.

The candidate envelope is available for deterministic observe-only clamping and
preview. It is not authorized for hardware actuation.

## Recommended Control Cadence

For SW2 design now:

- Emit observe-only control telemetry at the selected count-observation cadence.
  In current H1 long-gate metrology, `CNT` windows are 300 s.
- Emit aggregated plant-model/reporting telemetry at 60 s or slower.
- Do not actuate periodically until a separate guarded-experiment policy turns
  the measured settling and gain into cadence, update, abort, and arming rules.

For the first future actuation experiment after plant characterization:

- Use an actuation interval no faster than the larger of 60 s or 10 times the
  measured 95 percent settling time.
- Use only averaged error over the full interval.
- Require several consecutive valid PPS and FC0 observations before every
  actuation decision.

The 60 s lower bound is deliberately much slower than the current 1 s FC0 sample
cadence and 5 s H1 dwell windows. It is a design guardrail, not a tuned loop
constant.

## Recommended DAC Update Size

After Run 020, local gain is known on a clean measurement path, but no automatic
update has been authorized:

- Active DAC update size: 0 codes.
- Open-loop preview update size: clamp requested preview movement to `0x0300`
  codes per manual step.
- Automatic actuation update size for the first guarded I-only experiment:
  undefined until the evidence is reviewed into a versioned actuation policy.
  The future value must be chosen so one
  update is a small fraction of the observed short-term count noise floor and a
  small fraction of the characterized capture range.

No PR should introduce PPS-derived or FC0-error-derived DAC changes before this
undefined value is replaced by an H1-derived number.

## Recommended Startup Holdoff

Current recommendation:

- Set `0x8000` at startup only when explicitly running a manual nominal-restore
  mode.
- Observe only for at least 1800 s before any future steering experiment.
- Require no post-inhibit invalid count windows during the whole eligibility
  window. A clean startup followed by later zero-count faults is not
  actuation-ready.

The 1800 s holdoff remains a conservative placeholder. `run_019` gives a clean
overnight open-loop run with an 8.17 h final `0x8000` hold, but the holdoff should
be revisited only when the first SW2 actuation policy records the chosen
estimator and reference-validity rules.

## Recommended Initial Controller Type

Initial SW2 controller type:

- Current implementation target: telemetry-only state skeleton.
- First actuation-capable controller after H1 closes the data gap: guarded,
  very slow I-only control.
- PI control remains a later option after lock, holdover, plant gain, settling,
  and noise behavior are validated over long runs.

No PID controller should be considered for SW2 initial actuation.

## Proposed Control-Loop Architecture

Design only:

```text
startup:
  set nominal DAC only in explicit nominal-restore mode
  otherwise leave DAC static
  observe PPS, count windows, DAC state, and health

warmup:
  no steering
  require startup holdoff and valid telemetry history

acquire:
  no steering until plant slope is known on a clean count path
  future behavior: slow coarse correction with explicit preview telemetry first

discipline:
  future behavior: very slow I-only loop
  PI only after long-run evidence supports proportional action

holdover:
  freeze correction initially
  future behavior: decay correction cautiously only after holdover data exists

fault:
  clamp output
  stop steering
  keep last known safe static DAC code when possible
  emit warning telemetry
```

## Telemetry Requirements

SW2 firmware should emit these fields before active steering is allowed:

- `control_state`
- `control_state_reason`
- `dac_code`
- `dac_code_requested`
- `dac_code_applied`
- `dac_clamped`
- `dac_min_code`
- `dac_max_code`
- `estimated_tune_voltage_v`
- `tune_voltage_model_source`
- `pps_valid`
- `pps_age_s`
- `fc0_valid`
- `fc0_age_s`
- `fc0_gate_s`
- `error_hz`
- `error_ppm`
- `error_source`
- `correction_hz`
- `correction_ppm`
- `correction_code_preview`
- `loop_interval_s`
- `integrator_state`
- `integrator_enabled`
- `saturation_state`
- `warmup_elapsed_s`
- `warmup_inhibit`
- `startup_inhibit_active`
- `startup_inhibit_elapsed_s`
- `fc0_observed_valid`
- `fc0_valid_for_control`
- `fc0_clean_window_count`
- `fc0_fault`
- `slew_limited`
- `bus_status`
- `i2c_recovery_count`
- `plant_model_version`
- `plant_model_hz_per_v`
- `plant_model_ppm_per_v`
- `plant_model_hz_per_code`
- `plant_model_valid`

Telemetry should make unavailable values explicit. Do not encode unknown plant
gain as zero.

## Safety Requirements

SW2 safety gates:

- DAC clamps: model v3 records candidate `0xA800..0xAB00`, but actuation remains
  disabled. Firmware characterization limits must not be reused as control
  limits.
- Maximum slew per update: 0 codes for active control; `0x0300` codes for
  manual/open-loop preview only.
- Warmup/startup inhibit: prevent steering before the startup holdoff expires
  and before FC0 has met the post-inhibit clean-window requirement.
- PPS invalid inhibit: stop steering if PPS is missing, stale, nonmonotonic, or
  outside validity limits.
- FC0 invalid inhibit: stop steering if FC0 count windows are missing, stale,
  flagged, outside expected gate behavior, inside startup inhibit, or not yet
  post-inhibit clean-window qualified.
- Bus failure behavior: do not retry indefinitely while changing output; mark DAC
  write failure and enter fail-static/fault.
- I2C recovery behavior: attempt bounded bus recovery, re-read/report status,
  and require a fresh successful static write before leaving fault.
- Fail-static behavior: keep the last confirmed safe DAC code when possible;
  otherwise command the nominal `0x8000` only if the DAC bus is healthy and the
  write can be confirmed.
- Saturation behavior: disable integration while saturated or clamped.
- Startup behavior: do not infer previous lock from retained state unless the
  plant model version and safety envelope match the current firmware.

## Implementation Stages

Future SW2 PR sequence:

1. Completed: diagnostic foundations plus host EST/CTL replay validation and
   non-actuating fault fixtures.
2. Next: firmware telemetry-only state skeleton and host parity.
3. Validate manual nominal DAC restore to `0x8000` remains isolated from
   discipline policy and guarded by existing clamp logic.
4. Add firmware observe-only plant-model telemetry with explicit unavailable
   fields.
5. Compare firmware open-loop correction preview with host replay; no
   actuation.
6. Guarded I-only actuation only after the separate policy gate supplies and
   approves Hz/V or ppm/V, cadence, update size, abort rules, settling time, and
   noise-floor evidence.
7. Lock/holdover state machine.
8. Reporting and long-run validation.

Each stage should preserve the non-goal that no active PPS-derived DAC steering
exists before the guarded actuation stage.

## Explicit Risks

- Treating the older unresolved `run_006` slope as zero would produce a
  controller with the wrong sign or infinite gain assumptions.
- Treating noisy long-gate slopes from earlier fault-contaminated runs as final
  plant gain would produce unsafe sign or gain assumptions.
- The bench path produced post-startup zero-count windows in `run_011`,
  `run_012`, and `run_013`; `run_014` traced that class of failure to a G17
  solder fault and verified a clean repaired count path.
- Run 020 supports a 900 s observe-only settling exclusion, not a selected loop
  cadence.
- Existing manifest safety fields are null, so future code must not rely only on
  manifests for clamp values until run metadata is backfilled.
- PPS startup artifacts, the short-interval PPS/reference anomaly burst in
  `run_014`, and rollover-sensitive diagnostic counters can poison acquire
  logic if the state machine accepts early, anomalous, or miscomputed reference
  diagnostics without filtering and fault accounting.
- Manual voltage notes are not the same as continuous measured tune-voltage
  telemetry.
- Hysteresis and thermal drift are not characterized enough for holdover or
  environmental compensation.
- DAC bus recovery and fail-static behavior must be verified before any
  actuation-capable PR is merged.

## Gate To Reopen SW2 Actuation

Run 020 and Phase 3 satisfy the observe-only plant-model gate. Revisit guarded
actuation only after the remaining policy and verification work provides:

- one integrated long live estimator/preview run using the accepted PPS-gated
  backend, with actionability and actuation remaining false;
- populated safe DAC code and tune-voltage limits in the run manifest;
- connected tune-voltage measurements bound to DAC dwell points or equivalent
  calibrated telemetry;
- an explicitly approved update size and cadence derived from the recorded
  local gain and settling evidence;
- a full warmup or thermal run that meets or supersedes the 1800 s target;
- short-term PPS-gated noise floor measured with the same estimator and span
  SW2 will use, with FC0 retained as an independent long-gate comparison where
  available;
- endpoint hysteresis bounds adequate for the proposed update size, or an
  explicit conservative uncertainty treatment;
- no post-inhibit zero-count windows or equivalent invalid count-observation
  faults over the planned actuation eligibility window;
- resolved or explicitly gated PPS/reference cadence anomalies.

Until then, SW2 work should stay in design, telemetry, manual restore, and
observe-only preview stages.
