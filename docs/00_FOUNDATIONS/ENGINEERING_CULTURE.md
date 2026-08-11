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
sealed acquisition is complete and a later defect is demonstrably confined to
a deterministic offline analyzer, the correct response is a provenance-linked
reanalysis—not another physical run. Preserve both verdicts and their analyzer
identities so the supersession is explicit.

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

---

# DRY, But Not Abstract For Its Own Sake

OTIS values DRY principles strongly.

Repeated:
- protocol semantics;
- validation logic;
- telemetry definitions;
- timing transforms;

should be treated as architectural smells.

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
