# Evidence and Provenance Engineering Note

## Decision

OTIS completed runs can now be sealed by a deterministic, versioned
`evidence_manifest.json`. This closes the gap between a run manifest saying
which artifacts should exist and an auditable record of the exact bytes that
were observed.

The implementation is intentionally host-side and narrow. It does not change
firmware records, telemetry contracts, capture ordering, analysis, or control.
Raw evidence remains untouched. If a run selects a repository profile, sealing
copies its exact bytes to `selected_profile.yaml` before hashing so later
repository profile edits cannot silently change replay context.

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

## Backwards compatibility

Manifest schema version 1 and all CSV contracts are unchanged. Existing runs
without snapshots continue to validate, with a warning that their evidence is
not cryptographically bound. Once a snapshot is present, a mismatch is a hard
validation failure. This is deliberate: silently accepting changed evidence
would defeat the snapshot contract.

## Risk assessment

| Risk | Assessment and mitigation |
|---|---|
| SHA-256 proves integrity, not authorship | The snapshot is tamper-evident only relative to a trusted copy of its digest. Signing and external transparency logs remain out of scope. |
| A partial run may need preservation | Default sealing requires `COMPLETE`; `--allow-incomplete` is explicit and still refuses active capture. |
| Repository profile changes break replay | The selected profile bytes are copied into the run before sealing. |
| Derived reports legitimately change | They are excluded unless explicitly declared by the run manifest. Primary evidence remains bound. |
| Legacy layouts use root-level raw logs | `serial_raw.log` and `raw_serial.log` are covered alongside the canonical `raw/` tree. |
| Additional evidence may appear after sealing | Validation fails for uncovered evidence-bearing files, requiring a new immutable snapshot/run rather than mutation. |

## Plant-model promotion handoff

Before using a run for plant-model promotion:

1. stop capture and create `COMPLETE`;
2. populate known manifest provenance rather than inventing missing values;
3. run `python3 -m host.otis_tools.evidence RUN_DIR`;
4. run the normal validator and analysis;
5. retain the run directory and snapshot digest together.

This establishes byte-exact inputs for later plant-model reproduction without
making any claim about calibration quality, reference authority, or control
eligibility.
