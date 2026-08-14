# Stage 1 Prompt: Baseline and Evidence Handoff

Execute Stage 1 without flashing firmware or issuing a serial command.

## Goal

Establish one reproducible development baseline from the completed observe-only
programme without rerunning successful long captures.

## Procedure

1. Verify the repository is on clean `main`, equals `origin/main`, has no other
   local branch and has no linked worktree. Stop before modifying code if not.
2. Create the campaign directory and durable state file required by the master.
3. Locate and validate the sealed Stage 1, 3, 5 and 6 evidence referenced by
   the final-readiness report. Do not modify or reseal it.
4. Recompute and record the selected estimator, plant-model and preview-policy
   hashes. Confirm they match the final-readiness identities.
5. Preserve the previous `ready_for_more_observe_only_testing` decision as the
   correct result of its deliberately non-actuating programme. Do not rewrite
   it retrospectively; create new active-control authority and decisions under
   this programme.
6. Confirm the Stage 6 flashed artifact identity and final `0xA950` applied-code
   record from evidence. Treat the physical current code as unknown until the
   Stage 2 live query or acknowledgement.
7. Run the complete software suite, current firmware matrix and no-hardware
   validation. Explain skips. Repair only genuine baseline defects.
8. Inventory the precise code surfaces required for:
   - receiver metadata;
   - active authority and arming;
   - actuator request/accepted/applied records;
   - correction and cumulative budgets;
   - response classification;
   - future cross-core queues.
9. Reconcile the repository's contradictory core-number documents. Freeze the
   programme convention as Core 0 services and Core 1 protected timing. Correct
   any test wording that says to stall the timing core while expecting the
   service core to preserve timing.

## Explicit non-work

- no new long observation run;
- no firmware upload;
- no DAC command;
- no GPS configuration command;
- no dual-core implementation yet;
- no change to the accepted PIO/DMA snapshot mechanism.

## Deliverables and exit gate

Produce a Stage 1 report under the campaign directory containing exact source,
evidence, test and architecture identities plus the implementation inventory.

Pass only if the evidence validates, the current full test/build baseline is
clean, and the accepted backend/model/policy identities are unambiguous.
