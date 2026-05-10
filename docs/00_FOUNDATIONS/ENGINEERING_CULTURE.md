# OTIS Engineering Culture

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
