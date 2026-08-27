# Prompt 04: Exact Build, Operational Rehearsal and Trial Handoff

Execute this prompt after Prompt 03 reaches one of its implementation-complete
terminals. This prompt authorizes compilation and no-hardware rehearsal only.
It does not authorize serial-device access, flashing, reset, wiring, receiver
commands, DAC writes, controller arm or a physical integrated trial.

## Goal

Prove that the exact confirmed integration profile compiles every required
field and state, that host and firmware semantics agree, and that the complete
producer-to-consumer operational path survives the decision-bearing handoffs
and fault overlaps before scarce physical time is requested.

If Prompt 02 blocked integration, verify the non-effective implementation but
do not create a live-trial authority proposal. If Prompt 02 confirmed unchanged
CX322 and Prompt 03 passed, freeze one exact non-effective bundle for a later
separately authorized 72-hour integrated hybrid/output trial.

## Phase 1 — bind the exact candidate

Create one immutable candidate manifest containing:

- clean source branch/revision and all semantic parents;
- sealed GNSS/UART package, V2 study, D9 waveform and frequency-only soak
  identities;
- exact D9 output, D6 monitor and qualified load contracts;
- unchanged CX322 request-law, selected frequency estimator, phase estimator,
  response classifier and operational-state identities;
- all changed firmware, profile, schema, host, analyzer, supervisor, monitor,
  sealer and registration files;
- build system, Arduino/Pico core, compiler, libraries, compile definitions and
  expected binary identity inputs;
- command envelope, acknowledgements, deadlines, abort, stop conditions and
  final-state semantics; and
- the exact test, rehearsal and future evidence destinations.

Reject an uncommitted dependency or unexplained dirty change. Do not silently
rebind the candidate after testing begins.

## Phase 2 — proportionate verification

Run verification according to the changed risk surface:

1. focused unit, contract, replay, source-guard and native parity tests during
   repair;
2. affected integration/analyzer/replay tests and current exact profiles;
3. the applicable Release gate because shared clock/GPIO ownership, protocol,
   telemetry, cross-core transaction and safety semantics changed; and
4. supported/expected-failure build profiles that prove D9, D6, metadata-hold,
   hybrid authority and shadow features cannot leak into unselected builds.

Do not use a broad build matrix as a substitute for the exact profile. Do not
repeat unrelated historical compatibility tests whose packages are not part of
the current product matrix.

Require deterministic coverage of:

- every Request 01 D9/D6 contract/source guard;
- unchanged CX322 law and exact host/firmware request parity;
- metadata hold at unused-arm, private-unreleased, released-pending,
  accepted/application, first-consumer and response-pending boundaries;
- rejection, expiry, deadline, duplicate and contradictory outcomes;
- phase loss/new epoch/FLL fallback and low-efficiency static inhibit;
- shadow, D6 and D10 fault containment;
- D9 output invalidity separated from D14/D8 measurement truth;
- legal counter rollover and forbidden cross-domain comparisons;
- queue/event overlaps, repeated requests and first dependent consumers;
- terminal, abort, finalization and replay semantics; and
- exact package/source/tool/artifact identities.

After a narrow defect, add the smallest direct regression, rebuild the affected
profile and return to the rehearsal. Do not expand into a new campaign.

## Phase 3 — exact firmware build and binary proof

Build the exact future integrated profile and prove from source, configuration,
build logs, ELF/UF2 and emitted binary that it contains and propagates:

- D14/D8 measurement fields and selected estimators;
- D9 GPIN0/GPOUT0 divide-by-one configuration/readback and qualified contract;
- D6 monitor resource/status with zero authority;
- unchanged CX322 FLL/PLL request law and exact component attribution;
- all operational states and request-release/outcome fields;
- GNSS metadata qualification separated from D14/D8 health;
- phase fallback, low-efficiency inhibit and requalification fields;
- bounded shadow identity/status/drop counters with no authority path;
- exact transaction, first-consumer and response identities;
- independent abort and bounded delivery evidence; and
- selected operational receiver baud and finalized UART service path.

Also prove absence of:

- the rejected correction-debt/persistence request-law candidates;
- runtime D9 source/pin selection, fractional divider or arbitrary register
  command;
- D6/D10/shadow consumers in measurement validity or control eligibility;
- metadata-only run terminal in the otherwise healthy D14/D8 case;
- a second physical I2C actuator call site or ownerless request interval;
- system/reference/peripheral clock rerouting; and
- authority enabled by default or without the later exact bundle.

A successful fixture cannot prove a field compiled into this profile; inspect
the exact source guards, build output and binary.

## Phase 4 — complete no-hardware operational-path rehearsal

Use the real capture, sole-owner serial carrier, supervisor, shadow process,
monitor, logging, command, analyzer, sealing, content snapshot and temporary
registration programs. Use deterministic PTY/pseudo-device I/O, accelerated
time and retained-evidence replay where physical signals would otherwise be
required.

The rehearsal must:

1. establish continuous capture and exact identity before producers can
   overflow;
2. start every supervisor, monitor and bounded shadow consumer;
3. verify the expected boot/status/output/controller transcript;
4. issue repeated representative requests and trace acceptance, application,
   applied code/DAC epoch, first dependent consumer and response;
5. exercise periodic, settling, cadence, metadata freshness, request expiry,
   response and stop boundaries under accelerated exact-counter time;
6. lose metadata at every request ownership state and verify the exact owner,
   outcome and hold ordering;
7. requalify with fresh metadata but a stale snapshot, then with a complete
   causally later D14/D8 observation;
8. inject phase loss at every transaction state, prove FLL fallback and a new
   phase epoch without numeric rejoin;
9. inject phase-material low efficiency followed by two independent FLL-only
   low-efficiency episodes and prove static inhibit with continuing measurement;
10. kill, stall, delay, corrupt and reject the shadow while proving baseline
    decision/application/terminal identity remains exact;
11. inject D6 and D10 absence/noise/overflow/queue failure without D14/D8 or
    controller mutation;
12. inject D9 status invalidity and prove the delivered-output trial terminal
    is distinct from canonical measurement health;
13. obstruct normal transport, submit the independent abort and keep the sole
    owner alive until capture records sent or bounded delivery failure;
14. rotate/transfer ownership atomically with no ownerless interval;
15. stop cleanly and run the actual analyzer, sealer, content snapshot and
    temporary registration; and
16. replay the exact chronology and compare every host/firmware state, reason,
    request and terminal.

Cover all legal overlaps and repetitions that can reach authority or a terminal;
do not assume flags or states are mutually exclusive because they have
different names.

## Rehearsal claim boundary

Report explicitly which real boundaries were exercised. The rehearsal may
prove:

- actual host process topology and sole-owner handoff;
- parser, schema, replay, analyzer, sealing and registration integration;
- deterministic firmware/native state and cross-core queue contracts; and
- exact deadline and fault semantics under controlled I/O.

It does not prove:

- physical Core 0/Core 1 propagation timing on the board;
- physical DAC application or VCOCXO response;
- D9 waveform, load or non-interference beyond the already sealed Prompt 02
  evidence;
- receiver/UART electrical behavior beyond the sealed GNSS result; or
- 72-hour hybrid performance.

Retain the live pre-actuation identity/output/readback gate for the remaining
physical integration risk.

## Phase 5 — freeze the later integrated-trial proposal

Only when D9/FLL confirmed unchanged CX322 and all verification/rehearsal gates
pass, create one non-effective proposal for a later 72-hour trial. Freeze before
requesting authority:

- exact firmware/profile/binary and host tool identities;
- exact unchanged CX322 coherent FLL/PLL law and operational state contract;
- D9 continuously enabled at integer divide one under the exact qualified load;
- D6 monitor configuration and its zero-authority failure behavior;
- selected receiver baud and UART configuration;
- starting-code provenance query, with no nominal restoration;
- 72 measurement-qualified hours, qualification deadline and absolute
  wall-clock ceiling;
- exact application, movement, step, range, cadence, settling, response,
  reversal, hold and inhibit budgets inherited or narrowed from retained
  evidence;
- expected D14/D8, D9, D6, metadata, phase, controller, shadow, resource and
  service telemetry;
- independent abort, finalization and safe final-state behavior;
- monitoring cadence and milestone schedule; and
- all scientific, platform, output and operator stop conditions.

The future trial must judge:

- selected-600 D14-relative frequency RMS, tails and band occupancy;
- unjoined D14-relative phase slope, endpoint movement and excursion;
- application response, recovery, holds/degraded residence and lost
  opportunities;
- applications, absolute DAC path, net movement and reversals per named
  measurement/control duration;
- natural reversals and low-efficiency behavior;
- shadow containment and queue/service isolation; and
- delivered D9 continuity and non-interference under the qualified load.

It is operating evidence for the confirmed hybrid law and integrated output.
It is not a repetition of the already qualified FLL/PLL plumbing, UART link or
D9 waveform campaign.

Do not set physical authority true and do not create the live run directory.
Ask the operator separately to authorize the exact proposal by identity.

## Deliverables and terminal

Produce:

- verification matrix and exact commands/results;
- exact build logs, binary identities and source/binary guards;
- complete rehearsal package, analysis, seal and temporary registration;
- end-to-end handoff ledger through every first dependent consumer;
- known remaining physical boundaries and pre-actuation checks;
- synchronized architecture, telemetry, profile, methodology, operational and
  known-limitations documentation;
- final integration readiness report; and
- when permitted by the prior gates, the exact non-effective 72-hour proposal.

Choose exactly one terminal:

- `integrated_hybrid_output_bundle_ready_for_separate_72h_authority`;
- `non_effective_semantics_verified_promotion_blocked_by_d9_gate`;
- `exact_profile_build_or_field_propagation_failed`;
- `operational_rehearsal_failed`; or
- `integration_readiness_invalid_due_to_identity_or_evidence_failure`.

Stop after reporting that terminal. Do not begin the 72-hour trial.
