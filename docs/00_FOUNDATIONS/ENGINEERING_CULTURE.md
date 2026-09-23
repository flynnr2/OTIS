# OTIS Engineering Culture

This document explains the human-facing rationale for OTIS engineering
culture. General preferences live in `~/.codex/AGENTS.md`; the repository-root
`AGENTS.md` contains the concise OTIS-specific operational instructions
automatically applied by Codex. A lasting preference change should update the
applicable instruction layer and this document when it affects both human
contributors and Codex.

OTIS aims to cultivate a culture of careful scientific instrumentation engineering.

The project values:

- deterministic behavior;
- explicit semantics;
- long-term maintainability;
- replayable experimentation;
- architectural clarity;
- scientifically serious observability.

---

# General Philosophy

OTIS should feel closer to:

- scientific instrumentation;
- Bell Labs engineering culture;
- HP/Tektronix application-note culture;
- metrology engineering;

than to:

- rapid feature-churn software projects;
- framework-centric architecture;
- hobbyist prototype culture.

The goal is not maximal complexity.

The goal is disciplined, comprehensible engineering.

---

# Simplicity Is an Operational Requirement

The finished instrument should be usable without understanding its engineering
campaign machinery. Power on, allow acquisition and discipline, use the output;
attach a host when recording or inspection is useful. This is the intended
experience, now implemented as an offline-verified candidate pending physical
qualification.

Be ruthless about accumulated scaffolding. A component must protect timing
correctness, preserve necessary evidence, or make an experiment easier to run.
Remove or replace it otherwise. Qualification manifests, private simulators,
runners and sealing belong outside the ordinary instrument runtime. Their
necessary checks should run automatically, not become operator bookkeeping.
One operation should have one owner and one deadline consumed by its nested
waits. Progress must mean an exact causal transition, not a busy observer.
Urgent abort and established ownership service must not disappear inside a
blocking diagnostic wait. Independent firmware safety expiry protects a
different boundary and must not be confused with those host deadlines.

Retired campaigns survive in their source revisions and retained evidence, not
in permanent compatibility layers. Sunk engineering effort is not a reason to
keep an approach. Fix demonstrated architectural duplication before another
qualification when that is the finite, safer route to a useful result.

---

# Explicit Over Clever

OTIS strongly prefers:

- explicit naming;
- explicit semantics;
- explicit state transitions;
- explicit clock domains;
- explicit telemetry provenance.

Cleverness that obscures instrumentation semantics is discouraged.

Readability and traceability matter.

---

# Determinism Matters

The project assumes:

- timing truth belongs to hardware capture;
- timestamps are scientific observations;
- interrupt latency is not an acceptable timestamp definition mechanism.

Architectural discussions should continuously ask:

"What actually establishes timing truth?"

---

# Development and Bench Exchange

The development Mac and bench Mac exchange prepared bundles, manifests, JSON,
checksums, prompts and completed evidence through `~/Documents/OTIS_DATA/`.
A bench handoff must name the actual shared delivery directory and a return
location there. Copy and verify the prepared files before reporting delivery;
a verified local copy does not prove synchronization has reached the other Mac.
Keep active acquisition in the repository's local `runs/` directory and copy
completed evidence without changing its records or seals. State access or
transfer failures explicitly rather than substituting an unshared local path.

---

# Replayability Is Sacred

Raw logs and telemetry are not debugging exhaust.

They are:

- experimental records;
- scientific artifacts;
- reproducibility mechanisms.

OTIS should preserve enough information to permit:

- offline reconstruction;
- independent verification;
- future reinterpretation.

That replayability should save bench time as well as support audit. If a
complete acquisition that is immutable, or content-addressed and unchanged,
later encounters a defect demonstrably confined to a deterministic offline
analyzer or finalizer, the correct response is a provenance-linked replay,
completion, or reanalysis—not another physical run. Preserve the original
failure and the old and new tool identities so the supersession is explicit. A
replay may correct implementation of a frozen criterion; it must not redefine
success after the evidence is seen.

Acquisition, live host orchestration, offline analysis, sealing, and
registration are separate gates. Failure in a downstream gate does not rewrite
the result of a completed upstream gate. Conversely, calling a defect
"host-side" is not sufficient to preserve a run: changes to capture, commands,
ownership, timing, segmentation, safety, plant interaction, or firmware-visible
behavior require repetition of the shortest affected operational gate.

Missing, partial, late, duplicated, or out-of-order telemetry is not evidence of
a clean, zero, unchanged, or causally ordered state. Those claims require direct
evidence or an explicit reconstruction with stated assumptions.

---

# Preflight, Rehearsal, and Qualification Are Different

OTIS uses three distinct verification gates:

- a preflight checks configuration, identity, authority, and structural
  invariants without I/O;
- a short operational-path rehearsal executes the complete host workflow,
  including commands, acknowledgements, fault handling, capture boundaries,
  analysis, sealing, and registration, using acceleration or replay where long
  timing boundaries are not themselves under test; and
- a physical qualification supplies the real-duration firmware, plant, and
  measurement evidence needed for a decision.

A long bench run should not be where ordinary host integration failures are
first discovered. Conversely, a short rehearsal must not be mistaken for
scientific evidence about real duration or plant behavior.

An acknowledgement is a local fact, not an end-to-end fact. When a setup,
application, authority, session, or epoch crosses cores or processes, the
verification claim is complete only when the exact identity and ordering are
observed at every decision-bearing consumer. A coherent host fixture proves
the host path against that fixture; it does not prove that firmware actually
propagates the corresponding state between cores. Rehearsal reports should say
which real boundaries they exercise, and focused deterministic regressions
should cover the boundaries they simulate.

An abort submission is likewise intent, not delivery. An aborting terminal must
retain the sole serial owner until the priority abort is recorded as sent, or a
bounded delivery failure is recorded. Closing capture merely because the
supervisor has published its terminal state can otherwise race the abort queue
and turn an otherwise valid finite endpoint into an avoidable platform escape.

---

# Deliver the Instrument

The intended instrument should eventually discipline its oscillator and
provide its output without requiring a host to run the control loop. A host
attaches to an instrument that may already be acquiring, steering, held, or
faulted; it discovers that state before requesting authority or a transition.
Connecting a recorder is not an implicit reset or a claim that the actuator
starts at a known code. Historical acknowledged campaigns retain their original
contracts; they do not impose leases on the autonomous runtime.

The accepted implementation uses autonomous hybrid discipline as the
boot default, with explicit serial-selected operating modes under the same
firmware owner. A basic host records; connecting or closing that recorder does
not change operating mode. The [consolidated replacement proposal](../50_SOFTWARE/HOST_CONTROL_REPLACEMENT_PROPOSAL.md)
brings this work forward and supersedes the proposed mandatory host decision
worker. Offline implementation and physical qualification are separate gates;
ordinary use requires no campaign leases, per-correction host acknowledgements
or Codex. The detailed fault mapping still needs its reserved operator review.

Compact serial evidence and full replay are different reporting contracts,
not different owners of timing or control. Characterization and future output
division should use the same instrument services with explicit policies and
resource ownership. Service-latency diagnostics help demonstrate that service
work stays isolated from hardware capture, but cannot establish latch-to-ISR
delay unless both endpoints and their common clock relation are actually
observable.

The deliverable is working firmware, a working operational host path, and
reproducible evidence sufficient to support the next decision. Test harnesses
and campaign scaffolding are supporting infrastructure, not parallel products.
They should be hardened when they protect the instrument outcome, make evidence
credible, or prevent a demonstrated escape from recurring. They should not grow
merely to make the verification machinery more elaborate.

OTIS prefers ambitious but bounded programmes: broad in the interfaces,
state transitions, and failure modes they exercise, while finite in authority,
duration, and cost. Accelerated time, replay, fault injection, and short
complete-path rehearsals should expose ordinary integration failures before an
expensive physical qualification. Narrow tests are valuable for discriminating
and localizing a known defect; a collection of isolated micro-tests is not a
substitute for an outcome-bearing end-to-end result.

---

# Recover Defects Without Creating Mini-Campaigns

A campaign stop should teach us something concrete and then move us back toward
the decision the campaign exists to make. A narrow repair is not an invitation
to construct a second qualification programme around the defect.

The normal recovery sequence is:

1. preserve the failed evidence and identify the changed risk surface;
2. add the cheapest deterministic regression that directly covers the defect;
3. rebuild the exact affected profile;
4. exercise the existing operational-path rehearsal; and
5. resume the bounded, guarded experiment.

For a handoff escape, "directly covers" means exercising both sides of the
handoff and at least the first downstream decision that depends on it. Merely
checking that the producer accepted or logged the transition recreates the
same blind spot.

Another physical qualification is justified only when its outcome could change
safety, scientific validity, or the next decision. It must also have a
deterministic stimulus. Requiring a rare diagnostic to occur spontaneously is
not meaningful qualification: if it does not occur, nothing has been learned
about the repair. Formatter, framing, parser, and contract repairs are usually
better covered with deterministic source checks, fixtures, or retained-evidence
replay, while the live path's pre-actuation stop remains the integration guard.

Artifact identity and semantic invalidation are distinct. A new firmware hash
must be bound exactly to its build and candidate, but it does not automatically
erase physical, topology, or scientific evidence whose relevant inputs did not
change. Repeat the shortest affected gate and explicitly reuse the rest.

Prefer the actual frozen rehearsal and campaign runner. A temporary helper,
when truly necessary, should have its imports, configuration, and no-I/O path
checked before it consumes a flash, reset, bench interval, or acquisition.
Complete only the authority and provenance bookkeeping needed to execute
safely; write the broader narrative after the decision-bearing gate when the
raw evidence and identities can be preserved without blocking it.

Once the direct regression, affected build, and required rehearsal pass, stop
expanding the validation tree. Returning promptly to the guarded experiment is
part of rigorous engineering, not a relaxation of it.

---

# DRY, But Not Abstract For Its Own Sake

OTIS values DRY principles strongly.

Repeated:
- protocol semantics;
- validation logic;
- telemetry definitions;
- timing transforms;
- deadlines, baselines, counters, and verdict predicates;

should be treated as architectural smells.

Operational semantics should come from one frozen contract or manifest wherever
practical. A runner, supervisor, analyzer, recovery tool, and test harness must
not each carry a subtly different version of the same rule.

However:

abstraction is not automatically improvement.

Avoid abstractions that:
- obscure instrumentation semantics;
- increase hidden behavior;
- create framework complexity without clear payoff.

---

# Engineered Enough

OTIS seeks systems that are:

- robust enough;
- explicit enough;
- maintainable enough;
- thoughtful enough.

The project intentionally avoids both:

- under-engineered fragility;
- over-engineered architecture astronautics.

---

# Thoughtfulness Over Speed

OTIS generally prefers:

- careful architectural reasoning;
- edge-case consideration;
- deterministic semantics;
- explicit assumptions;

over:

- rapid implementation;
- premature optimization;
- speculative extensibility.

---

# Unknowns Should Be Admitted

OTIS should explicitly document:

- unresolved questions;
- measurement uncertainty;
- architectural tradeoffs;
- limitations;
- assumptions.

Scientific instrumentation becomes stronger when uncertainty is acknowledged clearly.

---

# Modularity Must Not Dilute Semantics

OTIS intends to evolve toward a broader ecosystem.

However, modularity must not compromise:

- timing semantics;
- deterministic behavior;
- replayability;
- provenance;
- instrumentation rigor.

Architectural clarity takes priority over maximal configurability.

## Operation without an available reviewer

An explicitly authorized unattended experiment runs under the firmware owner
with optional local recording and monitoring, without a Codex session or model
budget. Routine decisions and known
causal recovery follow a frozen contract. Escalation combines an immediate
predefined response with a retained request for later review; silence is never
approval or permission to abort. An unresolved decision-bearing discrepancy
holds new authority while preserving capture, exact pending-phase identity and
the last confirmed code. Firmware retains independent bounded fail-static
behavior. A monitor observes and records transitions but cannot command, restart
or terminate the instrument. Rehearsal must leave a review request unanswered
and exercise continued capture and internal application service across the
relevant decision boundaries.

Operational elapsed duration and accepted D14/D8 measurement coverage are
distinct results. A 72-hour observation endpoint does not claim 72 hours of
qualified measurement or uninterrupted steering. An explicitly selected finite
firmware operation owns its stop deadline; ordinary recording duration does not
stop steering. Unresolved endpoint evidence remains explicit. Publication or
offline analysis failure does not erase
otherwise valid acquisition.
