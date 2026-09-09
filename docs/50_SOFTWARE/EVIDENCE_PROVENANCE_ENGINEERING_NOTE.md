# Evidence and Provenance Engineering Note

## Decision

OTIS completed runs can now be sealed by a deterministic, versioned
`evidence_manifest.json`. This closes the gap between a run manifest saying
which artifacts should exist and an auditable record of the exact bytes that
were observed.

Run sealing remains host-side and does not change capture ordering, analysis,
or control. Firmware now emits build-generated identity rows, and sealing binds
their exact source/configuration hashes, Git state, FQBN/board, core, compiler,
toolchain, image, and invocation identity into the canonical snapshot. Raw
evidence remains untouched. The frozen bundle copies and hashes the exact
current policy, estimator, model, and run-manifest bytes so later repository
edits cannot silently change replay context.

Qualification firmware is produced only by `tools/build_firmware.py` from the
canonical `firmware/arduino/firmware_build_manifest.json`. The builder verifies
pinned Arduino CLI/core/toolchain identities, hashes the functional installed
core and toolchain, hashes all sketch/build-definition inputs, and compiles a
disposable sketch copy with a one-use generated provenance header. It rechecks
Git/source/configuration and installed-tool identities after compilation and
artifact hashing, then removes transient source/header bytes. A fresh builder
session identity binds the generated header to the compiler invocation. The
firmware has no fallback commit, board, configuration, alternate manifest, or
profile selector.

Installed-tree hashes deliberately exclude package-manager metadata
(`installed.json`), Finder metadata, and generated Python bytecode caches.
Those files are not release inputs and vary with installation/runtime context;
all functional source, library, executable, and symlink bytes remain covered.

There is no Arduino IDE provenance escape path on current HEAD. Bench and
qualification binaries use the same fixed builder and canonical manifest.

Multi-session captures require the same preservation rule. A reset or reconnect
may define a later authoritative session, but the original raw capture remains
immutable. Any session-scoped derived product must identify the source run,
source hashes, BOOT/session boundary, original sequence ranges, and selection
rule. It must not rewrite, splice, renumber, or present a filtered derivative
as the original capture. A disturbed pre-BOOT session may therefore coexist
with a successful later engineering session without erasing either fact.

## Storage boundary

Sealing evidence does not make a run a Git artifact. The repository
`.gitignore` remains authoritative at all times, and the complete `runs/` tree
is intentionally ignored. Run directories are locally stored evidence and
must not be force-added or otherwise smuggled past ignore rules. This keeps raw
captures, generated reports, and sealed packages from bloating repository
history.

References to `runs/...` elsewhere in the documentation are local provenance
references. They may resolve on the bench workstation that retains the
evidence, but they are not expected to resolve in a fresh clone. The operator
is responsible for retaining and backing up important run directories together
with their snapshot digests.

Promotion from a run means committing a compact, reviewed result outside
`runs/`, such as a result note, plant model, schema, contract, or purpose-built
small test fixture. It does not mean committing the source run directory.

## Determinism and evidence preservation

- SHA-256 is computed over file bytes in bounded chunks.
- Artifact paths are normalized, run-relative, unique, and sorted.
- The overall snapshot digest uses canonical JSON and contains no wall-clock or
  filesystem metadata.
- Symbolic links and paths escaping the run directory are rejected.
- Active captures cannot be sealed.
- Existing snapshots cannot be overwritten.
- Validators recompute both artifact and canonical snapshot digests.
- Newly added raw or declared evidence is reported as uncovered rather than
  silently ignored.

## Current compatibility boundary

Current non-template packages require the current manifest, current CSV
contracts, the complete fixed-build provenance banner, and an immutable
snapshot. Missing or mismatched identity is a hard validation failure. Current
HEAD does not accept an older layout, infer an absent snapshot, or translate a
retired firmware identity. Historical packages remain evidence, but their
recorded Git revision supplies their reader and validation rules.

## Risk assessment

| Risk | Assessment and mitigation |
|---|---|
| SHA-256 proves integrity, not authorship | The snapshot is tamper-evident only relative to a trusted copy of its digest. Signing and external transparency logs remain out of scope. |
| A partial run may need preservation | Default sealing requires `COMPLETE`; `--allow-incomplete` is explicit and still refuses active capture. |
| Repository policy or model changes break replay | The frozen bundle and run manifest bind the exact policy, estimator, and model bytes. |
| Derived reports legitimately change | They are excluded unless explicitly declared by the run manifest. Primary evidence remains bound. |
| Additional evidence may appear after sealing | Validation fails for uncovered evidence-bearing files, requiring a new immutable snapshot/run rather than mutation. |
| A malicious caller can replay a generated session binding | The binding prevents accidental stale-header/raw builds, but it is deliberately unsigned and not secret. A caller that reconstructs the matching invocation remains outside the trust boundary; signing and isolated builders remain future work. |

## Plant-model promotion handoff

Before using a run for plant-model promotion:

1. stop capture and create `COMPLETE`;
2. populate known manifest provenance rather than inventing missing values;
3. run `.venv/bin/python -m host.otis_tools.evidence RUN_DIR`;
4. run `.venv/bin/python -m host.otis_tools.adaptive_hybrid_analyze RUN_DIR`;
5. retain and back up the local run directory and snapshot digest together;
6. promote only reviewed, compact outputs to tracked paths outside `runs/`.

This establishes byte-exact inputs for later plant-model reproduction without
making any claim about calibration quality, reference authority, or control
eligibility.
