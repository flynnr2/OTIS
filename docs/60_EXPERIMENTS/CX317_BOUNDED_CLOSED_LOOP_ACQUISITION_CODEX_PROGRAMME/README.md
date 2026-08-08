# CX317 Bounded Closed-Loop Acquisition Codex Programme

This folder contains the staged programme that follows the successful
PPS-gated estimator and observe-only controller campaign.

## Completed outcome

The programme completed on 2026-08-08 with the evidence-gated decision
`dual_core_frequency_control_endurance_passed`. The authoritative report is
[`../CX317_BOUNDED_CLOSED_LOOP_ACQUISITION_FINAL_REPORT.md`](../CX317_BOUNDED_CLOSED_LOOP_ACQUISITION_FINAL_REPORT.md).

The final 24-hour dual-core endurance run applied one exact `+19`-code
correction from `0xA815` to `0xA828`, then retained `0xA828` inside the frozen
deadband for 150 consecutive qualified observations / 90,000 s. All four
service bursts, cross-core transaction phases, replay, transport and fail-
static gates passed. The board remains static at `0xA828`.

The selected next goal is a replayable phase estimator and a non-actionable
bounded hybrid phase/frequency preview. The completed programme does not claim
calibrated absolute accuracy, UTC traceability, phase lock, holdover or
oscilloscope-qualified waveform margin, and it grants no authority for those
functions.

The programme is deliberately ambitious. It moves from the proved preview
chain to bounded automatic frequency acquisition, learns from repeated
actuation in both directions, then introduces the RP2040 dual-core boundary
before sustained operation. It is built around one operating rule:

> Fail early, locally, observably, and recoverably.

The programme does not interpret every unresolved calibration or physical
qualification item as a reason to repeat long observe-only runs. It separates:

- evidence required to move the DAC safely inside the already exercised code
  range;
- evidence required to claim calibrated frequency accuracy, UTC traceability,
  physical input margin, holdover performance, or a finished GPSDO.

It also separates measurement validity from control eligibility. A valid
response remains evidence if the plant model later becomes inapplicable; new
writes then stop in `OUT_OF_MODEL_HOLD`. Nearby-air SHT41 temperature is a
recorded covariate, not a demonstrated oscillator-temperature safety bound.

## Execution order

1. `00_MASTER_UNATTENDED_PROMPT.md`
2. `01_BASELINE_AND_EVIDENCE_HANDOFF_PROMPT.md`
3. `02_GNSS_AND_ACTUATOR_PREFLIGHT_PROMPT.md`
4. `03_BOUNDED_ACTIVE_CONTROLLER_PROMPT.md`
5. `04_CAMPAIGN_A_A950_ACQUISITION_PROMPT.md`
6. `05_CAMPAIGN_B_BIDIRECTIONAL_ACQUISITION_PROMPT.md`
7. `06_DUAL_CORE_TIMING_SERVICE_PARTITION_PROMPT.md`
8. `07_DUAL_CORE_ACTIVE_ENDURANCE_PROMPT.md`
9. `08_FINAL_REVIEW_AND_NEXT_GOAL_PROMPT.md`

`PROGRAMME_STATE_TEMPLATE.md` is the durable campaign ledger. The executing
Codex session must copy it into a new run directory before changing firmware
or touching the rig.

## Authorization boundary

These files are a proposed programme, not standing permission to actuate the
rig. An operator must explicitly instruct Codex to execute the master prompt.
That instruction authorizes only the exact bounded actions and limits in the
master and stage prompts. It does not authorize wider code ranges, larger or
faster corrections, phase steering, holdover correction, adaptive control, or
unbounded operation.

## Intended outcome

A successful programme should leave OTIS with:

- receiver metadata qualifying the captured PPS without replacing PPS timing
  truth;
- a transaction-safe, capped I-only frequency controller;
- two-direction closed-loop acquisition evidence;
- measured same-backend step/settling response;
- an explicit Core 0 service / Core 1 timing partition;
- a dual-core active endurance run demonstrating bounded frequency control;
- a clear decision on progression to acquisition refinement, hybrid phase
  control, holdover, or further hardware work.
