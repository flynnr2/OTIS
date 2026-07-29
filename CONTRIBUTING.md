# Contributing to OTIS

Thank you for your interest in contributing to OTIS.

OTIS is intended to become a scientifically serious timing instrumentation platform. Contributions should therefore prioritize:

- determinism;
- reproducibility;
- explicit semantics;
- observability;
- long-term maintainability.

OTIS values careful engineering over rapid feature accumulation.

---

# Contribution Philosophy

Contributors are encouraged to:

- document assumptions explicitly;
- preserve architectural clarity;
- separate conceptual and implementation concerns;
- prefer deterministic behavior over convenience;
- preserve replayability and telemetry integrity.

OTIS strongly prefers:

- explicit over clever;
- engineered-enough over under- or over-engineered;
- thoughtful edge-case handling over optimistic assumptions.

---

# Engineering Expectations

## DRY Matters

Repetition should be treated as a design smell.

Contributors should aggressively look for:
- duplicated logic;
- duplicated schemas;
- duplicated validation paths;
- duplicated protocol semantics.

However, DRY should not become abstraction theatre.

Avoid abstractions that:
- obscure timing semantics;
- reduce observability;
- increase cognitive load without clear benefit.

## Engineered Enough

OTIS seeks systems that are:
- robust;
- understandable;
- maintainable;
- appropriately explicit.

Avoid:
- fragile hacks;
- premature frameworks;
- excessive indirection;
- speculative generalization.

## Determinism First

The CPU must not define timing truth.

Timing correctness, timestamp provenance, and deterministic capture are higher priorities than:
- throughput;
- convenience;
- feature count.

## Replayability and Provenance

Telemetry and logs are primary scientific artifacts.

Changes affecting:
- schemas;
- timing semantics;
- timestamp provenance;
- replayability;
- capture ordering;
- clock domains;

must be documented carefully.

## Respect `.gitignore`

The repository `.gitignore` is an architectural storage boundary, not a
suggestion. Contributors and automation must respect it at all times. Do not
force-add ignored files, use lower-level Git commands to bypass ignore rules,
or temporarily weaken the rules merely to stage an artifact.

The entire `runs/` tree is reserved for locally stored experimental evidence,
including raw captures, manifests, evidence snapshots, generated reports, and
operator material. Keeping that evidence local prevents large and
continuously generated run packages from clogging repository history.

Documentation may cite `runs/...` paths as local provenance. Such citations do
not make those files repository assets or imply that they are available in a
fresh clone. Preserve and back up important local runs according to the
operator's evidence-retention practice. Commit only the compact outputs that
belong in the shared source tree, such as reviewed result summaries, versioned
plant models, schemas, contracts, and deliberately constructed small fixtures
outside `runs/`.

If a future use case genuinely requires tracking a currently ignored class of
file, change the policy and `.gitignore` explicitly in a reviewed pull request
before adding the files. Do not create one-off exceptions.

---

# Documentation Expectations

Substantial changes should include corresponding updates to:

- architectural documentation;
- telemetry semantics;
- schema/version notes;
- experimental methodology;
- known limitations.

Unknowns and limitations should be documented explicitly.

---

# Pull Requests

Pull requests should:

- have a clearly stated motivation;
- describe architectural impact;
- document telemetry/schema implications;
- explain determinism implications if relevant;
- avoid unrelated cleanup.

Small, focused pull requests are preferred.

---

# Project Direction

OTIS is initially pursuing a canonical instrument-appliance architecture.

Modularity and ecosystem expansion are expected later, but should not compromise:

- semantic clarity;
- deterministic behavior;
- reproducibility;
- instrumentation rigor.
