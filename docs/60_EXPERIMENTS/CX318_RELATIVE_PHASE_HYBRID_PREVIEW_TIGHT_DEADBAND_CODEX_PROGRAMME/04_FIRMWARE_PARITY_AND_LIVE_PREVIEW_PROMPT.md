# Stage 4 Prompt: Firmware Parity and Short Live Preview

Execute Stage 4 after host replay passes. The DAC remains static throughout this
stage.

## Goal

Run the selected relative-phase estimator and hybrid candidates on the protected
timing core, prove exact host/firmware parity, then expose them to a short real-
GPS live record before granting the separate tight-deadband experiment any
authority.

## Firmware integration

- Preserve the accepted PIO/DMA snapshot mechanism unchanged.
- Keep timing/estimation/preview on Core 1 and service/formatting on Core 0.
- Emit immutable phase observations and candidate preview records with exact
  source identities and configuration hashes.
- Ensure telemetry formatting, queue pressure and Core 0 stalls cannot mutate
  estimator/preview state.
- Give phase/hybrid code no actuator-request callback or authority object.
- Preserve existing frequency-control code but compile this stage with
  actuation disabled.

## Parity and fault tests

Require exact or contractually bounded parity for:

- interval error and cumulative phase;
- phase epoch start/reset;
- selected phase/frequency state;
- preview state transitions;
- frequency term, phase-bias term and combined request;
- clamp, rounding and counterfactual code;
- every rejection, hold and recovery reason.

Run source guards, focused tests, full tests, firmware matrix and no-hardware
validation before flashing.

Judge phase continuity from the RPH session/epoch and qualification sequence.
An exactly replayed `RECOVER_PREVIEW` while a newly opened phase epoch awaits
its first authoritative 600 s frequency estimate is initialization, not by
itself a phase discontinuity. A later invalid RPH, second epoch-open,
`REFERENCE_LOST_PREVIEW` or `FAULT_PREVIEW` remains a stop condition.

## Live preview

After exact identity and board preflight:

0. complete the exact-bundle operational rehearsal required by `AGENTS.md`;

1. confirm the last applied DAC code from live evidence; do not rewrite it;
2. flash only the dedicated non-actuating CX318 preview profile;
3. capture at least two complete 600 s authoritative estimates and normally
   2--4 h of qualified real-GPS operation;
4. exercise bounded normal GNSS, environment, USB and telemetry service load;
5. monitor phase epochs, queue health and preview candidates continuously;
6. stop at the finite endpoint; do not extend merely to obtain a preferred
   phase trend.

## Live stop conditions

Stop and seal diagnostic evidence on reset, identity mismatch, capture
discontinuity, queue loss, source association failure, unexplained parity
mismatch or any attempted/actual DAC write.

## Deliverables and exit gate

Deliver the firmware profile, parity fixtures, live preview run, exact replay,
load/isolation result and Stage 4 report.

Pass only if host and firmware explain the same phase and preview sequence,
timing ownership remains intact, and zero DAC requests/writes or authority
consumption occur.
