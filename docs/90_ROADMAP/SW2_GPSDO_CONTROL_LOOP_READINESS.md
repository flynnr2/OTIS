# SW2 GPSDO Control Loop Readiness

## Decision

SW2 active GPSDO steering is **not ready**.

The repo now contains useful H1 evidence for DAC I2C operation, DAC clamping,
connected tune-voltage sanity checks, scripted long-gate open-loop sweeps,
PPS/reference telemetry, environmental telemetry, session-aware host reporting,
startup/control-eligibility status, and a completed clean `run_014` after the
G17 conditioning fault was repaired. Earlier evidence showed that the
count-observation path could produce post-startup zero-count faults under the
faulted bench configuration; `run_014` now explains that failure as a hardware
short on the SN74LVC1G17 breakout rather than a host analysis, logging, or
firmware-counting artifact.

The current state supports SW2 design work, telemetry contracts, safety gates,
manual nominal restore, and observe-only firmware scaffolding. It does **not**
support automatic DAC actuation from PPS or count error. The next decision point
is not dual-core firmware or a PI loop; it is producing a versioned
conservative plant model from the clean H1 evidence, carrying the explicit
REF/PPS anomaly gate into SW2 control eligibility, and then planning an
intentionally guarded actuation experiment.

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
- `ocxo_free_run/run_004/reports/anomalies.md` reports 20 bad FC0 windows
  confined to startup, with the first clean CNT window about 3.67 minutes after
  the first CNT window and about 10.18 hours of clean observation afterward.
- `ocxo_free_run/run_004/reports/h1_characterization_summary.md` treats the
  current MID free-run data as FC0 control-eligible only after a startup inhibit
  and clean-window requirement; this is an estimator/control gate, not a raw
  capture filter.

## H1 Evidence Missing

Missing or insufficient evidence for active SW2 control:

- No `runs/h1_open_loop/settling_thermal/run_001/reports/h1_characterization_summary.md`
  artifact is present.
- Several run manifests still leave plant-critical fields unset, including
  oscillator nominal frequency, oscillator control-voltage range, DAC reference
  voltage, manifest safety limits, and measured tuning sensitivity.
- The connected sweep lacks populated per-step voltage columns in
  `dac_steps.csv`; most voltage evidence still comes from notes or the manifest
  voltage model rather than measured dwell-row telemetry.
- `run_014` reports `open_loop_slope_known: true` on a clean count path, but the
  slope is still noisy and should be frozen as a conservative local plant model
  before it is used to calculate automatic updates.
- `run_014` reports `settling_time_characterized: true`, but the settling
  estimates are still analysis products rather than loop constants until a
  guarded model records the selected cadence, uncertainty, and valid operating
  neighbourhood.
- `run_011`, `run_012`, and `run_013` report `fc0_valid_for_control: false`
  because zero-count windows occur after startup inhibit.
- PPS/reference anomalies remain present in the completed `run_014`, but they
  are now explicitly gated rather than an unclassified validation failure. SW2
  must still treat those windows as not control-eligible until the
  reference/capture path has its own fault telemetry or a clean validation run.

## Measured Plant Model

Current measured model:

| Quantity                                     | Current value                                              | Source                                  | Design implication                                                       |
| -------------------------------------------- | ---------------------------------------------------------- | --------------------------------------- | ------------------------------------------------------------------------ |
| Nominal DAC code                             | `0x8000` / 32768                                           | H1 notes and DAC sweep rows             | Use as the documented manual restore point.                              |
| Conservative checked DAC span                | `0x7000..0x9000` / 28672..36864                            | H1 notes and status summaries           | Best current SW2 clamp candidate.                                        |
| Extended bench sweep span                    | `0x6000..0xE000` / 24576..57344                            | `run_010` notes and summaries           | Useful for characterization only; do not use as automatic steering span. |
| Connected `0x7000..0x9000` tune-voltage span | 1.091 V..1.401 V                                           | `dac_manual_sweep/run_006/notes.md`     | Safe observed narrow envelope.                                           |
| Extended estimated tune-voltage span         | about 0.936 V..2.176 V for `0x6000..0xE000`                | `run_010`/`run_011` voltage model notes | Characterization estimate, not a closed-loop safety envelope.            |
| Approximate V/code from bench endpoints      | about 37.8 uV/code                                         | Derived from H1 notes                   | Useful only for telemetry estimates unless measured per dwell.           |
| Local Hz/V and ppm/V                         | clean-path median center-bracketed slope about 4.30 Hz/V   | `run_014` characterization summary      | Positive local slope is now known, but should be frozen into a conservative plant model before actuation. |
| Settling estimates                           | present from clean `run_014`, still noisy                  | `run_014` characterization summary      | Analysis evidence; choose loop cadence only after model review.          |
| Startup/control gate                         | `run_014` reports `fc0_valid_for_control=true`, 282 clean windows at end | `run_014` characterization summary      | Count-path gate can reopen; reference/PPS anomaly gate remains.          |
| REF/PPS anomaly gate                         | 2719 short intervals explicitly gated as diagnostic-only and not control-eligible | `run_014` manifest and anomaly report   | Root cause remains unresolved; do not use anomalous REF/PPS windows for control. |
| Current bench next step                      | Plant-model freeze with explicit reference-validity gates   | `run_014` reports                       | Do not actuate until reference validity and model envelope are explicit. |

Because the clean `run_014` slope evidence has not yet been reduced into a
versioned automatic-control model, and because the PPS/reference anomaly is
gated rather than root-caused, SW2 must not convert PPS or count error into
active DAC movement.

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

The PPS-gated ratio backend may improve the raw evidence available to future
SW2 design, but it does not make active GPSDO steering ready by itself.
The backend should produce raw PPS-gated `CNT` observations and explicit
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

The only narrow envelope suitable for first SW2 design discussion is:

- Restore/nominal DAC code: `0x8000`.
- Firmware clamp candidates: `0x7000` minimum and `0x9000` maximum.
- Estimated tune-voltage reporting model, for telemetry only:
  - `Vctl_est = 1.246 V + (dac_code - 32768) * 0.0000378 V/code`
  - Clamp the estimate to the measured connected span 1.091 V..1.401 V when
    reporting from the H1 bench model.
- Manual preview step size: at most `0x0400` codes, matching the H1 small sweep
  step documented in `STAGED_BUILD_PLAN.md` and visible in run_006 sweep rows.
- Extended bench characterization spans such as `0x6000..0xE000` are not SW2
  actuation spans. They exist to reveal plant behavior and bench faults.

This envelope is not enough to close the loop. It is enough to prevent future
SW2 code from reaching outside the voltages already checked on the bench.

## Recommended Control Cadence

For SW2 design now:

- Emit observe-only control telemetry at the selected count-observation cadence.
  In current H1 long-gate metrology, `CNT` windows are 300 s.
- Emit aggregated plant-model/reporting telemetry at 60 s or slower.
- Do not actuate periodically until a real settling time and Hz/V or ppm/V slope
  are measured on a clean post-inhibit count path.

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

After `run_014`, the plant slope has been measured on a clean,
control-eligible count path, but it has not yet been converted into a frozen
automatic-control model:

- Active DAC update size: 0 codes.
- Open-loop preview update size: clamp requested preview movement to `0x0400`
  codes per manual step.
- Automatic actuation update size for the first guarded I-only experiment:
  undefined until the `run_014` slope, noise and settling evidence is reviewed
  into a versioned plant model. The future value must be chosen so one update is
  a small fraction of the observed short-term count noise floor and a small
  fraction of the characterized capture range.

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

The 1800 s holdoff remains a conservative placeholder. `run_014` gives a clean
24-hour-class open-loop run, but the holdoff should be revisited only when the
first SW2 plant model records the chosen estimator and reference-validity
rules.

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

- DAC clamps: enforce `0x7000..0x9000` until a newer H1 run documents a safer or
  wider envelope.
- Maximum slew per update: 0 codes for active control until plant gain is known;
  `0x0400` codes for manual/open-loop preview only.
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

1. Telemetry-only state skeleton.
2. Manual nominal DAC restore to `0x8000`, guarded by the existing clamp logic.
3. Observe-only plant-model telemetry with explicit unavailable fields.
4. Open-loop correction preview, no actuation.
5. Guarded I-only actuation after H1 supplies Hz/V or ppm/V, settling time, and
   noise-floor evidence.
6. Lock/holdover state machine.
7. Reporting and long-run validation.

Each stage should preserve the non-goal that no active PPS-derived DAC steering
exists before stage 5.

## Explicit Risks

- Treating the older unresolved `run_006` slope as zero would produce a
  controller with the wrong sign or infinite gain assumptions.
- Treating noisy long-gate slopes from earlier fault-contaminated runs as final
  plant gain would produce unsafe sign or gain assumptions.
- The bench path produced post-startup zero-count windows in `run_011`,
  `run_012`, and `run_013`; `run_014` traced that class of failure to a G17
  solder fault and verified a clean repaired count path.
- The current warmup and settling estimates are useful analysis products, not
  loop constants.
- Existing manifest safety fields are null, so future code must not rely only on
  manifests for clamp values until run metadata is backfilled.
- PPS startup artifacts and the short-interval PPS/reference anomaly burst in
  `run_014` can poison acquire logic if the state machine accepts early or
  anomalous reference intervals without filtering and fault accounting.
- Manual voltage notes are not the same as continuous measured tune-voltage
  telemetry.
- Hysteresis and thermal drift are not characterized enough for holdover or
  environmental compensation.
- DAC bus recovery and fail-static behavior must be verified before any
  actuation-capable PR is merged.

## Gate To Reopen SW2 Actuation

Revisit guarded actuation only after the completed `run_014` evidence, or a
newer H1 data set, is reduced into:

- populated safe DAC code and tune-voltage limits in the run manifest;
- connected tune-voltage measurements bound to DAC dwell points or equivalent
  calibrated telemetry;
- nonzero resolved local Hz/V or ppm/V with sign and uncertainty;
- settling response for at least two code-step sizes;
- a full warmup or thermal run that meets or supersedes the 1800 s target;
- short-term FC0 noise floor measured with the same estimator SW2 will use;
- repeated up/down sweeps sufficient to bound hysteresis;
- no post-inhibit zero-count windows or equivalent invalid count-observation
  faults over the planned actuation eligibility window;
- resolved or explicitly gated PPS/reference cadence anomalies.

Until then, SW2 work should stay in design, telemetry, manual restore, and
observe-only preview stages.
