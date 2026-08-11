# Evidence Lifecycle

## Current policy

Raw OTIS evidence remains outside Git. Each retained package is registered in
the external content-addressed `otis_evidence_index_v1` with its content hash,
per-file manifest, storage location, source revision, build identity, profile
identity, attempt classification, result or failure reason, and analyzer
identity.

The default local index is:

```text
~/.local/share/otis/evidence_index_v1.json
```

`host.otis_tools.evidence_index` rejects an index path inside the repository.
It hashes regular files recursively in deterministic relative-path order and
rejects symlinks, so a recorded identity cannot depend on an unrecorded target.
Validation succeeds when at least one registered storage location still has
the exact recorded content identity. A moved exact copy may be added as a
second location by registering it with the same provenance.

## Attempt classification

Every package uses one explicit classification:

- `successful_rehearsal`
- `failed_rehearsal`
- `completed_campaign`
- `interrupted_campaign`
- `diagnostic`
- `historical`

Failure or interruption is evidence, not absence. The result field records the
concrete result or failure reason rather than implying that an unsealed attempt
passed.

## Mothball gate

Mothballing keeps the raw package and its identity but removes it from active
investigation. It requires all of the following:

1. no active investigation, programme, or unresolved anomaly depends on it;
2. its decision-bearing result and lessons are captured in a reviewed tracked
   summary, test, contract, or limitation;
3. that reviewed summary exists and is content-hashed in the index; and
4. the operator or maintainer running the command explicitly confirms there is
   no active dependency.

Example:

```bash
.venv/bin/python -m host.otis_tools.evidence_index mothball CONTENT_SHA256 \
  --reviewed-summary docs/path/to/reviewed-summary.md \
  --reason "superseded by the reviewed result" \
  --confirm-no-active-dependency
```

Mothballing does not delete or rewrite raw files.

## Future deletion gate

No current repository command deletes indexed raw evidence. Deletion may be
introduced only after all of these prerequisites are met:

1. OTIS has reached an explicitly declared stable and mature milestone;
2. no active programme, investigation, accepted claim, reproducibility need,
   or unresolved anomaly depends on the package;
3. the package is already mothballed;
4. a reviewed compact summary and the full identity/provenance record remain;
5. at least one independent validation of the retained index has passed; and
6. the operator gives explicit approval for the named content identities.

Deletion must target exact content hashes, never a broad path, glob, workspace,
or unresolved environment variable. The operation and outcome must be logged,
and the tracked summary and content identity normally remain permanently.

## Registration example

```bash
.venv/bin/python -m host.otis_tools.evidence_index register /absolute/run/path \
  --source-revision GIT_REVISION \
  --build-identity FIRMWARE_MANIFEST_SHA256 \
  --profile-identity PROFILE_ID \
  --attempt-classification successful_rehearsal \
  --result-or-failure-reason "all exact-bundle rehearsal gates passed" \
  --analyzer-identity ANALYZER_SHA256
```

The external index is mutable stewardship metadata; each raw package remains
immutable scientific evidence. If a package changes, it has a new content
identity and must be registered as a new package.
