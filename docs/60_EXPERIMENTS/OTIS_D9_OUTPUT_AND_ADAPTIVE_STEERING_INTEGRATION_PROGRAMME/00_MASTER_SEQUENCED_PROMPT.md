# Master Prompt: D9 Output Gate and Adaptive-Steering Integration

You are operating in the OTIS repository on the computer attached to the bench
rig. Execute this programme in the declared order. Treat a decision-bearing
result, exact operational handoff and reproducible evidence package as the unit
of progress.

Recommended lead: **GPT-5.6 Sol, xhigh reasoning**.

Use **GPT-5.6 Terra, high reasoning** subagents for bounded read-only evidence
audits, disjoint implementation, focused test triage and independent claims
review when this materially reduces elapsed time. The lead alone owns physical
authority, serial ownership, flashing, live supervision, gate decisions,
contract freezes, integration and final claims. A subagent may never touch the
bench, issue a receiver or DAC command, change authority, decide a live gate,
weaken a criterion, commit, push, delete or reseal evidence.

If subagents are unavailable, continue serially without weakening any gate.

## Programme objective

Deliver a characterized forwarded 10 MHz output on D9 and the smallest
confirmed adaptive-steering integration needed to operate the CX317 VCOCXO
close to nominal 10 MHz relative to D14 PPS while retaining bounded actuator
use, explicit phase semantics and fail-local degradation.

The final integrated control candidate is the retained unchanged CX322 coherent
FLL/PLL request law unless the D9/FLL-output gate blocks integration:

- the FLL term reacts to current qualified D8 frequency error relative to D14;
- the slower PLL term may request a bounded temporary frequency bias to reduce
  same-epoch D14-relative phase movement;
- both terms share one policy, persistence/cadence envelope and actuator
  transaction path;
- D8/D14 measurement, not D9 or D6, remains control truth;
- a stationary DAC code is not the objective; and
- the controller must not chase one-second quantization/noise or claim UTC,
  absolute epoch alignment, calibrated accuracy or oscillator-only stability.

The first D9 sustained soak is deliberately frequency-only. It establishes the
forwarded-output and non-interference baseline before hybrid behavior is
integrated.

## Frozen starting decision

Validate these identities before making a programme change:

- V2 contract:
  `b7525de381bbd6506978819a46ccdc280993c47aba2d1ab673a9e595b48e325f`;
- V2 derived manifest:
  `705361d252782c911cea63bfca691691c6ab045956942f057f87db31827b4816`;
- V2 tracked report:
  `c411e44042162192228b04c4ebd567b90d73ddd77344f9d1d6f494ada863e9e5`;
- analysis tool bundle:
  `fbbcb152880b0079e97eb9b9d216e292aa805ceb829e78996c4e06dee282b1ca`;
- terminal:
  `provisional_cx322_unchanged_pending_d9_gate`.

The changed tagged-debt candidates remain non-selectable. Do not implement
their changed request mathematics, refit the failed static model, adjust a
threshold after seeing D9 evidence or call unchanged CX322 superior. The D9
gate can confirm the fail-closed unchanged candidate or block integration.

## Mandatory read-first set

Read completely and apply:

- repository and applicable nested `AGENTS.md` files;
- `docs/00_FOUNDATIONS/OTIS_ARCHITECTURE_OVERVIEW.md`;
- `docs/00_FOUNDATIONS/OTIS_DESIGN_PRINCIPLES.md`;
- `docs/00_FOUNDATIONS/OTIS_NON_GOALS.md`;
- `docs/00_FOUNDATIONS/OTIS_REFERENCE_TERMINOLOGY.md`;
- `docs/10_REFERENCE_ARCHITECTURE/ADAPTIVE_FREQUENCY_STEERING.md`;
- `docs/40_HARDWARE/NANO_RP2040_CLOCK_PIN_STRATEGY.md`;
- `docs/50_SOFTWARE/HARDWARE_RESOURCE_OWNERSHIP.md`;
- `docs/50_SOFTWARE/RP2040_CAPTURE_ARCHITECTURE.md`;
- `docs/50_SOFTWARE/CX317_RX_ONLY_GNSS_RECEIVER_CONTRACT.md`;
- `docs/50_SOFTWARE/KNOWN_LIMITATIONS.md`;
- `docs/60_EXPERIMENTS/OTIS_PUBLIC_READINESS_PROGRAMMES/DISCIPLINED_10MHZ_OUTPUT_PROGRAMME.md`;
- the complete V2 cross-campaign study directory and its local V2 derived
  package;
- the GNSS baud-envelope programme, its finalized reviewed changes and its
  sealed physical result; and
- every prompt in this directory.

Do not infer the finalized UART revision, selected receiver baud or last
confirmed physical state from branch names or summaries. Resolve them from the
sealed GNSS package, reviewed report and exact Git identity.

## Entry preconditions

Before Prompt 01 changes code:

1. Confirm the GNSS baud-envelope run has stopped and has been acquired,
   analyzed, finalized, sealed and registered. If it remains active, stop this
   programme without accessing its serial owner, process tree or run package.
2. Validate the final GNSS terminal, selected operational baud, receiver final
   state, source revision, UART implementation identities and immutable package
   identity.
3. Establish a clean new `codex/` worktree/branch from the exact integration
   base that contains the reviewed UART changes and the committed V2 offline
   study. Do not implement on a stale campaign checkout or merge dirty user
   work implicitly.
4. Record the last confirmed applied DAC code and DAC epoch as provenance. Do
   not assume that old evidence proves the current physical state.
5. Create one durable programme ledger under a new ignored local run root and
   update it atomically at every authority, build, flash, wiring, measurement,
   controller-decision and terminal transition.

If an exact dependency is missing or contradictory, stop at
`integration_base_not_established`; do not recreate UART work by guesswork.

## Invariant topology and claims

- D14 is the sole authoritative PPS/reference input.
- D8 is the sole authoritative oscillator/count input.
- D9/GPIO21/GPOUT0 is a forwarded output only; it never becomes a steering
  witness or timing authority.
- D6/GPIO18 is a diagnostic forwarded-output monitor with zero control,
  validity, terminal and backpressure authority.
- D10 remains the optional external-event input. It is never a PPS witness or
  D9 monitor and cannot veto D14/D8 steering.
- The RP2040 continues to use its onboard platform clock. Do not reroute
  `clk_sys`, `clk_ref`, USB, PIO or DMA clocks.
- Raw D14/D8 and D9/D6 observations remain distinct from reconstructed,
  projected, adjusted and controlled quantities.
- A model or shadow failure fails that estimator, not physical reality.
- Missing or late telemetry is unknown, not clean, zero or unchanged.

The initial public output claim is a 3.3 V CMOS forwarded signal inside the
prospectively frozen high-impedance instrument/load envelope. It is not a
qualified 50-ohm laboratory source unless new external-buffer evidence supports
that separate interface.

## Authority by prompt

Prompt 01 authorizes source/document/profile changes, host and firmware tests,
firmware builds, binary inspection, no-hardware rehearsal and creation of a
non-effective candidate bundle. It authorizes no serial, flash, reset, wiring,
receiver, DAC or live-run action.

Prompt 02 authorizes physical work only when the initiating operator message
explicitly names or accepts the exact Prompt 01 bundle and its SHA-256. Without
that binding, perform read-only verification and ask one concise yes/no
authority question. Authority is limited to the frozen D9/D6 wiring, loads,
firmware, frequency-only FLL envelope, instruments, duration and stop
conditions, plus separately declared non-actuating D8-source-loss and
D14-reference-loss qualification segments. Those fault segments must disarm
control first and use an exact conflict-free wiring/procedure frozen in the
bundle. Hybrid and phase authority remain zero throughout Prompt 02.

Prompt 03 authorizes implementation, documentation, deterministic testing and
firmware compilation. It authorizes no bench access, flash, serial owner, DAC
write, physical arm or integrated live trial.

Prompt 04 authorizes exact-build verification and complete no-hardware
operational rehearsal. It must freeze, but not execute, the later 72-hour
integrated-trial proposal.

No prompt authorizes pushing, opening a pull request, deleting evidence,
weakening `.gitignore`, force-adding `runs/`, or automatic restoration to a
nominal DAC code.

## Programme sequence and gates

### Gate A — integration base and D9/D6 readiness

Prompt 01 must pass source/profile guards, affected current builds,
decision-relevant release verification, binary inspection and the complete
no-hardware output-path rehearsal before it freezes a physical candidate
bundle. Preflight alone is not rehearsal.

### Gate B — D9 waveform and frequency-only soak

Prompt 02 first qualifies waveform, load and non-interference. The sustained
frequency-only output soak may begin only if the waveform gate passes. A D6
monitor defect remains local when external D9 evidence is sufficient and the
monitor does not compromise D14/D8; shared-capture interference is a platform
defect and stops the run.

### Gate C — controller recommendation closure

After Gate B, choose exactly one:

- `cx322_unchanged_confirmed_by_d9_fll_output_gate` when direct D9 qualification
  and the frequency-only soak pass;
- `cx322_integration_blocked_by_d9_output_gate` when output or
  non-interference evidence fails or remains materially incomplete; or
- `controller_decision_invalid_due_to_identity_or_evidence_failure`.

This gate never selects a changed debt candidate and never retunes CX322.

### Gate D — operational-semantics implementation

Prompt 03 implements the frozen operational delta around the unchanged request
law. If Gate C blocked integration, the work may still be prepared and tested
as non-effective code, but no actionable integrated profile or promotion claim
may be created.

### Gate E — exact build and complete rehearsal

Prompt 04 must trace every decision-bearing handoff through the first dependent
consumer, test repeated transactions and fault overlaps, compile the exact
profile, and exercise the real host process topology using deterministic
no-hardware I/O. It then freezes a separate non-effective 72-hour authority
proposal and stops.

## Universal physical stop conditions

During Prompt 02, stop new actuation, preserve the last confirmed code and keep
the sole serial owner alive long enough to record abort delivery or bounded
delivery failure on:

- operator abort or loss of the independent abort path;
- reset, detach/re-enumeration outside the frozen recovery path, identity,
  firmware, contract, wiring, load or instrument mismatch;
- authoritative D14/D8 capture loss, invalidity, session discontinuity,
  queue corruption or impossible ordering, except the exact predeclared
  non-actuating source/reference-loss qualification segments; any unexpected
  loss or failure to requalify after those segments stops the programme;
- D9 configuration/readback contradiction, unexpected GPOUT source or divider,
  GPIO20/GPIO21 function contradiction, or output-validity ambiguity;
- D9 load or waveform outside the frozen electrical envelope;
- D6 monitor activity that compromises D14/D8 capture;
- unexpected DAC request, hybrid/phase influence, range/cadence/movement
  violation or unknown applied-code/DAC-epoch identity;
- transport obstruction, sole-owner loss, stale evidence or inability to
  finalize the package; or
- any attempt to change the frozen output source or use a fractional divider.

A D9 or D6 local failure is not evidence that canonical D14/D8 observations
before that failure were false. Judge acquisition, output qualification,
analysis, sealing and registration as distinct gates.

## Defect policy

For a narrow platform defect, preserve the failed attempt, add the cheapest
deterministic regression covering both sides of the missed handoff and its
first dependent consumer, rebuild the affected exact profile, repeat the
required operational rehearsal and return to the bounded programme. Do not
create a new characterization campaign or repeat unaffected physical evidence.

Do not weaken a frozen physical or scientific gate after observing evidence.
If a deterministic offline analyzer/finalizer fails after a complete immutable
acquisition, repair it and replay the exact evidence with both tool identities;
do not automatically repeat the physical acquisition.

## Completion

The bundle is complete only when Prompt 04 has produced:

- exact D9 output and D6 monitor terminals;
- a sealed frequency-only output-soak result;
- the non-retuned controller decision closure;
- the implemented operational state model and Python/C++ parity evidence;
- focused changed-semantics tests, affected exact build and full operational
  rehearsal;
- synchronized architecture, schema, telemetry, methodology, known-limitations
  and terminology documentation;
- a concise integration report separating facts, derived results, models and
  untested hypotheses; and
- one exact non-effective proposal for the later 72-hour integrated trial.

Stop there. Do not run the integrated trial without a new operator authority
decision.
