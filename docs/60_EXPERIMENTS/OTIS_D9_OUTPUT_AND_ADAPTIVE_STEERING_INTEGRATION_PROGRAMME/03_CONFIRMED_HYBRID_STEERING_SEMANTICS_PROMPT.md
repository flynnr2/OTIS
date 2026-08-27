# Prompt 03: Confirmed Hybrid-Steering Operational Semantics

Execute this prompt only after Prompt 02 has finalized and sealed its physical
evidence and controller-decision closure.

This is an implementation and deterministic-verification task. It authorizes
no bench access, flash, reset, serial owner, receiver command, DAC write,
control arm or live run.

## Entry decision

Accept exactly one Prompt 02 controller terminal:

- `cx322_unchanged_confirmed_by_d9_fll_output_gate`;
- `cx322_integration_blocked_by_d9_output_gate`; or
- `controller_decision_invalid_due_to_identity_or_evidence_failure`.

If the decision is invalid, stop without implementation. If integration is
blocked by a valid D9 result, the operational semantics below may still be
implemented and tested as non-effective safety architecture, but no actionable
integrated profile or promotion claim may be created.

If confirmed, integrate the unchanged CX322 coherent FLL/PLL request law. Do
not adopt either rejected tagged-correction-debt candidate, add same-sign
persistence to the request law, refit the failed static model or alter a
request threshold after seeing D9 evidence.

The offline `adaptive_steering_offline.py` primitives are executable reference
semantics and test oracles. They are not a firmware module to copy blindly and
do not confer authority.

## Controlled objective

Keep the CX317 VCOCXO D8 output as close to nominal 10 MHz relative to qualified
D14 PPS as the retained estimator resolution and bounded actuator policy permit,
while reducing same-epoch D14-relative phase movement without unacceptable
frequency degradation or actuator churn.

Concretely:

- retain the recorded CX322 selected-600 frequency estimator and request math;
- retain the selected relative-phase estimator and phase sign convention;
- use the FLL term to reject current qualified frequency error;
- allow the slower PLL term to request only its existing bounded temporary
  frequency bias;
- combine both through one existing request/transaction path; and
- retain cadence, settling, range, step, acknowledgement, response and movement
  bounds.

Do not optimize instantaneous one-second count error, stationary DAC code,
unobserved oscillator temperature, UTC alignment or an unmeasured output phase.

## Phase 1 — freeze the minimal operational delta

Create one reviewed implementation contract that binds:

- exact unchanged CX322 host and firmware request-law identities;
- selected frequency and phase estimator identities/configurations;
- exact D14/D8 evidence and phase frontiers consumed by each decision;
- controller states, transition events, owners and deadlines;
- current and new telemetry/schema versions and backward-compatibility policy;
- D9 output contract identity and zero input authority;
- the D6 and D10 local-failure invariants;
- optional shadow identity, bounded input/output queues and zero authority;
- every host, firmware, replay, analyzer, supervisor, sealer and profile file in
  the changed bundle; and
- non-effective authority until the later integrated-trial decision.

Freeze two independent FLL-only low-efficiency episodes as the threshold for
`LOW_EFFICIENCY_INHIBIT`. Each episode must be a completed, identity-bound,
actually applied FLL-only transaction with its declared response/exposure
window. Do not count censored, rejected, expired, unapplied, phase-material or
overlapping episodes.

The unchanged CX322 request law has no newly selected tagged correction debt.
Do not introduce one. Where the architecture says to discard PLL-origin debt,
the unchanged implementation discards any uncommitted/cached phase-derived
request contribution and records `not_applicable_no_committed_pll_debt` when no
such state exists.

## Phase 2 — separate measurement health, metadata qualification and output

Refactor the existing paths rather than creating another controller or
supervisor.

Represent separately:

- `d14_d8_measurement_healthy` — authoritative capture/count evidence;
- `gnss_metadata_qualified` and an exact local reason/sequence/age — receiver
  qualification evidence from the receiver that supplies D14;
- `control_rearm_eligible` — the causal combination needed for a new request;
- `phase_evidence_qualified` and exact phase epoch/frontier;
- `d9_output_valid` and output reason — delivered-output status, never a
  steering witness; and
- optional D6/D10/shadow status — zero-authority local evidence.

GNSS serial metadata must never replace D14. D9/D6 must never enter estimator
truth. A D9 invalidity may stop a future delivered-output trial while canonical
D14/D8 measurement and controller diagnostics remain correctly classified.

## Phase 3 — implement transaction-aware `GNSS_METADATA_HOLD`

Implement these exact ownership cases around the existing Core 1 request
producer and Core 0 actuator owner:

1. **No request created / unused arm:** Core 1 consumes or withdraws the exact
   unused arm, records its identity and enters metadata hold at the last
   confirmed applied code.
2. **Private request not durably released:** Core 1 is sole owner, records
   `private_unreleased_withdrawn`, inhibits new requests and enters hold. Core 0
   must never observe that request.
3. **Durably released, not accepted:** Core 0 is sole outcome owner. Core 1 may
   neither withdraw, reuse nor replace the identity. Core 0 emits exactly one
   accepted, rejected or bounded-expiry outcome.
4. **Rejected/expired:** discard the pending proposal, leave committed
   controller state unchanged and enter hold.
5. **Acceptance wins:** complete the exact application, observe applied code and
   DAC epoch through the first dependent consumer, retain the required D14/D8
   response and then remain held. Metadata loss may not undo acceptance.
6. **Application complete, response pending:** continue a healthy D14/D8
   response observation and classification but inhibit rearm.
7. **No authoritative outcome by the exact deadline or contradictory identity:**
   enter `ACTUATOR_PROVENANCE_FAIL_STATIC`. Never infer rejection, application
   or unchanged code from silence.

During `GNSS_METADATA_HOLD`:

- continue D14/D8 capture, selected estimation, relative-phase accumulation,
  canonical telemetry and response evidence;
- preserve valid estimator and phase history;
- hold the last confirmed code and issue no new request;
- freeze request persistence/candidate state rather than advancing it on held
  intervals; and
- report hold duration and lost eligible opportunities in exact domains.

Rearm requires fresh qualified metadata from the same receiver followed by one
complete causally later D14/D8 observation with exact session, applied-code,
DAC-epoch and estimator frontier. Snapshot recency alone is insufficient.

Loss, invalidity or contradiction of authoritative D14/D8 evidence remains a
separate reference/capture condition. Unknown actuator state remains fail-static.
Do not call metadata hold `holdover`.

## Phase 4 — phase degradation and low-efficiency attribution

Phase evidence failure uses the same outstanding-transaction ownership order.
After the transaction and required response resolve:

- discard only the uncommitted/cached PLL contribution;
- preserve healthy FLL evidence and state;
- enter `PHASE_DEGRADED_FLL`;
- prohibit a phase-derived request while degraded; and
- open a new explicit phase epoch after requalification. Numeric reconvergence
  cannot rejoin the old epoch.

Attribute low efficiency from the request actually applied:

- compute and record the exact frequency-only integer request and the actual
  combined integer request at the same frontier;
- mark an application phase-material only when those integer requests differ;
- a phase-material low-efficiency episode disables the PLL contribution after
  the outstanding application/first-consumer/response sequence and falls back
  to the unchanged FLL path;
- one completed FLL-only low-efficiency episode records local degradation and
  remains measured; and
- the second independent completed FLL-only low-efficiency episode enters
  `LOW_EFFICIENCY_INHIBIT`, retains the last confirmed code and continues
  measurement with automatic actuation disabled.

Low efficiency is not a D14/D8 measurement terminal. Recovery from static
inhibit requires explicit future operator authority; it is not automatic retry
or silent state reset.

## Phase 5 — optional shadow and D10/D6 isolation

Use an existing suitable optional estimator if one is already reviewed. If no
such estimator exists, implement only the smallest bounded zero-authority
shadow interface and deterministic reference producer needed to establish
containment; do not create a predictive-model project.

The shadow receives a bounded copy of canonical evidence. It has:

- no controller, transaction, abort, terminal, serial-owner or queue-health
  capability;
- bounded nonblocking input and additive output queues;
- explicit input-drop, output-drop, stale, killed, stalled, corrupt, rejected
  and model-infeasible status; and
- source, configuration and causal frontier identity on every output.

Enabling, disabling, stalling, killing, delaying or corrupting the shadow must
leave canonical records, baseline CX322 decisions, applied DAC transactions,
D9 state and all non-shadow terminals identical.

D10 absence, noise, invalidity, overflow or queue failure remains D10-local.
D6 failure remains monitor-local. If either compromises D14/D8 capture, classify
and repair a platform-isolation defect; do not turn the optional input into a
health veto.

## Phase 6 — telemetry and replay

Version the existing schemas only where decision-bearing fields are absent.
Every relevant record must bind:

- run/build/profile/policy/output-contract identities;
- capture session, evidence sequence/frontier and exact clock domain;
- D14/D8 health separately from GNSS metadata state;
- metadata sequence, age, hold entry, requalification and post-requalification
  observation frontier;
- request release state, owner, request/decision/authorization sequence, nonce,
  outcome, outcome sequence and deadline domain;
- accepted/applied code, DAC epoch, application and first-consumer sequence;
- response support, measurement health, class and rearm inhibition;
- exact FLL and PLL component requests and phase-material attribution;
- low-efficiency exposure, path, net movement and episode identity;
- phase degraded/new-epoch and static-inhibit reasons;
- D9/D6/D10 and shadow local status without upstream authority; and
- missing, stale, censored and contradictory states explicitly.

Extend host parser, replay, analyzer, supervisor, sealer and source guards in the
same change. Preserve historical readers at their historical revision. Do not
reinterpret missing fields in old packages as clean current semantics.

## Phase 7 — deterministic tests and Python/C++ parity

Add focused tests covering at least:

- exact unchanged CX322 own-law replay before and after the operational delta;
- every metadata-loss request ownership state, including acceptance races,
  repeated requests, rejection, expiry, first consumer and response pending;
- stale-but-coherent snapshots versus contradictory identity and deadline
  expiry;
- metadata requalification requiring a wholly later D14/D8 observation;
- phase loss with no transaction and at every transaction phase;
- new phase epoch and prevention of numeric rejoin;
- phase-material attribution using exact integer request comparison;
- phase-material low efficiency to FLL fallback;
- first and second independent FLL-only low-efficiency episodes and static
  inhibit;
- no correction debt introduced into unchanged CX322 request mathematics;
- shadow killed/stalled/delayed/corrupt/rejected/infeasible invariance;
- D6 and D10 local fault/overflow isolation;
- D9 invalidity separated from measurement truth and trial terminal;
- request/acknowledgement/application/DAC-epoch and first-consumer identity;
- wrap-safe deadlines in their declared domain;
- queue overlap, saturation, repeated events and legal combined flags; and
- exact host/firmware state, request, reason and telemetry parity.

Use deterministic firmware/native integration fixtures for cross-core handoff
semantics. A host-only coherent fixture cannot prove the firmware queue or first
consumer boundary. No physical fault must occur spontaneously to pass this gate.

## Deliverables and terminal

Deliver:

- minimal implementation contract and semantic-change ledger;
- firmware and host changes in the existing parity/transaction paths;
- versioned telemetry/schema/parser/replay/analyzer updates;
- exact unchanged-law parity corpus and fault matrix;
- focused test results and affected-profile build readiness;
- updated architecture, resource, methodology, terminology and known-limitations
  documents; and
- a concise list of boundaries still requiring Prompt 04 rehearsal or a later
  physical trial.

Choose exactly one terminal:

- `confirmed_hybrid_operational_semantics_implemented_non_effective`;
- `operational_semantics_implemented_promotion_blocked_by_d9_gate`;
- `implementation_blocked_by_identity_or_contract_mismatch`; or
- `implementation_invalid_due_to_parity_or_safety_failure`.

Do not flash, arm or run the integrated controller. Hand the exact changed tree
to Prompt 04.
