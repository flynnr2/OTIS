# OTIS Adversarial Architecture and Evidence Review Prompt

Use this prompt from the root of the OTIS repository. This is an independent
architecture review, not an implementation campaign and not a request to make
the next live run pass.

---

## Prompt

You are conducting a detailed, adversarial, evidence-led architecture review
of OTIS as a complete scientific instrument. Review the firmware, both RP2040
cores, hardware timing fabric, host services, command and telemetry protocols,
supervisors, analyzers, evidence lifecycle, operational procedures, tests, git
history, and retained experimental results as one interacting system.

The decision this review must support is:

> Is the present OTIS architecture genuinely robust across its supported
> lifecycle, or does it only fail safely and pass under narrowly frozen,
> continuously supervised campaign conditions?

Do not begin by defending the current architecture or proposing repairs. First
try to falsify its claimed properties. A safe stop is not automatically robust
operation. A passing frozen campaign is not automatically architectural
validation. A large test count is not automatically concurrency evidence.

### Authority and safety boundary

This review is read-only except for writing the review report and deliberately
small review artifacts. You may inspect source, documentation, git history,
tests, manifests, reports, seals, and local `runs/` evidence. You may run
offline tests, analyzers, replay, static checks, and simulations that cannot
touch physical hardware.

Do not:

- flash firmware;
- open or manipulate physical serial devices;
- issue DAC, arm, abort, or other device commands;
- start a live campaign or qualification;
- alter authority, campaign state, evidence seals, or registered evidence;
- modify production code while conducting the review;
- silently repair a defect and then review the repaired system;
- force-add ignored evidence or weaken `.gitignore`.

If a useful check would require hardware or mutation, specify the smallest
bounded experiment needed and mark it `not executed`.

Read and obey `AGENTS.md`. Before evaluating timing semantics or architecture,
read the applicable documents under `docs/00_FOUNDATIONS/` completely. Treat
the repository state and retained evidence as primary evidence; do not rely on
filenames, summaries, final reports, or current comments alone.

If independent sub-agents are available, use them for genuinely independent
review tracks. At minimum assign separate tracks for:

1. firmware concurrency, ownership, scheduling, startup, and queue liveness;
2. host lifecycle, attachment, command authority, evidence handling, and
   campaign orchestration;
3. historical evidence, failed runs, git chronology, test escapes, and claim
   strength.

Require each track to try to disprove the architecture independently. The main
reviewer must inspect the primary evidence behind every material conclusion
and reconcile disagreements; do not merely concatenate sub-agent reports.

## Required review posture

Use these rules throughout:

- Separate observed facts, derived results, inferences, and hypotheses.
- State uncertainty and missing evidence explicitly.
- Prefer an identified counterexample over a broad assurance.
- Distinguish timing/metrology integrity, actuation safety, evidence integrity,
  liveness, availability, recoverability, and operability. Do not let strength
  in one category stand in for another.
- Distinguish a classic data race from starvation, ordering ambiguity,
  generation mismatch, ownership gaps, queue instability, stale state,
  incomplete recovery, and host/firmware contract disagreement.
- Treat repeated local fixes in the same area as possible evidence of a
  missing abstraction or invariant, not automatically as unrelated bugs.
- Treat comments and architecture documents as claims until implementation and
  evidence corroborate them.
- Treat a deterministic fail-static response to an ordinary supported event as
  a possible availability defect, even when it preserves safety.
- Do not characterize a failure as an unavoidable consequence of dual cores
  until a concrete mechanism rules out a simpler architectural cause.
- Do not strengthen a conclusion merely because a run was sealed, replayed, or
  described as final. Audit what that evidence actually exercised.

## Review questions

Answer all of the following.

### 1. Claimed architecture versus actual architecture

Construct an inventory of the architecture's claimed invariants and identify
their authoritative sources. Include at least:

- hardware capture establishes timing truth;
- Core 1 timing and control ownership;
- Core 0 service, transport, GNSS, and physical actuator ownership;
- host non-authority and host independence;
- immutable cross-core communication;
- bounded non-blocking behavior;
- exactly-one serial ownership;
- diagnostics not affecting timing or control correctness;
- preservation of canonical raw evidence;
- deterministic replay;
- fail-static actuation;
- startup, recovery, and qualification semantics.

For each claimed invariant, identify:

- the exact implementation mechanism;
- every component on which it depends;
- the verification that directly exercises it;
- counterevidence or scope limitations;
- whether the claim is proven, supported only within a bounded envelope,
  contradicted, or untested.

Explicitly identify differences between documented queue/resource inventories
and the queues/resources actually present in current code.

### 2. Complete lifecycle and state model

Reconstruct the actual distributed state machine spanning:

- RP2040 reset and both core startup orders;
- PIO/DMA initialization and ownership binding;
- receiver initialization and identity epochs;
- boot telemetry generation and drainage;
- host absent from power-on;
- late host attachment;
- host detachment and reattachment;
- serial congestion and partial frame transmission;
- campaign-to-campaign handoff;
- capture lease acquisition and loss;
- control qualification, arming, application, acknowledgement, and recovery;
- GNSS outage, parser failure, identity transition, and requalification;
- queue exhaustion and fail-static entry;
- clean shutdown, fault shutdown, and restart.

Do not infer a coherent state machine merely because individual flags exist.
Identify which transitions are atomic, which are generation-bound, which rely
on polling order or timing, and which can leave the host and firmware holding
different but individually valid views.

Produce at least one state/sequence diagram showing the intended lifecycle and
one showing a credible failing interleaving derived from actual code or
evidence.

### 3. Firmware concurrency and liveness

Audit all shared state and cross-core communication, including data that
crosses cores outside the declared queues. For every shared object identify:

- owner and permitted readers/writers;
- initialization order;
- memory-ordering mechanism;
- mutability after publication;
- reset behavior;
- rollover behavior;
- failure and recovery behavior.

Examine Core 0 as a cooperative scheduler. Enumerate every early return,
bounded drain, blocking or potentially slow operation, serial-frame ownership
path, sensor transaction, command path, and boot wait. Establish which services
have maximum-service-interval requirements and whether every control-flow path
meets them.

For every queue or ring, derive rather than assume:

- producer rate and maximum burst;
- consumer rate and maximum latency;
- permitted consumer absence;
- capacity margin;
- behavior at capacity;
- whether overflow is an integrity failure, expected disconnection behavior,
  or a policy choice;
- whether recovery requires a reboot;
- whether diagnostics or formatting contribute to exhaustion.

Pay special attention to exact burst-derived capacities. Determine whether an
apparently harmless new status field, diagnostic record, or formatter change
can alter startup or runtime liveness.

### 4. Host independence and attachment semantics

Test the architectural proposition:

> Firmware boots, measures, diagnoses, and maintains bounded internal state
> without a host. A host may attach, detach, and reattach without changing
> timing truth, receiver identity, estimator state, or control eligibility.

Determine separately what should happen to:

- live measurement;
- control authority;
- durable evidence capture;
- pre-attachment history;
- queue contents;
- loss counters;
- receiver and control epochs;
- status snapshot consistency.

Identify every path where lack of USB readiness, lack of serial ownership, or
lack of a host consumer can alter firmware health. Determine whether the host
can obtain one coherent current-state snapshot with sufficient boot identity,
configuration identity, generations, epochs, sequences, loss counters, and
authority to begin consuming from an explicit boundary.

Do not assume that continuous host drainage is compatible with firmware/host
independence. If continuous drainage is required, identify it as an explicit
architectural dependency and evaluate whether it is acceptable.

### 5. Diagnostics and evidence non-interference

Trace the complete path by which status, telemetry, diagnostic summaries,
formatted evidence, and raw observations are produced, queued, formatted,
transmitted, captured, analyzed, sealed, and registered.

Determine whether diagnostics can affect:

- Core 1 execution time or stack margin;
- queue availability for scientific or control records;
- Core 0 scheduling and GNSS drainage;
- serial ownership and command latency;
- startup completion;
- control eligibility;
- campaign success or failure.

Identify cases where a diagnostic intended to reveal a fault participates in
causing that fault. Distinguish canonical scientific evidence from redundant
host-facing presentation. Question whether non-droppable formatted serial
frames belong on a timing-to-service critical path.

### 6. Cross-surface authority and coherent snapshots

Compare firmware predicates with host readiness, pre-write, arm, analyzer, and
promotion predicates. For every action-capable transition determine whether:

- the host checks the same state the firmware will use;
- the checked records form one coherent generation;
- state can change between check and action;
- an impossible-to-qualify state is rejected before any write;
- a stale, partial, or mixed status response can appear healthy;
- the analyzer can reproduce the exact decision from retained evidence.

Look specifically for locally correct predicates whose composition is wrong.

### 7. Historical evidence-pattern review

Do not inspect only passing or final runs. Build a chronological failure and
repair table from git history, programme reports, retained runs, manifests,
analyzer outputs, and seals. Include unsuccessful rehearsals, aborted runs,
missing artifacts, platform stops, campaign escapes, and superseded bundles.

For each material event record:

- date and exact code/bundle identity where available;
- intended decision or qualification;
- observed outcome;
- earliest layer that could have caught it;
- actual layer that caught it;
- classification: scientific rejection, firmware defect, rehearsal-caught
  platform defect, campaign escape, evidence-pipeline defect, or irrelevant
  anomaly;
- immediate repair;
- underlying failure class;
- whether that class recurred;
- test or invariant added afterward;
- whether the repair changed the operational architecture and should have
  invalidated earlier evidence.

Actively look for these evidence patterns:

- repeated fixes to startup drainage, frame serialization, queue sizing,
  host attachment, acknowledgement order, or campaign finalization;
- the same failure class moving to a different surface;
- tests introduced only after physical or campaign escape;
- successful exact-bundle results being generalized beyond their workload;
- final reports emphasizing the passing artifact while minimizing the number
  and nature of failed predecessors;
- survivorship bias from missing, partial, or unsealed runs;
- review conclusions stronger than the experiments' stated scope;
- fixes that preserve safety but require increasingly exact choreography;
- operational procedures compensating for architectural coupling;
- evidence that diagnostics reveal failures reliably but the system does not
  recover from ordinary lifecycle events.

Quantify patterns where the evidence permits it. Do not use raw failure count
alone: distinguish productive scientific rejection from avoidable platform
and orchestration escapes.

### 8. Verification adequacy

Classify the relevant tests as:

- source-text or structural guard;
- unit/contract test;
- deterministic concurrency harness;
- replay;
- simulated operational rehearsal;
- real-I/O rehearsal;
- physical qualification.

For each major architectural claim, identify which class supports it and what
that class cannot prove. Specifically evaluate whether existing tests explore
scheduling variation or merely protect one known ordering.

Design, and where safe run, adversarial offline checks for:

- delayed Core 0 and delayed Core 1 startup;
- long boot/status output bursts;
- host absent indefinitely, then late attachment;
- repeated detach/reattach;
- GNSS bytes arriving during every early-return path;
- serial backpressure aligned with status and evidence bursts;
- queue capacity minus one, exact capacity, and capacity plus one;
- state changes between status snapshot and command;
- receiver discontinuity followed by complete requalification;
- sequence and timer rollover;
- interruption at each transaction phase;
- mixed-generation status records;
- loss of the normal command path while the independent abort path remains.

Use deterministic schedule exploration, model-based tests, or fault injection
where practical. Do not claim that an offline simulation proves physical
timing behavior.

### 9. Change sensitivity and architectural maturity

Identify changes that appear local but can invalidate system-level evidence,
including:

- adding a telemetry field;
- changing formatting or frame length;
- changing a drain budget;
- adding an early return;
- moving a service call;
- adding a queue or status response;
- changing host attachment delay;
- changing firmware boot duration;
- altering a qualification predicate;
- changing capture ownership or close behavior.

Assess whether the architecture is compositional: can a component change while
its declared contracts remain satisfied without requiring a new whole-system
campaign? If not, identify the hidden contracts.

## Required deliverable

Write the primary report to:

`docs/10_REFERENCE_ARCHITECTURE/OTIS_ADVERSARIAL_ARCHITECTURE_REVIEW.md`

Do not modify production behavior. If supplementary data is useful, write a
small machine-readable findings table beside the report and document its
provenance.

The report must contain:

1. **Executive verdict** — one of `robust`, `conditionally robust`, `fragile`,
   or `structurally unsound`, with separate verdicts for metrology integrity,
   actuation safety, liveness, host independence, startup determinism,
   recovery, diagnostics non-interference, evidence integrity, and campaign
   gating.
2. **Strongest falsifying evidence** — the smallest set of concrete examples
   that most directly challenge the architecture's claims.
3. **Claim-to-evidence matrix** — claimed invariant, implementation,
   supporting evidence, counterevidence, scope, and confidence.
4. **Actual lifecycle model** — including intended and failing sequences.
5. **Concurrency and queue analysis** — with explicit rate, burst, latency,
   capacity, ownership, and recovery assumptions.
6. **Historical failure-pattern analysis** — showing recurrence and where
   defects escaped the intended verification layer.
7. **Verification-gap matrix** — what current tests prove and do not prove.
8. **Findings ordered by architectural significance** — each with severity,
   concrete evidence, user/scientific consequence, affected invariant,
   confidence, and the smallest discriminating check.
9. **Alternative explanations considered** — especially where failures might
   be attributed to dual-core complexity, hardware behavior, host tooling, or
   campaign procedure.
10. **Minimum corrective architecture** — requirements and invariants only,
    not a speculative rewrite. Separate necessary corrections from optional
    improvements.
11. **Qualification plan** — the smallest finite set of offline, rehearsal,
    and physical checks needed to retire each material uncertainty.
12. **Residual uncertainty and stop conditions** — including what cannot be
    concluded from available evidence.

For every finding, cite exact repository paths and line numbers, commits,
artifact identities, or retained-run evidence. Avoid general statements such
as "there may be races" without naming a state, owner, transition, and
discriminating observation.

## Decision standard

Do not call the system robust merely because:

- timestamps originate in hardware;
- unsafe commands are rejected;
- faults are visible;
- queues are bounded;
- final campaign artifacts pass;
- replay matches firmware decisions;
- the latest known defect has a patch;
- the repository test suite passes.

Call a property robust only when its success does not depend on undocumented
choreography, ordinary supported lifecycle variation cannot invalidate it,
failure and recovery semantics are explicit, and evidence directly exercises
the relevant boundary.

End with a concise answer to these questions:

1. Which parts of OTIS are already trustworthy, and within what envelope?
2. Which parts are safe but operationally fragile?
3. Which claimed properties are currently contradicted by evidence?
4. What recurring failure classes indicate missing architectural invariants?
5. What must be true before another live campaign can provide decision-bearing
   scientific evidence rather than further platform discovery?

Do not implement repairs until the operator has reviewed this report and
explicitly authorized a corrective phase.

