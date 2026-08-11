# Codex Prompt: Replace Programme-Sequence Names with Durable Semantic Names

## Recommended execution setting

Use **GPT-5.6 Sol with High reasoning**.

This is a cross-cutting architecture and compatibility refactor spanning Python
modules, firmware translation units, build profiles, schemas, tests, tool
identities, telemetry, documentation, and evidence provenance. It requires more
context integration and judgement than a routine mechanical rename. Use
Extra High only if the initial inventory reveals that current and historical
artifact identities cannot be separated cleanly. Terra/High is appropriate for
a later, tightly bounded migration tranche after Sol has established and
documented the naming classification and compatibility plan.

## Prompt

Work in the OTIS repository and implement a focused semantic-naming refactor.
The outcome is that durable source code is named for the capability, physical
quantity, responsibility, or hardware specialization it implements—not for the
roadmap phase, programme sequence, or stage in which it happened to be created.

This is an implementation task, not merely a naming review. Complete the
largest safe finite migration that establishes the durable boundary end to end,
while preserving scientific provenance and existing user work.

### Core naming decision

Treat the following as distinct categories:

1. **Legitimate hardware identity.** `CX317` is the identity of a physical
   oscillator. Preserve `cx317` in a source filename, symbol, profile, or
   contract when the implementation is genuinely coupled to that oscillator's
   electrical, plant, tuning, or measured-response semantics. Do not preserve
   it merely because that hardware happened to be used when otherwise reusable
   logic was first developed.
2. **Legitimate timing terminology.** `phase` and `relative_phase` are valid
   metrology terms when the reference, clock domain, epoch, units, and
   transformation are explicit. Do not replace precise physical terminology
   just because it contains the word `phase`.
3. **Roadmap or programme chronology.** Names such as `phase4`, `cx318`,
   `cx319`, `stage4`, `stage5`, `stage7`, and similar sequence labels do not
   describe durable software semantics. Remove them from reusable source
   filenames, module names, primary symbols, and new runtime interfaces.
4. **Historical provenance.** Programme/stage identities may and often must
   remain in sealed reports, immutable manifests, historical run references,
   legacy tool identifiers, schema versions, and compatibility readers. Keep
   those identities as data and provenance, not as the organizing vocabulary
   of current reusable source code.

Examples of the intended direction, subject to inspection of actual semantics:

- `phase4_boundary_estimator` might become
  `pps_boundary_frequency_estimator`;
- `phase4_replay` might become `observe_only_discipline_replay`;
- `otis_phase4_engine` might become `otis_observe_only_discipline_engine`;
- `cx318_relative_phase` might become
  `reference_relative_phase_estimator`;
- `cx318_stage5_runtime_contract` might become
  `prewrite_readiness_contract`;
- a `cx319_g1_*` tool should be named for what it actually performs, such as
  no-write operational-path supervision, bundle construction, or analysis.

These examples are hypotheses, not mandatory spellings. Prefer the repository's
precise terminology and choose names only after reading the implementation and
its consumers.

### Required preparation

Before editing:

1. Read the repository `AGENTS.md` and the applicable documents under
   `docs/00_FOUNDATIONS/` in full, especially the reference terminology,
   architecture overview, design principles, and non-goals.
2. Inspect the working tree. Preserve all existing user changes and do not
   overwrite, revert, stage, or commit them.
3. Determine current programme authority and whether any source/profile is
   part of a frozen or active campaign bundle. Do not perform hardware I/O,
   flash firmware, issue serial commands, arm control, or run a live campaign.
4. Inventory chronological names across at least:
   - host and firmware filenames;
   - imports, includes, functions, types, constants, and build switches;
   - tests and fixtures;
   - firmware matrix entries and profile identifiers;
   - schemas, telemetry component names, tool IDs, output paths, and manifests;
   - current documentation links and commands;
   - historical artifact readers and replay validators.
5. Classify every affected identity as one of:
   - durable capability name to migrate;
   - genuine CX317 hardware specialization to retain;
   - current programme/configuration identity that belongs in data rather than
     source structure;
   - immutable historical/provenance identity that must remain readable;
   - compatibility surface requiring an explicit adapter or alias.

Record the classification and proposed old-to-new mapping in a concise tracked
engineering note before or as part of the implementation. Explain borderline
decisions rather than applying a text-substitution rule.

### Implementation requirements

1. Rename reusable modules and firmware units according to their enduring
   responsibility. Rename corresponding primary symbols, imports/includes,
   tests, documentation, and build references coherently.
2. Separate reusable platform capability from campaign configuration.
   Programme IDs, leg/gate IDs, selected policies, durations, authority limits,
   and expected artifacts should be explicit configuration or manifest data.
   They should not determine the reusable module's name.
3. Keep campaign-specific orchestration thin. It should primarily select
   firmware/profile, stimulus, estimator/controller policy, duration, metrics,
   and stop conditions while using shared transport, capture, supervision,
   acknowledgement, abort, handoff, analysis, and sealing capabilities.
4. Do not create speculative abstractions. Extract only semantics already
   demonstrated by current CX317/CX318/CX319 implementations or by repeated
   concrete use.
5. Preserve exact historical interpretation:
   - do not rewrite sealed run contents or canonical raw observations;
   - do not silently change historical tool IDs, telemetry tags, schema IDs,
     report paths, or manifest meanings;
   - where historical readers require an old identity, retain it explicitly as
     a legacy identifier and document why;
   - if a new semantic implementation reads an old artifact, make that mapping
     explicit, deterministic, and tested;
   - do not make old evidence satisfy a newer product matrix unless migration
     or current compatibility explicitly requires it.
6. Avoid permanent wrappers whose only purpose is translating one programme
   number into another. Prefer one semantic implementation with programme
   identity supplied as data. A small compatibility adapter is acceptable when
   required to preserve an established external or historical contract, but it
   must be clearly labelled, tested, and excluded from new use.
7. Keep `cx317` only where the code truly depends on CX317 hardware or its
   measured plant model. For reusable transaction, preview, estimator,
   supervisor, status, or actuator mechanisms, use semantic names and pass the
   plant/profile identity explicitly.
8. Preserve timing-domain semantics, raw/derived separation, fail-static
   control behavior, authority boundaries, exact acknowledgements, serial-owner
   invariants, replayability, and evidence provenance. A rename must not alter
   these behaviors accidentally.
9. Update architectural, software, terminology, lifecycle, and operational
   documentation when the ownership or meaning of a component changes. Do not
   cosmetically rewrite historical experiment reports solely to modernize
   vocabulary.
10. Do not broaden this task into unrelated cleanup or a generalized timing
    framework.

### Migration strategy

Do not perform an unreviewable repository-wide search-and-replace. Work in
coherent vertical slices. A preferred order is:

1. establish the classification/mapping and naming rule;
2. migrate the most reused foundational estimator/discipline components;
3. migrate shared runtime contracts and platform operations;
4. migrate current campaign consumers onto those semantic interfaces;
5. retain and test only the compatibility surfaces needed for historical
   artifacts;
6. remove obsolete aliases after proving there are no remaining current
   consumers.

If the full safe migration is too large for one change, complete a meaningful
end-to-end tranche rather than leaving duplicate half-migrated implementations.
Document the remaining bounded tranches, their dependencies, and why they were
not included. Do not claim the repository-wide issue is resolved while current
reusable code still depends on chronological module names.

### Verification

Choose verification according to the changed risk surface, but treat shared
module names, firmware includes, build profiles, schemas, tool identities, and
artifact readers as broad integration surfaces.

At minimum:

1. run focused unit and contract tests for every migrated capability;
2. run import/include and source-guard checks proving current code uses the new
   semantic names;
3. build every affected current firmware profile;
4. replay representative current and historical fixtures through the migrated
   readers and analyzers;
5. verify legacy identities remain accepted only where intentionally required;
6. verify no control authority, command envelope, timing semantics, telemetry
   meaning, or evidence hash interpretation changed unintentionally;
7. run the broader release checks required by any materially changed shared
   protocol, build-system, verifier, or safety boundary.

No bench run is authorized by this prompt. If offline verification cannot
establish safety or compatibility, stop with a precise evidence gap and the
smallest proposed follow-up gate.

### Acceptance criteria

The task is complete only when:

- current reusable source filenames and primary symbols no longer use
  `phase4`, `cx318`, `cx319`, or programme-style `stageN` labels;
- any retained `cx317` source identity has a documented, demonstrable hardware
  or plant coupling;
- valid terms such as reference-relative phase remain precise and include the
  necessary reference/domain semantics;
- current programmes select semantic capabilities through explicit profiles,
  policies, manifests, or other configuration;
- sealed and historical evidence remains unchanged and replayable;
- any compatibility aliases are narrow, documented, tested, and not used by
  new/current code;
- documentation states the durable naming rule and the boundary between source
  semantics and evidence provenance;
- affected tests, builds, and replay checks pass; and
- the final report separately lists observed changes, retained legacy
  identities, verification evidence, limitations, and deferred work.

Finish by reporting the semantic mapping, files changed, compatibility choices,
verification results, and any remaining chronological identifiers with an
individual justification for each. Do not stage, commit, push, or open a pull
request unless the operator explicitly requests it.
