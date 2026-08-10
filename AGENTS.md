# OTIS Engineering Working Agreements

These instructions apply to Codex work throughout this repository. Explicit
operator directions and campaign-specific safety or authority limits take
precedence.

The global `~/.codex/AGENTS.md` supplies general engineering preferences.
`docs/00_FOUNDATIONS/ENGINEERING_CULTURE.md` explains the OTIS-specific
human-facing rationale. This file carries the OTIS operational rules that Codex
must apply on every task. Keep the applicable layers synchronized when a
lasting preference changes.

## Product identity

- Treat OTIS as a provenance-preserving scientific timing instrument, not a
  feature-churn application, hobby prototype, black-box controller, or generic
  embedded framework. Aim for Bell Labs and HP/Tektronix-style disciplined,
  comprehensible instrumentation engineering.
- For OTIS, prioritize determinism, correctness, explicit timing semantics,
  observability, replayability, architectural clarity, and long-term
  maintainability over convenience, feature count, throughput, or rapid
  implementation.

## Timing, telemetry, and control semantics

- Hardware capture establishes timing truth. The CPU may observe timing events
  but interrupt latency, scheduling, logging, networking, UI, and storage must
  not define or contaminate their timestamps.
- Every timing value must identify its reference or clock domain. Never compare
  values across domains without an explicit reconstruction, projection, or
  synchronization step and its assumptions.
- Preserve canonical raw observations unchanged. Derived, adjusted,
  reconstructed, projected, calibrated, or disciplined values must not
  overwrite or obscure raw evidence.
- Treat telemetry and logs as scientific records, not debugging exhaust.
  Preserve sufficient schema, ordering, identity, configuration, and provenance
  to permit deterministic replay, offline reconstruction, independent
  verification, and later reinterpretation.
- Keep capture, measurement, metrology, diagnostics, telemetry, and control as
  distinct responsibilities. Diagnostics must state why control is permitted,
  degraded, held, or inhibited.
- Make every requested and applied control action reconstructable from recorded
  observations, estimator identity and outputs, diagnostic gates, plant-model
  provenance, policy/version, command acknowledgement, and resulting state.
- Use the precise terminology in
  `docs/00_FOUNDATIONS/OTIS_REFERENCE_TERMINOLOGY.md`. Avoid ambiguous names
  such as `time`, `corrected`, `synced`, `stable`, `accurate`, or `phase` when
  the domain, reference, transformation, or criterion is not explicit.
- Treat lock as satisfaction of stated criteria, not proof of correctness.

## Architecture and scope discipline

- Separate architectural requirements from implementations. For example,
  deterministic capture is architectural; RP2040 PIO is one implementation.
- Isolate host services, dashboards, networking, and storage from the timing
  fabric so service activity cannot compromise capture correctness.
- Preserve timing semantics, provenance, replayability, and deterministic
  behavior across hardware substitutions and modular boundaries. Treat a
  hardware substitution as a documented, comparable experiment.
- Build the concrete OTIS instrument and complete the current roadmap before
  extracting a generalized timing framework. Design for possible future
  abstraction, but abstract only from demonstrated experience.
- Treat the initial non-goals in `docs/00_FOUNDATIONS/OTIS_NON_GOALS.md` as
  scope boundaries unless the operator explicitly changes project direction.

## Repository and documentation discipline

- Treat `.gitignore` as an architectural storage boundary. Never force-add an
  ignored file, bypass ignore rules, or weaken them temporarily to stage an
  artifact.
- Keep `runs/` as local experimental evidence. Commit reviewed summaries,
  schemas, contracts, plant models, and deliberately small fixtures rather than
  raw campaign packages.
- When behavior or meaning changes, update the relevant architecture,
  telemetry/schema, methodology, known-limitations, and terminology documents
  in the same change.
- Before changing timing semantics or core architecture, read the applicable
  documents under `docs/00_FOUNDATIONS/`; do not rely on filenames or summaries
  alone.

## Optimize for decision-bearing capability

- A bounded experiment that rejects a controller or reveals a real firmware
  limitation is useful progress. Avoidable host, orchestration, and artifact
  failures are verification escapes and should be moved into rehearsal.

## Freeze a campaign bundle

Before a live campaign, record one immutable bundle containing:

- firmware source revision, build profile, compile-time configuration, and
  binary identity;
- capture, supervisor, shadow, analyzer, and sealing tools;
- command envelope, command cadence, acknowledgements, and stop conditions;
- expected identity and query transcript;
- rehearsal procedure and logging destinations.

Rehearse and run the same operationally significant bundle. Rehearse again
when firmware, host behavior, configuration, protocol, FIFO/process topology,
command timing, verifier semantics, authority, or stop conditions change. A
path rename, documentation-only edit, or other non-operational change does not
by itself invalidate a successful rehearsal.

Validate historical artifacts against the manifest and matrix with which they
were created. Do not require them to satisfy the current expanding product
matrix unless the task explicitly concerns migration or current compatibility.

## Rehearse the complete operational path

An evidence-bearing rehearsal must exercise the actual long-run path:

1. establish continuous capture and confirm identity;
2. start every supervisor and shadow process;
3. issue representative commands and verify exact acknowledgements;
4. exercise relevant timeout and periodic boundaries;
5. inject transport obstruction and verify an independent bounded abort path;
6. transfer serial ownership without an ownerless interval;
7. stop cleanly, then run the actual analyzer and sealing procedure.

Use accelerated time, replay, or fault injection for boundaries longer than a
short bench rehearsal, while still testing the genuine real-time I/O path.

## Serial and process invariants

- Maintain exactly one known serial owner and continuous bounded drainage when
  firmware queue health depends on host consumption.
- Make capture handoff atomic; analysis must not create an ownerless interval.
- Bound serial reads, writes, flushes, process shutdown, and command waits.
- Send console output to a continuously drained file or bounded logger.
- Keep abort independent of normal-command backpressure.
- Treat these as reusable platform invariants rather than rebuilding them for
  each experiment. A passive bridge is one possible implementation, not a
  required architecture.

## Proportionate verification

Choose verification from the changed risk surface:

- **Fast:** focused unit, contract, and source-guard checks plus the affected
  current firmware profile. Run during narrow development.
- **Campaign:** affected integration/replay tests, analyzer checks, current
  live profile, and rehearsal simulation. Run before bundle rehearsal.
- **Release:** full tests, exhaustive proofs, historical profiles, and the full
  expected-failure matrix. Run before the first live campaign, after final
  integration, and whenever a shared transport, protocol, verifier, build
  system, or safety boundary changes materially.
- **Bench:** exact-bundle rehearsal followed by the authorized finite live run.

Do not automatically run the full repository suite or complete firmware matrix
after every narrow repair. Reuse build results only when source, configuration,
toolchain, and all other relevant inputs have identical identities.

## Operating premises and safety

- Treat operations inside a documented, previously characterized electrical
  envelope as authorized without repeated speculative safety analysis, unless
  new evidence invalidates that envelope.
- The characterized DAC range `0xA800..0xAB00` is the established bounded
  operating envelope unless a campaign-specific instruction narrows it.
- Distinguish provenance uncertainty (for example, an unknown applied code)
  from evidence of physical danger.
- USB re-enumeration, reset, and flashing are normal operations, but preserve
  authority separation, bounded actuator movement, exact acknowledgements,
  independent abort, fail-static behavior, and the last confirmed state.
- Optional sensors and telemetry are not blockers unless the experimental
  decision or a stated safety condition depends on them.

## Anomaly triage and rabbit-hole control

For each anomaly:

1. state one concrete hypothesis and the decision it could affect;
2. run one discriminating check with a default 30-minute offline or one-short-
   rehearsal budget;
3. continue only if it affects safety, scientific validity, or the next run;
4. otherwise record the anomaly and defer it.

Do not improve optional telemetry, historical validation, or general
architecture during an active campaign. Do not turn every defect into a
repository-wide framework project.

Classify failures in reports as scientific rejection, firmware defect under
intended stress, platform defect caught in rehearsal, platform escape into a
campaign, or irrelevant/deferred anomaly. Support causal claims with evidence
such as timestamps, queue capacity, telemetry rate, logs, and artifact hashes;
avoid hindsight-only wording.

## Separate platform and campaign engineering

Stabilize transport, logging, serial ownership, acknowledgement handling,
supervision, and sealing as reusable platform components. Campaign-specific
code should primarily select firmware/profile, starting stimulus,
estimator/controller policy, duration, metrics, and stop conditions.

Track process efficiency where practical: bench hours, time to first useful
signal, invalidated captures, repeated release gates, physical interventions,
rehearsal escape rate, and serial-owner gaps.
