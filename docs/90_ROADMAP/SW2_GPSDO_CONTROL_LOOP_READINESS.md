# SW2 GPSDO Control Loop Readiness

## Decision

SW2 active GPSDO steering is **not ready**.

The repo now contains useful H1 evidence for DAC I2C operation, conservative DAC
clamping, connected tune-voltage sanity checks, open-loop sweep telemetry, FC0
count observations, PPS/reference telemetry, and warmup/drift reporting. It does
not yet contain a resolved DAC-to-frequency plant model. The current H1 sweep
therefore supports SW2 design work, telemetry contracts, safety gates, and
observe-only firmware scaffolding, but it does not support automatic DAC
actuation from PPS or FC0 error.

## H1 Evidence Available

Primary artifacts:

- `runs/h1_open_loop/dac_output_verify/run_001/reports/h1_characterization_summary.md`
- `runs/h1_open_loop/dac_output_verify/run_001/reports/summary.md`
- `runs/h1_open_loop/dac_output_verify/run_001/notes.md`
- `runs/h1_open_loop/dac_manual_sweep/run_006/reports/h1_characterization_summary.md`
- `runs/h1_open_loop/dac_manual_sweep/run_006/reports/summary.md`
- `runs/h1_open_loop/dac_manual_sweep/run_006/notes.md`
- `runs/h1_open_loop/dac_manual_sweep/run_006/csv/dac_steps.csv`
- `runs/h1_open_loop/dac_manual_sweep/run_006/csv/cnt.csv`
- `runs/h1_open_loop/dac_manual_sweep/run_006/csv/ref.csv`

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
- `dac_manual_sweep/run_006/reports/summary.md` reports 758 count windows, 725
  reference events, 165 DAC events, and 3146 health rows.
- `dac_manual_sweep/run_006/reports/summary.md` reports `fc0_measure_period_ms:
  1000`, so the current raw observation cadence is one FC0 report per second.
- `dac_manual_sweep/run_006/reports/h1_characterization_summary.md` reports a
  requested warmup window of 1800 s, an actual span of 756.999 s, and a practical
  stability time of 754.999 s, with a note that the requested warmup window
  exceeds the run duration.
- `dac_manual_sweep/run_006/notes.md` records that the frequency response is not
  resolved by the current short FC0 gate and that ppm/V should remain unclaimed.

## H1 Evidence Missing

Missing or insufficient evidence for active SW2 control:

- No `runs/h1_open_loop/ocxo_free_run/run_001/reports/summary.md` artifact is
  present.
- No `runs/h1_open_loop/settling_thermal/run_001/reports/h1_characterization_summary.md`
  artifact is present.
- The current run manifests leave several plant-critical fields unset, including
  oscillator nominal frequency, oscillator control-voltage range, DAC reference
  voltage, manifest safety limits, and measured tuning sensitivity.
- The connected sweep lacks populated per-step voltage columns in
  `dac_steps.csv`; the bench voltages are documented in notes rather than bound
  to each DAC dwell row.
- `open_loop_slope_known` is `false` in both current H1 characterization
  summaries.
- `safe_voltage_window_known` is `false` in both current H1 characterization
  summaries, even though bench notes document a conservative checked voltage
  span.
- `settling_time_characterized` is `false` in both current H1 characterization
  summaries.
- Hysteresis is only partially observable. The repeated center code reports 0 Hz
  median span in the current analysis, but up/down comparison is unavailable for
  most tested codes.
- The run_006 summary includes a startup PPS/reference interval anomaly and is
  not fixture-ready.

## Measured Plant Model

Current measured model:

| Quantity | Current value | Source | Design implication |
|---|---:|---|---|
| Nominal DAC code | `0x8000` / 32768 | H1 notes and DAC sweep rows | Use as the only documented nominal restore point. |
| Conservative checked DAC span | `0x7000..0x9000` / 28672..36864 | H1 notes and status summaries | Accept as a bench-verified voltage envelope, not yet as a control envelope. |
| Connected tune-voltage span | 1.091 V..1.401 V | `dac_manual_sweep/run_006/notes.md` | Safe for observed CX317 `Vc` wiring in H1. |
| Connected midpoint voltage | 1.246 V at `0x8000` | `dac_manual_sweep/run_006/notes.md` | Startup restore candidate. |
| Approximate V/code from bench endpoints | `(1.401 - 1.091) / (0x9000 - 0x7000)` = 37.8 uV/code | Derived from run_006 notes | Useful only for telemetry voltage estimates. |
| Local Hz/V | unavailable | H1 characterization summaries | Do not compute DAC corrections. |
| Local ppm/V | unavailable | H1 characterization summaries | Do not compute DAC corrections. |
| Local Hz/code | unresolved; summary reports 0 for tested steps | `dac_manual_sweep/run_006/reports/h1_characterization_summary.md` | Treat as measurement-resolution failure, not zero plant gain. |
| Warmup observation | practical stability at 754.999 s within a 756.999 s run | run_006 characterization summary | At least 755 s of observe-only warmup is needed; the requested 1800 s window has not been satisfied. |
| Settling time | not characterized | H1 characterization summaries | No closed-loop cadence may be finalized. |
| Short-term FC0 floor | not cleanly established; medians quantize to 10 MHz and some means/stddev are dominated by artifacts | run_006 characterization summary | Improve gate/resolution before deriving loop constants. |

Because Hz/V and ppm/V are unavailable, SW2 must not convert PPS or FC0 error
into active DAC movement yet.

## Safe Operating Envelope

The only envelope suitable for SW2 design discussion is:

- Restore/nominal DAC code: `0x8000`.
- Firmware clamp candidates: `0x7000` minimum and `0x9000` maximum.
- Estimated tune-voltage reporting model, for telemetry only:
  - `Vctl_est = 1.246 V + (dac_code - 32768) * 0.0000378 V/code`
  - Clamp the estimate to the measured connected span 1.091 V..1.401 V when
    reporting from the H1 bench model.
- Manual preview step size: at most `0x0400` codes, matching the H1 small sweep
  step documented in `STAGED_BUILD_PLAN.md` and visible in run_006 sweep rows.
- Extended manual preview step size: `0x0800` codes was observed inside the
  checked `0x7000..0x9000` span, but it should not be used for automatic steering.

This envelope is not enough to close the loop. It is enough to prevent future
SW2 code from reaching outside the voltages already checked on the bench.

## Recommended Control Cadence

For SW2 design now:

- Emit observe-only control telemetry at the existing H1 FC0 cadence of 1 s.
- Emit aggregated plant-model/reporting telemetry at 60 s or slower.
- Do not actuate periodically until a real settling time and Hz/V or ppm/V slope
  are measured.

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

Until the plant slope is measured:

- Active DAC update size: 0 codes.
- Open-loop preview update size: clamp requested preview movement to `0x0400`
  codes per manual step.
- Automatic actuation update size for the first guarded I-only experiment:
  undefined until Hz/code or ppm/code is measured. The future value must be
  chosen so one update is a small fraction of the observed short-term FC0 noise
  floor and a small fraction of the characterized capture range.

No PR should introduce PPS-derived or FC0-error-derived DAC changes before this
undefined value is replaced by an H1-derived number.

## Recommended Startup Holdoff

Current recommendation:

- Set `0x8000` at startup only when explicitly running a manual nominal-restore
  mode.
- Observe only for at least 1800 s before any future steering experiment.
- If 1800 s is not practical during a bench run, require at least the measured
  755 s practical stability time from run_006 and mark the run as not a full
  warmup validation.

The 1800 s holdoff comes from the H1 characterization warmup target, not from a
completed 30 minute stable run. It remains a conservative placeholder until H1
captures a full warmup/thermal run.

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
  observe PPS, FC0, DAC state, and health

warmup:
  no steering
  require startup holdoff and valid telemetry history

acquire:
  no steering until plant slope is known
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
- Warmup inhibit: prevent steering before the startup holdoff expires.
- PPS invalid inhibit: stop steering if PPS is missing, stale, nonmonotonic, or
  outside validity limits.
- FC0 invalid inhibit: stop steering if FC0 count windows are missing, stale,
  flagged, or outside expected gate behavior.
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

- Treating the unresolved run_006 slope as zero would produce a controller with
  the wrong sign or infinite gain assumptions.
- The current FC0 observation path appears too coarse for the small DAC steps
  tested; longer gates or a better phase/frequency estimator may be required.
- The current warmup data is shorter than the requested 1800 s warmup target.
- Existing manifest safety fields are null, so future code must not rely only on
  manifests for clamp values until run metadata is backfilled.
- PPS startup artifacts can poison acquire logic if the state machine accepts
  early reference intervals without filtering.
- Manual voltage notes are not the same as continuous measured tune-voltage
  telemetry.
- Hysteresis and thermal drift are not characterized enough for holdover or
  environmental compensation.
- DAC bus recovery and fail-static behavior must be verified before any
  actuation-capable PR is merged.

## Gate To Reopen SW2 Actuation

Revisit guarded actuation only after a new H1 data set provides:

- populated safe DAC code and tune-voltage limits in the run manifest;
- connected tune-voltage measurements bound to DAC dwell points or equivalent
  calibrated telemetry;
- nonzero resolved local Hz/V or ppm/V with sign and uncertainty;
- settling response for at least two code-step sizes;
- a full warmup or thermal run that meets or supersedes the 1800 s target;
- short-term FC0 noise floor measured with the same estimator SW2 will use;
- repeated up/down sweeps sufficient to bound hysteresis.

Until then, SW2 work should stay in design, telemetry, manual restore, and
observe-only preview stages.
