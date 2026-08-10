# OTIS Phase 1 — Independent Verification, Architecture, and Technical-Debt Reviews

You are working in the OTIS repository.

## Objective

Conduct a comprehensive, evidence-based repository review from three independent engineering perspectives.  Consider the engineering culture in docs/00_FOUNDATIONS/ENGINEERING_CULTURE.md

This is Phase 1: inspection and assessment only.

Do not implement recommendations or change the repository.

## Strict Read-Only Constraint

The repository must remain untouched.

Do not:

- edit, create, delete, move, or rename files;
- apply patches;
- change symbols or reorganise directories;
- modify code, configuration, tests, documentation, generated artifacts, or dependencies;
- run formatters, generators, migrations, builds, tests, firmware tools, or other commands that may create or update files;
- stage or commit changes.

Use only read-only inspection. Read the applicable repository instructions and foundational documents before evaluating timing semantics or core architecture.

If an important conclusion would require executing code, building firmware, accessing unavailable hardware, or inspecting unavailable evidence, identify that limitation explicitly. Do not substitute speculation for evidence.

## Repository Context

OTIS is a scientific timing and metrology platform, not simply embedded firmware.

Its long-term direction includes:

- disciplined oscillators;
- laboratory-quality metrology;
- evidence-driven engineering;
- deterministic capture and behaviour;
- replay and offline reconstruction;
- plant identification and characterisation;
- calibration and uncertainty management;
- diagnostics as permanent, first-class architecture;
- future SW2 evolution;
- multiple oscillator technologies;
- multiple hardware revisions;
- multiple timing references;
- distributed timing;
- ClockMesh and RSN compatibility;
- additional products and laboratory workflows.

Hardware capture establishes timing truth. CPU scheduling, interrupt latency, logging, networking, storage, and user interfaces must not define or contaminate hardware timestamps.

Canonical raw observations must remain distinguishable from derived, reconstructed, projected, calibrated, or disciplined values.

Metrology is more important than control. Diagnostics and provenance are permanent architecture.

## Required Independence

Produce three completely independent reports:

1. Senior Embedded Firmware Architect
2. Senior Timing & Metrology Engineer
3. Future OTIS Maintainer, Five Years Later

Treat the reports as if they were written by three senior engineers who did not consult one another.

Each reviewer must:

- inspect the repository through their own professional lens;
- defend their own conclusions;
- make their own retention decisions;
- produce their own priorities and recommendations;
- include substantial positive findings;
- acknowledge evidence gaps without trying to harmonise them with another reviewer.

Disagreement is valuable.

Do not:

- compare the reviewers;
- merge their findings;
- reconcile conflicting recommendations;
- vote or rank reviewers;
- create a consensus retention matrix;
- write a cross-review synthesis;
- identify a “winning” architecture.

Synthesis belongs to a later phase.

## Questions Every Reviewer Must Address

Each reviewer must independently address the following four areas, applying their own priorities and standards.

### 1. Test and Verification Lifecycle

Inventory the repository’s checks and classify their apparent purpose:

- current-product safeguard;
- compatibility check;
- historical programme evidence;
- campaign-specific validation;
- static source or structural assertion;
- hardware-dependent bench verification;
- unclear or unverified purpose.

Assess where each check belongs:

- Fast;
- Standard or Campaign;
- Release;
- Bench;
- Outside default verification but retained as historical evidence;
- Candidate for retirement.

Determine whether the verification structure:

- protects the current timing path;
- preserves meaningful compatibility;
- confuses historical stage completion with current-product support;
- duplicates coverage;
- relies excessively on static source assertions;
- omits important integration, replay, fault-injection, or operational-path checks;
- clearly separates current compatibility from historical validation.

Do not assume an old test is obsolete merely because of its name or age. Likewise, do not assume historical coverage belongs permanently in the default matrix.

### 2. Firmware-Mode and Profile Lifecycle

Inventory the H0/SW1 bring-up modes, historical CX317 phase profiles, active CX318 profiles, diagnostic modes, laboratory profiles, and other material firmware configurations.

For each mode or profile, independently recommend one classification:

- **Keep active** — supported operational or development mode;
- **Keep diagnostic/recovery** — retained for a defined diagnostic, recovery, or hardware-characterisation purpose;
- **Keep compile-only** — compatibility fixture that should continue to compile but need not receive full runtime qualification;
- **Archive out of default checks** — retained as historical programme evidence, documentation, a small fixture, or Git history;
- **Retire** — no longer justified by a current, diagnostic, compatibility, evidentiary, or safety purpose;
- **Undetermined** — repository evidence is insufficient to support a responsible decision.

Explicitly examine, where present:

- early USB modes;
- GPIO loopback modes;
- GPS-PPS modes;
- FC0 modes;
- PIO long-gate modes;
- pseudo-PPS modes;
- H1 laboratory modes;
- stage-specific active profiles;
- historical CX317 phase profiles;
- qualified PPS snapshot configurations;
- CX318 relative-phase and hybrid-preview configurations.

Do not automatically grant all historical modes equal permanent status.

Do not recommend removing a mode until you have identified the timing, diagnostic, recovery, safety, compatibility, or evidentiary guard it may provide.

### 3. Code, Configuration, and Verification Debt

Identify material examples of:

- code retained solely for completed stage gates;
- duplicated compile-time or runtime feature switches;
- excessive compile-time configuration combinations;
- stage-numbered host tools whose behaviour may now be reusable;
- redundant schemas, contracts, or profile versions;
- static source assertions substituting for behavioural verification;
- profiles that differ only by historical parameter values;
- duplicated host and firmware policy logic;
- safety constraints embedded inside obsolete programme structure;
- historical terminology leaking into active interfaces;
- documentation, contracts, tools, and firmware that no longer agree;
- code that would be clearer as a versioned policy or data profile;
- obsolete compatibility scaffolding;
- unclear ownership or dependency direction.

Distinguish durable safety or measurement constraints from the historical programme structure in which they were first implemented.

Do not recommend abstraction merely to reduce superficial repetition. Recommend extraction only where a durable concept, invariant, schema, policy, or interface is demonstrably present.

### 4. Active Architecture

Review the currently relevant path, insofar as repository evidence establishes it, including:

- the qualified PPS snapshot backend;
- hardware capture and timestamp construction;
- interrupt-service routines and event handoff;
- dual-core ownership and concurrency;
- queueing, drainage, and backpressure;
- CX318 relative-phase and hybrid-preview paths;
- canonical telemetry and command contracts;
- raw versus derived measurement representations;
- diagnostic gating;
- DAC authority and acknowledgement boundaries;
- host capture, supervision, analysis, replay, and sealing;
- configuration and policy ownership.

Assess:

- module boundaries and dependency direction;
- capture, measurement, metrology, diagnostics, telemetry, and control separation;
- state-machine clarity;
- ownership of mutable state and hardware resources;
- ISR boundedness and determinism;
- cross-core and host/firmware concurrency;
- timestamp and clock-domain semantics;
- failure handling and fail-static behaviour;
- provenance and replayability;
- maintainability of the build and configuration model;
- alignment between documented architecture and implementation.

## Evidence Standard

Every material observation must include all of the following:

- **Type:** Objective observation or Architectural opinion
- **Severity:** Critical, High, Medium, Low, or Informational
- **Confidence:** High, Medium, or Low
- **Evidence:** Specific files, symbols, configuration names, tests, documentation sections, or Git history where relevant
- **Rationale:** Why the evidence supports the observation
- **Potential consequences:** What could happen if the condition remains unchanged
- **Evidence limitations:** Anything that could not be established through read-only repository inspection

Use precise file paths and line numbers where practical.

Do not present an inference as an observed fact. Label interpretations, forecasts, and design preferences as architectural opinion.

Severity should reflect potential impact on timing integrity, scientific validity, safety or authority boundaries, deterministic behaviour, replayability, operational reliability, or long-term cost—not merely coding style.

If evidence is conflicting, cite the conflict. If evidence is absent, state “undetermined” and identify what evidence would resolve it.

## Report A — Senior Embedded Firmware Architect

Review the repository as an expert embedded firmware architect responsible for deterministic, maintainable instrument firmware.

Focus on:

- firmware architecture;
- layering and dependency direction;
- module boundaries;
- API design;
- coupling and cohesion;
- ISR design;
- hardware capture;
- state machines;
- concurrency and dual-core behaviour;
- ownership of resources and mutable state;
- queueing and backpressure;
- host/firmware boundaries;
- build and configuration systems;
- testing strategy;
- Core 0 / Core 1 split, contracts, & coordination;
- memory usage;
- potential race conditions;
- contract consistency across firmware and host side;
- maintainability and technical debt.

Ensure you cover the entire producer-to-consumer contract chain, missing-as-clean behaviour, duplicated gates/status, provenance terminology, lifecycle state machines, cheap preflights, and all failed attempts.

Do not optimise for elegance alone. Preserve deterministic behaviour, explicit timing semantics, bounded execution, and understandable hardware ownership.

Look for opportunities to simplify the active system without weakening capture integrity, diagnostics, recovery capability, safety constraints, or evidentiary value.

## Report B — Senior Timing & Metrology Engineer

Review the repository as the engineer accountable for laboratory measurement quality and scientific defensibility.

Focus on:

- measurement integrity;
- timestamp origin and quality;
- clock-domain identification;
- raw and derived observation separation;
- telemetry schemas;
- diagnostics;
- calibration;
- uncertainty and error budgets;
- provenance and traceability;
- deterministic replay;
- evidence capture and sealing;
- observability;
- fault isolation;
- estimator and plant-model provenance;
- plant identification and characterisation;
- reconstruction of requested and applied control actions;
- suitability for independent verification and later reinterpretation.

Assume metrology is more important than control.

Treat diagnostics, canonical raw observations, provenance, and traceability as permanent architecture.

Avoid software-centric simplifications that would weaken measurement quality, obscure transformations, discard useful evidence, or make scientific conclusions harder to reproduce.

## Report C — Future OTIS Maintainer, Five Years Later

Assume it is five years in the future and OTIS now supports:

- multiple oscillator technologies;
- multiple hardware revisions;
- several timing references;
- SW2;
- deterministic replay;
- mature laboratory workflows;
- distributed timing;
- ClockMesh and RSN integration;
- additional products.

Review today’s repository from the perspective of the engineer who must maintain and extend that system.

Focus on:

- scalability of architecture and configuration;
- subsystem boundaries;
- interface stability;
- extension points;
- hardware and product variation;
- schema and contract evolution;
- policy versus implementation;
- documentation quality;
- accumulated compatibility burden;
- test and profile growth;
- assumptions likely to age poorly;
- technical debt that will become expensive;
- decisions that remain sound across future products.

Identify decisions that will become costly if left unchanged.

Also identify decisions that were excellent and should remain untouched, even if they constrain future redesign.

Do not assume that a generic framework is automatically desirable. Evaluate whether proposed flexibility is justified by the stated future product variations and whether it would preserve deterministic timing and provenance.

## Required Structure for Each Independent Report

Each report must stand alone and contain these sections in this order:

### Executive Summary

State the reviewer’s independent assessment, principal concerns, and overall architectural position.

### Scope and Evidence Limitations

Describe what was inspected and what could not be established through static, read-only review.

### Strengths

Document concrete strengths with the full evidence fields.

### Weaknesses

Document concrete weaknesses with the full evidence fields.

### Architectural Assessment

Assess the current architecture through that reviewer’s professional lens. Clearly separate objective observations from architectural opinions.

### Test and Verification Lifecycle

Provide the reviewer’s independent assessment of test purpose and verification-tier placement.

### Firmware-Mode and Profile Retention Matrix

Provide a table with, at minimum:

| Mode, profile, or profile family | Apparent purpose | Evidence | Recommended classification | Confidence | Retained guard or value | Risk of decision | Required follow-up |
|---|---|---|---|---|---|---|---|

Use only the specified lifecycle classifications.

Group entries only when the repository demonstrates that they share semantics and lifecycle needs. Do not hide materially different modes inside a broad category.

### Technical Debt

Identify and assess code, configuration, verification, schema, documentation, and programme-history debt.

### Risks

Identify risks to current correctness, deterministic behaviour, measurement integrity, operational reliability, scientific validity, and future maintenance as appropriate to the reviewer.

### Things I Would Preserve

This section is mandatory and must be substantial.

Identify concrete architectural decisions, invariants, interfaces, tests, diagnostic capabilities, evidence practices, or implementation choices that should remain intact.

Explain why each should be preserved and what could be lost through careless simplification.

### Recommended Future Work

Provide the reviewer’s own ordered future-work plan.

For every recommendation include:

- intended outcome;
- affected area;
- prerequisite evidence or decision;
- risk if undertaken;
- risk if deferred;
- suggested verification level: Fast, Standard/Campaign, Release, or Bench;
- whether the work is deletion, consolidation, refactoring, documentation, additional verification, or further investigation.

Recommendations must remain proposals only. Do not implement them.

### Reviewer’s Unresolved Questions

List evidence gaps that materially affect this reviewer’s conclusions. Do not ask questions whose answers can already be found in the repository.

## Final Deliverable Rules

Produce three separate reports, clearly labelled Report A, Report B, and Report C.

Each must be complete and independently reasoned.

Do not add:

- a combined executive summary;
- a comparison table;
- a consensus section;
- a consolidated retention matrix;
- a unified roadmap;
- majority or minority opinions;
- reconciliation commentary.

The objective is not to produce “the answer.”

The objective is to surface three defensible expert viewpoints for later synthesis by the project architect.
