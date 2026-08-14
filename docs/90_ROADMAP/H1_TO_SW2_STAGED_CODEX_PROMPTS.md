# H1 to SW2 Staged Codex Prompts

This prompt pack is for progressing OTIS from the current H1 open-loop evidence
state toward SW2 observe-only design. It is intentionally staged. Do not skip to
dual-core firmware or active DAC control until the evidence gates below are
satisfied.

Current status note:

- Stage 1 has been completed for `run_010`; see
  `runs/h1_open_loop/dac_manual_sweep/run_010/reports/anomaly_classification.md`.
- Stage 2-style host handling exists in current reports; `run_010` is
  analysis-useful after explicit segmentation but is not fixture-ready.
- Stage 3 readiness language is now captured in
  `docs/90_ROADMAP/SW2_GPSDO_CONTROL_LOOP_READINESS.md`.
- Stage 4's planned `run_011` is no longer the next run. `run_011`, `run_012`,
  and `run_013` exist and show post-inhibit zero-count faults. `run_014`
  isolated that class of failure to a G17 breakout solder short, verified clean
  repaired-path CX317 counts, and explicitly gated its PPS/reference anomaly as
  diagnostic-only unresolved evidence.
- `run_020` completed the intended focused profile and is the current local
  model-review input. It directly brackets 10 MHz, places the crossing near
  `0xA950`, and confirms local gain `0.0001559..0.0001876 Hz/code`.
- Phase 3 freezes this evidence in `cx317_h1_bench_v2.json`, model version 3,
  with explicit observe-only applicability and disabled actuation.
- Stage 5 is now the appropriate next stage. Active DAC actuation remains
  blocked.

Current anchor evidence:

- `runs/h1_open_loop/dac_manual_sweep/run_010/`
- `runs/h1_open_loop/dac_manual_sweep/run_010/reports/h1_characterization_summary.md`
- `runs/h1_open_loop/dac_manual_sweep/run_010/reports/summary.md`
- `runs/h1_open_loop/dac_manual_sweep/run_011/reports/h1_characterization_summary.md`
- `runs/h1_open_loop/dac_manual_sweep/run_012/reports/h1_characterization_summary.md`
- `runs/h1_open_loop/dac_manual_sweep/run_013/reports/h1_characterization_summary.md`
- `runs/h1_open_loop/dac_manual_sweep/run_014/notes.md`
- `runs/h1_open_loop/dac_manual_sweep/run_014/reports/anomalies.md`
- `runs/h1_open_loop/dac_manual_sweep/run_014/reports/h1_characterization_summary.md`
- `runs/h1_open_loop/dac_manual_sweep/run_014/reports/summary.md`
- `runs/h1_open_loop/dac_manual_sweep/run_017/reports/anomalies.md`
- `runs/h1_open_loop/dac_manual_sweep/run_017/reports/h1_characterization_summary.md`
- `runs/h1_open_loop/dac_manual_sweep/run_017/reports/summary.md`
- `runs/h1_open_loop/dac_manual_sweep/run_017/csv/h1_count_frequency_estimates.csv`
- `runs/h1_open_loop/dac_manual_sweep/run_017/csv/h1_center_bracketed_slopes.csv`
- `runs/h1_open_loop/dac_manual_sweep/run_019/reports/h1_characterization_summary.md`
- `runs/h1_open_loop/dac_manual_sweep/run_019/reports/summary.md`
- `runs/h1_open_loop/dac_manual_sweep/run_019/csv/h1_count_frequency_estimates.csv`
- `docs/60_EXPERIMENTS/COMPLETED_AND_HISTORICAL/RUN_019_PLANT_MODEL_RESULTS.md`
- `runs/h1_open_loop/dac_manual_sweep/run_020/reports/run_020_analysis_precis.md`
- `runs/h1_open_loop/dac_manual_sweep/run_020/evidence_manifest.json`
- `docs/60_EXPERIMENTS/COMPLETED_AND_HISTORICAL/RUN_020_PLANT_MODEL_RESULTS.md`
- `profiles/plant_models/cx317_h1_bench_v2.json`
- `docs/90_ROADMAP/SW2_GPSDO_CONTROL_LOOP_READINESS.md`
- `docs/90_ROADMAP/STAGED_BUILD_PLAN.md`
- `docs/90_ROADMAP/otis_h1_ocxo_characterization_plan.md`

## Stage 1 Prompt: Classify Run 010 Anomalies

```text
We are in the OTIS repo. Please classify the anomalies in
`runs/h1_open_loop/dac_manual_sweep/run_010` before any SW2 control-loop work.

Read:
- `runs/h1_open_loop/dac_manual_sweep/run_010/reports/summary.md`
- `runs/h1_open_loop/dac_manual_sweep/run_010/reports/validate_report.md`
- `runs/h1_open_loop/dac_manual_sweep/run_010/reports/h1_characterization_summary.md`
- `runs/h1_open_loop/dac_manual_sweep/run_010/raw/capture_device.log`
- `runs/h1_open_loop/dac_manual_sweep/run_010/raw/serial.log`
- the relevant validator/report code in `host/otis_tools/`

Focus on:
- `health.csv` status sequence reset near row 5;
- `environment.csv` env sequence reset near row 3;
- PPS/reference interval anomalies in `raw_events.csv`;
- whether these are host-ingest/session-stitching artifacts, firmware resets,
  serial capture restarts, real PPS gaps, or validator limitations;
- whether H1 characterization should treat this run as one segment or multiple
  explicit capture segments.

Deliver:
- a concise anomaly classification report in
  `runs/h1_open_loop/dac_manual_sweep/run_010/reports/anomaly_classification.md`;
- concrete recommendations for host validation/reporting changes;
- no broad refactor yet;
- no firmware control-loop changes;
- no dual-core work.

Run the relevant validation/report commands after analysis and include exact
commands and outcomes in the report.
```

Gate to Stage 2:

- Each validation error in `run_010` has a classified cause.
- The report says which intervals are trustworthy for plant-model analysis.
- The report identifies whether code changes are needed in validation,
  reporting, characterization, or capture tooling.

## Stage 2 Prompt: Implement Segment-Aware Host Handling

```text
We are in the OTIS repo. Implement only the host-side changes needed by the
`run_010` anomaly classification.

Read:
- `runs/h1_open_loop/dac_manual_sweep/run_010/reports/anomaly_classification.md`
- `host/otis_tools/validate_run.py`
- `host/otis_tools/report_run.py`
- `host/otis_tools/h1_characterize.py`
- `data_contracts/health_v1.csv.md`
- `data_contracts/environment_v1.csv.md`
- `data_contracts/raw_events_v1.csv.md`
- relevant tests under `tests/`

Goal:
- make validation/reporting explicitly handle capture-session segments where
  that is the correct interpretation;
- preserve strict validation for fixture-ready single-session runs;
- ensure H1 characterization does not silently mix bad PPS/count/environment
  intervals into plant-model calculations;
- keep raw observations authoritative and unmodified.

Constraints:
- no broad cleanup;
- no firmware control-loop work;
- no dual-core work;
- no changes that hide real PPS or counter faults;
- update tests or add focused tests for the new segment/anomaly behavior.

Deliver:
- code changes;
- updated reports for `run_010` if appropriate;
- a short note in the final answer stating whether `run_010` is now
  fixture-ready, analysis-useful-only, or invalid for plant-model use.

Run:
- `python3 -m pytest`
- `python3 -m host.otis_tools.validate_run runs/h1_open_loop/dac_manual_sweep/run_010`
- `python3 -m host.otis_tools.report_run runs/h1_open_loop/dac_manual_sweep/run_010`
- `python3 -m host.otis_tools.h1_characterize runs/h1_open_loop/dac_manual_sweep/run_010`
```

Gate to Stage 3:

- Tests pass.
- `run_010` has explicit segment/anomaly interpretation.
- H1 characterization either excludes bad intervals or marks the resulting
  plant evidence as not control-ready.

## Stage 3 Prompt: Update Readiness Docs Around Run 010

```text
We are in the OTIS repo. Update the roadmap/readiness documentation to reflect
the latest H1 evidence from `run_010`.

Read:
- `docs/90_ROADMAP/SW2_GPSDO_CONTROL_LOOP_READINESS.md`
- `docs/90_ROADMAP/STAGED_BUILD_PLAN.md`
- `docs/90_ROADMAP/otis_h1_ocxo_characterization_plan.md`
- `runs/h1_open_loop/dac_manual_sweep/run_010/reports/anomaly_classification.md`
- `runs/h1_open_loop/dac_manual_sweep/run_010/reports/h1_characterization_summary.md`
- `runs/h1_open_loop/dac_manual_sweep/run_010/reports/summary.md`

Goal:
- replace stale `run_006`-centered readiness language where `run_010` is now
  the better evidence source;
- clearly distinguish analysis-useful evidence from fixture-ready evidence;
- document the measured slope/settling/warmup status conservatively;
- keep active SW2 DAC actuation deferred unless the evidence is clean enough;
- identify the next bench confirmation run.

Constraints:
- do not claim closed-loop readiness unless the anomaly classification supports
  it;
- do not introduce dual-core as the next step;
- do not erase older evidence; demote it where superseded.

Deliver:
- updated docs;
- a concise summary of what changed and why;
- any remaining evidence gaps as explicit bullets.
```

Gate to Stage 4:

- The roadmap says plainly whether SW2 is still blocked, observe-only-ready, or
  actuation-experiment-ready.
- The next bench run has a specific purpose.

## Stage 4 Prompt: Design the Confirmation Sweep

```text
We are in the OTIS repo. Design the next targeted H1 confirmation sweep, but do
not change firmware unless the existing sweep commands cannot express it.

Read:
- updated `docs/90_ROADMAP/SW2_GPSDO_CONTROL_LOOP_READINESS.md`
- `runs/h1_open_loop/dac_manual_sweep/run_010/reports/anomaly_classification.md`
- `runs/h1_open_loop/dac_manual_sweep/run_010/reports/h1_characterization_summary.md`
- `docs/60_EXPERIMENTS/COMPLETED_AND_HISTORICAL/H1_OCXO_DAC_CHARACTERIZATION_RUNBOOK.md`
- `host/otis_tools/h1_endpoint_repeat.py`
- firmware sweep command docs in
  `firmware/arduino/otis_nano_rp2040_connect/README.md`

Goal:
- produce a run plan for a shorter confirmation sweep that verifies slope sign,
  approximate magnitude, settling behavior, and thermal drift around the stable
  operating region;
- prefer center-bracketed repeated steps;
- avoid testing outside the already justified voltage/safety envelope;
- specify exact run directory, commands, dwell times, expected artifacts, and
  acceptance criteria.

Deliver:
- `runs/h1_open_loop/dac_manual_sweep/run_011/notes.md` as a planned-run note,
  or another run number if `run_011` already exists;
- any required manifest/config template edits;
- no active control-loop implementation;
- no dual-core work.
```

Gate to Stage 5:

- The confirmation run plan is executable at the bench.
- Acceptance criteria identify what would make SW2 observe-only work safe to
  begin and what would keep it blocked.

## Stage 5 Prompt: SW2 Observe-Only Skeleton

```text
We are in the OTIS repo. Implement an SW2 observe-only skeleton only after the
H1 anomaly review and confirmation-sweep plan are complete.

Read:
- `docs/90_ROADMAP/SW2_GPSDO_CONTROL_LOOP_READINESS.md`
- `docs/50_SOFTWARE/PPS_GATED_RATIO_BACKEND_DESIGN.md`
- `docs/50_SOFTWARE/COUNT_OBSERVATION_MEASUREMENT_CONTRACT.md`
- `firmware/arduino/otis_nano_rp2040_connect/otis_nano_rp2040_connect.ino`
- `firmware/arduino/otis_nano_rp2040_connect/otis_config.h`
- `host/otis_tools/`
- relevant tests

Goal:
- add observe-only SW2 state/telemetry surfaces for control eligibility,
  startup inhibit, clean-window qualification, fault status, nominal restore
  policy, and plant-model reporting;
- make active DAC actuation impossible unless explicitly enabled by a separate
  future compile-time/control gate;
- preserve all raw CNT/REF/STS/DAC telemetry;
- keep the state logic backend-generic enough to support FC0 and future
  PPS-gated ratio observations.

Constraints:
- no automatic DAC movement from PPS or FC0 error;
- no PI/PID/Kalman/filter control;
- no holdover implementation beyond telemetry labels if needed;
- no dual-core work;
- keep changes small and testable.

Deliver:
- firmware/host changes required for observe-only SW2 telemetry;
- tests or validation fixtures for the new telemetry;
- updated docs describing the observe-only boundary;
- compile/test commands and outcomes.
```

Gate to Active SW2 Actuation:

- The H1 plant-evidence gate is complete: `run_020` supplies the local crossing,
  gain, repeatability, and settling bounds.
- The versioned observe-only model passes its range and applicability tests.
- A separate actuation policy defines and tests update size, cadence,
  fail-static handling, saturation/anti-windup, and explicit arming.
- Startup and fault gates are tested.
- The readiness doc explicitly authorizes a first guarded actuation experiment.

## Stage 6 Prompt: First Guarded Actuation Experiment Plan

Use this only after the active-actuation gate above is satisfied.

```text
We are in the OTIS repo. Plan, but do not yet implement, the first guarded SW2
actuation experiment.

Read the latest readiness docs and H1 confirmation-run reports. Produce a
proposal that defines:
- controller type, expected to be very slow I-only unless evidence says
  otherwise;
- DAC update size in codes and its derivation from H1 evidence;
- actuation cadence and its derivation from settling time;
- startup holdoff;
- valid-observation requirements before each actuation;
- hard clamps;
- abort/fault rules;
- raw and derived telemetry needed for replay.

Deliver:
- a draft experiment plan under `docs/60_EXPERIMENTS/`;
- no firmware actuation code yet unless explicitly requested afterward.
```
